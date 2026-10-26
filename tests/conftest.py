"""Shared test fixtures.

Database tests (marker `db`) need the lea_test database reachable at TEST_DATABASE_URL. The session
fixture resets it with `alembic downgrade base` + `alembic upgrade head`, applies the test-only EXCLUDE
constraint (amendment A3), and every test runs inside a transaction that is rolled back, so tests never
see each other's rows. Safety: the database name must end with `_test` (risk RK-13).

No wall clock anywhere: fixed timestamps based on AS_OF_DATE 2026-10-22 (amendment A7).
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

AS_OF = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
AS_OF_DATE = date(2026, 10, 22)
T0 = datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)  # a fixed "event" time inside the dataset window
CORR = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _test_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL")


def pytest_collection_modifyitems(config, items):
    """Skip db tests cleanly when no test database is configured or reachable."""
    url = _test_url()
    reason = None
    if not url:
        reason = "TEST_DATABASE_URL not set (copy .env.example to .env)"
    else:
        try:
            engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
            with engine.connect() as conn:
                conn.execute(sa.text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            reason = f"test database not reachable: {type(exc).__name__}"
    if reason:
        marker = pytest.mark.skip(reason=reason)
        for item in items:
            if "db" in item.keywords:
                item.add_marker(marker)


@pytest.fixture(scope="session")
def test_url() -> str:
    url = _test_url()
    assert url, "TEST_DATABASE_URL must be set"
    dbname = make_url(url).database or ""
    assert dbname.endswith("_test"), f"refusing to run tests against non-test database '{dbname}'"
    return url


def run_alembic(url: str, direction: str, target: str) -> None:
    from alembic import command
    from alembic.config import Config

    os.environ["ALEMBIC_DATABASE_URL"] = url
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    if direction == "upgrade":
        command.upgrade(cfg, target)
    else:
        command.downgrade(cfg, target)


def apply_test_only_constraints(engine: sa.Engine) -> None:
    """Run the multi-statement test-only SQL through the raw psycopg connection and commit it."""
    sql = (ROOT / "sql" / "test_only_constraints.sql").read_text(encoding="utf-8")
    raw = engine.raw_connection()
    try:
        raw.dbapi_connection.execute(sql)
        raw.commit()
    finally:
        raw.close()


@pytest.fixture(scope="session")
def engine(test_url: str) -> sa.Engine:
    eng = sa.create_engine(test_url, poolclass=sa.pool.NullPool, future=True)
    run_alembic(test_url, "downgrade", "base")
    run_alembic(test_url, "upgrade", "head")
    apply_test_only_constraints(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def conn(engine: sa.Engine):
    """A connection inside an outer transaction that is always rolled back."""
    connection = engine.connect()
    outer = connection.begin()
    try:
        yield connection
    finally:
        outer.rollback()
        connection.close()


@pytest.fixture(scope="session")
def tables(engine: sa.Engine) -> dict[str, sa.Table]:
    """All tables keyed as 'schema.table', reflected from the models' metadata."""
    from src.models import Base, GroundTruthBase

    out: dict[str, sa.Table] = {}
    for md in (Base.metadata, GroundTruthBase.metadata):
        for key, table in md.tables.items():
            out[key] = table
    return out


def expect_db_error(conn: sa.Connection, statement, *, match: str | None = None):
    """Execute `statement` inside a savepoint and assert the database rejects it."""
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError) as info:
        with conn.begin_nested():
            conn.execute(statement)
    if match:
        assert match.lower() in str(info.value.orig).lower(), str(info.value.orig)
    return info


@pytest.fixture()
def seed(conn: sa.Connection, tables: dict[str, sa.Table]) -> dict:
    """Minimal valid object graph used by constraint tests. Values are synthetic."""
    t = tables
    conn.execute(
        sa.insert(t["ops.department"]).values(
            department_id="DEPT-01", department_name="Engineering", head_employee_id=None, created_at=T0
        )
    )
    conn.execute(
        sa.insert(t["ops.cost_center"]).values(
            cost_center_id="CC-0001", cost_center_name="Engineering-IN", department_id="DEPT-01",
            country="IN", currency="INR", is_active=True, effective_from=date(2025, 1, 1), created_at=T0,
        )
    )
    conn.execute(
        sa.insert(t["ops.cost_center_budget"]).values(
            cost_center_budget_id="CCB-CC-0001-2026", cost_center_id="CC-0001",
            budget_period_start=date(2026, 1, 1), budget_period_end=date(2026, 12, 31), currency="INR",
            budget_amount=Decimal("1000000.00"), committed_amount=Decimal("0"), actual_amount=Decimal("0"),
        )
    )
    manager = dict(
        employee_id="EMP-000001", full_name="Asha Manager", email="emp000001@example.test", manager_id=None,
        department_id="DEPT-01", job_title="Engineering Manager", grade="G5", country="IN", currency="INR",
        employment_start=date(2018, 3, 1), employment_end=None, employment_status="ACTIVE",
        default_cost_center_id="CC-0001", is_department_head=False, is_finance_controller=False, created_at=T0,
    )
    requester = dict(
        manager, employee_id="EMP-000002", full_name="Ravi Requester", email="emp000002@example.test",
        manager_id="EMP-000001", job_title="Engineer", grade="G2", employment_start=date(2022, 6, 15),
    )
    conn.execute(sa.insert(t["ops.employee"]).values(manager))
    conn.execute(sa.insert(t["ops.employee"]).values(requester))
    conn.execute(
        sa.insert(t["ops.leave_policy"]).values(
            leave_policy_id="LPOL-ANNUAL-IN-V1", policy_family="LPOL-ANNUAL-IN", version=1,
            policy_name="Annual leave (IN) v1", leave_type="ANNUAL", country_scope="IN",
            annual_entitlement_days=Decimal("18.0"), accrual_method="MONTHLY", carry_forward_cap_days=Decimal("10.0"),
            negative_balance_allowed=False, negative_limit_days=Decimal("0"), min_service_days=0,
            requires_medical_cert_over_days=None, max_days_per_year=None,
            effective_start=date(2025, 1, 1), effective_end=None, is_active=True,
        )
    )
    conn.execute(
        sa.insert(t["ops.expense_policy"]).values(
            expense_policy_id="XPOL-MEALS-IN-V1", policy_family="XPOL-MEALS-IN", version=1,
            policy_name="Meals (IN) v1", country="IN", category="MEALS", currency="INR",
            per_line_limit=Decimal("6230.00"), per_claim_limit=Decimal("498000.00"), receipt_threshold=Decimal("2080.00"),
            requires_pre_approval=False, effective_start=date(2025, 1, 1), effective_end=None, is_active=True,
        )
    )
    conn.execute(
        sa.insert(t["ops.approval_rule"]).values(
            approval_rule_id="RULE-E-001", request_type="EXPENSE", country=None, category_or_leave_type=None,
            min_amount_usd=None, max_amount_usd=Decimal("200.00"), min_days=None, max_days=None,
            required_levels=["L1"], priority=10, effective_start=date(2025, 1, 1), effective_end=None, is_active=True,
        )
    )
    conn.execute(
        sa.insert(t["ops.exception_code"]).values(
            exception_code="MISSING_RECEIPT", exception_class="DATA_QUALITY", severity="CORRECTABLE",
            default_route="RETURNED_FOR_CORRECTION",
            requester_message_template="Line {line} of {amount} {currency} needs a receipt (threshold {threshold}).",
            analyst_message_template="Receipt missing on line {line}; threshold {threshold}.",
        )
    )
    conn.execute(
        sa.insert(t["ops.role"]).values(role_id="ROLE-REQUESTER", role_name="REQUESTER", description="Submits requests")
    )
    conn.execute(
        sa.insert(t["ops.application_user"]).values(
            user_id="USR-000002", username="emp000002", password_hash="$2b$12$synthetic-hash-placeholder",
            employee_id="EMP-000002", is_active=True, created_at=T0,
        )
    )
    return {"manager": "EMP-000001", "requester": "EMP-000002", "corr": CORR, "t0": T0}


def approved_claim(conn: sa.Connection, tables: dict[str, sa.Table], claim_id: str = "EXP-2026-000001") -> str:
    """Insert an APPROVED expense claim with one line and one approved L1 step; return the step id."""
    t = tables
    conn.execute(
        sa.insert(t["ops.expense_claim"]).values(
            expense_claim_id=claim_id, employee_id="EMP-000002", first_submitted_at=T0,
            claim_period_start=date(2026, 1, 10), claim_period_end=date(2026, 1, 10), country="IN", currency="INR",
            cost_center_id="CC-0001", expense_policy_id="XPOL-MEALS-IN-V1",
            total_amount=Decimal("1500.00"), approved_amount=Decimal("1500.00"), total_amount_usd=Decimal("17.75"),
            fx_rate_used=Decimal("84.500000"), workflow_status="APPROVED", exception_class="NONE",
            receipt_status="NOT_REQUIRED", current_round=1, created_at=T0,
        )
    )
    conn.execute(
        sa.insert(t["ops.expense_line"]).values(
            expense_line_id=f"EXPL-{claim_id}-01", expense_claim_id=claim_id, line_number=1, submission_round=1,
            category="MEALS", merchant_description="Team lunch", expense_date=date(2026, 1, 10),
            quantity=None, unit_amount=None, line_amount=Decimal("1500.00"), currency="INR",
            receipt_id=None, cost_center_id=None, expense_policy_id="XPOL-MEALS-IN-V1", validation_result="PASS",
        )
    )
    step_id = f"APR-{claim_id}-01"
    conn.execute(
        sa.insert(t["ops.approval_step"]).values(
            approval_step_id=step_id, request_type="EXPENSE", leave_request_id=None, expense_claim_id=claim_id,
            submission_round=1, sequence_no=1, approval_rule_id="RULE-E-001", required_level="L1",
            approver_employee_id="EMP-000001", delegated_from_employee_id=None, step_status="APPROVED",
            assigned_at=T0, decision_at=datetime(2026, 1, 16, 10, 0, tzinfo=timezone.utc),
            decision_reason_code="APPROVED_CLEAN", decision_comment=None,
        )
    )
    return step_id
