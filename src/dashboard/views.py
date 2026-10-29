"""Operational dashboard views (Phase 10): Overview, Requests, Exceptions.

Aggregates come from the analytics views (lea_analytics_ro); one request's detail and its explanation come from the
API. None of these views reads evaluation data: that is evaluation_view.py, through GET /evaluation only.
Workflow status, exception class and severity are shown as separate columns, as stored.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.dashboard import client

STATUS_ORDER = ["DRAFT", "PENDING_APPROVAL", "ESCALATED_FOR_REVIEW", "RETURNED_FOR_CORRECTION", "APPROVED",
                "REJECTED", "CANCELLED"]
SEVERITY_ORDER = ["HARD", "CORRECTABLE", "SOFT", "INFO"]


def _fmt(amount) -> str:
    return f"{amount:,.2f}"


def _table(rows: list[dict]) -> pd.DataFrame:
    """API rows as text for display (ids, Decimal strings, JSON lists, timestamps) so every cell renders."""
    return pd.DataFrame(rows).fillna("").astype(str)


# --- Overview ---------------------------------------------------------------------------------------------------

def high_priority(req: pd.DataFrame) -> dict:
    """High-priority issues (DEC-CP-03, AMB-CP-03): distinct OPEN requests (not APPROVED, REJECTED or CANCELLED)
    that are ESCALATED_FOR_REVIEW or carry a HARD exception code in their current round, plus OPEN reimbursement
    processing failures. Same definition as GET /dashboard/metrics."""
    ex, failures = client.frame("exceptions"), client.frame("failures")
    hard = set(ex[ex.severity == "HARD"].request_id)
    open_ = ~req.workflow_status.isin(["APPROVED", "REJECTED", "CANCELLED"])
    requests_ = int((open_ & (req.workflow_status.eq("ESCALATED_FOR_REVIEW") | req.request_id.isin(hard))).sum())
    open_failures = int(((failures.entity_type == "reimbursement") & (failures.resolution_status == "OPEN")).sum())
    return {"requests": requests_, "payment_failures": open_failures, "total": requests_ + open_failures}


def overview(token: str, user: dict) -> None:
    st.header("Overview")
    req, rb = client.frame("requests"), client.frame("reimbursements")
    leave, claims = req[req.request_type == "LEAVE"], req[req.request_type == "EXPENSE"]
    issues = high_priority(req)

    c = st.columns(4)
    c[0].metric("Total employees", len(client.frame("employees")))
    c[1].metric("Leave requests", len(leave))
    c[2].metric("Expense claims", len(claims))
    c[3].metric("Reimbursements", len(rb))
    c = st.columns(4)
    c[0].metric("Pending approval (both)", int((req.workflow_status == "PENDING_APPROVAL").sum()))
    c[0].caption("PENDING_APPROVAL only; ESCALATED_FOR_REVIEW and RETURNED_FOR_CORRECTION are counted separately.")
    c[1].metric("Escalated for review", int((req.workflow_status == "ESCALATED_FOR_REVIEW").sum()))
    c[2].metric("Returned for correction", int((req.workflow_status == "RETURNED_FOR_CORRECTION").sum()))
    c[3].metric("High-priority issues", issues["total"])
    c[3].caption(f"{issues['requests']} open requests (not approved, rejected or cancelled) escalated for review or "
                 f"with a HARD exception, plus {issues['payment_failures']} open reimbursement processing failures.")
    c = st.columns(4)
    c[0].metric("Approved", int((req.workflow_status == "APPROVED").sum()))
    c[1].metric("Rejected", int((req.workflow_status == "REJECTED").sum()))
    c[2].metric("Requests with a policy exception", int((req.exception_class != "NONE").sum()))
    c[3].metric("Claimed amount, USD (stored conversion)", _fmt(client.money(claims.total_amount_usd)))

    st.subheader("Requests by workflow status")
    counts = (req.groupby(["workflow_status", "request_type"]).size().unstack(fill_value=0)
              .reindex([s for s in STATUS_ORDER if s in set(req.workflow_status)]))
    counts = counts.rename(columns={"LEAVE": "Leave requests", "EXPENSE": "Expense claims"})
    left, right = st.columns([2, 3])
    left.dataframe(counts, width="stretch")
    right.bar_chart(counts, stack=False)

    st.subheader("Expense claims and reimbursements by currency")
    st.caption("Amounts are exact sums in each claim's own currency. Approved = APPROVED claims only.")
    rows = []
    for cur in sorted(set(claims.currency.dropna()) | set(rb.currency.dropna())):
        cl, r = claims[claims.currency == cur], rb[rb.currency == cur]
        done = r[r.reimbursement_status == "COMPLETED"]
        rows.append({"Currency": cur, "Claims": len(cl), "Claimed amount": _fmt(client.money(cl.total_amount)),
                     "Approved amount": _fmt(client.money(cl[cl.workflow_status == "APPROVED"].approved_amount)),
                     "Reimbursements": len(r), "Reimbursed (completed)": _fmt(client.money(done.approved_amount)),
                     "Awaiting payment": _fmt(client.money(r[r.reimbursement_status != "COMPLETED"]
                                                           .approved_amount))})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.subheader("Reimbursements by status")
    st.dataframe(rb.groupby("reimbursement_status").size().rename("Reimbursements").to_frame(),
                 width="stretch")


# --- Requests ---------------------------------------------------------------------------------------------------

def requests(token: str, user: dict) -> None:
    st.header("Requests")
    req = client.frame("requests")
    c = st.columns(4)
    kind = c[0].selectbox("Request type", ["All", "Leave", "Expense"])
    statuses = c[1].multiselect("Workflow status", [s for s in STATUS_ORDER if s in set(req.workflow_status)])
    classes = c[2].multiselect("Exception class", sorted(req.exception_class.unique()))
    countries = c[3].multiselect("Country", sorted(req.country.unique()))
    text = st.text_input("Request or employee id contains", "")

    view = req
    if kind != "All":
        view = view[view.request_type == kind.upper()]
    if statuses:
        view = view[view.workflow_status.isin(statuses)]
    if classes:
        view = view[view.exception_class.isin(classes)]
    if countries:
        view = view[view.country.isin(countries)]
    if text.strip():
        t = text.strip().upper()
        view = view[view.request_id.str.contains(t, regex=False) | view.employee_id.str.contains(t, regex=False)]

    st.caption(f"{len(view)} of {len(req)} requests")
    cols = ["request_type", "request_id", "employee_id", "country", "workflow_status", "exception_class",
            "current_round", "first_submitted_at", "period_start", "period_end", "leave_days", "total_amount",
            "currency"]
    st.dataframe(view[cols].astype(str).replace({"None": "", "NaT": "", "nan": ""}), hide_index=True,
                 width="stretch", height=320)
    if view.empty:
        st.info("No request matches the filters.")
        return
    request_id = st.selectbox("Show details for", list(view.request_id))
    _detail(token, request_id, set(user["roles"]))


def _detail(token: str, request_id: str, roles: set[str]) -> None:
    """Analysts get GET /requests/{id}/investigation (adds expense lines, applicable policies, approval attempts
    and audit events); approvers the plain request detail."""
    if roles & client.ANALYST_ROLES:
        path = f"/requests/{request_id}/investigation"
    else:
        path = f"/leave-requests/{request_id}" if request_id.startswith("LVE-") else f"/expense-claims/{request_id}"
    try:
        d = client.get(token, path)
        e = client.get(token, f"/requests/{request_id}/explanation")
    except client.DashboardError as exc:
        st.error(str(exc))
        return
    r = d["request"]
    st.subheader(f"{request_id}")
    c = st.columns(3)
    c[0].metric("Workflow status", r["workflow_status"])
    c[1].metric("Exception class", r["exception_class"])
    c[2].metric("Round", r["current_round"])

    st.markdown("**Explanation**")
    st.info(e["explanation"]["text"])
    source = e["explanation"]["source"]
    note = f"Source: {source}" + (f" (model {e['explanation']['model']})" if source == "llm" else "")
    if e.get("fallback_reason"):
        note += f"; template used because: {e['fallback_reason']}"
    st.caption(note + ". Display only: the explanation never changes a decision, status or amount.")

    for title, key in (("Approval steps", "steps"), ("Status history", "status_history"),
                       ("Exception codes", "exceptions"), ("Expense lines", "lines"),
                       ("Applicable policy", "policies"), ("Approval attempts", "approval_attempts"),
                       ("Reimbursements", "reimbursements"), ("Audit events", "audit_events")):
        if key not in d:
            continue
        st.markdown(f"**{title}**")
        if d[key]:
            st.dataframe(_table(d[key]), hide_index=True, width="stretch")
        else:
            st.caption("None.")


# --- Exceptions -------------------------------------------------------------------------------------------------

def exceptions(token: str, user: dict) -> None:
    st.header("Exceptions")
    ex, req = client.frame("exceptions"), client.frame("requests")
    st.caption("Exception codes recorded at submission, current round of each request. Severity: HARD rejects, "
               "CORRECTABLE returns for correction, SOFT sends for review, INFO is a note only.")
    sev = ex.groupby("severity").size()
    c = st.columns(5)
    for i, s in enumerate(SEVERITY_ORDER):
        c[i].metric(s.title(), int(sev.get(s, 0)))
    c[4].metric("Requests with an exception", int((req.exception_class != "NONE").sum()))

    st.subheader("By exception code")
    by_code = (ex.groupby(["exception_code", "exception_class", "severity"])
               .agg(codes=("exception_id", "count"), requests=("request_id", "nunique"))
               .reset_index().sort_values(["codes", "exception_code"], ascending=[False, True]))
    left, right = st.columns([3, 2])
    left.dataframe(by_code, hide_index=True, width="stretch")
    right.bar_chart(by_code.set_index("exception_code")["codes"])

    st.subheader("Requests by exception class")
    by_class = req.groupby(["exception_class", "request_type"]).size().unstack(fill_value=0)
    st.dataframe(by_class, width="stretch")

    st.subheader("Suspicious-pattern detections")
    try:
        det = client.get(token, "/detections")
    except client.DashboardError as exc:
        st.info(f"Not available for this user: {exc}")
        return
    if not det["available"]:
        st.info("No detector output yet. Run: python -m src.validation")
        return
    d = pd.DataFrame(det["items"])
    d = d[d.exception_class == "SUSPICIOUS_PATTERN"] if not d.empty else d
    st.caption("System detectors at submission and in the batch run (data/validation/detections.csv).")
    if d.empty:
        st.caption("None.")
        return
    st.dataframe(d.groupby(["exception_code", "detected_by"]).size().rename("detections").reset_index(),
                 hide_index=True, width="stretch")
    st.dataframe(d[["record_type", "record_id", "exception_code", "detected_by", "detail"]], hide_index=True,
                 width="stretch", height=280)
