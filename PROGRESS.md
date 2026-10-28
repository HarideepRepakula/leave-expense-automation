Project: Enterprise Leave and Expense Approval Automation System

Current phase: Phase 6 (Expense validation and expense claim services)
Status: IN PROGRESS (started 2026-10-28 after "APPROVED PHASE 5").

Phase 1: APPROVED 2026-10-26 (review round 1 applied; S19 split into S19-L / S19-E for clear subtotals).
Phase 2: APPROVED 2026-10-26, including DEC-30 to DEC-36.
Phase 3: APPROVED 2026-10-28. Owner verified fingerprint e8758c8f... and "132 passed" independently.
  Owner decision on the cross-year rule (AMB-P3-02): the generator keeps the stricter posted-ledger guard;
  Phase 5 implements the per-year rule (docs/05 BR-LBAL-09). Consequences recorded for Phase 5:
  - the dataset fingerprint WILL change when Phase 5 relaxes the guard (expected, not a defect);
  - Phase 5 must measure the cross-year share of leave requests and check it against ASM-042 (about 3 percent;
    Phase 3 baseline has 1 of 800).
Phase 4: APPROVED 2026-10-28. Owner re-ran validation, the reproducibility check (53 of 53 identical,
  fingerprint 67515636...) and pytest (238 passed) independently. Decisions AMB-P4-01..07 accepted as applied.
  - S19 limitation (all 8 S19 cases are one employee, the G7) is to be revisited in Phase 7.
  - Phase 4 cleanup item (owner, 2026-10-28): when a dataset (e.g. the starter scale) cannot reach a scenario,
    the generator prints a clear warning and the manifest records which scenarios were not generated
    (or were only partly generated). Scheduled as the first task of Phase 5.

Phase 5: APPROVED 2026-10-28. AMB-P5-01..04 accepted as applied. The OneDrive copy is already deleted (item closed).

## Phase 5 record

Scope implemented (spec 26 Phase 5; docs/05 sections 1, 2, 9; docs/06 sections 2, 8.1; docs/07):
- Business days and half-days (BR-CAL-01..05): calendar_service + half-day check; full parametrised matrix.
- Balance (BR-LBAL-03..09): negative floor, carry-forward (cap, expiry, negative debt), per-year available balance
  at submission incl. accrual scheduled up to the part start (BR-LBAL-09, AMB-P3-02), open reservations, carry-forward
  recomputed until year-end rows exist (BR-LV-13), accrual-ledger mismatch as a technical failure, USAGE postings
  split by year, snapshot reconciliation.
- Validation (BR-LV-01..12) in the fixed order, all codes recorded, severity precedence, exception class.
- Overlap: approved (HARD) and pending (SOFT), complementary half-days on one shared date excepted.
- Submission: DRAFT -> SUBMITTED -> VALIDATING -> outcome through the transition table (lifecycle.py), on an
  in-memory store and on PostgreSQL (row locks FOR UPDATE, request_status_event, request_exception, ids via
  id_sequence).
- Leave batch detectors (OVERLAPPING_APPROVED_LEAVE, NEGATIVE_BALANCE_UNPERMITTED) -> data/validation/detections.csv.
- Services vs oracle comparison for every leave record (src/evaluation). Services import nothing from src/reference
  (independence test passes).
Waits: Phase 7 = routing, approval steps and decisions, NO_VALID_APPROVAL_PATH / RULE_CONFLICT, resubmission, USAGE at
approval, year-end CARRY_FORWARD rows, S6 outcomes written into the dataset (requests stay SUBMITTED, AMB-P3-01);
Phase 8 = audit_event rows and idempotency records on submit.
Generator (DEC-01): S3 and the S5 guards now call the Phase 5 services (DEC-P5-02); the stricter Phase 3 guard is gone.
Year-end requests added to reach ASM-042 (ASM-P5-07, AMB-P5-01).
Phase 4 cleanup item: done (generate.py scenario_shortfalls: stderr WARNING + manifest scenarios_not_reached; tested).
Correction found while doing it: the Phase 4 note on starter shortfalls (BC-07, BC-10, S09, S21, S24) did not match
the committed Phase 4 code, which gives BC-05 (1 of 2) and S09 (2 of 5); verified by building the starter at the
previous commit in a temporary worktree (starter expense tables identical to now). ASM-P4-18 corrected in docs/09.

Files created:
- src/services/: exception_service.py, lifecycle.py, leave_request_service.py, leave_detectors.py, leave_batch.py
- src/repositories/leave_repository.py; src/evaluation/leave_service_vs_oracle.py
- tests/unit/: leave_world.py, test_business_days.py, test_leave_balance.py, test_leave_validation.py
- tests/data/test_leave_services_on_dataset.py; tests/db/test_leave_submission_db.py
Files changed: src/services/{calendar_service,leave_balance_service}.py; src/data/{generate,export}.py;
src/data/stages/{leave,workbench,anomalies,boundaries,balances}.py; src/validation/report.py (write_detections);
config/generation.yaml (leave.year_end); tests/data/test_generator_baseline.py (Phase 3 conservative-guard test replaced
by an independent oracle check); docs/07 (section 13), docs/09 (section 8 approved, ASM-P4-18 corrected, section 9:
ASM-P5-01..11, DEC-P5-01..07, AMB-P5-01..04), docs/11, docs/15; pyproject.toml (0.5.0); data/manifest.json and
data/ground_truth/* (regenerated). No new packages installed.

Commands:
    python -m src.data.generate --seed 20261022 --employees 400 --leave-requests 800 --expense-claims 1000 --load
    python -m src.validation
    python -m src.evaluation.leave_service_vs_oracle
    .\scripts\reproducibility_check.ps1
    pytest -q

REAL results (2026-10-28):
- Full run with --load: exit 0; every ops table count in lea_dev = generated (leave_request 800, expense_claim 1000,
  leave_balance 1909, leave_balance_transaction 13086, ...); every Group A scenario, control and boundary actual =
  planned (S04 60 >= 40, S14 790 >= 150); labels 180 planted positives, 3 natural positives (BUDGET_EXCEEDED 1,
  SPLIT_CLAIM_SUSPECTED 2); scenarios_not_reached = [] at full scale.
- Validation: 21 checks, 0 failed, 8 not applicable; M1 0/24924, M2 0/30350, M3 3757/3757 = 1.0.
- Services vs oracle, all 800 leave requests (DRAFT 8, LEGACY 24, SUBMITTED 768): AGREE 796, ROUTING_PHASE7 4,
  DISAGREE 0. The 4 = the planted S19-L records (G7 requester): the oracle adds NO_VALID_APPROVAL_PATH (final
  ESCALATED_FOR_REVIEW); the Phase 5 services do no routing, so they stop at PENDING_APPROVAL. Starter: AGREE 79,
  ROUTING_PHASE7 1, DISAGREE 0.
- detections.csv: INSUFFICIENT_BALANCE 12, MEDICAL_CERT_REQUIRED 8, OVERLAPPING_PENDING_LEAVE 8 (SUBMISSION);
  OVERLAPPING_APPROVED_LEAVE 16, NEGATIVE_BALANCE_UNPERMITTED 8 (BATCH_DETECTOR) = exactly the planted leave labels
  (tested), none on the S01b permitted-negative controls.
- Cross-year: 24 of 800 = 3.00 percent (submitted 23 of 792 = 2.90 percent); ASM-042 about 3 percent. Natural spans
  alone (year-end share 0) measured 5 of 800 = 0.62 percent; Phase 3/4 had 1 of 800.
- Dataset fingerprint (seed 20261022, 400/800/1000): 7dbe66725d539ad394a81430848a1eaac9003b894275d38d9d3aec6b3c3fa88f
  (changed from 67515636..., as expected). Against Phase 4: 38 files byte-identical (all expense tables, master data,
  users), 15 changed (leave_request, leave ledger and balances, ground truth, seed.sql, validation report), 1 new
  (validation/detections.csv).
- reproducibility_check.ps1 (full scale): 54 files, 54 identical SHA-256 (raw 42, processed 2, ground_truth 5,
  validation 5), RESULT: REPRODUCIBLE, exit 0.
- pytest -q: 349 passed in 56.96s (0 failed, 0 skipped; 238 before + 111 new).
- ruff 0.17.2 --select F,E9 on all Phase 5 files: All checks passed.
Debugging during the phase (reproduce -> root cause -> smallest fix -> rerun):
  1. Generation stopped (DEC-P4-02): S01 LVE-2025-000223 construction [NEGATIVE_BALANCE_UNPERMITTED] != oracle
     [+ OVERLAPPING_APPROVED_LEAVE]. Root cause: S01 lengthens a request and forces it to a legacy approval; the new
     service-based guard cannot see its overlap with an earlier request that is still pending (legacy rows are not
     validated; the detector compares approved pairs only), while the oracle's eventual model approves that request.
     Fix: the generator keeps its Phase 3/4 raw-input rule "no unplanted overlap between submitted requests of one
     employee" (LeaveGuard). Rerun: generation completes, 0 disagreements.
  2. Tests: test_leave_balance_never_exceeded (full, starter) failed by design: it asserted the Phase 3 rule "only
     UNPAID may span leave years". Replaced by an independent oracle check of the baseline (owner decision AMB-P3-02).

Open issues / for owner decision:
- AMB-P5-01..04 in docs/09 section 9.3 (year-end share 0.03; carry-forward before year-end rows; detector counts open
  reservations; decision_reason_code also for RETURNED/ESCALATED). Defaults applied; please confirm or change.
- S19 limitation (all S19 cases are the one G7 employee) stays for Phase 7 as decided.
- The 4 ROUTING_PHASE7 records will only agree fully once the Phase 7 routing exists.
- data/validation/leave_service_vs_oracle.csv is written by the comparison command only; not in the manifest.
- Carried forward: pre-existing unused import in tests/db/test_reimbursement_constraints.py; new JWT_SECRET before
  Phase 9; Groq names and limits (ASM-051/052) unverified until Phase 9; OneDrive copy to delete.

Acceptance criteria (spec section 25) after Phase 5:
1-5, 8: MET (unchanged; full Phase 5 dataset loads into lea_dev; M1 = M2 = 0; volumes exact).
6 leave balances reconcile: MET (V-ARITH-05 1909/1909; balance service rules unit-tested; reconcile_snapshot; replay
  posts exactly the dataset's USAGE rows).
7 business-day calculations work: MET (BR-CAL matrix; V-ARITH-06 800/800; quantity and per-year split equal the
  oracle on all 800 requests).
12 edge cases represented and labelled: PARTIAL (unchanged; attempt scenarios need Phases 7-8).
13 ground truth isolated: MET (isolation and independence tests pass with the new modules).
16 audit history: PARTIAL (DB submission writes request_status_event history; audit_event in Phase 8).
17 reproducible: MET (54/54 incl. detections.csv).
18 validation metrics from actual results: PARTIAL (M1-M3; leave detections ready for M6-M8 in Phase 11).
21 automated tests: MET for current scope (349 passed).
22 documentation: PARTIAL (docs/07, 09, 11, 15 updated; full README in Phase 12).
9, 10, 11, 14, 15, 19, 20: PARTIAL or NOT STARTED as before (Phases 7-10).

Next phase: Phase 6 (expense validation and expense claim services) after "APPROVED PHASE 5".

## Phase 4 record

Scope implemented: S5 anomaly injection (all 18 Group A rows of docs/07 7.2 = 176 records; controls S01b, S04,
S14-L5, S24), S5 boundary records BC-01..BC-10, the independent reference oracle (src/reference), S9 ground truth
(files + ground_truth schema), the validation framework (src/validation, 21 checks, M1-M3), negative fixtures
(S16 x8, S17 x8, S20 x2, 3 structural), exception_code catalogue, isolation and independence tests.
Anomalies only MODIFY existing rows: volumes stay exactly 400 / 6 / 800 / 1,000 (tested at both scales).
Waits for later phases (listed in scenarios.json with actual_count NULL): S11, S12, S18 (Phase 7 steps and
idempotency), S13 and S25 (Phase 8), at-as-of timing of outcomes (Phase 7, ASM-P4-03), detections.csv (Phase 5-6).

Carry-ins done: >= 8 claims at L5 (S14-L5: 8, tested); natural split pair labelled is_planted = false (2 labels);
S19 = G7 requester only, no natural NO_VALID_APPROVAL_PATH (tested); .gitattributes (LF); manifest generated_at
kept when content is unchanged (tested; verified on data/manifest.json: identical SHA-256 after a re-run).

Files created:
- config/exception_codes.yaml; .gitattributes; scripts/build_negative_fixtures.py
- src/reference/oracle.py
- src/data/stages/: workbench.py, anomalies.py, boundaries.py, ground_truth.py
- src/validation/: reader.py, checks.py, report.py, __main__.py
- data/ground_truth/: record_expectations.csv, anomaly_labels.csv, boundary_cases.csv, scenarios.json, ground_truth.json
- tests/fixtures/negative/: lifecycle_01..08.json, arithmetic_01..08_*.json, structural_01..03_*.json, rules_conflict_01..02_*.yaml
- tests/: test_ground_truth_isolation.py, test_reference_independence.py, reference/test_reference_oracle.py,
  validation/test_validation.py, data/test_anomalies_and_ground_truth.py
Files changed: config/generation.yaml (anomalies, boundaries, two streams appended), config/expense_policies.yaml
(detection), src/data/{generate,export,compare_runs,config_loader,dataset}.py, src/data/stages/{balances,master}.py,
tests/data/{conftest,test_generator_reproducibility}.py, tests/db/test_generator_load.py, docs/07 (section 12),
docs/09 (section 8: ASM-P4-01..18, DEC-P4-01..07, AMB-P4-01..07), docs/11, docs/15, pyproject.toml (0.4.0),
data/manifest.json. No new packages installed.

Commands:
    python -m src.data.generate --seed 20261022 --employees 400 --leave-requests 800 --expense-claims 1000 --load
    python -m src.validation
    .\scripts\reproducibility_check.ps1
    python scripts\build_negative_fixtures.py      # only to rebuild the fixtures
    pytest -q

REAL results (2026-10-28):
- Full run with --load: ops counts in lea_dev = generated (employee 400, leave_policy 6, leave_request 800,
  expense_claim 1000, expense_line 3201, receipt 2927, leave_balance_transaction 13083, exception_code 26, ...);
  ground_truth schema: record_expectation 1800, anomaly_label 1022, boundary_case 40, scenario 41.
- Every Group A scenario, control and boundary: actual = planned (S04 44 >= 40; S14 771 >= 150).
  Labels: 180 planted positives (176 Group A + 4 BC-10), 29 planted controls, 3 natural positives
  (SPLIT_CLAIM_SUSPECTED 2 = the Phase 3 natural pair, BUDGET_EXCEEDED 1 on CC-0024), 810 natural controls.
  The oracle agreed with every planted and boundary record (generation stops otherwise).
- Validation: 21 checks, 0 failed, 8 not applicable (no workflow rows yet); M1 0/24921, M2 0/30344, M3 3757/3757 = 1.0.
- Dataset fingerprint (seed 20261022, 400/800/1000): 67515636201baff3d6746974fa34046b499c2511ffe79ed5a8c82b8ffe7a9de6
  (changed from Phase 3 as expected: anomalies, exception_code, renumbered ids, two new streams).
- reproducibility_check.ps1 (full scale): 53 files, 53 identical SHA-256 (raw 42, processed 2, ground_truth 5,
  validation 4), RESULT: REPRODUCIBLE, exit 0.
- pytest -q: 238 passed in 36.04s (0 failed, 0 skipped).
- ruff --select F,E9 on all Phase 4 files: clean.
Debugging during the phase (reproduce -> root cause -> smallest fix -> rerun):
  1. KeyError on an UNPAID legacy approval: UNPAID has no balance, so no USAGE is posted (ASM-P4-09).
  2. ground_truth CHECK route_is_array: None was stored as JSON null; the loader now sends SQL NULL.
  3. Stream independence test failed: S5 used one stream for leave and expense; split into two (ASM-P4-02).
  4. lea_test rejected S02 overlaps via the A3 test-only EXCLUDE: by design; test now proves it (DEC-P4-06).

Open issues / for owner decision:
- AMB-P4-01..07 in docs/09 section 8.3 (defaults applied; please confirm or change).
- Starter scale cannot place every scenario (ASM-P4-18): BC-07, BC-10, one S09 group, S21, S24 have too few
  candidates at 40/80/100. Full scale reaches every count.
- Pre-existing lint finding (Phase 2 file, not touched): unused `date` import in tests/db/test_reimbursement_constraints.py.
- Carried forward: cross-year rule and ~3 percent cross-year check in Phase 5 (fingerprint will change);
  new JWT_SECRET before Phase 9; Groq names and limits (ASM-051/052) unverified until Phase 9; OneDrive copy to delete.

Acceptance criteria (spec section 25) after Phase 4:
1, 2: MET (unchanged; full dataset with anomalies loads into lea_dev).
3 exact volumes: MET (400 / 6 / 800 / 1,000 after injection, tested).
4 ID conventions: MET (V-PK-01 and V-ID-01: 0 violations; ids re-derived in submission order, tested).
5 PK/FK validate: MET (M1 = 0, M2 = 0 from actual results).
6 leave balances reconcile: MET for posted ledger (V-ARITH-05: 1909/1909, including legacy USAGE).
8 expense totals reconcile with lines: MET (V-ARITH-01: 1000/1000; negative fixtures caught).
12 edge cases represented and labelled: MET for dataset scenarios, boundaries and fixtures; PARTIAL overall:
   attempt scenarios S11, S12, S13, S18 and S25 need Phases 7-8.
13 ground truth isolated: MET (separate schema/folder, no FKs, no label columns, isolation tests).
17 reproducible: MET including ground-truth and validation files (53/53).
18 validation metrics from actual results: PARTIAL (M1-M3 computed now; M4-M18 need the engine, Phase 11).
21 automated tests: MET for current scope (238 passed).
22 documentation: PARTIAL (docs/07, 09, 11, 15 updated; full README in Phase 12).
7, 9, 10, 11, 14, 15, 16: PARTIAL or NOT STARTED as before (services, engine, API: Phases 5-9); 19, 20: NOT STARTED.

Next phase: Phase 5 (leave balance and leave request services) after "APPROVED PHASE 4".

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

Owner decisions 2026-10-28 (recorded in docs/09 section 7.3, docs/05, docs/07, CLAUDE.md):
- AMB-P3-01 accepted; AMB-P3-02 changed (per-year check incl. scheduled accrual, docs/05 BR-LBAL-09);
  AMB-P3-03 accepted with one step covering L1+L2 (docs/05 5.4; needs a Phase 7 migration); AMB-P3-04 accepted.
- CLAUDE.md rule added: never print the contents of .env or any secret in output.
- Not yet applied to data: the generator still uses the stricter cross-year guard (data and fingerprint
  unchanged). Owner to choose: regenerate in Phase 3 with the per-year rule, or let Phase 5 implement it.
Carried into Phase 4: at least 8 claims reach the L5 level (> 5,000 USD), planted or by amounts; the natural
split-claim pair is labelled is_planted = false; S19 planted on a cause other than "L1 is the G7";
.gitattributes for line endings; new JWT_SECRET before Phase 9.

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
