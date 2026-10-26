# 15. Testing instructions

## Layout

| Folder | Needs database | Content (Phase 2) |
|---|---|---|
| tests/test_project_layout.py | no | folder structure, .env.example hygiene, .gitignore |
| tests/test_no_wallclock_usage.py | no | amendment A7: no datetime.now in src/ |
| tests/test_dictionary_matches_models.py | no (needs SQLAlchemy) | every model table and column is in docs/10 and vice versa |
| tests/db/ | yes (lea_test) | schema entities, ID and enum CHECKs, employee and date rules, exactly-one request FK, expense claim and line rules, reimbursement uniqueness and trigger, append-only and immutability triggers, leave balance generated column, test-only EXCLUDE constraint, role permissions, migration cycle |

Later phases add tests/unit, tests/integration, tests/api, tests/analytics, tests/validation, tests/evaluation, tests/reference and tests/fixtures/negative.

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
