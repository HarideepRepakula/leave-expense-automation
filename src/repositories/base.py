"""Shared repository helpers: ops tables by name, id allocation (DEC-32) and the status/exception writes that leave
and expense submissions share (docs/06 8.1 step 7). No business rules."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.common.enums import DetectedBy
from src.models import Base
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
