# 03. Architecture

Phase 1 deliverable. Describes what will be built; nothing here exists as code yet.
Covers spec section 28 items A, B, C, D, N, O and the amendment G risk list.

## 1. Executive summary

The system is a deterministic, rules-driven workflow engine for employee leave requests and expense claims, backed by PostgreSQL and exposed through a FastAPI service and a Streamlit dashboard. A seeded synthetic-data generator produces exactly 400 employees, 6 leave policies, 800 leave requests and 1,000 expense claims, plus supporting records, and drives every outcome (validation result, approval route, approval decision, reimbursement) through the same business services the API uses. A separate ground-truth dataset records what the rules should have produced for every request and every planted anomaly. An evaluation package, the only code allowed to read both sides, compares actual behaviour against ground truth and reports 18 metrics.

Three design commitments shape everything else:

1. One rule implementation. The generator does not simulate the rules; it calls them. The API calls the same services. Routing accuracy therefore measures the engine, not a copy of it.
2. Separate dimensions. Workflow status, exception class, technical processing status, approval-step status and reimbursement status are distinct fields on distinct tables. Audit events are append-only and separate again.
3. Ground-truth isolation. Operational code cannot import or query ground truth. This is enforced by a Postgres schema boundary, database roles, and a test that scans imports.

## 2. Problem statement and measurable objectives

Problem: manual processing of leave and expense requests produces wrong balances, unauthorised approvals, mis-routed requests, limit breaches, missing or duplicate receipts, split claims, premature or duplicate reimbursements, and inconsistent audit trails (spec section 2).

Measurable objectives (each maps to a metric in docs/08):

| Objective | Metric(s) | Target stated in spec | Phase 1 stance |
|---|---|---|---|
| Structural integrity of generated data | M1 PK violation rate, M2 FK violation rate | zero expected on main dataset | no number claimed until Phase 11 run |
| Correct derived values | M3 arithmetic reconciliation rate | all reconcile | same |
| Rules applied consistently | M4 compliance rate, M5 routing accuracy | routes follow configured policies | same |
| Anomalies found | M6-M8 precision, recall, F1 | planted anomalies detected, permitted cases not flagged | same |
| Authority enforced | M9 unauthorised approval detection | self and unauthorised approvals blocked | same |
| Receipts and payments controlled | M10, M11, M12 | duplicates detected, no ineligible reimbursement | same |
| Reproducible | M13 | identical checksums on two runs | same |
| Operational visibility | M14-M18 turnaround, backlog, exception and rejection rates, time per level | reported, no target | same |

## 3. Components and responsibilities

| Component | Package | Responsibility | Reads | Writes |
|---|---|---|---|---|
| Common kernel | src/common | Injectable clock (AS_OF_DATE 2026-10-22), ID formatting and counters, seeded RNG stream factory, config loader, money/FX helpers, enums | config/ | nothing |
| Domain models | src/models | SQLAlchemy 2.x declarative models for the ops schema; enum types; constraints | DB | DB via sessions |
| Repositories | src/repositories | Query and persistence per aggregate; row locking helpers (SELECT ... FOR UPDATE); no business rules | ops schema | ops schema |
| Business services | src/services | calendar (business days, holidays, half-days), leave balance ledger and snapshot, leave request validation, expense validation, policy resolver (effective-dated), authority (chain and levels), approval engine (rules, routing, steps, guards), budget ledger, reimbursement, lifecycle (state machines), audit, idempotency, exception catalogue, split-claim and duplicate-receipt detectors, decision output assembly | repositories, config | repositories |
| Data generator | src/data | CLI; staged pipeline (master, balances, leave, expenses, anomalies and boundaries, approvals and outcomes, reimbursements, audit, ground truth); exporters (CSV, JSON, SQL seed); checksum and manifest | config, services | data/raw, data/processed, data/ground_truth, DB (optional load) |
| Validation and detectors | src/validation | Structural, date and lifecycle, arithmetic, workflow, reproducibility validators; batch detectors; validation report | ops schema or exported files | data/validation/ |
| Reference calculation | src/reference | Independent, table-driven computation of expected exception codes, routes and final statuses from config and raw master data; the oracle for ground truth. Shares no code with src/services (import-separation test). Not used at runtime (DEC-01, ASM-054) | config/, raw master frames | ground-truth stage only |
| Evaluation | src/evaluation | Matching on (record_id, issue_type); 18 metrics; CSV, JSON and Markdown report | ops schema AND ground_truth schema/files | data/validation/evaluation.* |
| Explanation (optional) | src/services/explanation_service.py | Rewords deterministic reason text via the Groq free tier for display; off by default; strict fallback to template text; never touches decisions, codes, routes, exports or audit (DEC-29, ASM-051..053) | template text | nothing persistent (in-memory cache) |
| API | src/api | FastAPI app, JWT auth (simulated), RBAC dependencies, routers per resource, Pydantic schemas, structured errors, OpenAPI | services | services |
| Analytics | src/analytics + sql/views.sql | Read-only SQL views and parameterised queries for KPIs and filters | ops schema via analytics_ro role | nothing |
| Dashboard | src/dashboard | Streamlit pages per actor; role selector in dev mode; all writes go through the API | analytics queries; API | API only |
| Database | migrations/ (Alembic), sql/ | Two schemas (ops, ground_truth); roles; triggers for audit immutability and PK immutability; test-only EXCLUDE constraint | n/a | n/a |

Human-readable reasons always come from deterministic templates. The optional explanation service may reword them for display when LLM_EXPLANATIONS_ENABLED is true and GROQ_API_KEY is set; with the flag off (the default, and the state in which all tests run) the system is identical to one with no LLM.

## 4. Data flows

### 4.1 Generation flow (Phases 3-4)

```
config/*.yaml + master seed 20261022
        |
        v
SeedSequence -> one child stream per stage (employees, policies, cost_centers, holidays,
                balances, leave, expenses, anomalies, boundaries, delays, payments)
        |
        v
Stage 1 master -> Stage 2 balances -> Stage 3 leave -> Stage 4 expenses
        |
        v
Stage 5 anomalies + boundaries (modify a deterministic index set; counts unchanged)
        |
        v
Stage 6 outcomes: for each request, call services.validate -> services.route -> simulate
        approver decisions (rule-based outcome, seeded delay) -> steps, status events, attempts
        |
        v
Stage 7 reimbursements (only finally approved claims) -> Stage 8 audit events
        |
        +--> data/raw/*.csv|json (operational tables, sorted by PK)
        +--> data/ground_truth/*.csv|json (expectations and anomaly labels)   [separate]
        +--> data/manifest.json (seed, parameters, row counts, SHA-256 per file)
        +--> optional: load into Postgres (ops and ground_truth schemas)
```

### 4.2 Runtime flow (Phases 5-10)

```
Streamlit (requester / approver / process owner / analyst / admin)
    | HTTPS JSON + JWT                      | read-only SQL (analytics_ro)
    v                                       v
FastAPI routers --> services --> repositories --> PostgreSQL ops schema <-- sql/views.sql
    ^
    | every state change: lifecycle.transition() + audit_service.record() in the same transaction
```

### 4.3 Evaluation flow (Phase 11)

```
ops schema (actual, produced by src/services) ----\
                                                   +--> src/evaluation (matching, metrics) --> data/validation/evaluation.{csv,json,md}
ground_truth schema (expected, produced by -------/
  planted-scenario definitions + src/reference; never by src/services)
```

### 4.4 Optional explanation flow (Phase 9, flag off by default)

```
decision_output (codes, amounts, template text)
   -> explanation_service: if flag off or key missing -> return template text (source=TEMPLATE)
                           else POST to Groq (timeout 5s, 1 retry) -> check output still contains every code,
                                id and amount, and no forbidden words -> return reworded (source=LLM)
                           any error / 429 / failed check -> template text (source=TEMPLATE)
   -> API response field explanation {text, source, model}; never stored, exported or audited
```

As built in Phase 9 (DEC-29 revised): GET /requests/{id}/explanation; facts from the request's own ops rows (codes, status, steps, amount; no names or emails); model openai/gpt-oss-20b by default (config/llm.yaml, GROQ_MODEL overrides); source "llm" or "template"; no cache.

### 4.5 Dashboard read paths (Phase 10)

As built: aggregates from ops.v_request, ops.v_request_exception and ops.v_reimbursement (migration 0003) as lea_analytics_ro (SELECT on those views only); request detail, explanation, GET /detections and GET /evaluation through the API with the user's JWT. Only src/dashboard/evaluation_view.py calls /evaluation. Guide: docs/13_dashboard_guide.md.

## 5. Technology choices and rationale

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.12 | spec section 5 |
| Database | PostgreSQL 16 in Docker Compose; non-Docker alternative: local Postgres 16 install with the same init SQL | AM-F1; CHECK, UNIQUE, partial indexes, triggers, schemas, roles, btree_gist all available |
| ORM and migrations | SQLAlchemy 2.x (typed declarative), Alembic | spec; Alembic gives an executable, versioned schema (acceptance criterion 1) |
| Randomness | numpy.random.Generator from SeedSequence children; Faker seeded per stage | AM-A8 independence of stages |
| Time | src/common/clock.Clock protocol; FrozenClock(AS_OF_DATE) in generation and tests; SystemClock only in the API process for request receipt timestamps | AM-A7 single time source; a lint test fails on datetime.now() outside clock.py |
| Money | Decimal with 2 dp; FX via fx_rate effective on the submission date (ASM-031) | avoids float drift in reconciliation |
| API | FastAPI + Pydantic v2 + Uvicorn | spec |
| Auth | JWT (HS256, secret from .env) issued by /auth/login for seeded application_user rows; roles as claims | AM-F2; documented as simulated, not production auth |
| Dashboard | Streamlit + Plotly; dev-mode role selector | spec, AM-F2 |
| Tests | pytest, pytest-postgresql or a dedicated test database from Docker Compose; parametrised tests | spec section 23 |
| Config | YAML files under config/ with an `illustrative_synthetic: true` header; .env for secrets and connection strings; .env.example committed | spec 13.5, 24 |
| Optional LLM | Groq API free tier via its HTTP endpoint (OpenAI-compatible) from explanation_service; model and rate limits in config/llm.yaml (ASM-051, ASM-052); GROQ_API_KEY in .env, placeholder in .env.example | spec 5 optional item; DEC-29; no paid API required for the core workflow |
| Packaging | pyproject.toml (PEP 621) plus exported requirements.txt | spec |

Alternatives rejected: SQLite (no schemas, roles, EXCLUDE, partial indexes); Django (heavier than needed); storing ground truth in the same schema with a flag (violates AM-E1).

## 6. Proposed folder structure

Matches spec section 21 with these additions, each explained: src/common (shared kernel), src/evaluation (separate from validation because only it may read ground truth), config/ split into topic files, tests/fixtures/negative (AM-A2), sql/ for roles, triggers and views that Alembic migrations call.

```
leave-expense-automation/
  CLAUDE.md
  PROGRESS.md
  README.md
  pyproject.toml
  requirements.txt
  .env.example
  .gitignore
  docker-compose.yml
  alembic.ini
  config/
    generation.yaml          # volumes, master seed, AS_OF_DATE, window, anomaly counts, stream names
    leave_policies.yaml      # 6 policies (ASM-006)
    expense_policies.yaml    # categories, limits, receipt thresholds (ASM-011, ASM-012)
    approval_rules.yaml      # thresholds and levels (ASM-009, ASM-013)
    holidays.yaml            # hand-written calendars (ASM-005)
    fx_rates.yaml            # fixed illustrative rates (ASM-003)
    cost_centers.yaml        # budgets (ASM-016)
    simulation.yaml          # delay distributions, resubmission behaviour, payment simulation (ASM-024, 025, 035)
    exception_codes.yaml     # catalogue (docs/05 section 9)
    llm.yaml                 # optional explanation layer: model names, rate limits, timeout (ASM-051..053)
  data/
    raw/                     # generator output, operational tables, CSV + JSON
    processed/               # DB-load-ready SQL seed and derived exports
    ground_truth/            # record_expectations, anomaly_labels, boundary_cases, scenarios, ground_truth.json
    validation/              # validation_report.*, detections.csv, evaluation.*
    manifest.json
  src/
    common/      clock.py ids.py rng.py config.py money.py enums.py
    models/      one module per table (ops schema) + ground_truth models used ONLY by evaluation and loader
    repositories/
    services/    calendar_service.py leave_balance_service.py leave_request_service.py expense_service.py
                 policy_resolver.py authority_service.py approval_engine.py budget_service.py
                 reimbursement_service.py lifecycle.py audit_service.py idempotency_service.py
                 exception_service.py split_claim_detector.py duplicate_receipt_detector.py decision_output.py
                 explanation_service.py                   # optional Groq rewording, flag off by default
    reference/   calendar_ref.py validate_ref.py route_ref.py   # independent oracle; no imports from services
    data/        generate.py (CLI) export.py checksum.py loader.py stages/{master,balances,leave,expenses,
                 anomalies,boundaries,outcomes,reimbursements,audit,ground_truth}.py
    validation/  structural.py dates_lifecycle.py arithmetic.py workflow.py reproducibility.py
                 detectors/{negative_balance,overlapping_leave,...}.py report.py
    evaluation/  matching.py metrics.py report.py        # ONLY runtime package allowed to import ground truth
    api/         main.py auth.py deps.py errors.py routers/ schemas/
    analytics/   queries.py filters.py
    dashboard/   app.py auth.py pages/{overview,leave,expenses,approvals,reimbursements,exceptions,admin}.py
  sql/
    roles.sql    triggers.sql    views.sql    test_only_constraints.sql
  migrations/    (Alembic env + versions)
  tests/
    conftest.py  unit/  integration/  db/  api/  analytics/  validation/  evaluation/
    fixtures/negative/   reference/   test_ground_truth_isolation.py  test_reference_independence.py  test_no_wallclock_usage.py
  scripts/
    generate.ps1 generate.sh reproducibility_check.ps1 reproducibility_check.sh seed_db.py
  docs/
```

## 7. Security, roles and auditability approach

### 7.1 Database schemas and roles (ASM-037)

| Role | Grants | Used by |
|---|---|---|
| lea_migrator | owner of both schemas; runs Alembic | migrations only |
| lea_app | ops: SELECT, INSERT, UPDATE, DELETE on mutable tables; INSERT, SELECT only on audit_event, request_status_event, approval_event, approval_attempt, reimbursement_attempt, leave_balance_transaction, cost_center_transaction, idempotency_record, processing_failure; NO access to ground_truth | FastAPI, generator loader |
| lea_analytics_ro | SELECT on ops views only; NO access to ground_truth | Streamlit |
| lea_evaluation | SELECT on ops and ground_truth | src/evaluation |

Operational code therefore cannot read ground truth even if a bug tried to; the evaluation role is only loaded by the evaluation entry point.

### 7.2 Audit immutability (AM-F4)

- Trigger on audit_event and the other append-only tables raises on UPDATE and DELETE.
- lea_app lacks UPDATE and DELETE privileges on those tables, so the trigger is a second line of defence.
- Trigger blocks changes to any primary key column on all ops tables (ID immutability).
- Trigger blocks UPDATE of approval_step rows whose status is not PENDING (decided steps are frozen).
- Hash chain (audit_event.prev_hash and row_hash = SHA-256(prev_hash || canonical row)) is a low-priority stretch item (DEC-20, ASM-045): it would make tampering detectable rather than merely blocked, but triggers and grants are the required mechanism.
- Documented limit: a superuser or the migrator role can drop the trigger or alter rows. Protection is against application bugs and ordinary users, not against a DBA. Phase 12 documentation states this plainly.

### 7.3 Application security

- Secrets (DB passwords, JWT secret, GROQ_API_KEY) only in .env; .env.example committed with placeholders; a test scans the repo for secret-like strings. The Groq key is read only by explanation_service and is never logged.
- Simulated authentication: application_user rows with bcrypt password hashes of synthetic passwords; /auth/login returns a JWT with user_id, employee_id and roles; RBAC enforced by FastAPI dependencies per router.
- Input validation by Pydantic; all SQL through SQLAlchemy (parameterised).
- Employee responses omit nothing sensitive because the synthetic model holds no salary, address or national ID. Name and email are synthetic. Manager and grade are returned only to roles that need them (approver, process owner, admin).
- Not a production security posture; no certification claimed.

## 8. Concurrency and transaction safety (summary, detail in docs/06 section 8)

- Row locks: SELECT ... FOR UPDATE on leave_balance and cost_center rows during submit, approve and resubmit.
- Idempotency: idempotency_record keyed by client key or derived hash; replay returns the stored response.
- Uniqueness: partial unique index on reimbursement(expense_claim_id) WHERE status <> 'CANCELLED'.
- One SQLAlchemy session per use case; services never commit partially.

## 9. Recommended implementation sequence

Follows spec section 26 exactly. For each phase the entry criterion is your "APPROVED PHASE N-1".

| Phase | Builds | Exit evidence |
|---|---|---|
| 2 | Data dictionary (docs/10), Alembic migrations for both schemas, roles, triggers, SQLAlchemy models, docker-compose, pyproject, .env.example, test DB fixture | alembic upgrade head and downgrade base succeed; constraint tests pass |
| 3 | src/common, generator stages 1-4 with export, checksum, manifest; CLI | 400/6/800/1,000 rows; two runs identical checksums |
| 4 | Anomaly and boundary injection, independent reference calculation (src/reference), ground truth, validation framework, negative fixtures, isolation and independence tests | validation report on real output; isolation and independence tests pass; reference oracle tests pass |
| 5 | Calendar, leave balance ledger, leave request service, lifecycle for leave | parametrised unit tests incl. boundaries |
| 6 | Expense validation, policy resolver, budget ledger, detectors | parametrised unit tests |
| 7 | Authority, approval engine, state machines, attempts; generator stage 6 switches to real engine | routing tests, guard tests, resubmission tests |
| 8 | Reimbursement, audit service, processing failures; generator stages 7-8; hash chain only as a stretch at the end | uniqueness and immutability tests |
| 9 | FastAPI, auth, RBAC, routers, decision output; optional explanation service (flag off by default) as the last sub-step | API tests, OpenAPI available; all tests pass with the LLM flag off; fallback test with a mocked 429 |
| 10 | Analytics views, Streamlit pages, role selector | KPI query tests |
| 11 | Integration tests, reproducibility verification, evaluation run, metrics report | real metrics in data/validation |
| 12 | README, guides, limitations, GitHub preparation | documentation checklist complete |

## 10. Risk list (AM-G)

| ID | Risk | Likelihood | Impact | Mitigation | Owner phase |
|---|---|---|---|---|---|
| RK-01 | Generator and API diverge in rule behaviour | Medium | High (routing accuracy becomes meaningless) | Generator calls the same service functions; no rule logic in src/data | 3, 7 |
| RK-02 | Ground truth leaks into operational code | Low | High | Separate schema, roles, AST import-scan test that fails CI | 2, 4 |
| RK-03 | Hidden nondeterminism (dict ordering, set iteration, Faker locale, pandas sort stability) breaks checksums | Medium | High | Sort by PK before export; canonical CSV; stable sorts; stream per stage; two-run test in CI | 3, 11 |
| RK-04 | Anomaly injection accidentally produces unlabelled side effects (e.g. modifying a claim changes budget usage so another claim becomes BUDGET_EXCEEDED naturally) | Medium | Medium | Outcomes computed after injection; naturally occurring violations are labelled is_planted=false by comparing against baseline run (docs/07 section 7.4) | 4 |
| RK-05 | Resubmission model complicates line versioning and totals | Medium | Medium | Lines carry submission_round; claim total defined over current round only; tests | 6, 7 |
| RK-06 | Clock misuse (datetime.now) in services | Medium | Medium | Clock injection; lint test | 2 onward |
| RK-07 | Boundary inclusivity implemented inconsistently between validators and rules | Medium | Medium | One comparison helper in src/common; boundary records in ground truth | 5-7 |
| RK-08 | Docker unavailable on learner's machine | Medium | Low | Non-Docker Postgres instructions; same init SQL | 2 |
| RK-09 | Float arithmetic drift in totals and FX | Medium | Medium | Decimal everywhere; NUMERIC(14,2) in DB; rounding rule documented | 2, 6 |
| RK-10 | Audit trigger blocks legitimate migration data fixes | Low | Low | Migrator role may disable trigger within a migration; documented | 2 |
| RK-11 | Over-scoping (LLM explanations, approved-leave cancellation, multi-currency lines) | Medium | Medium | Explicitly out of scope list in docs/09 section 5 | 1 |
| RK-12 | Illustrative policy values mistaken for real company policy | Low | Medium | Every config file carries illustrative_synthetic: true; dashboard footer states it | 2, 10 |
| RK-13 | Test database and dev database share state | Low | Medium | Separate database names in docker-compose; conftest asserts the name ends with _test | 2 |
| RK-14 | Spec requires 1-10 lines per claim but correction rounds may exceed 10 | Medium | Low | DEC-11: numbering continues to 99; baseline stays within 10 | 6 |
| RK-15 | Reference calculation and production engine share the same misunderstanding of a rule, so M5 looks perfect while both are wrong | Medium | Medium | Planted scenarios give construction-known expectations independent of both; reference is table-driven and tested on hand-built cases; any planted-vs-reference disagreement stops generation | 4, 11 |
| RK-16 | Optional LLM layer introduces nondeterminism or hallucinated figures into displayed reasons | Medium | Medium | Display-only; off by default; output must contain every code, id and amount from the template and no forbidden words or it is discarded; never stored or exported | 9 |
| RK-17 | Groq free-tier model names or rate limits change | High | Low | Names and limits in config/llm.yaml; fallback model; template fallback on any error | 9 |

## 11. Documentation plan (spec section 22)

| Required document | Location | Phase |
|---|---|---|
| README | README.md | 12 (skeleton in 2) |
| Architecture | docs/03 (this file) | 1 |
| Data dictionary | docs/10_data_dictionary.md | 2 |
| Entity relationships | docs/04 | 1 |
| Business rules | docs/05 | 1 |
| Approval routing decision table | docs/05 section 5 | 1 |
| State machines | docs/06 | 1 |
| Synthetic data generation guide | docs/07 + docs/11_generation_guide.md | 1, 3 |
| Validation report | data/validation/validation_report.md (generated) | 4, 11 |
| API usage guide | docs/12_api_guide.md | 9 |
| Dashboard guide | docs/13_dashboard_guide.md | 10 |
| Setup instructions | docs/14_setup.md | 2 |
| Testing instructions | docs/15_testing.md | 2 onward |
| Configuration reference | docs/16_configuration.md | 2 |
| Troubleshooting | docs/17_troubleshooting.md | 12 |
| Limitations and assumptions | docs/09 + docs/18_limitations.md | 1, 12 |
