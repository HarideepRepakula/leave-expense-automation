"""FastAPI application (Phase 9). Start with:

    uvicorn src.api.main:create_app --factory --port 8000

OpenAPI docs at /docs. Operations use the lea_app role, GET /evaluation the lea_evaluation role (docs/03 7.1).
Simulated authentication only (amendment F2): not production security.
"""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
import yaml
from fastapi import FastAPI

from src.api import evaluation_routes, read_routes, routes
from src.api.core import ApiContext, install_error_handlers
from src.common.clock import SystemClock
from src.common.config import Settings, get_settings
from src.data.config_loader import load_config
from src.services.exception_service import ExceptionCatalogue
from src.services.expense_service import DetectionParams
from src.services.explanation_service import LlmConfig

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"


def llm_config(settings: Settings) -> LlmConfig:
    cfg = yaml.safe_load((CONFIG / "llm.yaml").read_text(encoding="utf-8"))
    return LlmConfig.from_config(cfg, settings.llm_explanations_enabled, settings.groq_api_key, settings.groq_model)


def build_context(settings: Settings | None = None) -> ApiContext:
    settings = settings or get_settings()
    if not settings.jwt_secret:
        raise RuntimeError("JWT_SECRET is empty: set it in .env (see .env.example)")
    cfg = load_config(CONFIG)
    app_engine = sa.create_engine(settings.role_url(settings.postgres_app_user, settings.postgres_app_password),
                                  pool_pre_ping=True)
    evaluation_engine = sa.create_engine(settings.role_url(settings.postgres_evaluation_user,
                                                           settings.postgres_evaluation_password),
                                         pool_pre_ping=True)
    return ApiContext(
        settings=settings, catalogue=ExceptionCatalogue.from_config(cfg["exception_codes"]),
        weekend_days=cfg["calendar"]["weekend_days"], detection=DetectionParams.from_config(cfg["expense_policies"]),
        llm=llm_config(settings), clock=SystemClock(), engine=app_engine,
        evaluation=evaluation_routes.default_evaluation(evaluation_engine, ROOT / "data" / "validation"),
        detections_file=ROOT / "data" / "validation" / "detections.csv")


def create_app(ctx: ApiContext | None = None) -> FastAPI:
    app = FastAPI(title="Leave and Expense Approval API", version="1.0.0",
                  description="Synthetic data only. Errors: {\"error\": {\"code\", \"message\", \"details\"}}. "
                              "Log in at POST /auth/login, then use the token as a Bearer token.")
    app.state.ctx = ctx or build_context()
    install_error_handlers(app)
    app.include_router(routes.router)
    app.include_router(read_routes.router)
    app.include_router(evaluation_routes.router)
    return app
