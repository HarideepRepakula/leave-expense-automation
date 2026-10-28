"""A small hand-built world for the Phase 5 leave service tests (synthetic values; no database).

Calendar: Sat/Sun weekends; holidays IN 2025-08-15 (Fri), IN 2026-01-26 (Mon), US 2025-07-04 (Fri),
US 2026-07-04 (Sat, not substituted), US 2026-01-01 (Thu), GB 2025-12-25 (Thu), GB 2025-12-26 (Fri),
GB 2026-01-01 (Thu). IN has no Jan 1 holiday here.
Employees: E1 IN since 2022 (2025 opening 4.0), E2 US since 2020 (opening 2.0), E3 IN joined 2025-03-10,
E4 IN left 2025-09-30, E5 GB since 2019 (opening 0).
Policies: ANNUAL-IN 1.5/month cap 10 no negatives; ANNUAL-US 1.0/month cap 5 negatives to -3; ANNUAL-GB-V1
2.0/month, effective until 2025-06-30 only; SICK-ALL grant 10 on Jan 1, certificate above 3; UNPAID-ALL cap 30.
The ledger is OPENING (2025) + the accrual schedule up to AS_OF, exactly what stage S2 posts.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import yaml

from src.common import ids
from src.services.calendar_service import HolidayCalendar
from src.services.exception_service import ExceptionCatalogue
from src.services.leave_balance_service import accrual_schedule
from src.services.leave_request_service import InMemoryLeaveStore, submit_leave

ROOT = Path(__file__).resolve().parents[2]
AS_OF = date(2026, 10, 22)
WEEKEND = {"IN": [6, 7], "US": [6, 7], "GB": [6, 7]}
HOLIDAYS = [("IN", date(2025, 8, 15)), ("IN", date(2026, 1, 26)), ("US", date(2025, 7, 4)), ("US", date(2026, 7, 4)),
            ("US", date(2026, 1, 1)), ("GB", date(2025, 12, 25)), ("GB", date(2025, 12, 26)), ("GB", date(2026, 1, 1))]
CAL = HolidayCalendar.from_rows(WEEKEND, [{"country": c, "holiday_date": d} for c, d in HOLIDAYS])
CATALOGUE = ExceptionCatalogue.from_config(
    yaml.safe_load((ROOT / "config" / "exception_codes.yaml").read_text(encoding="utf-8")))
D = Decimal


def policy(pid: str, leave_type: str, scope: str, entitlement: str, method: str, cap: str = "0.0",
           negative: bool = False, limit: str = "0.0", cert: str | None = None, max_days: str | None = None,
           end: date | None = None) -> dict:
    return {"leave_policy_id": pid, "policy_family": pid.rsplit("-V", 1)[0], "leave_type": leave_type,
            "country_scope": scope, "annual_entitlement_days": D(entitlement), "accrual_method": method,
            "carry_forward_cap_days": D(cap), "negative_balance_allowed": negative, "negative_limit_days": D(limit),
            "min_service_days": 0, "requires_medical_cert_over_days": None if cert is None else D(cert),
            "max_days_per_year": None if max_days is None else D(max_days), "effective_start": date(2025, 1, 1),
            "effective_end": end, "is_active": True}


POLICIES = {p["leave_policy_id"]: p for p in [
    policy("LPOL-ANNUAL-IN-V1", "ANNUAL", "IN", "18.0", "MONTHLY", cap="10.0"),
    policy("LPOL-ANNUAL-US-V1", "ANNUAL", "US", "15.0", "MONTHLY", cap="5.0", negative=True, limit="3.0"),
    policy("LPOL-ANNUAL-GB-V1", "ANNUAL", "GB", "25.0", "MONTHLY", cap="5.0", end=date(2025, 6, 30)),
    policy("LPOL-SICK-ALL-V1", "SICK", "ALL", "10.0", "ANNUAL_GRANT", cert="3.0"),
    policy("LPOL-UNPAID-ALL-V1", "UNPAID", "ALL", "0.0", "NONE", max_days="30.0"),
]}
ANNUAL_IN, ANNUAL_US, ANNUAL_GB, SICK, UNPAID = POLICIES


def employee(eid: str, country: str, start: date, end: date | None = None) -> dict:
    return {"employee_id": eid, "country": country, "employment_start": start, "employment_end": end}


E1, E2, E3, E4, E5 = (f"EMP-00000{i}" for i in range(1, 6))
EMPLOYEES = {e["employee_id"]: e for e in [
    employee(E1, "IN", date(2022, 6, 15)), employee(E2, "US", date(2020, 1, 1)),
    employee(E3, "IN", date(2025, 3, 10)), employee(E4, "IN", date(2018, 1, 1), date(2025, 9, 30)),
    employee(E5, "GB", date(2019, 1, 1)),
]}
OPENING = {(E1, ANNUAL_IN): D("4.0"), (E2, ANNUAL_US): D("2.0")}


def txn(lbal: str, txn_type: str, qty: Decimal, on: date, request_id: str | None = None) -> dict:
    return {"leave_balance_id": lbal, "txn_type": txn_type, "quantity": qty, "txn_date": on,
            "leave_request_id": request_id}


def ledger_and_balances() -> tuple[list[dict], list[dict]]:
    rows, balances = [], []
    for e in EMPLOYEES.values():
        for pol in POLICIES.values():
            if pol["accrual_method"] == "NONE" or pol["country_scope"] not in (e["country"], "ALL"):
                continue
            for year in (2025, 2026):
                if e["employment_start"] > date(year, 12, 31) or \
                        (e["employment_end"] is not None and e["employment_end"] < date(year, 1, 1)):
                    continue
                lbal = ids.leave_balance_id(e["employee_id"], pol["leave_policy_id"], year)
                balances.append({"leave_balance_id": lbal, "employee_id": e["employee_id"],
                                 "leave_policy_id": pol["leave_policy_id"], "leave_year": year})
                opening = OPENING.get((e["employee_id"], pol["leave_policy_id"]))
                if year == 2025 and opening:
                    rows.append(txn(lbal, "OPENING", opening, date(2025, 1, 1)))
                for d, q in accrual_schedule(pol, e["employment_start"], e["employment_end"], year, AS_OF):
                    rows.append(txn(lbal, "ACCRUAL", q, d))
    return rows, balances


def new_store() -> InMemoryLeaveStore:
    rows, balances = ledger_and_balances()
    return InMemoryLeaveStore(EMPLOYEES, POLICIES, CAL, rows, balances)


def at(y: int, m: int, d: int, hour: int = 9) -> datetime:
    return datetime(y, m, d, hour, 0, tzinfo=timezone.utc)


def req(rid: str, emp: str, pol: str, start: date, end: date, sh: bool = False, eh: bool = False,
        cert: bool = False, status: str = "DRAFT", created: datetime | None = None) -> dict:
    created = created or at(start.year, 1, 1)
    return {"leave_request_id": rid, "employee_id": emp, "leave_policy_id": pol, "start_date": start,
            "end_date": end, "start_half_day": sh, "end_half_day": eh, "medical_cert_flag": cert,
            "workflow_status": status, "current_round": 1, "created_at": created,
            "first_submitted_at": None if status == "DRAFT" else created,
            # an APPROVED row in a replay's input is a legacy approval and carries its marker (DEC-P7B-02)
            "decision_reason_code": "LEGACY_APPROVAL" if status == "APPROVED" else None}


def submit(store: InMemoryLeaveStore, r: dict, when: datetime):
    store.add_request(r)
    return submit_leave(store, r["leave_request_id"], CATALOGUE, when, r["employee_id"],
                        uuid.uuid5(uuid.NAMESPACE_URL, r["leave_request_id"]))
