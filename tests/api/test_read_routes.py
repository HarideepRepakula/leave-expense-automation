"""Read-only routes of the completion pass (src/api/read_routes.py) on lea_test: one test per endpoint and one role
test. World: tests/api/conftest.py (EMP-000002 requester reports to EMP-000001; USR-000001 = EMP-000001 with
APPROVER, PROCESS_OWNER, OPS_ANALYST)."""
from __future__ import annotations

import pytest
import sqlalchemy as sa

from src.api.core import issue_token
from tests.api.test_api import CLAIM, LEAVE
from tests.db.test_approval_steps_db import _head

pytestmark = pytest.mark.db


def _token(ctx, user_id: str, employee_id: str, roles: list[str]) -> dict:
    return {"Authorization": "Bearer " + issue_token(ctx.settings, user_id, employee_id, roles)}


@pytest.fixture()
def leave_id(client, conn, users, requester) -> str:
    _head(conn, users, "EMP-000001")                     # one pending step at EMP-000001
    r = client.post("/leave-requests", json=LEAVE, headers=requester)
    assert r.status_code == 201, r.text
    return r.json()["request"]["leave_request_id"]


@pytest.fixture()
def claim_id(client, requester) -> str:
    r = client.post("/expense-claims", json=CLAIM, headers=requester)
    assert r.status_code == 201, r.text
    return r.json()["request"]["expense_claim_id"]


def test_staff_only_routes_refuse_a_requester(client, ctx, leave_id):
    only_requester = _token(ctx, "USR-000002", "EMP-000002", ["REQUESTER"])
    for path in ("/employees", "/approval-queue", f"/requests/{leave_id}/audit-history",
                 f"/requests/{leave_id}/investigation", "/dashboard/metrics"):
        r = client.get(path, headers=only_requester)
        assert (r.status_code, r.json()["error"]["code"]) == (403, "FORBIDDEN_ROLE"), path


def test_employees_hide_personal_fields_except_for_admins(client, ctx, manager):
    r = client.get("/employees", params={"limit": 1}, headers=manager)
    assert r.status_code == 200 and r.json()["limit"] == 1 and len(r.json()["items"]) == 1
    assert "full_name" not in r.json()["items"][0] and "email" not in r.json()["items"][0]
    admin = _token(ctx, "USR-000001", "EMP-000001", ["SYSTEM_ADMIN"])
    item = client.get("/employees", params={"limit": 1}, headers=admin).json()["items"][0]
    assert {"full_name", "email"} <= set(item)


def test_policies_are_readable_by_any_user(client, requester):
    leave = client.get("/leave-policies", headers=requester).json()["items"]
    assert "LPOL-UNPAID-ALL-V1" in {p["leave_policy_id"] for p in leave}
    r = client.get("/expense-policies", params={"category": "MEALS"}, headers=requester)
    assert r.status_code == 200 and all(p["category"] == "MEALS" for p in r.json()["items"])


def test_leave_balances_requester_sees_only_their_own(client, requester, manager):
    own = client.get("/leave-balances", params={"employee_id": "EMP-000001"}, headers=requester).json()["items"]
    assert all(b["employee_id"] == "EMP-000002" for b in own)
    other = client.get("/leave-balances", params={"employee_id": "EMP-000001"}, headers=manager).json()["items"]
    assert all(b["employee_id"] == "EMP-000001" for b in other)


def test_expense_lines_of_own_claims_only(client, ctx, claim_id, requester):
    lines = client.get("/expense-lines", params={"expense_claim_id": claim_id}, headers=requester).json()["items"]
    assert [ln["line_amount"] for ln in lines] == ["1500.00"] and "merchant_description" not in lines[0]
    stranger = _token(ctx, "USR-000001", "EMP-000001", ["REQUESTER"])
    assert client.get("/expense-lines", params={"expense_claim_id": claim_id}, headers=stranger).json()["items"] == []


def test_approval_queue_approver_sees_only_their_own(client, ctx, leave_id, manager):
    everyone = client.get("/approval-queue", headers=manager).json()["items"]
    assert leave_id in {s["request_id"] for s in everyone}
    head = _token(ctx, "USR-000001", "EMP-000001", ["APPROVER"])
    assert {s["approver_employee_id"] for s in client.get("/approval-queue", headers=head).json()["items"]} == \
        {"EMP-000001"}
    other = _token(ctx, "USR-000002", "EMP-000002", ["APPROVER"])
    asked = client.get("/approval-queue", params={"approver_employee_id": "EMP-000001"}, headers=other)
    assert asked.json()["items"] == []                   # the filter is replaced by the caller's own id


def test_audit_history_of_a_request(client, leave_id, manager):
    r = client.get(f"/requests/{leave_id}/audit-history", headers=manager)
    assert r.status_code == 200, r.text
    events = r.json()["items"]
    assert events and {e["entity_type"] for e in events} <= {"leave_request", "approval_step"}
    assert client.get("/requests/LVE-2026-999999/audit-history", headers=manager).status_code == 404


def test_investigation_returns_request_lines_policy_steps_and_audit(client, claim_id, manager):
    r = client.get(f"/requests/{claim_id}/investigation", headers=manager)
    assert r.status_code == 200, r.text
    d = r.json()
    assert {"request", "lines", "policies", "steps", "status_history", "exceptions", "approval_attempts",
            "reimbursements", "audit_events"} <= set(d)
    assert len(d["lines"]) == 1 and d["audit_events"]
    assert all({"exception_class", "severity"} <= set(x) for x in d["exceptions"])


def test_dashboard_metrics_match_direct_counts(client, conn, leave_id, claim_id, manager):
    m = client.get("/dashboard/metrics", headers=manager).json()
    direct = conn.execute(sa.text(
        "SELECT (SELECT count(*) FROM ops.employee), (SELECT count(*) FROM ops.leave_request), "
        "(SELECT count(*) FROM ops.expense_claim)")).one()
    assert (m["employees"], m["leave_requests"], m["expense_claims"]) == tuple(direct)
    assert m["high_priority_issues"] == m["escalated_or_hard_requests"] + m["open_payment_failures"]
