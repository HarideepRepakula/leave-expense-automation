"""Hand-built cases for the pure rule functions brought forward in Phase 3 (DEC-37).
Phase 5 extends these into the full parametrised matrix (BR-CAL, BR-LBAL)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.common.money import floor_half, round_to_unit
from src.services.calendar_service import HolidayCalendar, quantity_by_year, requested_quantity
from src.services.leave_balance_service import accrual_schedule, monthly_accrual
from src.services.policy_resolver import PolicyResolutionError, resolve_version

CAL = HolidayCalendar({"IN": {6, 7}}, {"IN": {date(2025, 1, 1), date(2025, 1, 26), date(2025, 12, 25)}})
ANNUAL_IN = {"annual_entitlement_days": Decimal("18.0"), "accrual_method": "MONTHLY"}
ANNUAL_US = {"annual_entitlement_days": Decimal("15.0"), "accrual_method": "MONTHLY"}
SICK = {"annual_entitlement_days": Decimal("10.0"), "accrual_method": "ANNUAL_GRANT"}


@pytest.mark.parametrize("start,end,expected", [
    (date(2025, 1, 6), date(2025, 1, 10), 5),     # Mon-Fri
    (date(2025, 1, 10), date(2025, 1, 13), 2),    # Fri-Mon spans a weekend
    (date(2024, 12, 30), date(2025, 1, 3), 4),    # New Year's Day holiday inside
    (date(2025, 1, 25), date(2025, 1, 26), 0),    # Saturday + Sunday holiday
    (date(2025, 1, 10), date(2025, 1, 9), 0),     # end before start
])
def test_business_day_count(start, end, expected):
    assert CAL.business_day_count(start, end, "IN") == expected


def test_nth_and_next_business_day():
    assert CAL.next_business_day(date(2025, 1, 25), "IN") == date(2025, 1, 27)
    assert CAL.nth_business_day(date(2024, 12, 31), 2, "IN") == date(2025, 1, 2)


def test_requested_quantity_and_year_split():
    assert requested_quantity(3, True, False) == Decimal("2.5")
    assert requested_quantity(1, False, True) == Decimal("0.5")
    split = quantity_by_year(CAL, date(2025, 12, 29), date(2026, 1, 2), "IN", True, False)
    assert split == {2025: Decimal("2.5"), 2026: Decimal("2.0")}


def test_rounding_helpers():
    assert floor_half(Decimal("1.25")) == Decimal("1.0")
    assert floor_half(Decimal("2.083")) == Decimal("2.0")
    assert round_to_unit(Decimal("6225"), 10) == Decimal("6230.00")
    assert round_to_unit(Decimal("59.25"), 1) == Decimal("59.00")


def test_monthly_accrual_amounts():
    assert monthly_accrual(ANNUAL_IN) == Decimal("1.5")
    assert monthly_accrual(ANNUAL_US) == Decimal("1.0")  # 15/12 = 1.25 rounded DOWN to 0.5 (BR-LBAL-03)


def test_accrual_full_year_and_as_of_cutoff():
    full = accrual_schedule(ANNUAL_IN, date(2020, 1, 1), None, 2025, date(2026, 10, 22))
    assert len(full) == 12 and sum(q for _, q in full) == Decimal("18.0")
    cut = accrual_schedule(ANNUAL_IN, date(2020, 1, 1), None, 2026, date(2026, 10, 22))
    assert [d.month for d, _ in cut] == list(range(1, 11))


def test_accrual_mid_month_joiner_and_leaver():
    # joins 16 Jan 2025: 16 of 31 days x 1.5 = 0.77 -> 0.5, dated on the joining date
    joined = accrual_schedule(ANNUAL_IN, date(2025, 1, 16), None, 2025, date(2026, 10, 22))
    assert joined[0] == (date(2025, 1, 16), Decimal("0.5"))
    assert len(joined) == 12
    # leaves 10 Mar 2025: Jan, Feb, Mar accrue (Mar started before the end date); April onwards do not
    left = accrual_schedule(ANNUAL_IN, date(2020, 1, 1), date(2025, 3, 10), 2025, date(2026, 10, 22))
    assert [d for d, _ in left] == [date(2025, 1, 1), date(2025, 2, 1), date(2025, 3, 1)]


def test_annual_grant():
    assert accrual_schedule(SICK, date(2020, 1, 1), None, 2025, date(2026, 10, 22)) == [
        (date(2025, 1, 1), Decimal("10.0"))]
    # joins 2 Jul 2025: 183 of 365 days x 10 = 5.01 -> 5.0
    assert accrual_schedule(SICK, date(2025, 7, 2), None, 2025, date(2026, 10, 22)) == [
        (date(2025, 7, 2), Decimal("5.0"))]


def test_resolve_version_by_effective_date():
    rows = [
        {"policy_family": "XPOL-MEALS-IN", "id": "V1", "is_active": True,
         "effective_start": date(2025, 1, 1), "effective_end": date(2025, 12, 31)},
        {"policy_family": "XPOL-MEALS-IN", "id": "V2", "is_active": True,
         "effective_start": date(2026, 1, 1), "effective_end": None},
    ]
    assert resolve_version(rows, "XPOL-MEALS-IN", date(2025, 12, 31))["id"] == "V1"
    assert resolve_version(rows, "XPOL-MEALS-IN", date(2026, 1, 1))["id"] == "V2"
    with pytest.raises(PolicyResolutionError):
        resolve_version(rows, "XPOL-MEALS-IN", date(2024, 12, 31))
