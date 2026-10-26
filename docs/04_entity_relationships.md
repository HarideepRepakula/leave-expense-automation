# 04. Entity relationships

Phase 1 deliverable, amended in Phase 2 (real request FKs, cost_center_budget, id_sequence, service-level currency rule). Defines every table in the `ops` schema and the `ground_truth` schema: primary keys, foreign keys, cardinalities, effective dates, lifecycle responsibility and, for every non-core entity, why it exists. The field-level data dictionary is a Phase 2 deliverable (docs/10); section 8 gives its outline.

Notation: PK = primary key, FK = foreign key, 1:N = one-to-many, N:M = many-to-many via bridge table. All IDs are text, immutable, formats in docs/07 section 3. All monetary columns NUMERIC(14,2). All timestamps `timestamptz` in UTC; all calendar dates `date` (ASM-046).

## 1. Entity inventory

### 1.1 Core entities (spec section 7)

| # | Table | PK format | Lifecycle owner |
|---|---|---|---|
| 1 | employee | EMP-000001 | master data (generator / admin) |
| 2 | leave_policy | LPOL-<TYPE>-<CC>-V<n> | process owner |
| 3 | leave_balance | LBAL-<EMP-id>-<policy>-<year> | leave_balance_service (snapshot) |
| 4 | leave_request | LVE-<yyyy>-000001 | leave_request_service + lifecycle |
| 5 | expense_policy | XPOL-<CATEGORY>-<CC>-V<n> | process owner |
| 6 | expense_claim | EXP-<yyyy>-000001 | expense_service + lifecycle |
| 7 | expense_line | EXPL-<claim-id>-NN | expense_service |
| 8 | cost_center | CC-0001 | process owner / finance |
| 9 | approval_rule | RULE-L-001 / RULE-E-001 | process owner |
| 10 | approval_step | APR-<request-id>-NN | approval_engine |
| 11 | reimbursement | RMB-<yyyy>-000001 | reimbursement_service |

### 1.2 Supporting entities and why each exists

| Table | PK format | Why it is necessary |
|---|---|---|
| department | DEPT-01 | Holds head_employee_id so authority level L3 (department head) resolves to a person without a circular text match on employee.department (AM-B7). |
| employee_cost_center_assignment | ECA-000001 | Employees change cost center over time; a claim must use the assignment effective on its expense date (AM-C). Effective-dated. |
| country_holiday | HOL-<CC>-<yyyymmdd> | Business-day calculation needs country-specific holidays (spec 7.4, AM-B2). |
| fx_rate | FX-<FROM>-<TO>-<yyyymmdd> | Thresholds are in USD; claims are in local currency (AM-B1). Effective-dated. |
| leave_balance_transaction | LBT-<yyyy>-000001 | Ledger of opening, accrual, usage, reversal, adjustment, carry-forward. Makes balances auditable and reconcilable; leave_balance is the snapshot (spec 7.3, AM-C). |
| receipt | RCT-000000001 | Owns receipt hash and metadata; lets duplicate hashes be detected across claims and employees (AM-B14). |
| cost_center_transaction | CCT-000000001 | Budget ledger: RESERVATION, RELEASE, ACTUAL, OVERRIDE. Needed for available = budget - actual - committed (AM-B11). |
| cost_center_budget | CCB-<CC>-<year> | One budget period (calendar year) per cost center with budget_amount and snapshot committed/actual columns, so CC-0001 stays a single master row across 2025 and 2026 (DEC-17, pending approval). |
| request_exception | REX-000000001 | A request can carry several exception codes at once; exception_class on the request is the summary (AM-D2). Append-only per submission round. |
| exception_code | code text | Lookup: class, severity, default route, human wording (AM-D2, AM-H3). |
| request_status_event | RSE-000000001 | Append-only history of workflow_status transitions per request (spec 15, AM-C). |
| approval_event | APE-000000001 | Append-only record of what happened to an approval step (assigned, approved, rejected, skipped, cancelled, reassigned) (AM-H1). |
| approval_attempt | APA-000000001 | Blocked approve/reject actions create no step change; this table records them so "unauthorised approval attempts" can be measured (AM-C, AM-H2). |
| reimbursement_attempt | RMA-000000001 | Payment attempts, failures, retries and blocked duplicates; reimbursement itself is unique per claim (AM-C). |
| audit_event | AUD-000000001 | Cross-entity append-only audit with prev/new state, actor, rule, policy version, reason code, correlation id, calculated values (spec 15, AM-F4). Hash-chain columns are a stretch item (DEC-20). |
| delegation | DLG-000001 | Approver on leave delegates authority for a date range (AM-B9). Effective-dated. |
| application_user | USR-000001 | Simulated login identity; linked 1:1 (optional) to an employee (AM-F2). |
| role | ROLE-<NAME> | REQUESTER, APPROVER, PROCESS_OWNER, OPS_ANALYST, SYSTEM_ADMIN. |
| user_role | (user_id, role_id) | Bridge for the genuine N:M between users and roles (spec section 9). |
| processing_failure | PFL-000000001 | Technical failures (payment gateway simulation, DB error, timeout) separate from business exceptions (AM-D3). |
| idempotency_record | (actor_user_id, idempotency_key) | Prevents repeated submission or processing; stores request hash and response (AM-C, AM-H4). |
| id_sequence | sequence_scope text | Per-scope counters (LVE-2026, EXP-2026, RMB-2026, ...) locked FOR UPDATE when the API allocates IDs (docs/06 8.1). The generator assigns IDs deterministically without it. Added in Phase 2. |

### 1.3 Ground-truth schema (no FKs from or to ops)

| Table | PK | Content |
|---|---|---|
| ground_truth.record_expectation | (record_type, record_id) | expected_route (ordered levels and approver IDs), expected_final_status_at_asof, expected_reimbursement_eligibility, expected_exception_codes, expected_approved_amount |
| ground_truth.anomaly_label | label_id | scenario_id, affected_record_type, affected_record_id, issue_type, label, expected_detection (DETECT / NOT_DETECT), expected_workflow_behaviour, injection_reason, is_planted |
| ground_truth.boundary_case | case_id | record_type, record_id, boundary_type, expected_outcome |
| ground_truth.scenario | scenario_id | issue_type, description, planned_count, actual_count |

record_id values textually match ops IDs but there is deliberately no FK; the evaluation joins by value.

## 2. Relationship catalogue

| From | To | Cardinality | FK column | Optional | Notes |
|---|---|---|---|---|---|
| employee | employee (manager) | N:1 | employee.manager_id | yes (top of chain) | Self-reference; no cycles (validated by hierarchy_service; depth <= 7) |
| employee | department | N:1 | employee.department_id | no | |
| department | employee (head) | 1:1 | department.head_employee_id | yes | head must belong to the department |
| employee | cost_center (default) | N:1 | employee.default_cost_center_id | no | |
| employee | employee_cost_center_assignment | 1:N | eca.employee_id | | effective-dated; exactly one active per date (service-enforced) |
| cost_center | employee_cost_center_assignment | 1:N | eca.cost_center_id | | |
| cost_center | department | N:1 | cost_center.department_id | no | |
| cost_center | cost_center_transaction | 1:N | cct.cost_center_id | | ledger |
| expense_claim | cost_center_transaction | 1:N | cct.expense_claim_id | yes | reservation/release/actual per claim |
| leave_policy | leave_balance | 1:N | leave_balance.leave_policy_id | | |
| leave_policy | leave_request | 1:N | leave_request.leave_policy_id | | request stores the exact version id used |
| employee | leave_balance | 1:N | leave_balance.employee_id | | UNIQUE(employee_id, leave_policy_id, leave_year) |
| leave_balance | leave_balance_transaction | 1:N | lbt.leave_balance_id | | ledger; snapshot reconciles to SUM |
| leave_request | leave_balance_transaction | 1:N | lbt.leave_request_id | yes | USAGE and USAGE_REVERSAL only |
| employee | leave_request | 1:N | leave_request.employee_id | | |
| employee | expense_claim | 1:N | expense_claim.employee_id | | |
| cost_center | expense_claim | N:1 | expense_claim.cost_center_id | yes | NULL only when exception_class <> 'NONE' (CHECK, AM-A2) |
| expense_policy | expense_claim | N:1 | expense_claim.expense_policy_id | yes | resolved policy version for the claim's primary category; may be NULL when POLICY_NOT_APPLICABLE |
| expense_claim | expense_line | 1:N | expense_line.expense_claim_id | | 1..10 lines per round; total = SUM(current round) |
| expense_policy | expense_line | N:1 | expense_line.expense_policy_id | yes | per-line resolution by category and country |
| receipt | expense_line | 1:N | expense_line.receipt_id | yes | one receipt may legitimately cover one line; several lines sharing a receipt in the SAME claim is allowed (same hash within claim is not a duplicate) |
| cost_center | expense_line | N:1 | expense_line.cost_center_id | yes | override; NULL = inherit claim's |
| approval_rule | approval_step | 1:N | approval_step.approval_rule_id | | |
| employee | approval_step (approver) | 1:N | approval_step.approver_employee_id | yes | NULL only for steps created then CANCELLED before assignment |
| leave_request | approval_step | 1:N | approval_step.leave_request_id (nullable, real FK) | | exactly one of leave_request_id / expense_claim_id is set: CHECK num_nonnulls(...) = 1; request_type discriminator CHECK-matched to the populated FK (DEC-03, revised at review) |
| expense_claim | approval_step | 1:N | approval_step.expense_claim_id (nullable, real FK) | | same CHECK |
| approval_step | approval_event | 1:N | approval_event.approval_step_id | | append-only |
| leave_request / expense_claim | request_status_event | 1:N | leave_request_id / expense_claim_id (nullable real FKs, exactly-one CHECK) | | append-only |
| leave_request / expense_claim | request_exception | 1:N | leave_request_id / expense_claim_id (nullable real FKs, exactly-one CHECK) + submission_round | | append-only |
| exception_code | request_exception | 1:N | request_exception.exception_code | | |
| leave_request / expense_claim | approval_attempt | 1:N | leave_request_id / expense_claim_id (nullable real FKs, exactly-one CHECK); request_type and request_id columns retained as required by AM-H2, with request_id CHECK-equal to the populated FK | | append-only |
| employee | approval_attempt (actor) | 1:N | approval_attempt.actor_id | | |
| expense_claim | reimbursement | 1:0..1 | reimbursement.expense_claim_id | | partial UNIQUE where status <> 'CANCELLED' |
| employee | reimbursement | 1:N | reimbursement.employee_id | | denormalised from claim for reporting; CHECK via trigger that it equals claim.employee_id |
| approval_step | reimbursement | 1:0..1 | reimbursement.approval_completion_step_id | | the final approving step |
| reimbursement | reimbursement_attempt | 1:N | reimbursement_attempt.reimbursement_id | yes | NULL when the attempt was blocked before any reimbursement existed |
| expense_claim | reimbursement_attempt | 1:N | reimbursement_attempt.expense_claim_id | | |
| employee | delegation (delegator, delegate) | 1:N twice | delegation.approver_id, delegation.delegate_id | | effective-dated; delegate <> approver |
| employee | application_user | 1:0..1 | application_user.employee_id | yes | admin users may have no employee |
| application_user | role | N:M | user_role bridge | | |
| audit_event | any entity | N:1 (polymorphic) | (entity_type, entity_id) | | the only polymorphic reference kept after review, together with processing_failure, because these two tables reference any entity type, not only requests; no FK constraint by design: audit must survive entity deletion in tests; integrity checked by validator |
| processing_failure | any entity | N:1 (polymorphic) | (entity_type, entity_id) | yes | |
| idempotency_record | leave_request / expense_claim | N:1 | leave_request_id / expense_claim_id (nullable real FKs; at most one set, both NULL while IN_PROGRESS or for non-request operations) | yes | filled once the operation succeeded |
| country_holiday | country | N:1 | country_code | | country is an enum, not a table (3 values) |
| fx_rate | currency pair | n/a | from_currency, to_currency, effective_from | | UNIQUE(from, to, effective_from) |

## 3. Effective dating and versioning

| Table | Columns | Rule |
|---|---|---|
| leave_policy, expense_policy | effective_start, effective_end (nullable), version, policy_family, is_active | A request resolves the version with effective_start <= date <= effective_end (end inclusive, BC-07). Versions of a family must not overlap (validator). Requests store the resolved version id and never re-resolve. |
| approval_rule | effective_start, effective_end, priority, is_active | Rules evaluated as of submission date of the current round. Expired rule used at decision time -> approval_attempt BLOCKED with EXPIRED_RULE. |
| employee_cost_center_assignment | effective_from, effective_to | Claims use the assignment effective on the earliest line expense_date (DEC-13). |
| fx_rate | effective_from | Latest rate with effective_from <= submission date (ASM-031). |
| delegation | effective_from, effective_to | Active if the routing date is within range. |
| cost_center | effective_from, effective_to, is_active | Inactive or expired cost center -> INVALID_COST_CENTER. |
| cost_center_budget | budget_period_start, budget_period_end | Budget period = calendar year (ASM-016). The period containing the submission date is used (DEC-17). |
| employee | employment_start, employment_end (nullable), employment_status | Dates inclusive (BC-05). |

## 4. Lifecycle responsibilities

| Entity | Status column | Values | Who changes it | History table |
|---|---|---|---|---|
| leave_request, expense_claim | workflow_status | DRAFT, SUBMITTED, VALIDATING, PENDING_APPROVAL, RETURNED_FOR_CORRECTION, APPROVED, REJECTED, CANCELLED, ESCALATED_FOR_REVIEW | lifecycle.transition() only | request_status_event |
| leave_request, expense_claim | exception_class | NONE, POLICY_VIOLATION, SUSPICIOUS_PATTERN, DATA_QUALITY, NO_VALID_APPROVAL_PATH, RULE_CONFLICT | exception_service (highest-severity class of current-round codes) | request_exception |
| approval_step | step_status | PENDING, APPROVED, REJECTED, SKIPPED, CANCELLED | approval_engine | approval_event |
| reimbursement | reimbursement_status | ELIGIBLE, PROCESSING, COMPLETED, FAILED, CANCELLED | reimbursement_service | reimbursement_attempt + audit_event |
| reimbursement | eligibility_status | ELIGIBLE, INELIGIBLE | derived at creation; never changes | |
| expense_claim | receipt_status | NOT_REQUIRED, COMPLETE, MISSING | expense_service per round | |
| employee | employment_status | ACTIVE, TERMINATED, ON_LEAVE_OF_ABSENCE | master data | audit_event |
| processing_failure | resolution_status | OPEN, RETRIED, RESOLVED, IGNORED | admin / retry job | |

Technical processing status is never written into workflow_status (AM-D3).

## 5. Key constraints to be implemented in Phase 2

| Table | Constraint |
|---|---|
| all | PK text with CHECK on regex pattern of the ID format |
| employee | CHECK employment_end IS NULL OR employment_end >= employment_start; CHECK manager_id <> employee_id |
| leave_request | CHECK end_date >= start_date; CHECK requested_quantity >= 0.5; CHECK business_day_count >= requested_quantity; UNIQUE(id) trivially; test-DB only: EXCLUDE USING gist (employee_id WITH =, daterange(start_date, end_date, '[]') WITH &&) WHERE (workflow_status = 'APPROVED') |
| leave_balance | UNIQUE(employee_id, leave_policy_id, leave_year); CHECK available_balance = opening + accrued + adjustments - used (as generated column) |
| expense_claim | CHECK (cost_center_id IS NOT NULL OR exception_class <> 'NONE'); CHECK approved_amount IS NULL OR approved_amount <= total_amount; CHECK current_round >= 1 |
| expense_line | UNIQUE(expense_claim_id, line_number); CHECK line_amount > 0; CHECK quantity IS NULL OR quantity > 0; CHECK id = 'EXPL-' + claim id + 2-digit line number. Currency = claim currency is a SERVICE rule, not a DB constraint, because CURRENCY_MISMATCH (S26) is a planted anomaly that must be able to exist in the dataset (amendment A2; corrected in Phase 2) |
| receipt | UNIQUE(receipt_id); INDEX on receipt_hash (not unique: duplicates are an anomaly to detect, not to prevent) |
| approval_step, request_status_event, request_exception, approval_attempt | leave_request_id REFERENCES leave_request, expense_claim_id REFERENCES expense_claim, both nullable; CHECK (num_nonnulls(leave_request_id, expense_claim_id) = 1); CHECK ((request_type = 'LEAVE' AND leave_request_id IS NOT NULL) OR (request_type = 'EXPENSE' AND expense_claim_id IS NOT NULL)); where a request_id text column is kept (approval_attempt per AM-H2) CHECK request_id = COALESCE(leave_request_id, expense_claim_id) |
| idempotency_record | same two nullable FKs; CHECK (num_nonnulls(leave_request_id, expense_claim_id) <= 1) |
| approval_step | UNIQUE(COALESCE(leave_request_id, expense_claim_id), sequence_no) via a unique index on the coalesced expression; CHECK decision_at IS NULL OR decision_at >= assigned_at; trigger: no UPDATE when step_status <> 'PENDING' |
| approval_rule | CHECK min_amount IS NULL OR max_amount IS NULL OR min_amount < max_amount; CHECK priority >= 1 |
| reimbursement | UNIQUE (expense_claim_id) WHERE reimbursement_status <> 'CANCELLED' (partial); CHECK approved_amount > 0 |
| cost_center_transaction | CHECK txn_type IN ('RESERVATION','RELEASE','ACTUAL','OVERRIDE') |
| leave_balance_transaction | CHECK txn_type IN ('OPENING','ACCRUAL','USAGE','USAGE_REVERSAL','ADJUSTMENT','CARRY_FORWARD','CARRY_FORWARD_EXPIRY') |
| audit_event and all event/attempt/ledger tables | trigger: RAISE on UPDATE or DELETE |
| user_role | PK (user_id, role_id) |
| fx_rate | UNIQUE(from_currency, to_currency, effective_from) |
| delegation | CHECK approver_id <> delegate_id; CHECK effective_to >= effective_from |

## 6. Cardinality summary diagram (text)

```
department 1---N employee N---1 employee(manager)
department 1---1 employee(head)
employee 1---N employee_cost_center_assignment N---1 cost_center 1---N cost_center_transaction
employee 1---N leave_balance N---1 leave_policy
leave_balance 1---N leave_balance_transaction N---0..1 leave_request
employee 1---N leave_request N---1 leave_policy(version)
employee 1---N expense_claim N---0..1 cost_center
expense_claim 1---N expense_line N---0..1 receipt
expense_line N---0..1 expense_policy(version)
expense_claim 1---0..1 reimbursement 1---N reimbursement_attempt
leave_request 1---N approval_step (leave_request_id)      expense_claim 1---N approval_step (expense_claim_id)
   [each step row sets exactly one of the two FKs]        approval_step N---1 approval_rule
approval_step N---1 employee(approver)
approval_step 1---N approval_event
leave_request|expense_claim 1---N request_status_event        (two nullable FKs, exactly one set)
leave_request|expense_claim 1---N request_exception N---1 exception_code   (same pattern)
leave_request|expense_claim 1---N approval_attempt N---1 employee(actor)   (same pattern)
employee 1---N delegation(approver) ; employee 1---N delegation(delegate)
employee 1---0..1 application_user N---M role   (bridge: user_role)
audit_event --(polymorphic entity_type, entity_id)--> any
processing_failure --(polymorphic)--> any
idempotency_record --(leave_request_id | expense_claim_id, nullable FKs)--> request
```

## 7. Decisions embedded in this document (listed in docs/09 section 4)

- DEC-04 No PolicyVersion table; version in policy row and ID.
- DEC-10 Receipt hash stored on receipt only.
- DEC-03 / DEC-12 (revised at review) Real foreign keys for request references: nullable leave_request_id and expense_claim_id with CHECK that exactly one is set, on approval_step, request_status_event, request_exception and approval_attempt (at most one on idempotency_record). request_type is kept as a CHECK-matched discriminator. Only audit_event and processing_failure remain polymorphic because they reference any entity.
- DEC-13 Cost center assignment resolved on the earliest line expense_date.
- DEC-14 All lines in a claim share the claim currency.
- DEC-15 Department table added as a supporting entity.
- DEC-16 Expense line optional cost_center_id override.

## 8. Data dictionary outline (superseded by docs/10_data_dictionary.md, which is authoritative from Phase 2)

For every table the dictionary will list each field with: name, type, required, PK/FK, allowed values, units, uniqueness, default, validation rule, relationship, effective-date behaviour, origin (generated / calculated / user-supplied / derived).

Field groups per core entity (from spec section 7, plus amendments):

- employee: employee_id, full_name, email (synthetic), manager_id, department_id, job_title, grade (G1..G7), country (IN/US/GB), currency, employment_start, employment_end, employment_status, default_cost_center_id, is_department_head, is_finance_controller, created_at.
- leave_policy: leave_policy_id, policy_family, version, policy_name, leave_type, country_scope, annual_entitlement_days, accrual_method, carry_forward_cap_days, negative_balance_allowed, negative_limit_days, min_service_days, requires_medical_cert_over_days, max_days_per_year (unpaid), effective_start, effective_end, is_active.
- leave_balance: leave_balance_id, employee_id, leave_policy_id, leave_year, opening_balance, accrued, adjustments, used, available_balance (generated), last_recalculated_at.
- leave_request: leave_request_id, employee_id, leave_policy_id, start_date, end_date, start_half_day, end_half_day, submitted_at (first), current_round, business_day_count, requested_quantity, workflow_status, exception_class, medical_cert_flag, decision_reason_code, decision_reason_text, created_at.
- expense_policy: expense_policy_id, policy_family, version, policy_name, country, category, currency, per_line_limit, per_claim_limit, receipt_threshold, requires_pre_approval (bool, unused in v1), effective_start, effective_end, is_active.
- expense_claim: expense_claim_id, employee_id, submitted_at, claim_period_start, claim_period_end, country, currency, cost_center_id, expense_policy_id, total_amount, approved_amount, total_amount_usd, workflow_status, exception_class, receipt_status, current_round, decision_reason_code, decision_reason_text, created_at.
- expense_line: expense_line_id, expense_claim_id, line_number, submission_round, category, merchant_description, expense_date, quantity, unit_amount, line_amount, currency, receipt_id, cost_center_id, expense_policy_id, validation_result (PASS / CAPPED / FAIL), validation_detail.
- cost_center: cost_center_id, name, department_id, country, currency, budget_period_start, budget_period_end, budget_amount, committed_amount (snapshot), actual_amount (snapshot), is_active, effective_from, effective_to.
- approval_rule: approval_rule_id, request_type, country (nullable = all), category_or_leave_type (nullable), min_amount_usd, max_amount_usd (or min_days, max_days), required_level, approval_sequence, priority, effective_start, effective_end, is_active.
- approval_step: approval_step_id, request_type, leave_request_id, expense_claim_id, submission_round, sequence_no, approval_rule_id, required_level, approver_employee_id, delegated_from_employee_id, step_status, assigned_at, decision_at, decision_reason_code, decision_comment.
- reimbursement: reimbursement_id, expense_claim_id, employee_id, approved_amount, currency, eligibility_status, reimbursement_status, approval_completion_step_id, created_at, payment_reference, completed_at.

Supporting entities follow the same template; approval_attempt fields are fixed by AM-H2.
