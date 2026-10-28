"""PostgreSQL LeaveStore for leave submission (docs/06 section 8.1 steps 2-4 and 7; docs/03 section 8; AM-F5).

The store works on one SQLAlchemy Connection inside the caller's transaction: one transaction per use case, and
the store never commits (the caller commits or rolls back). Locks, in this order: the request row, then the
employee's leave_balance rows on the request's policy, both FOR UPDATE, before the ledger is read, so two
submissions of the same employee cannot both spend the same balance. No business rule lives here.

IDs for request_status_event (RSE) and request_exception (REX) come from ops.id_sequence (DEC-32). A missing scope
row is created from the highest id already in the table, so ids continue after a loaded dataset.
Not yet: idempotency_record and audit_event rows (Phase 8), approval steps (Phase 7).
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.common.enums import DetectedBy, RequestType, WorkflowStatus
from src.models import Base
from src.services.calendar_service import HolidayCalendar
from src.services.leave_request_service import LeaveContext, SubmissionResult


def _t(name: str) -> sa.Table:
    return Base.metadata.tables[f"ops.{name}"]


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

    def _allocate(self, table: str, prefix: str, n: int) -> list[str]:
        """n consecutive ids <PREFIX>-000000001 from id_sequence, locked FOR UPDATE (DEC-32)."""
        if n == 0:
            return []
        seq, tbl = _t("id_sequence"), _t(table)
        pk = list(tbl.primary_key.columns)[0]
        highest = sa.select(sa.func.coalesce(sa.func.max(sa.cast(sa.func.substr(pk, len(prefix) + 2),
                                                                  sa.Integer)), 0) + 1).scalar_subquery()
        self.conn.execute(pg_insert(seq).values(sequence_scope=prefix, next_value=highest)
                          .on_conflict_do_nothing(index_elements=["sequence_scope"]))
        first = self.conn.execute(sa.select(seq.c.next_value).where(seq.c.sequence_scope == prefix)
                                  .with_for_update()).scalar_one()
        self.conn.execute(sa.update(seq).where(seq.c.sequence_scope == prefix).values(next_value=first + n))
        return [f"{prefix}-{i:09d}" for i in range(first, first + n)]

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
        events = [{**common, "event_id": eid, **e}
                  for eid, e in zip(self._allocate("request_status_event", "RSE", len(result.events)), result.events)]
        self.conn.execute(sa.insert(_t("request_status_event")), events)
        if v.findings:
            rex = self._allocate("request_exception", "REX", len(v.findings))
            self.conn.execute(sa.insert(_t("request_exception")), [
                {**common, "exception_id": xid, "exception_code": f.code, "detail": f.detail,
                 "detected_at": result.submitted_at, "detected_by": DetectedBy.SUBMISSION.value}
                for xid, f in zip(rex, v.findings)])
