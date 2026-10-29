# Enterprise Leave and Expense Approval Automation System

A deterministic, rules-driven workflow engine for employee leave requests and expense claims, with a
seeded synthetic-data generator, separate ground truth, an evaluation suite, a FastAPI backend and a
Streamlit dashboard. All data is synthetic. All policy values are illustrative and labelled as assumptions.

Status: Phase 10 (Streamlit dashboard). See PROGRESS.md.

Start the API and the dashboard: `.\scripts\start_dashboard.ps1` (details in docs/13_dashboard_guide.md).

Generate the full baseline and load it into lea_dev (details in docs/11_generation_guide.md):

```powershell
python -m src.data.generate --seed 20261022 --employees 400 --leave-requests 800 --expense-claims 1000 --load
```

## Documents

| File | Content |
|---|---|
| docs/00_original_spec.md, docs/01_amendments.md | source of truth (amendments win on conflict) |
| docs/02 .. docs/09 | Phase 1: traceability, architecture, entities, rules, lifecycle, generation, evaluation, assumptions |
| docs/10_data_dictionary.md | Phase 2: every table and field |
| docs/11_generation_guide.md | Phase 3: generator commands, outputs, reproducibility |
| docs/13_dashboard_guide.md | Phase 10: dashboard views, login, data paths |
| docs/14_setup.md, docs/15_testing.md | how to set up and test |

## Quick start (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env        # then edit the passwords
# PostgreSQL: see docs/14_setup.md (local install, or docker compose up -d)
alembic upgrade head
pytest -q
```

## Layout

```
config/      illustrative policy and generation configuration (Phase 3)
data/        generated datasets, ground truth, validation output (Phase 3+)
docs/        specification, amendments, design documents, guides
migrations/  Alembic migrations (ops and ground_truth schemas)
sql/         roles, triggers, grants, test-only constraints, container init scripts
src/         common kernel, models, services, generator, reference oracle, validation, evaluation, api, dashboard
tests/       pytest suites; tests/db need the lea_test database
scripts/     setup and operational scripts
```

## Design in one paragraph

Workflow status, exception class, approval-step status, reimbursement status and technical failures are
separate dimensions. History is append-only and protected by triggers and role grants. Ground truth lives in
its own schema, is produced from planted-scenario definitions and an independent reference calculation, and
is readable only by the evaluation role. The generator calls the same business services as the API.

## Known limitations

- Simulated authentication only (amendment F2): synthetic users, a JWT from POST /auth/login. Not production security.
- First submissions (POST /leave-requests, POST /expense-claims) are not idempotent through the API: no client
  Idempotency-Key is accepted for them yet (AMB-P9-01). Decisions and reimbursements do require one.
- A token's roles are trusted until it expires (8 h); a role change or deactivation is not re-checked on every call
  (AMB-P9-02).
- Receipts cannot be attached through the API; no resubmission, cancellation or payment-run endpoints yet.
- The dashboard is read-only and open to approvers, process owners, analysts and admins (not to requesters).
