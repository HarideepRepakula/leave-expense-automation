"""Write the negative fixtures in tests/fixtures/negative/ (docs/07 sections 7.2 Group D and 7.3, AM-A2).

    python scripts/build_negative_fixtures.py

Fixtures break structural integrity on purpose and are NEVER part of the generated dataset. Tests load them into
in-memory tables and assert that src/validation (or the reference oracle, for rule conflicts) detects each one.
Values use the canonical export text (ISO dates, UTC timestamps with Z, decimals as text). Synthetic only.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "negative"
CORR = "00000000-0000-5000-8000-000000000001"


def event(n: int, prev: str | None, new: str, at: str) -> dict:
    return {"event_id": f"RSE-{n:09d}", "request_type": "LEAVE", "leave_request_id": "LVE-2026-000001",
            "submission_round": "1", "previous_status": prev or "", "new_status": new,
            "occurred_at": at, "correlation_id": CORR}


LIFECYCLE = [  # S16: eight distinct illegal transitions (docs/06 2.2)
    ("DRAFT", "APPROVED"), ("REJECTED", "PENDING_APPROVAL"), ("APPROVED", "CANCELLED"), ("SUBMITTED", "APPROVED"),
    ("CANCELLED", "SUBMITTED"), ("PENDING_APPROVAL", "DRAFT"), ("VALIDATING", "CANCELLED"),
    ("RETURNED_FOR_CORRECTION", "APPROVED"),
]


def claim(cid: str, total: str, **kw) -> dict:
    row = {"expense_claim_id": cid, "employee_id": "EMP-000001", "first_submitted_at": "2026-03-02T09:00:00Z",
           "claim_period_start": "2026-02-20", "claim_period_end": "2026-02-20", "country": "IN", "currency": "INR",
           "cost_center_id": "CC-0001", "total_amount": total, "workflow_status": "SUBMITTED",
           "exception_class": "NONE", "receipt_status": "NOT_REQUIRED", "current_round": "1",
           "created_at": "2026-03-02T09:00:00Z"}
    row.update(kw)
    return row


def line(cid: str, n: int, amount: str, **kw) -> dict:
    row = {"expense_line_id": f"EXPL-{cid}-{n:02d}", "expense_claim_id": cid, "line_number": str(n),
           "submission_round": "1", "category": "MEALS", "merchant_description": "Lunch - Example Pvt Ltd",
           "expense_date": "2026-02-20", "line_amount": amount, "currency": "INR", "validation_result": "PENDING"}
    row.update(kw)
    return row


C = "EXP-2026-000001"
ARITHMETIC = [  # S17: eight arithmetic mismatches (docs/07 7.2 Group D)
    ("total_too_high", "V-ARITH-01", "claim total above the sum of its lines",
     {"expense_claim": [claim(C, "1500.00")], "expense_line": [line(C, 1, "1000.00")]}),
    ("total_too_low", "V-ARITH-01", "claim total below the sum of its lines",
     {"expense_claim": [claim(C, "500.00")], "expense_line": [line(C, 1, "1000.00")]}),
    ("quantity_times_unit", "V-ARITH-03", "line amount differs from quantity x unit amount",
     {"expense_claim": [claim(C, "3500.00")],
      "expense_line": [line(C, 1, "3500.00", quantity="3.00", unit_amount="1000.00")]}),
    ("approved_above_total", "V-ARITH-02", "approved amount greater than the claim total",
     {"expense_claim": [claim(C, "1000.00", workflow_status="APPROVED", approved_amount="1200.00")],
      "expense_line": [line(C, 1, "1000.00")]}),
    ("reimbursement_amount", "V-ARITH-04", "reimbursement amount differs from the approved amount",
     {"expense_claim": [claim(C, "1000.00", workflow_status="APPROVED", approved_amount="1000.00")],
      "reimbursement": [{"reimbursement_id": "RMB-2026-000001", "expense_claim_id": C, "employee_id": "EMP-000001",
                         "approved_amount": "900.00", "currency": "INR", "eligibility_status": "ELIGIBLE",
                         "reimbursement_status": "ELIGIBLE", "approval_completion_step_id": f"APR-{C}-01",
                         "created_at": "2026-03-05T10:00:00Z"}]}),
    ("balance_snapshot", "V-ARITH-05", "leave balance snapshot differs from the ledger",
     {"leave_balance": [{"leave_balance_id": "LBAL-EMP-000001-LPOL-ANNUAL-IN-V1-2026", "employee_id": "EMP-000001",
                         "leave_policy_id": "LPOL-ANNUAL-IN-V1", "leave_year": "2026", "opening_balance": "0.0",
                         "accrued": "10.0", "adjustments": "0.0", "used": "0.0", "available_balance": "10.0",
                         "last_recalculated_at": "2026-10-22T00:00:00Z"}],
      "leave_balance_transaction": [{"transaction_id": "LBT-2026-000001",
                                     "leave_balance_id": "LBAL-EMP-000001-LPOL-ANNUAL-IN-V1-2026",
                                     "txn_type": "ACCRUAL", "quantity": "8.0", "txn_date": "2026-01-01",
                                     "posted_at": "2026-01-01T00:00:00Z", "reason": "Monthly accrual",
                                     "correlation_id": CORR}]}),
    ("fx_conversion", "V-ARITH-07", "USD total differs from total / rate on the submission date",
     {"expense_claim": [claim(C, "8450.00", total_amount_usd="120.00", fx_rate_used="84.500000")],
      "expense_line": [line(C, 1, "8450.00")],
      "fx_rate": [{"fx_rate_id": "FX-USD-INR-20260101", "from_currency": "USD", "to_currency": "INR",
                   "rate": "84.500000", "effective_from": "2026-01-01"}]}),
    ("budget_snapshot", "V-ARITH-08", "budget committed amount differs from the budget ledger",
     {"cost_center_budget": [{"cost_center_budget_id": "CCB-CC-0001-2026", "cost_center_id": "CC-0001",
                              "budget_period_start": "2026-01-01", "budget_period_end": "2026-12-31",
                              "currency": "INR", "budget_amount": "1000000.00", "committed_amount": "5000.00",
                              "actual_amount": "0.00"}],
      "cost_center_transaction": [{"transaction_id": "CCT-000000001", "cost_center_id": "CC-0001",
                                   "cost_center_budget_id": "CCB-CC-0001-2026", "expense_claim_id": C,
                                   "txn_type": "RESERVATION", "amount": "3000.00", "currency": "INR",
                                   "txn_date": "2026-03-02", "posted_at": "2026-03-02T09:00:00Z",
                                   "correlation_id": CORR}]}),
]

STRUCTURAL = [  # docs/07 7.3: dangling references and a malformed id
    ("line_without_claim", "V-FK-01", "expense line references a claim that does not exist",
     {"expense_claim": [claim(C, "100.00")], "expense_line": [line("EXP-2026-000999", 1, "100.00")]}),
    ("step_without_request", "V-FK-01", "approval step references a leave request that does not exist",
     {"leave_request": [], "approval_step": [{"approval_step_id": "APR-LVE-2026-000999-01", "request_type": "LEAVE",
                                              "leave_request_id": "LVE-2026-000999", "submission_round": "1",
                                              "sequence_no": "1", "approval_rule_id": "RULE-L-001",
                                              "required_level": "L1", "step_status": "PENDING"}]}),
    ("malformed_employee_id", "V-PK-01", "employee id EMP-1 does not match EMP-nnnnnn",
     {"employee": [{"employee_id": "EMP-1", "full_name": "Example Person", "email": "example.person@example.test",
                    "department_id": "DEPT-01", "job_title": "Associate, Engineering", "grade": "G1",
                    "country": "IN", "currency": "INR", "employment_start": "2024-01-01",
                    "employment_status": "ACTIVE", "default_cost_center_id": "CC-0001",
                    "is_department_head": "false", "is_finance_controller": "false",
                    "created_at": "2024-12-31T00:00:00Z"}]}),
]

CONFLICTS = [  # S20: equal priority, overlapping band, different outcome (docs/05 5.2, AMB-14)
    ("expense", {"id": "RULE-E-005", "request_type": "EXPENSE", "min_amount_usd": "200.00",
                 "max_amount_usd": "1000.00", "levels": ["L1", "L4"], "priority": 10},
     {"request_type": "EXPENSE", "measure": "500.00"}),
    ("leave", {"id": "RULE-L-005", "request_type": "LEAVE", "max_days": "5.0", "levels": ["L1", "L3"],
               "priority": 10},
     {"request_type": "LEAVE", "measure": "3.0"}),
]


def dump(path: Path, doc) -> None:
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    base = yaml.safe_load((ROOT / "config" / "approval_rules.yaml").read_text(encoding="utf-8"))
    for i, (prev, new) in enumerate(LIFECYCLE, start=1):
        dump(OUT / f"lifecycle_{i:02d}.json", {
            "fixture_id": f"S16-{i:02d}", "scenario_id": "S16", "expected_checks": ["V-LIFE-01"],
            "description": f"illegal transition {prev} -> {new}",
            "tables": {"request_status_event": [event(1, None, "SUBMITTED", "2026-03-01T09:00:00Z"),
                                                event(2, "SUBMITTED", "VALIDATING", "2026-03-01T09:00:01Z"),
                                                event(3, prev, new, "2026-03-02T09:00:00Z")]}})
    for i, (slug, check, desc, tables) in enumerate(ARITHMETIC, start=1):
        dump(OUT / f"arithmetic_{i:02d}_{slug}.json", {"fixture_id": f"S17-{i:02d}", "scenario_id": "S17",
                                                       "expected_checks": [check], "description": desc,
                                                       "tables": tables})
    for i, (slug, check, desc, tables) in enumerate(STRUCTURAL, start=1):
        dump(OUT / f"structural_{i:02d}_{slug}.json", {"fixture_id": f"STR-{i:02d}", "scenario_id": "STRUCTURAL",
                                                       "expected_checks": [check], "description": desc,
                                                       "tables": tables})
    for i, (slug, extra, probe) in enumerate(CONFLICTS, start=1):
        doc = {"illustrative_synthetic": True, "fixture_id": f"S20-{i:02d}", "scenario_id": "S20",
               "description": f"{slug} rule set with two equal-priority rules of different outcome",
               "expected": "RULE_CONFLICT", "probe": probe, "effective_start": str(base["effective_start"]),
               "rules": base["rules"] + [extra]}
        (OUT / f"rules_conflict_{i:02d}_{slug}.yaml").write_text(
            yaml.safe_dump(doc, sort_keys=False), encoding="utf-8", newline="\n")
    print(f"wrote {len(LIFECYCLE)} lifecycle, {len(ARITHMETIC)} arithmetic, {len(STRUCTURAL)} structural, "
          f"{len(CONFLICTS)} rule-conflict fixtures to {OUT}")


if __name__ == "__main__":
    main()
