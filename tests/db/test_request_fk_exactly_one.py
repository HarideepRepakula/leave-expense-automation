"""DEC-03 (review item 2): request references are real FKs with exactly one populated."""
from datetime import date

import pytest
import sqlalchemy as sa

from tests.conftest import CORR, T0, expect_db_error

pytestmark = pytest.mark.db


@pytest.fixture()
def pending_claim(conn, tables, seed):
    conn.execute(
        sa.insert(tables["ops.expense_claim"]).values(
            expense_claim_id="EXP-2026-000001", employee_id="EMP-000002", first_submitted_at=T0,
            claim_period_start=date(2026, 1, 10), claim_period_end=date(2026, 1, 10), country="IN", currency="INR",
            cost_center_id="CC-0001", expense_policy_id="XPOL-MEALS-IN-V1", total_amount=1500,
            workflow_status="PENDING_APPROVAL", exception_class="NONE", receipt_status="NOT_REQUIRED",
            current_round=1, created_at=T0,
        )
    )
    conn.execute(
        sa.insert(tables["ops.leave_request"]).values(
            leave_request_id="LVE-2026-000001", employee_id="EMP-000002", leave_policy_id="LPOL-ANNUAL-IN-V1",
            start_date=date(2026, 2, 2), end_date=date(2026, 2, 3), first_submitted_at=T0, current_round=1,
            business_day_count=2, requested_quantity=2, workflow_status="PENDING_APPROVAL", exception_class="NONE",
            medical_cert_flag=False, created_at=T0,
        )
    )
    return "EXP-2026-000001"


def _step(**over):
    base = dict(
        approval_step_id="APR-EXP-2026-000001-01", request_type="EXPENSE", leave_request_id=None,
        expense_claim_id="EXP-2026-000001", submission_round=1, sequence_no=1, approval_rule_id="RULE-E-001",
        required_level="L1", covered_levels=["L1"], approver_employee_id="EMP-000001", step_status="PENDING",
        assigned_at=T0,
    )
    base.update(over)
    return base


def test_step_with_no_request_fk_rejected(conn, tables, pending_claim):
    expect_db_error(
        conn, sa.insert(tables["ops.approval_step"]).values(**_step(expense_claim_id=None)), match="exactly_one_request_fk"
    )


def test_step_with_both_request_fks_rejected(conn, tables, pending_claim):
    expect_db_error(
        conn,
        sa.insert(tables["ops.approval_step"]).values(**_step(leave_request_id="LVE-2026-000001")),
        match="exactly_one_request_fk",
    )


def test_step_request_type_must_match_populated_fk(conn, tables, pending_claim):
    expect_db_error(
        conn, sa.insert(tables["ops.approval_step"]).values(**_step(request_type="LEAVE")), match="request_type_matches_fk"
    )


def test_step_with_exactly_one_fk_accepted(conn, tables, pending_claim):
    conn.execute(sa.insert(tables["ops.approval_step"]).values(**_step()))
    row = conn.execute(sa.text("SELECT expense_claim_id FROM ops.approval_step WHERE approval_step_id = 'APR-EXP-2026-000001-01'")).one()
    assert row[0] == "EXP-2026-000001"


def test_step_fk_must_reference_existing_request(conn, tables, pending_claim):
    expect_db_error(
        conn,
        sa.insert(tables["ops.approval_step"]).values(**_step(approval_step_id="APR-EXP-2026-000999-01", expense_claim_id="EXP-2026-000999")),
        match="foreign key",
    )


def test_step_id_must_match_request_and_sequence(conn, tables, pending_claim):
    expect_db_error(
        conn,
        sa.insert(tables["ops.approval_step"]).values(**_step(approval_step_id="APR-EXP-2026-000001-02")),
        match="id_matches_request_and_sequence",
    )


def test_approval_attempt_request_id_must_equal_populated_fk(conn, tables, pending_claim):
    base = dict(
        attempt_id="APA-000000001", actor_id="EMP-000002", request_type="EXPENSE", leave_request_id=None,
        expense_claim_id="EXP-2026-000001", submission_round=1, approval_step_id=None, attempted_action="APPROVE",
        attempted_at=T0, outcome="BLOCKED", reason_code="SELF_APPROVAL", correlation_id=CORR,
    )
    expect_db_error(
        conn, sa.insert(tables["ops.approval_attempt"]).values(**base, request_id="EXP-2026-000002"), match="request_id_matches_fk"
    )
    conn.execute(sa.insert(tables["ops.approval_attempt"]).values(**base, request_id="EXP-2026-000001"))


def test_blocked_attempt_requires_reason_and_accepted_forbids_it(conn, tables, pending_claim):
    base = dict(
        attempt_id="APA-000000002", actor_id="EMP-000001", request_type="EXPENSE", request_id="EXP-2026-000001",
        leave_request_id=None, expense_claim_id="EXP-2026-000001", submission_round=1, approval_step_id=None,
        attempted_action="APPROVE", attempted_at=T0, correlation_id=CORR,
    )
    expect_db_error(conn, sa.insert(tables["ops.approval_attempt"]).values(**base, outcome="BLOCKED", reason_code=None), match="blocked_has_reason")
    expect_db_error(
        conn, sa.insert(tables["ops.approval_attempt"]).values(**base, outcome="ACCEPTED", reason_code="X"), match="blocked_has_reason"
    )


def test_status_event_for_leave_and_expense_use_their_own_fk(conn, tables, pending_claim):
    t = tables["ops.request_status_event"]
    conn.execute(
        sa.insert(t).values(
            event_id="RSE-000000001", request_type="LEAVE", leave_request_id="LVE-2026-000001", expense_claim_id=None,
            submission_round=1, previous_status="SUBMITTED", new_status="VALIDATING", actor_id=None, occurred_at=T0,
            correlation_id=CORR,
        )
    )
    conn.execute(
        sa.insert(t).values(
            event_id="RSE-000000002", request_type="EXPENSE", leave_request_id=None, expense_claim_id="EXP-2026-000001",
            submission_round=1, previous_status="VALIDATING", new_status="PENDING_APPROVAL", actor_id=None,
            occurred_at=T0, correlation_id=CORR,
        )
    )
    expect_db_error(
        conn,
        sa.insert(t).values(
            event_id="RSE-000000003", request_type="EXPENSE", leave_request_id=None, expense_claim_id="EXP-2026-000001",
            submission_round=1, previous_status="VALIDATING", new_status="VALIDATING", actor_id=None,
            occurred_at=T0, correlation_id=CORR,
        ),
        match="status_changed",
    )
