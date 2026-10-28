"""The generated starter dataset loads into a real PostgreSQL schema: every CHECK (ID formats, enums, date
rules), FK, UNIQUE and trigger accepts it, and the database counts equal the generated counts.
Runs against lea_test and empties the ops tables afterwards so other db tests stay isolated.

lea_test carries a test-only EXCLUDE constraint against overlapping APPROVED leave (amendment A3). The planted
S02 pairs are exactly such rows, so lea_test rejects them (proved below); lea_dev has no such constraint.
To check every other constraint the count test lifts that one constraint for its load and restores it."""
from __future__ import annotations

import pytest
import sqlalchemy as sa

from src.data.dataset import TABLE_ORDER
from src.data.generate import build
from src.data.loader import check_target, load_dataset, truncate_ops
from src.data.stages.ground_truth import load_ground_truth
from tests.conftest import apply_test_only_constraints

pytestmark = pytest.mark.db
EXCLUSION = "excl_no_overlapping_approved_leave"


@pytest.fixture(scope="module")
def starter():
    return build(20261022, employees=40, leave_requests=80, expense_claims=100)


def test_planted_overlaps_are_rejected_by_test_only_constraint(engine, test_url, starter):
    """Amendment A3: the service-layer rule has a DB backstop in lea_test; planted S02 rows trip it."""
    try:
        with pytest.raises(sa.exc.IntegrityError, match=EXCLUSION):
            load_dataset(starter.dataset, test_url)
    finally:
        truncate_ops(test_url)


def test_starter_dataset_loads_with_matching_counts(engine, test_url, starter):
    gen = starter
    dataset = gen.dataset
    with engine.begin() as conn:
        conn.execute(sa.text(f"ALTER TABLE ops.leave_request DROP CONSTRAINT IF EXISTS {EXCLUSION}"))
    try:
        counts = load_dataset(dataset, test_url)
        assert counts == {t: len(dataset[t]) for t in TABLE_ORDER}
        gt_counts = load_ground_truth(gen.truth, test_url)
        assert gt_counts == {t: len(gen.truth.tables[t]) for t in gt_counts}
        with engine.connect() as conn:
            mismatched = conn.execute(sa.text(
                "SELECT count(*) FROM ops.leave_balance b WHERE b.available_balance <> "
                "(SELECT COALESCE(SUM(t.quantity), 0) FROM ops.leave_balance_transaction t "
                " WHERE t.leave_balance_id = b.leave_balance_id)"
            )).scalar_one()
            assert mismatched == 0
            nulls = conn.execute(sa.text(
                "SELECT count(*) FROM ground_truth.record_expectation WHERE expected_route IS NULL")).scalar_one()
            assert nulls == sum(r["expected_route"] is None for r in gen.truth.tables["record_expectation"])
            heads = conn.execute(sa.text(
                "SELECT count(*) FROM ops.department WHERE head_employee_id IS NOT NULL")).scalar_one()
            assert heads == 8
    finally:
        truncate_ops(test_url)
        with engine.begin() as conn:
            conn.execute(sa.text("TRUNCATE ground_truth.record_expectation, ground_truth.anomaly_label, "
                                 "ground_truth.boundary_case, ground_truth.scenario"))
        apply_test_only_constraints(engine)       # restore the A3 constraint for every later test


def test_loader_refuses_other_databases():
    with pytest.raises(ValueError):
        check_target("postgresql+psycopg://u:p@localhost:5432/postgres")
    assert check_target("postgresql+psycopg://u:p@localhost:5432/lea_dev") == "lea_dev"
