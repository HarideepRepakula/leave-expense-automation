"""Expense claim submission through the PostgreSQL store (docs/06 8.1; docs/05 section 6; AM-F5). Runs in lea_test
inside the rolled-back `conn` transaction. seed: EMP-000002 (IN, INR), CC-0001 with a 2026 budget of 1,000,000 INR,
XPOL-MEALS-IN-V1 (per line 6230, receipt from 2080). Added here: the catalogue, 1 USD = 84.5 INR, two drafts."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa
import yaml

from src.repositories.expense_repository import SqlExpenseStore
from src.services.exception_service import ExceptionCatalogue
from src.services.expense_service import DetectionParams, submit_expense
from tests.conftest import ROOT, T0

pytestmark = pytest.mark.db

CODES = yaml.safe_load((ROOT / "config" / "exception_codes.yaml").read_text(encoding="utf-8"))
CATALOGUE = ExceptionCatalogue.from_config(CODES)
ROUTE = {"HARD": "REJECTED", "CORRECTABLE": "RETURNED_FOR_CORRECTION", "SOFT": "ESCALATED_FOR_REVIEW", "INFO": "NONE"}
PARAMS = DetectionParams(90, 7, Decimal("200.00"))
SUBMIT = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)


@pytest.fixture()
def world(conn, tables, seed):
    t = tables
    have = set(conn.execute(sa.select(t["ops.exception_code"].c.exception_code)).scalars())
    conn.execute(sa.insert(t["ops.exception_code"]), [
        {"exception_code": c["code"], "exception_class": c["class"], "severity": c["severity"],
         "default_route": ROUTE[c["severity"]], "requester_message_template": c["requester"],
         "analyst_message_template": c["analyst"]} for c in CODES["codes"] if c["code"] not in have])
    conn.execute(sa.insert(t["ops.fx_rate"]).values(fx_rate_id="FX-USD-INR-20250101", from_currency="USD",
                                                     to_currency="INR", rate=Decimal("84.5"),
                                                     effective_from=date(2025, 1, 1)))
    for cid, amount, q in (("EXP-2026-000901", "1500.00", "2"), ("EXP-2026-000902", "7000.00", "1")):
        conn.execute(sa.insert(t["ops.expense_claim"]).values(
            expense_claim_id=cid, employee_id="EMP-000002", first_submitted_at=None,
            claim_period_start=date(2026, 2, 20), claim_period_end=date(2026, 2, 20), country="IN", currency="INR",
            cost_center_id="CC-0001", expense_policy_id=None, total_amount=Decimal(amount),
            workflow_status="DRAFT", exception_class="NONE", receipt_status="NOT_REQUIRED", current_round=1,
            created_at=T0))
        conn.execute(sa.insert(t["ops.expense_line"]).values(
            expense_line_id=f"EXPL-{cid}-01", expense_claim_id=cid, line_number=1, submission_round=1,
            category="MEALS", merchant_description="Team meal", expense_date=date(2026, 2, 20),
            quantity=Decimal(q), unit_amount=Decimal(amount) / Decimal(q), line_amount=Decimal(amount), currency="INR",
            receipt_id=None, validation_result="PENDING"))
    return t


def _submit(conn, cid: str):
    return submit_expense(SqlExpenseStore(conn, PARAMS), cid, CATALOGUE, SUBMIT, "EMP-000002",
                          uuid.uuid5(uuid.NAMESPACE_URL, cid))


def test_clean_claim_is_persisted_with_reservation(conn, world):
    res = _submit(conn, "EXP-2026-000901")
    assert res.status == "PENDING_APPROVAL" and res.validation.codes == []
    ec, el = world["ops.expense_claim"], world["ops.expense_line"]
    row = conn.execute(sa.select(ec).where(ec.c.expense_claim_id == "EXP-2026-000901")).mappings().one()
    assert (row["workflow_status"], row["total_amount_usd"], row["fx_rate_used"], row["expense_policy_id"]) == \
        ("PENDING_APPROVAL", Decimal("17.75"), Decimal("84.500000"), "XPOL-MEALS-IN-V1")
    assert conn.execute(sa.select(el.c.validation_result).where(el.c.expense_claim_id == "EXP-2026-000901")).scalar() \
        == "PASS"
    ev = world["ops.request_status_event"]
    assert conn.execute(sa.select(sa.func.count()).select_from(ev).where(ev.c.expense_claim_id == "EXP-2026-000901")) \
        .scalar() == 3
    cct, ccb = world["ops.cost_center_transaction"], world["ops.cost_center_budget"]
    assert conn.execute(sa.select(cct.c.transaction_id, cct.c.txn_type, cct.c.amount)).all() == \
        [("CCT-000000001", "RESERVATION", Decimal("1500.00"))]
    assert conn.execute(sa.select(ccb.c.committed_amount)).scalar() == Decimal("1500.00")


def test_returned_claim_records_all_codes_caps_and_releases(conn, world):
    """7000 above the 6230 line limit (INFO, CAPPED) and above 2080 without a receipt (CORRECTABLE): RETURNED,
    both codes stored, the line FAILs, the reservation is released at once (committed back to 0)."""
    res = _submit(conn, "EXP-2026-000902")
    assert res.status == "RETURNED_FOR_CORRECTION"
    rx = world["ops.request_exception"]
    assert [c for c, in conn.execute(sa.select(rx.c.exception_code).order_by(rx.c.exception_id))] == \
        ["LINE_LIMIT_EXCEEDED", "MISSING_RECEIPT"]
    el, cct, ccb = world["ops.expense_line"], world["ops.cost_center_transaction"], world["ops.cost_center_budget"]
    assert conn.execute(sa.select(el.c.validation_result).where(el.c.expense_claim_id == "EXP-2026-000902")) \
        .scalar() == "FAIL"
    assert [t for t, in conn.execute(sa.select(cct.c.txn_type).order_by(cct.c.transaction_id))] == \
        ["RESERVATION", "RELEASE"]
    assert conn.execute(sa.select(ccb.c.committed_amount)).scalar() == Decimal("0.00")


def test_submit_locks_claim_cost_center_and_budget(conn, world):
    _submit(conn, "EXP-2026-000901")
    locked = set(conn.execute(sa.text(
        "SELECT c.relname FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
        "WHERE l.pid = pg_backend_pid() AND l.mode = 'RowShareLock'")).scalars())
    assert {"expense_claim", "cost_center", "cost_center_budget"} <= locked
