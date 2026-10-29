# 15. Testing instructions

## Layout

| Folder | Needs database | Content (Phase 2) |
|---|---|---|
| tests/test_project_layout.py | no | folder structure, .env.example hygiene, .gitignore |
| tests/test_no_wallclock_usage.py | no | amendment A7: no datetime.now in src/ |
| tests/test_dictionary_matches_models.py | no (needs SQLAlchemy) | every model table and column is in docs/10 and vice versa |
| tests/db/ | yes (lea_test) | schema entities, ID and enum CHECKs, employee and date rules, exactly-one request FK, expense claim and line rules, reimbursement uniqueness and trigger, append-only and immutability triggers, leave balance generated column, test-only EXCLUDE constraint, role permissions, migration cycle; Phase 3: test_generator_load.py loads the starter dataset into lea_test (every CHECK, FK and trigger must accept it), compares counts, then truncates ops |
| tests/data/ (Phase 3) | no | test_generator_baseline.py: exact volumes at full and starter scale, ID formats, PK uniqueness, FK resolution, hierarchy and authority structure, ledger = snapshot, validity of every leave request and expense claim; test_generator_reproducibility.py: two runs give identical row counts and SHA-256 per file (full and starter), a different seed changes the data, canonical CSV, stream independence |
| tests/unit/ (Phase 3) | no | test_calendar_and_accrual.py: hand-built cases for business days, quantities, year split, accrual, annual grant, rounding, version resolution |

| tests/data/test_anomalies_and_ground_truth.py (Phase 4) | no | exact volumes after S5, planned = actual per scenario, 176 planted anomaly records (56 leave + 120 expense), one planted scenario per record, labels agree with expectations, natural labels complete, carry-ins (8+ claims at L5, natural split pairs is_planted=false and planted S09 detected exactly, S19 = a G7 requester, one G7 per country), legacy USAGE reconciles, receipts and ids consistent after edits, oracle accrual = ledger |
| tests/reference/ (Phase 4) | no | hand-built organisation: routing bands, G7 covering L1+L2 in one step, dedupe, substitution, delegation, rule-conflict fixtures, split window and threshold, half-day overlap, outcome precedence, accrual agreement |
| tests/validation/ (Phase 4) | no | the real export passes all 21 checks (M1 = M2 = 0, M3 = 1.0), reader round-trip, ground-truth files in the manifest, every negative fixture caught by its check |
| tests/test_ground_truth_isolation.py, tests/test_reference_independence.py (Phase 4) | no | no operational module imports or names ground truth; the oracle shares no code with services/data; only the S9 stage uses the oracle |
| tests/fixtures/negative/ (Phase 4) | no | 8 lifecycle (S16), 8 arithmetic (S17), 3 structural, 2 rule-conflict (S20) fixtures; built by scripts/build_negative_fixtures.py |

| tests/unit/test_business_days.py, test_leave_balance.py, test_leave_validation.py (Phase 5) | no | BR-CAL matrix (weekends and holidays per country, inclusive ends, no substitution, half days, year split); balance rules (floor, carry-forward incl. negative and cap, per-year available incl. scheduled accrual and part start, reservations, year without balance, accrual mismatch, usage postings, snapshot reconciliation); every leave code, severity precedence, overlaps with the half-day boundary, cross-year per-year check, UNPAID cap, input errors, transition table (all 81 pairs), catalogue classification, detectors and replay. World in tests/unit/leave_world.py |
| tests/data/test_leave_services_on_dataset.py (Phase 5, 7A) | no | full and starter scale: services (with routing) agree with the oracle on every leave request incl. rule, route and steps; ROUTING_PHASE7 = 0; exactly the S19-L records escalate with NO_VALID_APPROVAL_PATH; leave detections = planted leave labels; replay posts exactly the legacy USAGE; cross-year share 2.5-3.5 percent; scenarios_not_reached warning and manifest entry |
| tests/db/test_leave_submission_db.py (Phase 5) | yes | PostgreSQL store: request update, three status events, exception rows, RSE/REX ids from id_sequence, row locks on leave_request and leave_balance |

| tests/unit/test_expense_validation.py (Phase 6) | no | every expense code and its route, USD half-up rounding, line PASS/CAPPED/FAIL and approved amount, budget reservation and release, duplicate receipts, claim pattern, split windows and threshold, batch detectors, input errors, policy configuration error |
| tests/data/test_expense_services_on_dataset.py (Phase 6, 7A) | no | full and starter scale: services (with routing) agree with the oracle on every claim incl. rule, route and steps; ROUTING_PHASE7 = 0; exactly S19-E escalate with NO_VALID_APPROVAL_PATH; expense detections = expense labels; quantity x unit = amount on every line |
| tests/db/test_expense_submission_db.py (Phase 6) | yes | PostgreSQL store: claim and line updates, status events, exception rows, CCT reservation and release with committed_amount, row locks on claim, cost center and budget |
| tests/unit/test_approval_routing.py (Phase 7A) | no | routing matrix: bands lower-exclusive / upper-inclusive at every boundary, priority, RULE_CONFLICT, lowest id on equal outcome, inactive / not effective rules, L1-L5 resolution, covered_levels, substitution (requester, ended employment, delegation, delegate chain), L5 per country, two candidates; steps at submission only for PENDING_APPROVAL (leave and expense, in memory) |
| tests/db/test_approval_steps_db.py (Phase 7A) | yes | both PostgreSQL stores write approval_step (covered_levels, first step assigned) and the ASSIGNED approval_event; unresolved level -> ESCALATED with a request_exception row and no step; the covered_levels CHECKs |
| tests/db/test_roles_and_migration_cycle.py (Phase 7A addition) | yes | migration 0002 down to 0001 and up again: column and CHECKs removed and restored, existing decided step backfilled and still frozen |

tests/data/test_generator_baseline.py (Phase 5 change): the Phase 3 test of the conservative balance guard is replaced
by an independent check: the reference oracle finds no exception code on any baseline request.

tests/db/test_generator_load.py (Phase 4): lea_test has the test-only EXCLUDE constraint (amendment A3), so loading
the dataset with the planted S02 overlaps must FAIL there (tested); the count test lifts that one constraint for its
own load and restores it afterwards. It also loads the ground_truth schema.

Later phases add tests/integration, tests/api, tests/analytics and tests/evaluation.

## Commands (PowerShell, venv active, from the project root)

```powershell
pytest -q                 # everything; db tests skip with a reason if lea_test is unreachable
pytest -q -m db           # only database tests
pytest -q -m "not db"     # only tests that need no database
pytest -q tests/db/test_reimbursement_constraints.py -k duplicate   # one area
pytest -q --tb=short -ra  # short tracebacks and a summary of skips/failures
```

## How the database tests work

1. The session fixture reads TEST_DATABASE_URL, refuses any database whose name does not end with `_test`, runs `alembic downgrade base` then `alembic upgrade head`, and applies sql/test_only_constraints.sql.
2. Each test gets a connection inside an outer transaction that is rolled back afterwards, so tests never see each other's rows and the database is clean at the end.
3. Expected failures are executed inside a savepoint (`expect_db_error` in tests/conftest.py) and the error text is matched against the constraint or trigger name.
4. The role tests connect as lea_app, lea_analytics_ro and lea_evaluation using the passwords in .env; they skip if a password is empty.
5. Timestamps in tests are fixed values inside the dataset window; the wall clock is never used (amendment A7).

## Reporting rule

Real output only. PROGRESS.md and the end-of-phase report quote the actual pytest summary line; a run that was not executed is reported as NOT RUN with the reason.

## Phase 7B tests

- tests/unit/test_approval_decisions.py: every guard, higher-level authority, idempotent replay and conflict, reject / return effects, resubmission (round 2, ids and history kept, maximum rounds), expense approved amount, RELEASE and resubmitted lines, process-owner send-on / reject, L4 budget override, the decision-time rule (more than 24 hours after assignment).
- tests/unit/test_leave_balance.py: year-end CARRY_FORWARD rows replace the recompute.
- tests/db/test_approval_decisions_db.py: the same decisions, process-owner decisions and resubmission through the PostgreSQL stores (attempt and idempotency rows, committed_amount, lines of round 2, LBT ids per year).
- tests/data/test_outcomes_on_dataset.py: S6 on the generated dataset at both scales (timing, S22 partners, status at as-of = ground truth, carry-forward rows, approved amounts, legacy markers).

## Phase 8A tests

- tests/unit/test_reimbursement_and_audit.py: reimbursement at final approval (one row, amount = approved amount, currency, final step, actor SYSTEM); none for rejected, returned or pending claims; manual create guards (CLAIM_NOT_APPROVED, DUPLICATE_REIMBURSEMENT, AMOUNT_MISMATCH on amount or currency), replay and conflict; ZERO_APPROVED_AMOUNT; payment fail -> processing_failure -> RETRY -> COMPLETED with ACTUAL and RELEASE; illegal transitions; cancel reasons; the transition table; audit rows for submissions, blocked and accepted decisions, process-owner decisions, skipped steps, replays and reassignment; cancellation by the requester (steps cancelled, reservation released, no attempt).
- tests/db/test_reimbursement_and_audit_db.py: SqlWorkflow.record_reassignment (carried over from 7B); reimbursement row accepted by the eligibility trigger, RMB / RMA / PFL / AUD ids, payment failure and retry, ACTUAL with committed_amount and actual_amount, SYSTEM idempotency scope; duplicate create blocked by the guard and, in a simulated race, by the partial unique index (savepoint); run_recording_failure (rollback, processing_failure in a second transaction, business errors pass through); cancellation.
- tests/reference/test_reference_oracle.py::test_status_at_as_of_depends_on_the_departed_approver_reassignment: hand-built oracle case (delays pinned to 1 business day) where the status at as-of is APPROVED without the reassignment and PENDING_APPROVAL with it (carried over from 7B).
- tests/db/test_leave_submission_db.py: id_sequence now also has the AUD scope (3 audit rows per submission).

## Phase 8B-1 tests

- tests/data/test_outcomes_on_dataset.py: one reimbursement per claim APPROVED at as-of with its approved amount,
  currency and employee; completed_at only on COMPLETED and before as-of; S13 BLOCKED attempts and S25
  processing_failure rows equal their ground-truth labels; ACTUAL = approved amount for every completed payment;
  audit ids follow time; one audit row per request transition.
- tests/data/test_anomalies_and_ground_truth.py and test_expense_services_on_dataset.py: S13 / S25 counted and
  excluded from the exception-code and detector comparisons (they are attempt and failure rows).
