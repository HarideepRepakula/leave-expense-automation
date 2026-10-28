"""Reimbursements (spec 7.11 and 10 stage 6; docs/05 section 8; docs/06 sections 4, 5.2, 8.2 step 6, 8.4 and 8.5).

- on_final_approval(): the ELIGIBLE row and its CREATE attempt, built inside the final-approval transaction of an
  expense claim (approval_service._finish). Idempotency comes from the approve action's key and the partial unique
  index (docs/06 8.4 normal path).
- create_reimbursement(): the manual path (admin API, retries after a technical failure), with its own key.
- start_payment() / settle_payment(): the payment run, ELIGIBLE or FAILED -> PROCESSING -> COMPLETED or FAILED
  (docs/06 8.5). COMPLETED posts ACTUAL = approved amount and RELEASE of the rest of the reservation (BR-BUD-05);
  FAILED writes a processing_failure row (technical, never a workflow status).
- cancel_reimbursement(): ELIGIBLE or FAILED -> CANCELLED with a reason code.

Guards for a new row, in this order (docs/06 8.4 step 3): CLAIM_NOT_APPROVED, ZERO_APPROVED_AMOUNT (BR-RMB-01,
AMB-P8-01), DUPLICATE_REIMBURSEMENT, AMOUNT_MISMATCH (amount or currency other than the claim's). A blocked attempt
is a normal result: one reimbursement_attempt BLOCKED and an audit row, nothing else. Every call writes at least
one attempt row; transitions not in lifecycle.REIMBURSEMENT_TRANSITIONS raise IllegalTransition. Who may call the
manual paths (SYSTEM_ADMIN) is checked by the API layer (Phase 9, DEC-P8-03). Actor: an employee id, or SYSTEM for
the system and the payment run.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from src.common import ids
from src.common.enums import (
    ActorType,
    EligibilityStatus,
    IdempotencyOperation,
    ReimbursementAction,
    ReimbursementAttemptOutcome,
    ReimbursementStatus,
    StepStatus,
    WorkflowStatus,
)
from src.services import audit_service
from src.services.idempotency import IdempotencyConflict, body_hash, sha256_hex
from src.services.lifecycle import check_reimbursement_transition

SYSTEM = audit_service.SYSTEM
R, A, O = ReimbursementStatus, ReimbursementAction, ReimbursementAttemptOutcome
CLAIM_NOT_APPROVED = "CLAIM_NOT_APPROVED"
ZERO_APPROVED_AMOUNT = "ZERO_APPROVED_AMOUNT"
DUPLICATE_REIMBURSEMENT = "DUPLICATE_REIMBURSEMENT"
AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
# The schema requires a reason on every attempt that is not ACCEPTED (CHECK non_accepted_has_reason), so a
# COMPLETED attempt carries this one (ASM-P8-04).
PAYMENT_COMPLETED = "PAYMENT_COMPLETED"
CANCEL_REASONS = frozenset({"DUPLICATE_FOUND", "EMPLOYEE_REQUEST", "ADMIN_CORRECTION"})   # docs/06 section 4


@dataclass
class ReimbursementResult:
    expense_claim_id: str
    action: str                                  # CREATE, PROCESS, RETRY, CANCEL
    actor_id: str                                # employee id or SYSTEM
    at: datetime
    correlation_id: uuid.UUID
    operation: str | None = None                 # IdempotencyOperation of the record, None = no own record
    idempotency_key: str | None = None
    request_hash: str | None = None
    outcome: str | None = None                   # of the call's last attempt; None for a replay
    reason_code: str | None = None
    replayed: bool = False
    reimbursement_id: str | None = None
    attempts: list[dict] = field(default_factory=list)          # reimbursement_attempt rows, unnumbered
    new_reimbursement: dict | None = None
    update: dict = field(default_factory=dict)                  # changed columns of reimbursement_id
    budget_postings: list[dict] = field(default_factory=list)   # ACTUAL / RELEASE, unnumbered
    failures: list[dict] = field(default_factory=list)          # processing_failure rows, unnumbered
    audit_events: list[dict] = field(default_factory=list)

    @property
    def status(self) -> str | None:
        if self.update:
            return self.update.get("reimbursement_status")
        return self.new_reimbursement["reimbursement_status"] if self.new_reimbursement else None

    @property
    def idempotency_row(self) -> dict | None:
        if self.operation is None or self.replayed:
            return None
        response = {"outcome": self.outcome, "reason_code": self.reason_code, "status": self.status,
                    "reimbursement_id": self.reimbursement_id}
        return {"actor_id": self.actor_id, "idempotency_key": self.idempotency_key, "operation": self.operation,
                "request_hash": self.request_hash, "request_type": "EXPENSE", "request_id": self.expense_claim_id,
                "response_hash": body_hash(response), "created_at": self.at, "completed_at": self.at}


class ReimbursementStore(Protocol):
    """Implemented by the in-memory and PostgreSQL expense stores. The DB store locks the claim and the
    reimbursement rows it returns FOR UPDATE."""

    def load_claim(self, claim_id: str) -> dict: ...

    def steps_of(self, request_id: str) -> list[dict]: ...

    def active_reimbursements(self, claim_id: str) -> list[dict]: ...      # not CANCELLED

    def load_reimbursement(self, reimbursement_id: str) -> dict: ...

    def reimbursement_attempts_of(self, reimbursement_id: str) -> list[dict]: ...

    def next_reimbursement_id(self, year: int) -> str: ...

    def completion_postings(self, claim: dict, amount: Decimal, at: datetime) -> list[dict]: ...

    def idempotency(self, actor_id: str, key: str) -> dict | None: ...

    def record_reimbursement(self, result: ReimbursementResult) -> None: ...


def create_key(actor_id: str, claim_id: str) -> str:
    """docs/06 8.4: SHA-256(actor_id | 'CREATE_REIMBURSEMENT' | expense_claim_id)."""
    return sha256_hex(actor_id, IdempotencyOperation.CREATE_REIMBURSEMENT.value, claim_id)


def process_key(reimbursement_id: str, attempt_no: int) -> str:
    """docs/06 8.5: SHA-256('PROCESS' | reimbursement_id | attempt_no)."""
    return sha256_hex(A.PROCESS.value, reimbursement_id, attempt_no)


# --- rows ------------------------------------------------------------------------------------------------------
def _attempt(res: ReimbursementResult, outcome: str, reason: str | None) -> dict:
    employee = res.actor_id != SYSTEM
    return {"actor_type": ActorType.EMPLOYEE.value if employee else ActorType.SYSTEM.value,
            "actor_employee_id": res.actor_id if employee else None, "expense_claim_id": res.expense_claim_id,
            "reimbursement_id": res.reimbursement_id, "attempted_action": res.action, "attempted_at": res.at,
            "outcome": outcome, "reason_code": reason, "correlation_id": res.correlation_id}


def _values(b: dict, res: ReimbursementResult) -> dict:
    return {"attempted_action": res.action, "approved_amount": str(b["approved_amount"]), "currency": b["currency"],
            "approval_completion_step_id": b["approval_completion_step_id"]}


def _block(res: ReimbursementResult, claim: dict, reason: str) -> ReimbursementResult:
    res.outcome, res.reason_code = O.BLOCKED.value, reason
    res.attempts.append(_attempt(res, O.BLOCKED.value, reason))
    state = claim["workflow_status"]
    res.audit_events.append(audit_service.event(
        "expense_claim", res.expense_claim_id, state, state, res.actor_id, res.at, res.correlation_id,
        reason_code=reason, values={"attempted_action": res.action, "outcome": O.BLOCKED.value}))
    return res


def creation_guard(claim: dict, active: list[dict], amount: Decimal | None = None,
                   currency: str | None = None) -> str | None:
    """docs/06 8.4 step 3 (and BR-RMB-01, 04, 05): the first failing guard, or None."""
    if claim["workflow_status"] != WorkflowStatus.APPROVED:
        return CLAIM_NOT_APPROVED
    if claim["approved_amount"] is None or claim["approved_amount"] <= 0:
        return ZERO_APPROVED_AMOUNT
    if active:
        return DUPLICATE_REIMBURSEMENT
    if (amount is not None and amount != claim["approved_amount"]) or \
            (currency is not None and currency != claim["currency"]):
        return AMOUNT_MISMATCH
    return None


def _create(store: ReimbursementStore, res: ReimbursementResult, claim: dict, step_id: str | None,
            amount: Decimal | None = None, currency: str | None = None) -> ReimbursementResult:
    reason = creation_guard(claim, store.active_reimbursements(claim["expense_claim_id"]), amount, currency)
    if reason is None and step_id is None:
        reason = CLAIM_NOT_APPROVED            # APPROVED without an approved final step: never created (V-WF-03)
    if reason is not None:
        return _block(res, claim, reason)
    res.reimbursement_id = store.next_reimbursement_id(res.at.year)
    b = {"reimbursement_id": res.reimbursement_id, "expense_claim_id": claim["expense_claim_id"],
         "employee_id": claim["employee_id"], "approved_amount": claim["approved_amount"],
         "currency": claim["currency"], "eligibility_status": EligibilityStatus.ELIGIBLE.value,
         "reimbursement_status": R.ELIGIBLE.value, "approval_completion_step_id": step_id, "created_at": res.at,
         "payment_reference": None, "completed_at": None}
    res.new_reimbursement = b
    res.outcome = O.ACCEPTED.value
    res.attempts.append(_attempt(res, O.ACCEPTED.value, None))
    res.audit_events.append(audit_service.event("reimbursement", res.reimbursement_id, None, R.ELIGIBLE.value,
                                                res.actor_id, res.at, res.correlation_id, values=_values(b, res)))
    return res


def final_step_id(steps: list[dict], claim: dict) -> str | None:
    """The last step of the claim's current round, when every step of that round is APPROVED (BR-RMB-02)."""
    rnd = [s for s in steps if s["submission_round"] == claim["current_round"]]
    if not rnd or any(s["step_status"] != StepStatus.APPROVED for s in rnd):
        return None
    return max(rnd, key=lambda s: s["sequence_no"])["approval_step_id"]


# --- creation --------------------------------------------------------------------------------------------------
def on_final_approval(store: ReimbursementStore, claim: dict, step_id: str, at: datetime,
                      correlation_id: uuid.UUID) -> ReimbursementResult:
    """docs/06 8.2 step 6: `claim` carries the columns of the approval (APPROVED, approved_amount). Actor SYSTEM
    (ASM-P8-01); no own idempotency record."""
    res = ReimbursementResult(claim["expense_claim_id"], A.CREATE.value, SYSTEM, at, correlation_id)
    return _create(store, res, claim, step_id)


def create_reimbursement(store: ReimbursementStore, claim_id: str, actor_id: str, at: datetime,
                         correlation_id: uuid.UUID, amount: Decimal | None = None, currency: str | None = None,
                         idempotency_key: str | None = None) -> ReimbursementResult:
    """docs/06 8.4 manual path: idempotency, lock the claim, guards, attempt, ELIGIBLE row, audit, record."""
    key = idempotency_key or create_key(actor_id, claim_id)
    body = {"claim": claim_id, "amount": amount, "currency": currency}
    claim = store.load_claim(claim_id)
    res = ReimbursementResult(claim_id, A.CREATE.value, actor_id, at, correlation_id,
                              IdempotencyOperation.CREATE_REIMBURSEMENT.value, key, body_hash(body))
    if _replayed(store, res):
        return res
    steps = store.steps_of(claim_id)
    _create(store, res, claim, final_step_id(steps, claim), amount, currency)
    store.record_reimbursement(res)
    return res


def _replayed(store: ReimbursementStore, res: ReimbursementResult) -> bool:
    """A known key with the same body: nothing but an IDEMPOTENT_REPLAY audit row. Another body: conflict."""
    known = store.idempotency(res.actor_id, res.idempotency_key)
    if known is None:
        return False
    if known["request_hash"] != res.request_hash:
        raise IdempotencyConflict(f"idempotency key {res.idempotency_key[:12]}... was used for a different request")
    res.replayed = True
    on = ("reimbursement", res.reimbursement_id) if res.reimbursement_id else (None, None)
    res.audit_events.append(audit_service.replay_event("EXPENSE", res.expense_claim_id, *on, res.actor_id,
                                                       res.at, res.correlation_id, res.operation))
    store.record_reimbursement(res)
    return True


# --- payment run (docs/06 8.5) ------------------------------------------------------------------------------------
def _runs(store: ReimbursementStore, reimbursement_id: str) -> list[dict]:
    return [a for a in store.reimbursement_attempts_of(reimbursement_id)
            if a["attempted_action"] in (A.PROCESS, A.RETRY) and a["outcome"] == O.ACCEPTED]


def _move(res: ReimbursementResult, b: dict, new: str, outcome: str, reason: str | None) -> None:
    check_reimbursement_transition(b["reimbursement_status"], new)
    res.outcome, res.reason_code = outcome, reason
    res.update["reimbursement_status"] = new
    res.attempts.append(_attempt(res, outcome, reason))
    res.audit_events.append(audit_service.event("reimbursement", b["reimbursement_id"], b["reimbursement_status"],
                                                new, res.actor_id, res.at, res.correlation_id, reason_code=reason,
                                                values={**_values(b, res), "outcome": outcome}))


def start_payment(store: ReimbursementStore, reimbursement_id: str, at: datetime, correlation_id: uuid.UUID,
                  attempt_no: int | None = None) -> ReimbursementResult:
    """ELIGIBLE -> PROCESSING (PROCESS) or FAILED -> PROCESSING (RETRY), actor SYSTEM. attempt_no defaults to the
    number of earlier runs + 1; calling again with the same attempt_no is a replay."""
    b = store.load_reimbursement(reimbursement_id)
    n = attempt_no or len(_runs(store, reimbursement_id)) + 1
    action = A.RETRY.value if b["reimbursement_status"] == R.FAILED else A.PROCESS.value
    key = process_key(reimbursement_id, n)
    res = ReimbursementResult(b["expense_claim_id"], action, SYSTEM, at, correlation_id,
                              IdempotencyOperation.PROCESS_PAYMENT.value, key,
                              body_hash({"reimbursement": reimbursement_id, "attempt_no": n}),
                              reimbursement_id=reimbursement_id)
    if _replayed(store, res):
        return res
    _move(res, b, R.PROCESSING.value, O.ACCEPTED.value, None)
    store.record_reimbursement(res)
    return res


def settle_payment(store: ReimbursementStore, reimbursement_id: str, at: datetime, correlation_id: uuid.UUID,
                   succeeded: bool, payment_reference: str | None = None, error_code: str = "PAYMENT_FAILED",
                   error_message: str = "simulated payment gateway failure") -> ReimbursementResult:
    """PROCESSING -> COMPLETED (ACTUAL + RELEASE, BR-BUD-05) or FAILED (processing_failure row, docs/06 6)."""
    b = store.load_reimbursement(reimbursement_id)
    runs = _runs(store, reimbursement_id)
    action = runs[-1]["attempted_action"] if runs else A.PROCESS.value
    res = ReimbursementResult(b["expense_claim_id"], action, SYSTEM, at, correlation_id,
                              reimbursement_id=reimbursement_id)
    if succeeded:
        _move(res, b, R.COMPLETED.value, O.COMPLETED.value, PAYMENT_COMPLETED)
        res.update.update(completed_at=at, payment_reference=payment_reference)
        claim = store.load_claim(b["expense_claim_id"])
        res.budget_postings.extend(store.completion_postings(claim, b["approved_amount"], at))
    else:
        _move(res, b, R.FAILED.value, O.PAYMENT_FAILED.value, error_code)
        failure = {"entity_type": "reimbursement", "entity_id": reimbursement_id,
                   "operation": IdempotencyOperation.PROCESS_PAYMENT.value, "error_code": error_code,
                   "error_message": error_message, "occurred_at": at, "correlation_id": correlation_id,
                   "resolution_status": "OPEN"}
        res.failures.append(failure)
        res.audit_events.append(audit_service.failure_event(failure))
    store.record_reimbursement(res)
    return res


def cancel_reimbursement(store: ReimbursementStore, reimbursement_id: str, actor_id: str, reason_code: str,
                         at: datetime, correlation_id: uuid.UUID) -> ReimbursementResult:
    """ELIGIBLE or FAILED -> CANCELLED (docs/06 section 4); the reason goes on the attempt and the audit row. No
    budget posting (AMB-P8-02). A second cancel is an IllegalTransition, so no idempotency record is kept."""
    if reason_code not in CANCEL_REASONS:
        raise ValueError(f"cancel reason must be one of {sorted(CANCEL_REASONS)}")
    b = store.load_reimbursement(reimbursement_id)
    res = ReimbursementResult(b["expense_claim_id"], A.CANCEL.value, actor_id, at, correlation_id,
                              reimbursement_id=reimbursement_id)
    _move(res, b, R.CANCELLED.value, O.ACCEPTED.value, reason_code)
    store.record_reimbursement(res)
    return res


# --- shared store parts --------------------------------------------------------------------------------------------
class InMemoryReimbursements:
    """The ReimbursementStore parts of InMemoryExpenseStore: reimbursements, attempts and processing failures.
    The store supplies claims, budget_ledger, audit_events, failures and record_idempotency()."""

    def init_reimbursements(self) -> None:
        self.reimbursements: dict[str, dict] = {}
        self.reimbursement_attempts: list[dict] = []

    def active_reimbursements(self, claim_id: str) -> list[dict]:
        return [b for b in self.reimbursements.values()
                if b["expense_claim_id"] == claim_id and b["reimbursement_status"] != R.CANCELLED]

    def load_reimbursement(self, reimbursement_id: str) -> dict:
        return self.reimbursements[reimbursement_id]

    def reimbursement_attempts_of(self, reimbursement_id: str) -> list[dict]:
        return [a for a in self.reimbursement_attempts if a["reimbursement_id"] == reimbursement_id]

    def next_reimbursement_id(self, year: int) -> str:
        return ids.reimbursement_id(year, 1 + sum(1 for i in self.reimbursements if i.startswith(f"RMB-{year}-")))

    def record_reimbursement(self, res: ReimbursementResult) -> None:
        if res.new_reimbursement is not None:
            self.reimbursements[res.reimbursement_id] = dict(res.new_reimbursement)
        if res.update:
            self.reimbursements[res.reimbursement_id].update(res.update)
        self.reimbursement_attempts.extend(res.attempts)
        self.budget_ledger.extend(res.budget_postings)
        self.failures.extend(res.failures)
        self.audit_events.extend(res.audit_events)
        if res.idempotency_row is not None:
            self.record_idempotency(res.idempotency_row)
