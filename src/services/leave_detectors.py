"""Leave batch detectors over operational data (spec 13.1, docs/05 BR-LBAL-08 and BR-LV-10, DEC-P4-07).

- OVERLAPPING_APPROVED_LEAVE: two APPROVED requests of one employee whose dates intersect (EC-02). A pair whose
  overlap a process owner already reviewed and accepted (OVERLAPPING_PENDING_LEAVE at submission) is not flagged
  again (ASM-P4-07).
- NEGATIVE_BALANCE_UNPERMITTED: after a USAGE posting the balance of that year is below the policy floor (AM-A4b).
  The balance uses the same BalanceBook as validation, so requests that were still open when the usage was posted
  count as reserved (ASM-P5-05). A policy-permitted negative balance (AM-A4a) is not a finding.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.common.enums import DetectedBy, LeaveTxnType
from src.services.leave_balance_service import balance_year, negative_floor
from src.services.leave_request_service import APPROVED, InMemoryLeaveStore, overlaps


@dataclass(frozen=True)
class Detection:
    record_type: str
    record_id: str
    exception_code: str
    detected_by: str
    detail: str


def overlapping_approved_leave(requests: list[dict], reviewed: set[frozenset] = frozenset()) -> list[Detection]:
    approved: dict[str, list[dict]] = {}
    for r in sorted(requests, key=lambda r: r["leave_request_id"]):
        if r["workflow_status"] == APPROVED:
            approved.setdefault(r["employee_id"], []).append(r)
    found: dict[str, list[str]] = {}
    for reqs in approved.values():
        for i, a in enumerate(reqs):
            for b in reqs[i + 1:]:
                pair = frozenset((a["leave_request_id"], b["leave_request_id"]))
                if pair not in reviewed and overlaps(a, b):
                    found.setdefault(a["leave_request_id"], []).append(b["leave_request_id"])
                    found.setdefault(b["leave_request_id"], []).append(a["leave_request_id"])
    return [Detection("LEAVE", rid, "OVERLAPPING_APPROVED_LEAVE", DetectedBy.BATCH_DETECTOR.value,
                      f"approved dates intersect approved {', '.join(sorted(others))}")
            for rid, others in sorted(found.items())]


def negative_balance_unpermitted(store: InMemoryLeaveStore) -> list[Detection]:
    found: dict[str, list[str]] = {}
    for (emp_id, pol_id), rows in sorted(store.ledger.items()):
        usage = [t for t in rows if t["txn_type"] == LeaveTxnType.USAGE.value]
        if not usage:
            continue
        book = store.book(emp_id, pol_id)
        floor = negative_floor(store.policies[pol_id])
        for t in sorted(usage, key=lambda t: (t["txn_date"], t["leave_request_id"])):
            r = store.requests[t["leave_request_id"]]
            year = balance_year(t["leave_balance_id"])
            after = book.available(year, t["txn_date"], exclude=r["leave_request_id"],
                                   before=r["first_submitted_at"] or r["created_at"])
            if after < floor:
                found.setdefault(r["leave_request_id"], []).append(
                    f"{t['leave_balance_id']} {after} after usage on {t['txn_date']} (floor {floor})")
    return [Detection("LEAVE", rid, "NEGATIVE_BALANCE_UNPERMITTED", DetectedBy.BATCH_DETECTOR.value, "; ".join(d))
            for rid, d in sorted(found.items())]
