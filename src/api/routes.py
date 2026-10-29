"""Operational routes (Phase 9). Every route needs a JWT; state changes go through src/services in one lea_app
transaction. These routes never read ground truth (only evaluation_routes reaches src/evaluation).

Workflow status, exception class, technical status (processing_failure) and audit/attempt history stay separate
fields in every response, as stored."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field

from src.api.core import (ApiContext, ApiError, CurrentUser, correlation, current_user, get_ctx, issue_token,
                          password_ok, read, require, respond, run)
from src.repositories import read_repository as rr
from src.repositories.base import allocate_year_ids, table
from src.repositories.expense_repository import SqlExpenseStore
from src.repositories.leave_repository import SqlLeaveStore
from src.services.approval_service import decide_escalated, decide_step
from src.services.expense_service import submit_expense
from src.services.explanation_service import explain, facts_of
from src.services.idempotency import sha256_hex
from src.services.leave_request_service import submit_leave
from src.services.reimbursement_service import create_reimbursement

router = APIRouter()
IdempotencyKey = Header(..., alias="Idempotency-Key", min_length=8, max_length=200,
                        description="Client key; a repeat with the same body replays, another body is a 409")
GUARD_403 = {"SELF_APPROVAL", "UNAUTHORIZED_APPROVER"}


# --- schemas ----------------------------------------------------------------------------------------------------

class LoginIn(BaseModel):
    username: str
    password: str


class LeaveIn(BaseModel):
    leave_policy_id: str
    start_date: date
    end_date: date
    start_half_day: bool = False
    end_half_day: bool = False


class LineIn(BaseModel):
    category: str
    merchant_description: str = Field(min_length=1, max_length=200)
    expense_date: date
    line_amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit_amount: Decimal | None = Field(default=None, gt=0)


class ExpenseIn(BaseModel):
    lines: list[LineIn] = Field(min_length=1, max_length=50)
    cost_center_id: str | None = None          # default: the employee's default cost center


class DecisionIn(BaseModel):
    action: Literal["APPROVE", "REJECT", "RETURN"]
    reason_code: str | None = None
    comment: str | None = Field(default=None, max_length=1000)


class ReimbursementIn(BaseModel):
    expense_claim_id: str
    amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


# --- helpers ----------------------------------------------------------------------------------------------------

def _kind(request_id: str) -> str:
    kind = rr.kind_of(request_id)
    if kind is None:
        raise ApiError(404, "NOT_FOUND", f"unknown request {request_id}")
    return kind


def _store(ctx: ApiContext, conn: sa.Connection, kind: str):
    return SqlLeaveStore(conn, ctx.weekend_days) if kind == "LEAVE" else SqlExpenseStore(conn, ctx.detection)


def _detail(conn: sa.Connection, kind: str, request_id: str, user: CurrentUser) -> dict:
    """The request with its history; requesters see only their own (404 for others, so ids do not leak)."""
    d = rr.get_request(conn, kind, request_id)
    if d is None or (not user.reads_all and d["request"]["employee_id"] != user.employee_id):
        raise ApiError(404, "NOT_FOUND", f"unknown request {request_id}")
    return d


def _decision_body(res, request_id: str, status: str) -> dict:
    body = {"request_id": request_id, "outcome": res.outcome, "reason_code": res.reason_code,
            "replayed": res.replayed, "workflow_status": status}
    if res.outcome == "BLOCKED":                  # the attempt is committed; the caller still gets an error
        raise ApiError(403 if res.reason_code in GUARD_403 else 409, res.reason_code,
                       f"decision blocked ({res.reason_code}); the attempt is recorded", body)
    return body


# --- auth -------------------------------------------------------------------------------------------------------

@router.post("/auth/login", tags=["auth"], summary="Log in with a synthetic dev user; returns a JWT")
def login(body: LoginIn, ctx: ApiContext = Depends(get_ctx)):
    found = read(ctx, lambda conn: rr.login_row(conn, body.username))
    if found is None or not found[0]["is_active"] or not password_ok(body.password, found[0]["password_hash"]):
        raise ApiError(401, "INVALID_CREDENTIALS", "unknown user, inactive user or wrong password")
    user, roles = found
    return {"access_token": issue_token(ctx.settings, user["user_id"], user["employee_id"], roles),
            "token_type": "bearer", "user_id": user["user_id"], "employee_id": user["employee_id"], "roles": roles,
            "expires_in_minutes": ctx.settings.jwt_expires_minutes}


@router.get("/auth/me", tags=["auth"])
def me(user: CurrentUser = Depends(current_user)):
    return {"user_id": user.user_id, "employee_id": user.employee_id, "roles": sorted(user.roles)}


# --- submissions ------------------------------------------------------------------------------------------------

@router.post("/leave-requests", tags=["leave"], status_code=201, summary="Create and submit a leave request")
def submit_leave_request(body: LeaveIn, user: CurrentUser = Depends(require("REQUESTER")),
                         ctx: ApiContext = Depends(get_ctx)):
    emp, at = user.employee(), ctx.clock.now()
    corr = correlation(user.user_id, "SUBMIT_LEAVE", body.model_dump_json(), at.isoformat())

    def work(conn):
        lp = table("leave_policy")
        if conn.execute(sa.select(lp.c.leave_policy_id).where(lp.c.leave_policy_id == body.leave_policy_id)) \
                .scalar_one_or_none() is None:
            raise ApiError(422, "UNKNOWN_POLICY", f"unknown leave policy {body.leave_policy_id}")
        rid = allocate_year_ids(conn, "leave_request", "LVE", at.year, 1)[0]
        conn.execute(sa.insert(table("leave_request")).values(
            leave_request_id=rid, employee_id=emp, first_submitted_at=None, current_round=1,
            business_day_count=Decimal("0"), requested_quantity=Decimal("0"), workflow_status="DRAFT",
            exception_class="NONE", medical_cert_flag=False, created_at=at, **body.model_dump()))
        submit_leave(SqlLeaveStore(conn, ctx.weekend_days), rid, ctx.catalogue, at, emp, corr)
        return rr.get_request(conn, "LEAVE", rid)
    return respond(run(ctx, "SUBMIT_LEAVE", "leave_request", None, at, corr, work), 201)


@router.post("/expense-claims", tags=["expense"], status_code=201, summary="Create and submit an expense claim")
def submit_expense_claim(body: ExpenseIn, user: CurrentUser = Depends(require("REQUESTER")),
                         ctx: ApiContext = Depends(get_ctx)):
    emp_id, at = user.employee(), ctx.clock.now()
    corr = correlation(user.user_id, "SUBMIT_EXPENSE", body.model_dump_json(), at.isoformat())

    def work(conn):
        emp = rr.employee(conn, emp_id)
        dates = [ln.expense_date for ln in body.lines]
        cid = allocate_year_ids(conn, "expense_claim", "EXP", at.year, 1)[0]
        conn.execute(sa.insert(table("expense_claim")).values(
            expense_claim_id=cid, employee_id=emp_id, first_submitted_at=None, claim_period_start=min(dates),
            claim_period_end=max(dates), country=emp["country"], currency=emp["currency"],
            cost_center_id=body.cost_center_id or emp["default_cost_center_id"], expense_policy_id=None,
            total_amount=sum(ln.line_amount for ln in body.lines), workflow_status="DRAFT", exception_class="NONE",
            receipt_status="NOT_REQUIRED", current_round=1, created_at=at))
        conn.execute(sa.insert(table("expense_line")), [
            {"expense_line_id": f"EXPL-{cid}-{i:02d}", "expense_claim_id": cid, "line_number": i,
             "submission_round": 1, "currency": emp["currency"], "receipt_id": None, "validation_result": "PENDING",
             **ln.model_dump()} for i, ln in enumerate(body.lines, start=1)])
        submit_expense(SqlExpenseStore(conn, ctx.detection), cid, ctx.catalogue, at, emp_id, corr)
        return rr.get_request(conn, "EXPENSE", cid)
    return respond(run(ctx, "SUBMIT_EXPENSE", "expense_claim", None, at, corr, work), 201)


# --- decisions --------------------------------------------------------------------------------------------------

@router.post("/requests/{request_id}/steps/{step_id}/decision", tags=["approvals"],
             summary="Approve, reject or return one approval step (idempotent)")
def decide_on_step(request_id: str, step_id: str, body: DecisionIn, idempotency_key: str = IdempotencyKey,
                   user: CurrentUser = Depends(require("APPROVER", "PROCESS_OWNER")),
                   ctx: ApiContext = Depends(get_ctx)):
    kind, at = _kind(request_id), ctx.clock.now()
    key = sha256_hex("api", idempotency_key)
    corr = correlation(user.user_id, "DECIDE_STEP", step_id, at.isoformat(), key)

    def work(conn):
        d = rr.get_request(conn, kind, request_id)
        if d is None or step_id not in {s["approval_step_id"] for s in d["steps"]}:
            raise ApiError(404, "NOT_FOUND", f"unknown request {request_id} or step {step_id}")
        res = decide_step(_store(ctx, conn, kind), request_id, step_id, user.actor, body.action, at, corr, key,
                          body.reason_code, body.comment)
        return res, rr.get_request(conn, kind, request_id)["request"]["workflow_status"]
    res, status = run(ctx, "DECIDE_STEP", "approval_step", step_id, at, corr, work)
    return respond(_decision_body(res, request_id, status))


@router.post("/requests/{request_id}/escalation-decision", tags=["approvals"],
             summary="Process-owner decision on an ESCALATED_FOR_REVIEW request (idempotent)")
def decide_on_escalation(request_id: str, body: DecisionIn, idempotency_key: str = IdempotencyKey,
                         user: CurrentUser = Depends(require("PROCESS_OWNER", "APPROVER")),
                         ctx: ApiContext = Depends(get_ctx)):
    kind, at = _kind(request_id), ctx.clock.now()
    key = sha256_hex("api", idempotency_key)
    corr = correlation(user.user_id, "DECIDE_ESCALATED", request_id, at.isoformat(), key)

    def work(conn):
        if rr.get_request(conn, kind, request_id) is None:
            raise ApiError(404, "NOT_FOUND", f"unknown request {request_id}")
        res = decide_escalated(_store(ctx, conn, kind), request_id, user.actor, body.action, at, corr, key,
                               body.reason_code, body.comment)
        return res, rr.get_request(conn, kind, request_id)["request"]["workflow_status"]
    res, status = run(ctx, "DECIDE_ESCALATED", kind.lower(), request_id, at, corr, work)
    return respond(_decision_body(res, request_id, status))


# --- reimbursements ---------------------------------------------------------------------------------------------

@router.post("/reimbursements", tags=["reimbursements"], summary="Create a reimbursement for an approved claim")
def create_reimbursement_route(body: ReimbursementIn, idempotency_key: str = IdempotencyKey,
                               user: CurrentUser = Depends(require("OPS_ANALYST", "PROCESS_OWNER", "SYSTEM_ADMIN")),
                               ctx: ApiContext = Depends(get_ctx)):
    at, key = ctx.clock.now(), sha256_hex("api", idempotency_key)
    corr = correlation(user.user_id, "CREATE_REIMBURSEMENT", body.expense_claim_id, at.isoformat(), key)

    def work(conn):
        if rr.get_request(conn, "EXPENSE", body.expense_claim_id) is None:
            raise ApiError(404, "NOT_FOUND", f"unknown expense claim {body.expense_claim_id}")
        res = create_reimbursement(SqlExpenseStore(conn, ctx.detection), body.expense_claim_id, user.actor, at,
                                   corr, body.amount, body.currency, key)
        return res, rr.get_reimbursement(conn, res.reimbursement_id) if res.reimbursement_id else None
    res, detail = run(ctx, "CREATE_REIMBURSEMENT", "expense_claim", body.expense_claim_id, at, corr, work)
    out = {"expense_claim_id": body.expense_claim_id, "outcome": res.outcome, "reason_code": res.reason_code,
           "replayed": res.replayed, "reimbursement_id": res.reimbursement_id, "detail": detail}
    if res.outcome == "BLOCKED":
        raise ApiError(409, res.reason_code, f"reimbursement blocked ({res.reason_code}); the attempt is recorded",
                       out)
    return respond(out, 200 if res.replayed else 201)


@router.get("/reimbursements/{reimbursement_id}", tags=["reimbursements"])
def get_reimbursement(reimbursement_id: str, user: CurrentUser = Depends(current_user),
                      ctx: ApiContext = Depends(get_ctx)):
    def work(conn):
        d = rr.get_reimbursement(conn, reimbursement_id)
        if d is None:
            raise ApiError(404, "NOT_FOUND", f"unknown reimbursement {reimbursement_id}")
        _detail(conn, "EXPENSE", d["reimbursement"]["expense_claim_id"], user)       # access check (404)
        return d
    return respond(read(ctx, work))


# --- reads ------------------------------------------------------------------------------------------------------

def _list(kind: str, user: CurrentUser, ctx: ApiContext, limit: int, offset: int):
    owner = None if user.reads_all else user.employee()
    rows = read(ctx, lambda conn: rr.list_requests(conn, kind, owner, limit, offset))
    return respond({"items": rows, "limit": limit, "offset": offset})


@router.get("/leave-requests", tags=["leave"])
def list_leave_requests(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                        user: CurrentUser = Depends(current_user), ctx: ApiContext = Depends(get_ctx)):
    return _list("LEAVE", user, ctx, limit, offset)


@router.get("/leave-requests/{request_id}", tags=["leave"], summary="A leave request with steps and status history")
def get_leave_request(request_id: str, user: CurrentUser = Depends(current_user), ctx: ApiContext = Depends(get_ctx)):
    if rr.kind_of(request_id) != "LEAVE":
        raise ApiError(404, "NOT_FOUND", f"unknown leave request {request_id}")
    return respond(read(ctx, lambda conn: _detail(conn, "LEAVE", request_id, user)))


@router.get("/expense-claims", tags=["expense"])
def list_expense_claims(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                        user: CurrentUser = Depends(current_user), ctx: ApiContext = Depends(get_ctx)):
    return _list("EXPENSE", user, ctx, limit, offset)


@router.get("/expense-claims/{request_id}", tags=["expense"],
            summary="An expense claim with lines, steps and status history")
def get_expense_claim(request_id: str, user: CurrentUser = Depends(current_user), ctx: ApiContext = Depends(get_ctx)):
    if rr.kind_of(request_id) != "EXPENSE":
        raise ApiError(404, "NOT_FOUND", f"unknown expense claim {request_id}")
    return respond(read(ctx, lambda conn: _detail(conn, "EXPENSE", request_id, user)))


@router.get("/requests/{request_id}/explanation", tags=["explanation"],
            summary="Plain-language explanation (display only; never changes anything)")
def get_explanation(request_id: str, user: CurrentUser = Depends(current_user), ctx: ApiContext = Depends(get_ctx)):
    """DEC-29 revised, DEC-P9-01..05: facts from this request's own ops rows; template fallback; not stored."""
    kind = _kind(request_id)
    d = read(ctx, lambda conn: _detail(conn, kind, request_id, user))
    e = explain(facts_of(kind, d["request"], d["steps"], d["exceptions"]), ctx.llm, ctx.http_client)
    return {"request_id": request_id, "explanation": {"text": e.text, "source": e.source, "model": e.model},
            "fallback_reason": e.fallback_reason}
