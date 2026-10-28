"""Load a generated dataset into PostgreSQL (docs/07 section 2 [export], spec section 18).

A load REPLACES the operational data: every ops table is truncated, then the dataset is inserted in
dependency order inside ONE transaction, so a failure leaves the previous contents untouched. It connects
with DATABASE_URL (the schema owner): TRUNCATE is an administrative reset that lea_app may not perform
on append-only tables (DEC-38). ground_truth is never touched here. Refuses any database other than
lea_dev or a *_test database (RK-13).
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine import make_url

from src.data.dataset import TABLE_ORDER, Dataset, table
from src.data.export import insert_order
from src.models.base import Base

ALLOWED_DATABASES = ("lea_dev",)


def check_target(database_url: str) -> str:
    name = make_url(database_url).database or ""
    if name not in ALLOWED_DATABASES and not name.endswith("_test"):
        raise ValueError(f"refusing to load into database '{name}' (allowed: lea_dev or *_test)")
    return name


def _truncate_all(conn: sa.Connection) -> None:
    ops_tables = [t for t in Base.metadata.sorted_tables if t.schema == "ops"]
    conn.execute(sa.text("TRUNCATE " + ", ".join(t.fullname for t in ops_tables) + " CASCADE"))


def load_dataset(dataset: Dataset, database_url: str) -> dict[str, int]:
    check_target(database_url)
    engine = sa.create_engine(database_url, poolclass=sa.pool.NullPool)
    try:
        with engine.begin() as conn:
            _truncate_all(conn)
            for name in TABLE_ORDER:
                tbl = table(name)
                cols = [c.name for c in tbl.columns if c.computed is None]
                rows = [
                    {c: (None if name == "department" and c == "head_employee_id" else r[c]) for c in cols}
                    for r in insert_order(name, dataset[name])
                ]
                if rows:
                    conn.execute(tbl.insert(), rows)
            dept = table("department")
            for d in dataset["department"]:
                conn.execute(dept.update().where(dept.c.department_id == d["department_id"])
                             .values(head_employee_id=d["head_employee_id"]))
            return {name: conn.execute(sa.select(sa.func.count()).select_from(table(name))).scalar_one()
                    for name in TABLE_ORDER}
    finally:
        engine.dispose()


def truncate_ops(database_url: str) -> None:
    """Empty every ops table (tests use it to clean up after loading into lea_test)."""
    check_target(database_url)
    engine = sa.create_engine(database_url, poolclass=sa.pool.NullPool)
    try:
        with engine.begin() as conn:
            _truncate_all(conn)
    finally:
        engine.dispose()
