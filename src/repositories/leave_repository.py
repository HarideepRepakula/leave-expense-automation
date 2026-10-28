"""PostgreSQL LeaveStore for leave submission (docs/06 section 8.1 steps 2-4 and 7; docs/03 section 8; AM-F5).

The store works on one SQLAlchemy Connection inside the caller's transaction: one transaction per use case, and
the store never commits (the caller commits or rolls back). Locks, in this order: the request row, then the
employee's leave_balance rows on the request's policy, both FOR UPDATE, before the ledger is read, so two
submissions of the same employee cannot both spend the same balance. No business rule lives here.

IDs for request_status_event (RSE) and request_exception (REX) come from ops.id_sequence (DEC-32, base.py).
Routing (Phase 7A) reads approval_rule, employee, department and delegation in the same transaction; approval_step
rows and the ASSIGNED approval_event (APE) are written for PENDING_APPROVAL.
Phase 7B: the store is also a WorkflowStore (SqlWorkflow, base.py) for approval_service decisions: USAGE rows at
approval (LBT ids per year) with the leave_balance snapshot kept equal to its ledger, resubmission (round + 1,
corrected columns, first_submitted_at kept) and idempotency_record rows for decisions and resubmissions.
Not yet: audit_event rows (Phase 8).
"""
from __future__ import annotations

import sqlalchemy as sa

from src.common.enums import RequestType, WorkflowStatus
from src.repositories.base import table as _t
from src.repositories.base import SqlWorkflow, allocate_ledger_ids, load_router, next_step_sequence, \
    write_events_and_exceptions, write_steps
from src.services.approval_routing import ApprovalRouter
from src.services.calendar_service import HolidayCalendar
from src.services.leave_request_service import LeaveContext, SubmissionResult, approval_postings


class SqlLeaveStore(SqlWorkflow):
    request_type, fk, request_table = RequestType.LEAVE.value, "leave_request_id", "leave_request"

    def __init__(self, conn: sa.Connection, weekend_days: dict[str, list[int]]) -> None:
        self.conn, self.weekend_days = conn, weekend_days

    def _one(self, table: str, column: str, value, lock: bool = False) -> dict:
        t = _t(table)
        q = sa.select(t).where(t.c[column] == value)
        return dict(self.conn.execute(q.with_for_update() if lock else q).mappings().one())

    def load_request(self, request_id: str) -> dict:
        return self._one("leave_request", "leave_request_id", request_id, lock=True)

    def router(self) -> ApprovalRouter:
        return load_router(self.conn)

    def next_step_sequence(self, request_id: str) -> int:
        return next_step_sequence(self.conn, "leave_request_id", request_id)

    def calendar(self, country: str) -> HolidayCalendar:
        hol = _t("country_holiday")
        rows = [dict(h) for h in self.conn.execute(sa.select(hol).where(hol.c.country == country)).mappings()]
        return HolidayCalendar.from_rows(self.weekend_days, rows)

    # WorkflowStore (approval_service) -----------------------------------------------------------------------
    def routing_inputs(self, r: dict):
        pol = self._one("leave_policy", "leave_policy_id", r["leave_policy_id"])
        return (pol["leave_type"], r["requested_quantity"],
                self.round_submitted_at(r["leave_request_id"], r["current_round"]).date())

    def approval_effects(self, r: dict, at):
        emp = self._one("employee", "employee_id", r["employee_id"])
        pol = self._one("leave_policy", "leave_policy_id", r["leave_policy_id"])
        return {}, approval_postings(self.calendar(emp["country"]), r, emp["country"], pol, at)

    def release_postings(self, r: dict, at, reason: str) -> list[dict]:
        return []

    def override_postings(self, r: dict, at) -> list[dict]:
        return []

    def post_decision_rows(self, res) -> None:
        """USAGE rows (BR-LBAL-05) and the snapshot's used column (BR-LBAL-06), balance rows locked first."""
        lt, lb = _t("leave_balance_transaction"), _t("leave_balance")
        for t in res.leave_postings:
            self.conn.execute(sa.select(lb.c.leave_balance_id).where(lb.c.leave_balance_id == t["leave_balance_id"])
                              .with_for_update())
            tid = allocate_ledger_ids(self.conn, t["txn_date"].year, 1)[0]
            self.conn.execute(sa.insert(lt).values(transaction_id=tid, posted_at=res.at,
                                                   correlation_id=res.correlation_id, **t))
            self.conn.execute(sa.update(lb).where(lb.c.leave_balance_id == t["leave_balance_id"])
                              .values(used=lb.c.used - t["quantity"], last_recalculated_at=res.at))

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
            **result.changes, workflow_status=c.status_after_validation, exception_class=c.exception_class,
            decision_reason_code=c.decision_reason_code,
            first_submitted_at=sa.func.coalesce(lr.c.first_submitted_at, result.submitted_at),
            business_day_count=v.business_days, requested_quantity=v.quantity))
        if result.idempotency is not None:
            self.record_idempotency(result.idempotency)
        common = {"request_type": RequestType.LEAVE.value, "leave_request_id": result.request_id,
                  "expense_claim_id": None, "submission_round": result.submission_round,
                  "correlation_id": result.correlation_id}
        write_events_and_exceptions(self.conn, common, result.events, result.findings, result.submitted_at)
        write_steps(self.conn, result.steps, result.correlation_id)
        self.record_audit(result.audit_events)
