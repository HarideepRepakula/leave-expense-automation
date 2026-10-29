"""Read-only queries for the API (Phase 9): a request with its steps, status history, exceptions and (claims) lines;
a page of requests; a reimbursement with its attempts; a login. Ops tables only, no business rules."""
from __future__ import annotations

import sqlalchemy as sa

from src.repositories.base import table

KINDS = {"LEAVE": ("leave_request", "leave_request_id"), "EXPENSE": ("expense_claim", "expense_claim_id")}


def kind_of(request_id: str) -> str | None:
    """LVE-... is a leave request, EXP-... an expense claim (docs/10 id formats)."""
    return "LEAVE" if request_id.startswith("LVE-") else "EXPENSE" if request_id.startswith("EXP-") else None


def _rows(conn: sa.Connection, query) -> list[dict]:
    return [dict(r) for r in conn.execute(query).mappings()]


def list_requests(conn: sa.Connection, kind: str, employee_id: str | None, limit: int, offset: int) -> list[dict]:
    name, pk = KINDS[kind]
    t = table(name)
    q = sa.select(t).order_by(t.c[pk]).limit(limit).offset(offset)
    if employee_id is not None:
        q = q.where(t.c.employee_id == employee_id)
    return _rows(conn, q)


def get_request(conn: sa.Connection, kind: str, request_id: str) -> dict | None:
    """The request row plus steps, status_history, exceptions and (claims) lines; None when unknown."""
    name, pk = KINDS[kind]
    t = table(name)
    row = conn.execute(sa.select(t).where(t.c[pk] == request_id)).mappings().one_or_none()
    if row is None:
        return None
    st, ev, rx = table("approval_step"), table("request_status_event"), table("request_exception")
    out = {"request": dict(row),
           "steps": _rows(conn, sa.select(st).where(st.c[pk] == request_id).order_by(st.c.sequence_no)),
           "status_history": _rows(conn, sa.select(ev).where(ev.c[pk] == request_id).order_by(ev.c.event_id)),
           "exceptions": _rows(conn, sa.select(rx).where(rx.c[pk] == request_id).order_by(rx.c.exception_id))}
    if kind == "EXPENSE":
        el = table("expense_line")
        out["lines"] = _rows(conn, sa.select(el).where(el.c.expense_claim_id == request_id)
                             .order_by(el.c.submission_round, el.c.line_number))
    return out


def get_reimbursement(conn: sa.Connection, reimbursement_id: str) -> dict | None:
    rb, ra = table("reimbursement"), table("reimbursement_attempt")
    row = conn.execute(sa.select(rb).where(rb.c.reimbursement_id == reimbursement_id)).mappings().one_or_none()
    if row is None:
        return None
    return {"reimbursement": dict(row),
            "attempts": _rows(conn, sa.select(ra).where(ra.c.reimbursement_id == reimbursement_id)
                              .order_by(ra.c.attempt_id))}


def employee(conn: sa.Connection, employee_id: str) -> dict | None:
    e = table("employee")
    row = conn.execute(sa.select(e).where(e.c.employee_id == employee_id)).mappings().one_or_none()
    return None if row is None else dict(row)


def login_row(conn: sa.Connection, username: str) -> tuple[dict, list[str]] | None:
    """The application_user and its role names (user_role), or None."""
    u, ur, r = table("application_user"), table("user_role"), table("role")
    row = conn.execute(sa.select(u).where(u.c.username == username)).mappings().one_or_none()
    if row is None:
        return None
    roles = sorted(conn.execute(sa.select(r.c.role_name).join(ur, ur.c.role_id == r.c.role_id)
                                .where(ur.c.user_id == row["user_id"])).scalars())
    return dict(row), roles
