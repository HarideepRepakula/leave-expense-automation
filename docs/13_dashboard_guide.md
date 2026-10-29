# 13. Dashboard guide (Phase 10)

One Streamlit app, `src/dashboard/app.py`, read-only. Synthetic data only; policy values are illustrative.

## Start it (Windows PowerShell, venv active, project root)

One launch script (opens the API in a second window, the dashboard in this one):

```powershell
.\scripts\start_dashboard.ps1
```

Or two windows by hand:

```powershell
# window 1
uvicorn src.api.main:create_app --factory --port 8000
# window 2
streamlit run src/dashboard/app.py
```

Open http://localhost:8501. The dashboard calls the API at `DASHBOARD_API_URL` (default http://127.0.0.1:8000).
macOS / Linux: the same two commands in two terminals; activate the venv with `source .venv/bin/activate`.
Before the first start: `alembic upgrade head` (migrations 0003 and 0004 create the analytics views),
`python -m src.validation` (writes the detector output and M1-M3) and, for M13, `.\scripts\reproducibility_check.ps1`.

## Log in

Use a synthetic dev user from `data/processed/dev_credentials.csv` (git-ignored, written by the generator). The
login goes to POST /auth/login (simulated authentication, amendment F2). Who sees what:

| Roles | Overview, Requests, Exceptions | Suspicious-pattern list | Evaluation |
|---|---|---|---|
| REQUESTER only | refused (the analytics views have no per-user filter) | - | - |
| APPROVER | yes | no (API 403, shown as a note) | no (API 403) |
| PROCESS_OWNER | yes | yes | no (API 403) |
| OPS_ANALYST, SYSTEM_ADMIN | yes | yes | yes |

## Views

| View | Shows | Source |
|---|---|---|
| Overview | counts by workflow status for leave and expense; claims, claimed and approved amounts per currency; reimbursements by status and amount; USD total from the stored conversion | analytics views |
| Requests | filterable table (type, status, exception class, country, id); detail panel: status, exception class, round, plain-language explanation with its source (llm or template), approval steps, status history, exception codes, expense lines | table: analytics views; detail: GET /leave-requests/{id}, /expense-claims/{id}, /requests/{id}/explanation |
| Exceptions | codes of the current round by severity (HARD / CORRECTABLE / SOFT / INFO), by code with class and severity, requests by exception class; suspicious-pattern detections (submission and batch detectors) | analytics views; GET /detections |
| Evaluation | M1-M18 with a breakdown per metric ("not measurable: reason" where the data cannot support it) and the "How to read these results" note; M1-M3, detection results (TP / FP / FN, precision, recall, per code), services vs oracle AGREE / DISAGREE, status at as-of vs expected | GET /evaluation only |
| Analytics (completion pass) | leave by type (approval / rejection rates), by country and department, insufficient-balance and overlap cases, turnaround; expenses by category, country, cost center, claimed vs approved per currency, missing receipts, duplicates, policy breaches, split claims, outside employment. Sidebar filters: submission dates, country, department, manager, status, cost center, category, exception type | analytics views |
| Approval operations (completion pass) | pending queue with age, requests awaiting each level, approval aging buckets, approver workload, average turnaround and time per level, blocked (unauthorized) approval attempts; same filters | analytics views |
| Reimbursements (completion pass) | eligible claims, awaiting, completed, amounts per currency, failed processing, failed payment attempts, duplicate reimbursement attempts | analytics views |

Overview (completion pass) also shows total employees, escalated and returned counts (the "Pending approval" caption
says PENDING_APPROVAL only), approved, rejected, requests with a policy exception and "High-priority issues" =
requests ESCALATED_FOR_REVIEW or with a HARD exception (current round) + OPEN reimbursement processing failures
(DEC-CP-03). For analysts the Requests detail comes from GET /requests/{id}/investigation and adds the applicable
policy, approval attempts, reimbursements and audit events. Ages are counted at the dataset as-of date.

## Data paths and isolation (docs/03 7.1, amendment F3)

- Aggregates: `ops.v_request`, `ops.v_request_exception`, `ops.v_reimbursement` as `lea_analytics_ro`, which has
  SELECT on these three views and nothing else (no table, no ground truth).
- Details, explanation, detections, evaluation: the API with the user's JWT.
- The dashboard never connects as lea_app or lea_evaluation and imports nothing from src/reference, src/evaluation,
  src/services, src/repositories or src/models. Only `evaluation_view.py` calls /evaluation
  (tests/dashboard/test_dashboard.py).

## KPI definitions used

- Counts by status: rows of v_request grouped by request_type and workflow_status.
- Claimed amount: exact sum of total_amount per currency; approved amount: sum of approved_amount of APPROVED claims.
- Reimbursed (completed) / awaiting payment: sum of reimbursement approved_amount with status COMPLETED / any other.
- Exceptions: request_exception rows of each request's current round; "requests with an exception" =
  exception_class <> NONE.
