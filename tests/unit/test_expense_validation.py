"""Expense validation and submission (docs/05 sections 3, 6, 7, 9; docs/06 8.1), FX and money arithmetic, split
groups, duplicates and the batch detectors. Hand-built synthetic world (no database): 1 USD = 84.5 INR from
2025-01-01; IN MEALS V1 (2025) / V2 (2026) limit 6230 / 6850 per line, receipt from 2080; IN TRAVEL claim limit
20000; CC-0001 active, CC-0002 inactive; CC-0001 budget 100000 (2025) and 5000 (2026)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from src.services.expense_batch import replay_expense
from src.services.expense_service import (
    DetectionParams,
    ExpenseInputError,
    InMemoryExpenseStore,
    PolicyConfigurationError,
    resolve_expense_policy,
    split_groups,
    submit_expense,
    to_usd,
)
from src.services.lifecycle import IllegalTransition
from tests.unit.leave_world import CATALOGUE

D = Decimal
PARAMS = DetectionParams(90, 7, D("200.00"))
FX = [{"from_currency": "USD", "to_currency": "INR", "rate": D("84.500000"), "effective_from": date(2025, 1, 1)},
      {"from_currency": "USD", "to_currency": "GBP", "rate": D("0.800000"), "effective_from": date(2025, 1, 1)}]


def pol(pid, category, line, claim, start, end=None):
    return {"expense_policy_id": pid, "category": category, "country": "IN", "currency": "INR", "is_active": True,
            "per_line_limit": D(line), "per_claim_limit": D(claim), "receipt_threshold": D("2080.00"),
            "effective_start": start, "effective_end": end}


POLICIES = [pol("XPOL-MEALS-IN-V1", "MEALS", "6230.00", "498000.00", date(2025, 1, 1), date(2025, 12, 31)),
            pol("XPOL-MEALS-IN-V2", "MEALS", "6850.00", "498000.00", date(2026, 1, 1)),
            pol("XPOL-TRAVEL-IN-V1", "TRAVEL", "126750.00", "20000.00", date(2025, 1, 1))]
EMPLOYEES = {e: {"employee_id": e, "country": "IN", "currency": "INR", "employment_start": s, "employment_end": end}
             for e, s, end in (("E1", date(2022, 1, 1), None), ("E2", date(2021, 1, 1), None),
                               ("E3", date(2018, 1, 1), date(2025, 6, 30)))}
CCS = [{"cost_center_id": "CC-0001", "is_active": True, "effective_from": date(2015, 1, 1), "effective_to": None},
       {"cost_center_id": "CC-0002", "is_active": False, "effective_from": date(2015, 1, 1), "effective_to": None}]
BUDGETS = [{"cost_center_budget_id": f"CCB-CC-0001-{y}", "cost_center_id": "CC-0001",
            "budget_period_start": date(y, 1, 1), "budget_period_end": date(y, 12, 31), "budget_amount": D(a)}
           for y, a in ((2025, "100000.00"), (2026, "5000.00"))]
RECEIPTS = [{"receipt_id": f"R{i}", "receipt_hash": h}
            for i, h in enumerate(["H1", "H1", "H1", "H4", "H5", "H6", "H7"], start=1)]
SUB = datetime(2025, 6, 2, 9, 0, tzinfo=timezone.utc)


def store() -> InMemoryExpenseStore:
    return InMemoryExpenseStore(EMPLOYEES, POLICIES, FX, CCS, BUDGETS, RECEIPTS, [], PARAMS)


def claim(cid, emp, lines, cc="CC-0001", policy_id=None, created=SUB):
    """lines: (category, date, amount, receipt_id[, currency[, quantity]])."""
    rows = []
    for n, ln in enumerate(lines, start=1):
        cat, d, amount, rid, *rest = ln
        cur = rest[0] if rest else "INR"
        q = rest[1] if len(rest) > 1 else None
        rows.append({"expense_line_id": f"EXPL-{cid}-{n:02d}", "expense_claim_id": cid, "line_number": n,
                     "submission_round": 1, "category": cat, "expense_date": d, "line_amount": D(amount),
                     "quantity": None if q is None else D(q), "unit_amount": None if q is None else D(amount) / D(q),
                     "currency": cur, "receipt_id": rid, "expense_policy_id": None,
                     "validation_result": "PENDING", "validation_detail": None})
    row = {"expense_claim_id": cid, "employee_id": emp, "currency": "INR", "cost_center_id": cc,
           "expense_policy_id": policy_id, "total_amount": sum((r["line_amount"] for r in rows), D(0)),
           "current_round": 1, "workflow_status": "DRAFT", "first_submitted_at": None, "created_at": created,
           "exception_class": "NONE", "receipt_status": "NOT_REQUIRED", "decision_reason_code": None,
           "total_amount_usd": None, "fx_rate_used": None}
    return row, rows


def submit(s, c, when=SUB):
    row, rows = c
    s.add_claim(row, rows)
    return submit_expense(s, row["expense_claim_id"], CATALOGUE, when, row["employee_id"],
                          uuid.uuid5(uuid.NAMESPACE_URL, row["expense_claim_id"]))


def test_clean_claim_usd_policy_lines_reservation_and_events():
    s = store()
    res = submit(s, claim("C1", "E1", [("MEALS", date(2025, 5, 20), "1000.00", None, "INR", "2")]))
    v = res.validation
    assert res.status == "PENDING_APPROVAL" and v.codes == []
    assert (v.usd, v.rate, v.policy_id, v.approved_amount, v.receipt_status) == \
        (D("11.83"), D("84.5"), "XPOL-MEALS-IN-V1", D("1000.00"), "NOT_REQUIRED")
    assert [r.validation_result for r in v.lines] == ["PASS"]
    assert [(p["txn_type"], p["amount"]) for p in res.budget_postings] == [("RESERVATION", D("1000.00"))]
    assert [(e["previous_status"], e["new_status"]) for e in res.events] == [
        ("DRAFT", "SUBMITTED"), ("SUBMITTED", "VALIDATING"), ("VALIDATING", "PENDING_APPROVAL")]
    stored = s.claims["C1"]
    assert (stored["total_amount_usd"], stored["expense_policy_id"], stored["first_submitted_at"]) == \
        (D("11.83"), "XPOL-MEALS-IN-V1", SUB)
    assert s.lines["C1"][0]["validation_result"] == "PASS"


JUN = date(2025, 5, 20)
FEB26 = datetime(2026, 2, 2, 9, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("c,when,code,status", [
    (claim("X1", "E3", [("MEALS", date(2025, 7, 2), "500.00", None)]), datetime(2025, 7, 10, tzinfo=timezone.utc),
     "EXPENSE_OUTSIDE_EMPLOYMENT", "REJECTED"),                                          # BR-EX-01
    (claim("X2", "E1", [("MEALS", date(2025, 3, 3), "500.00", None)]), SUB, "EXPENSE_DATE_TOO_OLD",
     "RETURNED_FOR_CORRECTION"),                                                         # 91 days (BR-EX-02)
    (claim("X3", "E1", [("MEALS", date(2025, 6, 3), "500.00", None)]), SUB, "EXPENSE_DATE_TOO_OLD",
     "RETURNED_FOR_CORRECTION"),                                                         # after submission
    (claim("X4", "E1", [("CLIENT_ENTERTAINMENT", JUN, "500.00", None)]), SUB, "POLICY_NOT_APPLICABLE", "REJECTED"),
    (claim("X5", "E1", [("MEALS", JUN, "7000.00", "R4")]), SUB, "LINE_LIMIT_EXCEEDED", "PENDING_APPROVAL"),  # INFO
    (claim("X6", "E1", [("TRAVEL", JUN, "15000.00", "R4"), ("TRAVEL", JUN, "15000.00", "R5")]), SUB,
     "CLAIM_LIMIT_EXCEEDED", "ESCALATED_FOR_REVIEW"),
    (claim("X7", "E1", [("MEALS", JUN, "2080.00", None)]), SUB, "MISSING_RECEIPT",
     "RETURNED_FOR_CORRECTION"),                                                         # threshold inclusive
    (claim("X8", "E1", [("MEALS", JUN, "500.00", None, "USD")]), SUB, "CURRENCY_MISMATCH", "RETURNED_FOR_CORRECTION"),
    (claim("X9", "E1", [("MEALS", JUN, "500.00", None)], cc=None), SUB, "MISSING_COST_CENTER", "ESCALATED_FOR_REVIEW"),
    (claim("X10", "E1", [("MEALS", JUN, "500.00", None)], cc="CC-0002"), SUB, "INVALID_COST_CENTER",
     "ESCALATED_FOR_REVIEW"),
    (claim("X11", "E1", [("MEALS", date(2026, 1, 20), "500.00", None)], policy_id="XPOL-MEALS-IN-V1"), FEB26,
     "POLICY_VERSION_EXPIRED", "ESCALATED_FOR_REVIEW"),
    (claim("X12", "E1", [("MEALS", date(2026, 1, 20), "6000.00", "R4")]), FEB26, "BUDGET_EXCEEDED",
     "ESCALATED_FOR_REVIEW"),                                                            # 6000 > 5000 (BR-BUD-03)
])
def test_each_expense_code(c, when, code, status):
    res = submit(store(), c, when)
    assert code in res.validation.codes, res.validation.codes
    assert res.status == status


def test_line_limit_caps_the_approved_amount_and_rejection_releases_the_budget():
    capped = submit(store(), claim("L1", "E1", [("MEALS", JUN, "7000.00", "R4")])).validation
    assert capped.approved_amount == D("6230.00") and capped.lines[0].validation_result == "CAPPED"
    res = submit(store(), claim("L2", "E3", [("MEALS", date(2025, 7, 2), "500.00", None)]),
                 datetime(2025, 7, 10, tzinfo=timezone.utc))
    assert [p["txn_type"] for p in res.budget_postings] == ["RESERVATION", "RELEASE"]          # BR-BUD-04
    assert res.validation.lines[0].validation_result == "FAIL"


def test_open_reservations_reduce_the_budget():
    s = store()
    assert submit(s, claim("B1", "E1", [("MEALS", date(2026, 1, 20), "3000.00", "R4")]), FEB26).validation.codes == []
    second = submit(s, claim("B2", "E2", [("MEALS", date(2026, 1, 21), "2500.00", "R5")]), FEB26)
    assert second.validation.codes == ["BUDGET_EXCEEDED"] and second.validation.budget["available"] == D("2000.00")


def test_duplicate_receipts_pattern_and_split_at_submission_and_in_batch():
    s = store()
    first = submit(s, claim("D1", "E1", [("MEALS", JUN, "4500.00", "R1"), ("MEALS", JUN, "4500.00", "R4")]))
    assert first.validation.codes == []                                                  # 106.51 USD alone
    self_dup = submit(s, claim("D2", "E1", [("MEALS", date(2025, 5, 22), "4400.00", "R2"),
                                            ("MEALS", date(2025, 5, 22), "4400.00", "R5")]),
                      datetime(2025, 6, 4, tzinfo=timezone.utc))
    assert set(self_dup.validation.codes) == {"DUPLICATE_RECEIPT_SELF", "SPLIT_CLAIM_SUSPECTED"}
    cross = submit(s, claim("D3", "E2", [("TRAVEL", JUN, "900.00", "R3")]))
    assert cross.validation.codes == ["DUPLICATE_RECEIPT_CROSS_EMPLOYEE"]
    pattern = submit(s, claim("D4", "E1", [("MEALS", JUN, "4500.00", "R6"), ("MEALS", JUN, "4500.00", "R7")]),
                     datetime(2025, 8, 15, tzinfo=timezone.utc))
    assert "DUPLICATE_CLAIM_PATTERN" in pattern.validation.codes
    assert "split" in next(f.detail for f in self_dup.validation.findings if f.code == "SPLIT_CLAIM_SUSPECTED")
    assert "fraud" not in str([f.detail for f in self_dup.validation.findings]).lower()

    tables = {"employee": list(EMPLOYEES.values()), "expense_policy": POLICIES, "fx_rate": FX, "cost_center": CCS,
              "cost_center_budget": BUDGETS, "receipt": RECEIPTS,
              "expense_claim": [{**s.claims[c], "workflow_status": "SUBMITTED"} for c in ("D1", "D2", "D3")],
              "expense_line": [ln for c in ("D1", "D2", "D3") for ln in s.lines[c]]}
    rep = replay_expense(tables, CATALOGUE, PARAMS)
    batch = {(d.record_id, d.exception_code) for d in rep.detections}
    assert batch == {("D1", "DUPLICATE_RECEIPT_SELF"), ("D2", "DUPLICATE_RECEIPT_SELF"),
                     ("D1", "DUPLICATE_RECEIPT_CROSS_EMPLOYEE"), ("D2", "DUPLICATE_RECEIPT_CROSS_EMPLOYEE"),
                     ("D3", "DUPLICATE_RECEIPT_CROSS_EMPLOYEE"), ("D1", "SPLIT_CLAIM_SUSPECTED"),
                     ("D2", "SPLIT_CLAIM_SUSPECTED")}


@pytest.mark.parametrize("days,amounts,groups", [
    ((0, 6), ("100.00", "100.00"), [["A", "B"]]),             # window max - min = 6, sum exactly 200 (BC-10)
    ((0, 7), ("150.00", "150.00"), []),                       # outside the 7-day window
    ((0, 3), ("99.99", "100.00"), []),                        # sum below 200
    ((0, 3, 8), ("120.00", "90.00", "150.00"), [["A", "B"]]),   # greedy from the earliest; C left alone
])
def test_split_groups(days, amounts, groups):
    d0 = date(2025, 5, 1)
    items = [(date.fromordinal(d0.toordinal() + d), SUB, cid, D(a)) for d, a, cid in zip(days, amounts, "ABC")]
    assert split_groups(items, 7, D("200.00")) == groups


@pytest.mark.parametrize("amount,currency,usd", [("1000.00", "INR", "11.83"), ("845.00", "INR", "10.00"),
                                                  ("0.10", "GBP", "0.13"), ("50.00", "USD", "50.00")])
def test_usd_conversion_is_exact_half_up(amount, currency, usd):
    assert to_usd(D(amount), currency, FX, date(2025, 6, 2))[0] == D(usd)


def test_input_errors_and_illegal_submission():
    row, rows = claim("I1", "E1", [("MEALS", JUN, "1000.00", None)])
    with pytest.raises(ExpenseInputError):
        submit(store(), ({**row, "total_amount": D("999.00")}, rows))                  # BR-EX-11 total
    rows[0]["quantity"], rows[0]["unit_amount"] = D("3"), D("333.33")                   # 3 x 333.33 = 999.99
    with pytest.raises(ExpenseInputError):
        submit(store(), (row, rows))
    s = store()
    s.add_claim({**row, "workflow_status": "PENDING_APPROVAL", "first_submitted_at": SUB}, rows)
    with pytest.raises(IllegalTransition):
        submit_expense(s, "I1", CATALOGUE, SUB, "E1", uuid.uuid4())


def test_two_effective_versions_are_a_configuration_error():
    clash = POLICIES + [pol("XPOL-TRAVEL-IN-V2", "TRAVEL", "1.00", "1.00", date(2025, 1, 1))]
    with pytest.raises(PolicyConfigurationError):
        resolve_expense_policy(clash, "TRAVEL", "IN", date(2025, 6, 2))
