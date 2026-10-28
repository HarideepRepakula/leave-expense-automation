"""S2 leave balances (docs/07 section 2, BR-LBAL-01..03).

Phase 3 posts OPENING (2025, raw draw within the carry-forward cap, ASM-007) and ACCRUAL from the shared
accrual schedule in src/services/leave_balance_service.py, and builds the 2025 and 2026 snapshots from them.
CARRY_FORWARD on 2026-01-01 needs 2025 USAGE, which only exists once the Phase 7 engine approves requests;
it is posted from Phase 7 on (AMB-P3-02). UNPAID has no balance (ASM-047), so it gets no snapshot row.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal

from src.common import ids
from src.common.enums import AccrualMethod, LeaveTxnType
from src.common.rng import RngStreams
from src.data.stages import GenParams
from src.services.leave_balance_service import accrual_schedule

CORRELATION_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:lea:generator")
TXN_ORDER = {LeaveTxnType.OPENING.value: 0, LeaveTxnType.CARRY_FORWARD.value: 1, LeaveTxnType.ACCRUAL.value: 2,
             LeaveTxnType.USAGE.value: 3}
ZERO = Decimal("0.0")


def applicable_policies(employee: dict, policies: list[dict]) -> list[dict]:
    """Balance-carrying policies for an employee's country (BR-POL-03); UNPAID excluded (ASM-047)."""
    return [
        pol for pol in policies
        if pol["accrual_method"] != AccrualMethod.NONE and pol["country_scope"] in (employee["country"], "ALL")
    ]


def build_balances(p: GenParams, streams: RngStreams, employees: list[dict], policies: list[dict],
                   years: list[int]) -> dict[str, list[dict]]:
    rng = streams.get("balances")
    snapshots: list[dict] = []
    postings: list[dict] = []
    as_of_ts = datetime.combine(p.as_of, time(0, 0), tzinfo=timezone.utc)
    for emp in employees:  # employee_id order
        start, end = emp["employment_start"], emp["employment_end"]
        for pol in sorted(applicable_policies(emp, policies), key=lambda r: r["leave_policy_id"]):
            for year in years:
                if year > p.as_of.year or start > date(year, 12, 31) or (end and end < date(year, 1, 1)):
                    continue
                lbal = ids.leave_balance_id(emp["employee_id"], pol["leave_policy_id"], year)
                opening = ZERO
                cap = pol["carry_forward_cap_days"]
                if year == p.window_start.year and start < p.window_start and cap > 0:
                    opening = (Decimal(int(rng.integers(0, int(cap * 2) + 1))) / 2).quantize(Decimal("0.1"))
                    if opening > 0:
                        postings.append({"leave_balance_id": lbal, "txn_type": LeaveTxnType.OPENING.value,
                                         "quantity": opening, "txn_date": p.window_start,
                                         "reason": f"Opening balance {year}"})
                accrued = ZERO
                for when, qty in accrual_schedule(pol, start, end, year, p.as_of):
                    accrued += qty
                    reason = "Annual grant" if pol["accrual_method"] == AccrualMethod.ANNUAL_GRANT else "Monthly accrual"
                    postings.append({"leave_balance_id": lbal, "txn_type": LeaveTxnType.ACCRUAL.value,
                                     "quantity": qty, "txn_date": when, "reason": reason})
                snapshots.append({
                    "leave_balance_id": lbal,
                    "employee_id": emp["employee_id"],
                    "leave_policy_id": pol["leave_policy_id"],
                    "leave_year": year,
                    "opening_balance": opening,
                    "accrued": accrued.quantize(Decimal("0.1")),
                    "adjustments": ZERO,
                    "used": ZERO,
                    "available_balance": (opening + accrued).quantize(Decimal("0.1")),  # GENERATED in the DB
                    "last_recalculated_at": as_of_ts,
                })

    return {"leave_balance": snapshots, "leave_balance_transaction": number_transactions(postings)}


def number_transactions(postings: list[dict]) -> list[dict]:
    """LBT counters per year of txn_date, after a stable sort (docs/07 section 3). Used by S2 and again by S5
    after legacy USAGE postings are added, so ledger ids always follow date order."""
    postings = sorted(postings, key=lambda r: (r["txn_date"], r["leave_balance_id"], TXN_ORDER[r["txn_type"]],
                                               r.get("leave_request_id") or ""))
    counters: dict[int, int] = {}
    transactions = []
    for r in postings:
        year = r["txn_date"].year
        counters[year] = counters.get(year, 0) + 1
        txn_id = ids.leave_balance_txn_id(year, counters[year])
        transactions.append({
            "transaction_id": txn_id,
            "leave_balance_id": r["leave_balance_id"],
            "leave_request_id": r.get("leave_request_id"),
            "txn_type": r["txn_type"],
            "quantity": r["quantity"],
            "txn_date": r["txn_date"],
            "posted_at": datetime.combine(r["txn_date"], time(0, 0), tzinfo=timezone.utc),
            "reason": r["reason"],
            "correlation_id": uuid.uuid5(CORRELATION_NAMESPACE, txn_id),
        })
    return transactions


def ledger_index(transactions: list[dict]) -> dict[str, list[tuple[date, Decimal]]]:
    """leave_balance_id -> postings sorted by date, for 'available on a date' lookups."""
    index: dict[str, list[tuple[date, Decimal]]] = {}
    for t in transactions:
        index.setdefault(t["leave_balance_id"], []).append((t["txn_date"], t["quantity"]))
    for v in index.values():
        v.sort()
    return index
