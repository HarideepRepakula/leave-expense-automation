"""Leave balance ledger rules (BR-LBAL-01..03).

Phase 3 brings forward the pure accrual schedule so the generator does not re-implement it (DEC-01, RK-01).
Phase 5 adds carry-forward (BR-LBAL-04), usage postings, snapshot reconciliation and the DB-backed service.
"""
from __future__ import annotations

import calendar as _cal
from datetime import date
from decimal import Decimal

from src.common.enums import AccrualMethod
from src.common.money import floor_half


def monthly_accrual(policy: dict) -> Decimal:
    """BR-LBAL-03: entitlement / 12 rounded down to 0.5."""
    return floor_half(Decimal(policy["annual_entitlement_days"]) / 12)


def accrual_schedule(
    policy: dict, employment_start: date, employment_end: date | None, year: int, as_of: date
) -> list[tuple[date, Decimal]]:
    """ACCRUAL postings for one (employee, policy, leave year), dated, non-zero, none after `as_of`.

    MONTHLY: on the 1st of each month; a joiner's first month is the monthly amount x remaining_days /
    days_in_month, rounded down to 0.5, dated on the joining date. No accrual for months that start after
    employment_end (BR-LBAL-03).
    ANNUAL_GRANT: full entitlement on Jan 1; a joiner during the year gets entitlement x remaining days of
    the year / days in the year, rounded down to 0.5, dated on the joining date (ASM-006, ASM-P3-14).
    NONE: no accrual.
    """
    method = policy["accrual_method"]
    postings: list[tuple[date, Decimal]] = []
    if method == AccrualMethod.NONE:
        return postings

    if method == AccrualMethod.ANNUAL_GRANT:
        year_start, year_end = date(year, 1, 1), date(year, 12, 31)
        if employment_start > year_end or (employment_end is not None and employment_end < year_start):
            return postings
        if employment_start <= year_start:
            when, qty = year_start, floor_half(Decimal(policy["annual_entitlement_days"]))
        else:
            days_in_year = (year_end - year_start).days + 1
            remaining = (year_end - employment_start).days + 1
            when = employment_start
            qty = floor_half(Decimal(policy["annual_entitlement_days"]) * remaining / days_in_year)
        if when <= as_of and qty > 0:
            postings.append((when, qty))
        return postings

    if method != AccrualMethod.MONTHLY:
        raise ValueError(f"unknown accrual method {method}")
    per_month = monthly_accrual(policy)
    for month in range(1, 13):
        month_start = date(year, month, 1)
        days_in_month = _cal.monthrange(year, month)[1]
        month_end = date(year, month, days_in_month)
        if employment_start > month_end:
            continue
        if employment_end is not None and month_start > employment_end:
            continue
        if employment_start <= month_start:
            when, qty = month_start, per_month
        else:
            remaining = (month_end - employment_start).days + 1
            when, qty = employment_start, floor_half(per_month * remaining / days_in_month)
        if when <= as_of and qty > 0:
            postings.append((when, qty))
    return postings
