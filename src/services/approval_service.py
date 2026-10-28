"""Approval decisions (spec 13.3; docs/05 sections 5.5 and 9.4; docs/06 sections 2-3, 5.1 and 8.2).

decide_step(): approve, reject or return one approval step. decide_escalated(): the process owner's decision on an
ESCALATED_FOR_REVIEW request (send on with steps, reject, return). Both work on any WorkflowStore (the in-memory
leave and expense stores, and the PostgreSQL stores in src/repositories) and follow docs/06 8.2:

1. Idempotency: the key is the client's, else derived (SHA-256 of actor | step or request | action | round). A
   known key with the same request hash is a replay: nothing is written, the result is marked replayed. A known
   key with a different hash raises IdempotencyConflict (HTTP 409 in Phase 9).
2. The request and its steps are loaded (and locked by the DB store).
3. Guards, in this order (ASM-P7B-01): SELF_APPROVAL, UNAUTHORIZED_APPROVER, DUPLICATE_ACTION, STEP_NOT_PENDING,
   LEVEL_SKIPPED, EXPIRED_RULE. The first failing guard blocks.
4. One approval_attempt row is written for every call, ACCEPTED or BLOCKED. A blocked attempt changes nothing else.
5. Accepted: step status and decision fields, approval_event rows, the next step's assignment, the request status
   event and, on a final decision, the request's own columns and postings: leave USAGE at approval (BR-LBAL-05);
   expense approved_amount (BR-EX-14) on approval, RELEASE of the reservation on reject or return (BR-BUD-04),
   OVERRIDE when a process owner sends on a BUDGET_EXCEEDED claim (BR-BUD-06).

Business rules that depend on the request type live in leave_request_service / expense_service; the store only
loads the rows they need. Phase 8: the final approval of an expense claim also builds its reimbursement
(reimbursement_service.on_final_approval, docs/06 8.2 step 6), and every call carries its audit_event rows
(audit_service): the attempt, the steps it changed and the request transitions; a replay writes one
IDEMPOTENT_REPLAY audit row and nothing else.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from src.common.enums import (
    ApprovalEventType,
    ApprovalLevel,
    AttemptedAction,
    AttemptOutcome,
    BlockedReason,
    IdempotencyOperation,
    RequestType,
    RoleName,
    StepStatus,
    WorkflowStatus,
)
from src.services import audit_service
from src.services.approval_routing import ApprovalRouter, Routing, assignment_event, build_steps
from src.services.idempotency import IdempotencyConflict, IdempotentReplay, body_hash, sha256_hex  # noqa: F401
from src.services.lifecycle import IllegalTransition, check_transition
from src.services.reimbursement_service import ReimbursementResult, on_final_approval

S = WorkflowStatus
ACTIONS = (AttemptedAction.APPROVE.value, AttemptedAction.REJECT.value, AttemptedAction.RETURN.value)
CHAIN_LEVELS = (ApprovalLevel.L1.value, ApprovalLevel.L2.value, ApprovalLevel.L3.value)
# decision_reason_code on the request when the decider gives none (ASM-P7B-03).
DEFAULT_REASON = {AttemptedAction.REJECT.value: "APPROVER_REJECTED", AttemptedAction.RETURN.value: "APPROVER_RETURNED"}
PROCESS_OWNER_ACCEPTED = "PROCESS_OWNER_ACCEPTED"
BUDGET_OVERRIDE = "BUDGET_OVERRIDE"


class DecisionRefused(Exception):
    """A process owner cannot send on a request without a valid approval path (HTTP 409); nothing is written."""


def step_key(actor_id: str, step_id: str, action: str, submission_round: int) -> str:
    """docs/06 8.2: SHA-256(actor_id | approval_step_id | action | submission_round)."""
    return sha256_hex(actor_id, step_id, action, submission_round)


def escalated_key(actor_id: str, request_id: str, action: str, submission_round: int) -> str:
    """Process-owner decision (no step): SHA-256(actor_id | 'ESCALATED' | request_id | action | round)."""
    return sha256_hex(actor_id, "ESCALATED", request_id, action, submission_round)


def resubmission_key(actor_id: str, request_id: str, next_round: int) -> str:
    """docs/06 8.3: SHA-256(actor_id | request_id | (current_round + 1))."""
    return sha256_hex(actor_id, request_id, next_round)


def resubmission_record(actor_id: str, request_type: str, request_id: str, key: str, body: dict,
                        at: datetime, status: str) -> dict:
    """The completed idempotency_record of a resubmission (docs/06 8.3), actor as employee id."""
    return {"actor_id": actor_id, "idempotency_key": key, "operation": IdempotencyOperation.RESUBMIT.value,
            "request_hash": body_hash(body), "request_type": request_type, "request_id": request_id,
            "response_hash": body_hash({"status": status}), "created_at": at, "completed_at": at}


@dataclass
class DecisionResult:
    request_type: str
    request_id: str
    submission_round: int
    actor_id: str
    action: str
    at: datetime
    correlation_id: uuid.UUID
    idempotency_key: str
    request_hash: str
    outcome: str | None = None                  # ACCEPTED / BLOCKED; None for a replay
    reason_code: str | None = None              # the blocking guard
    replayed: bool = False
    attempt: dict | None = None                 # approval_attempt row, unnumbered
    step_updates: list[dict] = field(default_factory=list)      # {approval_step_id, <changed columns>}
    approval_events: list[dict] = field(default_factory=list)   # unnumbered
    new_steps: list[dict] = field(default_factory=list)         # process owner sends on
    status_events: list[dict] = field(default_factory=list)     # request_status_event payloads
    request_updates: dict = field(default_factory=dict)         # columns of the request row
    leave_postings: list[dict] = field(default_factory=list)    # USAGE rows, unnumbered
    budget_postings: list[dict] = field(default_factory=list)   # RELEASE / OVERRIDE rows, unnumbered
    reimbursement: ReimbursementResult | None = None            # final expense approval (Phase 8)
    audit_events: list[dict] = field(default_factory=list)      # audit_event payloads, unnumbered

    @property
    def new_status(self) -> str | None:
        return self.request_updates.get("workflow_status")

    @property
    def idempotency_row(self) -> dict:
        """The completed idempotency_record (scope actor, key); actor as employee id, the DB maps it to a user."""
        response = {"outcome": self.outcome, "reason_code": self.reason_code, "status": self.new_status}
        return {"actor_id": self.actor_id, "idempotency_key": self.idempotency_key,
                "operation": IdempotencyOperation.APPROVE.value, "request_hash": self.request_hash,
                "request_type": self.request_type, "request_id": self.request_id,
                "response_hash": body_hash(response), "created_at": self.at, "completed_at": self.at}


class WorkflowStore(Protocol):
    request_type: str

    def load_request(self, request_id: str) -> dict: ...          # locked by the DB store

    def steps_of(self, request_id: str) -> list[dict]: ...        # every round, locked by the DB store

    def attempts_of(self, request_id: str) -> list[dict]: ...

    def idempotency(self, actor_id: str, key: str) -> dict | None: ...

    def roles_of(self, employee_id: str) -> set[str]: ...

    def router(self) -> ApprovalRouter | None: ...

    def next_step_sequence(self, request_id: str) -> int: ...

    def round_codes(self, request_id: str, submission_round: int) -> list[str]: ...

    def routing_inputs(self, r: dict) -> tuple[str, object, object]: ...   # (category, measure, routing date)

    def approval_effects(self, r: dict, at: datetime) -> tuple[dict, list[dict]]: ...   # (columns, USAGE rows)

    def release_postings(self, r: dict, at: datetime, reason: str) -> list[dict]: ...

    def override_postings(self, r: dict, at: datetime) -> list[dict]: ...

    def record_decision(self, result: DecisionResult) -> None: ...

    def record_reassignment(self, request_id: str, step_update: dict, event: dict, audit: dict) -> None: ...

    def record_audit(self, rows: list[dict]) -> None: ...


@dataclass(frozen=True)
class ProcessOwnerPolicy:
    """docs/05 9.5 and ASM-P4-15 for data generation: which decision a process owner takes on a set of codes."""
    approve_when_only: frozenset[str]
    reject_when_any: frozenset[str]
    return_when_any: frozenset[str]

    @classmethod
    def from_config(cls, exception_codes_cfg: dict) -> "ProcessOwnerPolicy":
        po = exception_codes_cfg["process_owner_decisions"]
        return cls(frozenset(po["approve_when_only"]), frozenset(po["reject_when_any"]),
                   frozenset(po["return_when_any"]))

    def action(self, soft_codes: set[str]) -> str | None:
        """REJECT > RETURN > APPROVE (all codes approvable); None = the request stays escalated."""
        if soft_codes & self.reject_when_any:
            return AttemptedAction.REJECT.value
        if soft_codes & self.return_when_any:
            return AttemptedAction.RETURN.value
        if soft_codes and soft_codes <= self.approve_when_only:
            return AttemptedAction.APPROVE.value
        return None


# --- shared helpers --------------------------------------------------------------------------------------------
def _fk(request_type: str, request_id: str) -> dict:
    return {"leave_request_id": request_id if request_type == RequestType.LEAVE else None,
            "expense_claim_id": request_id if request_type == RequestType.EXPENSE else None}


def _start(store: WorkflowStore, request_id: str, actor_id: str, action: str, at: datetime,
           correlation_id: uuid.UUID, key: str, body: dict, step_id: str | None) -> DecisionResult | None:
    """Idempotency (docs/06 8.2 step 1). Returns a replay result (after its IDEMPOTENT_REPLAY audit row), or None
    to go on."""
    if action not in ACTIONS:
        raise ValueError(f"unsupported action {action}")
    known = store.idempotency(actor_id, key)
    if known is None:
        return None
    if known["request_hash"] != body_hash(body):
        raise IdempotencyConflict(f"idempotency key {key[:12]}... was used for a different request")
    res = DecisionResult(store.request_type, request_id, 0, actor_id, action, at, correlation_id, key,
                         known["request_hash"], replayed=True)
    res.audit_events.append(audit_service.replay_event(
        store.request_type, request_id, "approval_step" if step_id else None, step_id, actor_id, at, correlation_id,
        IdempotencyOperation.APPROVE.value))
    store.record_audit(res.audit_events)
    return res


def _attempt(res: DecisionResult, step_id: str | None) -> dict:
    return {"actor_id": res.actor_id, "request_type": res.request_type, "request_id": res.request_id,
            **_fk(res.request_type, res.request_id), "submission_round": res.submission_round,
            "approval_step_id": step_id, "attempted_action": res.action, "attempted_at": res.at,
            "outcome": res.outcome, "reason_code": res.reason_code, "correlation_id": res.correlation_id}


def _event(res: DecisionResult, step_id: str, event_type: str, actor: str | None, reason: str | None = None,
           comment: str | None = None) -> dict:
    return {"approval_step_id": step_id, "event_type": event_type, "actor_id": actor, "occurred_at": res.at,
            "reason_code": reason, "comment": comment, "correlation_id": res.correlation_id}


def _transition(res: DecisionResult, r: dict, new: str, reason: str | None, values: dict | None = None) -> None:
    check_transition(r["workflow_status"], new)
    res.status_events.append({"previous_status": r["workflow_status"], "new_status": new, "occurred_at": res.at,
                              "actor_id": res.actor_id, "reason_code": reason, "calculated_values": values})
    res.request_updates["workflow_status"] = new
    # ASM-P5-08: the request's decision_reason_code is NULL while PENDING_APPROVAL.
    res.request_updates["decision_reason_code"] = None if new == S.PENDING_APPROVAL else reason


def _finish(store: WorkflowStore, res: DecisionResult, r: dict, new: str, reason: str | None,
            final_step: str | None = None) -> None:
    """Final effects of APPROVED / REJECTED / RETURNED_FOR_CORRECTION (docs/06 2.3). An approved expense claim
    gets its reimbursement in the same transaction (docs/06 8.2 step 6)."""
    _transition(res, r, new, reason)
    if new == S.APPROVED:
        columns, postings = store.approval_effects(r, res.at)
        res.request_updates.update(columns)
        res.leave_postings.extend(postings)
        if store.request_type == RequestType.EXPENSE:
            res.reimbursement = on_final_approval(store, {**r, **res.request_updates}, final_step, res.at,
                                                  res.correlation_id)
    else:
        res.budget_postings.extend(store.release_postings(r, res.at, new))


def _record(store: WorkflowStore, res: DecisionResult, r: dict, step: dict | None, rule_id: str | None) -> None:
    res.audit_events = audit_service.decision_events(res, r, step, rule_id)
    store.record_decision(res)


def _blocked(store: WorkflowStore, res: DecisionResult, reason: str, r: dict, step: dict | None,
             rule_id: str | None = None) -> DecisionResult:
    res.outcome, res.reason_code = AttemptOutcome.BLOCKED.value, reason
    res.attempt = _attempt(res, step["approval_step_id"] if step else None)
    _record(store, res, r, step, rule_id)
    return res


def _ancestors(employees: dict[str, dict], person: str | None) -> list[str]:
    out, seen = [], set()
    while person is not None and person not in seen:
        seen.add(person)
        person = employees[person]["manager_id"]
        if person is not None:
            out.append(person)
    return out


def holds_step(router: ApprovalRouter, step: dict, actor_id: str, requester: dict) -> bool:
    """docs/05 5.1: the step's approver, or someone who holds a higher level in the same chain: for L1-L3 a
    manager above the step's (original) approver; for L4 the requester's L5 (ASM-P7B-04)."""
    if actor_id == step["approver_employee_id"]:
        return True
    if step["required_level"] in CHAIN_LEVELS:
        base = step["delegated_from_employee_id"] or step["approver_employee_id"]
        return actor_id in _ancestors(router.org.employees, base)
    if step["required_level"] == ApprovalLevel.L4:
        return actor_id == router.org.base_approver(ApprovalLevel.L5.value, requester)
    return False


def _rule_effective(router: ApprovalRouter, rule_id: str, on) -> bool:
    rule = next((x for x in router.rules if x["approval_rule_id"] == rule_id), None)
    return rule is not None and rule["is_active"] and rule["effective_start"] <= on \
        and (rule["effective_end"] is None or on <= rule["effective_end"])


# --- step decisions --------------------------------------------------------------------------------------------
def decide_step(store: WorkflowStore, request_id: str, step_id: str, actor_id: str, action: str, at: datetime,
                correlation_id: uuid.UUID, idempotency_key: str | None = None, reason_code: str | None = None,
                comment: str | None = None) -> DecisionResult:
    """Approve, reject or return one step (docs/06 8.2). Returns the result; a blocked attempt is a normal
    result (outcome BLOCKED), not an exception."""
    r = store.load_request(request_id)
    rnd = r["current_round"]
    key = idempotency_key or step_key(actor_id, step_id, action, rnd)
    body = {"step": step_id, "action": action, "reason": reason_code, "comment": comment}
    replay = _start(store, request_id, actor_id, action, at, correlation_id, key, body, step_id)
    if replay is not None:
        return replay
    steps = store.steps_of(request_id)
    step = next((s for s in steps if s["approval_step_id"] == step_id), None)
    if step is None:
        raise KeyError(f"{step_id} is not a step of {request_id}")
    res = DecisionResult(store.request_type, request_id, rnd, actor_id, action, at, correlation_id, key,
                         body_hash(body))
    router = store.router()
    requester = router.org.employees[r["employee_id"]]
    same_round = [s for s in steps if s["submission_round"] == rnd]
    if actor_id == r["employee_id"]:
        return _blocked(store, res, BlockedReason.SELF_APPROVAL.value, r, step)
    if not holds_step(router, step, actor_id, requester):
        return _blocked(store, res, BlockedReason.UNAUTHORIZED_APPROVER.value, r, step)
    if any(a["approval_step_id"] == step_id and a["actor_id"] == actor_id and a["attempted_action"] == action
           and a["outcome"] == AttemptOutcome.ACCEPTED for a in store.attempts_of(request_id)):
        return _blocked(store, res, BlockedReason.DUPLICATE_ACTION.value, r, step)
    if step["step_status"] != StepStatus.PENDING or step["submission_round"] != rnd \
            or r["workflow_status"] != S.PENDING_APPROVAL:
        return _blocked(store, res, BlockedReason.STEP_NOT_PENDING.value, r, step)
    if any(s["sequence_no"] < step["sequence_no"] and s["step_status"] == StepStatus.PENDING for s in same_round):
        return _blocked(store, res, BlockedReason.LEVEL_SKIPPED.value, r, step)
    if not _rule_effective(router, step["approval_rule_id"], at.date()):
        return _blocked(store, res, BlockedReason.EXPIRED_RULE.value, r, step)

    res.outcome = AttemptOutcome.ACCEPTED.value
    res.attempt = _attempt(res, step_id)
    later = sorted((s for s in same_round if s["sequence_no"] > step["sequence_no"]
                    and s["step_status"] == StepStatus.PENDING), key=lambda s: s["sequence_no"])
    if action == AttemptedAction.APPROVE:
        res.step_updates.append({"approval_step_id": step_id, "step_status": StepStatus.APPROVED.value,
                                 "decision_at": at, "decision_reason_code": reason_code, "decision_comment": comment})
        res.approval_events.append(_event(res, step_id, ApprovalEventType.APPROVED.value, actor_id, reason_code,
                                          comment))
        if later:
            nxt = later[0]["approval_step_id"]
            res.step_updates.append({"approval_step_id": nxt, "assigned_at": at})
            res.approval_events.append(_event(res, nxt, ApprovalEventType.ASSIGNED.value, None))
        else:
            _finish(store, res, r, S.APPROVED.value, reason_code, step_id)
    elif action == AttemptedAction.REJECT:
        res.step_updates.append({"approval_step_id": step_id, "step_status": StepStatus.REJECTED.value,
                                 "decision_at": at, "decision_reason_code": reason_code, "decision_comment": comment})
        res.approval_events.append(_event(res, step_id, ApprovalEventType.REJECTED.value, actor_id, reason_code,
                                          comment))
        for s in later:
            res.step_updates.append({"approval_step_id": s["approval_step_id"],
                                     "step_status": StepStatus.SKIPPED.value})
            res.approval_events.append(_event(res, s["approval_step_id"], ApprovalEventType.SKIPPED.value, None))
        _finish(store, res, r, S.REJECTED.value, reason_code or DEFAULT_REASON[action])
    else:   # RETURN: the returning step and every later pending step are CANCELLED (docs/05 5.5, ASM-P7B-03)
        res.step_updates.append({"approval_step_id": step_id, "step_status": StepStatus.CANCELLED.value,
                                 "decision_reason_code": reason_code, "decision_comment": comment})
        res.approval_events.append(_event(res, step_id, ApprovalEventType.RETURNED.value, actor_id, reason_code,
                                          comment))
        for s in later:
            res.step_updates.append({"approval_step_id": s["approval_step_id"],
                                     "step_status": StepStatus.CANCELLED.value})
            res.approval_events.append(_event(res, s["approval_step_id"], ApprovalEventType.CANCELLED.value, None))
        _finish(store, res, r, S.RETURNED_FOR_CORRECTION.value, reason_code or DEFAULT_REASON[action])
    _record(store, res, r, step, step["approval_rule_id"])
    return res


# --- reassignment (AMB-P7B-11) -----------------------------------------------------------------------------------
APPROVER_EMPLOYMENT_ENDED = "APPROVER_EMPLOYMENT_ENDED"


def reassign_departed(store: WorkflowStore, request_id: str, step_id: str, at: datetime,
                      correlation_id: uuid.UUID) -> str | None:
    """AMB-P7B-11: a PENDING step whose approver's employment ended before `at` goes to the person the routing
    substitution gives on that date (docs/05 5.4: the delegate, else the next person up; never the requester).
    The step row gets the new approver (and delegated_from when a delegate is used); assigned_at and the original
    ASSIGNED event stay; a REASSIGNED approval_event (actor NULL = system, comment "old -> new") is appended.
    Returns the new approver, or None when nothing changes (approver still employed, or nobody can act)."""
    r = store.load_request(request_id)
    step = next(s for s in store.steps_of(request_id) if s["approval_step_id"] == step_id)
    if step["step_status"] != StepStatus.PENDING or step["submission_round"] != r["current_round"]:
        return None
    org = store.router().org
    old = step["approver_employee_id"]
    end = org.employees[old]["employment_end"]
    if end is None or end >= at.date():
        return None
    new, delegated_from = org.substitute(old, r["employee_id"], at.date())
    if new is None:
        return None
    update = {"approval_step_id": step_id, "approver_employee_id": new}
    if delegated_from is not None:
        update["delegated_from_employee_id"] = delegated_from
    store.record_reassignment(request_id, update, {
        "approval_step_id": step_id, "event_type": ApprovalEventType.REASSIGNED.value, "actor_id": None,
        "occurred_at": at, "reason_code": APPROVER_EMPLOYMENT_ENDED, "comment": f"{old} -> {new}",
        "correlation_id": correlation_id},
        audit_service.reassignment_event(step, old, new, at, correlation_id, APPROVER_EMPLOYMENT_ENDED))
    return new


# --- process-owner decisions (docs/05 9.4) ------------------------------------------------------------------------
def may_decide_escalated(store: WorkflowStore, router: ApprovalRouter, r: dict, actor_id: str,
                         codes: list[str]) -> bool:
    """PROCESS_OWNER role; or the requester's L4 finance controller when BUDGET_EXCEEDED is the only escalating
    code of the round (docs/05 9.4, BR-BUD-06). INFO codes (LINE_LIMIT_EXCEEDED) never escalate."""
    if RoleName.PROCESS_OWNER.value in store.roles_of(actor_id):
        return True
    escalating = {c for c in codes if c != "LINE_LIMIT_EXCEEDED"}
    requester = router.org.employees[r["employee_id"]]
    return escalating == {"BUDGET_EXCEEDED"} \
        and actor_id == router.org.base_approver(ApprovalLevel.L4.value, requester)


def decide_escalated(store: WorkflowStore, request_id: str, actor_id: str, action: str, at: datetime,
                     correlation_id: uuid.UUID, idempotency_key: str | None = None, reason_code: str | None = None,
                     comment: str | None = None) -> DecisionResult:
    """Process owner (or L4 for BUDGET_EXCEEDED) on an ESCALATED_FOR_REVIEW request: APPROVE sends it on (steps are
    created from the route at the round's submission date, AMB-P7A-02) or approves it when every step of the
    round is already approved; REJECT; RETURN. The attempt carries no step (approval_step_id NULL)."""
    r = store.load_request(request_id)
    rnd = r["current_round"]
    key = idempotency_key or escalated_key(actor_id, request_id, action, rnd)
    body = {"escalated": request_id, "action": action, "reason": reason_code, "comment": comment}
    replay = _start(store, request_id, actor_id, action, at, correlation_id, key, body, None)
    if replay is not None:
        return replay
    res = DecisionResult(store.request_type, request_id, rnd, actor_id, action, at, correlation_id, key,
                         body_hash(body))
    router = store.router()
    codes = store.round_codes(request_id, rnd)
    if actor_id == r["employee_id"]:
        return _blocked(store, res, BlockedReason.SELF_APPROVAL.value, r, None)
    if not may_decide_escalated(store, router, r, actor_id, codes):
        return _blocked(store, res, BlockedReason.UNAUTHORIZED_APPROVER.value, r, None)
    if any(a["approval_step_id"] is None and a["actor_id"] == actor_id and a["attempted_action"] == action
           and a["submission_round"] == rnd and a["outcome"] == AttemptOutcome.ACCEPTED
           for a in store.attempts_of(request_id)):
        return _blocked(store, res, BlockedReason.DUPLICATE_ACTION.value, r, None)
    if r["workflow_status"] != S.ESCALATED_FOR_REVIEW:
        return _blocked(store, res, BlockedReason.STEP_NOT_PENDING.value, r, None)

    res.outcome = AttemptOutcome.ACCEPTED.value
    rule_id = None
    if action == AttemptedAction.APPROVE:
        steps = [s for s in store.steps_of(request_id) if s["submission_round"] == rnd]
        if steps and all(s["step_status"] == StepStatus.APPROVED for s in steps):
            last = max(steps, key=lambda s: s["sequence_no"])
            rule_id = last["approval_rule_id"]
            _finish(store, res, r, S.APPROVED.value, reason_code or PROCESS_OWNER_ACCEPTED, last["approval_step_id"])
        else:
            category, measure, on = store.routing_inputs(r)
            routing: Routing = router.route(store.request_type, r["employee_id"], category, measure, on)
            if routing.finding is not None:
                raise DecisionRefused(f"{request_id}: {routing.finding.code} ({routing.finding.detail})")
            rule_id = routing.rule_id
            override = "BUDGET_EXCEEDED" in codes
            reason = reason_code or (BUDGET_OVERRIDE if override else PROCESS_OWNER_ACCEPTED)
            res.new_steps = build_steps(store.request_type, request_id, rnd, routing, at,
                                        store.next_step_sequence(request_id))
            res.approval_events.append(assignment_event(res.new_steps[0], correlation_id))
            _transition(res, r, S.PENDING_APPROVAL.value, reason, routing.as_values())
            if override:
                res.budget_postings.extend(store.override_postings(r, at))
    else:
        new = S.REJECTED.value if action == AttemptedAction.REJECT else S.RETURNED_FOR_CORRECTION.value
        _finish(store, res, r, new, reason_code or DEFAULT_REASON[action])
    res.attempt = _attempt(res, None)
    _record(store, res, r, None, rule_id)
    return res


# --- cancellation by the requester (docs/06 2.2 and 2.3; ASM-040) ------------------------------------------------
REQUESTER_CANCELLED = "REQUESTER_CANCELLED"


def cancel_request(store: WorkflowStore, request_id: str, actor_id: str, at: datetime, correlation_id: uuid.UUID,
                   reason_code: str | None = None) -> DecisionResult:
    """The requester withdraws a DRAFT, PENDING_APPROVAL or RETURNED_FOR_CORRECTION request (Phase 8). Pending
    steps of the round become CANCELLED (approval_event CANCELLED, actor NULL); an expense claim RELEASEs what it
    still holds (BR-BUD-04); one status event and its audit rows. Anyone but the requester, or any other status,
    raises IllegalTransition. Not an approval action: no approval_attempt and no idempotency record (a repeat finds
    CANCELLED, which is terminal, DEC-P8-04)."""
    r = store.load_request(request_id)
    if actor_id != r["employee_id"]:
        raise IllegalTransition("only the requester may cancel")
    rnd = r["current_round"]
    res = DecisionResult(store.request_type, request_id, rnd, actor_id, "CANCEL", at, correlation_id, "", "",
                         outcome=AttemptOutcome.ACCEPTED.value)
    _transition(res, r, S.CANCELLED.value, reason_code or REQUESTER_CANCELLED)
    for s in store.steps_of(request_id):
        if s["submission_round"] == rnd and s["step_status"] == StepStatus.PENDING:
            res.step_updates.append({"approval_step_id": s["approval_step_id"],
                                     "step_status": StepStatus.CANCELLED.value})
            res.approval_events.append(_event(res, s["approval_step_id"], ApprovalEventType.CANCELLED.value, None))
    if r["workflow_status"] != S.DRAFT:
        res.budget_postings.extend(store.release_postings(r, at, S.CANCELLED.value))
    _record(store, res, r, None, None)
    return res


# --- in-memory stores ----------------------------------------------------------------------------------------------
class InMemoryWorkflow:
    """The WorkflowStore parts shared by InMemoryLeaveStore and InMemoryExpenseStore: steps, attempts, idempotency
    records and roles. The store supplies request_type, steps, approval_events, status_events, exceptions,
    load_request(), next_step_sequence() and post_decision_rows()."""

    def init_workflow(self, roles: dict[str, set[str]] | None) -> None:
        self.roles = roles or {}
        self.attempts: list[dict] = []
        self.idempotency_records: dict[tuple[str, str], dict] = {}
        self.audit_events: list[dict] = []
        self.failures: list[dict] = []            # processing_failure rows

    def steps_of(self, request_id: str) -> list[dict]:
        return sorted(self.steps.get(request_id, []), key=lambda s: s["sequence_no"])

    def attempts_of(self, request_id: str) -> list[dict]:
        return [a for a in self.attempts if a["request_id"] == request_id]

    def idempotency(self, actor_id: str, key: str) -> dict | None:
        return self.idempotency_records.get((actor_id, key))

    def roles_of(self, employee_id: str) -> set[str]:
        return self.roles.get(employee_id, set())

    def round_codes(self, request_id: str, submission_round: int) -> list[str]:
        return [e["exception_code"] for e in self.exceptions
                if e["request_id"] == request_id and e["submission_round"] == submission_round]

    def record_idempotency(self, row: dict) -> None:
        self.idempotency_records[(row["actor_id"], row["idempotency_key"])] = row

    def record_audit(self, rows: list[dict]) -> None:
        self.audit_events.extend(rows)

    def record_decision(self, res: DecisionResult) -> None:
        rid = res.request_id
        if res.attempt is not None:                  # a cancellation has neither attempt nor key
            self.attempts.append(res.attempt)
            self.record_idempotency(res.idempotency_row)
        by_id = {s["approval_step_id"]: s for s in self.steps.get(rid, [])}
        for u in res.step_updates:
            by_id[u["approval_step_id"]].update({k: v for k, v in u.items() if k != "approval_step_id"})
        if res.new_steps:
            self.steps.setdefault(rid, []).extend(res.new_steps)
        self.approval_events.extend(res.approval_events)
        for e in res.status_events:
            self.status_events.append({"request_id": rid, "submission_round": res.submission_round,
                                       "correlation_id": res.correlation_id, **e})
        self.load_request(rid).update(res.request_updates)
        self.post_decision_rows(res)
        self.record_audit(res.audit_events)
        if res.reimbursement is not None:
            self.record_reimbursement(res.reimbursement)

    def record_reassignment(self, request_id: str, step_update: dict, event: dict, audit: dict) -> None:
        step = next(s for s in self.steps[request_id] if s["approval_step_id"] == step_update["approval_step_id"])
        step.update({k: v for k, v in step_update.items() if k != "approval_step_id"})
        self.approval_events.append(event)
        self.record_audit([audit])
