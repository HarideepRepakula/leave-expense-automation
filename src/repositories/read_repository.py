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


def page(conn: sa.Connection, name: str, columns: list[str] | None, filters: dict, order: str, limit: int,
         offset: int) -> list[dict]:
    """One page of a table: only `columns` (all when None), equality filters (None values skipped)."""
    t = table(name)
    q = sa.select(*(t.c[c] for c in columns)) if columns else sa.select(t)
    for col, value in filters.items():
        if value is not None:
            q = q.where(t.c[col] == value)
    return _rows(conn, q.order_by(t.c[order]).limit(limit).offset(offset))


def expense_lines(conn: sa.Connection, columns: list[str], claim_id: str | None, owner: str | None, limit: int,
                  offset: int) -> list[dict]:
    """Lines of every claim, or of one claim; `owner` limits them to that employee's claims."""
    el, ec = table("expense_line"), table("expense_claim")
    q = sa.select(*(el.c[c] for c in columns))
    if owner is not None:
        q = q.join(ec, ec.c.expense_claim_id == el.c.expense_claim_id).where(ec.c.employee_id == owner)
    if claim_id is not None:
        q = q.where(el.c.expense_claim_id == claim_id)
    return _rows(conn, q.order_by(el.c.expense_line_id).limit(limit).offset(offset))


def approval_queue(conn: sa.Connection, approver: str | None, level: str | None, limit: int,
                   offset: int) -> list[dict]:
    """Assigned PENDING approval steps (the queue), oldest assignment first."""
    st = table("approval_step")
    q = sa.select(st.c.approval_step_id, st.c.request_type,
                  sa.func.coalesce(st.c.leave_request_id, st.c.expense_claim_id).label("request_id"),
                  st.c.submission_round, st.c.sequence_no, st.c.required_level, st.c.approver_employee_id,
                  st.c.delegated_from_employee_id, st.c.assigned_at) \
        .where(st.c.step_status == "PENDING", st.c.assigned_at.is_not(None))
    if approver is not None:
        q = q.where(st.c.approver_employee_id == approver)
    if level is not None:
        q = q.where(st.c.required_level == level)
    return _rows(conn, q.order_by(st.c.assigned_at, st.c.approval_step_id).limit(limit).offset(offset))


def audit_history(conn: sa.Connection, kind: str, request_id: str, limit: int, offset: int) -> list[dict]:
    """audit_event rows of the request, its approval steps and (claims) its reimbursements, in event order."""
    name, pk = KINDS[kind]
    ae, st, rb = table("audit_event"), table("approval_step"), table("reimbursement")
    related = sa.or_(
        sa.and_(ae.c.entity_type == name, ae.c.entity_id == request_id),
        sa.and_(ae.c.entity_type == "approval_step",
                ae.c.entity_id.in_(sa.select(st.c.approval_step_id).where(st.c[pk] == request_id))))
    if kind == "EXPENSE":
        related = sa.or_(related, sa.and_(ae.c.entity_type == "reimbursement", ae.c.entity_id.in_(
            sa.select(rb.c.reimbursement_id).where(rb.c.expense_claim_id == request_id))))
    return _rows(conn, sa.select(ae).where(related).order_by(ae.c.occurred_at, ae.c.event_id)
                 .limit(limit).offset(offset))


def investigation(conn: sa.Connection, kind: str, request_id: str) -> dict | None:
    """get_request plus the applicable policies, exception class / severity, approval attempts, reimbursements
    and the audit history (first 500 events)."""
    d = get_request(conn, kind, request_id)
    if d is None:
        return None
    pk = KINDS[kind][1]
    k, aa = table("exception_code"), table("approval_attempt")
    codes = {r["exception_code"]: r for r in _rows(conn, sa.select(k.c.exception_code, k.c.exception_class,
                                                                    k.c.severity, k.c.analyst_message_template))}
    for x in d["exceptions"]:
        x.update({key: codes[x["exception_code"]][key] for key in ("exception_class", "severity",
                                                                   "analyst_message_template")})
    if kind == "LEAVE":
        lp = table("leave_policy")
        d["policies"] = _rows(conn, sa.select(lp).where(lp.c.leave_policy_id == d["request"]["leave_policy_id"]))
    else:
        ep, rb = table("expense_policy"), table("reimbursement")
        ids = {d["request"]["expense_policy_id"]} | {ln["expense_policy_id"] for ln in d["lines"]}
        d["policies"] = _rows(conn, sa.select(ep).where(ep.c.expense_policy_id.in_(ids - {None}))
                              .order_by(ep.c.expense_policy_id))
        d["reimbursements"] = _rows(conn, sa.select(rb).where(rb.c.expense_claim_id == request_id)
                                    .order_by(rb.c.reimbursement_id))
    d["approval_attempts"] = _rows(conn, sa.select(aa).where(aa.c[pk] == request_id).order_by(aa.c.attempt_id))
    d["audit_events"] = audit_history(conn, kind, request_id, 500, 0)
    return d


DASHBOARD_METRICS = sa.text("""
    WITH req AS (
        SELECT 'LEAVE' AS request_type, leave_request_id AS request_id, workflow_status, exception_class,
               current_round FROM ops.leave_request
        UNION ALL
        SELECT 'EXPENSE', expense_claim_id, workflow_status, exception_class, current_round FROM ops.expense_claim),
    hard AS (
        SELECT DISTINCT coalesce(x.leave_request_id, x.expense_claim_id) AS request_id
        FROM ops.request_exception x JOIN ops.exception_code k ON k.exception_code = x.exception_code
        JOIN req ON req.request_id = coalesce(x.leave_request_id, x.expense_claim_id)
        WHERE k.severity = 'HARD' AND x.submission_round = req.current_round)
    SELECT (SELECT count(*) FROM ops.employee) AS employees,
           count(*) FILTER (WHERE request_type = 'LEAVE') AS leave_requests,
           count(*) FILTER (WHERE request_type = 'EXPENSE') AS expense_claims,
           count(*) FILTER (WHERE workflow_status = 'APPROVED') AS approved,
           count(*) FILTER (WHERE workflow_status = 'REJECTED') AS rejected,
           count(*) FILTER (WHERE workflow_status = 'PENDING_APPROVAL') AS pending_approval,
           count(*) FILTER (WHERE workflow_status = 'ESCALATED_FOR_REVIEW') AS escalated_for_review,
           count(*) FILTER (WHERE workflow_status = 'RETURNED_FOR_CORRECTION') AS returned_for_correction,
           count(*) FILTER (WHERE exception_class <> 'NONE') AS requests_with_exception,
           count(*) FILTER (WHERE request_id IN (SELECT request_id FROM hard)) AS hard_exception_requests,
           count(*) FILTER (WHERE workflow_status NOT IN ('APPROVED', 'REJECTED', 'CANCELLED')
                            AND (workflow_status = 'ESCALATED_FOR_REVIEW'
                                 OR request_id IN (SELECT request_id FROM hard))) AS escalated_or_hard_requests,
           (SELECT count(*) FROM ops.processing_failure
            WHERE entity_type = 'reimbursement' AND resolution_status = 'OPEN') AS open_payment_failures
    FROM req""")
AMOUNTS_BY_CURRENCY = sa.text("""
    SELECT c.currency, count(*) AS claims, sum(c.total_amount) AS claimed_amount,
           coalesce(sum(c.approved_amount) FILTER (WHERE c.workflow_status = 'APPROVED'), 0) AS approved_amount,
           coalesce((SELECT sum(r.approved_amount) FROM ops.reimbursement r
                     WHERE r.currency = c.currency AND r.reimbursement_status = 'COMPLETED'), 0) AS reimbursed_amount
    FROM ops.expense_claim c GROUP BY c.currency ORDER BY c.currency""")


def dashboard_metrics(conn: sa.Connection) -> dict:
    """Operational KPIs (no ground truth). high_priority_issues = distinct OPEN requests (not APPROVED, REJECTED or
    CANCELLED) that are ESCALATED_FOR_REVIEW or carry a HARD exception code in the current round, plus OPEN
    reimbursement processing failures (DEC-CP-03 as amended by AMB-CP-03)."""
    m = dict(conn.execute(DASHBOARD_METRICS).mappings().one())
    m["high_priority_issues"] = m["escalated_or_hard_requests"] + m["open_payment_failures"]
    rb = table("reimbursement")
    m["reimbursements_by_status"] = dict(conn.execute(
        sa.select(rb.c.reimbursement_status, sa.func.count()).group_by(rb.c.reimbursement_status)
        .order_by(rb.c.reimbursement_status)).all())
    m["amounts_by_currency"] = _rows(conn, AMOUNTS_BY_CURRENCY)
    return m


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
