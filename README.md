# Enterprise Leave and Expense Approval Automation System

A deterministic, rules-driven workflow engine for employee leave requests and expense claims, with a
seeded synthetic-data generator, separate ground truth, an evaluation suite, a FastAPI backend and a
Streamlit dashboard. All data is synthetic. All policy values are illustrative and labelled as assumptions.

Status: Phase 2 (data dictionary, database schema, migrations). See PROGRESS.md.

## Documents

| File | Content |
|---|---|
| docs/00_original_spec.md, docs/01_amendments.md | source of truth (amendments win on conflict) |
| docs/02 .. docs/09 | Phase 1: traceability, architecture, entities, rules, lifecycle, generation, evaluation, assumptions |
| docs/10_data_dictionary.md | Phase 2: every table and field |
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
