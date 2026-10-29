"""API tests (Phase 9) with FastAPI's TestClient on lea_test: auth, one happy path per endpoint, idempotent replay,
a blocked self-approval and the isolation rule (operational routes never reach ground truth)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
import sqlalchemy as sa

from src.api.core import issue_token
from tests.api.conftest import DECIDE
from tests.conftest import ROOT, approved_claim
from tests.db.test_approval_steps_db import _head

pytestmark = pytest.mark.db
LEAVE = {"leave_policy_id": "LPOL-UNPAID-ALL-V1", "start_date": "2026-03-09", "end_date": "2026-03-10"}
CLAIM = {"lines": [{"category": "MEALS", "merchant_description": "Team meal", "expense_date": "2026-02-20",
                    "line_amount": "1500.00"}]}


def _rows(conn, t, name, **where) -> list[dict]:
    tb = t[f"ops.{name}"]
    q = sa.select(tb)
    for k, v in where.items():
        q = q.where(tb.c[k] == v)
    return [dict(r) for r in conn.execute(q).mappings()]


# --- auth -------------------------------------------------------------------------------------------------------

def test_login_returns_roles_from_user_role_and_routes_need_a_token(client, requester):
    r = client.get("/auth/me", headers=requester)
    assert r.json() == {"user_id": "USR-000002", "employee_id": "EMP-000002", "roles": ["APPROVER", "REQUESTER"]}
    bad = client.post("/auth/login", json={"username": "emp000002", "password": "wrong"})
    assert (bad.status_code, bad.json()["error"]["code"]) == (401, "INVALID_CREDENTIALS")
    for path in ("/leave-requests", "/expense-claims", "/evaluation", "/requests/LVE-2026-000911/explanation"):
        r = client.get(path)
        assert (r.status_code, r.json()["error"]["code"]) == (401, "NOT_AUTHENTICATED"), path
    r = client.get("/leave-requests", headers={"Authorization": "Bearer not-a-jwt"})
    assert (r.status_code, r.json()["error"]["code"]) == (401, "INVALID_TOKEN")


def test_roles_are_enforced(client, ctx):
    only_requester = {"Authorization": "Bearer " + issue_token(ctx.settings, "USR-000002", "EMP-000002",
                                                               ["REQUESTER"])}
    for method, path, body in (("get", "/evaluation", None),
                               ("post", "/reimbursements", {"expense_claim_id": "EXP-2026-000911"}),
                               ("post", "/requests/LVE-2026-000911/escalation-decision", {"action": "REJECT"})):
        r = client.request(method.upper(), path, headers={**only_requester, "Idempotency-Key": "k-roles-1"},
                           json=body)
        assert (r.status_code, r.json()["error"]["code"]) == (403, "FORBIDDEN_ROLE"), path


# --- leave: submit, self-approval, approve, replay, reads -------------------------------------------------------

def test_leave_submit_self_approval_approve_and_replay(client, ctx, conn, users, requester, manager):
    _head(conn, users, "EMP-000001")                     # one L3 step at EMP-000001 covers L1 and L3
    r = client.post("/leave-requests", json=LEAVE, headers=requester)
    assert r.status_code == 201, r.text
    body = r.json()
    rid, step = body["request"]["leave_request_id"], body["steps"][0]["approval_step_id"]
    assert (rid, body["request"]["workflow_status"], body["request"]["exception_class"]) == \
        ("LVE-2026-000912", "PENDING_APPROVAL", "NONE")
    assert [e["new_status"] for e in body["status_history"]] == ["SUBMITTED", "VALIDATING", "PENDING_APPROVAL"]

    ctx.clock.at = DECIDE
    url = f"/requests/{rid}/steps/{step}/decision"
    blocked = client.post(url, json={"action": "APPROVE"}, headers={**requester, "Idempotency-Key": "self-001"})
    assert (blocked.status_code, blocked.json()["error"]["code"]) == (403, "SELF_APPROVAL")
    assert blocked.json()["error"]["details"]["workflow_status"] == "PENDING_APPROVAL"
    assert [(a["outcome"], a["reason_code"]) for a in _rows(conn, users, "approval_attempt")] == \
        [("BLOCKED", "SELF_APPROVAL")]                 # the blocked attempt is committed (audit trail)

    ok = client.post(url, json={"action": "APPROVE"}, headers={**manager, "Idempotency-Key": "mgr-approve-1"})
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"request_id": rid, "outcome": "ACCEPTED", "reason_code": None, "replayed": False,
                         "workflow_status": "APPROVED"}
    replay = client.post(url, json={"action": "APPROVE"}, headers={**manager, "Idempotency-Key": "mgr-approve-1"})
    assert (replay.status_code, replay.json()["replayed"], replay.json()["workflow_status"]) == (200, True, "APPROVED")
    assert len(_rows(conn, users, "approval_attempt")) == 2          # the replay wrote no attempt
    other = client.post(url, json={"action": "REJECT"}, headers={**manager, "Idempotency-Key": "mgr-approve-1"})
    assert (other.status_code, other.json()["error"]["code"]) == (409, "IDEMPOTENCY_CONFLICT")

    got = client.get(f"/leave-requests/{rid}", headers=requester).json()
    assert got["request"]["workflow_status"] == "APPROVED" and got["steps"][0]["step_status"] == "APPROVED"
    assert got["status_history"][-1]["new_status"] == "APPROVED"
    listed = client.get("/leave-requests?limit=10&offset=0", headers=requester).json()
    assert rid in {i["leave_request_id"] for i in listed["items"]}


def test_process_owner_decides_an_escalated_leave(client, conn, users, requester, manager, ctx):
    _head(conn, users, None)                             # no L3 approver: NO_VALID_APPROVAL_PATH, escalated
    rid = client.post("/leave-requests", json=LEAVE, headers=requester).json()["request"]["leave_request_id"]
    assert client.get(f"/leave-requests/{rid}", headers=manager).json()["request"]["workflow_status"] == \
        "ESCALATED_FOR_REVIEW"
    ctx.clock.at = DECIDE
    r = client.post(f"/requests/{rid}/escalation-decision", headers={**manager, "Idempotency-Key": "po-reject-1"},
                    json={"action": "REJECT", "reason_code": "NO_VALID_APPROVAL_PATH"})
    assert r.status_code == 200, r.text
    assert (r.json()["outcome"], r.json()["workflow_status"]) == ("ACCEPTED", "REJECTED")


# --- expense ----------------------------------------------------------------------------------------------------

def test_expense_submit_get_and_list(client, requester, manager):
    r = client.post("/expense-claims", json=CLAIM, headers=requester)
    assert r.status_code == 201, r.text
    claim = r.json()
    cid = claim["request"]["expense_claim_id"]
    assert (claim["request"]["workflow_status"], claim["request"]["total_amount"], claim["request"]["currency"]) == \
        ("PENDING_APPROVAL", "1500.00", "INR")
    assert [ln["line_amount"] for ln in claim["lines"]] == ["1500.00"] and len(claim["steps"]) == 1
    got = client.get(f"/expense-claims/{cid}", headers=manager).json()
    assert got["status_history"][-1]["new_status"] == "PENDING_APPROVAL"
    assert cid in {i["expense_claim_id"] for i in client.get("/expense-claims", headers=requester).json()["items"]}
    bad = client.post("/expense-claims", json={"lines": []}, headers=requester)
    assert (bad.status_code, bad.json()["error"]["code"]) == (422, "VALIDATION_ERROR")


# --- reimbursement ----------------------------------------------------------------------------------------------

def test_reimbursement_create_read_and_duplicate(client, conn, users, manager, requester):
    approved_claim(conn, users)                          # EXP-2026-000001 APPROVED, no reimbursement yet
    r = client.post("/reimbursements", json={"expense_claim_id": "EXP-2026-000001"},
                    headers={**manager, "Idempotency-Key": "rmb-create-1"})
    assert r.status_code == 201, r.text
    rid = r.json()["reimbursement_id"]
    assert r.json()["detail"]["reimbursement"]["reimbursement_status"] == "ELIGIBLE"
    got = client.get(f"/reimbursements/{rid}", headers=requester)       # the claimant may read it
    assert (got.status_code, got.json()["reimbursement"]["approved_amount"]) == (200, "1500.00")
    dup = client.post("/reimbursements", json={"expense_claim_id": "EXP-2026-000001"},
                      headers={**manager, "Idempotency-Key": "rmb-create-2"})
    assert (dup.status_code, dup.json()["error"]["code"]) == (409, "DUPLICATE_REIMBURSEMENT")


# --- evaluation and isolation -----------------------------------------------------------------------------------

def test_evaluation_endpoint_returns_the_evaluation_summary(client, ctx, engine, manager):
    from src.evaluation.summary import summarize

    ctx.evaluation = lambda: summarize(engine, ROOT / "data" / "validation")
    r = client.get("/evaluation", headers=manager)
    assert r.status_code == 200, r.text
    comp = r.json()["comparisons"]
    assert comp["leave_service_vs_oracle"]["available"] and comp["expense_service_vs_oracle"]["available"]
    assert "DISAGREE" not in comp["leave_service_vs_oracle"] and "DISAGREE" not in comp["expense_service_vs_oracle"]
    assert r.json()["status_at_asof_vs_expected"] == []           # lea_test holds no ground-truth rows


def _imports(path: Path) -> set[str]:
    mods = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    return mods


def test_isolation_only_the_evaluation_route_reaches_src_evaluation():
    api = ROOT / "src" / "api"
    users = sorted(p.name for p in api.rglob("*.py") if any(m.startswith("src.evaluation") for m in _imports(p)))
    assert users == ["evaluation_routes.py"]
    assert not any(m.startswith("src.reference") for p in api.rglob("*.py") for m in _imports(p))
    summary = _imports(ROOT / "src" / "evaluation" / "summary.py")
    assert not any(m.startswith(("src.reference", "src.services")) for m in summary)
    explanation = _imports(ROOT / "src" / "services" / "explanation_service.py")
    assert not any(m.startswith(("src.evaluation", "src.reference", "src.repositories")) for m in explanation)


def test_isolation_operations_use_lea_app_which_cannot_read_ground_truth(test_url):
    from sqlalchemy.engine import make_url

    from src.api.main import build_context
    from src.common.config import Settings

    s = Settings(JWT_SECRET="x" * 40)
    ctx = build_context(s)
    assert ctx.engine.url.username == s.postgres_app_user == "lea_app"
    app_url = make_url(test_url).set(username=s.postgres_app_user, password=s.postgres_app_password)
    eng = sa.create_engine(app_url, poolclass=sa.pool.NullPool)
    try:
        with eng.connect() as c:
            assert c.execute(sa.text("SELECT count(*) FROM ops.leave_request")).scalar() is not None
            with pytest.raises(sa.exc.ProgrammingError, match="permission denied"):
                c.execute(sa.text("SELECT count(*) FROM ground_truth.record_expectation"))
    finally:
        eng.dispose()
