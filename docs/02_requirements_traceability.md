# 02. Requirements traceability and edge-case coverage matrix

Phase 1 deliverable. No code exists yet; every module and test named here is PLANNED.
Source precedence: docs/01_amendments.md > docs/00_original_spec.md.

## 0. Conventions used in this file

| Prefix | Meaning |
|---|---|
| R-P1-nn | Requirement from Part 1 (assignment brief) of docs/00_original_spec.md |
| R-s.n | Requirement from Part 2, section s, item n (e.g. R-13.3 = section 13.3) |
| AM-xx | Amendment from docs/01_amendments.md (A1..H5) |
| EC-nn | Required edge case (spec section 11, items 1..18) plus added cases |
| BC-nn | Boundary case (amendment E5) |
| CF-nn | Conflict between spec and amendments (section 7 of this file) |
| AMB-nn | Open ambiguity with a proposed default (docs/09, section 3) |
| ASM-nnn | Assumption, illustrative synthetic (docs/09, section 2) |
| DEC-nn | Decision requiring approval (docs/09, section 4) |

Planned module paths follow the folder structure in docs/03_architecture.md section 6.
Planned test files live under tests/ (unit/, integration/, db/, evaluation/, fixtures/negative/).
Phase column = the phase (spec section 26) in which the module and test are built.

## 1. Spec section 28 "first response" items mapped to Phase 1 documents

| Item | Content | Delivered in |
|---|---|---|
| A | Executive summary | 03_architecture.md section 1 |
| B | Problem statement and measurable objectives | 03 section 2, 08 (metrics) |
| C | System architecture | 03 sections 3-5 |
| D | Proposed project folder structure | 03 section 6 |
| E | Entity relationship specification with cardinalities | 04 |
| F | Data-generation dependency graph | 07 section 2 |
| G | Business rule catalogue | 05 |
| H | Approval routing decision table | 05 section 5 |
| I | Request and reimbursement lifecycle definitions | 06 sections 2-4 |
| J | Exception-handling strategy | 05 section 9, 06 section 6 |
| K | Ground-truth design | 07 section 8, 08 section 2 |
| L | Data dictionary outline | 04 section 8 (full dictionary is Phase 2) |
| M | Validation and evaluation strategy | 08 |
| N | Security and auditability approach | 03 section 7, 06 section 7 |
| O | Recommended implementation sequence | 03 section 9 |
| P | Assumptions that require approval | 09 |
| G (amendment) | Edge-case coverage matrix and risk list | this file section 6; 03 section 10 |

## 2. Part 1 brief requirements

| ID | Requirement (abridged) | Planned module | Planned acceptance test | Phase |
|---|---|---|---|---|
| R-P1-01 | Route leave and expense requests using policy, balances, budgets and approval authority | src/services/approval_engine.py, leave_request_service.py, expense_service.py, budget_service.py | tests/integration/test_routing_end_to_end.py | 5-7 |
| R-P1-02 | Expose key decisions and exceptions, preserve traceability, measurable outputs | src/services/audit_service.py, src/evaluation/ | tests/integration/test_decision_output.py, tests/evaluation/test_metrics.py | 8, 11 |
| R-P1-03 | Actors: requester, process owner, approver, operations analyst, system administrator | src/api/auth.py (roles), src/dashboard/ role selector | tests/integration/test_rbac.py | 9-10 |
| R-P1-04 | Master data first, then dependent records with valid parent IDs | src/data/stages/ (ordered pipeline) | tests/unit/test_generation_order.py, tests/db/test_fk_integrity.py | 3 |
| R-P1-05 | Seed hierarchy and policies; compute accrual/balance; leave requests with business days; claims with lines, receipts, cost centers; route; approval steps and reimbursements only after final approval | src/data/stages/*, src/services/* | tests/integration/test_pipeline_full.py | 3-8 |
| R-P1-06 | Persist state changes as records/events; do not overwrite history | src/services/audit_service.py, lifecycle.py; sql/triggers.sql | tests/db/test_audit_immutability.py, tests/unit/test_append_only_steps.py | 2, 8 |
| R-P1-07 | Outcomes and ground truth from documented rules, not random | src/data/stages/outcomes.py (uses services), src/data/stages/ground_truth.py | tests/unit/test_outcomes_deterministic.py | 3-4 |
| R-P1-08 | 11 core entities with PK, FK, cardinality, optional relations, effective dates, lifecycle states; bridge tables; event history | src/models/*, migrations/ | tests/db/test_schema_entities.py | 2 |
| R-P1-09 | Anomaly cases carry an issue_type / ground-truth label, never silently corrupt rows | data/ground_truth/ (see CF-01: label lives only in ground truth) | tests/evaluation/test_ground_truth_coverage.py | 4 |
| R-P1-10 | ID formats EMP, LVE, EXP, EXPL, APR, RMB | src/common/ids.py | tests/unit/test_id_formats.py | 2-3 |
| R-P1-11 | Data dictionary per field: type, required, allowed values, units, uniqueness, validation | docs/10_data_dictionary.md (Phase 2) | tests/unit/test_dictionary_matches_models.py | 2 |
| R-P1-12 | Baseline volume 400 / 6 / 800 / 1,000 with 1-10 lines; fixed seed 20261022; parameterised scale | src/data/generate.py (CLI) | tests/integration/test_baseline_volumes.py | 3 |
| R-P1-13 | Valid baseline first, then inject labelled edge cases | src/data/stages/anomalies.py | tests/unit/test_anomaly_injection_replaces_not_adds.py | 3-4 |
| R-P1-14 | Derived values calculated from source records | src/services/* (generator calls services) | tests/unit/test_derived_values.py | 3 |
| R-P1-15 | Separate ground_truth.csv/json, never leaked into inputs | src/data/stages/ground_truth.py, src/evaluation/ | tests/test_ground_truth_isolation.py (import scan) | 4 |
| R-P1-16 | Validation: PK, FK, enums, date ordering, arithmetic, lifecycle, duplicates | src/validation/ | tests/validation/test_validators.py | 4 |
| R-P1-17 | Export CSV/JSON/SQL plus README, dictionary, command, seed, manifest, validation summary | src/data/export.py, scripts/ | tests/integration/test_export_manifest.py | 3, 12 |
| R-P1-18 | Regenerate twice, compare counts and checksums | src/data/checksum.py, scripts/reproducibility_check.ps1 / .sh | tests/integration/test_reproducibility.py | 3, 11 |
| R-P1-19 | Evaluation focus (a)-(g) | src/evaluation/report.py | tests/evaluation/test_report_sections.py | 11 |
| R-P1-20 | Public data optional; synthetic only; record provenance if used | docs/provenance (README section); no external data planned | manual review (documentation) | 12 |

## 3. Part 2 detailed specification requirements

### Sections 1-6

| ID | Requirement (abridged) | Planned module | Planned acceptance test | Phase |
|---|---|---|---|---|
| R-1.1 | Phased delivery, verify behaviour before declaring complete | PROGRESS.md process; CLAUDE.md rules | each phase's real test output | all |
| R-2.1 | System evaluates requests, determines workflow, records decisions, flags exceptions, provides analytics | whole system | tests/integration/test_pipeline_full.py | all |
| R-3.1 | Routing inputs: hierarchy, policies, balances, dates, amounts, categories, country/currency, cost centers/budgets, authority, thresholds, receipts, exceptions, final status | src/services/approval_engine.py, policy_resolver.py | tests/unit/test_routing_inputs_parametrized.py | 7 |
| R-3.2 | Distinguish approved / rejected / pending / returned / escalated / policy violation / suspicious / technical failure; not interchangeable | src/services/lifecycle.py, exception_service.py, models/processing_failure.py | tests/unit/test_status_dimensions_separate.py | 2, 7 |
| R-4.1 | Requester capabilities (view own, submit, status, history, correct and resubmit) | src/api/routers/leave.py, expenses.py; dashboard pages | tests/integration/test_requester_flow.py | 9-10 |
| R-4.2 | Approver capabilities; no self-approval | src/api/routers/approvals.py, src/services/authority_service.py | tests/unit/test_self_approval_blocked.py | 7, 9 |
| R-4.3 | Process owner: policies, thresholds, performance, exceptions, bottlenecks | src/api/routers/config.py, dashboard/pages/process_owner.py | tests/integration/test_process_owner_flow.py | 9-10 |
| R-4.4 | Operations analyst: investigate exceptions, receipts, split claims, failed attempts, eligibility, reports | src/api/routers/exceptions.py, dashboard/pages/exceptions.py | tests/integration/test_analyst_flow.py | 9-10 |
| R-4.5 | System administrator: configuration, users/roles, errors, settings, validation reports | src/api/routers/admin.py | tests/integration/test_admin_flow.py | 9 |
| R-4.6 | Role-based access control appropriate to scope | src/api/auth.py, src/api/deps.py | tests/integration/test_rbac.py | 9 |
| R-5.1 | Stack: Python 3.12, Pandas, NumPy, Faker, PostgreSQL, SQLAlchemy, Alembic, FastAPI, Pydantic, Uvicorn, Streamlit, Plotly, Pytest, Git, env vars, pyproject/requirements, .env.example | pyproject.toml, docker-compose.yml | tests/test_environment.py (imports and versions) | 2 |
| R-5.2 | No paid LLM required for core workflow | core workflow has no LLM dependency; optional explanation layer is flag-off by default and uses only a free tier (DEC-29) | tests/api/test_decision_output.py runs with LLM flag off | 9 |
| R-5.3 | Optional LLM for explaining deterministic decisions in natural language (spec 5 optional) | src/services/explanation_service.py; config/llm.yaml; GROQ_API_KEY in .env | tests/unit/test_explanation_fallback.py (mocked 429, timeout, missing key, output failing the content check all return template text; decisions unchanged) | 9 |
| R-6.1 | Baseline volumes exactly 400 / 6 / 800 / 1,000; lines 1-10 | src/data/generate.py | tests/integration/test_baseline_volumes.py | 3 |
| R-6.2 | Supporting records: balances, expense policies, cost centers, rules, steps, reimbursements, audit events, balance movements, receipts, ground truth | src/data/stages/* | tests/integration/test_supporting_record_counts.py | 3-4 |
| R-6.3 | Configurable seed 20261022; starter and full dataset share logic | src/common/rng.py, config/generation.yaml | tests/unit/test_seed_streams.py | 3 |
| R-6.4 | Documented executable generate command | README, scripts/ | tests/integration/test_cli_help.py | 3 |

### Section 7 entities

| ID | Requirement (abridged) | Planned module | Planned acceptance test | Phase |
|---|---|---|---|---|
| R-7.0 | 11 core entities; justified supporting entities | src/models/*; docs/04 | tests/db/test_schema_entities.py | 2 |
| R-7.1 | Employee fields; validate manager relations; no circular hierarchy | models/employee.py; services/hierarchy_service.py | tests/unit/test_hierarchy_no_cycles.py; tests/db/test_employee_constraints.py | 2-3 |
| R-7.2 | LeavePolicy fields incl. accrual, carry-forward, negative-balance policy, effective dates, version | models/leave_policy.py | tests/db/test_policy_effective_dates.py | 2 |
| R-7.3 | LeaveBalance fields; materialised vs transactional; reconciliation | models/leave_balance.py, leave_balance_transaction.py; services/leave_balance_service.py | tests/unit/test_balance_reconciliation.py | 2, 5 |
| R-7.4 | LeaveRequest fields; date ordering; business days with weekends and holidays; overlaps, half-days, resubmission | models/leave_request.py; services/calendar_service.py, leave_request_service.py | tests/unit/test_business_days.py, test_half_days.py, test_overlaps.py, test_resubmission.py | 2, 5 |
| R-7.5 | ExpensePolicy fields incl. limits, receipt threshold, effective dates, version | models/expense_policy.py | tests/db/test_policy_effective_dates.py | 2 |
| R-7.6 | ExpenseClaim fields; total from lines | models/expense_claim.py; services/expense_service.py | tests/unit/test_claim_totals.py | 2, 6 |
| R-7.7 | ExpenseLine fields; line totals reconcile with claim | models/expense_line.py | tests/unit/test_claim_totals.py; tests/db/test_claim_total_check.py | 2, 6 |
| R-7.8 | CostCenter fields; budget availability; reservations; no approval against invalid cost center without documented exception path | models/cost_center.py, cost_center_transaction.py; services/budget_service.py | tests/unit/test_budget_availability.py, test_missing_cost_center_route.py | 2, 6 |
| R-7.9 | ApprovalRule fields; configurable, not hardcoded | models/approval_rule.py; config/approval_rules.yaml | tests/unit/test_rules_loaded_from_config.py | 2, 7 |
| R-7.10 | ApprovalStep fields; multiple steps per request; retain previous decisions on resubmit or reassign | models/approval_step.py (real FKs leave_request_id / expense_claim_id with exactly-one CHECK, DEC-03); services/approval_engine.py | tests/unit/test_steps_retained_on_resubmit.py; tests/db/test_request_fk_exactly_one.py | 2, 7 |
| R-7.11 | Reimbursement fields; prevent duplicates via constraints and transaction-safe logic | models/reimbursement.py; services/reimbursement_service.py; migration partial unique index | tests/db/test_reimbursement_unique.py; tests/integration/test_reimbursement_concurrency.py | 2, 8 |

### Sections 8-12

| ID | Requirement (abridged) | Planned module | Planned acceptance test | Phase |
|---|---|---|---|---|
| R-8.1 | Deterministic ID formats; define formats for remaining entities | src/common/ids.py (all formats per AM-A6 and docs/07 section 3) | tests/unit/test_id_formats.py | 2 |
| R-8.2 | IDs unique, immutable, zero-padded, exact FK references, consistent across CSV/JSON/SQL/API, reproducible | ids.py; export.py; DB PK constraints; trigger blocking PK update | tests/db/test_pk_unique.py, test_id_immutable_trigger.py; tests/integration/test_ids_consistent_across_exports.py | 2-3 |
| R-9.1 | Comprehensive data dictionary with all listed attributes, lifecycle states, FK relations, cardinality, bridge tables | docs/10_data_dictionary.md (Phase 2); outline in docs/04 section 8 | tests/unit/test_dictionary_matches_models.py | 2 |
| R-10.1 | Stage 1 master data internally consistent | src/data/stages/master.py | tests/unit/test_master_consistency.py | 3 |
| R-10.2 | Stage 2 balances: opening, accrual (annual/periodic), consumption, adjustments, carry-forward, negative where permitted or seeded; never randomised | src/data/stages/balances.py uses services/leave_balance_service.py | tests/unit/test_accrual.py, test_carry_forward.py, test_balance_not_random.py | 3, 5 |
| R-10.3 | Stage 3: 800 leave requests with valid dates, business days, quantity, eligibility, expected route | src/data/stages/leave.py | tests/integration/test_leave_stage.py | 3 |
| R-10.4 | Stage 4: 1,000 claims, 1-10 lines, categories, amounts, currency/country consistency, cost centers, receipts, deterministic hashes, totals, policy resolution | src/data/stages/expenses.py | tests/integration/test_expense_stage.py; tests/unit/test_receipt_hash_deterministic.py | 3 |
| R-10.5 | Stage 5: approval steps from deterministic engine using type, amount, category, country, policy version, cost center, hierarchy, authority | src/data/stages/approvals.py uses services/approval_engine.py | tests/unit/test_approval_engine_parametrized.py | 3, 7 |
| R-10.6 | Stage 6: reimbursements only for eligible, finally approved claims | src/data/stages/reimbursements.py | tests/unit/test_reimbursement_only_after_approval.py | 3, 8 |
| R-10.7 | Stage 7: audit history from actual transitions; no contradictions | src/data/stages/audit.py | tests/unit/test_audit_matches_transitions.py | 3, 8 |
| R-11.1 | Valid baseline first, then controlled labelled injection | src/data/stages/anomalies.py | tests/unit/test_anomaly_injection_replaces_not_adds.py | 3-4 |
| R-11.2 | 18 edge cases (see section 6 matrix) | see matrix | see matrix | 3-8 |
| R-11.3 | Referential integrity maintained; FK/arithmetic breakers isolated in negative fixtures | tests/fixtures/negative/ | tests/validation/test_negative_fixtures_detected.py | 4 |
| R-11.4 | Per scenario: scenario ID, record ID, issue type, label, expected detection, expected workflow behaviour, reason | data/ground_truth/anomaly_labels.csv | tests/evaluation/test_ground_truth_schema.py | 4 |
| R-11.5 | Distinguish planted anomaly from naturally occurring violation | is_planted column in ground truth (AM-E4) | tests/evaluation/test_is_planted_populated.py | 4 |
| R-12.1 | Separate ground_truth.csv/json: anomalies, expected routing, outcomes, eligibility, exception classes | data/ground_truth/*.csv, ground_truth.json | tests/evaluation/test_ground_truth_files.py | 4 |
| R-12.2 | Ground truth never an operational input; not used for predictions | import scan test; separate DB schema and role | tests/test_ground_truth_isolation.py | 4 |
| R-12.3 | Separate evaluation process comparing actual vs expected | src/evaluation/ | tests/evaluation/test_metrics.py | 11 |
| R-12.4 | Ground-truth expectations independent of the engine under test (review item 1, DEC-01) | src/reference/ (table-driven oracle); stages/ground_truth.py reads planted definitions and src/reference only | tests/test_reference_independence.py; tests/reference/test_reference_oracle.py | 4 |

### Section 13 business rule engine

| ID | Requirement (abridged) | Planned module | Planned acceptance test | Phase |
|---|---|---|---|---|
| R-13.1 | Leave validation checks (11 items) and expected balance from transactions | services/leave_request_service.py, leave_balance_service.py, calendar_service.py | tests/unit/test_leave_validation_parametrized.py | 5 |
| R-13.2 | Expense validation checks (14 items) | services/expense_service.py, split_claim_detector.py, duplicate_receipt_detector.py, budget_service.py | tests/unit/test_expense_validation_parametrized.py | 6 |
| R-13.3 | Routing by effective-dated rules, deterministic precedence, multi-level; prevent self-approval, unauthorised, skipped levels, expired rule, duplicate events, premature reimbursement; conflict or no path -> explicit exception state | services/approval_engine.py, authority_service.py | tests/unit/test_routing_guards.py, test_no_valid_path.py, test_rule_conflict.py | 7 |
| R-13.4 | Decision output fields (12 items) | services/decision_output.py; api/schemas/decision.py | tests/unit/test_decision_output_complete.py | 7, 9 |
| R-13.5 | Configurable thresholds, entitlements, limits, receipts, dates; illustrative labelled policies; never presented as real policy | config/*.yaml with "illustrative_synthetic: true" header | tests/unit/test_config_labelled_illustrative.py | 2 |

### Sections 14-18

| ID | Requirement (abridged) | Planned module | Planned acceptance test | Phase |
|---|---|---|---|---|
| R-14.1 | Explicit state machines for request, claim, step, reimbursement; legal transitions and actors | services/lifecycle.py (single transition table); docs/06 | tests/unit/test_state_machine_transitions.py | 7 |
| R-14.2 | Lifecycle consistent across DB, services, API, dashboard | DB CHECK on status enums; services enforce; API uses same enum | tests/integration/test_lifecycle_consistency.py | 7-10 |
| R-14.3 | No overwrite of historical decisions on resubmission | approval_step append-only; trigger blocks update of decided steps | tests/db/test_decided_step_immutable.py | 7 |
| R-15.1 | Append-only audit events with 12 listed fields | models/audit_event.py; services/audit_service.py | tests/unit/test_audit_event_fields.py | 8 |
| R-15.2 | Transactions for all-or-nothing operations | services use one SQLAlchemy session per use case (docs/06 section 8) | tests/integration/test_transaction_rollback.py | 5-8 |
| R-15.3 | Duplicate reimbursement prevented via uniqueness and idempotency | partial unique index; idempotency_record | tests/db/test_reimbursement_unique.py; tests/integration/test_idempotent_create_reimbursement.py | 8 |
| R-15.4 | Explain audit immutability limits and DB permissions | docs/06 section 7; sql/roles.sql, triggers.sql | tests/db/test_audit_immutability.py | 2, 8 |
| R-16.1 | Structural integrity validators | src/validation/structural.py | tests/validation/test_structural.py | 4 |
| R-16.2 | Date and lifecycle validators | src/validation/dates_lifecycle.py | tests/validation/test_dates_lifecycle.py | 4 |
| R-16.3 | Arithmetic validators | src/validation/arithmetic.py | tests/validation/test_arithmetic.py | 4 |
| R-16.4 | Workflow validators | src/validation/workflow.py | tests/validation/test_workflow.py | 4, 7 |
| R-16.5 | Reproducibility comparison incl. checksums; exclude documented nondeterministic metadata | src/data/checksum.py; config lists excluded columns | tests/integration/test_reproducibility.py | 3, 11 |
| R-17.1 | 18 metrics defined mathematically with population and denominator | src/evaluation/metrics.py; docs/08 | tests/evaluation/test_each_metric.py | 11 |
| R-17.2 | Deliberate anomalies not counted as accidental DQ failures | evaluation reads is_planted and excludes/explains | tests/evaluation/test_planted_excluded.py | 11 |
| R-17.3 | No claimed perfect metrics without execution; results in CSV, JSON, Markdown | src/evaluation/report.py -> data/validation/ | tests/evaluation/test_report_formats.py | 11 |
| R-18.1 | PostgreSQL authoritative; schema, models, Alembic, seeds, indexes, FK, CHECK, UNIQUE, transaction-safe ops | migrations/, src/models/, scripts/seed_db.py | tests/db/test_migrations_upgrade_downgrade.py | 2 |
| R-18.2 | Export CSV and JSON deterministically; SQL seed; validate relationships after export | src/data/export.py; src/validation/post_export.py | tests/integration/test_export_roundtrip.py | 3 |

### Sections 19-27

| ID | Requirement (abridged) | Planned module | Planned acceptance test | Phase |
|---|---|---|---|---|
| R-19.1 | REST endpoints for 13 resource groups | src/api/routers/* | tests/api/test_endpoints_smoke.py | 9 |
| R-19.2 | Pydantic schemas, validation, status codes, structured errors | src/api/schemas/*, errors.py | tests/api/test_validation_errors.py | 9 |
| R-19.3 | OpenAPI docs | FastAPI built in | tests/api/test_openapi_available.py | 9 |
| R-19.4 | RBAC per auth model; no unnecessary sensitive data | src/api/deps.py; response schemas omit salary-like fields (none exist) | tests/api/test_rbac_matrix.py | 9 |
| R-20.1 | Executive overview KPIs | src/analytics/queries.py; dashboard/pages/overview.py | tests/analytics/test_kpi_queries.py | 10 |
| R-20.2 | Leave analytics | dashboard/pages/leave.py | tests/analytics/test_leave_queries.py | 10 |
| R-20.3 | Expense analytics | dashboard/pages/expenses.py | tests/analytics/test_expense_queries.py | 10 |
| R-20.4 | Approval operations | dashboard/pages/approvals.py | tests/analytics/test_approval_queries.py | 10 |
| R-20.5 | Reimbursement analytics | dashboard/pages/reimbursements.py | tests/analytics/test_reimbursement_queries.py | 10 |
| R-20.6 | Exception investigation drill-down; operational views separate from ground truth | dashboard/pages/exceptions.py; analytics_ro role has no ground_truth grant | tests/db/test_analytics_role_cannot_read_ground_truth.py | 10 |
| R-20.7 | Filters: dates, country, department, manager, status, category, cost center, exception type | src/analytics/filters.py | tests/analytics/test_filters.py | 10 |
| R-20.8 | PostgreSQL as dashboard source | dashboard reads via analytics_ro role (AM-F3) | tests/analytics/test_connection_role.py | 10 |
| R-21.1 | Modular folder structure; explain changes | docs/03 section 6 | tests/test_project_layout.py | 2 |
| R-22.1 | 16 documentation artefacts | docs/ (see docs/03 section 11 for mapping) | manual review | 12 |
| R-22.2 | Document seed, parameters, provenance, validation results | data/manifest.json; README | tests/integration/test_manifest_fields.py | 3, 12 |
| R-23.1 | 22 test areas; normal, boundary, failure, exception; isolated test DB | tests/ (conftest with test database) | pytest run output in each phase | all |
| R-24.1 | Security practices (9 items); no production certification claim | .env.example; auth; ORM; docs | tests/test_no_secrets_in_repo.py | 2, 9 |
| R-25.1 | 22 acceptance criteria; unmet ones listed as incomplete | PROGRESS.md acceptance table | per phase | all |
| R-26.1 | 12 phases; end-of-phase reporting | PROGRESS.md | per phase | all |
| R-27.1 | 15 working rules | CLAUDE.md | per phase | all |

## 4. Amendments traceability

| ID | Amendment (abridged) | Planned module | Planned acceptance test | Phase |
|---|---|---|---|---|
| AM-A1 | Exact volumes; anomalies replace or modify, never add | stages/anomalies.py operates on fixed index set | tests/unit/test_anomaly_injection_replaces_not_adds.py; tests/integration/test_baseline_volumes.py | 3 |
| AM-A2 | Row-valid anomalies in main dataset; structure-breaking ones in tests/fixtures/negative; nullable cost center with CHECK; blocked actions recorded as attempts | models, migrations (CHECK), approval_attempt, reimbursement_attempt | tests/db/test_cost_center_null_check.py; tests/validation/test_negative_fixtures_detected.py | 2-4 |
| AM-A3 | Overlap enforced in service layer; EXCLUDE constraint only in test DB | services/leave_request_service.py; tests/db/conftest adds btree_gist constraint | tests/db/test_overlap_exclude_constraint.py; tests/unit/test_overlaps.py | 5 |
| AM-A4 | Two negative-balance causes labelled separately | detectors/negative_balance.py; ground truth labels | tests/unit/test_negative_balance_permitted_vs_anomaly.py | 5 |
| AM-A5 | Resubmission keeps ID; submission_round; APR numbering continues; old steps CANCELLED | services/approval_engine.py, lifecycle.py | tests/unit/test_resubmission_ids.py | 7 |
| AM-A6 | Year segment = submission year; window 2025-01-01..2026-10-22; per-year counters; RMB year = final approval year; added ID formats; EXPL 2 digits | src/common/ids.py; config/generation.yaml | tests/unit/test_id_formats.py, test_year_counters.py | 2-3 |
| AM-A7 | Injectable clock, AS_OF_DATE = 2026-10-22; no now(); checksums exclude documented columns only | src/common/clock.py; lint test scanning for datetime.now / now() | tests/test_no_wallclock_usage.py | 2 |
| AM-A8 | Master seed 20261022; SeedSequence per stage; Faker seeded per stage; stage volume independence; sorted exports; SHA-256 canonical CSV | src/common/rng.py; export.py; checksum.py | tests/unit/test_seed_streams.py (changing leave volume leaves employees unchanged) | 3 |
| AM-A9 | Deterministic approver behaviour; delays stochastic, outcomes rule-based | stages/outcomes.py; config/simulation.yaml | tests/unit/test_outcomes_deterministic.py | 3, 7 |
| AM-B1 | Countries IN/US/GB; currencies; USD base; fx_rate table | models/fx_rate.py; config/fx_rates.yaml | tests/unit/test_fx_conversion.py | 2-3 |
| AM-B2 | Weekend Sat/Sun configurable; hand-written holidays | config/holidays.yaml; models/country_holiday.py | tests/unit/test_business_days.py | 2-3 |
| AM-B3 | Six named leave policies | config/leave_policies.yaml | tests/integration/test_baseline_volumes.py (6 policies) | 3 |
| AM-B4 | Monthly accrual, pro-rata, none after end; carry-forward cap on Jan 1 | services/leave_balance_service.py | tests/unit/test_accrual.py, test_carry_forward.py | 5 |
| AM-B5 | Half-day rules | services/calendar_service.py | tests/unit/test_half_days.py | 5 |
| AM-B6 | Overlap with APPROVED hard fail; with PENDING soft -> review | services/leave_request_service.py | tests/unit/test_overlaps.py | 5 |
| AM-B7 | Grades G1-G7, flags, levels L1-L5, authority rule | services/authority_service.py | tests/unit/test_authority_levels.py | 7 |
| AM-B8 | Illustrative thresholds in approval_rule, never hardcoded; sick > 3 days needs certificate flag | config/approval_rules.yaml; leave validation | tests/unit/test_thresholds_from_config.py, test_medical_cert.py | 5, 7 |
| AM-B9 | No arbitrary approver; NO_VALID_APPROVAL_PATH; delegation table | services/approval_engine.py; models/delegation.py | tests/unit/test_no_valid_path.py, test_delegation.py | 7 |
| AM-B10 | Rule conflict: priority wins; equal priority different outcome -> RULE_CONFLICT; effective-dated | services/approval_engine.py | tests/unit/test_rule_conflict.py | 7 |
| AM-B11 | Budget ledger: available = budget - actual - committed; reservation, release, conversion; BUDGET_EXCEEDED -> escalate; finance override with reason | services/budget_service.py; models/cost_center_transaction.py | tests/unit/test_budget_ledger.py | 6 |
| AM-B12 | Partial approval: approved_amount <= total; reimbursement uses approved_amount | services/expense_service.py, reimbursement_service.py | tests/unit/test_partial_approval.py | 6, 8 |
| AM-B13 | Split-claim rule configurable | services/split_claim_detector.py; config | tests/unit/test_split_claim_detector.py | 6 |
| AM-B14 | Duplicate hash self vs cross-employee; SHA-256 of deterministic string | services/duplicate_receipt_detector.py; stages/expenses.py | tests/unit/test_duplicate_receipt_detector.py | 6 |
| AM-B15 | Receipt required at threshold; MISSING_RECEIPT -> RETURNED_FOR_CORRECTION | services/expense_service.py | tests/unit/test_receipt_requirement.py | 6 |
| AM-C | New entities (events, attempts, ledgers, holidays, fx, delegation, assignment, users/roles, processing_failure, idempotency) | src/models/* | tests/db/test_schema_entities.py | 2 |
| AM-D | Separate status dimensions; transition table; ESCALATED exits by process owner | services/lifecycle.py | tests/unit/test_state_machine_transitions.py | 7 |
| AM-E1 | ground_truth schema and files; no FKs into it; no label columns in ops tables | migrations (two schemas); tests scanning columns | tests/db/test_no_ground_truth_columns_in_ops.py | 2, 4 |
| AM-E2 | Only src/evaluation reads both; test fails if ops packages reference ground_truth | tests/test_ground_truth_isolation.py (AST import scan) | same | 4 |
| AM-E3 | Matching unit (record_id, issue_type); permitted cases are expected negatives | src/evaluation/matching.py | tests/evaluation/test_matching.py | 11 |
| AM-E4 | Ground-truth columns per record and per anomaly incl. is_planted | stages/ground_truth.py | tests/evaluation/test_ground_truth_schema.py | 4 |
| AM-E5 | Boundary records | stages/anomalies.py (boundary sub-stage) | tests/unit/test_boundary_records_present.py | 3-4 |
| AM-F1 | Docker Compose Postgres 16; non-Docker alternative | docker-compose.yml; docs/setup | manual + tests/db connection test | 2 |
| AM-F2 | Simulated auth: seeded users, JWT, Streamlit role selector; documented limitation | src/api/auth.py; dashboard/auth.py | tests/api/test_login_jwt.py | 9-10 |
| AM-F3 | Dashboard via read-only views and role; writes through API | sql/views.sql, sql/roles.sql | tests/db/test_analytics_role_readonly.py | 10 |
| AM-F4 | Trigger blocks UPDATE/DELETE on audit_event; app user INSERT/SELECT only; optional hash chain; superuser caveat documented | sql/triggers.sql, roles.sql; hash chain in audit_service only as a stretch (DEC-20) | tests/db/test_audit_immutability.py; tests/unit/test_hash_chain.py only if the stretch is built | 2, 8 |
| AM-F5 | SELECT FOR UPDATE on balance/budget rows; idempotency keys; unique active reimbursement | repositories/*.lock_for_update; idempotency_service | tests/integration/test_concurrent_submit.py, test_reimbursement_concurrency.py | 5-8 |
| AM-F6 | No performance over-engineering | design principle | n/a | all |
| AM-G | Edge-case matrix and risk list in Phase 1 | this file section 6; docs/03 section 10 | n/a (document) | 1 |
| AM-H1 | Glossary in docs/06 | docs/06 section 1 | n/a | 1 |
| AM-H2 | approval_attempt and reimbursement_attempt fields | models/approval_attempt.py, reimbursement_attempt.py | tests/db/test_schema_entities.py | 2 |
| AM-H3 | Split-claim flag = SUSPICIOUS_PATTERN, never "fraud" | exception_code lookup text; dashboard labels | tests/unit/test_exception_code_wording.py | 6 |
| AM-H4 | Transaction boundaries and idempotency keys for submit, approve/reject, resubmit, create reimbursement | docs/06 section 8; services | tests/integration/test_idempotency_*.py | 5-8 |
| AM-H5 | Every spec requirement maps to module and test | this file | tests/test_traceability_file_complete.py (every R-/AM- ID has module and test) | 1, 12 |

## 5. Exception code catalogue used by the matrix

Routing severity: HARD -> REJECTED; CORRECTABLE -> RETURNED_FOR_CORRECTION; SOFT -> ESCALATED_FOR_REVIEW; INFO -> no routing effect. Precedence when several codes apply: HARD > CORRECTABLE > SOFT (ASM-029, DEC-07). Full definitions in docs/05 section 9.

| Code | Class | Severity |
|---|---|---|
| INSUFFICIENT_BALANCE | POLICY_VIOLATION | HARD |
| NEGATIVE_BALANCE_UNPERMITTED | POLICY_VIOLATION | SOFT (detected on ledger, not at submission) |
| OVERLAPPING_APPROVED_LEAVE | POLICY_VIOLATION | HARD at submission; SOFT when found by detector on seeded data |
| OVERLAPPING_PENDING_LEAVE | POLICY_VIOLATION | SOFT |
| LEAVE_OUTSIDE_EMPLOYMENT | POLICY_VIOLATION | HARD |
| ZERO_BUSINESS_DAYS | DATA_QUALITY | CORRECTABLE |
| HALF_DAY_ON_NON_BUSINESS_DAY | DATA_QUALITY | CORRECTABLE |
| MEDICAL_CERT_REQUIRED | POLICY_VIOLATION | CORRECTABLE |
| UNPAID_LIMIT_EXCEEDED | POLICY_VIOLATION | HARD |
| EXPENSE_OUTSIDE_EMPLOYMENT | POLICY_VIOLATION | HARD |
| LINE_LIMIT_EXCEEDED | POLICY_VIOLATION | INFO (partial approval, amount capped) |
| CLAIM_LIMIT_EXCEEDED | POLICY_VIOLATION | SOFT |
| MISSING_RECEIPT | DATA_QUALITY | CORRECTABLE |
| DUPLICATE_RECEIPT_SELF | DATA_QUALITY | CORRECTABLE |
| DUPLICATE_RECEIPT_CROSS_EMPLOYEE | SUSPICIOUS_PATTERN | SOFT |
| SPLIT_CLAIM_SUSPECTED | SUSPICIOUS_PATTERN | SOFT |
| MISSING_COST_CENTER | DATA_QUALITY | SOFT |
| INVALID_COST_CENTER | DATA_QUALITY | SOFT |
| BUDGET_EXCEEDED | POLICY_VIOLATION | SOFT |
| CURRENCY_MISMATCH | DATA_QUALITY | CORRECTABLE |
| POLICY_VERSION_EXPIRED | DATA_QUALITY | SOFT |
| POLICY_NOT_APPLICABLE | POLICY_VIOLATION | HARD |
| NO_VALID_APPROVAL_PATH | NO_VALID_APPROVAL_PATH | SOFT |
| RULE_CONFLICT | RULE_CONFLICT | SOFT |

Blocked-action reason codes (approval_attempt): SELF_APPROVAL, UNAUTHORIZED_APPROVER, EXPIRED_RULE, DUPLICATE_ACTION, STEP_NOT_PENDING, LEVEL_SKIPPED.
Blocked-action reason codes (reimbursement_attempt): DUPLICATE_REIMBURSEMENT, CLAIM_NOT_APPROVED, AMOUNT_MISMATCH; processing outcomes PAYMENT_FAILED, RETRY.

## 6. Edge-case coverage matrix

Columns: where generated (which generator stage and how), where detected (which service or detector), how labelled (ground truth issue_type, and whether the record is an expected POSITIVE or NEGATIVE for anomaly metrics), which test. Counts are ASSUMPTIONS from ASM-027 and need approval.

| EC | Edge case (spec section 11 unless noted) | Lives in | Generated by | Detected by | Ground-truth label | Expected workflow behaviour | Test |
|---|---|---|---|---|---|---|---|
| EC-01 | Negative leave balance (seeded, unpermitted) | main dataset | stages/anomalies.py: for 8 employees, inject an APPROVED 2025 leave usage exceeding available, representing a legacy manual override; ledger shows negative available | detectors/negative_balance.py (ledger reconciliation vs policy.negative_balance_allowed and negative_limit) | NEGATIVE_BALANCE_UNPERMITTED, POSITIVE, is_planted=true | Balance flagged; subsequent new requests on that policy fail INSUFFICIENT_BALANCE | tests/unit/test_negative_balance_permitted_vs_anomaly.py |
| EC-01b | Negative balance permitted by policy (AM-A4a) | main dataset | stages/anomalies.py: 8 employees on LPOL-ANNUAL-US (negative allowed to -3) with approved requests driving balance to -1..-3 | same detector must NOT flag | PERMITTED_NEGATIVE_BALANCE, expected NEGATIVE (false-positive test) | Approved normally | same test, negative case |
| EC-02 | Overlapping approved leave, same employee | main dataset | stages/anomalies.py: 8 pairs; second request of each pair forced APPROVED with overlapping dates (bypasses service rule, AM-A3) | detectors/overlapping_leave.py (pairwise interval overlap among APPROVED) | OVERLAPPING_APPROVED_LEAVE, POSITIVE, is_planted=true | Both flagged SOFT for analyst; no auto-change to historic approvals | tests/unit/test_overlaps.py; tests/db/test_overlap_exclude_constraint.py (test DB only) |
| EC-03 | Insufficient leave balance | main dataset | stages/anomalies.py: 12 requests with quantity > available at submission (policy forbids negative) | leave_request_service.validate (balance check) | INSUFFICIENT_BALANCE, POSITIVE, is_planted=true | REJECTED at validation; reason recorded | tests/unit/test_leave_validation_parametrized.py |
| EC-04 | Leave spanning weekends and holidays | main dataset (normal) | stages/leave.py guarantees >= 40 requests crossing a holiday and many crossing weekends | calendar_service.business_days | WEEKEND_HOLIDAY_SPAN, expected NEGATIVE (not an anomaly) | Quantity excludes non-business days; routes normally | tests/unit/test_business_days.py |
| EC-05 | Missing expense receipt | main dataset | stages/anomalies.py: 10 claims, one line >= receipt threshold with receipt_id NULL | expense_service.validate (receipt rule, AM-B15) | MISSING_RECEIPT, POSITIVE | RETURNED_FOR_CORRECTION; 50% resubmitted with receipt (ASM-025) | tests/unit/test_receipt_requirement.py |
| EC-06 | Duplicate receipt hash | main dataset | stages/anomalies.py: 8 self pairs (same employee, 2 claims share hash, 16 claims), 8 cross pairs (different employees, 16 claims) | duplicate_receipt_detector.py (batch over receipt.hash) plus at-submission check | DUPLICATE_RECEIPT_SELF / DUPLICATE_RECEIPT_CROSS_EMPLOYEE, POSITIVE on both claims of each pair; both codes count in metric M10 (AMB-07 confirmed) | Self -> RETURNED_FOR_CORRECTION; cross -> ESCALATED_FOR_REVIEW | tests/unit/test_duplicate_receipt_detector.py |
| EC-07 | Expense policy limit breach | main dataset | 8 claims with a line > per-line limit; 8 claims with total > per-claim limit | expense_service.validate | LINE_LIMIT_EXCEEDED (INFO, partial approval) / CLAIM_LIMIT_EXCEEDED (SOFT), POSITIVE | Line: approved_amount capped, routes normally; claim: ESCALATED_FOR_REVIEW | tests/unit/test_partial_approval.py, test_expense_validation_parametrized.py |
| EC-08 | Expense date outside employment dates | main dataset | 8 claims for terminated or not-yet-joined employees, expense_date outside [start, end] | expense_service.validate | EXPENSE_OUTSIDE_EMPLOYMENT, POSITIVE | REJECTED | tests/unit/test_expense_validation_parametrized.py |
| EC-09 | Split claims to evade thresholds | main dataset | 8 groups (6 pairs, 2 triples; 18 claims total) carved from the 1,000: same employee, same category, within 7 days, each < 200 USD, sum >= 200 USD | split_claim_detector.py (batch window scan) | SPLIT_CLAIM_SUSPECTED, POSITIVE, all claims in group | ESCALATED_FOR_REVIEW (SUSPICIOUS_PATTERN; wording per AM-H3) | tests/unit/test_split_claim_detector.py |
| EC-10 | Missing cost center | main dataset | 8 claims with cost_center_id NULL (CHECK allows because exception_class != NONE) | expense_service.validate (cost center resolution) | MISSING_COST_CENTER, POSITIVE | ESCALATED_FOR_REVIEW | tests/unit/test_missing_cost_center_route.py; tests/db/test_cost_center_null_check.py |
| EC-11 | Approval attempt by requester | approval_attempt table only | stages/anomalies.py: 8 BLOCKED attempts where actor_id = requester | authority_service (self-approval guard) | SELF_APPROVAL_ATTEMPT, POSITIVE (record = attempt_id) | Attempt BLOCKED, reason SELF_APPROVAL; request unchanged | tests/unit/test_self_approval_blocked.py |
| EC-12 | Unauthorised approver | approval_attempt table only | 8 BLOCKED attempts by employees outside chain / below level | authority_service | UNAUTHORIZED_APPROVER_ATTEMPT, POSITIVE | BLOCKED, reason UNAUTHORIZED_APPROVER | tests/unit/test_routing_guards.py |
| EC-13 | Duplicate reimbursement attempt | reimbursement_attempt table only | 8 BLOCKED attempts to create a second reimbursement for an already reimbursed claim | reimbursement_service + partial unique index | DUPLICATE_REIMBURSEMENT_ATTEMPT, POSITIVE | BLOCKED, reason DUPLICATE_REIMBURSEMENT; exactly one reimbursement row | tests/db/test_reimbursement_unique.py; tests/integration/test_reimbursement_concurrency.py |
| EC-14 | Multi-level approval | main dataset (normal) | emerges from amounts/durations above L1 thresholds; expect >= 150 requests | approval_engine | MULTI_LEVEL_ROUTE, expected NEGATIVE; expected_route recorded | Sequential steps L1 -> L2 -> ... | tests/unit/test_approval_engine_parametrized.py |
| EC-15 | Invalid or expired policy reference | main dataset | 8 claims referencing a superseded XPOL V1 whose effective_end < submission date | policy_resolver (version effective on date != referenced version) | POLICY_VERSION_EXPIRED, POSITIVE | ESCALATED_FOR_REVIEW (ASM-033) | tests/unit/test_policy_resolution.py |
| EC-16 | Invalid lifecycle transition | tests/fixtures/negative only | fixture JSON: e.g. DRAFT -> APPROVED, REJECTED -> PENDING_APPROVAL (8 fixtures) | lifecycle.transition() raises IllegalTransition; validation/dates_lifecycle flags | fixture label INVALID_LIFECYCLE_TRANSITION | Operation refused; processing_failure not used (business refusal) | tests/unit/test_state_machine_transitions.py; tests/validation/test_negative_fixtures_detected.py |
| EC-17 | Claim total fails reconciliation | tests/fixtures/negative only | fixture: claim.total != sum(lines) and seven other arithmetic mismatches (8 fixtures) | validation/arithmetic.py; DB CHECK cannot span tables, so a deferred trigger in test DB | fixture label CLAIM_TOTAL_MISMATCH | Validation report lists it; never in main dataset | tests/validation/test_arithmetic.py |
| EC-18 | Repeated submission or processing attempt | idempotency_record table | 8 replays of an existing submit with the same idempotency key | idempotency_service | REPEATED_SUBMISSION, POSITIVE (record = idempotency key) | Same response returned; no second request row; audit event IDEMPOTENT_REPLAY | tests/integration/test_idempotency_submit.py |
| EC-19 | No valid approval path (AM-B9) | main dataset | 8 requests (4 leave, 4 expense): manager terminated with no delegate and no skip-level, or G7 requester | approval_engine | NO_VALID_APPROVAL_PATH, POSITIVE | ESCALATED_FOR_REVIEW | tests/unit/test_no_valid_path.py |
| EC-20 | Rule conflict (AM-B10) | tests/fixtures/negative + unit test config | 2 fixture rule sets (expense, leave) with two equal-priority rules of different outcome | approval_engine | RULE_CONFLICT | ESCALATED_FOR_REVIEW | tests/unit/test_rule_conflict.py |
| EC-21 | Budget exceeded (AM-B11) | main dataset | 8 claims whose reservation exceeds available budget of a low-budget cost center | budget_service | BUDGET_EXCEEDED, POSITIVE | ESCALATED_FOR_REVIEW; finance override path with reason code | tests/unit/test_budget_ledger.py |
| EC-22 | Overlap with pending leave (AM-B6) | main dataset | 8 requests overlapping a PENDING_APPROVAL request | leave_request_service | OVERLAPPING_PENDING_LEAVE, POSITIVE (soft) | ESCALATED_FOR_REVIEW | tests/unit/test_overlaps.py |
| EC-23 | Sick leave > 3 days without certificate flag (AM-B8) | main dataset | 8 requests | leave_request_service | MEDICAL_CERT_REQUIRED, POSITIVE | RETURNED_FOR_CORRECTION | tests/unit/test_medical_cert.py |
| EC-24 | Terminated manager with active delegation (AM-B9) | main dataset (normal) | 8 requests (4 leave, 4 expense) routed to delegate | approval_engine + delegation lookup | DELEGATED_ROUTE, expected NEGATIVE | Delegate approves at L1 | tests/unit/test_delegation.py |
| EC-25 | Technical processing failure (spec section 3) | processing_failure table | simulation: 5 failed payment attempts (PAYMENT_FAILED) then retry | reimbursement_service | PROCESSING_FAILURE, expected NEGATIVE for anomaly metrics | Reimbursement FAILED -> PROCESSING -> COMPLETED on retry | tests/unit/test_reimbursement_retry.py |

### Boundary records (AM-E5)

| BC | Boundary | Count | Expected outcome (ASM-009, ASM-013 inclusivity: lower exclusive, upper inclusive) | Test |
|---|---|---|---|---|
| BC-01 | Expense amount exactly 200.00 USD-equivalent | 3 | L1 only (<= 200) | tests/unit/test_thresholds_from_config.py |
| BC-02 | Expense amount exactly 1,000.00 and 5,000.00 USD-equivalent | 3 + 3 | L1+L2 (<= 1,000); L1+L2+L4 (<= 5,000) | same |
| BC-03 | Leave quantity exactly 5.0 and 10.0 days | 3 + 3 | L1 (<= 5); L1+L2 (<= 10) | same |
| BC-04 | Leave quantity exactly equal to available balance | 3 | Approved; balance becomes 0 | tests/unit/test_leave_validation_parametrized.py |
| BC-05 | Expense on employment start date and on employment end date | 3 + 3 | Valid (inclusive bounds) | tests/unit/test_expense_validation_parametrized.py |
| BC-06 | Leave starting on a public holiday | 3 | Holiday excluded from quantity; valid if remaining business days > 0 | tests/unit/test_business_days.py |
| BC-07 | Request submitted on a policy effective_end date | 3 | Policy still applicable (inclusive end) | tests/unit/test_policy_resolution.py |
| BC-08 | Line amount exactly at receipt threshold (25 USD-equivalent) | 3 | Receipt required (>=) | tests/unit/test_receipt_requirement.py |
| BC-09 | Line amount exactly at per-line limit | 3 | Not a breach (<=) | tests/unit/test_partial_approval.py |
| BC-10 | Split-claim pair whose combined total is exactly the threshold | 2 groups | Flagged (>=) | tests/unit/test_split_claim_detector.py |

## 7. Conflicts found between the original spec and the amendments

Each conflict is resolved in favour of the amendments (CLAUDE.md precedence). Listed so you can confirm.

| CF | Original spec says | Amendment says | Resolution applied in Phase 1 docs |
|---|---|---|---|
| CF-01 | Part 1 Entities: "For deliberate anomaly cases, keep an issue_type/ground_truth label rather than silently corrupting unrelated rows" (reads as a column on the record) | AM-E1: no is_anomaly / issue_type columns in operational tables | Labels live only in ground_truth schema and files; operational tables carry exception_class and request_exception rows produced by the system itself, which are outputs, not labels |
| CF-02 | Section 3: "Technical processing failures" is one of the statuses the system must distinguish | AM-D3: technical failures live in ProcessingFailure, never in workflow_status | processing_failure table; API decision output includes a technical_status field derived from it |
| CF-03 | Section 7 lists PolicyVersion as a possible supporting entity | AM-A6 encodes version in the policy ID (V<n>) | No PolicyVersion table. Each policy row is one version; policy_family + version columns group them (DEC-04) |
| CF-04 | Section 7.5 ExpensePolicy has its own currency and limits | AM-B1: base currency for thresholds is USD | Approval-rule thresholds are in USD and converted at submission; expense-policy limits are stored in the policy's local currency, derived once at generation from USD base values (ASM-012, DEC-05) |
| CF-05 | Section 7.7 "Receipt reference" and "Receipt hash" both on ExpenseLine | AM-C introduces a Receipt entity | receipt table owns the hash; expense_line.receipt_id is the reference; receipt_hash appears on line exports via join, not as a stored duplicate (DEC-10) |
| CF-06 | Part 1 Step 4 asks the baseline volume to "include" anomalies; Step 5 asks for a valid baseline first then injection | AM-A1: anomalies replace or modify baseline rows | Two-pass generation: valid baseline, then in-place modification of a deterministic index set; totals unchanged |
| CF-07 | Section 8 EXPL-<claim-id>-01 and 1-10 lines | AM-A6: line number is 2 digits 01..10; AM-A5 resubmission is allowed and may change lines | Line numbers continue across submission rounds (11, 12, ...) up to 99; baseline rounds stay within 01..10 (DEC-11) |
| CF-08 | Section 13.3 "If rules conflict ... route to explicit exception state" | AM-B10: highest priority wins; only equal priority with different outcome is a conflict | Amendment is a refinement; implemented as written in AM-B10 |
| CF-09 | Section 14 lists VALIDATING as a request state | AM-D1 keeps it | Kept as a transient state: it appears in request_status_event history but no request rests in it at AS_OF_DATE (DEC-08) |
| CF-10 | Section 6 example command passes --employees, --leave-requests, --expense-claims | AM-A8: changing the volume of one stage must not reshuffle others | Independent streams per stage. Changing --employees necessarily changes which employees downstream records reference (fewer parents), but the leave and expense streams themselves are unchanged; documented in docs/07 section 4 |
| CF-11 | Section 11 item 2 lists overlapping approved leave as an anomaly to generate; section 13.1 requires the engine to reject overlaps | AM-A3: service-layer enforcement; seeded overlaps may exist | Seeded rows represent legacy data that predates enforcement; detector flags them; new submissions are rejected |

Open ambiguities (not conflicts) are listed with proposed defaults in docs/09 section 3.

## 8. Spec section 11 edge cases mapped to scenario IDs and matrix rows (review item 8)

| Spec 11 item | Edge case | Scenario ID(s) in docs/07 section 7.2 | Matrix row(s) in section 6 | Lives in |
|---|---|---|---|---|
| 1 | Negative leave balance | S01 (anomaly), S01b (permitted control) | EC-01, EC-01b | main dataset + ledger |
| 2 | Overlapping approved leave for the same employee | S02 | EC-02 | main dataset |
| 3 | Insufficient leave balance | S03 | EC-03 | main dataset |
| 4 | Leave requests spanning weekends and public holidays | S04 | EC-04 | main dataset (normal, expected negative) |
| 5 | Missing expense receipt | S05 | EC-05 | main dataset |
| 6 | Duplicate receipt hash | S06a (same employee), S06b (cross-employee) | EC-06 | main dataset |
| 7 | Expense policy limit breach | S07a (per line), S07b (per claim) | EC-07 | main dataset |
| 8 | Expense date outside employment dates | S08 | EC-08 | main dataset |
| 9 | Potential split claims designed to evade thresholds | S09 | EC-09 | main dataset |
| 10 | Missing cost center | S10 | EC-10 | main dataset |
| 11 | Approval attempt by the requester | S11 | EC-11 | approval_attempt table |
| 12 | Unauthorised approver | S12 | EC-12 | approval_attempt table |
| 13 | Duplicate reimbursement attempt | S13 | EC-13 | reimbursement_attempt table |
| 14 | Multi-level approval | S14 | EC-14 | main dataset (natural, expected negative) |
| 15 | Invalid or expired policy reference | S15 | EC-15 | main dataset |
| 16 | Invalid lifecycle transition | S16 | EC-16 | tests/fixtures/negative |
| 17 | Claim total that fails reconciliation | S17 | EC-17 | tests/fixtures/negative |
| 18 | Repeated submission or processing attempt | S18 | EC-18 | idempotency_record table |

Amendment-driven additions beyond spec section 11: S19 / EC-19 no valid approval path, S20 / EC-20 rule conflict, S21 / EC-21 budget exceeded, S22 / EC-22 overlap with pending leave, S23 / EC-23 medical certificate, S24 / EC-24 delegated route, S25 / EC-25 processing failure, S26 currency mismatch (validation check from spec 13.2, no separate EC row), boundary cases BC-01..BC-10.
