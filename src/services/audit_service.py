"""Append-only audit events (spec 15; docs/06 section 7; Phase 8).

Builders only: each function returns audit_event payloads without event_id. The stores number and write them in
the same transaction as the change they describe (in-memory stores append them in call order; the PostgreSQL stores
take AUD ids from id_sequence). entity_type is the table name (docs/10); actor_id is the acting employee id, or
SYSTEM for a system step (actor NULL on the source row). correlation_id is the operation's, so an audit row links to
the attempt, status event and approval event rows written by the same operation.

Audited in Phase 8 (docs/06 7.2): request transitions (submission, resubmission, decisions), every approval attempt
(accepted or blocked: one row on the step, or on the request when there is no step), steps a decision changes
(SKIPPED, CANCELLED), reassignments, idempotent replays, reimbursement creation, status changes and blocked attempts,
and processing failures. Not yet: ledger postings and master-data changes (AMB-P8-03).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from src.common.enums import RequestType

SYSTEM = "SYSTEM"
IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"
REQUEST_TABLE = {RequestType.LEAVE.value: "leave_request", RequestType.EXPENSE.value: "expense_claim"}
POLICY_COLUMN = {RequestType.LEAVE.value: "leave_policy_id", RequestType.EXPENSE.value: "expense_policy_id"}


def event(entity_type: str, entity_id: str, previous: str | None, new: str | None, actor: str | None,
          at: datetime, correlation_id: uuid.UUID, rule_id: str | None = None, policy_version_id: str | None = None,
          reason_code: str | None = None, values: dict | None = None) -> dict:
    """One audit_event payload (docs/06 7.1). values must be JSON-ready (decimals as text)."""
    return {"entity_type": entity_type, "entity_id": entity_id, "previous_state": previous, "new_state": new,
            "actor_id": actor or SYSTEM, "occurred_at": at, "rule_id": rule_id, "policy_version_id": policy_version_id,
            "reason_code": reason_code, "correlation_id": correlation_id, "calculated_values": values}


def request_transitions(request_type: str, request_id: str, status_events: list[dict], correlation_id: uuid.UUID,
                        rule_id: str | None = None, policy_version_id: str | None = None) -> list[dict]:
    """One audit row per request_status_event payload, same states, actor, reason and calculated values."""
    return [event(REQUEST_TABLE[request_type], request_id, e["previous_status"], e["new_status"], e["actor_id"],
                  e["occurred_at"], correlation_id, rule_id, policy_version_id, e["reason_code"],
                  e["calculated_values"]) for e in status_events]


def submission_events(request_type: str, request: dict, result) -> list[dict]:
    """A submission or resubmission (docs/06 8.1 step 7): its three transitions, with the route's rule and the
    request's policy version."""
    rule = result.routing.rule_id if result.routing is not None else None
    policy = request.get(POLICY_COLUMN[request_type]) or getattr(result.validation, "policy_id", None)
    rid = request["leave_request_id"] if request_type == RequestType.LEAVE else request["expense_claim_id"]
    return request_transitions(request_type, rid, result.events, result.correlation_id, rule, policy)


def replay_event(request_type: str, request_id: str, entity_type: str | None, entity_id: str | None,
                 actor_id: str | None, at: datetime, correlation_id: uuid.UUID, operation: str) -> dict:
    """docs/06 8.1 step 1 / 7.2: an idempotent replay writes nothing but this row (state unchanged)."""
    return event(entity_type or REQUEST_TABLE[request_type], entity_id or request_id, None, None, actor_id, at,
                 correlation_id, reason_code=IDEMPOTENT_REPLAY, values={"operation": operation})


def decision_events(res, r: dict, step: dict | None, rule_id: str | None) -> list[dict]:
    """An approve / reject / return call (accepted or blocked), docs/06 8.2 steps 5 and 7:
    - the attempt, on its step (or on the request for a process-owner decision): previous and new step state,
      the blocking guard or the decision reason;
    - every other step the decision changed (SKIPPED / CANCELLED, actor SYSTEM);
    - every request transition."""
    rtype, rid = res.request_type, res.request_id
    new_status = {u["approval_step_id"]: u["step_status"] for u in res.step_updates if "step_status" in u}
    values = {"attempted_action": res.action, "outcome": res.outcome, "submission_round": res.submission_round}
    policy = r.get(POLICY_COLUMN[rtype])
    if step is not None:
        sid, before = step["approval_step_id"], step["step_status"]
        out = [event("approval_step", sid, before, new_status.get(sid, before), res.actor_id, res.at,
                     res.correlation_id, step["approval_rule_id"], policy, res.reason_code or _reason(res, sid),
                     {**values, "required_level": step["required_level"]})]
    elif not res.status_events:      # blocked without a step: the request keeps its state
        out = [event(REQUEST_TABLE[rtype], rid, r["workflow_status"], r["workflow_status"], res.actor_id, res.at,
                     res.correlation_id, rule_id, policy, res.reason_code, {**values, "approval_step_id": None})]
    else:                            # accepted without a step: the request transition below is the attempt's row
        out = []
    for sid, status in new_status.items():
        if step is None or sid != step["approval_step_id"]:
            out.append(event("approval_step", sid, "PENDING", status, None, res.at, res.correlation_id,
                             rule_id, policy))
    out += request_transitions(rtype, rid, res.status_events, res.correlation_id, rule_id, policy)
    return out


def _reason(res, step_id: str | None) -> str | None:
    if step_id is not None:
        u = next((u for u in res.step_updates if u["approval_step_id"] == step_id), {})
        if u.get("decision_reason_code"):
            return u["decision_reason_code"]
    return res.request_updates.get("decision_reason_code")


def reassignment_event(step: dict, old: str, new: str, at: datetime, correlation_id: uuid.UUID,
                       reason: str) -> dict:
    """AMB-P7B-11: the step stays PENDING; who holds it moves (actor SYSTEM)."""
    return event("approval_step", step["approval_step_id"], "PENDING", "PENDING", None, at, correlation_id,
                 step["approval_rule_id"], reason_code=reason, values={"from": old, "to": new})


def failure_event(failure: dict) -> dict:
    """A processing_failure row (technical, docs/06 6): the entity keeps its state (previous = new = NULL)."""
    return event(failure["entity_type"] or "processing_failure", failure["entity_id"] or failure["operation"], None,
                 None, None, failure["occurred_at"], failure["correlation_id"], reason_code=failure["error_code"],
                 values={"operation": failure["operation"]})
