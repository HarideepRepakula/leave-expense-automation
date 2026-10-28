"""Decisions on approval steps, process-owner decisions, resubmission, idempotency and decision timing (Phase 7B;
docs/05 5.5 and 9.4; docs/06 2-3, 5.1, 8.2, 8.3). No database: the in-memory stores, the organisation of
tests/unit/test_approval_routing.py (CEO <- HEAD <- MGR <- E1; CTL_IN the IN finance controller) and the leave and
expense worlds of tests/unit."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.services.approval_service import DecisionRefused, IdempotencyConflict, IdempotentReplay, \
    ProcessOwnerPolicy, decide_escalated, decide_step, reassign_departed, step_key
from src.services.lifecycle import IllegalTransition
from src.services.workflow_simulation import DecisionTiming
from tests.unit import leave_world as lw
from tests.unit import test_expense_validation as xw
from tests.unit.test_approval_routing import CEO, CTL_IN, DEV, HEAD, MGR, emp, leave_router, router

D = Decimal
CORR = uuid.UUID(int=7)
PO_ROLES = {CEO: {"PROCESS_OWNER"}}


def at(y, m, d, h=9):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


def leave_store(roles=None):
    rows, balances = lw.ledger_and_balances()
    return lw.InMemoryLeaveStore(lw.EMPLOYEES, lw.POLICIES, lw.CAL, rows, balances, leave_router(), roles or PO_ROLES)


def two_step(s, rid="LVE-2025-000010", when=at(2025, 6, 2)):
    """E1, 6 ANNUAL days in July: RULE-L-002 -> L1 MGR, L2 HEAD."""
    res = lw.submit(s, lw.req(rid, lw.E1, lw.ANNUAL_IN, date(2025, 7, 7), date(2025, 7, 14)), when)
    assert res.status == "PENDING_APPROVAL" and [st["approver_employee_id"] for st in s.steps[rid]] == [MGR, HEAD]
    return rid


def decide(s, rid, n, actor, action="APPROVE", when=at(2025, 6, 4, 17), **kw):
    return decide_step(s, rid, f"APR-{rid}-{n:02d}", actor, action, when, CORR, **kw)


# --- guards (docs/05 5.5) -----------------------------------------------------------------------------------------
def test_guards_block_and_write_an_attempt_without_changing_anything():
    s = leave_store()
    rid = two_step(s)
    assert decide(s, rid, 1, lw.E1).reason_code == "SELF_APPROVAL"
    assert decide(s, rid, 1, DEV).reason_code == "UNAUTHORIZED_APPROVER"
    assert decide(s, rid, 2, HEAD).reason_code == "LEVEL_SKIPPED"           # step 1 still pending
    assert [a["outcome"] for a in s.attempts] == ["BLOCKED"] * 3
    assert all(st["step_status"] == "PENDING" for st in s.steps[rid])
    assert s.requests[rid]["workflow_status"] == "PENDING_APPROVAL"
    assert len(s.idempotency_records) == 3                       # every call completes its key


def test_a_higher_level_in_the_chain_may_act_and_the_next_step_is_assigned():
    s = leave_store()
    rid = two_step(s)
    res = decide(s, rid, 1, HEAD)                                # HEAD is above MGR (docs/05 5.1)
    assert res.outcome == "ACCEPTED"
    s1, s2 = s.steps[rid]
    assert (s1["step_status"], s1["decision_at"], s2["assigned_at"]) == \
        ("APPROVED", at(2025, 6, 4, 17), at(2025, 6, 4, 17))
    assert [(e["approval_step_id"][-2:], e["event_type"], e["actor_id"]) for e in s.approval_events[-2:]] == \
        [("01", "APPROVED", HEAD), ("02", "ASSIGNED", None)]
    assert s.requests[rid]["workflow_status"] == "PENDING_APPROVAL"


def test_duplicate_action_replay_conflict_and_step_not_pending():
    s = leave_store()
    rid = two_step(s)
    first = decide(s, rid, 1, MGR)
    attempts = len(s.attempts)
    replay = decide(s, rid, 1, MGR)                              # same derived key, same body
    assert replay.replayed and len(s.attempts) == attempts
    with pytest.raises(IdempotencyConflict):
        decide(s, rid, 1, MGR, comment="changed")                # same key, different body
    dup = decide(s, rid, 1, MGR, idempotency_key="f" * 64)       # new key, same step, actor and action
    assert (first.outcome, dup.reason_code) == ("ACCEPTED", "DUPLICATE_ACTION")
    assert decide(s, rid, 1, HEAD).reason_code == "STEP_NOT_PENDING"
    assert first.idempotency_key == step_key(MGR, f"APR-{rid}-01", "APPROVE", 1)


def test_expired_rule_blocks():
    s = leave_store()
    rid = two_step(s)
    rules = s.router().rules = list(s.router().rules)            # own list: RULES is shared by other tests
    i = next(i for i, r in enumerate(rules) if r["approval_rule_id"] == "RULE-L-002")
    rules[i] = {**rules[i], "effective_end": date(2025, 6, 3)}
    assert decide(s, rid, 1, MGR).reason_code == "EXPIRED_RULE"


# --- outcomes -----------------------------------------------------------------------------------------------------
def test_final_approval_posts_usage_dated_at_approval():
    s = leave_store()
    rid = two_step(s)
    decide(s, rid, 1, MGR)
    res = decide(s, rid, 2, HEAD, when=at(2025, 6, 6, 17))
    assert res.new_status == "APPROVED" and s.requests[rid]["workflow_status"] == "APPROVED"
    usage = [t for t in s.ledger[(lw.E1, lw.ANNUAL_IN)] if t["txn_type"] == "USAGE"]
    assert [(t["quantity"], t["txn_date"], t["leave_request_id"]) for t in usage] == \
        [(D("-6.0"), date(2025, 6, 6), rid)]
    assert [(e["previous_status"], e["new_status"], e["actor_id"]) for e in s.status_events[-1:]] == \
        [("PENDING_APPROVAL", "APPROVED", HEAD)]


def test_reject_skips_later_steps_and_return_cancels_them():
    s = leave_store()
    rid = two_step(s)
    res = decide(s, rid, 1, MGR, "REJECT", reason_code="TEAM_CAPACITY")
    assert [st["step_status"] for st in s.steps[rid]] == ["REJECTED", "SKIPPED"]
    assert (s.requests[rid]["workflow_status"], s.requests[rid]["decision_reason_code"]) == \
        ("REJECTED", "TEAM_CAPACITY")
    assert res.leave_postings == [] and s.steps[rid][1]["decision_at"] is None
    rid2 = two_step(s, "LVE-2025-000011", at(2025, 6, 9))
    decide(s, rid2, 1, MGR, "RETURN", when=at(2025, 6, 10, 17))
    assert [st["step_status"] for st in s.steps[rid2]] == ["CANCELLED", "CANCELLED"]
    assert (s.requests[rid2]["workflow_status"], s.requests[rid2]["decision_reason_code"]) == \
        ("RETURNED_FOR_CORRECTION", "APPROVER_RETURNED")
    assert [e["event_type"] for e in s.approval_events[-2:]] == ["RETURNED", "CANCELLED"]


# --- resubmission (docs/06 8.3) -----------------------------------------------------------------------------------
def test_resubmission_opens_round_two_keeps_ids_and_history():
    s = leave_store()
    rid = two_step(s)
    decide(s, rid, 1, MGR, "RETURN")
    events_before = len(s.status_events)
    with pytest.raises(IllegalTransition):                       # only the requester resubmits
        lw.submit_leave(s, rid, lw.CATALOGUE, at(2025, 6, 5), MGR, CORR)
    res = lw.submit_leave(s, rid, lw.CATALOGUE, at(2025, 6, 5), lw.E1, CORR,
                          changes={"start_date": date(2025, 7, 8), "end_date": date(2025, 7, 9)})
    r = s.requests[rid]
    assert (res.submission_round, r["current_round"], r["leave_request_id"], r["first_submitted_at"]) == \
        (2, 2, rid, at(2025, 6, 2))
    assert (r["start_date"], r["requested_quantity"], res.status) == (date(2025, 7, 8), D("2.0"), "PENDING_APPROVAL")
    assert [(e["previous_status"], e["new_status"], e["submission_round"]) for e in s.status_events[events_before:]] \
        == [("RETURNED_FOR_CORRECTION", "SUBMITTED", 2), ("SUBMITTED", "VALIDATING", 2),
            ("VALIDATING", "PENDING_APPROVAL", 2)]
    assert [(st["sequence_no"], st["submission_round"], st["step_status"]) for st in s.steps[rid]] == \
        [(1, 1, "CANCELLED"), (2, 1, "CANCELLED"), (3, 2, "PENDING")]      # sequence continues (AM-A5)
    with pytest.raises(IllegalTransition):                       # no longer RETURNED
        lw.submit_leave(s, rid, lw.CATALOGUE, at(2025, 6, 6), lw.E1, CORR, idempotency_key="a" * 64)
    decide(s, rid, 3, MGR, "RETURN", when=at(2025, 6, 9, 17))
    with pytest.raises(IdempotentReplay):                        # the round-2 key again
        lw.submit_leave(s, rid, lw.CATALOGUE, at(2025, 6, 10), lw.E1, CORR,
                        idempotency_key=res.idempotency["idempotency_key"])
    s.requests[rid]["current_round"] = 3
    with pytest.raises(IllegalTransition):                       # maximum 3 rounds (ASM-025)
        lw.submit_leave(s, rid, lw.CATALOGUE, at(2025, 6, 10), lw.E1, CORR)


def expense_store(roles=None):
    r = router(extra_emps=[emp("E1", "E2"), emp("E2", None, grade="G6")])
    return xw.InMemoryExpenseStore(xw.EMPLOYEES, xw.POLICIES, xw.FX, xw.CCS, xw.BUDGETS, xw.RECEIPTS, [], xw.PARAMS,
                                   r, roles or PO_ROLES)


def test_expense_approval_stores_the_approved_amount_and_return_releases_then_resubmits():
    s = expense_store()
    xw.submit(s, xw.claim("C1", "E1", [("MEALS", date(2025, 5, 20), "7000.00", "R4")]))   # capped at 6230
    res = decide_step(s, "C1", "APR-C1-01", "E2", "APPROVE", at(2025, 6, 4, 17), CORR)
    assert res.new_status == "APPROVED" and s.claims["C1"]["approved_amount"] == D("6230.00")
    xw.submit(s, xw.claim("C2", "E1", [("MEALS", date(2025, 5, 21), "1000.00", None)]))
    decide_step(s, "C2", "APR-C2-01", "E2", "RETURN", at(2025, 6, 4, 17), CORR)
    assert [(p["txn_type"], p["amount"]) for p in s.budget_ledger if p["expense_claim_id"] == "C2"] == \
        [("RESERVATION", D("1000.00")), ("RELEASE", D("1000.00"))]
    new = [{"category": "MEALS", "merchant_description": "Lunch", "expense_date": date(2025, 5, 21),
            "quantity": None, "unit_amount": None, "line_amount": D("900.00"), "currency": "INR", "receipt_id": None}]
    again = xw.submit_expense(s, "C2", lw.CATALOGUE, at(2025, 6, 5), "E1", CORR, new_lines=new)
    assert (again.status, again.submission_round, s.claims["C2"]["total_amount"]) == \
        ("PENDING_APPROVAL", 2, D("900.00"))
    assert [(ln["line_number"], ln["submission_round"]) for ln in s.lines["C2"]] == [(1, 1), (2, 2)]
    assert [p["txn_type"] for p in s.budget_ledger if p["expense_claim_id"] == "C2"] == \
        ["RESERVATION", "RELEASE", "RESERVATION"]


# --- process owner (docs/05 9.4) ------------------------------------------------------------------------------------
def test_process_owner_sends_on_and_others_are_blocked():
    s = leave_store()
    lw.submit(s, lw.req("LVE-2025-000020", lw.E1, lw.ANNUAL_IN, date(2025, 7, 7), date(2025, 7, 7)), at(2025, 6, 2))
    lw.submit(s, lw.req("LVE-2025-000021", lw.E1, lw.SICK, date(2025, 7, 7), date(2025, 7, 7)), at(2025, 6, 3))
    rid = "LVE-2025-000021"                                      # OVERLAPPING_PENDING_LEAVE -> escalated
    assert s.requests[rid]["workflow_status"] == "ESCALATED_FOR_REVIEW"
    assert decide_escalated(s, rid, MGR, "APPROVE", at(2025, 6, 5, 17), CORR).reason_code == "UNAUTHORIZED_APPROVER"
    assert decide_escalated(s, "LVE-2025-000020", CEO, "APPROVE", at(2025, 6, 5, 17), CORR).reason_code == \
        "STEP_NOT_PENDING"
    res = decide_escalated(s, rid, CEO, "APPROVE", at(2025, 6, 5, 17), CORR)
    assert (res.outcome, res.attempt["approval_step_id"], s.requests[rid]["workflow_status"]) == \
        ("ACCEPTED", None, "PENDING_APPROVAL")
    assert [(st["approver_employee_id"], st["assigned_at"]) for st in s.steps[rid]] == [(MGR, at(2025, 6, 5, 17))]
    assert s.status_events[-1]["reason_code"] == "PROCESS_OWNER_ACCEPTED"
    assert s.requests[rid]["decision_reason_code"] is None
    own = leave_store({lw.E1: {"PROCESS_OWNER"}})
    lw.submit(own, lw.req("LVE-2025-000030", lw.E1, lw.ANNUAL_IN, date(2025, 7, 7), date(2025, 7, 7)), at(2025, 6, 2))
    lw.submit(own, lw.req("LVE-2025-000031", lw.E1, lw.SICK, date(2025, 7, 7), date(2025, 7, 7)), at(2025, 6, 3))
    assert decide_escalated(own, "LVE-2025-000031", lw.E1, "REJECT", at(2025, 6, 5, 17), CORR).reason_code == \
        "SELF_APPROVAL"


def test_no_valid_path_cannot_be_sent_on():
    rows, balances = lw.ledger_and_balances()
    s = lw.InMemoryLeaveStore(lw.EMPLOYEES, lw.POLICIES, lw.CAL, rows, balances, leave_router(manager_of_e5=None),
                              PO_ROLES)
    lw.submit(s, lw.req("LVE-2025-000040", lw.E5, lw.SICK, date(2025, 3, 10), date(2025, 3, 10)), at(2025, 3, 3))
    with pytest.raises(DecisionRefused):
        decide_escalated(s, "LVE-2025-000040", CEO, "APPROVE", at(2025, 3, 5, 17), CORR)
    assert s.attempts == [] and s.requests["LVE-2025-000040"]["workflow_status"] == "ESCALATED_FOR_REVIEW"


def test_budget_override_by_the_finance_controller_and_release_on_reject():
    s = expense_store()
    when = at(2026, 6, 2)
    xw.submit(s, xw.claim("B1", "E1", [("MEALS", date(2026, 5, 20), "6000.00", "R4")], created=when), when)
    assert s.claims["B1"]["workflow_status"] == "ESCALATED_FOR_REVIEW"          # budget 5,000 (BUDGET_EXCEEDED)
    res = decide_escalated(s, "B1", CTL_IN, "APPROVE", at(2026, 6, 4, 17), CORR)    # L4 may decide (BR-BUD-06)
    assert res.outcome == "ACCEPTED" and s.status_events[-1]["reason_code"] == "BUDGET_OVERRIDE"
    assert [(p["txn_type"], p["amount"], p["reason_code"]) for p in s.budget_ledger if p["txn_type"] == "OVERRIDE"] \
        == [("OVERRIDE", D("6000.00"), "BUDGET_OVERRIDE")]
    xw.submit(s, xw.claim("B2", "E1", [("MEALS", date(2026, 5, 21), "500.00", None)], created=when), when)
    assert s.claims["B2"]["workflow_status"] == "ESCALATED_FOR_REVIEW"
    assert decide_escalated(s, "B2", "E2", "REJECT", at(2026, 6, 4, 17), CORR).reason_code == \
        "UNAUTHORIZED_APPROVER"                                  # neither process owner nor the L4
    decide_escalated(s, "B2", CEO, "REJECT", at(2026, 6, 4, 17), CORR)
    assert [p["txn_type"] for p in s.budget_ledger if p["expense_claim_id"] == "B2"] == ["RESERVATION", "RELEASE"]


# --- reassignment when the approver has left (AMB-P7B-11) -----------------------------------------------------------
def test_a_step_whose_approver_has_left_is_reassigned_to_the_next_person_up():
    s = leave_store()
    rid = two_step(s)
    decide(s, rid, 1, MGR)                                       # step 2 assigned to HEAD at 4 June 17:00
    org = s.router().org
    org.employees[HEAD] = {**org.employees[HEAD], "employment_end": date(2025, 6, 5)}
    sid = f"APR-{rid}-02"
    assert reassign_departed(s, rid, sid, at(2025, 6, 5, 17), CORR) is None      # still employed that day
    assert reassign_departed(s, rid, sid, at(2025, 6, 6, 0), CORR) == CEO
    step = s.steps[rid][1]
    assert (step["approver_employee_id"], step["assigned_at"], step["step_status"]) ==         (CEO, at(2025, 6, 4, 17), "PENDING")                     # assignment time kept, nobody decided
    events = [(e["event_type"], e["comment"]) for e in s.approval_events if e["approval_step_id"] == sid]
    assert events == [("ASSIGNED", None), ("REASSIGNED", f"{HEAD} -> {CEO}")]    # history appended, not rewritten
    assert reassign_departed(s, rid, sid, at(2025, 6, 9, 0), CORR) is None       # CEO is employed: no change
    assert decide(s, rid, 2, HEAD, when=at(2025, 6, 9, 17)).reason_code == "UNAUTHORIZED_APPROVER"
    assert decide(s, rid, 2, CEO, when=at(2025, 6, 9, 17)).outcome == "ACCEPTED"
    assert s.requests[rid]["workflow_status"] == "APPROVED"


# --- timing (ASM-024, S22 rule) -----------------------------------------------------------------------------------
def timing(delay: int) -> DecisionTiming:
    return DecisionTiming(lw.CAL, {"X": "IN"}, lambda key, lo, hi: delay, {"L1": (0, 5)}, (),
                          ProcessOwnerPolicy(frozenset(), frozenset(), frozenset()), at(2026, 10, 22, 0))


@pytest.mark.parametrize("assigned,delay,expected", [
    (at(2025, 8, 11, 10), 0, at(2025, 8, 12, 17)),   # Mon 10:00, 0 -> 1 business day: Tue 17:00
    (at(2025, 8, 11, 17), 1, at(2025, 8, 13, 17)),   # assigned at 17:00 counts from Tuesday
    (at(2025, 8, 14, 10), 1, at(2025, 8, 18, 17)),   # Thu: Fri 15 Aug is an IN holiday, then the weekend
    (at(2025, 8, 11, 10), 3, at(2025, 8, 14, 17)),
])
def test_decision_time_rule(assigned, delay, expected):
    assert timing(delay).decision_at(assigned, "L1", ("k",), "X") == expected


def test_every_decision_is_more_than_24_hours_after_its_assignment():
    t = timing(0)
    start = at(2025, 3, 3, 0)
    for h in range(24 * 21):                                     # every hour over three weeks
        assigned = start + timedelta(hours=h, minutes=59)
        assert t.decision_at(assigned, "L1", ("k",), "X") - assigned > timedelta(hours=24)
