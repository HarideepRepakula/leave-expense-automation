"""Business-day calendar (BR-CAL-01..05).

Pure functions over a HolidayCalendar built from country_holiday rows and configured weekend days.
Brought forward from Phase 5 so the generator and the services share one implementation (DEC-01, RK-01);
Phase 5 adds the full parametrised test matrix.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

HALF = Decimal("0.5")


class HolidayCalendar:
    def __init__(self, weekend_days: dict[str, set[int]], holidays: dict[str, set[date]]) -> None:
        self._weekend = {c: frozenset(days) for c, days in weekend_days.items()}
        self._holidays = {c: frozenset(days) for c, days in holidays.items()}

    @classmethod
    def from_rows(cls, weekend_days: dict[str, list[int]], holiday_rows: list[dict]) -> "HolidayCalendar":
        holidays: dict[str, set[date]] = {c: set() for c in weekend_days}
        for row in holiday_rows:
            holidays.setdefault(row["country"], set()).add(row["holiday_date"])
        return cls({c: set(d) for c, d in weekend_days.items()}, holidays)

    def is_business_day(self, d: date, country: str) -> bool:
        """BR-CAL-01/02: not a weekend day and not a holiday of that country."""
        return d.isoweekday() not in self._weekend[country] and d not in self._holidays.get(country, ())

    def is_holiday(self, d: date, country: str) -> bool:
        return d in self._holidays.get(country, ())

    def business_day_count(self, start: date, end: date, country: str) -> int:
        """BR-CAL-03: business days in [start, end], both ends inclusive; 0 when end < start."""
        count = 0
        d = start
        while d <= end:
            if self.is_business_day(d, country):
                count += 1
            d += timedelta(days=1)
        return count

    def next_business_day(self, d: date, country: str) -> date:
        """The first business day on or after d."""
        while not self.is_business_day(d, country):
            d += timedelta(days=1)
        return d

    def nth_business_day(self, start: date, n: int, country: str) -> date:
        """Date of the n-th business day counting from `start` (a business day counts as the first)."""
        if n < 1:
            raise ValueError("n must be >= 1")
        d = self.next_business_day(start, country)
        seen = 1
        while seen < n:
            d += timedelta(days=1)
            if self.is_business_day(d, country):
                seen += 1
        return d


def requested_quantity(business_days: int, start_half_day: bool, end_half_day: bool) -> Decimal:
    """BR-CAL-04: business days minus 0.5 per half-day flag."""
    return (Decimal(business_days) - HALF * int(start_half_day) - HALF * int(end_half_day)).quantize(Decimal("0.1"))


def half_days_on_non_business_days(calendar: HolidayCalendar, start: date, end: date, country: str,
                                   start_half_day: bool, end_half_day: bool) -> list[date]:
    """BR-CAL-04 / ASM-008: dates carrying a half-day flag that are weekends or holidays (a correctable error)."""
    flagged = sorted({d for d, flag in ((start, start_half_day), (end, end_half_day)) if flag})
    return [d for d in flagged if not calendar.is_business_day(d, country)]


def quantity_by_year(
    calendar: HolidayCalendar, start: date, end: date, country: str, start_half_day: bool, end_half_day: bool
) -> dict[int, Decimal]:
    """BR-LBAL-09: split a request's quantity by leave year. A half-day flag reduces the year it falls in."""
    result: dict[int, Decimal] = {}
    for year in range(start.year, end.year + 1):
        seg_start = max(start, date(year, 1, 1))
        seg_end = min(end, date(year, 12, 31))
        days = calendar.business_day_count(seg_start, seg_end, country)
        qty = requested_quantity(days, start_half_day and seg_start == start, end_half_day and seg_end == end)
        if qty > 0:
            result[year] = qty
    return result
