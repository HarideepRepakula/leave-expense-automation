"""Request state machine as data (docs/06 section 2.2, section 9).

The table lives once, here. Phase 5 uses it for the leave submission path (DRAFT -> SUBMITTED -> VALIDATING ->
outcome); Phase 7 adds the actor checks and the approval-step machine. Anything not listed is illegal.
"""
from __future__ import annotations

from src.common.enums import WorkflowStatus as S

SYSTEM, REQUESTER, APPROVER, PROCESS_OWNER = "system", "requester", "step approver", "process owner"

# (from, to) -> (trigger, actor allowed)
REQUEST_TRANSITIONS: dict[tuple[str, str], tuple[str, str]] = {
    (S.DRAFT, S.SUBMITTED): ("submit", REQUESTER),
    (S.DRAFT, S.CANCELLED): ("cancel", REQUESTER),
    (S.SUBMITTED, S.VALIDATING): ("automatic", SYSTEM),
    (S.VALIDATING, S.PENDING_APPROVAL): ("no HARD/CORRECTABLE/SOFT codes; steps created", SYSTEM),
    (S.VALIDATING, S.REJECTED): ("HARD code present", SYSTEM),
    (S.VALIDATING, S.RETURNED_FOR_CORRECTION): ("CORRECTABLE present, no HARD", SYSTEM),
    (S.VALIDATING, S.ESCALATED_FOR_REVIEW): ("SOFT present, no HARD/CORRECTABLE; or routing failure", SYSTEM),
    (S.PENDING_APPROVAL, S.APPROVED): ("last step approved", APPROVER),
    (S.PENDING_APPROVAL, S.REJECTED): ("a step rejected", APPROVER),
    (S.PENDING_APPROVAL, S.RETURNED_FOR_CORRECTION): ("step approver returns", APPROVER),
    (S.PENDING_APPROVAL, S.ESCALATED_FOR_REVIEW): ("approver escalates or becomes unresolvable", APPROVER),
    (S.PENDING_APPROVAL, S.CANCELLED): ("cancel", REQUESTER),
    (S.RETURNED_FOR_CORRECTION, S.SUBMITTED): ("resubmit (round + 1)", REQUESTER),
    (S.RETURNED_FOR_CORRECTION, S.CANCELLED): ("cancel", REQUESTER),
    (S.ESCALATED_FOR_REVIEW, S.PENDING_APPROVAL): ("process owner accepts; routing resumes", PROCESS_OWNER),
    (S.ESCALATED_FOR_REVIEW, S.APPROVED): ("process owner approves; no steps remain", PROCESS_OWNER),
    (S.ESCALATED_FOR_REVIEW, S.REJECTED): ("process owner rejects", PROCESS_OWNER),
    (S.ESCALATED_FOR_REVIEW, S.RETURNED_FOR_CORRECTION): ("process owner returns", PROCESS_OWNER),
}
TERMINAL = frozenset({S.APPROVED.value, S.REJECTED.value, S.CANCELLED.value})
MAX_ROUNDS = 3   # ASM-025: a request returned in its third round stays RETURNED_FOR_CORRECTION


class IllegalTransition(Exception):
    """Raised for any transition not in REQUEST_TRANSITIONS (HTTP 409 in Phase 9)."""


def check_transition(current: str, new: str) -> tuple[str, str]:
    try:
        return REQUEST_TRANSITIONS[(S(current), S(new))]
    except (KeyError, ValueError):
        raise IllegalTransition(f"{current} -> {new} is not a legal request transition") from None


def check_resubmission(r: dict, actor_id: str | None) -> None:
    """docs/06 8.3 step 2: only the requester, only from RETURNED_FOR_CORRECTION, at most MAX_ROUNDS rounds."""
    check_transition(r["workflow_status"], S.SUBMITTED.value)
    if r["workflow_status"] != S.RETURNED_FOR_CORRECTION:
        raise IllegalTransition(f"{r['workflow_status']} -> SUBMITTED is a submission, not a resubmission")
    if actor_id is not None and actor_id != r["employee_id"]:
        raise IllegalTransition("only the requester may resubmit")
    if r["current_round"] >= MAX_ROUNDS:
        raise IllegalTransition(f"round {r['current_round']} is the last allowed round (maximum {MAX_ROUNDS})")
