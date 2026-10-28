"""approval_step.covered_levels: the levels one approval step covers (Phase 7A; docs/05 5.4, ASM-030, AMB-P3-03).

Revision ID: 0002_step_covered_levels
Revises: 0001_initial_schema

One person resolved for several required levels gets ONE step at the highest level; covered_levels records all of
them, e.g. ["L1", "L2"] when the direct manager is the top of the chain. JSONB NOT NULL with three CHECKs: a
non-empty array, it contains required_level, every element is a level L1..L5. The CHECK text is written out here
(not imported from the model) so this revision never changes; a test compares it with the model.

Upgrade on a database that already has steps: existing rows get [required_level]. Decided steps are frozen by
trg_decided_step_frozen, so that one trigger is disabled for the backfill only and enabled again in the same
transaction. Downgrade drops the CHECKs and the column.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_step_covered_levels"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

TABLE, SCHEMA = "approval_step", "ops"
CHECKS = {
    "ck_approval_step_covered_levels_is_array":
        "jsonb_typeof(covered_levels) = 'array' AND jsonb_array_length(covered_levels) >= 1",
    "ck_approval_step_covered_levels_include_required": "covered_levels @> jsonb_build_array(required_level)",
    "ck_approval_step_covered_levels_enum": "covered_levels <@ jsonb_build_array('L1', 'L2', 'L3', 'L4', 'L5')",
}


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("covered_levels", JSONB(), nullable=True), schema=SCHEMA)
    op.execute("ALTER TABLE ops.approval_step DISABLE TRIGGER trg_decided_step_frozen")
    op.execute("UPDATE ops.approval_step SET covered_levels = jsonb_build_array(required_level)")
    op.execute("ALTER TABLE ops.approval_step ENABLE TRIGGER trg_decided_step_frozen")
    op.alter_column(TABLE, "covered_levels", nullable=False, schema=SCHEMA)
    for name, sql in CHECKS.items():
        op.create_check_constraint(name, TABLE, sql, schema=SCHEMA)


def downgrade() -> None:
    for name in CHECKS:
        op.drop_constraint(name, TABLE, schema=SCHEMA, type_="check")
    op.drop_column(TABLE, "covered_levels", schema=SCHEMA)
