"""Evaluation summary served by GET /evaluation (Phase 9). The only API-reachable code that reads both ops and
ground truth: (1) the AGREE / DISAGREE counts of the two services-vs-oracle comparisons (the CSVs written by
python -m src.evaluation.leave_service_vs_oracle / expense_service_vs_oracle); (2) through the lea_evaluation role
(docs/03 7.1), the expected status at as-of of every ground-truth record against the stored ops status.

Imports nothing from src/reference or src/services: the comparisons are run by their own CLIs, this module only
reads their results. Note: (2) compares the CURRENT ops status, so requests changed through the API after the
dataset load show up as differences; the counts say so.
"""
from __future__ import annotations

import csv
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


def summarize(evaluation_engine: sa.Engine, validation_dir: Path) -> dict:
    return {"comparisons": comparison_counts(validation_dir),
            "status_at_asof_vs_expected": status_vs_expected(evaluation_engine)}
