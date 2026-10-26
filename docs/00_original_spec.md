# PART 1: Assignment brief

Business Context / Problem
Route leave and expense requests using policy, balances, budgets and approval authority.

Objective and Scope
Build a working solution for this end-to-end workflow: Route leave and expense requests using policy, balances, budgets and approval authority. The solution should expose key decisions and exceptions, preserve traceability, and produce measurable outputs. Medium complexity means multiple related entities, conditional rules, at least one exception path and meaningful evaluation metrics.

Primary Actors / Systems
Business requester, process owner, approver, operations analyst and system administrator

Business Workflow and Rules
1. Generate/reference master data first: Employee, LeavePolicy, LeaveBalance, LeaveRequest, ExpensePolicy.
2. Generate dependent transaction/event records using valid parent IDs.
3. Apply business logic: Seed employee hierarchy and policies; compute leave accrual/balance; create leave requests with date ranges and business-day counts; create expense claims with line items, receipts metadata and cost centers; route by amount, category, country and manager; produce approval steps and reimbursement records only after final approval.
4. Persist state changes as explicit records/events where relevant; do not overwrite history.
5. Generate outcomes and ground-truth labels from documented rules, not independent random assignment.

Entities and Relationships
Core entities: Employee, LeavePolicy, LeaveBalance, LeaveRequest, ExpensePolicy, ExpenseClaim, ExpenseLine, CostCenter, ApprovalRule, ApprovalStep, Reimbursement. Define a primary key for every entity and foreign keys for every relationship. Document cardinality (1:1, 1:N, N:M), optional relationships, effective dates and lifecycle states. Use bridge tables for many-to-many relationships; retain event history for state changes; validate all joins. For deliberate anomaly cases, keep an issue_type/ground_truth label rather than silently corrupting unrelated rows.

ID / Nomenclature Conventions
EMP-000001; LVE-2026-000001; EXP-2026-000001; EXPL-<claim-id>-01; APR-<request-id>-01; RMB-2026-000001.

Synthetic Data Generation Instructions (Granular)
Step 1 — Write a data dictionary for: Employee, LeavePolicy, LeaveBalance, LeaveRequest, ExpensePolicy, ExpenseClaim, ExpenseLine, CostCenter, ApprovalRule, ApprovalStep, Reimbursement. For each field specify type, required/optional, allowed values, units, uniqueness and validation rule.
Step 2 — Create parent/master tables first, then child and event tables. Apply this domain-specific generation logic: Seed employee hierarchy and policies; compute leave accrual/balance; create leave requests with date ranges and business-day counts; create expense claims with line items, receipts metadata and cost centers; route by amount, category, country and manager; produce approval steps and reimbursement records only after final approval.
Step 3 — Apply deterministic IDs and naming: EMP-000001; LVE-2026-000001; EXP-2026-000001; EXPL-<claim-id>-01; APR-<request-id>-01; RMB-2026-000001. Keep counters zero-padded, IDs immutable, and referenced IDs exactly consistent across files.
Step 4 — Generate the baseline volume: Generate 400 employees, 6 leave policies, 800 leave requests and 1,000 expense claims with 1–10 lines each. Include overlapping leave, insufficient balance, weekend/holiday spans, missing receipt, duplicate receipt hash, policy limit breach and multi-level approval. Use a fixed seed (e.g. 20261022) and parameterize scale so starter and full datasets use the same generator.
Step 5 — Generate valid baseline records first, then inject labelled edge cases: Negative leave balance; same employee has overlapping approved leave; expense date outside employment dates; split claims to evade thresholds; missing cost center; approval by requester; duplicate reimbursement.
Step 6 — Calculate derived values (totals, balances, scores, statuses and dates) from source records rather than generating them independently.
Step 7 — Produce a separate ground_truth.csv/json for known anomalies, expected decisions or labels; never leak it into input features.
Step 8 — Run validation: primary-key uniqueness, foreign-key integrity, allowed enums, date ordering, arithmetic reconciliation, lifecycle transitions and duplicate checks.
Step 9 — Export CSV/JSON/SQL seed data plus README, schema/data dictionary, generator command, fixed seed, source manifest and validation summary.
Step 10 — Regenerate twice with the same seed and compare row counts/checksums to demonstrate reproducibility.

Suggested Volume and Coverage
Generate 400 employees, 6 leave policies, 800 leave requests and 1,000 expense claims with 1–10 lines each. Include overlapping leave, insufficient balance, weekend/holiday spans, missing receipt, duplicate receipt hash, policy limit breach and multi-level approval.

Required Edge Cases / Negative Scenarios
Negative leave balance; same employee has overlapping approved leave; expense date outside employment dates; split claims to evade thresholds; missing cost center; approval by requester; duplicate reimbursement.

Validation Rules / Acceptance Criteria
Balance calculations are correct; approval path follows thresholds; duplicate claims are flagged; reimbursements exist only for eligible approved claims; all decision reasons are auditable.

Evaluation Focus for Generated Data
Review: (a) realistic distributions and meaningful variation; (b) consistent IDs and valid joins; (c) dependency/lifecycle consistency across entities; (d) correct derived values and reconciliation; (e) normal, boundary, failure and exception coverage; (f) separate ground truth; (g) fixed-seed reproducibility, documentation and lawful provenance.

Public Data Guidance / Lawful Use
External data is optional. If used, record source URL, dataset/version, retrieval date, license/terms, attribution, transformations and fields discarded. Use only data you are legally permitted to access and redistribute; do not bypass access controls or collect confidential/personal information. If licensing or suitability is unclear, use synthetic data and cite public reference data only for schema inspiration.

---

# PART 2: Detailed project specification

# PROJECT TITLE

Enterprise Leave and Expense Approval Automation System

# 1. YOUR ROLE

Act as a senior enterprise software architect, data engineer, Python developer, database architect, business process automation engineer, QA engineer, and technical mentor.

Your responsibility is to design, implement, test, document, and prepare a complete, working, portfolio-quality enterprise application based on the business requirements below.

I want to develop this project from scratch, with a clear architecture, modular code, a relational database, synthetic datasets, deterministic business rules, an approval workflow, auditability, analytics, a dashboard, automated tests, and comprehensive documentation.

Do not treat this as a simple CRUD application or a basic synthetic-data-generation exercise.

The system must demonstrate realistic enterprise data engineering, business rule automation, approval routing, exception handling, data quality, reproducibility, and measurable business outcomes.

Explain important technical decisions clearly. Implement the application in manageable phases and verify the actual behavior before declaring any feature complete.

# 2. BUSINESS CONTEXT

Organizations receive employee leave requests and expense claims that must be processed according to internal policies, employee hierarchy, available leave balances, expense limits, approval authority, country-specific requirements, and cost-center budgets.

Manual processing can result in:

* Incorrect leave balance calculations.
* Unauthorized approvals.
* Requests routed to the wrong approvers.
* Expense claims exceeding policy limits.
* Missing or duplicate receipts.
* Suspiciously split expense claims.
* Reimbursements issued before approval.
* Duplicate reimbursements.
* Inconsistent audit records.
* Limited visibility into pending requests and policy exceptions.

The objective is to build an automated system that evaluates requests, determines the appropriate workflow, records decisions, flags exceptions, and provides operational analytics.

# 3. PRIMARY OBJECTIVE

Build a working end-to-end application that routes employee leave and expense requests using:

* Employee hierarchy.
* Applicable leave and expense policies.
* Leave balances and accruals.
* Request dates and employment dates.
* Expense amounts and categories.
* Country and currency.
* Cost centers and budgets.
* Manager and approver authority.
* Approval thresholds.
* Receipt requirements.
* Policy exceptions.
* Final approval status.

The application must expose key decisions and exceptions, preserve traceability, and produce measurable evaluation metrics.

The system must distinguish among:

* Approved requests.
* Rejected requests.
* Pending requests.
* Requests returned for correction.
* Requests escalated for review.
* Policy violations.
* Suspicious patterns requiring investigation.
* Technical processing failures.

These statuses must not be treated as interchangeable.

# 4. USERS AND ACTORS

Design the application for the following actors.

## 4.1 Business Requester

Can:

* View their own leave and expense requests.
* Submit leave requests.
* Submit expense claims with line items and receipt metadata.
* View current request status.
* View approval history and decision reasons.
* Correct and resubmit eligible requests.

## 4.2 Manager or Approver

Can:

* View requests assigned to them.
* Inspect policy checks and request details.
* Approve or reject requests within their authority.
* Return requests for correction.
* Add decision comments.
* View previous approval decisions.

Approvers must not approve their own requests.

## 4.3 Process Owner

Can:

* Manage leave and expense policy configurations.
* Configure approval thresholds.
* Review workflow performance.
* Review policy exceptions.
* Analyze processing bottlenecks.

## 4.4 Operations Analyst

Can:

* Investigate exceptions.
* Review missing receipts and duplicate receipt hashes.
* Examine potential split claims.
* Review failed approval attempts.
* Inspect reimbursement eligibility.
* Generate operational reports.

## 4.5 System Administrator

Can:

* Manage application configuration.
* Manage authorized users and roles.
* Inspect system errors.
* Manage database and application settings.
* Access administrative validation reports.

Implement role-based access control appropriate to the project scope.

# 5. REQUIRED TECHNOLOGY STACK

Use the following stack unless a technical incompatibility requires a documented alternative.

Programming:

* Python 3.12 or a compatible current Python version.

Data processing:

* Pandas.
* NumPy where appropriate.
* Faker for synthetic descriptive data.

Database:

* PostgreSQL.
* SQLAlchemy.
* Alembic for schema migrations.

Backend:

* FastAPI.
* Pydantic.
* Uvicorn.

Frontend and analytics:

* Streamlit.
* Pandas.
* Plotly or Streamlit-native charts.

Testing:

* Pytest.
* Parameterized tests.
* Integration tests.
* Database constraint tests.

Development:

* Git.
* GitHub.
* Environment variables for configuration.
* requirements.txt or pyproject.toml.
* .env.example.

Optional:

* An LLM API for explaining deterministic decisions in natural language.
* Docker and Docker Compose for reproducible deployment.

Do not require a paid LLM API for the core business workflow. The application must work using deterministic Python rules and a PostgreSQL database.

# 6. REQUIRED DATA VOLUME

Generate the following baseline dataset:

* 400 employees.
* 6 leave policies.
* 800 leave requests.
* 1,000 expense claims.
* Between 1 and 10 expense lines per claim.

Generate the necessary supporting records for:

* Leave balances.
* Expense policies.
* Cost centers.
* Approval rules.
* Approval steps.
* Reimbursement records.
* Audit events.
* Leave balance movements.
* Receipt metadata.
* Ground-truth anomaly labels.

Use a configurable fixed random seed:

20261022

The generator must support both a small starter dataset and the full baseline dataset without changing the generation logic.

Example command:

python -m src.data.generate --seed 20261022 --employees 400 --leave-requests 800 --expense-claims 1000

The command may be adjusted to match the final project structure, but it must be documented and executable.

# 7. REQUIRED ENTITIES AND RELATIONSHIPS

Implement the following core entities:

1. Employee
2. LeavePolicy
3. LeaveBalance
4. LeaveRequest
5. ExpensePolicy
6. ExpenseClaim
7. ExpenseLine
8. CostCenter
9. ApprovalRule
10. ApprovalStep
11. Reimbursement

Additional supporting entities may be introduced when needed, including:

* LeaveBalanceTransaction.
* ApprovalEvent.
* RequestStatusEvent.
* Receipt.
* EmployeeCostCenterAssignment.
* PolicyVersion.
* CountryHoliday.
* ApplicationUser.
* Role.
* UserRole.
* IdempotencyRecord.

Document why each additional entity is necessary.

## 7.1 Employee

Include:

* Employee ID.
* Employee name.
* Manager ID.
* Department.
* Job title.
* Country.
* Employment start date.
* Employment end date, when applicable.
* Employment status.
* Default cost center.
* Currency or relevant payroll region.
* Created timestamp.

Validate manager relationships and prevent circular reporting hierarchies.

## 7.2 LeavePolicy

Include:

* Policy ID.
* Policy name.
* Leave type.
* Country or applicable employee scope.
* Annual entitlement.
* Accrual method.
* Carry-forward rules.
* Negative-balance policy.
* Applicable employment conditions.
* Effective start and end dates.
* Policy version.
* Active status.

## 7.3 LeaveBalance

Include:

* Leave balance ID.
* Employee ID.
* Leave policy ID.
* Leave year or accrual period.
* Opening balance.
* Earned accrual.
* Adjustments.
* Approved leave usage.
* Available balance.
* Last recalculation timestamp.

Define whether balances are stored as materialized values, calculated from transactions, or both.

If both are stored, provide reconciliation logic.

## 7.4 LeaveRequest

Include:

* Leave request ID.
* Employee ID.
* Leave policy ID.
* Start date.
* End date.
* Submission timestamp.
* Business-day count.
* Requested leave quantity.
* Current workflow status.
* Applicable policy version.
* Decision reason.
* Created timestamp.

Validate date ordering and calculate business days using configured weekends and country-specific holiday calendars.

Define how partially overlapping dates, half-days, and resubmissions are handled.

## 7.5 ExpensePolicy

Include:

* Expense policy ID.
* Policy name.
* Applicable country.
* Expense category.
* Currency.
* Per-line limit.
* Per-claim limit.
* Receipt threshold.
* Approval requirements.
* Applicable effective dates.
* Policy version.
* Active status.

## 7.6 ExpenseClaim

Include:

* Expense claim ID.
* Employee ID.
* Submission date.
* Expense date or applicable claim period.
* Country.
* Currency.
* Cost center ID.
* Total claim amount.
* Approved amount.
* Current status.
* Applicable policy version.
* Receipt status.
* Exception status.
* Created timestamp.

Calculate the total claim amount from its expense lines.

## 7.7 ExpenseLine

Include:

* Expense line ID.
* Expense claim ID.
* Expense category.
* Merchant or vendor description.
* Expense date.
* Quantity, where appropriate.
* Unit amount, where appropriate.
* Line amount.
* Currency.
* Receipt reference.
* Receipt hash.
* Cost center assignment where needed.
* Policy validation result.

Ensure that line totals reconcile with the parent claim.

## 7.8 CostCenter

Include:

* Cost center ID.
* Cost center name.
* Department.
* Country.
* Currency.
* Budget period.
* Budget amount.
* Committed amount, where defined.
* Actual expenditure, where defined.
* Active status.
* Effective dates.

Define how budget availability is calculated and whether reservations are needed for pending claims.

Do not allow the system to approve claims against an unavailable or invalid cost center without following an explicitly documented exception path.

## 7.9 ApprovalRule

Include:

* Approval rule ID.
* Request type.
* Applicable country.
* Expense category or leave type, where applicable.
* Minimum and maximum amount, where applicable.
* Required approver role or authority.
* Approval level.
* Rule priority.
* Effective start and end dates.
* Active status.

Support configurable rules instead of hardcoding approval thresholds throughout the application.

## 7.10 ApprovalStep

Include:

* Approval step ID.
* Request type.
* Request ID.
* Approval rule ID.
* Approver employee ID.
* Approval sequence.
* Step status.
* Assigned timestamp.
* Decision timestamp.
* Decision reason.
* Decision comments.

A request can have multiple approval steps.

Retain previous decisions when a request is resubmitted or reassigned.

## 7.11 Reimbursement

Include:

* Reimbursement ID.
* Expense claim ID.
* Employee ID.
* Approved amount.
* Currency.
* Eligibility status.
* Reimbursement status.
* Approval completion reference.
* Created timestamp.
* Payment or processing reference, when applicable.

Prevent duplicate reimbursement creation through database constraints and transaction-safe service logic.

# 8. ID AND NAMING CONVENTIONS

Use the following deterministic ID formats:

Employee:
EMP-000001

Leave request:
LVE-2026-000001

Expense claim:
EXP-2026-000001

Expense line:
EXPL-<claim-id>-01

Approval step:
APR-<request-id>-01

Reimbursement:
RMB-2026-000001

Define consistent formats for the remaining entities.

Requirements:

* IDs must be unique.
* IDs must be immutable.
* Counters must be zero-padded as specified.
* Foreign keys must reference exact IDs.
* IDs must remain consistent across CSV, JSON, SQL, and API outputs.
* Regeneration using the same configuration must reproduce the same logical IDs.

# 9. DATA DICTIONARY

Create a comprehensive data dictionary for every core and supporting entity.

For each field specify:

* Field name.
* Data type.
* Required or optional.
* Primary key or foreign key.
* Allowed values.
* Units.
* Uniqueness requirements.
* Default value.
* Validation rules.
* Relationships.
* Effective-date behavior.
* Whether the field is generated, calculated, user-supplied, or derived.

Include lifecycle-state definitions and foreign-key relationships.

Document cardinality:

* One-to-one.
* One-to-many.
* Many-to-many.

Use bridge tables where genuine many-to-many relationships exist.

# 10. SYNTHETIC DATA GENERATION WORKFLOW

Generate the data in dependency order.

## Stage 1: Master data

Generate:

* Employees.
* Employee hierarchy.
* Leave policies.
* Expense policies.
* Cost centers.
* Approval rules.
* Holiday calendars.

Ensure master data is internally consistent before generating transactions.

## Stage 2: Leave balances

Generate valid opening balances and derive accruals and balance movements using documented rules.

Support:

* Annual accrual.
* Periodic accrual, if configured.
* Approved leave consumption.
* Adjustments.
* Carry-forward.
* Negative balances where the documented policy or a deliberately seeded anomaly permits them.

Do not independently randomize calculated balances.

## Stage 3: Leave requests

Generate 800 leave requests.

For each request:

* Reference an existing employee.
* Reference the applicable leave policy.
* Generate valid date ranges for baseline records.
* Calculate business days.
* Account for weekends and configured holidays.
* Derive the requested leave quantity.
* Calculate eligibility and available balance.
* Generate an expected routing path according to the rules.

## Stage 4: Expense claims

Generate 1,000 expense claims.

For each claim:

* Reference an existing employee.
* Generate 1–10 expense lines.
* Generate realistic categories and amounts.
* Assign currencies and countries consistently.
* Assign cost centers according to documented rules.
* Generate receipt metadata.
* Generate receipt hashes deterministically.
* Calculate claim totals from line items.
* Resolve applicable policies.

## Stage 5: Approval workflows

Generate approval steps using the deterministic approval engine.

Approval routing must depend on:

* Request type.
* Amount.
* Expense category.
* Country.
* Applicable policy version.
* Cost center.
* Employee-manager hierarchy.
* Required approval authority.

## Stage 6: Reimbursements

Generate reimbursement records only for claims that satisfy all configured eligibility conditions and have completed final approval.

Do not generate reimbursements independently of workflow state.

## Stage 7: Audit history

Generate state-change and decision events from actual transitions.

Do not generate contradictory event histories.

# 11. REQUIRED EDGE CASES AND NEGATIVE SCENARIOS

Generate a valid baseline first.

Then inject deliberate, labelled anomalies in a controlled phase.

Include:

1. Negative leave balance.
2. Overlapping approved leave for the same employee.
3. Insufficient leave balance.
4. Leave requests spanning weekends and public holidays.
5. Missing expense receipt.
6. Duplicate receipt hash.
7. Expense policy limit breach.
8. Expense date outside employment dates.
9. Potential split claims designed to evade approval thresholds.
10. Missing cost center.
11. Approval attempt by the requester.
12. Unauthorized approver.
13. Duplicate reimbursement attempt.
14. Multi-level approval.
15. Invalid or expired policy reference where the scenario is designed to test policy resolution.
16. Invalid lifecycle transition.
17. Claim total that fails reconciliation, if intentionally testing a validation failure.
18. Repeated submission or processing attempt.

Maintain referential integrity whenever possible.

If a deliberate test requires an invalid foreign key or inconsistent arithmetic, place it in a clearly isolated negative-test fixture or controlled test scenario instead of silently corrupting the baseline production-like dataset.

For every injected scenario, record:

* Scenario ID.
* Affected record ID.
* Issue type.
* Ground-truth label.
* Expected detection behavior.
* Expected workflow behavior.
* Reason for injection.

Distinguish a deliberately planted anomaly from a real business-rule violation.

# 12. GROUND-TRUTH DATASET

Create a separate ground_truth.csv and/or ground_truth.json.

It must contain documented labels for:

* Seeded anomalies.
* Expected routing decisions.
* Expected approval outcomes.
* Expected reimbursement eligibility.
* Expected exception classifications.

Ground truth must not be exposed as an operational input feature.

Do not use ground-truth labels to determine the system's own predictions during evaluation.

Create a separate evaluation process that compares actual results against expected outcomes.

# 13. BUSINESS RULE ENGINE

Implement deterministic business rules using Python services and PostgreSQL.

## 13.1 Leave validation

Check:

* Employee existence.
* Employment dates.
* Policy applicability.
* Policy effective dates.
* Leave type.
* Date ordering.
* Business-day count.
* Available balance.
* Overlapping requests.
* Overlapping approved leave.
* Accrual and carry-forward rules.

Calculate the expected balance using documented transactions.

## 13.2 Expense validation

Check:

* Employee existence.
* Employment dates.
* Expense dates.
* Applicable policy.
* Per-line limits.
* Per-claim limits.
* Receipt requirements.
* Duplicate receipt hashes.
* Currency consistency.
* Cost-center assignment.
* Budget availability.
* Claim arithmetic.
* Duplicate claim patterns.
* Potential split claims.

## 13.3 Approval routing

Route requests according to the applicable approval configuration.

Use effective-dated rules and deterministic precedence.

Support multiple approval levels.

Prevent:

* Self-approval.
* Approval by an unauthorized employee.
* Skipping mandatory approval levels.
* Approval under an expired rule.
* Duplicate approval events.
* Reimbursement before final approval.

If rules conflict or no valid approval path exists, route the request to an explicit exception state instead of silently choosing an arbitrary approver.

## 13.4 Decision output

For every evaluated request, return:

* Request ID.
* Current status.
* Decision.
* Applicable policy version.
* Applicable rule IDs.
* Required approval levels.
* Approver IDs.
* Validation results.
* Exception codes.
* Human-readable reasons.
* Reimbursement eligibility.
* Relevant audit-event references.

## 13.5 Policy configuration

Keep approval thresholds, leave entitlements, expense limits, receipt requirements, and effective dates configurable.

If exact company policies are unspecified, use clearly labelled illustrative synthetic policies.

Never represent assumed thresholds as actual corporate policy.

# 14. WORKFLOW LIFECYCLE

Define explicit state machines for leave requests, expense claims, approval steps, and reimbursements.

Possible request states include:

* DRAFT.
* SUBMITTED.
* VALIDATING.
* PENDING_APPROVAL.
* RETURNED_FOR_CORRECTION.
* APPROVED.
* REJECTED.
* CANCELLED.
* ESCALATED_FOR_REVIEW.

Define which transitions are legal and which actors may perform them.

The exact lifecycle must be documented and implemented consistently across the database, services, API, and dashboard.

For approval steps, distinguish pending, approved, rejected, skipped where permitted, and cancelled states.

For reimbursements, distinguish eligibility, processing, completion, failure, and cancellation as appropriate.

Do not overwrite historical decisions during resubmission.

# 15. AUDITABILITY AND TRANSACTION SAFETY

Implement append-only application-level audit events.

Record:

* Event ID.
* Entity type.
* Entity ID.
* Previous state.
* New state.
* Actor ID.
* Timestamp.
* Rule ID.
* Policy version.
* Reason code.
* Correlation ID.
* Relevant calculated values.

Use database transactions for operations that must succeed or fail together.

Prevent duplicate reimbursement creation with appropriate uniqueness constraints and idempotent service operations.

Explain the limits of audit immutability and how database permissions can help protect the history.

# 16. VALIDATION AND DATA QUALITY

Implement validation for:

## Structural integrity

* Primary-key uniqueness.
* Non-null required fields.
* Foreign-key integrity.
* Allowed enums.
* Unique constraints.
* ID naming conventions.

## Date and lifecycle integrity

* Valid date ranges.
* Employment-date consistency.
* Policy effective dates.
* Legal lifecycle transitions.
* Approval sequence consistency.

## Arithmetic integrity

* Leave accrual calculations.
* Leave balance reconciliation.
* Business-day calculations.
* Expense line totals.
* Claim totals.
* Currency conversion calculations, where applicable.
* Approved amounts.
* Reimbursement amounts.

## Workflow integrity

* Correct approval path.
* Authorized approvers.
* No self-approval.
* No premature reimbursement.
* No duplicate reimbursement.
* Correct handling of rejected and pending claims.

## Reproducibility

Generate the same dataset twice with the same seed and compare:

* Row counts.
* Logical records.
* Deterministic output checksums.
* Ground-truth labels.
* Validation results.

Exclude explicitly documented nondeterministic metadata from checksum comparisons.

# 17. EVALUATION METRICS

Calculate and document:

1. Primary-key violation rate.
2. Foreign-key violation rate.
3. Arithmetic reconciliation rate.
4. Business-rule compliance rate.
5. Approval routing accuracy.
6. Anomaly precision.
7. Anomaly recall.
8. Anomaly F1 score.
9. Unauthorized approval detection rate.
10. Duplicate receipt detection rate.
11. Duplicate reimbursement detection rate.
12. Reimbursement eligibility violation rate.
13. Reproducibility rate.
14. Average approval turnaround time.
15. Pending approval backlog.
16. Policy exception rate.
17. Request rejection rate.
18. Average time spent at each approval level.

Define every metric mathematically and specify the evaluation population and denominator.

Do not count deliberate anomalies as accidental data-quality failures unless the metric explicitly measures detection of those anomalies.

Do not claim perfect metrics without execution results.

Generate evaluation results in CSV, JSON, and Markdown.

# 18. DATABASE AND EXPORT REQUIREMENTS

PostgreSQL is the authoritative operational database.

Generate:

* PostgreSQL schema.
* SQLAlchemy models.
* Alembic migrations.
* Seed scripts.
* Appropriate indexes.
* Foreign keys.
* CHECK constraints.
* UNIQUE constraints.
* Transaction-safe application operations.

Export entity tables to CSV and JSON.

Use deterministic serialization and consistent identifiers.

Generate SQL seed data where appropriate.

Validate all relationships after export.

# 19. FASTAPI BACKEND

Implement a documented REST API.

Include appropriate endpoints for:

* Employees.
* Leave policies.
* Leave balances.
* Leave requests.
* Expense policies.
* Expense claims.
* Expense lines.
* Approval queues.
* Approval decisions.
* Reimbursement records.
* Exception investigation.
* Audit history.
* Dashboard metrics.

Use Pydantic schemas, input validation, proper HTTP status codes, and structured error responses.

Provide Swagger/OpenAPI documentation through FastAPI.

Use role-based access controls appropriate to the implemented authentication model.

Do not expose sensitive data unnecessarily.

# 20. STREAMLIT DASHBOARD

Create an interactive operational dashboard for requesters, approvers, process owners, and operations analysts.

## Executive overview

Display:

* Total employees.
* Total leave requests.
* Total expense claims.
* Approved, rejected, and pending requests.
* Total claimed amount.
* Total approved reimbursement amount.
* Pending approval backlog.
* Policy exceptions.
* High-priority issues.

## Leave analytics

Display:

* Requests by leave type.
* Requests by country and department.
* Approval and rejection rates.
* Insufficient-balance cases.
* Overlapping approved leave.
* Leave utilization.
* Average approval turnaround time.

## Expense analytics

Display:

* Claims by category.
* Claims by country.
* Claims by cost center.
* Claimed versus approved amounts.
* Missing receipts.
* Duplicate receipt hashes.
* Policy breaches.
* Potential split claims.
* Claims outside employment dates.

## Approval operations

Display:

* Pending approval queue.
* Requests awaiting each approval level.
* Approval aging.
* Average approval turnaround time.
* Approver workload.
* Unauthorized approval attempts.

## Reimbursement analytics

Display:

* Eligible claims.
* Claims awaiting reimbursement.
* Reimbursement amounts.
* Completed reimbursements.
* Failed reimbursement processing.
* Duplicate reimbursement attempts.

## Exception investigation

Allow authorized analysts to inspect:

* Source records.
* Related expense lines.
* Applicable policies.
* Approval history.
* Decision reasons.
* Exception classifications.
* Audit events.

Keep operational views separate from ground-truth evaluation views.

Provide filters for dates, country, department, manager, status, category, cost center, and exception type.

Use PostgreSQL as the dashboard's data source.

# 21. PROJECT FOLDER STRUCTURE

Create a clean and modular structure similar to:

leave-expense-automation/
config/
data/
raw/
processed/
ground_truth/
validation/
src/
data/
models/
repositories/
services/
validation/
api/
analytics/
dashboard/
sql/
migrations/
tests/
docs/
scripts/
requirements.txt
.env.example
.gitignore
README.md

Adjust the structure if needed, but explain any significant changes.

Separate data generation, business logic, database access, API handling, analytics, and presentation code.

Avoid monolithic files.

# 22. REQUIRED DOCUMENTATION

Create:

* README.md.
* Architecture documentation.
* Data dictionary.
* Entity relationship documentation.
* Business rules specification.
* Approval routing decision table.
* State-machine documentation.
* Synthetic data generation guide.
* Validation report.
* API usage guide.
* Dashboard guide.
* Setup instructions.
* Testing instructions.
* Configuration reference.
* Troubleshooting guide.
* Limitations and assumptions.

Document the random seed, generation parameters, dataset provenance, and validation results.

Use synthetic data exclusively unless a public source is explicitly approved and legally suitable.

# 23. TESTING STRATEGY

Write tests for:

* Primary-key uniqueness.
* Foreign-key integrity.
* Deterministic ID generation.
* Fixed-seed reproducibility.
* Leave balance reconciliation.
* Business-day calculations.
* Expense arithmetic.
* Approval thresholds.
* Multi-level approval.
* Unauthorized approval.
* Self-approval prevention.
* Duplicate receipt detection.
* Split-claim detection.
* Missing cost centers.
* Policy effective dates.
* Rejected claims without reimbursement.
* Pending claims without reimbursement.
* Duplicate reimbursement prevention.
* Invalid lifecycle transitions.
* Audit-event preservation.
* API validation.
* Dashboard KPI calculations.

Include normal, boundary, failure, and exception tests.

Use isolated test data and a separate test database where appropriate.

# 24. SECURITY AND CONFIGURATION

Implement sensible security practices:

* Keep credentials out of source code.
* Use environment variables.
* Include .env.example without real secrets.
* Validate API inputs.
* Apply role-based access controls.
* Avoid exposing unnecessary employee information.
* Use parameterized queries or ORM-safe operations.
* Protect sensitive administrative operations.
* Document development versus production configuration.

Do not claim production security certification.

# 25. ACCEPTANCE CRITERIA

The project is complete only when the following conditions have been tested:

1. The database schema is executable.
2. All required entities and relationships are present.
3. The baseline data volumes are correct.
4. All IDs follow the documented conventions.
5. Primary keys and foreign keys validate.
6. Leave balances reconcile.
7. Business-day calculations work.
8. Expense totals reconcile with line items.
9. Approval routes follow configured policies.
10. Self-approval is prevented.
11. Unauthorized approvals are rejected or flagged according to policy.
12. Required edge cases are represented and labelled.
13. Ground-truth labels are isolated from operational input.
14. Reimbursements exist only for eligible, finally approved claims.
15. Duplicate reimbursement creation is prevented.
16. Audit history preserves relevant state transitions.
17. The fixed-seed generator is reproducible.
18. Validation metrics are generated from actual results.
19. The API works.
20. The dashboard works.
21. Automated tests run successfully.
22. Documentation explains how to reproduce the project.

Any unmet acceptance criterion must be explicitly listed as incomplete.

# 26. DEVELOPMENT APPROACH

Build the application in these phases.

PHASE 1: Requirements, assumptions, and architecture.

PHASE 2: Data dictionary, database schema, and migrations.

PHASE 3: Synthetic master data and transaction generator.

PHASE 4: Ground-truth generation and validation framework.

PHASE 5: Leave balance and leave request services.

PHASE 6: Expense validation and expense claim services.

PHASE 7: Approval engine and lifecycle management.

PHASE 8: Reimbursement and audit services.

PHASE 9: FastAPI backend.

PHASE 10: Streamlit dashboard.

PHASE 11: Integration testing and reproducibility verification.

PHASE 12: Documentation, final evaluation, and GitHub preparation.

At the end of each phase:

* List the files created or changed.
* Explain the important implementation decisions.
* Provide exact commands to run.
* Execute tests when the environment supports execution.
* Report actual test results.
* Identify unresolved issues.
* Verify the phase's acceptance criteria.

Do not skip phases.

Do not repeatedly regenerate working files without inspecting the existing implementation.

Before making substantial changes, inspect the project structure and preserve existing working code.

When debugging, reproduce the error, identify the root cause, apply the smallest suitable correction, and run the relevant regression tests.

# 27. IMPORTANT WORKING RULES

1. Begin by understanding the entire specification.
2. Do not generate the entire application in one enormous response.
3. Do not invent undocumented business policies.
4. Label assumptions clearly.
5. Do not use random outcomes for derived calculations or approval decisions.
6. Keep ground truth separate.
7. Never claim that commands or tests were executed if they were not.
8. Use realistic synthetic data.
9. Keep IDs and relationships consistent across all files.
10. Preserve approval history.
11. Prefer maintainable, modular code.
12. Explain commands for my development environment.
13. Do not proceed to the next major phase until I approve the current phase.
14. When working in Claude Code, inspect and use the actual project files rather than assuming files exist.
15. If a requirement is ambiguous, identify the ambiguity and propose a documented default.

# 28. FIRST RESPONSE REQUIRED

Start with PHASE 1 only.

Do not write application code yet.

First provide:

A. Executive summary.
B. Problem statement and measurable objectives.
C. System architecture.
D. Proposed project folder structure.
E. Entity relationship specification with cardinalities.
F. Data-generation dependency graph.
G. Business rule catalogue.
H. Approval routing decision table.
I. Request and reimbursement lifecycle definitions.
J. Exception-handling strategy.
K. Ground-truth design.
L. Data dictionary outline.
M. Validation and evaluation strategy.
N. Security and auditability approach.
O. Recommended implementation sequence.
P. Assumptions that require approval.

Identify missing information explicitly.

Where the requirements do not specify exact policy values, propose illustrative synthetic defaults and label them as assumptions.

Conclude with a checklist of architecture decisions requiring my approval.

Wait for my confirmation before proceeding to PHASE 2.