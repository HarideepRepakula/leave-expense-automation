"""Evaluation metrics M1-M18 (spec section 17, defined in docs/08 section 3). Completion pass.

    python -m src.evaluation.metrics          # writes data/validation/evaluation.{csv,json,md}

Reads the stored operational data and ground truth through the lea_evaluation role, plus three files written by
other commands: validation_report.json (M1-M3, python -m src.validation), detections.csv (batch detectors, same
command) and reproducibility.json (M13, scripts/reproducibility_check.ps1). The only code that reads both kinds of
data; it imports nothing from src/services or src/reference.

Every metric is either computed from real rows or marked "not measurable: <reason>"; no number is invented.
Planted anomalies are excluded from the data-quality figures (spec 17): M4, M16 and M17 lead with the figure over
requests WITHOUT a planted anomaly (anomaly_label is_planted, expected_detection DETECT) and also give the figure
over all requests. Population dates are fixed at the dataset as-of date (config/generation.yaml as_of_date).
"""
from __future__ import annotations

import csv
import json
import statistics
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import sqlalchemy as sa
import yaml

from src.evaluation.summary import DETECTIONS_IN_DB, data_quality

ROOT = Path(__file__).resolve().parents[2]
VALIDATION_DIR = ROOT / "data" / "validation"
CSV_COLUMNS = ["metric_id", "metric_name", "breakdown_key", "breakdown_value", "numerator", "denominator", "value",
               "unit", "status", "note", "population_description", "computed_at"]
HOW_TO_READ = (
    "How to read these results: the benchmark is synthetic and its anomalies are planted by our own generator, so "
    "100% precision and recall shows that the detectors implement the documented rules; it does not predict "
    "accuracy on real data. Some detections are counted by construction: a duplicate reimbursement is blocked by a "
    "database unique index and recorded as a BLOCKED attempt, and a payment failure is recorded as a "
    "processing_failure row, so both are always 'detected'.")
ROUTING_CODES = ("NO_VALID_APPROVAL_PATH", "RULE_CONFLICT")
BUCKETS = ((0, 2, "0-2"), (3, 7, "3-7"), (8, 14, "8-14"), (15, 30, "15-30"), (31, 10 ** 6, ">30"))


def as_of_date() -> date:
    cfg = yaml.safe_load((ROOT / "config" / "generation.yaml").read_text(encoding="utf-8"))
    value = cfg["as_of_date"]
    return value if isinstance(value, date) else date.fromisoformat(str(value))


# --- small helpers ----------------------------------------------------------------------------------------------

def ratio(num: int, den: int) -> float | None:
    return None if den == 0 else round(num / den, 4)


def f1(p: float | None, r: float | None) -> float | None:
    if p is None or r is None:
        return None
    return 0.0 if p + r == 0 else round(2 * p * r / (p + r), 4)


def p90(values: list[float]) -> float:
    """Nearest-rank 90th percentile."""
    s = sorted(values)
    return s[max(0, -(-9 * len(s) // 10) - 1)]


def bucket(days: int) -> str:
    return next(label for lo, hi, label in BUCKETS if lo <= days <= hi)


def metric(mid: str, name: str, population: str, unit: str = "ratio", numerator=None, denominator=None,
           value=None, breakdown=None, note: str = "") -> dict:
    return {"metric_id": mid, "metric_name": name, "status": "measured", "value": value, "unit": unit,
            "numerator": numerator, "denominator": denominator, "population": population, "note": note,
            "breakdown": breakdown or []}


def not_measurable(mid: str, name: str, population: str, reason: str) -> dict:
    return {"metric_id": mid, "metric_name": name, "status": "not_measurable", "value": None, "unit": "",
            "numerator": None, "denominator": None, "population": population,
            "note": f"not measurable: {reason}", "breakdown": []}


def row(key: str, value, numerator=None, denominator=None, result=None, unit: str = "ratio") -> dict:
    return {"key": key, "value": value, "numerator": numerator, "denominator": denominator, "result": result,
            "unit": unit}


def mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def stats_rows(prefix: str, values: list[float]) -> list[dict]:
    if not values:
        return [row(prefix, "count", 0, None, 0, "count")]
    return [row(prefix, "count", len(values), None, len(values), "count"),
            row(prefix, "mean", None, None, round(statistics.fmean(values), 2), "days"),
            row(prefix, "median", None, None, round(statistics.median(values), 2), "days"),
            row(prefix, "p90", None, None, round(p90(values), 2), "days")]


# --- queries ----------------------------------------------------------------------------------------------------

REQUESTS = sa.text("""
    SELECT 'LEAVE' AS request_type, leave_request_id AS request_id, workflow_status, exception_class, current_round,
           first_submitted_at FROM ops.leave_request
    UNION ALL
    SELECT 'EXPENSE', expense_claim_id, workflow_status, exception_class, current_round, first_submitted_at
    FROM ops.expense_claim""")
CURRENT_EXCEPTIONS = sa.text("""
    SELECT coalesce(x.leave_request_id, x.expense_claim_id) AS request_id, x.exception_code, k.severity,
           k.exception_class
    FROM ops.request_exception x JOIN ops.exception_code k ON k.exception_code = x.exception_code
    LEFT JOIN ops.leave_request l ON l.leave_request_id = x.leave_request_id
    LEFT JOIN ops.expense_claim c ON c.expense_claim_id = x.expense_claim_id
    WHERE x.submission_round = coalesce(l.current_round, c.current_round)""")
PLANTED = sa.text("""
    SELECT DISTINCT affected_record_id FROM ground_truth.anomaly_label
    WHERE is_planted AND expected_detection = 'DETECT' AND affected_record_type IN ('LEAVE', 'EXPENSE')""")
LABELS = sa.text("""
    SELECT DISTINCT affected_record_id, issue_type, is_planted FROM ground_truth.anomaly_label
    WHERE expected_detection = 'DETECT'""")
EXPECTATIONS = sa.text("""
    SELECT record_type, record_id, expected_route, expected_exception_codes FROM ground_truth.record_expectation
    WHERE record_type IN ('LEAVE', 'EXPENSE')""")
STEPS = sa.text("""
    SELECT coalesce(s.leave_request_id, s.expense_claim_id) AS request_id, s.sequence_no, s.required_level,
           s.approver_employee_id, s.delegated_from_employee_id, s.covered_levels, s.step_status, s.assigned_at,
           s.decision_at
    FROM ops.approval_step s
    LEFT JOIN ops.leave_request l ON l.leave_request_id = s.leave_request_id
    LEFT JOIN ops.expense_claim c ON c.expense_claim_id = s.expense_claim_id
    WHERE s.submission_round = coalesce(l.current_round, c.current_round)
    ORDER BY request_id, s.sequence_no""")
STATUS_EVENTS = sa.text("""
    SELECT coalesce(leave_request_id, expense_claim_id) AS request_id, previous_status, new_status, occurred_at
    FROM ops.request_status_event ORDER BY request_id, occurred_at, event_id""")
UNAUTHORIZED_LABELS = sa.text("""
    SELECT affected_record_id FROM ground_truth.anomaly_label
    WHERE issue_type IN ('SELF_APPROVAL_ATTEMPT', 'UNAUTHORIZED_APPROVER_ATTEMPT')""")
ATTEMPT_RECHECK = sa.text("""
    SELECT count(*) FILTER (WHERE a.actor_id = coalesce(l.employee_id, c.employee_id)) AS self_accepted,
           count(*) FILTER (WHERE a.actor_id <> s.approver_employee_id) AS not_assigned_accepted,
           count(*) AS accepted
    FROM ops.approval_attempt a JOIN ops.approval_step s ON s.approval_step_id = a.approval_step_id
    LEFT JOIN ops.leave_request l ON l.leave_request_id = a.leave_request_id
    LEFT JOIN ops.expense_claim c ON c.expense_claim_id = a.expense_claim_id
    WHERE a.outcome = 'ACCEPTED'""")
DUP_REIMBURSEMENT = sa.text("""
    SELECT g.affected_record_id,
           EXISTS (SELECT 1 FROM ops.reimbursement_attempt a WHERE a.expense_claim_id = g.affected_record_id
                   AND a.outcome = 'BLOCKED' AND a.reason_code = 'DUPLICATE_REIMBURSEMENT') AS blocked,
           (SELECT count(*) FROM ops.reimbursement r WHERE r.expense_claim_id = g.affected_record_id
            AND r.reimbursement_status <> 'CANCELLED') AS active
    FROM ground_truth.anomaly_label g WHERE g.issue_type = 'DUPLICATE_REIMBURSEMENT_ATTEMPT'""")
MULTI_ACTIVE = sa.text("""
    SELECT count(*) FROM (SELECT expense_claim_id FROM ops.reimbursement WHERE reimbursement_status <> 'CANCELLED'
                          GROUP BY expense_claim_id HAVING count(*) > 1) d""")
ELIGIBILITY = sa.text("""
    WITH approved_at AS (
        SELECT expense_claim_id, max(occurred_at) AS at FROM ops.request_status_event
        WHERE new_status = 'APPROVED' AND expense_claim_id IS NOT NULL GROUP BY expense_claim_id),
    active AS (SELECT expense_claim_id, count(*) AS n FROM ops.reimbursement
               WHERE reimbursement_status <> 'CANCELLED' GROUP BY expense_claim_id)
    SELECT count(*) AS reimbursements,
           count(*) FILTER (WHERE c.workflow_status <> 'APPROVED') AS claim_not_approved,
           count(*) FILTER (WHERE r.approved_amount <> c.approved_amount OR r.currency <> c.currency)
               AS amount_mismatch,
           count(*) FILTER (WHERE p.at IS NULL OR r.created_at < p.at) AS before_approval,
           count(*) FILTER (WHERE a.n > 1) AS second_active,
           count(*) FILTER (WHERE c.workflow_status <> 'APPROVED' OR r.approved_amount <> c.approved_amount
                            OR r.currency <> c.currency OR p.at IS NULL OR r.created_at < p.at OR a.n > 1)
               AS violations
    FROM ops.reimbursement r JOIN ops.expense_claim c ON c.expense_claim_id = r.expense_claim_id
    LEFT JOIN approved_at p ON p.expense_claim_id = r.expense_claim_id
    LEFT JOIN active a ON a.expense_claim_id = r.expense_claim_id
    WHERE r.reimbursement_status <> 'CANCELLED'""")
APPROVED_WITHOUT_REIMBURSEMENT = sa.text("""
    SELECT count(*) FROM ops.expense_claim c WHERE c.workflow_status = 'APPROVED' AND c.approved_amount > 0
    AND NOT EXISTS (SELECT 1 FROM ops.reimbursement r WHERE r.expense_claim_id = c.expense_claim_id
                    AND r.reimbursement_status <> 'CANCELLED')""")


# --- the metrics ------------------------------------------------------------------------------------------------

def data_quality_metrics(validation_dir: Path) -> list[dict]:
    names = {"M1": "Primary-key violation rate", "M2": "Foreign-key violation rate",
             "M3": "Arithmetic reconciliation rate"}
    dq = data_quality(validation_dir)
    out = []
    for mid, name in names.items():
        if not dq.get("available") or mid not in dq:
            out.append(not_measurable(mid, name, "validation report",
                                      "data/validation/validation_report.json missing; run python -m src.validation"))
            continue
        m = dq[mid]
        out.append(metric(mid, name, "exported operational rows (python -m src.validation; docs/08 3)",
                          numerator=m["numerator"], denominator=m["denominator"], value=m["value"],
                          note="computed by the validation checks on the stored data"))
    return out


def compliance(reqs: list[dict], exc: list[dict], planted: set[str]) -> dict:
    blocking = {e["request_id"] for e in exc if e["severity"] in ("HARD", "CORRECTABLE", "SOFT")}
    clean = [r for r in reqs if r["request_id"] not in planted]
    ok_all = sum(r["request_id"] not in blocking for r in reqs)
    ok_clean = sum(r["request_id"] not in blocking for r in clean)
    return metric("M4", "Business-rule compliance rate",
                  "requests (leave + expense), current round; headline excludes requests with a planted anomaly",
                  numerator=ok_clean, denominator=len(clean), value=ratio(ok_clean, len(clean)),
                  breakdown=[row("population", "without planted anomalies", ok_clean, len(clean),
                                 ratio(ok_clean, len(clean))),
                             row("population", "all requests (business view)", ok_all, len(reqs),
                                 ratio(ok_all, len(reqs)))],
                  note="compliant = no HARD, CORRECTABLE or SOFT exception code in the current round (INFO "
                       "allowed)")


def _actual_route(steps: list[dict]) -> list[tuple]:
    return [(s["required_level"], tuple(sorted(s["covered_levels"] or [])), s["approver_employee_id"],
             s["delegated_from_employee_id"]) for s in steps]


def _expected_route(route: list[dict]) -> list[tuple]:
    return [(x["level"], tuple(sorted(x.get("covers") or [])), x["approver_id"], x.get("delegated_from"))
            for x in route]


def routing(expectations: list[dict], steps_by_req: dict, exc_codes: dict, routed: set[str]) -> dict:
    """routed = requests that reached routing (a PENDING_APPROVAL status event, or stored steps for legacy rows);
    the expected route is also filled for requests stopped before routing, which docs/08 M5 leaves out."""
    population = correct = level_correct = 0
    by_type: Counter = Counter()
    by_type_ok: Counter = Counter()
    wrong = []
    for x in expectations:
        codes = [c for c in (x["expected_exception_codes"] or []) if c in ROUTING_CODES]
        if not codes and (x["expected_route"] is None or x["record_id"] not in routed):
            continue
        population += 1
        by_type[x["record_type"]] += 1
        steps = steps_by_req.get(x["record_id"], [])
        if x["expected_route"] is not None:
            exp, act = _expected_route(x["expected_route"]), _actual_route(steps)
            ok = exp == act
            lvl_ok = [e[0] for e in exp] == [a[0] for a in act]
        else:
            ok = lvl_ok = not steps and set(codes) <= exc_codes.get(x["record_id"], set())
        correct += ok
        level_correct += lvl_ok
        by_type_ok[x["record_type"]] += ok
        if not ok:
            wrong.append(x["record_id"])
    breakdown = [row("request_type", t, by_type_ok[t], by_type[t], ratio(by_type_ok[t], by_type[t]))
                 for t in sorted(by_type)]
    breakdown.append(row("secondary", "level-only accuracy", level_correct, population,
                         ratio(level_correct, population)))
    breakdown += [row("disagreement", rid, None, None, None, "record") for rid in wrong[:50]]
    return metric("M5", "Approval routing accuracy",
                  "requests that reached routing (PENDING_APPROVAL at some point, or stored steps), plus requests "
                  "whose expectation is a routing exception code (NO_VALID_APPROVAL_PATH, RULE_CONFLICT)",
                  numerator=correct, denominator=population, value=ratio(correct, population), breakdown=breakdown,
                  note="stored current-round approval steps (level, covered levels, approver, delegated-from) vs "
                       "the expected route from the independent reference calculation; for S19 / S20 the "
                       "expected routing exception code and no steps")


def anomaly_metrics(detected: set, labels: list[tuple]) -> list[dict]:
    positives = {(r, c) for r, c, _ in labels}
    planted = {(r, c) for r, c, p in labels if p}
    natural = positives - planted
    tp, fp, fn = len(detected & positives), len(detected - positives), len(positives - detected)
    p, r = ratio(tp, tp + fp), ratio(tp, tp + fn)
    per_code = []
    for code in sorted({c for _, c in detected | positives}):
        d, g = {x for x in detected if x[1] == code}, {x for x in positives if x[1] == code}
        cp, cr = ratio(len(d & g), len(d)), ratio(len(d & g), len(g))
        per_code.append((code, len(d & g), len(d - g), len(g - d), cp, cr, f1(cp, cr)))
    macro_p = mean([c[4] for c in per_code if c[4] is not None])
    macro_r = mean([c[5] for c in per_code if c[5] is not None])
    pop = "(record_id, code) pairs: detections vs ground-truth labels with expected_detection = DETECT (docs/08 2)"
    common = [row("count", "TP", tp, None, tp, "count"), row("count", "FP", fp, None, fp, "count"),
              row("count", "FN", fn, None, fn, "count")]
    sub = [row("subset recall", "planted", len(detected & planted), len(planted),
               ratio(len(detected & planted), len(planted))),
           row("subset recall", "natural", len(detected & natural), len(natural),
               ratio(len(detected & natural), len(natural)))]
    return [
        metric("M6", "Anomaly precision", pop, numerator=tp, denominator=tp + fp, value=p,
               breakdown=common + [row("macro average", "precision", None, None, macro_p)]
               + [row("issue_type", c[0], c[1], c[1] + c[2], c[4]) for c in per_code],
               note="micro-averaged over issue types"),
        metric("M7", "Anomaly recall", pop, numerator=tp, denominator=tp + fn, value=r,
               breakdown=common + sub + [row("macro average", "recall", None, None, macro_r)]
               + [row("issue_type", c[0], c[1], c[1] + c[3], c[5]) for c in per_code],
               note="micro-averaged over issue types; planted and natural positives reported separately"),
        metric("M8", "Anomaly F1 score", pop, value=f1(p, r),
               breakdown=[row("macro average", "F1", None, None, f1(macro_p, macro_r))]
               + [row("issue_type", c[0], None, None, c[6]) for c in per_code],
               note="F1 = 2PR / (P + R)"),
    ]


def subset_detection(mid: str, name: str, detected: set, labels: list[tuple], codes: set[str], note: str) -> dict:
    g = {(r, c) for r, c, _ in labels if c in codes}
    d = {x for x in detected if x[1] in codes}
    pop = f"ground-truth labels with issue_type in {sorted(codes)}"
    if not g:
        return not_measurable(mid, name, pop, "no labelled records of these issue types in the dataset")
    per_code = []
    for c in sorted(codes):
        hit, total = len({x for x in d & g if x[1] == c}), len({x for x in g if x[1] == c})
        per_code.append(row("issue_type", c, hit, total, ratio(hit, total)))
    return metric(mid, name, pop, numerator=len(d & g), denominator=len(g), value=ratio(len(d & g), len(g)),
                  breakdown=[row("precision (same types)", "precision", len(d & g), len(d),
                                 ratio(len(d & g), len(d)))] + per_code, note=note)


def unauthorized(conn: sa.Connection) -> dict:
    labels = conn.execute(UNAUTHORIZED_LABELS).scalars().all()
    name, pop = ("Unauthorized approval detection rate",
                 "labels SELF_APPROVAL_ATTEMPT / UNAUTHORIZED_APPROVER_ATTEMPT (attempt ids)")
    recheck = conn.execute(ATTEMPT_RECHECK).mappings().one()
    if not labels:
        m = not_measurable("M9", name, pop, "the S11 / S12 plants (self-approval and unauthorized-approver "
                                            "attempts) are deferred to 8B-2, so the dataset has no labelled "
                                            "attempt; the guards are covered by unit and API tests instead")
    else:
        blocked = set(conn.execute(sa.text(
            "SELECT attempt_id FROM ops.approval_attempt WHERE outcome = 'BLOCKED' "
            "AND reason_code IN ('SELF_APPROVAL', 'UNAUTHORIZED_APPROVER')")).scalars())
        n = sum(label in blocked for label in labels)
        m = metric("M9", name, pop, numerator=n, denominator=len(labels), value=ratio(n, len(labels)))
    m["breakdown"] = [row("supplement", "ACCEPTED attempts by the requester (must be 0)", recheck["self_accepted"],
                          recheck["accepted"], recheck["self_accepted"], "count"),
                      row("supplement", "ACCEPTED attempts by someone other than the step's approver (must be 0)",
                          recheck["not_assigned_accepted"], recheck["accepted"], recheck["not_assigned_accepted"],
                          "count")]
    return m


def duplicate_reimbursement(conn: sa.Connection) -> dict:
    rows = conn.execute(DUP_REIMBURSEMENT).mappings().all()
    name, pop = "Duplicate reimbursement detection rate", "labels DUPLICATE_REIMBURSEMENT_ATTEMPT (claim ids)"
    if not rows:
        return not_measurable("M11", name, pop, "no labelled duplicate reimbursement attempt in the dataset")
    n = sum(bool(r["blocked"]) and r["active"] == 1 for r in rows)
    multi = conn.execute(MULTI_ACTIVE).scalar_one()
    return metric("M11", name, pop, numerator=n, denominator=len(rows), value=ratio(n, len(rows)),
                  breakdown=[row("supplement", "claims with more than one active reimbursement (must be 0)", multi,
                                 None, multi, "count")],
                  note="detected = BLOCKED DUPLICATE_REIMBURSEMENT attempt and exactly one active reimbursement; "
                       "counted by construction (unique index), see 'How to read'")


def eligibility(conn: sa.Connection) -> dict:
    e = conn.execute(ELIGIBILITY).mappings().one()
    missing = conn.execute(APPROVED_WITHOUT_REIMBURSEMENT).scalar_one()
    return metric("M12", "Reimbursement eligibility violation rate", "reimbursements with status <> CANCELLED",
                  numerator=e["violations"], denominator=e["reimbursements"],
                  value=ratio(e["violations"], e["reimbursements"]),
                  breakdown=[row("violation", k, e[k], e["reimbursements"], ratio(e[k], e["reimbursements"]))
                             for k in ("claim_not_approved", "amount_mismatch", "before_approval", "second_active")]
                  + [row("supplement", "APPROVED claims (amount > 0) with no reimbursement", missing, None, missing,
                         "count")],
                  note="before_approval = created before the claim's APPROVED status event")


def reproducibility(validation_dir: Path) -> dict:
    name, pop = "Reproducibility rate", "exported files of two generator runs with identical parameters"
    path = validation_dir / "reproducibility.json"
    if not path.exists():
        return not_measurable("M13", name, pop, "data/validation/reproducibility.json missing; run "
                                                "scripts/reproducibility_check.ps1")
    r = json.loads(path.read_text(encoding="utf-8"))
    return metric("M13", name, pop, numerator=r["identical_sha256"], denominator=r["files_compared"],
                  value=ratio(r["identical_sha256"], r["files_compared"]),
                  breakdown=[row("folder", k, v["identical"], v["files"], ratio(v["identical"], v["files"]))
                             for k, v in r["per_folder"].items()]
                  + [row("fingerprint", "A == B", None, None, r["fingerprint_a"] == r["fingerprint_b"], "bool")],
                  note="identical = same SHA-256 of the canonical file, manifest.generated_at excluded (ASM-050)")


def turnaround(reqs: list[dict], events: dict) -> dict:
    by_type: dict[str, list[float]] = defaultdict(list)
    legacy = 0
    for r in reqs:
        if r["workflow_status"] not in ("APPROVED", "REJECTED") or r["first_submitted_at"] is None:
            continue
        times = [e["occurred_at"] for e in events[r["request_id"]] if e["new_status"] == r["workflow_status"]]
        if not times:                   # legacy approval: no status events by design (DEC-P7B-02), no decision time
            legacy += 1
            continue
        by_type[r["request_type"]].append((max(times) - r["first_submitted_at"]).total_seconds() / 86400)
    values = [v for vs in by_type.values() for v in vs]
    rounds = sorted({r["current_round"] for r in reqs})
    return metric("M14", "Average approval turnaround time",
                  "requests APPROVED or REJECTED at as-of with a recorded decision; final decision time - first "
                  "submission time",
                  unit="days", numerator=len(values), value=round(statistics.fmean(values), 2) if values else None,
                  breakdown=stats_rows("all", values) + [x for t in sorted(by_type)
                                                         for x in stats_rows(t, by_type[t])]
                  + [row("excluded", "legacy approvals without a decision time (DEC-P7B-02)", legacy, None, legacy,
                         "count")],
                  note="calendar days with decimals. Not measured: the business-day variant (not computed in "
                       f"this pass) and the split by number of rounds (rounds present: {rounds}; resubmissions "
                       "are deferred to 8B-2)")


def backlog(reqs: list[dict], events: dict, steps_by_req: dict, as_of: date) -> dict:
    status = Counter(r["workflow_status"] for r in reqs)
    pending = [r for r in reqs if r["workflow_status"] == "PENDING_APPROVAL"]
    aging: Counter = Counter()
    by_level: Counter = Counter()
    for r in pending:
        last = max(e["occurred_at"] for e in events[r["request_id"]])
        aging[bucket((as_of - last.date()).days)] += 1
        waiting = [s for s in steps_by_req.get(r["request_id"], []) if s["step_status"] == "PENDING"]
        by_level[waiting[0]["required_level"] if waiting else "none"] += 1
    return metric("M15", "Pending approval backlog", f"requests in PENDING_APPROVAL at as-of {as_of}", unit="count",
                  numerator=len(pending), value=len(pending),
                  breakdown=[row("counted separately", s, status[s], None, status[s], "count")
                             for s in ("ESCALATED_FOR_REVIEW", "RETURNED_FOR_CORRECTION")]
                  + [row("aging (days since last status change)", lbl, aging[lbl], len(pending), aging[lbl],
                         "count") for _, _, lbl in BUCKETS]
                  + [row("awaiting level", lvl, n, len(pending), n, "count") for lvl, n in sorted(by_level.items())])


def exception_rate(reqs: list[dict], exc: list[dict], planted: set[str]) -> dict:
    clean = [r for r in reqs if r["request_id"] not in planted]

    def has(rs):
        return sum(r["exception_class"] != "NONE" for r in rs)

    codes = Counter(e["exception_code"] for e in exc)
    classes = Counter(r["exception_class"] for r in reqs if r["exception_class"] != "NONE")
    return metric("M16", "Policy exception rate",
                  "requests, current round; headline excludes requests with a planted anomaly",
                  numerator=has(clean), denominator=len(clean), value=ratio(has(clean), len(clean)),
                  breakdown=[row("population", "without planted anomalies", has(clean), len(clean),
                                 ratio(has(clean), len(clean))),
                             row("population", "all requests (business view)", has(reqs), len(reqs),
                                 ratio(has(reqs), len(reqs)))]
                  + [row("exception_class (all requests)", k, v, len(reqs), ratio(v, len(reqs)))
                     for k, v in sorted(classes.items())]
                  + [row("exception_code (all requests, once per code)", k, v, None, v, "count")
                     for k, v in sorted(codes.items())],
                  note="exception = exception_class <> NONE")


def rejection(reqs: list[dict], events: dict, planted: set[str]) -> dict:
    stage_of = {"VALIDATING": "at validation", "PENDING_APPROVAL": "by an approver",
                "ESCALATED_FOR_REVIEW": "by a process owner"}
    decided = [r for r in reqs if r["workflow_status"] in ("APPROVED", "REJECTED")]
    clean = [r for r in decided if r["request_id"] not in planted]

    def rej(rs):
        return sum(r["workflow_status"] == "REJECTED" for r in rs)

    stages: Counter = Counter()
    for r in decided:
        if r["workflow_status"] == "REJECTED":
            prev = [e["previous_status"] for e in events[r["request_id"]] if e["new_status"] == "REJECTED"][-1]
            stages[stage_of.get(prev, prev)] += 1
    return metric("M17", "Request rejection rate",
                  "requests APPROVED or REJECTED; headline excludes requests with a planted anomaly",
                  numerator=rej(clean), denominator=len(clean), value=ratio(rej(clean), len(clean)),
                  breakdown=[row("population", "decided, without planted anomalies", rej(clean), len(clean),
                                 ratio(rej(clean), len(clean))),
                             row("population", "decided, all (business view)", rej(decided), len(decided),
                                 ratio(rej(decided), len(decided))),
                             row("secondary", "rejected / all requests", rej(reqs), len(reqs),
                                 ratio(rej(reqs), len(reqs)))]
                  + [row("stage (all rejections)", s, stages.get(s, 0), rej(decided), stages.get(s, 0), "count")
                     for s in stage_of.values()])


def level_time(steps_by_req: dict, as_of: date) -> dict:
    decided: dict[str, list[float]] = defaultdict(list)
    pending: dict[str, list[int]] = defaultdict(list)
    for steps in steps_by_req.values():
        for s in steps:
            if s["step_status"] in ("APPROVED", "REJECTED") and s["decision_at"] is not None:
                decided[s["required_level"]].append((s["decision_at"] - s["assigned_at"]).total_seconds() / 86400)
            elif s["step_status"] == "PENDING" and s["assigned_at"] is not None:     # later steps: not yet assigned
                pending[s["required_level"]].append((as_of - s["assigned_at"].date()).days)
    levels = ["L1", "L2", "L3", "L4", "L5"]
    breakdown = []
    for lvl in levels:
        breakdown += stats_rows(lvl, decided[lvl])[:3]
        breakdown.append(row(lvl, "pending steps: mean age at as-of (not in the mean)", len(pending[lvl]), None,
                             round(statistics.fmean(pending[lvl]), 2) if pending[lvl] else None, "days"))
    all_values = [v for lvl in levels for v in decided[lvl]]
    return metric("M18", "Average time spent at each approval level",
                  "approval steps (current round) APPROVED or REJECTED; decision_at - assigned_at",
                  unit="days", numerator=len(all_values),
                  value=round(statistics.fmean(all_values), 2) if all_values else None, breakdown=breakdown,
                  note="headline = mean over all levels; per-level count, mean and median in the breakdown")


def compute(engine: sa.Engine, validation_dir: Path = VALIDATION_DIR, as_of: date | None = None) -> dict:
    as_of = as_of or as_of_date()
    with engine.connect() as conn:
        reqs = [dict(r) for r in conn.execute(REQUESTS).mappings()]
        exc = [dict(r) for r in conn.execute(CURRENT_EXCEPTIONS).mappings()]
        planted = set(conn.execute(PLANTED).scalars())
        labels = [tuple(r) for r in conn.execute(LABELS)]
        expectations = [dict(r) for r in conn.execute(EXPECTATIONS).mappings()]
        steps_by_req: dict[str, list[dict]] = defaultdict(list)
        for s in conn.execute(STEPS).mappings():
            steps_by_req[s["request_id"]].append(dict(s))
        events: dict[str, list[dict]] = defaultdict(list)
        for e in conn.execute(STATUS_EVENTS).mappings():
            events[e["request_id"]].append(dict(e))
        detected = {(r, c) for r, c in conn.execute(DETECTIONS_IN_DB)}
        m9, m11, m12 = unauthorized(conn), duplicate_reimbursement(conn), eligibility(conn)
    path = validation_dir / "detections.csv"
    if path.exists():
        with path.open(encoding="utf-8", newline="") as fh:
            detected |= {(d["record_id"], d["exception_code"]) for d in csv.DictReader(fh)}
    exc_codes: dict[str, set] = defaultdict(set)
    for e in exc:
        exc_codes[e["request_id"]].add(e["exception_code"])
    metrics = data_quality_metrics(validation_dir)
    metrics.append(compliance(reqs, exc, planted))
    routed = set(steps_by_req) | {rid for rid, evs in events.items()
                                  if any(e["new_status"] == "PENDING_APPROVAL" for e in evs)}
    metrics.append(routing(expectations, steps_by_req, exc_codes, routed))
    metrics += anomaly_metrics(detected, labels)
    metrics.append(m9)
    metrics.append(subset_detection("M10", "Duplicate receipt detection rate", detected, labels,
                                    {"DUPLICATE_RECEIPT_SELF", "DUPLICATE_RECEIPT_CROSS_EMPLOYEE"},
                                    "recall over the duplicate-receipt labels; precision for the same types in "
                                    "the breakdown"))
    metrics += [m11, m12, reproducibility(validation_dir), turnaround(reqs, events),
                backlog(reqs, events, steps_by_req, as_of), exception_rate(reqs, exc, planted),
                rejection(reqs, events, planted), level_time(steps_by_req, as_of)]
    return {"as_of": as_of.isoformat(), "how_to_read": HOW_TO_READ, "metrics": metrics}


# --- output -----------------------------------------------------------------------------------------------------

def display(value, unit: str) -> str:
    if value is None:
        return ""
    if unit == "ratio" and isinstance(value, float):
        return f"{value:.2%}"
    return str(value)


def headline(m: dict) -> str:
    return m["note"] if m["status"] == "not_measurable" else f"{display(m['value'], m['unit'])} {m['unit']}"


def csv_rows(result: dict) -> list[dict]:
    out = []
    for m in result["metrics"]:
        base = {"metric_id": m["metric_id"], "metric_name": m["metric_name"], "status": m["status"],
                "population_description": m["population"], "computed_at": result["as_of"]}
        out.append({**base, "breakdown_key": "", "breakdown_value": "", "numerator": m["numerator"],
                    "denominator": m["denominator"], "value": m["value"], "unit": m["unit"], "note": m["note"]})
        for b in m["breakdown"]:
            out.append({**base, "breakdown_key": b["key"], "breakdown_value": b["value"],
                        "numerator": b["numerator"], "denominator": b["denominator"], "value": b["result"],
                        "unit": b["unit"], "note": ""})
    return out


def _cell(value) -> str:
    return "" if value is None else str(value)


def markdown(result: dict) -> str:
    lines = ["# Evaluation results (M1-M18)", "",
             f"Generated by `python -m src.evaluation.metrics` from the stored data; as-of {result['as_of']}. "
             "Definitions: docs/08 section 3. Every number is produced by the code (same data as evaluation.csv).",
             "", "> " + result["how_to_read"], "",
             "| Metric | Name | Value | Numerator / denominator |", "|---|---|---|---|"]
    for m in result["metrics"]:
        nd = "" if m["numerator"] is None else f"{m['numerator']} / {_cell(m['denominator']) or '-'}"
        lines.append(f"| {m['metric_id']} | {m['metric_name']} | {headline(m)} | {nd} |")
    for m in result["metrics"]:
        lines += ["", f"## {m['metric_id']} {m['metric_name']}", "", f"Population: {m['population']}."]
        if m["note"]:
            lines.append(f"Note: {m['note']}.")
        if m["breakdown"]:
            lines += ["", "| Breakdown | Item | Numerator | Denominator | Value |", "|---|---|---|---|---|"]
            lines += [f"| {b['key']} | {b['value']} | {_cell(b['numerator'])} | {_cell(b['denominator'])} | "
                      f"{display(b['result'], b['unit'])} |" for b in m["breakdown"]]
    return "\n".join(lines) + "\n"


def write(result: dict, out_dir: Path = VALIDATION_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "evaluation.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(csv_rows(result))
    (out_dir / "evaluation.json").write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8",
                                             newline="\n")
    (out_dir / "evaluation.md").write_text(markdown(result), encoding="utf-8", newline="\n")


def main() -> int:
    from src.common.config import get_settings

    s = get_settings()
    engine = sa.create_engine(s.role_url(s.postgres_evaluation_user, s.postgres_evaluation_password))
    result = compute(engine)
    write(result)
    for m in result["metrics"]:
        print(f"{m['metric_id']:<4} {m['metric_name']:<45} {headline(m)}")
    print(f"written: {VALIDATION_DIR / 'evaluation.csv'}, evaluation.json, evaluation.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
