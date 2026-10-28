"""Approval steps written at submission by both PostgreSQL stores (Phase 7A; docs/05 5.3 step 7, docs/06 8.1).

Runs in lea_test inside the rolled-back `conn` transaction. seed: EMP-000002 (IN) reports to EMP-000001, who has no
manager; the configured approval rules are inserted. An UNPAID request routes by RULE-L-004 (L1, L3): with
EMP-000001 as head of DEPT-01 one step at L3 covers L1 and L3; with no head the request escalates
(NO_VALID_APPROVAL_PATH). An expense claim of 1,500 INR (17.75 USD) routes by RULE-E-001 to EMP-000001."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa
import yaml

from src.repositories.expense_repository import SqlExpenseStore
from src.repositories.leave_repository import SqlLeaveStore
from src.services.exception_service import ExceptionCatalogue
from src.services.expense_service import DetectionParams, submit_expense
from src.services.leave_request_service import submit_leave
from tests.conftest import ROOT, T0, expect_db_error, insert_configured_rules

pytestmark = pytest.mark.db

CODES = yaml.safe_load((ROOT / "config" / "exception_codes.yaml").read_text(encoding="utf-8"))
CATALOGUE = ExceptionCatalogue.from_config(CODES)
PARAMS = DetectionParams.from_config(yaml.safe_load((ROOT / "config" / "expense_policies.yaml")
                                                    .read_text(encoding="utf-8")))
ROUTE = {"HARD": "REJECTED", "CORRECTABLE": "RETURNED_FOR_CORRECTION", "SOFT": "ESCALATED_FOR_REVIEW", "INFO": "NONE"}
WEEKEND = {"IN": [6, 7], "US": [6, 7], "GB": [6, 7]}
SUBMIT = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)
LVE, EXP = "LVE-2026-000911", "EXP-2026-000911"


@pytest.fixture()
def world(conn, tables, seed):
    t = tables
    have = set(conn.execute(sa.select(t["ops.exception_code"].c.exception_code)).scalars())
    conn.execute(sa.insert(t["ops.exception_code"]), [
        {"exception_code": c["code"], "exception_class": c["class"], "severity": c["severity"],
         "default_route": ROUTE[c["severity"]], "requester_message_template": c["requester"],
         "analyst_message_template": c["analyst"]} for c in CODES["codes"] if c["code"] not in have])
    insert_configured_rules(conn, t)
    conn.execute(sa.insert(t["ops.leave_policy"]).values(
        leave_policy_id="LPOL-UNPAID-ALL-V1", policy_family="LPOL-UNPAID-ALL", version=1, policy_name="Unpaid v1",
        leave_type="UNPAID", country_scope="ALL", annual_entitlement_days=Decimal("0"), accrual_method="NONE",
        carry_forward_cap_days=Decimal("0"), negative_balance_allowed=False, negative_limit_days=Decimal("0"),
        min_service_days=0, requires_medical_cert_over_days=None, max_days_per_year=Decimal("30.0"),
        effective_start=date(2025, 1, 1), effective_end=None, is_active=True))
    conn.execute(sa.insert(t["ops.leave_request"]).values(
        leave_request_id=LVE, employee_id="EMP-000002", leave_policy_id="LPOL-UNPAID-ALL-V1",
        start_date=date(2026, 3, 9), end_date=date(2026, 3, 10), start_half_day=False, end_half_day=False,
        first_submitted_at=None, current_round=1, business_day_count=Decimal("0"), requested_quantity=Decimal("0"),
        workflow_status="DRAFT", exception_class="NONE", medical_cert_flag=False, created_at=T0))
    conn.execute(sa.insert(t["ops.fx_rate"]).values(fx_rate_id="FX-USD-INR-20250101", from_currency="USD",
                                                     to_currency="INR", rate=Decimal("84.5"),
                                                     effective_from=date(2025, 1, 1)))
    conn.execute(sa.insert(t["ops.expense_claim"]).values(
        expense_claim_id=EXP, employee_id="EMP-000002", first_submitted_at=None, claim_period_start=date(2026, 2, 20),
        claim_period_end=date(2026, 2, 20), country="IN", currency="INR", cost_center_id="CC-0001",
        expense_policy_id=None, total_amount=Decimal("1500.00"), workflow_status="DRAFT", exception_class="NONE",
        receipt_status="NOT_REQUIRED", current_round=1, created_at=T0))
    conn.execute(sa.insert(t["ops.expense_line"]).values(
        expense_line_id=f"EXPL-{EXP}-01", expense_claim_id=EXP, line_number=1, submission_round=1, category="MEALS",
        merchant_description="Team meal", expense_date=date(2026, 2, 20), quantity=Decimal("1"),
        unit_amount=Decimal("1500.00"), line_amount=Decimal("1500.00"), currency="INR", receipt_id=None,
        validation_result="PENDING"))
    return t


def _head(conn, world, head: str | None) -> None:
    d = world["ops.department"]
    conn.execute(sa.update(d).where(d.c.department_id == "DEPT-01").values(head_employee_id=head))


def _steps(conn, world, column: str, request_id: str) -> list[dict]:
    st = world["ops.approval_step"]
    return [dict(r) for r in conn.execute(sa.select(st).where(st.c[column] == request_id)
                                          .order_by(st.c.sequence_no)).mappings()]


def test_leave_step_covers_l1_and_l3_and_is_assigned(conn, world):
    _head(conn, world, "EMP-000001")
    res = submit_leave(SqlLeaveStore(conn, WEEKEND), LVE, CATALOGUE, SUBMIT, "EMP-000002",
                       uuid.uuid5(uuid.NAMESPACE_URL, LVE))
    assert res.status == "PENDING_APPROVAL" and res.routing.rule_id == "RULE-L-004"
    steps = _steps(conn, world, "leave_request_id", LVE)
    assert [(s["approval_step_id"], s["sequence_no"], s["submission_round"], s["approval_rule_id"],
             s["required_level"], s["covered_levels"], s["approver_employee_id"], s["delegated_from_employee_id"],
             s["step_status"], s["assigned_at"]) for s in steps] == [
        (f"APR-{LVE}-01", 1, 1, "RULE-L-004", "L3", ["L1", "L3"], "EMP-000001", None, "PENDING", SUBMIT)]
    ev = world["ops.approval_event"]
    events = conn.execute(sa.select(ev.c.approval_event_id, ev.c.approval_step_id, ev.c.event_type, ev.c.actor_id,
                                    ev.c.occurred_at)).all()
    assert [tuple(e) for e in events] == [("APE-000000001", f"APR-{LVE}-01", "ASSIGNED", None, SUBMIT)]
    rse = world["ops.request_status_event"]
    values = conn.execute(sa.select(rse.c.calculated_values).where(rse.c.leave_request_id == LVE,
                                                                   rse.c.new_status == "PENDING_APPROVAL")).scalar_one()
    assert values["route"] == [{"level": "L3", "approver_id": "EMP-000001", "covered_levels": ["L1", "L3"],
                                "delegated_from": None}]


def test_unresolved_level_escalates_with_an_exception_row_and_no_step(conn, world):
    _head(conn, world, None)
    res = submit_leave(SqlLeaveStore(conn, WEEKEND), LVE, CATALOGUE, SUBMIT, "EMP-000002",
                       uuid.uuid5(uuid.NAMESPACE_URL, LVE))
    assert res.status == "ESCALATED_FOR_REVIEW"
    lr, rx = world["ops.leave_request"], world["ops.request_exception"]
    assert conn.execute(sa.select(lr.c.workflow_status, lr.c.exception_class, lr.c.decision_reason_code)
                        .where(lr.c.leave_request_id == LVE)).one() == \
        ("ESCALATED_FOR_REVIEW", "NO_VALID_APPROVAL_PATH", "NO_VALID_APPROVAL_PATH")
    assert conn.execute(sa.select(rx.c.exception_code, rx.c.detected_by).where(rx.c.leave_request_id == LVE)).all() \
        == [("NO_VALID_APPROVAL_PATH", "SUBMISSION")]
    assert _steps(conn, world, "leave_request_id", LVE) == []


def test_expense_step_is_written_and_the_db_checks_guard_covered_levels(conn, world):
    res = submit_expense(SqlExpenseStore(conn, PARAMS), EXP, CATALOGUE, SUBMIT, "EMP-000002",
                         uuid.uuid5(uuid.NAMESPACE_URL, EXP))
    assert res.status == "PENDING_APPROVAL" and res.validation.usd == Decimal("17.75")
    steps = _steps(conn, world, "expense_claim_id", EXP)
    assert [(s["approval_step_id"], s["required_level"], s["covered_levels"], s["approver_employee_id"])
            for s in steps] == [(f"APR-{EXP}-01", "L1", ["L1"], "EMP-000001")]
    st = world["ops.approval_step"]
    # [] breaks two CHECKs; PostgreSQL reports whichever it evaluates first, so only the column is matched.
    for bad, name in (([], "ck_approval_step_covered_levels"), (["L2"], "covered_levels_include_required"),
                      (["L1", "L9"], "covered_levels_enum")):
        expect_db_error(conn, sa.update(st).where(st.c.approval_step_id == f"APR-{EXP}-01")
                        .values(covered_levels=bad), match=name)
