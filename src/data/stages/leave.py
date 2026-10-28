"""S3 leave requests: raw inputs only (docs/07 section 2).

Random: employee, leave type, submission timestamp, business-day count, half-day flags, start offset,
draft flag. Calculated through the shared services: start/end business days, business_day_count,
requested_quantity, per-year split, policy version (DEC-01, RK-01).

The baseline is VALID (CF-06): a draw is kept only when the Phase 5 leave services, replaying all submitted
requests of that employee in submission order, find no exception code on any of them (LeaveGuard). Since
Phase 5 this applies the per-year balance rule BR-LBAL-09 (AMB-P3-02) instead of the stricter Phase 3 guard.
Two raw-input bounds remain the generator's own: leave starts on or after the window start (no balance exists
before it, ASM-P5-06) and ends by last_leave_date (ASM-P3-13).
Workflow outcome is NOT decided here: requests rest in SUBMITTED (about 1% DRAFT) until the Phase 7 engine
runs stage S6 (AMB-P3-01).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

import numpy as np

from src.common import ids
from src.common.enums import ExceptionClass, LeaveType, WorkflowStatus
from src.common.rng import RngStreams
from src.data.sampling import pick, timestamp_on, weighted_date, weighted_pick
from src.data.stages import GenParams
from src.services.calendar_service import HolidayCalendar, requested_quantity
from src.services.exception_service import ExceptionCatalogue
from src.services.leave_batch import replay_leave
from src.services.leave_request_service import overlaps
from src.services.policy_resolver import resolve_version


def policy_family(leave_type: str, country: str) -> str:
    """BR-POL-03: ANNUAL per country; SICK and UNPAID for all; CASUAL only IN (ASM-048)."""
    scope = country if leave_type in (LeaveType.ANNUAL, LeaveType.CASUAL) else "ALL"
    return f"LPOL-{leave_type}-{scope}"


class LeaveGuard:
    """DEC-01: one rule implementation. A set of one employee's requests is acceptable when the raw-input bounds
    hold and the Phase 5 services (replay in submission order, plus the leave batch detectors) find exactly the
    expected codes: none, except on planted records (`expect`). `legacy` ids are treated as legacy approvals."""

    def __init__(self, cfg: dict, p: GenParams, employees: list[dict], policies: list[dict],
                 calendar: HolidayCalendar, transactions: list[dict], balances: list[dict]) -> None:
        self.window_start = p.window_start
        self.last_leave = cfg["generation"]["leave"]["last_leave_date"]
        self.emps = {e["employee_id"]: e for e in employees}
        self.pols = {x["leave_policy_id"]: x for x in policies}
        self.cal = calendar
        self.catalogue = ExceptionCatalogue.from_config(cfg["exception_codes"])
        owner = {b["leave_balance_id"]: b["employee_id"] for b in balances}
        self.balances: dict[str, list[dict]] = defaultdict(list)
        for b in balances:
            self.balances[b["employee_id"]].append(b)
        self.ledger: dict[str, list[dict]] = defaultdict(list)
        for t in transactions:
            self.ledger[owner[t["leave_balance_id"]]].append(t)

    def ok(self, emp_id: str, requests: list[dict], expect: dict[str, set[str]] | None = None,
           legacy: frozenset[str] = frozenset()) -> bool:
        if any(r["start_date"] < self.window_start or r["end_date"] > self.last_leave for r in requests):
            return False
        expect = expect or {}
        # Raw-input rule kept from Phase 3/4: submitted requests of one employee never overlap unless the overlap
        # is planted (S02, S22). The services alone cannot see an overlap between a legacy approval (never
        # validated) and an earlier request that is still pending, which would become an unplanted
        # OVERLAPPING_APPROVED_LEAVE once that request is approved (Phase 5 debugging note 1).
        live = [r for r in requests if r["workflow_status"] != WorkflowStatus.DRAFT.value]
        for i, a in enumerate(live):
            for b in live[i + 1:]:
                if overlaps(a, b) and not any(c.startswith("OVERLAPPING_") for c in
                                              expect.get(a["leave_request_id"], set())
                                              | expect.get(b["leave_request_id"], set())):
                    return False
        replay = replay_leave(requests, self.emps, self.pols, self.cal, self.ledger[emp_id], self.balances[emp_id],
                              self.catalogue, legacy)
        return all(replay.codes(r["leave_request_id"]) == expect.get(r["leave_request_id"], set())
                   for r in requests if r["workflow_status"] != WorkflowStatus.DRAFT.value)


def build_leave_requests(cfg: dict, p: GenParams, streams: RngStreams, employees: list[dict],
                         policies: list[dict], calendar: HolidayCalendar, transactions: list[dict],
                         balances: list[dict]) -> list[dict]:
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
    guard = LeaveGuard(cfg, p, employees, policies, calendar, transactions, balances)
    submitted: dict[str, list[dict]] = {}     # accepted, submitted (non-draft) candidates per employee
    accepted: list[dict] = []

    for r in range(p.leave_requests):
        year_end = bool(rng.random() < lcfg["year_end"]["share"])         # ASM-P5-07, one draw per request
        for _ in range(lcfg["max_attempts_per_request"]):
            d = (_draw_year_end if year_end else _draw)(rng, lcfg, tcfg, p, eligible, calendar, last_submit)
            if d is None:
                continue
            d["policy"] = resolve_version(policies, policy_family(d["leave_type"], d["emp"]["country"]),
                                          d["ts"].date())
            d["row"] = _candidate(d, f"DRAW-{r:06d}")
            emp_id = d["emp"]["employee_id"]
            if guard.ok(emp_id, submitted.get(emp_id, []) + [d["row"]]):
                break
        else:
            raise RuntimeError(f"could not draw a valid leave request #{r} in "
                               f"{lcfg['max_attempts_per_request']} attempts")
        d["draw"] = r
        d["is_draft"] = bool(rng.random() < tcfg["draft_share"])
        if not d["is_draft"]:
            submitted.setdefault(d["emp"]["employee_id"], []).append(d["row"])   # drafts are invisible
        accepted.append(d)

    # IDs: per submission year, in submission order (docs/07 section 3, AMB-04). Drafts use their creation time.
    accepted.sort(key=lambda x: (x["ts"], x["draw"]))
    counters: dict[int, int] = {}
    rows = []
    for d in accepted:
        year = d["ts"].year
        counters[year] = counters.get(year, 0) + 1
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
            "medical_cert_flag": d["row"]["medical_cert_flag"],
            "decision_reason_code": None,
            "decision_reason_text": None,
            "created_at": d["ts"],
        })
    return rows


def _candidate(d: dict, temp_id: str) -> dict:
    """The draw as a submitted leave_request row for the guard. Valid baseline: the certificate flag is set
    exactly when the policy needs it (ASM-010, ASM-P3-17)."""
    sick_limit = d["policy"]["requires_medical_cert_over_days"]
    return {"leave_request_id": temp_id, "employee_id": d["emp"]["employee_id"],
            "leave_policy_id": d["policy"]["leave_policy_id"], "start_date": d["start"], "end_date": d["end"],
            "start_half_day": d["start_half"], "end_half_day": d["end_half"],
            "medical_cert_flag": sick_limit is not None and d["quantity"] > sick_limit,
            "workflow_status": WorkflowStatus.SUBMITTED.value, "created_at": d["ts"], "first_submitted_at": d["ts"],
            "current_round": 1}


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
            "quantity": quantity}


def _draw_year_end(rng: np.random.Generator, lcfg: dict, tcfg: dict, p: GenParams, eligible: list[dict],
                   calendar: HolidayCalendar, last_submit: date) -> dict | None:
    """ASM-P5-07: a request whose last `new_year_business_days` business days fall in January of the next year
    and the rest in the last business days of December (the only boundary inside the window is 2025 -> 2026).
    Submission = start - the usual start offset; None when that date or the employee does not fit."""
    emp = pick(rng, eligible)
    country = emp["country"]
    leave_type = weighted_pick(rng, lcfg["type_weights"][country])
    dur = lcfg["durations"][leave_type]
    tail = int(lcfg["year_end"]["new_year_business_days"])
    sizes = list(range(max(dur["min_bd"], tail + 1), dur["max_bd"] + 1))
    if not sizes:
        return None
    weights = np.array([dur["decay"] ** (k - sizes[0]) for k in sizes])
    business_days = sizes[int(rng.choice(len(sizes), p=weights / weights.sum()))]
    start_half = bool(rng.random() < dur["half_day_prob"])
    end_half = bool(rng.random() < dur["half_day_prob"])
    offsets = lcfg["start_offset_days"].get(leave_type, lcfg["start_offset_days"]["default"])
    offset = int(rng.integers(offsets["min"], offsets["max"] + 1))

    year = p.window_start.year
    december = [date(year, 12, d) for d in range(1, 32) if calendar.is_business_day(date(year, 12, d), country)]
    in_old_year = business_days - tail
    if in_old_year > len(december):
        return None
    start = december[-in_old_year]
    end = calendar.nth_business_day(start, business_days, country)
    sub_date = start - timedelta(days=offset)
    lo = max(p.window_start, emp["employment_start"])
    hi = min(last_submit, emp["employment_end"] or last_submit)
    if not (lo <= sub_date <= hi) or end.year != year + 1:
        return None
    ts = timestamp_on(rng, sub_date, tcfg["submission_hour_min"], tcfg["submission_hour_max"])
    return {"emp": emp, "leave_type": leave_type, "ts": ts, "start": start, "end": end,
            "start_half": start_half, "end_half": end_half, "business_days": business_days,
            "quantity": requested_quantity(business_days, start_half, end_half)}
