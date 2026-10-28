"""PostgreSQL LeaveStore for leave submission (docs/06 section 8.1 steps 2-4 and 7; docs/03 section 8; AM-F5).

The store works on one SQLAlchemy Connection inside the caller's transaction: one transaction per use case, and
the store never commits (the caller commits or rolls back). Locks, in this order: the request row, then the
employee's leave_balance rows on the request's policy, both FOR UPDATE, before the ledger is read, so two
submissions of the same employee cannot both spend the same balance. No business rule lives here.

IDs for request_status_event (RSE) and request_exception (REX) come from ops.id_sequence (DEC-32, base.py).
Not yet: idempotency_record and audit_event rows (Phase 8), approval steps (Phase 7).
"""
from __future__ import annotations

import sqlalchemy as sa

from src.common.enums import RequestType, WorkflowStatus
from src.repositories.base import table as _t
from src.repositories.base import write_events_and_exceptions
from src.services.calendar_service import HolidayCalendar
from src.services.leave_request_service import LeaveContext, SubmissionResult


class SqlLeaveStore:
    def __init__(self, conn: sa.Connection, weekend_days: dict[str, list[int]]) -> None:
        self.conn, self.weekend_days = conn, weekend_days

    def _one(self, table: str, column: str, value, lock: bool = False) -> dict:
        t = _t(table)
        q = sa.select(t).where(t.c[column] == value)
        return dict(self.conn.execute(q.with_for_update() if lock else q).mappings().one())

    def load_request(self, request_id: str) -> dict:
        return self._one("leave_request", "leave_request_id", request_id, lock=True)

    def context(self, r: dict) -> LeaveContext:
        emp = self._one("employee", "employee_id", r["employee_id"])
        lr, lb, lt, lp, hol = (_t("leave_request"), _t("leave_balance"), _t("leave_balance_transaction"),
                               _t("leave_policy"), _t("country_holiday"))
        policies = {p["leave_policy_id"]: dict(p) for p in self.conn.execute(sa.select(lp)).mappings()}
        others = [dict(o) for o in self.conn.execute(
            sa.select(lr).where(lr.c.employee_id == r["employee_id"], lr.c.leave_request_id != r["leave_request_id"],
                                lr.c.workflow_status != WorkflowStatus.DRAFT.value)
            .order_by(lr.c.leave_request_id)).mappings()]
        balances = [dict(b) for b in self.conn.execute(
            sa.select(lb).where(lb.c.employee_id == r["employee_id"], lb.c.leave_policy_id == r["leave_policy_id"])
            .order_by(lb.c.leave_balance_id).with_for_update()).mappings()]
        ledger = [dict(t) for t in self.conn.execute(
            sa.select(lt).where(lt.c.leave_balance_id.in_([b["leave_balance_id"] for b in balances]))
            .order_by(lt.c.transaction_id)).mappings()] if balances else []
        holidays = [dict(h) for h in self.conn.execute(sa.select(hol).where(hol.c.country == emp["country"]))
                    .mappings()]
        calendar = HolidayCalendar.from_rows(self.weekend_days, holidays)
        return LeaveContext(emp, policies[r["leave_policy_id"]], calendar, others, policies, ledger,
                            {b["leave_year"] for b in balances})

    def record_submission(self, result: SubmissionResult) -> None:
        v, c = result.validation, result.classification
        lr = _t("leave_request")
        self.conn.execute(sa.update(lr).where(lr.c.leave_request_id == result.request_id).values(
            workflow_status=c.status_after_validation, exception_class=c.exception_class,
            decision_reason_code=c.decision_reason_code, first_submitted_at=result.submitted_at,
            business_day_count=v.business_days, requested_quantity=v.quantity))
        common = {"request_type": RequestType.LEAVE.value, "leave_request_id": result.request_id,
                  "expense_claim_id": None, "submission_round": result.submission_round,
                  "correlation_id": result.correlation_id}
        write_events_and_exceptions(self.conn, common, result.events, v.findings, result.submitted_at)
