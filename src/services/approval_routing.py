"""Approval routing (docs/05 sections 5.1-5.4; ASM-009, ASM-013, ASM-014, ASM-030; AMB-P3-03).

route() picks the approval rule from the ops.approval_rule rows and resolves every required level to a person as
of the routing date. Rule selection (docs/05 5.3): active and effective rules of the request type whose country and
category (or leave type) match or are NULL, and whose band holds the measure (USD total or leave quantity) with
the lower bound exclusive and the upper bound inclusive. The highest priority wins; equal top priority with
different required levels -> RULE_CONFLICT; equal outcome -> the lowest rule id. No match ->
NO_VALID_APPROVAL_PATH. Never an arbitrary approver (AM-B9): an unresolved level -> NO_VALID_APPROVAL_PATH.

Levels (docs/05 5.1): L1 the direct manager; L2 the manager's manager, or the manager when the manager is the top
of the chain (AMB-P3-03); L3 the head of the requester's department; L4 the one finance controller of the
requester's country; L5 the one G7 of the requester's country (owner decision S19 option a), or the organisation's
single G7 while no country has its own (AMB-P7A-01). Two candidates for one role -> unresolved.

Substitution (docs/05 5.4, ASM-030): the requester moves one step up the chain; a person with an active delegation
is replaced by the delegate (delegated_from = the first person replaced by a delegate); a person whose employment
ended before the routing date and who has no delegate is replaced by their manager. One person resolved for
several levels gets ONE step at the highest of them, which records every level it covers (covered_levels).

Pure functions over plain rows; no database, no src/reference import (DEC-01).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from src.common.enums import ApprovalEventType, ApprovalLevel, RequestType, StepStatus
from src.services.exception_service import Finding

LEVELS = tuple(lv.value for lv in ApprovalLevel)
TOP_GRADE = "G7"


@dataclass(frozen=True)
class RouteStep:
    level: str                       # the highest level this person covers = approval_step.required_level
    approver_id: str
    covered_levels: tuple[str, ...]  # in level order
    delegated_from: str | None


@dataclass(frozen=True)
class Routing:
    rule_id: str | None
    required_levels: tuple[str, ...]
    steps: tuple[RouteStep, ...]
    finding: Finding | None          # NO_VALID_APPROVAL_PATH or RULE_CONFLICT

    @property
    def findings(self) -> list[Finding]:
        return [] if self.finding is None else [self.finding]

    def as_values(self) -> dict:
        """The route for calculated_values (docs/06 7.1)."""
        return {"approval_rule_id": self.rule_id, "required_levels": list(self.required_levels),
                "route": [{"level": s.level, "approver_id": s.approver_id, "covered_levels": list(s.covered_levels),
                           "delegated_from": s.delegated_from} for s in self.steps]}


class Organisation:
    """Who holds which role, from employee, department and delegation rows."""

    def __init__(self, employees: dict[str, dict], departments: list[dict], delegations: list[dict]) -> None:
        self.employees = employees
        self.heads = {d["department_id"]: d["head_employee_id"] for d in departments}
        self.controllers: dict[str, list[str]] = {}
        self.top: dict[str, list[str]] = {}
        for e in sorted(employees.values(), key=lambda e: e["employee_id"]):
            if e["is_finance_controller"]:
                self.controllers.setdefault(e["country"], []).append(e["employee_id"])
            if e["grade"] == TOP_GRADE:
                self.top.setdefault(e["country"], []).append(e["employee_id"])
        self.delegations: dict[str, list[dict]] = {}
        for g in sorted(delegations, key=lambda g: g["delegation_id"]):
            self.delegations.setdefault(g["approver_id"], []).append(g)

    def delegate_of(self, emp_id: str, on: date) -> str | None:
        """The delegate of the first (lowest id) delegation of this approver that covers the date."""
        return next((g["delegate_id"] for g in self.delegations.get(emp_id, [])
                     if g["effective_from"] <= on <= g["effective_to"]), None)

    def base_approver(self, level: str, requester: dict) -> str | None:
        """docs/05 5.1: the person who holds `level` for this requester before substitution."""
        manager = requester["manager_id"]
        if level == ApprovalLevel.L1:
            return manager
        if level == ApprovalLevel.L2:
            # AMB-P3-03: when L1 is the top of the chain there is no skip-level; L1 covers L2 in the same step.
            return None if manager is None else (self.employees[manager]["manager_id"] or manager)
        if level == ApprovalLevel.L3:
            return self.heads.get(requester["department_id"])
        if level == ApprovalLevel.L4:
            found = self.controllers.get(requester["country"], [])
            return found[0] if len(found) == 1 else None
        found = self.top.get(requester["country"], [])
        if not found:                     # AMB-P7A-01: no G7 in the country -> the organisation's only G7
            everyone = [e for ids in self.top.values() for e in ids]
            found = everyone if len(everyone) == 1 else []
        return found[0] if len(found) == 1 else None

    def substitute(self, person: str | None, requester_id: str, on: date) -> tuple[str | None, str | None]:
        """docs/05 5.4: (acting person, delegated_from) or (None, None) when nobody can act."""
        delegated_from, visited = None, set()
        while person is not None and person not in visited:
            visited.add(person)
            e = self.employees[person]
            if person == requester_id:
                person = e["manager_id"]
                continue
            delegate = self.delegate_of(person, on)
            if delegate is not None:
                delegated_from = delegated_from or person
                person = delegate
            elif e["employment_end"] is not None and e["employment_end"] < on:
                person = e["manager_id"]
            else:
                return person, delegated_from
        return None, None


def _in_band(measure: Decimal, low, high) -> bool:
    return (low is None or measure > low) and (high is None or measure <= high)


def matching_rules(rules: list[dict], request_type: str, country: str, category: str, measure: Decimal,
                   on: date) -> list[dict]:
    low, high = ("min_days", "max_days") if request_type == RequestType.LEAVE else ("min_amount_usd", "max_amount_usd")
    return [r for r in rules
            if r["request_type"] == request_type and r["is_active"] and r["effective_start"] <= on
            and (r["effective_end"] is None or on <= r["effective_end"])
            and r["country"] in (None, country) and r["category_or_leave_type"] in (None, category)
            and _in_band(measure, r[low], r[high])]


class ApprovalRouter:
    def __init__(self, rules: list[dict], organisation: Organisation) -> None:
        self.rules, self.org = rules, organisation

    @classmethod
    def from_rows(cls, rules: list[dict], employees: list[dict], departments: list[dict],
                  delegations: list[dict]) -> "ApprovalRouter":
        return cls(rules, Organisation({e["employee_id"]: e for e in employees}, departments, delegations))

    def select_rule(self, request_type: str, country: str, category: str, measure: Decimal,
                    on: date) -> tuple[dict | None, Finding | None]:
        found = matching_rules(self.rules, request_type, country, category, measure, on)
        if not found:
            return None, Finding("NO_VALID_APPROVAL_PATH",
                                 f"no {request_type} rule matches {category} {measure} in {country} on {on}")
        top = max(r["priority"] for r in found)
        best = sorted((r for r in found if r["priority"] == top), key=lambda r: r["approval_rule_id"])
        if len({tuple(r["required_levels"]) for r in best}) > 1:
            return None, Finding("RULE_CONFLICT", "rules " + ", ".join(r["approval_rule_id"] for r in best)
                                 + f" match with priority {top} and different required levels")
        return best[0], None

    def route(self, request_type: str, employee_id: str, category: str, measure: Decimal, on: date) -> Routing:
        requester = self.org.employees[employee_id]
        rule, problem = self.select_rule(request_type, requester["country"], category, measure, on)
        if rule is None:
            return Routing(None, (), (), problem)
        levels = tuple(rule["required_levels"])
        covered: dict[str, list[str]] = {}
        delegated: dict[str, str | None] = {}
        for level in levels:
            person, delegated_from = self.org.substitute(self.org.base_approver(level, requester), employee_id, on)
            if person is None:
                return Routing(rule["approval_rule_id"], levels, (), Finding(
                    "NO_VALID_APPROVAL_PATH", f"level {level} unresolved for {employee_id} on {on}"))
            covered.setdefault(person, []).append(level)
            delegated[person] = delegated.get(person) or delegated_from
        steps = sorted((RouteStep(max(lv, key=LEVELS.index), person, tuple(sorted(lv, key=LEVELS.index)),
                                  delegated[person]) for person, lv in covered.items()),
                       key=lambda s: LEVELS.index(s.level))
        return Routing(rule["approval_rule_id"], levels, tuple(steps), None)


def build_steps(request_type: str, request_id: str, submission_round: int, routing: Routing, at: datetime,
                first_sequence: int = 1) -> list[dict]:
    """approval_step rows for a routed request (docs/05 5.3 step 7): all PENDING, sequence numbers continue across
    rounds (AM-A5), only the first step is assigned now (the next one when the previous step is approved)."""
    out = []
    for i, s in enumerate(routing.steps):
        seq = first_sequence + i
        out.append({
            "approval_step_id": f"APR-{request_id}-{seq:02d}", "request_type": request_type,
            "leave_request_id": request_id if request_type == RequestType.LEAVE else None,
            "expense_claim_id": request_id if request_type == RequestType.EXPENSE else None,
            "submission_round": submission_round, "sequence_no": seq, "approval_rule_id": routing.rule_id,
            "required_level": s.level, "covered_levels": list(s.covered_levels),
            "approver_employee_id": s.approver_id, "delegated_from_employee_id": s.delegated_from,
            "step_status": StepStatus.PENDING.value, "assigned_at": at if i == 0 else None,
            "decision_at": None, "decision_reason_code": None, "decision_comment": None,
        })
    return out


def assignment_event(step: dict, correlation_id) -> dict:
    """approval_event ASSIGNED for the step that is assigned now (actor NULL = system), unnumbered."""
    return {"approval_step_id": step["approval_step_id"], "event_type": ApprovalEventType.ASSIGNED.value,
            "actor_id": None, "occurred_at": step["assigned_at"], "reason_code": None, "comment": None,
            "correlation_id": correlation_id}
