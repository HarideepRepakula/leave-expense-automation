"""Evaluation view (Phase 10). The ONLY dashboard module that shows evaluation results, and it reads them through
GET /evaluation only (src/evaluation behind the API, role lea_evaluation). No database connection, no file read
(tests/dashboard/test_dashboard.py checks it)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.dashboard import client


def _pct(value) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def evaluation(token: str, user: dict) -> None:
    st.header("Evaluation")
    try:
        ev = client.get(token, "/evaluation")
    except client.DashboardError as exc:
        st.info(f"Not available for this user (analysts and admins only): {exc}")
        return

    st.subheader("Data quality (M1-M3)")
    dq = ev.get("data_quality", {})
    if dq.get("available"):
        st.dataframe(pd.DataFrame([{"Metric": k, "Name": m["name"], "Numerator": m["numerator"],
                                    "Denominator": m["denominator"], "Value": _pct(m["value"])}
                                   for k, m in dq.items() if k.startswith("M")]),
                     hide_index=True, width="stretch")
    else:
        st.info("No validation report yet. Run: python -m src.validation")
    st.caption("M1 = primary-key violations / rows checked; M2 = foreign-key violations / non-NULL foreign-key "
               "values; M3 = records passing every arithmetic check / records subject to one (docs/08 section 3). "
               "Computed by python -m src.validation from the stored data.")

    st.subheader("Detection results")
    det = ev["detection"]
    o = det["overall"]
    c = st.columns(5)
    c[0].metric("True positives", o["tp"])
    c[1].metric("False positives", o["fp"])
    c[2].metric("False negatives", o["fn"])
    c[3].metric("Precision", _pct(o["precision"]))
    c[4].metric("Recall", _pct(o["recall"]))
    st.dataframe(pd.DataFrame(det["by_code"]).assign(precision=lambda d: d.precision.map(_pct),
                                                     recall=lambda d: d.recall.map(_pct)),
                 hide_index=True, width="stretch")
    st.caption("A detection is a (record, code) pair the system produced: an exception code at submission, a "
               "batch-detector row, a blocked duplicate reimbursement or a reimbursement processing failure. A "
               "positive is a ground-truth label that expects detection. TP = in both, FP = detected only, "
               "FN = expected only; precision = TP / (TP + FP), recall = TP / (TP + FN) (docs/08 section 2). "
               "A preliminary view of M6-M8; the full evaluation report is Phase 11.")

    st.subheader("Services vs reference oracle")
    st.dataframe(pd.DataFrame([{"Comparison": name, **v} for name, v in ev["comparisons"].items()]).fillna(0),
                 hide_index=True, width="stretch")
    st.dataframe(pd.DataFrame(ev["status_at_asof_vs_expected"]), hide_index=True, width="stretch")
    st.caption("AGREE / DISAGREE: the business services and the independent reference calculation, request by "
               "request. Status at as-of: stored workflow status equal to the expected status.")
