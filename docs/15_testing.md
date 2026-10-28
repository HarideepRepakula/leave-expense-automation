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

| tests/data/test_anomalies_and_ground_truth.py (Phase 4) | no | exact volumes after S5, planned = actual per scenario, 176 planted anomaly records (56 leave + 120 expense), one planted scenario per record, labels agree with expectations, natural labels complete, carry-ins (8+ claims at L5, natural split pair is_planted=false, S19 = G7 requester), legacy USAGE reconciles, receipts and ids consistent after edits, oracle accrual = ledger |
| tests/reference/ (Phase 4) | no | hand-built organisation: routing bands, G7 covering L1+L2 in one step, dedupe, substitution, delegation, rule-conflict fixtures, split window and threshold, half-day overlap, outcome precedence, accrual agreement |
| tests/validation/ (Phase 4) | no | the real export passes all 21 checks (M1 = M2 = 0, M3 = 1.0), reader round-trip, ground-truth files in the manifest, every negative fixture caught by its check |
| tests/test_ground_truth_isolation.py, tests/test_reference_independence.py (Phase 4) | no | no operational module imports or names ground truth; the oracle shares no code with services/data; only the S9 stage uses the oracle |
| tests/fixtures/negative/ (Phase 4) | no | 8 lifecycle (S16), 8 arithmetic (S17), 3 structural, 2 rule-conflict (S20) fixtures; built by scripts/build_negative_fixtures.py |

| tests/unit/test_business_days.py, test_leave_balance.py, test_leave_validation.py (Phase 5) | no | BR-CAL matrix (weekends and holidays per country, inclusive ends, no substitution, half days, year split); balance rules (floor, carry-forward incl. negative and cap, per-year available incl. scheduled accrual and part start, reservations, year without balance, accrual mismatch, usage postings, snapshot reconciliation); every leave code, severity precedence, overlaps with the half-day boundary, cross-year per-year check, UNPAID cap, input errors, transition table (all 81 pairs), catalogue classification, detectors and replay. World in tests/unit/leave_world.py |
| tests/data/test_leave_services_on_dataset.py (Phase 5) | no | full and starter scale: services agree with the oracle on every leave request (only ROUTING_PHASE7 differences, exactly the S19-L records); leave detections = planted leave labels; replay posts exactly the legacy USAGE; cross-year share 2.5-3.5 percent; scenarios_not_reached warning and manifest entry |
| tests/db/test_leave_submission_db.py (Phase 5) | yes | PostgreSQL store: request update, three status events, exception rows, RSE/REX ids from id_sequence, row locks on leave_request and leave_balance |

| tests/unit/test_expense_validation.py (Phase 6) | no | every expense code and its route, USD half-up rounding, line PASS/CAPPED/FAIL and approved amount, budget reservation and release, duplicate receipts, claim pattern, split windows and threshold, batch detectors, input errors, policy configuration error |
| tests/data/test_expense_services_on_dataset.py (Phase 6) | no | full and starter scale: services agree with the oracle on every claim (only ROUTING_PHASE7, exactly S19-E); expense detections = expense labels; quantity x unit = amount on every line |
| tests/db/test_expense_submission_db.py (Phase 6) | yes | PostgreSQL store: claim and line updates, status events, exception rows, CCT reservation and release with committed_amount, row locks on claim, cost center and budget |

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
