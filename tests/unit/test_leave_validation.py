"""Leave request validation and submission (docs/05 sections 2 and 9, docs/06 section 2), the exception catalogue,
the request state machine and the leave batch detectors. World: tests/unit/leave_world.py. No database.

Balances used below (E1, IN annual, opening 4.0, 1.5 per month): submitted 10 Mar 2025 for leave starting in
March = 8.5; for leave starting in April = 10.0."""
from __future__ import annotations

import itertools
from datetime import date
from decimal import Decimal

import pytest

from src.common.enums import WorkflowStatus
from src.services.leave_batch import replay_leave
from src.services.leave_detectors import overlapping_approved_leave
from src.services.leave_request_service import LeaveInputError, LedgerMismatch, submit_leave
from src.services.lifecycle import REQUEST_TRANSITIONS, IllegalTransition, check_transition
from tests.unit.leave_world import (
    ANNUAL_GB,
    ANNUAL_IN,
    ANNUAL_US,
    CAL,
    CATALOGUE,
    E1,
    E2,
    E3,
    E4,
    E5,
    EMPLOYEES,
    POLICIES,
    SICK,
    UNPAID,
    at,
    ledger_and_balances,
    new_store,
    req,
    submit,
)

D = Decimal
MAR10 = at(2025, 3, 10)


def one(r: dict, when=MAR10, store=None):
    return submit(store or new_store(), r, when)


# --- the clean path and the three status events -----------------------------------------------------------------
def test_clean_request_ends_pending_approval_with_three_status_events():
    res = one(req("LVE-2025-000001", E1, ANNUAL_IN, date(2025, 3, 17), date(2025, 3, 21)))
    assert res.validation.codes == [] and res.status == "PENDING_APPROVAL"
    assert res.classification.exception_class == "NONE" and res.classification.decision_reason_code is None
    assert [(e["previous_status"], e["new_status"]) for e in res.events] == [
        ("DRAFT", "SUBMITTED"), ("SUBMITTED", "VALIDATING"), ("VALIDATING", "PENDING_APPROVAL")]
    assert [e["actor_id"] for e in res.events] == [E1, None, None]          # NULL actor = system
    cv = res.events[-1]["calculated_values"]
    assert cv["requested_quantity"] == "5.0" and cv["balances"]["2025"]["available"] == "8.5"


def test_store_records_status_exception_class_and_quantity():
    store = new_store()
    one(req("LVE-2025-000001", E1, SICK, date(2025, 3, 17), date(2025, 3, 20)), store=store)
    r = store.requests["LVE-2025-000001"]
    assert (r["workflow_status"], r["exception_class"], r["requested_quantity"]) == \
        ("RETURNED_FOR_CORRECTION", "POLICY_VIOLATION", D("4.0"))
    assert r["first_submitted_at"] == MAR10 and r["decision_reason_code"] == "MEDICAL_CERT_REQUIRED"
    assert [x["exception_code"] for x in store.exceptions] == ["MEDICAL_CERT_REQUIRED"]
    assert len(store.status_events) == 3


# --- one test per business code (docs/05 section 2) ------------------------------------------------------------
@pytest.mark.parametrize("r,when,code,status", [
    # BR-LV-01/02 employment: request dates before the joining date; submitted after the leaving date
    (req("X1", E3, ANNUAL_IN, date(2025, 3, 5), date(2025, 3, 11)), at(2025, 3, 1), "LEAVE_OUTSIDE_EMPLOYMENT",
     "REJECTED"),
    (req("X2", E4, ANNUAL_IN, date(2025, 10, 13), date(2025, 10, 14)), at(2025, 10, 6), "LEAVE_OUTSIDE_EMPLOYMENT",
     "REJECTED"),
    # BR-LV-04 policy for another country
    (req("X3", E1, ANNUAL_US, date(2025, 3, 17), date(2025, 3, 18)), MAR10, "POLICY_NOT_APPLICABLE", "REJECTED"),
    # BR-LV-05 version not effective on the submission date (GB V1 ended 30 Jun 2025)
    (req("X4", E5, ANNUAL_GB, date(2025, 8, 11), date(2025, 8, 12)), at(2025, 8, 1), "POLICY_VERSION_EXPIRED",
     "ESCALATED_FOR_REVIEW"),
    # BR-LV-07 half-day on a Saturday; only weekend days
    (req("X5", E1, ANNUAL_IN, date(2025, 3, 8), date(2025, 3, 12), sh=True), MAR10, "HALF_DAY_ON_NON_BUSINESS_DAY",
     "RETURNED_FOR_CORRECTION"),
    (req("X6", E1, ANNUAL_IN, date(2025, 3, 15), date(2025, 3, 16)), MAR10, "ZERO_BUSINESS_DAYS",
     "RETURNED_FOR_CORRECTION"),
    # BR-LV-08 9 days against 8.5
    (req("X7", E1, ANNUAL_IN, date(2025, 3, 17), date(2025, 3, 27)), MAR10, "INSUFFICIENT_BALANCE", "REJECTED"),
    # BR-LV-12 SICK 4 days without a certificate
    (req("X8", E1, SICK, date(2025, 3, 17), date(2025, 3, 20)), MAR10, "MEDICAL_CERT_REQUIRED",
     "RETURNED_FOR_CORRECTION"),
])
def test_each_leave_code(r, when, code, status):
    res = one(r, when)
    assert code in res.validation.codes, res.validation.codes
    assert res.status == status


def test_all_codes_are_recorded_and_the_highest_severity_decides():
    """docs/05 2 + 9.3: SICK 11 days, no certificate: HARD INSUFFICIENT_BALANCE and CORRECTABLE
    MEDICAL_CERT_REQUIRED are both recorded; HARD decides (REJECTED, reason = that code)."""
    res = one(req("X9", E1, SICK, date(2025, 3, 3), date(2025, 3, 17)))
    assert res.validation.codes == ["INSUFFICIENT_BALANCE", "MEDICAL_CERT_REQUIRED"]
    assert res.status == "REJECTED" and res.classification.decision_reason_code == "INSUFFICIENT_BALANCE"
    assert res.classification.exception_class == "POLICY_VIOLATION"


@pytest.mark.parametrize("end,cert,codes", [
    (date(2025, 3, 19), False, []),                         # 3 days: not above the limit
    (date(2025, 3, 20), True, []),                          # 4 days with a certificate
    (date(2025, 3, 20), False, ["MEDICAL_CERT_REQUIRED"]),
])
def test_medical_certificate_limit_is_exclusive(end, cert, codes):
    assert one(req("S1", E1, SICK, date(2025, 3, 17), end, cert=cert)).validation.codes == codes


# --- balance rules at submission (BR-LBAL-07..09) ----------------------------------------------------------------
def test_quantity_exactly_equal_to_the_balance_is_accepted():
    """BC-04: 9 business days minus a half day = 8.5 = available."""
    res = one(req("B1", E1, ANNUAL_IN, date(2025, 3, 17), date(2025, 3, 27), eh=True))
    assert res.validation.quantity == D("8.5") and res.validation.codes == []
    assert res.validation.balances[2025]["available"] == D("8.5")


@pytest.mark.parametrize("end,codes", [
    (date(2025, 3, 19), []),                           # 5 - 8 = -3, the permitted floor (AM-A4a)
    (date(2025, 3, 20), ["INSUFFICIENT_BALANCE"]),      # 5 - 9 = -4, below the floor
])
def test_negative_balance_permitted_only_within_the_limit(end, codes):
    assert one(req("U1", E2, ANNUAL_US, date(2025, 3, 10), end), at(2025, 3, 3)).validation.codes == codes


@pytest.mark.parametrize("eh,codes,parts", [
    (False, ["INSUFFICIENT_BALANCE"], {2025: D("3.0"), 2026: D("2.0")}),   # 2026 part 2.0 > Jan accrual 1.5
    (True, [], {2025: D("3.0"), 2026: D("1.5")}),                         # end half-day lands in 2026
])
def test_cross_year_request_checks_each_year_against_its_own_balance(eh, codes, parts):
    """BR-LBAL-09 (AMB-P3-02): submitted 10 Dec 2025; 2025 part against 2025 (22.0 available), 2026 part
    against 2026 = its scheduled 1 Jan accrual only (carry-forward unknown until 31 Dec)."""
    res = one(req("C1", E1, ANNUAL_IN, date(2025, 12, 29), date(2026, 1, 2), eh=eh), at(2025, 12, 10))
    assert res.validation.parts == parts and res.validation.codes == codes
    assert res.validation.balances[2025]["available"] == D("22.0")
    assert res.validation.balances[2026]["available"] == D("1.5")


def test_open_requests_reserve_balance_and_rejected_ones_do_not():
    store = new_store()
    first = one(req("R1", E1, ANNUAL_IN, date(2025, 4, 7), date(2025, 4, 11)), store=store)      # 5 of 10.0
    assert first.status == "PENDING_APPROVAL"
    second = one(req("R2", E1, ANNUAL_IN, date(2025, 4, 21), date(2025, 4, 28)), store=store)    # 6 > 10 - 5
    assert second.validation.codes == ["INSUFFICIENT_BALANCE"] and second.status == "REJECTED"
    third = one(req("R3", E1, ANNUAL_IN, date(2025, 4, 22), date(2025, 4, 28)), store=store)     # 5 <= 5
    assert third.validation.codes == []                       # R2 was rejected: it reserves nothing


def test_unpaid_yearly_cap_counts_holding_requests():
    """BR-LV-09: 20 + 11 = 31 > 30."""
    store = new_store()
    assert one(req("P1", E1, UNPAID, date(2025, 6, 2), date(2025, 6, 27)), store=store).validation.codes == []
    res = one(req("P2", E1, UNPAID, date(2025, 9, 1), date(2025, 9, 15)), store=store)
    assert res.validation.codes == ["UNPAID_LIMIT_EXCEEDED"] and res.status == "REJECTED"


# --- overlaps (BR-LV-10/11, ASM-008) -------------------------------------------------------------------------------
def _with(first_status: str, a: dict, b: dict):
    store = new_store()
    if first_status == "APPROVED":
        store.add_request({**a, "workflow_status": "APPROVED", "first_submitted_at": MAR10})
    else:
        one(a, store=store)
    return one(b, store=store)


@pytest.mark.parametrize("first_status,code,status", [
    ("APPROVED", "OVERLAPPING_APPROVED_LEAVE", "REJECTED"),
    ("PENDING", "OVERLAPPING_PENDING_LEAVE", "ESCALATED_FOR_REVIEW"),
])
def test_overlap_with_approved_and_with_pending_leave(first_status, code, status):
    a = req("O1", E1, ANNUAL_IN, date(2025, 4, 7), date(2025, 4, 11))
    b = req("O2", E1, SICK, date(2025, 4, 10), date(2025, 4, 14))          # any policy counts
    res = _with(first_status, a, b)
    assert res.validation.codes == [code] and res.status == status
    assert res.validation.findings[0].other_request_ids == ["O1"]


@pytest.mark.parametrize("a_end_half,b_start_half,codes", [
    (True, True, []),                                  # complementary half days on the shared date: no overlap
    (True, False, ["OVERLAPPING_PENDING_LEAVE"]),
    (False, True, ["OVERLAPPING_PENDING_LEAVE"]),
])
def test_shared_boundary_date_with_half_days(a_end_half, b_start_half, codes):
    a = req("H1", E1, ANNUAL_IN, date(2025, 4, 7), date(2025, 4, 9), eh=a_end_half)
    b = req("H2", E1, ANNUAL_IN, date(2025, 4, 9), date(2025, 4, 11), sh=b_start_half)
    assert _with("PENDING", a, b).validation.codes == codes


# --- input errors, technical failures and illegal transitions ------------------------------------------------------
@pytest.mark.parametrize("r", [
    req("I1", E1, ANNUAL_IN, date(2025, 3, 12), date(2025, 3, 10)),                     # end before start
    req("I2", E1, ANNUAL_IN, date(2025, 3, 12), date(2025, 3, 12), sh=True, eh=True),   # single day, two flags
])
def test_structurally_invalid_input_is_an_input_error(r):
    with pytest.raises(LeaveInputError):
        one(r)


def test_accrual_ledger_mismatch_is_a_technical_failure():
    """BR-LV-13: never a business code; the request stays a DRAFT."""
    store = new_store()
    rows = store.ledger[(E1, ANNUAL_IN)]
    rows.remove(next(t for t in rows if t["txn_type"] == "ACCRUAL" and t["txn_date"] == date(2025, 2, 1)))
    with pytest.raises(LedgerMismatch):
        one(req("L1", E1, ANNUAL_IN, date(2025, 3, 17), date(2025, 3, 18)), store=store)
    assert store.requests["L1"]["workflow_status"] == "DRAFT" and store.status_events == []


@pytest.mark.parametrize("status", ["PENDING_APPROVAL", "APPROVED", "REJECTED", "ESCALATED_FOR_REVIEW"])
def test_only_a_draft_can_be_submitted(status):
    """RETURNED_FOR_CORRECTION is a resubmission since Phase 7B (tests/unit/test_approval_decisions.py)."""
    store = new_store()
    store.add_request(req("N1", E1, ANNUAL_IN, date(2025, 3, 17), date(2025, 3, 18), status=status))
    with pytest.raises(IllegalTransition):
        submit_leave(store, "N1", CATALOGUE, MAR10, E1, None)


def test_transition_table_legal_and_illegal():
    """docs/06 2.2: every listed transition is legal, every other pair raises; terminal states have no exit."""
    statuses = [s.value for s in WorkflowStatus]
    for a, b in itertools.product(statuses, statuses):
        if (a, b) in REQUEST_TRANSITIONS:
            check_transition(a, b)
        else:
            with pytest.raises(IllegalTransition):
                check_transition(a, b)
    assert len(REQUEST_TRANSITIONS) == 18
    assert not [k for k in REQUEST_TRANSITIONS if k[0] in ("APPROVED", "REJECTED", "CANCELLED")]


# --- exception catalogue (docs/05 9.2/9.3) -----------------------------------------------------------------------
@pytest.mark.parametrize("codes,cls,status,reason", [
    ([], "NONE", "PENDING_APPROVAL", None),
    (["LINE_LIMIT_EXCEEDED"], "POLICY_VIOLATION", "PENDING_APPROVAL", None),             # INFO only
    (["CLAIM_LIMIT_EXCEEDED", "DUPLICATE_RECEIPT_CROSS_EMPLOYEE"], "SUSPICIOUS_PATTERN", "ESCALATED_FOR_REVIEW",
     "CLAIM_LIMIT_EXCEEDED"),                                                            # class tie-break
    (["MISSING_RECEIPT", "INSUFFICIENT_BALANCE"], "POLICY_VIOLATION", "REJECTED", "INSUFFICIENT_BALANCE"),
    (["ZERO_BUSINESS_DAYS", "HALF_DAY_ON_NON_BUSINESS_DAY"], "DATA_QUALITY", "RETURNED_FOR_CORRECTION",
     "ZERO_BUSINESS_DAYS"),                                                              # catalogue order
])
def test_classification(codes, cls, status, reason):
    c = CATALOGUE.classify(codes)
    assert (c.exception_class, c.status_after_validation, c.decision_reason_code) == (cls, status, reason)


def test_unknown_code_is_an_error():
    with pytest.raises(KeyError):
        CATALOGUE.classify(["NOT_A_CODE"])


# --- batch detectors and the replay (DEC-P4-07) -------------------------------------------------------------------
def _replay(requests: list[dict]):
    rows, balances = ledger_and_balances()
    return replay_leave(requests, EMPLOYEES, POLICIES, CAL, rows, balances, CATALOGUE)


def test_legacy_approval_beyond_the_floor_is_detected_and_permitted_negative_is_not():
    """AM-A4: E1 10 days against 8.5 with negatives forbidden -> NEGATIVE_BALANCE_UNPERMITTED; E2 8 days against
    5.0 with a -3 limit -> -3, permitted, not detected. Both are legacy approvals (USAGE posted on submission)."""
    rep = _replay([req("A1", E1, ANNUAL_IN, date(2025, 3, 17), date(2025, 3, 28), status="APPROVED", created=MAR10),
                   req("A2", E2, ANNUAL_US, date(2025, 3, 10), date(2025, 3, 19), status="APPROVED",
                       created=at(2025, 3, 3))])
    assert [(d.record_id, d.exception_code) for d in rep.detections] == [("A1", "NEGATIVE_BALANCE_UNPERMITTED")]
    assert "-1.5" in rep.detections[0].detail
    assert rep.legacy == ["A2", "A1"] and rep.codes("A2") == set()


def test_reservations_count_when_judging_a_legacy_usage():
    """ASM-P5-05: an earlier open request reserves 5 days, so a legacy 4 days on 8.5 goes below 0."""
    rep = _replay([req("P1", E1, ANNUAL_IN, date(2025, 3, 17), date(2025, 3, 21), status="SUBMITTED", created=MAR10),
                   req("A3", E1, ANNUAL_IN, date(2025, 3, 24), date(2025, 3, 27), status="APPROVED",
                       created=at(2025, 3, 10, 15))])
    assert rep.store.requests["P1"]["workflow_status"] == "PENDING_APPROVAL"
    assert rep.codes("A3") == {"NEGATIVE_BALANCE_UNPERMITTED"}


def test_overlapping_approved_pairs_are_detected_unless_reviewed():
    a = req("V1", E1, ANNUAL_IN, date(2025, 4, 7), date(2025, 4, 11), status="APPROVED")
    b = req("V2", E1, ANNUAL_IN, date(2025, 4, 10), date(2025, 4, 14), status="APPROVED")
    c = req("V3", E2, ANNUAL_US, date(2025, 4, 10), date(2025, 4, 14), status="APPROVED")   # other employee
    found = overlapping_approved_leave([a, b, c])
    assert [(d.record_id, d.exception_code) for d in found] == [("V1", "OVERLAPPING_APPROVED_LEAVE"),
                                                                ("V2", "OVERLAPPING_APPROVED_LEAVE")]
    assert overlapping_approved_leave([a, b, c], reviewed={frozenset(("V1", "V2"))}) == []
