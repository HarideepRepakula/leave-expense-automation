"""S3 leave requests: raw inputs only (docs/07 section 2).

Random: employee, leave type, submission timestamp, business-day count, half-day flags, start offset,
draft flag. Calculated through the shared services: start/end business days, business_day_count,
requested_quantity, per-year split, policy version (DEC-01, RK-01).

Phase 3 produces a VALID baseline (CF-06): a draw is re-drawn when it would overlap another request of the
same employee, fall outside employment, exceed the unpaid yearly cap, or exceed the balance available at
submission. The balance guard is conservative: every earlier request of the same balance counts as consumed
and carry-forward is ignored (AMB-P3-02), so no baseline request can fail INSUFFICIENT_BALANCE later.
Workflow outcome is NOT decided here: requests rest in SUBMITTED (about 1% DRAFT) until the Phase 7 engine
runs stage S6 (AMB-P3-01).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import numpy as np

from src.common import ids
from src.common.enums import ExceptionClass, LeaveType, WorkflowStatus
from src.common.rng import RngStreams
from src.data.sampling import pick, timestamp_on, weighted_date, weighted_pick
from src.data.stages import GenParams
from src.services.calendar_service import HolidayCalendar, quantity_by_year, requested_quantity
from src.services.policy_resolver import resolve_version


def policy_family(leave_type: str, country: str) -> str:
    """BR-POL-03: ANNUAL per country; SICK and UNPAID for all; CASUAL only IN (ASM-048)."""
    scope = country if leave_type in (LeaveType.ANNUAL, LeaveType.CASUAL) else "ALL"
    return f"LPOL-{leave_type}-{scope}"


def _available_on(ledger: list[tuple[date, Decimal]], on: date) -> Decimal:
    return sum((q for d, q in ledger if d <= on), Decimal("0"))


def build_leave_requests(cfg: dict, p: GenParams, streams: RngStreams, employees: list[dict],
                         policies: list[dict], calendar: HolidayCalendar,
                         ledger: dict[str, list[tuple[date, Decimal]]]) -> list[dict]:
    lcfg = cfg["generation"]["leave"]
    tcfg = cfg["generation"]["timeline"]
    rng = streams.get("leave")
    last_submit = p.as_of - timedelta(days=1)  # submissions happen strictly before the as-of instant
    eligible = [
        e for e in employees
        if e["grade"] != "G7"  # a G7 requester has no approval path (that case is planted as S19 in Phase 4)
        and e["employment_start"] <= last_submit
        and (e["employment_end"] is None or e["employment_end"] >= p.window_start)
    ]
    by_emp: dict[str, list[dict]] = {}
    balance_claims: dict[str, list[tuple[datetime, Decimal]]] = {}
    unpaid: dict[tuple[str, int], Decimal] = {}
    accepted: list[dict] = []

    for r in range(p.leave_requests):
        for _ in range(lcfg["max_attempts_per_request"]):
            d = _draw(rng, lcfg, tcfg, p, eligible, calendar, last_submit)
            if d is None:
                continue
            d["policy"] = resolve_version(policies, policy_family(d["leave_type"], d["emp"]["country"]),
                                          d["ts"].date())
            if _valid(d, lcfg, by_emp, balance_claims, unpaid, ledger):
                break
        else:
            raise RuntimeError(f"could not draw a valid leave request #{r} in "
                               f"{lcfg['max_attempts_per_request']} attempts")
        d["draw"] = r
        d["is_draft"] = bool(rng.random() < tcfg["draft_share"])
        _record(d, by_emp, balance_claims, unpaid)
        accepted.append(d)

    # IDs: per submission year, in submission order (docs/07 section 3, AMB-04). Drafts use their creation time.
    accepted.sort(key=lambda x: (x["ts"], x["draw"]))
    counters: dict[int, int] = {}
    rows = []
    for d in accepted:
        year = d["ts"].year
        counters[year] = counters.get(year, 0) + 1
        sick_limit = d["policy"]["requires_medical_cert_over_days"]
        rows.append({
            "leave_request_id": ids.leave_request_id(year, counters[year]),
            "employee_id": d["emp"]["employee_id"],
            "leave_policy_id": d["policy"]["leave_policy_id"],
            "start_date": d["start"],
            "end_date": d["end"],
            "start_half_day": d["start_half"],
            "end_half_day": d["end_half"],
            "first_submitted_at": None if d["is_draft"] else d["ts"],
            "current_round": 1,
            "business_day_count": Decimal(d["business_days"]).quantize(Decimal("0.1")),
            "requested_quantity": d["quantity"],
            "workflow_status": WorkflowStatus.DRAFT.value if d["is_draft"] else WorkflowStatus.SUBMITTED.value,
            "exception_class": ExceptionClass.NONE.value,
            # Valid baseline: the certificate flag is set exactly when the policy needs it (ASM-010, ASM-P3-17).
            "medical_cert_flag": sick_limit is not None and d["quantity"] > sick_limit,
            "decision_reason_code": None,
            "decision_reason_text": None,
            "created_at": d["ts"],
        })
    return rows


def _draw(rng: np.random.Generator, lcfg: dict, tcfg: dict, p: GenParams, eligible: list[dict],
          calendar: HolidayCalendar, last_submit: date) -> dict | None:
    emp = pick(rng, eligible)
    country = emp["country"]
    leave_type = weighted_pick(rng, lcfg["type_weights"][country])
    dur = lcfg["durations"][leave_type]
    lo = max(p.window_start, emp["employment_start"])
    hi = min(last_submit, emp["employment_end"] or last_submit)
    if lo > hi:
        return None
    sub_date = weighted_date(rng, lo, hi, tcfg["weekend_submission_weight"])
    ts = timestamp_on(rng, sub_date, tcfg["submission_hour_min"], tcfg["submission_hour_max"])

    sizes = list(range(dur["min_bd"], dur["max_bd"] + 1))
    weights = np.array([dur["decay"] ** (k - dur["min_bd"]) for k in sizes])
    business_days = sizes[int(rng.choice(len(sizes), p=weights / weights.sum()))]
    start_half = bool(rng.random() < dur["half_day_prob"])
    end_half = bool(rng.random() < dur["half_day_prob"])
    if business_days == 1 and start_half and end_half:
        end_half = False  # single day: at most one half-day flag (ASM-008)
    quantity = requested_quantity(business_days, start_half, end_half)
    if quantity < Decimal(dur["min_quantity"]):
        start_half = end_half = False
        quantity = requested_quantity(business_days, False, False)

    offsets = lcfg["start_offset_days"].get(leave_type, lcfg["start_offset_days"]["default"])
    offset = int(rng.integers(offsets["min"], offsets["max"] + 1))
    start = calendar.next_business_day(sub_date + timedelta(days=offset), country)
    end = calendar.nth_business_day(start, business_days, country)
    return {"emp": emp, "leave_type": leave_type, "ts": ts, "start": start, "end": end,
            "start_half": start_half, "end_half": end_half, "business_days": business_days,
            "quantity": quantity,
            "by_year": quantity_by_year(calendar, start, end, country, start_half, end_half)}


def _valid(d: dict, lcfg: dict, by_emp: dict, balance_claims: dict, unpaid: dict, ledger: dict) -> bool:
    emp = d["emp"]
    if d["start"] < emp["employment_start"]:
        return False
    if emp["employment_end"] is not None and d["end"] > emp["employment_end"]:
        return False
    if d["end"] > lcfg["last_leave_date"]:
        return False
    for other in by_emp.get(emp["employee_id"], []):
        if not (d["end"] < other["start"] or d["start"] > other["end"]):
            return False  # any shared date counts: overlaps are planted only in Phase 4 (S02, S22)
    policy = d["policy"]
    if policy["leave_type"] == LeaveType.UNPAID:
        cap = policy["max_days_per_year"]
        return all(unpaid.get((emp["employee_id"], y), Decimal("0")) + q <= cap for y, q in d["by_year"].items())
    for year, qty in d["by_year"].items():
        lbal = ids.leave_balance_id(emp["employee_id"], policy["leave_policy_id"], year)
        claims = sorted(balance_claims.get(lbal, []) + [(d["ts"], qty)])
        used = Decimal("0")
        for ts, q in claims:
            used += q
            if _available_on(ledger.get(lbal, []), ts.date()) < used:
                return False
    return True


def _record(d: dict, by_emp: dict, balance_claims: dict, unpaid: dict) -> None:
    emp_id = d["emp"]["employee_id"]
    by_emp.setdefault(emp_id, []).append(d)
    policy = d["policy"]
    for year, qty in d["by_year"].items():
        if policy["leave_type"] == LeaveType.UNPAID:
            unpaid[(emp_id, year)] = unpaid.get((emp_id, year), Decimal("0")) + qty
        else:
            lbal = ids.leave_balance_id(emp_id, policy["leave_policy_id"], year)
            balance_claims.setdefault(lbal, []).append((d["ts"], qty))
