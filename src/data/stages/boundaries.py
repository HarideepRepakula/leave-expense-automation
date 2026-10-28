"""S5 boundary records BC-01..BC-10 (docs/02 section 6, docs/07 section 8, AM-E5).

The `boundaries` RNG stream picks records (disjoint from planted scenarios) and sets exact boundary values in
place. Each boundary is recorded with its expected outcome by construction; the independent oracle must agree
(stage S9). Boundary records are expected NEGATIVES for anomaly metrics, except BC-10 whose rule outcome is a
flag (split total exactly at the threshold is flagged, >=), so its two claims are labelled positives (AMB-P4-08).
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

from src.data.stages.anomalies import EXPENSE, LEAVE, Planter
from src.data.stages.workbench import Boundary, Plant


class Boundaries(Planter):
    def run(self) -> None:
        bcfg = self.cfg["generation"]["boundaries"]
        n, nl = self.n_expense(bcfg["per_case"]), self.n_leave(bcfg["per_case"])
        self.use(LEAVE)                       # leave boundaries: `boundaries` stream only
        self.bc_leave_quantity(nl, 5, ["L1"])
        self.bc_leave_quantity(nl, 10, ["L1", "L2"])
        self.bc_equal_balance(nl)
        self.bc_holiday_start(nl)
        self.use(EXPENSE)                     # expense boundaries: `boundaries_expense` stream only
        self.bc_amount("BC-01", n, Decimal("200.00"), ["L1"], "EXPENSE_AT_200_USD")
        self.bc_amount("BC-02", n, Decimal("1000.00"), ["L1", "L2"], "EXPENSE_AT_1000_USD")
        self.bc_amount("BC-02", n, Decimal("5000.00"), ["L1", "L2", "L4"], "EXPENSE_AT_5000_USD")
        self.bc_employment(n, at_start=True)
        self.bc_employment(n, at_start=False)
        self.bc_policy_end(n)
        self.bc_line("BC-08", n, "receipt_threshold", "LINE_AT_RECEIPT_THRESHOLD",
                     "Receipt required (>= threshold, inclusive); receipt present, no exception")
        self.bc_line("BC-09", n, "per_line_limit", "LINE_AT_PER_LINE_LIMIT",
                     "Not a breach (<= per-line limit); no exception, nothing capped")
        self.bc_split(self.n_expense(bcfg["bc10_groups"]))

    def record(self, case: str, kind: str, rid: str, btype: str, outcome: str, codes=frozenset(), **checks):
        self.wb.boundaries.append(Boundary(case, kind, rid, btype, outcome, frozenset(codes), checks))

    def absorb(self, c: dict, ln: dict, target_local: Decimal) -> bool:
        """Move the claim total to exactly `target_local` by changing one line (no change when impossible)."""
        wb = self.wb
        new = ln["line_amount"] + (target_local - c["total_amount"])
        if new <= 0 or new > wb.xpol(ln["category"], c)["per_line_limit"]:
            return False
        wb.set_line(ln, self.rng, line_amount=new)
        return c["total_amount"] == target_local

    # --- expenses ----------------------------------------------------------------------------------------------
    def bc_amount(self, case: str, n: int, usd: Decimal, levels: list[str], btype: str) -> None:
        """BC-01 / BC-02: claim total exactly at a routing threshold in USD-equivalent (upper bound inclusive)."""
        wb = self.wb
        done = 0
        for c in self.claim_cands(lambda c: True):
            if done == n:
                break
            target = wb.local_for_usd(c, usd)

            def edit(c=c, target=target):
                top = wb.top_line(c)
                ok = self.absorb(c, top, target) or wb.set_claim_total(c, target, self.rng)
                return ok and wb.usd(c) == usd and c["total_amount"] <= wb.claim_limit(c) \
                    and wb.split_safe(c["employee_id"]) \
                    and all(ln["line_amount"] <= wb.xpol(ln["category"], c)["per_line_limit"]
                            for ln in wb.lines[c["expense_claim_id"]])

            if self.attempt([], [c["expense_claim_id"]], edit):
                wb.take(EXPENSE, c["expense_claim_id"], c["employee_id"])
                self.record(case, EXPENSE, c["expense_claim_id"], btype,
                            f"Routes {'+'.join(levels)} (exactly {usd} USD; bands are upper-inclusive)", levels=levels)
                done += 1

    def bc_employment(self, n: int, at_start: bool) -> None:
        """BC-05: an expense line dated exactly on the employment start date, or exactly on the end date."""
        wb = self.wb
        done = 0
        for c in self.claim_cands(lambda c: wb.usd(c) >= Decimal("200.00")):
            if done == n:
                break
            sub = wb.sub_date(c)
            window = (sub - timedelta(days=89), sub - timedelta(days=1))
            if at_start:
                options = [e for e in sorted(wb.emps) if self.target_free(EXPENSE, e)
                           and wb.same_country(e, c["employee_id"]) and wb.employed(e, sub)
                           and window[0] <= wb.emps[e]["employment_start"] <= window[1]]
            else:
                options = [e for e in sorted(wb.emps) if self.target_free(EXPENSE, e)
                           and wb.same_country(e, c["employee_id"]) and wb.emps[e]["employment_end"] is not None
                           and window[0] <= wb.emps[e]["employment_end"] <= window[1]
                           and wb.emps[e]["employment_start"] <= sub - timedelta(days=90)]
            if not options:
                continue
            emp = self.pick(options)
            e = wb.emps[emp]
            lines = wb.lines[c["expense_claim_id"]]
            old = c["employee_id"]
            if at_start:
                edge = e["employment_start"]
                first = min(lines, key=lambda ln: (ln["expense_date"], ln["line_number"]))
                for ln in lines:
                    wb.set_line(ln, expense_date=edge if ln is first else max(ln["expense_date"], edge))
            else:
                edge = e["employment_end"]
                floor = sub - timedelta(days=90)
                last = max(lines, key=lambda ln: (ln["expense_date"], ln["line_number"]))
                for ln in lines:
                    wb.set_line(ln, expense_date=edge if ln is last else max(min(ln["expense_date"], edge), floor))
            wb.reassign_claim(c, emp)
            wb.take(EXPENSE, c["expense_claim_id"], emp, old)
            which = "start" if at_start else "end"
            self.record("BC-05", EXPENSE, c["expense_claim_id"], f"EXPENSE_ON_EMPLOYMENT_{which.upper()}",
                        f"Valid: line dated exactly on the employment {which} date {edge} (inclusive bounds)")
            done += 1

    def bc_policy_end(self, n: int) -> None:
        """BC-07: a MEALS claim submitted on 2025-12-31, the effective_end of the V1 policy it references."""
        wb = self.wb
        end = date(2025, 12, 31)
        done = 0
        for c in self.claim_cands(lambda c: date(2025, 10, 15) <= wb.sub_date(c) < end
                                  and wb.top_line(c)["category"] == "MEALS" and wb.lines_fit(c, c["employee_id"], end)):
            if done == n:
                break
            original = wb.sub_date(c)
            wb.move_submission(c, end)
            if not wb.split_safe(c["employee_id"]):
                wb.move_submission(c, original)
                continue
            c["expense_policy_id"] = f"XPOL-MEALS-{c['country']}-V1"
            wb.take(EXPENSE, c["expense_claim_id"], c["employee_id"])
            self.record("BC-07", EXPENSE, c["expense_claim_id"], "SUBMITTED_ON_POLICY_EFFECTIVE_END",
                        f"Policy {c['expense_policy_id']} still applicable on its effective_end (inclusive)")
            done += 1

    def bc_line(self, case: str, n: int, field: str, btype: str, outcome: str) -> None:
        """BC-08 / BC-09: one line exactly at the receipt threshold / exactly at the per-line limit."""
        wb = self.wb
        done = 0
        for c in self.claim_cands(lambda c: True):
            if done == n:
                break
            ln = self.pick(wb.lines[c["expense_claim_id"]])

            def edit(c=c, ln=ln):
                wb.ensure_receipt(ln, self.rng)
                wb.set_line(ln, self.rng, line_amount=wb.xpol(ln["category"], c)[field])
                return c["total_amount"] <= wb.claim_limit(c) and wb.split_safe(c["employee_id"])

            if self.attempt([], [c["expense_claim_id"]], edit):
                wb.take(EXPENSE, c["expense_claim_id"], c["employee_id"])
                self.record(case, EXPENSE, c["expense_claim_id"], btype,
                            f"{outcome} (line {ln['line_number']} = {ln['line_amount']} {ln['currency']})")
                done += 1

    def bc_split(self, groups: int) -> None:
        """BC-10: a split pair whose combined total is exactly the 200 USD threshold (flagged, >=)."""
        wb = self.wb
        threshold = Decimal(wb.det["split_threshold_usd"])
        window = int(wb.det["split_window_days"])
        done = 0
        for a in self.claim_cands(lambda c: wb.usd(c) < threshold - Decimal("1.00")):
            if done == groups:
                break
            if not wb.free(EXPENSE, a):
                continue
            emp, cat, a_sub = a["employee_id"], wb.top_line(a)["category"], wb.sub_date(a)
            new_sub = a_sub + timedelta(days=self.int_between(1, window - 1))
            if new_sub.year != a_sub.year or new_sub >= self.p.as_of or not wb.employed(emp, new_sub):
                continue
            if any(c is not a and c["workflow_status"] != "DRAFT" and wb.top_line(c)["category"] == cat
                   and wb.usd(c) < threshold and abs((wb.sub_date(c) - a_sub).days) <= 2 * window
                   for c in wb.claims_of(emp)):
                continue
            need_usd = threshold - wb.usd(a)
            for b in self.claim_cands(lambda b: b is not a and wb.same_country(b["employee_id"], emp)
                                      and wb.sub_date(b).year == a_sub.year and wb.top_line(b)["category"] == cat
                                      and wb.lines_fit(b, emp, new_sub)):
                old = b["employee_id"]

                def edit(b=b):
                    wb.reassign_claim(b, emp)
                    wb.move_submission(b, new_sub)
                    top = wb.top_line(b)
                    return (top["receipt_id"] is not None and self.absorb(b, top, wb.local_for_usd(b, need_usd))
                            and wb.top_line(b)["category"] == cat and wb.usd(b) == need_usd
                            and wb.usd(a) + wb.usd(b) == threshold)

                if self.attempt([], [b["expense_claim_id"]], edit):
                    done += 1
                    group = f"BC-10-{done:02d}"
                    wb.take(EXPENSE, a["expense_claim_id"], emp)
                    wb.take(EXPENSE, b["expense_claim_id"], old)
                    for rec in (a, b):
                        self.record("BC-10", EXPENSE, rec["expense_claim_id"], "SPLIT_PAIR_AT_THRESHOLD",
                                    "Flagged SPLIT_CLAIM_SUSPECTED (group sum exactly 200.00 USD, >=)",
                                    codes={"SPLIT_CLAIM_SUSPECTED"})
                        wb.plants.append(Plant(
                            "BC-10", EXPENSE, rec["expense_claim_id"], "SPLIT_CLAIM_SUSPECTED",
                            frozenset({"SPLIT_CLAIM_SUSPECTED"}), True,
                            "Suspected split claim, requires investigation (boundary: sum equals the threshold)",
                            "boundary pair: same employee and category, sum exactly 200.00 USD", group))
                    break

    # --- leave ---------------------------------------------------------------------------------------------
    def bc_leave_quantity(self, n: int, days: int, levels: list[str]) -> None:
        """BC-03: leave quantity exactly 5.0 or 10.0 days (routing bands upper-inclusive)."""
        wb = self.wb
        done = 0
        for r in self.leave_cands(lambda r: wb.leave_type(r) != "UNPAID"):
            if done == n:
                break

            def edit(r=r):
                wb.set_leave_length(r, r["start_date"], days)
                return r["end_date"].year == r["start_date"].year and wb.leave_guard(r["employee_id"])

            if self.attempt([r["leave_request_id"]], [], edit):
                wb.take(LEAVE, r["leave_request_id"], r["employee_id"])
                self.record("BC-03", LEAVE, r["leave_request_id"], f"LEAVE_QUANTITY_{days}",
                            f"Routes {'+'.join(levels)} (quantity exactly {days}.0; upper-inclusive)", levels=levels)
                done += 1

    def bc_equal_balance(self, n: int) -> None:
        """BC-04: quantity exactly equal to the available balance (approved; balance becomes 0)."""
        wb = self.wb
        done = 0
        for r in self.leave_cands(lambda r: wb.leave_type(r) != "UNPAID" and wb.sub_date(r).year == 2025
                                  and r["end_date"].year == 2025 and wb.last_on_balance(r)):
            if done == n:
                break
            emp, rid = r["employee_id"], r["leave_request_id"]
            avail = wb.scheduled(emp, r["leave_policy_id"], 2025, max(wb.sub_date(r), r["start_date"])) \
                - wb.consumed_before(r, 2025)
            if not (Decimal("1.0") <= avail <= Decimal("20.0")):
                continue
            days = math.ceil(avail)
            half = Decimal(days) != avail

            def edit(r=r, days=days, half=half, avail=avail):
                wb.set_leave_length(r, r["start_date"], days, end_half=half)
                return r["requested_quantity"] == avail and r["end_date"].year == 2025 \
                    and wb.leave_guard(emp)    # the services must accept exactly the whole balance (BC-04)

            if self.attempt([rid], [], edit):
                wb.take(LEAVE, rid, emp)
                self.record("BC-04", LEAVE, rid, "LEAVE_EQUALS_AVAILABLE_BALANCE",
                            f"Approved; quantity {avail} equals the available balance, which becomes 0")
                done += 1

    def bc_holiday_start(self, n: int) -> None:
        """BC-06: leave starting on a public holiday; the holiday is excluded from the quantity."""
        wb = self.wb
        holidays = sorted((h["country"], h["holiday_date"]) for h in wb.ds["country_holiday"])
        done = 0
        for r in self.leave_cands(lambda r: True):
            if done == n:
                break
            c, sub = wb.country_of(r), wb.sub_date(r)
            days = int(r["business_day_count"])
            for country, h in holidays:
                if country != c or h.isoweekday() >= 6 or h.year != sub.year \
                        or not (sub + timedelta(days=1) <= h <= sub + timedelta(days=60)):
                    continue

                def edit(r=r, h=h):
                    wb.set_leave_dates(r, h, wb.cal.nth_business_day(h, days, c))
                    return r["end_date"].year == h.year and wb.leave_guard(r["employee_id"])

                if self.attempt([r["leave_request_id"]], [], edit):
                    wb.take(LEAVE, r["leave_request_id"], r["employee_id"])
                    self.record("BC-06", LEAVE, r["leave_request_id"], "LEAVE_STARTS_ON_HOLIDAY",
                                f"Holiday {h} excluded: quantity {r['requested_quantity']} business days; valid",
                                start_is_holiday=True)
                    done += 1
                    break


def inject_boundaries(cfg: dict, p, wb, rngs: dict) -> None:
    Boundaries(cfg, p, wb, rngs).run()
