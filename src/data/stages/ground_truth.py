"""S9 ground truth (docs/07 section 9, spec 12, amendments E1-E5, DEC-01).

Expectations come from exactly two sources, never from the production engine:
  1. the planted-scenario and boundary definitions (known by construction, stage S5), and
  2. the independent reference oracle in src/reference (shares no code with src/services).
Every planted and boundary record is checked: when construction and oracle disagree, generation STOPS
(GroundTruthDisagreement), because one of them is wrong (docs/07 9.2). Codes the oracle finds on records that
were not planted become natural labels (is_planted = false, injection_reason "natural consequence", 7.4).

This is the only generator module that writes ground truth; operational code never imports it
(tests/test_ground_truth_isolation.py). Files go to <out>/ground_truth/, rows to the ground_truth schema.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa

from src.data.export import canonical_text, json_value
from src.data.sampling import scaled_count
from src.data.stages import GenParams
from src.data.stages.anomalies import BEHAVIOUR, ISSUE
from src.data.stages.workbench import Boundary, Plant
from src.models.base import GroundTruthBase
from src.reference.oracle import Expectation, compute_expectations

GT_TABLES = ("record_expectation", "anomaly_label", "boundary_case", "scenario")
FILES = {"record_expectation": "record_expectations.csv", "anomaly_label": "anomaly_labels.csv",
         "boundary_case": "boundary_cases.csv"}
FIXTURE_GLOBS = {"S16": "lifecycle_*.json", "S17": "arithmetic_*.json", "S20": "rules_conflict_*.yaml"}
EXTRA_ISSUES = {"S11": "SELF_APPROVAL_ATTEMPT", "S12": "UNAUTHORIZED_APPROVER_ATTEMPT",
                "S13": "DUPLICATE_REIMBURSEMENT_ATTEMPT", "S16": "INVALID_LIFECYCLE_TRANSITION",
                "S17": "CLAIM_TOTAL_MISMATCH", "S18": "REPEATED_SUBMISSION", "S20": "RULE_CONFLICT",
                "S25": "PROCESSING_FAILURE", "BC-10": "SPLIT_CLAIM_SUSPECTED"}
DESCRIPTIONS = {
    "S01": "Negative leave balance on a policy that forbids it (legacy approval)",
    "S01b": "Negative balance permitted by policy (control, expected negative)",
    "S02": "Overlapping approved leave for the same employee (pairs)",
    "S03": "Insufficient leave balance at submission",
    "S04": "Leave spanning weekends and public holidays (control; planted + natural, at least the planned total)",
    "S05": "Missing expense receipt", "S06a": "Duplicate receipt hash, same employee (pairs)",
    "S06b": "Duplicate receipt hash, different employees (pairs)", "S07a": "Per-line limit breach",
    "S07b": "Per-claim limit breach", "S08": "Expense dated outside employment",
    "S09": "Suspected split claims (6 pairs + 2 triples)", "S10": "Missing cost center",
    "S11": "Approval attempt by the requester (rows built in Phase 7)",
    "S12": "Unauthorised approver attempt (rows built in Phase 7)",
    "S13": "Duplicate reimbursement attempt (rows built in Phase 8)",
    "S14": "Multi-level approval route (natural control; expected at least the planned count)",
    "S14-L5": "Claims above 5,000 USD reaching the L5 level (control)",
    "S15": "Expired policy version referenced", "S16": "Invalid lifecycle transition (negative fixtures)",
    "S17": "Arithmetic reconciliation failure (negative fixtures)",
    "S18": "Repeated submission, idempotent replay (rows built in Phase 7)",
    "S19-L": "No valid approval path, leave (G7 requester)", "S19-E": "No valid approval path, expense (G7 requester)",
    "S20": "Rule conflict (negative fixtures)", "S21": "Budget exceeded on CC-0024",
    "S22": "Overlap with pending leave", "S23": "Sick leave above 3 days without certificate",
    "S24": "Delegated L1 route (control)",
    "S25": "Technical payment failure (Phase 8; 5 percent of first payment attempts, count not fixed in advance)",
    "S26": "Line currency differs from claim currency", "BC-10": "Split pair at exactly the threshold (boundary)",
}


class GroundTruthDisagreement(RuntimeError):
    """Planted expectation and independent oracle disagree: the dataset must not ship (docs/07 9.2)."""


@dataclass
class GroundTruth:
    tables: dict[str, list[dict]]
    expectations: dict[tuple[str, str], Expectation]


def _check(subject: str, expected: frozenset[str], x: Expectation, checks: dict, problems: list[str]) -> None:
    if set(x.codes) != set(expected):
        problems.append(f"{subject}: construction {sorted(expected)} != oracle {x.codes}")
    if "levels" in checks and x.required_levels != checks["levels"]:
        problems.append(f"{subject}: levels {checks['levels']} != oracle {x.required_levels}")
    if "max_level" in checks and checks["max_level"] not in x.required_levels:
        problems.append(f"{subject}: {checks['max_level']} not in oracle levels {x.required_levels}")
    if "delegated_from" in checks and not any(s["delegated_from"] == checks["delegated_from"] for s in x.route or []):
        problems.append(f"{subject}: oracle route {x.route} has no step delegated from {checks['delegated_from']}")
    if checks.get("start_is_holiday") and not x.facts.get("holiday_span"):
        problems.append(f"{subject}: oracle does not see the holiday")


def planned_counts(cfg: dict, p: GenParams) -> dict[str, int]:
    a = cfg["generation"]["anomalies"]
    ref = a["reference_volumes"]

    def nl(k: int) -> int:
        return scaled_count(k, p.leave_requests, ref["leave"])

    def ne(k: int) -> int:
        return scaled_count(k, p.expense_claims, ref["expense"])

    out = {k: nl(v) * (2 if k == "S02" else 1) for k, v in a["leave"].items()}
    out.update({k: ne(v) * (2 if k in ("S06a", "S06b") else 1) for k, v in a["expense"].items()})
    out["S09"] = 2 * ne(a["split_groups"]["pairs"]) + 3 * ne(a["split_groups"]["triples"])
    c = a["controls"]
    out.update({"S01b": nl(c["S01b"]), "S04": nl(c["S04_min_total"]), "S14-L5": ne(c["S14-L5"]),
                "S24": nl(c["S24"]["leave"]) + ne(c["S24"]["expense"]), "S14": ne(150)})
    out.update({k: nl(v) for k, v in a["attempts"].items()})
    out.update(a["fixtures"])                      # fixed fixture files, not scaled
    out["S25"] = 0
    b = cfg["generation"]["boundaries"]
    per_e, per_l = ne(b["per_case"]), nl(b["per_case"])
    out.update({"BC-01": per_e, "BC-02": 2 * per_e, "BC-03": 2 * per_l, "BC-04": per_l, "BC-05": 2 * per_e,
                "BC-06": per_l, "BC-07": per_e, "BC-08": per_e, "BC-09": per_e, "BC-10": 2 * ne(b["bc10_groups"])})
    return out


def build_ground_truth(cfg: dict, p: GenParams, dataset: dict[str, list[dict]], plants: list[Plant],
                       boundaries: list[Boundary], leave_map: dict[str, str], claim_map: dict[str, str],
                       config_dir: Path, fixtures_dir: Path | None = None) -> GroundTruth:
    exp = compute_expectations(dataset, config_dir)
    remap = {"LEAVE": leave_map, "EXPENSE": claim_map}
    problems: list[str] = []
    planted: dict[tuple[str, str], set[str]] = {}
    labels: list[dict] = []
    for pl in plants:
        rid = remap[pl.record_type][pl.record_id]
        x = exp[(pl.record_type, rid)]
        _check(f"{pl.scenario_id} {rid}", pl.expected_codes, x, pl.checks, problems)
        planted.setdefault((pl.record_type, rid), set()).add(pl.issue_type)
        labels.append({
            "scenario_id": pl.scenario_id, "affected_record_type": pl.record_type, "affected_record_id": rid,
            "issue_type": pl.issue_type,
            "label": f"planted {pl.scenario_id}" + (f" ({pl.group})" if pl.group else ""),
            "expected_detection": "DETECT" if pl.detect else "NOT_DETECT",
            "expected_workflow_behaviour": pl.behaviour, "injection_reason": pl.reason, "is_planted": True,
        })
    bc_rows = []
    for b in boundaries:
        rid = remap[b.record_type][b.record_id]
        _check(f"{b.case_id} {rid}", b.expected_codes, exp[(b.record_type, rid)], b.checks, problems)
        bc_rows.append({"record_type": b.record_type, "record_id": rid,
                        "boundary_type": f"{b.case_id}:{b.boundary_type}", "expected_outcome": b.expected_outcome})
    if problems:
        raise GroundTruthDisagreement("planted expectation and reference oracle disagree:\n  " + "\n  ".join(problems))

    # Natural violations (docs/07 7.4) and natural controls (S04 holiday spans, S14 multi-level routes).
    planted_keys = {(sid, pl.record_type, remap[pl.record_type][pl.record_id])
                    for pl in plants for sid in [pl.scenario_id]}
    for key, x in sorted(exp.items()):
        if x.final_status == "DRAFT":
            continue
        for code in x.codes:
            if code not in planted.get(key, set()):
                labels.append({
                    "scenario_id": "NATURAL", "affected_record_type": key[0], "affected_record_id": key[1],
                    "issue_type": code, "label": "naturally occurring", "expected_detection": "DETECT",
                    "expected_workflow_behaviour": f"Expected outcome {x.final_status} (reference oracle)",
                    "injection_reason": "natural consequence", "is_planted": False,
                })
        if key[0] == "LEAVE" and x.facts.get("holiday_span") and ("S04", *key) not in planted_keys:
            labels.append(_control("S04", key, "natural: spans a public holiday"))
        if len(x.required_levels) >= 2 and ("S14-L5", *key) not in planted_keys:
            labels.append(_control("S14", key, f"natural: route {'+'.join(x.required_levels)}"))

    labels.sort(key=lambda r: (not r["is_planted"], r["scenario_id"], r["affected_record_type"],
                               r["affected_record_id"], r["issue_type"]))
    for i, r in enumerate(labels, start=1):
        r["label_id"] = f"GTL-{i:06d}"
    bc_rows.sort(key=lambda r: (r["boundary_type"], r["record_type"], r["record_id"]))
    for i, r in enumerate(bc_rows, start=1):
        r["case_id"] = f"GTB-{i:04d}"

    records = [{
        "record_type": k[0], "record_id": k[1],
        "expected_route": None if x.route is None else [dict(step) for step in x.route],
        "expected_final_status_at_asof": x.final_status,
        "expected_reimbursement_eligibility": x.eligible if k[0] == "EXPENSE" else None,
        "expected_exception_codes": x.codes, "expected_approved_amount": x.approved_amount,
    } for k, x in sorted(exp.items())]

    planned = planned_counts(cfg, p)
    actual: dict[str, int | None] = {}
    for r in labels:
        if r["scenario_id"].startswith("BC-"):
            continue                      # boundary records are counted once, from boundary_case below
        if r["is_planted"] or r["scenario_id"] in ("S04", "S14"):
            actual[r["scenario_id"]] = actual.get(r["scenario_id"], 0) + 1
    for r in bc_rows:
        case = r["boundary_type"].split(":")[0]
        actual[case] = actual.get(case, 0) + 1
    for sid, pattern in FIXTURE_GLOBS.items():
        actual[sid] = len(list(fixtures_dir.glob(pattern))) if fixtures_dir and fixtures_dir.is_dir() else None
    scenarios = [{
        "scenario_id": sid, "issue_type": {**ISSUE, **EXTRA_ISSUES}.get(sid, "BOUNDARY_CASE"),
        "description": DESCRIPTIONS.get(sid, f"Boundary record {sid} (docs/02 section 6)"),
        "planned_count": planned[sid], "actual_count": actual.get(sid),
    } for sid in sorted(planned)]
    return GroundTruth({"record_expectation": records, "anomaly_label": labels, "boundary_case": bc_rows,
                        "scenario": scenarios}, exp)


def _control(scenario: str, key: tuple[str, str], reason: str) -> dict:
    return {"scenario_id": scenario, "affected_record_type": key[0], "affected_record_id": key[1],
            "issue_type": ISSUE[scenario], "label": "naturally occurring control", "expected_detection": "NOT_DETECT",
            "expected_workflow_behaviour": BEHAVIOUR[scenario], "injection_reason": reason, "is_planted": False}


def gt_table(name: str) -> sa.Table:
    return GroundTruthBase.metadata.tables[f"ground_truth.{name}"]


def _pk_sorted(name: str, rows: list[dict]) -> list[dict]:
    keys = [c.name for c in gt_table(name).primary_key.columns]
    return sorted(rows, key=lambda r: tuple(r[k] for k in keys))


def write_ground_truth(gt: GroundTruth, folder: Path) -> list[Path]:
    """Canonical files (same rules as the ops export): CSV per table, scenarios.json, ground_truth.json."""
    folder.mkdir(parents=True, exist_ok=True)
    written, combined = [], {}
    for name in GT_TABLES:
        cols = list(gt_table(name).columns)
        rows = _pk_sorted(name, gt.tables[name])
        combined[name] = [{c.name: json_value(c, r[c.name]) for c in cols} for r in rows]
        if name in FILES:
            path = folder / FILES[name]
            with path.open("w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh, lineterminator="\n")
                w.writerow([c.name for c in cols])
                for r in rows:
                    w.writerow(["" if (v := canonical_text(c, r[c.name])) is None else v for c in cols])
            written.append(path)
    for path, payload in ((folder / "scenarios.json", combined["scenario"]), (folder / "ground_truth.json", combined)):
        path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
        written.append(path)
    return written


def load_ground_truth(gt: GroundTruth, database_url: str) -> dict[str, int]:
    """Replace the ground_truth schema contents in one transaction (owner role from DATABASE_URL)."""
    engine = sa.create_engine(database_url, poolclass=sa.pool.NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("TRUNCATE " + ", ".join(f"ground_truth.{t}" for t in GT_TABLES)))
            for name in GT_TABLES:
                # A JSON column stores Python None as JSON 'null'; the CHECK wants SQL NULL for "no route".
                rows = [{k: (sa.null() if v is None and k == "expected_route" else v) for k, v in r.items()}
                        for r in _pk_sorted(name, gt.tables[name])]
                if rows:
                    conn.execute(gt_table(name).insert(), rows)
            return {name: conn.execute(sa.select(sa.func.count()).select_from(gt_table(name))).scalar_one()
                    for name in GT_TABLES}
    finally:
        engine.dispose()
