"""Evaluation view (Phase 10). The ONLY dashboard module that shows evaluation results, and it reads them through
GET /evaluation only (src/evaluation behind the API, role lea_evaluation). No database connection, no file read
(tests/dashboard/test_dashboard.py checks it)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.dashboard import client


def _pct(value) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def _value(value, unit: str) -> str:
    if value is None:
        return "n/a"
    return _pct(value) if unit == "ratio" else f"{value} {unit}"


def evaluation(token: str, user: dict) -> None:
    st.header("Evaluation")
    try:
        ev = client.get(token, "/evaluation")
    except client.DashboardError as exc:
        st.info(f"Not available for this user (analysts and admins only): {exc}")
        return

    st.subheader("Evaluation metrics (M1-M18)")
    metrics = ev.get("metrics")
    if metrics:
        st.info(metrics["how_to_read"])
        st.dataframe(pd.DataFrame([{
            "Metric": m["metric_id"], "Name": m["metric_name"],
            "Value": m["note"] if m["status"] == "not_measurable" else _value(m["value"], m["unit"]),
            "Numerator": "" if m["numerator"] is None else str(m["numerator"]),
            "Denominator": "" if m["denominator"] is None else str(m["denominator"]),
            "Population": m["population"]} for m in metrics["metrics"]]), hide_index=True, width="stretch")
        chosen = st.selectbox("Breakdown for", [m["metric_id"] for m in metrics["metrics"]])
        m = next(x for x in metrics["metrics"] if x["metric_id"] == chosen)
        if m["note"]:
            st.caption(m["note"])
        if m["breakdown"]:
            st.dataframe(pd.DataFrame([{"Breakdown": b["key"], "Item": str(b["value"]),
                                        "Numerator": "" if b["numerator"] is None else str(b["numerator"]),
                                        "Denominator": "" if b["denominator"] is None else str(b["denominator"]),
                                        "Value": _value(b["result"], b["unit"])} for b in m["breakdown"]]),
                         hide_index=True, width="stretch")
        st.caption(f"As-of {metrics['as_of']}. Definitions: docs/08 section 3. Files: python -m "
                   "src.evaluation.metrics writes data/validation/evaluation.csv, .json and .md.")

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
               "M6-M8 above use the same matching.")

    st.subheader("Services vs reference oracle")
    st.dataframe(pd.DataFrame([{"Comparison": name, **v} for name, v in ev["comparisons"].items()]).fillna(0),
                 hide_index=True, width="stretch")
    st.dataframe(pd.DataFrame(ev["status_at_asof_vs_expected"]), hide_index=True, width="stretch")
    st.caption("AGREE / DISAGREE: the business services and the independent reference calculation, request by "
               "request. Status at as-of: stored workflow status equal to the expected status.")
