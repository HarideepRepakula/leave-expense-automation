"""Stage S6: workflow outcomes with decision timing (docs/07 section 2; docs/05 9.5; ASM-024; Phase 7B).

Every submitted request is replayed in time order through the services with the router and the simulated
decisions (leave_batch.replay_leave / expense_batch.replay_expense with a DecisionTiming); the year-end
carry-forward rows are posted on 1 January. The result is written into the dataset:
- leave_request / expense_claim / expense_line: status, exception class, decision reason, the values written at
  submission (USD total, rate, policy versions, line results, receipt status) and approved_amount;
- approval_step, approval_event, approval_attempt, request_status_event, request_exception, idempotency_record;
- leave_balance_transaction (renumbered: legacy and approval USAGE, CARRY_FORWARD, CARRY_FORWARD_EXPIRY) and the
  leave_balance snapshots recomputed from it (BR-LBAL-06);
- cost_center_transaction (RESERVATION, RELEASE, OVERRIDE) and the cost_center_budget snapshots (V-ARITH-08).
Raw inputs are never changed, so the replay can be run again on the S6 output (raw-input view, DEC-P7B-02).
Ids follow time: rows are numbered after a stable sort on their instant (docs/07 section 3).
"""
from __future__ import annotations

import uuid
from datetime import datetime, time, timezone
from decimal import Decimal

from src.common.enums import BudgetTxnType, RequestType, RoleName
from src.common.rng import RngStreams
from src.data.stages import GenParams
from src.data.stages.balances import CORRELATION_NAMESPACE, number_transactions
from src.services.approval_routing import ApprovalRouter
from src.services.calendar_service import HolidayCalendar
from src.services.exception_service import ExceptionCatalogue
from src.services.expense_batch import ExpenseReplay, replay_expense
from src.services.expense_service import DetectionParams
from src.services.leave_batch import LeaveReplay, replay_leave
from src.services.workflow_simulation import DecisionTiming, employee_roles

ONE_DP, CENT, ZERO = Decimal("0.1"), Decimal("0.01"), Decimal("0")
LEAVE_COLUMNS = ("workflow_status", "exception_class", "decision_reason_code", "first_submitted_at",
                 "business_day_count", "requested_quantity")
CLAIM_COLUMNS = ("workflow_status", "exception_class", "decision_reason_code", "first_submitted_at",
                 "expense_policy_id", "total_amount_usd", "fx_rate_used", "receipt_status", "approved_amount")
LINE_COLUMNS = ("expense_policy_id", "validation_result", "validation_detail")
WORKFLOW_TABLES = ("approval_step", "approval_event", "approval_attempt", "request_status_event",
                   "request_exception", "idempotency_record")


def as_of_instant(as_of) -> datetime:
    """FrozenClock: midnight UTC at the start of the as-of date (docs/03 section 5)."""
    return datetime.combine(as_of, time(0, 0), tzinfo=timezone.utc)


def decision_timing(cfg: dict, tables: dict[str, list[dict]], calendar: HolidayCalendar, roles: dict[str, set[str]],
                    delays, as_of) -> DecisionTiming:
    owners = [e for e, r in roles.items() if RoleName.PROCESS_OWNER.value in r]
    return DecisionTiming.from_config(cfg["generation"], cfg["exception_codes"], calendar, tables["employee"],
                                      owners, delays, as_of_instant(as_of))


def simulate(cfg: dict, tables: dict[str, list[dict]], calendar: HolidayCalendar,
             delays, as_of) -> tuple[LeaveReplay, ExpenseReplay]:
    """Both replays with routing and the simulated decisions up to the as-of instant. `delays(key, low, high)` is
    the keyed draw on the delays stream. Also used by src/evaluation on the exported dataset."""
    roles = employee_roles(tables["application_user"], tables["user_role"], tables["role"])
    timing = decision_timing(cfg, tables, calendar, roles, delays, as_of)
    catalogue = ExceptionCatalogue.from_config(cfg["exception_codes"])
    router = ApprovalRouter.from_rows(tables["approval_rule"], tables["employee"], tables["department"],
                                      tables["delegation"])
    leave = replay_leave(tables["leave_request"], {e["employee_id"]: e for e in tables["employee"]},
                         {x["leave_policy_id"]: x for x in tables["leave_policy"]}, calendar,
                         tables["leave_balance_transaction"], tables["leave_balance"], catalogue,
                         router=router, timing=timing, roles=roles)
    expense = replay_expense(tables, catalogue, DetectionParams.from_config(cfg["expense_policies"]),
                             router=router, timing=timing, roles=roles)
    return leave, expense


def build_outcomes(cfg: dict, p: GenParams, streams: RngStreams, dataset: dict[str, list[dict]],
                   calendar: HolidayCalendar) -> tuple[LeaveReplay, ExpenseReplay]:
    """Run S6 and write its rows into `dataset` (in place). Returns the replays (for detections.csv)."""
    leave, expense = simulate(cfg, dataset, calendar,
                              lambda key, lo, hi: streams.keyed_integers("delays", key, lo, hi), p.as_of)
    ls, es = leave.store, expense.store
    for r in dataset["leave_request"]:
        got = ls.requests.get(r["leave_request_id"])
        if got is not None:
            r.update({k: got[k] for k in LEAVE_COLUMNS})
            r["business_day_count"] = Decimal(r["business_day_count"]).quantize(ONE_DP)
    for c in dataset["expense_claim"]:
        got = es.claims.get(c["expense_claim_id"])
        if got is not None:
            c.update({k: got.get(k) for k in CLAIM_COLUMNS})
    lines = {ln["expense_line_id"]: ln for cl in es.lines.values() for ln in cl}
    for ln in dataset["expense_line"]:
        got = lines.get(ln["expense_line_id"])
        if got is not None:
            ln.update({k: got[k] for k in LINE_COLUMNS})
    _ledger(dataset, ls)
    _budget(dataset, es.budget_ledger)
    dataset.update(_workflow_rows(dataset, ls, es))
    return leave, expense


def _workflow_rows(dataset: dict[str, list[dict]], ls, es) -> dict[str, list[dict]]:
    users = {u["employee_id"]: u["user_id"] for u in dataset["application_user"] if u["employee_id"]}
    out: dict[str, list[dict]] = {name: [] for name in WORKFLOW_TABLES}
    for rtype, store in ((RequestType.LEAVE.value, ls), (RequestType.EXPENSE.value, es)):
        fk, other = (("leave_request_id", "expense_claim_id") if rtype == RequestType.LEAVE
                     else ("expense_claim_id", "leave_request_id"))

        def owned(e: dict) -> dict:
            return {"request_type": rtype, fk: e["request_id"], other: None,
                    **{k: v for k, v in e.items() if k != "request_id"}}

        out["approval_step"] += [dict(s) for steps in store.steps.values() for s in steps]
        out["approval_event"] += [dict(e) for e in store.approval_events]
        out["approval_attempt"] += [dict(a) for a in store.attempts]
        out["request_status_event"] += [owned(e) for e in store.status_events]
        out["request_exception"] += [owned(e) for e in store.exceptions]
        out["idempotency_record"] += [
            {"actor_user_id": users[i["actor_id"]], "idempotency_key": i["idempotency_key"],
             "operation": i["operation"], "request_hash": i["request_hash"], fk: i["request_id"], other: None,
             "status": "COMPLETED", "response_hash": i["response_hash"], "created_at": i["created_at"],
             "completed_at": i["completed_at"]} for i in store.idempotency_records.values()]

    def request_of(r: dict) -> str:
        return r["leave_request_id"] or r["expense_claim_id"]

    _number(out["approval_event"], "approval_event_id", "APE", "occurred_at", lambda r: r["approval_step_id"])
    _number(out["approval_attempt"], "attempt_id", "APA", "attempted_at", request_of)
    _number(out["request_status_event"], "event_id", "RSE", "occurred_at", request_of)
    _number(out["request_exception"], "exception_id", "REX", "detected_at", request_of)
    out["approval_step"].sort(key=lambda s: s["approval_step_id"])
    out["idempotency_record"].sort(key=lambda r: (r["actor_user_id"], r["idempotency_key"]))
    return out


def _number(rows: list[dict], pk: str, prefix: str, when: str, owner) -> None:
    """Ids <PREFIX>-000000001.. in time order; owner id, then the original (append) order break ties."""
    order = sorted(range(len(rows)), key=lambda i: (rows[i][when], owner(rows[i]), i))
    rows[:] = [rows[i] for i in order]
    for n, r in enumerate(rows, start=1):
        r[pk] = f"{prefix}-{n:09d}"


def _sums(rows: list[dict], key: str, amount: str) -> dict[str, dict[str, Decimal]]:
    out: dict[str, dict[str, Decimal]] = {}
    for t in rows:
        s = out.setdefault(t[key], {})
        s[t["txn_type"]] = s.get(t["txn_type"], ZERO) + t[amount]
    return out


def _ledger(dataset: dict[str, list[dict]], store) -> None:
    """The whole leave ledger after S6, renumbered in date order, and the snapshots from it (BR-LBAL-06)."""
    rows = [t for ts in store.ledger.values() for t in ts]
    dataset["leave_balance_transaction"] = number_transactions(
        [{k: t.get(k) for k in ("leave_balance_id", "leave_request_id", "txn_type", "quantity", "txn_date", "reason")}
         for t in rows])
    sums = _sums(dataset["leave_balance_transaction"], "leave_balance_id", "quantity")
    for b in dataset["leave_balance"]:
        s = sums.get(b["leave_balance_id"], {})
        b["opening_balance"] = (s.get("OPENING", ZERO) + s.get("CARRY_FORWARD", ZERO)).quantize(ONE_DP)
        b["accrued"] = s.get("ACCRUAL", ZERO).quantize(ONE_DP)
        b["adjustments"] = (s.get("ADJUSTMENT", ZERO) + s.get("CARRY_FORWARD_EXPIRY", ZERO)).quantize(ONE_DP)
        b["used"] = (-(s.get("USAGE", ZERO) + s.get("USAGE_REVERSAL", ZERO))).quantize(ONE_DP)
        b["available_balance"] = (b["opening_balance"] + b["accrued"] + b["adjustments"] - b["used"]).quantize(ONE_DP)


def _budget(dataset: dict[str, list[dict]], ledger: list[dict]) -> None:
    """cost_center_transaction in time order (CCT ids) and committed / actual on cost_center_budget (BR-BUD-01)."""
    order = sorted(range(len(ledger)), key=lambda i: (ledger[i]["posted_at"], ledger[i]["expense_claim_id"] or "", i))
    rows = []
    for n, i in enumerate(order, start=1):
        t, tid = ledger[i], f"CCT-{n:09d}"
        rows.append({"transaction_id": tid, **{k: t[k] for k in (
            "cost_center_id", "cost_center_budget_id", "expense_claim_id", "txn_type", "amount", "currency",
            "txn_date", "posted_at", "reason_code")}, "correlation_id": uuid.uuid5(CORRELATION_NAMESPACE, tid)})
    dataset["cost_center_transaction"] = rows
    sums = _sums(rows, "cost_center_budget_id", "amount")
    for b in dataset["cost_center_budget"]:
        s = sums.get(b["cost_center_budget_id"], {})
        actual = s.get(BudgetTxnType.ACTUAL.value, ZERO)
        b["actual_amount"] = actual.quantize(CENT)
        b["committed_amount"] = (s.get(BudgetTxnType.RESERVATION.value, ZERO)
                                 - s.get(BudgetTxnType.RELEASE.value, ZERO) - actual).quantize(CENT)
