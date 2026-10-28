# 09. Assumptions and decisions

Phase 1 deliverable. Every value below is an ASSUMPTION (illustrative synthetic). None is a real corporate policy. Nothing here is approved until you reply "APPROVED PHASE 1" or amend it.

Three sections: assumptions (ASM), open ambiguities with a proposed default (AMB), and decisions that need your explicit approval (DEC). Section 5 lists what is deliberately out of scope.

## 1. How to read this file

- ASM-nnn: a concrete value or rule we invented because the spec and amendments do not give one. It will be placed in config files with the header `illustrative_synthetic: true`.
- AMB-nn: a place where the spec can be read in more than one way. We propose a default and will implement it unless you say otherwise.
- DEC-nn: an architectural or modelling choice with alternatives. Listed as a checklist for approval.

## 2. Assumptions (illustrative synthetic)

### 2.1 Countries, currencies, FX

| ID | Assumption |
|---|---|
| ASM-001 | Countries IN, US, GB. Employee distribution 50% IN, 30% US, 20% GB (200 / 120 / 80 of 400). |
| ASM-002 | Currency by country: IN -> INR, US -> USD, GB -> GBP. Base currency USD. Employee currency = country currency. |
| ASM-003 | fx_rate rows (1 unit of from_currency in to_currency): USD->INR 83.00 effective 2025-01-01; USD->INR 84.50 effective 2026-01-01; USD->GBP 0.79 effective 2025-01-01; USD->GBP 0.78 effective 2026-01-01. USD->USD 1.00 implicit. Rates are illustrative and not market data. Conversion: amount_usd = amount_local / rate(USD->local), rounded half-up to 2 dp. |

### 2.2 Calendars

| ID | Assumption |
|---|---|
| ASM-004 | Weekend = Saturday and Sunday for all three countries (config allows per-country override). |
| ASM-005 | Hand-written illustrative holiday calendars, no substitution when a holiday falls on a weekend. IN 2025: 01-01, 01-26, 03-14, 08-15, 10-02, 10-20, 12-25. IN 2026: 01-01, 01-26, 03-03, 08-15, 10-02, 11-08, 12-25. US 2025: 01-01, 01-20, 05-26, 07-04, 09-01, 11-27, 12-25. US 2026: 01-01, 01-19, 05-25, 07-04, 09-07, 11-26, 12-25. GB 2025: 01-01, 04-18, 04-21, 05-05, 05-26, 08-25, 12-25, 12-26. GB 2026: 01-01, 04-03, 04-06, 05-04, 05-25, 08-31, 12-25, 12-26. These are synthetic calendars for the exercise and are not verified against official gazettes. |
| ASM-046 | All timestamps stored in UTC; calendar dates are local calendar dates with no time zone arithmetic. |

### 2.3 Leave policies

| ID | Assumption |
|---|---|
| ASM-006 | Six policies, all V1 effective 2025-01-01, open end, leave year = calendar year: LPOL-ANNUAL-IN-V1: 18 days, monthly accrual, carry-forward cap 10, negative not allowed. LPOL-ANNUAL-US-V1: 15 days, monthly, cap 5, negative allowed to -3. LPOL-ANNUAL-GB-V1: 25 days, monthly, cap 5, negative not allowed. LPOL-SICK-ALL-V1: 10 days, annual grant on Jan 1 (or pro-rated at joining), cap 0, negative not allowed, medical certificate required above 3 days. LPOL-CASUAL-IN-V1: 8 days, monthly, cap 0, negative not allowed, IN only. LPOL-UNPAID-ALL-V1: 0 entitlement, no balance check, maximum 30 days per leave year, routes L1+L3. min_service_days = 0 for all. |
| ASM-007 | Opening balance at 2025-01-01 for employees who joined before 2025 = a raw-input draw from the balances stream, uniform in 0.5 steps within [0, carry_forward_cap]; 0 for later joiners. Monthly accrual = entitlement / 12 rounded down to 0.5; mid-month joiner pro-rated by remaining days / days in month, rounded down to 0.5. |
| ASM-008 | Half-day: start_half_day and end_half_day flags; single-day requests may set only one; quantity = business days - 0.5 per flag; a flag on a non-business day is a correctable error. Two requests touching on one date with complementary half-day flags do not overlap. |
| ASM-009 | Leave routing bands: quantity <= 5 -> L1; 5 < q <= 10 -> L1+L2; q > 10 -> L1+L3; UNPAID any -> L1+L3. Lower bound exclusive, upper inclusive. |
| ASM-010 | Sick leave above 3.0 days requires medical_cert_flag; missing flag -> RETURNED_FOR_CORRECTION. |
| ASM-042 | Leave request durations: ANNUAL 1-15 business days (skewed short), CASUAL 0.5-3, SICK 0.5-7, UNPAID 1-20. Start 1-60 days after submission (SICK may start up to 3 days before). About 3% of requests span a leave-year boundary and are split for balance purposes. |
| ASM-047 | Unpaid leave: no balance; yearly cap 30 days; exceeding it is a HARD failure. |
| ASM-048 | Casual leave exists only for IN. |

### 2.4 Expense policies

| ID | Assumption |
|---|---|
| ASM-011 | Categories: TRAVEL, MEALS, ACCOMMODATION, OFFICE_SUPPLIES, TRAINING, CLIENT_ENTERTAINMENT. One policy family per (category, country) = 18 families. Three families (MEALS-IN, MEALS-US, MEALS-GB) have a V1 effective 2025-01-01 to 2025-12-31 and a V2 from 2026-01-01 (V2 raises the per-line limit by 10%), giving 21 policy rows and real effective-date resolution. |
| ASM-012 | USD base limits per line: TRAVEL 1,500; MEALS 75; ACCOMMODATION 300; OFFICE_SUPPLIES 250; TRAINING 2,000; CLIENT_ENTERTAINMENT 200. Per-claim limit 6,000 for all. Receipt threshold 25. Local-currency values = USD x rate at 2025-01-01, rounded to the nearest 10 INR / 1 USD / 1 GBP, stored on the policy row; comparisons happen in local currency. |
| ASM-013 | Expense routing bands (USD-equivalent at submission): <= 200 -> L1; 200 < a <= 1,000 -> L1+L2; 1,000 < a <= 5,000 -> L1+L2+L4; > 5,000 -> L1+L2+L4+L5. Lower exclusive, upper inclusive. |
| ASM-041 | Line amounts drawn per category from log-normal-shaped ranges in USD then converted: TRAVEL 50-1,400; MEALS 8-70; ACCOMMODATION 80-290; OFFICE_SUPPLIES 5-240; TRAINING 100-1,900; CLIENT_ENTERTAINMENT 20-190. Expense dates within 90 days before submission; older is a correctable error. Line counts 1-10 skewed toward 1-4. |
| ASM-019 | Split-claim window 7 days; threshold = 200 USD (the lowest routing band boundary); same employee and same primary category. |
| ASM-020 | Duplicate receipt: same hash on lines of different claims. Same employee -> DUPLICATE_RECEIPT_SELF, RETURNED_FOR_CORRECTION. Different employees -> DUPLICATE_RECEIPT_CROSS_EMPLOYEE, ESCALATED_FOR_REVIEW. Hash = SHA-256 of "merchant|date|amount|currency|synthetic-receipt-no". |
| ASM-021 | Receipt required when line_amount >= receipt_threshold (inclusive). Missing -> RETURNED_FOR_CORRECTION. |
| ASM-032 | Per-line limit breach -> partial approval (amount capped, INFO code, routing continues). Per-claim limit breach -> ESCALATED_FOR_REVIEW. |
| ASM-033 | Reference to a policy version not effective on the submission date -> POLICY_VERSION_EXPIRED, ESCALATED_FOR_REVIEW. |
| ASM-039 | All lines in a claim must be in the claim currency, which is the employee's country currency; mismatch -> RETURNED_FOR_CORRECTION. |

### 2.5 Organisation and authority

| ID | Assumption |
|---|---|
| ASM-014 | Grades G1..G7 with approximate shares 30/25/18/12/8/6/1 percent; exactly one G7 (CFO-level, L5). Hierarchy generated as a tree by grade (a manager has a strictly higher grade), max depth 7, no cycles. Exactly one finance controller per country (is_finance_controller, grade G5 or G6, in the Finance department). |
| ASM-015 | Eight departments: Engineering, Sales, Finance, HR, Operations, Marketing, Legal, IT. Each has a head (is_department_head, grade G6, or G7 for Finance). |
| ASM-016 | 24 cost centers = 8 departments x 3 countries, CC-0001..CC-0024. Budget period = calendar year (2025 and 2026 rows via budget_period columns on one cost center row per year, or one row with two periods; see DEC-17). Budget amounts USD-equivalent between 50,000 and 400,000 drawn from the cost_centers stream, except CC-0024 (Legal-GB) fixed at 8,000 USD-equivalent to produce BUDGET_EXCEEDED cases. |
| ASM-026 | Employment start dates uniform 2015-01-01 to 2026-09-30; about 5% (20) employees TERMINATED with employment_end inside 2025-01-01..2026-09-30; about 2% ON_LEAVE_OF_ABSENCE at AS_OF_DATE. |
| ASM-030 | Approver substitution: if the resolved approver is the requester, move one level up the chain; if the approver is terminated or absent, use an active delegation, else move up the chain; if one person resolves for two levels, keep one step at the higher level; if any level remains unresolved -> NO_VALID_APPROVAL_PATH. |
| ASM-049 | About 10 delegations seeded, each 5-20 days long, inside the window. |

### 2.6 Budgets, reimbursement, simulation

| ID | Assumption |
|---|---|
| ASM-017 | Budget reservation on submission and resubmission; release on REJECTED, CANCELLED and RETURNED_FOR_CORRECTION; ACTUAL on reimbursement COMPLETED with release of the remaining reservation. Reservation is posted even when it causes BUDGET_EXCEEDED. |
| ASM-018 | Partial approval: approved_amount = sum of min(line_amount, per_line_limit) over non-failed current-round lines; reason recorded per capped line. |
| ASM-031 | FX conversion date and policy resolution date = submission date of the current round. |
| ASM-034 | Pending leave requests reserve balance for validation purposes (computed, not posted to the ledger). |
| ASM-035 | Reimbursement created in the final-approval transaction with status ELIGIBLE; payment simulation moves it to PROCESSING after 1-5 business days and COMPLETED the same day; 5% of first attempts fail (PAYMENT_FAILED) and are retried after 2 business days, succeeding. Steps after AS_OF_DATE do not happen. |
| ASM-024 | Simulated decision delays in business days (delays stream): L1 uniform 0-5; L2 1-7; L3 1-7; L4 2-10; L5 3-15; process owner on ESCALATED 3-20. Simulated process-owner decisions per exception code are listed in docs/05 section 9.5. |
| ASM-025 | RETURNED_FOR_CORRECTION requests: 50% are resubmitted after 1-10 business days with the issue corrected (receipt added, cost center set, certificate flagged, currency fixed, old line removed); the rest stay returned. Maximum 3 submission rounds; a request returned a third time stays RETURNED. |
| ASM-040 | Cancellation allowed by the requester from DRAFT, SUBMITTED, PENDING_APPROVAL and RETURNED_FOR_CORRECTION; about 2% of requests are cancelled in the simulation. Cancelling APPROVED requests is out of scope. |

### 2.7 Generation mechanics

| ID | Assumption |
|---|---|
| ASM-022 | Window 2025-01-01 to 2026-10-22; submission timestamps spread across the window with a mild weekday bias; about 1% of requests remain DRAFT (never submitted). Leave and expense volumes per year are whatever the draw produces; counters per year are assigned in submission order. |
| ASM-023 | Master seed 20261022; stream names as in docs/07 section 4. |
| ASM-027 | Planted anomaly counts as listed in docs/07 section 7.2, revised at review: 176 anomaly records = 9.8 percent of 1,800 (leave 56 = S01 8 + S02 16 + S03 12 + S19-L 4 + S22 8 + S23 8; expense 120 = S05 10 + S06a 16 + S06b 16 + S07a 8 + S07b 8 + S08 8 + S09 18 + S10 8 + S15 8 + S19-E 4 + S21 8 + S26 8), at least 8 examples of every dataset scenario (S19 counts 8 across its leave and expense halves). Controls (S01b, S04, S14, S24, S25, boundaries), attempt-type scenarios (S11, S12, S13, S18, 8 each) and fixtures (S16, S17: 8 each; S20: 2) sit outside that percentage. |
| ASM-028 | Starter dataset: 40 employees, 80 leave requests, 100 expense claims; anomaly counts divided by 10 (minimum 1 per scenario). |
| ASM-029 | Exception precedence for routing: HARD > CORRECTABLE > SOFT > INFO. Class tie order for exception_class: SUSPICIOUS_PATTERN > POLICY_VIOLATION > DATA_QUALITY > NO_VALID_APPROVAL_PATH > RULE_CONFLICT. |
| ASM-038 | Expense line numbers continue across submission rounds (01..10 baseline, up to 99). |
| ASM-050 | Checksum exclusion: only manifest.generated_at. All operational and ground-truth files are compared in full. |

### 2.8 Platform and security

| ID | Assumption |
|---|---|
| ASM-054 | Independent reference calculation (src/reference) exists only to produce ground-truth expectations and to serve as an oracle; it is not used at runtime by the API or dashboard, and it is table-driven pandas code reading config/*.yaml directly. |
| ASM-036 | Simulated authentication: one application_user per employee (USR-000001.. in EMP order) plus USR-000401 admin without employee; synthetic passwords derived from the users stream and listed in data/processed/dev_credentials.csv (synthetic data only, clearly labelled); JWT HS256 with secret from .env, 8-hour expiry; roles: REQUESTER for all employees, APPROVER for anyone who is a manager or holds L3-L5, PROCESS_OWNER for department heads of Finance and HR, OPS_ANALYST for 5 Operations employees, SYSTEM_ADMIN for the admin user. |
| ASM-037 | Schemas: ops (operational) and ground_truth. Roles: lea_migrator, lea_app, lea_analytics_ro, lea_evaluation (docs/03 section 7). Databases: lea_dev and lea_test in the same Postgres container. |
| ASM-043 | Deterministic templates are the source of every decision reason. An optional LLM layer (ASM-051..053) may reword a template's text for display only; it never produces, changes or influences a decision, a code, a route or a stored value. |
| ASM-044 | Reason templates live in config/exception_codes.yaml and never use the words fraud or misconduct. The LLM rewording must preserve this; its output is rejected if it contains either word. |
| ASM-045 | Audit hash chain (prev_hash, row_hash) is a LOW-PRIORITY STRETCH item (DEC-20). Core immutability relies on triggers and role grants. |
| ASM-051 | LLM provider: Groq API, free tier only. Default model `llama-3.1-8b-instant`, selectable in config; fallback model `llama-3.3-70b-versatile` if the default is retired. Model names must be re-checked against the Groq console when Phase 9 starts. |
| ASM-052 | Groq free-tier rate limits assumed for design: about 30 requests per minute and about 14,400 requests per day for the 8B model; about 30 requests per minute and about 1,000 requests per day for the 70B model; token-per-minute limits in the low thousands to tens of thousands. These figures are from memory, change over time, and are to be verified at implementation; they live in config/llm.yaml, not in code. |
| ASM-053 | LLM behaviour: feature flag LLM_EXPLANATIONS_ENABLED (default false); key GROQ_API_KEY in .env with a placeholder in .env.example; timeout 5 seconds; one retry on transient error; on any failure, timeout, HTTP 429 or missing key the deterministic template text is returned unchanged with source = TEMPLATE. Rewordings are produced on demand for the API decision-output and dashboard explanation views, cached in memory per (request_id, round, template hash), and never written to any exported dataset, checksum, audit event or ground-truth file. The reworded text must still contain every exception code, policy id, rule id and monetary or day amount present in the template, otherwise it is discarded and the template is shown. |

## 3. Open ambiguities with proposed defaults (please confirm or change)

| ID | Ambiguity | Proposed default |
|---|---|---|
| AMB-01 | Spec 7.3 asks whether balances are materialised, transactional or both. | Both: ledger is authoritative, snapshot is a generated column reconciled by a validator (docs/05 BR-LBAL-06). |
| AMB-02 | Spec 7.4 "partially overlapping dates": hard fail or trim? | Hard fail against APPROVED (AM-B6); no automatic trimming. |
| AMB-03 | Does leave usage reduce the balance at submission or at approval? | At approval (ledger USAGE); pending requests reserve for validation only (ASM-034). |
| AMB-04 | Year segment for EXP IDs (AM-A6 names LVE explicitly). | Same rule: year of submission. |
| AMB-05 | Expense amount for routing: at expense date or submission date FX? | Submission date (ASM-031). |
| AMB-06 | Per-claim limit breach: reject, escalate or partial? | Escalate (ASM-032). |
| AMB-07 | Duplicate receipt within the same employee: honest error or violation? | Correctable error, RETURNED_FOR_CORRECTION (ASM-020). Confirmed at review: it still produces the flagged exception code DUPLICATE_RECEIPT_SELF in request_exception and in the batch detector output, so the duplicate-receipt detection metric M10 counts it (docs/08 M10). Only the routing differs from the cross-employee case. |
| AMB-08 | When several exceptions apply, which decides the route? | Severity precedence HARD > CORRECTABLE > SOFT; all codes stored (ASM-029). |
| AMB-09 | Does a rejection at L1 leave later steps PENDING, SKIPPED or CANCELLED? | SKIPPED (never needed); CANCELLED is reserved for return, cancel and resubmit. |
| AMB-10 | Are approval steps for later levels created upfront or lazily? | Upfront at routing, all PENDING; assigned_at set when the previous step is approved. |
| AMB-11 | Can a requester resubmit indefinitely? | Maximum 3 rounds (ASM-025). |
| AMB-12 | Spec 11 item 15 "invalid or expired policy reference": main dataset or fixture? | Main dataset (a valid FK to a superseded version), ESCALATED (ASM-033). |
| AMB-13 | Spec 11 item 18 "repeated submission": a duplicate row or an idempotent replay? | Idempotent replay recorded in idempotency_record and audit; no duplicate request row. |
| AMB-14 | Should seeded rule conflicts exist in the main approval_rule table? | No; only in a test fixture, so the main dataset routes deterministically (EC-20). |
| AMB-15 | VALIDATING: persisted state or transient? | Transient; appears only in status event history (DEC-08). |
| AMB-16 | Who may resolve ESCALATED_FOR_REVIEW? | PROCESS_OWNER role; additionally L4 finance controller for BUDGET_EXCEEDED only. |
| AMB-17 | Half-day flag on a weekend or holiday. | Correctable error (ASM-008). |
| AMB-18 | Leave request spanning two leave years. | Split quantity by year for balance checks and usage (BR-LBAL-09). |
| AMB-19 | Spec 7.7 "cost center assignment where needed" on lines. | Optional override column; NULL inherits the claim's cost center (DEC-16). |
| AMB-20 | Spec 20 dashboard data source "PostgreSQL" vs AM-F3 "read-only views". | Streamlit connects with lea_analytics_ro to ops views; all writes through the API. |
| AMB-21 | Spec 6 "generator supports starter dataset": fixed sizes or free? | Free via CLI flags; documented starter sizes (ASM-028). |
| AMB-22 | How many requests should be DRAFT or CANCELLED at AS_OF_DATE? | About 1% DRAFT, about 2% CANCELLED (ASM-022, ASM-040). |
| AMB-23 | Does a terminated employee's approved claim still get reimbursed? | Yes; eligibility depends on claim status only (BR-RMB-01). |
| AMB-24 | What counts as "unauthorised" for a higher-level manager approving an L1 step? | Allowed: anyone holding a higher level in the requester's chain may act at a lower level (docs/05 section 5.1). Finance roles may not act at L1-L3. |

## 4. Decision checklist requiring your approval

| ID | Decision | Alternatives considered |
|---|---|---|
| DEC-01 | Generator calls the production services for validation, routing and outcomes (one rule implementation) to produce the OPERATIONAL data. Ground-truth EXPECTATIONS never come from that engine: they come from the planted-scenario definitions (known by construction) and from an independent reference calculation in src/reference that shares no code with src/services (docs/07 section 9.2, docs/08 M5). A test enforces the import separation. | Separate simplified simulator producing the operational data (rejected: routing accuracy would measure a copy); expectations recorded from the engine (rejected at review: circular). |
| DEC-02 | Two Postgres schemas (ops, ground_truth) with four roles; evaluation role is the only one that can read both. | Single schema with a flag column (violates AM-E1); separate database (heavier). |
| DEC-03 | Real foreign keys for request references (revised at review): approval_step, request_status_event, request_exception, approval_attempt and idempotency_record each carry nullable leave_request_id and expense_claim_id with real FKs and CHECK (num_nonnulls(leave_request_id, expense_claim_id) = 1). request_type is kept as a discriminator column (required by AM-H2) with a CHECK that it matches the populated FK. audit_event and processing_failure stay polymorphic (entity_type, entity_id) because they reference any entity, not only requests. | Polymorphic (request_type, request_id) with trigger-enforced integrity (rejected at review); separate tables per request type. |
| DEC-04 | No PolicyVersion table; each policy row is a version (policy_family + version). | Separate PolicyVersion entity as spec section 7 suggests. |
| DEC-05 | Approval-rule thresholds in USD; expense-policy limits stored in local currency derived once from USD base values. | All in USD with conversion everywhere; all in local currency per rule. |
| DEC-06 | Budget ledger with RESERVATION / RELEASE / ACTUAL / OVERRIDE; snapshots reconciled. | Snapshot-only committed and actual columns. |
| DEC-07 | Exception precedence decides the route; all codes stored per round. | First failing check decides; checks stop at first failure. |
| DEC-08 | VALIDATING is transient: no request rests in it at AS_OF_DATE, but every submission round still writes a request_status_event row SUBMITTED -> VALIDATING and a second row VALIDATING -> outcome, each with its own audit_event (confirmed at review; docs/06 sections 2.1 and 8.1 step 7). | Persisted resting state; skipping the VALIDATING event entirely. |
| DEC-09 | Reimbursement created inside the final-approval transaction. | Separate scheduled job creates it (adds a window where an approved claim has no reimbursement). |
| DEC-10 | Receipt hash lives on receipt; line references receipt; hash exported on lines via join. | Store hash on both (duplication risk). |
| DEC-11 | Expense line numbers continue across rounds (up to 99); baseline stays 01..10. | Replace lines in place (overwrites history); per-round line tables. |
| DEC-12 | Same as DEC-03 (kept for cross-reference from docs/04): real FKs with exactly-one CHECK. | |
| DEC-13 | Cost center assignment resolved on the earliest line expense date. | Submission date; employee default only. |
| DEC-14 | One currency per claim, equal to the employee's country currency. | Multi-currency lines with per-line FX. |
| DEC-15 | Department table added (head_employee_id). | Department as free text on employee only. |
| DEC-16 | Optional per-line cost center override. | Claim-level only. |
| DEC-17 | Cost center budget period modelled as one cost_center row per (cost center, year) sharing a cost_center_code, or a separate cost_center_budget table. Proposed: separate cost_center_budget table (CCB-<CC>-<year>) so CC-0001 stays one row. | Duplicate cost center rows per year. |
| DEC-18 | Approval steps created upfront per round; later levels PENDING until previous approval. | Lazy creation. |
| DEC-19 | Simulated process-owner decisions per exception code (docs/05 section 9.5). | Always approve; always reject. |
| DEC-20 | Audit hash chain is LOW PRIORITY / STRETCH (revised at review). Triggers and role grants are the required immutability mechanism; the hash chain columns are added only if time allows at the end of Phase 8, and their absence is not an acceptance failure. | Hash chain as a required Phase 8 deliverable. |
| DEC-21 | Illustrative holiday calendars written by hand (ASM-005), not scraped or verified. | Use a holidays library (external data, licensing and reproducibility questions). |
| DEC-22 | Starter dataset = 1/10 scale with the same anomaly scenarios. | Clean starter dataset without anomalies. |
| DEC-23 | Grades G1-G7 shares, one G7, one finance controller per country, eight departments, 24 cost centers (ASM-014..016). | Fewer or more; your preference. |
| DEC-24 | 5% terminated employees; 2% on leave of absence (ASM-026). | |
| DEC-25 | Resubmission: 50% corrected, max 3 rounds (ASM-025). | |
| DEC-26 | Planted anomaly counts (ASM-027, docs/07 section 7.2). | Scale up or down. |
| DEC-27 | Dashboard reads Postgres directly with a read-only role; writes via API (AM-F3). | Dashboard calls the API for everything. |
| DEC-28 | Out-of-scope list in section 5 accepted (revised at review: "no LLM" removed). | Include some of them. |
| DEC-29 | Optional LLM explanation layer (added at review): Groq free tier rewords deterministic reason text for display only; feature-flagged off by default; strict fallback to template text; never affects decisions or stored data (ASM-051..053). Built in Phase 9 as an optional sub-step; the API and dashboard must pass all tests with the flag off. | No LLM at all; LLM that also classifies or decides (rejected: non-deterministic decisions violate spec 27.5). |

## 5. Explicitly out of scope for v1 (to avoid over-engineering, AM-F6)

| Item | Reason |
|---|---|
| Cancellation or amendment of APPROVED leave or claims (usage reversal) | Not required by spec edge cases; adds a reversal workflow. Ledger type USAGE_REVERSAL is reserved for a later phase. |
| Multi-currency lines within one claim | Spec requires currency consistency checks, which a single-currency model satisfies (DEC-14). |
| Live FX rates, real holiday feeds, any external data | AM-B1, AM-B2; synthetic only. |
| LLM involvement in any decision, classification, routing or stored value | Spec 27.5 forbids random outcomes for decisions. The optional Groq layer (DEC-29) only rewords display text and is off by default. |
| Production authentication, password policies, SSO | AM-F2 simulated auth with documented limitation. |
| Email or notification delivery | Not in spec. |
| Pre-approval of expenses (requires_pre_approval column reserved but unused) | Not in spec. |
| Performance tuning beyond indexes on FKs and status columns | AM-F6. |
| Scheduled background workers | Payment processing is simulated in the generator and exposed as an admin API action; no scheduler. |

## 6. Conflicts between spec and amendments

Listed with resolutions in docs/02 section 7 (CF-01..CF-11). All resolved in favour of the amendments as CLAUDE.md requires; please confirm.

## 7. Phase 3 additions (generator), awaiting "APPROVED PHASE 3"

### 7.1 Assumptions (illustrative synthetic; values live in config/*.yaml)

| ID | Assumption |
|---|---|
| ASM-P3-01 | Department shares of non-structural employees: Engineering 25%, Sales 18%, Finance 10%, HR 7%, Operations 15%, Marketing 8%, IT 10%, Legal 7%. |
| ASM-P3-02 | Department order DEPT-01..08 = Engineering, Sales, Finance, HR, Operations, Marketing, IT, Legal; cost centers numbered department-major then IN, US, GB, so CC-0024 = Legal GB as ASM-016 requires. Cost centers effective from 2015-01-01 (covers the earliest employment start). Budget: USD drawn uniform 50,000-400,000, rounded to whole thousands, converted at that year's Jan 1 rate, 2 dp. |
| ASM-P3-03 | Structural roles are fixed first: one G7 (heads Finance, root of the tree), one G6 head per other department (reports to the G7), one G5 finance controller per country in Finance. They are hired 2015-01-01..2024-12-31 and never terminated or on leave of absence. Grade quotas use largest remainder with minimums G6 >= 7 and G5 >= 3 (only binding at starter scale). A manager is in the same department with a strictly higher grade (closest grade preferred), was employed by max(report start, 2025-01-01) and had not left before the report joined; fallback = department head, then the G7. |
| ASM-P3-04 | Job titles: "<grade title>, <department>" with G1 Associate .. G6 Senior Manager; "Head of <department>"; "Finance Controller (<country>)"; G7 "Chief Financial Officer". Email = first.last.<6-digit employee number>@example.test. |
| ASM-P3-05 | Submission timestamps: dates in the window with weekday weight 1.0 and weekend weight 0.4; hour 08-18 UTC, minute uniform; always strictly before the as-of date. |
| ASM-P3-06 | Leave type draw weights: IN ANNUAL 0.50, SICK 0.25, CASUAL 0.15, UNPAID 0.10; US and GB ANNUAL 0.60, SICK 0.30, UNPAID 0.10. Business-day count weighted decay^(N-min) (ANNUAL 0.82, CASUAL 0.60, SICK 0.65, UNPAID 0.88); half-day flag probability per end ANNUAL 0.10, CASUAL 0.25, SICK 0.15, UNPAID 0. Start = submission + offset (1..60 days; SICK -3..60, the literal reading of ASM-042), moved to the next business day; end = N-th business day. |
| ASM-P3-07 | Expense primary category weights TRAVEL 0.20, MEALS 0.30, ACCOMMODATION 0.15, OFFICE_SUPPLIES 0.15, TRAINING 0.08, CLIENT_ENTERTAINMENT 0.12; each line keeps that category with probability 0.70, else another category uniformly. Line amounts log-uniform inside the ASM-041 USD ranges, converted at the submission-date rate. Latest line date = submission - 1..30 days; other lines uniform in [max(submission - 90, employment start), latest]. quantity and unit_amount are NULL on baseline lines. |
| ASM-P3-08 | Every line at or above the receipt threshold carries a receipt; lines below it carry one with probability 0.60. |
| ASM-P3-09 | Merchant = Faker company() for the employee's locale; description "<label> - <merchant>" with labels per category in config; receipt number "INV-" + 8 digits. |
| ASM-P3-10 | Simulated users: username = employee email; synthetic 12-character passwords from the users stream; bcrypt cost 4 with a salt drawn from the users stream (deterministic so checksums are reproducible; synthetic dev credentials only, never real security). Plain passwords are written to data/processed/dev_credentials.csv, which is git-ignored. Terminated employees' users are inactive. OPS_ANALYST count scales with employees (5 at 400, minimum 1). |
| ASM-P3-11 | MEALS V2 per-line limit = USD base x 1.10, converted at the 2025-01-01 reference rate and rounded like V1 (US: 82.50 -> 83.00). |
| ASM-P3-12 | Holiday names are illustrative labels for the ASM-005 dates. |
| ASM-P3-13 | No leave ends after 2026-12-31 (no 2027 balances exist). |
| ASM-P3-14 | SICK annual grant for a joiner = entitlement x remaining days of the year / days in the year, rounded down to 0.5, dated on the joining date. MONTHLY joiner pro-rating applies to the already-rounded monthly amount. |
| ASM-P3-15 | One cost center assignment per employee covering the whole employment (no transfers in the baseline). |
| ASM-P3-16 | Delegations: count scales with employees (10 at 400, minimum 1); approver = a manager (not the G7) employed and active for the whole window; delegate = a same-grade peer in the department, else the approver's own manager; 5-20 days inside the window. |
| ASM-P3-17 | Baseline medical_cert_flag is true exactly when a SICK request exceeds 3.0 days. DRAFT requests (about 1%) take their ID year from their creation timestamp. |
| ASM-P3-18 | Timestamps: master rows created_at = 2024-12-31T00:00:00Z (docs/07 section 6, also for later hires); ledger posted_at = txn_date 00:00 UTC; leave_balance.last_recalculated_at = as-of date 00:00 UTC; ledger correlation_id = UUIDv5 of the transaction id. |

### 7.2 Decisions

| ID | Decision | Alternatives considered |
|---|---|---|
| DEC-37 | Three pure rule functions are brought forward from Phases 5-6 into src/services (calendar_service: business days and quantities; leave_balance_service.accrual_schedule; policy_resolver.resolve_version) so the generator never re-implements a rule (DEC-01, RK-01). Phases 5-6 extend them with the DB-backed services and full test matrices. | Duplicate the rules in src/data (rejected: two implementations); leave business_day_count etc. empty (impossible: NOT NULL columns). |
| DEC-38 | `--load` replaces the lea_dev ops data: TRUNCATE all ops tables and insert in one transaction, using DATABASE_URL (schema owner), refusing any database other than lea_dev or *_test. lea_app cannot truncate append-only tables, by design. ground_truth is untouched. | Load through lea_app with DELETE (blocked by append-only triggers); incremental upsert. |
| DEC-39 | JSON export renders decimals and timestamps as strings (exact, canonical); booleans and integers stay native. CSV renders decimals with the column's scale. | Decimals as JSON numbers (float formatting is not canonical). |
| DEC-40 | Generator dependencies are pinned to exact versions (numpy 2.2.6, Faker 37.4.0, PyYAML 6.0.2, bcrypt 4.3.0), because a Faker or numpy upgrade can change drawn values and therefore checksums. | Ranges (would silently break M13 after an upgrade). |
| DEC-41 | Phase 3 data is a valid baseline only: re-draw (not repair) any draw that would overlap, exceed the balance at submission, leave employment, exceed the unpaid cap, exceed a policy limit, or come from the G7. Anomalies are planted only in Phase 4 (docs/07 section 7). | Generate and then repair records (harder to reason about); allow natural violations. |

### 7.3 Ambiguities found in Phase 3

Owner decisions (2026-10-28):
- AMB-P3-01: ACCEPTED as proposed.
- AMB-P3-02: CHANGED. Split cross-year requests by leave year; check each part against its own year's balance including that year's scheduled accrual (docs/05 BR-LBAL-09 updated). The Phase 3 generator still uses the stricter posted-ledger guard, which is valid under the new rule but produces few cross-year requests (see PROGRESS.md).
- AMB-P3-03: ACCEPTED with refinement. When the G7 is L1 and the only possible L2, create ONE step recording both levels (docs/05 section 5.4). Planted S19 cases use a different cause (docs/07 section 7.2).
- AMB-P3-04: ACCEPTED, provided SICK, CASUAL and UNPAID keep enough examples to score (full run: SICK 252, UNPAID 98, CASUAL 59).

Original proposals:

| ID | Ambiguity | Proposed default |
|---|---|---|
| AMB-P3-01 | Which workflow state do generated requests have before the Phase 7 engine exists? | SUBMITTED (about 1% DRAFT), exception_class NONE, validation fields empty (claim policy id, FX, USD total NULL; lines PENDING). Stage S6 in Phase 7 replaces them with real outcomes. |
| AMB-P3-02 | Requests that cross into the next leave year: at submission the next year has no posted accrual or carry-forward yet, so under BR-LBAL-07/08 any ANNUAL/SICK/CASUAL cross-year request fails INSUFFICIENT_BALANCE. ASM-042 expected about 3% cross-year requests. | Keep the rule as written (posted ledger only). Baseline cross-year requests are therefore UNPAID only (1 of 800 in the full run). Alternative: count the next year's scheduled Jan 1 accrual/grant as available for the next-year portion (a rule change for Phase 5). |
| AMB-P3-03 | Direct reports of the G7 have no skip-level manager. 30 employees report to the G7 (the 7 department heads among them); 15 leave and 49 expense baseline requests from them need L2. docs/05 section 5.4 would make all of them NO_VALID_APPROVAL_PATH. | Proposed for Phase 7 (not implemented in Phase 3): when L1 is the root (G7), the L2 requirement is met by the G7 (one step at the higher level, like the ASM-030 dedupe rule); NO_VALID_APPROVAL_PATH stays for G7 requesters and broken chains (S19). Until decided, Phase 4 ground truth would label these 64 as natural NO_VALID_APPROVAL_PATH. |
| AMB-P3-04 | Rejection sampling shifts the realised leave type mix (full run: ANNUAL 391 / SICK 252 / UNPAID 98 / CASUAL 59, i.e. ANNUAL 49% vs a drawn ~56%), because ANNUAL draws fail the balance guard more often. | Accept and document; alternative is to re-draw dates within the same type. |

## 8. Phase 4 additions (anomalies, ground truth, validation), APPROVED 2026-10-28 (AMB-P4-01..07 accepted)

### 8.1 Assumptions (ASSUMPTION, illustrative synthetic; values in config/*.yaml)

| ID | Assumption |
|---|---|
| ASM-P4-01 | Control S14-L5 (carry-in "8 claims above 5,000 USD"): 8 claims scaled to a total drawn uniform in 5,100-5,800 USD-equivalent (above the L5 threshold, inside the 6,000 USD per-claim limit). Line amounts are proportional to their per-line limits; when capacity is short, lines move to the highest-limit category (TRAINING). Expected negative (MULTI_LEVEL_ROUTE, NOT_DETECT). |
| ASM-P4-02 | S5 streams: `anomalies` and `boundaries` drive leave edits; `anomalies_expense` and `boundaries_expense` (appended at the end of the stream list) drive expense edits, so changing one request volume never changes the other's planted records (AM-A8, CF-10). |
| ASM-P4-03 | Until stage S6 exists (Phase 7), `expected_final_status_at_asof` holds the EVENTUAL outcome with no timing: clean -> APPROVED; HARD -> REJECTED; CORRECTABLE -> RETURNED_FOR_CORRECTION (no resubmission); SOFT -> simulated process-owner decision. Phase 7 applies the seeded decision delays, the AS_OF cut-off and resubmissions (ASM-024/025), which turns some of these into PENDING_APPROVAL / ESCALATED at the as-of date. See AMB-P4-03. |
| ASM-P4-04 | When a later request is checked, an earlier request whose eventual outcome holds dates, balance or budget (APPROVED or ESCALATED) counts as still pending: it reserves balance (BR-LBAL-07), reserves budget (BR-BUD-02) and gives OVERLAPPING_PENDING_LEAVE on overlap. Legacy approvals (S01/S02) count as APPROVED from their submission date. Rejected and returned requests release (BR-BUD-04). |
| ASM-P4-05 | `expected_route` is recorded whenever validation neither rejects nor returns the request (it is the route that applies when routing happens, also after a process-owner approval); NULL when validation rejects/returns, and NULL with the code NO_VALID_APPROVAL_PATH or RULE_CONFLICT when routing fails. Route entries: {level, approver_id, covers, delegated_from}; `covers` lists every level one person covers (ASM-030, AMB-P3-03). |
| ASM-P4-06 | S22 pairs are taken in order of the smallest submission gap (at most 24 hours) between the pending partner and the overlapping request. Correct only if the Phase 7 simulation does not decide the partner within that gap (see AMB-P4-04). |
| ASM-P4-07 | An overlap that a process owner reviewed and approved (OVERLAPPING_PENDING_LEAVE -> APPROVED) is not flagged again as OVERLAPPING_APPROVED_LEAVE by the batch overlap detector. |
| ASM-P4-08 | Codes found only by batch detectors are part of `expected_exception_codes` but do not change that record's own submission outcome: the earlier claim of a duplicate-receipt pair, the first claim of a split group, the legacy pairs of S02, the S01 negative ledger balance. |
| ASM-P4-09 | Legacy approvals (S01, S02): workflow_status APPROVED with no approval steps (rows that predate enforcement, AM-A3); a USAGE posting dated on the submission date reduces the balance; an UNPAID legacy request posts nothing (no balance, ASM-047). |
| ASM-P4-10 | S08 and BC-05 (end date): the claim is re-assigned to a terminated employee of the same country and submitted after the employment end (a former employee claiming expenses); cost center = assignment on the earliest line date, else the employee's default. |
| ASM-P4-11 | S21: CC-0024 (budget fixed at 8,000 USD-equivalent) is reserved for S21. The first planted claim (year 2026 tried first) is re-assigned to a Legal GB employee and scaled so its reservation exceeds the remaining budget by 2 percent of the budget; 7 later GB claims of that year are re-assigned too. Baseline CC-0024 claims submitted after the crossing become natural BUDGET_EXCEEDED labels (1 in the full run). |
| ASM-P4-12 | Oracle carry-forward (BR-LBAL-04): the 2026 opening is computed from 2025 opening + full 2025 accrual - 2025 approved usage, capped; a negative balance carries only when the policy allows negatives. Not counted for a next-year part at submission (BR-LBAL-09). The Phase 3 generator ignored carry-forward (stricter), so the baseline stays valid under both. |
| ASM-P4-13 | Split window: all submission dates within 7 calendar days, i.e. max(date) - min(date) <= 6 (BR-SPLIT-02); groups formed greedily from the earliest unassigned claim. |
| ASM-P4-14 | The exception catalogue (config/exception_codes.yaml, 26 codes, loaded into ops.exception_code) adds two codes that docs/05 uses but docs/02 section 5 does not list: EXPENSE_DATE_TOO_OLD (DATA_QUALITY, CORRECTABLE, BR-EX-02) and DUPLICATE_CLAIM_PATTERN (SUSPICIOUS_PATTERN, SOFT, BR-EX-12). Templates are placeholders for Phase 9 and never use accusatory words. |
| ASM-P4-15 | Process-owner decision when several SOFT codes are present: any reject code (SPLIT_CLAIM_SUSPECTED, DUPLICATE_RECEIPT_CROSS_EMPLOYEE) -> REJECTED; else any return code (MISSING/INVALID_COST_CENTER) -> RETURNED; else when every code is an approve code (OVERLAPPING_PENDING_LEAVE, BUDGET_EXCEEDED, POLICY_VERSION_EXPIRED) -> APPROVED; otherwise (CLAIM_LIMIT_EXCEEDED, NO_VALID_APPROVAL_PATH, NEGATIVE_BALANCE_UNPERMITTED, DUPLICATE_CLAIM_PATTERN, RULE_CONFLICT) the request stays ESCALATED_FOR_REVIEW (docs/05 9.5 gives no decision). See AMB-P4-07. |
| ASM-P4-16 | Natural controls are labelled NOT_DETECT with is_planted = false: S04 for every submitted leave request whose dates include a public holiday, S14 for every request whose rule requires two or more levels. Label ids GTL-nnnnnn in order (planted first, scenario, record, issue type); boundary ids GTB-nnnn. |
| ASM-P4-17 | manifest.generated_at = time the content was first generated: when a run produces content identical to the existing manifest (apart from generated_at), the file is left untouched, so git shows no change. ASM-050 still excludes generated_at from comparisons. |
| ASM-P4-18 | Starter scale (ASM-028): counts scale to max(1, full/10); scenarios that find no valid candidate at that scale report actual < planned (corrected in Phase 5: the committed Phase 4 code gives BC-05 1 of 2 and S09 2 of 5 at starter scale; the earlier list BC-07, BC-10, S09, S21, S24 did not match it; since Phase 5 the generator prints a warning and the manifest records scenarios_not_reached). Full scale must and does reach every planned count (tested). |

### 8.2 Decisions

| ID | Decision | Alternatives considered |
|---|---|---|
| DEC-P4-01 | The reference oracle (src/reference/oracle.py) is plain table-driven Python using only the standard library and PyYAML; docs/07 9.2 said "pandas". This avoids a new pinned dependency (DEC-40) and keeps the oracle small. It imports nothing from src.services, src.data, src.validation or src.models (tested). | pandas (new dependency, no functional gain at these volumes). |
| DEC-P4-02 | Every planted and boundary record is checked against the oracle in S9: codes, required levels, L5 coverage, delegated step, holiday start. Any disagreement stops generation (GroundTruthDisagreement), as docs/07 9.2 requires. | Warn and continue (would ship an inconsistent oracle). |
| DEC-P4-03 | S5 edits may move a submission timestamp (S09, BC-07, BC-10), so after all edits the LVE/EXP ids are re-derived in submission order, receipts renumbered in claim/line order and the ledger renumbered (nothing referenced them yet). The Phase 3 fingerprint therefore changes (expected). | Never move timestamps (S09 and BC-07 as specified would be impossible). |
| DEC-P4-04 | The validation report and the ground-truth files are written before the manifest and checksummed in it, so the reproducibility check (M13) covers ops, ground-truth and validation files alike. | Separate manifests. |
| DEC-P4-05 | The exception_code catalogue is generated from config/exception_codes.yaml in S1 (ops.exception_code, 26 rows), because the oracle and the validator need severities now. | Wait for Phase 5. |
| DEC-P4-06 | tests/db/test_generator_load.py: lea_test's test-only EXCLUDE constraint (A3) must reject the planted S02 overlaps (tested); to check every other constraint the count test lifts that one constraint for its own load and restores it. lea_dev has no such constraint and loads the full dataset. | Load only the baseline into lea_test. |
| DEC-P4-07 | Validation (src/validation) is structural and arithmetic only (21 checks, M1-M3, lifecycle, workflow integrity). Business-rule detection (detections.csv) belongs to the Phase 5-6 detectors and services. | Put detectors in the validator (would duplicate rules outside src/services). |

### 8.3 Ambiguities found in Phase 4 (default APPLIED; please confirm or change)

| ID | Ambiguity | Default applied |
|---|---|---|
| AMB-P4-01 | S19 "manager terminated with no delegate and no one above to substitute": under ASM-030 a terminated manager is always replaced by the next person up the chain, and "L1 is the G7" now resolves (AMB-P3-03). The only construction that has no valid path is a G7 requester. | All 8 S19 records (4 leave + 4 expense) are requests re-assigned to the G7 (no L1). The oracle confirms NO_VALID_APPROVAL_PATH on each; no natural NO_VALID_APPROVAL_PATH remains. |
| AMB-P4-02 | S10 sets cost_center_id NULL, but the DB CHECK (AM-A2) requires exception_class <> NONE for that, while other raw requests keep NONE until S6 (AMB-P3-01). | S10 claims carry exception_class DATA_QUALITY (the catalogue class of MISSING_COST_CENTER), known by construction. |
| AMB-P4-03 | `expected_final_status_at_asof` cannot include timing before Phase 7 (delays are drawn by S6). | Eventual outcome now (ASM-P4-03); Phase 7 recomputes the at-as-of status from the delays stream, still independently of the engine. |
| AMB-P4-04 | S22 needs the partner to be still pending when the overlapping request arrives; with ASM-024 an L1 decision delay of 0 business days is possible. | Smallest gaps (<= 24 h) chosen; Phase 7 should treat a 0-day delay as "end of the business day" or later, or keep S22 partners undecided until the S22 submission. |
| AMB-P4-05 | BC-10 (split pair exactly at 200 USD) is a boundary but its rule outcome is a flag. | Labelled as planted positives (scenario BC-10, SPLIT_CLAIM_SUSPECTED, DETECT), counted outside the 176 Group A records. |
| AMB-P4-06 | S08 / BC-05 end date need a line after / on the employment end, which only exists when the claim is submitted after termination. | Accepted as a former-employee claim (ASM-P4-10). |
| AMB-P4-07 | docs/05 9.5 defines process-owner decisions only for single codes; mixed SOFT codes and codes without a decision need a rule. | ASM-P4-15 precedence (reject > return > approve-only; otherwise stays escalated). |

## 9. Phase 5 additions (leave balance and leave request services), APPROVED 2026-10-28 (AMB-P5-01..04 accepted)

### 9.1 Assumptions (ASSUMPTION, illustrative synthetic; values in config/*.yaml)

| ID | Assumption |
|---|---|
| ASM-P5-01 | Accrual at submission is taken from the BR-LBAL-03 schedule. Posted ACCRUAL rows must equal that schedule up to the submission date (BR-LV-13); a difference raises LedgerMismatch, a technical failure (a processing_failure row from Phase 8), never a business exception code. |
| ASM-P5-02 | The per-year rule of BR-LBAL-09 is applied to every request, single-year or cross-year: available(year) = carry-forward into that year + posted ledger rows of that year dated on or before the submission date (other than ACCRUAL) + accrual scheduled on or before max(submission date, start of the part in that year) - open reservations (PENDING_APPROVAL, ESCALATED_FOR_REVIEW) of the same employee, policy and year. INSUFFICIENT_BALANCE when available - part < floor (0, or -negative_limit_days). |
| ASM-P5-03 | Carry-forward before the year-end CARRY_FORWARD rows exist (they are posted from Phase 7): on or after 1 January it is recomputed from the previous year's ledger at 31 December (plus usage posted since) minus that year's still-open reservations (requests pending at year end are treated as if approved), then BR-LBAL-04. Before 1 January it is not counted (BR-LBAL-09). Once CARRY_FORWARD rows are posted they are used as they are. See AMB-P5-02. |
| ASM-P5-04 | Replay rules (src/services/leave_batch.py), used by the generator guards, detections.csv and the oracle comparison: DRAFT requests are invisible; an APPROVED request in the data is a legacy approval (S01, S02; ASM-P4-09), not validated, whose USAGE is posted on its submission date when its turn comes; every other request is submitted as a DRAFT at its created_at instant. Requests stay SUBMITTED in the dataset (AMB-P3-01). |
| ASM-P5-05 | NEGATIVE_BALANCE_UNPERMITTED (batch detector): after each USAGE posting, the balance of that year computed with the same formula as validation, counting requests that were open (submitted earlier, not rejected or returned) as reserved; below the floor = finding. A permitted negative balance (AM-A4a, within the limit) is never a finding. See AMB-P5-03. |
| ASM-P5-06 | A leave year without a leave_balance row has nothing available (there is no balance to post usage to). The generator keeps every leave on or after the window start (2025-01-01), as it already ends them by 2026-12-31 (ASM-P3-13). |
| ASM-P5-07 | Year-end requests (config/generation.yaml leave.year_end): each request draws once from the leave stream whether it is a designated year-end request (probability 0.03). Such a request has its last business day (new_year_business_days = 1) on the first business day of January 2026 and the rest on the last business days of December 2025; submission = start minus the usual start offset. With natural spans this gives 24 of 800 requests = 3.00 percent cross-year (ASM-042). Natural spans alone gave 5 of 800 = 0.62 percent. See AMB-P5-01. |
| ASM-P5-08 | decision_reason_code = the first code, in catalogue order, of the deciding severity for REJECTED, RETURNED_FOR_CORRECTION and ESCALATED_FOR_REVIEW (docs/05 9.3 names it only for REJECTED); NULL for PENDING_APPROVAL. See AMB-P5-04. |
| ASM-P5-09 | requested_quantity is stored as max(computed, 0): a half-day flag on a request with no business days would compute -0.5, which the DB CHECK forbids; ZERO_BUSINESS_DAYS and HALF_DAY_ON_NON_BUSINESS_DAY record the problem. |
| ASM-P5-10 | BR-LV-06 (leave type matches the policy) has nothing separate to compare: the request stores only the policy version id, whose leave_type is by definition the request's leave type. |
| ASM-P5-11 | Status events of a submission: DRAFT -> SUBMITTED (actor = requester), SUBMITTED -> VALIDATING and VALIDATING -> outcome (actor NULL = system), all at the submission instant; the outcome event carries reason_code = decision_reason_code and calculated_values (business days, quantity, per-year split, balance per year, codes, exception class). |

### 9.2 Decisions

| ID | Decision | Alternatives considered |
|---|---|---|
| DEC-P5-01 | The services are plain functions over a LeaveStore protocol with two implementations: an in-memory store (generator guards, replay, unit tests) and a PostgreSQL store (src/repositories/leave_repository.py) that locks the request row and the employee's leave_balance rows FOR UPDATE before reading the ledger (AM-F5) and never commits (the caller owns the transaction). | DB-only services (the generator could not use them without a database). |
| DEC-P5-02 | DEC-01 applied to the generator now: the S3 validity guard and the S5 workbench guard are the Phase 5 services (replay of all of the employee's requests plus the leave detectors must find exactly the planted codes, nothing on any other request). The Phase 3 conservative posted-ledger guard is removed. The generator keeps its own raw-input bounds (window start, last leave date) and the Phase 3/4 rule that submitted requests of one employee never overlap unless planted (debugging note 1 in PROGRESS.md). | Keep the stricter guard (fails ASM-042: about 0.1 percent cross-year). |
| DEC-P5-03 | data/validation/detections.csv is produced now from the replay (submission findings and batch detectors; columns record_type, record_id, exception_code, detected_by, detail) and is checksummed in the manifest (M13). The dataset rows are not changed. Expense detections join it in Phase 6. | Wait for Phase 7 request_exception rows. |
| DEC-P5-04 | The leave batch detectors (OVERLAPPING_APPROVED_LEAVE, NEGATIVE_BALANCE_UNPERMITTED) live in src/services/leave_detectors.py and use the same balance code as validation (DEC-P4-07: no rules in src/validation). | src/validation/detectors (would duplicate the balance rules). |
| DEC-P5-05 | The services-vs-oracle comparison is src/evaluation/leave_service_vs_oracle.py (the only package allowed to read both). Routing codes (NO_VALID_APPROVAL_PATH, RULE_CONFLICT) belong to Phase 7: they are removed from both sides and every record that carries one is reported as ROUTING_PHASE7, never as agreement. | Compare only the records without routing codes (would hide the gap). |
| DEC-P5-06 | Not in Phase 5: routing and approval steps, resubmission (submit_leave raises IllegalTransition for RETURNED_FOR_CORRECTION with a Phase 7 message), USAGE at approval and year-end CARRY_FORWARD rows (Phase 7); audit_event rows and idempotency records on submit (Phase 8). | |
| DEC-P5-07 | id_sequence scopes RSE and REX are created on first use from the highest id already in the table, so ids allocated by the services continue after a loaded dataset (DEC-32). | Start at 1 (would collide with loaded rows). |

### 9.3 Ambiguities found in Phase 5 (default APPLIED; please confirm or change)

| ID | Ambiguity | Default applied |
|---|---|---|
| AMB-P5-01 | ASM-042 asks for about 3 percent cross-year requests, but with the per-year rule natural spans give only 0.62 percent (5 of 800): few start dates fall in the last days of December, and a next-year part can only use that year's 1 January accrual (1.0 to 2.0 days for annual leave). | Designated year-end requests (ASM-P5-07): share 0.03, one business day in January. Result 24 of 800 = 3.00 percent. Alternatives: accept the natural share; allow more January days (fewer pass the balance check). |
| AMB-P5-02 | BR-LBAL-09 says carry-forward is unknown until 31 December, but not how to treat it after 1 January when the year-end CARRY_FORWARD posting does not exist yet (Phase 7). | Recompute it from the previous year's ledger minus still-open reservations (ASM-P5-03). The services then agree with the oracle (ASM-P4-12) on every leave record of the dataset. Alternatives: count no carry-forward until it is posted (stricter); ignore open reservations (more lenient). |
| AMB-P5-03 | AM-A4 says the negative-balance detector looks at "the ledger". In Phase 5 the only USAGE rows are legacy approvals; earlier requests still pending are not in the ledger yet. A ledger-only detector would miss S01 records whose balance was already reserved by earlier pending requests (the oracle and the S01 construction count them). | Count open reservations (ASM-P5-05). Alternative: posted ledger only (would disagree with the oracle on S01). |
| AMB-P5-04 | docs/05 9.3 gives decision_reason_code only for REJECTED. | Also set for RETURNED_FOR_CORRECTION and ESCALATED_FOR_REVIEW (ASM-P5-08). |
