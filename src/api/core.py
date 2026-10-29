"""API plumbing (Phase 9): the application context, transactions, JWT auth with roles from user_role (amendment F2),
and one error format for every failure: {"error": {"code", "message", "details"}}."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable

import bcrypt
import httpx
import jwt
import sqlalchemy as sa
from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.common.clock import Clock, SystemClock
from src.common.config import Settings
from src.repositories.base import run_recording_failure
from src.services.approval_service import DecisionRefused
from src.services.audit_service import SYSTEM
from src.services.exception_service import ExceptionCatalogue
from src.services.expense_service import DetectionParams
from src.services.explanation_service import LlmConfig
from src.services.idempotency import IdempotencyConflict
from src.services.lifecycle import IllegalTransition

JWT_ALGORITHM = "HS256"
READ_ALL_ROLES = frozenset({"APPROVER", "PROCESS_OWNER", "OPS_ANALYST", "SYSTEM_ADMIN"})


@dataclass
class ApiContext:
    settings: Settings
    catalogue: ExceptionCatalogue
    weekend_days: dict[str, list[int]]
    detection: DetectionParams
    llm: LlmConfig
    clock: Clock                                   # request-receipt time (src/common/clock.py: SystemClock)
    engine: sa.Engine | None                       # lea_app (docs/03 7.1)
    evaluation: Callable[[], dict]                 # src/evaluation summary (lea_evaluation)
    http_client: httpx.Client | None = None        # Groq calls; tests pass a mocked transport
    conn: sa.Connection | None = None              # tests: every request runs in this connection (savepoints)
    detections_file: Path | None = None            # data/validation/detections.csv (system detector output)


def get_ctx(request: Request) -> ApiContext:
    return request.app.state.ctx


def run(ctx: ApiContext, operation: str, entity_type: str | None, entity_id: str | None, at, correlation_id,
        work):
    """work(conn) in one transaction; a technical failure is rolled back and recorded (processing_failure)."""
    if ctx.conn is not None:
        with ctx.conn.begin_nested():
            return work(ctx.conn)
    return run_recording_failure(ctx.engine, operation, entity_type, entity_id, at, correlation_id, work)


def read(ctx: ApiContext, work):
    if ctx.conn is not None:
        return work(ctx.conn)
    with ctx.engine.connect() as conn:
        return work(conn)


def correlation(*parts) -> uuid.UUID:
    """Deterministic per call (no random ids): user, operation, target, receipt time, client key."""
    return uuid.uuid5(uuid.NAMESPACE_URL, "|".join(str(p) for p in parts))


def respond(data, status_code: int = 200) -> JSONResponse:
    """Money and quantities as exact strings, times as ISO-8601."""
    return JSONResponse(jsonable_encoder(data, custom_encoder={Decimal: str}), status_code=status_code)


# --- errors -----------------------------------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details=None) -> None:
        super().__init__(message)
        self.status_code, self.code, self.message, self.details = status_code, code, message, details


def error(status_code: int, code: str, message: str, details=None) -> JSONResponse:
    return respond({"error": {"code": code, "message": message, "details": details}}, status_code)


def install_error_handlers(app: FastAPI) -> None:
    def mapped(status_code: int, code: str):
        return lambda request, exc: error(status_code, code, str(exc))

    app.add_exception_handler(ApiError, lambda request, exc: error(exc.status_code, exc.code, exc.message,
                                                                   exc.details))
    app.add_exception_handler(StarletteHTTPException, lambda request, exc: error(
        exc.status_code, "HTTP_" + str(exc.status_code), str(exc.detail)))
    app.add_exception_handler(RequestValidationError, lambda request, exc: error(
        422, "VALIDATION_ERROR", "the request is not valid",
        [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]))
    app.add_exception_handler(IdempotencyConflict, mapped(409, "IDEMPOTENCY_CONFLICT"))
    app.add_exception_handler(DecisionRefused, mapped(409, "DECISION_REFUSED"))
    app.add_exception_handler(IllegalTransition, mapped(409, "ILLEGAL_TRANSITION"))
    app.add_exception_handler(sa.exc.IntegrityError, lambda request, exc: error(
        409, "CONSTRAINT_VIOLATION", "the database rejected the change"))
    app.add_exception_handler(ValueError, mapped(422, "INVALID_INPUT"))
    app.add_exception_handler(Exception, lambda request, exc: error(
        500, "INTERNAL_ERROR", "unexpected error; technical failures are recorded in processing_failure"))


# --- auth -------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    employee_id: str | None
    roles: frozenset[str]

    @property
    def actor(self) -> str:
        """The services' actor: the employee, or SYSTEM for the admin user without an employee (ASM-P8-02)."""
        return self.employee_id or SYSTEM

    def employee(self) -> str:
        if self.employee_id is None:
            raise ApiError(403, "NO_EMPLOYEE", "this user has no employee record")
        return self.employee_id

    @property
    def reads_all(self) -> bool:
        return bool(self.roles & READ_ALL_ROLES)


def password_ok(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:                             # not a bcrypt hash
        return False


def issue_token(settings: Settings, user_id: str, employee_id: str | None, roles: list[str]) -> str:
    """Token lifetime is wall-clock based (SystemClock), unlike business time."""
    now = SystemClock().now()
    payload = {"sub": user_id, "emp": employee_id, "roles": roles, "iat": now,
               "exp": now + timedelta(minutes=settings.jwt_expires_minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                 ctx: ApiContext = Depends(get_ctx)) -> CurrentUser:
    if creds is None:
        raise ApiError(401, "NOT_AUTHENTICATED", "send Authorization: Bearer <token> (POST /auth/login)")
    try:
        p = jwt.decode(creds.credentials, ctx.settings.jwt_secret, algorithms=[JWT_ALGORITHM],
                       options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "TOKEN_EXPIRED", "the token has expired; log in again") from None
    except jwt.InvalidTokenError:
        raise ApiError(401, "INVALID_TOKEN", "the token is not valid") from None
    return CurrentUser(p["sub"], p.get("emp"), frozenset(p.get("roles", [])))


def require(*roles: str):
    """A dependency that admits users holding at least one of `roles`."""
    def dependency(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if not user.roles & set(roles):
            raise ApiError(403, "FORBIDDEN_ROLE", f"requires one of the roles {', '.join(roles)}")
        return user
    return dependency
