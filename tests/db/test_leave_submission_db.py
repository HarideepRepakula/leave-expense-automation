"""Leave submission through the PostgreSQL store (docs/06 8.1 for leave; AM-F5). Runs in lea_test inside the
rolled-back `conn` transaction: the request row is updated, three request_status_event rows and one
request_exception row per code are written with ids from id_sequence, and the DB CHECKs accept every row."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa
import yaml

from src.repositories.leave_repository import SqlLeaveStore
from src.services.exception_service import ExceptionCatalogue
from src.services.leave_balance_service import accrual_schedule
from src.services.leave_request_service import submit_leave
from tests.conftest import ROOT, T0, insert_configured_rules

pytestmark = pytest.mark.db

CODES = yaml.safe_load((ROOT / "config" / "exception_codes.yaml").read_text(encoding="utf-8"))
CATALOGUE = ExceptionCatalogue.from_config(CODES)
ROUTE = {"HARD": "REJECTED", "CORRECTABLE": "RETURNED_FOR_CORRECTION", "SOFT": "ESCALATED_FOR_REVIEW", "INFO": "NONE"}
WEEKEND = {"IN": [6, 7], "US": [6, 7], "GB": [6, 7]}
SUBMIT = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)
LBAL = "LBAL-EMP-000002-LPOL-ANNUAL-IN-V1-2026"


@pytest.fixture()
def world(conn, tables, seed):
    """seed: EMP-000002 (IN, joined 2022-06-15) and LPOL-ANNUAL-IN-V1 (18 days, monthly). Add the catalogue,
    a 2026 balance whose ledger is the accrual schedule up to the submission day (4.5 days), and two drafts."""
    t = tables
    have = set(conn.execute(sa.select(t["ops.exception_code"].c.exception_code)).scalars())
    conn.execute(sa.insert(t["ops.exception_code"]), [
        {"exception_code": c["code"], "exception_class": c["class"], "severity": c["severity"],
         "default_route": ROUTE[c["severity"]], "requester_message_template": c["requester"],
         "analyst_message_template": c["analyst"]}
        for c in CODES["codes"] if c["code"] not in have])
    insert_configured_rules(conn, t)
    lp = t["ops.leave_policy"]
    policy = dict(conn.execute(sa.select(lp).where(lp.c.leave_policy_id == "LPOL-ANNUAL-IN-V1")).mappings().one())
    accruals = accrual_schedule(policy, date(2022, 6, 15), None, 2026, SUBMIT.date())
    conn.execute(sa.insert(t["ops.leave_balance"]).values(
        leave_balance_id=LBAL, employee_id="EMP-000002", leave_policy_id="LPOL-ANNUAL-IN-V1", leave_year=2026,
        opening_balance=Decimal("0"), accrued=sum(q for _, q in accruals), adjustments=Decimal("0"),
        used=Decimal("0"), last_recalculated_at=T0))
    conn.execute(sa.insert(t["ops.leave_balance_transaction"]), [
        {"transaction_id": f"LBT-2026-{i:06d}", "leave_balance_id": LBAL, "leave_request_id": None,
         "txn_type": "ACCRUAL", "quantity": q, "txn_date": d,
         "posted_at": datetime(d.year, d.month, d.day, tzinfo=timezone.utc), "reason": "Monthly accrual",
         "correlation_id": uuid.uuid5(uuid.NAMESPACE_URL, f"lbt-{i}")} for i, (d, q) in enumerate(accruals, start=1)])
    for rid, end in (("LVE-2026-000901", date(2026, 3, 11)), ("LVE-2026-000902", date(2026, 3, 13))):
        conn.execute(sa.insert(t["ops.leave_request"]).values(
            leave_request_id=rid, employee_id="EMP-000002", leave_policy_id="LPOL-ANNUAL-IN-V1",
            start_date=date(2026, 3, 9), end_date=end, start_half_day=False, end_half_day=False,
            first_submitted_at=None, current_round=1, business_day_count=Decimal("0"),
            requested_quantity=Decimal("0"), workflow_status="DRAFT", exception_class="NONE",
            medical_cert_flag=False, created_at=T0))
    return t


def _submit(conn, rid: str):
    return submit_leave(SqlLeaveStore(conn, WEEKEND), rid, CATALOGUE, SUBMIT, "EMP-000002",
                        uuid.uuid5(uuid.NAMESPACE_URL, rid))


def test_clean_submission_is_persisted(conn, world):
    """3 days against 4.5 (Jan, Feb, Mar accrual): PENDING_APPROVAL, three status events, no exception rows."""
    res = _submit(conn, "LVE-2026-000901")
    assert res.status == "PENDING_APPROVAL" and res.validation.balances[2026]["available"] == Decimal("4.5")
    lr = world["ops.leave_request"]
    row = conn.execute(sa.select(lr).where(lr.c.leave_request_id == "LVE-2026-000901")).mappings().one()
    assert (row["workflow_status"], row["requested_quantity"], row["first_submitted_at"]) == \
        ("PENDING_APPROVAL", Decimal("3.0"), SUBMIT)
    ev = world["ops.request_status_event"]
    events = conn.execute(sa.select(ev.c.event_id, ev.c.previous_status, ev.c.new_status)
                          .where(ev.c.leave_request_id == "LVE-2026-000901").order_by(ev.c.event_id)).all()
    assert [(p, n) for _, p, n in events] == [("DRAFT", "SUBMITTED"), ("SUBMITTED", "VALIDATING"),
                                              ("VALIDATING", "PENDING_APPROVAL")]
    assert [e for e, _, _ in events] == ["RSE-000000001", "RSE-000000002", "RSE-000000003"]
    assert conn.execute(sa.select(sa.func.count()).select_from(world["ops.request_exception"])).scalar() == 0


def test_second_submission_sees_the_first_as_a_reservation_and_overlap(conn, world):
    """The open first request reserves 3.0 and overlaps: 5 days against 1.5 -> INSUFFICIENT_BALANCE (HARD) and
    OVERLAPPING_PENDING_LEAVE (SOFT) are both stored; HARD decides (REJECTED)."""
    _submit(conn, "LVE-2026-000901")
    res = _submit(conn, "LVE-2026-000902")
    assert res.status == "REJECTED" and res.validation.balances[2026]["available"] == Decimal("1.5")
    rx = world["ops.request_exception"]
    stored = conn.execute(sa.select(rx.c.exception_id, rx.c.exception_code, rx.c.detected_by)
                          .where(rx.c.leave_request_id == "LVE-2026-000902").order_by(rx.c.exception_id)).all()
    assert [(c, d) for _, c, d in stored] == [("INSUFFICIENT_BALANCE", "SUBMISSION"),
                                              ("OVERLAPPING_PENDING_LEAVE", "SUBMISSION")]
    assert [i for i, _, _ in stored] == ["REX-000000001", "REX-000000002"]
    seq = world["ops.id_sequence"]
    # APE: the first (clean) request got its approval step and one ASSIGNED event (Phase 7A); the rejected one none.
    assert dict(conn.execute(sa.select(seq.c.sequence_scope, seq.c.next_value)).all()) == \
        {"RSE": 7, "REX": 3, "APE": 2}


def test_submit_locks_the_request_and_the_balance_rows(conn, world):
    """AM-F5: after submit the open transaction holds row locks (ROW SHARE) on leave_request and leave_balance."""
    _submit(conn, "LVE-2026-000901")
    locked = conn.execute(sa.text(
        "SELECT c.relname FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
        "WHERE l.pid = pg_backend_pid() AND l.mode = 'RowShareLock'")).scalars().all()
    assert {"leave_request", "leave_balance"} <= set(locked)
