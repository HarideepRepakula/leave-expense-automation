"""API test fixtures (Phase 9). The app runs inside the rolled-back lea_test `conn` (every request is a savepoint),
on the world of tests/db/test_approval_steps_db.py: EMP-000002 (IN, INR) reports to EMP-000001; an UNPAID policy;
the configured approval rules; 1 USD = 84.5 INR. Users: USR-000001 = EMP-000001 (APPROVER, PROCESS_OWNER,
OPS_ANALYST); USR-000002 = EMP-000002 (REQUESTER, APPROVER: so a self-approval reaches the service guard).
Synthetic passwords; a test-only JWT secret; no wall clock for business time (a settable clock)."""
from __future__ import annotations

from datetime import datetime, timezone

import bcrypt
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from src.api.core import ApiContext
from src.api.main import create_app
from src.common.config import Settings
from src.services.explanation_service import LlmConfig
from tests.conftest import T0
from tests.db.test_approval_steps_db import CATALOGUE, PARAMS, WEEKEND, world  # noqa: F401

PASSWORD = "synthetic-pw-1"
SUBMIT = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)
DECIDE = datetime(2026, 3, 4, 17, 0, tzinfo=timezone.utc)
ROLES = ("REQUESTER", "APPROVER", "PROCESS_OWNER", "OPS_ANALYST", "SYSTEM_ADMIN")


class SetClock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at

    def today(self):
        return self.at.date()


def llm(enabled: bool = False, key: str = "") -> LlmConfig:
    return LlmConfig(enabled, key, "openai/gpt-oss-20b", "https://api.groq.test/openai/v1/chat/completions",
                     5.0, 1, 1024, 0.0)


@pytest.fixture()
def users(conn, world):  # noqa: F811
    t = world
    pw = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(4)).decode()
    have = set(conn.execute(sa.select(t["ops.role"].c.role_name)).scalars())
    conn.execute(sa.insert(t["ops.role"]), [{"role_id": f"ROLE-{r}", "role_name": r, "description": r}
                                            for r in ROLES if r not in have])
    u = t["ops.application_user"]
    conn.execute(sa.update(u).where(u.c.user_id == "USR-000002").values(password_hash=pw))
    conn.execute(sa.insert(u).values(user_id="USR-000001", username="emp000001", password_hash=pw,
                                     employee_id="EMP-000001", is_active=True, created_at=T0))
    conn.execute(sa.insert(t["ops.user_role"]), [
        {"user_id": "USR-000001", "role_id": "ROLE-APPROVER"}, {"user_id": "USR-000001", "role_id": "ROLE-PROCESS_OWNER"},
        {"user_id": "USR-000001", "role_id": "ROLE-OPS_ANALYST"}, {"user_id": "USR-000002", "role_id": "ROLE-REQUESTER"},
        {"user_id": "USR-000002", "role_id": "ROLE-APPROVER"}])
    return t


@pytest.fixture()
def ctx(conn, users) -> ApiContext:
    settings = Settings(JWT_SECRET="test-only-secret-not-used-anywhere-else-0123456789", JWT_EXPIRES_MINUTES=5)
    return ApiContext(settings=settings, catalogue=CATALOGUE, weekend_days=WEEKEND, detection=PARAMS, llm=llm(),
                      clock=SetClock(SUBMIT), engine=None, evaluation=lambda: {}, conn=conn)


@pytest.fixture()
def client(ctx) -> TestClient:
    return TestClient(create_app(ctx))


def login(client: TestClient, username: str) -> dict:
    r = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def requester(client) -> dict:
    return login(client, "emp000002")


@pytest.fixture()
def manager(client) -> dict:
    return login(client, "emp000001")
