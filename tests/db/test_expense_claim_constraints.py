"""Expense claim and line constraints (R-7.6, R-7.7, AM-A2 missing cost center, DEC-11 line numbering)."""
from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa

from tests.conftest import T0, expect_db_error

pytestmark = pytest.mark.db


def _claim(**over):
    base = dict(
        expense_claim_id="EXP-2026-000001", employee_id="EMP-000002", first_submitted_at=T0,
        claim_period_start=date(2026, 1, 10), claim_period_end=date(2026, 1, 12), country="IN", currency="INR",
        cost_center_id="CC-0001", expense_policy_id="XPOL-MEALS-IN-V1", total_amount=Decimal("1500.00"),
        approved_amount=None, workflow_status="PENDING_APPROVAL", exception_class="NONE",
        receipt_status="NOT_REQUIRED", current_round=1, created_at=T0,
    )
    base.update(over)
    return base


def test_missing_cost_center_rejected_when_no_exception(conn, tables, seed):
    """Amendment A2: NULL cost center only when exception_class <> 'NONE'."""
    expect_db_error(
        conn, sa.insert(tables["ops.expense_claim"]).values(**_claim(cost_center_id=None)), match="cost_center_or_exception"
    )


def test_missing_cost_center_allowed_with_exception_class(conn, tables, seed):
    conn.execute(
        sa.insert(tables["ops.expense_claim"]).values(
            **_claim(cost_center_id=None, exception_class="DATA_QUALITY", workflow_status="ESCALATED_FOR_REVIEW")
        )
    )
    row = conn.execute(sa.text("SELECT cost_center_id, exception_class FROM ops.expense_claim")).one()
    assert row == (None, "DATA_QUALITY")


def test_approved_amount_cannot_exceed_total(conn, tables, seed):
    expect_db_error(
        conn,
        sa.insert(tables["ops.expense_claim"]).values(
            **_claim(workflow_status="APPROVED", approved_amount=Decimal("1500.01"))
        ),
        match="approved_within_total",
    )


def test_approved_amount_only_when_approved(conn, tables, seed):
    expect_db_error(
        conn,
        sa.insert(tables["ops.expense_claim"]).values(**_claim(approved_amount=Decimal("1000.00"))),
        match="approved_amount_only_when_approved",
    )


def test_partial_approval_amount_accepted(conn, tables, seed):
    """AM-B12: approved_amount may be below total when APPROVED."""
    conn.execute(
        sa.insert(tables["ops.expense_claim"]).values(**_claim(workflow_status="APPROVED", approved_amount=Decimal("1200.00")))
    )


def _line(**over):
    base = dict(
        expense_line_id="EXPL-EXP-2026-000001-01", expense_claim_id="EXP-2026-000001", line_number=1,
        submission_round=1, category="MEALS", merchant_description="Lunch", expense_date=date(2026, 1, 10),
        quantity=None, unit_amount=None, line_amount=Decimal("1500.00"), currency="INR", receipt_id=None,
        cost_center_id=None, expense_policy_id="XPOL-MEALS-IN-V1", validation_result="PASS",
    )
    base.update(over)
    return base


def test_line_id_must_match_claim_and_line_number(conn, tables, seed):
    conn.execute(sa.insert(tables["ops.expense_claim"]).values(**_claim()))
    expect_db_error(
        conn, sa.insert(tables["ops.expense_line"]).values(**_line(expense_line_id="EXPL-EXP-2026-000001-02")),
        match="id_matches_claim_and_line",
    )
    conn.execute(sa.insert(tables["ops.expense_line"]).values(**_line()))


def test_line_numbers_unique_per_claim_and_may_continue_past_ten(conn, tables, seed):
    """DEC-11: baseline 01..10, resubmission rounds continue up to 99."""
    conn.execute(sa.insert(tables["ops.expense_claim"]).values(**_claim(current_round=2)))
    conn.execute(sa.insert(tables["ops.expense_line"]).values(**_line()))
    # The line ID is derived from the line number (CHECK id_matches_claim_and_line), so a duplicate line
    # number collides on the primary key before the UNIQUE(claim, line_number) constraint is reached.
    expect_db_error(conn, sa.insert(tables["ops.expense_line"]).values(**_line()), match="duplicate key value")
    conn.execute(
        sa.insert(tables["ops.expense_line"]).values(
            **_line(expense_line_id="EXPL-EXP-2026-000001-11", line_number=11, submission_round=2)
        )
    )
    expect_db_error(
        conn,
        sa.insert(tables["ops.expense_line"]).values(**_line(expense_line_id="EXPL-EXP-2026-000001-100", line_number=100)),
        match="violates check constraint",
    )


def test_line_amount_must_be_positive_and_quantity_unit_travel_together(conn, tables, seed):
    conn.execute(sa.insert(tables["ops.expense_claim"]).values(**_claim()))
    expect_db_error(conn, sa.insert(tables["ops.expense_line"]).values(**_line(line_amount=Decimal("0"))), match="amount_positive")
    expect_db_error(
        conn, sa.insert(tables["ops.expense_line"]).values(**_line(quantity=Decimal("2"))), match="quantity_and_unit_together"
    )


def test_receipt_hash_must_be_sha256_hex_and_duplicates_are_allowed(conn, tables, seed):
    """AM-B14: duplicate hashes are an anomaly to DETECT, so the DB must allow them."""
    t = tables["ops.receipt"]
    good = "a" * 64
    conn.execute(sa.insert(t).values(receipt_id="RCT-000000001", receipt_hash=good, created_at=T0))
    conn.execute(sa.insert(t).values(receipt_id="RCT-000000002", receipt_hash=good, created_at=T0))
    expect_db_error(conn, sa.insert(t).values(receipt_id="RCT-000000003", receipt_hash="not-a-hash", created_at=T0), match="hash_is_sha256_hex")


def test_line_currency_mismatch_is_allowed_by_db(conn, tables, seed):
    """CURRENCY_MISMATCH is a planted anomaly living in the dataset (AM-A2); the SERVICE flags it, not the DB."""
    conn.execute(sa.insert(tables["ops.expense_claim"]).values(**_claim()))
    conn.execute(sa.insert(tables["ops.expense_line"]).values(**_line(currency="USD")))
