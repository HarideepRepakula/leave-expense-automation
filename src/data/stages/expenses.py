"""S4 expense claims, lines and receipts: raw inputs only (docs/07 section 2).

Random: employee, submission timestamp, line count, categories, expense dates, USD amounts (log-uniform,
ASM-041), merchants, receipt presence below the threshold, receipt numbers, draft flag.
Calculated: local amounts (FX on the submission date, ASM-031), claim total = SUM(lines) (BR-EX-11), claim
period, country and currency (DEC-14), cost center from the assignment on the earliest line date (DEC-13),
receipt hash (ASM-020), receipt_status.

Valid baseline (CF-06): every line is within its per-line limit, the total within the per-claim limit, lines
within employment and at most 90 days before submission, a receipt on every line at or above the threshold,
one currency, unique receipt hashes. Policy ids, FX and USD totals on the claim stay NULL and lines stay
PENDING until the Phase 6 services validate them in stage S6 (AMB-P3-01).
"""
from __future__ import annotations

import hashlib
import math
from datetime import date, timedelta
from decimal import Decimal

import numpy as np

from src.common import ids
from src.common.enums import ExceptionClass, LineValidationResult, ReceiptStatus, WorkflowStatus
from src.common.money import fx_rate_on, money
from src.common.rng import RngStreams
from src.data.sampling import pick, timestamp_on, weighted_date, weighted_pick
from src.data.stages import GenParams
from src.services.policy_resolver import resolve_version


def receipt_hash(merchant: str, d: date, amount: Decimal, currency: str, number: str) -> str:
    """ASM-020: SHA-256 of "merchant|date|amount|currency|synthetic-receipt-no"."""
    return hashlib.sha256(f"{merchant}|{d.isoformat()}|{amount:.2f}|{currency}|{number}".encode()).hexdigest()


def assignment_on(assignments: list[dict], on: date) -> str | None:
    """DEC-13: the employee's cost center assignment effective on a date."""
    for a in assignments:
        if a["effective_from"] <= on and (a["effective_to"] is None or on <= a["effective_to"]):
            return a["cost_center_id"]
    return None


def build_expense_claims(cfg: dict, p: GenParams, streams: RngStreams, employees: list[dict],
                         assignments: list[dict], policies: list[dict], fx: list[dict]) -> dict[str, list[dict]]:
    xcfg = cfg["generation"]["expenses"]
    tcfg = cfg["generation"]["timeline"]
    rng = streams.get("expenses")
    fakers = streams.fakers("expenses")
    last_submit = p.as_of - timedelta(days=1)
    eligible = [
        e for e in employees
        if e["grade"] != "G7"
        and e["employment_start"] + timedelta(days=1) <= last_submit
        and (e["employment_end"] is None or e["employment_end"] >= p.window_start)
    ]
    assignments_by_emp: dict[str, list[dict]] = {}
    for a in assignments:
        assignments_by_emp.setdefault(a["employee_id"], []).append(a)

    accepted = []
    for c in range(p.expense_claims):
        for _ in range(xcfg["max_attempts_per_claim"]):
            claim = _draw(rng, fakers, xcfg, tcfg, p, eligible, policies, fx, last_submit)
            if claim is not None:
                break
        else:
            raise RuntimeError(f"could not draw a valid expense claim #{c}")
        claim["draw"] = c
        claim["is_draft"] = bool(rng.random() < tcfg["draft_share"])
        accepted.append(claim)

    accepted.sort(key=lambda x: (x["ts"], x["draw"]))
    counters: dict[int, int] = {}
    claims, lines, receipts = [], [], []
    receipt_no = 0
    for claim in accepted:
        year = claim["ts"].year
        counters[year] = counters.get(year, 0) + 1
        claim_id = ids.expense_claim_id(year, counters[year])
        emp = claim["emp"]
        ordered = sorted(enumerate(claim["lines"]), key=lambda x: (x[1]["expense_date"], x[0]))
        for line_number, (_, ln) in enumerate(ordered, start=1):
            rid = None
            if ln["has_receipt"]:
                receipt_no += 1
                rid = ids.receipt_id(receipt_no)
                receipts.append({
                    "receipt_id": rid,
                    "receipt_hash": receipt_hash(ln["merchant"], ln["expense_date"], ln["amount"],
                                                 claim["currency"], ln["receipt_number"]),
                    "receipt_number": ln["receipt_number"],
                    "merchant": ln["merchant"],
                    "receipt_date": ln["expense_date"],
                    "amount": ln["amount"],
                    "currency": claim["currency"],
                    "created_at": claim["ts"],
                })
            lines.append({
                "expense_line_id": ids.expense_line_id(claim_id, line_number),
                "expense_claim_id": claim_id,
                "line_number": line_number,
                "submission_round": 1,
                "category": ln["category"],
                "merchant_description": f"{ln['label']} - {ln['merchant']}",
                "expense_date": ln["expense_date"],
                "quantity": None,
                "unit_amount": None,
                "line_amount": ln["amount"],
                "currency": claim["currency"],
                "receipt_id": rid,
                "cost_center_id": None,          # NULL = inherit the claim's cost center (DEC-16)
                "expense_policy_id": None,       # resolved by the Phase 6 policy resolver in stage S6
                "validation_result": LineValidationResult.PENDING.value,
                "validation_detail": None,
            })
        dates = [ln["expense_date"] for ln in claim["lines"]]
        claims.append({
            "expense_claim_id": claim_id,
            "employee_id": emp["employee_id"],
            "first_submitted_at": None if claim["is_draft"] else claim["ts"],
            "claim_period_start": min(dates),
            "claim_period_end": max(dates),
            "country": emp["country"],
            "currency": claim["currency"],
            "cost_center_id": assignment_on(assignments_by_emp[emp["employee_id"]], min(dates)),
            "expense_policy_id": None,
            "total_amount": money(sum(ln["amount"] for ln in claim["lines"])),
            "approved_amount": None,
            "total_amount_usd": None,
            "fx_rate_used": None,
            "workflow_status": WorkflowStatus.DRAFT.value if claim["is_draft"] else WorkflowStatus.SUBMITTED.value,
            "exception_class": ExceptionClass.NONE.value,
            "receipt_status": (ReceiptStatus.COMPLETE.value if claim["receipt_required"]
                               else ReceiptStatus.NOT_REQUIRED.value),
            "current_round": 1,
            "decision_reason_code": None,
            "decision_reason_text": None,
            "created_at": claim["ts"],
        })
    hashes = [r["receipt_hash"] for r in receipts]
    if len(hashes) != len(set(hashes)):
        raise RuntimeError("baseline produced a duplicate receipt hash; duplicates are planted only in Phase 4")
    return {"receipt": receipts, "expense_claim": claims, "expense_line": lines}


def _draw(rng: np.random.Generator, fakers: dict, xcfg: dict, tcfg: dict, p: GenParams, eligible: list[dict],
          policies: list[dict], fx: list[dict], last_submit: date) -> dict | None:
    emp = pick(rng, eligible)
    country = emp["country"]
    currency = emp["currency"]
    lo = max(p.window_start, emp["employment_start"] + timedelta(days=1))
    hi = min(last_submit, emp["employment_end"] or last_submit)
    if lo > hi:
        return None
    sub_date = weighted_date(rng, lo, hi, tcfg["weekend_submission_weight"])
    ts = timestamp_on(rng, sub_date, tcfg["submission_hour_min"], tcfg["submission_hour_max"])
    weights = np.array(xcfg["line_count_weights"], dtype=float)
    n_lines = int(rng.choice(len(weights), p=weights / weights.sum())) + 1
    primary = weighted_pick(rng, xcfg["primary_category_weights"])
    gap_lo, gap_hi = xcfg["submission_after_latest_line_days"]
    latest = sub_date - timedelta(days=int(rng.integers(gap_lo, gap_hi + 1)))
    earliest = max(sub_date - timedelta(days=xcfg["max_line_age_days"]), emp["employment_start"])
    if latest < earliest:
        return None
    rate = fx_rate_on(fx, "USD", currency, sub_date)
    others = [c for c in xcfg["primary_category_weights"] if c != primary]

    lines = []
    for i in range(n_lines):
        category = primary if rng.random() < xcfg["same_category_share"] else pick(rng, others)
        if i == 0:
            expense_date = latest
        else:
            expense_date = earliest + timedelta(days=int(rng.integers(0, (latest - earliest).days + 1)))
        lo_usd, hi_usd = xcfg["amount_range_usd"][category]
        usd = Decimal(f"{math.exp(rng.uniform(math.log(lo_usd), math.log(hi_usd))):.2f}")
        merchant = fakers[country].company()
        lines.append({
            "category": category,
            "expense_date": expense_date,
            "amount": money(usd * rate),
            "label": pick(rng, xcfg["merchant_labels"][category]),
            "merchant": merchant,
            "receipt_number": f"INV-{int(rng.integers(10_000_000, 100_000_000))}",
            "receipt_draw": rng.random(),
        })

    # Validity guards against the policy version effective on the submission date (BR-POL-01).
    receipt_required = False
    for ln in lines:
        pol = resolve_version(policies, f"XPOL-{ln['category']}-{country}", sub_date)
        if ln["amount"] > pol["per_line_limit"]:
            return None
        needs = ln["amount"] >= pol["receipt_threshold"]
        receipt_required |= needs
        ln["has_receipt"] = needs or ln["receipt_draw"] < xcfg["receipt_below_threshold_share"]
    top = max(lines, key=lambda ln: ln["amount"])  # primary category = highest-amount line (BR-EX-03)
    claim_limit = resolve_version(policies, f"XPOL-{top['category']}-{country}", sub_date)["per_claim_limit"]
    if sum(ln["amount"] for ln in lines) > claim_limit:
        return None
    return {"emp": emp, "ts": ts, "currency": currency, "lines": lines, "receipt_required": receipt_required}
