"""Acceptance criterion 16 and amendment F4: append-only history, immutable IDs, frozen decided steps,
no self-approval step (sql/triggers.sql)."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa

from tests.conftest import CORR, T0, approved_claim, expect_db_error

pytestmark = pytest.mark.db


def _audit_row(event_id="AUD-000000001"):
    return dict(
        event_id=event_id, entity_type="expense_claim", entity_id="EXP-2026-000001", previous_state="VALIDATING",
        new_state="PENDING_APPROVAL", actor_id="SYSTEM", occurred_at=T0, correlation_id=CORR,
        calculated_values={"amount_usd": "17.75"},
    )


def test_audit_event_cannot_be_updated_or_deleted(conn, tables, seed):
    t = tables["ops.audit_event"]
    conn.execute(sa.insert(t).values(**_audit_row()))
    expect_db_error(conn, sa.update(t).where(t.c.event_id == "AUD-000000001").values(new_state="APPROVED"), match="append-only")
    expect_db_error(conn, sa.delete(t).where(t.c.event_id == "AUD-000000001"), match="append-only")
    assert conn.execute(sa.text("SELECT new_state FROM ops.audit_event")).scalar() == "PENDING_APPROVAL"


@pytest.mark.parametrize(
    "table_key,row",
    [
        (
            "ops.leave_balance_transaction",
            None,  # built in the test because it needs a balance row
        ),
    ],
)
def test_ledger_is_append_only(conn, tables, seed, table_key, row):
    conn.execute(
        sa.insert(tables["ops.leave_balance"]).values(
            leave_balance_id="LBAL-EMP-000002-LPOL-ANNUAL-IN-V1-2026", employee_id="EMP-000002",
            leave_policy_id="LPOL-ANNUAL-IN-V1", leave_year=2026, opening_balance=Decimal("5.0"),
            accrued=Decimal("0"), adjustments=Decimal("0"), used=Decimal("0"), last_recalculated_at=T0,
        )
    )
    t = tables[table_key]
    conn.execute(
        sa.insert(t).values(
            transaction_id="LBT-2026-000001", leave_balance_id="LBAL-EMP-000002-LPOL-ANNUAL-IN-V1-2026",
            leave_request_id=None, txn_type="OPENING", quantity=Decimal("5.0"), txn_date=date(2026, 1, 1),
            posted_at=T0, correlation_id=CORR,
        )
    )
    expect_db_error(conn, sa.update(t).where(t.c.transaction_id == "LBT-2026-000001").values(quantity=Decimal("6.0")), match="append-only")
    expect_db_error(conn, sa.delete(t).where(t.c.transaction_id == "LBT-2026-000001"), match="append-only")


def test_primary_key_is_immutable(conn, tables, seed):
    t = tables["ops.employee"]
    expect_db_error(
        conn, sa.update(t).where(t.c.employee_id == "EMP-000002").values(employee_id="EMP-000099"), match="immutable"
    )
    # Non-key columns remain updatable.
    conn.execute(sa.update(t).where(t.c.employee_id == "EMP-000002").values(job_title="Senior Engineer"))


def test_decided_step_is_frozen_but_pending_step_is_not(conn, tables, seed):
    step_id = approved_claim(conn, tables)  # creates an APPROVED step
    t = tables["ops.approval_step"]
    expect_db_error(
        conn, sa.update(t).where(t.c.approval_step_id == step_id).values(decision_comment="edited later"), match="cannot be modified"
    )
    conn.execute(
        sa.insert(tables["ops.expense_claim"]).values(
            expense_claim_id="EXP-2026-000002", employee_id="EMP-000002", first_submitted_at=T0,
            claim_period_start=date(2026, 1, 10), claim_period_end=date(2026, 1, 10), country="IN", currency="INR",
            cost_center_id="CC-0001", total_amount=Decimal("100.00"), workflow_status="PENDING_APPROVAL",
            exception_class="NONE", receipt_status="NOT_REQUIRED", current_round=1, created_at=T0,
        )
    )
    conn.execute(
        sa.insert(t).values(
            approval_step_id="APR-EXP-2026-000002-01", request_type="EXPENSE", expense_claim_id="EXP-2026-000002",
            submission_round=1, sequence_no=1, approval_rule_id="RULE-E-001", required_level="L1",
            approver_employee_id="EMP-000001", step_status="PENDING", assigned_at=T0,
        )
    )
    conn.execute(
        sa.update(t)
        .where(t.c.approval_step_id == "APR-EXP-2026-000002-01")
        .values(step_status="APPROVED", decision_at=datetime(2026, 1, 16, tzinfo=timezone.utc), decision_reason_code="OK")
    )


def test_self_approval_step_rejected_by_trigger(conn, tables, seed):
    """Acceptance criterion 10: a step can never be assigned to the requester."""
    conn.execute(
        sa.insert(tables["ops.expense_claim"]).values(
            expense_claim_id="EXP-2026-000003", employee_id="EMP-000002", first_submitted_at=T0,
            claim_period_start=date(2026, 1, 10), claim_period_end=date(2026, 1, 10), country="IN", currency="INR",
            cost_center_id="CC-0001", total_amount=Decimal("100.00"), workflow_status="PENDING_APPROVAL",
            exception_class="NONE", receipt_status="NOT_REQUIRED", current_round=1, created_at=T0,
        )
    )
    expect_db_error(
        conn,
        sa.insert(tables["ops.approval_step"]).values(
            approval_step_id="APR-EXP-2026-000003-01", request_type="EXPENSE", expense_claim_id="EXP-2026-000003",
            submission_round=1, sequence_no=1, approval_rule_id="RULE-E-001", required_level="L1",
            approver_employee_id="EMP-000002", step_status="PENDING", assigned_at=T0,
        ),
        match="self-approval",
    )


def test_idempotency_record_status_can_change_but_key_fields_cannot(conn, tables, seed):
    t = tables["ops.idempotency_record"]
    key = "b" * 64
    conn.execute(
        sa.insert(t).values(
            actor_user_id="USR-000002", idempotency_key=key, operation="SUBMIT", request_hash="c" * 64,
            status="IN_PROGRESS", created_at=T0,
        )
    )
    conn.execute(
        sa.update(t).where(t.c.idempotency_key == key).values(status="COMPLETED", response_hash="d" * 64, completed_at=T0)
    )
    expect_db_error(conn, sa.update(t).where(t.c.idempotency_key == key).values(request_hash="e" * 64), match="immutable")
    expect_db_error(conn, sa.delete(t).where(t.c.idempotency_key == key), match="cannot be deleted")


def test_exception_code_catalogue_rejects_accusatory_wording(conn, tables, seed):
    """Amendment H3: 'fraud' and 'misconduct' never appear in the catalogue."""
    t = tables["ops.exception_code"]
    bad = dict(
        exception_code="SPLIT_CLAIM_SUSPECTED", exception_class="SUSPICIOUS_PATTERN", severity="SOFT",
        default_route="ESCALATED_FOR_REVIEW", requester_message_template="Possible fraud detected.",
        analyst_message_template="Suspected split claim, requires investigation.",
    )
    expect_db_error(conn, sa.insert(t).values(**bad), match="no_accusatory_wording")
    conn.execute(sa.insert(t).values(**{**bad, "requester_message_template": "Suspected split claim, requires investigation."}))


def test_exception_code_route_must_match_severity(conn, tables, seed):
    t = tables["ops.exception_code"]
    expect_db_error(
        conn,
        sa.insert(t).values(
            exception_code="INSUFFICIENT_BALANCE", exception_class="POLICY_VIOLATION", severity="HARD",
            default_route="ESCALATED_FOR_REVIEW", requester_message_template="x", analyst_message_template="y",
        ),
        match="route_matches_severity",
    )
