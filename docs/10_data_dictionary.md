# 10. Data dictionary

Phase 2 deliverable (spec section 9, R-9.1). Authoritative field list for every table in the `ops` and `ground_truth` schemas. The SQLAlchemy models in src/models are generated from the same design; tests/test_dictionary_matches_models.py fails if a table or column exists in one and not the other. Where docs/04 sketched field groups, this file wins.

Column legend: Req = required (NOT NULL); Key = PK, FK (target), UQ (unique), GEN (generated column); Origin = how the value arises: CFG (loaded from config), GEN (raw generated input), CALC (calculated by a rule from other fields), USER (supplied by an actor through the API), SYS (set by the system during processing), DER (derived snapshot reconciled to a ledger). Types are PostgreSQL types. All timestamps are `timestamptz` in UTC; dates are local calendar dates (ASM-046). Monetary amounts are `numeric(14,2)`; leave quantities `numeric(5,1)` or `numeric(6,1)` in days with 0.5 granularity.

All IDs are text, immutable (trigger), zero-padded, and CHECK-constrained to the patterns in src/common/ids.py. Every enum column is CHECK-constrained to the values of the matching enum in src/common/enums.py.

## 1. Master data

### ops.department
Why: resolves authority level L3 (department head) to a person (DEC-15). 1:N employees, 1:N cost centers.

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| department_id | text | yes | PK | DEPT-01 .. DEPT-99 | | pattern ^DEPT-\d{2}$ | CFG |
| department_name | text | yes | UQ | | | unique | CFG |
| head_employee_id | text | no | FK employee | | NULL | head must belong to this department (service check); FK added after employee exists (circular) | CFG |
| created_at | timestamptz | yes | | | | from simulated clock | SYS |

### ops.cost_center
Why: core entity (spec 7.8). Budget periods live in cost_center_budget (DEC-17). 1:N claims, 1:N budgets, 1:N ledger rows.

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| cost_center_id | text | yes | PK | CC-0001 .. | | pattern ^CC-\d{4}$ | CFG |
| cost_center_name | text | yes | | | | | CFG |
| department_id | text | yes | FK department | | | | CFG |
| country | text | yes | | IN, US, GB | | enum | CFG |
| currency | text | yes | | INR, USD, GBP | | enum; must equal country currency (service) | CFG |
| is_active | bool | yes | | | true | inactive -> INVALID_COST_CENTER | CFG |
| effective_from | date | yes | | | | | CFG |
| effective_to | date | no | | | NULL | >= effective_from | CFG |
| created_at | timestamptz | yes | | | | | SYS |

### ops.cost_center_budget
Why: one budget period (calendar year, ASM-016) per cost center so the cost center stays a single master row (DEC-17). Snapshot columns are reconciled to cost_center_transaction (BR-BUD-01).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| cost_center_budget_id | text | yes | PK | CCB-CC-0001-2026 | | pattern ^CCB-CC-\d{4}-\d{4}$ | CFG |
| cost_center_id | text | yes | FK cost_center | | | UQ with budget_period_start | CFG |
| budget_period_start | date | yes | | | | | CFG |
| budget_period_end | date | yes | | | | >= budget_period_start | CFG |
| currency | text | yes | | INR, USD, GBP | | enum | CFG |
| budget_amount | numeric(14,2) | yes | | local currency | | >= 0 | CFG (GEN within range) |
| committed_amount | numeric(14,2) | yes | | local currency | 0 | >= 0; = SUM(RESERVATION) - SUM(RELEASE) | DER |
| actual_amount | numeric(14,2) | yes | | local currency | 0 | >= 0; = SUM(ACTUAL) | DER |

### ops.employee
Why: core entity (spec 7.1). Self-referencing hierarchy; no cycles (service validation, depth <= 7).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| employee_id | text | yes | PK | EMP-000001 .. | | pattern ^EMP-\d{6}$ | GEN |
| full_name | text | yes | | synthetic (Faker) | | | GEN |
| email | text | yes | UQ | synthetic, example.test domain | | unique | GEN |
| manager_id | text | no | FK employee | | NULL at top of chain | <> employee_id; manager grade > employee grade (service) | GEN |
| department_id | text | yes | FK department | | | | GEN |
| job_title | text | yes | | | | | GEN |
| grade | text | yes | | G1 .. G7 | | enum; exactly one G7 (service) | GEN |
| country | text | yes | | IN, US, GB | | enum | GEN |
| currency | text | yes | | INR, USD, GBP | | enum; = CURRENCY_BY_COUNTRY[country] (service) | CALC |
| employment_start | date | yes | | | | | GEN |
| employment_end | date | no | | | NULL | >= employment_start; NOT NULL iff status TERMINATED | GEN |
| employment_status | text | yes | | ACTIVE, TERMINATED, ON_LEAVE_OF_ABSENCE | | enum | GEN |
| default_cost_center_id | text | yes | FK cost_center | | | | GEN |
| is_department_head | bool | yes | | | false | at most one per department (service) | GEN |
| is_finance_controller | bool | yes | | | false | one per country (service) | GEN |
| created_at | timestamptz | yes | | | | | SYS |

### ops.employee_cost_center_assignment
Why: employees move between cost centers; a claim uses the assignment effective on its earliest line date (AM-C, DEC-13).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| assignment_id | text | yes | PK | ECA-000001 | | pattern ^ECA-\d{6}$ | GEN |
| employee_id | text | yes | FK employee | | | UQ with effective_from | GEN |
| cost_center_id | text | yes | FK cost_center | | | | GEN |
| effective_from | date | yes | | | | no overlapping ranges per employee (service) | GEN |
| effective_to | date | no | | | NULL | >= effective_from | GEN |
| created_at | timestamptz | yes | | | | | SYS |

### ops.country_holiday
Why: business-day calculation (spec 7.4, AM-B2). Hand-written illustrative calendars (ASM-005).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| holiday_id | text | yes | PK | HOL-IN-20250126 | | pattern ^HOL-(IN\|US\|GB)-\d{8}$ | CFG |
| country | text | yes | | IN, US, GB | | enum; UQ with holiday_date | CFG |
| holiday_date | date | yes | | | | | CFG |
| holiday_name | text | yes | | | | | CFG |

### ops.fx_rate
Why: thresholds in USD, claims in local currency (AM-B1). Fixed illustrative rates (ASM-003).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| fx_rate_id | text | yes | PK | FX-USD-INR-20250101 | | pattern ^FX-[A-Z]{3}-[A-Z]{3}-\d{8}$ | CFG |
| from_currency | text | yes | | INR, USD, GBP | | enum | CFG |
| to_currency | text | yes | | INR, USD, GBP | | enum; UQ (from, to, effective_from) | CFG |
| rate | numeric(18,6) | yes | | units of to_currency per 1 from_currency | | > 0 | CFG |
| effective_from | date | yes | | | | latest rate <= submission date is used (ASM-031) | CFG |

### ops.delegation
Why: approvers on leave delegate authority for a date range (AM-B9).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| delegation_id | text | yes | PK | DLG-000001 | | pattern ^DLG-\d{6}$ | GEN |
| approver_id | text | yes | FK employee | | | <> delegate_id | GEN |
| delegate_id | text | yes | FK employee | | | | GEN |
| effective_from | date | yes | | | | | GEN |
| effective_to | date | yes | | | | >= effective_from | GEN |
| reason | text | no | | | NULL | | GEN |
| created_at | timestamptz | yes | | | | | SYS |

### ops.id_sequence
Why: per-scope counters locked FOR UPDATE when the API allocates IDs (docs/06 8.1). The generator does not use it.

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| sequence_scope | text | yes | PK | e.g. LVE-2026, EXP-2026, RMB-2026, AUD | | | SYS |
| next_value | int | yes | | | 1 | >= 1 | SYS |

## 2. Policies and rules

### ops.leave_policy
Why: core entity (spec 7.2). One row per version (DEC-04). Six illustrative policies (ASM-006).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| leave_policy_id | text | yes | PK | LPOL-ANNUAL-IN-V1 | | pattern ^LPOL-[A-Z]+-(IN\|US\|GB\|ALL)-V\d+$ | CFG |
| policy_family | text | yes | | LPOL-ANNUAL-IN | | UQ with version | CFG |
| version | int | yes | | | | >= 1; versions of a family must not overlap in time (validator) | CFG |
| policy_name | text | yes | | | | | CFG |
| leave_type | text | yes | | ANNUAL, SICK, CASUAL, UNPAID | | enum | CFG |
| country_scope | text | yes | | IN, US, GB, ALL | | enum | CFG |
| annual_entitlement_days | numeric(5,1) | yes | | days | | >= 0 | CFG |
| accrual_method | text | yes | | MONTHLY, ANNUAL_GRANT, NONE | | enum | CFG |
| carry_forward_cap_days | numeric(5,1) | yes | | days | | >= 0 | CFG |
| negative_balance_allowed | bool | yes | | | false | | CFG |
| negative_limit_days | numeric(5,1) | yes | | days | 0 | >= 0; must be 0 unless negative_balance_allowed | CFG |
| min_service_days | int | yes | | days | 0 | >= 0 | CFG |
| requires_medical_cert_over_days | numeric(5,1) | no | | days | NULL | SICK only (service) | CFG |
| max_days_per_year | numeric(5,1) | no | | days | NULL | UNPAID only (service) | CFG |
| effective_start | date | yes | | | | | CFG |
| effective_end | date | no | | | NULL | >= effective_start; inclusive (BC-07) | CFG |
| is_active | bool | yes | | | true | | CFG |

### ops.expense_policy
Why: core entity (spec 7.5). One row per (category, country) version. Limits in local currency (DEC-05, ASM-012).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| expense_policy_id | text | yes | PK | XPOL-MEALS-IN-V1 | | pattern ^XPOL-[A-Z_]+-(IN\|US\|GB)-V\d+$ | CFG |
| policy_family | text | yes | | XPOL-MEALS-IN | | UQ with version | CFG |
| version | int | yes | | | | >= 1 | CFG |
| policy_name | text | yes | | | | | CFG |
| country | text | yes | | IN, US, GB | | enum | CFG |
| category | text | yes | | TRAVEL, MEALS, ACCOMMODATION, OFFICE_SUPPLIES, TRAINING, CLIENT_ENTERTAINMENT | | enum | CFG |
| currency | text | yes | | INR, USD, GBP | | enum | CFG |
| per_line_limit | numeric(14,2) | yes | | local currency | | > 0 | CFG |
| per_claim_limit | numeric(14,2) | yes | | local currency | | > 0 | CFG |
| receipt_threshold | numeric(14,2) | yes | | local currency | | >= 0; receipt required when line_amount >= threshold | CFG |
| requires_pre_approval | bool | yes | | | false | reserved, unused in v1 | CFG |
| effective_start | date | yes | | | | | CFG |
| effective_end | date | no | | | NULL | >= effective_start | CFG |
| is_active | bool | yes | | | true | | CFG |

### ops.approval_rule
Why: core entity (spec 7.9). Configurable, effective-dated, prioritised routing (AM-B8, AM-B10). Bands: lower exclusive, upper inclusive (ASM-009, ASM-013).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| approval_rule_id | text | yes | PK | RULE-L-001, RULE-E-001 | | pattern ^RULE-(L\|E)-\d{3}$; prefix matches request_type | CFG |
| request_type | text | yes | | LEAVE, EXPENSE | | enum | CFG |
| country | text | no | | IN, US, GB | NULL = all | enum when present | CFG |
| category_or_leave_type | text | no | | expense category or leave type | NULL = all | | CFG |
| min_amount_usd | numeric(14,2) | no | | USD, exclusive lower bound | NULL | < max_amount_usd; EXPENSE only | CFG |
| max_amount_usd | numeric(14,2) | no | | USD, inclusive upper bound | NULL = open | EXPENSE only | CFG |
| min_days | numeric(5,1) | no | | days, exclusive lower bound | NULL | < max_days; LEAVE only | CFG |
| max_days | numeric(5,1) | no | | days, inclusive upper bound | NULL = open | LEAVE only | CFG |
| required_levels | jsonb | yes | | array of L1..L5 in sequence, e.g. ["L1","L2"] | | non-empty array | CFG |
| priority | int | yes | | | | >= 1; highest wins; equal + different outcome = RULE_CONFLICT | CFG |
| effective_start | date | yes | | | | | CFG |
| effective_end | date | no | | | NULL | >= effective_start | CFG |
| is_active | bool | yes | | | true | | CFG |

### ops.exception_code
Why: lookup for exception codes (AM-D2); carries class, severity, default route and wording (AM-H3).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| exception_code | text | yes | PK | e.g. MISSING_RECEIPT (docs/02 section 5) | | pattern ^[A-Z][A-Z_]+$ | CFG |
| exception_class | text | yes | | POLICY_VIOLATION, SUSPICIOUS_PATTERN, DATA_QUALITY, NO_VALID_APPROVAL_PATH, RULE_CONFLICT | | enum (NONE is not a catalogue value) | CFG |
| severity | text | yes | | HARD, CORRECTABLE, SOFT, INFO | | enum | CFG |
| default_route | text | yes | | REJECTED, RETURNED_FOR_CORRECTION, ESCALATED_FOR_REVIEW, NONE | | must match severity (HARD->REJECTED, CORRECTABLE->RETURNED, SOFT->ESCALATED, INFO->NONE) | CFG |
| requester_message_template | text | yes | | placeholders in braces | | must not contain fraud or misconduct | CFG |
| analyst_message_template | text | yes | | | | same wording rule | CFG |

## 3. Leave

### ops.leave_balance
Why: core entity (spec 7.3). Materialised snapshot; the ledger is authoritative (AMB-01).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| leave_balance_id | text | yes | PK | LBAL-EMP-000001-LPOL-ANNUAL-IN-V1-2026 | | pattern | CALC |
| employee_id | text | yes | FK employee | | | UQ (employee, policy, year) | GEN |
| leave_policy_id | text | yes | FK leave_policy | | | | GEN |
| leave_year | int | yes | | 2000..2100 | | | GEN |
| opening_balance | numeric(6,1) | yes | | days | | = OPENING + CARRY_FORWARD transactions | DER |
| accrued | numeric(6,1) | yes | | days | 0 | = SUM(ACCRUAL) | DER |
| adjustments | numeric(6,1) | yes | | days, signed | 0 | = SUM(ADJUSTMENT) - SUM(CARRY_FORWARD_EXPIRY) | DER |
| used | numeric(6,1) | yes | | days | 0 | >= 0; = SUM(USAGE) - SUM(USAGE_REVERSAL) | DER |
| available_balance | numeric(6,1) | yes | GEN | days | | generated: opening + accrued + adjustments - used | CALC |
| last_recalculated_at | timestamptz | yes | | | | | SYS |

### ops.leave_request
Why: core entity (spec 7.4). Resubmission keeps the ID; current_round counts cycles (AM-A5).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| leave_request_id | text | yes | PK | LVE-2026-000001 (year = submission year) | | pattern ^LVE-\d{4}-\d{6}$ | SYS |
| employee_id | text | yes | FK employee | | | | USER/GEN |
| leave_policy_id | text | yes | FK leave_policy | resolved version | | effective on submission date (BR-LV-05) | CALC |
| start_date | date | yes | | | | | USER/GEN |
| end_date | date | yes | | | | >= start_date | USER/GEN |
| start_half_day | bool | yes | | | false | | USER/GEN |
| end_half_day | bool | yes | | | false | both flags not allowed on a single-day request | USER/GEN |
| first_submitted_at | timestamptz | no | | | NULL while DRAFT | NULL iff workflow_status = DRAFT | SYS |
| current_round | int | yes | | | 1 | >= 1; max 3 (service, ASM-025) | SYS |
| business_day_count | numeric(5,1) | yes | | days | | BR-CAL-03; >= requested_quantity | CALC |
| requested_quantity | numeric(5,1) | yes | | days | | = business days - 0.5 per half-day flag | CALC |
| workflow_status | text | yes | | 9 values (docs/06) | | enum; transitions by lifecycle service | SYS |
| exception_class | text | yes | | NONE + 5 classes | NONE | enum; summary of current-round request_exception rows | CALC |
| medical_cert_flag | bool | yes | | | false | required for SICK > 3 days | USER/GEN |
| decision_reason_code | text | no | | | NULL | | SYS |
| decision_reason_text | text | no | | template-rendered | NULL | | CALC |
| created_at | timestamptz | yes | | | | | SYS |

### ops.leave_balance_transaction
Why: append-only ledger behind leave_balance (AM-C).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| transaction_id | text | yes | PK | LBT-2026-000001 | | pattern ^LBT-\d{4}-\d{6}$ | SYS |
| leave_balance_id | text | yes | FK leave_balance | | | | SYS |
| leave_request_id | text | no | FK leave_request | | NULL | NOT NULL iff txn_type in (USAGE, USAGE_REVERSAL) | SYS |
| txn_type | text | yes | | OPENING, ACCRUAL, USAGE, USAGE_REVERSAL, ADJUSTMENT, CARRY_FORWARD, CARRY_FORWARD_EXPIRY | | enum | SYS |
| quantity | numeric(6,1) | yes | | days, signed | | <> 0 | CALC |
| txn_date | date | yes | | | | | CALC |
| posted_at | timestamptz | yes | | | | | SYS |
| reason | text | no | | | NULL | | SYS |
| correlation_id | uuid | yes | | | | | SYS |

## 4. Expenses

### ops.receipt
Why: owns the receipt hash so duplicates can be detected across claims and employees (DEC-10, AM-B14). Hash is indexed, not unique.

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| receipt_id | text | yes | PK | RCT-000000001 | | pattern ^RCT-\d{9}$ | SYS |
| receipt_hash | text | yes | | 64 hex chars | | SHA-256 of deterministic synthetic receipt string | CALC |
| receipt_number | text | no | | synthetic | NULL | | GEN |
| merchant | text | no | | synthetic | NULL | | GEN |
| receipt_date | date | no | | | NULL | | GEN |
| amount | numeric(14,2) | no | | | NULL | | GEN |
| currency | text | no | | INR, USD, GBP | NULL | enum when present | GEN |
| created_at | timestamptz | yes | | | | | SYS |

### ops.expense_claim
Why: core entity (spec 7.6). Total is calculated from current-round lines (BR-EX-11).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| expense_claim_id | text | yes | PK | EXP-2026-000001 (year = submission year) | | pattern ^EXP-\d{4}-\d{6}$ | SYS |
| employee_id | text | yes | FK employee | | | | USER/GEN |
| first_submitted_at | timestamptz | no | | | NULL while DRAFT | NULL iff DRAFT | SYS |
| claim_period_start | date | yes | | earliest line expense_date | | <= claim_period_end | CALC |
| claim_period_end | date | yes | | latest line expense_date | | | CALC |
| country | text | yes | | IN, US, GB | | enum; = employee country | CALC |
| currency | text | yes | | INR, USD, GBP | | enum; = employee currency (DEC-14) | CALC |
| cost_center_id | text | no | FK cost_center | | | NULL only when exception_class <> NONE (AM-A2) | CALC |
| expense_policy_id | text | no | FK expense_policy | version for the primary category | NULL when POLICY_NOT_APPLICABLE | | CALC |
| total_amount | numeric(14,2) | yes | | local currency | | >= 0; = SUM(current-round line_amount) | CALC |
| approved_amount | numeric(14,2) | no | | local currency | NULL | NULL unless APPROVED; 0 <= approved <= total (AM-B12) | CALC |
| total_amount_usd | numeric(14,2) | no | | USD | NULL | = total_amount / fx_rate_used, 2 dp | CALC |
| fx_rate_used | numeric(18,6) | no | | USD->local rate at submission | NULL | | CALC |
| workflow_status | text | yes | | 9 values | | enum | SYS |
| exception_class | text | yes | | NONE + 5 classes | NONE | enum | CALC |
| receipt_status | text | yes | | NOT_REQUIRED, COMPLETE, MISSING | NOT_REQUIRED | enum | CALC |
| current_round | int | yes | | | 1 | >= 1 | SYS |
| decision_reason_code | text | no | | | NULL | | SYS |
| decision_reason_text | text | no | | | NULL | | CALC |
| created_at | timestamptz | yes | | | | | SYS |

### ops.expense_line
Why: core entity (spec 7.7). Versioned by submission_round; line numbers continue across rounds (DEC-11).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| expense_line_id | text | yes | PK | EXPL-EXP-2026-000001-01 | | pattern; must equal 'EXPL-' + claim id + '-' + 2-digit line_number | SYS |
| expense_claim_id | text | yes | FK expense_claim | | | UQ with line_number | SYS |
| line_number | int | yes | | 1..99 (baseline 1..10) | | | SYS |
| submission_round | int | yes | | | 1 | >= 1 | SYS |
| category | text | yes | | 6 categories | | enum | USER/GEN |
| merchant_description | text | yes | | synthetic | | | USER/GEN |
| expense_date | date | yes | | | | within employment dates; <= submission date | USER/GEN |
| quantity | numeric(10,2) | no | | | NULL | > 0; present iff unit_amount present | USER/GEN |
| unit_amount | numeric(14,2) | no | | local currency | NULL | > 0 | USER/GEN |
| line_amount | numeric(14,2) | yes | | local currency | | > 0; = round(quantity x unit_amount, 2) when both given | USER/GEN or CALC |
| currency | text | yes | | INR, USD, GBP | | enum; must equal claim currency (SERVICE rule; mismatch is a planted anomaly, so no DB constraint) | USER/GEN |
| receipt_id | text | no | FK receipt | | NULL | required when line_amount >= receipt_threshold (service) | USER/GEN |
| cost_center_id | text | no | FK cost_center | override | NULL = inherit claim (DEC-16) | | USER/GEN |
| expense_policy_id | text | no | FK expense_policy | resolved version for (category, country) | NULL | | CALC |
| validation_result | text | yes | | PENDING, PASS, CAPPED, FAIL | PENDING | enum | CALC |
| validation_detail | text | no | | | NULL | | CALC |

### ops.cost_center_transaction
Why: append-only budget ledger; available = budget - actual - committed (AM-B11, DEC-06).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| transaction_id | text | yes | PK | CCT-000000001 | | pattern ^CCT-\d{9}$ | SYS |
| cost_center_id | text | yes | FK cost_center | | | | SYS |
| cost_center_budget_id | text | yes | FK cost_center_budget | period containing the submission date | | | CALC |
| expense_claim_id | text | no | FK expense_claim | | NULL | required unless txn_type = OVERRIDE | SYS |
| txn_type | text | yes | | RESERVATION, RELEASE, ACTUAL, OVERRIDE | | enum | SYS |
| amount | numeric(14,2) | yes | | local currency | | > 0 | CALC |
| currency | text | yes | | INR, USD, GBP | | enum | CALC |
| txn_date | date | yes | | | | | CALC |
| posted_at | timestamptz | yes | | | | | SYS |
| reason_code | text | no | | e.g. BUDGET_OVERRIDE | NULL | | SYS |
| correlation_id | uuid | yes | | | | | SYS |

## 5. Approval workflow

### ops.approval_step
Why: core entity (spec 7.10). One required approval in a round; one step per person, covering every level that person resolves for (covered_levels). Real FKs with exactly one request set (DEC-03). Decided steps are frozen by trigger; no step may be assigned to the requester (trigger). Created at submission for requests that end in PENDING_APPROVAL (Phase 7A); the first step is assigned at once and gets an ASSIGNED approval_event.

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| approval_step_id | text | yes | PK | APR-LVE-2026-000001-01 | | pattern; = 'APR-' + request id + '-' + 2-digit sequence_no | SYS |
| request_type | text | yes | | LEAVE, EXPENSE | | enum; must match populated FK | SYS |
| leave_request_id | text | no | FK leave_request | | NULL | exactly one of the two FKs set | SYS |
| expense_claim_id | text | no | FK expense_claim | | NULL | | SYS |
| submission_round | int | yes | | | | >= 1 | SYS |
| sequence_no | int | yes | | continues across rounds (AM-A5) | | >= 1; UQ per request | SYS |
| approval_rule_id | text | yes | FK approval_rule | | | | CALC |
| required_level | text | yes | | L1..L5 | | enum; the highest level in covered_levels | CALC |
| covered_levels | jsonb | yes | | array of the levels this one step covers, in level order, e.g. ["L1", "L2"] when the direct manager is the top of the chain (ASM-030, AMB-P3-03) | | non-empty array; contains required_level; elements in L1..L5 (3 CHECKs). Added by migration 0002 (Phase 7A); rows that existed before were backfilled with [required_level] | CALC |
| approver_employee_id | text | no | FK employee | resolved person or delegate | NULL only when cancelled before assignment | <> requester (trigger) | CALC |
| delegated_from_employee_id | text | no | FK employee | original approver when a delegate acts | NULL | <> approver_employee_id | CALC |
| step_status | text | yes | | PENDING, APPROVED, REJECTED, SKIPPED, CANCELLED | PENDING | enum; frozen once not PENDING | SYS |
| assigned_at | timestamptz | no | | | NULL until the previous step is approved | | SYS |
| decision_at | timestamptz | no | | | NULL | NOT NULL iff status in (APPROVED, REJECTED); >= assigned_at | SYS |
| decision_reason_code | text | no | | | NULL | | USER/SYS |
| decision_comment | text | no | | | NULL | | USER |

### ops.approval_event
Why: append-only record of what happened to a step (AM-H1).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| approval_event_id | text | yes | PK | APE-000000001 | | pattern ^APE-\d{9}$ | SYS |
| approval_step_id | text | yes | FK approval_step | | | | SYS |
| event_type | text | yes | | ASSIGNED, APPROVED, REJECTED, RETURNED, ESCALATED, SKIPPED, CANCELLED, REASSIGNED | | enum | SYS |
| actor_id | text | no | FK employee | | NULL = system | | SYS |
| occurred_at | timestamptz | yes | | | | | SYS |
| reason_code | text | no | | | NULL | | SYS |
| comment | text | no | | | NULL | | USER |
| correlation_id | uuid | yes | | | | | SYS |

### ops.approval_attempt
Why: blocked approvals create no step change; this table makes them measurable (AM-C, AM-H2, metric M9). Append-only.

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| attempt_id | text | yes | PK | APA-000000001 | | pattern ^APA-\d{9}$ | SYS |
| actor_id | text | yes | FK employee | | | | SYS |
| request_type | text | yes | | LEAVE, EXPENSE | | enum; matches populated FK | SYS |
| request_id | text | yes | | the request's ID (AM-H2) | | = COALESCE(leave_request_id, expense_claim_id) | SYS |
| leave_request_id | text | no | FK leave_request | | NULL | exactly one FK set | SYS |
| expense_claim_id | text | no | FK expense_claim | | NULL | | SYS |
| submission_round | int | yes | | | | >= 1 | SYS |
| approval_step_id | text | no | FK approval_step | | NULL when no step could be identified | | SYS |
| attempted_action | text | yes | | APPROVE, REJECT, RETURN, ESCALATE | | enum | USER |
| attempted_at | timestamptz | yes | | | | | SYS |
| outcome | text | yes | | ACCEPTED, BLOCKED | | enum | CALC |
| reason_code | text | no | | SELF_APPROVAL, UNAUTHORIZED_APPROVER, EXPIRED_RULE, DUPLICATE_ACTION, STEP_NOT_PENDING, LEVEL_SKIPPED | NULL | NULL iff outcome = ACCEPTED | CALC |
| correlation_id | uuid | yes | | | | | SYS |

### ops.request_status_event
Why: append-only workflow_status history (spec 15, AM-C); VALIDATING appears here even though no request rests in it (DEC-08).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| event_id | text | yes | PK | RSE-000000001 | | pattern ^RSE-\d{9}$ | SYS |
| request_type | text | yes | | LEAVE, EXPENSE | | enum; matches populated FK | SYS |
| leave_request_id | text | no | FK leave_request | | NULL | exactly one FK set | SYS |
| expense_claim_id | text | no | FK expense_claim | | NULL | | SYS |
| submission_round | int | yes | | | | >= 1 | SYS |
| previous_status | text | no | | workflow status | NULL for the creating event | enum when present; <> new_status | SYS |
| new_status | text | yes | | workflow status | | enum | SYS |
| actor_id | text | no | FK employee | | NULL = system | | SYS |
| occurred_at | timestamptz | yes | | | | | SYS |
| reason_code | text | no | | | NULL | | SYS |
| correlation_id | uuid | yes | | | | | SYS |
| calculated_values | jsonb | no | | e.g. business_day_count, available_before/after, amount_usd | NULL | | CALC |

### ops.request_exception
Why: a request can carry several exception codes per round; exception_class on the request is the summary (AM-D2). Append-only.

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| exception_id | text | yes | PK | REX-000000001 | | pattern ^REX-\d{9}$ | SYS |
| request_type | text | yes | | LEAVE, EXPENSE | | enum; matches populated FK | SYS |
| leave_request_id | text | no | FK leave_request | | NULL | exactly one FK set | SYS |
| expense_claim_id | text | no | FK expense_claim | | NULL | | SYS |
| submission_round | int | yes | | | | >= 1; UQ (request, round, code, detected_by) | SYS |
| exception_code | text | yes | FK exception_code | | | | CALC |
| detail | text | no | | computed values for the template | NULL | | CALC |
| detected_at | timestamptz | yes | | | | | SYS |
| detected_by | text | yes | | SUBMISSION, BATCH_DETECTOR, REVIEW | | enum | SYS |
| correlation_id | uuid | yes | | | | | SYS |

## 6. Reimbursement

### ops.reimbursement
Why: core entity (spec 7.11). At most one active row per claim (partial unique index); trigger requires an APPROVED claim with matching employee, amount and currency.

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| reimbursement_id | text | yes | PK | RMB-2026-000001 (year = final approval year) | | pattern ^RMB-\d{4}-\d{6}$ | SYS |
| expense_claim_id | text | yes | FK expense_claim | | | unique where status <> CANCELLED | SYS |
| employee_id | text | yes | FK employee | | | = claim.employee_id (trigger) | CALC |
| approved_amount | numeric(14,2) | yes | | local currency | | > 0; = claim.approved_amount (trigger) | CALC |
| currency | text | yes | | INR, USD, GBP | | enum; = claim currency (trigger) | CALC |
| eligibility_status | text | yes | | ELIGIBLE, INELIGIBLE | ELIGIBLE | enum; set once | CALC |
| reimbursement_status | text | yes | | ELIGIBLE, PROCESSING, COMPLETED, FAILED, CANCELLED | ELIGIBLE | enum | SYS |
| approval_completion_step_id | text | yes | FK approval_step | the final approving step | | | SYS |
| created_at | timestamptz | yes | | | | | SYS |
| payment_reference | text | no | | synthetic | NULL | | SYS |
| completed_at | timestamptz | no | | | NULL | NOT NULL iff status = COMPLETED | SYS |

### ops.reimbursement_attempt
Why: payment attempts, failures, retries and blocked duplicates (AM-C, metric M11). Append-only.

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| attempt_id | text | yes | PK | RMA-000000001 | | pattern ^RMA-\d{9}$ | SYS |
| actor_type | text | yes | | EMPLOYEE, SYSTEM | | enum | SYS |
| actor_employee_id | text | no | FK employee | | NULL for SYSTEM | NOT NULL iff actor_type = EMPLOYEE | SYS |
| expense_claim_id | text | yes | FK expense_claim | | | | SYS |
| reimbursement_id | text | no | FK reimbursement | | NULL when blocked before any row existed | | SYS |
| attempted_action | text | yes | | CREATE, PROCESS, RETRY, CANCEL | | enum | USER/SYS |
| attempted_at | timestamptz | yes | | | | | SYS |
| outcome | text | yes | | ACCEPTED, BLOCKED, COMPLETED, PAYMENT_FAILED | | enum | CALC |
| reason_code | text | no | | DUPLICATE_REIMBURSEMENT, CLAIM_NOT_APPROVED, AMOUNT_MISMATCH, payment failure code | NULL | required unless outcome = ACCEPTED | CALC |
| correlation_id | uuid | yes | | | | | SYS |

## 7. Audit and technical

### ops.audit_event
Why: cross-entity append-only audit (spec 15, AM-F4). Polymorphic by design; no FK so it survives entity deletion in tests. Hash-chain columns are a stretch item (DEC-20) and absent.

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| event_id | text | yes | PK | AUD-000000001 | | pattern ^AUD-\d{9}$ | SYS |
| entity_type | text | yes | | table name, e.g. expense_claim | | indexed with entity_id | SYS |
| entity_id | text | yes | | | | | SYS |
| previous_state | text | no | | | NULL | | SYS |
| new_state | text | no | | | NULL | | SYS |
| actor_id | text | no | | employee id, user id or SYSTEM | NULL | | SYS |
| occurred_at | timestamptz | yes | | | | | SYS |
| rule_id | text | no | | approval rule applied | NULL | | SYS |
| policy_version_id | text | no | | policy version applied | NULL | | SYS |
| reason_code | text | no | | | NULL | | SYS |
| correlation_id | uuid | yes | | | | indexed | SYS |
| calculated_values | jsonb | no | | | NULL | | CALC |

### ops.processing_failure
Why: technical failures separate from business exceptions (AM-D3).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| failure_id | text | yes | PK | PFL-000000001 | | pattern ^PFL-\d{9}$ | SYS |
| entity_type | text | no | | | NULL | | SYS |
| entity_id | text | no | | | NULL | | SYS |
| operation | text | yes | | e.g. PROCESS_PAYMENT, SUBMIT | | | SYS |
| error_code | text | yes | | e.g. PAYMENT_FAILED, DB_ERROR, TIMEOUT | | | SYS |
| error_message | text | yes | | | | | SYS |
| occurred_at | timestamptz | yes | | | | | SYS |
| correlation_id | uuid | yes | | | | | SYS |
| resolution_status | text | yes | | OPEN, RETRIED, RESOLVED, IGNORED | OPEN | enum | SYS |

### ops.idempotency_record
Why: prevents repeated submission or processing (AM-C, docs/06 section 8). Scope (actor, key). Never deleted; only status fields change (trigger).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| actor_user_id | text | yes | PK, FK application_user | | | | SYS |
| idempotency_key | text | yes | PK | 64 hex chars (client key or derived SHA-256) | | pattern | USER/CALC |
| operation | text | yes | | SUBMIT, APPROVE, RESUBMIT, CREATE_REIMBURSEMENT, PROCESS_PAYMENT | | enum | SYS |
| request_hash | text | yes | | SHA-256 of canonical payload | | 64 hex | CALC |
| leave_request_id | text | no | FK leave_request | | NULL | at most one FK set | SYS |
| expense_claim_id | text | no | FK expense_claim | | NULL | | SYS |
| status | text | yes | | IN_PROGRESS, COMPLETED, FAILED | IN_PROGRESS | enum | SYS |
| response_hash | text | no | | SHA-256 of the stored response | NULL | | CALC |
| created_at | timestamptz | yes | | | | | SYS |
| completed_at | timestamptz | no | | | NULL | NOT NULL iff status = COMPLETED | SYS |

## 8. Security

### ops.role

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| role_id | text | yes | PK | ROLE-REQUESTER, ROLE-APPROVER, ROLE-PROCESS_OWNER, ROLE-OPS_ANALYST, ROLE-SYSTEM_ADMIN | | pattern ^ROLE-[A-Z_]+$ | CFG |
| role_name | text | yes | UQ | REQUESTER, APPROVER, PROCESS_OWNER, OPS_ANALYST, SYSTEM_ADMIN | | | CFG |
| description | text | no | | | NULL | | CFG |

### ops.application_user
Why: simulated login identity (AM-F2, ASM-036). 1:0..1 with employee.

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| user_id | text | yes | PK | USR-000001 | | pattern ^USR-\d{6}$ | GEN |
| username | text | yes | UQ | | | | GEN |
| password_hash | text | yes | | bcrypt hash of a synthetic password | | never a plain password | CALC |
| employee_id | text | no | FK employee, UQ | | NULL for admin-only users | | GEN |
| is_active | bool | yes | | | true | | GEN |
| created_at | timestamptz | yes | | | | | SYS |

### ops.user_role
Why: bridge for the genuine N:M between users and roles (spec section 9).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| user_id | text | yes | PK, FK application_user | | | | GEN |
| role_id | text | yes | PK, FK role | | | | GEN |

## 9. Ground truth schema (no FKs to or from ops; readable only by lea_evaluation)

### ground_truth.record_expectation
Why: expected behaviour per request (AM-E4). Produced from planted-scenario definitions and the independent reference calculation, never from the production engine (DEC-01).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| record_type | text | yes | PK | LEAVE, EXPENSE | | enum | REF |
| record_id | text | yes | PK | matches an ops ID by value | | | REF |
| expected_route | jsonb | no | | array of {level, approver_id}; NULL when routing is not reached | NULL | array when present | REF |
| expected_final_status_at_asof | text | yes | | workflow status | | | REF |
| expected_reimbursement_eligibility | bool | no | | EXPENSE only | NULL | | REF |
| expected_exception_codes | jsonb | yes | | array of codes, [] when clean | | array | REF |
| expected_approved_amount | numeric(14,2) | no | | local currency | NULL | | REF |

### ground_truth.anomaly_label
Why: one row per planted or naturally occurring anomaly instance (spec 11, AM-E4). Matching unit for metrics is (affected_record_id, issue_type).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| label_id | text | yes | PK | GTL-000001 | | pattern ^GTL-\d{6}$ | REF |
| scenario_id | text | yes | | S01 .. S26 (docs/07 section 7.2) | | | REF |
| affected_record_type | text | yes | | LEAVE, EXPENSE, APPROVAL_ATTEMPT, REIMBURSEMENT_ATTEMPT, IDEMPOTENCY | | | REF |
| affected_record_id | text | yes | | | | | REF |
| issue_type | text | yes | | exception code or attempt reason | | | REF |
| label | text | yes | | human-readable label | | | REF |
| expected_detection | text | yes | | DETECT, NOT_DETECT | | enum | REF |
| expected_workflow_behaviour | text | yes | | e.g. REJECTED, ESCALATED_FOR_REVIEW, BLOCKED | | | REF |
| injection_reason | text | yes | | why planted, or "natural consequence" | | | REF |
| is_planted | bool | yes | | | | | REF |

### ground_truth.boundary_case
Why: deliberately planted boundary records (AM-E5, docs/02 BC-01..BC-10).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| case_id | text | yes | PK | GTB-0001 | | pattern ^GTB-\d{4}$ | REF |
| record_type | text | yes | | LEAVE, EXPENSE | | enum | REF |
| record_id | text | yes | | | | | REF |
| boundary_type | text | yes | | BC-01 .. BC-10 | | | REF |
| expected_outcome | text | yes | | | | | REF |

### ground_truth.scenario
Why: catalogue of scenarios with planned and actual counts (docs/07 section 9.1).

| Field | Type | Req | Key | Allowed values / units | Default | Validation | Origin |
|---|---|---|---|---|---|---|---|
| scenario_id | text | yes | PK | S01 .. S26, S19-L, S19-E | | | CFG |
| issue_type | text | yes | | | | | CFG |
| description | text | yes | | | | | CFG |
| planned_count | int | yes | | | | >= 0 | CFG |
| actual_count | int | no | | | NULL until generated | | CALC |

Origin REF = written by the ground-truth stage from the planted definitions and src/reference.

## 10. Cardinality summary

See docs/04 section 2 for the full relationship catalogue. In short: department 1:N employee, cost_center, cost_center_budget; employee 1:N leave_balance, leave_request, expense_claim, delegation (twice), assignment, approval_step (as approver), approval_attempt (as actor); leave_policy 1:N leave_balance, leave_request; leave_balance 1:N leave_balance_transaction; expense_claim 1:N expense_line, cost_center_transaction, 1:0..1 reimbursement; receipt 1:N expense_line; request (leave or expense) 1:N approval_step, request_status_event, request_exception, approval_attempt via exactly-one nullable FKs; approval_step 1:N approval_event; reimbursement 1:N reimbursement_attempt; application_user N:M role via user_role.

## Phase 7B notes

- leave_request.decision_reason_code = LEGACY_APPROVAL marks a legacy approval (S01/S02), a raw input written by stage S5 (DEC-P7B-02). Other values are exception codes (ASM-P5-08) or decision reasons (APPROVER_REJECTED, APPROVER_RETURNED, PROCESS_OWNER_ACCEPTED, BUDGET_OVERRIDE, ASM-P7B-03).
- Stage S6 (Phase 7B) populates approval_step, approval_event, approval_attempt, request_status_event, request_exception, idempotency_record and cost_center_transaction in the generated dataset; their columns are unchanged.
