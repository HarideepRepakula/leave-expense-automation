"""Reimbursements and audit events on the in-memory stores (Phase 8; docs/05 section 8; docs/06 sections 4, 5.2, 7,
8.2 step 6, 8.4, 8.5). The expense world of tests/unit/test_approval_decisions.py: E1 (requester) reports to E2;
claim C1 has one MEALS line of 7,000 INR capped at the 6,230 per-line limit, so approved_amount = 6,230.00 and the
reservation holds 7,000.00."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from src.services.approval_service import IdempotencyConflict, cancel_request, decide_escalated, decide_step, \
    reassign_departed
from src.services.lifecycle import REIMBURSEMENT_TRANSITIONS, IllegalTransition, check_reimbursement_transition
from src.services.reimbursement_service import cancel_reimbursement, create_reimbursement, creation_guard, \
    settle_payment, start_payment
from tests.unit import leave_world as lw
from tests.unit import test_expense_validation as xw
from tests.unit.test_approval_decisions import CEO, HEAD, MGR, at, decide, expense_store, leave_store, two_step

D = Decimal
CORR = uuid.UUID(int=8)
APPROVED_AT = at(2025, 6, 4, 17)


def approved_c1():
    s = expense_store()
    xw.submit(s, xw.claim("C1", "E1", [("MEALS", date(2025, 5, 20), "7000.00", "R4")]))
    res = decide_step(s, "C1", "APR-C1-01", "E2", "APPROVE", APPROVED_AT, CORR)
    assert res.new_status == "APPROVED"
    return s


def test_final_approval_creates_one_eligible_reimbursement_in_the_same_operation():
    s = approved_c1()
    assert list(s.reimbursements) == ["RMB-2025-000001"]                  # year of the final approval (AM-A6)
    b = s.reimbursements["RMB-2025-000001"]
    assert (b["expense_claim_id"], b["employee_id"], b["approved_amount"], b["currency"], b["eligibility_status"],
            b["reimbursement_status"], b["approval_completion_step_id"], b["created_at"]) == \
        ("C1", "E1", D("6230.00"), "INR", "ELIGIBLE", "ELIGIBLE", "APR-C1-01", APPROVED_AT)
    assert [(a["actor_type"], a["attempted_action"], a["outcome"], a["correlation_id"])
            for a in s.reimbursement_attempts] == [("SYSTEM", "CREATE", "ACCEPTED", CORR)]
    created = [e for e in s.audit_events if e["entity_type"] == "reimbursement"]
    assert [(e["previous_state"], e["new_state"], e["correlation_id"]) for e in created] == [(None, "ELIGIBLE", CORR)]


def test_no_reimbursement_unless_approved():
    s = expense_store()
    for cid, action, amount in (("C2", "REJECT", "1000.00"), ("C3", "RETURN", "1100.00"), ("C4", None, "1200.00")):
        xw.submit(s, xw.claim(cid, "E1", [("MEALS", date(2025, 5, 21), amount, None)]))   # no duplicate pattern
        if action:
            decide_step(s, cid, f"APR-{cid}-01", "E2", action, APPROVED_AT, CORR)
    assert {c: s.claims[c]["workflow_status"] for c in ("C2", "C3", "C4")} == \
        {"C2": "REJECTED", "C3": "RETURNED_FOR_CORRECTION", "C4": "PENDING_APPROVAL"}
    assert s.reimbursements == {} and s.reimbursement_attempts == []
    res = create_reimbursement(s, "C4", "E2", at(2025, 6, 5), CORR)          # manual path on a pending claim
    assert (res.outcome, res.reason_code, res.reimbursement_id) == ("BLOCKED", "CLAIM_NOT_APPROVED", None)
    assert s.reimbursements == {} and len(s.reimbursement_attempts) == 1


def test_manual_create_guards_replay_and_conflict():
    s = approved_c1()
    dup = create_reimbursement(s, "C1", "E2", at(2025, 6, 5), CORR)
    assert (dup.outcome, dup.reason_code) == ("BLOCKED", "DUPLICATE_REIMBURSEMENT")
    attempts = len(s.reimbursement_attempts)
    replay = create_reimbursement(s, "C1", "E2", at(2025, 6, 6), CORR)       # same derived key and body
    assert replay.replayed and len(s.reimbursement_attempts) == attempts
    assert s.audit_events[-1]["reason_code"] == "IDEMPOTENT_REPLAY"
    with pytest.raises(IdempotencyConflict):
        create_reimbursement(s, "C1", "E2", at(2025, 6, 6), CORR, amount=D("1.00"))
    cancel_reimbursement(s, "RMB-2025-000001", "E2", "ADMIN_CORRECTION", at(2025, 6, 7), CORR)
    assert s.active_reimbursements("C1") == []
    wrong = create_reimbursement(s, "C1", "E2", at(2025, 6, 8), CORR, amount=D("7000.00"), idempotency_key="a" * 64)
    assert wrong.reason_code == "AMOUNT_MISMATCH"
    wrong = create_reimbursement(s, "C1", "E2", at(2025, 6, 8), CORR, currency="GBP", idempotency_key="b" * 64)
    assert wrong.reason_code == "AMOUNT_MISMATCH"
    ok = create_reimbursement(s, "C1", "E2", at(2025, 6, 8), CORR, amount=D("6230.00"), idempotency_key="c" * 64)
    assert (ok.outcome, ok.reimbursement_id) == ("ACCEPTED", "RMB-2025-000002")
    assert s.reimbursements["RMB-2025-000002"]["approval_completion_step_id"] == "APR-C1-01"
    assert [b["reimbursement_status"] for b in s.reimbursements.values()] == ["CANCELLED", "ELIGIBLE"]


def test_zero_approved_amount_is_not_eligible():
    claim = {"workflow_status": "APPROVED", "approved_amount": D("0.00"), "currency": "INR"}
    assert creation_guard(claim, []) == "ZERO_APPROVED_AMOUNT"
    assert creation_guard({**claim, "workflow_status": "PENDING_APPROVAL"}, []) == "CLAIM_NOT_APPROVED"


def test_payment_fails_once_then_completes_with_actual_and_release():
    s = approved_c1()
    rmb = "RMB-2025-000001"
    first = start_payment(s, rmb, at(2025, 6, 9), CORR)
    assert (first.action, first.outcome, s.reimbursements[rmb]["reimbursement_status"]) == \
        ("PROCESS", "ACCEPTED", "PROCESSING")
    again = start_payment(s, rmb, at(2025, 6, 9), CORR, attempt_no=1)       # the same run again: replay
    assert again.replayed
    failed = settle_payment(s, rmb, at(2025, 6, 9, 10), CORR, succeeded=False)
    assert (failed.outcome, failed.reason_code, s.reimbursements[rmb]["reimbursement_status"]) == \
        ("PAYMENT_FAILED", "PAYMENT_FAILED", "FAILED")
    assert [(f["entity_id"], f["operation"], f["error_code"], f["resolution_status"]) for f in s.failures] == \
        [(rmb, "PROCESS_PAYMENT", "PAYMENT_FAILED", "OPEN")]
    assert s.claims["C1"]["workflow_status"] == "APPROVED"                  # a technical failure, not a workflow state
    retry = start_payment(s, rmb, at(2025, 6, 11), CORR)
    assert retry.action == "RETRY"
    done = settle_payment(s, rmb, at(2025, 6, 11, 10), CORR, succeeded=True, payment_reference="PAY-1")
    b = s.reimbursements[rmb]
    assert (done.outcome, b["reimbursement_status"], b["completed_at"], b["payment_reference"]) == \
        ("COMPLETED", "COMPLETED", at(2025, 6, 11, 10), "PAY-1")
    assert [(p["txn_type"], p["amount"]) for p in s.budget_ledger if p["expense_claim_id"] == "C1"] == \
        [("RESERVATION", D("7000.00")), ("ACTUAL", D("6230.00")), ("RELEASE", D("770.00"))]
    assert [(a["attempted_action"], a["outcome"]) for a in s.reimbursement_attempts] == \
        [("CREATE", "ACCEPTED"), ("PROCESS", "ACCEPTED"), ("PROCESS", "PAYMENT_FAILED"), ("RETRY", "ACCEPTED"),
         ("RETRY", "COMPLETED")]
    with pytest.raises(IllegalTransition):
        start_payment(s, rmb, at(2025, 6, 12), CORR)                        # COMPLETED is terminal
    with pytest.raises(IllegalTransition):
        cancel_reimbursement(s, rmb, "E2", "ADMIN_CORRECTION", at(2025, 6, 12), CORR)


def test_cancel_needs_a_listed_reason():
    s = approved_c1()
    with pytest.raises(ValueError):
        cancel_reimbursement(s, "RMB-2025-000001", "E2", "BECAUSE", at(2025, 6, 7), CORR)
    res = cancel_reimbursement(s, "RMB-2025-000001", "E2", "EMPLOYEE_REQUEST", at(2025, 6, 7), CORR)
    assert (res.attempts[0]["attempted_action"], res.attempts[0]["reason_code"]) == ("CANCEL", "EMPLOYEE_REQUEST")
    with pytest.raises(IllegalTransition):
        cancel_reimbursement(s, "RMB-2025-000001", "E2", "EMPLOYEE_REQUEST", at(2025, 6, 8), CORR)


def test_reimbursement_transition_table_is_docs_06_section_4():
    assert set(REIMBURSEMENT_TRANSITIONS) == {("ELIGIBLE", "PROCESSING"), ("PROCESSING", "COMPLETED"),
                                              ("PROCESSING", "FAILED"), ("FAILED", "PROCESSING"),
                                              ("ELIGIBLE", "CANCELLED"), ("FAILED", "CANCELLED")}
    for bad in (("ELIGIBLE", "COMPLETED"), ("COMPLETED", "PROCESSING"), ("CANCELLED", "ELIGIBLE"), ("X", "Y")):
        with pytest.raises(IllegalTransition):
            check_reimbursement_transition(*bad)


# --- audit_event (docs/06 section 7) --------------------------------------------------------------------------------
def rows_of(s, entity_id):
    return [(e["entity_type"], e["previous_state"], e["new_state"], e["actor_id"], e["reason_code"])
            for e in s.audit_events if e["entity_id"] == entity_id]


def test_audit_rows_for_submission_blocked_and_accepted_decisions():
    s = expense_store()
    xw.submit(s, xw.claim("C1", "E1", [("MEALS", date(2025, 5, 20), "7000.00", "R4")]))
    decide_step(s, "C1", "APR-C1-01", "E1", "APPROVE", at(2025, 6, 3, 17), CORR)     # self-approval, blocked
    decide_step(s, "C1", "APR-C1-01", "E2", "APPROVE", APPROVED_AT, CORR)
    assert rows_of(s, "C1") == [
        ("expense_claim", "DRAFT", "SUBMITTED", "E1", None),
        ("expense_claim", "SUBMITTED", "VALIDATING", "SYSTEM", None),
        ("expense_claim", "VALIDATING", "PENDING_APPROVAL", "SYSTEM", None),
        ("expense_claim", "PENDING_APPROVAL", "APPROVED", "E2", None)]
    assert rows_of(s, "APR-C1-01") == [("approval_step", "PENDING", "PENDING", "E1", "SELF_APPROVAL"),
                                       ("approval_step", "PENDING", "APPROVED", "E2", None)]
    step_row = next(e for e in s.audit_events if e["entity_id"] == "APR-C1-01" and e["new_state"] == "APPROVED")
    assert (step_row["rule_id"], step_row["policy_version_id"], step_row["calculated_values"]["outcome"]) == \
        ("RULE-E-001", "XPOL-MEALS-IN-V1", "ACCEPTED")
    outcome = next(e for e in s.audit_events if e["new_state"] == "PENDING_APPROVAL")
    assert outcome["calculated_values"]["amount_usd"] == "82.84"           # the submission's calculated values
    # one audit row per request transition, the same count as request_status_event
    assert len([e for e in s.audit_events if e["entity_type"] == "expense_claim" and e["previous_state"] !=
                e["new_state"]]) == len([e for e in s.status_events if e["request_id"] == "C1"])


def test_audit_rows_for_skipped_steps_replay_and_reassignment():
    s = leave_store()
    rid = two_step(s)
    decide(s, rid, 1, MGR, "REJECT")                                 # step 2 SKIPPED by the system
    assert rows_of(s, f"APR-{rid}-02") == [("approval_step", "PENDING", "SKIPPED", "SYSTEM", None)]
    decide(s, rid, 1, MGR, "REJECT")                                 # replay of the same call
    assert rows_of(s, f"APR-{rid}-01")[-1] == ("approval_step", None, None, MGR, "IDEMPOTENT_REPLAY")
    s = leave_store()
    rid = two_step(s)
    decide(s, rid, 1, MGR)
    org = s.router().org
    org.employees[HEAD] = {**org.employees[HEAD], "employment_end": date(2025, 6, 5)}
    reassign_departed(s, rid, f"APR-{rid}-02", at(2025, 6, 6, 0), CORR)
    row = s.audit_events[-1]
    assert (row["entity_id"], row["previous_state"], row["new_state"], row["actor_id"], row["reason_code"],
            row["calculated_values"]) == (f"APR-{rid}-02", "PENDING", "PENDING", "SYSTEM",
                                          "APPROVER_EMPLOYMENT_ENDED", {"from": HEAD, "to": CEO})


def test_process_owner_decision_has_one_audit_row_per_transition():
    s = leave_store()
    lw.submit(s, lw.req("LVE-2025-000020", lw.E1, lw.ANNUAL_IN, date(2025, 7, 7), date(2025, 7, 7)), at(2025, 6, 2))
    lw.submit(s, lw.req("LVE-2025-000021", lw.E1, lw.SICK, date(2025, 7, 7), date(2025, 7, 7)), at(2025, 6, 3))
    rid = "LVE-2025-000021"                                          # escalated (OVERLAPPING_PENDING_LEAVE)
    decide_escalated(s, rid, MGR, "APPROVE", at(2025, 6, 5, 17), CORR)          # not a process owner: blocked
    decide_escalated(s, rid, CEO, "APPROVE", at(2025, 6, 5, 17), CORR)
    assert rows_of(s, rid)[-2:] == [("leave_request", "ESCALATED_FOR_REVIEW", "ESCALATED_FOR_REVIEW", MGR,
                                     "UNAUTHORIZED_APPROVER"),
                                    ("leave_request", "ESCALATED_FOR_REVIEW", "PENDING_APPROVAL", CEO,
                                     "PROCESS_OWNER_ACCEPTED")]


# --- cancellation by the requester (ASM-040) ----------------------------------------------------------------------
def test_requester_cancels_a_pending_claim_steps_cancelled_and_reservation_released():
    s = expense_store()
    xw.submit(s, xw.claim("C5", "E1", [("MEALS", date(2025, 5, 22), "1300.00", None)]))
    with pytest.raises(IllegalTransition):
        cancel_request(s, "C5", "E2", at(2025, 6, 3), CORR)                  # only the requester
    res = cancel_request(s, "C5", "E1", at(2025, 6, 3), CORR)
    assert (res.new_status, s.claims["C5"]["decision_reason_code"]) == ("CANCELLED", "REQUESTER_CANCELLED")
    assert [(st["step_status"]) for st in s.steps["C5"]] == ["CANCELLED"]
    assert [e["event_type"] for e in s.approval_events if e["approval_step_id"] == "APR-C5-01"] == \
        ["ASSIGNED", "CANCELLED"]
    assert [(p["txn_type"], p["amount"], p["reason_code"]) for p in s.budget_ledger
            if p["expense_claim_id"] == "C5"] == [("RESERVATION", D("1300.00"), None),
                                                  ("RELEASE", D("1300.00"), "CANCELLED")]
    assert s.attempts == [] and s.idempotency_records == {}                 # not an approval action
    assert rows_of(s, "C5")[-1] == ("expense_claim", "PENDING_APPROVAL", "CANCELLED", "E1", "REQUESTER_CANCELLED")
    assert rows_of(s, "APR-C5-01") == [("approval_step", "PENDING", "CANCELLED", "SYSTEM", None)]
    with pytest.raises(IllegalTransition):
        cancel_request(s, "C5", "E1", at(2025, 6, 4), CORR)                  # CANCELLED is terminal
    assert decide_step(s, "C5", "APR-C5-01", "E2", "APPROVE", at(2025, 6, 4, 17), CORR).reason_code == \
        "STEP_NOT_PENDING"
    assert s.reimbursements == {}
