"""Dashboard data access (Phase 10; docs/03 sections 3 and 7.1, amendment F3). Two read paths, nothing else:

- the API with the user's JWT: login, a request with its history, the explanation, the detections, the evaluation;
- the read-only analytics views ops.v_request, ops.v_request_exception, ops.v_reimbursement as lea_analytics_ro.

Nothing here writes. The dashboard never connects as lea_app or lea_evaluation. Tests set `api` (an in-process
TestClient) and `analytics` (an engine) before running the app.
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pandas as pd
import sqlalchemy as sa
import yaml

from src.common.config import get_settings

ROOT = Path(__file__).resolve().parents[2]
API_URL = os.environ.get("DASHBOARD_API_URL", "http://127.0.0.1:8000")
VIEWS = {"requests": "ops.v_request", "exceptions": "ops.v_request_exception",
         "reimbursements": "ops.v_reimbursement",
         # migration 0004 (completion pass)
         "employees": "ops.v_employee", "dimensions": "ops.v_request_dimension", "lines": "ops.v_expense_line",
         "steps": "ops.v_approval_step", "approval_attempts": "ops.v_approval_attempt",
         "reimbursement_attempts": "ops.v_reimbursement_attempt", "failures": "ops.v_processing_failure"}
ANALYST_ROLES = {"PROCESS_OWNER", "OPS_ANALYST", "SYSTEM_ADMIN"}

api: httpx.Client | None = None
analytics: sa.Engine | None = None


class DashboardError(Exception):
    """An API call failed; the message is shown to the user as is."""


def _api() -> httpx.Client:
    global api
    if api is None:
        api = httpx.Client(base_url=API_URL, timeout=60.0)
    return api


def _analytics() -> sa.Engine:
    global analytics
    if analytics is None:
        s = get_settings()
        analytics = sa.create_engine(s.role_url(s.postgres_analytics_user, s.postgres_analytics_password),
                                     pool_pre_ping=True)
    return analytics


def _check(r: httpx.Response, what: str) -> dict:
    if r.status_code != 200:
        try:
            err = r.json()["error"]
            detail = f"{err['code']}: {err['message']}"
        except (ValueError, KeyError, TypeError):
            detail = r.text[:200]
        raise DashboardError(f"{what} failed ({r.status_code}) - {detail}")
    return r.json()


def login(username: str, password: str) -> dict:
    """POST /auth/login; returns the token and roles."""
    try:
        r = _api().post("/auth/login", json={"username": username, "password": password})
    except httpx.HTTPError as exc:
        raise DashboardError(f"cannot reach the API at {API_URL} ({exc.__class__.__name__}); is it running?")
    return _check(r, "Login")


def get(token: str, path: str) -> dict:
    try:
        r = _api().get(path, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise DashboardError(f"cannot reach the API at {API_URL} ({exc.__class__.__name__}); is it running?")
    return _check(r, f"GET {path}")


def frame(view: str) -> pd.DataFrame:
    """All rows of one analytics view (a few thousand at most, amendment F6)."""
    with _analytics().connect() as conn:
        return pd.read_sql(sa.text(f"SELECT * FROM {VIEWS[view]}"), conn)


def as_of() -> date:
    """The dataset as-of date (config/generation.yaml), used for ages; the data are synthetic and end there."""
    cfg = yaml.safe_load((ROOT / "config" / "generation.yaml").read_text(encoding="utf-8"))
    value = cfg["as_of_date"]
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def money(values) -> Decimal:
    """Exact sum of a column of Decimals (NULLs skipped)."""
    return sum((Decimal(v) for v in values if v is not None and not pd.isna(v)), Decimal("0"))
