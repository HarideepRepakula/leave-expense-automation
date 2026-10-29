# 17. Configuration reference

All policy values are ILLUSTRATIVE SYNTHETIC assumptions (each file has `illustrative_synthetic: true`; IDs in
docs/09). Changing a value changes the generated dataset and its fingerprint.

## config/*.yaml

| File | Top-level keys | Used by |
|---|---|---|
| generation.yaml | master_seed (20261022), as_of_date (2026-10-22), window_start, master_load_timestamp, streams (independent seeded RNG streams), volumes, employees, delegations, users, timeline, leave, expenses, anomalies, decisions, payments, boundaries | generator (docs/07, docs/11); as_of_date also by metrics and dashboard ages |
| organisation.yaml | departments, cost_center_countries, cost_center_effective_from, budgets | generator (master data) |
| calendar.yaml | weekend_days (ISO weekday numbers), holidays, fx_rates | business days, FX conversion |
| leave_policies.yaml | policies, common | leave policy versions (docs/05 sections 1-2) |
| expense_policies.yaml | reference_rate_date, local_rounding, countries, categories, per_claim_limit_usd, receipt_threshold_usd, per_line_limit_usd, default_effective_start, detection (duplicate / split-claim parameters), versioned | expense policy versions and detectors (docs/05 sections 3, 7) |
| approval_rules.yaml | effective_start, rules (bands, levels, priority) | approval routing; the decision table is docs/05 section 5.2 |
| exception_codes.yaml | process_owner_decisions, codes (class, severity, default route, messages) | exception catalogue (docs/05 section 9) |
| llm.yaml | provider, endpoint, default_model, timeout_seconds, retries_on_transient_error, max_completion_tokens, temperature, documented_limits | Groq explanation layer only (docs/09 section 14) |

## .env (copy .env.example; never commit .env)

| Variable | Meaning |
|---|---|
| POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DEV_DB, POSTGRES_TEST_DB | server and database names (lea_dev, lea_test) |
| POSTGRES_MIGRATOR_USER / _PASSWORD | owner role: Alembic, generator load |
| POSTGRES_APP_USER / _PASSWORD | lea_app: the API |
| POSTGRES_ANALYTICS_USER / _PASSWORD | lea_analytics_ro: dashboard, SELECT on ops views only |
| POSTGRES_EVALUATION_USER / _PASSWORD | lea_evaluation: src/evaluation only (ops + ground_truth) |
| DATABASE_URL, TEST_DATABASE_URL | migrator URLs for lea_dev and lea_test |
| AS_OF_DATE | simulated "today" (2026-10-22); the wall clock is never used for rules |
| JWT_SECRET, JWT_EXPIRES_MINUTES | API token signing (generate your own secret) and lifetime (480) |
| LLM_EXPLANATIONS_ENABLED, GROQ_API_KEY, GROQ_MODEL | optional Groq explanations; off by default; empty model = llm.yaml default |
| DASHBOARD_API_URL (optional, environment) | API base URL for the dashboard (default http://127.0.0.1:8000) |

## Generator CLI

`python -m src.data.generate --seed --employees --leave-requests --expense-claims --out --load` (docs/11 section 3).
Baseline: seed 20261022, 400 / 800 / 1000.
