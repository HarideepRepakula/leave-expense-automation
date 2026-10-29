"""Dashboard pages added in the completion pass (spec section 20): Analytics, Approval operations, Reimbursements,
and the shared filters. Same data paths as views.py: the analytics views (lea_analytics_ro) only; nothing here
reads evaluation data. Ages are measured at the dataset as-of date (client.as_of()).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.dashboard import client

DECIDED = ("APPROVED", "REJECTED")
AGING = ((0, 2, "0-2 days"), (3, 7, "3-7 days"), (8, 14, "8-14 days"), (15, 30, "15-30 days"),
         (31, 10 ** 6, "over 30 days"))
LEAVE_CASES = {"INSUFFICIENT_BALANCE": "Insufficient balance",
               "OVERLAPPING_APPROVED_LEAVE": "Overlapping approved leave",
               "OVERLAPPING_PENDING_LEAVE": "Overlapping pending leave",
               "NEGATIVE_BALANCE_UNPERMITTED": "Negative balance not permitted"}
EXPENSE_CASES = {"MISSING_RECEIPT": "Missing receipts",
                 "DUPLICATE_RECEIPT_SELF": "Duplicate receipt (same employee)",
                 "DUPLICATE_RECEIPT_CROSS_EMPLOYEE": "Duplicate receipt (other employee)",
                 "LINE_LIMIT_EXCEEDED": "Policy breach: line limit",
                 "CLAIM_LIMIT_EXCEEDED": "Policy breach: claim limit",
                 "SPLIT_CLAIM_SUSPECTED": "Potential split claims",
                 "EXPENSE_OUTSIDE_EMPLOYMENT": "Claims outside employment dates"}


def _aging(days: int) -> str:
    return next(label for lo, hi, label in AGING if lo <= days <= hi)


def _days(later: pd.Series, earlier: pd.Series) -> pd.Series:
    return (pd.to_datetime(later, utc=True) - pd.to_datetime(earlier, utc=True)).dt.total_seconds() / 86400


def _rate(num: int, den: int) -> str:
    return "n/a" if den == 0 else f"{num / den:.1%}"


def _money(values) -> str:
    return f"{client.money(values):,.2f}"


def _mean_days(values: pd.Series) -> str:
    values = values.dropna()
    return f"{values.mean():.2f}" if len(values) else "n/a"


# --- data and filters -------------------------------------------------------------------------------------------

def requests_frame() -> pd.DataFrame:
    """v_request joined with v_request_dimension (leave type, cost center, manager, decided_at)."""
    req = client.frame("requests").merge(client.frame("dimensions").drop(columns="request_type"), on="request_id",
                                         how="left")
    req["submitted_on"] = pd.to_datetime(req.first_submitted_at, utc=True).dt.date
    return req


def filters(req: pd.DataFrame, key: str) -> pd.DataFrame:
    """Sidebar filters (spec 20): submission date range, country, department, manager, workflow status, cost
    center, expense category, exception type. Returns the matching requests."""
    lines, ex = client.frame("lines"), client.frame("exceptions")
    sb = st.sidebar
    sb.markdown("**Filters**")
    dated = req.submitted_on.dropna()
    view = req
    if not dated.empty:
        lo, hi = dated.min(), dated.max()
        span = sb.date_input("Submitted between", (lo, hi), min_value=lo, max_value=hi, key=f"{key}-dates")
        if isinstance(span, (tuple, list)) and len(span) == 2:
            view = view[view.submitted_on.isna()
                        | ((view.submitted_on >= span[0]) & (view.submitted_on <= span[1]))]
    choices = {"Country": "country", "Department": "department_id", "Manager": "manager_id",
               "Workflow status": "workflow_status", "Cost center": "cost_center_id"}
    for label, col in choices.items():
        picked = sb.multiselect(label, sorted(req[col].dropna().unique()), key=f"{key}-{col}")
        if picked:
            view = view[view[col].isin(picked)]
    cats = sb.multiselect("Expense category", sorted(lines.category.unique()), key=f"{key}-category")
    if cats:
        view = view[view.request_id.isin(lines[lines.category.isin(cats)].expense_claim_id)]
    codes = sb.multiselect("Exception type", sorted(ex.exception_code.unique()), key=f"{key}-code")
    if codes:
        view = view[view.request_id.isin(ex[ex.exception_code.isin(codes)].request_id)]
    sb.caption(f"{len(view)} of {len(req)} requests match")
    return view


# --- Analytics --------------------------------------------------------------------------------------------------

def _decision_rates(df: pd.DataFrame, by: str) -> pd.DataFrame:
    rows = []
    for value, g in df.groupby(by):
        approved = int((g.workflow_status == "APPROVED").sum())
        rejected = int((g.workflow_status == "REJECTED").sum())
        rows.append({by: value, "Requests": len(g), "Approved": approved, "Rejected": rejected,
                     "Approval rate": _rate(approved, approved + rejected),
                     "Rejection rate": _rate(rejected, approved + rejected)})
    return pd.DataFrame(rows)


def _case_counts(ex: pd.DataFrame, ids: pd.Series, cases: dict) -> pd.DataFrame:
    sub = ex[ex.request_id.isin(ids)]
    return pd.DataFrame([{"Case": label, "Exception code": code,
                          "Requests": int(sub[sub.exception_code == code].request_id.nunique())}
                         for code, label in cases.items()])


def analytics(token: str, user: dict) -> None:
    st.header("Analytics")
    req = filters(requests_frame(), "analytics")
    ex, lines = client.frame("exceptions"), client.frame("lines")
    st.caption("Approval rate = APPROVED / (APPROVED + REJECTED); pending, escalated, returned and draft requests "
               "are not decided yet. Turnaround = final decision time - first submission time (decided requests "
               "with a recorded decision).")

    leave = req[req.request_type == "LEAVE"]
    decided = leave[leave.workflow_status.isin(DECIDED)]
    st.subheader("Leave")
    c = st.columns(4)
    c[0].metric("Leave requests", len(leave))
    c[1].metric("Approval rate", _rate(int((decided.workflow_status == "APPROVED").sum()), len(decided)))
    c[2].metric("Days approved", f"{leave[leave.workflow_status == 'APPROVED'].leave_days.astype(float).sum():,.1f}")
    c[3].metric("Average turnaround (days)", _mean_days(_days(decided.decided_at, decided.first_submitted_at)))
    left, right = st.columns(2)
    left.markdown("**By leave type**")
    left.dataframe(_decision_rates(leave, "leave_type"), hide_index=True, width="stretch")
    right.markdown("**Insufficient balance and overlapping leave**")
    right.dataframe(_case_counts(ex, leave.request_id, LEAVE_CASES), hide_index=True, width="stretch")
    st.markdown("**By country and department** (requests)")
    st.dataframe(leave.pivot_table(index="country", columns="department_id", values="request_id", aggfunc="count",
                                   fill_value=0), width="stretch")
    st.caption("Leave utilisation against entitlement needs the balance ledger, which the analytics views do not "
               "expose; 'Days approved' is shown instead.")

    claims = req[req.request_type == "EXPENSE"]
    dec = claims[claims.workflow_status.isin(DECIDED)]
    st.subheader("Expenses")
    c = st.columns(3)
    c[0].metric("Expense claims", len(claims))
    c[1].metric("Claimed, USD (stored conversion)", _money(claims.total_amount_usd))
    c[2].metric("Approval rate", _rate(int((dec.workflow_status == "APPROVED").sum()), len(dec)))
    cl_lines = lines[lines.expense_claim_id.isin(claims.request_id)]
    left, right = st.columns(2)
    left.markdown("**By category** (current-round lines)")
    left.dataframe(cl_lines.groupby("category").agg(lines=("expense_line_id", "count"),
                                                    claims=("expense_claim_id", "nunique")).reset_index(),
                   hide_index=True, width="stretch")
    right.markdown("**By country**")
    right.dataframe(pd.DataFrame([{"country": k, "claims": len(g), "claimed_usd": _money(g.total_amount_usd)}
                                  for k, g in claims.groupby("country")]), hide_index=True, width="stretch")
    st.markdown("**By cost center**")
    st.dataframe(pd.DataFrame([{"cost_center_id": k, "claims": len(g), "claimed_usd": _money(g.total_amount_usd)}
                               for k, g in claims.groupby(claims.cost_center_id.fillna("(none)"))]),
                 hide_index=True, width="stretch", height=240)
    st.markdown("**Claimed versus approved** (each claim's own currency; approved = APPROVED claims)")
    st.dataframe(pd.DataFrame([{"Currency": cur, "Claims": len(g), "Claimed": _money(g.total_amount),
                                "Approved": _money(g[g.workflow_status == "APPROVED"].approved_amount)}
                               for cur, g in claims.groupby("currency")]), hide_index=True, width="stretch")
    st.markdown("**Missing receipts, duplicates, policy breaches, split claims, outside employment**")
    st.dataframe(_case_counts(ex, claims.request_id, EXPENSE_CASES), hide_index=True, width="stretch")


# --- Approval operations ----------------------------------------------------------------------------------------

def approval_operations(token: str, user: dict) -> None:
    st.header("Approval operations")
    req = filters(requests_frame(), "approvals")
    steps = client.frame("steps")
    steps = steps[steps.request_id.isin(req.request_id)]
    as_of = pd.Timestamp(client.as_of())
    queue = steps[(steps.step_status == "PENDING") & steps.assigned_at.notna()].copy()
    assigned_on = pd.to_datetime(queue.assigned_at, utc=True).dt.tz_localize(None).dt.normalize()
    queue["age_days"] = (as_of - assigned_on).dt.days
    queue["aging"] = queue.age_days.map(_aging)
    attempts = client.frame("approval_attempts")
    blocked = attempts[(attempts.outcome == "BLOCKED") & attempts.request_id.isin(req.request_id)]
    decided = req[req.workflow_status.isin(DECIDED)]

    c = st.columns(4)
    c[0].metric("Pending approval steps", len(queue))
    c[1].metric("Requests awaiting approval", int(queue.request_id.nunique()))
    c[2].metric("Average turnaround (days)", _mean_days(_days(decided.decided_at, decided.first_submitted_at)))
    c[3].metric("Unauthorized approval attempts (blocked)", len(blocked))
    st.caption(f"Ages at the dataset as-of date {client.as_of()}. A blocked attempt is a self-approval or an "
               "approval by someone who is not the step's approver, refused and recorded (approval_attempt).")

    left, right = st.columns(2)
    left.markdown("**Requests awaiting each level**")
    left.dataframe(queue.groupby("required_level").agg(requests=("request_id", "nunique")).reset_index(),
                   hide_index=True, width="stretch")
    right.markdown("**Approval aging**")
    right.dataframe(pd.DataFrame([{"Age": label, "Pending steps": int((queue.aging == label).sum())}
                                  for _, _, label in AGING]), hide_index=True, width="stretch")

    st.markdown("**Pending approval queue** (oldest first)")
    st.dataframe(queue.sort_values(["assigned_at", "approval_step_id"])[
        ["approval_step_id", "request_type", "request_id", "required_level", "approver_employee_id", "assigned_at",
         "age_days"]].astype(str), hide_index=True, width="stretch", height=260)

    done = steps[steps.step_status.isin(DECIDED) & steps.decision_at.notna()].copy()
    done["days"] = _days(done.decision_at, done.assigned_at)
    left, right = st.columns(2)
    left.markdown("**Approver workload** (pending and decided steps)")
    workload = (queue.groupby("approver_employee_id").size().rename("pending").to_frame()
                .join(done.groupby("approver_employee_id").size().rename("decided"), how="outer").fillna(0)
                .astype(int).sort_values(["pending", "decided"], ascending=False).reset_index())
    left.dataframe(workload, hide_index=True, width="stretch", height=260)
    right.markdown("**Average time at each level** (decided steps, days)")
    right.dataframe(done.groupby("required_level").days.agg(["count", "mean", "median"]).round(2).reset_index(),
                    hide_index=True, width="stretch")
    st.markdown("**Blocked approval attempts by reason**")
    if blocked.empty:
        st.caption("None in the data (the self-approval and unauthorized-approver plants S11 / S12 are deferred).")
    else:
        st.dataframe(blocked.groupby("reason_code").size().rename("attempts").reset_index(), hide_index=True,
                     width="stretch")


# --- Reimbursements ---------------------------------------------------------------------------------------------

def reimbursements(token: str, user: dict) -> None:
    st.header("Reimbursements")
    req, rb = client.frame("requests"), client.frame("reimbursements")
    attempts, failures = client.frame("reimbursement_attempts"), client.frame("failures")
    failures = failures[failures.entity_type == "reimbursement"]
    eligible = req[(req.request_type == "EXPENSE") & (req.workflow_status == "APPROVED")
                   & (req.approved_amount.fillna(0).astype(float) > 0)]
    dup = attempts[(attempts.outcome == "BLOCKED") & (attempts.reason_code == "DUPLICATE_REIMBURSEMENT")]
    c = st.columns(3)
    c[0].metric("Eligible claims", len(eligible))
    c[1].metric("Awaiting reimbursement", int((rb.reimbursement_status != "COMPLETED").sum()))
    c[2].metric("Completed reimbursements", int((rb.reimbursement_status == "COMPLETED").sum()))
    c = st.columns(3)
    c[0].metric("Failed processing", len(failures))
    c[1].metric("Failed payment attempts", int((attempts.outcome == "PAYMENT_FAILED").sum()))
    c[2].metric("Duplicate reimbursement attempts", len(dup))
    st.caption("Eligible = APPROVED claims with an approved amount above zero. Failed processing = reimbursement "
               "processing_failure rows (technical status, kept separate from the workflow status); a failed "
               "payment can be retried and completed later. A duplicate attempt is refused by a unique index and "
               "recorded as a BLOCKED attempt.")
    st.subheader("Amounts by currency")
    st.dataframe(pd.DataFrame([{"Currency": cur, "Reimbursements": len(g), "Amount": _money(g.approved_amount),
                                "Completed": _money(g[g.reimbursement_status == "COMPLETED"].approved_amount)}
                               for cur, g in rb.groupby("currency")]), hide_index=True, width="stretch")
    left, right = st.columns(2)
    left.markdown("**Failed processing by error and resolution**")
    left.dataframe(failures.groupby(["error_code", "resolution_status"]).size().rename("failures").reset_index(),
                   hide_index=True, width="stretch")
    right.markdown("**Attempts by outcome**")
    right.dataframe(attempts.fillna({"reason_code": "-"}).groupby(["outcome", "reason_code"]).size()
                    .rename("attempts").reset_index(), hide_index=True, width="stretch")
    st.markdown("**Duplicate reimbursement attempts**")
    st.dataframe(dup[["attempt_id", "expense_claim_id", "attempted_at", "reason_code"]].astype(str), hide_index=True,
                 width="stretch")
