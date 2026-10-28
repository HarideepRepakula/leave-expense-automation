"""Phase 4: anomaly injection keeps exact volumes, every planted scenario reaches its planned count, ground truth
is complete and consistent with the independent oracle, and the Phase 3 carry-ins hold. No database needed."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import yaml

from src.data.config_loader import load_config
from src.data.stages import GenParams
from src.data.stages.expenses import receipt_hash
from src.data.stages.ground_truth import planned_counts
from src.reference.oracle import ledger_accrual_mismatches

ROOT = Path(__file__).resolve().parents[2]
GROUP_A = ["S01", "S02", "S03", "S19-L", "S22", "S23", "S05", "S06a", "S06b", "S07a", "S07b", "S08", "S09", "S10",
           "S15", "S19-E", "S21", "S26"]
CONTROLS = ["S01b", "S14-L5", "S24"]
BOUNDARIES = [f"BC-{i:02d}" for i in range(1, 11)]


def _scenarios(g):
    return {s["scenario_id"]: s for s in g.truth.tables["scenario"]}


def test_exact_core_volumes_after_injection(gen):
    _, vol, g = gen
    ds = g.dataset
    assert (len(ds["employee"]), len(ds["leave_policy"]), len(ds["leave_request"]), len(ds["expense_claim"])) == \
        (vol["employees"], 6, vol["leave_requests"], vol["expense_claims"])
    assert len(g.truth.tables["record_expectation"]) == vol["leave_requests"] + vol["expense_claims"]


def test_full_scale_planted_counts_equal_plan(full_gen):
    s = _scenarios(full_gen)
    for sid in GROUP_A + CONTROLS + BOUNDARIES + ["S16", "S17", "S20"]:
        assert s[sid]["actual_count"] == s[sid]["planned_count"], sid
    assert s["S04"]["actual_count"] >= 40 and s["S14"]["actual_count"] >= 150
    planted = [r for r in full_gen.truth.tables["anomaly_label"] if r["is_planted"] and r["scenario_id"] in GROUP_A]
    assert len(planted) == 176                                   # ASM-027: 9.8 percent of 1,800
    assert Counter(r["affected_record_type"] for r in planted) == {"LEAVE": 56, "EXPENSE": 120}


def test_attempt_scenarios_are_listed_but_not_yet_built(full_gen):
    s = _scenarios(full_gen)
    for sid in ("S11", "S12", "S13", "S18", "S25"):
        assert s[sid]["actual_count"] is None, sid               # rows arrive with Phases 7-8


def test_one_planted_scenario_per_record(gen):
    _, _, g = gen
    per_record = Counter((r["affected_record_type"], r["affected_record_id"])
                         for r in g.truth.tables["anomaly_label"] if r["is_planted"])
    assert max(per_record.values()) == 1


def test_labels_agree_with_record_expectations(gen):
    _, _, g = gen
    expectations = {(r["record_type"], r["record_id"]): r for r in g.truth.tables["record_expectation"]}
    for lab in g.truth.tables["anomaly_label"]:
        rec = expectations[(lab["affected_record_type"], lab["affected_record_id"])]
        if lab["expected_detection"] == "DETECT":
            assert lab["issue_type"] in rec["expected_exception_codes"], lab["label_id"]
        elif lab["is_planted"]:
            assert rec["expected_exception_codes"] == [], lab["label_id"]   # planted controls are clean


def test_natural_labels_cover_every_unplanted_code(gen):
    _, _, g = gen
    labelled = {(r["affected_record_type"], r["affected_record_id"], r["issue_type"])
                for r in g.truth.tables["anomaly_label"] if r["expected_detection"] == "DETECT"}
    for rec in g.truth.tables["record_expectation"]:
        for code in rec["expected_exception_codes"]:
            assert (rec["record_type"], rec["record_id"], code) in labelled
    for r in g.truth.tables["anomaly_label"]:
        if r["scenario_id"] == "NATURAL":
            assert not r["is_planted"] and r["injection_reason"] == "natural consequence"


def test_natural_split_pair_labelled_naturally_occurring(full_gen):
    """Carry-in: the split pair that occurs naturally in the baseline is labelled is_planted = false."""
    natural = [r for r in full_gen.truth.tables["anomaly_label"]
               if r["scenario_id"] == "NATURAL" and r["issue_type"] == "SPLIT_CLAIM_SUSPECTED"]
    assert len(natural) == 2 and all(not r["is_planted"] for r in natural)


def test_at_least_eight_claims_reach_l5(full_gen):
    """Carry-in: at least 8 claims route to the highest level (amount above 5,000 USD)."""
    l5 = [r for r in full_gen.truth.tables["record_expectation"]
          if r["record_type"] == "EXPENSE" and r["expected_route"]
          and any("L5" in step["covers"] for step in r["expected_route"])]
    assert len(l5) >= 8


def test_s19_cause_is_g7_requester_not_l1_is_g7(gen):
    """Carry-in: planted S19 requests come from the G7 (no L1), never from a direct report of the G7."""
    _, _, g = gen
    ds = g.dataset
    g7 = next(e["employee_id"] for e in ds["employee"] if e["grade"] == "G7")
    owners = {**{r["leave_request_id"]: r["employee_id"] for r in ds["leave_request"]},
              **{c["expense_claim_id"]: c["employee_id"] for c in ds["expense_claim"]}}
    s19 = [r for r in g.truth.tables["anomaly_label"] if r["scenario_id"] in ("S19-L", "S19-E")]
    assert s19 and all(owners[r["affected_record_id"]] == g7 for r in s19)
    natural_nvp = [r for r in g.truth.tables["anomaly_label"]
                   if r["scenario_id"] == "NATURAL" and r["issue_type"] == "NO_VALID_APPROVAL_PATH"]
    assert natural_nvp == [], "direct reports of the G7 resolve to one G7 step (AMB-P3-03)"


def test_g7_direct_reports_get_one_step_covering_l1_and_l2(full_gen):
    ds = full_gen.dataset
    g7 = next(e["employee_id"] for e in ds["employee"] if e["grade"] == "G7")
    reports = {e["employee_id"] for e in ds["employee"] if e["manager_id"] == g7}
    owners = {c["expense_claim_id"]: c["employee_id"] for c in ds["expense_claim"]}
    checked = 0
    for r in full_gen.truth.tables["record_expectation"]:
        if r["record_type"] == "EXPENSE" and owners[r["record_id"]] in reports and r["expected_route"]:
            first = r["expected_route"][0]
            if "L2" in first["covers"]:
                assert first["approver_id"] == g7 and first["covers"][:2] == ["L1", "L2"]
                assert len({s["approver_id"] for s in r["expected_route"]}) == len(r["expected_route"])
                checked += 1
    assert checked > 0


def test_legacy_approvals_post_usage_and_reconcile(full_gen):
    ds = full_gen.dataset
    usage = [t for t in ds["leave_balance_transaction"] if t["txn_type"] == "USAGE"]
    legacy = {r["leave_request_id"] for r in ds["leave_request"] if r["workflow_status"] == "APPROVED"}
    assert len(legacy) == 8 + 16                                  # S01 + S02
    assert {t["leave_request_id"] for t in usage} <= legacy and all(t["quantity"] < 0 for t in usage)
    sums = defaultdict(Decimal)
    for t in ds["leave_balance_transaction"]:
        sums[t["leave_balance_id"]] += t["quantity"]
    for b in ds["leave_balance"]:
        assert b["available_balance"] == sums[b["leave_balance_id"]]
    s01 = {r["affected_record_id"] for r in full_gen.truth.tables["anomaly_label"] if r["scenario_id"] == "S01"}
    assert {t["leave_request_id"] for t in usage} >= s01


def test_missing_cost_center_rows_satisfy_db_rule(gen):
    _, _, g = gen
    for c in g.dataset["expense_claim"]:
        assert c["cost_center_id"] is not None or c["exception_class"] != "NONE"


def test_oracle_accrual_matches_posted_ledger(gen):
    """The oracle re-implements accrual independently; it must reproduce every posted ACCRUAL row."""
    _, _, g = gen
    assert ledger_accrual_mismatches(g.dataset, ROOT / "config", date(2026, 10, 22)) == []


def test_receipts_consistent_after_edits(gen):
    _, _, g = gen
    receipts = {r["receipt_id"]: r for r in g.dataset["receipt"]}
    used = [ln["receipt_id"] for ln in g.dataset["expense_line"] if ln["receipt_id"]]
    assert len(used) == len(set(used)) == len(receipts)          # one line per receipt row, no orphans
    assert sorted(receipts) == [f"RCT-{i:09d}" for i in range(1, len(receipts) + 1)]
    for ln in g.dataset["expense_line"]:
        if ln["receipt_id"]:
            r = receipts[ln["receipt_id"]]
            assert (r["amount"], r["receipt_date"], r["currency"]) == \
                (ln["line_amount"], ln["expense_date"], ln["currency"])
            assert r["receipt_hash"] == receipt_hash(r["merchant"], r["receipt_date"], r["amount"], r["currency"],
                                                     r["receipt_number"])


def test_ids_follow_submission_order_after_edits(gen):
    _, _, g = gen
    for name, pk in (("leave_request", "leave_request_id"), ("expense_claim", "expense_claim_id")):
        per_year = defaultdict(list)
        for r in sorted(g.dataset[name], key=lambda r: r[pk]):
            assert int(r[pk][4:8]) == r["created_at"].year
            per_year[r[pk][4:8]].append(r)
        for rows in per_year.values():
            assert [int(r[pk][-6:]) for r in rows] == list(range(1, len(rows) + 1))
            assert [r["created_at"] for r in rows] == sorted(r["created_at"] for r in rows)


def test_labels_and_templates_never_use_accusatory_words(gen):
    _, _, g = gen
    text = " ".join(f"{r['label']} {r['expected_workflow_behaviour']} {r['injection_reason']}"
                    for r in g.truth.tables["anomaly_label"]).lower()
    catalogue = (ROOT / "config" / "exception_codes.yaml").read_text(encoding="utf-8").lower()
    for word in ("fraud", "misconduct"):
        assert word not in text and word not in catalogue


def test_catalogue_severities_follow_docs():
    doc = yaml.safe_load((ROOT / "config" / "exception_codes.yaml").read_text(encoding="utf-8"))
    codes = {c["code"]: c for c in doc["codes"]}
    assert codes["INSUFFICIENT_BALANCE"]["severity"] == "HARD"
    assert codes["DUPLICATE_RECEIPT_SELF"]["severity"] == "CORRECTABLE"
    assert codes["DUPLICATE_RECEIPT_CROSS_EMPLOYEE"]["class"] == "SUSPICIOUS_PATTERN"
    assert codes["LINE_LIMIT_EXCEEDED"]["severity"] == "INFO"
    po = doc["process_owner_decisions"]
    assert set(po["approve_when_only"]) | set(po["reject_when_any"]) | set(po["return_when_any"]) <= set(codes)


def test_planned_counts_scale_to_starter(starter_gen):
    cfg = load_config(ROOT / "config")
    p = GenParams(20261022, 40, 80, 100, date(2026, 10, 22), date(2025, 1, 1),
                  datetime(2024, 12, 31, tzinfo=timezone.utc))
    planned = planned_counts(cfg, p)
    assert (planned["S03"], planned["S02"], planned["S09"]) == (1, 2, 5)
    s = _scenarios(starter_gen)
    for sid in GROUP_A:
        assert (s[sid]["actual_count"] or 0) <= s[sid]["planned_count"], sid
