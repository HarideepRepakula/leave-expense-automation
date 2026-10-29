"""Evaluator tests (docs/08 section 6), completion pass: the helpers and the anomaly matching on hand-built sets with
known answers, "not measurable" instead of a number when an input is missing, and (lea_dev, skipped when not
reachable) that every metric M1-M18 is either measured or carries a "not measurable: <reason>" note."""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from src.evaluation import metrics as m


def test_helpers():
    assert m.ratio(1, 4) == 0.25 and m.ratio(1, 0) is None
    assert m.f1(1.0, 0.5) == 0.6667 and m.f1(0.0, 0.0) == 0.0 and m.f1(None, 1.0) is None
    assert m.p90([float(i) for i in range(1, 11)]) == 9.0
    assert [m.bucket(d) for d in (0, 2, 3, 14, 15, 31)] == ["0-2", "0-2", "3-7", "8-14", "15-30", ">30"]


def test_anomaly_matching_counts_tp_fp_fn_per_pair():
    labels = [("EXP-1", "MISSING_RECEIPT", True), ("EXP-2", "MISSING_RECEIPT", True),
              ("EXP-3", "PROCESSING_FAILURE", False)]
    detected = {("EXP-1", "MISSING_RECEIPT"), ("EXP-3", "PROCESSING_FAILURE"), ("EXP-9", "MISSING_RECEIPT")}
    m6, m7, m8 = m.anomaly_metrics(detected, labels)
    assert (m6["numerator"], m6["denominator"], m6["value"]) == (2, 3, 0.6667)       # TP 2, FP 1
    assert (m7["numerator"], m7["denominator"], m7["value"]) == (2, 3, 0.6667)       # FN 1 (EXP-2)
    assert m8["value"] == 0.6667
    subsets = {b["value"]: b["result"] for b in m7["breakdown"] if b["key"] == "subset recall"}
    assert subsets == {"planted": 0.5, "natural": 1.0}


def test_missing_inputs_are_not_measurable_not_numbers(tmp_path):
    assert m.reproducibility(tmp_path)["note"].startswith("not measurable:")
    assert all(x["status"] == "not_measurable" and x["value"] is None for x in m.data_quality_metrics(tmp_path))
    assert m.subset_detection("M10", "x", set(), [], {"DUPLICATE_RECEIPT_SELF"}, "")["status"] == "not_measurable"


def test_planted_requests_are_left_out_of_the_data_quality_figure():
    reqs = [{"request_id": f"R{i}", "exception_class": "NONE"} for i in range(4)]
    exc = [{"request_id": "R0", "severity": "HARD", "exception_code": "X", "exception_class": "POLICY_VIOLATION"}]
    m4 = m.compliance(reqs, exc, planted={"R0"})
    assert (m4["numerator"], m4["denominator"]) == (3, 3)                            # headline: planted excluded
    business = next(b for b in m4["breakdown"] if b["value"].startswith("all requests"))
    assert (business["numerator"], business["denominator"]) == (3, 4)


def test_every_metric_is_measured_or_says_why_not_on_the_dev_dataset():
    from src.common.config import get_settings

    s = get_settings()
    if not s.postgres_evaluation_password:
        pytest.skip("POSTGRES_EVALUATION_PASSWORD not set")
    engine = sa.create_engine(s.role_url(s.postgres_evaluation_user, s.postgres_evaluation_password),
                              poolclass=sa.pool.NullPool)
    try:
        result = m.compute(engine)
    except DBAPIError as exc:
        pytest.skip(f"lea_dev not reachable: {exc.orig.__class__.__name__}")
    finally:
        engine.dispose()
    ids = [x["metric_id"] for x in result["metrics"]]
    assert ids == [f"M{i}" for i in range(1, 19)]
    for x in result["metrics"]:
        if x["status"] == "measured":
            assert x["value"] is not None, x["metric_id"]
        else:
            assert x["value"] is None and x["note"].startswith("not measurable: "), x["metric_id"]
    assert "does not predict accuracy on real data" in m.markdown(result)
    assert len(m.csv_rows(result)) > 18
