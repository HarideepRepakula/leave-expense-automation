"""Leave balance ledger rules (docs/05 BR-LBAL-03..09): negative floor, carry-forward, the per-year available
balance at submission, reservations, usage postings and snapshot reconciliation. World: tests/unit/leave_world.py
(E1 IN: opening 4.0, 1.5 per month, cap 10). No database."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from src.common import ids
from src.services.leave_balance_service import (
    BalanceBook,
    Reservation,
    carry_forward,
    negative_floor,
    reconcile_snapshot,
    usage_postings,
)
from tests.unit.leave_world import ANNUAL_IN, ANNUAL_US, E1, E2, E4, POLICIES, new_store, txn

D = Decimal
T0 = datetime(2025, 3, 1, tzinfo=timezone.utc)


def book(emp: str, pol: str, extra: list[dict] = (), drop: dict | None = None,
         reservations: list[Reservation] = ()) -> BalanceBook:
    s = new_store()
    rows = [t for t in s.ledger[(emp, pol)] if t is not drop] + list(extra)
    return BalanceBook(s.employees[emp], s.policies[pol], rows, s.years[(emp, pol)], reservations)


def lbal(emp: str, pol: str, year: int) -> str:
    return ids.leave_balance_id(emp, pol, year)


@pytest.mark.parametrize("pol,expected", [(ANNUAL_IN, "0"), (ANNUAL_US, "-3.0")])
def test_negative_floor(pol, expected):
    assert negative_floor(POLICIES[pol]) == D(expected)


@pytest.mark.parametrize("pol,available,carried,expired", [
    (ANNUAL_IN, "7.5", "7.5", "0.0"),     # under the cap: all carried
    (ANNUAL_IN, "10.0", "10.0", "0.0"),   # exactly the cap
    (ANNUAL_IN, "22.0", "10.0", "12.0"),  # above the cap: excess expires
    (ANNUAL_US, "-2.0", "-2.0", "0.0"),   # negative permitted: debt carries in full
    (ANNUAL_IN, "-3.0", "0.0", "0.0"),    # negative not permitted: nothing carries (ASM-P4-12)
    ("LPOL-SICK-ALL-V1", "6.0", "0.0", "6.0"),   # cap 0
])
def test_carry_forward(pol, available, carried, expired):
    """BR-LBAL-04."""
    assert carry_forward(D(available), POLICIES[pol]) == (D(carried), D(expired))


def test_available_uses_posted_ledger_on_the_submission_date():
    assert book(E1, ANNUAL_IN).available(2025, date(2025, 3, 10)) == D("8.5")   # 4.0 + 3 x 1.5


def test_available_counts_accrual_scheduled_up_to_the_part_start():
    """BR-LBAL-09: posted on 10 Mar + accrual scheduled on or before the part's start (1 Apr and 1 May)."""
    assert book(E1, ANNUAL_IN).available(2025, date(2025, 3, 10), part_start=date(2025, 5, 5)) == D("11.5")


def test_next_year_part_at_submission_counts_only_its_scheduled_accrual():
    """Submitted 10 Dec 2025 for January 2026: carry-forward unknown (not counted), Jan 1 accrual counted."""
    b = book(E1, ANNUAL_IN)
    assert b.carry_in(2026, date(2025, 12, 10)) == 0
    assert b.available(2026, date(2025, 12, 10), part_start=date(2026, 1, 1)) == D("1.5")
    assert b.available(2026, date(2025, 12, 10), part_start=date(2026, 2, 2)) == D("3.0")


def test_carry_forward_is_recomputed_after_january_first():
    """BR-LV-13: no CARRY_FORWARD row posted yet, so it is recomputed: min(4 + 18 - 0, cap 10) = 10."""
    b = book(E1, ANNUAL_IN)
    assert b.carry_in(2026, date(2026, 2, 2)) == D("10.0")
    assert b.available(2026, date(2026, 2, 2)) == D("13.0")


def test_posted_carry_forward_row_is_used_instead_of_recomputing():
    b = book(E1, ANNUAL_IN, extra=[txn(lbal(E1, ANNUAL_IN, 2026), "CARRY_FORWARD", D("6.0"), date(2026, 1, 1))])
    assert b.carry_in(2026, date(2026, 2, 2)) == 0
    assert b.available(2026, date(2026, 2, 2)) == D("9.0")


def test_carry_forward_follows_prior_year_usage_and_open_reservations():
    used = txn(lbal(E1, ANNUAL_IN, 2025), "USAGE", D("-15.0"), date(2025, 6, 2), "LVE-2025-000001")
    assert book(E1, ANNUAL_IN, extra=[used]).available(2026, date(2026, 2, 2)) == D("10.0")   # 7 carried + 3
    pending = [Reservation("LVE-2025-000002", 2025, D("16.0"), T0)]
    assert book(E1, ANNUAL_IN, reservations=pending).carry_in(2026, date(2026, 2, 2)) == D("6.0")   # ASM-P5-03


@pytest.mark.parametrize("emp,pol,usage,expected", [
    (E2, ANNUAL_US, "-16.0", "-1.0"),   # 2 + 12 - 16 = -2 carried as debt, + Jan accrual 1.0
    (E1, ANNUAL_IN, "-25.0", "1.5"),    # 4 + 18 - 25 = -3 does not carry, + Jan accrual 1.5
])
def test_negative_carry_forward(emp, pol, usage, expected):
    used = txn(lbal(emp, pol, 2025), "USAGE", D(usage), date(2025, 6, 2), "LVE-2025-000001")
    assert book(emp, pol, extra=[used]).available(2026, date(2026, 1, 5)) == D(expected)


def test_reservations_reduce_availability_except_the_request_itself():
    """BR-LBAL-07: open requests reserve; a request never reserves against itself."""
    res = [Reservation("R1", 2025, D("5.0"), T0), Reservation("R2", 2026, D("2.0"), T0)]
    b = book(E1, ANNUAL_IN, reservations=res)
    assert b.available(2025, date(2025, 3, 10)) == D("3.5")
    assert b.available(2025, date(2025, 3, 10), exclude="R1") == D("8.5")
    assert b.available(2025, date(2025, 3, 10), before=T0) == D("8.5")   # only reservations submitted earlier


def test_year_without_a_balance_row_has_nothing_available():
    """ASM-P5-06: E4 left on 2025-09-30, so there is no 2026 balance."""
    assert book(E4, ANNUAL_IN).available(2026, date(2026, 1, 5)) == 0


def test_posted_accrual_must_match_the_schedule():
    """BR-LV-13: a missing ACCRUAL row is reported for its year (a technical failure, not a business code)."""
    s = new_store()
    feb = next(t for t in s.ledger[(E1, ANNUAL_IN)]
               if t["txn_type"] == "ACCRUAL" and t["txn_date"] == date(2025, 2, 1))
    assert book(E1, ANNUAL_IN).accrual_mismatches(date(2026, 10, 22)) == []
    gap = BalanceBook(s.employees[E1], s.policies[ANNUAL_IN], [t for t in s.ledger[(E1, ANNUAL_IN)] if t is not feb],
                      s.years[(E1, ANNUAL_IN)])
    assert gap.accrual_mismatches(date(2025, 3, 10)) == [2025]
    assert gap.accrual_mismatches(date(2025, 1, 31)) == []      # not yet due


def test_usage_postings_split_by_year():
    """BR-LBAL-05 + BR-LBAL-09: one negative USAGE row per leave year, dated on the given day."""
    r = {"leave_request_id": "LVE-2025-000009", "employee_id": E1, "leave_policy_id": ANNUAL_IN}
    rows = usage_postings(r, {2026: D("2.0"), 2025: D("3.0")}, date(2025, 12, 12), "approved")
    assert [(t["leave_balance_id"], t["quantity"], t["txn_type"]) for t in rows] == [
        (lbal(E1, ANNUAL_IN, 2025), D("-3.0"), "USAGE"), (lbal(E1, ANNUAL_IN, 2026), D("-2.0"), "USAGE")]
    assert all(t["txn_date"] == date(2025, 12, 12) and t["leave_request_id"] == "LVE-2025-000009" for t in rows)


def test_reconcile_snapshot():
    """BR-LBAL-06: the snapshot equals the ledger; a mismatch is reported, never corrected."""
    rows = [txn("B", "OPENING", D("4.0"), date(2025, 1, 1)), txn("B", "ACCRUAL", D("1.5"), date(2025, 1, 1)),
            txn("B", "USAGE", D("-2.0"), date(2025, 2, 3), "R")]
    good = {"opening_balance": D("4.0"), "accrued": D("1.5"), "adjustments": D("0"), "used": D("2.0"),
            "available_balance": D("3.5")}
    assert reconcile_snapshot(good, rows) == []
    assert reconcile_snapshot({**good, "used": D("1.0")}, rows) == ["used 1.0 != ledger 2.0"]
