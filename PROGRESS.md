Project: Enterprise Leave and Expense Approval Automation System

Current phase: Phase 8B-1 (reimbursements, payment runs, S13, S25, audit_event export)
Status: 8B-1 COMPLETE. Awaiting "APPROVED 8B-1"; then 8B-2 (resubmissions, cancellations, S11/S12, S18, migration
  0003 record_round_expectation). "APPROVED PHASE 8" after 8B-2.

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
Phase 6: APPROVED 2026-10-28 (commit c4f1590). AMB-P6-01..05 accepted. Owner instruction for Phase 7A: change the
  oracle so an escalated expense claim keeps its budget reservation until the final decision (reservation kept
  unless validation rejects or returns the claim), matching the services and BR-BUD-03/04; re-run both comparisons.
Phase 7A: APPROVED 2026-10-28 (commit 4922b17). AMB-P7A-01..04, DEC-P7A-02 and DEC-P7A-04 accepted as applied.
Phase 7 plan (owner 2026-10-28):
  7A = oracle budget change; routing service src/services/approval_routing.py (bands lower-exclusive/upper-inclusive,
       priority, RULE_CONFLICT, NO_VALID_APPROVAL_PATH); approvers L1-L5 with substitution, delegation and
       covered_levels; migration 0002 approval_step.covered_levels (JSONB NOT NULL) + model + docs/10 + up/down test;
       steps at submission for PENDING_APPROVAL (memory and both DB stores); comparisons extended to the route
       (target 0 ROUTING_PHASE7, 0 DISAGREE); dataset unchanged (verify file by file).
  7B = decisions (approve/reject/return) with attempts, idempotency and history; resubmission; process-owner
       decisions; S6 timing into the dataset; year-end CARRY_FORWARD rows replacing AMB-P5-02; S19 and S22 data.
  S19 (owner decision): option (a) one G7 per country, each the ONLY G7 in its country; L5 = the G7 of the
       requester's country, so a G7 requester still has no valid path and S19 plants come from several people.
       Dataset change decided in 7B and shown to the owner BEFORE it is made; not touched in 7A.
  S22 timing (proposed for 7B): decisions at 17:00 UTC on a business day at least one business day after
       assignment, so an S22 partner submitted at most 24 h earlier is never decided first (closes AMB-P4-04).

Phase 7B: APPROVED 2026-10-29 (commit ce59a2a). ASM-P7B-12 accepted.
Phase 8 split (2026-10-29, owner allowed a split): 8A = carried-over items 1-2, reimbursement service, audit_event,
  processing_failure, cancellation service, tests, docs, dataset plan; 8B = every dataset change (AMB-P7B-02/03/04,
  S7 / S8 stages, S11-S13, S25, V-ARITH-04 and V-WF-03 on real rows), after the owner's OK on docs/09 13.4.

Phase 8A: accepted by the owner 2026-10-29 (commit d9eeca9); 8B plan approved with conditions (docs/09 13.4).

## Phase 8B-1 record

Scope: stage S7 in the S6 replay (reimbursement at final approval for every claim APPROVED at as-of; payment runs
on the reserved `payments` stream: 5 percent first-attempt failures with processing_failure rows and a retry, S25;
ACTUAL + RELEASE at completion); S13 (8 planted second CREATEs -> BLOCKED DUPLICATE_REIMBURSEMENT); S8 export of
audit_event; four new exported / loaded tables. Oracle: own payment model and capped-excess budget release; the
expense comparison also compares each reimbursement. Ground truth: S13 planted labels, S25 labels from the oracle.
No ground_truth schema change, no resubmission / cancellation / S11 / S12 / S18 (8B-2). Services import nothing from
src/reference; ground truth isolated (tests pass). Ledger-posting audit skipped (DEC-P8-09); hash chain deferred
(DEC-P8-10).

Files changed: config/generation.yaml (payments); src/services/workflow_simulation.py; src/data/{dataset,generate}.py;
src/data/stages/{outcomes,ground_truth}.py; src/reference/oracle.py; src/evaluation/{leave,expense}_service_vs_oracle.py;
tests/data/{test_outcomes_on_dataset,test_anomalies_and_ground_truth,test_expense_services_on_dataset}.py;
docs/09 (13.4 decisions, 13.5), docs/15; PROGRESS.md; data/manifest.json, data/ground_truth/{anomaly_labels.csv,
scenarios.json,ground_truth.json}. No migration, no new packages.

REAL results (2026-10-29):
- generate --load: exit 0; every lea_dev count = generated (reimbursement 902, reimbursement_attempt 2770,
  processing_failure 37, audit_event 12288, idempotency_record 3501, cost_center_transaction 1942); ground_truth
  1800 / 1100 / 40 / 41. Fingerprint 60d8e0770f00b2ee6c6495ad7c19f4a7ff5a210ec1b9a56d0e9a34ac6eb3f601 (was 28ece855...).
- Validation: 22 checks, 0 failed, 0 not applicable; V-ARITH-04 PASS 902, V-WF-03 PASS 902; M1 0/66090,
  M2 0/92252, M3 7883/7883.
- Leave comparison 800 AGREE / 0 DISAGREE; expense 1000 AGREE / 0 DISAGREE (incl. reimbursement status and amount).
- reproducibility_check.ps1: 76 of 76 identical, RESULT: REPRODUCIBLE, exit 0.
- pytest -q: 488 passed in 87.31s (482 + 6 new). ruff: All checks passed. Note: an earlier full run in the same
  session ended its output with a runpy traceback and no visible summary line (cause not captured); the rerun above
  is clean.
- Scenario counts before -> after: all planted and boundary counts unchanged; S13 none -> 8; S25 none -> 37;
  natural S04 62, S14 788, BUDGET_EXCEEDED 1 unchanged (docs/09 13.5).

## Phase 8A record

Scope implemented: src/services/reimbursement_service.py (row at final approval inside the approval operation, only
for APPROVED claims, guards CLAIM_NOT_APPROVED / ZERO_APPROVED_AMOUNT / DUPLICATE_REIMBURSEMENT / AMOUNT_MISMATCH,
amount and currency = the claim's approved amount, manual create with key, payment run start / settle with keys,
failure -> processing_failure, retry, COMPLETED -> ACTUAL + RELEASE, cancel with reason; state machine as data in
lifecycle.REIMBURSEMENT_TRANSITIONS); src/services/audit_service.py (audit rows for submissions, decisions,
attempts, steps changed, reassignments, replays, reimbursements, failures, written in the same transaction by all
four stores); approval_service.cancel_request (needed for 8B cancellations); repositories/base.run_recording_failure
(technical error -> rollback, processing_failure in a second transaction); unique-index race -> BLOCKED attempt
(savepoint). Services import nothing from src/reference (test passes); ground truth untouched; workflow status,
exception class, processing_failure and audit/attempt rows stay separate. Hash chain NOT done (DEC-P8-07).
Carried over: (1) DB test for SqlWorkflow.record_reassignment: done. (2) hand-built oracle test where the status at
as-of flips with the reassignment: done. (3) Phase 8 must-include items: all three are dataset changes, planned for
8B in docs/09 13.4 (not applied).

Files created: src/services/{reimbursement_service,audit_service,idempotency}.py;
tests/unit/test_reimbursement_and_audit.py; tests/db/test_reimbursement_and_audit_db.py.
Files changed: src/services/{approval_service,expense_service,leave_request_service,lifecycle}.py;
src/repositories/{base,expense_repository,leave_repository}.py; src/common/ids.py; tests/db/test_leave_submission_db.py
(AUD scope); tests/reference/test_reference_oracle.py (new test); docs/06, 09 (12 approved, 13 new), 15;
pyproject.toml (0.8.0a1). No migration, no new packages, no data change.

Commands:
    python -m src.data.generate --seed 20261022 --employees 400 --leave-requests 800 --expense-claims 1000 --load
    python -m src.validation
    python -m src.evaluation.leave_service_vs_oracle
    python -m src.evaluation.expense_service_vs_oracle
    .\scripts\reproducibility_check.ps1
    pytest -q

REAL results (2026-10-29):
- Generate --load: exit 0; every lea_dev count = generated (unchanged from 7B); fingerprint
  28ece8554f97a48e6323ef032ff926919596a80ff5f2b5da3ebe2fc9edf42dfa = 7B; git shows no change under data/.
- Validation: 22 checks, 0 failed, 2 not applicable (V-ARITH-04, V-WF-03: no reimbursement rows until 8B);
  M1 0/48254, M2 0/79435, M3 6981/6981.
- Leave comparison: 800 AGREE, 0 DISAGREE. Expense comparison: 1000 AGREE, 0 DISAGREE.
- reproducibility_check.ps1: 68 files, 68 identical, RESULT: REPRODUCIBLE, exit 0.
- pytest -q: 482 passed in 54.40s (465 + 17 new). ruff --select F,E9 src tests migrations: All checks passed.
Debugging: (1) test_second_submission... pinned the id_sequence scopes; submissions now also allocate AUD ids:
expectation updated. (2) DB test: CHECK non_accepted_has_reason rejected a COMPLETED attempt without a reason
(the in-memory store cannot see it); fix: reason PAYMENT_COMPLETED (ASM-P8-04). (3) a payment-run replay was
audited on the claim instead of the reimbursement; fixed. (4) a process-owner decision got two audit rows for one
transition; fixed (ASM-P8-06). (5) my unit test data hit DUPLICATE_CLAIM_PATTERN (same total and date); test fixed.

Open issues / for owner decision: the 8B plan and questions (a)-(e) in docs/09 13.4; AMB-P8-01..05 (defaults
applied); JWT_SECRET before Phase 9; Groq limits unverified until Phase 9.

Acceptance criteria after 8A: 14 reimbursements only for eligible approved claims: PARTIAL (service + trigger +
tests; dataset rows in 8B); 15 duplicate reimbursement prevented: MET at service and DB level (guard, partial unique
index, race converted, idempotent replay; dataset S13 in 8B); 16 audit history: PARTIAL (audit_event written by every
service path, append-only trigger; dataset rows in 8B); others as after 7B.

## Phase 7B record

Scope implemented: src/services/approval_service.py (decide_step: APPROVE / REJECT / RETURN with guards SELF_APPROVAL,
UNAUTHORIZED_APPROVER, DUPLICATE_ACTION, STEP_NOT_PENDING, LEVEL_SKIPPED, EXPIRED_RULE; an approval_attempt for every
call; idempotency keys per docs/06 8.2 with replay and conflict; next-step assignment; USAGE at approval; approved_amount;
RELEASE on reject / return. decide_escalated: process owner, or L4 for BUDGET_EXCEEDED only: send on (steps created),
APPROVE, REJECT, RETURN; OVERRIDE posting). Resubmission in submit_leave / submit_expense (round + 1, same ids,
first_submitted_at kept, new-round lines, history append-only, max 3 rounds, RESUBMIT idempotency). Both in-memory and
both PostgreSQL stores implement the WorkflowStore. Year-end CARRY_FORWARD / EXPIRY rows replace the recompute
(AMB-P5-02). Stage S6 (src/data/stages/outcomes.py, src/services/workflow_simulation.py): decisions with timing
(17:00 UTC, more than 24 h after assignment, S22 rule) written into the dataset; the oracle got its own timing
model. Services import nothing from src/reference (test passes); ground truth isolated (tests pass); workflow
status, exception class, processing status and audit/attempt rows stay separate columns and tables.
Not done (DEC-P7B-06): S19 dataset change (waiting), reimbursement and audit_event (Phase 8), dataset resubmissions /
cancellations and S11 / S12 / S18 attempt rows (AMB-P7B-02/03).

Files created: src/services/{approval_service,workflow_simulation}.py; src/data/stages/outcomes.py;
tests/unit/test_approval_decisions.py; tests/db/test_approval_decisions_db.py; tests/data/test_outcomes_on_dataset.py.
Files changed: src/common/rng.py (keyed draws); src/services/{leave_request_service,expense_service,leave_balance_service,
leave_batch,expense_batch,leave_detectors,lifecycle}.py; src/repositories/{base,leave_repository,expense_repository}.py;
src/reference/oracle.py (timing, legacy marker, budget release time); src/data/{dataset,generate}.py;
src/data/stages/{balances,ground_truth,workbench}.py; src/evaluation/{leave,expense}_service_vs_oracle.py;
config/generation.yaml (decisions); tests/unit/{leave_world,test_leave_balance,test_leave_validation}.py;
tests/data/{test_anomalies_and_ground_truth,test_generator_baseline}.py; tests/reference/test_reference_oracle.py;
docs/05, 06, 07, 09 (section 12), 10, 11, 15; pyproject.toml (0.7.0); data/manifest.json, data/ground_truth/*.
No migration, no new packages.

Commands:
    python -m src.data.generate --seed 20261022 --employees 400 --leave-requests 800 --expense-claims 1000 --load
    python -m src.validation
    python -m src.evaluation.leave_service_vs_oracle
    python -m src.evaluation.expense_service_vs_oracle
    .\scripts\reproducibility_check.ps1
    pytest -q

REAL results (2026-10-28):
- Generate --load: exit 0; every table count in lea_dev = generated (leave_request 800, expense_claim 1000,
  leave_balance_transaction 15514, cost_center_transaction 1042, approval_step 2548, approval_event 5044,
  approval_attempt 2551, request_status_event 6949, request_exception 131, idempotency_record 2551); ground_truth
  1800 / 1057 / 40 / 41. Volumes 400 / 6 / 800 / 1,000 unchanged; every scenario count unchanged.
- Validation: 21 checks, 0 failed, 2 not applicable (reimbursement, Phase 8); M1 0/48168, M2 0/79269, M3 6958/6958.
- Leave comparison: 800 (DRAFT 8, LEGACY 24, SUBMITTED 768): AGREE 800, DISAGREE 0; at as-of APPROVED 755,
  PENDING_APPROVAL 12, ESCALATED 5, REJECTED 12, RETURNED 8, DRAFT 8 (services = oracle = dataset).
- Expense comparison: 1000: AGREE 1000, DISAGREE 0; at as-of APPROVED 893, PENDING_APPROVAL 20, ESCALATED 19,
  REJECTED 27, RETURNED 33, DRAFT 8.
- Fingerprint 56cfaf0cbaae06426b21e11da3284f2786a208530806bdcfc0c3422d865ddc6a (was 0a84321b...). Against Phase 7A:
  35 files identical (incl. detections.csv), 19 changed (leave_request marker and outcomes, claims, lines, ledger,
  balances, budgets, ground truth at as-of, seed.sql, validation report), 14 new (7 workflow tables).
- reproducibility_check.ps1: 68 files, 68 identical, RESULT: REPRODUCIBLE.
- pytest -q: 463 passed in 56.88s (433 + 30 new). ruff --select F,E9 src tests migrations: All checks passed.
Debugging: (1) steps_match DISAGREE on every routed record: in-memory stores kept the submission result's step dicts,
which later decisions mutated; fix: stores keep copies. (2) a unit test mutated the shared RULES list (EXPIRED_RULE
leaked into later tests); fix: the test gives its router its own list. (3) generator baseline / oracle tests expected
eventual statuses; now final_status is at as-of and eventual_status is checked.

S19 option A (owner 2026-10-28; AMB-P7B-09, ASM-P7B-11, DEC-P7B-09), applied after the main 7B commit:
- S1 promotes the lowest-id ACTIVE G6 (no end date, started by the window start) in each country without a G7:
  EMP-000031 (US), EMP-000181 (GB); EMP-000314 (IN) unchanged. Manager NULL, no draws. Neither is the subject of any
  other plant. S19 plants split 2+2 / 1+1 / 1+1 over the three G7s; no unplanted NO_VALID_APPROVAL_PATH.
- AMB-P7A-01 fallback removed from routing; the oracle's single-G7 L5 replaced by the per-country rule.
- Condition 3 (owner, amended): planned counts met and planted actuals unchanged (all are). Natural counts moved:
  S04 60 -> 62, S14 790 -> 788, natural split-claim labels 2 -> 0 (labels 1057 -> 1055).
- New check V-WF-05 (AMB-P7B-06): no decision after the approver's employment end. REAL result: 1 violation,
  APR-EXP-2025-000483-02 (EMP-000190 decided 2025-12-17, employed until 2025-12-14). 0 at e15dc94 (rebuilt to check);
  it comes from the redraw. Not hidden: validation and the generator exit 1, pytest shows it as strict xfail, and
  reproducibility_check.ps1 stops at the generator's exit code (run by hand below). Owner decision AMB-P7B-11.
- AMB-P7B-10 (default applied, please confirm): a country without an eligible G6 keeps no G7; WARNING + manifest
  countries_without_g7 (found at starter scale, seed 20261023; not reached at full scale).
- Tests adjusted: one G7 per country (baseline, S19, G7 direct reports for every G7), L5 without fallback, natural split
  test -> planted S09 detected exactly, baseline overlap test now allows AM + PM half days on one date (ASM-008; a
  pair the redraw produced; the generator was right).
- Files changed: src/data/stages/{master,anomalies,ground_truth}.py, src/data/generate.py, src/services/approval_routing.py,
  src/reference/oracle.py, src/validation/checks.py; tests/unit/test_approval_routing.py,
  tests/data/{test_generator_baseline,test_anomalies_and_ground_truth}.py, tests/validation/test_validation.py;
  docs/05, 07, 09 (12.2-12.4), 10, 15; data/manifest.json, data/ground_truth/*.
- Before -> after: employee G6 24 -> 22, G7 1 -> 3; approval_step 2548 -> 2547 (APPROVED 2506 -> 2518, PENDING 42 -> 29);
  leave APPROVED 755 -> 756, DRAFT 8 -> 7, ESCALATED 5 -> 6, PENDING 12 -> 11; expense APPROVED 893 -> 902,
  ESCALATED 19 -> 17, PENDING 20 -> 12, RETURNED 33 -> 34; user_role 596 -> 597.
- REAL results (2026-10-28): generate --load exit 1 (V-WF-05 only), every lea_dev count = generated; validation 22
  checks, 1 failed (V-WF-05), M1 0/48253, M2 0/79434, M3 6981/6981; leave 800 AGREE / 0 DISAGREE; expense 1000 AGREE /
  0 DISAGREE; reproducibility by hand (two runs + compare_runs): RESULT: REPRODUCIBLE, fingerprint
  5d85c28b7fc102c212a22a22db13d2531e5cf434abb6a13a5ad5c99f38e170fe; files vs e15dc94: 22 identical, 46 changed;
  pytest -q: 463 passed, 1 xfailed; ruff --select F,E9: All checks passed.

AMB-P7B-11 option (1) (owner 2026-10-29; supersedes AMB-P7B-06; AMB-P7B-10 and the S19 test changes accepted):
- approval_service.reassign_departed: a PENDING step whose approver's employment ended before the date goes to the
  routing substitute (delegate, else next up, never the requester); approver_employee_id (and delegated_from for a
  delegate) updated, assigned_at and the ASSIGNED event kept, approval_event REASSIGNED appended (actor NULL,
  reason APPROVER_EMPLOYMENT_ENDED, comment "old -> new"). record_reassignment on the in-memory and SQL stores.
- Simulation (workflow_simulation.DecisionDriver): decision date after the employment end -> reassign at 00:00 UTC the
  day after the end (or at assignment, if later), new decision keyed (id, round, level, new approver) (ASM-P7B-12).
  Oracle at_as_of mirrors it with its own _substitute (no src/services import).
- Dataset effect: APR-EXP-2025-000483-02 reassigned 2025-12-15 17:00 UTC EMP-000190 -> EMP-000126, approved
  2025-12-26 (was 2025-12-17 by EMP-000190). approval_event 5059 -> 5060; every other count, every planted and natural
  scenario count, ground truth and every status at as-of unchanged. Fingerprint 28ece855... (was 5d85c28b...).
- Tests: V-WF-05 xfail -> normal test (also checks ASSIGNED, REASSIGNED, APPROVED events); new unit test
  test_a_step_whose_approver_has_left_is_reassigned_to_the_next_person_up.
- Files changed: src/services/{approval_service,workflow_simulation}.py, src/repositories/base.py,
  src/reference/oracle.py; tests/unit/test_approval_decisions.py, tests/validation/test_validation.py;
  docs/05 (5.4, 9.5), 06 (3), 09 (ASM-P7B-10, ASM-P7B-12, AMB-P7B-06, AMB-P7B-11); data/manifest.json.
- REAL results (2026-10-29): generate --load exit 0, lea_dev counts = generated; validation 22 checks, 0 failed,
  V-WF-05 PASS (2518 subjects), M1 0/48254, M2 0/79435, M3 6981/6981; leave 800 AGREE / 0 DISAGREE; expense 1000
  AGREE / 0 DISAGREE; reproducibility_check.ps1: 68 of 68 identical, RESULT: REPRODUCIBLE, exit 0; pytest -q 465 passed;
  ruff --select F,E9: All checks passed.
- Notes: the SQL record_reassignment has no DB test yet (the dataset path uses the in-memory store). The claim is
  APPROVED at as-of with or without the reassignment, so the comparisons cannot tell the two timings apart; the unit
  test and V-WF-05 cover the behaviour.

Phase 8 MUST include (owner 2026-10-28):
- Resubmission rounds and cancellations in the dataset (AMB-P7B-02; ASM-025, ASM-040).
- S11 / S12 self-approval and unauthorised-approval attempt scenarios in the dataset (AMB-P7B-03).
- The reimbursement row created at final approval (AMB-P7B-04; docs/06 8.2).

Open issues: DB test for SqlWorkflow.record_reassignment (Phase 8); JWT_SECRET before Phase 9; Groq limits unverified until Phase 9.

Acceptance criteria after Phase 7B: 1-8, 13, 17, 21 MET; 9 approval routing MET for routing and decisions (agreed
with the oracle at as-of on every record); 10 self-approval MET at service and DB level (guard + trigger, V-WF-02);
16 audit history PARTIAL (status events, attempts, approval events append-only; audit_event in Phase 8); 12, 18, 22
PARTIAL; 11, 14, 15, 19, 20 PARTIAL or NOT STARTED.

## Phase 7A record

Scope implemented (docs/05 5.1-5.4; owner 7A plan): oracle budget change (DEC-P7A-03); routing service
src/services/approval_routing.py over approval_rule rows (bands lower-exclusive / upper-inclusive, highest priority,
RULE_CONFLICT on equal priority with different levels, lowest id on equal outcome, NO_VALID_APPROVAL_PATH when no
rule matches or a level is unresolved); L1-L5 with substitution, delegation and covered_levels (one step per person at
the highest level); migration 0002 approval_step.covered_levels JSONB NOT NULL + 3 CHECKs; steps at submission for
PENDING_APPROVAL in memory and in both PostgreSQL stores (step 1 assigned + approval_event ASSIGNED); both comparisons
extended to codes incl. routing, rule, route and steps. Services import nothing from src/reference (test passes).
Dataset unchanged (verified file by file). Waits for 7B: decisions, attempts, idempotency, resubmission, process-owner
decisions, S6 timing, CARRY_FORWARD rows, S19 / S22 data.

Files created: src/services/approval_routing.py; migrations/versions/0002_step_covered_levels.py;
tests/unit/test_approval_routing.py; tests/db/test_approval_steps_db.py.
Files changed: src/reference/oracle.py (budget); src/services/{exception_service,leave_request_service,expense_service,
leave_batch,expense_batch}.py; src/repositories/{base,leave_repository,expense_repository}.py; src/models/approvals.py;
migrations/versions/0001_initial_schema.py (LATER_COLUMNS, DEC-P7A-02); src/evaluation/{leave,expense}_service_vs_oracle.py;
tests/conftest.py (insert_seed, insert_configured_rules, approved_claim covered_levels); tests/db/{test_leave_submission_db,
test_expense_submission_db,test_immutability_triggers,test_request_fk_exactly_one,test_roles_and_migration_cycle}.py;
tests/data/test_{leave,expense}_services_on_dataset.py; tests/reference/test_reference_oracle.py; docs/05 (L5, 5.4 note),
docs/09 (section 11), docs/10 (covered_levels), docs/15; pyproject.toml (0.7.0a1). No new packages.

Commands:
    alembic upgrade head            # lea_dev: 0001_initial_schema -> 0002_step_covered_levels
    python -m src.data.generate --seed 20261022 --employees 400 --leave-requests 800 --expense-claims 1000 --load
    python -m src.validation
    python -m src.evaluation.expense_service_vs_oracle
    python -m src.evaluation.leave_service_vs_oracle
    .\scripts
eproducibility_check.ps1
    pytest -q

REAL results (2026-10-28):
- alembic upgrade head on lea_dev: "Running upgrade 0001_initial_schema -> 0002_step_covered_levels"; current = head.
- Generate --load: exit 0; lea_dev expense_claim 1000, expense_line 3201, receipt 2927, leave_request 800,
  leave_balance_transaction 13086, approval_step 0; ground_truth 1800 / 1057. Fingerprint 0a84321b... = Phase 6.
- File by file: 54 of 54 files identical SHA-256 to the committed manifest; git shows no change under data/.
- Validation: 21 checks, 0 failed, 7 not applicable; M1 0/24924, M2 0/30350, M3 6958/6958 = 1.0.
- Expense comparison: 1000 (DRAFT 8, SUBMITTED 992): AGREE 1000, ROUTING_PHASE7 0, DISAGREE 0; routed 958; 1580 steps
  on 901 claims in PENDING_APPROVAL. Leave: 800 (DRAFT 8, LEGACY 24, SUBMITTED 768): AGREE 800, ROUTING_PHASE7 0,
  DISAGREE 0; routed 748; 941 steps on 736 requests. The 8 S19 records escalate with NO_VALID_APPROVAL_PATH.
  Route content checked: 65 routed records have a step covering several levels, 12 a delegated step, 17 claims L5.
- reproducibility_check.ps1: 54 files, 54 identical, RESULT: REPRODUCIBLE, exit 0.
- pytest -q: 433 passed in 47.21s (384 + 49 new). ruff --select F,E9 src tests migrations: All checks passed.
Debugging: (1) test_second_submission... expected id_sequence {RSE, REX}; the clean first request now also writes an
APE event; expectation updated. (2) Migration test with hand-written SQL rows hit NOT NULL columns; replaced by the
shared seed graph (insert_seed). (3) Oracle budget test confirmed to FAIL on the old oracle and pass on the new one.

Open issues / for owner decision: AMB-P7A-01..04 (docs/09 11.3). S19 dataset change (one G7 per country) to be shown
before it is made, in 7B. JWT_SECRET before Phase 9; Groq limits unverified until Phase 9.

Acceptance criteria after Phase 7A: 1-8, 13, 17, 21 MET (1 now incl. migration 0002 both ways); 9 approval routing
PARTIAL (routes and steps, agreed with the oracle on every record; decisions in 7B); 10 self-approval PARTIAL (routing
never assigns the requester, DB trigger; attempt guards in 7B); 12, 16, 18, 22 PARTIAL; 11, 14, 15, 19, 20 PARTIAL or
NOT STARTED.

## Phase 6 record

Scope implemented (spec 13.2, 26 Phase 6; docs/05 sections 3, 4, 6, 7, 9; docs/06 8.1): expense line and claim
validation BR-EX-01..13 (all codes recorded, highest severity decides), USD conversion with the fixed fx_rate rows
(exact Decimal, half-up), policy resolution and per-category limits, receipt rules, duplicate receipts (self /
cross-employee), duplicate claim pattern, split claims (SUSPICIOUS_PATTERN, "suspected split claim, requires
investigation", never "fraud"), budget availability with RESERVATION / RELEASE postings, line PASS / CAPPED / FAIL,
approved amount if approved; submission DRAFT -> SUBMITTED -> VALIDATING -> outcome in memory and in PostgreSQL
(locks on claim, cost center, budget; status events, exception rows, budget ledger, committed_amount); batch
detectors (duplicate receipts, split) into data/validation/detections.csv; services-vs-oracle comparison for all
1,000 claims. Services import nothing from src/reference (independence test passes).
Waits: routing and approvals (Phase 7), reimbursement, audit_event and idempotency (Phase 8), API and dashboard.
Generator (DEC-01): S4 validity = the expense service on each drawn claim (draws unchanged); quantity x unit on
every line from a new appended stream; set_line keeps them consistent. Leave files unchanged (verified).

Files created: src/services/{expense_service,expense_batch}.py; src/repositories/{base,expense_repository}.py;
src/evaluation/expense_service_vs_oracle.py; tests/unit/test_expense_validation.py;
tests/data/test_expense_services_on_dataset.py; tests/db/test_expense_submission_db.py.
Files changed: src/services/{exception_service,leave_request_service}.py (Finding/FindingSet shared);
src/repositories/leave_repository.py (uses base.py); src/data/{generate,export}.py; src/data/stages/{expenses,
workbench}.py; config/generation.yaml (stream expense_quantities, quantity_max); tests/data/test_leave_services_on_dataset.py
(filter leave detections); tests/db/test_reimbursement_constraints.py (old unused import removed); docs/07 (section 14),
docs/09 (section 9 approved, section 10: ASM-P6-01..07, DEC-P6-01..05, AMB-P6-01..05), docs/11, docs/15;
pyproject.toml (0.6.0); data/manifest.json. No new packages.

Commands:
    python -m src.data.generate --seed 20261022 --employees 400 --leave-requests 800 --expense-claims 1000 --load
    python -m src.validation
    python -m src.evaluation.expense_service_vs_oracle
    python -m src.evaluation.leave_service_vs_oracle
    .\scripts\reproducibility_check.ps1
    pytest -q

REAL results (2026-10-28):
- Generate --load: exit 0; lea_dev counts = generated (expense_claim 1000, expense_line 3201, receipt 2927,
  leave_request 800, leave_balance_transaction 13086); ground_truth schema 1800 / 1057 / 40 / 41.
- Validation: 21 checks, 0 failed, 7 not applicable; V-ARITH-03 now runs: 3201/3201; M1 0/24924, M2 0/30350,
  M3 6958/6958 = 1.0.
- Expense services vs oracle (1000 claims: DRAFT 8, SUBMITTED 992): AGREE 996, ROUTING_PHASE7 4 (the planted S19-E
  G7 claims; oracle final ESCALATED_FOR_REVIEW via NO_VALID_APPROVAL_PATH), DISAGREE 0. Leave unchanged: AGREE 796,
  ROUTING_PHASE7 4, DISAGREE 0.
- detections.csv: expense codes equal the expense labels expected DETECT (tested), e.g. SPLIT_CLAIM_SUSPECTED batch 24
  (S09 18 + BC-10 4 + natural 2), BUDGET_EXCEEDED 9 (S21 8 + natural 1).
- Fingerprint 0a84321bc8b848814688c55067befd6260d91ae149b603e27127626e2606ca2a (was 7dbe6672...). Against Phase 5:
  47 of 54 files identical (every leave file, expense_claim, receipt, ground truth); changed: expense_line (csv, json),
  seed.sql, detections.csv, validation_report (csv, json, md).
- reproducibility_check.ps1: 54 files, 54 identical SHA-256, RESULT: REPRODUCIBLE, exit 0.
- pytest -q: 384 passed in 34.84s (349 + 35 new). ruff --select F,E9 src tests: All checks passed.
Debugging: test_leave_detections_equal_the_planted_leave_labels (full, starter) failed after detections.csv gained
expense rows; root cause: the test compared all detections with leave labels; fix: filter record_type LEAVE.

Open issues / for owner decision: AMB-P6-01..05 (docs/09 section 10.3). S19 still all on the G7 (Phase 7).
JWT_SECRET before Phase 9; Groq limits unverified until Phase 9.

Acceptance criteria after Phase 6: 1-8, 13, 17, 21 MET (8 now also with line quantity x unit, V-ARITH-03);
12, 16, 18, 22 PARTIAL; 9, 10, 11, 14, 15, 19, 20 PARTIAL or NOT STARTED (Phases 7-10).

Next phase: Phase 7 (approval engine and lifecycle management) after "APPROVED PHASE 6".


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
