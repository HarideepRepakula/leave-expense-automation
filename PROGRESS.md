Project: Enterprise Leave and Expense Approval Automation System

Current phase: Phase 3 (Synthetic master data and transaction generator)
Status: NOT STARTED. Waiting for the owner's Phase 3 prompt.

Phase 1: APPROVED 2026-10-26 (review round 1 applied; S19 split into S19-L / S19-E for clear subtotals).
Phase 2: APPROVED 2026-10-26, including DEC-30 to DEC-36.

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
