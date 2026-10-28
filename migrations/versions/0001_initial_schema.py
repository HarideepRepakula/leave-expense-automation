"""Initial schema: ops and ground_truth schemas, all tables, triggers and grants.

Revision ID: 0001_initial_schema
Revises: None

Design decision DEC-30 (Phase 2): this first migration builds the tables from the SQLAlchemy metadata
(create_all) so the models are the single source of truth, then applies sql/triggers.sql and
sql/grants.sql. Later migrations are written with explicit Alembic operations (autogenerate diff).
Because create_all builds the CURRENT models, columns that a later revision adds are dropped again at the end of
this revision (LATER_COLUMNS, DEC-P7A-02), so the schema at 0001 is exactly the 0001 schema and every later
revision can be upgraded and downgraded on its own.
Downgrade drops both schemas, which removes every table, trigger and function they contain.
"""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import op

from src.models import Base, GroundTruthBase

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

REQUIRED_ROLES = ("lea_app", "lea_analytics_ro", "lea_evaluation")
SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
# (schema, table, column) added by a later revision; dropped here with the CHECKs that reference them.
LATER_COLUMNS = [("ops", "approval_step", "covered_levels")]   # 0002_step_covered_levels


def _execute_sql_file(bind: sa.engine.Connection, filename: str) -> None:
    """Run a multi-statement SQL file through the raw psycopg connection (no parameter parsing, so
    PL/pgSQL '%I' format strings and $$ bodies pass through untouched)."""
    sql = (SQL_DIR / filename).read_text(encoding="utf-8")
    dbapi_connection = bind.connection.dbapi_connection
    dbapi_connection.execute(sql)


def upgrade() -> None:
    bind = op.get_bind()

    missing = [
        role
        for role in REQUIRED_ROLES
        if bind.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar() is None
    ]
    if missing:
        raise RuntimeError(
            f"Database roles missing: {missing}. Create them first: with Docker they come from "
            "sql/init/01_roles.sql on first start; without Docker run scripts/init_local_db.ps1."
        )

    bind.execute(sa.text("CREATE SCHEMA IF NOT EXISTS ops"))
    bind.execute(sa.text("CREATE SCHEMA IF NOT EXISTS ground_truth"))

    Base.metadata.create_all(bind)
    GroundTruthBase.metadata.create_all(bind)
    for schema, table, column in LATER_COLUMNS:
        op.drop_column(table, column, schema=schema)

    _execute_sql_file(bind, "triggers.sql")
    _execute_sql_file(bind, "grants.sql")


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DROP SCHEMA IF EXISTS ground_truth CASCADE"))
    bind.execute(sa.text("DROP SCHEMA IF EXISTS ops CASCADE"))
