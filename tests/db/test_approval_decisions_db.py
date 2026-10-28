"""Decisions, process-owner decisions and resubmission through the PostgreSQL stores (Phase 7B; docs/06 8.2, 8.3).

Runs in lea_test inside the rolled-back `conn` transaction, on the world of tests/db/test_approval_steps_db.py:
EMP-000002 (requester) reports to EMP-000001. EMP-000001 gets an application_user (the idempotency scope) and, where
a test needs it, the PROCESS_OWNER role."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa

from src.repositories.base import allocate_ledger_ids
from src.repositories.expense_repository import SqlExpenseStore
from src.repositories.leave_repository import SqlLeaveStore
from src.services.approval_service import DecisionRefused, decide_escalated, decide_step
from src.services.expense_service import submit_expense
from src.services.leave_request_service import submit_leave
from tests.conftest import T0
from tests.db.test_approval_steps_db import CATALOGUE, EXP, LVE, PARAMS, SUBMIT, WEEKEND, _head, world  # noqa: F401

pytestmark = pytest.mark.db
DECIDE = datetime(2026, 3, 4, 17, 0, tzinfo=timezone.utc)
CORR = uuid.UUID(int=11)


@pytest.fixture()
def users(conn, world):  # noqa: F811
    t = world
    conn.execute(sa.insert(t["ops.application_user"]).values(
        user_id="USR-000001", username="emp000001", password_hash="$2b$12$synthetic-hash-placeholder",
        employee_id="EMP-000001", is_active=True, created_at=T0))
    return t


def _po(conn, t) -> None:
    conn.execute(sa.insert(t["ops.role"]).values(role_id="ROLE-PROCESS_OWNER", role_name="PROCESS_OWNER",
                                                 description="Resolves escalated requests"))
    conn.execute(sa.insert(t["ops.user_role"]).values(user_id="USR-000001", role_id="ROLE-PROCESS_OWNER"))


def _rows(conn, t, name, **where) -> list[dict]:
    tb = t[f"ops.{name}"]
    q = sa.select(tb)
    for k, v in where.items():
        q = q.where(tb.c[k] == v)
    return [dict(r) for r in conn.execute(q).mappings()]


def test_blocked_then_accepted_leave_approval(conn, users):
    t = users
    _head(conn, t, "EMP-000001")
    submit_leave(SqlLeaveStore(conn, WEEKEND), LVE, CATALOGUE, SUBMIT, "EMP-000002", CORR)
    blocked = decide_step(SqlLeaveStore(conn, WEEKEND), LVE, f"APR-{LVE}-01", "EMP-000002", "APPROVE", DECIDE, CORR)
    assert (blocked.outcome, blocked.reason_code) == ("BLOCKED", "SELF_APPROVAL")
    res = decide_step(SqlLeaveStore(conn, WEEKEND), LVE, f"APR-{LVE}-01", "EMP-000001", "APPROVE", DECIDE, CORR)
    assert res.outcome == "ACCEPTED"
    assert [(a["attempt_id"], a["outcome"], a["reason_code"]) for a in
            sorted(_rows(conn, t, "approval_attempt"), key=lambda a: a["attempt_id"])] == \
        [("APA-000000001", "BLOCKED", "SELF_APPROVAL"), ("APA-000000002", "ACCEPTED", None)]
    step = _rows(conn, t, "approval_step", leave_request_id=LVE)[0]
    assert (step["step_status"], step["decision_at"]) == ("APPROVED", DECIDE)
    assert _rows(conn, t, "leave_request", leave_request_id=LVE)[0]["workflow_status"] == "APPROVED"
    assert {(r["actor_user_id"], r["operation"], r["status"]) for r in _rows(conn, t, "idempotency_record")} == \
        {("USR-000002", "APPROVE", "COMPLETED"), ("USR-000001", "APPROVE", "COMPLETED")}
    assert [e["new_status"] for e in sorted(_rows(conn, t, "request_status_event", leave_request_id=LVE),
                                             key=lambda e: e["event_id"])][-1] == "APPROVED"
    replay = decide_step(SqlLeaveStore(conn, WEEKEND), LVE, f"APR-{LVE}-01", "EMP-000001", "APPROVE", DECIDE, CORR)
    assert replay.replayed and len(_rows(conn, t, "approval_attempt")) == 2


def test_process_owner_on_an_escalated_leave(conn, users):
    t = users
    _head(conn, t, None)                                         # no L3: NO_VALID_APPROVAL_PATH
    submit_leave(SqlLeaveStore(conn, WEEKEND), LVE, CATALOGUE, SUBMIT, "EMP-000002", CORR)
    blocked = decide_escalated(SqlLeaveStore(conn, WEEKEND), LVE, "EMP-000001", "REJECT", DECIDE, CORR)
    assert blocked.reason_code == "UNAUTHORIZED_APPROVER"        # not a process owner yet
    _po(conn, t)
    with pytest.raises(DecisionRefused):
        decide_escalated(SqlLeaveStore(conn, WEEKEND), LVE, "EMP-000001", "APPROVE", DECIDE, CORR)
    # The blocked REJECT completed its derived key (docs/06 8.2 step 5): a retry needs a new client key.
    res = decide_escalated(SqlLeaveStore(conn, WEEKEND), LVE, "EMP-000001", "REJECT", DECIDE, CORR,
                           idempotency_key="b" * 64, reason_code="NO_VALID_APPROVAL_PATH")
    assert res.outcome == "ACCEPTED"
    r = _rows(conn, t, "leave_request", leave_request_id=LVE)[0]
    assert (r["workflow_status"], r["decision_reason_code"]) == ("REJECTED", "NO_VALID_APPROVAL_PATH")
    attempts = sorted(_rows(conn, t, "approval_attempt"), key=lambda a: a["attempt_id"])
    assert [(a["approval_step_id"], a["outcome"]) for a in attempts] == [(None, "BLOCKED"), (None, "ACCEPTED")]


def test_expense_approval_return_release_and_resubmission(conn, users):
    t = users
    submit_expense(SqlExpenseStore(conn, PARAMS), EXP, CATALOGUE, SUBMIT, "EMP-000002", CORR)
    decide_step(SqlExpenseStore(conn, PARAMS), EXP, f"APR-{EXP}-01", "EMP-000001", "RETURN", DECIDE, CORR)
    claim = _rows(conn, t, "expense_claim", expense_claim_id=EXP)[0]
    assert claim["workflow_status"] == "RETURNED_FOR_CORRECTION"
    assert [(x["txn_type"], x["amount"]) for x in sorted(_rows(conn, t, "cost_center_transaction"),
                                                        key=lambda x: x["transaction_id"])] == \
        [("RESERVATION", Decimal("1500.00")), ("RELEASE", Decimal("1500.00"))]
    assert _rows(conn, t, "cost_center_budget")[0]["committed_amount"] == Decimal("0.00")
    new = [{"category": "MEALS", "merchant_description": "Team meal", "expense_date": date(2026, 2, 20),
            "quantity": Decimal("1"), "unit_amount": Decimal("1200.00"), "line_amount": Decimal("1200.00"),
            "currency": "INR", "receipt_id": None}]
    again = submit_expense(SqlExpenseStore(conn, PARAMS), EXP, CATALOGUE, datetime(2026, 3, 5, 9, tzinfo=timezone.utc),
                           "EMP-000002", CORR, new_lines=new)
    assert (again.status, again.submission_round) == ("PENDING_APPROVAL", 2)
    claim = _rows(conn, t, "expense_claim", expense_claim_id=EXP)[0]
    assert (claim["current_round"], claim["total_amount"], claim["first_submitted_at"]) == \
        (2, Decimal("1200.00"), SUBMIT)
    lines = sorted(_rows(conn, t, "expense_line", expense_claim_id=EXP), key=lambda ln: ln["line_number"])
    assert [(ln["line_number"], ln["submission_round"], ln["line_amount"]) for ln in lines] == \
        [(1, 1, Decimal("1500.00")), (2, 2, Decimal("1200.00"))]
    steps = sorted(_rows(conn, t, "approval_step", expense_claim_id=EXP), key=lambda s: s["sequence_no"])
    assert [(s["sequence_no"], s["submission_round"], s["step_status"]) for s in steps] == \
        [(1, 1, "CANCELLED"), (2, 2, "PENDING")]
    res = decide_step(SqlExpenseStore(conn, PARAMS), EXP, f"APR-{EXP}-02", "EMP-000001", "APPROVE",
                      datetime(2026, 3, 6, 17, tzinfo=timezone.utc), CORR)
    assert res.new_status == "APPROVED"
    claim = _rows(conn, t, "expense_claim", expense_claim_id=EXP)[0]
    assert (claim["workflow_status"], claim["approved_amount"]) == ("APPROVED", Decimal("1200.00"))
    assert _rows(conn, t, "cost_center_budget")[0]["committed_amount"] == Decimal("1200.00")
    assert {r["operation"] for r in _rows(conn, t, "idempotency_record")} == {"APPROVE", "RESUBMIT"}


def test_ledger_ids_continue_per_year(conn, users):
    assert allocate_ledger_ids(conn, 2031, 2) == ["LBT-2031-000001", "LBT-2031-000002"]
    assert allocate_ledger_ids(conn, 2031, 1) == ["LBT-2031-000003"]
