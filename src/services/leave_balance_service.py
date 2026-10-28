"""Leave balance ledger rules (BR-LBAL-01..09).

Phase 3 brought forward the pure accrual schedule (DEC-01, RK-01). Phase 5 adds the negative floor (BR-LBAL-08),
carry-forward (BR-LBAL-04), the per-year available balance used at submission (BR-LBAL-07/09), usage postings
(BR-LBAL-05) and snapshot reconciliation (BR-LBAL-06). Everything here is derived from the ledger rows, the
accrual schedule and the open reservations it is given; nothing here writes.
"""
from __future__ import annotations

import calendar as _cal
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from src.common import ids
from src.common.enums import AccrualMethod, LeaveTxnType
from src.common.money import floor_half

ZERO = Decimal("0")
ONE_DP = Decimal("0.1")
CARRY_TYPES = frozenset({LeaveTxnType.CARRY_FORWARD.value, LeaveTxnType.CARRY_FORWARD_EXPIRY.value})


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


def negative_floor(policy: dict) -> Decimal:
    """BR-LBAL-08: the lowest available balance the policy permits (0, or -negative_limit_days)."""
    return -Decimal(policy["negative_limit_days"]) if policy["negative_balance_allowed"] else ZERO


def carry_forward(available_at_year_end: Decimal, policy: dict) -> tuple[Decimal, Decimal]:
    """BR-LBAL-04: (carried into Jan 1, expired). A positive balance carries up to the cap and the excess expires.
    A negative balance carries in full as debt when the policy permits negatives, else nothing (ASM-P4-12)."""
    if available_at_year_end < 0:
        carried = available_at_year_end if policy["negative_balance_allowed"] else ZERO
        return carried.quantize(ONE_DP), ZERO
    carried = min(available_at_year_end, Decimal(policy["carry_forward_cap_days"]))
    return carried.quantize(ONE_DP), (available_at_year_end - carried).quantize(ONE_DP)


def balance_year(leave_balance_id: str) -> int:
    """LBAL-<employee>-<policy>-<yyyy> (AM-A6): the leave year is the last segment."""
    return int(leave_balance_id.rsplit("-", 1)[1])


@dataclass(frozen=True)
class Reservation:
    """The part of an open (PENDING_APPROVAL / ESCALATED_FOR_REVIEW) request that falls in one leave year."""
    request_id: str
    year: int
    quantity: Decimal
    submitted_at: datetime


class BalanceBook:
    """One employee's balances on one policy (BR-LBAL-01): ledger rows of every year, the accrual schedule and
    the open reservations.

    Accrual is taken from the BR-LBAL-03 schedule ("recomputed from the ledger rules", BR-LV-13); posted ACCRUAL
    rows must equal the schedule and `accrual_mismatches` reports any difference as a technical problem.
    """

    def __init__(self, employee: dict, policy: dict, ledger: list[dict], balance_years,
                 reservations: list[Reservation] = ()) -> None:
        self.employee, self.policy = employee, policy
        self.years = frozenset(balance_years)
        self.rows: dict[int, list[dict]] = {}
        for t in ledger:
            self.rows.setdefault(balance_year(t["leave_balance_id"]), []).append(t)
        self.reservations = list(reservations)
        self._schedule: dict[int, list[tuple[date, Decimal]]] = {}

    def schedule(self, year: int) -> list[tuple[date, Decimal]]:
        if year not in self._schedule:
            e = self.employee
            self._schedule[year] = accrual_schedule(self.policy, e["employment_start"], e["employment_end"], year,
                                                    date(year, 12, 31))
        return self._schedule[year]

    def accrued(self, year: int, upto: date) -> Decimal:
        return sum((q for d, q in self.schedule(year) if d <= upto), ZERO)

    def posted(self, year: int, on: date, include_accrual: bool = False) -> Decimal:
        """Ledger rows of that year dated on or before `on` (ACCRUAL rows only when asked)."""
        return sum((t["quantity"] for t in self.rows.get(year, []) if t["txn_date"] <= on
                    and (include_accrual or t["txn_type"] != LeaveTxnType.ACCRUAL.value)), ZERO)

    def reserved(self, year: int, exclude: str | None = None, before: datetime | None = None) -> Decimal:
        """BR-LBAL-07: open reservations of that year (optionally only those submitted before `before`)."""
        return sum((r.quantity for r in self.reservations if r.year == year and r.request_id != exclude
                    and (before is None or r.submitted_at < before)), ZERO)

    def available(self, year: int, on: date, part_start: date | None = None, exclude: str | None = None,
                  before: datetime | None = None) -> Decimal:
        """BR-LBAL-07/09: available_for_validation for one leave year, checked on `on` (the submission date):
        posted ledger as of `on` (the CARRY_FORWARD rows dated Jan 1 included, so carry-forward counts only from
        Jan 1, BR-LBAL-09) + accrual scheduled on or before max(on, part_start) - open reservations of that year.
        Compare against negative_floor(policy) (BR-LBAL-08). A year without a leave_balance row has nothing
        available: there is no balance to post usage to (ASM-P5-06). Phase 7B: carry-forward is never recomputed
        any more; it exists only as the year-end rows of year_end_postings() (replaces ASM-P5-03, AMB-P5-02)."""
        if year not in self.years:
            return ZERO.quantize(ONE_DP)
        upto = on if part_start is None else max(on, part_start)
        return (self.posted(year, on) + self.accrued(year, upto) - self.reserved(year, exclude, before)) \
            .quantize(ONE_DP)

    def year_end_postings(self, year: int, reason: str = "Year-end carry-forward") -> list[dict]:
        """BR-LBAL-04 at the start of `year` (ASM-P7B-05): the previous year's balance at Dec 31 (posted rows,
        its own carry-forward included, plus its full accrual schedule) minus the previous year's reservations
        still open now (treated as if approved, as ASM-P5-03 did). Rows, both dated Jan 1 of `year` in the new
        year's balance: CARRY_FORWARD = that balance (debt only when the policy permits negatives), and
        CARRY_FORWARD_EXPIRY = minus the part above the cap. Nothing when either year has no balance or the
        amount is zero. Unnumbered: the caller assigns LBT ids."""
        if year not in self.years or (year - 1) not in self.years:
            return []
        dec31 = date(year - 1, 12, 31)
        at_year_end = (self.posted(year - 1, dec31) + self.accrued(year - 1, dec31)
                       - self.reserved(year - 1)).quantize(ONE_DP)
        carried, expired = carry_forward(at_year_end, self.policy)
        brought = carried + expired
        bal = ids.leave_balance_id(self.employee["employee_id"], self.policy["leave_policy_id"], year)
        row = {"leave_balance_id": bal, "leave_request_id": None, "txn_date": date(year, 1, 1)}
        rows = []
        if brought != 0:
            rows.append({**row, "txn_type": LeaveTxnType.CARRY_FORWARD.value, "quantity": brought,
                         "reason": f"{reason} from {year - 1}"})
        if expired != 0:
            rows.append({**row, "txn_type": LeaveTxnType.CARRY_FORWARD_EXPIRY.value, "quantity": -expired,
                         "reason": f"{reason}: above the cap of {self.policy['carry_forward_cap_days']} days"})
        return rows

    def accrual_mismatches(self, on: date) -> list[int]:
        """Years whose posted ACCRUAL rows (dated <= on) differ from the schedule (BR-LV-13 technical check)."""
        bad = []
        for year in sorted(self.years):
            posted = sorted((t["txn_date"], t["quantity"]) for t in self.rows.get(year, [])
                            if t["txn_type"] == LeaveTxnType.ACCRUAL.value and t["txn_date"] <= on)
            if posted != [(d, q) for d, q in self.schedule(year) if d <= on]:
                bad.append(year)
        return bad


def usage_postings(request: dict, parts: dict[int, Decimal], on: date, reason: str) -> list[dict]:
    """BR-LBAL-05 + BR-LBAL-09: one USAGE row per leave year of an approved request, dated `on` (the approval
    date; the submission date for legacy rows, ASM-P4-09). Unnumbered: the caller assigns LBT ids."""
    return [{"leave_balance_id": ids.leave_balance_id(request["employee_id"], request["leave_policy_id"], year),
             "leave_request_id": request["leave_request_id"], "txn_type": LeaveTxnType.USAGE.value,
             "quantity": -qty, "txn_date": on, "reason": reason}
            for year, qty in sorted(parts.items())]


def reconcile_snapshot(snapshot: dict, ledger: list[dict]) -> list[str]:
    """BR-LBAL-06: snapshot columns recomputed from the ledger rows of that balance; returns the mismatches.
    A mismatch is reported, never silently corrected."""
    s: dict[str, Decimal] = {}
    for t in ledger:
        s[t["txn_type"]] = s.get(t["txn_type"], ZERO) + t["quantity"]
    expected = {
        "opening_balance": s.get("OPENING", ZERO) + s.get("CARRY_FORWARD", ZERO),
        "accrued": s.get("ACCRUAL", ZERO),
        "adjustments": s.get("ADJUSTMENT", ZERO) + s.get("CARRY_FORWARD_EXPIRY", ZERO),
        "used": -(s.get("USAGE", ZERO) + s.get("USAGE_REVERSAL", ZERO)),
        "available_balance": sum(s.values(), ZERO),
    }
    return [f"{k} {snapshot[k]} != ledger {v}" for k, v in expected.items() if snapshot[k] != v]
