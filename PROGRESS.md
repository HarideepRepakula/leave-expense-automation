Project: Enterprise Leave and Expense Approval Automation System

Current phase: Phase 3 (Synthetic master data and transaction generator)
Status: COMPLETE AND VERIFIED 2026-10-28. Waiting for "APPROVED PHASE 3". Do not start Phase 4 before that.

Phase 1: APPROVED 2026-10-26 (review round 1 applied; S19 split into S19-L / S19-E for clear subtotals).
Phase 2: APPROVED 2026-10-26, including DEC-30 to DEC-36.

## Phase 3 record

Scope implemented (docs/07 stages): S1 master (all 14 master tables), S2 balances (OPENING 2025 + ACCRUAL;
CARRY_FORWARD and USAGE deferred to Phase 7), S3 leave raw inputs (800), S4 expense raw inputs (1,000 claims,
1-10 lines, receipts), canonical CSV/JSON export, SQL seed, manifest with SHA-256 per file, loader into
lea_dev, reproducibility scripts. Valid baseline only (DEC-41); anomalies, boundaries and ground truth are
Phase 4 (docs/07 does not place any of them in Phase 3). Requests rest in SUBMITTED (about 1% DRAFT) until the
Phase 7 engine runs S6 (AMB-P3-01).

Deferred by dependency (DEC-01): S5 anomalies + boundaries and S9 ground truth (Phase 4); S6 outcomes, budget
ledger postings, carry-forward and usage (Phase 7, needs Phases 5-6 services); S7 reimbursements and S8 audit
(Phase 8); exception_code catalogue load (Phase 4/5, needs config/exception_codes.yaml templates).

Files created:
- config/: generation.yaml, organisation.yaml, leave_policies.yaml, expense_policies.yaml, approval_rules.yaml, calendar.yaml
- src/common/: clock.py, rng.py, money.py (ids.py extended with formatters)
- src/services/: calendar_service.py, leave_balance_service.py, policy_resolver.py (pure functions brought forward, DEC-37)
- src/data/: config_loader.py, dataset.py, sampling.py, export.py, loader.py, generate.py, compare_runs.py,
  stages/__init__.py, stages/master.py, stages/balances.py, stages/leave.py, stages/expenses.py
- scripts/: reproducibility_check.ps1, reproducibility_check.sh
- tests/: data/conftest.py, data/test_generator_baseline.py, data/test_generator_reproducibility.py,
  unit/test_calendar_and_accrual.py, db/test_generator_load.py
- docs/11_generation_guide.md; data/manifest.json (committed; data/raw and data/processed stay git-ignored)
Files changed: src/common/ids.py, requirements.txt, pyproject.toml (0.3.0, pinned deps), docs/07 (final command),
docs/09 (section 7: ASM-P3-01..18, DEC-37..41, AMB-P3-01..04), docs/15_testing.md, README.md, PROGRESS.md.
Packages installed into .venv: numpy 2.2.6, Faker 37.4.0, PyYAML 6.0.2, bcrypt 4.3.0.

Commands:
    python -m src.data.generate --seed 20261022 --employees 400 --leave-requests 800 --expense-claims 1000 --load
    python -m src.data.generate --seed 20261022 --employees 40 --leave-requests 80 --expense-claims 100 --out data\starter
    .\scripts\reproducibility_check.ps1
    pytest -q

REAL results (2026-10-28):
- Full run with --load: 20 tables, counts in lea_dev equal generated counts (employee 400, leave_policy 6,
  leave_request 800, expense_claim 1000, expense_line 3201, receipt 2922, leave_balance 1909,
  leave_balance_transaction 13062, application_user 401, user_role 596, delegation 10, ...); 42 files exported; 5.7 s.
- Dataset fingerprint (seed 20261022, 400/800/1000): e8758c8f06b424b4e3cf6846ee6110c1f6f3d5d6f7b56dbf23e6a3b4bf72b64b
- reproducibility_check.ps1 (full scale): files compared 42, identical SHA-256 42, RESULT: REPRODUCIBLE, exit 0.
- pytest -q: 132 passed in 19.17s (81 Phase 2 + 51 Phase 3; 0 failed, 0 skipped). New tests passed on the first run.
- ruff --select F,E9 on Phase 3 files: All checks passed.

Observations measured on the full baseline (input for Phase 4 natural-violation labelling):
- Natural split-claim candidate pairs: 1. Budgets exceeded by submitted claims: none (CC-0024 included), so S21 must be planted.
- Claims by USD band: <=200: 398, 200-1000: 411, 1000-5000: 190, >5000: 1 (L5 route barely exercised naturally).
- Leave: quantity 5-10: 113, >10: 37; cross-year: 1 (UNPAID); spanning a holiday: 32 (S04 needs >= 40, planted in Phase 4).
- 30 employees report directly to the G7; 15 leave + 49 expense requests of theirs need an L2 that does not exist (AMB-P3-03).

Open issues / for owner decision:
- AMB-P3-01..04 in docs/09 section 7.3 (workflow state before Phase 7; cross-year balance at submission;
  G7 direct reports and L2; leave type mix shift from re-drawing).
- .env JWT_SECRET value was printed once in this session's tool output while checking the environment
  (not committed, not sent anywhere). Recommend generating a new value before Phase 9.
- OneDrive copy of the project still to be deleted by the owner (from the relocation note).
- Groq names and limits (ASM-051, ASM-052) still unverified until Phase 9.

Acceptance criteria (spec section 25) after Phase 3:
1 schema executable: MET (unchanged; full dataset loads and every CHECK/FK/trigger accepts it).
2 entities and relationships present: MET; now populated (FK resolution test over every generated table).
17 fixed-seed generator reproducible: MET for Phase 3 stages (two runs, 42/42 identical SHA-256; test at both scales).
21 automated tests run: MET for current scope (132 passed).
22 documentation explains how to reproduce: PARTIAL (docs/11 for generation; full README in Phase 12).
10, 15, 16: PARTIAL at DB level (unchanged from Phase 2).
3-9, 11-14, 18-20: NOT STARTED (anomalies, ground truth, services, API, dashboard in later phases).

Next phase: Phase 4 (ground-truth generation and validation framework) after "APPROVED PHASE 3".

## Phase 2 and relocation record (history)

Project relocation (2026-10-26): project copied by the owner from OneDrive to C:\projects\leave-expense-automation.
- Verified: both copies identical (87 files each, byte-for-byte). The OneDrive copy still exists and should be deleted by the owner once this location is confirmed; otherwise OneDrive keeps syncing a stale duplicate that also contains .env.
- .venv recreated at the new location (Python 3.11.7; same package versions as before) and requirements reinstalled.
- Real output from the new location:
    alembic current  ->  0001_initial_schema (head)
    pytest -q        ->  81 passed in 9.58s
- Git repository initialised at the new location; .env and .venv untracked; first commit "Phase 1 and 2: design docs, schema and migrations" (see git log).

Phase 2 record (kept for history):
Status at close: COMPLETE AND VERIFIED 2026-10-26. Migration applied to lea_dev; full test suite passes (81 passed).

Environment (verified 2026-10-26):
- Windows 11 Home, Python 3.11.7 (allowed: requires-python >= 3.11), pip 25.2, Git 2.50.1.
- PostgreSQL 16.15 installed locally (option A, winget), service postgresql-x64-16 running on port 5432; psql at C:\Program Files\PostgreSQL\16\bin.
- Docker not installed (not needed; docker-compose.yml kept as the documented alternative).
- .env created from .env.example with generated letters-and-numbers passwords (never printed); roles and databases created by the owner via scripts/init_local_db.ps1.
- Project venv .venv with SQLAlchemy 2.1.6, alembic 1.20.1, psycopg 3.3.6, pydantic 2.14.1, pydantic-settings 2.16.1, python-dotenv 1.2.4, pytest 8.4.2.

Completed in Phase 2:
- Scaffold: pyproject.toml, requirements.txt, .env.example, .gitignore, docker-compose.yml, README.md, folder tree from spec section 21 with placeholder packages.
- SQL: sql/init/01_roles.sql, sql/init/02_test_database.sql, sql/triggers.sql, sql/grants.sql, sql/test_only_constraints.sql.
- Models: src/common/{enums,ids,config}.py; src/models/{base,master,policies,leave,expenses,approvals,reimbursement,audit,security,ground_truth}.py; 33 ops tables + 4 ground_truth tables.
- Alembic: alembic.ini, migrations/env.py, migrations/versions/0001_initial_schema.py.
- Tests: tests/conftest.py; tests/db/ (9 files, 74 tests); 3 database-free test files (7 tests); 81 in total.
- Docs: docs/10_data_dictionary.md (37 tables, every column; matches models by test), docs/14_setup.md, docs/15_testing.md; corrections to docs/04 and docs/06.
- Scripts: scripts/init_local_db.ps1 (used successfully by the owner).

REAL run results (2026-10-26):
- alembic upgrade head on lea_dev:
    INFO  [alembic.runtime.migration] Running upgrade  -> 0001_initial_schema, Initial schema: ops and ground_truth schemas, all tables, triggers and grants.
    exit 0
- lea_dev after migration: ops 33 tables, ground_truth 4 tables, alembic_version = 0001_initial_schema;
  triggers: trg_append_only x16 (8 tables x UPDATE/DELETE), trg_pk_immutable x33, trg_decided_step_frozen x1, trg_no_self_approval x2, trg_reimbursement_eligibility x2, trg_idempotency_guard x2;
  constraints in ops: 173 CHECK, 55 FK, 33 PK, 13 UNIQUE.
- pytest -q, first run: 5 failed, 76 passed in 10.93s.
  Failure 1: test_line_numbers_unique_per_claim... asserted the UNIQUE(claim, line_number) name, but the derived-ID CHECK makes a duplicate line number collide on the primary key first. Test expectation fixed (match "duplicate key value"). Schema unchanged.
  Failures 2-5: role tests built the connection URL with str(URL), which SQLAlchemy masks to '***'. Fixed with render_as_string(hide_password=False). Schema and roles unchanged (psql login as each role succeeded with .env passwords).
  Also added path_separator = os to alembic.ini to remove a deprecation warning.
- pytest -q, second run: 81 passed in 9.96s (0 failed, 0 skipped).
- Test-only EXCLUDE constraint excl_no_overlapping_approved_leave: present in lea_test, absent in lea_dev (amendment A3).

Phase 2 decisions (for approval):
- DEC-30 Initial migration uses metadata.create_all plus SQL files; later migrations use explicit Alembic operations.
- DEC-31 Enums stored as text with CHECK constraints generated from src/common/enums.py (no PostgreSQL ENUM types).
- DEC-32 id_sequence table for API-side ID allocation; the generator assigns IDs deterministically without it.
- DEC-33 Expense line currency consistency enforced by the service, not the database (planted S26 must exist).
- DEC-34 idempotency_record allows status updates; DELETE and key-field changes are blocked.
- DEC-35 Only audit_event and processing_failure remain polymorphic; all request references are real FKs (DEC-03).
- DEC-36 UNIQUE(expense_claim_id, line_number) kept although redundant with PK + derived-ID CHECK (documents intent; harmless).

Open issues:
- Project lives inside OneDrive; .venv and .env are synced unless OneDrive is paused. Suggest moving to C:\projects before Phase 3 (owner's call).
- Folder is not a git repository yet; `git init` recommended before Phase 3 so each phase can be committed.
- Groq model names and rate limits (ASM-051, ASM-052) remain unverified until Phase 9.

Acceptance criteria status (spec section 25):
1 schema executable: MET (alembic upgrade head exit 0 on lea_dev; downgrade/upgrade cycle test passes).
2 required entities and relationships present: MET (test_schema_entities, 33 + 4 tables, FK integrity tests).
10 self-approval prevented: PARTIAL at DB level (trigger test passes); service-level guard arrives in Phase 7.
15 duplicate reimbursement prevented: PARTIAL at DB level (partial unique index test passes); idempotent service arrives in Phase 8.
16 audit history preserved: PARTIAL at DB level (append-only trigger tests pass); audit service arrives in Phase 8.
3-9, 11-14, 17-22: NOT STARTED (later phases).

Next phase: Phase 3 (synthetic master data and transaction generator) after "APPROVED PHASE 2".
