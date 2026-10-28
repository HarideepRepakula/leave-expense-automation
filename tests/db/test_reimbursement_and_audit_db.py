"""Reassignment, reimbursements, payments, audit_event and processing_failure through the PostgreSQL stores
(Phase 8; docs/06 sections 3, 4, 6, 7, 8.2 step 6, 8.4, 8.5).

Runs in lea_test inside the rolled-back `conn` transaction, on the world of tests/db/test_approval_decisions_db.py:
EMP-000002 (requester) reports to EMP-000001; claim EXP of 1,500 INR routes to EMP-000001 at L1 (RULE-E-001).
Added here: EMP-000003 (EMP-000001's manager, user USR-000003) and a SYSTEM_ADMIN user USR-000099 (the idempotency
scope of the SYSTEM payment run, ASM-P8-02)."""
from __future__ import annotations

import contextlib
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa

from src.repositories.base import run_recording_failure, write_audit
from src.repositories.expense_repository import SqlExpenseStore
from src.services import audit_service
from src.services.approval_service import cancel_request, decide_step, reassign_departed
from src.services.expense_service import submit_expense
from src.services.reimbursement_service import create_reimbursement, settle_payment, start_payment
from tests.conftest import T0
from tests.db.test_approval_decisions_db import CORR, DECIDE, _rows, users  # noqa: F401
from tests.db.test_approval_steps_db import CATALOGUE, EXP, PARAMS, SUBMIT, world  # noqa: F401

pytestmark = pytest.mark.db
STEP = f"APR-{EXP}-01"


@pytest.fixture()
def org(conn, users):  # noqa: F811
    t = users
    boss = dict(employee_id="EMP-000003", full_name="Mira Director", email="emp000003@example.test", manager_id=None,
                department_id="DEPT-01", job_title="Director", grade="G6", country="IN", currency="INR",
                employment_start=date(2015, 1, 1), employment_end=None, employment_status="ACTIVE",
                default_cost_center_id="CC-0001", is_department_head=False, is_finance_controller=False,
                created_at=T0)
    conn.execute(sa.insert(t["ops.employee"]).values(boss))
    conn.execute(sa.update(t["ops.employee"]).where(t["ops.employee"].c.employee_id == "EMP-000001")
                 .values(manager_id="EMP-000003"))
    conn.execute(sa.insert(t["ops.application_user"]), [
        dict(user_id="USR-000003", username="emp000003", password_hash="$2b$12$synthetic-hash-placeholder",
             employee_id="EMP-000003", is_active=True, created_at=T0),
        dict(user_id="USR-000099", username="admin", password_hash="$2b$12$synthetic-hash-placeholder",
             employee_id=None, is_active=True, created_at=T0)])
    conn.execute(sa.insert(t["ops.role"]).values(role_id="ROLE-SYSTEM_ADMIN", role_name="SYSTEM_ADMIN",
                                                 description="Administers configuration and users"))
    conn.execute(sa.insert(t["ops.user_role"]).values(user_id="USR-000099", role_id="ROLE-SYSTEM_ADMIN"))
    return t


def _store(conn) -> SqlExpenseStore:
    return SqlExpenseStore(conn, PARAMS)


def _submitted(conn) -> None:
    res = submit_expense(_store(conn), EXP, CATALOGUE, SUBMIT, "EMP-000002", CORR)
    assert res.status == "PENDING_APPROVAL"


def _sorted(conn, t, name, key, **where) -> list[dict]:
    return sorted(_rows(conn, t, name, **where), key=lambda r: r[key])


# --- carried over from Phase 7B: SqlWorkflow.record_reassignment -----------------------------------------------------
def test_record_reassignment_on_postgresql(conn, org):
    t = org
    _submitted(conn)
    emp = t["ops.employee"]
    conn.execute(sa.update(emp).where(emp.c.employee_id == "EMP-000001")
                 .values(employment_end=date(2026, 3, 2), employment_status="TERMINATED"))
    when = datetime(2026, 3, 3, 0, 0, tzinfo=timezone.utc)
    assert reassign_departed(_store(conn), EXP, STEP, when, CORR) == "EMP-000003"
    step = _rows(conn, t, "approval_step", approval_step_id=STEP)[0]
    assert (step["approver_employee_id"], step["delegated_from_employee_id"], step["assigned_at"],
            step["step_status"]) == ("EMP-000003", None, SUBMIT, "PENDING")
    events = _sorted(conn, t, "approval_event", "approval_event_id", approval_step_id=STEP)
    assert [(e["event_type"], e["actor_id"], e["reason_code"], e["comment"], e["occurred_at"]) for e in events] == [
        ("ASSIGNED", None, None, None, SUBMIT),
        ("REASSIGNED", None, "APPROVER_EMPLOYMENT_ENDED", "EMP-000001 -> EMP-000003", when)]
    audit = [a for a in _rows(conn, t, "audit_event", entity_id=STEP)]
    assert [(a["previous_state"], a["new_state"], a["actor_id"], a["reason_code"], a["calculated_values"])
            for a in audit] == [("PENDING", "PENDING", "SYSTEM", "APPROVER_EMPLOYMENT_ENDED",
                                 {"from": "EMP-000001", "to": "EMP-000003"})]
    assert reassign_departed(_store(conn), EXP, STEP, when, CORR) is None      # EMP-000003 is employed
    assert len(_rows(conn, t, "approval_event", approval_step_id=STEP)) == 2
    old = decide_step(_store(conn), EXP, STEP, "EMP-000001", "APPROVE", DECIDE, CORR)
    assert old.reason_code == "UNAUTHORIZED_APPROVER"                        # the leaver can no longer act
    new = decide_step(_store(conn), EXP, STEP, "EMP-000003", "APPROVE", DECIDE, CORR)
    assert new.new_status == "APPROVED"
    assert _rows(conn, t, "approval_step", approval_step_id=STEP)[0]["step_status"] == "APPROVED"


# --- reimbursement at final approval, payment run, audit ---------------------------------------------------------
def test_final_approval_reimbursement_payment_failure_retry_and_audit(conn, org):
    t = org
    _submitted(conn)
    decide_step(_store(conn), EXP, STEP, "EMP-000001", "APPROVE", DECIDE, CORR)
    (b,) = _rows(conn, t, "reimbursement")
    assert (b["reimbursement_id"], b["expense_claim_id"], b["employee_id"], b["approved_amount"], b["currency"],
            b["reimbursement_status"], b["approval_completion_step_id"], b["created_at"]) == \
        ("RMB-2026-000001", EXP, "EMP-000002", Decimal("1500.00"), "INR", "ELIGIBLE", STEP, DECIDE)
    rmb = b["reimbursement_id"]
    pay = datetime(2026, 3, 9, 10, tzinfo=timezone.utc)
    start_payment(_store(conn), rmb, pay, CORR)
    assert start_payment(_store(conn), rmb, pay, CORR, attempt_no=1).replayed
    settle_payment(_store(conn), rmb, pay, CORR, succeeded=False)
    (f,) = _rows(conn, t, "processing_failure")
    assert (f["failure_id"], f["entity_type"], f["entity_id"], f["operation"], f["error_code"],
            f["resolution_status"]) == ("PFL-000000001", "reimbursement", rmb, "PROCESS_PAYMENT", "PAYMENT_FAILED",
                                        "OPEN")
    assert _rows(conn, t, "expense_claim", expense_claim_id=EXP)[0]["workflow_status"] == "APPROVED"
    retry = datetime(2026, 3, 11, 10, tzinfo=timezone.utc)
    start_payment(_store(conn), rmb, retry, CORR)
    settle_payment(_store(conn), rmb, retry, CORR, succeeded=True, payment_reference="PAY-0001")
    b = _rows(conn, t, "reimbursement")[0]
    assert (b["reimbursement_status"], b["completed_at"], b["payment_reference"]) == ("COMPLETED", retry, "PAY-0001")
    attempts = _sorted(conn, t, "reimbursement_attempt", "attempt_id")
    assert [(a["attempt_id"], a["actor_type"], a["attempted_action"], a["outcome"], a["reason_code"])
            for a in attempts] == [
        ("RMA-000000001", "SYSTEM", "CREATE", "ACCEPTED", None),
        ("RMA-000000002", "SYSTEM", "PROCESS", "ACCEPTED", None),
        ("RMA-000000003", "SYSTEM", "PROCESS", "PAYMENT_FAILED", "PAYMENT_FAILED"),
        ("RMA-000000004", "SYSTEM", "RETRY", "ACCEPTED", None),
        ("RMA-000000005", "SYSTEM", "RETRY", "COMPLETED", "PAYMENT_COMPLETED")]
    ledger = _sorted(conn, t, "cost_center_transaction", "transaction_id")
    assert [(x["txn_type"], x["amount"]) for x in ledger] == [("RESERVATION", Decimal("1500.00")),
                                                               ("ACTUAL", Decimal("1500.00"))]
    budget = _rows(conn, t, "cost_center_budget")[0]
    assert (budget["committed_amount"], budget["actual_amount"]) == (Decimal("0.00"), Decimal("1500.00"))
    idem = {(r["actor_user_id"], r["operation"]) for r in _rows(conn, t, "idempotency_record")}
    assert idem == {("USR-000001", "APPROVE"), ("USR-000099", "PROCESS_PAYMENT")}     # two runs, one admin scope
    assert len(_rows(conn, t, "idempotency_record", operation="PROCESS_PAYMENT")) == 2
    audit = _sorted(conn, t, "audit_event", "event_id")
    claim = [(a["previous_state"], a["new_state"]) for a in audit if a["entity_id"] == EXP]
    assert claim == [("DRAFT", "SUBMITTED"), ("SUBMITTED", "VALIDATING"), ("VALIDATING", "PENDING_APPROVAL"),
                     ("PENDING_APPROVAL", "APPROVED")]
    assert [(a["previous_state"], a["new_state"], a["reason_code"]) for a in audit if a["entity_id"] == rmb] == [
        (None, "ELIGIBLE", None), ("ELIGIBLE", "PROCESSING", None), (None, None, "IDEMPOTENT_REPLAY"),
        ("PROCESSING", "FAILED", "PAYMENT_FAILED"), (None, None, "PAYMENT_FAILED"),
        ("FAILED", "PROCESSING", None), ("PROCESSING", "COMPLETED", "PAYMENT_COMPLETED")]
    assert audit[0]["event_id"] == "AUD-000000001" and len({a["event_id"] for a in audit}) == len(audit)


def test_manual_create_is_blocked_before_approval_and_for_a_duplicate_even_in_a_race(conn, org):
    t = org
    _submitted(conn)
    early = create_reimbursement(_store(conn), EXP, "EMP-000001", DECIDE, CORR)
    assert (early.outcome, early.reason_code) == ("BLOCKED", "CLAIM_NOT_APPROVED")
    assert _rows(conn, t, "reimbursement") == []
    decide_step(_store(conn), EXP, STEP, "EMP-000001", "APPROVE", DECIDE, CORR)
    dup = create_reimbursement(_store(conn), EXP, "EMP-000001", DECIDE, CORR, idempotency_key="d" * 64)
    assert (dup.outcome, dup.reason_code) == ("BLOCKED", "DUPLICATE_REIMBURSEMENT")
    racing = _store(conn)
    racing.active_reimbursements = lambda claim_id: []          # as if a concurrent creation was not yet visible
    raced = create_reimbursement(racing, EXP, "EMP-000001", DECIDE, CORR, idempotency_key="e" * 64)
    assert (raced.outcome, raced.reason_code, raced.reimbursement_id) == ("BLOCKED", "DUPLICATE_REIMBURSEMENT", None)
    assert [b["reimbursement_id"] for b in _rows(conn, t, "reimbursement")] == ["RMB-2026-000001"]
    assert [(a["attempted_action"], a["outcome"], a["reason_code"])
            for a in _sorted(conn, t, "reimbursement_attempt", "attempt_id")] == [
        ("CREATE", "BLOCKED", "CLAIM_NOT_APPROVED"), ("CREATE", "ACCEPTED", None),
        ("CREATE", "BLOCKED", "DUPLICATE_REIMBURSEMENT"), ("CREATE", "BLOCKED", "DUPLICATE_REIMBURSEMENT")]


def test_a_technical_error_rolls_back_and_records_a_processing_failure(conn, org):
    t = org

    class InTestTransaction:                    # engine.begin() as a savepoint of the rolled-back test transaction
        @contextlib.contextmanager
        def begin(self):
            with conn.begin_nested():
                yield conn

    corr = uuid.UUID(int=99)

    def work(c):
        write_audit(c, [audit_service.event("expense_claim", EXP, None, None, "EMP-000002", SUBMIT, corr)])
        raise sa.exc.OperationalError("SELECT 1", {}, Exception("connection reset"))

    with pytest.raises(sa.exc.OperationalError):
        run_recording_failure(InTestTransaction(), "SUBMIT", "expense_claim", EXP, SUBMIT, corr, work)
    (f,) = _rows(conn, t, "processing_failure")
    assert (f["entity_id"], f["operation"], f["error_code"], f["correlation_id"]) == \
        (EXP, "SUBMIT", "OperationalError", corr)
    audit = _rows(conn, t, "audit_event")
    assert [(a["entity_id"], a["reason_code"], a["correlation_id"]) for a in audit] == \
        [(EXP, "OperationalError", corr)]                      # the work's own audit row was rolled back

    def refused(c):
        raise ValueError("not a technical error")

    with pytest.raises(ValueError):
        run_recording_failure(InTestTransaction(), "SUBMIT", "expense_claim", EXP, SUBMIT, corr, refused)
    assert len(_rows(conn, t, "processing_failure")) == 1


def test_cancel_on_postgresql_releases_and_writes_no_attempt(conn, org):
    t = org
    _submitted(conn)
    res = cancel_request(_store(conn), EXP, "EMP-000002", DECIDE, CORR)
    assert res.new_status == "CANCELLED"
    claim = _rows(conn, t, "expense_claim", expense_claim_id=EXP)[0]
    assert (claim["workflow_status"], claim["decision_reason_code"]) == ("CANCELLED", "REQUESTER_CANCELLED")
    assert _rows(conn, t, "approval_step", approval_step_id=STEP)[0]["step_status"] == "CANCELLED"
    assert _rows(conn, t, "approval_attempt") == [] and _rows(conn, t, "idempotency_record") == []
    assert [(x["txn_type"], x["amount"]) for x in _sorted(conn, t, "cost_center_transaction", "transaction_id")] == \
        [("RESERVATION", Decimal("1500.00")), ("RELEASE", Decimal("1500.00"))]
    assert _rows(conn, t, "cost_center_budget")[0]["committed_amount"] == Decimal("0.00")
    last = _sorted(conn, t, "audit_event", "event_id")[-1]
    assert (last["entity_id"], last["previous_state"], last["new_state"], last["actor_id"]) == \
        (EXP, "PENDING_APPROVAL", "CANCELLED", "EMP-000002")
