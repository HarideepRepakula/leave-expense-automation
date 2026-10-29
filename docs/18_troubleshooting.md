# 18. Troubleshooting guide

Collects the known problems in one place. Setup-specific tables stay in docs/14 section 7 (database) and docs/11
section 6 (generator).

| Symptom | Cause | Fix |
|---|---|---|
| `Database roles missing` / `password authentication failed` | roles not created or .env password differs | `.\scripts\init_local_db.ps1 -SuperuserPassword "..."` (re-sets passwords) or `docker compose up -d` |
| `refusing to run tests against non-test database` | TEST_DATABASE_URL points at lea_dev | end the URL with /lea_test |
| many tests skipped ("not reachable") | PostgreSQL stopped, or role passwords / JWT_SECRET missing in .env | start the service; fill .env |
| `ModuleNotFoundError: No module named 'src'` | not run from the project root | `cd` to the root and use `python -m ...` |
| `refusing to load into database` | `--load` only accepts lea_dev or *_test | fix DATABASE_URL |
| fingerprint differs from PROGRESS.md | different package versions (numpy) | `pip install -r requirements.txt` (numpy 2.2.6) |
| a PowerShell script stops at an alembic `INFO` line (NativeCommandError) | Windows PowerShell 5.1 treats native stderr as an error under `$ErrorActionPreference = "Stop"` | scripts use "Continue" and check `$LASTEXITCODE` (scripts/run_all.ps1) |
| dashboard: `relation "ops.v_..." does not exist` / permission denied | migrations 0003 / 0004 not applied | `alembic upgrade head` |
| dashboard: "cannot reach the API" | API not started or wrong DASHBOARD_API_URL | `uvicorn src.api.main:create_app --factory --port 8000` |
| API: `JWT_SECRET is empty` | .env has no secret | `python -c "import secrets; print(secrets.token_urlsafe(48))"`, paste into .env |
| explanation shows "Source: template" | LLM_EXPLANATIONS_ENABLED=false, no GROQ_API_KEY, timeout, rate limit or output check failed | intended fallback; the reason is shown next to the text |
| Evaluation shows "not measurable: ... missing" | validation / reproducibility not run | `python -m src.validation`; `.\scripts\reproducibility_check.ps1` |
| dashboard counts include API test rows | requests created through the API after the load | regenerate: `python -m src.data.generate ... --load` |
