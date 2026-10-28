"""Expense batch detectors and the submission-order replay (docs/05 BR-EX-07, BR-SPLIT-03/04; DEC-P4-07).

Batch detectors over every submitted claim (drafts are invisible):
- DUPLICATE_RECEIPT_SELF / _CROSS_EMPLOYEE: one receipt hash on lines of different claims; every claim of the
  group is flagged, so the earlier claim of a pair is caught too (ASM-P4-08).
- SPLIT_CLAIM_SUSPECTED: maximal groups (BR-SPLIT-02) per employee and primary category; reported with exception
  class SUSPICIOUS_PATTERN as "suspected split claim, requires investigation" (AM-H3).

replay_expense() submits every non-draft claim as a DRAFT at its created_at instant through submit_expense(), in
time order, on an in-memory store (ASM-P6-01), whatever outcome a previous S6 run wrote on it (raw-input view,
DEC-P7B-02). The budget ledger starts empty: every cost_center_transaction row is posted by the replay itself
(stage S6 is the only source of them). With a router (Phase 7A) every submission is also routed; with a
DecisionTiming (Phase 7B) the simulated decisions run too (workflow_simulation). Routing codes are part of codes()
but not of submission_detections() (DEC-P7A-04).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from src.common.enums import DetectedBy, WorkflowStatus
from src.services.approval_routing import ApprovalRouter
from src.services.exception_service import ExceptionCatalogue
from src.services.expense_service import DetectionParams, InMemoryExpenseStore, claim_hashes, current_lines, \
    split_groups, submit_expense
from src.services.leave_detectors import Detection
from src.services.workflow_simulation import SUBMIT, DecisionDriver, DecisionTiming, EventQueue

REPLAY_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:lea:expense-replay")


def duplicate_receipts(store: InMemoryExpenseStore) -> list[Detection]:
    by_hash: dict[str, set[str]] = {}
    for cid in store.results:
        for h in claim_hashes(current_lines(store.claims[cid], store.lines[cid]), store.receipts):
            by_hash.setdefault(h, set()).add(cid)
    found: dict[tuple[str, str], set[str]] = {}
    for group in by_hash.values():
        for a in group:
            for b in group - {a}:
                same = store.claims[a]["employee_id"] == store.claims[b]["employee_id"]
                code = "DUPLICATE_RECEIPT_SELF" if same else "DUPLICATE_RECEIPT_CROSS_EMPLOYEE"
                found.setdefault((a, code), set()).add(b)
    return [Detection("EXPENSE", cid, code, DetectedBy.BATCH_DETECTOR.value,
                      f"receipt hash also on {', '.join(sorted(others))}")
            for (cid, code), others in sorted(found.items())]


def split_claims(store: InMemoryExpenseStore, params: DetectionParams) -> list[Detection]:
    pools: dict[tuple[str, str], list[tuple]] = {}
    for cid, res in store.results.items():
        v = res.validation
        if v.usd < params.split_threshold_usd:
            pools.setdefault((store.claims[cid]["employee_id"], v.primary_category), []).append(
                (v.submitted_on, res.submitted_at, cid, v.usd))
    out = []
    for key in sorted(pools):
        for group in split_groups(pools[key], params.split_window_days, params.split_threshold_usd):
            for cid in group:
                out.append(Detection("EXPENSE", cid, "SPLIT_CLAIM_SUSPECTED", DetectedBy.BATCH_DETECTOR.value,
                                     "suspected split claim, requires investigation: group "
                                     + ", ".join(sorted(group))))
    return out


@dataclass
class ExpenseReplay:
    store: InMemoryExpenseStore
    detections: list[Detection]
    driver: DecisionDriver | None = None

    def codes(self, claim_id: str) -> set[str]:
        res = self.store.results.get(claim_id)
        found = set(res.codes) if res else set()
        return found | {d.exception_code for d in self.detections if d.record_id == claim_id}

    def submission_detections(self) -> list[Detection]:
        return [Detection("EXPENSE", cid, f.code, DetectedBy.SUBMISSION.value, f.detail)
                for cid, res in sorted(self.store.results.items()) for f in res.validation.findings]


def replay_expense(tables: dict[str, list[dict]], catalogue: ExceptionCatalogue, params: DetectionParams,
                   claims: list[dict] | None = None, router: ApprovalRouter | None = None,
                   timing: DecisionTiming | None = None, roles: dict[str, set[str]] | None = None) -> ExpenseReplay:
    """`tables`: the ops tables (employee, expense_policy, fx_rate, cost_center, cost_center_budget, receipt,
    expense_line); `claims` defaults to tables["expense_claim"]; `router`: route every submission (Phase 7A);
    `timing`: run the simulated decisions up to timing.as_of (Phase 7B, needs a router and `roles`)."""
    store = InMemoryExpenseStore({e["employee_id"]: e for e in tables["employee"]}, tables["expense_policy"],
                                 tables["fx_rate"], tables["cost_center"], tables["cost_center_budget"],
                                 tables["receipt"], [], params, router, roles)
    lines: dict[str, list[dict]] = {}
    for ln in tables["expense_line"]:
        if ln["submission_round"] == 1:          # the dataset's raw lines (no resubmission in S6, ASM-P7B-06)
            lines.setdefault(ln["expense_claim_id"], []).append(ln)
    queue = EventQueue()
    driver = DecisionDriver(store, catalogue, timing, queue)

    def submit(c: dict, at) -> None:
        cid = c["expense_claim_id"]
        store.add_claim({**c, "current_round": 1, "decision_reason_code": None, "approved_amount": None},
                        lines.get(cid, []), WorkflowStatus.DRAFT.value)
        submit_expense(store, cid, catalogue, at, c["employee_id"], uuid.uuid5(REPLAY_NAMESPACE, cid))
        driver.after(cid)

    for c in (claims if claims is not None else tables["expense_claim"]):
        if c["workflow_status"] != WorkflowStatus.DRAFT.value:
            queue.push(c["created_at"], SUBMIT, c["expense_claim_id"], lambda at, c=c: submit(c, at))
    queue.run()
    detections = duplicate_receipts(store) + split_claims(store, params)
    return ExpenseReplay(store, sorted(detections, key=lambda d: (d.record_id, d.exception_code)), driver)
