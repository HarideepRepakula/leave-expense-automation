"""Read-only routes added in the completion pass (spec section 19): employees, leave and expense policies, leave
balances, expense lines, the approval queue, a request's audit history, exception investigation and the dashboard
metrics. Every route needs a JWT and a role, pages with limit / offset, and returns only the columns listed here
(DEC-CP-01). Ops tables through lea_app; never ground truth."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.api.core import ApiContext, ApiError, CurrentUser, current_user, get_ctx, read, require, respond
from src.repositories import read_repository as rr

router = APIRouter()
ANALYSTS = ("PROCESS_OWNER", "OPS_ANALYST", "SYSTEM_ADMIN")
STAFF = ("APPROVER",) + ANALYSTS
QUEUE_ALL = set(ANALYSTS)                          # may look at any approver's queue
EMPLOYEE_COLUMNS = ["employee_id", "manager_id", "department_id", "job_title", "grade", "country", "currency",
                    "employment_status", "default_cost_center_id"]
PERSONAL_COLUMNS = ["full_name", "email", "employment_start", "employment_end"]     # SYSTEM_ADMIN only
LINE_COLUMNS = ["expense_line_id", "expense_claim_id", "line_number", "submission_round", "category",
                "expense_date", "quantity", "unit_amount", "line_amount", "currency", "receipt_id", "cost_center_id",
                "expense_policy_id", "validation_result", "validation_detail"]
BALANCE_COLUMNS = ["leave_balance_id", "employee_id", "leave_policy_id", "leave_year", "opening_balance", "accrued",
                   "adjustments", "used", "available_balance", "last_recalculated_at"]
Limit = Query(50, ge=1, le=200)
Offset = Query(0, ge=0)


def _page(items: list[dict], limit: int, offset: int):
    return respond({"items": items, "limit": limit, "offset": offset})


def _kind(request_id: str) -> str:
    kind = rr.kind_of(request_id)
    if kind is None:
        raise ApiError(404, "NOT_FOUND", f"unknown request {request_id}")
    return kind


@router.get("/employees", tags=["master data"],
            summary="Employees (organisation fields; names, e-mail and employment dates for SYSTEM_ADMIN only)")
def list_employees(department_id: str | None = None, country: str | None = None,
                   manager_id: str | None = None, limit: int = Limit, offset: int = Offset,
                   user: CurrentUser = Depends(require(*STAFF)), ctx: ApiContext = Depends(get_ctx)):
    cols = EMPLOYEE_COLUMNS + (PERSONAL_COLUMNS if "SYSTEM_ADMIN" in user.roles else [])
    filters = {"department_id": department_id, "country": country, "manager_id": manager_id}
    return _page(read(ctx, lambda conn: rr.page(conn, "employee", cols, filters, "employee_id", limit, offset)),
                 limit, offset)


@router.get("/leave-policies", tags=["leave"], summary="Leave policy versions (any logged-in user)")
def list_leave_policies(country_scope: str | None = None, leave_type: str | None = None,
                        is_active: bool | None = None, limit: int = Limit, offset: int = Offset,
                        user: CurrentUser = Depends(current_user), ctx: ApiContext = Depends(get_ctx)):
    filters = {"country_scope": country_scope, "leave_type": leave_type, "is_active": is_active}
    return _page(read(ctx, lambda conn: rr.page(conn, "leave_policy", None, filters, "leave_policy_id", limit,
                                                offset)), limit, offset)


@router.get("/expense-policies", tags=["expense"], summary="Expense policy versions (any logged-in user)")
def list_expense_policies(country: str | None = None, category: str | None = None, is_active: bool | None = None,
                          limit: int = Limit, offset: int = Offset, user: CurrentUser = Depends(current_user),
                          ctx: ApiContext = Depends(get_ctx)):
    filters = {"country": country, "category": category, "is_active": is_active}
    return _page(read(ctx, lambda conn: rr.page(conn, "expense_policy", None, filters, "expense_policy_id", limit,
                                                offset)), limit, offset)


@router.get("/leave-balances", tags=["leave"],
            summary="Leave balances; a requester sees only their own, staff roles anyone's")
def list_leave_balances(employee_id: str | None = None, leave_year: int | None = None, limit: int = Limit,
                        offset: int = Offset, user: CurrentUser = Depends(current_user),
                        ctx: ApiContext = Depends(get_ctx)):
    if not user.reads_all:
        employee_id = user.employee()
    filters = {"employee_id": employee_id, "leave_year": leave_year}
    return _page(read(ctx, lambda conn: rr.page(conn, "leave_balance", BALANCE_COLUMNS, filters,
                                                "leave_balance_id", limit, offset)), limit, offset)


@router.get("/expense-lines", tags=["expense"],
            summary="Expense lines; a requester sees only lines of their own claims")
def list_expense_lines(expense_claim_id: str | None = None, limit: int = Limit, offset: int = Offset,
                       user: CurrentUser = Depends(current_user), ctx: ApiContext = Depends(get_ctx)):
    owner = None if user.reads_all else user.employee()
    return _page(read(ctx, lambda conn: rr.expense_lines(conn, LINE_COLUMNS, expense_claim_id, owner, limit,
                                                         offset)), limit, offset)


@router.get("/approval-queue", tags=["approvals"],
            summary="Pending approval steps; an approver sees their own queue, analysts any approver's")
def get_approval_queue(approver_employee_id: str | None = None, required_level: str | None = None,
                       limit: int = Limit, offset: int = Offset, user: CurrentUser = Depends(require(*STAFF)),
                       ctx: ApiContext = Depends(get_ctx)):
    if not user.roles & QUEUE_ALL:
        approver_employee_id = user.employee()
    return _page(read(ctx, lambda conn: rr.approval_queue(conn, approver_employee_id, required_level, limit,
                                                          offset)), limit, offset)


@router.get("/requests/{request_id}/audit-history", tags=["audit"],
            summary="Audit events of a request, its approval steps and its reimbursements (analysts)")
def get_audit_history(request_id: str, limit: int = Query(200, ge=1, le=1000), offset: int = Offset,
                      user: CurrentUser = Depends(require(*ANALYSTS)), ctx: ApiContext = Depends(get_ctx)):
    kind = _kind(request_id)

    def work(conn):
        if rr.get_request(conn, kind, request_id) is None:
            raise ApiError(404, "NOT_FOUND", f"unknown request {request_id}")
        return rr.audit_history(conn, kind, request_id, limit, offset)
    return _page(read(ctx, work), limit, offset)


@router.get("/requests/{request_id}/investigation", tags=["exceptions"],
            summary="Exception investigation: request, lines, applicable policies, steps, exceptions, attempts, "
                    "audit events (analysts)")
def get_investigation(request_id: str, user: CurrentUser = Depends(require(*ANALYSTS)),
                      ctx: ApiContext = Depends(get_ctx)):
    kind = _kind(request_id)
    d = read(ctx, lambda conn: rr.investigation(conn, kind, request_id))
    if d is None:
        raise ApiError(404, "NOT_FOUND", f"unknown request {request_id}")
    return respond(d)


@router.get("/dashboard/metrics", tags=["dashboard"],
            summary="Operational KPIs: counts by status, exceptions, high-priority issues, amounts by currency")
def get_dashboard_metrics(user: CurrentUser = Depends(require(*STAFF)), ctx: ApiContext = Depends(get_ctx)):
    return respond(read(ctx, rr.dashboard_metrics))
