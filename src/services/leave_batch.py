"""Replay leave requests through the Phase 5 services in submission order (docs/07 section 2, S6 order).

Used by the generator guards (S3, S5: DEC-01, one rule implementation), by detections.csv and by the oracle
comparison in src/evaluation. The replay never changes the dataset: requests stay SUBMITTED there until the
Phase 7 engine runs stage S6 (AMB-P3-01).

Rules of the replay (ASM-P5-04):
- DRAFT requests are invisible.
- An APPROVED request in the data is a legacy approval (S01/S02, ASM-P4-09): it is not validated; its USAGE is
  posted on its submission date when its turn comes (leave_balance_service.usage_postings).
- Every other request is submitted as a DRAFT at its created_at instant through submit_leave().
- Ledger rows other than USAGE are loaded up front; USAGE rows in the data are not, because the replay posts them.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from src.common.enums import DetectedBy, LeaveTxnType, LeaveType, WorkflowStatus
from src.services.calendar_service import HolidayCalendar
from src.services.exception_service import ExceptionCatalogue
from src.services.leave_balance_service import usage_postings
from src.services.leave_detectors import Detection, negative_balance_unpermitted, overlapping_approved_leave
from src.services.leave_request_service import APPROVED, InMemoryLeaveStore, leave_parts, submit_leave

LEGACY_REASON = "Legacy approval (pre-enforcement)"
REPLAY_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:lea:leave-replay")


@dataclass
class LeaveReplay:
    store: InMemoryLeaveStore
    legacy: list[str]
    detections: list[Detection]

    def codes(self, request_id: str) -> set[str]:
        """Submission codes plus batch-detector codes of one request."""
        res = self.store.results.get(request_id)
        found = set(res.validation.codes) if res else set()
        return found | {d.exception_code for d in self.detections if d.record_id == request_id}

    def submission_detections(self) -> list[Detection]:
        return [Detection("LEAVE", rid, f.code, DetectedBy.SUBMISSION.value, f.detail)
                for rid, res in sorted(self.store.results.items()) for f in res.validation.findings]


def replay_leave(requests: list[dict], employees: dict[str, dict], policies: dict[str, dict],
                 calendar: HolidayCalendar, ledger: list[dict], balances: list[dict], catalogue: ExceptionCatalogue,
                 legacy: frozenset[str] = frozenset()) -> LeaveReplay:
    """`legacy`: extra request ids to treat as legacy approvals (the S5 guards use it before approving)."""
    store = InMemoryLeaveStore(employees, policies, calendar,
                               [t for t in ledger if t["txn_type"] != LeaveTxnType.USAGE.value], balances)
    done = []
    for r in sorted((r for r in requests if r["workflow_status"] != WorkflowStatus.DRAFT.value),
                    key=lambda r: (r["created_at"], r["leave_request_id"])):
        rid = r["leave_request_id"]
        if r["workflow_status"] == APPROVED or rid in legacy:
            row = store.add_request(r, APPROVED)
            if policies[r["leave_policy_id"]]["leave_type"] != LeaveType.UNPAID:   # ASM-047: no balance
                parts = leave_parts(calendar, row, employees[r["employee_id"]]["country"])
                store.post(usage_postings(row, parts, r["created_at"].date(), LEGACY_REASON))
            done.append(rid)
            continue
        store.add_request(r, WorkflowStatus.DRAFT.value)
        submit_leave(store, rid, catalogue, r["created_at"], r["employee_id"], uuid.uuid5(REPLAY_NAMESPACE, rid))
    reviewed = {frozenset((rid, other)) for rid, res in store.results.items() for f in res.validation.findings
                if f.code == "OVERLAPPING_PENDING_LEAVE" for other in f.other_request_ids}
    detections = (overlapping_approved_leave(list(store.requests.values()), reviewed)
                  + negative_balance_unpermitted(store))
    return LeaveReplay(store, done, sorted(detections, key=lambda d: (d.record_id, d.exception_code)))
