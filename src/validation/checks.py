"""Structural and arithmetic validation of operational data (docs/07 section 11, docs/08 M1-M3).

Runs on exported files or on in-memory tables (negative fixtures). Every check records which records it was
applied to ("subjects") and every violation as a finding, so M1 (PK), M2 (FK) and M3 (arithmetic) are computed
from actual results. Business-rule detection (exception codes) is NOT done here: that is the services' job
(Phases 5-7). This module never reads ground truth.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

import sqlalchemy as sa

from src.common.ids import ID_PATTERNS
from src.common.money import fx_rate_on
from src.data.dataset import pk_columns, table
from src.services.calendar_service import HolidayCalendar, requested_quantity
from src.services.policy_resolver import resolve_version

CENT = Decimal("0.01")
ENUM_RX = re.compile(r"^(\w+) IN \((.+)\)$")

# docs/06 section 2.2 legal transitions, plus creation events with no previous status.
LEGAL_TRANSITIONS = {
    (None, "DRAFT"), (None, "SUBMITTED"),
    ("DRAFT", "SUBMITTED"), ("DRAFT", "CANCELLED"), ("SUBMITTED", "VALIDATING"),
    ("VALIDATING", "PENDING_APPROVAL"), ("VALIDATING", "REJECTED"), ("VALIDATING", "RETURNED_FOR_CORRECTION"),
    ("VALIDATING", "ESCALATED_FOR_REVIEW"),
    ("PENDING_APPROVAL", "APPROVED"), ("PENDING_APPROVAL", "REJECTED"), ("PENDING_APPROVAL", "RETURNED_FOR_CORRECTION"),
    ("PENDING_APPROVAL", "ESCALATED_FOR_REVIEW"), ("PENDING_APPROVAL", "CANCELLED"),
    ("RETURNED_FOR_CORRECTION", "SUBMITTED"), ("RETURNED_FOR_CORRECTION", "CANCELLED"),
    ("ESCALATED_FOR_REVIEW", "PENDING_APPROVAL"), ("ESCALATED_FOR_REVIEW", "APPROVED"),
    ("ESCALATED_FOR_REVIEW", "REJECTED"), ("ESCALATED_FOR_REVIEW", "RETURNED_FOR_CORRECTION"),
}


@dataclass
class Finding:
    check_id: str
    table_name: str
    record_id: str
    detail: str


@dataclass
class CheckResult:
    check_id: str
    name: str
    metric: str
    subject_keys: set[tuple[str, str]] = field(default_factory=set)
    findings: list[Finding] = field(default_factory=list)

    @property
    def subjects(self) -> int:
        return len(self.subject_keys)

    @property
    def violations(self) -> int:
        return len(self.findings)

    @property
    def status(self) -> str:
        if not self.subject_keys:
            return "NOT_APPLICABLE"
        return "PASS" if not self.findings else "FAIL"

    def subject(self, table_name: str, record_id: str) -> None:
        self.subject_keys.add((table_name, str(record_id)))

    def fail(self, table_name: str, record_id: str, detail: str) -> None:
        self.findings.append(Finding(self.check_id, table_name, str(record_id), detail))


def _key(name: str, row: dict) -> str:
    return "|".join(str(row[k]) for k in pk_columns(name))


class Validator:
    def __init__(self, ds: dict[str, list[dict]], weekend_days: dict[str, list[int]]) -> None:
        self.ds = ds
        self.cal = HolidayCalendar.from_rows(weekend_days, ds.get("country_holiday", []))
        self.results: list[CheckResult] = []

    def rows(self, name: str) -> list[dict]:
        return self.ds.get(name, [])

    def check(self, check_id: str, name: str, metric: str) -> CheckResult:
        r = CheckResult(check_id, name, metric)
        self.results.append(r)
        return r

    def run(self) -> list[CheckResult]:
        for fn in (self.primary_keys, self.foreign_keys, self.enums, self.derived_ids, self.date_order,
                   self.employment_status, self.policy_versions, self.rule_conflicts, self.claim_totals,
                   self.approved_amounts, self.line_arithmetic, self.reimbursement_amounts, self.balance_ledger,
                   self.leave_quantities, self.fx_conversion, self.budget_ledger, self.lifecycle,
                   self.approval_sequence, self.self_approval, self.reimbursement_eligibility,
                   self.cost_center_exception, self.approver_employed_at_decision):
            fn()
        return self.results

    # --- M1 / M2 / data dictionary ---------------------------------------------------------------------------
    def primary_keys(self) -> None:
        r = self.check("V-PK-01", "Primary keys present, well-formed and unique", "M1")
        for name, rows in sorted(self.ds.items()):
            keys = pk_columns(name)
            rx = re.compile(ID_PATTERNS[name]) if name in ID_PATTERNS and len(keys) == 1 else None
            seen: dict[str, int] = defaultdict(int)
            for row in rows:
                seen[_key(name, row)] += 1
            for i, row in enumerate(rows):
                k = _key(name, row)
                r.subject(name, f"{k}#{i}")
                if any(row[c] is None for c in keys):
                    r.fail(name, k, "NULL primary key")
                elif rx and not rx.match(str(row[keys[0]])):
                    r.fail(name, k, f"malformed id (pattern {rx.pattern})")
                elif seen[k] > 1:
                    r.fail(name, k, f"duplicate primary key ({seen[k]} rows)")

    def foreign_keys(self) -> None:
        r = self.check("V-FK-01", "Foreign keys reference existing rows", "M2")
        for name, rows in sorted(self.ds.items()):
            for fk in sorted(table(name).foreign_keys, key=lambda f: f.parent.name):
                target = fk.column.table.name
                if target not in self.ds:
                    continue
                values = {t[fk.column.name] for t in self.ds[target]}
                for row in rows:
                    v = row[fk.parent.name]
                    if v is None:
                        continue
                    r.subject(name, f"{_key(name, row)}.{fk.parent.name}")
                    if v not in values:
                        r.fail(name, _key(name, row), f"{fk.parent.name}={v} not found in {target}")

    def enums(self) -> None:
        r = self.check("V-ENUM-01", "Enumerated columns hold allowed values", "DICTIONARY")
        for name, rows in sorted(self.ds.items()):
            allowed = {}
            for c in table(name).constraints:
                if isinstance(c, sa.CheckConstraint) and (m := ENUM_RX.match(str(c.sqltext))):
                    allowed[m.group(1)] = {v.strip().strip("'") for v in m.group(2).split(",")}
            for row in rows:
                r.subject(name, _key(name, row))
                for col, values in sorted(allowed.items()):
                    if row.get(col) is not None and row[col] not in values:
                        r.fail(name, _key(name, row), f"{col}={row[col]} not allowed")

    def derived_ids(self) -> None:
        r = self.check("V-ID-01", "Derived ids match their parents (lines, steps, balances)", "M1")
        for ln in self.rows("expense_line"):
            r.subject("expense_line", ln["expense_line_id"])
            if ln["expense_line_id"] != f"EXPL-{ln['expense_claim_id']}-{ln['line_number']:02d}":
                r.fail("expense_line", ln["expense_line_id"], "id != claim id + line number")
        for s in self.rows("approval_step"):
            r.subject("approval_step", s["approval_step_id"])
            if s["approval_step_id"] != f"APR-{s['leave_request_id'] or s['expense_claim_id']}-{s['sequence_no']:02d}":
                r.fail("approval_step", s["approval_step_id"], "id != request id + sequence")
        for b in self.rows("leave_balance"):
            r.subject("leave_balance", b["leave_balance_id"])
            if b["leave_balance_id"] != f"LBAL-{b['employee_id']}-{b['leave_policy_id']}-{b['leave_year']}":
                r.fail("leave_balance", b["leave_balance_id"], "id != employee + policy + year")

    def date_order(self) -> None:
        r = self.check("V-DATE-01", "Date ranges are ordered", "DATES")
        pairs = {"leave_request": ("start_date", "end_date"),
                 "expense_claim": ("claim_period_start", "claim_period_end"),
                 "employee": ("employment_start", "employment_end"),
                 "delegation": ("effective_from", "effective_to"),
                 "leave_policy": ("effective_start", "effective_end"),
                 "expense_policy": ("effective_start", "effective_end"),
                 "cost_center_budget": ("budget_period_start", "budget_period_end"),
                 "employee_cost_center_assignment": ("effective_from", "effective_to")}
        for name, (a, b) in pairs.items():
            for row in self.rows(name):
                r.subject(name, _key(name, row))
                if row[a] is not None and row[b] is not None and row[b] < row[a]:
                    r.fail(name, _key(name, row), f"{b} {row[b]} before {a} {row[a]}")

    def employment_status(self) -> None:
        r = self.check("V-EMP-01", "TERMINATED exactly when an employment end date exists", "DATES")
        for e in self.rows("employee"):
            r.subject("employee", e["employee_id"])
            if (e["employment_status"] == "TERMINATED") != (e["employment_end"] is not None):
                r.fail("employee", e["employee_id"], "status / end date mismatch")

    def policy_versions(self) -> None:
        r = self.check("V-POL-01", "At most one active policy version per family and date (BR-POL-02)", "CONFIG")
        for name, pk in (("leave_policy", "leave_policy_id"), ("expense_policy", "expense_policy_id")):
            fams = defaultdict(list)
            for p in self.rows(name):
                if p["is_active"]:
                    fams[p["policy_family"]].append(p)
            for fam, versions in sorted(fams.items()):
                r.subject(name, fam)
                versions.sort(key=lambda p: p["effective_start"])
                for a, b in zip(versions, versions[1:]):
                    if a["effective_end"] is None or a["effective_end"] >= b["effective_start"]:
                        r.fail(name, b[pk], f"overlaps {a[pk]} in family {fam}")

    def rule_conflicts(self) -> None:
        """Equal-priority active rules whose scope and bands overlap but whose required levels differ (AM-B10)."""
        r = self.check("V-RULE-01", "No equal-priority approval rules with different outcomes", "CONFIG")
        rules = sorted((x for x in self.rows("approval_rule") if x["is_active"]), key=lambda x: x["approval_rule_id"])

        def band(x):
            lo = x["min_amount_usd"] if x["request_type"] == "EXPENSE" else x["min_days"]
            hi = x["max_amount_usd"] if x["request_type"] == "EXPENSE" else x["max_days"]
            return (Decimal("-1e18") if lo is None else lo, Decimal("1e18") if hi is None else hi)

        for i, a in enumerate(rules):
            r.subject("approval_rule", a["approval_rule_id"])
            for b in rules[i + 1:]:
                if (a["request_type"], a["priority"], a["category_or_leave_type"]) != \
                        (b["request_type"], b["priority"], b["category_or_leave_type"]):
                    continue
                if a["country"] is not None and b["country"] is not None and a["country"] != b["country"]:
                    continue
                (alo, ahi), (blo, bhi) = band(a), band(b)
                if max(alo, blo) < min(ahi, bhi) and list(a["required_levels"]) != list(b["required_levels"]):
                    r.fail("approval_rule", b["approval_rule_id"], f"conflicts with {a['approval_rule_id']} (RULE_CONFLICT)")

    # --- M3 arithmetic ---------------------------------------------------------------------------------------
    def _lines_by_claim(self) -> dict[str, list[dict]]:
        out = defaultdict(list)
        for ln in self.rows("expense_line"):
            out[ln["expense_claim_id"]].append(ln)
        return out

    def claim_totals(self) -> None:
        r = self.check("V-ARITH-01", "Claim total equals the sum of current-round lines (BR-EX-11)", "M3")
        lines = self._lines_by_claim()
        for c in self.rows("expense_claim"):
            r.subject("expense_claim", c["expense_claim_id"])
            s = sum((ln["line_amount"] for ln in lines.get(c["expense_claim_id"], [])
                     if ln["submission_round"] == c["current_round"]), Decimal("0"))
            if s != c["total_amount"]:
                r.fail("expense_claim", c["expense_claim_id"], f"total {c['total_amount']} != sum of lines {s}")

    def approved_amounts(self) -> None:
        r = self.check("V-ARITH-02", "Approved amount = sum of min(line, per-line limit) when APPROVED (BR-EX-14)", "M3")
        lines = self._lines_by_claim()
        for c in self.rows("expense_claim"):
            if c["approved_amount"] is None and c["workflow_status"] != "APPROVED":
                continue
            r.subject("expense_claim", c["expense_claim_id"])
            if c["workflow_status"] != "APPROVED" or c["approved_amount"] is None:
                r.fail("expense_claim", c["expense_claim_id"],
                       f"approved amount {c['approved_amount']} with status {c['workflow_status']}")
                continue
            if c["approved_amount"] > c["total_amount"]:
                r.fail("expense_claim", c["expense_claim_id"], "approved amount exceeds the total")
                continue
            sub = c["first_submitted_at"].date()
            expected = Decimal("0")
            for ln in lines.get(c["expense_claim_id"], []):
                if ln["submission_round"] != c["current_round"] or ln["validation_result"] == "FAIL":
                    continue
                pol = resolve_version(self.rows("expense_policy"), f"XPOL-{ln['category']}-{c['country']}", sub)
                expected += min(ln["line_amount"], pol["per_line_limit"])
            if c["approved_amount"] != expected:
                r.fail("expense_claim", c["expense_claim_id"], f"approved {c['approved_amount']} != expected {expected}")

    def line_arithmetic(self) -> None:
        r = self.check("V-ARITH-03", "Line amount = round(quantity x unit amount, 2) when both are given", "M3")
        for ln in self.rows("expense_line"):
            if ln["quantity"] is None or ln["unit_amount"] is None:
                continue
            r.subject("expense_line", ln["expense_line_id"])
            if (ln["quantity"] * ln["unit_amount"]).quantize(CENT, rounding=ROUND_HALF_UP) != ln["line_amount"]:
                r.fail("expense_line", ln["expense_line_id"],
                       f"{ln['quantity']} x {ln['unit_amount']} != {ln['line_amount']}")

    def reimbursement_amounts(self) -> None:
        r = self.check("V-ARITH-04", "Reimbursement amount and currency match the claim", "M3")
        claims = {c["expense_claim_id"]: c for c in self.rows("expense_claim")}
        for b in self.rows("reimbursement"):
            r.subject("reimbursement", b["reimbursement_id"])
            c = claims.get(b["expense_claim_id"])
            if c and (b["approved_amount"] != c["approved_amount"] or b["currency"] != c["currency"]):
                r.fail("reimbursement", b["reimbursement_id"],
                       f"{b['approved_amount']} {b['currency']} != claim {c['approved_amount']} {c['currency']}")

    def balance_ledger(self) -> None:
        r = self.check("V-ARITH-05", "Leave balance snapshot reconciles with its ledger (BR-LBAL-06)", "M3")
        sums = defaultdict(lambda: defaultdict(Decimal))
        for t in self.rows("leave_balance_transaction"):
            sums[t["leave_balance_id"]][t["txn_type"]] += t["quantity"]
        for b in self.rows("leave_balance"):
            r.subject("leave_balance", b["leave_balance_id"])
            s = sums[b["leave_balance_id"]]
            expected = {
                "opening_balance": s["OPENING"] + s["CARRY_FORWARD"], "accrued": s["ACCRUAL"],
                "used": -(s["USAGE"] + s["USAGE_REVERSAL"]),
                "adjustments": s["ADJUSTMENT"] + s["CARRY_FORWARD_EXPIRY"],
                "available_balance": sum(s.values(), Decimal("0")),
            }
            bad = [f"{k} {b[k]} != ledger {v}" for k, v in expected.items() if b[k] != v]
            if b["available_balance"] != b["opening_balance"] + b["accrued"] + b["adjustments"] - b["used"]:
                bad.append("available != opening + accrued + adjustments - used")
            if bad:
                r.fail("leave_balance", b["leave_balance_id"], "; ".join(bad))

    def leave_quantities(self) -> None:
        r = self.check("V-ARITH-06", "Leave business days and quantity recompute from the calendar (BR-CAL-03/04)", "M3")
        emps = {e["employee_id"]: e for e in self.rows("employee")}
        for q in self.rows("leave_request"):
            if q["employee_id"] not in emps:
                continue
            r.subject("leave_request", q["leave_request_id"])
            bd = self.cal.business_day_count(q["start_date"], q["end_date"], emps[q["employee_id"]]["country"])
            if q["business_day_count"] != bd or \
                    q["requested_quantity"] != requested_quantity(bd, q["start_half_day"], q["end_half_day"]):
                r.fail("leave_request", q["leave_request_id"],
                       f"stored {q['business_day_count']} / {q['requested_quantity']} vs calendar {bd} business days")

    def fx_conversion(self) -> None:
        r = self.check("V-ARITH-07", "USD total = round(total / rate on the submission date, 2) when present", "M3")
        for c in self.rows("expense_claim"):
            if c["total_amount_usd"] is None:
                continue
            r.subject("expense_claim", c["expense_claim_id"])
            rate = fx_rate_on(self.rows("fx_rate"), "USD", c["currency"], c["first_submitted_at"].date())
            expected = (c["total_amount"] / rate).quantize(CENT, rounding=ROUND_HALF_UP)
            if c["fx_rate_used"] != rate or c["total_amount_usd"] != expected:
                r.fail("expense_claim", c["expense_claim_id"],
                       f"usd {c['total_amount_usd']} at {c['fx_rate_used']} != {expected} at {rate}")

    def budget_ledger(self) -> None:
        r = self.check("V-ARITH-08", "Budget committed / actual snapshots reconcile with the budget ledger", "M3")
        sums = defaultdict(lambda: defaultdict(Decimal))
        for t in self.rows("cost_center_transaction"):
            sums[t["cost_center_budget_id"]][t["txn_type"]] += t["amount"]
        for b in self.rows("cost_center_budget"):
            r.subject("cost_center_budget", b["cost_center_budget_id"])
            s = sums[b["cost_center_budget_id"]]
            committed = s["RESERVATION"] - s["RELEASE"] - s["ACTUAL"]
            if b["committed_amount"] != committed or b["actual_amount"] != s["ACTUAL"]:
                r.fail("cost_center_budget", b["cost_center_budget_id"],
                       f"committed/actual {b['committed_amount']}/{b['actual_amount']} != ledger {committed}/{s['ACTUAL']}")

    # --- lifecycle and workflow integrity ---------------------------------------------------------------------
    def lifecycle(self) -> None:
        r = self.check("V-LIFE-01", "Status history uses legal transitions and ends in the stored status", "WORKFLOW")
        current = {**{q["leave_request_id"]: q["workflow_status"] for q in self.rows("leave_request")},
                   **{c["expense_claim_id"]: c["workflow_status"] for c in self.rows("expense_claim")}}
        events = defaultdict(list)
        for e in self.rows("request_status_event"):
            events[e["leave_request_id"] or e["expense_claim_id"]].append(e)
        for req, evs in sorted(events.items()):
            r.subject("request", req)
            evs.sort(key=lambda e: (e["occurred_at"], e["event_id"]))
            prev = None
            for e in evs:
                if (e["previous_status"], e["new_status"]) not in LEGAL_TRANSITIONS:
                    r.fail("request_status_event", e["event_id"],
                           f"illegal transition {e['previous_status']} -> {e['new_status']}")
                elif prev is not None and e["previous_status"] != prev:
                    r.fail("request_status_event", e["event_id"],
                           f"previous_status {e['previous_status']} != last status {prev}")
                prev = e["new_status"]
            if req in current and prev != current[req]:
                r.fail("request_status_event", req, f"history ends in {prev} but the request is {current[req]}")

    def approval_sequence(self) -> None:
        r = self.check("V-WF-01", "Approval steps decided in sequence (no level skipped)", "WORKFLOW")
        rounds = defaultdict(list)
        for s in self.rows("approval_step"):
            rounds[(s["leave_request_id"] or s["expense_claim_id"], s["submission_round"])].append(s)
        for key, steps in sorted(rounds.items()):
            r.subject("request_round", f"{key[0]}#{key[1]}")
            steps.sort(key=lambda s: s["sequence_no"])
            for earlier, later in zip(steps, steps[1:]):
                if later["step_status"] in ("APPROVED", "REJECTED") and earlier["step_status"] != "APPROVED":
                    r.fail("approval_step", later["approval_step_id"],
                           f"decided while {earlier['approval_step_id']} is {earlier['step_status']}")

    def self_approval(self) -> None:
        r = self.check("V-WF-02", "No decided step or accepted attempt by the requester (spec 13.3)", "M9")
        owner = {**{q["leave_request_id"]: q["employee_id"] for q in self.rows("leave_request")},
                 **{c["expense_claim_id"]: c["employee_id"] for c in self.rows("expense_claim")}}
        for s in self.rows("approval_step"):
            if s["step_status"] in ("APPROVED", "REJECTED"):
                r.subject("approval_step", s["approval_step_id"])
                if s["approver_employee_id"] == owner.get(s["leave_request_id"] or s["expense_claim_id"]):
                    r.fail("approval_step", s["approval_step_id"], "approver is the requester")
        for a in self.rows("approval_attempt"):
            if a["outcome"] == "ACCEPTED":
                r.subject("approval_attempt", a["attempt_id"])
                if a["actor_id"] == owner.get(a["leave_request_id"] or a["expense_claim_id"]):
                    r.fail("approval_attempt", a["attempt_id"], "accepted attempt by the requester")

    def reimbursement_eligibility(self) -> None:
        r = self.check("V-WF-03", "Reimbursements only for APPROVED claims, at most one active, after approval", "M12")
        claims = {c["expense_claim_id"]: c for c in self.rows("expense_claim")}
        steps = {s["approval_step_id"]: s for s in self.rows("approval_step")}
        active = defaultdict(list)
        for b in self.rows("reimbursement"):
            if b["reimbursement_status"] == "CANCELLED":
                continue
            r.subject("reimbursement", b["reimbursement_id"])
            active[b["expense_claim_id"]].append(b)
            c = claims.get(b["expense_claim_id"])
            if c is not None and c["workflow_status"] != "APPROVED":
                r.fail("reimbursement", b["reimbursement_id"], f"claim is {c['workflow_status']}")
            step = steps.get(b["approval_completion_step_id"])
            if step is not None and step["decision_at"] is not None and b["created_at"] < step["decision_at"]:
                r.fail("reimbursement", b["reimbursement_id"], "created before the final approval")
        for claim_id, items in sorted(active.items()):
            if len(items) > 1:
                r.fail("reimbursement", claim_id, f"{len(items)} active reimbursements for one claim")

    def cost_center_exception(self) -> None:
        r = self.check("V-WF-04", "A claim without a cost center carries an exception class (AM-A2)", "WORKFLOW")
        for c in self.rows("expense_claim"):
            r.subject("expense_claim", c["expense_claim_id"])
            if c["cost_center_id"] is None and c["exception_class"] == "NONE":
                r.fail("expense_claim", c["expense_claim_id"], "NULL cost center with exception class NONE")

    def approver_employed_at_decision(self) -> None:
        """AMB-P7B-06: no step decision dated after the assigned approver's employment end date."""
        r = self.check("V-WF-05", "No approval decision after the approver's employment end date (AMB-P7B-06)",
                       "WORKFLOW")
        end = {e["employee_id"]: e["employment_end"] for e in self.rows("employee")}
        for s in self.rows("approval_step"):
            if s["decision_at"] is not None:
                r.subject("approval_step", s["approval_step_id"])
                left = end.get(s["approver_employee_id"])
                if left is not None and s["decision_at"].date() > left:
                    r.fail("approval_step", s["approval_step_id"],
                           f"decided {s['decision_at'].date()} by {s['approver_employee_id']}, employment ended {left}")


def validate(ds: dict[str, list[dict]], weekend_days: dict[str, list[int]]) -> list[CheckResult]:
    return Validator(ds, weekend_days).run()


def summary_metrics(results: list[CheckResult]) -> dict[str, dict]:
    """M1, M2 and M3 from the actual check results (docs/08 section 3)."""
    by_id = {r.check_id: r for r in results}
    pk, fk = by_id["V-PK-01"], by_id["V-FK-01"]
    pk_bad = len({(f.table_name, f.record_id) for f in pk.findings + by_id["V-ID-01"].findings})
    arith = [r for r in results if r.metric == "M3"]
    subjects = set().union(*(r.subject_keys for r in arith)) if arith else set()
    failing = {(f.table_name, f.record_id) for r in arith for f in r.findings}

    def rate(num: int, den: int):
        return None if den == 0 else round(num / den, 6)

    return {
        "M1": {"name": "Primary-key violation rate", "numerator": pk_bad, "denominator": pk.subjects,
               "value": rate(pk_bad, pk.subjects)},
        "M2": {"name": "Foreign-key violation rate", "numerator": fk.violations, "denominator": fk.subjects,
               "value": rate(fk.violations, fk.subjects)},
        "M3": {"name": "Arithmetic reconciliation rate", "numerator": len(subjects) - len(failing & subjects),
               "denominator": len(subjects), "value": rate(len(subjects) - len(failing & subjects), len(subjects))},
    }
