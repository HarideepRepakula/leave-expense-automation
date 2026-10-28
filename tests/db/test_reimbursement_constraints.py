"""Acceptance criteria 14 and 15: reimbursements only for approved claims; duplicates prevented (R-7.11, AM-F5)."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa

from tests.conftest import CORR, T0, approved_claim, expect_db_error

pytestmark = pytest.mark.db

DONE = datetime(2026, 1, 20, 12, 0, tzinfo=timezone.utc)


def _rmb(step_id, **over):
    base = dict(
        reimbursement_id="RMB-2026-000001", expense_claim_id="EXP-2026-000001", employee_id="EMP-000002",
        approved_amount=Decimal("1500.00"), currency="INR", eligibility_status="ELIGIBLE",
        reimbursement_status="ELIGIBLE", approval_completion_step_id=step_id, created_at=T0,
    )
    base.update(over)
    return base


def test_reimbursement_for_approved_claim_accepted(conn, tables, seed):
    step = approved_claim(conn, tables)
    conn.execute(sa.insert(tables["ops.reimbursement"]).values(**_rmb(step)))
    assert conn.execute(sa.text("SELECT count(*) FROM ops.reimbursement")).scalar() == 1


def test_reimbursement_for_pending_claim_rejected_by_trigger(conn, tables, seed):
    step = approved_claim(conn, tables)
    conn.execute(
        sa.update(tables["ops.expense_claim"])
        .where(tables["ops.expense_claim"].c.expense_claim_id == "EXP-2026-000001")
        .values(workflow_status="PENDING_APPROVAL", approved_amount=None)
    )
    expect_db_error(conn, sa.insert(tables["ops.reimbursement"]).values(**_rmb(step)), match="claim status is PENDING_APPROVAL")


def test_reimbursement_amount_must_match_claim(conn, tables, seed):
    step = approved_claim(conn, tables)
    expect_db_error(
        conn, sa.insert(tables["ops.reimbursement"]).values(**_rmb(step, approved_amount=Decimal("1499.00"))),
        match="does not match claim approved_amount",
    )


def test_reimbursement_employee_must_match_claim(conn, tables, seed):
    step = approved_claim(conn, tables)
    expect_db_error(
        conn, sa.insert(tables["ops.reimbursement"]).values(**_rmb(step, employee_id="EMP-000001")),
        match="does not match claim employee",
    )


def test_second_active_reimbursement_for_same_claim_rejected(conn, tables, seed):
    step = approved_claim(conn, tables)
    conn.execute(sa.insert(tables["ops.reimbursement"]).values(**_rmb(step)))
    expect_db_error(
        conn, sa.insert(tables["ops.reimbursement"]).values(**_rmb(step, reimbursement_id="RMB-2026-000002")),
        match="uq_reimbursement_active_per_claim",
    )


def test_new_reimbursement_allowed_after_cancellation(conn, tables, seed):
    step = approved_claim(conn, tables)
    conn.execute(sa.insert(tables["ops.reimbursement"]).values(**_rmb(step, reimbursement_status="CANCELLED")))
    conn.execute(sa.insert(tables["ops.reimbursement"]).values(**_rmb(step, reimbursement_id="RMB-2026-000002")))
    assert conn.execute(sa.text("SELECT count(*) FROM ops.reimbursement")).scalar() == 2


def test_completed_requires_completed_at(conn, tables, seed):
    step = approved_claim(conn, tables)
    expect_db_error(
        conn, sa.insert(tables["ops.reimbursement"]).values(**_rmb(step, reimbursement_status="COMPLETED")),
        match="completed_has_timestamp",
    )
    conn.execute(sa.insert(tables["ops.reimbursement"]).values(**_rmb(step, reimbursement_status="COMPLETED", completed_at=DONE)))


def test_blocked_duplicate_attempt_recorded_without_reimbursement_row(conn, tables, seed):
    """EC-13: the attempt table records the blocked duplicate; reimbursement count stays at one."""
    step = approved_claim(conn, tables)
    conn.execute(sa.insert(tables["ops.reimbursement"]).values(**_rmb(step)))
    conn.execute(
        sa.insert(tables["ops.reimbursement_attempt"]).values(
            attempt_id="RMA-000000001", actor_type="EMPLOYEE", actor_employee_id="EMP-000001",
            expense_claim_id="EXP-2026-000001", reimbursement_id="RMB-2026-000001", attempted_action="CREATE",
            attempted_at=T0, outcome="BLOCKED", reason_code="DUPLICATE_REIMBURSEMENT", correlation_id=CORR,
        )
    )
    assert conn.execute(sa.text("SELECT count(*) FROM ops.reimbursement")).scalar() == 1
    assert conn.execute(sa.text("SELECT count(*) FROM ops.reimbursement_attempt WHERE outcome = 'BLOCKED'")).scalar() == 1


def test_system_actor_has_no_employee_and_employee_actor_requires_one(conn, tables, seed):
    approved_claim(conn, tables)
    base = dict(
        attempt_id="RMA-000000002", expense_claim_id="EXP-2026-000001", reimbursement_id=None,
        attempted_action="PROCESS", attempted_at=T0, outcome="ACCEPTED", reason_code=None, correlation_id=CORR,
    )
    conn.execute(sa.insert(tables["ops.reimbursement_attempt"]).values(**base, actor_type="SYSTEM", actor_employee_id=None))
    expect_db_error(
        conn,
        sa.insert(tables["ops.reimbursement_attempt"]).values(
            **{**base, "attempt_id": "RMA-000000003"}, actor_type="EMPLOYEE", actor_employee_id=None
        ),
        match="employee_actor_has_id",
    )
