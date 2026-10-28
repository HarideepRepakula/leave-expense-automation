"""Approval routing (docs/05 5.1-5.4; Phase 7A) and approval steps created at submission, without a database.

Synthetic organisation (all IN unless noted):
  CEO (G7, heads FIN, no manager) <- HEAD (G6, heads ENG) <- MGR (G5) <- DEV (G2)
  CEO <- CTL_IN (finance controller IN), CEO <- CTL_US (controller, US); MGR <- DEV_US (US)
  HEAD <- LEFT (G5, employment ended 2025-12-31) <- DEV2
  DELEG (G5, under HEAD). Delegations: LEFT -> DELEG 2026-03-01..2026-12-31; MGR -> DELEG 2026-06-01..2026-06-30.
Rules: config/approval_rules.yaml as stage S1 builds them, plus extra rows per test.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import yaml

from src.data.stages.master import _approval_rules
from src.services.approval_routing import ApprovalRouter, Organisation, RouteStep, build_steps
from tests.unit import leave_world as lw
from tests.unit import test_expense_validation as xw

ROOT = lw.ROOT
D = Decimal
RULES = _approval_rules({"approval_rules": yaml.safe_load(
    (ROOT / "config" / "approval_rules.yaml").read_text(encoding="utf-8"))})
CEO, HEAD, MGR, DEV, CTL_IN, CTL_US, DEV_US, LEFT, DEV2, DELEG = (f"EMP-0001{i:02d}" for i in range(10))
ON = date(2026, 2, 2)


def emp(eid, manager, dept="DEPT-ENG", grade="G2", country="IN", controller=False, end=None) -> dict:
    return {"employee_id": eid, "manager_id": manager, "department_id": dept, "grade": grade, "country": country,
            "is_finance_controller": controller, "employment_end": end}


def org_rows(extra: list[dict] = ()) -> list[dict]:
    rows = [emp(CEO, None, "DEPT-FIN", "G7"), emp(HEAD, CEO, grade="G6"), emp(MGR, HEAD, grade="G5"),
            emp(DEV, MGR), emp(CTL_IN, CEO, "DEPT-FIN", "G6", controller=True),
            emp(CTL_US, CEO, "DEPT-FIN", "G6", "US", controller=True), emp(DEV_US, MGR, country="US"),
            emp(LEFT, HEAD, grade="G5", end=date(2025, 12, 31)), emp(DEV2, LEFT), emp(DELEG, HEAD, grade="G5")]
    return rows + list(extra)


DEPARTMENTS = [{"department_id": "DEPT-ENG", "head_employee_id": HEAD},
               {"department_id": "DEPT-FIN", "head_employee_id": CEO}]
DELEGATIONS = [{"delegation_id": "DLG-0001", "approver_id": LEFT, "delegate_id": DELEG,
                "effective_from": date(2026, 3, 1), "effective_to": date(2026, 12, 31)},
               {"delegation_id": "DLG-0002", "approver_id": MGR, "delegate_id": DELEG,
                "effective_from": date(2026, 6, 1), "effective_to": date(2026, 6, 30)}]


def router(rules=None, extra_emps=(), delegations=None) -> ApprovalRouter:
    return ApprovalRouter.from_rows(RULES if rules is None else rules, org_rows(extra_emps), DEPARTMENTS,
                                    DELEGATIONS if delegations is None else delegations)


def route(r: ApprovalRouter, rtype: str, who: str, measure: str, category: str = "MEALS", on: date = ON):
    res = r.route(rtype, who, "ANNUAL" if rtype == "LEAVE" and category == "MEALS" else category, D(measure), on)
    code = res.finding.code if res.finding else None
    return res.rule_id, [(s.level, s.approver_id, s.covered_levels, s.delegated_from) for s in res.steps], code


def rule(rid, rtype, levels, priority=10, low=None, high=None, **kw) -> dict:
    lo, hi = ("min_days", "max_days") if rtype == "LEAVE" else ("min_amount_usd", "max_amount_usd")
    row = {"approval_rule_id": rid, "request_type": rtype, "country": None, "category_or_leave_type": None,
           "min_amount_usd": None, "max_amount_usd": None, "min_days": None, "max_days": None,
           "required_levels": levels, "priority": priority, "effective_start": date(2025, 1, 1),
           "effective_end": None, "is_active": True}
    row.update({lo: None if low is None else D(low), hi: None if high is None else D(high)}, **kw)
    return row


# --- rule selection: bands lower-exclusive / upper-inclusive, priority, conflicts -----------------------------
@pytest.mark.parametrize("rtype, measure, category, rule_id", [
    ("EXPENSE", "0.01", "MEALS", "RULE-E-001"), ("EXPENSE", "200.00", "MEALS", "RULE-E-001"),
    ("EXPENSE", "200.01", "MEALS", "RULE-E-002"), ("EXPENSE", "1000.00", "TRAVEL", "RULE-E-002"),
    ("EXPENSE", "1000.01", "TRAVEL", "RULE-E-003"), ("EXPENSE", "5000.00", "TRAVEL", "RULE-E-003"),
    ("EXPENSE", "5000.01", "TRAVEL", "RULE-E-004"),
    ("LEAVE", "0.5", "ANNUAL", "RULE-L-001"), ("LEAVE", "5.0", "ANNUAL", "RULE-L-001"),
    ("LEAVE", "5.5", "SICK", "RULE-L-002"), ("LEAVE", "10.0", "ANNUAL", "RULE-L-002"),
    ("LEAVE", "10.5", "ANNUAL", "RULE-L-003"),
    ("LEAVE", "1.0", "UNPAID", "RULE-L-004"), ("LEAVE", "12.0", "UNPAID", "RULE-L-004"),   # priority 20 wins
])
def test_bands_and_priority(rtype, measure, category, rule_id):
    found, problem = router().select_rule(rtype, "IN", category, D(measure), ON)
    assert problem is None and found["approval_rule_id"] == rule_id


def test_rule_conflict_on_equal_priority_with_different_levels():
    rules = RULES + [rule("RULE-E-005", "EXPENSE", ["L1", "L2"], high="200.00")]
    assert route(router(rules), "EXPENSE", DEV, "150.00") == (None, [], "RULE_CONFLICT")
    assert route(router(rules), "EXPENSE", DEV, "250.00")[2] is None        # outside the conflicting band


def test_equal_priority_and_identical_levels_take_the_lowest_rule_id():
    rules = [rule("RULE-E-009", "EXPENSE", ["L1"], high="200.00")] + RULES
    assert route(router(rules), "EXPENSE", DEV, "150.00")[0] == "RULE-E-001"


def test_higher_priority_country_and_category_rules():
    rules = RULES + [rule("RULE-E-006", "EXPENSE", ["L1", "L4"], priority=30, country="US"),
                     rule("RULE-E-007", "EXPENSE", ["L1", "L2"], priority=30, category_or_leave_type="TRAINING")]
    assert route(router(rules), "EXPENSE", DEV_US, "50.00")[0] == "RULE-E-006"
    assert route(router(rules), "EXPENSE", DEV, "50.00")[0] == "RULE-E-001"
    assert route(router(rules), "EXPENSE", DEV, "50.00", "TRAINING")[0] == "RULE-E-007"


def test_no_matching_rule_inactive_or_not_effective_is_no_valid_approval_path():
    rules = [rule("RULE-E-001", "EXPENSE", ["L1"], high="200.00", is_active=False),
             rule("RULE-E-002", "EXPENSE", ["L1"], high="200.00", effective_start=date(2026, 3, 1)),
             rule("RULE-E-003", "EXPENSE", ["L1"], high="200.00", effective_end=date(2026, 1, 31))]
    assert route(router(rules), "EXPENSE", DEV, "150.00") == (None, [], "NO_VALID_APPROVAL_PATH")
    assert route(router(rules), "EXPENSE", DEV, "150.00", on=date(2026, 3, 1))[0] == "RULE-E-002"


# --- levels L1..L5 and covered_levels ----------------------------------------------------------------------------
@pytest.mark.parametrize("who, rtype, measure, category, steps", [
    (DEV, "EXPENSE", "150.00", "MEALS", [("L1", MGR, ("L1",), None)]),
    (DEV, "EXPENSE", "500.00", "MEALS", [("L1", MGR, ("L1",), None), ("L2", HEAD, ("L2",), None)]),
    (DEV, "EXPENSE", "2000.00", "TRAVEL", [("L1", MGR, ("L1",), None), ("L2", HEAD, ("L2",), None),
                                           ("L4", CTL_IN, ("L4",), None)]),
    (DEV, "EXPENSE", "6000.00", "TRAVEL", [("L1", MGR, ("L1",), None), ("L2", HEAD, ("L2",), None),
                                           ("L4", CTL_IN, ("L4",), None), ("L5", CEO, ("L5",), None)]),
    (DEV_US, "EXPENSE", "2000.00", "TRAVEL", [("L1", MGR, ("L1",), None), ("L2", HEAD, ("L2",), None),
                                              ("L4", CTL_US, ("L4",), None)]),
    (DEV, "LEAVE", "11.0", "ANNUAL", [("L1", MGR, ("L1",), None), ("L3", HEAD, ("L3",), None)]),
    # L1 is also the department head: one step at L3 covering L1 and L3.
    (MGR, "LEAVE", "11.0", "ANNUAL", [("L3", HEAD, ("L1", "L3"), None)]),
    # The manager is the top of the chain: the G7 covers L2 in the same step (AMB-P3-03).
    (HEAD, "EXPENSE", "500.00", "MEALS", [("L2", CEO, ("L1", "L2"), None)]),
    # The requester is the department head: L3 moves one step up, to the G7, who is also L1.
    (HEAD, "LEAVE", "1.0", "UNPAID", [("L3", CEO, ("L1", "L3"), None)]),
    # One person for L1, L2 and L5; ordered by level, so the controller (L4) comes first.
    (HEAD, "EXPENSE", "6000.00", "TRAVEL", [("L4", CTL_IN, ("L4",), None), ("L5", CEO, ("L1", "L2", "L5"), None)]),
    # The requester is the finance controller: L4 moves up the chain, to the G7 (also L1 and L2).
    (CTL_IN, "EXPENSE", "2000.00", "TRAVEL", [("L4", CEO, ("L1", "L2", "L4"), None)]),
])
def test_level_resolution_and_covered_levels(who, rtype, measure, category, steps):
    rule_id, found, problem = route(router(), rtype, who, measure, category)
    assert problem is None and found == steps


def test_the_g7_requester_has_no_valid_path():
    assert route(router(), "EXPENSE", CEO, "150.00") == ("RULE-E-001", [], "NO_VALID_APPROVAL_PATH")
    assert route(router(), "LEAVE", CEO, "1.0", "ANNUAL") == ("RULE-L-001", [], "NO_VALID_APPROVAL_PATH")


# --- substitution (docs/05 5.4) -----------------------------------------------------------------------------------
def test_ended_employment_without_delegate_moves_up_the_chain():
    assert route(router(), "EXPENSE", DEV2, "150.00")[1] == [("L1", HEAD, ("L1",), None)]


def test_ended_employment_with_an_active_delegation_uses_the_delegate():
    assert route(router(), "EXPENSE", DEV2, "150.00", on=date(2026, 3, 2))[1] == [("L1", DELEG, ("L1",), LEFT)]


def test_an_approver_on_delegation_is_replaced_by_the_delegate():
    found = route(router(), "EXPENSE", DEV, "500.00", on=date(2026, 6, 15))[1]
    assert found == [("L1", DELEG, ("L1",), MGR), ("L2", HEAD, ("L2",), None)]
    assert route(router(), "EXPENSE", DEV, "500.00", on=date(2026, 7, 1))[1][0] == ("L1", MGR, ("L1",), None)


def test_lowest_delegation_id_wins_and_delegate_chain_keeps_the_first_delegator():
    dlg = [{"delegation_id": "DLG-0009", "approver_id": MGR, "delegate_id": HEAD,
            "effective_from": ON, "effective_to": ON},
           {"delegation_id": "DLG-0003", "approver_id": MGR, "delegate_id": LEFT,
            "effective_from": ON, "effective_to": ON},
           {"delegation_id": "DLG-0004", "approver_id": LEFT, "delegate_id": DELEG,
            "effective_from": ON, "effective_to": ON}]
    # MGR -> LEFT (lowest id); LEFT has ended and delegates on to DELEG; delegated_from stays MGR.
    assert route(router(delegations=dlg), "EXPENSE", DEV, "150.00")[1] == [("L1", DELEG, ("L1",), MGR)]


def test_delegation_to_the_requester_leaves_the_level_unresolved():
    """AMB-P7A-03 (default as the oracle): the requester moves up to the delegator, already visited -> unresolved."""
    dlg = [{"delegation_id": "DLG-0005", "approver_id": MGR, "delegate_id": DEV,
            "effective_from": ON, "effective_to": ON}]
    assert route(router(delegations=dlg), "EXPENSE", DEV, "150.00")[2] == "NO_VALID_APPROVAL_PATH"


# --- L5 per country (S19 option a) and ambiguous roles -----------------------------------------------------------
def test_l5_is_the_g7_of_the_requesters_country_else_the_only_g7():
    us_g7 = emp("EMP-000190", None, "DEPT-FIN", "G7", "US")
    assert route(router(), "EXPENSE", DEV_US, "6000.00", "TRAVEL")[1][-1] == ("L5", CEO, ("L5",), None)  # AMB-P7A-01
    assert route(router(extra_emps=[us_g7]), "EXPENSE", DEV_US, "6000.00", "TRAVEL")[1][-1] == \
        ("L5", "EMP-000190", ("L5",), None)
    assert route(router(extra_emps=[us_g7]), "EXPENSE", DEV, "6000.00", "TRAVEL")[1][-1] == ("L5", CEO, ("L5",), None)


def test_two_people_for_one_role_never_pick_one():
    second_g7 = emp("EMP-000191", None, "DEPT-FIN", "G7")
    second_ctl = emp("EMP-000192", CEO, "DEPT-FIN", "G6", controller=True)
    assert route(router(extra_emps=[second_g7]), "EXPENSE", DEV, "6000.00", "TRAVEL")[2] == "NO_VALID_APPROVAL_PATH"
    assert route(router(extra_emps=[second_ctl]), "EXPENSE", DEV, "2000.00", "TRAVEL")[2] == "NO_VALID_APPROVAL_PATH"


def test_build_steps_ids_sequence_and_assignment():
    r = router().route("EXPENSE", HEAD, "TRAVEL", D("6000.00"), ON)
    at = datetime(2026, 2, 2, 9, tzinfo=timezone.utc)
    steps = build_steps("EXPENSE", "EXP-2026-000001", 2, r, at, first_sequence=3)
    assert [(s["approval_step_id"], s["sequence_no"], s["required_level"], s["covered_levels"], s["assigned_at"])
            for s in steps] == [("APR-EXP-2026-000001-03", 3, "L4", ["L4"], at),
                                ("APR-EXP-2026-000001-04", 4, "L5", ["L1", "L2", "L5"], None)]
    assert {(s["expense_claim_id"], s["leave_request_id"], s["submission_round"], s["step_status"],
             s["approval_rule_id"]) for s in steps} == {("EXP-2026-000001", None, 2, "PENDING", "RULE-E-004")}


def test_organisation_ignores_unknown_department_head():
    org = Organisation({e["employee_id"]: e for e in org_rows([emp("EMP-000193", MGR, "DEPT-NEW")])}, DEPARTMENTS, [])
    assert org.base_approver("L3", org.employees["EMP-000193"]) is None
    assert RouteStep("L1", MGR, ("L1",), None).covered_levels == ("L1",)


# --- submission creates steps only for PENDING_APPROVAL (in-memory stores) ---------------------------------------
def leave_router(manager_of_e5: str | None = None) -> ApprovalRouter:
    """The leave_world employees placed in the organisation: E1, E2 report to MGR; E5 to `manager_of_e5`."""
    extra = [emp(lw.E1, MGR), emp(lw.E2, MGR, country="US"), emp(lw.E5, manager_of_e5, country="GB")]
    return router(extra_emps=extra)


def leave_store(r: ApprovalRouter | None) -> lw.InMemoryLeaveStore:
    rows, balances = lw.ledger_and_balances()
    return lw.InMemoryLeaveStore(lw.EMPLOYEES, lw.POLICIES, lw.CAL, rows, balances, r)


def test_clean_leave_gets_steps_an_assigned_event_and_the_route_in_calculated_values():
    s = leave_store(leave_router())
    when = lw.at(2025, 3, 3)
    res = lw.submit(s, lw.req("LVE-2025-000001", lw.E1, lw.ANNUAL_IN, date(2025, 3, 10), date(2025, 3, 11)), when)
    assert res.status == "PENDING_APPROVAL" and res.codes == []
    assert [(st["approval_step_id"], st["required_level"], st["covered_levels"], st["approver_employee_id"],
             st["assigned_at"]) for st in s.steps["LVE-2025-000001"]] == \
        [("APR-LVE-2025-000001-01", "L1", ["L1"], MGR, when)]
    assert [(e["approval_step_id"], e["event_type"], e["actor_id"]) for e in s.approval_events] == \
        [("APR-LVE-2025-000001-01", "ASSIGNED", None)]
    values = res.events[-1]["calculated_values"]
    assert values["approval_rule_id"] == "RULE-L-001" and values["route"][0]["approver_id"] == MGR


def test_routing_failure_escalates_with_the_code_and_creates_no_steps():
    s = leave_store(leave_router(manager_of_e5=None))
    res = lw.submit(s, lw.req("LVE-2025-000002", lw.E5, lw.SICK, date(2025, 3, 10), date(2025, 3, 10)),
                    lw.at(2025, 3, 3))
    assert (res.status, res.codes, res.classification.exception_class) == \
        ("ESCALATED_FOR_REVIEW", ["NO_VALID_APPROVAL_PATH"], "NO_VALID_APPROVAL_PATH")
    assert res.routing.rule_id == "RULE-L-001" and res.steps == [] and s.steps == {}
    assert [x["exception_code"] for x in s.exceptions] == ["NO_VALID_APPROVAL_PATH"]
    assert res.validation.codes == []          # the routing code is not a validation finding (detections.csv)


def test_soft_outcome_is_routed_but_gets_no_steps_and_hard_or_correctable_is_not_routed():
    s = leave_store(leave_router())
    first = lw.req("LVE-2025-000003", lw.E1, lw.ANNUAL_IN, date(2025, 3, 10), date(2025, 3, 10))
    lw.submit(s, first, lw.at(2025, 3, 3))
    overlap = lw.req("LVE-2025-000004", lw.E1, lw.SICK, date(2025, 3, 10), date(2025, 3, 10))
    res = lw.submit(s, overlap, lw.at(2025, 3, 4))
    assert res.status == "ESCALATED_FOR_REVIEW" and res.codes == ["OVERLAPPING_PENDING_LEAVE"]
    assert res.routing.rule_id == "RULE-L-001" and res.steps == []
    no_cert = lw.req("LVE-2025-000005", lw.E1, lw.SICK, date(2025, 4, 7), date(2025, 4, 11))
    res = lw.submit(s, no_cert, lw.at(2025, 4, 1))
    assert res.status == "RETURNED_FOR_CORRECTION" and res.routing is None and res.steps == []
    assert list(s.steps) == ["LVE-2025-000003"]


def test_a_store_without_router_keeps_the_phase_5_behaviour():
    s = leave_store(None)
    res = lw.submit(s, lw.req("LVE-2025-000006", lw.E5, lw.SICK, date(2025, 3, 10), date(2025, 3, 10)),
                    lw.at(2025, 3, 3))
    assert res.status == "PENDING_APPROVAL" and res.routing is None and res.steps == [] and s.approval_events == []


def test_expense_claim_steps_with_one_step_covering_l1_and_l2():
    """E1's manager E2 is the top of the chain: a RULE-E-002 claim gets ONE step for E2 covering L1 and L2;
    a claim of E2 itself has no L1 (NO_VALID_APPROVAL_PATH) and keeps its budget reservation."""
    r = router(extra_emps=[emp("E1", "E2"), emp("E2", None, grade="G6")])
    s = xw.InMemoryExpenseStore(xw.EMPLOYEES, xw.POLICIES, xw.FX, xw.CCS, xw.BUDGETS, xw.RECEIPTS, [], xw.PARAMS, r)
    res = xw.submit(s, xw.claim("C1", "E1", [("TRAVEL", date(2025, 5, 20), "19000.00", "R4")]))
    assert res.status == "PENDING_APPROVAL" and res.validation.usd == D("224.85") and res.codes == []
    assert [(st["approval_step_id"], st["required_level"], st["covered_levels"], st["approver_employee_id"],
             st["approval_rule_id"]) for st in s.steps["C1"]] == [("APR-C1-01", "L2", ["L1", "L2"], "E2", "RULE-E-002")]
    assert [p["txn_type"] for p in res.budget_postings] == ["RESERVATION"]
    escalated = xw.submit(s, xw.claim("C2", "E2", [("MEALS", date(2025, 5, 20), "1000.00", None)]))
    assert escalated.status == "ESCALATED_FOR_REVIEW" and escalated.codes == ["NO_VALID_APPROVAL_PATH"]
    assert [p["txn_type"] for p in escalated.budget_postings] == ["RESERVATION"]     # kept until the decision
    assert "C2" not in s.steps and uuid.UUID(str(s.approval_events[0]["correlation_id"]))
