"""BR-CAL-01..05 parametrised matrix (docs/05 section 1): weekends per country, holidays per country, both ends
inclusive, holidays on weekends not substituted, half-day quantities, half-days on non-business days, and the
per-year split of BR-LBAL-09. Calendar and dates in tests/unit/leave_world.py. No database."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.services.calendar_service import (
    HolidayCalendar,
    half_days_on_non_business_days,
    quantity_by_year,
    requested_quantity,
)
from tests.unit.leave_world import CAL

D = Decimal


@pytest.mark.parametrize("country,start,end,expected", [
    ("IN", date(2025, 3, 3), date(2025, 3, 7), 5),        # Mon..Fri, both ends inclusive
    ("IN", date(2025, 3, 3), date(2025, 3, 3), 1),        # single day
    ("IN", date(2025, 3, 8), date(2025, 3, 9), 0),        # Sat..Sun only
    ("IN", date(2025, 3, 7), date(2025, 3, 10), 2),       # Fri..Mon across a weekend
    ("IN", date(2025, 3, 10), date(2025, 3, 7), 0),       # end before start
    ("IN", date(2025, 8, 11), date(2025, 8, 15), 4),      # IN holiday Fri 15 Aug
    ("US", date(2025, 8, 11), date(2025, 8, 15), 5),      # ...is not a US holiday (per country, BR-CAL-02)
    ("US", date(2025, 6, 30), date(2025, 7, 4), 4),       # US holiday Fri 4 Jul
    ("US", date(2026, 6, 29), date(2026, 7, 3), 5),       # 4 Jul 2026 is a Saturday: not substituted (ASM-005)
    ("US", date(2026, 7, 3), date(2026, 7, 6), 2),
    ("GB", date(2025, 12, 22), date(2025, 12, 26), 3),    # GB 25 and 26 Dec
    ("IN", date(2025, 12, 22), date(2025, 12, 26), 5),
    ("GB", date(2025, 12, 29), date(2026, 1, 2), 4),      # GB 1 Jan holiday
    ("IN", date(2025, 12, 29), date(2026, 1, 2), 5),      # no IN holiday on 1 Jan in this world
])
def test_business_day_count(country, start, end, expected):
    assert CAL.business_day_count(start, end, country) == expected


def test_weekend_days_are_configurable_per_country():
    """BR-CAL-01: a Friday/Saturday weekend counts Sunday as a business day."""
    cal = HolidayCalendar({"XX": {5, 6}}, {})
    assert cal.business_day_count(date(2025, 3, 3), date(2025, 3, 9), "XX") == 5
    assert not cal.is_business_day(date(2025, 3, 7), "XX") and cal.is_business_day(date(2025, 3, 9), "XX")


@pytest.mark.parametrize("days,sh,eh,expected", [
    (5, False, False, "5.0"), (5, True, False, "4.5"), (5, False, True, "4.5"), (5, True, True, "4.0"),
    (1, True, False, "0.5"), (1, False, True, "0.5"), (1, False, False, "1.0"), (0, False, False, "0.0"),
])
def test_requested_quantity(days, sh, eh, expected):
    """BR-CAL-04: business days minus 0.5 per half-day flag."""
    assert requested_quantity(days, sh, eh) == D(expected)


@pytest.mark.parametrize("country,start,end,sh,eh,expected", [
    ("IN", date(2025, 3, 8), date(2025, 3, 12), True, False, [date(2025, 3, 8)]),      # Saturday start
    ("IN", date(2025, 3, 10), date(2025, 3, 16), False, True, [date(2025, 3, 16)]),    # Sunday end
    ("GB", date(2025, 12, 22), date(2025, 12, 25), False, True, [date(2025, 12, 25)]),  # GB holiday
    ("IN", date(2025, 12, 22), date(2025, 12, 25), False, True, []),                    # business day in IN
    ("IN", date(2025, 3, 10), date(2025, 3, 12), True, True, []),
    ("IN", date(2025, 3, 10), date(2025, 3, 12), False, False, []),
])
def test_half_day_on_non_business_day(country, start, end, sh, eh, expected):
    """BR-CAL-04 / ASM-008: a flag on a weekend or holiday is reported (HALF_DAY_ON_NON_BUSINESS_DAY)."""
    assert half_days_on_non_business_days(CAL, start, end, country, sh, eh) == expected


@pytest.mark.parametrize("country,start,end,sh,eh,expected", [
    ("IN", date(2025, 12, 29), date(2026, 1, 2), False, False, {2025: "3.0", 2026: "2.0"}),
    ("IN", date(2025, 12, 29), date(2026, 1, 2), True, False, {2025: "2.5", 2026: "2.0"}),   # start half: old year
    ("IN", date(2025, 12, 29), date(2026, 1, 2), False, True, {2025: "3.0", 2026: "1.5"}),   # end half: new year
    ("GB", date(2025, 12, 29), date(2026, 1, 2), False, False, {2025: "3.0", 2026: "1.0"}),
    ("US", date(2025, 12, 31), date(2026, 1, 1), False, False, {2025: "1.0"}),               # 1 Jan US holiday
    ("IN", date(2025, 3, 3), date(2025, 3, 7), True, True, {2025: "4.0"}),
])
def test_quantity_by_year(country, start, end, sh, eh, expected):
    """BR-LBAL-09: the quantity splits by leave year; a year with nothing in it is left out."""
    parts = quantity_by_year(CAL, start, end, country, sh, eh)
    assert parts == {y: D(q) for y, q in expected.items()}
    assert sum(parts.values()) == max(requested_quantity(CAL.business_day_count(start, end, country), sh, eh), D(0))
