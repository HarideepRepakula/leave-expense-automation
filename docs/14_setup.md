# 14. Setup instructions (Windows first, macOS/Linux notes at the end)

This guide gets a working PostgreSQL 16 and Python environment, applies the schema and runs the constraint tests. Nothing here needs an internet service other than package downloads.

## 0. What the machine already has (checked 2026-10-26)

| Item | Found | Needed |
|---|---|---|
| Python | 3.11.7 with pip 25.2 | yes, usable (spec says 3.12 "or compatible"; 3.11 is fine) |
| Git | 2.50.1 | yes, but the folder is not yet a repository (`git init` when you want history) |
| Docker | not installed | optional, see Option B |
| WSL 2 | not installed; firmware reports virtualization disabled | only needed for Docker Desktop |
| PostgreSQL | not installed, port 5432 free | needed, see Option A or B |
| winget | 1.29 | available for installs |

Recommendation: Option A (local PostgreSQL). Docker Desktop on Windows 11 Home needs WSL 2, which needs virtualization enabled in the BIOS/UEFI and a reboot. That is doable but is a bigger change to your machine.

## 1. Python environment (both options)

Open a PowerShell terminal in VS Code (Ctrl + `) at the project root.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If activation is blocked by execution policy, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then try again.

Create your local settings file:

```powershell
Copy-Item .env.example .env
```

Open .env and replace every `change-me-...` password with your own values. Keep the user names as they are. The two URL lines at the bottom of the database section must use the migrator password you chose.

## 2. Option A: local PostgreSQL 16 (recommended for this machine)

Install (one of):

```powershell
winget install --id PostgreSQL.PostgreSQL.16 -e
```

or download the EDB installer for PostgreSQL 16 from the PostgreSQL site and run it. During install, set a password for the `postgres` superuser and remember it; keep port 5432; you do not need Stack Builder.

Then create the project roles and databases (this reads your .env):

```powershell
.\scripts\init_local_db.ps1 -SuperuserPassword "<your postgres password>"
```

If psql is not at `C:\Program Files\PostgreSQL\16\bin\psql.exe`, pass `-PsqlPath` with the right location.

## 3. Option B: Docker Desktop

1. Enable virtualization in BIOS/UEFI (vendor-specific; usually "Intel VT-x" or "SVM Mode").
2. In an administrator PowerShell: `wsl --install`, then reboot.
3. Install Docker Desktop: `winget install --id Docker.DockerDesktop -e`, start it, accept WSL 2 backend.
4. From the project root: `docker compose up -d`. The first start runs sql/init/*.sql, which creates the roles and the lea_test database. Check with `docker compose ps` (state should be healthy).

## 4. Apply the schema

```powershell
alembic upgrade head
```

Expected: INFO lines ending with `Running upgrade  -> 0001_initial_schema, Initial schema`. To undo: `alembic downgrade base`.

## 5. Run the tests

```powershell
pytest -q
```

Database tests use TEST_DATABASE_URL (lea_test). They reset that database with downgrade/upgrade at the start of the run, add the test-only EXCLUDE constraint, and roll back every test. If the test database is not reachable the db tests are skipped with a reason, and the non-database tests still run.

## 6. macOS / Linux differences

- Virtual environment activation: `source .venv/bin/activate`.
- Docker: Docker Desktop (macOS) or the docker engine package (Linux); `docker compose up -d` is the same.
- Local PostgreSQL without Docker: install with Homebrew (`brew install postgresql@16`) or apt (`postgresql-16`), then run the SQL in sql/init/01_roles.sql and sql/init/02_test_database.sql with psql as the superuser, exporting LEA_APP_PASSWORD, LEA_ANALYTICS_PASSWORD, LEA_EVALUATION_PASSWORD and LEA_TEST_DB first (the scripts read them with backticks). A shell equivalent of scripts/init_local_db.ps1 is planned for Phase 3.

## 7. Troubleshooting (Phase 2)

| Symptom | Cause | Fix |
|---|---|---|
| `Database roles missing: [...]` from alembic | roles not created | run scripts/init_local_db.ps1 (Option A) or `docker compose down -v && docker compose up -d` (Option B) |
| `password authentication failed` | .env password differs from the role's password | re-run init_local_db.ps1 after fixing .env; it re-sets passwords |
| `refusing to run tests against non-test database` | TEST_DATABASE_URL points at lea_dev | fix the URL to end with /lea_test |
| db tests skipped: "test database not reachable" | PostgreSQL not running or wrong port | start the service (services.msc, postgresql-x64-16) or `docker compose up -d` |
| `extension "btree_gist" is not available` | test DB created without the init script | `psql -U postgres -d lea_test -c "CREATE EXTENSION btree_gist"` |

## 8. Start the API and the dashboard (Phase 10)

```powershell
alembic upgrade head              # once: migrations 0003 and 0004 add the analytics views
.\scripts\start_dashboard.ps1     # API in a new window (port 8000), dashboard here (http://localhost:8501)
```

Two windows by hand: `uvicorn src.api.main:create_app --factory --port 8000`, then
`streamlit run src/dashboard/app.py`. macOS / Linux: the same two commands in two terminals. Details:
docs/13_dashboard_guide.md.

## 9. One command sequence: prepared PostgreSQL to a verified system (Phases 11 + 12)

Once per machine: PostgreSQL 16 running; `copy .env.example .env` and fill in the passwords and JWT_SECRET;
`.\scripts\init_local_db.ps1 -SuperuserPassword "<postgres password>"` (or `docker compose up -d`); the venv:
`python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt`.

Then:

```powershell
.\scripts\run_all.ps1          # alembic upgrade head, generate --load, validation, both comparisons,
                               # reproducibility check, metrics, pytest; stops at the first failing step
.\scripts\start_dashboard.ps1  # API (http://localhost:8000/docs) in a new window, dashboard at http://localhost:8501
```

macOS / Linux (venv active, `cp .env.example .env`, roles via `docker compose up -d`):

```sh
alembic upgrade head
python -m src.data.generate --seed 20261022 --employees 400 --leave-requests 800 --expense-claims 1000 --load
python -m src.validation
python -m src.evaluation.leave_service_vs_oracle
python -m src.evaluation.expense_service_vs_oracle
sh scripts/reproducibility_check.sh
python -m src.evaluation.metrics
pytest -q
uvicorn src.api.main:create_app --factory --port 8000 &   # then, in another terminal:
streamlit run src/dashboard/app.py
```

To start from an empty schema first: `alembic downgrade base` (drops ops and ground_truth in lea_dev). Real output
of a full run: docs/12_final_evaluation.md.
