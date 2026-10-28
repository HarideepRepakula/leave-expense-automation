"""Shared repository helpers: ops tables by name, id allocation (DEC-32) and the status/exception writes that leave
and expense submissions share (docs/06 8.1 step 7). No business rules."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.common.enums import DetectedBy, RoleName
from src.models import Base
from src.services import audit_service
from src.services.approval_routing import ApprovalRouter, assignment_event


def table(name: str) -> sa.Table:
    return Base.metadata.tables[f"ops.{name}"]


def allocate_ids(conn: sa.Connection, table_name: str, prefix: str, n: int) -> list[str]:
    """n consecutive ids <PREFIX>-000000001 from id_sequence, locked FOR UPDATE (DEC-32). A missing scope row is
    created from the highest id already in the table, so ids continue after a loaded dataset (DEC-P5-07)."""
    if n == 0:
        return []
    seq, tbl = table("id_sequence"), table(table_name)
    pk = list(tbl.primary_key.columns)[0]
    highest = sa.select(sa.func.coalesce(sa.func.max(sa.cast(sa.func.substr(pk, len(prefix) + 2), sa.Integer)), 0)
                        + 1).scalar_subquery()
    conn.execute(pg_insert(seq).values(sequence_scope=prefix, next_value=highest)
                 .on_conflict_do_nothing(index_elements=["sequence_scope"]))
    first = conn.execute(sa.select(seq.c.next_value).where(seq.c.sequence_scope == prefix)
                         .with_for_update()).scalar_one()
    conn.execute(sa.update(seq).where(seq.c.sequence_scope == prefix).values(next_value=first + n))
    return [f"{prefix}-{i:09d}" for i in range(first, first + n)]


def load_router(conn: sa.Connection) -> ApprovalRouter:
    """The router over the current ops rows: approval_rule, employee, department, delegation (Phase 7A)."""
    def rows(name: str) -> list[dict]:
        return [dict(r) for r in conn.execute(sa.select(table(name))).mappings()]

    return ApprovalRouter.from_rows(rows("approval_rule"), rows("employee"), rows("department"), rows("delegation"))


def next_step_sequence(conn: sa.Connection, column: str, request_id: str) -> int:
    """sequence_no continues across rounds (AM-A5): one more than the request's highest step."""
    st = table("approval_step")
    return conn.execute(sa.select(sa.func.coalesce(sa.func.max(st.c.sequence_no), 0) + 1)
                        .where(st.c[column] == request_id)).scalar_one()


def write_steps(conn: sa.Connection, steps: list[dict], correlation_id) -> None:
    """approval_step rows and the ASSIGNED approval_event of the first step (append-only, ids from id_sequence)."""
    if not steps:
        return
    conn.execute(sa.insert(table("approval_step")), steps)
    event_id = allocate_ids(conn, "approval_event", "APE", 1)[0]
    conn.execute(sa.insert(table("approval_event")).values(approval_event_id=event_id,
                                                           **assignment_event(steps[0], correlation_id)))


def write_events_and_exceptions(conn: sa.Connection, common: dict, events: list[dict], findings: list,
                                detected_at) -> None:
    """request_status_event rows (one per transition) and one request_exception row per code, append-only."""
    ids = allocate_ids(conn, "request_status_event", "RSE", len(events))
    conn.execute(sa.insert(table("request_status_event")), [{**common, "event_id": i, **e} for i, e in zip(ids, events)])
    if findings:
        rex = allocate_ids(conn, "request_exception", "REX", len(findings))
        conn.execute(sa.insert(table("request_exception")), [
            {**common, "exception_id": i, "exception_code": f.code, "detail": f.detail, "detected_at": detected_at,
             "detected_by": DetectedBy.SUBMISSION.value} for i, f in zip(rex, findings)])


def allocate_ledger_ids(conn: sa.Connection, year: int, n: int) -> list[str]:
    """n consecutive leave ledger ids LBT-<year>-000001 (DEC-P5-07)."""
    return allocate_year_ids(conn, "leave_balance_transaction", "LBT", year, n)


def allocate_year_ids(conn: sa.Connection, table_name: str, base: str, year: int, n: int) -> list[str]:
    """n consecutive ids <BASE>-<year>-000001 (scope <BASE>-<year> in id_sequence, created from the highest id of
    that year already in the table, DEC-P5-07): leave ledger (LBT) and reimbursement (RMB, AM-A6) ids."""
    if n == 0:
        return []
    seq, lt = table("id_sequence"), table(table_name)
    pk = list(lt.primary_key.columns)[0]
    scope, prefix = f"{base}-{year}", f"{base}-{year}-"
    highest = sa.select(sa.func.coalesce(sa.func.max(sa.cast(sa.func.substr(pk, len(prefix) + 1),
                                                             sa.Integer)), 0) + 1) \
        .where(pk.like(prefix + "%")).scalar_subquery()
    conn.execute(pg_insert(seq).values(sequence_scope=scope, next_value=highest)
                 .on_conflict_do_nothing(index_elements=["sequence_scope"]))
    first = conn.execute(sa.select(seq.c.next_value).where(seq.c.sequence_scope == scope)
                         .with_for_update()).scalar_one()
    conn.execute(sa.update(seq).where(seq.c.sequence_scope == scope).values(next_value=first + n))
    return [f"{prefix}{i:06d}" for i in range(first, first + n)]


class SqlWorkflow:
    """WorkflowStore parts shared by the PostgreSQL leave and expense stores (approval_service, Phase 7B). The store
    supplies conn, request_type, fk (its request column), request_table and post_decision_rows(). Rows are read in
    the caller's transaction; the request row (load_request) and the steps are locked FOR UPDATE (docs/06 8.2)."""

    def steps_of(self, request_id: str) -> list[dict]:
        st = table("approval_step")
        return [dict(r) for r in self.conn.execute(sa.select(st).where(st.c[self.fk] == request_id)
                                                   .order_by(st.c.sequence_no).with_for_update()).mappings()]

    def attempts_of(self, request_id: str) -> list[dict]:
        at = table("approval_attempt")
        return [dict(r) for r in self.conn.execute(sa.select(at).where(at.c.request_id == request_id)).mappings()]

    def user_of(self, employee_id: str) -> str:
        """The idempotency scope of an actor: the employee's user; for SYSTEM (payment runs, Phase 8) the
        lowest-id user holding SYSTEM_ADMIN (ASM-P8-02)."""
        u = table("application_user")
        if employee_id == audit_service.SYSTEM:
            ur, r = table("user_role"), table("role")
            found = self.conn.execute(sa.select(sa.func.min(ur.c.user_id)).join(r, r.c.role_id == ur.c.role_id)
                                      .where(r.c.role_name == RoleName.SYSTEM_ADMIN.value)).scalar_one_or_none()
        else:
            found = self.conn.execute(sa.select(u.c.user_id).where(u.c.employee_id == employee_id)) \
                .scalar_one_or_none()
        if found is None:
            raise ValueError(f"{employee_id} has no application_user (idempotency scope is the user)")
        return found

    def idempotency(self, actor_id: str, key: str) -> dict | None:
        ir = table("idempotency_record")
        row = self.conn.execute(sa.select(ir).where(ir.c.actor_user_id == self.user_of(actor_id),
                                                    ir.c.idempotency_key == key)).mappings().one_or_none()
        return None if row is None else dict(row)

    def roles_of(self, employee_id: str) -> set[str]:
        u, ur, r = table("application_user"), table("user_role"), table("role")
        return set(self.conn.execute(sa.select(r.c.role_name).join(ur, ur.c.role_id == r.c.role_id)
                                     .join(u, u.c.user_id == ur.c.user_id).where(u.c.employee_id == employee_id))
                   .scalars())

    def round_codes(self, request_id: str, submission_round: int) -> list[str]:
        rx = table("request_exception")
        return list(self.conn.execute(sa.select(rx.c.exception_code).where(
            rx.c[self.fk] == request_id, rx.c.submission_round == submission_round)
            .order_by(rx.c.exception_id)).scalars())

    def round_submitted_at(self, request_id: str, submission_round: int):
        rse = table("request_status_event")
        return self.conn.execute(sa.select(sa.func.max(rse.c.occurred_at)).where(
            rse.c[self.fk] == request_id, rse.c.submission_round == submission_round,
            rse.c.new_status == "SUBMITTED")).scalar_one()

    def record_idempotency(self, row: dict) -> None:
        conn = self.conn
        conn.execute(sa.insert(table("idempotency_record")).values(
            actor_user_id=self.user_of(row["actor_id"]), idempotency_key=row["idempotency_key"],
            operation=row["operation"], request_hash=row["request_hash"],
            leave_request_id=row["request_id"] if self.fk == "leave_request_id" else None,
            expense_claim_id=row["request_id"] if self.fk == "expense_claim_id" else None,
            status="COMPLETED", response_hash=row["response_hash"], created_at=row["created_at"],
            completed_at=row["completed_at"]))

    def record_decision(self, res) -> None:
        """docs/06 8.2 steps 4-7: attempt, idempotency record, step updates, new steps, approval events, status
        events, request columns and the type's postings, all in the caller's transaction (append-only tables only
        receive inserts; only PENDING steps are updated, the trigger freezes decided ones)."""
        conn = self.conn
        if res.attempt is not None:                  # a cancellation has neither attempt nor key
            conn.execute(sa.insert(table("approval_attempt")).values(
                attempt_id=allocate_ids(conn, "approval_attempt", "APA", 1)[0], **res.attempt))
            self.record_idempotency(res.idempotency_row)
        st = table("approval_step")
        for u in res.step_updates:
            conn.execute(sa.update(st).where(st.c.approval_step_id == u["approval_step_id"])
                         .values({k: v for k, v in u.items() if k != "approval_step_id"}))
        if res.new_steps:
            conn.execute(sa.insert(st), res.new_steps)
        if res.approval_events:
            ids = allocate_ids(conn, "approval_event", "APE", len(res.approval_events))
            conn.execute(sa.insert(table("approval_event")),
                         [{"approval_event_id": i, **e} for i, e in zip(ids, res.approval_events)])
        if res.status_events:
            common = {"request_type": self.request_type, "leave_request_id": None, "expense_claim_id": None,
                      self.fk: res.request_id, "submission_round": res.submission_round,
                      "correlation_id": res.correlation_id}
            write_events_and_exceptions(conn, common, res.status_events, [], res.at)
        if res.request_updates:
            t = table(self.request_table)
            conn.execute(sa.update(t).where(t.c[self.fk] == res.request_id).values(res.request_updates))
        self.post_decision_rows(res)
        self.record_audit(res.audit_events)
        if res.reimbursement is not None:          # after the claim row is APPROVED (eligibility trigger)
            self.record_reimbursement(res.reimbursement)

    def record_reassignment(self, request_id: str, step_update: dict, event: dict, audit: dict) -> None:
        """AMB-P7B-11: the PENDING step's new approver, one REASSIGNED approval_event and its audit row, in the
        caller's transaction."""
        st = table("approval_step")
        self.conn.execute(sa.update(st).where(st.c.approval_step_id == step_update["approval_step_id"])
                          .values({k: v for k, v in step_update.items() if k != "approval_step_id"}))
        self.conn.execute(sa.insert(table("approval_event")).values(
            approval_event_id=allocate_ids(self.conn, "approval_event", "APE", 1)[0], **event))
        self.record_audit([audit])

    def record_audit(self, rows: list[dict]) -> None:
        write_audit(self.conn, rows)


def write_audit(conn: sa.Connection, rows: list[dict]) -> None:
    """audit_event rows (append-only, AUD ids from id_sequence), in the caller's transaction."""
    if rows:
        ids = allocate_ids(conn, "audit_event", "AUD", len(rows))
        conn.execute(sa.insert(table("audit_event")), [{"event_id": i, **r} for i, r in zip(ids, rows)])


TECHNICAL = (sa.exc.OperationalError, sa.exc.InterfaceError, sa.exc.InternalError, TimeoutError, ConnectionError)


def run_recording_failure(engine: sa.Engine, operation: str, entity_type: str | None, entity_id: str | None,
                          at, correlation_id, work):
    """docs/06 6 and 8: run work(conn) in one transaction. A technical error (TECHNICAL, or LedgerMismatch /
    PolicyConfigurationError raised as RuntimeError) rolls it back; a processing_failure row and its audit row are
    then written in a second short transaction with the same correlation_id, and the error is raised again.
    Business refusals (IllegalTransition, IdempotencyConflict, ValueError) are not technical and pass through."""
    try:
        with engine.begin() as conn:
            return work(conn)
    except (*TECHNICAL, RuntimeError) as exc:
        failure = {"entity_type": entity_type, "entity_id": entity_id, "operation": operation,
                   "error_code": type(exc).__name__, "error_message": str(exc)[:500], "occurred_at": at,
                   "correlation_id": correlation_id, "resolution_status": "OPEN"}
        with engine.begin() as conn:
            conn.execute(sa.insert(table("processing_failure")).values(
                failure_id=allocate_ids(conn, "processing_failure", "PFL", 1)[0], **failure))
            write_audit(conn, [audit_service.failure_event(failure)])
        raise
