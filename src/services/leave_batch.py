"""Replay leave requests through the services in time order (docs/07 section 2, stage S6).

Used by the generator guards (S3, S5: DEC-01, one rule implementation), by stage S6 (with decisions), by
detections.csv and by the oracle comparison in src/evaluation. The replay itself never changes its input rows.

Rules of the replay (ASM-P5-04, Phase 7B):
- DRAFT requests are invisible.
- A legacy approval (S01/S02, ASM-P4-09: APPROVED with decision_reason_code LEGACY_APPROVAL, or an id in `legacy`)
  is not validated; its USAGE is posted on its submission date when its turn comes.
- Every other request is submitted as a DRAFT at its created_at instant through submit_leave(), whatever outcome a
  previous S6 run wrote on it (the raw-input view, DEC-P7B-02).
- Ledger rows other than USAGE, CARRY_FORWARD and CARRY_FORWARD_EXPIRY are loaded up front; those three are posted
  by the replay itself: USAGE at approval, carry-forward at 00:00 UTC on 1 January (year_end_postings).
- With a router (Phase 7A) every submission is also routed; with a DecisionTiming (Phase 7B, stage S6) the
  simulated decisions run too (workflow_simulation). Routing codes are part of codes() but not of
  submission_detections() (detections.csv holds validation findings and batch detectors only, DEC-P7A-04).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from src.common.enums import DetectedBy, LeaveTxnType, LeaveType, WorkflowStatus
from src.services.approval_routing import ApprovalRouter
from src.services.calendar_service import HolidayCalendar
from src.services.exception_service import ExceptionCatalogue
from src.services.leave_balance_service import usage_postings
from src.services.leave_detectors import Detection, negative_balance_unpermitted, overlapping_approved_leave
from src.services.leave_request_service import APPROVED, LEGACY_APPROVAL, InMemoryLeaveStore, is_legacy, leave_parts, \
    submit_leave
from src.services.workflow_simulation import SUBMIT, YEAR_END, DecisionDriver, DecisionTiming, EventQueue, \
    year_end_instants

LEGACY_REASON = "Legacy approval (pre-enforcement)"
REPLAY_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:lea:leave-replay")
POSTED_BY_REPLAY = frozenset({LeaveTxnType.USAGE.value, LeaveTxnType.CARRY_FORWARD.value,
                              LeaveTxnType.CARRY_FORWARD_EXPIRY.value})


@dataclass
class LeaveReplay:
    store: InMemoryLeaveStore
    legacy: list[str]
    detections: list[Detection]
    driver: DecisionDriver | None = None

    def codes(self, request_id: str) -> set[str]:
        """Submission codes (validation and routing) plus batch-detector codes of one request."""
        res = self.store.results.get(request_id)
        found = set(res.codes) if res else set()
        return found | {d.exception_code for d in self.detections if d.record_id == request_id}

    def submission_detections(self) -> list[Detection]:
        return [Detection("LEAVE", rid, f.code, DetectedBy.SUBMISSION.value, f.detail)
                for rid, res in sorted(self.store.results.items()) for f in res.validation.findings]


def replay_leave(requests: list[dict], employees: dict[str, dict], policies: dict[str, dict],
                 calendar: HolidayCalendar, ledger: list[dict], balances: list[dict], catalogue: ExceptionCatalogue,
                 legacy: frozenset[str] = frozenset(), router: ApprovalRouter | None = None,
                 timing: DecisionTiming | None = None, roles: dict[str, set[str]] | None = None) -> LeaveReplay:
    """`legacy`: extra request ids to treat as legacy approvals (the S5 guards use it before approving).
    `router`: route every submission (Phase 7A). `timing`: run the simulated decisions up to timing.as_of
    (Phase 7B, needs a router; `roles` gives the process owners their role)."""
    store = InMemoryLeaveStore(employees, policies, calendar,
                               [t for t in ledger if t["txn_type"] not in POSTED_BY_REPLAY], balances, router, roles)
    queue = EventQueue()
    driver = DecisionDriver(store, catalogue, timing, queue)
    done = []

    def submit(r: dict, at) -> None:
        rid = r["leave_request_id"]
        if is_legacy(r) or rid in legacy:
            row = store.add_request({**r, "decision_reason_code": LEGACY_APPROVAL}, APPROVED)
            if policies[r["leave_policy_id"]]["leave_type"] != LeaveType.UNPAID:   # ASM-047: no balance
                parts = leave_parts(calendar, row, employees[r["employee_id"]]["country"])
                store.post(usage_postings(row, parts, at.date(), LEGACY_REASON))
            done.append(rid)
            return
        store.add_request({**r, "current_round": 1, "decision_reason_code": None}, WorkflowStatus.DRAFT.value)
        submit_leave(store, rid, catalogue, at, r["employee_id"], uuid.uuid5(REPLAY_NAMESPACE, rid))
        driver.after(rid)

    def year_end(at) -> None:
        for (emp_id, pol_id), years in sorted(store.years.items()):
            if at.year in years:
                store.post(store.book(emp_id, pol_id).year_end_postings(at.year))

    for r in requests:
        if r["workflow_status"] != WorkflowStatus.DRAFT.value:
            queue.push(r["created_at"], SUBMIT, r["leave_request_id"], lambda at, r=r: submit(r, at))
    for at in year_end_instants({y for ys in store.years.values() for y in ys}, timing and timing.as_of):
        queue.push(at, YEAR_END, "", year_end)
    queue.run()
    reviewed = {frozenset((rid, other)) for rid, res in store.results.items() for f in res.validation.findings
                if f.code == "OVERLAPPING_PENDING_LEAVE" for other in f.other_request_ids}
    detections = (overlapping_approved_leave(list(store.requests.values()), reviewed)
                  + negative_balance_unpermitted(store))
    return LeaveReplay(store, done, sorted(detections, key=lambda d: (d.record_id, d.exception_code)), driver)
