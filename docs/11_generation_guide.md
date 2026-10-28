# 11. Synthetic data generation guide

Phase 3 deliverable, extended in Phases 4 and 5. How to run the generator, what it produces, and how to check that it is
reproducible. Design background: docs/07. Every policy value is an illustrative synthetic ASSUMPTION (docs/09).

## 1. What the generator produces

| Stage (docs/07) | Status | Tables / files |
|---|---|---|
| S1 master | done (Phase 3; exception_code added in Phase 4) | department, cost_center, cost_center_budget, employee, employee_cost_center_assignment, country_holiday, fx_rate, delegation, leave_policy, expense_policy, approval_rule, exception_code, role, application_user, user_role |
| S2 balances | partly: OPENING + ACCRUAL (+ USAGE of legacy approvals, Phase 4) | leave_balance (2025, 2026), leave_balance_transaction. CARRY_FORWARD and engine USAGE arrive with Phase 7 |
| S3 leave | done (raw inputs; since Phase 5 validated by the leave services, per-year rule BR-LBAL-09, about 3% cross-year) | leave_request: SUBMITTED, about 1% DRAFT, 24 legacy APPROVED (S01, S02) |
| S4 expenses | done (raw inputs) | expense_claim (SUBMITTED, about 1% DRAFT), expense_line (PENDING), receipt |
| S5 anomalies + boundaries | done (Phase 4) | the same rows, modified in place (docs/07 section 12) |
| S9 ground truth | done (Phase 4) | data/ground_truth/*, ground_truth schema with --load |
| validation | done (Phase 4) | data/validation/* (src/validation) |
| leave detections | done (Phase 5) | data/validation/detections.csv: every submitted leave request replayed through the Phase 5 services in submission order, plus the leave batch detectors (the dataset rows are not changed) |
| S6 outcomes | Phase 7 | approval steps, events, exceptions, budget ledger |
| S7 reimbursements, S8 audit | Phase 8 | |

Stages S1-S4 still produce the Phase 3 **valid baseline** (DEC-41); S5 then plants the docs/07 section 7 scenarios
by modifying existing records only, so the core volumes stay exactly 400 / 6 / 800 / 1,000.

## 2. Commands (Windows PowerShell, project root, venv active)

```powershell
.\.venv\Scripts\Activate.ps1

# Full baseline: 400 employees, 800 leave requests, 1,000 expense claims -> data\
python -m src.data.generate --seed 20261022 --employees 400 --leave-requests 800 --expense-claims 1000

# Same, and replace the contents of lea_dev with it (uses DATABASE_URL from .env)
python -m src.data.generate --seed 20261022 --employees 400 --leave-requests 800 --expense-claims 1000 --load

# Starter dataset (one-tenth scale, same code) into its own folder
python -m src.data.generate --seed 20261022 --employees 40 --leave-requests 80 --expense-claims 100 --out data\starter

# Reproducibility check: generate twice into temp folders, compare row counts and SHA-256 of every file
.\scripts\reproducibility_check.ps1
.\scripts\reproducibility_check.ps1 -Employees 40 -LeaveRequests 80 -ExpenseClaims 100
```

macOS / Linux: activate with `source .venv/bin/activate`, use `/` in paths, and run
`sh scripts/reproducibility_check.sh` (arguments: seed employees leave expense).
If PowerShell blocks the script, run it once with `powershell -ExecutionPolicy Bypass -File .\scripts\reproducibility_check.ps1`.

| Flag | Default | Meaning |
|---|---|---|
| --seed | 20261022 | master seed; every stream derives from it |
| --employees / --leave-requests / --expense-claims | 400 / 800 / 1000 | exact volumes |
| --out | data | output folder |
| --load | off | TRUNCATE every ops table in lea_dev and insert this dataset in one transaction (DEC-38); refuses any database other than lea_dev or *_test |
| --database-url | DATABASE_URL | override the target database |
| --no-export | off | do not write files |
| --config-dir | config | where the YAML configuration lives |

## 3. Outputs

| Path | Content | In git |
|---|---|---|
| data/raw/<table>.csv | canonical CSV per table: UTF-8, LF, header, rows sorted by primary key, columns in data-dictionary order, decimals at column scale, dates `2025-01-31`, timestamps `2025-01-31T09:14:00Z`, booleans `true`/`false`, NULL empty | no (regenerable) |
| data/raw/<table>.json | same rows as JSON arrays; decimals and timestamps as strings, `sort_keys`, 2-space indent (DEC-39) | no |
| data/processed/seed.sql | INSERT statements in dependency order for an empty ops schema (`psql -d lea_dev -f data/processed/seed.sql`) | no |
| data/processed/dev_credentials.csv | synthetic login passwords for the simulated users (ASM-P3-10) | no (never commit) |
| data/ground_truth/record_expectations.csv | one row per request (1,800): expected route (JSON list of {level, approver_id, covers, delegated_from}), expected outcome, eligibility, codes (JSON list), approved amount | yes |
| data/ground_truth/anomaly_labels.csv | one row per planted or natural label (GTL-000001..): scenario, record, issue type, DETECT / NOT_DETECT, behaviour, injection reason, is_planted | yes |
| data/ground_truth/boundary_cases.csv | BC-01..BC-10 records (GTB-0001..) with the expected outcome | yes |
| data/ground_truth/scenarios.json, ground_truth.json | planned and actual count per scenario; everything combined | yes |
| data/validation/validation_report.{csv,json,md}, validation_findings.csv | src/validation results, M1-M3 | no (regenerable) |
| data/validation/detections.csv | Phase 5: leave detections (record_type, record_id, exception_code, detected_by SUBMISSION or BATCH_DETECTOR, detail) | no (regenerable; checksummed) |
| data/manifest.json | seed, parameters, as-of date, generator version, row counts, ground-truth counts, scenarios_not_reached, SHA-256 per file (raw, processed, ground_truth, validation), generated_at | yes |

Scenarios the chosen scale cannot place in full are printed as `WARNING: scenario <id> partial: <actual> of <planned>
planned records ...` on stderr and listed in manifest.json under `scenarios_not_reached` (empty at full scale).

Run validation on its own: `python -m src.validation` (or `--data data\starter`). Exit code 0 = no check failed.
Compare the Phase 5 leave services with the independent oracle (every leave request; writes
data/validation/leave_service_vs_oracle.csv, not part of the manifest):
`python -m src.evaluation.leave_service_vs_oracle` (or `--raw data\starter\raw --out data\starter\validation`).
Exit code 0 = no disagreement; records whose only difference is a Phase 7 routing code are listed as ROUTING_PHASE7.
The same for expense claims (Phase 6): python -m src.evaluation.expense_service_vs_oracle (writes data/validation/expense_service_vs_oracle.csv).
Since Phase 6 every expense line carries quantity and unit_amount (ASM-P6-02) and detections.csv also holds expense detections.
Rebuild the negative fixtures (tests only, never in data/): `python scripts\build_negative_fixtures.py`.

## 4. Reproducibility rules

- One master seed -> numpy SeedSequence -> one child stream per name in `config/generation.yaml: streams`
  (employees, cost_centers, balances, leave, expenses, anomalies, boundaries, delays, payments, delegations, users,
  anomalies_expense, boundaries_expense). New stream names must be appended at the end of that list, or every
  later stream changes. S5 uses `anomalies` / `boundaries` for leave edits and `anomalies_expense` /
  `boundaries_expense` for expense edits, so stream independence also holds after injection (ASM-P4-02).
- `manifest.generated_at` is the time the content was FIRST generated: when a run produces exactly the same
  content, manifest.json is left untouched, so git shows no change (ASM-P4-17).
- Stream independence (CF-10): changing `--expense-claims` does not change any leave or master row, and changing
  `--leave-requests` does not change any expense row (tested). Changing `--employees` changes the people that
  requests reference, so leave and expense rows change too; that is expected.
- No wall clock: the as-of instant is 2026-10-22T00:00:00Z (FrozenClock). The only wall-clock value is
  `manifest.generated_at`, which is excluded from comparisons (ASM-050).
- Dependencies are pinned exactly (DEC-40). Upgrading Faker or numpy may change the data; rerun the
  reproducibility check and record the new fingerprint in PROGRESS.md if you upgrade on purpose.
- Fingerprint of the Phase 3 full baseline (seed 20261022, 400/800/1000): see PROGRESS.md.

## 5. Where each value comes from

| Kind | Examples | Source |
|---|---|---|
| Configuration | policies, limits, rules, holidays, FX, budget of CC-0024 | config/*.yaml |
| Raw random input | names, grades, departments, dates, durations, amounts, merchants, budgets | the stage's RNG stream |
| Calculated by shared rules | business days, requested quantity, accruals, policy version, local amounts, totals, receipt hash | src/services (DEC-37), src/common/money.py |
| Planted by construction (S5) | which records carry a scenario, scenario parameters | `anomalies*` / `boundaries*` streams |
| Expected by the independent oracle (S9) | expected codes, routes, outcomes, natural labels | src/reference (never src/services) |
| Decided by the workflow engine | validation results, routes, approvals, reimbursements | not yet: Phases 7-8 |

## 6. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: No module named 'src'` | run from the project root with `python -m src.data.generate` |
| `refusing to load into database '...'` | `--load` only accepts lea_dev or a *_test database (RK-13) |
| `could not draw a valid leave request` | volumes far above the design (many requests for few employees) exhaust balances; lower `--leave-requests` |
| fingerprint differs between machines | different package versions; compare `pip freeze` with requirements.txt |
