"""Dashboard tests (Phase 10).

1. Isolation (no database): the dashboard imports nothing from src/reference, src/evaluation, src/services,
   src/repositories or the models; no string names the evaluation schema; only evaluation_view.py calls
   /evaluation, and it opens no database connection and no file.
2. Analytics role (lea_test): lea_analytics_ro reads the three views and nothing else; lea_app cannot write through
   them.
3. Smoke (lea_dev, read-only): AppTest logs in through the in-process API as a synthetic analyst and renders every
   view without an exception. Logging in and GET routes write nothing. LLM explanations are forced off (template).
   Skips when lea_dev, migration 0003 or the passwords are not available.
"""
from __future__ import annotations

import ast
import csv
import dataclasses

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from tests.conftest import ROOT
from tests.db.test_roles_and_migration_cycle import _connect, _role_url

DASHBOARD = ROOT / "src" / "dashboard"
APP = DASHBOARD / "app.py"
FORBIDDEN_IMPORTS = ("src.reference", "src.evaluation", "src.services", "src.repositories", "src.models")
VIEWS = ("Overview", "Requests", "Exceptions", "Evaluation")
ANALYST = "USR-000010"                             # REQUESTER;OPS_ANALYST in the dev dataset


# --- 1. isolation -----------------------------------------------------------------------------------------------

def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports(tree) -> set[str]:
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    return mods


def _strings(tree) -> list[str]:
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_dashboard_imports_no_reference_evaluation_or_service_code():
    files = sorted(DASHBOARD.glob("*.py"))
    assert APP in files and len(files) >= 5
    bad = [f"{p.name}: {m}" for p in files for m in _imports(_tree(p)) if m.startswith(FORBIDDEN_IMPORTS)]
    assert not bad, bad


def test_only_the_evaluation_view_reaches_evaluation_data():
    for path in sorted(DASHBOARD.glob("*.py")):
        strings = _strings(_tree(path))
        assert not any("ground_truth" in s for s in strings), path.name
        calls_evaluation = any(s == "/evaluation" for s in strings)
        assert calls_evaluation == (path.name == "evaluation_view.py"), path.name
    ev = _tree(DASHBOARD / "evaluation_view.py")
    assert _imports(ev) <= {"__future__", "pandas", "streamlit", "src.dashboard"}
    names = {n.attr for n in ast.walk(ev) if isinstance(n, ast.Attribute)} | \
            {n.id for n in ast.walk(ev) if isinstance(n, ast.Name)}
    assert not names & {"frame", "open", "read_sql", "connect", "analytics", "Path"}


# --- 2. analytics role on lea_test ------------------------------------------------------------------------------

@pytest.mark.db
def test_analytics_role_reads_the_views_only(engine, test_url):
    url = _role_url(test_url, "POSTGRES_ANALYTICS_USER", "POSTGRES_ANALYTICS_PASSWORD", "lea_analytics_ro")
    if not url:
        pytest.skip("POSTGRES_ANALYTICS_PASSWORD not set")
    with _connect(url) as conn:
        for view in ("v_request", "v_request_exception", "v_reimbursement"):
            conn.execute(sa.text(f"SELECT count(*) FROM ops.{view}"))
        for stmt in ("SELECT 1 FROM ops.leave_request", "SELECT 1 FROM ops.request_exception",
                     "SELECT 1 FROM ground_truth.anomaly_label",
                     "DELETE FROM ops.v_reimbursement"):
            with pytest.raises(DBAPIError) as info:
                conn.execute(sa.text(stmt))
            assert "permission denied" in str(info.value.orig).lower(), stmt
            conn.rollback()


@pytest.mark.db
def test_app_role_cannot_write_through_the_views(engine, test_url):
    url = _role_url(test_url, "POSTGRES_APP_USER", "POSTGRES_APP_PASSWORD", "lea_app")
    if not url:
        pytest.skip("POSTGRES_APP_PASSWORD not set")
    with _connect(url) as conn:
        with pytest.raises(DBAPIError) as info:
            conn.execute(sa.text("UPDATE ops.v_reimbursement SET currency = currency"))
        assert "permission denied" in str(info.value.orig).lower()


# --- 3. smoke test on lea_dev -----------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def dev_dashboard():
    """The real API context on lea_dev (lea_app / lea_evaluation) in-process, and the analytics engine."""
    from fastapi.testclient import TestClient

    from src.api.main import build_context, create_app
    from src.common.config import get_settings
    from src.dashboard import client

    settings = get_settings()
    if not (settings.jwt_secret and settings.postgres_analytics_password and settings.postgres_app_password):
        pytest.skip("JWT_SECRET or role passwords not set in .env")
    creds = ROOT / "data" / "processed" / "dev_credentials.csv"
    if not creds.exists():
        pytest.skip("data/processed/dev_credentials.csv not generated")
    with creds.open(encoding="utf-8", newline="") as fh:
        user = next(r for r in csv.DictReader(fh) if r["user_id"] == ANALYST)
    analytics = sa.create_engine(settings.role_url(settings.postgres_analytics_user,
                                                   settings.postgres_analytics_password), poolclass=sa.pool.NullPool)
    try:
        with analytics.connect() as conn:
            conn.execute(sa.text("SELECT 1 FROM ops.v_request LIMIT 1"))
    except DBAPIError as exc:
        pytest.skip(f"lea_dev analytics views not reachable (alembic upgrade head?): {exc.orig.__class__.__name__}")
    ctx = build_context(settings)
    ctx.llm = dataclasses.replace(ctx.llm, enabled=False)        # never call Groq from tests
    client.api, client.analytics = TestClient(create_app(ctx)), analytics
    yield user
    client.api, client.analytics = None, None
    analytics.dispose()


def _logged_in(user):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=120).run()
    assert not at.exception
    at.text_input[0].input(user["username"])
    at.text_input[1].input(user["password"])
    at.button[0].click().run()
    assert not at.exception, at.exception
    assert "auth" in at.session_state
    return at


def test_every_view_renders_on_the_dev_dataset(dev_dashboard):
    at = _logged_in(dev_dashboard)
    for view in VIEWS:
        at.sidebar.radio[0].set_value(view).run()
        assert not at.exception, (view, at.exception)
        assert not at.error, (view, [e.value for e in at.error])
        assert [h.value for h in at.header] == [view]
    # the Requests detail panel: explanation with its source, and the history tables
    at.sidebar.radio[0].set_value("Requests").run()
    captions = " ".join(c.value for c in at.caption)
    assert "Source: template" in captions
    assert {"**Approval steps**", "**Status history**", "**Exception codes**"} <= {m.value for m in at.markdown}


def test_wrong_password_shows_an_error_and_no_session(dev_dashboard):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=60).run()
    at.text_input[0].input(dev_dashboard["username"])
    at.text_input[1].input("wrong-password-for-the-test")
    at.button[0].click().run()
    assert not at.exception
    assert "auth" not in at.session_state
    assert any("INVALID_CREDENTIALS" in e.value for e in at.error)
