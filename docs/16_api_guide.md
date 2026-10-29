# 16. API usage guide

FastAPI app `src/api/main.py`. Synthetic data only; simulated authentication (amendment F2), not production
security. Interactive docs (Swagger / OpenAPI): http://localhost:8000/docs once the API runs.

## Start

```powershell
uvicorn src.api.main:create_app --factory --port 8000      # needs JWT_SECRET and role passwords in .env
```

## Log in and call a route (PowerShell)

```powershell
$cred = Import-Csv data\processed\dev_credentials.csv | Where-Object user_id -eq "USR-000010"   # an OPS_ANALYST
$login = Invoke-RestMethod -Method Post http://localhost:8000/auth/login -ContentType application/json `
         -Body (@{username=$cred.username; password=$cred.password} | ConvertTo-Json)
$h = @{Authorization = "Bearer $($login.access_token)"}
Invoke-RestMethod http://localhost:8000/dashboard/metrics -Headers $h
Invoke-RestMethod "http://localhost:8000/approval-queue?limit=5" -Headers $h
```

macOS / Linux: `curl -s -X POST localhost:8000/auth/login -H 'Content-Type: application/json' -d '{"username":"...","password":"..."}'`,
then `curl -H "Authorization: Bearer $TOKEN" localhost:8000/dashboard/metrics`.

Errors always have the shape `{"error": {"code", "message", "details"}}` (401 NOT_AUTHENTICATED / INVALID_TOKEN /
TOKEN_EXPIRED, 403 FORBIDDEN_ROLE / SELF_APPROVAL / UNAUTHORIZED_APPROVER, 404 NOT_FOUND, 409 conflicts and blocked
attempts, 422 VALIDATION_ERROR). Money and quantities are exact decimal strings; times are ISO-8601.

## Routes

| Method and path | Roles | Notes |
|---|---|---|
| POST /auth/login, GET /auth/me | anyone / logged in | JWT HS256, 8 h |
| POST /leave-requests, POST /expense-claims | REQUESTER | creates and submits in one transaction |
| GET /leave-requests, /expense-claims (+ /{id}) | logged in | a requester sees only their own |
| POST /requests/{id}/steps/{step}/decision | APPROVER, PROCESS_OWNER | APPROVE / REJECT / RETURN; header Idempotency-Key required |
| POST /requests/{id}/escalation-decision | PROCESS_OWNER, APPROVER | for ESCALATED_FOR_REVIEW; Idempotency-Key |
| POST /reimbursements, GET /reimbursements/{id} | analysts, process owners, admins / owner | duplicates are 409 and recorded |
| GET /employees | APPROVER, PROCESS_OWNER, OPS_ANALYST, SYSTEM_ADMIN | names, e-mail, employment dates only for SYSTEM_ADMIN |
| GET /leave-policies, /expense-policies | logged in | filters: country, type / category, is_active |
| GET /leave-balances, /expense-lines | logged in | a requester sees only their own |
| GET /approval-queue | staff roles | an approver sees only their own queue |
| GET /requests/{id}/audit-history | PROCESS_OWNER, OPS_ANALYST, SYSTEM_ADMIN | audit events of request, steps, reimbursements |
| GET /requests/{id}/investigation | same | request, lines, applicable policies, steps, exceptions, attempts, audit |
| GET /dashboard/metrics | staff roles | operational KPIs incl. high-priority issues (DEC-CP-03) |
| GET /detections | PROCESS_OWNER, OPS_ANALYST, SYSTEM_ADMIN | detector output (data/validation/detections.csv) |
| GET /requests/{id}/explanation | logged in (own requests for requesters) | plain-language text; Groq when enabled, else template |
| GET /evaluation | OPS_ANALYST, SYSTEM_ADMIN | M1-M18 and comparisons; the only route reading ground truth (lea_evaluation) |

Lists take `limit` (1-200, default 50) and `offset`. Decision details: docs/05 section 5, docs/06; decisions on
roles and fields: docs/09 sections 14-16.
