"""Stage S6 on the generated dataset (Phase 7B), at both scales, no database:
- decision timing: every decision at 17:00 UTC, more than 24 hours after its assignment, never after the as-of
  instant (S22 rule, ASM-P7B-02); S22 records still see their partner pending (OVERLAPPING_PENDING_LEAVE);
- expected_final_status_at_asof of the ground truth equals the status S6 wrote on every request;
- the year-end CARRY_FORWARD rows (BR-LBAL-04) are dated 1 January, carry at most the cap, and the snapshots
  reconcile with the ledger;
- approved_amount exists exactly on APPROVED claims; legacy approvals keep their marker and have no steps.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

AS_OF = datetime(2026, 10, 22, tzinfo=timezone.utc)


def test_decisions_follow_the_timing_rule(gen):
    _, _, g = gen
    decided = [s for s in g.dataset["approval_step"] if s["decision_at"] is not None]
    assert decided
    for s in decided:
        assert s["decision_at"].time() == time(17, 0) and s["decision_at"] <= AS_OF, s["approval_step_id"]
        assert s["decision_at"] - s["assigned_at"] > timedelta(hours=24), s["approval_step_id"]


def test_s22_partners_were_still_pending_when_the_overlap_arrived(gen):
    _, _, g = gen
    labels = [r for r in g.truth.tables["anomaly_label"] if r["scenario_id"] == "S22"]
    rex = {(r["leave_request_id"], r["exception_code"]) for r in g.dataset["request_exception"]}
    assert labels and all((r["affected_record_id"], "OVERLAPPING_PENDING_LEAVE") in rex for r in labels)


def test_ground_truth_status_at_asof_equals_the_dataset(gen):
    _, _, g = gen
    status = {("LEAVE", r["leave_request_id"]): r["workflow_status"] for r in g.dataset["leave_request"]}
    status.update({("EXPENSE", c["expense_claim_id"]): c["workflow_status"] for c in g.dataset["expense_claim"]})
    expected = {(r["record_type"], r["record_id"]): r["expected_final_status_at_asof"]
                for r in g.truth.tables["record_expectation"]}
    assert expected == status
    assert {"PENDING_APPROVAL", "APPROVED", "REJECTED"} <= set(status.values())


def test_year_end_carry_forward_rows_and_snapshots(gen):
    _, _, g = gen
    ds = g.dataset
    caps = {p["leave_policy_id"]: p["carry_forward_cap_days"] for p in ds["leave_policy"]}
    policy = {b["leave_balance_id"]: b["leave_policy_id"] for b in ds["leave_balance"]}
    carried: dict[str, Decimal] = defaultdict(Decimal)
    for t in ds["leave_balance_transaction"]:
        if t["txn_type"] in ("CARRY_FORWARD", "CARRY_FORWARD_EXPIRY"):
            assert t["txn_date"] == date(2026, 1, 1) and t["leave_balance_id"].endswith("-2026")
            carried[t["leave_balance_id"]] += t["quantity"]
    assert carried, "year-end rows exist (AMB-P5-02 replaced)"
    assert all(q <= caps[policy[b]] for b, q in carried.items())
    sums: dict[str, Decimal] = defaultdict(Decimal)
    for t in ds["leave_balance_transaction"]:
        sums[t["leave_balance_id"]] += t["quantity"]
    assert all(b["available_balance"] == sums[b["leave_balance_id"]] for b in ds["leave_balance"])


def test_approved_amount_and_legacy_markers(gen):
    _, _, g = gen
    ds = g.dataset
    assert all((c["approved_amount"] is not None) == (c["workflow_status"] == "APPROVED")
               for c in ds["expense_claim"])
    legacy = {r["leave_request_id"] for r in ds["leave_request"] if r["decision_reason_code"] == "LEGACY_APPROVAL"}
    assert legacy and not legacy & {s["leave_request_id"] for s in ds["approval_step"]}
    assert all(r["workflow_status"] == "APPROVED" for r in ds["leave_request"] if r["leave_request_id"] in legacy)


# --- stages S7-S8 (Phase 8B-1) -------------------------------------------------------------------------------------
def test_one_reimbursement_per_claim_approved_at_asof_with_the_approved_amount(gen):
    _, _, g = gen
    ds = g.dataset
    approved = {c["expense_claim_id"]: c for c in ds["expense_claim"] if c["workflow_status"] == "APPROVED"}
    by_claim = defaultdict(list)
    for b in ds["reimbursement"]:
        by_claim[b["expense_claim_id"]].append(b)
    assert set(by_claim) == set(approved) and all(len(v) == 1 for v in by_claim.values())
    steps = {s["approval_step_id"]: s for s in ds["approval_step"]}
    for cid, (b,) in by_claim.items():
        c = approved[cid]
        assert (b["approved_amount"], b["currency"], b["employee_id"]) == \
            (c["approved_amount"], c["currency"], c["employee_id"])
        assert b["created_at"] == steps[b["approval_completion_step_id"]]["decision_at"] or \
            steps[b["approval_completion_step_id"]]["step_status"] == "APPROVED"
        assert b["reimbursement_status"] in ("ELIGIBLE", "COMPLETED", "FAILED")
        assert (b["completed_at"] is not None) == (b["reimbursement_status"] == "COMPLETED")
        assert b["completed_at"] is None or b["created_at"] < b["completed_at"] <= AS_OF


def test_s13_and_s25_rows_equal_their_labels(gen):
    _, _, g = gen
    ds, labels = g.dataset, g.truth.tables["anomaly_label"]
    owner = {b["reimbursement_id"]: b["expense_claim_id"] for b in ds["reimbursement"]}
    blocked = {(a["expense_claim_id"], a["reason_code"]) for a in ds["reimbursement_attempt"] if a["outcome"] == "BLOCKED"}
    assert blocked == {(r["affected_record_id"], "DUPLICATE_REIMBURSEMENT") for r in labels if r["scenario_id"] == "S13"}
    failed = {owner[f["entity_id"]] for f in ds["processing_failure"]}
    assert failed == {r["affected_record_id"] for r in labels if r["scenario_id"] == "S25"}
    assert all(f["operation"] == "PROCESS_PAYMENT" and f["entity_type"] == "reimbursement"
               for f in ds["processing_failure"])


def test_payment_runs_completed_post_actual_and_audit_rows_follow_time(gen):
    _, _, g = gen
    ds = g.dataset
    actual = defaultdict(Decimal)
    for t in ds["cost_center_transaction"]:
        if t["txn_type"] == "ACTUAL":
            actual[t["expense_claim_id"]] += t["amount"]
    done = {b["expense_claim_id"]: b["approved_amount"] for b in ds["reimbursement"]
            if b["reimbursement_status"] == "COMPLETED"}
    assert dict(actual) == done                                   # BR-BUD-05
    ids = [e["event_id"] for e in sorted(ds["audit_event"], key=lambda e: e["event_id"])]
    times = [e["occurred_at"] for e in sorted(ds["audit_event"], key=lambda e: e["event_id"])]
    assert ids[0] == "AUD-000000001" and times == sorted(times) and max(times) <= AS_OF
    transitions = [e for e in ds["audit_event"] if e["entity_type"] in ("leave_request", "expense_claim")
                   and e["previous_state"] != e["new_state"]]
    assert len(transitions) == len(ds["request_status_event"])    # one audit row per request transition
