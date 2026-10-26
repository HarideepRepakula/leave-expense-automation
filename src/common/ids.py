"""Deterministic ID formats (spec section 8, amendment A6, docs/07 section 3).

Phase 2 provides the regular expressions used by database CHECK constraints and by tests.
Phase 3 adds the formatting and counter-allocation functions that the generator and services use.
Every pattern is anchored and zero-padded exactly as the specification requires.
"""
from __future__ import annotations

CC = r"(IN|US|GB)"
CC_OR_ALL = r"(IN|US|GB|ALL)"
CCY = r"[A-Z]{3}"

ID_PATTERNS: dict[str, str] = {
    "employee": r"^EMP-\d{6}$",
    "department": r"^DEPT-\d{2}$",
    "cost_center": r"^CC-\d{4}$",
    "cost_center_budget": r"^CCB-CC-\d{4}-\d{4}$",
    "employee_cost_center_assignment": r"^ECA-\d{6}$",
    "country_holiday": rf"^HOL-{CC}-\d{{8}}$",
    "fx_rate": rf"^FX-{CCY}-{CCY}-\d{{8}}$",
    "delegation": r"^DLG-\d{6}$",
    "leave_policy": rf"^LPOL-[A-Z]+-{CC_OR_ALL}-V\d+$",
    "expense_policy": rf"^XPOL-[A-Z_]+-{CC}-V\d+$",
    "approval_rule": r"^RULE-(L|E)-\d{3}$",
    "exception_code": r"^[A-Z][A-Z_]+$",
    "leave_balance": rf"^LBAL-EMP-\d{{6}}-LPOL-[A-Z]+-{CC_OR_ALL}-V\d+-\d{{4}}$",
    "leave_request": r"^LVE-\d{4}-\d{6}$",
    "leave_balance_transaction": r"^LBT-\d{4}-\d{6}$",
    "receipt": r"^RCT-\d{9}$",
    "expense_claim": r"^EXP-\d{4}-\d{6}$",
    "expense_line": r"^EXPL-EXP-\d{4}-\d{6}-\d{2}$",
    "cost_center_transaction": r"^CCT-\d{9}$",
    "approval_step": r"^APR-(LVE|EXP)-\d{4}-\d{6}-\d{2}$",
    "approval_event": r"^APE-\d{9}$",
    "approval_attempt": r"^APA-\d{9}$",
    "request_status_event": r"^RSE-\d{9}$",
    "request_exception": r"^REX-\d{9}$",
    "reimbursement": r"^RMB-\d{4}-\d{6}$",
    "reimbursement_attempt": r"^RMA-\d{9}$",
    "audit_event": r"^AUD-\d{9}$",
    "processing_failure": r"^PFL-\d{9}$",
    "application_user": r"^USR-\d{6}$",
    "role": r"^ROLE-[A-Z_]+$",
    "anomaly_label": r"^GTL-\d{6}$",
    "boundary_case": r"^GTB-\d{4}$",
    "sha256_hex": r"^[0-9a-f]{64}$",
}


def pattern(entity: str) -> str:
    """Return the anchored regex for an entity, raising KeyError for unknown names."""
    return ID_PATTERNS[entity]
