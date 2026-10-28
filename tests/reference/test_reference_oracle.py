"""The reference oracle on hand-built cases with known answers (docs/08 section 6). No database needed.

A tiny organisation is built by hand; reference tables (policies, FX, cost centers) come from a starter baseline.
    EMP-000001 G7 root, head of Finance (IN)       EMP-000002 G5 finance controller IN (reports to 001)
    EMP-000003 G6 head of Engineering (001)         EMP-000004 G5 manager (003)      EMP-000009 G5 peer (003)
    EMP-000005 G1 (004)    EMP-000007 G4 terminated 2025-03-31 (004)    EMP-000008 G1 (007)
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from src.data.generate import build
from src.reference.oracle import Oracle, ReferenceConfig
from src.services.leave_balance_service import accrual_schedule

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
FIXTURES = ROOT / "tests" / "fixtures" / "negative"
D = date(2026, 3, 2)


def emp(n, grade, manager, dept="DEPT-01", controller=False, end=None, country="IN"):
    return {"employee_id": f"EMP-{n:06d}", "grade": grade, "manager_id": manager and f"EMP-{manager:06d}",
            "department_id": dept, "country": country, "currency": "INR", "is_finance_controller": controller,
            "employment_start": date(2020, 1, 1), "employment_end": end,
            "employment_status": "TERMINATED" if end else "ACTIVE"}


@pytest.fixture(scope="module")
def tables():
    base = build(20261022, employees=40, leave_requests=80, expense_claims=100, baseline_only=True).dataset
    t = {k: base[k] for k in ("leave_policy", "expense_policy", "fx_rate", "cost_center", "cost_center_budget")}
    t["employee"] = [emp(1, "G7", None, "DEPT-03"), emp(2, "G5", 1, "DEPT-03", controller=True), emp(3, "G6", 1),
                     emp(4, "G5", 3), emp(9, "G5", 3), emp(5, "G1", 4), emp(7, "G4", 4, end=date(2025, 3, 31)),
                     emp(8, "G1", 7)]
    t["department"] = [{"department_id": "DEPT-01", "head_employee_id": "EMP-000003"},
                       {"department_id": "DEPT-03", "head_employee_id": "EMP-000001"}]
    t["delegation"] = [{"approver_id": "EMP-000004", "delegate_id": "EMP-000009",
                        "effective_from": date(2026, 5, 1), "effective_to": date(2026, 5, 10)}]
    t["country_holiday"] = [{"country": "IN", "holiday_date": date(2026, 8, 14)}]
    for k in ("leave_balance", "leave_balance_transaction", "leave_request", "expense_claim", "expense_line", "receipt"):
        t[k] = []
    return t


@pytest.fixture(scope="module")
def oracle(tables):
    return Oracle(tables, CONFIG)


def levels(route):
    return [(s["level"], s["approver_id"], s["covers"]) for s in route]


@pytest.mark.parametrize("usd, expected", [
    ("100.00", [("L1", "EMP-000004", ["L1"])]),
    ("200.00", [("L1", "EMP-000004", ["L1"])]),                                   # BC-01 upper-inclusive
    ("200.01", [("L1", "EMP-000004", ["L1"]), ("L2", "EMP-000003", ["L2"])]),
    ("5000.00", [("L1", "EMP-000004", ["L1"]), ("L2", "EMP-000003", ["L2"]), ("L4", "EMP-000002", ["L4"])]),
    ("5000.01", [("L1", "EMP-000004", ["L1"]), ("L2", "EMP-000003", ["L2"]), ("L4", "EMP-000002", ["L4"]),
                 ("L5", "EMP-000001", ["L5"])]),
])
def test_expense_routes_by_band(oracle, usd, expected):
    rule, err = oracle.select_rule("EXPENSE", "IN", "MEALS", Decimal(usd), D)
    assert err is None
    assert levels(oracle.resolve_route("EMP-000005", rule["levels"], D)) == expected


@pytest.mark.parametrize("qty, leave_type, rule_id", [
    ("5.0", "ANNUAL", "RULE-L-001"), ("5.5", "ANNUAL", "RULE-L-002"), ("10.0", "ANNUAL", "RULE-L-002"),
    ("10.5", "ANNUAL", "RULE-L-003"), ("1.0", "UNPAID", "RULE-L-004"),
])
def test_leave_rule_bands_and_unpaid_priority(oracle, qty, leave_type, rule_id):
    rule, err = oracle.select_rule("LEAVE", "IN", leave_type, Decimal(qty), D)
    assert err is None and rule["id"] == rule_id


def test_g7_as_l1_covers_l2_in_one_step(oracle):
    """AMB-P3-03: the head reports to the G7, who covers L1 and L2 in ONE step."""
    assert levels(oracle.resolve_route("EMP-000003", ("L1", "L2"), D)) == [("L2", "EMP-000001", ["L1", "L2"])]


def test_one_person_for_several_levels_keeps_the_highest(oracle):
    route = oracle.resolve_route("EMP-000003", ("L1", "L2", "L4", "L5"), D)
    assert levels(route) == [("L4", "EMP-000002", ["L4"]), ("L5", "EMP-000001", ["L1", "L2", "L5"])]


def test_g7_requester_has_no_path(oracle):
    assert oracle.resolve_route("EMP-000001", ("L1",), D) is None


def test_terminated_manager_without_delegate_moves_up(oracle):
    assert levels(oracle.resolve_route("EMP-000008", ("L1",), date(2025, 6, 2))) == [("L1", "EMP-000004", ["L1"])]


def test_active_delegation_routes_to_delegate(oracle):
    inside = oracle.resolve_route("EMP-000005", ("L1",), date(2026, 5, 4))
    outside = oracle.resolve_route("EMP-000005", ("L1",), date(2026, 5, 11))
    assert inside[0]["approver_id"] == "EMP-000009" and inside[0]["delegated_from"] == "EMP-000004"
    assert outside[0]["approver_id"] == "EMP-000004" and outside[0]["delegated_from"] is None


def test_requester_as_department_head_moves_up_for_l3(oracle):
    assert levels(oracle.resolve_route("EMP-000003", ("L1", "L3"), D)) == [("L3", "EMP-000001", ["L1", "L3"])]


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("rules_conflict_*.yaml")), ids=lambda p: p.stem)
def test_rule_conflict_fixtures(tables, path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    o = Oracle(tables, CONFIG, rules_override=doc["rules"])
    probe = doc["probe"]
    category = "MEALS" if probe["request_type"] == "EXPENSE" else "ANNUAL"
    rule, err = o.select_rule(probe["request_type"], "IN", category, Decimal(probe["measure"]), D)
    assert rule is None and err == doc["expected"] == "RULE_CONFLICT"


def test_no_conflict_in_shipped_rules(oracle):
    for rtype, cat, measures in (("EXPENSE", "MEALS", ["1", "200", "999", "5000", "9999"]),
                                 ("LEAVE", "ANNUAL", ["0.5", "5", "10", "15"]), ("LEAVE", "UNPAID", ["3"])):
        for m in measures:
            assert oracle.select_rule(rtype, "IN", cat, Decimal(m), D)[1] is None


def item(day, cid, usd):
    return (date(2026, 3, day), datetime(2026, 3, day, 9, tzinfo=timezone.utc), cid, Decimal(usd))


@pytest.mark.parametrize("items, groups", [
    ([item(2, "A", "100.00"), item(4, "B", "100.00")], [["A", "B"]]),                 # BC-10: sum = 200 flagged
    ([item(2, "A", "100.00"), item(4, "B", "99.99")], []),                           # below the threshold
    ([item(2, "A", "150.00"), item(8, "B", "150.00")], [["A", "B"]]),                # 6 days apart: inside
    ([item(2, "A", "150.00"), item(9, "B", "150.00")], []),                          # 7 days apart: outside
    ([item(2, "A", "150.00")], []),                                                  # one claim is no group
    ([item(2, "A", "80.00"), item(3, "B", "80.00"), item(5, "C", "80.00")], [["A", "B", "C"]]),
])
def test_split_groups(oracle, items, groups):
    assert oracle.split_groups(items) == groups


def leave(start, end, sh=False, eh=False):
    return {"start_date": start, "end_date": end, "start_half_day": sh, "end_half_day": eh}


def test_overlap_and_complementary_half_days(oracle):
    a = leave(date(2026, 3, 2), date(2026, 3, 4), eh=True)
    assert not oracle.overlap(a, leave(date(2026, 3, 4), date(2026, 3, 6), sh=True))   # ASM-008
    assert oracle.overlap(a, leave(date(2026, 3, 4), date(2026, 3, 6)))
    assert not oracle.overlap(a, leave(date(2026, 3, 5), date(2026, 3, 6)))


@pytest.mark.parametrize("codes, status", [
    (set(), "APPROVED"), ({"LINE_LIMIT_EXCEEDED"}, "APPROVED"), ({"INSUFFICIENT_BALANCE"}, "REJECTED"),
    ({"MISSING_RECEIPT", "BUDGET_EXCEEDED"}, "RETURNED_FOR_CORRECTION"), ({"BUDGET_EXCEEDED"}, "APPROVED"),
    ({"POLICY_VERSION_EXPIRED", "OVERLAPPING_PENDING_LEAVE"}, "APPROVED"), ({"SPLIT_CLAIM_SUSPECTED"}, "REJECTED"),
    ({"MISSING_COST_CENTER"}, "RETURNED_FOR_CORRECTION"), ({"CLAIM_LIMIT_EXCEEDED"}, "ESCALATED_FOR_REVIEW"),
    ({"NO_VALID_APPROVAL_PATH"}, "ESCALATED_FOR_REVIEW"),
    ({"BUDGET_EXCEEDED", "NO_VALID_APPROVAL_PATH"}, "ESCALATED_FOR_REVIEW"),
])
def test_outcome_precedence_and_process_owner_decisions(oracle, codes, status):
    assert oracle.outcome(codes) == status


def test_business_days_skip_weekend_and_holiday(oracle):
    # 2026-08-14 (Fri) is a holiday in the hand-built calendar; 15-16 is a weekend.
    assert oracle.business_days(date(2026, 8, 13), date(2026, 8, 17), "IN") == 2
    assert oracle.quantity(date(2026, 8, 13), date(2026, 8, 17), "IN", True, False) == Decimal("1.5")


@pytest.mark.parametrize("start", [date(2020, 1, 1), date(2025, 3, 17), date(2026, 2, 28)])
def test_accrual_matches_shared_schedule(tables, start):
    """Independent re-implementation agrees with the services' schedule (both read the same policy rows)."""
    for pol in tables["leave_policy"]:
        for year in (2025, 2026):
            assert Oracle.accruals(pol, start, None, year) == \
                accrual_schedule(pol, start, None, year, date(year, 12, 31)), (pol["leave_policy_id"], start, year)


def test_config_is_read_directly():
    cfg = ReferenceConfig(CONFIG)
    assert cfg.split_threshold == Decimal("200.00") and cfg.split_window == 7 and cfg.max_line_age == 90
    assert cfg.severity["MISSING_RECEIPT"] == "CORRECTABLE"
