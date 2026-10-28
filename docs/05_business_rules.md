# 05. Business rules

Phase 1 deliverable. Every rule is deterministic. Every numeric value marked ASM-nnn is an illustrative synthetic default defined in docs/09 and awaiting approval; none is a real company policy. Rules are evaluated with the injectable clock; "today" never appears.

Rule IDs: BR-<area>-<nn>. Each rule names its exception code (docs/02 section 5) and its planned test.

## 1. Calendar and leave calculations

| ID | Rule | Exception | Test |
|---|---|---|---|
| BR-CAL-01 | Weekend days per country from config; default Saturday and Sunday for IN, US, GB (ASM-004). | | test_business_days |
| BR-CAL-02 | Holidays from country_holiday for the employee's country. A holiday falling on a weekend is not substituted (ASM-005). | | test_business_days |
| BR-CAL-03 | business_day_count(start, end, country) = number of dates d in [start, end] where d is not a weekend and not a holiday. Both ends inclusive. | | test_business_days |
| BR-CAL-04 | requested_quantity = business_day_count - 0.5 * start_half_day - 0.5 * end_half_day. Single-day request: only one half-day flag may be set. Flags on a non-business day -> HALF_DAY_ON_NON_BUSINESS_DAY (ASM-008). | HALF_DAY_ON_NON_BUSINESS_DAY | test_half_days |
| BR-CAL-05 | requested_quantity must be >= 0.5; otherwise ZERO_BUSINESS_DAYS (request entirely on weekends/holidays). | ZERO_BUSINESS_DAYS | test_business_days |
| BR-LBAL-01 | Leave year = calendar year (ASM-006). One leave_balance per (employee, policy, year). | | test_accrual |
| BR-LBAL-02 | Opening balance for 2025 = seeded raw input in [0, carry_forward_cap] for employees who joined before 2025-01-01, else 0 (ASM-007). Recorded as OPENING transaction. | | test_accrual |
| BR-LBAL-03 | Monthly accrual on the first day of each month = annual_entitlement / 12, rounded to 0.5 down (ASM-007). Joiner mid-month: first accrual pro-rated by remaining_days / days_in_month, rounded to 0.5 down. No accrual in months starting after employment_end. No accrual before employment_start. | | test_accrual |
| BR-LBAL-04 | Carry-forward on Jan 1: carried = min(max(available_at_dec_31, 0), carry_forward_cap). Excess expires as CARRY_FORWARD_EXPIRY. Negative available carries forward in full as negative (debt), when permitted (ASM-006). | | test_carry_forward |
| BR-LBAL-05 | Usage posted as USAGE transaction only when a request becomes APPROVED, dated at approval. Reversal (USAGE_REVERSAL) if an approved request is later cancelled (out of scope in v1; see docs/09 section 5). | | test_balance_reconciliation |
| BR-LBAL-06 | available_balance = opening + accrued + adjustments - used, maintained as a generated column on the snapshot and reconciled to SUM(ledger) by the validator. Mismatch is a validation failure, never silently corrected. | | test_balance_reconciliation |
| BR-LBAL-07 | Pending reservation: available_for_validation(date) = available_balance - SUM(requested_quantity of the employee's PENDING_APPROVAL / ESCALATED requests on the same policy and year). Computed, not posted to the ledger (ASM-034). | | test_leave_validation |
| BR-LBAL-08 | Negative balance permitted only when policy.negative_balance_allowed and resulting balance >= -negative_limit_days. Otherwise INSUFFICIENT_BALANCE at submission; or NEGATIVE_BALANCE_UNPERMITTED when found in the ledger by the detector (AM-A4). | INSUFFICIENT_BALANCE, NEGATIVE_BALANCE_UNPERMITTED | test_negative_balance_permitted_vs_anomaly |
| BR-LBAL-09 | Requests spanning two leave years split the quantity by year for balance checks and usage posting (ASM-042). Each part is checked against ITS OWN year's balance (decided AMB-P3-02, 2026-10-28): available_for_validation(year) = that year's posted ledger as of the submission date + that year's accrual/grant postings scheduled (BR-LBAL-03 schedule) on or before the part's start date and not yet posted - pending reservations of that year (BR-LBAL-07). Carry-forward into the next year is not counted, because it is unknown until Dec 31. Any failing part -> INSUFFICIENT_BALANCE. | INSUFFICIENT_BALANCE | test_cross_year_request |

## 2. Leave request validation (spec 13.1)

Order of checks is fixed; all checks run and all failing codes are recorded, then the route is decided by precedence (section 9).

| ID | Check | Exception (severity) | Test |
|---|---|---|---|
| BR-LV-01 | Employee exists and is not TERMINATED on the submission date. | LEAVE_OUTSIDE_EMPLOYMENT (HARD) | test_leave_validation |
| BR-LV-02 | start_date and end_date within [employment_start, employment_end]. | LEAVE_OUTSIDE_EMPLOYMENT (HARD) | |
| BR-LV-03 | Date ordering: end_date >= start_date (also a DB CHECK). | DB rejects; API 422 | test_api_validation |
| BR-LV-04 | Policy applicability: policy.country_scope includes employee country (ALL or match); employee service days >= min_service_days. | POLICY_NOT_APPLICABLE (HARD) | test_policy_resolution |
| BR-LV-05 | Policy version effective on submission date; request stores that version. Referencing a version not effective on that date -> POLICY_VERSION_EXPIRED. | POLICY_VERSION_EXPIRED (SOFT) | test_policy_resolution |
| BR-LV-06 | Leave type matches policy leave_type. | POLICY_NOT_APPLICABLE (HARD) | |
| BR-LV-07 | Business-day count and quantity per BR-CAL-03..05. | ZERO_BUSINESS_DAYS, HALF_DAY_ON_NON_BUSINESS_DAY (CORRECTABLE) | |
| BR-LV-08 | Available balance per BR-LBAL-07..08 (not applied to UNPAID). | INSUFFICIENT_BALANCE (HARD) | |
| BR-LV-09 | UNPAID: total unpaid days in the leave year including this request <= max_days_per_year (30, ASM-047). | UNPAID_LIMIT_EXCEEDED (HARD) | |
| BR-LV-10 | Overlap with the employee's APPROVED requests (any policy): intervals [start, end] intersect. Half-days on the shared boundary date do not count as overlap when one request ends with end_half_day and the other starts with start_half_day (ASM-008). | OVERLAPPING_APPROVED_LEAVE (HARD) | test_overlaps |
| BR-LV-11 | Overlap with PENDING_APPROVAL or ESCALATED requests. | OVERLAPPING_PENDING_LEAVE (SOFT) | test_overlaps |
| BR-LV-12 | SICK: requested_quantity > requires_medical_cert_over_days (3) requires medical_cert_flag = true. | MEDICAL_CERT_REQUIRED (CORRECTABLE) | test_medical_cert |
| BR-LV-13 | Accrual and carry-forward recomputed from ledger before the balance check; snapshot mismatch raises a ProcessingFailure (technical), not a business exception. | processing_failure | test_balance_reconciliation |

## 3. Expense validation (spec 13.2)

| ID | Check | Exception (severity) | Test |
|---|---|---|---|
| BR-EX-01 | Employee exists; each line expense_date within [employment_start, employment_end] inclusive (BC-05). | EXPENSE_OUTSIDE_EMPLOYMENT (HARD) | test_expense_validation |
| BR-EX-02 | Line expense_date <= submission date; not older than 90 days before submission (ASM-041). | EXPENSE_DATE_TOO_OLD (CORRECTABLE) | |
| BR-EX-03 | Each line resolves an expense_policy version for (category, employee country) effective on the submission date; claim.expense_policy_id = version for the highest-amount line's category. No version -> POLICY_NOT_APPLICABLE; referenced expired version -> POLICY_VERSION_EXPIRED. | POLICY_NOT_APPLICABLE (HARD), POLICY_VERSION_EXPIRED (SOFT) | test_policy_resolution |
| BR-EX-04 | Per-line limit: line_amount <= policy.per_line_limit (local currency). Breach -> line validation_result CAPPED, approved share = per_line_limit. Claim continues. | LINE_LIMIT_EXCEEDED (INFO) | test_partial_approval |
| BR-EX-05 | Per-claim limit: total_amount <= policy.per_claim_limit for the claim's primary category. | CLAIM_LIMIT_EXCEEDED (SOFT) (ASM-032) | test_expense_validation |
| BR-EX-06 | Receipt required when line_amount >= policy.receipt_threshold (inclusive, BC-08). Missing -> MISSING_RECEIPT; claim.receipt_status = MISSING. | MISSING_RECEIPT (CORRECTABLE) | test_receipt_requirement |
| BR-EX-07 | Duplicate receipt hash: a receipt whose hash equals a receipt on a line of a DIFFERENT claim. Same employee -> DUPLICATE_RECEIPT_SELF; different employee -> DUPLICATE_RECEIPT_CROSS_EMPLOYEE. Same hash on several lines of the same claim is not a duplicate. Batch detector plus at-submission check against existing claims. | DUPLICATE_RECEIPT_SELF (CORRECTABLE), DUPLICATE_RECEIPT_CROSS_EMPLOYEE (SOFT) | test_duplicate_receipt_detector |
| BR-EX-08 | Currency consistency: every line currency = claim currency = employee's country currency. | CURRENCY_MISMATCH (CORRECTABLE) | |
| BR-EX-09 | Cost center: claim.cost_center_id must be present (resolved from employee_cost_center_assignment effective on earliest line date, DEC-13), active, and effective on the submission date. | MISSING_COST_CENTER, INVALID_COST_CENTER (SOFT) | test_missing_cost_center_route |
| BR-EX-10 | Budget availability per section 6. | BUDGET_EXCEEDED (SOFT) | test_budget_ledger |
| BR-EX-11 | Arithmetic: total_amount = SUM(line_amount of current round); if quantity and unit_amount given, line_amount = round(quantity * unit_amount, 2). Enforced at write time; a mismatch in stored data is a validator failure (negative fixtures only). | validator CLAIM_TOTAL_MISMATCH | test_arithmetic |
| BR-EX-12 | Duplicate claim pattern: another claim by the same employee with identical (category set, total_amount, earliest expense_date). | DUPLICATE_CLAIM_PATTERN (SOFT) | test_expense_validation |
| BR-EX-13 | Split-claim detection per section 7. | SPLIT_CLAIM_SUSPECTED (SOFT) | test_split_claim_detector |
| BR-EX-14 | approved_amount = SUM(min(line_amount, per_line_limit)) over current-round lines that are not FAIL; reimbursement uses approved_amount (AM-B12). | | test_partial_approval |

## 4. Policy applicability and resolution

| ID | Rule |
|---|---|
| BR-POL-01 | Resolution date = submission date of the current round for both leave and expense (ASM-031). |
| BR-POL-02 | Candidate versions: same policy_family, is_active, effective_start <= date <= effective_end (NULL end = open). Exactly one must match; zero -> POLICY_NOT_APPLICABLE; more than one -> configuration error raised as ProcessingFailure (validator prevents at load). |
| BR-POL-03 | Leave policies: LPOL-ANNUAL-<CC> by country; LPOL-SICK-ALL and LPOL-UNPAID-ALL for all countries; LPOL-CASUAL-IN only for IN (ASM-006, ASM-048). |
| BR-POL-04 | Expense policies: one family per (category, country) (ASM-011). |
| BR-POL-05 | A request stores the resolved version id; later policy changes never alter stored requests. |

## 5. Approval authority and routing decision table

### 5.1 Authority levels (AM-B7)

| Level | Who | Resolution |
|---|---|---|
| L1 | Direct manager | employee.manager_id |
| L2 | Skip-level manager | manager of L1 |
| L3 | Department head | department.head_employee_id of requester's department |
| L4 | Finance controller | employee with is_finance_controller and same country as requester (one per country, ASM-014) |
| L5 | CFO-level | the employee with grade G7 in the requester's country (owner decision S19 option a, AMB-P7B-09: one G7 per country); none or two in the country -> unresolved (NO_VALID_APPROVAL_PATH). The AMB-P7A-01 fallback was removed in Phase 7B |

Authority rank: L1 < L2 < L3 < L4 < L5. An approver "holds" a level if they are the resolved person for that level for this requester, or hold a higher level in the same chain (a department head may act at L1 or L2 for their own department). Finance roles (L4, L5) are chain-independent.

### 5.2 Routing decision table (illustrative thresholds ASM-009, ASM-013; inclusivity lower-exclusive, upper-inclusive)

Expense amounts are USD-equivalent of total_amount using the fx_rate effective on the submission date.

| Rule ID | Request type | Condition | Required levels (in sequence) | Priority |
|---|---|---|---|---|
| RULE-E-001 | EXPENSE | amount_usd <= 200 | L1 | 10 |
| RULE-E-002 | EXPENSE | 200 < amount_usd <= 1,000 | L1, L2 | 10 |
| RULE-E-003 | EXPENSE | 1,000 < amount_usd <= 5,000 | L1, L2, L4 | 10 |
| RULE-E-004 | EXPENSE | amount_usd > 5,000 | L1, L2, L4, L5 | 10 |
| RULE-L-001 | LEAVE (not UNPAID) | quantity <= 5 | L1 | 10 |
| RULE-L-002 | LEAVE (not UNPAID) | 5 < quantity <= 10 | L1, L2 | 10 |
| RULE-L-003 | LEAVE (not UNPAID) | quantity > 10 | L1, L3 | 10 |
| RULE-L-004 | LEAVE, type UNPAID | any quantity | L1, L3 | 20 (overrides L-001..003) |

Rules are effective 2025-01-01 with open end. A test fixture adds RULE-E-005 (equal priority, different outcome) to exercise RULE_CONFLICT.

### 5.3 Routing algorithm

1. Select active, effective rules matching request_type, country (NULL matches all), category or leave type (NULL matches all), and amount or quantity band.
2. If several match: keep the highest priority. If more than one remains with equal priority and different required levels -> RULE_CONFLICT -> ESCALATED_FOR_REVIEW. Equal priority and identical outcome: take the lowest rule id (deterministic).
3. If none match -> NO_VALID_APPROVAL_PATH (code NO_RULE_MATCHED variant).
4. Resolve each required level to a person (section 5.1) as of the routing date, applying substitution (section 5.4).
5. Remove duplicates: if one person is resolved for two levels, keep one step at the higher level (ASM-030).
6. If any required level cannot be resolved -> NO_VALID_APPROVAL_PATH -> ESCALATED_FOR_REVIEW. Never pick an arbitrary approver (AM-B9).
7. Create approval_step rows in sequence; step 1 assigned_at = routing time.

### 5.4 Substitution when the resolved approver cannot act (ASM-030)

| Situation | Action |
|---|---|
| Resolved approver is the requester | Move to the next person up the chain for that level; if none, level unresolved |
| Resolved approver TERMINATED or employment_end < routing date | Active delegation for that approver covering the routing date -> delegate acts (approval_step.delegated_from_employee_id set); else next person up the chain; else unresolved |
| Resolved approver has an active delegation (on leave) | Delegate acts |
| Assigned approver's employment ends before the decision date (step still PENDING; AMB-P7B-11, owner 2026-10-29) | The step is reassigned by the same substitution as of the reassignment date (delegate, else next person up, never the requester): approval_step.approver_employee_id becomes the new person (delegated_from set when a delegate acts), assigned_at and the original ASSIGNED event stay, one approval_event REASSIGNED is appended (actor NULL = system, reason_code APPROVER_EMPLOYMENT_ENDED, comment "old -> new"). The new person decides under the same guards (self-approval, no skipped level). Nobody can act -> the step stays PENDING. src/services/approval_service.reassign_departed |
| Requester is G7 (top of chain) | L1/L2/L3 unresolved -> NO_VALID_APPROVAL_PATH |
| L1 is the G7 (root), so no skip-level exists for L2 (decided AMB-P3-03, 2026-10-28) | The G7 covers L2. Create ONE approval step for the G7 that records both levels it covers (L1 and L2), never two identical steps for the same person. Not NO_VALID_APPROVAL_PATH. approval_step.covered_levels (migration 0002, Phase 7A) records the levels the step covers; required_level is the highest |

### 5.5 Guards at decision time (spec 13.3)

Every approve/reject/return action writes an approval_attempt first. Outcome ACCEPTED or BLOCKED with reason:

| Guard | Reason code |
|---|---|
| actor_id = request's employee_id | SELF_APPROVAL |
| actor is not the step's approver (or delegate) and does not hold a higher level in chain | UNAUTHORIZED_APPROVER |
| step's rule not effective on the decision date | EXPIRED_RULE |
| step_status <> PENDING | STEP_NOT_PENDING |
| an earlier sequence step is still PENDING | LEVEL_SKIPPED |
| same (step_id, actor, action, idempotency key) already accepted | DUPLICATE_ACTION |

Guard order (ASM-P7B-01): SELF_APPROVAL, UNAUTHORIZED_APPROVER, DUPLICATE_ACTION, STEP_NOT_PENDING, LEVEL_SKIPPED, EXPIRED_RULE. Implemented in src/services/approval_service.py (Phase 7B); a process-owner decision on an escalated request writes an attempt with approval_step_id NULL.

Decision outcomes: APPROVED on last step -> request APPROVED (expense: reimbursement created ELIGIBLE in the same transaction, docs/06). REJECTED at any step -> request REJECTED; later steps SKIPPED. RETURN -> request RETURNED_FOR_CORRECTION; all PENDING steps CANCELLED.

## 6. Budget calculations (AM-B11)

| ID | Rule |
|---|---|
| BR-BUD-01 | available = budget_amount - actual - committed, computed from cost_center_transaction for the budget period containing the submission date. Snapshot columns on cost_center are maintained and reconciled. |
| BR-BUD-02 | On submission (and resubmission) a RESERVATION of total_amount (local currency) is posted under SELECT ... FOR UPDATE of the cost_center row. |
| BR-BUD-03 | If reservation would make available < 0 -> BUDGET_EXCEEDED (SOFT). Reservation is still posted so the escalation reviewer sees the true commitment. |
| BR-BUD-04 | REJECTED, CANCELLED and RETURNED_FOR_CORRECTION post a RELEASE of the reservation (ASM-017). |
| BR-BUD-05 | Reimbursement COMPLETED posts ACTUAL = approved_amount and RELEASE of the remaining reservation. |
| BR-BUD-06 | Finance override: process owner or L4 may approve an ESCALATED BUDGET_EXCEEDED claim; an OVERRIDE transaction with reason_code is recorded and the approval_step decision_reason_code = BUDGET_OVERRIDE. |

## 7. Split-claim detection (AM-B13, AM-H3)

| ID | Rule |
|---|---|
| BR-SPLIT-01 | Window W = 7 days (config). Threshold T = lowest expense rule upper bound (200 USD) (ASM-019). |
| BR-SPLIT-02 | Candidate group: claims of the same employee, same primary category, whose submission dates all lie within any W-day window, each with amount_usd < T, group sum >= T (inclusive, BC-10). Groups are maximal; a claim belongs to at most one group (earliest-start window wins). |
| BR-SPLIT-03 | Every claim in the group receives SPLIT_CLAIM_SUSPECTED (SOFT) and exception_class SUSPICIOUS_PATTERN. Wording everywhere: "suspected split claim, requires investigation". The words fraud or misconduct are never used (AM-H3); a test checks the catalogue text. |
| BR-SPLIT-04 | Runs at submission (against existing claims) and as a batch detector. |

## 8. Reimbursement eligibility

| ID | Rule |
|---|---|
| BR-RMB-01 | Eligible when and only when: claim.workflow_status = APPROVED, approved_amount > 0, no active (non-CANCELLED) reimbursement exists for the claim, employee not TERMINATED before the approval date (terminated employees with approved claims remain eligible; the condition is informational). |
| BR-RMB-02 | Created in the final-approval transaction with status ELIGIBLE, amount = approved_amount, currency = claim currency, approval_completion_step_id = final step (ASM-035). |
| BR-RMB-03 | Payment simulation: ELIGIBLE -> PROCESSING after a seeded delay of 1..5 business days; 5% of first attempts FAIL (PAYMENT_FAILED, processing_failure row), retried once after 2 business days; second attempt succeeds (ASM-035). |
| BR-RMB-04 | Any attempt to create a second reimbursement -> reimbursement_attempt BLOCKED DUPLICATE_REIMBURSEMENT; the partial unique index is the last line of defence. |
| BR-RMB-05 | Reimbursement for a claim not APPROVED -> attempt BLOCKED CLAIM_NOT_APPROVED. |

## 9. Exception handling strategy

### 9.1 Catalogue

See docs/02 section 5 for the code list. Each exception_code row has: code, exception_class, severity (HARD, CORRECTABLE, SOFT, INFO), default_route, requester_message_template, analyst_message_template.

### 9.2 Classification into dimensions

- workflow_status: where the request is.
- exception_class: the most severe class among current-round request_exception rows; NONE when there are none. Class order for ties at equal severity: SUSPICIOUS_PATTERN > POLICY_VIOLATION > DATA_QUALITY > NO_VALID_APPROVAL_PATH > RULE_CONFLICT (ASM-029).
- Technical failures: processing_failure rows; never an exception code.

### 9.3 Routing by precedence (ASM-029, DEC-07)

After all checks run on a submission round:

| Highest severity present | workflow_status after validation |
|---|---|
| HARD | REJECTED (decision_reason_code = first HARD code in catalogue order) |
| CORRECTABLE | RETURNED_FOR_CORRECTION |
| SOFT | ESCALATED_FOR_REVIEW |
| INFO or none | PENDING_APPROVAL (routing proceeds) |

All codes, not just the deciding one, are stored in request_exception for that round.

### 9.4 Exits from ESCALATED_FOR_REVIEW (AM-D1)

Process owner (role PROCESS_OWNER) or, for BUDGET_EXCEEDED, an L4 finance controller may: APPROVE (request goes to PENDING_APPROVAL and normal routing resumes, or directly APPROVED when the escalation happened after all steps were approved), REJECT, or RETURN_FOR_CORRECTION. The decision_reason_code records the override reason. Analysts may annotate but not decide.

### 9.5 Deterministic simulated decisions (AM-A9)

For data generation only, approver behaviour is a function of the request state:

| Request state at step | Simulated decision |
|---|---|
| exception_class = NONE or only INFO codes | APPROVE |
| SOFT codes (ESCALATED) | process owner: APPROVE when the only codes are OVERLAPPING_PENDING_LEAVE, BUDGET_EXCEEDED (override), or POLICY_VERSION_EXPIRED; REJECT for SPLIT_CLAIM_SUSPECTED and DUPLICATE_RECEIPT_CROSS_EMPLOYEE; RETURN for MISSING_COST_CENTER and INVALID_COST_CENTER (ASM-024) |
| CORRECTABLE (RETURNED) | requester resubmits with the issue fixed in 50% of cases after a seeded delay; otherwise stays RETURNED (ASM-025) |
| decision date > AS_OF_DATE | remains PENDING_APPROVAL / ESCALATED |

Delays are the only stochastic element and come from the "delays" RNG stream. Timing (Phase 7B, ASM-P7B-02): decided at 17:00 UTC on the max(1, delay)-th business day of the decider's country after the assignment day (from the next day when assigned at or after 17:00), so a decision is always more than 24 hours after its assignment; decisions after the as-of instant do not happen. When that decision date is after the approver's employment end, the step is first reassigned (section 5.4, AMB-P7B-11) at 00:00 UTC on the day after the employment end, or at the assignment when later (ASM-P7B-12); the new approver's decision follows the same rule counted from the reassignment, with its own keyed delay (request id, round, level, new approver). The oracle mirrors this in its own timing model.

## 10. Human-readable reasons (spec 13.4)

Templates per exception code and per decision, filled with computed values, for example: "Requested 6.0 days exceeds available balance of 4.5 days on LPOL-ANNUAL-IN-V1 (policy forbids negative balance)." Templates live in config/exception_codes.yaml and are the authoritative text (ASM-043, ASM-044).

Optional rewording (DEC-29, ASM-051..053): when LLM_EXPLANATIONS_ENABLED is true and GROQ_API_KEY is set, explanation_service may ask the Groq free tier to reword the template text for readability. Rules: the LLM receives only the template text and the codes, never the request data; it cannot change any decision, code, route, amount or stored value; the output is accepted only if it still contains every exception code, policy id, rule id and amount from the template and contains neither "fraud" nor "misconduct"; on any failure, timeout, rate limit or rejected output the template text is returned; the response marks source as TEMPLATE or LLM; nothing from the LLM is persisted, exported, checksummed or audited.

## 11. Decision output (spec 13.4)

For each evaluated request the service returns: request_id, request_type, current workflow_status, decision (last transition), applicable_policy_version, applicable_rule_ids, required_levels, approver_ids per level, validation_results (list of code, severity, detail), exception_codes, exception_class, human_readable_reasons, reimbursement_eligibility, technical_status (from processing_failure), audit_event_ids, correlation_id.
