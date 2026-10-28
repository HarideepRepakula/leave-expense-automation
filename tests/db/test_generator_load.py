"""The generated starter dataset loads into a real PostgreSQL schema: every CHECK (ID formats, enums, date
rules), FK, UNIQUE and trigger accepts it, and the database counts equal the generated counts.
Runs against lea_test and empties the ops tables afterwards so other db tests stay isolated."""
from __future__ import annotations

import pytest
import sqlalchemy as sa

from src.data.dataset import TABLE_ORDER
from src.data.generate import generate
from src.data.loader import check_target, load_dataset, truncate_ops

pytestmark = pytest.mark.db


def test_starter_dataset_loads_with_matching_counts(engine, test_url):
    dataset, _, _ = generate(20261022, employees=40, leave_requests=80, expense_claims=100)
    try:
        counts = load_dataset(dataset, test_url)
        assert counts == {t: len(dataset[t]) for t in TABLE_ORDER}
        with engine.connect() as conn:
            mismatched = conn.execute(sa.text(
                "SELECT count(*) FROM ops.leave_balance WHERE available_balance <> opening_balance + accrued"
            )).scalar_one()
            assert mismatched == 0
            heads = conn.execute(sa.text(
                "SELECT count(*) FROM ops.department WHERE head_employee_id IS NOT NULL")).scalar_one()
            assert heads == 8
    finally:
        truncate_ops(test_url)


def test_loader_refuses_other_databases():
    with pytest.raises(ValueError):
        check_target("postgresql+psycopg://u:p@localhost:5432/postgres")
    assert check_target("postgresql+psycopg://u:p@localhost:5432/lea_dev") == "lea_dev"
