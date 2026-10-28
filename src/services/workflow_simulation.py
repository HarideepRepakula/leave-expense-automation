"""Time-ordered workflow simulation for stage S6 (docs/07 section 2; docs/05 9.5; ASM-024; owner S22 rule).

The replays in leave_batch / expense_batch put every event on one queue and run it in time order:
- submissions at their created_at instant (submit_leave / submit_expense);
- year-end carry-forward at 00:00 UTC on 1 January (leave only, leave_balance_service.year_end_postings);
- with a DecisionTiming: the simulated decisions, made through approval_service exactly as an approver or a
  process owner would make them (DEC-01: one rule implementation).

Simulated behaviour (docs/05 9.5, data generation only): every assigned step is APPROVED by its approver; an
ESCALATED_FOR_REVIEW request gets the process-owner decision of ProcessOwnerPolicy (REJECT > RETURN > APPROVE =
send on), or none, in which case it stays escalated. A RETURNED_FOR_CORRECTION request is not resubmitted in the
dataset (ASM-P7B-06).

Timing (ASM-024, S22 rule, ASM-P7B-02): a decision is made at 17:00 UTC on the n-th business day (calendar of the
person deciding) after the day of assignment, n = max(1, delay); assignment at or after 17:00 counts from the next
day, so every decision is more than 24 hours after its assignment and an S22 partner submitted at most 24 hours
earlier is never decided first. The delay in business days is a keyed draw on the delays stream (key: request id,
round, level or PROCESS_OWNER), so it depends only on its key. Events after the as-of instant do not happen.

Approver leaves (AMB-P7B-11): when the assigned approver's employment ends before the decision date, the step is
reassigned (approval_service.reassign_departed, the routing substitution) at 00:00 UTC on the day after the
employment end, or at the assignment when that is later; the new approver decides on the same timing counted from
the reassignment, keyed (request id, round, level, new approver). Nobody to substitute -> the step stays pending.
"""
from __future__ import annotations

import heapq
import uuid
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Callable

from src.common.enums import AttemptedAction, AttemptOutcome, StepStatus, WorkflowStatus
from src.services.approval_service import (
    DecisionResult,
    ProcessOwnerPolicy,
    decide_escalated,
    decide_step,
    reassign_departed,
)
from src.services.calendar_service import HolidayCalendar
from src.services.exception_service import ExceptionCatalogue

PROCESS_OWNER = "PROCESS_OWNER"
YEAR_END, DECISION, SUBMIT = 0, 1, 2          # order of events that share an instant
SIM_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:lea:workflow-simulation")


class SimulationError(RuntimeError):
    """A simulated decision was blocked or refused: the simulation and the rules disagree (a defect)."""


@dataclass(frozen=True)
class DecisionTiming:
    calendar: HolidayCalendar
    countries: dict[str, str]                         # employee id -> country (whose calendar counts)
    delays: Callable[[tuple, int, int], int]          # keyed draw: (key, low, high) -> business days
    ranges: dict[str, tuple[int, int]]                # L1..L5 and PROCESS_OWNER (ASM-024)
    process_owners: tuple[str, ...]                   # employee ids holding PROCESS_OWNER, sorted
    policy: ProcessOwnerPolicy
    as_of: datetime                                   # nothing happens after this instant
    hour: int = 17

    @classmethod
    def from_config(cls, generation_cfg: dict, exception_codes_cfg: dict, calendar: HolidayCalendar,
                    employees: list[dict], process_owners, delays, as_of: datetime) -> "DecisionTiming":
        d = generation_cfg["decisions"]
        return cls(calendar, {e["employee_id"]: e["country"] for e in employees}, delays,
                   {k: (int(v[0]), int(v[1])) for k, v in d["delay_business_days"].items()},
                   tuple(sorted(process_owners)), ProcessOwnerPolicy.from_config(exception_codes_cfg), as_of,
                   int(d["decision_hour_utc"]))

    def decision_at(self, assigned_at: datetime, kind: str, key: tuple, decider: str) -> datetime:
        days = max(1, self.delays(key, *self.ranges[kind]))
        base = assigned_at.date() + timedelta(days=1 if assigned_at.time() >= time(self.hour) else 0)
        day = self.calendar.nth_business_day(base + timedelta(days=1), days, self.countries[decider])
        return datetime.combine(day, time(self.hour), tzinfo=timezone.utc)

    def process_owner_for(self, requester_id: str) -> str | None:
        """The lowest-id process owner who is not the requester (ASM-P7B-08)."""
        return next((p for p in self.process_owners if p != requester_id), None)


@dataclass(order=True)
class _Event:
    at: datetime
    order: int
    key: str
    n: int
    run: Callable[[datetime], None] = field(compare=False)


class EventQueue:
    def __init__(self) -> None:
        self._heap: list[_Event] = []
        self._n = 0

    def push(self, at: datetime, order: int, key: str, run: Callable[[datetime], None]) -> None:
        self._n += 1
        heapq.heappush(self._heap, _Event(at, order, key, self._n, run))

    def run(self) -> None:
        while self._heap:
            e = heapq.heappop(self._heap)
            e.run(e.at)


class DecisionDriver:
    """Schedules and makes the simulated decisions of one store (leave or expense)."""

    def __init__(self, store, catalogue: ExceptionCatalogue, timing: DecisionTiming | None, queue: EventQueue) -> None:
        self.store, self.catalogue, self.timing, self.queue = store, catalogue, timing, queue
        self.decided: list[DecisionResult] = []
        self.reassigned: dict[str, datetime] = {}       # step id -> instant of its latest reassignment

    def _correlation(self, rid: str, what: str) -> uuid.UUID:
        return uuid.uuid5(SIM_NAMESPACE, f"{rid}:{what}")

    def _push(self, at: datetime, rid: str, run) -> None:
        if at <= self.timing.as_of:
            self.queue.push(at, DECISION, rid, run)

    def after(self, rid: str) -> None:
        """Schedule the next decision of a request that just changed (submission or decision)."""
        if self.timing is None:
            return
        r = self.store.load_request(rid)
        rnd = r["current_round"]
        if r["workflow_status"] == WorkflowStatus.PENDING_APPROVAL:
            step = next(s for s in self.store.steps_of(rid) if s["submission_round"] == rnd
                        and s["step_status"] == StepStatus.PENDING and s["assigned_at"] is not None)
            sid, level, approver = step["approval_step_id"], step["required_level"], step["approver_employee_id"]
            base = self.reassigned.get(sid, step["assigned_at"])
            key = (rid, rnd, level) if sid not in self.reassigned else (rid, rnd, level, approver)
            when = self.timing.decision_at(base, level, key, approver)
            end = self.store.router().org.employees[approver]["employment_end"]
            if end is not None and when.date() > end:      # AMB-P7B-11: reassign before anyone decides
                at = max(base, datetime.combine(end + timedelta(days=1), time(0), tzinfo=timezone.utc))
                self._push(at, rid, lambda at, s=step: self._reassign(rid, s, at))
                return
            self._push(when, rid, lambda at, s=step: self._approve(rid, s, at))
        elif r["workflow_status"] == WorkflowStatus.ESCALATED_FOR_REVIEW:
            codes = {c for c in self.store.round_codes(rid, rnd)
                     if self.catalogue.info(c).severity == "SOFT"}
            action = self.timing.policy.action(codes)
            owner = self.timing.process_owner_for(r["employee_id"])
            if action is None or owner is None:
                return                                   # stays escalated (ASM-P4-15)
            submitted = max(e["occurred_at"] for e in self.store.status_events
                            if e["request_id"] == rid and e["submission_round"] == rnd)
            when = self.timing.decision_at(submitted, PROCESS_OWNER, (rid, rnd, PROCESS_OWNER), owner)
            reason = None if action == AttemptedAction.APPROVE else next(
                c for c in sorted(codes, key=lambda c: self.catalogue.info(c).order)
                if c in (self.timing.policy.reject_when_any if action == AttemptedAction.REJECT
                         else self.timing.policy.return_when_any))
            self._push(when, rid, lambda at: self._process_owner(rid, owner, action, reason, at))

    def _check(self, res: DecisionResult) -> None:
        if res.outcome != AttemptOutcome.ACCEPTED:
            raise SimulationError(f"{res.request_id}: simulated {res.action} by {res.actor_id} blocked "
                                  f"({res.reason_code})")
        self.decided.append(res)

    def _approve(self, rid: str, step: dict, at: datetime) -> None:
        self._check(decide_step(self.store, rid, step["approval_step_id"], step["approver_employee_id"],
                                AttemptedAction.APPROVE.value, at,
                                self._correlation(rid, step["approval_step_id"])))
        self.after(rid)

    def _reassign(self, rid: str, step: dict, at: datetime) -> None:
        sid = step["approval_step_id"]
        if reassign_departed(self.store, rid, sid, at, self._correlation(rid, f"{sid}:REASSIGN:{at.isoformat()}")):
            self.reassigned[sid] = at
            self.after(rid)

    def _process_owner(self, rid: str, owner: str, action: str, reason: str | None, at: datetime) -> None:
        rnd = self.store.load_request(rid)["current_round"]
        self._check(decide_escalated(self.store, rid, owner, action, at, self._correlation(rid, f"PO-{rnd}"),
                                     reason_code=reason))
        self.after(rid)


def employee_roles(users: list[dict], user_roles: list[dict], roles: list[dict]) -> dict[str, set[str]]:
    """employee id -> role names, from application_user, user_role and role rows."""
    names = {r["role_id"]: r["role_name"] for r in roles}
    emp = {u["user_id"]: u["employee_id"] for u in users if u["employee_id"]}
    out: dict[str, set[str]] = {}
    for ur in user_roles:
        if ur["user_id"] in emp:
            out.setdefault(emp[ur["user_id"]], set()).add(names[ur["role_id"]])
    return out


def year_end_instants(years, as_of: datetime | None) -> list[datetime]:
    """00:00 UTC on 1 January of every year whose previous year also has balances (and not after as_of)."""
    ys = sorted(set(years))
    out = [datetime(y, 1, 1, tzinfo=timezone.utc) for y in ys if y - 1 in ys]
    return [t for t in out if as_of is None or t <= as_of]
