"""Employee hierarchy and date constraints (R-7.1, R-16.2)."""
from datetime import date

import pytest
import sqlalchemy as sa

from tests.conftest import T0, expect_db_error

pytestmark = pytest.mark.db


def _emp(**over):
    base = dict(
        employee_id="EMP-000003", full_name="Test Person", email="emp000003@example.test", manager_id="EMP-000001",
        department_id="DEPT-01", job_title="Analyst", grade="G1", country="IN", currency="INR",
        employment_start=date(2024, 1, 1), employment_end=None, employment_status="ACTIVE",
        default_cost_center_id="CC-0001", is_department_head=False, is_finance_controller=False, created_at=T0,
    )
    base.update(over)
    return base


def test_employee_cannot_be_own_manager(conn, tables, seed):
    expect_db_error(conn, sa.insert(tables["ops.employee"]).values(**_emp(manager_id="EMP-000003")), match="not_own_manager")


def test_employment_end_before_start_rejected(conn, tables, seed):
    expect_db_error(
        conn,
        sa.insert(tables["ops.employee"]).values(**_emp(employment_end=date(2023, 12, 31), employment_status="TERMINATED")),
        match="employment_dates",
    )


def test_terminated_requires_end_date_and_vice_versa(conn, tables, seed):
    expect_db_error(
        conn, sa.insert(tables["ops.employee"]).values(**_emp(employment_status="TERMINATED")), match="terminated_has_end_date"
    )
    expect_db_error(
        conn,
        sa.insert(tables["ops.employee"]).values(**_emp(employment_end=date(2025, 6, 30), employment_status="ACTIVE")),
        match="terminated_has_end_date",
    )


def test_manager_must_exist(conn, tables, seed):
    expect_db_error(conn, sa.insert(tables["ops.employee"]).values(**_emp(manager_id="EMP-000999")), match="foreign key")


def test_leave_request_end_before_start_rejected(conn, tables, seed):
    stmt = sa.insert(tables["ops.leave_request"]).values(
        leave_request_id="LVE-2026-000001", employee_id="EMP-000002", leave_policy_id="LPOL-ANNUAL-IN-V1",
        start_date=date(2026, 2, 5), end_date=date(2026, 2, 3), first_submitted_at=T0, current_round=1,
        business_day_count=0, requested_quantity=0, workflow_status="SUBMITTED", exception_class="NONE",
        medical_cert_flag=False, created_at=T0,
    )
    expect_db_error(conn, stmt, match="date_order")


def test_single_day_leave_cannot_have_both_half_day_flags(conn, tables, seed):
    stmt = sa.insert(tables["ops.leave_request"]).values(
        leave_request_id="LVE-2026-000001", employee_id="EMP-000002", leave_policy_id="LPOL-ANNUAL-IN-V1",
        start_date=date(2026, 2, 3), end_date=date(2026, 2, 3), start_half_day=True, end_half_day=True,
        first_submitted_at=T0, current_round=1, business_day_count=1, requested_quantity=0,
        workflow_status="SUBMITTED", exception_class="NONE", medical_cert_flag=False, created_at=T0,
    )
    expect_db_error(conn, stmt, match="single_day_one_half_flag")


def test_draft_has_no_submission_timestamp_and_submitted_has_one(conn, tables, seed):
    common = dict(
        employee_id="EMP-000002", leave_policy_id="LPOL-ANNUAL-IN-V1", start_date=date(2026, 2, 3),
        end_date=date(2026, 2, 4), current_round=1, business_day_count=2, requested_quantity=2,
        exception_class="NONE", medical_cert_flag=False, created_at=T0,
    )
    expect_db_error(
        conn,
        sa.insert(tables["ops.leave_request"]).values(
            leave_request_id="LVE-2026-000001", workflow_status="DRAFT", first_submitted_at=T0, **common
        ),
        match="submitted_at_matches_status",
    )
    conn.execute(
        sa.insert(tables["ops.leave_request"]).values(
            leave_request_id="LVE-2026-000002", workflow_status="DRAFT", first_submitted_at=None, **common
        )
    )


def test_policy_effective_end_before_start_rejected(conn, tables, seed):
    stmt = sa.insert(tables["ops.leave_policy"]).values(
        leave_policy_id="LPOL-SICK-ALL-V1", policy_family="LPOL-SICK-ALL", version=1, policy_name="Sick",
        leave_type="SICK", country_scope="ALL", annual_entitlement_days=10, accrual_method="ANNUAL_GRANT",
        carry_forward_cap_days=0, negative_balance_allowed=False, negative_limit_days=0, min_service_days=0,
        effective_start=date(2025, 1, 1), effective_end=date(2024, 12, 31), is_active=True,
    )
    expect_db_error(conn, stmt, match="effective_dates")


def test_negative_limit_requires_flag(conn, tables, seed):
    stmt = sa.insert(tables["ops.leave_policy"]).values(
        leave_policy_id="LPOL-ANNUAL-US-V1", policy_family="LPOL-ANNUAL-US", version=1, policy_name="Annual US",
        leave_type="ANNUAL", country_scope="US", annual_entitlement_days=15, accrual_method="MONTHLY",
        carry_forward_cap_days=5, negative_balance_allowed=False, negative_limit_days=3, min_service_days=0,
        effective_start=date(2025, 1, 1), is_active=True,
    )
    expect_db_error(conn, stmt, match="negative_limit_requires_flag")
