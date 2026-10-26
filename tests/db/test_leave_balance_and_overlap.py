"""Leave balance generated column (R-7.3) and the test-only EXCLUDE constraint for overlapping approved leave (AM-A3)."""
from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa

from tests.conftest import CORR, T0, expect_db_error

pytestmark = pytest.mark.db


def test_available_balance_is_computed_from_components(conn, tables, seed):
    t = tables["ops.leave_balance"]
    conn.execute(
        sa.insert(t).values(
            leave_balance_id="LBAL-EMP-000002-LPOL-ANNUAL-IN-V1-2026", employee_id="EMP-000002",
            leave_policy_id="LPOL-ANNUAL-IN-V1", leave_year=2026, opening_balance=Decimal("4.0"),
            accrued=Decimal("13.5"), adjustments=Decimal("-1.0"), used=Decimal("6.5"), last_recalculated_at=T0,
        )
    )
    available = conn.execute(sa.select(t.c.available_balance)).scalar()
    assert available == Decimal("10.0")


def test_one_balance_per_employee_policy_year(conn, tables, seed):
    t = tables["ops.leave_balance"]
    row = dict(
        leave_balance_id="LBAL-EMP-000002-LPOL-ANNUAL-IN-V1-2026", employee_id="EMP-000002",
        leave_policy_id="LPOL-ANNUAL-IN-V1", leave_year=2026, opening_balance=Decimal("0"), last_recalculated_at=T0,
    )
    conn.execute(sa.insert(t).values(**row))
    expect_db_error(
        conn, sa.insert(t).values(**{**row, "leave_balance_id": "LBAL-EMP-000002-LPOL-ANNUAL-IN-V1-2027"}), match="uq_leave_balance"
    )


def test_usage_transaction_requires_request_and_accrual_forbids_it(conn, tables, seed):
    conn.execute(
        sa.insert(tables["ops.leave_balance"]).values(
            leave_balance_id="LBAL-EMP-000002-LPOL-ANNUAL-IN-V1-2026", employee_id="EMP-000002",
            leave_policy_id="LPOL-ANNUAL-IN-V1", leave_year=2026, opening_balance=Decimal("0"), last_recalculated_at=T0,
        )
    )
    t = tables["ops.leave_balance_transaction"]
    base = dict(
        leave_balance_id="LBAL-EMP-000002-LPOL-ANNUAL-IN-V1-2026", quantity=Decimal("1.5"),
        txn_date=date(2026, 2, 1), posted_at=T0, correlation_id=CORR,
    )
    expect_db_error(
        conn, sa.insert(t).values(transaction_id="LBT-2026-000001", txn_type="USAGE", leave_request_id=None, **base),
        match="usage_references_request",
    )
    conn.execute(sa.insert(t).values(transaction_id="LBT-2026-000002", txn_type="ACCRUAL", leave_request_id=None, **base))


def _leave(request_id, start, end, status="APPROVED"):
    return dict(
        leave_request_id=request_id, employee_id="EMP-000002", leave_policy_id="LPOL-ANNUAL-IN-V1",
        start_date=start, end_date=end, first_submitted_at=T0, current_round=1, business_day_count=Decimal("3"),
        requested_quantity=Decimal("3"), workflow_status=status, exception_class="NONE", medical_cert_flag=False,
        created_at=T0,
    )


def test_overlapping_approved_leave_rejected_in_test_database(conn, tables, seed):
    """Test-DB-only EXCLUDE constraint (AM-A3). In lea_dev the service layer enforces this instead."""
    t = tables["ops.leave_request"]
    conn.execute(sa.insert(t).values(**_leave("LVE-2026-000001", date(2026, 3, 2), date(2026, 3, 4))))
    expect_db_error(
        conn, sa.insert(t).values(**_leave("LVE-2026-000002", date(2026, 3, 4), date(2026, 3, 6))),
        match="excl_no_overlapping_approved_leave",
    )


def test_overlap_with_pending_or_rejected_leave_is_not_blocked_by_db(conn, tables, seed):
    """AM-B6: overlap with PENDING is a soft rule for the service; the constraint only covers APPROVED."""
    t = tables["ops.leave_request"]
    conn.execute(sa.insert(t).values(**_leave("LVE-2026-000001", date(2026, 3, 2), date(2026, 3, 4))))
    conn.execute(sa.insert(t).values(**_leave("LVE-2026-000002", date(2026, 3, 4), date(2026, 3, 6), status="PENDING_APPROVAL")))
    conn.execute(sa.insert(t).values(**_leave("LVE-2026-000003", date(2026, 3, 3), date(2026, 3, 3), status="REJECTED")))
    assert conn.execute(sa.text("SELECT count(*) FROM ops.leave_request")).scalar() == 3


def test_adjacent_approved_leave_is_allowed(conn, tables, seed):
    t = tables["ops.leave_request"]
    conn.execute(sa.insert(t).values(**_leave("LVE-2026-000001", date(2026, 3, 2), date(2026, 3, 4))))
    conn.execute(sa.insert(t).values(**_leave("LVE-2026-000002", date(2026, 3, 5), date(2026, 3, 6))))
