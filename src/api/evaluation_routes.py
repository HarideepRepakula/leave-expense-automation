"""GET /evaluation (Phase 9): the results of src/evaluation, read through the lea_evaluation role. The ONLY module of
src/api that imports src/evaluation (tests/api/test_api.py checks it); operational routes never read ground truth."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import sqlalchemy as sa
from fastapi import APIRouter, Depends

from src.api.core import ApiContext, CurrentUser, get_ctx, require, respond
from src.evaluation.summary import summarize

router = APIRouter()


def default_evaluation(evaluation_engine: sa.Engine, validation_dir: Path) -> Callable[[], dict]:
    return lambda: summarize(evaluation_engine, validation_dir)


@router.get("/evaluation", tags=["evaluation"],
            summary="Services-vs-oracle comparison counts and status at as-of vs expected (analysts, admins)")
def get_evaluation(user: CurrentUser = Depends(require("OPS_ANALYST", "SYSTEM_ADMIN")),
                   ctx: ApiContext = Depends(get_ctx)):
    return respond(ctx.evaluation())
