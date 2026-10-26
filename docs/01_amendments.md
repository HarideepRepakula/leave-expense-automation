# Amendments to the original specification

These resolve gaps, contradictions and missing edge cases found in review.
Where this file conflicts with docs/00_original_spec.md, THIS FILE WINS.
Every default below is an ASSUMPTION and must be listed in docs/09_assumptions_and_decisions.md for approval.

## A. Contradictions and ambiguities resolved

A1. Volumes are exact. Injected anomalies REPLACE or MODIFY baseline records; they never add rows.
    Totals stay exactly 400 employees, 6 leave policies, 800 leave requests, 1,000 expense claims.
    (Split-claim anomalies are therefore pairs/groups carved out of the 1,000.)
    Supporting records (approval steps, audit events, etc.) have their own counts.

A2. Injected anomalies vs constraints.
    - Anomalies that can exist as valid rows with an exception label (missing receipt, duplicate receipt hash,
      limit breach, split claims, expense outside employment dates, insufficient balance, negative balance,
      overlapping approved leave) live in the main dataset and are detected by the validation engine.
    - Anomalies that break structural integrity (claim total != sum of lines, invalid foreign key, invalid
      lifecycle transition, bad ID format) live ONLY in tests/fixtures/negative/ as isolated negative fixtures.
      They never enter the production-like dataset.
    - Missing cost center: expense_claim.cost_center_id is NULLABLE with a CHECK that NULL is only allowed when
      exception_status is not 'NONE'. The workflow must route it to ESCALATED_FOR_REVIEW.
    - Approval by requester / unauthorized approver / duplicate reimbursement: the bad action is REJECTED by the
      system, so no bad row exists. The attempt is recorded in append-only approval_attempt /
      reimbursement_attempt tables (see C).

A3. Overlapping approved leave: enforce in the service layer. A PostgreSQL EXCLUDE constraint (btree_gist) is
    tested only in the test database, so seeded overlapping-approved anomalies can exist in the main dataset.

A4. Negative balance has TWO distinct causes and must be labelled separately:
    (a) policy-permitted (policy.negative_balance_allowed = true, within negative_limit) = NOT an anomaly;
    (b) seeded anomaly (beyond limit, or policy forbids) = anomaly.

A5. Resubmission and IDs. IDs are immutable, so a resubmitted request keeps its ID and gets submission_round
    (1, 2, ...). Approval step IDs keep the format APR-<request-id>-NN with NN continuing across rounds
    (round 1 = 01,02; round 2 = 03,04). Old steps are marked CANCELLED, never edited or deleted.

A6. ID year segment = year of SUBMISSION. Because carry-forward needs history, the dataset window is
    2025-01-01 to 2026-10-22 (as-of date). LVE-2025-xxxxxx and LVE-2026-xxxxxx counters are independent per
    year. RMB year = year of final approval.
    ID formats added:
      Policy: LPOL-<TYPE>-<CC>-V<n>, XPOL-<CATEGORY>-<CC>-V<n>
      Cost center: CC-0001   Approval rule: RULE-L-001 / RULE-E-001
      Leave balance: LBAL-<EMP-id>-<policy>-<year>
      Leave balance txn: LBT-<year>-000001
      Audit event: AUD-000000001   Receipt: RCT-000000001
      Holiday: HOL-<CC>-<yyyymmdd>   Application user: USR-000001
    EXPL line number is 2 digits (01..10).

A7. Single time source. No now() in generation or rules. Use an injectable clock with AS_OF_DATE = 2026-10-22.
    created_at fields derive from the simulated timeline. Checksums exclude only documented columns.

A8. Reproducibility design. One master seed (20261022); derive an independent RNG stream per stage (employees,
    policies, leave, expenses, anomalies, ...) via numpy SeedSequence. Seed Faker per stage. Changing the volume
    of one stage must not reshuffle the others. Sort all outputs by primary key before export. Checksum method:
    SHA-256 of canonical CSV (UTF-8, LF, fixed column order).

A9. Decisions are not random. Approver behaviour is a documented deterministic function:
    hard validation failure -> REJECTED (or RETURNED_FOR_CORRECTION if correctable);
    clean request -> APPROVED; soft exception -> ESCALATED_FOR_REVIEW;
    request still within its simulated SLA at AS_OF_DATE -> PENDING_APPROVAL.
    Decision DELAYS (timestamps) may be drawn from seeded distributions; the outcome comes only from rules.

## B. Missing business definitions (illustrative synthetic defaults, to be approved)

B1. Countries: IN, US, GB. Currencies INR, USD, GBP. Base currency for thresholds: USD.
    fx_rate table with fixed illustrative rates and effective dates. No live rates.
B2. Weekend = Sat/Sun (configurable per country). Hand-written illustrative holiday calendars for 2025-2026 in a
    country_holiday table. No scraped data.
B3. Six leave policies: LPOL-ANNUAL-IN, LPOL-ANNUAL-US, LPOL-ANNUAL-GB, LPOL-SICK-ALL, LPOL-CASUAL-IN,
    LPOL-UNPAID-ALL. Illustrative entitlements and carry-forward caps in config.
B4. Accrual: monthly (entitlement/12) at month start, pro-rated for mid-month joiners, none after employment
    end. Carry-forward cap per policy, applied on Jan 1.
B5. Half-days: allowed only as 0.5 on a single date, or on the first/last day of a range (start_half_day,
    end_half_day). Quantity = business days minus 0.5 per half-day flag.
B6. Overlap: a request overlapping an existing APPROVED request of the same employee is a hard fail. Overlap
    with a PENDING request is a soft warning, routed to review.
B7. Authority model. Employee gets grade (G1..G7) and optional is_finance_controller, is_department_head.
    Levels: L1 direct manager, L2 skip-level manager, L3 department head, L4 finance controller, L5 CFO-level
    (grade G7). Approver must hold >= required level authority and be in the requester's chain or a designated
    finance role.
B8. Illustrative thresholds (USD-equivalent, configurable in approval_rule, never hard-coded):
    Expense: <=200 L1 | 200-1,000 L1+L2 | 1,000-5,000 L1+L2+L4 | >5,000 L1+L2+L4+L5.
    Leave: <=5 days L1 | 5-10 days L1+L2 | >10 days or UNPAID L1+L3. Sick leave >3 days needs a
    medical-certificate flag.
B9. Missing approver in chain (manager terminated, no skip-level, requester at top of chain): do NOT pick an
    arbitrary approver. Route to ESCALATED_FOR_REVIEW with exception code NO_VALID_APPROVAL_PATH.
    Add a delegation table (approver, delegate, date range) for approvers on leave.
B10. Rule conflict: highest priority wins; equal priority AND different outcome = exception RULE_CONFLICT ->
     ESCALATED_FOR_REVIEW. Rules are effective-dated.
B11. Budget: available = budget - actual - committed. Submission creates a RESERVATION (committed);
     rejection/cancel releases it; reimbursement completion converts committed -> actual.
     Over budget -> exception BUDGET_EXCEEDED -> ESCALATED_FOR_REVIEW; a finance override approval is the
     documented exception path (recorded with a reason code).
B12. Partial approval: approved_amount may be less than total_amount when lines exceed per-line limits (excess
     capped, with reason). Reimbursement uses approved_amount.
B13. Split-claim rule: same employee, same category, within 7 days, each claim below an approval threshold but
     combined >= that threshold. Window and threshold come from config.
B14. Duplicate receipt hash = same hash on lines in different claims (same employee = DUPLICATE_SELF,
     different employee = DUPLICATE_CROSS_EMPLOYEE). Hash = SHA-256 of a deterministic synthetic receipt string.
B15. Receipt required when line amount >= policy receipt_threshold; a missing receipt then triggers
     MISSING_RECEIPT -> RETURNED_FOR_CORRECTION.

## C. New entities (justify each in the data dictionary)

- RequestStatusEvent / ApprovalEvent / AuditEvent: append-only event history.
- ApprovalAttempt: records blocked approvals (self-approval, unauthorized, expired rule, duplicate click).
  Needed for the "unauthorized approval attempts" metric because blocked actions create no ApprovalStep.
- ReimbursementAttempt: payment attempts, failures, retries, duplicate attempts. Needed because one
  reimbursement per claim is UNIQUE but payment can fail and retry.
- LeaveBalanceTransaction: ledger (opening, accrual, usage, adjustment, carry-forward). LeaveBalance is a
  materialized snapshot reconciled against the ledger.
- CostCenterTransaction (budget ledger): reservations, releases, actuals.
- CountryHoliday, FxRate, Delegation, EmployeeCostCenterAssignment (claims use the assignment effective on the
  expense date), ApplicationUser/Role/UserRole.
- ProcessingFailure: technical errors, separate from business exceptions.
- IdempotencyRecord: prevents repeated submission/processing.

## D. Status model: keep these dimensions separate (never interchangeable)

1. workflow_status: DRAFT, SUBMITTED, VALIDATING, PENDING_APPROVAL, RETURNED_FOR_CORRECTION, APPROVED,
   REJECTED, CANCELLED, ESCALATED_FOR_REVIEW (+ legal transition table and who may perform each).
   Define exits from ESCALATED_FOR_REVIEW (-> APPROVED / REJECTED / RETURNED_FOR_CORRECTION, process owner only).
2. exception_class: NONE, POLICY_VIOLATION, SUSPICIOUS_PATTERN, DATA_QUALITY, NO_VALID_APPROVAL_PATH, ...
   with exception codes in a lookup table.
3. Technical failures live in ProcessingFailure, never in workflow_status.
4. Reimbursement status: ELIGIBLE, PROCESSING, COMPLETED, FAILED, CANCELLED.
5. Approval step status: PENDING, APPROVED, REJECTED, SKIPPED, CANCELLED.

## E. Ground truth and evaluation

E1. Ground truth lives in a separate Postgres schema `ground_truth` AND in data/ground_truth/*.csv|json.
    No foreign keys from operational tables into it. No is_anomaly / issue_type columns in operational tables.
E2. Detectors run on operational data only. Evaluation (src/evaluation/) is the only code allowed to read both.
    A test must fail if operational packages reference ground_truth.
E3. Matching unit for precision/recall/F1: (record_id, issue_type). Define TP/FP/FN per issue type and overall.
    Policy-permitted cases (e.g. allowed negative balance) are expected NEGATIVES and test false positives.
E4. Ground truth per record: expected_route, expected_final_status, expected_reimbursement_eligibility,
    expected_exception_codes. Per anomaly: scenario_id, affected_record_id, issue_type, label, expected
    detection, expected workflow behaviour, injection reason, and is_planted (planted vs naturally occurring).
E5. Add BOUNDARY records on purpose: amount exactly at a threshold, leave exactly equal to balance, expense on
    employment start/end date, leave starting on a holiday, request on a policy effective_end date.

## F. Technical decisions

F1. Local database via Docker Compose (Postgres 16). Provide a non-Docker alternative.
F2. Authentication is simulated: seeded ApplicationUser rows, JWT login endpoint with role claims. Streamlit uses
    a login/role selector in dev mode. Documented limitation: not production authentication.
F3. Dashboard reads analytics through read-only SQL views/queries (separate DB role); all state-changing actions
    go through FastAPI services.
F4. Audit immutability: trigger blocks UPDATE/DELETE on audit_event; app DB user has INSERT/SELECT only;
    optional hash-chain column. Document that a superuser can still bypass this.
F5. Concurrency: SELECT ... FOR UPDATE on leave balance / cost center budget rows; idempotency keys on submit
    and approve; UNIQUE on active reimbursement per claim.
F6. Do not over-engineer for performance; volumes are a few thousand rows.

## G. Phase 1 additions
Phase 1 must also deliver an edge-case coverage matrix (each required edge case -> where generated, detected,
labelled, tested) and a risk list.

## H. Additions from review
H1. Glossary (put in docs/06): request = the business object (leave or expense); submission round = one
    submit/resubmit cycle of a request; approval step = one required approval in a round; approval event =
    append-only record of something that happened to a step; approval attempt = any attempted approve/reject
    action, including ones the system blocked.
H2. approval_attempt fields: attempt_id, actor_id, request_type, request_id, submission_round,
    attempted_action, attempted_at, outcome (ACCEPTED/BLOCKED), reason_code, correlation_id.
    reimbursement_attempt is analogous.
H3. A split-claim flag means SUSPICIOUS_PATTERN requiring investigation. Never label it fraud or misconduct.
H4. Phase 1 must define transaction boundaries and idempotency keys for: submit, approve/reject, resubmit,
    create reimbursement.
H5. Every requirement in the original spec must map to a module and a test (traceability file).
