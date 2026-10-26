"""Controlled vocabularies (docs/04 section 4, docs/05, docs/06).

Each enum is the single source of truth for one status dimension. The database stores the values as
text with a CHECK constraint generated from these enums (src/models/base.py), Pydantic schemas reuse
them (Phase 9) and the lifecycle transition table (Phase 7) is keyed by them. Dimensions are never
mixed: workflow status, exception class, step status, reimbursement status and technical failures
are separate (amendment D).
"""
from __future__ import annotations

from enum import StrEnum


def values(enum_cls: type[StrEnum]) -> list[str]:
    """Return the string values of an enum, in declaration order."""
    return [member.value for member in enum_cls]


# --- geography and money (ASM-001, ASM-002) ---------------------------------------------------
class Country(StrEnum):
    IN = "IN"
    US = "US"
    GB = "GB"


class CountryScope(StrEnum):
    IN = "IN"
    US = "US"
    GB = "GB"
    ALL = "ALL"


class Currency(StrEnum):
    INR = "INR"
    USD = "USD"
    GBP = "GBP"


CURRENCY_BY_COUNTRY: dict[Country, Currency] = {
    Country.IN: Currency.INR,
    Country.US: Currency.USD,
    Country.GB: Currency.GBP,
}


# --- organisation (ASM-014, AM-B7) ------------------------------------------------------------
class Grade(StrEnum):
    G1 = "G1"
    G2 = "G2"
    G3 = "G3"
    G4 = "G4"
    G5 = "G5"
    G6 = "G6"
    G7 = "G7"


class EmploymentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    ON_LEAVE_OF_ABSENCE = "ON_LEAVE_OF_ABSENCE"


class ApprovalLevel(StrEnum):
    L1 = "L1"  # direct manager
    L2 = "L2"  # skip-level manager
    L3 = "L3"  # department head
    L4 = "L4"  # finance controller (country)
    L5 = "L5"  # CFO-level (grade G7)


# --- policies ---------------------------------------------------------------------------------
class LeaveType(StrEnum):
    ANNUAL = "ANNUAL"
    SICK = "SICK"
    CASUAL = "CASUAL"
    UNPAID = "UNPAID"


class AccrualMethod(StrEnum):
    MONTHLY = "MONTHLY"
    ANNUAL_GRANT = "ANNUAL_GRANT"
    NONE = "NONE"


class ExpenseCategory(StrEnum):
    TRAVEL = "TRAVEL"
    MEALS = "MEALS"
    ACCOMMODATION = "ACCOMMODATION"
    OFFICE_SUPPLIES = "OFFICE_SUPPLIES"
    TRAINING = "TRAINING"
    CLIENT_ENTERTAINMENT = "CLIENT_ENTERTAINMENT"


class RequestType(StrEnum):
    LEAVE = "LEAVE"
    EXPENSE = "EXPENSE"


# --- dimension 1: workflow status (amendment D1) ------------------------------------------------
class WorkflowStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VALIDATING = "VALIDATING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    RETURNED_FOR_CORRECTION = "RETURNED_FOR_CORRECTION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    ESCALATED_FOR_REVIEW = "ESCALATED_FOR_REVIEW"


# --- dimension 2: exception class and codes (amendment D2) -------------------------------------
class ExceptionClass(StrEnum):
    NONE = "NONE"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    SUSPICIOUS_PATTERN = "SUSPICIOUS_PATTERN"
    DATA_QUALITY = "DATA_QUALITY"
    NO_VALID_APPROVAL_PATH = "NO_VALID_APPROVAL_PATH"
    RULE_CONFLICT = "RULE_CONFLICT"


class Severity(StrEnum):
    HARD = "HARD"              # -> REJECTED
    CORRECTABLE = "CORRECTABLE"  # -> RETURNED_FOR_CORRECTION
    SOFT = "SOFT"              # -> ESCALATED_FOR_REVIEW
    INFO = "INFO"              # no routing effect


class DefaultRoute(StrEnum):
    REJECTED = "REJECTED"
    RETURNED_FOR_CORRECTION = "RETURNED_FOR_CORRECTION"
    ESCALATED_FOR_REVIEW = "ESCALATED_FOR_REVIEW"
    NONE = "NONE"


class DetectedBy(StrEnum):
    SUBMISSION = "SUBMISSION"
    BATCH_DETECTOR = "BATCH_DETECTOR"
    REVIEW = "REVIEW"


# --- expenses -----------------------------------------------------------------------------------
class ReceiptStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    COMPLETE = "COMPLETE"
    MISSING = "MISSING"


class LineValidationResult(StrEnum):
    PENDING = "PENDING"
    PASS = "PASS"
    CAPPED = "CAPPED"
    FAIL = "FAIL"


class BudgetTxnType(StrEnum):
    RESERVATION = "RESERVATION"
    RELEASE = "RELEASE"
    ACTUAL = "ACTUAL"
    OVERRIDE = "OVERRIDE"


# --- leave ledger -------------------------------------------------------------------------------
class LeaveTxnType(StrEnum):
    OPENING = "OPENING"
    ACCRUAL = "ACCRUAL"
    USAGE = "USAGE"
    USAGE_REVERSAL = "USAGE_REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"
    CARRY_FORWARD = "CARRY_FORWARD"
    CARRY_FORWARD_EXPIRY = "CARRY_FORWARD_EXPIRY"


# --- dimension 5: approval steps (amendment D5) --------------------------------------------------
class StepStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class ApprovalEventType(StrEnum):
    ASSIGNED = "ASSIGNED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETURNED = "RETURNED"
    ESCALATED = "ESCALATED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    REASSIGNED = "REASSIGNED"


class AttemptedAction(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    RETURN = "RETURN"
    ESCALATE = "ESCALATE"


class AttemptOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    BLOCKED = "BLOCKED"


class BlockedReason(StrEnum):
    SELF_APPROVAL = "SELF_APPROVAL"
    UNAUTHORIZED_APPROVER = "UNAUTHORIZED_APPROVER"
    EXPIRED_RULE = "EXPIRED_RULE"
    DUPLICATE_ACTION = "DUPLICATE_ACTION"
    STEP_NOT_PENDING = "STEP_NOT_PENDING"
    LEVEL_SKIPPED = "LEVEL_SKIPPED"


# --- dimension 4: reimbursement (amendment D4) ---------------------------------------------------
class ReimbursementStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EligibilityStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class ReimbursementAction(StrEnum):
    CREATE = "CREATE"
    PROCESS = "PROCESS"
    RETRY = "RETRY"
    CANCEL = "CANCEL"


class ReimbursementAttemptOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    PAYMENT_FAILED = "PAYMENT_FAILED"


class ActorType(StrEnum):
    EMPLOYEE = "EMPLOYEE"
    SYSTEM = "SYSTEM"


# --- dimension 3: technical processing (amendment D3) -------------------------------------------
class ResolutionStatus(StrEnum):
    OPEN = "OPEN"
    RETRIED = "RETRIED"
    RESOLVED = "RESOLVED"
    IGNORED = "IGNORED"


class IdempotencyOperation(StrEnum):
    SUBMIT = "SUBMIT"
    APPROVE = "APPROVE"
    RESUBMIT = "RESUBMIT"
    CREATE_REIMBURSEMENT = "CREATE_REIMBURSEMENT"
    PROCESS_PAYMENT = "PROCESS_PAYMENT"


class IdempotencyStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# --- ground truth (amendment E4) ----------------------------------------------------------------
class ExpectedDetection(StrEnum):
    DETECT = "DETECT"
    NOT_DETECT = "NOT_DETECT"


# --- security (ASM-036) --------------------------------------------------------------------------
class RoleName(StrEnum):
    REQUESTER = "REQUESTER"
    APPROVER = "APPROVER"
    PROCESS_OWNER = "PROCESS_OWNER"
    OPS_ANALYST = "OPS_ANALYST"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"
