"""Database roles (docs/03 section 7.1, amendments E1, F3, F4) and the migration upgrade/downgrade cycle."""
import os

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from tests.conftest import ROOT, apply_test_only_constraints, approved_claim, insert_seed, run_alembic

pytestmark = pytest.mark.db


def _role_url(test_url: str, user_env: str, password_env: str, default_user: str) -> str | None:
    password = os.environ.get(password_env)
    if not password:
        return None
    user = os.environ.get(user_env, default_user)
    # str(URL) masks the password as '***'; render it explicitly so the real password is sent.
    return make_url(test_url).set(username=user, password=password).render_as_string(hide_password=False)


def _connect(url: str):
    return sa.create_engine(url, poolclass=sa.pool.NullPool).connect()


def test_app_role_cannot_read_ground_truth(engine, test_url):
    url = _role_url(test_url, "POSTGRES_APP_USER", "POSTGRES_APP_PASSWORD", "lea_app")
    if not url:
        pytest.skip("POSTGRES_APP_PASSWORD not set")
    with _connect(url) as conn:
        with pytest.raises(DBAPIError) as info:
            conn.execute(sa.text("SELECT count(*) FROM ground_truth.scenario"))
        assert "permission denied" in str(info.value.orig).lower()


def test_app_role_cannot_update_or_delete_audit(engine, test_url):
    url = _role_url(test_url, "POSTGRES_APP_USER", "POSTGRES_APP_PASSWORD", "lea_app")
    if not url:
        pytest.skip("POSTGRES_APP_PASSWORD not set")
    with _connect(url) as conn:
        conn.execute(sa.text("SELECT count(*) FROM ops.audit_event"))  # SELECT allowed
        with pytest.raises(DBAPIError) as info:
            conn.execute(sa.text("DELETE FROM ops.audit_event"))
        assert "permission denied" in str(info.value.orig).lower()


def test_analytics_role_cannot_write_or_read_ground_truth(engine, test_url):
    url = _role_url(test_url, "POSTGRES_ANALYTICS_USER", "POSTGRES_ANALYTICS_PASSWORD", "lea_analytics_ro")
    if not url:
        pytest.skip("POSTGRES_ANALYTICS_PASSWORD not set")
    with _connect(url) as conn:
        for stmt in ("INSERT INTO ops.role (role_id, role_name) VALUES ('ROLE-X', 'X')", "SELECT 1 FROM ground_truth.scenario"):
            with pytest.raises(DBAPIError) as info:
                conn.execute(sa.text(stmt))
            assert "permission denied" in str(info.value.orig).lower()
            conn.rollback()


def test_evaluation_role_reads_both_schemas(engine, test_url):
    url = _role_url(test_url, "POSTGRES_EVALUATION_USER", "POSTGRES_EVALUATION_PASSWORD", "lea_evaluation")
    if not url:
        pytest.skip("POSTGRES_EVALUATION_PASSWORD not set")
    with _connect(url) as conn:
        conn.execute(sa.text("SELECT count(*) FROM ops.employee"))
        conn.execute(sa.text("SELECT count(*) FROM ground_truth.scenario"))
        with pytest.raises(DBAPIError):
            conn.execute(sa.text("INSERT INTO ground_truth.scenario (scenario_id, issue_type, description, planned_count) VALUES ('S99', 'X', 'x', 0)"))


def test_migration_downgrade_and_upgrade_cycle(engine, test_url):
    """Acceptance criterion 1: the schema is executable in both directions. Re-applies test-only constraints after."""
    run_alembic(test_url, "downgrade", "base")
    insp = sa.inspect(engine)
    assert "ops" not in insp.get_schema_names()
    run_alembic(test_url, "upgrade", "head")
    apply_test_only_constraints(engine)
    insp = sa.inspect(engine)
    assert "ops" in insp.get_schema_names() and "ground_truth" in insp.get_schema_names()
    with engine.connect() as conn:
        version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
    assert version == "0002_step_covered_levels"


def _step_columns(engine) -> dict[str, dict]:
    return {c["name"]: c for c in sa.inspect(engine).get_columns("approval_step", schema="ops")}


def _step_checks(engine) -> dict[str, str]:
    return {c["name"]: c["sqltext"] for c in sa.inspect(engine).get_check_constraints("approval_step", schema="ops")}


def test_migration_0002_covered_levels_down_and_up(engine, test_url, tables):
    """0002 alone: downgrade to 0001 removes covered_levels and its CHECKs (0001 is exactly the 0001 schema);
    upgrade adds it back as JSONB NOT NULL with the CHECK names the model declares; a decided step that existed
    before 0002 is backfilled with [required_level] and is still frozen afterwards."""
    from src.models.approvals import COVERED_LEVELS_CHECKS

    names = {f"ck_approval_step_{n}" for n in COVERED_LEVELS_CHECKS}
    try:
        run_alembic(test_url, "downgrade", "0001_initial_schema")
        assert "covered_levels" not in _step_columns(engine)
        assert not names & set(_step_checks(engine))
        with engine.begin() as conn:      # the seed graph and one decided step, created before 0002
            insert_seed(conn, tables)
            approved_claim(conn, tables, covered_levels=None)
        run_alembic(test_url, "upgrade", "0002_step_covered_levels")
        col = _step_columns(engine)["covered_levels"]
        assert not col["nullable"] and col["type"].__class__.__name__ == "JSONB"
        assert names <= set(_step_checks(engine))
        with engine.begin() as conn:
            assert conn.execute(sa.text("SELECT covered_levels FROM ops.approval_step")).scalar_one() == ["L1"]
        with pytest.raises(DBAPIError, match="cannot be modified"), engine.begin() as conn:
            conn.execute(sa.text("UPDATE ops.approval_step SET decision_comment = 'x'"))
    finally:
        run_alembic(test_url, "downgrade", "base")
        run_alembic(test_url, "upgrade", "head")
        apply_test_only_constraints(engine)


def test_sql_files_referenced_by_migration_exist():
    for name in ("triggers.sql", "grants.sql", "test_only_constraints.sql", "init/01_roles.sql", "init/02_test_database.sql"):
        assert (ROOT / "sql" / name).is_file(), name
