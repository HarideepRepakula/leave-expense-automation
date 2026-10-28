"""In-place editing toolkit for stage S5 (docs/07 section 7.1, AM-A1).

Anomaly and boundary injection only MODIFIES existing leave requests and expense claims; it never adds or removes
one, so the core volumes stay exact. Supporting rows follow the edited records and have their own counts:
receipts (created when a line needs one, removed for S05), USAGE ledger postings for legacy approvals (S01, S02).

Every derived value is recomputed through the shared services (calendar, policy resolution, accrual schedule) or
the same formulas S3/S4 use, so an edited record is internally consistent. After all edits `finalise()`
re-assigns the LVE/EXP ids in submission order (some edits move a submission timestamp), renumbers receipts and
the leave ledger, and returns the old-id -> new-id maps so labels can follow.

This module never reads or writes ground truth and never imports src/reference: what is planted is known by
construction; the independent oracle checks it later (DEC-01).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from src.common import ids
from src.common.enums import LeaveTxnType, ReceiptStatus, WorkflowStatus
from src.common.money import fx_rate_on, money
from src.data.stages import GenParams
from src.data.stages.balances import number_transactions
from src.data.stages.expenses import assignment_on, receipt_hash
from src.data.stages.leave import LeaveGuard, policy_family
from src.services.calendar_service import HolidayCalendar, quantity_by_year, requested_quantity
from src.services.leave_balance_service import accrual_schedule, usage_postings
from src.services.leave_batch import LEGACY_REASON
from src.services.leave_request_service import LEGACY_APPROVAL
from src.services.policy_resolver import resolve_version

ZERO = Decimal("0")
CENT = Decimal("0.01")


@dataclass
class Plant:
    """One planted record (or one member of a planted pair/group), known by construction."""
    scenario_id: str
    record_type: str            # LEAVE / EXPENSE
    record_id: str              # S3/S4 id; mapped to the final id after finalise()
    issue_type: str
    expected_codes: frozenset[str]
    detect: bool = True         # False for controls (expected negatives)
    behaviour: str = ""
    reason: str = ""
    group: str | None = None    # pair/group key for multi-record scenarios
    checks: dict = field(default_factory=dict)   # construction facts the oracle must reproduce


@dataclass
class Boundary:
    case_id: str                # BC-01 ... BC-10
    record_type: str
    record_id: str
    boundary_type: str
    expected_outcome: str
    expected_codes: frozenset[str] = frozenset()
    checks: dict = field(default_factory=dict)


class Workbench:
    def __init__(self, cfg: dict, p: GenParams, ds: dict[str, list[dict]], calendar: HolidayCalendar) -> None:
        self.cfg, self.p, self.ds, self.cal = cfg, p, ds, calendar
        self.det = cfg["expense_policies"]["detection"]
        self.emps = {e["employee_id"]: e for e in ds["employee"]}
        self.lpols = {x["leave_policy_id"]: x for x in ds["leave_policy"]}
        self.xpols = ds["expense_policy"]
        self.fx = ds["fx_rate"]
        self.leave = {r["leave_request_id"]: r for r in ds["leave_request"]}
        self.claims = {c["expense_claim_id"]: c for c in ds["expense_claim"]}
        self.lines: dict[str, list[dict]] = defaultdict(list)
        for ln in ds["expense_line"]:
            self.lines[ln["expense_claim_id"]].append(ln)
        for v in self.lines.values():
            v.sort(key=lambda ln: ln["line_number"])
        self.receipts = {r["receipt_id"]: r for r in ds["receipt"]}
        self.assignments: dict[str, list[dict]] = defaultdict(list)
        for a in ds["employee_cost_center_assignment"]:
            self.assignments[a["employee_id"]].append(a)
        self.opening: dict[str, Decimal] = defaultdict(Decimal)     # baseline OPENING per balance
        self.ledger: dict[str, list[tuple[date, Decimal]]] = defaultdict(list)   # OPENING + ACCRUAL
        for t in ds["leave_balance_transaction"]:
            self.ledger[t["leave_balance_id"]].append((t["txn_date"], t["quantity"]))
            if t["txn_type"] == LeaveTxnType.OPENING.value:
                self.opening[t["leave_balance_id"]] += t["quantity"]
        self.guard = LeaveGuard(cfg, p, ds["employee"], ds["leave_policy"], calendar, ds["leave_balance_transaction"],
                                ds["leave_balance"])
        self.taken: set[str] = set()               # records carrying a planted scenario, control or boundary
        self.locked: set[tuple[str, str]] = set()  # (LEAVE|EXPENSE, employee_id) whose records may not be edited
        self.legacy_approved: list[str] = []
        self.plants: list[Plant] = []
        self.boundaries: list[Boundary] = []
        self._new_receipts = 0

    # --- generic -------------------------------------------------------------------------------------------
    @staticmethod
    def sub_date(r: dict) -> date:
        return r["created_at"].date()

    def free(self, kind: str, rec: dict) -> bool:
        rid = rec["leave_request_id"] if kind == "LEAVE" else rec["expense_claim_id"]
        return (rid not in self.taken and rec["workflow_status"] != WorkflowStatus.DRAFT.value
                and (kind, rec["employee_id"]) not in self.locked)

    def take(self, kind: str, rid: str, *employees: str) -> None:
        self.taken.add(rid)
        for e in employees:
            self.locked.add((kind, e))

    def same_country(self, a: str, b: str) -> bool:
        return self.emps[a]["country"] == self.emps[b]["country"]

    def employed(self, emp_id: str, d: date) -> bool:
        e = self.emps[emp_id]
        return e["employment_start"] <= d and (e["employment_end"] is None or d <= e["employment_end"])

    def move_submission(self, rec: dict, new_date: date) -> None:
        ts: datetime = rec["created_at"]
        rec["created_at"] = datetime.combine(new_date, ts.timetz())
        if rec["first_submitted_at"] is not None:
            rec["first_submitted_at"] = rec["created_at"]

    # --- leave -----------------------------------------------------------------------------------------------
    def leave_of(self, emp_id: str) -> list[dict]:
        return [r for r in self.leave.values() if r["employee_id"] == emp_id]

    def leave_type(self, r: dict) -> str:
        return self.lpols[r["leave_policy_id"]]["leave_type"]

    def country_of(self, r: dict) -> str:
        return self.emps[r["employee_id"]]["country"]

    def set_leave_dates(self, r: dict, start: date, end: date, start_half: bool = False,
                        end_half: bool = False, medical_flag: bool | None = None) -> None:
        bd = self.cal.business_day_count(start, end, self.country_of(r))
        r.update(start_date=start, end_date=end, start_half_day=start_half, end_half_day=end_half,
                 business_day_count=Decimal(bd).quantize(Decimal("0.1")),
                 requested_quantity=requested_quantity(bd, start_half, end_half))
        limit = self.lpols[r["leave_policy_id"]]["requires_medical_cert_over_days"]
        r["medical_cert_flag"] = (limit is not None and r["requested_quantity"] > limit) if medical_flag is None \
            else medical_flag

    def set_leave_length(self, r: dict, start: date, n: int, **kw) -> None:
        self.set_leave_dates(r, start, self.cal.nth_business_day(start, n, self.country_of(r)), **kw)

    def reassign_leave(self, r: dict, emp_id: str) -> None:
        if not self.same_country(r["employee_id"], emp_id):
            raise ValueError("leave reassignment must keep the country (policy family)")
        family = policy_family(self.leave_type(r), self.emps[emp_id]["country"])
        r["employee_id"] = emp_id
        r["leave_policy_id"] = resolve_version(self.ds["leave_policy"], family, self.sub_date(r))["leave_policy_id"]

    def parts(self, r: dict) -> dict[int, Decimal]:
        return quantity_by_year(self.cal, r["start_date"], r["end_date"], self.country_of(r),
                                r["start_half_day"], r["end_half_day"])

    def posted(self, emp_id: str, policy_id: str, year: int, on: date) -> Decimal:
        """Posted OPENING + ACCRUAL of a balance on a date (the baseline ledger)."""
        lbal = ids.leave_balance_id(emp_id, policy_id, year)
        return sum((q for d, q in self.ledger.get(lbal, []) if d <= on), ZERO)

    def scheduled(self, emp_id: str, policy_id: str, year: int, on: date) -> Decimal:
        """Opening + accrual scheduled on or before a date, posted or not (BR-LBAL-03 schedule)."""
        e, pol = self.emps[emp_id], self.lpols[policy_id]
        accrued = sum((q for _, q in accrual_schedule(pol, e["employment_start"], e["employment_end"], year, on)),
                      ZERO)
        return self.opening[ids.leave_balance_id(emp_id, policy_id, year)] + accrued

    def consumed_before(self, r: dict, year: int) -> Decimal:
        """Quantity of the same balance taken by earlier submitted requests (clean baseline -> consuming)."""
        return sum((self.parts(o).get(year, ZERO) for o in self.leave_of(r["employee_id"])
                    if o is not r and o["leave_policy_id"] == r["leave_policy_id"] and o["workflow_status"] != "DRAFT"
                    and (o["created_at"], o["leave_request_id"]) < (r["created_at"], r["leave_request_id"])), ZERO)

    def last_on_balance(self, r: dict) -> bool:
        """No later submitted request of the same employee and policy touching the same years."""
        years = set(self.parts(r))
        return not any(
            o is not r and o["leave_policy_id"] == r["leave_policy_id"] and o["workflow_status"] != "DRAFT"
            and (o["created_at"], o["leave_request_id"]) > (r["created_at"], r["leave_request_id"])
            and years & set(self.parts(o))
            for o in self.leave_of(r["employee_id"]))

    def leave_guard(self, emp_id: str, expect: dict[str, set[str]] | None = None,
                    legacy: frozenset[str] = frozenset()) -> bool:
        """Validity guard for one employee after an edit (DEC-01, Phase 5): the leave services, replaying all of
        the employee's requests in submission order with the batch detectors, must find exactly `expect` on the
        planted records and nothing on any other. `legacy` ids are about to be forced APPROVED (S01, S02)."""
        return self.guard.ok(emp_id, self.leave_of(emp_id), expect, legacy)

    def approve_legacy(self, r: dict) -> None:
        r["workflow_status"] = WorkflowStatus.APPROVED.value
        r["decision_reason_code"] = LEGACY_APPROVAL     # raw-input marker of a legacy approval (DEC-P7B-02)
        self.legacy_approved.append(r["leave_request_id"])

    # --- expenses --------------------------------------------------------------------------------------------
    def rate(self, claim: dict) -> Decimal:
        return fx_rate_on(self.fx, "USD", claim["currency"], self.sub_date(claim))

    def usd(self, claim: dict) -> Decimal:
        return (claim["total_amount"] / self.rate(claim)).quantize(CENT, rounding=ROUND_HALF_UP)

    def local_for_usd(self, claim: dict, usd: Decimal) -> Decimal:
        return money(usd * self.rate(claim))

    def xpol(self, category: str, claim: dict) -> dict:
        return resolve_version(self.xpols, f"XPOL-{category}-{self.emps[claim['employee_id']]['country']}",
                               self.sub_date(claim))

    def top_line(self, claim: dict) -> dict:
        return sorted(self.lines[claim["expense_claim_id"]],
                      key=lambda ln: (-ln["line_amount"], ln["line_number"]))[0]

    def claim_limit(self, claim: dict) -> Decimal:
        return self.xpol(self.top_line(claim)["category"], claim)["per_claim_limit"]

    def claims_of(self, emp_id: str) -> list[dict]:
        return [c for c in self.claims.values() if c["employee_id"] == emp_id]

    def ensure_receipt(self, ln: dict, rng) -> None:
        if ln["receipt_id"] is not None:
            return
        self._new_receipts += 1
        rid = f"RCT-NEW-{self._new_receipts:06d}"      # renumbered in finalise()
        self.receipts[rid] = {"receipt_id": rid, "receipt_hash": "",
                              "merchant": ln["merchant_description"].split(" - ", 1)[-1],
                              "receipt_number": f"INV-{int(rng.integers(10_000_000, 100_000_000))}",
                              "receipt_date": ln["expense_date"], "amount": ln["line_amount"],
                              "currency": ln["currency"], "created_at": None}
        ln["receipt_id"] = rid
        self.sync_receipt(ln)

    def drop_receipt(self, ln: dict) -> None:
        del self.receipts[ln["receipt_id"]]
        ln["receipt_id"] = None
        self.refresh_claim(self.claims[ln["expense_claim_id"]])

    def sync_receipt(self, ln: dict) -> None:
        if ln["receipt_id"] is None:
            return
        r = self.receipts[ln["receipt_id"]]
        r.update(receipt_date=ln["expense_date"], amount=ln["line_amount"], currency=ln["currency"])
        r["receipt_hash"] = receipt_hash(r["merchant"], r["receipt_date"], r["amount"], r["currency"],
                                         r["receipt_number"])

    def set_line(self, ln: dict, rng=None, **changes) -> None:
        """Change a line's amount, date, category or currency; keep the receipt consistent and add one when
        the line reaches the receipt threshold (valid unless the scenario says otherwise)."""
        ln.update(changes)
        ln["line_amount"] = money(ln["line_amount"])
        # ASM-P6-02: keep quantity x unit = amount; the quantity stays when it divides the new amount exactly.
        q = int(ln["quantity"] or 1)
        q = q if int(ln["line_amount"] * 100) % q == 0 else 1
        ln["quantity"], ln["unit_amount"] = Decimal(q).quantize(CENT), money(ln["line_amount"] / q)
        claim = self.claims[ln["expense_claim_id"]]
        if rng is not None and ln["line_amount"] >= self.xpol(ln["category"], claim)["receipt_threshold"]:
            self.ensure_receipt(ln, rng)
        self.sync_receipt(ln)
        self.refresh_claim(claim)

    def refresh_claim(self, claim: dict) -> None:
        """Recompute the claim's derived raw fields exactly as S4 does (BR-EX-11, ASM-P3-08)."""
        cl = self.lines[claim["expense_claim_id"]]
        claim["total_amount"] = money(sum(ln["line_amount"] for ln in cl))
        claim["claim_period_start"] = min(ln["expense_date"] for ln in cl)
        claim["claim_period_end"] = max(ln["expense_date"] for ln in cl)
        required = [ln for ln in cl if ln["line_amount"] >= self.xpol(ln["category"], claim)["receipt_threshold"]]
        claim["receipt_status"] = (ReceiptStatus.MISSING.value if any(ln["receipt_id"] is None for ln in required)
                                   else ReceiptStatus.COMPLETE.value if required else ReceiptStatus.NOT_REQUIRED.value)

    def reassign_claim(self, claim: dict, emp_id: str) -> None:
        """Move a claim to another employee of the same country; cost center from the new assignment (DEC-13),
        falling back to the employee's default when no assignment covers the earliest line date."""
        if not self.same_country(claim["employee_id"], emp_id):
            raise ValueError("claim reassignment must keep the country and currency")
        claim["employee_id"] = emp_id
        self.refresh_claim(claim)
        claim["cost_center_id"] = assignment_on(self.assignments[emp_id], claim["claim_period_start"]) \
            or self.emps[emp_id]["default_cost_center_id"]

    def set_claim_total(self, claim: dict, target_local: Decimal, rng, allow_recategorise: bool = True) -> bool:
        """Scale line amounts so the total is exactly `target_local`, each line within its per-line limit
        (proportional to the limits). Lines may move to the highest-limit category when capacity is short.
        Returns False, leaving the claim unchanged, when impossible."""
        cl = self.lines[claim["expense_claim_id"]]
        cats = [ln["category"] for ln in cl]
        limits = [self.xpol(c, claim)["per_line_limit"] for c in cats]
        if sum(limits) < target_local and allow_recategorise:
            best = max(self.cfg["expense_policies"]["categories"],
                       key=lambda c: self.xpol(c, claim)["per_line_limit"])
            for i in range(len(cats)):
                if sum(limits) >= target_local:
                    break
                cats[i] = best
                limits[i] = self.xpol(best, claim)["per_line_limit"]
        if sum(limits) < target_local:
            return False
        ratio = target_local / sum(limits)
        amounts = [money(lim * ratio) for lim in limits]
        amounts[-1] = money(target_local - sum(amounts[:-1]))
        if any(a <= 0 or a > lim for a, lim in zip(amounts, limits)):
            return False
        labels = self.cfg["generation"]["expenses"]["merchant_labels"]
        for ln, cat, a in zip(cl, cats, amounts):
            if cat != ln["category"]:
                ln["merchant_description"] = f"{labels[cat][0]} - {ln['merchant_description'].split(' - ', 1)[-1]}"
            self.set_line(ln, rng, line_amount=a, category=cat)
        return True

    def split_safe(self, emp_id: str) -> bool:
        """Conservative guard: no two submitted claims of the employee within the split window with the same
        primary category and both below the threshold (a superset of every split group, BR-SPLIT-02)."""
        threshold = Decimal(self.det["split_threshold_usd"])
        window = int(self.det["split_window_days"])
        small = [(self.sub_date(c), self.top_line(c)["category"]) for c in self.claims_of(emp_id)
                 if c["workflow_status"] != "DRAFT" and self.usd(c) < threshold]
        return not any(a[1] == b[1] and abs((a[0] - b[0]).days) <= window - 1
                       for i, a in enumerate(small) for b in small[i + 1:])

    def lines_fit(self, claim: dict, emp_id: str, sub: date | None = None) -> bool:
        """All lines dated within employment, before submission and at most 90 days before it."""
        sub = sub or self.sub_date(claim)
        age = int(self.det["max_line_age_days"])
        return all(self.employed(emp_id, ln["expense_date"]) and ln["expense_date"] < sub
                   and (sub - ln["expense_date"]).days <= age for ln in self.lines[claim["expense_claim_id"]])

    # --- finalise ----------------------------------------------------------------------------------------------
    def finalise(self) -> tuple[dict[str, str], dict[str, str]]:
        """Re-derive ids in submission order (docs/07 section 3), rebuild receipts and the ledger."""
        leave_map = self._renumber(list(self.leave.values()), "leave_request_id", ids.leave_request_id)
        claim_map = self._renumber(list(self.claims.values()), "expense_claim_id", ids.expense_claim_id)
        lines, new_lines = [], {}
        for old, cl in self.lines.items():
            new = claim_map[old]
            for ln in cl:
                ln["expense_claim_id"] = new
                ln["expense_line_id"] = ids.expense_line_id(new, ln["line_number"])
                lines.append(ln)
            new_lines[new] = cl
        self.lines = defaultdict(list, new_lines)
        self.leave = {r["leave_request_id"]: r for r in self.leave.values()}
        self.claims = {c["expense_claim_id"]: c for c in self.claims.values()}
        receipts = []          # global counter in claim id order, then line number (as S4 assigns them)
        for cid in sorted(self.claims):
            for ln in self.lines[cid]:
                if ln["receipt_id"] is None:
                    continue
                r = self.receipts[ln["receipt_id"]]
                r["receipt_id"] = ln["receipt_id"] = ids.receipt_id(len(receipts) + 1)
                r["created_at"] = self.claims[cid]["created_at"]
                receipts.append(r)
        self.ds["leave_request"] = list(self.leave.values())
        self.ds["expense_claim"] = list(self.claims.values())
        self.ds["expense_line"] = lines
        self.ds["receipt"] = receipts
        self._post_legacy_usage(leave_map)
        return leave_map, claim_map

    @staticmethod
    def _renumber(rows: list[dict], pk: str, fmt) -> dict[str, str]:
        rows.sort(key=lambda r: (r["created_at"], r[pk]))
        counters: dict[int, int] = {}
        mapping = {}
        for r in rows:
            y = r["created_at"].year
            counters[y] = counters.get(y, 0) + 1
            mapping[r[pk]] = fmt(y, counters[y])
        for r in rows:
            r[pk] = mapping[r[pk]]
        return mapping

    def _post_legacy_usage(self, leave_map: dict[str, str]) -> None:
        """USAGE postings for legacy approvals, dated on the submission date (BR-LBAL-05; S01/S02, AM-A3)."""
        postings = [{k: t[k] for k in ("leave_balance_id", "leave_request_id", "txn_type", "quantity", "txn_date",
                                       "reason")} for t in self.ds["leave_balance_transaction"]]
        snapshots = {b["leave_balance_id"]: b for b in self.ds["leave_balance"]}
        for old in self.legacy_approved:
            r = self.leave[leave_map[old]]
            if self.leave_type(r) == "UNPAID":
                continue          # UNPAID has no balance and no ledger (ASM-047)
            for t in usage_postings(r, self.parts(r), self.sub_date(r), LEGACY_REASON):
                postings.append(t)
                snap = snapshots[t["leave_balance_id"]]
                snap["used"] = (snap["used"] - t["quantity"]).quantize(Decimal("0.1"))
                snap["available_balance"] = (snap["opening_balance"] + snap["accrued"] + snap["adjustments"]
                                             - snap["used"]).quantize(Decimal("0.1"))
        self.ds["leave_balance_transaction"] = number_transactions(postings)
