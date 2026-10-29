"""Evaluation summary served by GET /evaluation (Phase 9). The only API-reachable code that reads both ops and
ground truth: (1) the AGREE / DISAGREE counts of the two services-vs-oracle comparisons (the CSVs written by
python -m src.evaluation.leave_service_vs_oracle / expense_service_vs_oracle); (2) through the lea_evaluation role
(docs/03 7.1), the expected status at as-of of every ground-truth record against the stored ops status;
(3, Phase 10) M1-M3 as written by python -m src.validation (validation_report.json); (4, Phase 10) detection results
over the matching unit of docs/08 section 2: a detection is (record_id, code) from ops.request_exception
(any round), detections.csv, a BLOCKED DUPLICATE_REIMBURSEMENT attempt or a reimbursement processing_failure
(docs/08 section 1); a positive is an anomaly_label with expected_detection = DETECT. TP / FP / FN per issue type
and overall, with precision and recall (a preliminary view of M6-M8; the full report is Phase 11).

Imports nothing from src/reference or src/services: the comparisons are run by their own CLIs, this module only
reads their results. Note: (2) compares the CURRENT ops status, so requests changed through the API after the
dataset load show up as differences; the counts say so.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import sqlalchemy as sa

COMPARISONS = {"leave_service_vs_oracle": "leave_service_vs_oracle.csv",
               "expense_service_vs_oracle": "expense_service_vs_oracle.csv"}

STATUS_VS_EXPECTED = sa.text("""
    SELECT x.record_type, count(*) AS records,
           count(*) FILTER (WHERE coalesce(l.workflow_status, e.workflow_status) = x.expected_final_status_at_asof)
               AS matching
    FROM ground_truth.record_expectation x
    LEFT JOIN ops.leave_request l ON x.record_type = 'LEAVE' AND l.leave_request_id = x.record_id
    LEFT JOIN ops.expense_claim e ON x.record_type = 'EXPENSE' AND e.expense_claim_id = x.record_id
    GROUP BY x.record_type ORDER BY x.record_type""")


DETECTIONS_IN_DB = sa.text("""
    SELECT DISTINCT coalesce(leave_request_id, expense_claim_id) AS record_id, exception_code
    FROM ops.request_exception
    UNION
    SELECT expense_claim_id, 'DUPLICATE_REIMBURSEMENT_ATTEMPT' FROM ops.reimbursement_attempt
    WHERE outcome = 'BLOCKED' AND reason_code = 'DUPLICATE_REIMBURSEMENT'
    UNION
    SELECT r.expense_claim_id, 'PROCESSING_FAILURE' FROM ops.processing_failure f
    JOIN ops.reimbursement r ON f.entity_type = 'reimbursement' AND r.reimbursement_id = f.entity_id""")
POSITIVES = sa.text("""
    SELECT DISTINCT affected_record_id, issue_type FROM ground_truth.anomaly_label WHERE expected_detection = 'DETECT'""")


def comparison_counts(validation_dir: Path) -> dict:
    out = {}
    for name, file in COMPARISONS.items():
        path = validation_dir / file
        if not path.exists():
            out[name] = {"available": False}
            continue
        with path.open(encoding="utf-8", newline="") as fh:
            results = Counter(row["result"] for row in csv.DictReader(fh))
        out[name] = {"available": True, "records": sum(results.values()), **dict(sorted(results.items()))}
    return out


def status_vs_expected(evaluation_engine: sa.Engine) -> list[dict]:
    with evaluation_engine.connect() as conn:
        return [dict(r) for r in conn.execute(STATUS_VS_EXPECTED).mappings()]


def data_quality(validation_dir: Path) -> dict:
    path = validation_dir / "validation_report.json"
    if not path.exists():
        return {"available": False}
    return {"available": True, **json.loads(path.read_text(encoding="utf-8"))["metrics"]}


def _ratio(num: int, den: int) -> float | None:
    return None if den == 0 else round(num / den, 4)


def _scores(tp: int, fp: int, fn: int) -> dict:
    return {"tp": tp, "fp": fp, "fn": fn, "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn)}


def detection_results(evaluation_engine: sa.Engine, validation_dir: Path) -> dict:
    with evaluation_engine.connect() as conn:
        detected = {(r, c) for r, c in conn.execute(DETECTIONS_IN_DB)}
        positives = {(r, c) for r, c in conn.execute(POSITIVES)}
    path = validation_dir / "detections.csv"
    if path.exists():
        with path.open(encoding="utf-8", newline="") as fh:
            detected |= {(row["record_id"], row["exception_code"]) for row in csv.DictReader(fh)}
    by_code = []
    for code in sorted({c for _, c in detected | positives}):
        d, p = {x for x in detected if x[1] == code}, {x for x in positives if x[1] == code}
        by_code.append({"code": code, **_scores(len(d & p), len(d - p), len(p - d))})
    return {"overall": _scores(len(detected & positives), len(detected - positives), len(positives - detected)),
            "by_code": by_code}


def summarize(evaluation_engine: sa.Engine, validation_dir: Path) -> dict:
    return {"comparisons": comparison_counts(validation_dir),
            "status_at_asof_vs_expected": status_vs_expected(evaluation_engine),
            "data_quality": data_quality(validation_dir),
            "detection": detection_results(evaluation_engine, validation_dir)}
