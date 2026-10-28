"""S5 anomaly injection (docs/07 section 7, ASM-027, AM-A1/A2).

The `anomalies` RNG stream chooses which existing records receive which scenario and the scenario parameters.
Each chosen record is MODIFIED in place (never added); one record carries at most one planted scenario, and an
employee whose records were edited is locked against further edits so scenarios cannot interfere. A candidate
edit that would break the Phase 3 validity guards in an unintended way is rolled back and the next candidate is
tried. What was planted is recorded as `Plant` objects (known by construction, DEC-01); stage S9 turns them into
labels after the independent oracle has confirmed them.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

from src.common.money import money
from src.data.sampling import scaled_count
from src.data.stages import GenParams
from src.data.stages.workbench import Plant, Workbench

LEAVE, EXPENSE = "LEAVE", "EXPENSE"
USD_200 = Decimal("200.00")

ISSUE = {
    "S01": "NEGATIVE_BALANCE_UNPERMITTED", "S02": "OVERLAPPING_APPROVED_LEAVE", "S03": "INSUFFICIENT_BALANCE",
    "S19-L": "NO_VALID_APPROVAL_PATH", "S19-E": "NO_VALID_APPROVAL_PATH", "S22": "OVERLAPPING_PENDING_LEAVE",
    "S23": "MEDICAL_CERT_REQUIRED", "S05": "MISSING_RECEIPT", "S06a": "DUPLICATE_RECEIPT_SELF",
    "S06b": "DUPLICATE_RECEIPT_CROSS_EMPLOYEE", "S07a": "LINE_LIMIT_EXCEEDED", "S07b": "CLAIM_LIMIT_EXCEEDED",
    "S08": "EXPENSE_OUTSIDE_EMPLOYMENT", "S09": "SPLIT_CLAIM_SUSPECTED", "S10": "MISSING_COST_CENTER",
    "S15": "POLICY_VERSION_EXPIRED", "S21": "BUDGET_EXCEEDED", "S26": "CURRENCY_MISMATCH",
    "S01b": "PERMITTED_NEGATIVE_BALANCE", "S04": "WEEKEND_HOLIDAY_SPAN", "S14": "MULTI_LEVEL_ROUTE",
    "S14-L5": "MULTI_LEVEL_ROUTE", "S24": "DELEGATED_ROUTE",
}

BEHAVIOUR = {
    "S01": "Legacy APPROVED request kept; ledger detector flags the balance below the permitted floor (SOFT)",
    "S02": "Both legacy APPROVED requests kept; batch detector flags the overlap on both (no automatic change)",
    "S03": "REJECTED at validation (HARD INSUFFICIENT_BALANCE)",
    "S19-L": "ESCALATED_FOR_REVIEW (NO_VALID_APPROVAL_PATH: requester is the G7, no L1 exists)",
    "S19-E": "ESCALATED_FOR_REVIEW (NO_VALID_APPROVAL_PATH: requester is the G7, no L1 exists)",
    "S22": "ESCALATED_FOR_REVIEW; process owner approves, routing resumes",
    "S23": "RETURNED_FOR_CORRECTION (CORRECTABLE)",
    "S05": "RETURNED_FOR_CORRECTION (CORRECTABLE)",
    "S06a": "Later claim RETURNED_FOR_CORRECTION; batch detector flags both claims",
    "S06b": "Later claim ESCALATED_FOR_REVIEW then rejected by the process owner; batch detector flags both",
    "S07a": "Routes normally; approved amount capped at the per-line limit (INFO)",
    "S07b": "ESCALATED_FOR_REVIEW (SOFT)",
    "S08": "REJECTED at validation (HARD)",
    "S09": "Suspected split claim, requires investigation: flagged on every claim of the group (SOFT)",
    "S10": "ESCALATED_FOR_REVIEW; process owner returns it for a cost center",
    "S15": "ESCALATED_FOR_REVIEW; process owner approves, routing resumes",
    "S21": "ESCALATED_FOR_REVIEW; finance override approval path",
    "S26": "RETURNED_FOR_CORRECTION (CORRECTABLE)",
    "S01b": "Approved normally; negative balance within the policy limit is NOT an anomaly",
    "S04": "Quantity excludes weekend and holiday dates; routes normally (not an anomaly)",
    "S14": "Sequential approval steps per the expected route (not an anomaly)",
    "S14-L5": "Routes L1 -> L2 -> L4 -> L5 (amount above 5,000 USD; not an anomaly)",
    "S24": "L1 step assigned to the active delegate (not an anomaly)",
}


class Planter:
    """Shared candidate selection, rollback and recording for S5 anomalies and boundaries."""

    def __init__(self, cfg: dict, p: GenParams, wb: Workbench, rngs: dict) -> None:
        """rngs = {"LEAVE": Generator, "EXPENSE": Generator}: one independent stream per request type (AM-A8)."""
        self.cfg, self.p, self.wb, self.rngs = cfg, p, wb, rngs
        self.rng = rngs[LEAVE]
        self.a = cfg["generation"]["anomalies"]
        self.par = self.a["parameters"]

    def use(self, kind: str) -> None:
        """Every scenario draws only from the stream of the request type it edits."""
        self.rng = self.rngs[kind]

    def n_leave(self, full: int) -> int:
        return scaled_count(full, self.p.leave_requests, self.a["reference_volumes"]["leave"])

    def n_expense(self, full: int) -> int:
        return scaled_count(full, self.p.expense_claims, self.a["reference_volumes"]["expense"])

    def shuffled(self, items: list) -> list:
        return [items[int(i)] for i in self.rng.permutation(len(items))]

    def leave_cands(self, pred) -> list[dict]:
        return self.shuffled(sorted((r for r in self.wb.leave.values() if self.wb.free(LEAVE, r) and pred(r)),
                                    key=lambda r: r["leave_request_id"]))

    def claim_cands(self, pred) -> list[dict]:
        return self.shuffled(sorted((c for c in self.wb.claims.values() if self.wb.free(EXPENSE, c) and pred(c)),
                                    key=lambda c: c["expense_claim_id"]))

    def target_free(self, kind: str, emp_id: str) -> bool:
        return (kind, emp_id) not in self.wb.locked

    def pick(self, items: list):
        return items[self.int_between(0, len(items) - 1)]

    def attempt(self, leave_ids: list[str], claim_ids: list[str], edit) -> bool:
        """Run `edit()`; restore every touched record when it returns False."""
        wb = self.wb
        saved_leave = {i: dict(wb.leave[i]) for i in leave_ids}
        saved_claims = {i: (dict(wb.claims[i]), [dict(ln) for ln in wb.lines[i]]) for i in claim_ids}
        receipt_keys = set(wb.receipts)
        saved_receipts = {ln["receipt_id"]: dict(wb.receipts[ln["receipt_id"]])
                          for i in claim_ids for ln in wb.lines[i] if ln["receipt_id"]}
        counter = wb._new_receipts
        if edit():
            return True
        for i, row in saved_leave.items():
            wb.leave[i].clear()
            wb.leave[i].update(row)
        for i, (c, lines) in saved_claims.items():
            wb.claims[i].clear()
            wb.claims[i].update(c)
            for ln, old in zip(wb.lines[i], lines):
                ln.clear()
                ln.update(old)
        for k in set(wb.receipts) - receipt_keys:
            del wb.receipts[k]
        for k, row in saved_receipts.items():
            wb.receipts[k].clear()
            wb.receipts[k].update(row)
        wb._new_receipts = counter
        return False

    def plant(self, scenario: str, kind: str, rid: str, codes: set[str], reason: str,
              detect: bool = True, group: str | None = None, **checks) -> None:
        self.wb.plants.append(Plant(scenario, kind, rid, ISSUE[scenario], frozenset(codes), detect,
                                    BEHAVIOUR[scenario], reason, group, checks))

    def uniform_dec(self, lo: str, hi: str) -> Decimal:
        return Decimal(f"{self.rng.uniform(float(lo), float(hi)):.4f}")

    def int_between(self, lo: int, hi: int) -> int:
        return int(self.rng.integers(lo, hi + 1))


class Anomalies(Planter):
    def run(self) -> None:
        wb = self.wb
        self.root = next(e["employee_id"] for e in wb.emps.values() if e["grade"] == "G7")
        self.legal_gb = sorted(e["employee_id"] for e in wb.emps.values()
                               if e["default_cost_center_id"] == "CC-0024")
        for e in self.legal_gb:                       # CC-0024 is reserved for S21 (budget arithmetic)
            wb.locked.add((EXPENSE, e))
        lv, ex, ctl = self.a["leave"], self.a["expense"], self.a["controls"]
        # Leave scenarios draw only from the leave stream, expense scenarios only from the expense stream, so
        # one request volume never changes the other's plants. Scarcer constructions first in each.
        self.use(LEAVE)
        self.s19_leave(self.n_leave(lv["S19-L"]))
        self.s01(self.n_leave(lv["S01"]))
        self.s01b(self.n_leave(ctl["S01b"]))
        self.s03(self.n_leave(lv["S03"]))
        self.s02(self.n_leave(lv["S02"]))
        self.s22(self.n_leave(lv["S22"]))
        self.s23(self.n_leave(lv["S23"]))
        self.s24(LEAVE, self.n_leave(ctl["S24"]["leave"]))
        self.s04(self.n_leave(ctl["S04_min_total"]))
        self.use(EXPENSE)
        self.s21(self.n_expense(ex["S21"]))
        self.s19_expense(self.n_expense(ex["S19-E"]))
        self.s08(self.n_expense(ex["S08"]))
        self.s15(self.n_expense(ex["S15"]))
        self.s24(EXPENSE, self.n_expense(ctl["S24"]["expense"]))
        self.s09(self.n_expense(self.a["split_groups"]["pairs"]), self.n_expense(self.a["split_groups"]["triples"]))
        self.s06(self.n_expense(ex["S06a"]), self_employee=True)
        self.s06(self.n_expense(ex["S06b"]), self_employee=False)
        self.s14_l5(self.n_expense(ctl["S14-L5"]))
        self.s07b(self.n_expense(ex["S07b"]))
        self.s07a(self.n_expense(ex["S07a"]))
        self.s05(self.n_expense(ex["S05"]))
        self.s10(self.n_expense(ex["S10"]))
        self.s26(self.n_expense(ex["S26"]))

    # --- leave ---------------------------------------------------------------------------------------------
    def _single_year_2025(self, r: dict) -> bool:
        return self.wb.sub_date(r).year == 2025 and r["end_date"].year == 2025

    def _resize(self, scenario: str, n: int, pred, days_for, reason, codes: set[str], detect: bool = True) -> None:
        """Change the length of a request that is the last on its 2025 balance (S01, S01b, S03)."""
        wb = self.wb
        done = 0
        for r in self.leave_cands(lambda r: self._single_year_2025(r) and pred(r) and wb.last_on_balance(r)):
            if done == n:
                break
            emp, rid = r["employee_id"], r["leave_request_id"]
            days, avail = days_for(r)
            if days is None or days < 1:
                continue

            def edit():
                wb.set_leave_length(r, r["start_date"], days)
                # The services must find exactly the planted code (none for the S01b control); S01 is checked
                # as the legacy approval it is about to become.
                return r["end_date"].year == 2025 and wb.leave_guard(
                    emp, expect={rid: set(codes)}, legacy=frozenset({rid}) if scenario == "S01" else frozenset())

            if self.attempt([rid], [], edit):
                if scenario == "S01":
                    wb.approve_legacy(r)
                wb.take(LEAVE, rid, emp)
                self.plant(scenario, LEAVE, rid, codes, reason(days, avail), detect=detect)
                done += 1

    def s01(self, n: int) -> None:
        """2025 ANNUAL request on a policy that forbids negatives: quantity raised above the posted balance,
        then forced APPROVED as a legacy manual override with USAGE posted (docs/07 7.2)."""
        wb, (lo, hi) = self.wb, self.par["s01_excess_days"]

        def days_for(r):
            avail = wb.posted(r["employee_id"], r["leave_policy_id"], 2025, wb.sub_date(r)) - wb.consumed_before(r, 2025)
            return int(avail) + self.int_between(lo, hi), avail

        self._resize("S01", n, lambda r: wb.leave_type(r) == "ANNUAL"
                     and not wb.lpols[r["leave_policy_id"]]["negative_balance_allowed"], days_for,
                     lambda d, a: f"quantity raised to {d} days against {a} posted; forced legacy approval",
                     {"NEGATIVE_BALANCE_UNPERMITTED"})

    def s01b(self, n: int) -> None:
        """LPOL-ANNUAL-US (negative allowed to -3): quantity set so the balance after approval is -1..-3."""
        wb, (lo, hi) = self.wb, self.par["s01b_negative_days"]

        def days_for(r):
            on = max(wb.sub_date(r), r["start_date"])
            avail = wb.scheduled(r["employee_id"], r["leave_policy_id"], 2025, on) - wb.consumed_before(r, 2025)
            options = list(range(max(1, math.ceil(avail + lo)), math.floor(avail + hi) + 1))
            return (self.pick(options) if options else None), avail

        self._resize("S01b", n, lambda r: wb.leave_type(r) == "ANNUAL"
                     and wb.lpols[r["leave_policy_id"]]["negative_balance_allowed"], days_for,
                     lambda d, a: f"{d} days against {a} available: balance {a - d} after approval (limit -3)",
                     set(), detect=False)

    def s03(self, n: int) -> None:
        wb, (lo, hi) = self.wb, self.par["s03_excess_days"]

        def days_for(r):
            on = max(wb.sub_date(r), r["start_date"])
            avail = wb.scheduled(r["employee_id"], r["leave_policy_id"], 2025, on) - wb.consumed_before(r, 2025)
            return int(avail) + self.int_between(lo, hi), avail

        self._resize("S03", n, lambda r: wb.leave_type(r) in ("ANNUAL", "CASUAL")
                     and not wb.lpols[r["leave_policy_id"]]["negative_balance_allowed"], days_for,
                     lambda d, a: f"quantity raised to {d} days against {a} available (negative not allowed)",
                     {"INSUFFICIENT_BALANCE"})

    def _overlap_into(self, anchor: dict, moved: dict, same_year: bool, legacy: bool) -> bool:
        """Re-assign `moved` to the anchor's employee and re-date it to start inside the anchor's dates.
        legacy=True (S02): both become legacy approvals, so the batch detector must flag both; legacy=False (S22):
        the moved request must get OVERLAPPING_PENDING_LEAVE at submission and nothing else may change."""
        wb = self.wb
        emp = anchor["employee_id"]
        start = wb.cal.next_business_day(max(anchor["start_date"], wb.sub_date(moved) + timedelta(days=1)),
                                         wb.country_of(anchor))
        if start > anchor["end_date"] or not self.target_free(LEAVE, emp):
            return False
        n = int(moved["business_day_count"])
        pair = (anchor["leave_request_id"], moved["leave_request_id"])
        if legacy:
            expect, approved = {i: {"OVERLAPPING_APPROVED_LEAVE"} for i in pair}, frozenset(pair)
        else:
            expect, approved = {pair[1]: {"OVERLAPPING_PENDING_LEAVE"}}, frozenset()

        def edit():
            wb.reassign_leave(moved, emp)
            wb.set_leave_length(moved, start, n)
            return (not same_year or moved["end_date"].year == wb.sub_date(moved).year) \
                and wb.leave_guard(emp, expect=expect, legacy=approved)

        return self.attempt([moved["leave_request_id"]], [], edit)

    def s02(self, n: int) -> None:
        """Pairs: the second request moves to the anchor's employee and is re-dated to overlap; both are forced
        APPROVED as 2025 legacy rows (AM-A3: rows that predate service-layer enforcement)."""
        wb = self.wb
        done = 0
        for a in self.leave_cands(self._single_year_2025):
            if done == n:
                break
            if not wb.free(LEAVE, a):
                continue
            for b in self.leave_cands(lambda b: b is not a and self._single_year_2025(b)
                                      and wb.same_country(a["employee_id"], b["employee_id"])
                                      and wb.sub_date(b) < a["end_date"] and b["created_at"] > a["created_at"]):
                old_emp = b["employee_id"]
                if self._overlap_into(a, b, same_year=True, legacy=True):
                    group = f"S02-{done + 1:02d}"
                    for r in (a, b):
                        wb.approve_legacy(r)
                        wb.take(LEAVE, r["leave_request_id"], r["employee_id"], old_emp)
                        self.plant("S02", LEAVE, r["leave_request_id"], {"OVERLAPPING_APPROVED_LEAVE"},
                                   "pair re-dated to overlap; both forced legacy approvals", group=group)
                    done += 1
                    break

    def s22(self, n: int) -> None:
        """A request submitted shortly after a pending one moves to that employee and is re-dated to overlap it.
        Pairs are taken in order of the smallest submission gap (ASM-P4-06)."""
        wb = self.wb
        max_gap = timedelta(hours=self.par["s22_max_gap_hours"])
        reqs = sorted((r for r in wb.leave.values() if wb.free(LEAVE, r)),
                      key=lambda r: (r["created_at"], r["leave_request_id"]))
        pairs = []
        for i, first in enumerate(reqs):
            for r in reqs[i + 1:]:
                if r["created_at"] - first["created_at"] > max_gap:
                    break
                if r["created_at"] > first["created_at"] and wb.same_country(first["employee_id"], r["employee_id"]):
                    pairs.append((r["created_at"] - first["created_at"], first["leave_request_id"],
                                  r["leave_request_id"]))
        done = 0
        for _, pid, rid in sorted(pairs):
            if done == n:
                break
            first, r = wb.leave[pid], wb.leave[rid]
            if not (wb.free(LEAVE, first) and wb.free(LEAVE, r)):
                continue
            old_emp = r["employee_id"]
            if self._overlap_into(first, r, same_year=False, legacy=False):
                wb.take(LEAVE, pid, first["employee_id"])
                wb.take(LEAVE, rid, old_emp)
                self.plant("S22", LEAVE, rid, {"OVERLAPPING_PENDING_LEAVE"},
                           f"moved to {first['employee_id']} and re-dated to overlap pending {pid}", partner=pid)
                done += 1

    def s23(self, n: int) -> None:
        wb = self.wb
        done = 0
        for r in self.leave_cands(lambda r: wb.leave_type(r) == "SICK" and r["requested_quantity"] > Decimal("3.0")):
            if done == n:
                break
            r["medical_cert_flag"] = False
            wb.take(LEAVE, r["leave_request_id"], r["employee_id"])
            self.plant("S23", LEAVE, r["leave_request_id"], {"MEDICAL_CERT_REQUIRED"},
                       f"SICK {r['requested_quantity']} days with medical_cert_flag set to false")
            done += 1

    def s19_leave(self, n: int) -> None:
        """No valid approval path: the requester is the G7, so no L1 exists. Never "L1 is the G7", which
        resolves to one step (AMB-P3-03)."""
        wb = self.wb
        done = 0
        for r in self.leave_cands(lambda r: wb.same_country(r["employee_id"], self.root)
                                  and r["employee_id"] != self.root and r["requested_quantity"] <= Decimal("3.0")):
            if done == n:
                break
            old = r["employee_id"]

            def edit(r=r):
                wb.reassign_leave(r, self.root)
                return wb.leave_guard(self.root)

            if self.attempt([r["leave_request_id"]], [], edit):
                wb.take(LEAVE, r["leave_request_id"], old)
                self.plant("S19-L", LEAVE, r["leave_request_id"], {"NO_VALID_APPROVAL_PATH"},
                           "request re-assigned to the G7 (top of chain, no L1)")
                done += 1
        wb.locked.add((LEAVE, self.root))

    def s24(self, kind: str, n: int) -> None:
        """Delegated route: the requester's manager has an active delegation on the submission date. Run once
        for leave and once for expenses, each with its own stream."""
        wb = self.wb
        reports: dict[str, list[str]] = {}
        for e in sorted(wb.emps.values(), key=lambda e: e["employee_id"]):
            if e["manager_id"]:
                reports.setdefault(e["manager_id"], []).append(e["employee_id"])
        n_leave, n_expense = (n, 0) if kind == LEAVE else (0, n)
        done_l = done_e = 0
        for d in self.shuffled(sorted(wb.ds["delegation"], key=lambda d: d["delegation_id"])):
            def in_window(rec, d=d):
                return d["effective_from"] <= wb.sub_date(rec) <= d["effective_to"]

            for emp_id in reports.get(d["approver_id"], []):
                if done_l < n_leave and self.target_free(LEAVE, emp_id):
                    for r in self.leave_cands(lambda r: in_window(r) and wb.same_country(r["employee_id"], emp_id)
                                              and r["employee_id"] != emp_id):
                        old = r["employee_id"]

                        def edit(r=r):
                            wb.reassign_leave(r, emp_id)
                            return wb.leave_guard(emp_id)

                        if self.attempt([r["leave_request_id"]], [], edit):
                            wb.take(LEAVE, r["leave_request_id"], emp_id, old)
                            self.plant("S24", LEAVE, r["leave_request_id"], set(),
                                       f"re-assigned to a report of {d['approver_id']} during {d['delegation_id']}",
                                       detect=False, delegated_from=d["approver_id"])
                            done_l += 1
                            break
                if done_e < n_expense and self.target_free(EXPENSE, emp_id):
                    for c in self.claim_cands(lambda c: in_window(c) and wb.same_country(c["employee_id"], emp_id)
                                              and c["employee_id"] != emp_id and wb.usd(c) >= USD_200
                                              and wb.lines_fit(c, emp_id)):
                        old = c["employee_id"]
                        wb.reassign_claim(c, emp_id)
                        wb.take(EXPENSE, c["expense_claim_id"], emp_id, old)
                        self.plant("S24", EXPENSE, c["expense_claim_id"], set(),
                                   f"re-assigned to a report of {d['approver_id']} during {d['delegation_id']}",
                                   detect=False, delegated_from=d["approver_id"])
                        done_e += 1
                        break

    def s04(self, min_total: int) -> None:
        """Ensure at least `min_total` submitted leave requests span a public holiday: move the start to the
        second business day before a holiday, keeping the business-day count (docs/07 7.2 Group B)."""
        wb = self.wb
        holidays = sorted((h["country"], h["holiday_date"]) for h in wb.ds["country_holiday"])

        def spans(r):
            c = wb.country_of(r)
            return any(wb.cal.is_holiday(r["start_date"] + timedelta(days=i), c)
                       for i in range((r["end_date"] - r["start_date"]).days + 1))

        have = sum(1 for r in wb.leave.values() if r["workflow_status"] != "DRAFT" and spans(r))
        for r in self.leave_cands(lambda r: r["business_day_count"] >= 3 and not spans(r)):
            if have >= min_total:
                break
            c, sub = wb.country_of(r), wb.sub_date(r)
            n = int(r["business_day_count"])
            for country, h in holidays:
                if country != c or not (sub + timedelta(days=3) <= h <= sub + timedelta(days=60)) \
                        or h.year != sub.year or h.isoweekday() >= 6:
                    continue
                start = h
                for _ in range(2):
                    start -= timedelta(days=1)
                    while not wb.cal.is_business_day(start, c):
                        start -= timedelta(days=1)
                if start <= sub:
                    continue

                def edit(start=start):
                    wb.set_leave_length(r, start, n)
                    return r["end_date"].year == sub.year and wb.leave_guard(r["employee_id"])

                if self.attempt([r["leave_request_id"]], [], edit):
                    wb.take(LEAVE, r["leave_request_id"], r["employee_id"])
                    self.plant("S04", LEAVE, r["leave_request_id"], set(),
                               f"start moved to {start}, two business days before holiday {h}", detect=False)
                    have += 1
                    break

    # --- expenses ------------------------------------------------------------------------------------------
    def s19_expense(self, n: int) -> None:
        wb = self.wb
        done = 0
        for c in self.claim_cands(lambda c: wb.same_country(c["employee_id"], self.root)
                                  and wb.usd(c) >= USD_200 and wb.lines_fit(c, self.root)):
            if done == n:
                break
            old = c["employee_id"]
            wb.reassign_claim(c, self.root)
            wb.take(EXPENSE, c["expense_claim_id"], old)
            self.plant("S19-E", EXPENSE, c["expense_claim_id"], {"NO_VALID_APPROVAL_PATH"},
                       "claim re-assigned to the G7 (top of chain, no L1)")
            done += 1
        wb.locked.add((EXPENSE, self.root))

    def s08(self, n: int) -> None:
        """Claim moved to a terminated employee of the same country; its latest line is dated after the
        employment end date (the claim is submitted after leaving)."""
        wb = self.wb
        terminated = sorted(e["employee_id"] for e in wb.emps.values() if e["employment_end"] is not None)
        done = 0
        for c in self.claim_cands(lambda c: wb.usd(c) >= USD_200):
            if done == n:
                break
            sub = wb.sub_date(c)
            options = [t for t in terminated if self.target_free(EXPENSE, t) and wb.same_country(t, c["employee_id"])
                       and sub - timedelta(days=85) <= wb.emps[t]["employment_end"] <= sub - timedelta(days=2)]
            if not options:
                continue
            t = self.pick(options)
            end = wb.emps[t]["employment_end"]
            lines = wb.lines[c["expense_claim_id"]]
            latest = max(lines, key=lambda ln: (ln["expense_date"], ln["line_number"]))
            after = end + timedelta(days=self.int_between(1, (sub - end).days - 1))
            floor = max(wb.emps[t]["employment_start"], sub - timedelta(days=90))
            old = c["employee_id"]
            for ln in lines:
                wb.set_line(ln, expense_date=after if ln is latest else min(max(ln["expense_date"], floor), after))
            wb.reassign_claim(c, t)
            wb.take(EXPENSE, c["expense_claim_id"], t, old)
            self.plant("S08", EXPENSE, c["expense_claim_id"], {"EXPENSE_OUTSIDE_EMPLOYMENT"},
                       f"re-assigned to terminated {t} (end {end}); line dated {after}")
            done += 1

    def s15(self, n: int) -> None:
        wb = self.wb
        done = 0
        for c in self.claim_cands(lambda c: wb.sub_date(c).year == 2026 and wb.top_line(c)["category"] == "MEALS"):
            if done == n:
                break
            c["expense_policy_id"] = f"XPOL-MEALS-{c['country']}-V1"
            wb.take(EXPENSE, c["expense_claim_id"], c["employee_id"])
            self.plant("S15", EXPENSE, c["expense_claim_id"], {"POLICY_VERSION_EXPIRED"},
                       f"references superseded {c['expense_policy_id']} (ended 2025-12-31)")
            done += 1

    def s21(self, n: int) -> None:
        """Budget exceeded on CC-0024 (budget fixed at 8,000 USD-equivalent, ASM-016). The first planted claim is
        scaled so its reservation crosses the remaining budget; every later planted claim then exceeds too.
        Baseline CC-0024 claims after the crossing become natural BUDGET_EXCEEDED cases (docs/07 7.4)."""
        wb = self.wb
        for year in (2026, 2025):
            budget = next(b for b in wb.ds["cost_center_budget"]
                          if b["cost_center_id"] == "CC-0024" and b["budget_period_start"].year == year)
            baseline = [(c["created_at"], c["total_amount"]) for c in wb.claims.values()
                        if c["cost_center_id"] == "CC-0024" and c["workflow_status"] != "DRAFT"
                        and wb.sub_date(c).year == year]
            pool = sorted((c for c in wb.claims.values() if wb.free(EXPENSE, c) and c["country"] == "GB"
                           and wb.sub_date(c).year == year and wb.usd(c) >= USD_200),
                          key=lambda c: (c["created_at"], c["expense_claim_id"]))
            for first in reversed([c for c in pool if len(wb.lines[c["expense_claim_id"]]) >= 3]):
                followers = [c for c in pool if c["created_at"] > first["created_at"]]
                if len(followers) < n - 1:
                    continue
                targets = [e for e in self.legal_gb if wb.lines_fit(first, e)]
                if not targets:
                    continue
                emp = self.pick(targets)
                cum = sum((t for ts, t in baseline if ts < first["created_at"]), Decimal("0"))
                target_total = money(budget["budget_amount"] - cum + budget["budget_amount"] * Decimal("0.02"))

                def edit():
                    wb.reassign_claim(first, emp)
                    if target_total > first["total_amount"] and not wb.set_claim_total(first, target_total, self.rng):
                        return False
                    return first["total_amount"] <= wb.claim_limit(first) and first["cost_center_id"] == "CC-0024"

                old = first["employee_id"]
                if not self.attempt([], [first["expense_claim_id"]], edit):
                    continue
                wb.take(EXPENSE, first["expense_claim_id"], old)
                chosen = [first]
                for c in self.shuffled(followers):
                    if len(chosen) == n:
                        break
                    fits = [e for e in self.legal_gb if wb.lines_fit(c, e)]
                    if fits:
                        o = c["employee_id"]
                        wb.reassign_claim(c, self.pick(fits))
                        wb.take(EXPENSE, c["expense_claim_id"], o)
                        chosen.append(c)
                for c in chosen:
                    self.plant("S21", EXPENSE, c["expense_claim_id"], {"BUDGET_EXCEEDED"},
                               f"re-assigned to a Legal GB employee: CC-0024 {year} reservation exceeds the budget")
                return

    def s09(self, pairs: int, triples: int) -> None:
        """Split groups: claims of one category, each below 200 USD, moved to one employee and re-dated so all
        submission dates fall within the 7-day window and the group sum reaches 200 USD (BR-SPLIT-02)."""
        wb = self.wb
        threshold = Decimal(wb.det["split_threshold_usd"])
        window = int(wb.det["split_window_days"])
        groups_done = 0
        for size, wanted in ((2, pairs), (3, triples)):
            done = 0
            for a in self.claim_cands(lambda c: wb.usd(c) < threshold):
                if done == wanted:
                    break
                if not wb.free(EXPENSE, a):
                    continue
                emp, cat, a_sub = a["employee_id"], wb.top_line(a)["category"], wb.sub_date(a)
                offsets = sorted(int(x) for x in self.rng.choice(list(range(1, window)), size=size - 1, replace=False))
                partners: list[tuple[dict, date]] = []
                total = wb.usd(a)
                for off in offsets:
                    new_sub = a_sub + timedelta(days=off)
                    if new_sub.year != a_sub.year or new_sub >= self.p.as_of or not wb.employed(emp, new_sub):
                        break
                    for b in self.claim_cands(lambda b: b is not a and all(b is not x for x, _ in partners)
                                              and wb.same_country(b["employee_id"], emp)
                                              and wb.sub_date(b).year == a_sub.year
                                              and wb.top_line(b)["category"] == cat and wb.usd(b) < threshold
                                              and wb.lines_fit(b, emp, new_sub)):
                        partners.append((b, new_sub))
                        total += wb.usd(b)
                        break
                if len(partners) != size - 1 or total < threshold:
                    continue
                if any(c is not a and c["workflow_status"] != "DRAFT" and wb.top_line(c)["category"] == cat
                       and wb.usd(c) < threshold and abs((wb.sub_date(c) - a_sub).days) <= 2 * window
                       for c in wb.claims_of(emp)):
                    continue
                old = [b["employee_id"] for b, _ in partners]
                for b, new_sub in partners:
                    wb.reassign_claim(b, emp)
                    wb.move_submission(b, new_sub)
                groups_done += 1
                group = f"S09-{groups_done:02d}"
                wb.take(EXPENSE, a["expense_claim_id"], emp, *old)
                for rec in [a] + [b for b, _ in partners]:
                    wb.take(EXPENSE, rec["expense_claim_id"])
                    self.plant("S09", EXPENSE, rec["expense_claim_id"], {"SPLIT_CLAIM_SUSPECTED"},
                               f"group of {size}: same employee and category, each < 200 USD, within {window} days",
                               group=group)
                done += 1

    def _copy_receipt_line(self, a: dict, b: dict) -> bool:
        """Give one receipt line of claim b the receipt (merchant, number, date, amount) of a line of claim a, so
        both receipts hash to the same value (ASM-020)."""
        wb = self.wb
        b_sub = wb.sub_date(b)
        sources = [ln for ln in wb.lines[a["expense_claim_id"]] if ln["receipt_id"]
                   and b_sub - timedelta(days=90) <= ln["expense_date"] < b_sub
                   and wb.employed(b["employee_id"], ln["expense_date"])]
        sinks = [ln for ln in wb.lines[b["expense_claim_id"]] if ln["receipt_id"]]
        if not sources or not sinks:
            return False
        src, dst = self.pick(sources), self.pick(sinks)
        src_receipt = wb.receipts[src["receipt_id"]]

        def signature(c):
            return (frozenset(ln["category"] for ln in wb.lines[c["expense_claim_id"]]), c["total_amount"],
                    c["claim_period_start"])

        def edit():
            wb.receipts[dst["receipt_id"]].update(merchant=src_receipt["merchant"],
                                                  receipt_number=src_receipt["receipt_number"])
            wb.set_line(dst, self.rng, expense_date=src["expense_date"], line_amount=src["line_amount"],
                        category=src["category"], merchant_description=src["merchant_description"])
            return (all(ln["line_amount"] <= wb.xpol(ln["category"], b)["per_line_limit"]
                        for ln in wb.lines[b["expense_claim_id"]])
                    and b["total_amount"] <= wb.claim_limit(b) and wb.split_safe(b["employee_id"])
                    and signature(a) != signature(b))

        return self.attempt([], [b["expense_claim_id"]], edit)

    def s06(self, n: int, self_employee: bool) -> None:
        wb = self.wb
        scenario = "S06a" if self_employee else "S06b"
        done = 0
        for a in self.claim_cands(lambda c: any(ln["receipt_id"] for ln in wb.lines[c["expense_claim_id"]])):
            if done == n:
                break
            if not wb.free(EXPENSE, a):
                continue

            def pred(b, a=a):
                if b is a or b["created_at"] <= a["created_at"]:
                    return False
                if self_employee:
                    return b["employee_id"] == a["employee_id"] and \
                        b["created_at"] >= a["created_at"] + timedelta(days=8)
                return b["employee_id"] != a["employee_id"] and wb.same_country(a["employee_id"], b["employee_id"])

            for b in self.claim_cands(pred):
                if self._copy_receipt_line(a, b):
                    group = f"{scenario}-{done + 1:02d}"
                    wb.take(EXPENSE, a["expense_claim_id"], a["employee_id"])
                    wb.take(EXPENSE, b["expense_claim_id"], b["employee_id"])
                    for c in (a, b):
                        self.plant(scenario, EXPENSE, c["expense_claim_id"], {ISSUE[scenario]},
                                   "a line of the later claim reuses the receipt of the earlier claim", group=group)
                    done += 1
                    break

    def s14_l5(self, n: int) -> None:
        """Control: claims scaled to 5,100-5,800 USD (above the 5,000 USD L5 threshold, within the 6,000 USD
        per-claim limit) so the highest approval level is exercised (ASM-P4-01)."""
        wb = self.wb
        lo, hi = self.par["s14l5_usd"]
        done = 0
        for c in self.claim_cands(lambda c: len(wb.lines[c["expense_claim_id"]]) >= 3):
            if done == n:
                break
            target = wb.local_for_usd(c, money(self.uniform_dec(lo, hi)))

            def edit(c=c, target=target):
                return (wb.set_claim_total(c, target, self.rng) and wb.usd(c) > Decimal("5000.00")
                        and c["total_amount"] <= wb.claim_limit(c))

            if self.attempt([], [c["expense_claim_id"]], edit):
                wb.take(EXPENSE, c["expense_claim_id"], c["employee_id"])
                self.plant("S14-L5", EXPENSE, c["expense_claim_id"], set(),
                           f"lines scaled to {wb.usd(c)} USD", detect=False, max_level="L5")
                done += 1

    def s07b(self, n: int) -> None:
        wb = self.wb
        lo, hi = self.par["s07b_claim_factor"]
        done = 0
        for c in self.claim_cands(lambda c: len(wb.lines[c["expense_claim_id"]]) >= 4):
            if done == n:
                break
            factor = self.uniform_dec(lo, hi)

            def edit(c=c, factor=factor):
                return wb.set_claim_total(c, money(wb.claim_limit(c) * factor), self.rng) \
                    and c["total_amount"] > wb.claim_limit(c)

            if self.attempt([], [c["expense_claim_id"]], edit):
                wb.take(EXPENSE, c["expense_claim_id"], c["employee_id"])
                self.plant("S07b", EXPENSE, c["expense_claim_id"], {"CLAIM_LIMIT_EXCEEDED"},
                           f"lines scaled to {factor} x the per-claim limit, each within its per-line limit")
                done += 1

    def s07a(self, n: int) -> None:
        wb = self.wb
        lo, hi = self.par["s07a_line_factor"]
        done = 0
        for c in self.claim_cands(lambda c: True):
            if done == n:
                break
            ln = self.pick(wb.lines[c["expense_claim_id"]])
            factor = self.uniform_dec(lo, hi)

            def edit(c=c, ln=ln, factor=factor):
                wb.set_line(ln, self.rng, line_amount=wb.xpol(ln["category"], c)["per_line_limit"] * factor)
                return c["total_amount"] <= wb.claim_limit(c) and wb.split_safe(c["employee_id"])

            if self.attempt([], [c["expense_claim_id"]], edit):
                wb.take(EXPENSE, c["expense_claim_id"], c["employee_id"])
                self.plant("S07a", EXPENSE, c["expense_claim_id"], {"LINE_LIMIT_EXCEEDED"},
                           f"line {ln['line_number']} set to {factor} x its per-line limit")
                done += 1

    def s05(self, n: int) -> None:
        wb = self.wb
        done = 0
        for c in self.claim_cands(lambda c: True):
            if done == n:
                break
            required = [ln for ln in wb.lines[c["expense_claim_id"]] if ln["receipt_id"]
                        and ln["line_amount"] >= wb.xpol(ln["category"], c)["receipt_threshold"]]
            if not required:
                continue
            ln = self.pick(required)
            wb.drop_receipt(ln)
            wb.take(EXPENSE, c["expense_claim_id"], c["employee_id"])
            self.plant("S05", EXPENSE, c["expense_claim_id"], {"MISSING_RECEIPT"},
                       f"receipt removed from line {ln['line_number']} (amount at or above the threshold)")
            done += 1

    def s10(self, n: int) -> None:
        wb = self.wb
        done = 0
        for c in self.claim_cands(lambda c: True):
            if done == n:
                break
            c["cost_center_id"] = None
            # The DB requires exception_class <> NONE when the cost center is NULL (AM-A2); set from the
            # catalogue class of MISSING_COST_CENTER, known by construction (AMB-P4-02).
            c["exception_class"] = "DATA_QUALITY"
            wb.take(EXPENSE, c["expense_claim_id"], c["employee_id"])
            self.plant("S10", EXPENSE, c["expense_claim_id"], {"MISSING_COST_CENTER"}, "cost_center_id set to NULL")
            done += 1

    def s26(self, n: int) -> None:
        wb = self.wb
        done = 0
        for c in self.claim_cands(lambda c: True):
            if done == n:
                break
            ln = self.pick(wb.lines[c["expense_claim_id"]])
            new = self.pick([x for x in ("GBP", "INR", "USD") if x != c["currency"]])
            wb.set_line(ln, currency=new)
            wb.take(EXPENSE, c["expense_claim_id"], c["employee_id"])
            self.plant("S26", EXPENSE, c["expense_claim_id"], {"CURRENCY_MISMATCH"},
                       f"line {ln['line_number']} currency changed from {c['currency']} to {new}")
            done += 1


def inject_anomalies(cfg: dict, p: GenParams, wb: Workbench, rngs: dict) -> None:
    Anomalies(cfg, p, wb, rngs).run()
