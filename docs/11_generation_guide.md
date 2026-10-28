# 11. Synthetic data generation guide

Phase 3 deliverable. How to run the generator, what it produces, and how to check that it is reproducible.
Design background: docs/07. Every policy value is an illustrative synthetic ASSUMPTION (docs/09).

## 1. What Phase 3 generates

| Stage (docs/07) | Status | Tables |
|---|---|---|
| S1 master | done | department, cost_center, cost_center_budget, employee, employee_cost_center_assignment, country_holiday, fx_rate, delegation, leave_policy, expense_policy, approval_rule, role, application_user, user_role |
| S2 balances | partly: OPENING + ACCRUAL | leave_balance (2025, 2026), leave_balance_transaction. CARRY_FORWARD and USAGE arrive with the Phase 7 engine |
| S3 leave | done (raw inputs) | leave_request: status SUBMITTED, about 1% DRAFT |
| S4 expenses | done (raw inputs) | expense_claim (SUBMITTED, about 1% DRAFT), expense_line (PENDING), receipt |
| S5 anomalies, S9 ground truth | Phase 4 | |
| S6 outcomes | Phase 7 | approval steps, events, exceptions, budget ledger |
| S7 reimbursements, S8 audit | Phase 8 | |

The Phase 3 dataset is a **valid baseline**: no overlaps, enough balance at submission, inside employment,
within policy limits, receipts where required, unique receipt hashes (DEC-41). Anomalies are added in Phase 4.

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
| data/manifest.json | seed, parameters, as-of date, generator version, row counts, SHA-256 per file, generated_at | yes |

## 4. Reproducibility rules

- One master seed -> numpy SeedSequence -> one child stream per name in `config/generation.yaml: streams`
  (employees, cost_centers, balances, leave, expenses, anomalies, boundaries, delays, payments, delegations, users).
  New stream names must be appended at the end of that list, or every later stream changes.
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
| Decided by the workflow engine | validation results, routes, approvals, reimbursements | not yet: Phases 7-8 |

## 6. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: No module named 'src'` | run from the project root with `python -m src.data.generate` |
| `refusing to load into database '...'` | `--load` only accepts lea_dev or a *_test database (RK-13) |
| `could not draw a valid leave request` | volumes far above the design (many requests for few employees) exhaust balances; lower `--leave-requests` |
| fingerprint differs between machines | different package versions; compare `pip freeze` with requirements.txt |
