"""Leave request validation and submission (spec 13.1; docs/05 sections 1, 2 and 9; docs/06 sections 2 and 8.1).

validate_leave() runs BR-LV-01..12 in the fixed order of docs/05 section 2. Every failing check is recorded (all
codes, not only the deciding one); the route then follows the severity precedence (exception_service).

submit_leave() moves a DRAFT through SUBMITTED and VALIDATING to its outcome on any LeaveStore: the in-memory store
below (generator guards, replay, tests) or the PostgreSQL store in src/repositories/leave_repository.py.

Not here yet, by phase: routing, approval steps, NO_VALID_APPROVAL_PATH and RULE_CONFLICT (Phase 7), so a clean
request ends in PENDING_APPROVAL without steps; resubmission (Phase 7); audit_event rows and idempotency keys
(Phase 8). USAGE is posted at approval (Phase 7) through leave_balance_service.usage_postings.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from src.common.enums import LeaveType, WorkflowStatus
from src.services.calendar_service import (
    HolidayCalendar,
    half_days_on_non_business_days,
    quantity_by_year,
    requested_quantity,
)
from src.services.exception_service import Classification, ExceptionCatalogue, Finding, FindingSet
from src.services.leave_balance_service import BalanceBook, Reservation, negative_floor
from src.services.lifecycle import IllegalTransition, check_transition

ZERO = Decimal("0")
HALF = Decimal("0.5")
OPEN = frozenset({WorkflowStatus.PENDING_APPROVAL.value, WorkflowStatus.ESCALATED_FOR_REVIEW.value})
APPROVED = WorkflowStatus.APPROVED.value
HOLDING = OPEN | {APPROVED}          # requests that hold dates and balance (BR-LV-09..11, BR-LBAL-07)


class LeaveInputError(ValueError):
    """Structurally invalid input (BR-LV-03, BR-CAL-04 single day): API 422; the DB CHECKs reject it too."""


class LedgerMismatch(RuntimeError):
    """BR-LV-13: posted accrual differs from the schedule. A technical failure (processing_failure), never a
    business exception code."""


def check_input(r: dict) -> None:
    if r["end_date"] < r["start_date"]:
        raise LeaveInputError(f"{r['leave_request_id']}: end_date before start_date (BR-LV-03)")
    if r["start_date"] == r["end_date"] and r["start_half_day"] and r["end_half_day"]:
        raise LeaveInputError(f"{r['leave_request_id']}: a single-day request may set only one half-day flag")


def overlaps(a: dict, b: dict) -> bool:
    """BR-LV-10/11: the date intervals intersect, except when one request ends with a half day on the date the
    other starts with a half day (they then share exactly that one date, ASM-008)."""
    if a["end_date"] < b["start_date"] or b["end_date"] < a["start_date"]:
        return False
    for x, y in ((a, b), (b, a)):
        if x["end_date"] == y["start_date"] and x["end_half_day"] and y["start_half_day"]:
            return False
    return True


def leave_parts(calendar: HolidayCalendar, r: dict, country: str) -> dict[int, Decimal]:
    """BR-LBAL-09: quantity per leave year (a half-day reduces the year it falls in)."""
    return quantity_by_year(calendar, r["start_date"], r["end_date"], country, r["start_half_day"],
                            r["end_half_day"])


@dataclass
class LeaveValidation:
    request_id: str
    submitted_on: date
    business_days: int
    quantity: Decimal
    parts: dict[int, Decimal]
    findings: list[Finding]
    balances: dict[int, dict]       # year -> {available, requested, floor} (BR-LBAL-09 per part)

    @property
    def codes(self) -> list[str]:
        return [f.code for f in self.findings]


@dataclass
class LeaveContext:
    """Everything validation reads, loaded by a LeaveStore for one request (and locked by the DB store)."""
    employee: dict
    policy: dict
    calendar: HolidayCalendar
    others: list[dict]              # the employee's other submitted requests (any policy), with workflow_status
    policies: dict[str, dict]       # leave_policy rows by id (for the other requests' leave types)
    ledger: list[dict]              # ledger rows of every year of this employee's balance on this policy
    balance_years: set[int]


def reservations(ctx: LeaveContext, policy_id: str) -> list[Reservation]:
    """BR-LBAL-07: open requests of the same employee and policy reserve their per-year parts."""
    country = ctx.employee["country"]
    return [Reservation(o["leave_request_id"], y, q, o["first_submitted_at"] or o["created_at"])
            for o in ctx.others if o["workflow_status"] in OPEN and o["leave_policy_id"] == policy_id
            for y, q in leave_parts(ctx.calendar, o, country).items()]


def validate_leave(r: dict, ctx: LeaveContext, submitted_at: datetime) -> LeaveValidation:
    """BR-LV-01..12 in order (docs/05 section 2). `submitted_at` is the submission instant of this round."""
    check_input(r)
    on = submitted_at.date()
    emp, pol, cal = ctx.employee, ctx.policy, ctx.calendar
    country = emp["country"]
    rid = r["leave_request_id"]
    out = FindingSet()

    # BR-LV-01/02: employed on the submission date and on every leave date.
    start_emp, end_emp = emp["employment_start"], emp["employment_end"]
    if (end_emp is not None and end_emp < on) or r["start_date"] < start_emp \
            or (end_emp is not None and r["end_date"] > end_emp):
        out.add("LEAVE_OUTSIDE_EMPLOYMENT",
                f"leave {r['start_date']}..{r['end_date']}, submitted {on}, employment {start_emp}..{end_emp}")
    # BR-LV-04: applicable to the employee's country, active, minimum service. BR-LV-06: the request names a
    # policy version, whose leave_type is the request's leave type, so there is nothing separate to compare.
    if pol["country_scope"] not in (country, "ALL") or not pol["is_active"] \
            or (on - start_emp).days < int(pol.get("min_service_days") or 0):
        out.add("POLICY_NOT_APPLICABLE", f"{pol['leave_policy_id']} scope {pol['country_scope']} for {country}")
    # BR-LV-05: the stored version must be effective on the submission date.
    if not (pol["effective_start"] <= on and (pol["effective_end"] is None or on <= pol["effective_end"])):
        out.add("POLICY_VERSION_EXPIRED", f"{pol['leave_policy_id']} not effective on {on}")
    # BR-LV-07 / BR-CAL-03..05: business days, half-day flags, quantity (never stored below 0, DB CHECK).
    bd = cal.business_day_count(r["start_date"], r["end_date"], country)
    qty = max(requested_quantity(bd, r["start_half_day"], r["end_half_day"]), ZERO)
    bad_halves = half_days_on_non_business_days(cal, r["start_date"], r["end_date"], country,
                                                r["start_half_day"], r["end_half_day"])
    if bad_halves:
        out.add("HALF_DAY_ON_NON_BUSINESS_DAY", f"half-day flag on {', '.join(map(str, bad_halves))}")
    if qty < HALF:
        out.add("ZERO_BUSINESS_DAYS", f"{bd} business days in {r['start_date']}..{r['end_date']}")
    parts = leave_parts(cal, r, country)

    balances: dict[int, dict] = {}
    if pol["leave_type"] == LeaveType.UNPAID:
        # BR-LV-09: unpaid days per leave year, including this request, within max_days_per_year.
        cap = Decimal(pol["max_days_per_year"])
        for y, q in parts.items():
            taken = sum((leave_parts(cal, o, country).get(y, ZERO) for o in ctx.others
                         if o["workflow_status"] in HOLDING
                         and ctx.policies[o["leave_policy_id"]]["leave_type"] == LeaveType.UNPAID), ZERO)
            if taken + q > cap:
                out.add("UNPAID_LIMIT_EXCEEDED", f"unpaid days in {y}: {taken + q} (limit {cap})")
    else:
        # BR-LV-13 first (technical), then BR-LV-08 / BR-LBAL-07..09: each year's part against its own year.
        book = BalanceBook(emp, pol, ctx.ledger, ctx.balance_years, reservations(ctx, pol["leave_policy_id"]))
        mismatched = book.accrual_mismatches(on)
        if mismatched:
            raise LedgerMismatch(f"{emp['employee_id']} {pol['leave_policy_id']}: posted accrual differs from "
                                 f"the schedule in {mismatched}")
        floor = negative_floor(pol)
        for y, q in parts.items():
            avail = book.available(y, on, part_start=max(r["start_date"], date(y, 1, 1)), exclude=rid)
            balances[y] = {"available": avail, "requested": q, "floor": floor}
            if avail - q < floor:
                out.add("INSUFFICIENT_BALANCE", f"{y}: requested {q}, available {avail}, floor {floor}")
    # BR-LV-10/11: overlap with approved (HARD) and with open (SOFT) requests of the same employee, any policy.
    for o in sorted(ctx.others, key=lambda o: o["leave_request_id"]):
        if o["workflow_status"] in HOLDING and overlaps(r, o):
            if o["workflow_status"] == APPROVED:
                out.add("OVERLAPPING_APPROVED_LEAVE", "overlaps approved request", o["leave_request_id"])
            else:
                out.add("OVERLAPPING_PENDING_LEAVE", "overlaps pending request", o["leave_request_id"])
    # BR-LV-12: SICK above the certificate limit needs the flag.
    limit = pol["requires_medical_cert_over_days"]
    if pol["leave_type"] == LeaveType.SICK and limit is not None and qty > Decimal(limit) \
            and not r["medical_cert_flag"]:
        out.add("MEDICAL_CERT_REQUIRED", f"SICK {qty} days above {limit} without a medical certificate")
    return LeaveValidation(rid, on, bd, qty, parts, list(out.items.values()), balances)


# --- submission ----------------------------------------------------------------------------------------------
@dataclass
class SubmissionResult:
    request_id: str
    submission_round: int
    submitted_at: datetime
    actor_id: str | None
    correlation_id: uuid.UUID
    validation: LeaveValidation
    classification: Classification
    events: list[dict]              # request_status_event payloads, in order

    @property
    def status(self) -> str:
        return self.classification.status_after_validation


class LeaveStore(Protocol):
    def load_request(self, request_id: str) -> dict: ...

    def context(self, r: dict) -> LeaveContext: ...

    def record_submission(self, result: SubmissionResult) -> None: ...


def submit_leave(store: LeaveStore, request_id: str, catalogue: ExceptionCatalogue, at: datetime,
                 actor_id: str | None, correlation_id: uuid.UUID) -> SubmissionResult:
    """docs/06 8.1 steps 2-4 and 7 for leave: lock and load, validate, classify, record the three transitions
    (DRAFT -> SUBMITTED -> VALIDATING -> outcome) in one store transaction."""
    r = store.load_request(request_id)
    if r["workflow_status"] != WorkflowStatus.DRAFT.value:
        check_transition(r["workflow_status"], WorkflowStatus.SUBMITTED.value)   # raises when illegal
        raise IllegalTransition(f"{request_id}: resubmission ({r['workflow_status']} -> SUBMITTED) arrives in "
                                f"Phase 7")
    ctx = store.context(r)
    validation = validate_leave(r, ctx, at)
    classification = catalogue.classify(validation.codes)
    path = [WorkflowStatus.DRAFT.value, WorkflowStatus.SUBMITTED.value, WorkflowStatus.VALIDATING.value,
            classification.status_after_validation]
    events = []
    for prev, new in zip(path, path[1:]):
        check_transition(prev, new)
        last = new == path[-1]
        events.append({
            "previous_status": prev, "new_status": new, "occurred_at": at,
            "actor_id": actor_id if new == WorkflowStatus.SUBMITTED.value else None,   # NULL = system
            "reason_code": classification.decision_reason_code if last else None,
            "calculated_values": calculated_values(validation, classification) if last else None,
        })
    result = SubmissionResult(request_id, r["current_round"], at, actor_id, correlation_id, validation,
                              classification, events)
    store.record_submission(result)
    return result


def calculated_values(v: LeaveValidation, c: Classification) -> dict:
    """The derived values recorded on the outcome event (docs/06 7.1); decimals as text so the JSON is exact."""
    return {
        "business_day_count": v.business_days, "requested_quantity": str(v.quantity),
        "quantity_by_year": {str(y): str(q) for y, q in sorted(v.parts.items())},
        "balances": {str(y): {k: str(x) for k, x in b.items()} for y, b in sorted(v.balances.items())},
        "exception_codes": v.codes, "exception_class": c.exception_class,
    }


# --- in-memory store -------------------------------------------------------------------------------------------
class InMemoryLeaveStore:
    """A LeaveStore over plain rows (generator guards, the replay, unit tests). Same contract as the DB store."""

    def __init__(self, employees: dict[str, dict], policies: dict[str, dict], calendar: HolidayCalendar,
                 ledger: list[dict], balances: list[dict]) -> None:
        self.employees, self.policies, self.calendar = employees, policies, calendar
        self.balance_owner = {b["leave_balance_id"]: (b["employee_id"], b["leave_policy_id"]) for b in balances}
        self.years: dict[tuple[str, str], set[int]] = {}
        for b in balances:
            self.years.setdefault((b["employee_id"], b["leave_policy_id"]), set()).add(b["leave_year"])
        self.ledger: dict[tuple[str, str], list[dict]] = {}
        self.post(ledger)
        self.requests: dict[str, dict] = {}
        self.by_employee: dict[str, list[str]] = {}
        self.results: dict[str, SubmissionResult] = {}
        self.status_events: list[dict] = []
        self.exceptions: list[dict] = []

    def post(self, rows: list[dict]) -> None:
        for t in rows:
            self.ledger.setdefault(self.balance_owner[t["leave_balance_id"]], []).append(t)

    def add_request(self, row: dict, status: str | None = None) -> dict:
        """Add a copy of a request row; `status` overrides workflow_status (DRAFT for a request to be submitted)."""
        r = dict(row)
        if status is not None:
            r["workflow_status"] = status
            if status == WorkflowStatus.DRAFT.value:
                r["first_submitted_at"] = None
        self.requests[r["leave_request_id"]] = r
        self.by_employee.setdefault(r["employee_id"], []).append(r["leave_request_id"])
        return r

    def load_request(self, request_id: str) -> dict:
        return self.requests[request_id]

    def context(self, r: dict) -> LeaveContext:
        emp_id, pol_id = r["employee_id"], r["leave_policy_id"]
        others = [self.requests[i] for i in self.by_employee.get(emp_id, []) if i != r["leave_request_id"]
                  and self.requests[i]["workflow_status"] != WorkflowStatus.DRAFT.value]
        return LeaveContext(self.employees[emp_id], self.policies[pol_id], self.calendar, others, self.policies,
                            self.ledger.get((emp_id, pol_id), []), self.years.get((emp_id, pol_id), set()))

    def book(self, emp_id: str, pol_id: str) -> BalanceBook:
        """One employee's balance book on one policy, with every open reservation currently in the store."""
        ctx = self.context({"employee_id": emp_id, "leave_policy_id": pol_id, "leave_request_id": ""})
        return BalanceBook(ctx.employee, ctx.policy, ctx.ledger, ctx.balance_years, reservations(ctx, pol_id))

    def record_submission(self, result: SubmissionResult) -> None:
        r = self.requests[result.request_id]
        v, c = result.validation, result.classification
        r.update(workflow_status=c.status_after_validation, exception_class=c.exception_class,
                 decision_reason_code=c.decision_reason_code, first_submitted_at=result.submitted_at,
                 business_day_count=Decimal(v.business_days).quantize(Decimal("0.1")), requested_quantity=v.quantity)
        self.results[result.request_id] = result
        for e in result.events:
            self.status_events.append({"request_id": result.request_id, "submission_round": result.submission_round,
                                       "correlation_id": result.correlation_id, **e})
        for f in v.findings:
            self.exceptions.append({"request_id": result.request_id, "submission_round": result.submission_round,
                                    "exception_code": f.code, "detail": f.detail, "detected_at": result.submitted_at,
                                    "detected_by": "SUBMISSION", "correlation_id": result.correlation_id})
