"""Phase 3 baseline dataset: exact volumes, ID formats, keys, hierarchy, ledger and validity of every
generated request (CF-06: valid baseline first; anomalies only from Phase 4). No database needed."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.common.ids import ID_PATTERNS
from src.data.dataset import TABLE_ORDER, pk_columns, table
from src.data.stages.expenses import receipt_hash
from src.services.calendar_service import HolidayCalendar, requested_quantity
from src.services.policy_resolver import resolve_version

AS_OF = date(2026, 10, 22)
WINDOW_START = date(2025, 1, 1)
PK_ENTITY = {
    "department": "department", "cost_center": "cost_center", "cost_center_budget": "cost_center_budget",
    "employee": "employee", "employee_cost_center_assignment": "employee_cost_center_assignment",
    "country_holiday": "country_holiday", "fx_rate": "fx_rate", "delegation": "delegation",
    "leave_policy": "leave_policy", "expense_policy": "expense_policy", "approval_rule": "approval_rule",
    "role": "role", "application_user": "application_user", "leave_balance": "leave_balance",
    "leave_request": "leave_request", "leave_balance_transaction": "leave_balance_transaction",
    "receipt": "receipt", "expense_claim": "expense_claim", "expense_line": "expense_line",
}
GRADE_RANK = {f"G{i}": i for i in range(1, 8)}


def test_exact_core_volumes(run):
    _, vol, ds = run
    assert len(ds["employee"]) == vol["employees"]
    assert len(ds["leave_policy"]) == 6
    assert len(ds["leave_request"]) == vol["leave_requests"]
    assert len(ds["expense_claim"]) == vol["expense_claims"]


def test_fixed_master_volumes(run):
    _, _, ds = run
    assert (len(ds["department"]), len(ds["cost_center"]), len(ds["expense_policy"]),
            len(ds["approval_rule"]), len(ds["fx_rate"])) == (8, 24, 21, 8, 4)
    assert len(ds["cost_center_budget"]) == 48


def test_every_table_produced_and_non_empty(run):
    _, _, ds = run
    assert [t for t in TABLE_ORDER if not ds.get(t)] == []


def test_primary_keys_unique_and_well_formed(run):
    _, _, ds = run
    for name in TABLE_ORDER:
        keys = [tuple(r[k] for k in pk_columns(name)) for r in ds[name]]
        assert len(keys) == len(set(keys)), f"duplicate PK in {name}"
        if name in PK_ENTITY:
            rx = re.compile(ID_PATTERNS[PK_ENTITY[name]])
            bad = [k[0] for k in keys if not rx.match(k[0])]
            assert not bad, f"{name}: malformed ids {bad[:3]}"


def test_foreign_keys_resolve(run):
    """Every non-NULL FK value exists in the referenced table (spec 8: FKs reference exact IDs)."""
    _, _, ds = run
    for name in TABLE_ORDER:
        for fk in table(name).foreign_keys:
            target = fk.column.table.name
            values = {r[fk.column.name] for r in ds[target]}
            dangling = {r[fk.parent.name] for r in ds[name] if r[fk.parent.name] is not None} - values
            assert not dangling, f"{name}.{fk.parent.name} -> {target}: {sorted(dangling)[:3]}"


def test_id_years_and_counters(run):
    _, _, ds = run
    for name, pk in [("leave_request", "leave_request_id"), ("expense_claim", "expense_claim_id")]:
        ordered = sorted(ds[name], key=lambda r: r[pk])
        per_year = defaultdict(list)
        for r in ordered:
            assert int(r[pk][4:8]) == r["created_at"].year, "ID year = submission (creation) year (AM-A6)"
            per_year[r[pk][4:8]].append(r)
        for rows in per_year.values():
            assert [int(r[pk][-6:]) for r in rows] == list(range(1, len(rows) + 1)), "gap-free per year"
            ts = [r["created_at"] for r in rows]
            assert ts == sorted(ts), "counters follow submission order"
    emp = sorted(ds["employee"], key=lambda e: e["employee_id"])
    assert [e["employment_start"] for e in emp] == sorted(e["employment_start"] for e in emp), \
        "EMP ids in hire-date order"


def test_hierarchy_and_authority_structure(run):
    _, _, ds = run
    emps = {e["employee_id"]: e for e in ds["employee"]}
    roots = [e for e in emps.values() if e["manager_id"] is None]
    assert len(roots) == 1 and roots[0]["grade"] == "G7"
    assert sum(e["grade"] == "G7" for e in emps.values()) == 1
    for e in emps.values():
        if e["manager_id"]:
            assert GRADE_RANK[emps[e["manager_id"]]["grade"]] > GRADE_RANK[e["grade"]]
        depth, cur = 1, e
        while cur["manager_id"]:
            cur = emps[cur["manager_id"]]
            depth += 1
        assert depth <= 7
    controllers = [e for e in emps.values() if e["is_finance_controller"]]
    assert sorted(e["country"] for e in controllers) == ["GB", "IN", "US"]
    assert all(e["department_id"] == "DEPT-03" and e["grade"] in ("G5", "G6") for e in controllers)
    heads = {d["department_id"]: d["head_employee_id"] for d in ds["department"]}
    assert len(set(heads.values())) == 8
    for dept, head in heads.items():
        h = emps[head]
        assert h["is_department_head"] and h["department_id"] == dept
        assert h["grade"] == ("G7" if dept == "DEPT-03" else "G6")
        assert h["employment_end"] is None and h["employment_start"] < WINDOW_START
    assert sum(e["is_department_head"] for e in emps.values()) == 8


def test_employee_consistency(run):
    _, _, ds = run
    cur = {"IN": "INR", "US": "USD", "GB": "GBP"}
    ccs = {c["cost_center_id"]: c for c in ds["cost_center"]}
    emails = [e["email"] for e in ds["employee"]]
    assert len(emails) == len(set(emails))
    for e in ds["employee"]:
        assert e["currency"] == cur[e["country"]]
        cc = ccs[e["default_cost_center_id"]]
        assert (cc["department_id"], cc["country"]) == (e["department_id"], e["country"])
        assert (e["employment_status"] == "TERMINATED") == (e["employment_end"] is not None)
    assert ccs["CC-0024"]["cost_center_name"] == "Legal GB"


def test_country_and_grade_quotas_full_scale(full_run):
    emps = full_run[0]["employee"]
    assert Counter(e["country"] for e in emps) == {"IN": 200, "US": 120, "GB": 80}  # ASM-001
    assert Counter(e["employment_status"] for e in emps)["TERMINATED"] == 20         # ASM-026 (5%)


def test_ledger_reconciles_with_snapshots(run):
    """BR-LBAL-06: snapshot = ledger. Phase 3 has no usage or carry-forward yet."""
    _, _, ds = run
    sums = defaultdict(lambda: defaultdict(Decimal))
    for t in ds["leave_balance_transaction"]:
        sums[t["leave_balance_id"]][t["txn_type"]] += t["quantity"]
        assert t["quantity"] != 0 and t["leave_request_id"] is None
        assert t["transaction_id"][4:8] == str(t["txn_date"].year)
        assert t["txn_date"] <= AS_OF
    for b in ds["leave_balance"]:
        s = sums[b["leave_balance_id"]]
        assert b["opening_balance"] == s["OPENING"]
        assert b["accrued"] == s["ACCRUAL"]
        assert b["used"] == 0 and b["adjustments"] == 0
        assert b["available_balance"] == b["opening_balance"] + b["accrued"]
        if b["leave_year"] == 2026:
            assert b["opening_balance"] == 0  # carry-forward deferred to Phase 7 (AMB-P3-02)


@pytest.fixture()
def calendar(run):
    _, _, ds = run
    return HolidayCalendar.from_rows({"IN": [6, 7], "US": [6, 7], "GB": [6, 7]}, ds["country_holiday"])


def test_leave_requests_are_valid_baseline(run, calendar):
    _, _, ds = run
    emps = {e["employee_id"]: e for e in ds["employee"]}
    pols = {p["leave_policy_id"]: p for p in ds["leave_policy"]}
    by_emp = defaultdict(list)
    for r in ds["leave_request"]:
        e, pol = emps[r["employee_id"]], pols[r["leave_policy_id"]]
        assert pol["country_scope"] in (e["country"], "ALL")
        bd = calendar.business_day_count(r["start_date"], r["end_date"], e["country"])
        assert r["business_day_count"] == bd >= 1
        assert r["requested_quantity"] == requested_quantity(bd, r["start_half_day"], r["end_half_day"]) > 0
        assert calendar.is_business_day(r["start_date"], e["country"])
        assert calendar.is_business_day(r["end_date"], e["country"])
        assert e["employment_start"] <= r["start_date"]
        assert e["employment_end"] is None or r["end_date"] <= e["employment_end"]
        assert e["grade"] != "G7"
        assert r["exception_class"] == "NONE" and r["current_round"] == 1
        assert r["workflow_status"] in ("SUBMITTED", "DRAFT")
        assert (r["workflow_status"] == "DRAFT") == (r["first_submitted_at"] is None)
        submitted = r["created_at"].date()
        assert e["employment_start"] <= submitted < AS_OF
        if pol["leave_type"] == "SICK":
            assert r["medical_cert_flag"] == (r["requested_quantity"] > Decimal("3.0"))
            assert r["start_date"] >= submitted - timedelta(days=3)
        else:
            assert not r["medical_cert_flag"]
            assert r["start_date"] > submitted
        by_emp[r["employee_id"]].append(r)
    for reqs in by_emp.values():
        reqs.sort(key=lambda r: r["start_date"])
        for a, b in zip(reqs, reqs[1:]):
            assert a["end_date"] < b["start_date"], "no overlapping requests in the baseline"


def test_leave_balance_never_exceeded(run):
    """Conservative guard: all requests of a balance, in submission order, fit the ledger at that time."""
    _, _, ds = run
    ledger = defaultdict(list)
    for t in ds["leave_balance_transaction"]:
        ledger[t["leave_balance_id"]].append((t["txn_date"], t["quantity"]))
    pols = {p["leave_policy_id"]: p for p in ds["leave_policy"]}
    claims = defaultdict(list)
    unpaid = defaultdict(Decimal)
    for r in ds["leave_request"]:
        if pols[r["leave_policy_id"]]["leave_type"] == "UNPAID":
            unpaid[(r["employee_id"], r["start_date"].year)] += r["requested_quantity"]
            continue
        assert r["start_date"].year == r["end_date"].year, "only UNPAID may span leave years in Phase 3"
        lbal = f"LBAL-{r['employee_id']}-{r['leave_policy_id']}-{r['start_date'].year}"
        claims[lbal].append((r["created_at"], r["requested_quantity"]))
    for lbal, items in claims.items():
        used = Decimal("0")
        for ts, q in sorted(items):
            used += q
            assert sum(q2 for d, q2 in ledger[lbal] if d <= ts.date()) >= used, lbal
    assert all(v <= Decimal("30.0") for v in unpaid.values())


def test_expense_claims_are_valid_baseline(run):
    _, _, ds = run
    emps = {e["employee_id"]: e for e in ds["employee"]}
    receipts = {r["receipt_id"]: r for r in ds["receipt"]}
    pols = ds["expense_policy"]
    lines = defaultdict(list)
    for ln in ds["expense_line"]:
        lines[ln["expense_claim_id"]].append(ln)
    for c in ds["expense_claim"]:
        e = emps[c["employee_id"]]
        cl = sorted(lines[c["expense_claim_id"]], key=lambda ln: ln["line_number"])
        assert 1 <= len(cl) <= 10
        assert [ln["line_number"] for ln in cl] == list(range(1, len(cl) + 1))
        assert c["total_amount"] == sum(ln["line_amount"] for ln in cl)  # BR-EX-11
        assert c["country"] == e["country"] and c["currency"] == e["currency"]
        assert c["cost_center_id"] == e["default_cost_center_id"]
        assert c["claim_period_start"] == min(ln["expense_date"] for ln in cl)
        assert c["claim_period_end"] == max(ln["expense_date"] for ln in cl)
        assert c["exception_class"] == "NONE" and c["approved_amount"] is None
        assert (c["workflow_status"] == "DRAFT") == (c["first_submitted_at"] is None)
        sub = c["created_at"].date()
        required = False
        for ln in cl:
            assert ln["currency"] == c["currency"]
            assert sub - timedelta(days=90) <= ln["expense_date"] < sub
            assert e["employment_start"] <= ln["expense_date"]
            assert e["employment_end"] is None or ln["expense_date"] <= e["employment_end"]
            pol = resolve_version(pols, f"XPOL-{ln['category']}-{e['country']}", sub)
            assert ln["line_amount"] <= pol["per_line_limit"]
            if ln["line_amount"] >= pol["receipt_threshold"]:
                required = True
                assert ln["receipt_id"] is not None, "receipt required at or above threshold (BR-EX-06)"
            if ln["receipt_id"]:
                r = receipts[ln["receipt_id"]]
                assert (r["amount"], r["receipt_date"], r["currency"]) == (
                    ln["line_amount"], ln["expense_date"], ln["currency"])
                assert r["receipt_hash"] == receipt_hash(r["merchant"], r["receipt_date"], r["amount"],
                                                         r["currency"], r["receipt_number"])
        top = max(cl, key=lambda ln: ln["line_amount"])
        limit = resolve_version(pols, f"XPOL-{top['category']}-{e['country']}", sub)["per_claim_limit"]
        assert c["total_amount"] <= limit
        assert c["receipt_status"] == ("COMPLETE" if required else "NOT_REQUIRED")
    hashes = [r["receipt_hash"] for r in ds["receipt"]]
    assert len(hashes) == len(set(hashes)), "no duplicate receipt hashes in the baseline"


def test_expense_policy_limits_converted_once(full_run):
    """ASM-012: local limits = USD x 2025-01-01 rate, rounded to 10 INR / 1 USD / 1 GBP; MEALS V2 +10%."""
    pols = {p["expense_policy_id"]: p for p in full_run[0]["expense_policy"]}
    assert pols["XPOL-MEALS-IN-V1"]["per_line_limit"] == Decimal("6230.00")
    assert pols["XPOL-MEALS-IN-V1"]["receipt_threshold"] == Decimal("2080.00")
    assert pols["XPOL-TRAVEL-GB-V1"]["per_line_limit"] == Decimal("1185.00")
    assert pols["XPOL-MEALS-US-V2"]["per_line_limit"] == Decimal("83.00")
    assert pols["XPOL-MEALS-US-V1"]["effective_end"] == date(2025, 12, 31)
    assert pols["XPOL-TRAINING-IN-V1"]["per_claim_limit"] == Decimal("498000.00")


def test_users_and_roles(run):
    _, vol, ds = run
    assert len(ds["application_user"]) == vol["employees"] + 1
    roles = defaultdict(set)
    for ur in ds["user_role"]:
        roles[ur["user_id"]].add(ur["role_id"])
    assert all("ROLE-REQUESTER" in roles[u["user_id"]] for u in ds["application_user"] if u["employee_id"])
    assert sum("ROLE-PROCESS_OWNER" in r for r in roles.values()) == 2
    assert sum("ROLE-SYSTEM_ADMIN" in r for r in roles.values()) == 1
    assert all(u["password_hash"].startswith("$2b$04$") for u in ds["application_user"])


def test_delegations_valid(run):
    _, _, ds = run
    emps = {e["employee_id"]: e for e in ds["employee"]}
    for d in ds["delegation"]:
        a, g = emps[d["approver_id"]], emps[d["delegate_id"]]
        assert a["employment_end"] is None and g["employment_end"] is None
        assert GRADE_RANK[g["grade"]] >= GRADE_RANK[a["grade"]]
        assert 5 <= (d["effective_to"] - d["effective_from"]).days + 1 <= 20
        assert WINDOW_START <= d["effective_from"] and d["effective_to"] <= AS_OF
