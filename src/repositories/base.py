"""Shared repository helpers: ops tables by name, id allocation (DEC-32) and the status/exception writes that leave
and expense submissions share (docs/06 8.1 step 7). No business rules."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.common.enums import DetectedBy
from src.models import Base


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
