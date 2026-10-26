# 06. Lifecycle, audit, transactions and idempotency

Phase 1 deliverable. Defines the glossary (AM-H1), the state machines for requests, approval steps and reimbursements, approval and reimbursement attempts (AM-H2), the append-only audit model (spec 15, AM-F4), and the transaction boundaries and idempotency keys for submit, approve/reject, resubmit and create-reimbursement (AM-H4).

## 1. Glossary (AM-H1)

| Term | Definition |
|---|---|
| Request | The business object: a leave_request or an expense_claim. Identified by (request_type, request_id). |
| Submission round | One submit or resubmit cycle of a request. current_round starts at 1 and increments on each resubmission. Lines, exceptions and steps are tagged with the round they belong to. |
| Approval step | One required approval in a round, at one authority level, assigned to one approver. ID APR-<request-id>-NN with NN continuing across rounds. |
| Approval event | Append-only record of something that happened to a step: ASSIGNED, APPROVED, REJECTED, RETURNED, SKIPPED, CANCELLED, REASSIGNED. |
| Approval attempt | Any attempted approve, reject or return action by any actor, including ones the system blocked. Outcome ACCEPTED or BLOCKED with reason_code. |
| Reimbursement attempt | Any attempt to create or process a reimbursement, including blocked duplicates and failed payments. |
| Workflow status | Where the request is in its lifecycle. One of nine values (section 2). |
| Exception class | Summary of the business exceptions on the current round (NONE when clean). Independent of workflow status. |
| Processing failure | A technical error (database, payment gateway simulation, timeout). Never a workflow status. |
| Audit event | Append-only cross-entity record of a state change or decision, with before/after state, actor, rule, policy version, reason and correlation id. |
| Correlation id | UUID generated per API call or per generator operation; shared by every event, attempt and audit row written in that operation. |
| AS_OF_DATE | 2026-10-22, the frozen "now" for generation and evaluation. |

## 2. Request state machine (leave_request and expense_claim)

### 2.1 States

| State | Meaning | Resting at AS_OF_DATE? |
|---|---|---|
| DRAFT | Created, not submitted | yes (generator creates a small number, ASM-022) |
| SUBMITTED | Submit received; idempotency recorded; round opened | no (transient) |
| VALIDATING | Rules running. Transient, but every round writes two request_status_event rows through it (SUBMITTED -> VALIDATING, VALIDATING -> outcome), each with an audit_event, so the history is complete (DEC-08, confirmed at review) | no (transient) |
| PENDING_APPROVAL | Steps created, awaiting decisions | yes |
| RETURNED_FOR_CORRECTION | Correctable issue or approver return; requester must resubmit | yes |
| ESCALATED_FOR_REVIEW | Soft exception, routing failure or rule conflict; process owner must decide | yes |
| APPROVED | Final approval given (terminal) | yes |
| REJECTED | Hard failure or approver rejection (terminal) | yes |
| CANCELLED | Withdrawn by requester before final decision (terminal) | yes |

### 2.2 Legal transitions

| From | To | Trigger | Actor allowed |
|---|---|---|---|
| DRAFT | SUBMITTED | submit | requester (owner) |
| DRAFT | CANCELLED | cancel | requester |
| SUBMITTED | VALIDATING | automatic | system |
| VALIDATING | PENDING_APPROVAL | no HARD/CORRECTABLE/SOFT codes; steps created | system |
| VALIDATING | REJECTED | HARD code present | system |
| VALIDATING | RETURNED_FOR_CORRECTION | CORRECTABLE present, no HARD | system |
| VALIDATING | ESCALATED_FOR_REVIEW | SOFT present, no HARD/CORRECTABLE; or NO_VALID_APPROVAL_PATH; or RULE_CONFLICT | system |
| PENDING_APPROVAL | APPROVED | last step APPROVED | approver of last step (or delegate) |
| PENDING_APPROVAL | REJECTED | any step REJECTED | step approver |
| PENDING_APPROVAL | RETURNED_FOR_CORRECTION | step approver returns | step approver |
| PENDING_APPROVAL | ESCALATED_FOR_REVIEW | step approver escalates; or approver becomes unresolvable (termination without delegate) | step approver / system |
| PENDING_APPROVAL | CANCELLED | cancel | requester |
| RETURNED_FOR_CORRECTION | SUBMITTED | resubmit (round + 1) | requester |
| RETURNED_FOR_CORRECTION | CANCELLED | cancel | requester |
| ESCALATED_FOR_REVIEW | PENDING_APPROVAL | process owner accepts and routing resumes | PROCESS_OWNER (or L4 for BUDGET_EXCEEDED) |
| ESCALATED_FOR_REVIEW | APPROVED | process owner approves and no steps remain | PROCESS_OWNER / L4 |
| ESCALATED_FOR_REVIEW | REJECTED | process owner rejects | PROCESS_OWNER / L4 |
| ESCALATED_FOR_REVIEW | RETURNED_FOR_CORRECTION | process owner returns | PROCESS_OWNER / L4 |
| APPROVED, REJECTED, CANCELLED | any | none | nobody (terminal) |

Everything not in the table is illegal and raises IllegalTransition (HTTP 409). Cancellation of an APPROVED leave or claim is out of scope for v1 (docs/09 section 5, ASM-040).

### 2.3 Effects on other tables per transition

| Transition | Side effects (same transaction) |
|---|---|
| -> SUBMITTED | idempotency_record inserted; round opened; expense: RESERVATION posted |
| -> PENDING_APPROVAL | approval_step rows created; approval_event ASSIGNED for step 1 |
| -> REJECTED / RETURNED / CANCELLED | pending steps -> SKIPPED (after a rejection) or CANCELLED (return/cancel); expense: RELEASE posted |
| -> APPROVED | leave: USAGE transaction posted, leave_balance snapshot updated; expense: reimbursement ELIGIBLE created |
| every transition | request_status_event appended; audit_event appended |

## 3. Approval step state machine

| From | To | Trigger |
|---|---|---|
| PENDING | APPROVED | accepted approve action by the step approver or delegate, all earlier steps APPROVED |
| PENDING | REJECTED | accepted reject action |
| PENDING | SKIPPED | an earlier step in the round was REJECTED (later steps never needed) |
| PENDING | CANCELLED | request RETURNED_FOR_CORRECTION, CANCELLED, resubmitted, or re-routed after ESCALATED |
| APPROVED, REJECTED, SKIPPED, CANCELLED | any | none; decided steps are frozen by trigger |

All steps for a round are created at routing time with step_status PENDING. assigned_at of step n+1 is set when step n is APPROVED (an approval_event ASSIGNED is written then). Resubmission creates new steps with NN continuing (AM-A5).

## 4. Reimbursement state machine

| From | To | Trigger | Attempt row |
|---|---|---|---|
| (none) | ELIGIBLE | final approval of expense claim | reimbursement_attempt CREATE ACCEPTED |
| ELIGIBLE | PROCESSING | payment run picks it up | attempt PROCESS ACCEPTED |
| PROCESSING | COMPLETED | payment confirmed; ACTUAL posted to budget ledger | attempt outcome COMPLETED |
| PROCESSING | FAILED | payment failure; processing_failure row | attempt outcome PAYMENT_FAILED |
| FAILED | PROCESSING | retry | attempt RETRY ACCEPTED |
| ELIGIBLE, FAILED | CANCELLED | system administrator cancels with a reason code (DUPLICATE_FOUND, EMPLOYEE_REQUEST, ADMIN_CORRECTION) | attempt CANCEL ACCEPTED |
| COMPLETED, CANCELLED | any | none |

eligibility_status is set once at creation (ELIGIBLE) and never changes; a claim that is not APPROVED cannot produce a row at all (attempt BLOCKED CLAIM_NOT_APPROVED).

## 5. Attempts (AM-H2)

### 5.1 approval_attempt

| Field | Content |
|---|---|
| attempt_id | APA-000000001 |
| actor_id | employee_id of the person acting |
| request_type, request_id, submission_round | target, as required by AM-H2 |
| leave_request_id, expense_claim_id | nullable real FKs; exactly one set and CHECK-equal to request_id (DEC-03) |
| approval_step_id | nullable: NULL when no step could be identified (e.g. request not pending) |
| attempted_action | APPROVE, REJECT, RETURN, ESCALATE |
| attempted_at | from clock |
| outcome | ACCEPTED, BLOCKED |
| reason_code | NULL when ACCEPTED; SELF_APPROVAL, UNAUTHORIZED_APPROVER, EXPIRED_RULE, DUPLICATE_ACTION, STEP_NOT_PENDING, LEVEL_SKIPPED when BLOCKED |
| correlation_id | per operation |

Written in every approve/reject/return call before any state change. Blocked attempts leave the request untouched.

### 5.2 reimbursement_attempt

| Field | Content |
|---|---|
| attempt_id | RMA-000000001 |
| actor_id | employee_id or 'SYSTEM' user for scheduled payment runs |
| expense_claim_id | target claim |
| reimbursement_id | nullable |
| attempted_action | CREATE, PROCESS, RETRY, CANCEL |
| attempted_at | clock |
| outcome | ACCEPTED, BLOCKED, COMPLETED, PAYMENT_FAILED |
| reason_code | DUPLICATE_REIMBURSEMENT, CLAIM_NOT_APPROVED, AMOUNT_MISMATCH, or payment failure code |
| correlation_id | |

## 6. Exception handling in the lifecycle

- Exceptions are evaluated per round and stored in request_exception (append-only). A new round does not delete earlier rows; exception_class on the request reflects the current round only.
- ESCALATED_FOR_REVIEW is a workflow state; the reason is in request_exception; the two are never merged.
- Technical failures during any transition roll back the transaction and write a processing_failure row in a separate transaction with the same correlation_id; the request stays in its previous state.

## 7. Append-only audit model (spec 15, AM-F4)

### 7.1 audit_event columns

event_id (AUD-000000001), entity_type, entity_id, previous_state, new_state, actor_id, occurred_at, rule_id (nullable), policy_version_id (nullable), reason_code (nullable), correlation_id, calculated_values (JSONB: e.g. business_day_count, available_balance_before/after, amount_usd, fx_rate_used). Stretch (DEC-20): prev_hash, row_hash.

### 7.2 What is audited

Every request transition, every step decision, every attempt (accepted or blocked), every reimbursement status change, every ledger posting (balance and budget), every master-data change through the API (policy, rule, user, delegation), every idempotent replay (IDEMPOTENT_REPLAY), every processing failure.

### 7.3 Immutability mechanisms

1. Trigger raising on UPDATE and DELETE on audit_event, request_status_event, approval_event, approval_attempt, reimbursement_attempt, leave_balance_transaction, cost_center_transaction and request_exception. idempotency_record is not strictly append-only (its status moves IN_PROGRESS -> COMPLETED), so its trigger blocks DELETE and blocks changes to the key fields only (corrected in Phase 2).
2. Role lea_app has INSERT and SELECT only on those tables.
3. Primary keys are immutable by trigger on all ops tables.
4. Stretch, low priority (DEC-20, ASM-045): hash chain with row_hash = SHA-256(prev_hash || canonical JSON of the row without hashes) and prev_hash = row_hash of the previous event by event_id order, with a validator that recomputes the chain. Mechanisms 1-3 are the required protection; the chain is added only if time allows at the end of Phase 8.

### 7.4 Documented limits

A superuser, or the lea_migrator owner, can disable triggers, alter rows or rewrite the chain. The protection is against application defects and ordinary users. Phase 12 documentation states this and recommends, for a real deployment, shipping audit rows to an external write-once store, which this project does not implement.

## 8. Transaction boundaries and idempotency keys (AM-H4)

General pattern: one SQLAlchemy session, one transaction, per use case. Attempt rows that must survive a business refusal are written in the same transaction and the refusal is returned as a normal result, not an exception that rolls back. Technical errors roll back everything and then a second short transaction records processing_failure.

### 8.1 Submit (leave or expense)

Idempotency key: client-supplied header `Idempotency-Key`; if absent, derived = SHA-256(actor_id | request_type | canonical JSON of the payload). Scope: (actor_id, key). Generator uses derived keys.

Transaction:
1. Insert idempotency_record(key, actor_id, request_hash, status=IN_PROGRESS). Unique violation -> read existing: if request_hash matches and status=COMPLETED -> return stored response (HTTP 200, same body, audit IDEMPOTENT_REPLAY); if hash differs -> HTTP 409; if IN_PROGRESS -> HTTP 409 retry-later.
2. Allocate request id (per-year counter row locked FOR UPDATE), insert request (DRAFT->SUBMITTED events), lines, receipts.
3. Lock leave_balance row (leave) or cost_center row (expense) FOR UPDATE.
4. Run validation; insert request_exception rows; set exception_class.
5. Expense: post RESERVATION.
6. Route: select rules, resolve approvers, insert approval_step rows and ASSIGNED event, or set ESCALATED.
7. Insert request_status_event rows (SUBMITTED, VALIDATING, outcome) and audit_event rows.
8. Update idempotency_record: status=COMPLETED, response_hash, request_id.
9. Commit.

### 8.2 Approve / reject / return

Idempotency key: client header, else derived = SHA-256(actor_id | approval_step_id | action | submission_round). Scope: (actor_id, key).

Transaction:
1. Idempotency insert as above (replay returns stored result).
2. Lock approval_step FOR UPDATE; lock the request row FOR UPDATE.
3. Evaluate guards (docs/05 section 5.5) -> outcome.
4. Insert approval_attempt (ACCEPTED or BLOCKED).
5. If BLOCKED: insert audit_event; update idempotency_record COMPLETED; commit; return HTTP 403 (self/unauthorised), 409 (not pending, skipped, duplicate), 422 (expired rule) with structured body.
6. If ACCEPTED: update step (status, decision_at, reason, comment); insert approval_event; if APPROVE and more steps: set next step assigned_at, ASSIGNED event; if APPROVE and last step: request -> APPROVED, leave USAGE posting with leave_balance locked, or expense reimbursement row ELIGIBLE plus reimbursement_attempt CREATE ACCEPTED; if REJECT: request -> REJECTED, remaining steps SKIPPED, RELEASE posted; if RETURN: request -> RETURNED_FOR_CORRECTION, pending steps CANCELLED, RELEASE posted.
7. request_status_event and audit_event rows; idempotency COMPLETED; commit.

### 8.3 Resubmit

Idempotency key: client header, else derived = SHA-256(actor_id | request_id | (current_round + 1)). Scope: (actor_id, key).

Transaction:
1. Idempotency insert.
2. Lock request FOR UPDATE; require workflow_status = RETURNED_FOR_CORRECTION and current_round < max_rounds (3, ASM-025) else IllegalTransition 409.
3. Cancel any PENDING steps (CANCELLED events).
4. current_round += 1; for expense: insert corrected lines tagged with the new round (line numbers continue, DEC-11); old lines remain; total_amount recomputed over the new round's lines. For leave: dates and flags may change; history preserved via request_status_event calculated_values snapshot.
5. Steps 3-9 of Submit (validation, reservation, routing, events). APR numbering continues (AM-A5).
6. Commit.

### 8.4 Create reimbursement

Normal path: inside the final-approval transaction (8.2 step 6). Idempotency comes from the partial unique index and from the approve action's key.

Manual path (admin API, used for retries after a technical failure): key = client header, else derived = SHA-256(actor_id | 'CREATE_REIMBURSEMENT' | expense_claim_id).

Transaction:
1. Idempotency insert.
2. Lock expense_claim FOR UPDATE.
3. Guards: status APPROVED (else attempt BLOCKED CLAIM_NOT_APPROVED), no active reimbursement (else BLOCKED DUPLICATE_REIMBURSEMENT), amount = approved_amount (else BLOCKED AMOUNT_MISMATCH).
4. Insert reimbursement_attempt; if BLOCKED commit and return 409.
5. Insert reimbursement ELIGIBLE (partial unique index is the final guard; a violation here is a race and is converted into a BLOCKED attempt in a new transaction).
6. audit_event; idempotency COMPLETED; commit.

### 8.5 Payment processing (simulation and admin trigger)

Key = SHA-256('PROCESS' | reimbursement_id | attempt_no). Lock reimbursement FOR UPDATE; transition ELIGIBLE/FAILED -> PROCESSING -> COMPLETED or FAILED; on COMPLETED post ACTUAL and RELEASE to the budget ledger with the cost_center row locked; on FAILED write processing_failure.

## 9. Consistency across layers (spec 14)

- The transition table lives once, in src/services/lifecycle.py, as data. The DB stores status as text with a CHECK on the allowed set; a test loads the table and verifies the CHECK lists match. The API exposes the same enum through Pydantic. The dashboard reads the enum from the same module.
- A test replays every legal transition and asserts every illegal one raises.
