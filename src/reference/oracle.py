"""Independent reference calculation: the ground-truth oracle (docs/07 section 9.2, DEC-01, ASM-054).

For every leave request and expense claim it computes, from config/*.yaml and the raw tables only, the expected
exception codes, the expected ordered approval route and the expected outcome. It deliberately shares NO code
with src/services or src/data (tests/test_reference_independence.py): calendar, accrual, policy resolution,
routing and every check are re-implemented here in plain table-driven Python (DEC-P4-01).

Outcomes. The EVENTUAL outcome (eventual_status) has no time limit: clean -> APPROVED; HARD -> REJECTED;
CORRECTABLE -> RETURNED_FOR_CORRECTION; SOFT -> the simulated process-owner decision (docs/05 9.5), else
ESCALATED_FOR_REVIEW. An earlier request whose eventual outcome holds balance or dates (APPROVED or ESCALATED) is
treated as still pending when a later request is checked against it (ASM-P4-04).
Timing (Phase 7B, ASM-P4-03 completed): final_status is the status AT the as-of instant (midnight UTC at the start
of AS_OF_DATE), re-derived here from config/generation.yaml alone, independently of the engine: the process owner
(lowest employee id with PROCESS_OWNER, not the requester) decides an escalated request, and each route step is
decided by its approver, at 17:00 UTC on the max(1, delay)-th business day of the decider's country after the
assignment day (counting from the next day when assigned at or after 17:00); delay = a keyed draw on the delays
stream (key: request id, round 1, level or PROCESS_OWNER), re-implemented here with numpy. A decision after the
as-of instant has not happened: PENDING_APPROVAL or ESCALATED_FOR_REVIEW.
Budget (BR-BUD-02..04, owner decision on AMB-P6-01): a claim's reservation is kept unless validation itself rejects
or returns the claim; an escalated claim keeps it until the process owner's decision, and a later claim submitted
at or after a reject or return decision no longer sees it (Phase 7B timing).
Legacy approvals (S01/S02) are APPROVED rows with decision_reason_code LEGACY_APPROVAL (raw-input marker); every
other non-DRAFT row is a submission, whatever status an S6 run wrote on it.
"""
from __future__ import annotations

import calendar as _calendar
import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np
import yaml

ZERO = Decimal("0")
CENT = Decimal("0.01")
LEVELS = ["L1", "L2", "L3", "L4", "L5"]
HOLDS = {"APPROVED", "ESCALATED_FOR_REVIEW", "PENDING_APPROVAL"}   # outcomes that keep balance/budget/dates
SEVERITY_ROUTE = {"HARD": "REJECTED", "CORRECTABLE": "RETURNED_FOR_CORRECTION"}
LEGACY = "LEGACY_APPROVAL"
PO = "PROCESS_OWNER"


def is_legacy(r: dict) -> bool:
    return r["workflow_status"] == "APPROVED" and r.get("decision_reason_code") == LEGACY


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _dec(v) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def floor_half(x: Decimal) -> Decimal:
    return ((x * 2).to_integral_value(rounding=ROUND_FLOOR) / 2).quantize(Decimal("0.1"))


@dataclass
class Expectation:
    record_type: str
    record_id: str
    submission_codes: set[str] = field(default_factory=set)
    batch_codes: set[str] = field(default_factory=set)
    route: list[dict] | None = None
    required_levels: list[str] = field(default_factory=list)
    final_status: str = "DRAFT"         # at the as-of instant once leave() / expenses() has finished
    eventual_status: str = "DRAFT"      # without the as-of cut-off (ASM-P4-03)
    eligible: bool | None = None
    approved_amount: Decimal | None = None
    facts: dict = field(default_factory=dict)

    @property
    def codes(self) -> list[str]:
        return sorted(self.submission_codes | self.batch_codes)


class ReferenceConfig:
    """Rules read straight from config/*.yaml (never through src.data.config_loader)."""

    def __init__(self, config_dir: Path, rules_override: list[dict] | None = None) -> None:
        cal = _yaml(config_dir / "calendar.yaml")
        self.weekend = {c: set(days) for c, days in cal["weekend_days"].items()}
        ar = _yaml(config_dir / "approval_rules.yaml")
        self.rules = [self._rule(r, ar["effective_start"]) for r in (rules_override or ar["rules"])]
        ec = _yaml(config_dir / "exception_codes.yaml")
        self.severity = {c["code"]: c["severity"] for c in ec["codes"]}
        po = ec["process_owner_decisions"]
        self.po_approve, self.po_reject, self.po_return = (set(po["approve_when_only"]), set(po["reject_when_any"]),
                                                           set(po["return_when_any"]))
        det = _yaml(config_dir / "expense_policies.yaml")["detection"]
        self.max_line_age = int(det["max_line_age_days"])
        self.split_window = int(det["split_window_days"])
        self.split_threshold = Decimal(det["split_threshold_usd"])
        gen = _yaml(config_dir / "generation.yaml")
        self.master_seed, self.streams = int(gen["master_seed"]), list(gen["streams"])
        asof = gen["as_of_date"]
        self.as_of_date = asof if isinstance(asof, date) else date.fromisoformat(str(asof))
        self.decision_hour = int(gen["decisions"]["decision_hour_utc"])
        self.delay_ranges = {k: (int(v[0]), int(v[1])) for k, v in gen["decisions"]["delay_business_days"].items()}

    @staticmethod
    def _rule(r: dict, default_start) -> dict:
        start = r.get("effective_start", default_start)
        return {
            "id": r["id"], "type": r["request_type"], "country": r.get("country"),
            "category": r.get("category_or_leave_type"),
            "min_amount": _dec(r.get("min_amount_usd")), "max_amount": _dec(r.get("max_amount_usd")),
            "min_days": _dec(r.get("min_days")), "max_days": _dec(r.get("max_days")),
            "levels": tuple(r["levels"]), "priority": int(r["priority"]),
            "start": start if isinstance(start, date) else date.fromisoformat(str(start)),
            "end": r.get("effective_end"), "active": r.get("is_active", True),
        }


class Oracle:
    def __init__(self, tables: dict[str, list[dict]], config_dir: Path,
                 rules_override: list[dict] | None = None, seed: int | None = None, as_of: date | None = None) -> None:
        self.cfg = ReferenceConfig(config_dir, rules_override)
        self.t = tables
        root = np.random.SeedSequence(self.cfg.master_seed if seed is None else seed)
        self.delay_seed = root.spawn(len(self.cfg.streams))[self.cfg.streams.index("delays")]
        self.as_of = datetime.combine(as_of or self.cfg.as_of_date, time(0, 0), tzinfo=timezone.utc)
        role_names = {r["role_id"]: r["role_name"] for r in tables.get("role", [])}
        user_emp = {u["user_id"]: u["employee_id"] for u in tables.get("application_user", [])}
        self.process_owners = sorted({user_emp[ur["user_id"]] for ur in tables.get("user_role", [])
                                      if role_names.get(ur["role_id"]) == PO and user_emp.get(ur["user_id"])})
        self.emps = {e["employee_id"]: e for e in tables["employee"]}
        # L5: the G7 of the requester's country; none or several -> no approver (S19 option a, AMB-P7B-09).
        self.g7_by_country: dict[str, list[str]] = {}
        for e in self.emps.values():
            if e["grade"] == "G7":
                self.g7_by_country.setdefault(e["country"], []).append(e["employee_id"])
        self.heads = {d["department_id"]: d["head_employee_id"] for d in tables["department"]}
        self.controllers = {e["country"]: e["employee_id"] for e in self.emps.values() if e["is_finance_controller"]}
        self.delegations = tables.get("delegation", [])
        self.holidays = {(h["country"], h["holiday_date"]) for h in tables["country_holiday"]}
        self.lpol = {p["leave_policy_id"]: p for p in tables["leave_policy"]}
        self.xpol = tables["expense_policy"]
        self.fx = sorted(tables["fx_rate"], key=lambda r: r["effective_from"])
        self.ccs = {c["cost_center_id"]: c for c in tables["cost_center"]}
        self.budgets = {(b["cost_center_id"], b["budget_period_start"].year): b for b in tables["cost_center_budget"]}
        balances = tables.get("leave_balance", [])
        self.first_year = min((b["leave_year"] for b in balances), default=None)
        self.opening: dict[tuple, Decimal] = {}
        lbal = {b["leave_balance_id"]: b for b in balances}
        for t in tables.get("leave_balance_transaction", []):
            if t["txn_type"] == "OPENING":
                b = lbal[t["leave_balance_id"]]
                key = (b["employee_id"], b["leave_policy_id"], b["leave_year"])
                self.opening[key] = self.opening.get(key, ZERO) + t["quantity"]

    # --- calendar (BR-CAL-01..04) --------------------------------------------------------------------------
    def is_business_day(self, d: date, country: str) -> bool:
        return d.isoweekday() not in self.cfg.weekend[country] and (country, d) not in self.holidays

    def business_days(self, start: date, end: date, country: str) -> int:
        return sum(self.is_business_day(date.fromordinal(o), country)
                   for o in range(start.toordinal(), end.toordinal() + 1))

    def quantity(self, start: date, end: date, country: str, sh: bool, eh: bool) -> Decimal:
        return (Decimal(self.business_days(start, end, country))
                - Decimal("0.5") * (int(sh) + int(eh))).quantize(Decimal("0.1"))

    def parts_by_year(self, r: dict, country: str) -> dict[int, tuple[date, Decimal]]:
        """BR-LBAL-09: {year: (part start, quantity)}; a half-day reduces the year it falls in."""
        out = {}
        for y in range(r["start_date"].year, r["end_date"].year + 1):
            s, e = max(r["start_date"], date(y, 1, 1)), min(r["end_date"], date(y, 12, 31))
            q = self.quantity(s, e, country, r["start_half_day"] and s == r["start_date"],
                              r["end_half_day"] and e == r["end_date"])
            if q > 0:
                out[y] = (s, q)
        return out

    # --- accrual (BR-LBAL-03, ASM-006/007/P3-14), full-year schedule ------------------------------------
    @staticmethod
    def accruals(pol: dict, start: date, end: date | None, year: int) -> list[tuple[date, Decimal]]:
        ent = Decimal(pol["annual_entitlement_days"])
        ys, ye = date(year, 1, 1), date(year, 12, 31)
        if pol["accrual_method"] == "NONE" or start > ye or (end is not None and end < ys):
            return []
        if pol["accrual_method"] == "ANNUAL_GRANT":
            q = floor_half(ent) if start <= ys else floor_half(ent * ((ye - start).days + 1) / ((ye - ys).days + 1))
            return [(max(start, ys), q)] if q > 0 else []
        per = floor_half(ent / 12)
        out = []
        for m in range(1, 13):
            ms = date(year, m, 1)
            me = date(year, m, _calendar.monthrange(year, m)[1])
            if start > me or (end is not None and ms > end):
                continue
            q = per if start <= ms else floor_half(per * ((me - start).days + 1) / ((me - ms).days + 1))
            if q > 0:
                out.append((max(ms, start), q))
        return out

    # --- routing (docs/05 section 5) -------------------------------------------------------------------------
    def _delegation(self, emp_id: str, d: date) -> str | None:
        for g in self.delegations:
            if g["approver_id"] == emp_id and g["effective_from"] <= d <= g["effective_to"]:
                return g["delegate_id"]
        return None

    def _substitute(self, person: str | None, requester: str, d: date) -> tuple[str | None, str | None]:
        """docs/05 5.4 / ASM-030: requester -> next up; terminated -> delegate else next up; on leave -> delegate."""
        delegated_from, seen = None, set()
        while person is not None and person not in seen:
            seen.add(person)
            e = self.emps[person]
            if person == requester:
                person = e["manager_id"]
                continue
            delegate = self._delegation(person, d)
            if e["employment_end"] is not None and e["employment_end"] < d:
                if delegate:
                    delegated_from, person = delegated_from or person, delegate
                else:
                    person = e["manager_id"]
                continue
            if delegate:
                delegated_from, person = delegated_from or person, delegate
                continue
            return person, delegated_from
        return None, None

    def _base(self, level: str, emp: dict) -> str | None:
        m = emp["manager_id"]
        if level == "L1":
            return m
        if level == "L2":
            # AMB-P3-03: when L1 is a top-of-chain G7 there is no skip-level; that G7 covers L2 in one step.
            return None if m is None else (self.emps[m]["manager_id"] or m)
        if level == "L3":
            return self.heads.get(emp["department_id"])
        if level == "L4":
            return self.controllers.get(emp["country"])
        g7s = self.g7_by_country.get(emp["country"], [])
        return g7s[0] if len(g7s) == 1 else None

    def select_rule(self, request_type: str, country: str, category: str, measure: Decimal, d: date):
        """Returns (rule, error_code). Bands: lower exclusive, upper inclusive (ASM-009, ASM-013)."""
        lo_key, hi_key = ("min_days", "max_days") if request_type == "LEAVE" else ("min_amount", "max_amount")
        matches = [
            r for r in self.cfg.rules
            if r["type"] == request_type and r["active"] and r["start"] <= d
            and (r["end"] is None or d <= r["end"]) and r["country"] in (None, country)
            and r["category"] in (None, category)
            and (r[lo_key] is None or measure > r[lo_key]) and (r[hi_key] is None or measure <= r[hi_key])
        ]
        if not matches:
            return None, "NO_VALID_APPROVAL_PATH"
        top = max(r["priority"] for r in matches)
        best = sorted((r for r in matches if r["priority"] == top), key=lambda r: r["id"])
        if len({r["levels"] for r in best}) > 1:
            return None, "RULE_CONFLICT"
        return best[0], None

    def resolve_route(self, emp_id: str, levels: tuple[str, ...], d: date) -> list[dict] | None:
        emp = self.emps[emp_id]
        by_person: dict[str, dict] = {}
        for lv in levels:
            person, df = self._substitute(self._base(lv, emp), emp_id, d)
            if person is None:
                return None
            # ASM-030: one person resolved for several levels -> one step at the highest level.
            entry = by_person.setdefault(person, {"approver_id": person, "covers": [], "delegated_from": None})
            entry["covers"].append(lv)
            entry["level"] = max(entry["covers"], key=LEVELS.index)
            entry["delegated_from"] = entry["delegated_from"] or df
        route = sorted(by_person.values(), key=lambda x: LEVELS.index(x["level"]))
        return [{"level": x["level"], "approver_id": x["approver_id"],
                 "covers": sorted(x["covers"], key=LEVELS.index), "delegated_from": x["delegated_from"]}
                for x in route]

    # --- timing (Phase 7B): when each simulated decision happens -------------------------------------------------
    def delay(self, key: tuple, kind: str) -> int:
        lo, hi = self.cfg.delay_ranges[kind]
        s = self.delay_seed
        words = tuple(int.from_bytes(hashlib.sha256(str(k).encode()).digest()[:8], "big") for k in key)
        child = np.random.SeedSequence(s.entropy, spawn_key=tuple(s.spawn_key) + words, pool_size=s.pool_size)
        return int(np.random.Generator(np.random.PCG64(child)).integers(lo, hi + 1))

    def decided_at(self, assigned: datetime, kind: str, key: tuple, decider: str) -> datetime:
        n = max(1, self.delay(key, kind))
        hour = self.cfg.decision_hour
        d = assigned.date() + timedelta(days=2 if assigned.time() >= time(hour) else 1)
        country = self.emps[decider]["country"]
        while True:
            if self.is_business_day(d, country):
                n -= 1
                if n == 0:
                    return datetime.combine(d, time(hour), tzinfo=timezone.utc)
            d += timedelta(days=1)

    def po_action(self, codes: set[str]) -> str | None:
        soft = {c for c in codes if self.cfg.severity[c] == "SOFT"}
        if soft & self.cfg.po_reject:
            return "REJECTED"
        if soft & self.cfg.po_return:
            return "RETURNED_FOR_CORRECTION"
        if soft and soft <= self.cfg.po_approve:
            return "APPROVED"
        return None

    def at_as_of(self, x: Expectation, emp_id: str, submitted: datetime) -> tuple[str, datetime | None]:
        """(status at the as-of instant, instant of a process-owner reject / return, else None)."""
        if {self.cfg.severity[c] for c in x.submission_codes} & {"HARD", "CORRECTABLE"}:
            return x.final_status, None
        t = submitted
        if any(self.cfg.severity[c] == "SOFT" for c in x.submission_codes):
            action = self.po_action(x.submission_codes)
            owner = next((p for p in self.process_owners if p != emp_id), None)
            if action is None or owner is None:
                return "ESCALATED_FOR_REVIEW", None
            t = self.decided_at(submitted, PO, (x.record_id, 1, PO), owner)
            if t > self.as_of:
                return "ESCALATED_FOR_REVIEW", None
            if action != "APPROVED":
                return action, t
        for step in x.route or []:
            t = self.decided_at(t, step["level"], (x.record_id, 1, step["level"]), step["approver_id"])
            if t > self.as_of:
                return "PENDING_APPROVAL", None
        return "APPROVED", None

    @staticmethod
    def settle(out: dict[str, Expectation]) -> None:
        """final_status becomes the status at as-of; the eventual one is kept (eventual_status)."""
        for x in out.values():
            x.eventual_status = x.final_status
            x.final_status = x.facts.pop("status_at_asof", x.final_status)

    # --- outcome (docs/05 9.3 and 9.5) -----------------------------------------------------------------------
    def outcome(self, codes: set[str]) -> str:
        sev = {self.cfg.severity[c] for c in codes}
        for s in ("HARD", "CORRECTABLE"):
            if s in sev:
                return SEVERITY_ROUTE[s]
        soft = {c for c in codes if self.cfg.severity[c] == "SOFT"}
        if not soft:
            return "APPROVED"
        if soft & self.cfg.po_reject:
            return "REJECTED"
        if soft & self.cfg.po_return:
            return "RETURNED_FOR_CORRECTION"
        if soft <= self.cfg.po_approve:
            return "APPROVED"
        return "ESCALATED_FOR_REVIEW"

    def _finish(self, x: Expectation, rtype: str, emp_id: str, category: str, measure: Decimal, d: date) -> None:
        """Route unless validation already rejects or returns (ASM-P4-05); then decide the outcome."""
        if not {self.cfg.severity[c] for c in x.submission_codes} & {"HARD", "CORRECTABLE"}:
            rule, err = self.select_rule(rtype, self.emps[emp_id]["country"], category, measure, d)
            if err:
                x.submission_codes.add(err)
            else:
                x.required_levels = list(rule["levels"])
                x.facts["rule_id"] = rule["id"]
                route = self.resolve_route(emp_id, rule["levels"], d)
                if route is None:
                    x.submission_codes.add("NO_VALID_APPROVAL_PATH")
                else:
                    x.route = route
        x.final_status = self.outcome(x.submission_codes)

    # --- leave -------------------------------------------------------------------------------------------------
    @staticmethod
    def overlap(a: dict, b: dict) -> bool:
        """BR-LV-10: intervals intersect, except one shared boundary date with complementary half-days."""
        if a["end_date"] < b["start_date"] or b["end_date"] < a["start_date"]:
            return False
        for x, y in ((a, b), (b, a)):
            if x["end_date"] == y["start_date"] and x["end_half_day"] and y["start_half_day"]:
                return False
        return True

    def leave(self) -> dict[str, Expectation]:
        reqs = sorted(self.t["leave_request"], key=lambda r: (r["created_at"], r["leave_request_id"]))
        out: dict[str, Expectation] = {}
        consumed: dict[tuple, Decimal] = {}
        used_approved: dict[tuple, Decimal] = {}
        unpaid: dict[tuple, Decimal] = {}
        holding: dict[str, list[dict]] = {}
        reviewed: set[frozenset] = set()
        cache: dict[tuple, list] = {}

        def sched(emp, pol, year):
            k = (emp["employee_id"], pol["leave_policy_id"], year)
            if k not in cache:
                cache[k] = self.accruals(pol, emp["employment_start"], emp["employment_end"], year)
            return cache[k]

        def opening(emp, pol, year, sub: date) -> Decimal:
            """Posted opening (first year) or carry-forward from the previous year (BR-LBAL-04)."""
            if year == self.first_year:
                return self.opening.get((emp["employee_id"], pol["leave_policy_id"], year), ZERO)
            if sub.year < year or emp["employment_start"] > date(year - 1, 12, 31):
                return ZERO   # next year's carry-forward is unknown at submission (BR-LBAL-09)
            prev = (emp["employee_id"], pol["leave_policy_id"], year - 1)
            avail = (opening(emp, pol, year - 1, date(year - 1, 12, 31))
                     + sum((q for _, q in sched(emp, pol, year - 1)), ZERO) - used_approved.get(prev, ZERO))
            if avail < 0:
                return avail if pol["negative_balance_allowed"] else ZERO
            return min(avail, Decimal(pol["carry_forward_cap_days"]))

        def floor_of(pol) -> Decimal:
            return -Decimal(pol["negative_limit_days"]) if pol["negative_balance_allowed"] else ZERO

        def take(r, emp, pol, parts, approved: bool) -> None:
            holding.setdefault(emp["employee_id"], []).append(r)
            for y, (_, q) in parts.items():
                if pol["leave_type"] == "UNPAID":
                    unpaid[(emp["employee_id"], y)] = unpaid.get((emp["employee_id"], y), ZERO) + q
                    continue
                key = (emp["employee_id"], pol["leave_policy_id"], y)
                consumed[key] = consumed.get(key, ZERO) + q
                if approved:
                    used_approved[key] = used_approved.get(key, ZERO) + q

        for r in reqs:
            rid = r["leave_request_id"]
            emp = self.emps[r["employee_id"]]
            pol = self.lpol[r["leave_policy_id"]]
            country = emp["country"]
            x = Expectation("LEAVE", rid)
            out[rid] = x
            qty = self.quantity(r["start_date"], r["end_date"], country, r["start_half_day"], r["end_half_day"])
            x.facts.update(quantity=qty, leave_type=pol["leave_type"], holiday_span=any(
                (country, date.fromordinal(o)) in self.holidays
                for o in range(r["start_date"].toordinal(), r["end_date"].toordinal() + 1)))
            if r["workflow_status"] == "DRAFT":
                continue
            sub = r["created_at"].date()
            parts = self.parts_by_year(r, country)
            if is_legacy(r):
                # Legacy approval (S01/S02, AM-A3): USAGE posted on the submission date, no validation ran.
                x.facts["legacy"] = True
                x.final_status = "APPROVED"
                take(r, emp, pol, parts, approved=True)
                if pol["leave_type"] != "UNPAID":
                    for y in parts:
                        key = (emp["employee_id"], pol["leave_policy_id"], y)
                        running = (opening(emp, pol, y, sub) + sum((a for d, a in sched(emp, pol, y) if d <= sub), ZERO)
                                   - consumed[key])
                        if running < floor_of(pol):
                            x.batch_codes.add("NEGATIVE_BALANCE_UNPERMITTED")
                continue

            codes = x.submission_codes
            if (emp["employment_end"] is not None and emp["employment_end"] < sub) \
                    or r["start_date"] < emp["employment_start"] \
                    or (emp["employment_end"] is not None and r["end_date"] > emp["employment_end"]):
                codes.add("LEAVE_OUTSIDE_EMPLOYMENT")
            if pol["country_scope"] not in (country, "ALL") or not pol["is_active"]:
                codes.add("POLICY_NOT_APPLICABLE")
            if not (pol["effective_start"] <= sub and (pol["effective_end"] is None or sub <= pol["effective_end"])):
                codes.add("POLICY_VERSION_EXPIRED")
            if (r["start_half_day"] and not self.is_business_day(r["start_date"], country)) or \
                    (r["end_half_day"] and not self.is_business_day(r["end_date"], country)):
                codes.add("HALF_DAY_ON_NON_BUSINESS_DAY")
            if qty < Decimal("0.5"):
                codes.add("ZERO_BUSINESS_DAYS")
            if pol["leave_type"] == "UNPAID":
                cap = Decimal(pol["max_days_per_year"])
                if any(unpaid.get((emp["employee_id"], y), ZERO) + q > cap for y, (_, q) in parts.items()):
                    codes.add("UNPAID_LIMIT_EXCEEDED")
            else:
                for y, (ps, q) in parts.items():
                    key = (emp["employee_id"], pol["leave_policy_id"], y)
                    avail = (opening(emp, pol, y, sub)
                             + sum((a for d, a in sched(emp, pol, y) if d <= max(sub, ps)), ZERO)
                             - consumed.get(key, ZERO))
                    if avail - q < floor_of(pol):
                        codes.add("INSUFFICIENT_BALANCE")
            for o in holding.get(emp["employee_id"], []):
                if self.overlap(r, o):
                    if out[o["leave_request_id"]].facts.get("legacy"):
                        codes.add("OVERLAPPING_APPROVED_LEAVE")
                    else:
                        codes.add("OVERLAPPING_PENDING_LEAVE")
                        reviewed.add(frozenset((rid, o["leave_request_id"])))
            limit = pol["requires_medical_cert_over_days"]
            if pol["leave_type"] == "SICK" and limit is not None and qty > Decimal(limit) and not r["medical_cert_flag"]:
                codes.add("MEDICAL_CERT_REQUIRED")
            self._finish(x, "LEAVE", emp["employee_id"], pol["leave_type"], qty, sub)
            x.facts["status_at_asof"] = self.at_as_of(x, emp["employee_id"], r["created_at"])[0]
            if x.final_status in HOLDS:
                take(r, emp, pol, parts, approved=x.final_status == "APPROVED")

        # Batch overlap detector: approved requests of one employee that intersect (EC-02). An overlap the
        # process owner already reviewed and accepted (OVERLAPPING_PENDING_LEAVE) is not flagged again (ASM-P4-07).
        approved = [r for r in reqs if out[r["leave_request_id"]].final_status == "APPROVED"]
        for i, a in enumerate(approved):
            for b in approved[i + 1:]:
                if a["employee_id"] == b["employee_id"] and self.overlap(a, b) \
                        and frozenset((a["leave_request_id"], b["leave_request_id"])) not in reviewed:
                    out[a["leave_request_id"]].batch_codes.add("OVERLAPPING_APPROVED_LEAVE")
                    out[b["leave_request_id"]].batch_codes.add("OVERLAPPING_APPROVED_LEAVE")
        self.settle(out)
        return out

    # --- expenses ------------------------------------------------------------------------------------------
    def fx_rate(self, currency: str, d: date) -> Decimal:
        if currency == "USD":
            return Decimal("1")
        rows = [r for r in self.fx if r["from_currency"] == "USD" and r["to_currency"] == currency
                and r["effective_from"] <= d]
        return rows[-1]["rate"]

    def expense_policy(self, category: str, country: str, d: date) -> dict | None:
        found = [p for p in self.xpol if p["category"] == category and p["country"] == country and p["is_active"]
                 and p["effective_start"] <= d and (p["effective_end"] is None or d <= p["effective_end"])]
        if len(found) > 1:
            raise ValueError(f"policy configuration error: {len(found)} versions of {category}/{country} on {d}")
        return found[0] if found else None

    def split_groups(self, items: list[tuple]) -> list[list[str]]:
        """BR-SPLIT-02: items (sub_date, ts, claim_id, usd) of one employee and category, each below the threshold.
        Greedy from the earliest unassigned claim: window [d, d + W - 1]; a group needs >= 2 claims, sum >= T."""
        items = sorted(items)
        assigned: set[str] = set()
        groups = []
        for i, (d0, _, cid, _) in enumerate(items):
            if cid in assigned:
                continue
            members = [it for it in items[i:] if it[2] not in assigned
                       and (it[0] - d0).days <= self.cfg.split_window - 1]
            if len(members) >= 2 and sum(it[3] for it in members) >= self.cfg.split_threshold:
                groups.append([it[2] for it in members])
                assigned.update(it[2] for it in members)
        return groups

    def expenses(self) -> dict[str, Expectation]:
        claims = sorted(self.t["expense_claim"], key=lambda c: (c["created_at"], c["expense_claim_id"]))
        lines: dict[str, list[dict]] = {}
        for ln in self.t["expense_line"]:
            lines.setdefault(ln["expense_claim_id"], []).append(ln)
        receipts = {r["receipt_id"]: r for r in self.t["receipt"]}
        out: dict[str, Expectation] = {}
        seen_hashes: dict[str, list[str]] = {}           # hash -> employees of earlier submitted claims
        split_pool: dict[tuple, list[tuple]] = {}        # (employee, primary category) -> items
        budget_held: dict[tuple, list[tuple[Decimal, datetime | None]]] = {}   # (amount, released at)
        signatures: dict[str, set] = {}

        for c in claims:
            cid = c["expense_claim_id"]
            x = Expectation("EXPENSE", cid)
            out[cid] = x
            if c["workflow_status"] == "DRAFT":
                continue
            cl = sorted(lines.get(cid, []), key=lambda ln: ln["line_number"])
            emp = self.emps[c["employee_id"]]
            sub = c["created_at"].date()
            total = sum((ln["line_amount"] for ln in cl), ZERO)
            usd = (total / self.fx_rate(c["currency"], sub)).quantize(CENT, rounding=ROUND_HALF_UP)
            top = sorted(cl, key=lambda ln: (-ln["line_amount"], ln["line_number"]))[0]
            x.facts.update(usd=usd, total=total, primary_category=top["category"])
            codes = x.submission_codes
            pols = {}
            for ln in cl:
                if ln["expense_date"] < emp["employment_start"] or \
                        (emp["employment_end"] is not None and ln["expense_date"] > emp["employment_end"]):
                    codes.add("EXPENSE_OUTSIDE_EMPLOYMENT")
                if ln["expense_date"] > sub or (sub - ln["expense_date"]).days > self.cfg.max_line_age:
                    codes.add("EXPENSE_DATE_TOO_OLD")
                if ln["currency"] != c["currency"]:
                    codes.add("CURRENCY_MISMATCH")
                pol = pols[ln["expense_line_id"]] = self.expense_policy(ln["category"], emp["country"], sub)
                if pol is None:
                    codes.add("POLICY_NOT_APPLICABLE")
                    continue
                if ln["line_amount"] > pol["per_line_limit"]:
                    codes.add("LINE_LIMIT_EXCEEDED")
                if ln["line_amount"] >= pol["receipt_threshold"] and ln["receipt_id"] is None:
                    codes.add("MISSING_RECEIPT")
            if c["currency"] != emp["currency"]:
                codes.add("CURRENCY_MISMATCH")
            top_pol = pols.get(top["expense_line_id"])
            if top_pol is not None and total > top_pol["per_claim_limit"]:
                codes.add("CLAIM_LIMIT_EXCEEDED")
            if c["expense_policy_id"] is not None:
                ref = next(p for p in self.xpol if p["expense_policy_id"] == c["expense_policy_id"])
                if not (ref["effective_start"] <= sub and (ref["effective_end"] is None or sub <= ref["effective_end"])):
                    codes.add("POLICY_VERSION_EXPIRED")
            cc = self.ccs.get(c["cost_center_id"]) if c["cost_center_id"] else None
            if c["cost_center_id"] is None:
                codes.add("MISSING_COST_CENTER")
            elif not cc["is_active"] or cc["effective_from"] > sub or \
                    (cc["effective_to"] is not None and sub > cc["effective_to"]):
                codes.add("INVALID_COST_CENTER")
            hashes = {receipts[ln["receipt_id"]]["receipt_hash"] for ln in cl if ln["receipt_id"]}
            for h in hashes:                                   # BR-EX-07 at submission
                for other_emp in seen_hashes.get(h, []):
                    codes.add("DUPLICATE_RECEIPT_SELF" if other_emp == c["employee_id"]
                              else "DUPLICATE_RECEIPT_CROSS_EMPLOYEE")
            signature = (frozenset(ln["category"] for ln in cl), total, min(ln["expense_date"] for ln in cl))
            if signature in signatures.get(c["employee_id"], set()):   # BR-EX-12
                codes.add("DUPLICATE_CLAIM_PATTERN")
            key = (c["employee_id"], top["category"])
            item = (sub, c["created_at"], cid, usd)
            if usd < self.cfg.split_threshold and any(
                    cid in g for g in self.split_groups(split_pool.get(key, []) + [item])):   # BR-SPLIT-04
                codes.add("SPLIT_CLAIM_SUSPECTED")
            bkey = (c["cost_center_id"], sub.year)
            budget = self.budgets.get(bkey) if cc else None
            held = sum((a for a, released in budget_held.get(bkey, [])
                        if released is None or released > c["created_at"]), ZERO)
            if budget is not None and held + total > budget["budget_amount"]:
                codes.add("BUDGET_EXCEEDED")                    # BR-BUD-03

            self._finish(x, "EXPENSE", c["employee_id"], top["category"], usd, sub)
            x.facts["status_at_asof"], released_at = self.at_as_of(x, c["employee_id"], c["created_at"])
            if x.facts["status_at_asof"] == "APPROVED":     # amounts as they stand at as-of (DEC-P7B-05)
                x.approved_amount = sum((min(ln["line_amount"], pols[ln["expense_line_id"]]["per_line_limit"])
                                         for ln in cl), ZERO).quantize(CENT)   # BR-EX-14
                x.eligible = x.approved_amount > 0
            else:
                x.eligible = False
            validation_releases = {self.cfg.severity[k] for k in codes} & {"HARD", "CORRECTABLE"}
            if budget is not None and not validation_releases:          # BR-BUD-02/04 (AMB-P6-01)
                budget_held.setdefault(bkey, []).append((total, released_at))
            for h in hashes:
                seen_hashes.setdefault(h, []).append(c["employee_id"])
            signatures.setdefault(c["employee_id"], set()).add(signature)
            if usd < self.cfg.split_threshold:
                split_pool.setdefault(key, []).append(item)

        # Batch detectors over all submitted claims (BR-EX-07, BR-SPLIT-03/04).
        owner = {c["expense_claim_id"]: c["employee_id"] for c in claims}
        by_hash: dict[str, set[str]] = {}
        for ln in self.t["expense_line"]:
            if ln["receipt_id"] and owner_status(out, ln["expense_claim_id"]):
                by_hash.setdefault(receipts[ln["receipt_id"]]["receipt_hash"], set()).add(ln["expense_claim_id"])
        for ids in by_hash.values():
            for a in ids:
                for b in ids - {a}:
                    out[a].batch_codes.add("DUPLICATE_RECEIPT_SELF" if owner[a] == owner[b]
                                           else "DUPLICATE_RECEIPT_CROSS_EMPLOYEE")
        for items in split_pool.values():
            for group in self.split_groups(items):
                for cid in group:
                    out[cid].batch_codes.add("SPLIT_CLAIM_SUSPECTED")
        self.settle(out)
        return out

    def compute(self) -> dict[tuple[str, str], Expectation]:
        result = {("LEAVE", k): v for k, v in self.leave().items()}
        result.update({("EXPENSE", k): v for k, v in self.expenses().items()})
        return result


def owner_status(out: dict[str, Expectation], claim_id: str) -> bool:
    """True when the claim was submitted (drafts are invisible to detectors)."""
    return out[claim_id].final_status != "DRAFT"


def compute_expectations(tables: dict[str, list[dict]], config_dir: Path, rules_override: list[dict] | None = None,
                         seed: int | None = None, as_of: date | None = None) -> dict[tuple[str, str], Expectation]:
    return Oracle(tables, config_dir, rules_override, seed, as_of).compute()


def ledger_accrual_mismatches(tables: dict[str, list[dict]], config_dir: Path, as_of: date) -> list[str]:
    """Cross-check: the oracle's own accrual schedule equals the ACCRUAL rows of the raw ledger (up to as_of)."""
    o = Oracle(tables, config_dir)
    posted: dict[str, list] = {}
    for t in tables["leave_balance_transaction"]:
        if t["txn_type"] == "ACCRUAL":
            posted.setdefault(t["leave_balance_id"], []).append((t["txn_date"], t["quantity"]))
    problems = []
    for b in tables["leave_balance"]:
        e = o.emps[b["employee_id"]]
        expected = [(d, q) for d, q in o.accruals(o.lpol[b["leave_policy_id"]], e["employment_start"],
                                                  e["employment_end"], b["leave_year"]) if d <= as_of]
        if sorted(posted.get(b["leave_balance_id"], [])) != expected:
            problems.append(b["leave_balance_id"])
    return problems
