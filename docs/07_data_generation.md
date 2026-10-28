# 07. Synthetic data generation design

Phase 1 deliverable. Describes how the Phase 3-4 generator will work: dependency order, ID formats, RNG streams, the fixed as-of date, anomaly injection, negative fixtures, boundary records and ground-truth separation. Exact baseline counts: 400 employees, 6 leave policies, 800 leave requests, 1,000 expense claims. No code here.

## 1. Principles

1. Rules are not simulated; the generator calls the same services the API will use (docs/03 section 3).
2. Randomness only for raw inputs (names, dates, amounts, categories, which records get an anomaly) and designated stochastic fields (decision delays, payment timing). Every derived value and every decision comes from rules.
3. Anomalies replace or modify baseline rows; they never add rows (AM-A1). Attempt-type anomalies (self-approval, unauthorised approver, duplicate reimbursement, repeated submission) add rows only to attempt and idempotency tables, which have their own counts.
4. No wall clock. Clock = FrozenClock(AS_OF_DATE = 2026-10-22). created_at values are derived from the simulated timeline (AM-A7).
5. Ground truth is written to its own schema and folder and never read by stages 1-8 (AM-E1, AM-E2).

## 2. Dependency graph and stage order

```
config + master seed
  |
  v
[S1 master]  departments -> cost_centers -> employees (hierarchy) -> employee_cost_center_assignment
             -> leave_policies (6) -> expense_policies -> approval_rules -> country_holidays -> fx_rates
             -> delegations -> application_users / roles / user_roles
  |
  v
[S2 balances]  leave_balance_transaction (OPENING 2025, monthly ACCRUAL 2025-01..2026-10, CARRY_FORWARD 2026-01-01)
               -> leave_balance snapshots (2025, 2026)
  |
  v
[S3 leave]  800 leave_request raw inputs (employee, policy, dates, half-day flags, medical flag, submission timestamp)
  |
  v
[S4 expenses]  1,000 expense_claim raw inputs with 1-10 expense_line and receipt rows
  |
  v
[S5 anomalies + boundaries]  modify a deterministic subset of S3/S4 records in place (section 7); record intended labels in memory
  |
  v
[S6 outcomes]  for each request in submission-time order:
               services.validate -> request_exception, exception_class
               services.route -> approval_step rows
               simulate decisions (rule-based outcome, seeded delay) -> approval_event, approval_attempt
               lifecycle transitions -> request_status_event
               leave USAGE postings; budget RESERVATION / RELEASE postings
               resubmissions (new round) where the simulation says so
               attempt anomalies (blocked attempts, idempotent replays)
  |
  v
[S7 reimbursements]  for APPROVED claims: reimbursement ELIGIBLE -> payment simulation -> attempts, processing_failure
  |
  v
[S8 audit]  audit_event rows for every transition, posting and attempt, hash-chained in occurred_at, event order
  |
  v
[S9 ground truth]  record_expectation for every request FROM src/reference (independent calculation) and from
                   the planted-scenario definitions; anomaly_label for every planted and natural anomaly;
                   boundary_case; scenario counts            -> data/ground_truth/   (separate; never from S6 output)
  |
  v
[export]  sort by PK, canonical CSV + JSON, SQL seed, manifest with SHA-256 per file
[validate]  src/validation runs on exported files; report to data/validation/
```

S6 processes requests in global submission-time order so that overlap, duplicate-receipt, split-claim and budget checks see exactly the records that existed at that simulated moment.

## 3. ID formats (spec 8, AM-A6)

| Entity | Format | Counter scope | Example |
|---|---|---|---|
| employee | EMP-000001 | global, hire-date order | EMP-000001 |
| department | DEPT-01 | global | DEPT-03 |
| cost_center | CC-0001 | global | CC-0017 |
| leave_policy | LPOL-<TYPE>-<CC>-V<n> | per family | LPOL-ANNUAL-IN-V1, LPOL-SICK-ALL-V1 |
| expense_policy | XPOL-<CATEGORY>-<CC>-V<n> | per family | XPOL-MEALS-GB-V2 |
| approval_rule | RULE-L-001 / RULE-E-001 | per request type | RULE-E-003 |
| country_holiday | HOL-<CC>-<yyyymmdd> | natural key | HOL-IN-20250126 |
| fx_rate | FX-<FROM>-<TO>-<yyyymmdd> | natural key | FX-USD-INR-20250101 |
| leave_balance | LBAL-<EMP-id>-<policy-id>-<year> | natural key | LBAL-EMP-000042-LPOL-ANNUAL-IN-V1-2026 |
| leave_balance_transaction | LBT-<yyyy>-000001 | per year of transaction date | LBT-2026-000381 |
| leave_request | LVE-<yyyy>-000001 | per submission year, submission order | LVE-2025-000412 |
| expense_claim | EXP-<yyyy>-000001 | per submission year, submission order | EXP-2026-000207 |
| expense_line | EXPL-<claim-id>-NN | per claim, 01..10 baseline, continues to 99 across rounds | EXPL-EXP-2026-000207-03 |
| receipt | RCT-000000001 | global | RCT-000002210 |
| approval_step | APR-<request-id>-NN | per request, continues across rounds | APR-LVE-2026-000012-03 |
| approval_event | APE-000000001 | global | |
| approval_attempt | APA-000000001 | global | |
| request_status_event | RSE-000000001 | global | |
| request_exception | REX-000000001 | global | |
| reimbursement | RMB-<yyyy>-000001 | per year of final approval | RMB-2026-000098 |
| reimbursement_attempt | RMA-000000001 | global | |
| cost_center_transaction | CCT-000000001 | global | |
| audit_event | AUD-000000001 | global, occurred_at order | |
| delegation | DLG-000001 | global | |
| employee_cost_center_assignment | ECA-000001 | global | |
| application_user | USR-000001 | global | |
| role | ROLE-<NAME> | natural | ROLE-APPROVER |
| processing_failure | PFL-000000001 | global | |
| idempotency_record | 64-hex SHA-256 | natural | |

Counters are assigned after sorting the stage's raw records by (simulated timestamp, stable tiebreak), so IDs are deterministic. Year segment = year of submission for LVE and EXP; year of final approval for RMB.

## 4. RNG streams (AM-A8)

Master seed 20261022 (config, CLI override). `numpy.random.SeedSequence(master).spawn(n)` produces one child per named stream; each child seeds a `numpy.random.Generator(PCG64)` and a Faker instance where descriptive text is needed.

| Stream name | Used for |
|---|---|
| employees | names, countries, departments, grades, hire/termination dates, hierarchy shuffles |
| cost_centers | budget amounts within configured ranges |
| balances | 2025 opening balances |
| leave | request employee choice, dates, durations, half-day flags, medical flag |
| expenses | claim employee choice, dates, categories, amounts, line counts, merchants |
| anomalies | which record indices receive which anomaly; anomaly parameter values |
| boundaries | which records are forced to boundary values |
| delays | approver decision delays, resubmission delays |
| payments | payment timing and the 5% failure selection |
| delegations | which approvers delegate and when |
| users | synthetic passwords |

Stream independence: the leave stream's output depends only on the leave child seed and the leave count; changing --expense-claims cannot change leave requests. Changing --employees changes the parent set that leave and expense stages sample from, so references change while the drawn sequence does not; documented in the generation guide (CF-10).

Determinism safeguards: no Python `random` module, no set iteration order in logic, all DataFrames sorted by PK before export, stable sorts, Decimal arithmetic, Faker locale fixed per country.

## 5. Volumes and scale parameters

| Parameter | Full baseline | Starter (ASM-028) | Notes |
|---|---|---|---|
| --employees | 400 | 40 | |
| leave policies | 6 | 6 | fixed from config |
| --leave-requests | 800 | 80 | |
| --expense-claims | 1,000 | 100 | |
| lines per claim | 1-10 | 1-10 | from expenses stream |
| expense policies | 18 current + 3 superseded V1 = 21 rows | same | ASM-011 |
| cost centers | 24 | 24 | ASM-016 |
| departments | 8 | 8 | ASM-015 |
| approval rules | 8 | 8 | docs/05 section 5.2 |
| holidays | about 48 (3 countries x 2 years x about 8) | same | ASM-005 |
| fx rates | 4 rows | same | ASM-003 |
| anomaly counts | ASM-027 | scaled by 1/10, min 1 | |

Command (final form, Phase 3; all flags and outputs in docs/11_generation_guide.md):

```
python -m src.data.generate --seed 20261022 --employees 400 --leave-requests 800 --expense-claims 1000 --out data --load
```

## 6. Timeline (AM-A6, AM-A7)

- Window: 2025-01-01 to 2026-10-22 (AS_OF_DATE).
- Employment start dates: 2015-01-01 to 2026-09-30 (ASM-026); about 5% of employees terminated with employment_end inside the window.
- Leave submission timestamps: drawn across the window; leave start date 1-60 days after submission for ANNUAL and CASUAL; SICK may start up to 3 days before submission (retrospective) (ASM-042).
- Expense submission: 1-30 days after the latest line expense_date; line dates within 90 days before submission (ASM-041).
- Decision timestamps: assigned_at + seeded business-day delay per level (ASM-024). Any decision that would fall after AS_OF_DATE does not happen; the request rests in PENDING_APPROVAL or ESCALATED.
- created_at of each row = its first event's timestamp; for master data = a fixed seed-load timestamp 2024-12-31T00:00:00Z.

## 7. Anomaly injection (spec 11, AM-A1, AM-A2)

### 7.1 Method

1. After S3 and S4, the anomalies stream draws disjoint index sets from the 800 leave and 1,000 expense records for each scenario (sampling without replacement across scenarios so one record carries at most one planted scenario, except where a scenario inherently needs pairs or groups).
2. Each selected record is modified in place to exhibit the scenario (table below). Totals stay exactly 800 and 1,000.
3. The intended label is kept in memory and written to ground truth in S9 together with the record's final expected behaviour.
4. S6 then runs the real services on the modified data. The services, not the injector, decide the outcome.

### 7.2 Planted scenarios and counts (ASM-027, revised at Phase 1 review, to be approved)

Design target: planted anomaly records between 8 and 10 percent of the 1,800 requests, with at least 8 examples of every dataset scenario. Result: 176 anomaly records = 9.8 percent (leave 56 of 800 = 7.0 percent; expense 120 of 1,000 = 12.0 percent). Controls (expected negatives), attempt-type scenarios and fixtures are outside that percentage because they do not make a request anomalous.

Group A: planted anomaly records in the main dataset (count toward the 8-10 percent)

| Scenario | Target | Examples | Records | In-place modification |
|---|---|---|---|---|
| S01 NEGATIVE_BALANCE_UNPERMITTED | leave + ledger | 8 | 8 | a 2025 ANNUAL request is forced APPROVED with quantity exceeding available at that time; USAGE posted; represents a legacy manual override. Service rules are bypassed for this historical row only; the detector must find it |
| S02 OVERLAPPING_APPROVED_LEAVE | leave pairs | 8 pairs | 16 | second request of pair re-dated to overlap the first; both forced APPROVED in 2025 (legacy); detector must flag both |
| S03 INSUFFICIENT_BALANCE | leave | 12 | 12 | quantity raised above available at submission on a policy forbidding negatives |
| S19-L NO_VALID_APPROVAL_PATH (leave half) | leave | 4 | 4 | requester's manager terminated with no delegate and no one above to substitute (exact construction fixed in Phase 4); or G7 requester. Never "L1 is the G7": that case resolves (AMB-P3-03), so natural cases cannot swamp the planted ones. S19 has 8 examples in total: 4 leave + 4 expense (S19-E below) |
| S22 OVERLAPPING_PENDING_LEAVE | leave | 8 | 8 | request overlapping another request that is still PENDING at that simulated time |
| S23 MEDICAL_CERT_REQUIRED | leave | 8 | 8 | SICK request of 4-7 days with medical_cert_flag false |
| S05 MISSING_RECEIPT | expense | 10 | 10 | one line >= receipt threshold gets receipt_id NULL |
| S06a DUPLICATE_RECEIPT_SELF | expense pairs | 8 pairs | 16 | a line in claim B gets the receipt hash of a line in claim A, same employee; both claims labelled |
| S06b DUPLICATE_RECEIPT_CROSS_EMPLOYEE | expense pairs | 8 pairs | 16 | same, different employees; both claims labelled |
| S07a LINE_LIMIT_EXCEEDED | expense | 8 | 8 | one line amount set to 1.2-2.0 x per_line_limit |
| S07b CLAIM_LIMIT_EXCEEDED | expense | 8 | 8 | line amounts scaled so total > per_claim_limit |
| S08 EXPENSE_OUTSIDE_EMPLOYMENT | expense | 8 | 8 | claim assigned to a terminated employee with a line dated after employment_end, or dated before employment_start |
| S09 SPLIT_CLAIM_SUSPECTED | expense groups | 8 groups (6 pairs + 2 triples) | 18 | claims of one employee re-dated within 7 days, same category, each < 200 USD, sum >= 200 USD |
| S10 MISSING_COST_CENTER | expense | 8 | 8 | cost_center_id set NULL |
| S15 POLICY_VERSION_EXPIRED | expense | 8 | 8 | claim.expense_policy_id set to a superseded V1 id |
| S19-E NO_VALID_APPROVAL_PATH (expense half) | expense | 4 | 4 | same construction as S19-L, on expense claims |
| S21 BUDGET_EXCEEDED | expense | 8 | 8 | claims assigned to a low-budget cost center (CC-0024, budget deliberately small) |
| S26 CURRENCY_MISMATCH | expense | 8 | 8 | one line currency changed |
| Subtotal leave (6 rows: S01, S02, S03, S19-L, S22, S23) | | | 56 | 8 + 16 + 12 + 4 + 8 + 8 = 56 |
| Subtotal expense (12 rows: S05, S06a, S06b, S07a, S07b, S08, S09, S10, S15, S19-E, S21, S26) | | | 120 | 10 + 16 + 16 + 8 + 8 + 8 + 18 + 8 + 8 + 4 + 8 + 8 = 120 |
| Total | | | 176 | 56 + 120 = 176 = 9.8 percent of 1,800 |

Note on the review query: reading the former single S19 row (8 records) as leave-only gives 60 and 116, which also total 176. The design splits S19 evenly, so the subtotals are 56 and 120; the table above now shows the split as two rows to remove the ambiguity.

Group B: planted controls, expected NEGATIVES for anomaly metrics (not anomalies)

| Scenario | Target | Count | Modification |
|---|---|---|---|
| S01b PERMITTED_NEGATIVE_BALANCE | leave | 8 | LPOL-ANNUAL-US employees with approved requests taking balance to -1..-3 (within limit); must NOT be detected |
| S04 WEEKEND_HOLIDAY_SPAN | leave | >= 40 ensured | start date moved to 2 business days before a holiday, end after it |
| S14 MULTI_LEVEL | natural | expect >= 150 | none; labelled from the reference route |
| S24 DELEGATED_ROUTE | leave 4 + expense 4 | 8 | manager on leave with active delegation |
| S25 PROCESSING_FAILURE | reimbursement | 5 percent of payments | payments stream; technical, not a business anomaly |
| Boundary cases BC-01..BC-10 | leave/expense | 3 per boundary (2 groups for BC-10) | docs/02 section 6 |

Group C: attempt-type scenarios (rows only in attempt and idempotency tables)

| Scenario | Target | Count | Modification |
|---|---|---|---|
| S11 SELF_APPROVAL_ATTEMPT | approval_attempt | 8 | BLOCKED attempt rows where actor = requester, on otherwise normal pending requests |
| S12 UNAUTHORIZED_APPROVER_ATTEMPT | approval_attempt | 8 | BLOCKED attempts by an employee outside the chain |
| S13 DUPLICATE_REIMBURSEMENT_ATTEMPT | reimbursement_attempt | 8 | BLOCKED second CREATE on reimbursed claims |
| S18 REPEATED_SUBMISSION | idempotency_record | 8 | second submit with same derived key; audit IDEMPOTENT_REPLAY |

Group D: negative fixtures (never in the dataset)

| Scenario | Location | Count | Content |
|---|---|---|---|
| S16 INVALID_LIFECYCLE_TRANSITION | tests/fixtures/negative/lifecycle_*.json | 8 | eight distinct illegal transitions (DRAFT->APPROVED, REJECTED->PENDING_APPROVAL, APPROVED->CANCELLED, ...) |
| S17 CLAIM_TOTAL_MISMATCH | tests/fixtures/negative/arithmetic_*.json | 8 | total too high, too low, line quantity x unit mismatch, approved > total, reimbursement amount mismatch, balance snapshot mismatch, FX mismatch, budget snapshot mismatch |
| S20 RULE_CONFLICT | tests/fixtures/negative/rules_conflict_*.yaml | 2 | one expense and one leave rule set with equal priority and different outcomes |

Removed at review: the former S27 EXPENSE_DATE_TOO_OLD planted scenario (not a spec edge case). Rule BR-EX-02 remains as an API-time validation; the generator produces no record older than 90 days.

### 7.3 Negative fixtures (AM-A2)

tests/fixtures/negative/ holds small JSON or YAML files that break structural integrity on purpose: claim total != sum of lines; expense_line referencing a non-existent claim; approval_step referencing a non-existent request; employee with a malformed ID (EMP-1); illegal lifecycle transitions; conflicting rule set. They are loaded only by tests into an isolated test database or in-memory frames and must be detected by src/validation. They are never exported to data/.

### 7.4 Naturally occurring violations

Because rules run after injection, some unplanted records may trip a rule (for example a baseline request that happens to overlap a planted one, or a claim that exceeds budget because planted claims consumed it). S9 runs the independent reference calculation (section 9.2) over all records and compares with the intended plant list: any expected exception on a record that was not planted is written to anomaly_label with is_planted = false and injection_reason = "natural consequence". This keeps ground truth complete and honest (AM-E4, RK-04) without consulting the production engine.

## 8. Boundary records (AM-E5)

The boundaries stream selects records and sets exact values; each is written to ground_truth.boundary_case with the expected outcome. List and counts in docs/02 section 6 (BC-01..BC-10). Boundary records are expected NEGATIVES for anomaly metrics unless they coincide with a planted scenario (prevented by disjoint sampling).

## 9. Ground truth (spec 12, AM-E)

### 9.1 Files (data/ground_truth/)

| File | One row per | Columns |
|---|---|---|
| record_expectations.csv | request (1,800 rows) | record_type, record_id, expected_route (JSON list of {level, approver_id}), expected_final_status_at_asof, expected_reimbursement_eligibility, expected_exception_codes (JSON list), expected_approved_amount |
| anomaly_labels.csv | planted or natural anomaly instance | label_id, scenario_id, affected_record_type, affected_record_id, issue_type, label, expected_detection, expected_workflow_behaviour, injection_reason, is_planted |
| boundary_cases.csv | boundary record | case_id, record_type, record_id, boundary_type, expected_outcome |
| scenarios.json | scenario | scenario_id, issue_type, description, planned_count, actual_count |
| ground_truth.json | combined | the above as one document |

### 9.2 How expectations are produced without circularity (DEC-01)

Ground-truth expectations never come from the production engine under test. Two independent sources are used:

1. Known by construction. For every planted scenario the injector knows what it planted, so it writes expected_exception_codes, expected_detection and expected_workflow_behaviour directly from the scenario definition (for example S03 plants a quantity above the available balance, so the expectation is INSUFFICIENT_BALANCE, REJECTED, detect). Simulated decision delays are drawn before outcomes are computed, so whether a request is still pending at AS_OF_DATE is also known by construction.
2. Independent reference calculation. A small, separate package src/reference/ computes, for every request, the expected exception codes, the expected ordered route (levels and approver IDs) and the expected final status. It is written as plain table-driven pandas code that reads config/*.yaml and the raw master data directly. It shares no code with src/services; a test fails if src/reference imports src/services or the reverse. It is deliberately simple and heavily unit-tested on hand-built cases, so it can serve as an oracle.

The production engine (S6) produces the actual data. S9 writes ground truth only from sources 1 and 2. Where the planted expectation and the reference calculation disagree, generation stops with an error, because one of the two is wrong and the dataset must not ship with an inconsistent oracle. Where the production engine disagrees with ground truth, generation continues: that disagreement is exactly what the evaluation (M5, M6-M8) must report.

Naturally occurring violations (section 7.4) are the exception codes the reference calculation finds on records that were not planted; they get is_planted = false.

### 9.3 Separation

- Postgres schema ground_truth, owned by lea_migrator, readable only by lea_evaluation.
- No FK in either direction.
- No column in ops tables named is_anomaly, issue_type, scenario_id, is_planted or similar (test).
- tests/test_ground_truth_isolation.py parses every module under src/ except src/evaluation, src/reference and src/data/stages/ground_truth.py and fails if it imports or references ground_truth models, paths or schema names.
- tests/test_reference_independence.py fails if src/reference imports anything from src/services or src/data/stages, or if src/services imports src/reference.

## 10. Export, checksum and reproducibility

- Canonical CSV: UTF-8, LF line endings, fixed column order from the data dictionary, rows sorted by PK, Decimal rendered with 2 dp, dates ISO-8601, booleans true/false, NULL as empty.
- JSON: one array per table, same ordering, `sort_keys=True`, 2-space indent.
- SQL seed: INSERT statements per table in dependency order.
- manifest.json: seed, parameters, AS_OF_DATE, generator version, row counts per table, SHA-256 per file, generated_at (the only field excluded from the reproducibility comparison, ASM-050).
- scripts/reproducibility_check.ps1 and .sh: run the generator twice into two folders and compare row counts and checksums; the result feeds metric M13.

## 11. Validation after export

src/validation runs on the exported files and, when the database is loaded, on the database: PK uniqueness, FK integrity, enums, ID patterns, date ordering, employment-date consistency, policy effective dates, lifecycle legality from status events, approval sequence consistency, arithmetic (balances vs ledger, claim totals, approved amounts, reimbursement amounts, FX), workflow integrity (routes, authorised approvers, no self-approval, no premature or duplicate reimbursement). Output: data/validation/validation_report.{csv,json,md} and detections.csv for the evaluation.

## 12. As implemented in Phase 4 (assumptions in docs/09 section 8)

| Piece | Module | Notes |
|---|---|---|
| S5 editing toolkit | src/data/stages/workbench.py | in-place edits through the shared services; after all edits ids are re-derived in submission order, receipts and the ledger renumbered (DEC-P4-03) |
| S5 anomalies | src/data/stages/anomalies.py | all Group A scenarios and controls S01b, S04, S14-L5, S24; one planted scenario per record; edited employees are locked; leave and expense draw from separate streams (ASM-P4-02) |
| S5 boundaries | src/data/stages/boundaries.py | BC-01..BC-10 |
| S9 ground truth | src/data/stages/ground_truth.py | construction vs oracle check (stops on disagreement, DEC-P4-02), natural labels, scenarios.json, files and ground_truth schema |
| Oracle | src/reference/oracle.py | plain Python + PyYAML, not pandas (DEC-P4-01); eventual outcome until Phase 7 adds timing (ASM-P4-03) |
| Validation | src/validation/{reader,checks,report,__main__}.py | 21 structural/arithmetic/workflow checks; M1-M3; detections.csv arrives with the Phase 5-6 detectors (DEC-P4-07) |
| Negative fixtures | tests/fixtures/negative/ via scripts/build_negative_fixtures.py | 8 lifecycle (S16), 8 arithmetic (S17), 2 rule-conflict (S20), 3 structural |

S19 construction (fixed here, AMB-P4-01; Phase 7B AMB-P7B-09): the requester is a G7 (no L1). S1 promotes, in each country without a G7, the lowest-id ACTIVE G6 employed for the whole window to G7 (manager NULL, no draws), so there is one G7 per country; the S19 plants are split evenly over the G7s in id order. Attempt-type scenarios S11, S12, S13, S18 and
the technical failures S25 need approval steps, reimbursements and idempotency rows; they are listed in scenarios.json
with actual_count NULL and are built with Phases 7-8.

## 13. As implemented in Phase 5 (assumptions in docs/09 section 9)

| Piece | Module | Notes |
|---|---|---|
| Leave services | src/services/{calendar_service,leave_balance_service,leave_request_service,exception_service,lifecycle}.py | BR-CAL, BR-LBAL-03..09, BR-LV-01..13, severity precedence, transition table; pure functions over a LeaveStore |
| Stores | in-memory (leave_request_service.InMemoryLeaveStore), PostgreSQL (src/repositories/leave_repository.py) | DB store locks the request and balance rows FOR UPDATE; writes request_status_event and request_exception (DEC-P5-01) |
| Leave detectors | src/services/leave_detectors.py | OVERLAPPING_APPROVED_LEAVE and NEGATIVE_BALANCE_UNPERMITTED over operational data (DEC-P5-04) |
| Replay | src/services/leave_batch.py | submission-order replay (ASM-P5-04); used by the S3 and S5 guards (DEC-01), detections.csv and the comparison |
| S3 / S5 guards | src/data/stages/leave.py (LeaveGuard), workbench.leave_guard | the services must find exactly the planted codes; the Phase 3 conservative guard is gone (DEC-P5-02) |
| Year-end requests | src/data/stages/leave.py (_draw_year_end), config leave.year_end | about 3 percent cross-year (ASM-P5-07, AMB-P5-01) |
| Services vs oracle | src/evaluation/leave_service_vs_oracle.py | every leave request compared; routing codes reported as ROUTING_PHASE7 (DEC-P5-05) |

Stage S6 (outcomes written into the dataset), routing, approvals, USAGE at approval and year-end CARRY_FORWARD rows remain Phase 7.

## 14. As implemented in Phase 6 (assumptions in docs/09 section 10)

| Piece | Module | Notes |
|---|---|---|
| Expense services | src/services/expense_service.py | BR-EX-01..13, FX to USD, policy resolution, limits, receipts, duplicates, split, budget reservation and release, submission; in-memory store |
| Detectors and replay | src/services/expense_batch.py | duplicate-receipt and split batch detectors; submission-order replay (ASM-P6-01) |
| DB store | src/repositories/expense_repository.py (shared helpers in base.py) | locks claim, cost center and budget; status events, exception rows, budget ledger |
| S4 guard | src/data/stages/expenses.py (ExpenseGuard) | the expense service must find no code on a drawn claim (DEC-P6-02) |
| Quantities | expenses.line_quantity, workbench.set_line, stream expense_quantities | quantity x unit = amount on every line (ASM-P6-02) |
| Services vs oracle | src/evaluation/expense_service_vs_oracle.py | all 1,000 claims; routing codes as ROUTING_PHASE7 |

## 15. As implemented in Phase 7B (assumptions in docs/09 section 12)

Stage S6 (src/data/stages/outcomes.py) runs after S9: the leave and expense replays with the router and a DecisionTiming (src/services/workflow_simulation.py) process every event in time order: submissions at created_at, year-end carry-forward at 00:00 UTC on 1 January, and the simulated decisions of docs/05 9.5 made through src/services/approval_service.py. Decision instants follow ASM-P7B-02 (17:00 UTC, more than 24 hours after assignment, keyed draws on the delays stream); nothing after the as-of instant happens. S6 writes the outcome columns and the seven workflow tables (DEC-P7B-03). Raw inputs are not changed (legacy approvals carry LEGACY_APPROVAL, DEC-P7B-02), so the comparisons re-run S6 on the exported dataset and check services = oracle = dataset at as-of.
