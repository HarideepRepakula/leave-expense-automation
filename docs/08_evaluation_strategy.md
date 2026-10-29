# 08. Evaluation strategy

Phase 1 deliverable. Defines every metric in spec section 17 mathematically, with its population, denominator and matching unit. No metric values are claimed here; values appear only after Phase 11 execution (spec 17: "Do not claim perfect metrics without execution results").

## 1. Evaluation inputs and isolation

| Input | Source | Reader |
|---|---|---|
| Operational data | ops schema (or data/raw exports) | src/evaluation via role lea_evaluation |
| System detections | request_exception rows (per round) plus batch detector output data/validation/detections.csv; approval_attempt and reimbursement_attempt BLOCKED rows | src/evaluation |
| Ground truth | ground_truth schema / data/ground_truth, produced from planted-scenario definitions and the independent reference calculation in src/reference, never from the production engine (docs/07 section 9.2, DEC-01) | src/evaluation only |
| Validation report | data/validation/validation_report.json | src/evaluation for M1-M3 |
| Reproducibility run | two manifests | src/evaluation for M13 |

Outputs: data/validation/evaluation.csv (one row per metric and per breakdown), evaluation.json, evaluation.md.

## 2. Matching unit for anomaly metrics (AM-E3)

A detection is the pair D = (record_id, issue_type). A ground-truth positive is the pair G = (affected_record_id, issue_type) from anomaly_label where expected_detection = DETECT. Both planted (is_planted = true) and natural (is_planted = false) labels count as positives, reported separately.

| Term | Definition |
|---|---|
| TP | D present and G present with identical (record_id, issue_type) |
| FP | D present, no matching G. Includes detections on expected NEGATIVES (permitted negative balance, weekend spans, multi-level routes, boundary records) and detections on records with no label |
| FN | G present, no matching D |
| TN | not used (undefined population of non-issues); reported as count of expected-negative records with no detection for information |

Record identity for attempt-type scenarios: the attempt row id (APA-, RMA-) or the idempotency key, as written in ground truth.

Issue types with several codes (e.g. DUPLICATE_RECEIPT_SELF vs CROSS) are distinct issue types; a self duplicate detected as cross is one FP and one FN.

## 3. Metric definitions

Notation: |X| = count of set X. Populations are fixed as of AS_OF_DATE = 2026-10-22. "Requests" = 800 leave requests + 1,000 expense claims = 1,800 unless stated.

### M1 Primary-key violation rate

- Population: every row in every exported ops table T (and negative fixtures separately).
- PK violations V_pk(T) = rows whose PK is NULL, malformed (fails the ID regex) or duplicated within T (every row of a duplicate group counts).
- M1(T) = V_pk(T) / |T|; overall M1 = sum_T V_pk(T) / sum_T |T|.
- Planted anomalies never break PKs in the main dataset, so a non-zero value is a defect, not a detection.

### M2 Foreign-key violation rate

- Population: every non-NULL FK value f in every FK column of every ops table, including polymorphic (request_type, request_id) references.
- Violation = referenced row does not exist.
- M2 = |violations| / |non-NULL FK values|; also per FK column.

### M3 Arithmetic reconciliation rate

- Checks C applied to records subject to them:
  1. expense_claim: total_amount = SUM(line_amount) over current-round lines.
  2. expense_claim: approved_amount = SUM(min(line_amount, per_line_limit)) over non-FAIL current-round lines when APPROVED; NULL otherwise.
  3. expense_line: line_amount = round(quantity x unit_amount, 2) when both present.
  4. reimbursement: approved_amount = claim.approved_amount and currency matches.
  5. leave_balance: available_balance = SUM(ledger) per (employee, policy, year) and = opening + accrued + adjustments - used.
  6. leave_request: requested_quantity = business_day_count - 0.5 x half-day flags; business_day_count recomputed from calendar.
  7. expense_claim: total_amount_usd = round(total_amount x fx_rate effective on submission date, 2).
  8. cost_center: committed and actual snapshots = SUM(ledger).
- M3 = |records passing all applicable checks| / |records subject to at least one check|; also per check.
- Negative fixtures are evaluated separately and must show the planted failures (expected M3 < 1 there).

### M4 Business-rule compliance rate

- Population R = all 1,800 requests, current round.
- Compliant(r) = r has no request_exception row of severity HARD, CORRECTABLE or SOFT in its current round (INFO allowed).
- M4 = |{r : Compliant(r)}| / |R|.
- Reported twice: over all requests, and over requests with no planted anomaly (planted set read from ground truth by the evaluation only). The spec forbids counting deliberate anomalies as accidental failures; the second figure is the data-quality view, the first is the business view.

### M5 Approval routing accuracy

- Population P = requests that reached routing in any round (workflow_status at some point PENDING_APPROVAL, or ESCALATED with NO_VALID_APPROVAL_PATH / RULE_CONFLICT) in their final round.
- Actual route A(r) = ordered list of (required_level, approver_employee_id) of the final round's approval_step rows, or the routing exception code.
- Expected route E(r) from record_expectation.expected_route, which is computed by the independent reference calculation (src/reference) from config and raw master data, not by the production approval engine. For planted routing scenarios (S19, S20) the expectation is the exception code known by construction. M5 is therefore a comparison of two independent implementations plus construction knowledge, not a self-comparison.
- Correct(r) = A(r) equals E(r) exactly (same levels, same order, same approvers or same exception code).
- M5 = |{r : Correct(r)}| / |P|. Also level-only accuracy (ignoring approver identity) as a secondary figure.
- Disagreements are listed individually in the report so that a wrong reference calculation can be told apart from a wrong engine.

### M6 Anomaly precision, M7 Anomaly recall, M8 Anomaly F1

- Over the sets in section 2: Precision = TP / (TP + FP); Recall = TP / (TP + FN); F1 = 2PR / (P + R), with 0 when the denominator is 0.
- Reported per issue_type and overall (micro-averaged: sum TP, FP, FN across issue types). Macro-average also listed.
- Breakdown: planted only; natural only.

### M9 Unauthorised approval detection rate

- Population U = ground-truth labels with issue_type in {SELF_APPROVAL_ATTEMPT, UNAUTHORIZED_APPROVER_ATTEMPT}, record = attempt id.
- Detected(u) = the approval_attempt row exists with outcome BLOCKED and reason_code in {SELF_APPROVAL, UNAUTHORIZED_APPROVER}, and the target request shows no step decided by that actor.
- M9 = |{u : Detected(u)}| / |U|. Supplement: number of ACCEPTED attempts whose actor fails the authority check when re-evaluated (should be 0; any such row is a critical defect).

### M10 Duplicate receipt detection rate

- Population G_dup = ground-truth labels with issue_type in {DUPLICATE_RECEIPT_SELF, DUPLICATE_RECEIPT_CROSS_EMPLOYEE}.
- M10 = |TP restricted to those issue types| / |G_dup| (recall). Precision for the same types is reported alongside; records sharing a hash within one claim are expected negatives.
- Confirmation (review item AMB-07): a same-employee duplicate is routed as a correctable error, but it still produces the exception code DUPLICATE_RECEIPT_SELF in request_exception and in the batch detector output, so it is a detection and is counted in M10 exactly like the cross-employee case. Routing severity and detection are separate dimensions.

### M11 Duplicate reimbursement detection rate

- Population G_rmb = ground-truth labels with issue_type DUPLICATE_REIMBURSEMENT_ATTEMPT.
- Detected = reimbursement_attempt BLOCKED with reason DUPLICATE_REIMBURSEMENT exists for the labelled attempt and the claim has exactly one non-CANCELLED reimbursement.
- M11 = |detected| / |G_rmb|. Supplement: count of claims with more than one non-CANCELLED reimbursement (must be 0; the DB index makes this structurally impossible, the metric proves it).

### M12 Reimbursement eligibility violation rate

- Population RB = all reimbursement rows with status <> CANCELLED.
- Violation(b) = claim.workflow_status <> APPROVED, or b.approved_amount <> claim.approved_amount, or b.created_at < the final approval step decision_at, or a second active reimbursement exists for the claim.
- M12 = |violations| / |RB|. Also: number of APPROVED claims with approved_amount > 0 and no reimbursement (should be 0; reported as a count, not a rate).

### M13 Reproducibility rate

- Run the generator twice with identical parameters into two folders. For each exported file f (operational, ground truth, validation report): same(f) = identical row count and identical SHA-256 of the canonical content, excluding only manifest.generated_at (ASM-050).
- M13 = |{f : same(f)}| / |files|. Also report whether ground-truth labels and validation results are identical (binary).

### M14 Average approval turnaround time

- Population D = requests with terminal decided status APPROVED or REJECTED at AS_OF_DATE (CANCELLED excluded; PENDING and ESCALATED excluded and counted in M15).
- turnaround(r) = final decision timestamp - first submission timestamp (round 1), in calendar days with decimals. Secondary figure: business days using the requester's country calendar.
- M14 = mean over D; also median, p90, and split by request type and by number of rounds.

### M15 Pending approval backlog

- Count at AS_OF_DATE of requests in PENDING_APPROVAL; reported separately for ESCALATED_FOR_REVIEW and RETURNED_FOR_CORRECTION.
- Aging buckets by days since last status change: 0-2, 3-7, 8-14, 15-30, >30. Also by awaiting level (level of the earliest PENDING step).

### M16 Policy exception rate

- Population R = 1,800 requests.
- Exception(r) = exception_class <> NONE in the current round.
- M16 = |{r : Exception(r)}| / |R|; breakdown by exception_class and by exception code (a request with several codes counts once in the rate, once per code in the breakdown).

### M17 Request rejection rate

- Population T = requests with terminal status APPROVED or REJECTED.
- M17 = |REJECTED| / |T|. Secondary: |REJECTED| / |R| over all 1,800, and rejection by stage (at validation vs by approver vs by process owner).

### M18 Average time spent at each approval level

- Population S_L = approval_step rows at level L with step_status APPROVED or REJECTED.
- time(s) = decision_at - assigned_at in calendar days (decimal); business-day variant secondary.
- M18(L) = mean over S_L for L in {L1, L2, L3, L4, L5}; also median and count. PENDING steps are reported as aging (AS_OF_DATE - assigned_at) separately, not mixed into the mean.

## 4. Handling of deliberate anomalies (spec 17)

| Metric | Treatment of planted anomalies |
|---|---|
| M1, M2, M3 | none exist in the main dataset; fixtures evaluated separately |
| M4, M16, M17 | reported both including and excluding planted records |
| M5 | planted records are included; their expected route reflects the anomaly (e.g. ESCALATED) |
| M6-M11 | planted anomalies are the positives being measured |
| M12 | planted duplicate attempts are blocked rows, not reimbursement rows, so they do not inflate violations |
| M13 | unaffected |
| M14, M15, M18 | included; they are real workflow outcomes |

## 5. Report format

evaluation.csv columns: metric_id, metric_name, breakdown_key, breakdown_value, numerator, denominator, value, unit, population_description, computed_at (= AS_OF_DATE for evaluation of generated data; real run timestamp recorded separately in manifest).

evaluation.md: one section per metric with definition, population, result table and, for M6-M8, the per-issue-type confusion counts. Every number in the Markdown is produced by the code from the CSV; no hand-typed values.

## 6. Tests on the evaluator itself

- tests/evaluation/test_matching.py: synthetic detections and labels with known TP/FP/FN.
- tests/evaluation/test_each_metric.py: tiny hand-built datasets with known answers for every metric, including empty denominators.
- tests/evaluation/test_planted_excluded.py: M4 excluding planted records differs from including them by exactly the planted count when all planted are non-compliant.
- tests/test_ground_truth_isolation.py: fails if anything outside src/evaluation, src/reference and the ground-truth writer stage touches ground truth.
- tests/test_reference_independence.py: fails if src/reference and src/services import each other.
- tests/reference/test_reference_oracle.py: hand-built cases with known routes and exception codes for the reference calculation itself.

As built (completion pass): tests/evaluation/test_metrics.py covers the helpers, the matching (known TP / FP / FN),
the planted exclusion of M4, "not measurable" on missing inputs, and that every metric on lea_dev is either measured
or carries its reason. The separate files listed above were folded into that one file.

## 7. Implementation and how to read the results (completion pass)

Command: `python -m src.evaluation.metrics` (role lea_evaluation) writes data/validation/evaluation.csv,
evaluation.json and evaluation.md; GET /evaluation returns the same result under "metrics", shown in the dashboard's
Evaluation view. Inputs besides the database: validation_report.json (M1-M3) and detections.csv from
`python -m src.validation`, reproducibility.json (M13) from `scripts/reproducibility_check.ps1`. A metric whose
population is empty or whose input is missing is reported as "not measurable: <reason>", never as a number.

How to read these results: the benchmark is synthetic and its anomalies are planted by our own generator, so 100%
precision and recall shows that the detectors implement the documented rules; it does not predict accuracy on real
data. Some detections are counted by construction: a duplicate reimbursement is blocked by a database unique index
and recorded as a BLOCKED attempt, and a payment failure is recorded as a processing_failure row, so both are always
"detected".

Choices made when implementing section 3 (DEC-CP-04..07, docs/09 section 16):

- M4, M16, M17 headline = the figure over requests WITHOUT a planted anomaly (a planted label with expected_detection
  DETECT on the request); the all-requests (business) figure is in the breakdown.
- M5 population = requests that reached routing (a PENDING_APPROVAL status event, or stored steps) plus requests
  whose expectation is NO_VALID_APPROVAL_PATH / RULE_CONFLICT. record_expectation.expected_route is also filled for
  requests stopped before routing (escalated, returned or rejected at validation); those are left out, as section 3
  says.
- M9 is not measurable while the S11 / S12 plants are deferred (8B-2); the supplement (ACCEPTED attempts that fail a
  re-check, must be 0) is still reported.
- M14 leaves out legacy approvals (no status events by design, DEC-P7B-02) and reports how many; the business-day
  variant and the split by rounds are not computed (every request has one round).
- M15 ages are counted at the dataset as-of date; M18 pending steps without an assignment time (later steps of a
  route) are not aged.
