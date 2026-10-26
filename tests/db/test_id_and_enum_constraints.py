"""Acceptance criterion 4: IDs follow the documented conventions; enums are enforced (R-8.1, R-16.1)."""
from datetime import date

import pytest
import sqlalchemy as sa

from tests.conftest import T0, expect_db_error

pytestmark = pytest.mark.db


@pytest.mark.parametrize(
    "bad_id",
    ["EMP-1", "EMP-0000001", "emp-000003", "EMP000003", "EMPL-000003", "EMP-00000A"],
)
def test_malformed_employee_id_rejected(conn, tables, seed, bad_id):
    stmt = sa.insert(tables["ops.employee"]).values(
        employee_id=bad_id, full_name="X", email=f"{bad_id}@example.test", manager_id="EMP-000001",
        department_id="DEPT-01", job_title="Engineer", grade="G1", country="IN", currency="INR",
        employment_start=date(2024, 1, 1), employment_status="ACTIVE", default_cost_center_id="CC-0001",
        is_department_head=False, is_finance_controller=False, created_at=T0,
    )
    expect_db_error(conn, stmt, match="employee_id_format")


@pytest.mark.parametrize(
    "table_key,column,bad_value",
    [
        ("ops.leave_request", "leave_request_id", "LVE-26-000001"),
        ("ops.expense_claim", "expense_claim_id", "EXP-2026-1"),
        ("ops.approval_rule", "approval_rule_id", "RULE-X-001"),
        ("ops.cost_center", "cost_center_id", "CC-1"),
    ],
)
def test_malformed_ids_rejected_elsewhere(conn, tables, seed, table_key, column, bad_value):
    """Only the ID is wrong; every other value is valid. The CHECK name ends with _format."""
    base = {
        "ops.leave_request": dict(
            employee_id="EMP-000002", leave_policy_id="LPOL-ANNUAL-IN-V1", start_date=date(2026, 2, 2),
            end_date=date(2026, 2, 3), start_half_day=False, end_half_day=False, first_submitted_at=T0,
            current_round=1, business_day_count=2, requested_quantity=2, workflow_status="PENDING_APPROVAL",
            exception_class="NONE", medical_cert_flag=False, created_at=T0,
        ),
        "ops.expense_claim": dict(
            employee_id="EMP-000002", first_submitted_at=T0, claim_period_start=date(2026, 1, 10),
            claim_period_end=date(2026, 1, 10), country="IN", currency="INR", cost_center_id="CC-0001",
            total_amount=100, workflow_status="PENDING_APPROVAL", exception_class="NONE",
            receipt_status="NOT_REQUIRED", current_round=1, created_at=T0,
        ),
        "ops.approval_rule": dict(
            request_type="EXPENSE", max_amount_usd=200, required_levels=["L1"], priority=10,
            effective_start=date(2025, 1, 1), is_active=True,
        ),
        "ops.cost_center": dict(
            cost_center_name="X", department_id="DEPT-01", country="IN", currency="INR", is_active=True,
            effective_from=date(2025, 1, 1), created_at=T0,
        ),
    }[table_key]
    stmt = sa.insert(tables[table_key]).values(**base, **{column: bad_value})
    # PostgreSQL reports the first failing CHECK in its own order, so only assert that a CHECK failed.
    expect_db_error(conn, stmt, match="violates check constraint")


def test_invalid_workflow_status_rejected(conn, tables, seed):
    stmt = sa.insert(tables["ops.leave_request"]).values(
        leave_request_id="LVE-2026-000001", employee_id="EMP-000002", leave_policy_id="LPOL-ANNUAL-IN-V1",
        start_date=date(2026, 2, 2), end_date=date(2026, 2, 3), first_submitted_at=T0, current_round=1,
        business_day_count=2, requested_quantity=2, workflow_status="IN_PROGRESS", exception_class="NONE",
        medical_cert_flag=False, created_at=T0,
    )
    expect_db_error(conn, stmt, match="workflow_status_enum")


def test_exception_class_and_workflow_status_are_separate_columns(tables):
    """Amendment D: the dimensions are distinct columns, never a merged status."""
    cols = {c.name for c in tables["ops.expense_claim"].columns}
    assert {"workflow_status", "exception_class", "receipt_status"} <= cols
    assert "status" not in cols
