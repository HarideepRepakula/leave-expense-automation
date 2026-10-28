"""PostgreSQL ExpenseStore for claim submission (docs/06 section 8.1 steps 2-5 and 7; docs/05 section 6; AM-F5).

Same contract as the leave store: one Connection inside the caller's transaction, never commits. Locks, in this
order: the claim row, then its cost_center row and the cost_center_budget row of the submission date, FOR UPDATE
(BR-BUD-02), before the budget ledger is read. Writes: the claim and its current-round lines (policy version,
PASS / CAPPED / FAIL), three request_status_event rows, one request_exception row per code, the RESERVATION (and
RELEASE when rejected or returned) in cost_center_transaction with the budget's committed_amount kept equal to
its ledger (V-ARITH-08). Other claims count for duplicate, pattern and split checks with the USD total the
services stored on them (claims never validated by the services have none and are left out of split checks).
Routing (Phase 7A) reads approval_rule, employee, department and delegation in the same transaction; approval_step
rows and the ASSIGNED approval_event (APE) are written for PENDING_APPROVAL.
Phase 7B: the store is also a WorkflowStore (SqlWorkflow, base.py) for approval_service decisions: approved_amount
at approval, RELEASE / OVERRIDE rows with committed_amount kept equal to the budget ledger, resubmission (new-round
lines inserted, old lines kept, claim round and total updated) and idempotency_record rows.
"""
from __future__ import annotations

from datetime import date

import sqlalchemy as sa

from src.common.enums import BudgetTxnType, RequestType, WorkflowStatus
from src.repositories.base import SqlWorkflow, allocate_ids, load_router, next_step_sequence, table, \
    write_events_and_exceptions, write_steps
from src.services.approval_routing import ApprovalRouter
from src.services.expense_service import DetectionParams, ExpenseContext, ExpenseSubmissionResult, apply_to_claim, \
    approved_amount_of, claim_hashes, current_lines, override_postings, release_postings, top_line

CLAIM_WRITES = ("workflow_status", "exception_class", "decision_reason_code", "first_submitted_at", "expense_policy_id",
                "total_amount_usd", "fx_rate_used", "receipt_status", "current_round", "total_amount",
                "cost_center_id", "currency", "claim_period_start", "claim_period_end")


class SqlExpenseStore(SqlWorkflow):
    request_type, fk, request_table = RequestType.EXPENSE.value, "expense_claim_id", "expense_claim"

    def __init__(self, conn: sa.Connection, params: DetectionParams) -> None:
        self.conn, self.params = conn, params
        self._lines: dict[str, list[dict]] = {}

    def _rows(self, query) -> list[dict]:
        return [dict(r) for r in self.conn.execute(query).mappings()]

    def load_claim(self, claim_id: str) -> dict:
        t = table("expense_claim")
        return dict(self.conn.execute(sa.select(t).where(t.c.expense_claim_id == claim_id).with_for_update())
                    .mappings().one())

    def load_request(self, request_id: str) -> dict:
        return self.load_claim(request_id)

    def router(self) -> ApprovalRouter:
        return load_router(self.conn)

    def all_lines(self, claim_id: str) -> list[dict]:
        return self._claim_lines([claim_id])[claim_id]

    def add_round_lines(self, claim: dict, lines: list[dict]) -> None:
        """docs/06 8.3 step 4: the new round's lines are inserted; earlier lines stay as they are (DEC-11)."""
        self.conn.execute(sa.insert(table("expense_line")), lines)

    def _ledger_of(self, claim_id: str) -> list[dict]:
        t = table("cost_center_transaction")
        return self._rows(sa.select(t).where(t.c.expense_claim_id == claim_id).order_by(t.c.transaction_id))

    # WorkflowStore (approval_service) -----------------------------------------------------------------------
    def routing_inputs(self, r: dict):
        lines = current_lines(r, self.all_lines(r["expense_claim_id"]))
        return (top_line(lines)["category"], r["total_amount_usd"],
                self.round_submitted_at(r["expense_claim_id"], r["current_round"]).date())

    def approval_effects(self, r: dict, at):
        lines = current_lines(r, self.all_lines(r["expense_claim_id"]))
        return {"approved_amount": approved_amount_of(lines, self._rows(sa.select(table("expense_policy"))))}, []

    def release_postings(self, r: dict, at, reason: str) -> list[dict]:
        return release_postings(r, self._ledger_of(r["expense_claim_id"]), at, reason)

    def override_postings(self, r: dict, at) -> list[dict]:
        return override_postings(r, self._ledger_of(r["expense_claim_id"]), at)

    def post_decision_rows(self, res) -> None:
        self._post_budget(res.budget_postings, res.correlation_id)

    def _post_budget(self, postings: list[dict], correlation_id) -> None:
        """cost_center_transaction rows; committed_amount follows RESERVATION / RELEASE (V-ARITH-08). The budget
        rows are locked before they change (BR-BUD-02)."""
        if not postings:
            return
        t, b = table("cost_center_transaction"), table("cost_center_budget")
        for budget_id in sorted({p["cost_center_budget_id"] for p in postings}):
            self.conn.execute(sa.select(b.c.cost_center_budget_id).where(b.c.cost_center_budget_id == budget_id)
                              .with_for_update())
        ids = allocate_ids(self.conn, "cost_center_transaction", "CCT", len(postings))
        self.conn.execute(sa.insert(t), [{**p, "transaction_id": i, "correlation_id": correlation_id}
                                         for i, p in zip(ids, postings)])
        for p in postings:
            sign = {BudgetTxnType.RESERVATION.value: 1, BudgetTxnType.RELEASE.value: -1}.get(p["txn_type"], 0)
            if sign:
                self.conn.execute(sa.update(b).where(b.c.cost_center_budget_id == p["cost_center_budget_id"])
                                  .values(committed_amount=b.c.committed_amount + sign * p["amount"]))

    def next_step_sequence(self, claim_id: str) -> int:
        return next_step_sequence(self.conn, "expense_claim_id", claim_id)

    def _claim_lines(self, claim_ids: list[str]) -> dict[str, list[dict]]:
        el = table("expense_line")
        out: dict[str, list[dict]] = {cid: [] for cid in claim_ids}
        for ln in self._rows(sa.select(el).where(el.c.expense_claim_id.in_(claim_ids))):
            out[ln["expense_claim_id"]].append(ln)
        return out

    def context(self, claim: dict, on: date) -> ExpenseContext:
        ec, el, rc, emp_t = table("expense_claim"), table("expense_line"), table("receipt"), table("employee")
        cid = claim["expense_claim_id"]
        emp = self._rows(sa.select(emp_t).where(emp_t.c.employee_id == claim["employee_id"]))[0]
        lines = current_lines(claim, self._claim_lines([cid])[cid])
        self._lines[cid] = lines
        receipts = {r["receipt_id"]: r for r in self._rows(
            sa.select(rc).where(rc.c.receipt_id.in_([ln["receipt_id"] for ln in lines if ln["receipt_id"]])))}
        sharing = sa.select(el.c.expense_claim_id).join(rc, rc.c.receipt_id == el.c.receipt_id) \
            .where(rc.c.receipt_hash.in_(list(claim_hashes(lines, receipts))))
        others = self._rows(sa.select(ec).where(
            ec.c.expense_claim_id != cid, ec.c.workflow_status != WorkflowStatus.DRAFT.value,
            sa.or_(ec.c.employee_id == claim["employee_id"], ec.c.expense_claim_id.in_(sharing)))
            .order_by(ec.c.expense_claim_id))
        other_lines = self._claim_lines([o["expense_claim_id"] for o in others])
        ids = [ln["receipt_id"] for ls in other_lines.values() for ln in ls if ln["receipt_id"]]
        receipts.update({r["receipt_id"]: r for r in self._rows(sa.select(rc).where(rc.c.receipt_id.in_(ids)))})
        for o in others:
            o["lines"] = current_lines(o, other_lines[o["expense_claim_id"]])
            at = o["first_submitted_at"]
            o.update(usd=o["total_amount_usd"], submitted_at=at, submitted_on=at.date() if at else None,
                     primary_category=top_line(o["lines"])["category"] if o["lines"] else None)
        cc = budget = None
        ledger: list[dict] = []
        if claim["cost_center_id"] is not None:
            c, b, t = table("cost_center"), table("cost_center_budget"), table("cost_center_transaction")
            cc = self._rows(sa.select(c).where(c.c.cost_center_id == claim["cost_center_id"]).with_for_update())[0]
            found = self._rows(sa.select(b).where(b.c.cost_center_id == claim["cost_center_id"],
                                                  b.c.budget_period_start <= on, b.c.budget_period_end >= on)
                               .with_for_update())
            budget = found[0] if found else None
            if budget is not None:
                ledger = self._rows(sa.select(t).where(t.c.cost_center_budget_id == budget["cost_center_budget_id"]))
        policies = self._rows(sa.select(table("expense_policy")))
        fx = self._rows(sa.select(table("fx_rate")))
        return ExpenseContext(emp, lines, receipts, policies, fx, cc, budget, ledger, others, self.params)

    def record_submission(self, result: ExpenseSubmissionResult) -> None:
        cid = result.claim_id
        claim = self.load_claim(cid)
        lines = self._lines[cid]
        apply_to_claim(claim, lines, result)
        ec, el = table("expense_claim"), table("expense_line")
        self.conn.execute(sa.update(ec).where(ec.c.expense_claim_id == cid).values(
            {k: claim[k] for k in CLAIM_WRITES}))
        for ln in lines:
            self.conn.execute(sa.update(el).where(el.c.expense_line_id == ln["expense_line_id"]).values(
                expense_policy_id=ln["expense_policy_id"], validation_result=ln["validation_result"],
                validation_detail=ln["validation_detail"]))
        common = {"request_type": RequestType.EXPENSE.value, "leave_request_id": None, "expense_claim_id": cid,
                  "submission_round": result.submission_round, "correlation_id": result.correlation_id}
        write_events_and_exceptions(self.conn, common, result.events, result.findings, result.submitted_at)
        write_steps(self.conn, result.steps, result.correlation_id)
        self._post_budget(result.budget_postings, result.correlation_id)
        if result.idempotency is not None:
            self.record_idempotency(result.idempotency)
