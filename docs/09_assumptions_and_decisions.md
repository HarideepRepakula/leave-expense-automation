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
| ASM-014 | Grades G1..G7 with approximate shares 30/25/18/12/8/6/1 percent; exactly one G7 (CFO-level, L5); since Phase 7B one G7 per country (AMB-P7B-09). Hierarchy generated as a tree by grade (a manager has a strictly higher grade), max depth 7, no cycles. Exactly one finance controller per country (is_finance_controller, grade G5 or G6, in the Finance department). |
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

## 10. Phase 6 additions (expense validation and expense claim services), APPROVED 2026-10-28 (AMB-P6-01..05 accepted; AMB-P6-01: the oracle is aligned in Phase 7A)

### 10.1 Assumptions (ASSUMPTION, illustrative synthetic; values in config/*.yaml)

| ID | Assumption |
|---|---|
| ASM-P6-01 | Replay rules for expense (src/services/expense_batch.py), used for detections.csv and the oracle comparison: DRAFT claims are invisible; every other claim is submitted as a DRAFT at its created_at instant, in submission order. Claims stay SUBMITTED in the dataset (AMB-P3-01). |
| ASM-P6-02 | Every line carries quantity and unit_amount (V-ARITH-03). Quantity is a raw input drawn from the new, last stream expense_quantities among 1..quantity_max[category] (TRAVEL 3, MEALS 4, ACCOMMODATION 5, OFFICE_SUPPLIES 10, TRAINING 1, CLIENT_ENTERTAINMENT 4) that divide the line amount in cents exactly; unit_amount = amount / quantity, exact. When S5 changes a line amount, the quantity is kept if it still divides the new amount, else it becomes 1. Line amounts are never changed for this. |
| ASM-P6-03 | USD amount = round half-up to 2 dp of local total / rate, with the USD->local rate effective on the submission date (ASM-031); the same rate is stored in fx_rate_used. |
| ASM-P6-04 | Line validation_result: FAIL when the line carries EXPENSE_OUTSIDE_EMPLOYMENT, EXPENSE_DATE_TOO_OLD, CURRENCY_MISMATCH, POLICY_NOT_APPLICABLE or MISSING_RECEIPT; else CAPPED when above the per-line limit; else PASS. approved_amount (BR-EX-14) = SUM(min(line, per-line limit)) over non-FAIL lines; it is computed at submission but stored only when the claim is APPROVED (DB CHECK, Phase 7). |
| ASM-P6-05 | Budget at submission (BR-BUD-01..04): available = budget - actual - committed from the budget ledger of the period containing the submission date; a RESERVATION of the claim total is posted in the same transaction (also when BUDGET_EXCEEDED, BR-BUD-03) and RELEASED at once when the outcome is REJECTED or RETURNED_FOR_CORRECTION. ESCALATED claims keep their reservation until a decision (Phase 7). The DB store keeps cost_center_budget.committed_amount equal to the ledger (V-ARITH-08). |
| ASM-P6-06 | Cross-claim checks at submission (duplicate receipt, duplicate claim pattern, split claim) compare with every earlier submitted claim, whatever its outcome (a rejected claim's receipt is still a used receipt). Batch detectors use every submitted claim. |
| ASM-P6-07 | claim.expense_policy_id: a version already stored on the claim is kept and checked (POLICY_VERSION_EXPIRED); otherwise the version of the primary (highest-amount) line's category is stored (BR-EX-03). total_amount_usd, fx_rate_used, receipt_status and the line policy/result are written at submission by the DB store; the generated dataset keeps them NULL / PENDING until S6 (Phase 7), so V-ARITH-07 is still not applicable there. |

### 10.2 Decisions

| ID | Decision | Alternatives considered |
|---|---|---|
| DEC-P6-01 | Same pattern as leave: pure validate_claim / submit_expense over an ExpenseStore protocol, with an in-memory store and a PostgreSQL store (src/repositories/expense_repository.py) that locks the claim, its cost_center and the budget row FOR UPDATE. Finding/FindingSet moved to exception_service and id allocation plus the status/exception writes to src/repositories/base.py, shared by leave and expense (behaviour unchanged, leave tests pass). | Separate copies per request type. |
| DEC-P6-02 | DEC-01 for S4: a drawn claim is kept only when validate_claim finds no code on it alone. The draws are unchanged, so expense_claim, receipt and all ground truth are byte-identical to Phase 5; only expense_line gains quantity and unit_amount. | Also guard cross-claim patterns in S4 (would remove the natural split pair labelled in Phase 4 and change the dataset). |
| DEC-P6-03 | detections.csv now holds leave and expense detections (submission findings and the duplicate-receipt and split batch detectors). | Separate files. |
| DEC-P6-04 | src/evaluation/expense_service_vs_oracle.py compares all 1,000 claims; routing codes are reported as ROUTING_PHASE7 (DEC-P5-05). | |
| DEC-P6-05 | Not in Phase 6: routing and approvals (Phase 7), reimbursement (Phase 8), audit_event and idempotency rows (Phase 8), API and dashboard. | |

### 10.3 Ambiguities found in Phase 6 (default APPLIED; please confirm or change)

| ID | Ambiguity | Default applied |
|---|---|---|
| AMB-P6-01 | An ESCALATED claim that the process owner will later reject (split, cross-employee duplicate) still holds its budget reservation until then (BR-BUD-03/04); the oracle's eventual model (ASM-P4-04) drops it at once. No claim in the dataset is affected today (0 disagreements). | Keep the reservation until the decision, as the rules say. |
| AMB-P6-02 | Which line codes make a line FAIL (affects approved_amount only after approval). | ASM-P6-04. |
| AMB-P6-03 | How to give every line a quantity without changing amounts. | ASM-P6-02 (divisors of the amount; quantity 1 when none fits after an S5 edit). |
| AMB-P6-04 | DEC-01 for S5 expense edits: the S5 constructions keep their own helpers (lines_fit, split_safe); every result is then checked by the oracle (DEC-P4-02) and by the services-vs-oracle comparison (0 disagreements, tested). Rebuilding each S5 edit guard on the services, as done for leave, would change the expense dataset. | Keep the S5 expense helpers; S4 uses the services. |
| AMB-P6-05 | Cross-claim checks against earlier claims of any outcome, or only claims still holding. | Any outcome (ASM-P6-06), same as the oracle. |

## 11. Phase 7A additions (routing and approval steps), APPROVED 2026-10-28 (AMB-P7A-01..04, DEC-P7A-02 and DEC-P7A-04 accepted)

### 11.1 Assumptions (ASSUMPTION, illustrative synthetic)

| ID | Assumption |
|---|---|
| ASM-P7A-01 | Routing inputs: the routing date is the submission date; the measure is the leave request's whole requested_quantity (all leave years together) or the claim's USD total; the category is the leave type or the claim's primary (highest-amount) category. Same as the oracle. |
| ASM-P7A-02 | Delegation: of several delegations of one approver covering the routing date, the lowest delegation_id is used. A delegate who cannot act is substituted in turn (chain); delegated_from records the first person replaced by a delegate. |
| ASM-P7A-03 | L4 needs exactly one finance controller in the requester's country and L5 exactly one G7 in the requester's country (AMB-P7B-09; the AMB-P7A-01 fallback is removed); two candidates for one role leave the level unresolved (AM-B9: never pick one). |

### 11.2 Decisions

| ID | Decision | Alternatives considered |
|---|---|---|
| DEC-P7A-01 | Routing lives in src/services/approval_routing.py (pure; reads approval_rule rows, no src/reference import). Submission routes when the store supplies a router and validation neither rejects nor returns; the routing code joins the codes and the classification. Both PostgreSQL stores always route (rules, employees, departments, delegations read in the same transaction). In-memory stores route only when given a router, so the generator guards behave exactly as in Phases 5-6 and the dataset is unchanged. | Route in every store (would change generator guard behaviour). |
| DEC-P7A-02 | Migration 0001 builds tables from the current models (DEC-30), so it now drops columns that a later revision adds (LATER_COLUMNS) right after create_all. 0001 is therefore exactly the 0001 schema and 0002 can be downgraded and upgraded on its own (tested). | Rewrite 0001 as frozen explicit DDL (large change to an approved migration). |
| DEC-P7A-03 | Oracle (owner decision on AMB-P6-01): an expense claim keeps its budget reservation unless validation rejects or returns it (a HARD or CORRECTABLE submission code). Measured effect on the dataset: none (ground truth byte-identical); a hand-built oracle test shows the difference. | |
| DEC-P7A-04 | data/validation/detections.csv stays validation findings plus batch detectors; routing codes are not detections. They are recorded as request_exception rows (DB), in the replay's codes() and in both comparisons. Keeps the dataset byte-identical. | Add routing codes to detections.csv (changes the file and the fingerprint). |
| DEC-P7A-05 | Both comparisons compare all codes (routing included), the status after validation and routing, the rule id, the route (level, approver, covered levels, delegated_from) and the steps (exactly the route, in order, only step 1 assigned, when PENDING_APPROVAL; none otherwise). ROUTING_PHASE7 can no longer occur and is printed as 0. | |
| DEC-P7A-06 | At submission the first step is assigned (assigned_at = submission time) and one approval_event ASSIGNED (actor NULL = system, id APE from id_sequence) is written; later steps stay unassigned until the previous one is approved (7B). | No approval_event until Phase 8. |
| DEC-P7A-07 | Not in 7A: approve / reject / return with attempts, idempotency and history, resubmission, process-owner decisions, S6 timing, year-end CARRY_FORWARD rows, S19 and S22 data (all 7B). | |

### 11.3 Ambiguities found in Phase 7A (default APPLIED; please confirm or change)

| ID | Ambiguity | Default applied |
|---|---|---|
| AMB-P7A-01 | Owner decision S19 option (a): L5 = the G7 of the requester's country. The dataset keeps one G7 for all countries until 7B, so most countries have no G7 of their own. | When the requester's country has no G7 and the organisation has exactly one, that G7 is L5 (today's single-CFO model, ASM-014). Two G7s in one country -> unresolved. After the 7B dataset change every country has its own G7 and this fallback never applies. REMOVED in Phase 7B (AMB-P7B-09): routing and oracle use the per-country rule only. |
| AMB-P7A-02 | Escalated requests (SOFT) are routed but have no steps yet. | The route is recorded in calculated_values; steps are created when the process owner sends the request on (7B). |
| AMB-P7A-03 | A delegation whose delegate is the requester: substitution moves the requester up to the delegator, who was already visited. | Level unresolved -> NO_VALID_APPROVAL_PATH (same as the oracle). Alternative: continue with the delegator's manager (needs an oracle change too). |
| AMB-P7A-04 | Writing approval_event ASSIGNED now (Phase 7A) or with the audit work (Phase 8). | Now, for step 1 only (DEC-P7A-06). |

## 12. Phase 7B additions (decisions, resubmission, process owner, S6 timing, carry-forward), APPROVED 2026-10-29 (commit ce59a2a; ASM-P7B-12 accepted)

### 12.1 Assumptions (ASSUMPTION, illustrative synthetic; values in config/*.yaml)

| ID | Assumption |
|---|---|
| ASM-P7B-01 | Guard order at decision time: SELF_APPROVAL, UNAUTHORIZED_APPROVER, DUPLICATE_ACTION, STEP_NOT_PENDING, LEVEL_SKIPPED, EXPIRED_RULE; the first failing guard blocks. docs/05 5.5 lists the guards without an order; DUPLICATE_ACTION comes before STEP_NOT_PENDING so that it can occur at all (an accepted step is no longer pending). |
| ASM-P7B-02 | Decision timing (stage S6, config/generation.yaml decisions): a decision is made at 17:00 UTC on the max(1, delay)-th business day of the deciding person's country after the assignment day; an assignment at or after 17:00 counts from the next day, so every decision is more than 24 hours after its assignment. Delay = keyed draw on the delays stream, key (request id, round, level or PROCESS_OWNER), ranges ASM-024. The as-of instant is midnight UTC at the start of AS_OF_DATE (FrozenClock); a decision after it has not happened. |
| ASM-P7B-03 | Reasons: a reject or return without a reason gives the request decision_reason_code APPROVER_REJECTED / APPROVER_RETURNED. A returning step becomes CANCELLED (decision_at stays NULL, DB CHECK decided_has_timestamp) with an approval_event RETURNED; later pending steps CANCELLED (return) or SKIPPED (reject). A process owner's send-on writes reason PROCESS_OWNER_ACCEPTED, or BUDGET_OVERRIDE when BUDGET_EXCEEDED is among the round's codes, on the status event; the request's decision_reason_code is NULL while PENDING_APPROVAL (ASM-P5-08). In the simulation a process-owner reject or return gives the deciding code (catalogue order). |
| ASM-P7B-04 | "Holds a higher level in the same chain" (docs/05 5.1): for an L1-L3 step, any manager above the step's original approver (delegated_from, else approver); for an L4 step, the requester's L5; for L5 nobody else. |
| ASM-P7B-05 | Year-end carry-forward (BR-LBAL-04), posted at 00:00 UTC on 1 January: CARRY_FORWARD = the previous year's balance at Dec 31 (posted rows plus its full accrual schedule) minus that year's reservations still open then (treated as if approved, as ASM-P5-03 did), and CARRY_FORWARD_EXPIRY = minus the part above the cap; both in the new year's balance, dated 1 January. A negative balance carries only when the policy permits negatives; nothing is posted for zero. The recompute of ASM-P5-03 is removed: without these rows nothing is carried. |
| ASM-P7B-06 | The dataset contains no resubmissions and no cancellations: a request RETURNED_FOR_CORRECTION at as-of stays so (the resubmission service exists and is tested). See AMB-P7B-02. |
| ASM-P7B-07 | An expense resubmission without new lines carries the current round's lines into the new round unchanged (new line numbers, DEC-11). |
| ASM-P7B-08 | In the simulation the process owner who decides is the lowest employee id holding PROCESS_OWNER who is not the requester; the L4 path of docs/05 9.4 is available in the service but not used by the simulation. |
| ASM-P7B-09 | NEGATIVE_BALANCE_UNPERMITTED examines only USAGE that never passed the submission balance check (legacy approvals). A request approved through the workflow was checked at submission against every open reservation, and approval only turns its reservation into usage. |
| ASM-P7B-10 | A process owner's send-on creates steps from the route at the round's submission date (AMB-P7A-02). An approver whose employment ends before the decision date no longer decides: the step is reassigned (AMB-P7B-11, superseding AMB-P7B-06; ASM-P7B-12); validation check V-WF-05 checks it. |
| ASM-P7B-12 | ASSUMPTION (illustrative synthetic), AMB-P7B-11 timing: the reassignment happens at 00:00 UTC on the day after the approver's employment end, or at the step's assignment when that is later; the new approver decides at 17:00 UTC on the max(1, delay)-th business day after the reassignment (ASM-P7B-02 rule), delay keyed (request id, round, level, new approver) on the delays stream, so no other draw moves. Reassignment and decision after the as-of instant do not happen. REASSIGNED event: actor NULL, reason_code APPROVER_EMPLOYMENT_ENDED, comment "old -> new". |
| ASM-P7B-11 | S19 option (a) in data (AMB-P7B-09): stage S1, after manager assignment, promotes in each country without a G7 the lowest-id G6 that is ACTIVE, has no employment end and started on or before the window start; it becomes G7 with manager NULL and job title "Chief Financial Officer", keeping its department, head flag and reports. No random draws. At seed 20261022 / 400: EMP-000031 (US) and EMP-000181 (GB); EMP-000314 (IN) unchanged. |

### 12.2 Decisions

| ID | Decision | Alternatives considered |
|---|---|---|
| DEC-P7B-01 | src/services/approval_service.py holds decide_step and decide_escalated over a WorkflowStore protocol; request-type rules stay in leave_request_service (approval_postings) and expense_service (approved_amount_of, release_postings, override_postings). Four stores implement it: the two in-memory stores (shared InMemoryWorkflow) and the two PostgreSQL stores (shared SqlWorkflow in src/repositories/base.py). No src/reference import. | One service per request type. |
| DEC-P7B-02 | Legacy approvals carry decision_reason_code LEGACY_APPROVAL (set by S5, a raw input). The replays and the oracle read the raw-input view: DRAFT, legacy APPROVED, everything else a submission at created_at, whatever status S6 wrote. S6 writes only outputs, so the comparisons can run on the exported dataset. | Detect legacy rows by the absence of status events (an engine output). |
| DEC-P7B-03 | Stage S6 = the replays with routing and a DecisionTiming (DEC-01). It writes workflow_status, exception_class, decision_reason_code, the submission outputs and approved_amount, and seven tables that were empty before: cost_center_transaction, approval_step, approval_event, approval_attempt, request_status_event, request_exception, idempotency_record; the leave ledger is renumbered with USAGE and year-end rows and the snapshots recomputed. Ids follow time. detections.csv comes from the S6 replays (byte-identical to Phase 7A). | Keep the dataset at SUBMITTED. |
| DEC-P7B-04 | The oracle has its own timing model (numpy keyed draws re-implemented, same rule as ASM-P7B-02, process owner from user_role): final_status is the status at as-of, eventual_status keeps the eventual outcome. A claim's reservation is released at the process owner's reject or return instant for claims submitted at or after it. | Eventual outcome only (cannot check timing). |
| DEC-P7B-05 | expected_approved_amount and expected_reimbursement_eligibility follow the status at as-of: set only for claims APPROVED at as-of. | Eventual values. |
| DEC-P7B-06 | Not in 7B: reimbursement rows at final approval and reimbursement_attempt (Phase 8), audit_event rows (Phase 8), the ESCALATE action of a step approver, cancellation, attempt scenarios S11/S12/S18 in the dataset. | |
| DEC-P7B-07 | Both comparisons also compare the status at as-of: services' S6 simulation = oracle = dataset, and the approved amount stored at approval. Seed and as-of come from data/manifest.json. | |
| DEC-P7B-09 | S19 plants are split evenly over the G7s in employee-id order, the lowest ids taking the remainder (4 + 4 at 400 employees: EMP-000031 2 + 2, EMP-000181 1 + 1, EMP-000314 1 + 1). | Round-robin per plant; all on one G7. |
| DEC-P7B-08 | A blocked attempt completes its idempotency key (docs/06 8.2 step 5); the same derived key with a different body raises IdempotencyConflict, so a retry after a block needs a new client key. | Let a blocked key be reused. |

### 12.3 Ambiguities found in Phase 7B (default APPLIED unless stated; please confirm or change)

| ID | Ambiguity | Default |
|---|---|---|
| AMB-P7B-01 | The proposed S22 rule ("17:00 on a business day at least one business day after assignment") still allows a decision 23 hours after an 18:00 assignment, which could decide an S22 partner first. | Count from the next day when assigned at or after 17:00 (ASM-P7B-02): every decision is more than 24 hours after assignment. Applied. |
| AMB-P7B-02 | ASM-025 (50 percent of returned requests resubmitted) and ASM-040 (about 2 percent cancelled) in the dataset. | Not simulated in 7B (ASM-P7B-06); proposed for Phase 8 together with S18 (repeated submission). Applied. |
| AMB-P7B-03 | S11 / S12 (self-approval and unauthorised attempt rows) could be planted now that attempts exist. | Plant in Phase 8 with S13 / S18 (scenario actual_count stays NULL). Applied. |
| AMB-P7B-04 | docs/06 8.2 creates the reimbursement in the final-approval transaction, but reimbursement is Phase 8. | Phase 8; approved claims carry approved_amount now, no reimbursement row yet. Applied. |
| AMB-P7B-05 | Who decides escalations in the simulation. | ASM-P7B-08. Applied. |
| AMB-P7B-06 | Approver's employment ends after assignment, before the decision. | SUPERSEDED by AMB-P7B-11 (owner 2026-10-29). Was: the assigned approver still decides. Reason: a decision by someone no longer employed is invalid (V-WF-05 found one after the S19 redraw), and reusing the routing substitution keeps one rule for "approver cannot act". |
| AMB-P7B-07 | expected_approved_amount / eligibility at as-of or eventual. | At as-of (DEC-P7B-05). Applied. |
| AMB-P7B-08 | Form of the year-end rows: full balance plus a negative expiry, or the capped amount only. | Full balance + expiry, both visible in the ledger (ASM-P7B-05). Applied. |
| AMB-P7B-09 | S19: one G7 per country. | Owner decision 2026-10-28: option A (promote, ASM-P7B-11, DEC-P7B-09), accepting that S3 / S4 draws change. Condition 3 as amended by the owner: every planned count met and every planted actual unchanged; natural counts may move. Measured at seed 20261022 / 400: S04 actual 60 -> 62 (minimum 40), S14 actual 790 -> 788 (minimum 150), natural split-claim labels 2 -> 0 (the pair no longer occurs; not forced back); every planted count unchanged; no unplanted NO_VALID_APPROVAL_PATH. Applied. |
| AMB-P7B-10 | A country with no ACTIVE G6 employed for the whole window (small scales, e.g. starter 40 employees at seed 20261023) cannot get a G7. | That country keeps no G7: the generator prints a WARNING and records it in manifest.json under countries_without_g7; requests needing L5 there have no valid path. Not reached at the full scale. Alternative: promote from G5. Applied; please confirm. |
| AMB-P7B-11 | V-WF-05 (new, AMB-P7B-06) found 1 decision after the approver's employment end: APR-EXP-2025-000483-02, decided 2025-12-17 17:00 UTC by EMP-000190, employment ended 2025-12-14 (appeared with the S19 redraw). | Owner decision 2026-10-29: option (1), resolved in Phase 7B, supersedes AMB-P7B-06. At decision timing, a step whose approver's employment ended before the decision date is reassigned with the routing substitution (delegate, else next person up), recorded as REASSIGNED (original assignment and ASSIGNED event kept); the new assignee decides under the same guards; the oracle mirrors it independently (ASM-P7B-12, docs/05 5.4 and 9.5, docs/06 3). Result at seed 20261022 / 400: the step is reassigned at 2025-12-15 17:00 UTC (its assignment; EMP-000190 had already left) to EMP-000126 (EMP-000190's manager), who approves 2025-12-26 17:00 UTC; V-WF-05 PASS. Counts: approval_event 5059 -> 5060 (+1 REASSIGNED); every other table count, every planted and natural scenario count, ground truth and every status at as-of unchanged. Applied. |

### 12.4 Notes and lessons (Phase 7B, S19)

- Lesson: G7s are excluded from the request-requester pool in S3 / S4 (a G7 requester has no approval path; that case is only planted as S19). Promoting people to G7 therefore changes the pools and every later draw of S3 / S4, so a structural change to who is G7 can never be "master data only".
- Cosmetic synthetic-data quirk (owner 2026-10-28, keep): EMP-000181 (GB) is head of DEPT-05 and, after the promotion, has the job title "Chief Financial Officer". Routing is unaffected: one person resolved for several levels gets one step with covered_levels (in the dataset EMP-000181 holds L1, L2, L1+L2 in one step, and L3 steps; services = oracle on every record).
- Before / after the S19 change (seed 20261022 / 400): employees G6 24 -> 22, G7 1 -> 3; approval_step 2548 -> 2547 (APPROVED 2506 -> 2518, PENDING 42 -> 29); leave at as-of APPROVED 755 -> 756, DRAFT 8 -> 7, ESCALATED 5 -> 6, PENDING 12 -> 11 (REJECTED 12, RETURNED 8 unchanged); expense APPROVED 893 -> 902, ESCALATED 19 -> 17, PENDING 20 -> 12, RETURNED 33 -> 34 (DRAFT 8, REJECTED 27 unchanged).

## 13. Phase 8 additions (reimbursement and audit), split 8A / 8B; CLOSED 2026-10-29 (8A, 8B-1 approved; 8B-2 deferred)

Split (2026-10-29): 8A = services, tests and docs (the dataset is unchanged, fingerprint 28ece855...); 8B = the
dataset part, made only after the owner's OK on the plan in 13.4.

### 13.1 Assumptions (ASSUMPTION, illustrative synthetic)

| ID | Assumption |
|---|---|
| ASM-P8-01 | The reimbursement created inside the final-approval transaction (docs/06 8.2 step 6) has actor SYSTEM on its CREATE attempt and audit row (the approver approved the claim; the system created the payment record). It has no idempotency record of its own: the approve action's key and the partial unique index cover it (docs/06 8.4 normal path). |
| ASM-P8-02 | The idempotency scope of the SYSTEM actor (payment runs) is the lowest-id application_user holding SYSTEM_ADMIN (idempotency_record.actor_user_id is NOT NULL and references a user). |
| ASM-P8-03 | At COMPLETED, ACTUAL = approved_amount is posted on the budget the reservation was posted on, and RELEASE = what that reservation still holds beyond it (reason REIMBURSEMENT_COMPLETED). Several open reservations (possible after a resubmission in another budget year) are used in budget-id order. committed_amount -= ACTUAL and actual_amount += ACTUAL, so V-ARITH-08 keeps holding. |
| ASM-P8-04 | The schema requires a reason on every reimbursement_attempt that is not ACCEPTED (CHECK non_accepted_has_reason), so a COMPLETED attempt carries reason PAYMENT_COMPLETED; a PAYMENT_FAILED attempt carries the failure code (PAYMENT_FAILED in the simulation). Found by the DB test. |
| ASM-P8-05 | A cancelled request gets decision_reason_code REQUESTER_CANCELLED unless a reason is given. Its pending steps become CANCELLED (approval_event CANCELLED, actor NULL); an expense claim RELEASEs its open reservation (BR-BUD-04). |
| ASM-P8-06 | audit_event content: entity_type = table name; actor_id = employee id, or SYSTEM when the source row has actor NULL; one row per request transition (same states, reason and calculated_values as the status event), one per approval attempt on its step (blocked: previous = new state, reason = guard), one per step a decision changes (SKIPPED / CANCELLED), one per reassignment (calculated_values {from, to}), one per idempotent replay (reason IDEMPOTENT_REPLAY, states NULL), one per reimbursement creation / status change / blocked attempt, one per processing_failure (reason = error code). An accepted process-owner decision is audited by its request transition row (no second row). |

### 13.2 Decisions

| ID | Decision | Alternatives considered |
|---|---|---|
| DEC-P8-01 | src/services/reimbursement_service.py (creation at final approval, manual create, start / settle payment, cancel) over a ReimbursementStore protocol implemented by InMemoryExpenseStore (mixin InMemoryReimbursements) and SqlExpenseStore. The reimbursement state machine is data in lifecycle.REIMBURSEMENT_TRANSITIONS; anything else raises IllegalTransition. | A separate reimbursement store. |
| DEC-P8-02 | src/services/audit_service.py builds audit rows; the services attach them to their results and the stores write them in the same transaction (in memory: appended; PostgreSQL: AUD ids from id_sequence). Idempotency helpers moved to src/services/idempotency.py (approval_service re-exports them) so the two services do not import each other. | Database triggers writing audit rows (they cannot see actor, rule or reason). |
| DEC-P8-03 | Who may call the manual reimbursement paths (create, cancel: SYSTEM_ADMIN) is enforced by the API layer in Phase 9, like every other authentication check; the services record the actor. | A role check inside the service with a new blocked reason. |
| DEC-P8-04 | Cancellation (approval_service.cancel_request) is not an approval action: no approval_attempt, no idempotency record (a repeat finds CANCELLED, which is terminal, so it raises IllegalTransition). Only the requester may cancel. | An idempotency operation CANCEL (needs a migration of the enum CHECK). |
| DEC-P8-05 | A violation of uq_reimbursement_active_per_claim on insert (a race) is caught in a savepoint and recorded as a BLOCKED DUPLICATE_REIMBURSEMENT attempt in the same transaction (docs/06 8.4 step 5 says "in a new transaction"; a savepoint gives the same result without losing the caller's transaction). | A second transaction. |
| DEC-P8-06 | repositories/base.run_recording_failure(engine, ...): runs a use case in one transaction; a technical error (SQLAlchemy operational / interface / internal errors, timeouts, connection errors, RuntimeError subclasses such as LedgerMismatch and PolicyConfigurationError) rolls it back, then a processing_failure row and its audit row are written in a second transaction with the same correlation id and the error is raised again. Business refusals pass through. Used by the API in Phase 9. | |
| DEC-P8-07 | Audit hash chain (DEC-20, stretch): NOT done in 8A. It needs a migration (prev_hash, row_hash), a serialised insert order and a validator; proposed as the last, optional item of 8B. | |
| DEC-P8-08 | 8A leaves the dataset unchanged: the in-memory stores now also build reimbursement and audit rows during S6, but stage S6 does not export them yet (verified: fingerprint 28ece855..., git shows no change under data/). | |

### 13.3 Ambiguities found in Phase 8A (default APPLIED unless stated; please confirm or change)

| ID | Ambiguity | Default |
|---|---|---|
| AMB-P8-01 | BR-RMB-01 requires approved_amount > 0, but docs/06 lists no reason code for a zero amount. | Reason ZERO_APPROVED_AMOUNT (checked after CLAIM_NOT_APPROVED). Applied. |
| AMB-P8-02 | Cancelling a reimbursement (ELIGIBLE / FAILED -> CANCELLED): the budget effect is not defined. | No posting: the claim stays APPROVED and its reservation stays committed until a new reimbursement completes or an admin corrects it. Applied. |
| AMB-P8-03 | docs/06 7.2 also audits every ledger posting and master-data change. | Not in 8A: ledger rows already carry correlation ids and are append-only; master-data changes arrive with the API (Phase 9). Proposed: ledger-posting audit rows in 8B only if the owner wants them (adds about 18,000 rows). |
| AMB-P8-04 | docs/06 8.1 step 1 says submit writes an idempotency_record, but no store writes one for a first submission (only for a resubmission). S18 (repeated submission) needs it. | Not changed in 8A. Proposed for 8B: SUBMIT idempotency rows on every submission (about +1,785 rows) so that S18 can be planted; or leave S18 for Phase 9 (API). Owner to choose. |
| AMB-P8-05 | A processing_failure is OPEN; whether a successful retry sets it to RESOLVED. | Not changed (rows stay OPEN; resolution is an admin action). Applied; please confirm. |

### 13.4 Phase 8B dataset plan (NOT applied; waiting for the owner's OK)

Baseline today (commit ce59a2a, seed 20261022): volumes 400 employees / 6 leave policies / 800 leave requests /
1,000 expense claims; fingerprint 28ece8554f97a48e6323ef032ff926919596a80ff5f2b5da3ebe2fc9edf42dfa. At as-of:
leave APPROVED 756, PENDING_APPROVAL 11, ESCALATED 6, REJECTED 12, RETURNED 8, DRAFT 7; expense APPROVED 902,
PENDING_APPROVAL 12, ESCALATED 17, REJECTED 27, RETURNED 34, DRAFT 8. Every RETURNED request is a planted record:
S23 8 (leave), S05 10, S26 8, S06a 8, S10 8 (expense). Row counts: approval_step 2547, approval_event 5060,
approval_attempt 2563, request_status_event 6962, request_exception 130, idempotency_record 2563,
cost_center_transaction 1041, expense_line 3224, receipt 2941, leave_balance_transaction 15512; reimbursement,
reimbursement_attempt, audit_event, processing_failure 0. Ground truth 1800 / 1055 / 40 / 41.

What changes (stage S6 continued, in time order, through the services):
1. S7 reimbursements: the row at final approval for every claim APPROVED at as-of (~902). Payment run on the
   `payments` stream (reserved in the stream list and unused so far, so no other draw moves): PROCESSING and
   COMPLETED at 17:00 on the 1..5th business day after approval (ASM-035); 5% of first attempts fail (keyed draw)
   -> FAILED + processing_failure (S25), retry 2 business days later, succeeds. Nothing after as-of.
2. S13 (8): a second, manual CREATE on 8 reimbursed claims -> BLOCKED DUPLICATE_REIMBURSEMENT.
3. S11 (8) / S12 (8): BLOCKED attempts on pending steps of otherwise normal routed requests (4 leave + 4 expense
   each), one hour after assignment: by the requester (SELF_APPROVAL) and by an employee outside the chain
   (UNAUTHORIZED_APPROVER, the lowest-id active employee of another department). The request is not changed.
4. Resubmissions (ASM-025): each RETURNED request is resubmitted with the issue fixed when a keyed draw on a new
   stream `resubmissions` (appended) is < 0.5, after 1..10 business days: receipt added (S05), currency fixed (S26),
   duplicate line removed (S06a), cost center set (S10), certificate flagged (S23). Expected ~21 of 42.
5. Cancellations (ASM-040): each submitted request that is neither planted nor a boundary record gets a keyed draw
   on a new stream `cancellations` (appended); with probability 0.02 the requester cancels at 12:00 UTC on the next
   business day after submission if it is still PENDING_APPROVAL or RETURNED (before any 17:00 decision).
   Expected ~16 leave and ~20 expense.
6. S8 audit_event for every operation above and every existing one (submissions, decisions, reassignment).
7. Ground truth: expected_final_status / approved amount / reimbursement eligibility at as-of follow the new
   outcomes; S11 / S12 / S13 / S25 get labels and actual counts; labels of resubmitted records stay on round 1
   (detected at round 1); new expected field: reimbursement status at as-of. The oracle gets its own payment,
   resubmission and cancellation model (no src/services import) and must agree on every record.
8. V-ARITH-04 and V-WF-03 then run on real reimbursement rows (today NOT APPLICABLE).

What stays: volumes 400 / 6 / 800 / 1,000 (no new requests; resubmission keeps ids); all master data, policies,
users, rules, holidays, fx; every raw input of S3 / S4 / S5 (new draws come from `payments` and two appended
streams only); every planted count of Groups A and B and every boundary count (S05, S06a, S10, S23, S26 keep their
records and labels; their final status may change).

Expected counts (estimates; the real numbers will be reported): reimbursement ~900; reimbursement_attempt ~2,800
(CREATE, PROCESS, COMPLETED per paid claim, +3 per failure, +8 S13); processing_failure ~45 (= S25);
audit_event ~13,000; cost_center_transaction 1041 -> ~1,970 (ACTUAL per paid claim, RELEASE for the 8 capped S07a
claims, resubmission and cancellation postings); approval_attempt +16; idempotency_record +~1,820 (PROCESS_PAYMENT
per run, RESUBMIT, S13); request_status_event +~100; expense_line and receipt + a few (corrected rounds).
Status at as-of: CANCELLED ~16 leave / ~20 expense (mostly taken from APPROVED), RETURNED 8 -> ~4 and 34 -> ~17.
Natural counts that may move: S04 / S14 (only if a cancelled request is one of them), natural BUDGET_EXCEEDED (1),
because ACTUAL + RELEASE and cancellations change the available budget seen by later claims.

Fingerprint effect: changes. New files: reimbursement, reimbursement_attempt, processing_failure, audit_event
(csv + json each). Changed: expense_claim, expense_line, receipt, leave_request, leave_balance(_transaction),
cost_center_transaction, cost_center_budget, approval_*, request_*, idempotency_record, ground truth, seed.sql,
validation report; detections.csv only if a cancelled claim was part of a detection. Unchanged: every master,
policy, user, rule and calendar file.
Questions for the owner: (a) the plan as a whole; (b) cancellation selection and timing (item 5); (c) S18 / SUBMIT
idempotency rows (AMB-P8-04); (d) ledger-posting audit rows (AMB-P8-03); (e) hash chain at the end of 8B (DEC-P8-07).

Owner decisions 2026-10-29: plan approved, with every planted record keeping its label and round-1 expected outcome
and per-round checks at 0 DISAGREE; cancellation approved, never on planted or boundary records; S18 SUBMIT
idempotency rows in 8B; AMB-P8-01..05 defaults accepted; 8B split into 8B-1 (items 1, 2, 6, 8: reimbursements,
payments, S13, S25, audit export) and 8B-2 (items 3, 4, 5, S18, per-round ground truth with migration 0003).

### 13.5 Phase 8B-1 additions (applied)

| ID | Assumption / decision |
|---|---|
| DEC-P8-09 | Ledger postings are NOT audited (owner 2026-10-29, AMB-P8-03): leave_balance_transaction and cost_center_transaction are already append-only tables (trigger + grants) with correlation ids, so an audit row per posting would duplicate them. |
| DEC-P8-10 | Audit hash chain (DEC-20, DEC-P8-07) DEFERRED: optional, to be revisited in Phase 12. Triggers and role grants remain the immutability mechanism. |
| ASM-P8B-01 | ASSUMPTION (illustrative synthetic), payment run (BR-RMB-03, ASM-035; config/generation.yaml payments): start and settle at 17:00 UTC on the n-th business day of the claimant's country counted from the day after the final approval, n = keyed draw (claim id, "DELAY") in [1, 5] on the reserved `payments` stream; the first attempt fails when the keyed draw (claim id, "FAIL") in [0, 99] is < 5; the retry is 2 business days later and succeeds. Payment reference PAY-<RMB id>-<attempt>. Runs after the as-of instant do not happen. No existing draw moves (the stream was unused). |
| ASM-P8B-02 | ASSUMPTION, S13: the planted second CREATE is made by SYSTEM (manual path, key SHA-256(SYSTEM, CREATE_REIMBURSEMENT, claim)) one hour after the reimbursement was created, on the 8 lowest-id claims approved at as-of that carry no other planted label and are no boundary record (selected in S9 from the oracle; S6 receives the ids as a plant list). Result: BLOCKED DUPLICATE_REIMBURSEMENT. |
| ASM-P8B-03 | S25 labels (scenario S25, issue PROCESSING_FAILURE, record = the claim) are not planted: they come from the designated stochastic payments stream. The oracle derives them with its own keyed draws; S9 counts them as the S25 actual (planned 0, count not fixed in advance). |
| DEC-P8-11 | The oracle models the payment run itself (keyed draws re-implemented) and its budget: a COMPLETED payment of a capped claim releases total - approved_amount at the completion instant (BR-BUD-05). The expense comparison also compares each claim's active reimbursement (status at as-of, amount, currency) between services, oracle and dataset. |

Result at seed 20261022 / 400 (before = commit d9eeca9, after = 8B-1):
- Scenario counts: every planted and boundary count unchanged; S13 actual none -> 8 (planned 8); S25 actual none
  -> 37 (planned 0); natural counts unchanged: S04 62, S14 788, natural BUDGET_EXCEEDED 1 (the 8 capped-claim
  releases did not move any later budget check).
- New tables: reimbursement 902 (at as-of COMPLETED 893, ELIGIBLE 9); reimbursement_attempt 2,770 (ACCEPTED 1,832,
  COMPLETED 893, PAYMENT_FAILED 37, BLOCKED 8); processing_failure 37; audit_event 12,288.
- Changed counts: idempotency_record 2,563 -> 3,501 (+930 PROCESS_PAYMENT, +8 CREATE_REIMBURSEMENT);
  cost_center_transaction 1,041 -> 1,942 (+893 ACTUAL, +8 RELEASE at completion of the 8 capped S07a claims).
  Labels 1,055 -> 1,100 (+8 S13 planted, +37 S25). Every other table count and every status at as-of unchanged.

### 13.6 Phase 8 closure (owner 2026-10-29)

8A accepted (d9eeca9); 8B-1 APPROVED (6f1b4e1); AMB-P8-01..05 defaults accepted. 8B-2 DEFERRED to future work:
plan items 3, 4, 5 of 13.4 (S11 / S12 plants, resubmissions, cancellations never on planted or boundary records),
S18 SUBMIT idempotency rows (AMB-P8-04) and migration 0005 (was 0003; renumbered, 15.3 and 16)
ground_truth.record_round_expectation (record, round,
expected codes, expected status after validation). Until then the dataset has no resubmission, no cancellation and
no S11 / S12 / S18 rows (actual counts NULL).

## 14. Phase 9 scope decisions (owner 2026-10-29; implemented in Phase 9, see 14.1-14.3)

| ID | Decision |
|---|---|
| DEC-29 (revised) | Groq explanation layer: one endpoint GET /requests/{id}/explanation returns a plain-language explanation of what happened to a leave request or expense claim. The LLM receives a small synthetic fact set only: request type, status, exception codes, reason codes, approval steps (level, status, decision time), amount and currency, plus the template text; never names or emails. Replaces "only the template text and the codes". |
| DEC-P9-01 | The LLM never affects any decision, status, amount or routing; it only explains. The endpoint reads only the request's own operational rows (request, steps, exceptions, status events) through the services layer, never ground truth; tests/test_ground_truth_isolation.py covers the new module. |
| DEC-P9-02 | Output check kept: the LLM text must contain every exception code, rule id and amount of the facts and must not contain "fraud" or "misconduct"; otherwise the template text is returned. |
| DEC-P9-03 | Deterministic template fallback, flagged source "template", when LLM_EXPLANATIONS_ENABLED is off, GROQ_API_KEY is empty, or the call fails, times out or hits a rate limit; never an error for the user and never a blocked decision. The response carries source "llm" or "template". |
| DEC-P9-04 | The explanation is never stored, exported, checksummed or audited (no audit row, not even "served"). |
| DEC-P9-05 | GROQ_API_KEY, GROQ_MODEL and LLM_EXPLANATIONS_ENABLED are read from .env (.env.example keeps empty placeholders; the key is never printed). The default model is taken from Groq's current documentation at the start of Phase 9 (a free-tier model), with the documented free-tier limits recorded here; this closes the "Groq limits unverified" item (ASM-051, ASM-052). Tests mock the HTTP call: success, fallback on failure, no key, and decisions identical with and without the explanation. Time box about 15 minutes; one line in docs/03 and docs/09. |

### 14.1 Groq model and limits (checked 2026-10-29; closes ASM-051 / ASM-052)

- https://console.groq.com/docs/deprecations: llama-3.1-8b-instant and llama-3.3-70b-versatile (the ASM-051 names) were
  shut down on 2026-08-16 for free and developer tiers; Groq names openai/gpt-oss-20b as the replacement for the 8B model.
- https://console.groq.com/docs/models: openai/gpt-oss-20b is a production model. Default in config/llm.yaml.
- https://console.groq.com/docs/rate-limits: openai/gpt-oss-20b 30 requests/min, 1,000 requests/day, 8,000 tokens/min,
  200,000 tokens/day. Caveat: the page has Free / Developer tabs and its text says the table shows "base limits for the
  Developer plan"; the exact limits of an organisation are on its console limits page. On a limit: HTTP 429 with
  retry-after. Recorded in config/llm.yaml (documented_limits); the code does not enforce them (no rate limiting, as
  scoped).

### 14.2 Phase 9 decisions and assumptions (ASSUMPTION, illustrative synthetic)

| ID | Decision |
|---|---|
| DEC-P9-06 | API structure: src/api/core.py (context, transactions, JWT, errors), routes.py (operational), evaluation_routes.py (the only API module importing src/evaluation), main.py (create_app factory). Started with `uvicorn src.api.main:create_app --factory`. |
| DEC-P9-07 | Operations connect as lea_app, GET /evaluation as lea_evaluation (DATABASE_URL with the role's user and password from .env). lea_analytics_ro is not used (no views yet; Phase 10). |
| DEC-P9-08 | Submission = insert a DRAFT row (id from id_sequence, LVE-/EXP-<year>-nnnnnn of the receipt year) and call submit_leave / submit_expense in the same transaction. Claim country, currency and default cost center come from the employee; lines carry no receipt (receipt upload is out of scope), so lines above the receipt threshold return MISSING_RECEIPT as the rules say. |
| DEC-P9-09 | Business time of an API call = request receipt time from SystemClock (src/common/clock.py says so); tests inject a fixed clock. JWT expiry also uses the wall clock (8 h, JWT_EXPIRES_MINUTES). |
| DEC-P9-10 | Idempotency-Key header is required on decisions and on reimbursement creation; the stored key is sha256("api", client key), scoped per user as before. Same key and body: replay (200, replayed true, no new attempt); same key, other body: 409 IDEMPOTENCY_CONFLICT. |
| DEC-P9-11 | A BLOCKED attempt is committed (audit trail) and then answered as an error: 403 for SELF_APPROVAL / UNAUTHORIZED_APPROVER, 409 for other guards (e.g. DUPLICATE_REIMBURSEMENT); details carry outcome and the current workflow_status. |
| DEC-P9-12 | Errors always {"error": {"code", "message", "details"}}; 401 NOT_AUTHENTICATED / INVALID_TOKEN / TOKEN_EXPIRED / INVALID_CREDENTIALS, 403 FORBIDDEN_ROLE, 404 NOT_FOUND, 409 IDEMPOTENCY_CONFLICT / DECISION_REFUSED / ILLEGAL_TRANSITION / CONSTRAINT_VIOLATION, 422 VALIDATION_ERROR / INVALID_INPUT / UNKNOWN_POLICY, 500 INTERNAL_ERROR (no internals). Money and quantities are JSON strings. |
| DEC-P9-13 | Roles: submit = REQUESTER; step decisions = APPROVER or PROCESS_OWNER (the service then checks authority per step); escalation = PROCESS_OWNER or APPROVER (L4 for BUDGET_EXCEEDED); create reimbursement = OPS_ANALYST, PROCESS_OWNER or SYSTEM_ADMIN; evaluation = OPS_ANALYST or SYSTEM_ADMIN. Reads: a user holding only REQUESTER sees only their own requests (others 404); APPROVER, PROCESS_OWNER, OPS_ANALYST and SYSTEM_ADMIN see all. Roles are read from user_role at login and carried in the token. |
| DEC-P9-14 | Correlation ids of API calls are uuid5 of (user, operation, target, receipt time, key): deterministic, no random ids. |
| DEC-P9-15 | GET /evaluation returns src/evaluation/summary.py: the AGREE / DISAGREE counts of the two comparison CSVs (it does not re-run the oracle) and, through lea_evaluation, how many ground-truth records' expected status at as-of equals the stored ops status. The latter compares the CURRENT status, so API changes after the load show as differences. |
| DEC-P9-16 | Explanation: no in-memory cache (ASM-053 mentioned one; nothing is stored at all, simpler); the fallback reason (disabled, no_api_key, timeout, rate_limited, call_failed, output_check_failed) is returned next to the text. |

### 14.3 Ambiguities found in Phase 9 (default APPLIED; please confirm or change)

| ID | Question | Default applied |
|---|---|---|
| AMB-P9-01 | Should first submissions accept a client Idempotency-Key (the services only record RESUBMIT keys)? | No; submissions are not idempotent through the API yet. |
| AMB-P9-02 | Should a token be re-checked against user_role / is_active on every call? | No; roles from login are trusted until expiry (8 h). |
| AMB-P9-03 | Groq limits: the docs label the table ambiguously (Free vs Developer). | Recorded both the figures and the caveat (14.1); verify on the console limits page. |

### 14.4 Phase 9 approval (owner 2026-10-29)

APPROVED PHASE 9 (commit 90c730a). AMB-P9-01 and AMB-P9-02 accepted as applied and recorded as known limitations in
README.md (first submissions are not idempotent through the API; a token's roles are trusted until it expires).
Groq default model openai/gpt-oss-20b accepted. AMB-P9-03 (Free vs Developer limits label) stays open: verify on the
Groq console limits page.

## 15. Phase 10: Streamlit dashboard

### 15.1 Phase 10 decisions and assumptions (ASSUMPTION, illustrative synthetic)

| ID | Decision |
|---|---|
| DEC-P10-01 | Data paths (docs/03 7.1, AM-F3): aggregates from three read-only views (ops.v_request, ops.v_request_exception, ops.v_reimbursement; migration 0003_analytics_views) as lea_analytics_ro, which gets SELECT on these views only; one request's detail, the explanation, the detections and the evaluation through the API with the user's JWT. The dashboard never connects as lea_app or lea_evaluation. |
| DEC-P10-02 | lea_app gets no rights on the views (REVOKE ALL in the migration): the default privileges would grant it write rights, and a simple view is updatable through its owner's table rights. |
| DEC-P10-03 | Amounts are summed exactly (Decimal) per currency; the only cross-currency figure is the sum of the stored total_amount_usd. No conversion is done in the dashboard. |
| DEC-P10-04 | GET /evaluation also returns M1-M3 (from validation_report.json) and detection results: detections = (record, code) from request_exception (any round), detections.csv, BLOCKED DUPLICATE_REIMBURSEMENT attempts and reimbursement processing_failure rows (docs/08 section 1); positives = anomaly_label with expected_detection = DETECT; TP / FP / FN, precision, recall overall and per code. A preliminary M6-M8; the full report stays in Phase 11. Dev dataset: 226 TP, 0 FP, 0 FN. |
| DEC-P10-05 | New GET /detections (PROCESS_OWNER, OPS_ANALYST, SYSTEM_ADMIN): the detector output data/validation/detections.csv (operational system output, not ground truth) with exception_class and severity from the catalogue. Batch-detector rows exist only in that file, not in the database. |
| DEC-P10-06 | Dashboard access: APPROVER, PROCESS_OWNER, OPS_ANALYST, SYSTEM_ADMIN (the API's read-all roles). A requester-only user is refused, because the analytics views have no per-user filter. Evaluation: analysts and admins (enforced by the API). |
| DEC-P10-07 | streamlit==1.50.0 and pandas==2.3.3 pinned; numpy stays 2.2.6 (dataset checksums unchanged). |
| DEC-P10-08 | The AppTest smoke test runs on lea_dev read-only: the real API context in-process (TestClient), LLM explanations forced off, a synthetic analyst (USR-000010) from data/processed/dev_credentials.csv. Login and GET routes write nothing. It skips when lea_dev, migration 0003 or the passwords are missing. |

### 15.2 Ambiguities found in Phase 10 (default APPLIED; please confirm or change)

| ID | Question | Default applied |
|---|---|---|
| AMB-P10-01 | "Class (hard / correctable / soft)": in the schema HARD / CORRECTABLE / SOFT / INFO is the SEVERITY of an exception code; exception_class (POLICY_VIOLATION, SUSPICIOUS_PATTERN, ...) is a separate dimension. | The Exceptions view shows both: counts by severity, by code with class and severity, and requests by exception_class. |
| AMB-P10-02 | GET /evaluation did not return M1-M3 or detection results. | Extended src/evaluation/summary.py (DEC-P10-04); attempt and failure rows count as detections as docs/08 section 1 says. |
| AMB-P10-03 | Migration number: 0003 was earmarked for the deferred 8B-2 ground_truth.record_round_expectation (13.4). | 0003 = analytics views; the deferred migration becomes 0004 when 8B-2 is scheduled. |
| AMB-P10-04 | Suspicious-pattern detections: exception_class SUSPICIOUS_PATTERN only, or every detector row? | SUSPICIOUS_PATTERN only (duplicate receipts, split claims); every code is counted in "By exception code". |

### 15.3 Phase 10 approval (owner 2026-10-29)

APPROVED PHASE 10 (commit 62e065d). AMB-P10-01..04 accepted as applied. Note on AMB-P10-03: the completion pass
adds migration 0004 (analytics views 2), so the deferred 8B-2 migration (ground_truth.record_round_expectation)
becomes 0005.

## 16. Completion pass against the spec (after Phase 10)

### 16.1 Decisions and assumptions (ASSUMPTION, illustrative synthetic)

| ID | Decision |
|---|---|
| DEC-CP-01 | New read-only API routes (src/api/read_routes.py), JWT + role, limit / offset (max 200; audit history 1000): GET /employees (APPROVER, PROCESS_OWNER, OPS_ANALYST, SYSTEM_ADMIN; organisation fields only, full_name / email / employment dates for SYSTEM_ADMIN only), /leave-policies and /expense-policies (any logged-in user), /leave-balances and /expense-lines (a requester sees only their own; staff roles anyone's; lines without merchant text), /approval-queue (assigned PENDING steps; an approver sees only their own queue, analysts any), /requests/{id}/audit-history and /requests/{id}/investigation (PROCESS_OWNER, OPS_ANALYST, SYSTEM_ADMIN), /dashboard/metrics (staff roles). |
| DEC-CP-02 | Migration 0004_analytics_views_2: seven more read-only views for lea_analytics_ro (v_employee, v_request_dimension, v_expense_line, v_approval_step, v_approval_attempt, v_reimbursement_attempt, v_processing_failure); no names, e-mail, merchant text or error messages; lea_app gets nothing. The deferred 8B-2 migration becomes 0005. |
| DEC-CP-03 | "High-priority issues" = distinct requests ESCALATED_FOR_REVIEW or with a HARD exception code in their current round, plus OPEN reimbursement processing_failure rows. Same definition in the dashboard Overview and GET /dashboard/metrics. Dev dataset: 43 requests + 37 failures = 80. |
| DEC-CP-04 | M4, M16, M17 lead with the figure over requests without a planted anomaly (spec 17); the all-requests figure is in the breakdown (docs/08 section 7). |
| DEC-CP-05 | M5 population: requests that reached routing plus expected routing exceptions; the expected route of requests stopped before routing is not compared (docs/08 section 7). |
| DEC-CP-06 | M13 reads data/validation/reproducibility.json, written by compare_runs --report (both reproducibility scripts pass it). |
| DEC-CP-07 | Dashboard ages (approval aging, queue) are counted at the dataset as-of date (config/generation.yaml), not today: the synthetic data end there. |
| DEC-CP-08 | The request detail uses GET /requests/{id}/investigation for analysts (adds lines, applicable policy, approval attempts, reimbursements, audit events); approvers keep the plain detail. |

### 16.2 Ambiguities found (default APPLIED; please confirm or change)

| ID | Question | Default applied |
|---|---|---|
| AMB-CP-01 | M5 on the dev dataset: one disagreement, EXP-2025-000483. Ground truth keeps the route at assignment (L2 = EMP-000190); the stored step shows the documented reassignment to EMP-000126 (AMB-P7B-11). Which is the "expected route"? | Reported as measured: 917 / 918 expense, 1664 / 1665 overall (99.94%); level-only 100%. Not adjusted. Option: let the expectation follow reassignments (a ground-truth change, 8B-2 style). |
| AMB-CP-02 | Leave utilisation (spec 20) needs entitlement from the balance ledger, which no analytics view exposes. | Not shown; "days approved" shown instead. Option: a v_leave_balance view in a later migration. |
| AMB-CP-03 | High-priority issues counts HARD-exception requests that are already REJECTED (closed). | Counted, as the instruction suggested; can be limited to open requests. |
| AMB-CP-04 | Filters: the Requests page keeps its own filters (type, status, exception class, country, id); the full spec-20 filter set is on Analytics and Approval operations. | Applied. |
