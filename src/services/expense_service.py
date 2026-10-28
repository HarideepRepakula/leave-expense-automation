"""Expense claim validation and submission (spec 13.2; docs/05 sections 3, 4, 6, 7, 9; docs/06 sections 2 and 8.1).

validate_claim() runs BR-EX-01..13 over the current-round lines in the fixed order of docs/05 section 3; every
failing check is recorded and the route follows the severity precedence (exception_service). Money is Decimal:
amounts at 2 dp, USD = round_half_up(local / rate, 2) with the fixed rate effective on the submission date
(fx_rate rows, ASM-003, ASM-031).

submit_expense() moves a DRAFT through SUBMITTED and VALIDATING to its outcome on any ExpenseStore (in memory
below; PostgreSQL in src/repositories/expense_repository.py). At submission a budget RESERVATION of the claim total
is posted (BR-BUD-02) and released at once when the outcome is REJECTED or RETURNED_FOR_CORRECTION (BR-BUD-04).

Routing (Phase 7A, approval_routing): when the store has a router and validation neither rejects nor returns, the
claim is routed on its primary category and USD total as of the submission date; NO_VALID_APPROVAL_PATH /
RULE_CONFLICT join the codes (SOFT -> ESCALATED_FOR_REVIEW, the reservation is kept). Approval steps are created only
for an outcome of PENDING_APPROVAL. A store without a router (the generator guard) does no routing, as in Phase 6.

Resubmission (Phase 7B, docs/06 8.3): submit_expense() on a RETURNED_FOR_CORRECTION claim opens round + 1. The
corrected lines are inserted tagged with the new round, line numbers continuing (DEC-11); the old lines stay; the
total is recomputed over the new round's lines; a new RESERVATION is posted. Without new lines the current round's
lines are carried into the new round unchanged (ASM-P7B-07). The claim id never changes.
Decisions (approval_service): approved_amount (BR-EX-14) is stored at final approval from the stored line results
(approved_amount_of); RELEASE of the open reservation on reject or return (BR-BUD-04); OVERRIDE when a process owner
sends on a BUDGET_EXCEEDED claim (BR-BUD-06). Phase 8: every submission carries its audit_event rows
(audit_service); the store is also a ReimbursementStore (reimbursement_service), and completion_postings() gives
ACTUAL and RELEASE at a completed payment (BR-BUD-05).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from src.common import ids
from src.common.enums import BudgetTxnType, LineValidationResult, ReceiptStatus, RequestType, WorkflowStatus
from src.common.money import fx_rate_on
from src.services import audit_service
from src.services.approval_routing import ApprovalRouter, Routing, assignment_event, build_steps
from src.services.approval_service import BUDGET_OVERRIDE, DecisionResult, IdempotentReplay, InMemoryWorkflow, \
    resubmission_key, resubmission_record
from src.services.exception_service import Classification, ExceptionCatalogue, Finding, FindingSet
from src.services.lifecycle import check_resubmission, check_transition
from src.services.reimbursement_service import InMemoryReimbursements

ZERO = Decimal("0")
CENT = Decimal("0.01")
OPEN = frozenset({WorkflowStatus.PENDING_APPROVAL.value, WorkflowStatus.ESCALATED_FOR_REVIEW.value})
RELEASED = frozenset({WorkflowStatus.REJECTED.value, WorkflowStatus.RETURNED_FOR_CORRECTION.value})
# A line that carries one of these cannot be paid as it stands (ASM-P6-04); LINE_LIMIT_EXCEEDED only caps it.
LINE_FAIL_CODES = frozenset({"EXPENSE_OUTSIDE_EMPLOYMENT", "EXPENSE_DATE_TOO_OLD", "CURRENCY_MISMATCH",
                             "POLICY_NOT_APPLICABLE", "MISSING_RECEIPT"})
RESUBMIT_CLAIM_FIELDS = frozenset({"cost_center_id", "currency", "claim_period_start", "claim_period_end"})
LINE_INPUT_FIELDS = ("category", "merchant_description", "expense_date", "quantity", "unit_amount", "line_amount",
                     "currency", "receipt_id")


class ExpenseInputError(ValueError):
    """Structurally invalid input (BR-EX-11 arithmetic, no lines): API 422. A stored mismatch is a validator
    failure (negative fixtures), never a business exception code."""


class PolicyConfigurationError(RuntimeError):
    """BR-POL-02: more than one effective version of one family. A technical failure (processing_failure)."""


@dataclass(frozen=True)
class DetectionParams:
    """config/expense_policies.yaml detection (BR-EX-02, BR-SPLIT-01, ASM-019, ASM-041)."""
    max_line_age_days: int
    split_window_days: int
    split_threshold_usd: Decimal

    @classmethod
    def from_config(cls, expense_policies_cfg: dict) -> "DetectionParams":
        d = expense_policies_cfg["detection"]
        return cls(int(d["max_line_age_days"]), int(d["split_window_days"]), Decimal(str(d["split_threshold_usd"])))


def money(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def to_usd(amount: Decimal, currency: str, fx_rows: list[dict], on: date) -> tuple[Decimal, Decimal]:
    """(USD amount, rate used): the USD->currency rate effective on `on` (ASM-031); round half-up to 2 dp."""
    rate = fx_rate_on(fx_rows, "USD", currency, on)
    return money(amount / rate), rate


def resolve_expense_policy(policies: list[dict], category: str, country: str, on: date) -> dict | None:
    """BR-EX-03 / BR-POL-02: the one active version for (category, country) effective on `on`; None if none."""
    found = [p for p in policies if p["category"] == category and p["country"] == country and p["is_active"]
             and p["effective_start"] <= on and (p["effective_end"] is None or on <= p["effective_end"])]
    if len(found) > 1:
        raise PolicyConfigurationError(f"{len(found)} effective versions of {category}/{country} on {on}")
    return found[0] if found else None


def current_lines(claim: dict, lines: list[dict]) -> list[dict]:
    """The current round's lines in line order (DEC-11)."""
    return sorted((ln for ln in lines if ln["submission_round"] == claim["current_round"]),
                  key=lambda ln: ln["line_number"])


def top_line(lines: list[dict]) -> dict:
    """BR-EX-03: the highest-amount line decides the primary category (ties: lowest line number)."""
    return sorted(lines, key=lambda ln: (-ln["line_amount"], ln["line_number"]))[0]


def check_arithmetic(claim: dict, lines: list[dict]) -> None:
    """BR-EX-11 at write time: total = SUM(lines); line = round(quantity x unit, 2) when both are given."""
    if not lines:
        raise ExpenseInputError(f"{claim['expense_claim_id']}: a claim needs at least one line")
    for ln in lines:
        if ln["quantity"] is not None and money(ln["quantity"] * ln["unit_amount"]) != ln["line_amount"]:
            raise ExpenseInputError(f"{ln['expense_line_id']}: {ln['quantity']} x {ln['unit_amount']} != "
                                    f"{ln['line_amount']}")
    if claim["total_amount"] != sum((ln["line_amount"] for ln in lines), ZERO):
        raise ExpenseInputError(f"{claim['expense_claim_id']}: total_amount != sum of current-round lines")


def split_groups(items: list[tuple], window_days: int, threshold_usd: Decimal) -> list[list[str]]:
    """BR-SPLIT-02 (ASM-P4-13): items (submission date, submitted_at, claim_id, usd) of one employee and primary
    category, each already below the threshold. Greedy from the earliest unassigned claim: the window is
    [d, d + W - 1]; a group needs at least two claims and a sum >= threshold (inclusive, BC-10)."""
    items = sorted(items)
    assigned: set[str] = set()
    groups = []
    for i, (d0, _, cid, _) in enumerate(items):
        if cid in assigned:
            continue
        members = [it for it in items[i:] if it[2] not in assigned and (it[0] - d0).days <= window_days - 1]
        if len(members) >= 2 and sum(it[3] for it in members) >= threshold_usd:
            groups.append([it[2] for it in members])
            assigned.update(it[2] for it in members)
    return groups


def approved_amount_of(lines: list[dict], policies: list[dict]) -> Decimal:
    """BR-EX-14 at approval, from the stored line results of the current round (ASM-P6-04): SUM(min(line,
    per-line limit)) over the lines that are not FAIL."""
    limits = {p["expense_policy_id"]: p["per_line_limit"] for p in policies}
    return money(sum((min(ln["line_amount"], limits[ln["expense_policy_id"]]) for ln in lines
                      if ln["validation_result"] != LineValidationResult.FAIL.value), ZERO))


def open_reservations(claim_id: str, ledger: list[dict]) -> dict[str, tuple[str, Decimal]]:
    """Budget id -> (cost center, RESERVATION - RELEASE - ACTUAL) of one claim, where still positive."""
    out: dict[str, tuple[str, Decimal]] = {}
    for t in ledger:
        if t["expense_claim_id"] != claim_id or t["txn_type"] == BudgetTxnType.OVERRIDE.value:
            continue
        sign = 1 if t["txn_type"] == BudgetTxnType.RESERVATION.value else -1
        cc, amount = out.get(t["cost_center_budget_id"], (t["cost_center_id"], ZERO))
        out[t["cost_center_budget_id"]] = (cc, amount + sign * t["amount"])
    return {b: v for b, v in sorted(out.items()) if v[1] > 0}


def release_postings(claim: dict, ledger: list[dict], at: datetime, reason: str) -> list[dict]:
    """BR-BUD-04: RELEASE whatever the claim still holds (REJECTED, RETURNED_FOR_CORRECTION, CANCELLED)."""
    return [{"cost_center_id": cc, "cost_center_budget_id": b, "expense_claim_id": claim["expense_claim_id"],
             "txn_type": BudgetTxnType.RELEASE.value, "amount": amount, "currency": claim["currency"],
             "txn_date": at.date(), "posted_at": at, "reason_code": reason}
            for b, (cc, amount) in open_reservations(claim["expense_claim_id"], ledger).items()]


def override_postings(claim: dict, ledger: list[dict], at: datetime) -> list[dict]:
    """BR-BUD-06: an OVERRIDE row (the claim total, reason BUDGET_OVERRIDE) recording that a BUDGET_EXCEEDED claim
    was sent on knowingly. It does not change available or committed (BR-BUD-01 counts only RESERVATION, RELEASE
    and ACTUAL)."""
    return [{"cost_center_id": cc, "cost_center_budget_id": b, "expense_claim_id": claim["expense_claim_id"],
             "txn_type": BudgetTxnType.OVERRIDE.value, "amount": claim["total_amount"], "currency": claim["currency"],
             "txn_date": at.date(), "posted_at": at, "reason_code": BUDGET_OVERRIDE}
            for b, (cc, _) in open_reservations(claim["expense_claim_id"], ledger).items()]


def completion_postings(claim: dict, ledger: list[dict], amount: Decimal, at: datetime) -> list[dict]:
    """BR-BUD-05 at a COMPLETED reimbursement: ACTUAL of the approved amount and RELEASE of what the claim's
    reservation still holds beyond it, on the reservation's budget (several budgets in id order, ASM-P8-03).
    Nothing when the claim holds no reservation."""
    out, left = [], amount
    for b, (cc, held) in open_reservations(claim["expense_claim_id"], ledger).items():
        actual = min(held, left)
        left -= actual
        row = {"cost_center_id": cc, "cost_center_budget_id": b, "expense_claim_id": claim["expense_claim_id"],
               "currency": claim["currency"], "txn_date": at.date(), "posted_at": at, "reason_code": None}
        if actual > 0:
            out.append({**row, "txn_type": BudgetTxnType.ACTUAL.value, "amount": actual})
        if held - actual > 0:
            out.append({**row, "txn_type": BudgetTxnType.RELEASE.value, "amount": held - actual,
                        "reason_code": "REIMBURSEMENT_COMPLETED"})
    return out


def round_lines(claim: dict, previous: list[dict], new_lines: list[dict] | None, new_round: int) -> list[dict]:
    """docs/06 8.3 step 4: the new round's lines, numbered after every existing line (DEC-11). Without new lines the
    current round's lines are carried over unchanged (ASM-P7B-07)."""
    source = new_lines if new_lines is not None else [
        {k: ln[k] for k in LINE_INPUT_FIELDS} for ln in current_lines(claim, previous)]
    if not source:
        raise ExpenseInputError(f"{claim['expense_claim_id']}: a claim needs at least one line")
    start = max((ln["line_number"] for ln in previous), default=0)
    out = []
    for i, ln in enumerate(source, start=start + 1):
        unknown = set(ln) - set(LINE_INPUT_FIELDS)
        if unknown:
            raise ValueError(f"unknown line fields {sorted(unknown)}")
        out.append({**{k: ln.get(k) for k in LINE_INPUT_FIELDS},
                    "expense_line_id": ids.expense_line_id(claim["expense_claim_id"], i),
                    "expense_claim_id": claim["expense_claim_id"], "line_number": i, "submission_round": new_round,
                    "expense_policy_id": None, "validation_result": LineValidationResult.PENDING.value,
                    "validation_detail": None})
    return out


def budget_available(budget: dict, ledger: list[dict]) -> Decimal:
    """BR-BUD-01: budget - actual - committed, committed = RESERVATION - RELEASE - ACTUAL in the budget ledger."""
    s: dict[str, Decimal] = {}
    for t in ledger:
        s[t["txn_type"]] = s.get(t["txn_type"], ZERO) + t["amount"]
    actual = s.get(BudgetTxnType.ACTUAL.value, ZERO)
    committed = s.get(BudgetTxnType.RESERVATION.value, ZERO) - s.get(BudgetTxnType.RELEASE.value, ZERO) - actual
    return budget["budget_amount"] - actual - committed


@dataclass
class ExpenseContext:
    """Everything validation reads for one claim, loaded (and in the DB locked) by an ExpenseStore."""
    employee: dict
    lines: list[dict]               # the claim's current-round lines
    receipts: dict[str, dict]       # receipt rows by id: this claim's and the other claims'
    policies: list[dict]            # expense_policy rows (all versions)
    fx: list[dict]
    cost_center: dict | None
    budget: dict | None             # cost_center_budget whose period contains the submission date
    budget_ledger: list[dict]       # cost_center_transaction rows of that budget
    others: list[dict]              # other submitted claims that matter (same employee, or a shared receipt hash),
    params: DetectionParams         # each with "lines" (current round) and "usd" / "submitted_on" when known


@dataclass
class LineResult:
    expense_line_id: str
    expense_policy_id: str | None
    validation_result: str          # PASS / CAPPED / FAIL (ASM-P6-04)
    validation_detail: str | None


@dataclass
class ExpenseValidation:
    claim_id: str
    submitted_on: date
    total: Decimal
    usd: Decimal
    rate: Decimal
    primary_category: str
    policy_id: str | None           # version of the primary category's policy (BR-EX-03)
    findings: list[Finding]
    lines: list[LineResult]
    approved_amount: Decimal        # BR-EX-14 if approved as it stands: SUM(min(line, limit)) over non-FAIL lines
    receipt_status: str
    budget: dict | None             # {budget_id, available, requested} when a budget applies

    @property
    def codes(self) -> list[str]:
        return [f.code for f in self.findings]


def claim_hashes(lines: list[dict], receipts: dict[str, dict]) -> set[str]:
    return {receipts[ln["receipt_id"]]["receipt_hash"] for ln in lines
            if ln["receipt_id"] is not None and ln["receipt_id"] in receipts}


def validate_claim(claim: dict, ctx: ExpenseContext, submitted_at: datetime) -> ExpenseValidation:
    """BR-EX-01..13 in the order of docs/05 section 3. `submitted_at` is the submission instant of this round."""
    on = submitted_at.date()
    emp, p = ctx.employee, ctx.params
    lines = ctx.lines
    check_arithmetic(claim, lines)
    out = FindingSet()
    line_codes: dict[str, set[str]] = {ln["expense_line_id"]: set() for ln in lines}

    def line_hit(ln: dict, code: str, detail: str) -> None:
        line_codes[ln["expense_line_id"]].add(code)
        out.add(code, detail, ln["expense_line_id"])

    start, end = emp["employment_start"], emp["employment_end"]
    oldest = on - timedelta(days=p.max_line_age_days)
    pols: dict[str, dict | None] = {}
    for ln in lines:
        d = ln["expense_date"]
        if d < start or (end is not None and d > end):                                    # BR-EX-01
            line_hit(ln, "EXPENSE_OUTSIDE_EMPLOYMENT", f"line dated outside employment {start}..{end}")
        if d > on or d < oldest:                                                          # BR-EX-02
            line_hit(ln, "EXPENSE_DATE_TOO_OLD", f"line date outside {oldest}..{on}")
        pol = pols[ln["expense_line_id"]] = resolve_expense_policy(ctx.policies, ln["category"], emp["country"], on)
        if pol is None:                                                                   # BR-EX-03
            line_hit(ln, "POLICY_NOT_APPLICABLE", f"no {ln['category']} policy for {emp['country']} on {on}")
            continue
        if ln["line_amount"] > pol["per_line_limit"]:                                     # BR-EX-04
            line_hit(ln, "LINE_LIMIT_EXCEEDED", f"above the per-line limit of {pol['expense_policy_id']}")
        if ln["line_amount"] >= pol["receipt_threshold"] and ln["receipt_id"] is None:    # BR-EX-06
            line_hit(ln, "MISSING_RECEIPT", "receipt required at or above the threshold")
    total = claim["total_amount"]
    top = top_line(lines)
    top_pol = pols.get(top["expense_line_id"])
    if top_pol is not None and total > top_pol["per_claim_limit"]:                        # BR-EX-05
        out.add("CLAIM_LIMIT_EXCEEDED", f"total {total} above {top_pol['per_claim_limit']} "
                                        f"({top_pol['expense_policy_id']})")
    if claim["expense_policy_id"] is not None:                                            # BR-EX-03 stored version
        ref = next((x for x in ctx.policies if x["expense_policy_id"] == claim["expense_policy_id"]), None)
        if ref is None or not (ref["effective_start"] <= on
                               and (ref["effective_end"] is None or on <= ref["effective_end"])):
            out.add("POLICY_VERSION_EXPIRED", f"{claim['expense_policy_id']} not effective on {on}")
    hashes = claim_hashes(lines, ctx.receipts)                                            # BR-EX-07 at submission
    for o in sorted(ctx.others, key=lambda o: o["expense_claim_id"]):
        if hashes & claim_hashes(o["lines"], ctx.receipts):
            code = "DUPLICATE_RECEIPT_SELF" if o["employee_id"] == claim["employee_id"] \
                else "DUPLICATE_RECEIPT_CROSS_EMPLOYEE"
            out.add(code, "receipt hash also on claim", o["expense_claim_id"])
    for ln in lines:                                                                      # BR-EX-08
        if ln["currency"] != claim["currency"]:
            line_hit(ln, "CURRENCY_MISMATCH", f"line currency differs from claim {claim['currency']}")
    if claim["currency"] != emp["currency"]:
        out.add("CURRENCY_MISMATCH", f"claim currency {claim['currency']} is not {emp['currency']}")
    cc = ctx.cost_center                                                                  # BR-EX-09
    if claim["cost_center_id"] is None:
        out.add("MISSING_COST_CENTER", "no cost center")
    elif cc is None or not cc["is_active"] or cc["effective_from"] > on \
            or (cc["effective_to"] is not None and on > cc["effective_to"]):
        out.add("INVALID_COST_CENTER", f"{claim['cost_center_id']} not active on {on}")
    usd, rate = to_usd(total, claim["currency"], ctx.fx, on)
    budget = None
    if ctx.budget is not None and claim["cost_center_id"] is not None:                    # BR-EX-10 / BR-BUD-01..03
        available = budget_available(ctx.budget, ctx.budget_ledger)
        budget = {"budget_id": ctx.budget["cost_center_budget_id"], "available": available, "requested": total}
        if available - total < 0:
            out.add("BUDGET_EXCEEDED", f"{ctx.budget['cost_center_budget_id']}: requested {total}, available "
                                       f"{available}")
    signature = (frozenset(ln["category"] for ln in lines), total, min(ln["expense_date"] for ln in lines))
    for o in sorted(ctx.others, key=lambda o: o["expense_claim_id"]):                     # BR-EX-12
        if o["employee_id"] == claim["employee_id"] and o["lines"] and signature == (
                frozenset(ln["category"] for ln in o["lines"]), o["total_amount"],
                min(ln["expense_date"] for ln in o["lines"])):
            out.add("DUPLICATE_CLAIM_PATTERN", "same categories, total and first date as claim", o["expense_claim_id"])
    if usd < p.split_threshold_usd:                                                       # BR-SPLIT-04 at submission
        pool = [(o["submitted_on"], o["submitted_at"], o["expense_claim_id"], o["usd"]) for o in ctx.others
                if o["employee_id"] == claim["employee_id"] and o.get("usd") is not None
                and o["usd"] < p.split_threshold_usd and o["primary_category"] == top["category"]]
        mine = (on, submitted_at, claim["expense_claim_id"], usd)
        group = next((g for g in split_groups(pool + [mine], p.split_window_days, p.split_threshold_usd)
                      if claim["expense_claim_id"] in g), None)
        if group:
            out.add("SPLIT_CLAIM_SUSPECTED", "suspected split claim, requires investigation, with "
                    + ", ".join(c for c in group if c != claim["expense_claim_id"]))

    results, approved = [], ZERO
    for ln in lines:
        pol, codes = pols.get(ln["expense_line_id"]), line_codes[ln["expense_line_id"]]
        if codes & LINE_FAIL_CODES:
            res = LineValidationResult.FAIL.value
        elif "LINE_LIMIT_EXCEEDED" in codes:
            res = LineValidationResult.CAPPED.value
        else:
            res = LineValidationResult.PASS.value
        if res != LineValidationResult.FAIL.value:
            approved += min(ln["line_amount"], pol["per_line_limit"])
        results.append(LineResult(ln["expense_line_id"], pol["expense_policy_id"] if pol else None, res,
                                  ", ".join(sorted(codes)) or None))
    required = [ln for ln in lines if pols.get(ln["expense_line_id"]) is not None
                and ln["line_amount"] >= pols[ln["expense_line_id"]]["receipt_threshold"]]
    receipt_status = (ReceiptStatus.MISSING.value if any(ln["receipt_id"] is None for ln in required)
                      else ReceiptStatus.COMPLETE.value if required else ReceiptStatus.NOT_REQUIRED.value)
    return ExpenseValidation(claim["expense_claim_id"], on, total, usd, rate, top["category"],
                             top_pol["expense_policy_id"] if top_pol else None, out.findings(), results,
                             money(approved), receipt_status, budget)


# --- submission ----------------------------------------------------------------------------------------------
@dataclass
class ExpenseSubmissionResult:
    claim_id: str
    submission_round: int
    submitted_at: datetime
    actor_id: str | None
    correlation_id: uuid.UUID
    validation: ExpenseValidation
    classification: Classification
    events: list[dict]
    budget_postings: list[dict]     # RESERVATION (+ RELEASE when rejected/returned), unnumbered
    routing: Routing | None = None  # None when not routed (rejected/returned, or a store without a router)
    steps: list[dict] = field(default_factory=list)   # approval_step rows (PENDING_APPROVAL only)
    changes: dict = field(default_factory=dict)       # resubmission: corrected claim columns and current_round
    idempotency: dict | None = None                   # resubmission: the completed idempotency_record
    audit_events: list[dict] = field(default_factory=list)   # one per transition (Phase 8)

    @property
    def status(self) -> str:
        return self.classification.status_after_validation

    @property
    def findings(self) -> list[Finding]:
        """Validation findings, then the routing finding (one request_exception row each)."""
        return self.validation.findings + (self.routing.findings if self.routing else [])

    @property
    def codes(self) -> list[str]:
        return [f.code for f in self.findings]


class ExpenseStore(Protocol):
    def load_claim(self, claim_id: str) -> dict: ...

    def context(self, claim: dict, on: date) -> ExpenseContext: ...

    def router(self) -> ApprovalRouter | None: ...

    def next_step_sequence(self, claim_id: str) -> int: ...

    def record_submission(self, result: ExpenseSubmissionResult) -> None: ...

    def idempotency(self, actor_id: str, key: str) -> dict | None: ...

    def all_lines(self, claim_id: str) -> list[dict]: ...

    def add_round_lines(self, claim: dict, lines: list[dict]) -> None: ...

    def record_audit(self, rows: list[dict]) -> None: ...


def budget_postings(claim: dict, v: ExpenseValidation, budget: dict | None, status: str) -> list[dict]:
    """BR-BUD-02/04: RESERVATION of the total on submission; RELEASE in the same transaction when the outcome
    is REJECTED or RETURNED_FOR_CORRECTION. Nothing without a cost center, a budget or an amount."""
    if budget is None or claim["cost_center_id"] is None or v.total <= 0:
        return []
    row = {"cost_center_id": claim["cost_center_id"], "cost_center_budget_id": budget["cost_center_budget_id"],
           "expense_claim_id": claim["expense_claim_id"], "amount": v.total, "currency": claim["currency"],
           "txn_date": v.submitted_on, "reason_code": None}
    rows = [{**row, "txn_type": BudgetTxnType.RESERVATION.value}]
    if status in RELEASED:
        rows.append({**row, "txn_type": BudgetTxnType.RELEASE.value, "reason_code": status})
    return rows


def submit_expense(store: ExpenseStore, claim_id: str, catalogue: ExceptionCatalogue, at: datetime,
                   actor_id: str | None, correlation_id: uuid.UUID, changes: dict | None = None,
                   new_lines: list[dict] | None = None, idempotency_key: str | None = None) -> ExpenseSubmissionResult:
    """docs/06 8.1 steps 2-5 and 7 for expense claims, in one store transaction. On a RETURNED_FOR_CORRECTION claim
    it is the resubmission of docs/06 8.3 (round + 1, `changes` to RESUBMIT_CLAIM_FIELDS, `new_lines`)."""
    stored = store.load_claim(claim_id)
    first = stored["workflow_status"]
    key, body, claim = None, None, stored
    if first == WorkflowStatus.DRAFT.value:
        if changes or new_lines is not None:
            raise ValueError("changes and new lines apply to a resubmission only")
    else:
        unknown = set(changes or {}) - RESUBMIT_CLAIM_FIELDS
        if unknown:
            raise ValueError(f"fields that cannot change on resubmission: {sorted(unknown)}")
        key = idempotency_key or resubmission_key(actor_id, claim_id, stored["current_round"] + 1)
        known = store.idempotency(actor_id, key)
        if known is not None:
            store.record_audit([audit_service.replay_event(RequestType.EXPENSE.value, claim_id, None, None, actor_id,
                                                           at, correlation_id, known["operation"])])
            raise IdempotentReplay(known)
        check_resubmission(stored, actor_id)
        body = {"request": claim_id, "changes": changes or {}, "lines": new_lines}
        lines = round_lines({**stored, **(changes or {})}, store.all_lines(claim_id), new_lines,
                            stored["current_round"] + 1)
        claim = {**stored, **(changes or {}), "current_round": stored["current_round"] + 1,
                 "total_amount": sum((ln["line_amount"] for ln in lines), ZERO)}
        store.add_round_lines(claim, lines)
    ctx = store.context(claim, at.date())
    v = validate_claim(claim, ctx, at)
    router = store.router()
    routing = None
    if router is not None and not catalogue.rejects_or_returns(v.codes):
        routing = router.route(RequestType.EXPENSE.value, claim["employee_id"], v.primary_category, v.usd, at.date())
    codes = v.codes + [f.code for f in (routing.findings if routing else [])]
    c = catalogue.classify(codes)
    path = [first, WorkflowStatus.SUBMITTED.value, WorkflowStatus.VALIDATING.value, c.status_after_validation]
    events = []
    for prev, new in zip(path, path[1:]):
        check_transition(prev, new)
        last = new == path[-1]
        events.append({"previous_status": prev, "new_status": new, "occurred_at": at,
                       "actor_id": actor_id if new == WorkflowStatus.SUBMITTED.value else None,
                       "reason_code": c.decision_reason_code if last else None,
                       "calculated_values": calculated_values(v, c, codes, routing) if last else None})
    steps = []
    if routing is not None and c.status_after_validation == WorkflowStatus.PENDING_APPROVAL.value:
        steps = build_steps(RequestType.EXPENSE.value, claim_id, claim["current_round"], routing, at,
                            store.next_step_sequence(claim_id))
    result = ExpenseSubmissionResult(claim_id, claim["current_round"], at, actor_id, correlation_id, v, c, events,
                                     budget_postings(claim, v, ctx.budget, c.status_after_validation), routing, steps)
    for posting in result.budget_postings:
        posting["posted_at"] = at
    if key is not None:
        result.changes = {**(changes or {}), "current_round": claim["current_round"],
                          "total_amount": claim["total_amount"]}
        result.idempotency = resubmission_record(actor_id, RequestType.EXPENSE.value, claim_id, key, body, at,
                                                 c.status_after_validation)
    result.audit_events = audit_service.submission_events(RequestType.EXPENSE.value, claim, result)
    store.record_submission(result)
    return result


def calculated_values(v: ExpenseValidation, c: Classification, codes: list[str], routing: Routing | None) -> dict:
    """Derived values on the outcome event (docs/06 7.1); decimals as text so the JSON is exact."""
    return {"total_amount": str(v.total), "amount_usd": str(v.usd), "fx_rate_used": str(v.rate),
            "primary_category": v.primary_category, "expense_policy_id": v.policy_id,
            "approved_amount_if_approved": str(v.approved_amount), "receipt_status": v.receipt_status,
            "lines": {r.expense_line_id: r.validation_result for r in v.lines},
            "budget": None if v.budget is None else {k: str(x) for k, x in v.budget.items()},
            "exception_codes": codes, "exception_class": c.exception_class,
            **(routing.as_values() if routing else {})}


def apply_to_claim(claim: dict, lines: list[dict], result: ExpenseSubmissionResult) -> None:
    """The column updates of a submission, shared by both stores. A stored expense_policy_id is kept (it is the
    version the claim referenced, checked by BR-EX-03); otherwise the primary category's version is stored."""
    v, c = result.validation, result.classification
    claim.update(result.changes)
    claim.update(workflow_status=c.status_after_validation, exception_class=c.exception_class,
                 decision_reason_code=c.decision_reason_code,
                 first_submitted_at=claim["first_submitted_at"] or result.submitted_at,
                 expense_policy_id=claim["expense_policy_id"] or v.policy_id, total_amount_usd=v.usd,
                 fx_rate_used=v.rate, receipt_status=v.receipt_status)
    by_id = {r.expense_line_id: r for r in v.lines}
    for ln in lines:
        r = by_id.get(ln["expense_line_id"])
        if r is not None:
            ln.update(expense_policy_id=r.expense_policy_id, validation_result=r.validation_result,
                      validation_detail=r.validation_detail)


# --- in-memory store -------------------------------------------------------------------------------------------
class InMemoryExpenseStore(InMemoryWorkflow, InMemoryReimbursements):
    """An ExpenseStore and WorkflowStore over plain rows (generator guard, S6 simulation, unit tests). Same contract
    as the DB store. `roles`: employee id -> role names (process-owner decisions)."""

    request_type = RequestType.EXPENSE.value

    def __init__(self, employees: dict[str, dict], policies: list[dict], fx: list[dict], cost_centers: list[dict],
                 budgets: list[dict], receipts: list[dict], budget_ledger: list[dict], params: DetectionParams,
                 router: ApprovalRouter | None = None, roles: dict[str, set[str]] | None = None) -> None:
        self.employees, self.policies, self.fx, self.params, self._router = employees, policies, fx, params, router
        self.cost_centers = {c["cost_center_id"]: c for c in cost_centers}
        self.budgets = budgets
        self.receipts = {r["receipt_id"]: r for r in receipts}
        self.budget_ledger = list(budget_ledger)
        self.claims: dict[str, dict] = {}
        self.lines: dict[str, list[dict]] = {}
        self.by_employee: dict[str, list[str]] = {}
        self.by_hash: dict[str, set[str]] = {}
        self.results: dict[str, ExpenseSubmissionResult] = {}
        self.status_events: list[dict] = []
        self.exceptions: list[dict] = []
        self.steps: dict[str, list[dict]] = {}
        self.approval_events: list[dict] = []
        self.init_workflow(roles)
        self.init_reimbursements()

    def router(self) -> ApprovalRouter | None:
        return self._router

    def load_request(self, request_id: str) -> dict:
        return self.claims[request_id]

    def all_lines(self, claim_id: str) -> list[dict]:
        return self.lines[claim_id]

    def add_round_lines(self, claim: dict, lines: list[dict]) -> None:
        self.lines[claim["expense_claim_id"]].extend(dict(ln) for ln in lines)

    # WorkflowStore (approval_service) -----------------------------------------------------------------------
    def routing_inputs(self, r: dict) -> tuple[str, Decimal, date]:
        """Primary category, USD total and the round's submission date (ASM-P7A-01)."""
        res = self.results[r["expense_claim_id"]]
        return res.validation.primary_category, res.validation.usd, res.submitted_at.date()

    def approval_effects(self, r: dict, at: datetime) -> tuple[dict, list[dict]]:
        lines = current_lines(r, self.lines[r["expense_claim_id"]])
        return {"approved_amount": approved_amount_of(lines, self.policies)}, []

    def release_postings(self, r: dict, at: datetime, reason: str) -> list[dict]:
        return release_postings(r, self.budget_ledger, at, reason)

    def override_postings(self, r: dict, at: datetime) -> list[dict]:
        return override_postings(r, self.budget_ledger, at)

    def post_decision_rows(self, res: DecisionResult) -> None:
        self.budget_ledger.extend(res.budget_postings)

    def completion_postings(self, claim: dict, amount: Decimal, at: datetime) -> list[dict]:
        return completion_postings(claim, self.budget_ledger, amount, at)

    def next_step_sequence(self, claim_id: str) -> int:
        return len(self.steps.get(claim_id, [])) + 1

    def add_claim(self, row: dict, lines: list[dict], status: str | None = None) -> dict:
        c = dict(row)
        if status is not None:
            c["workflow_status"] = status
            if status == WorkflowStatus.DRAFT.value:
                c["first_submitted_at"] = None
        cid = c["expense_claim_id"]
        self.claims[cid] = c
        self.lines[cid] = [dict(ln) for ln in lines]
        self.by_employee.setdefault(c["employee_id"], []).append(cid)
        return c

    def load_claim(self, claim_id: str) -> dict:
        return self.claims[claim_id]

    def budget_for(self, cost_center_id: str | None, on: date) -> dict | None:
        return next((b for b in self.budgets if b["cost_center_id"] == cost_center_id
                     and b["budget_period_start"] <= on <= b["budget_period_end"]), None)

    def other_view(self, cid: str) -> dict:
        c = self.claims[cid]
        res = self.results.get(cid)
        return {**c, "lines": current_lines(c, self.lines[cid]),
                "usd": res.validation.usd if res else None,
                "primary_category": res.validation.primary_category if res else None,
                "submitted_on": res.validation.submitted_on if res else None,
                "submitted_at": res.submitted_at if res else None}

    def context(self, claim: dict, on: date) -> ExpenseContext:
        cid = claim["expense_claim_id"]
        lines = current_lines(claim, self.lines[cid])
        related = set(self.by_employee.get(claim["employee_id"], []))
        for h in claim_hashes(lines, self.receipts):
            related |= self.by_hash.get(h, set())
        others = [self.other_view(i) for i in sorted(related - {cid})
                  if self.claims[i]["workflow_status"] != WorkflowStatus.DRAFT.value]
        budget = self.budget_for(claim["cost_center_id"], on)
        ledger = [t for t in self.budget_ledger
                  if budget is not None and t["cost_center_budget_id"] == budget["cost_center_budget_id"]]
        return ExpenseContext(self.employees[claim["employee_id"]], lines, self.receipts, self.policies, self.fx,
                              self.cost_centers.get(claim["cost_center_id"]), budget, ledger, others, self.params)

    def record_submission(self, result: ExpenseSubmissionResult) -> None:
        cid = result.claim_id
        claim = self.claims[cid]
        apply_to_claim(claim, self.lines[cid], result)
        self.results[cid] = result
        self.budget_ledger.extend(result.budget_postings)
        self.record_audit(result.audit_events)
        if result.idempotency is not None:
            self.record_idempotency(result.idempotency)
        for h in claim_hashes(current_lines(claim, self.lines[cid]), self.receipts):
            self.by_hash.setdefault(h, set()).add(cid)
        for e in result.events:
            self.status_events.append({"request_id": cid, "submission_round": result.submission_round,
                                       "correlation_id": result.correlation_id, **e})
        for f in result.findings:
            self.exceptions.append({"request_id": cid, "submission_round": result.submission_round,
                                    "exception_code": f.code, "detail": f.detail, "detected_at": result.submitted_at,
                                    "detected_by": "SUBMISSION", "correlation_id": result.correlation_id})
        if result.steps:
            self.steps.setdefault(cid, []).extend(dict(s) for s in result.steps)
            self.approval_events.append(assignment_event(result.steps[0], result.correlation_id))
