"""Approval workflow: steps, step events, attempts, request status events, request exceptions.

Request references (DEC-03, revised at Phase 1 review): every table here carries nullable real foreign
keys leave_request_id and expense_claim_id with CHECK num_nonnulls(...) = 1, plus a request_type
discriminator that must match the populated FK. Constraint objects are created per table (a SQLAlchemy
constraint can be attached to only one Table), and functional unique indexes are declared after the
class so they reference real Table columns.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.common.enums import (
    ApprovalEventType,
    ApprovalLevel,
    AttemptedAction,
    AttemptOutcome,
    DetectedBy,
    RequestType,
    StepStatus,
    WorkflowStatus,
    values,
)
from src.models.base import Base, enum_check, id_check, ops_fk


def exactly_one_request_fk() -> CheckConstraint:
    return CheckConstraint("num_nonnulls(leave_request_id, expense_claim_id) = 1", name="exactly_one_request_fk")


def request_type_matches_fk() -> CheckConstraint:
    return CheckConstraint(
        "(request_type = 'LEAVE' AND leave_request_id IS NOT NULL) OR "
        "(request_type = 'EXPENSE' AND expense_claim_id IS NOT NULL)",
        name="request_type_matches_fk",
    )


_LEVEL_LIST = ", ".join(f"'{v}'" for v in values(ApprovalLevel))
COVERED_LEVELS_CHECKS = {
    "covered_levels_is_array": "jsonb_typeof(covered_levels) = 'array' AND jsonb_array_length(covered_levels) >= 1",
    "covered_levels_include_required": "covered_levels @> jsonb_build_array(required_level)",
    "covered_levels_enum": "covered_levels <@ jsonb_build_array(" + _LEVEL_LIST + ")",
}


def covered_levels_checks() -> list[CheckConstraint]:
    """approval_step.covered_levels (migration 0002): a non-empty array of levels that includes required_level."""
    return [CheckConstraint(sql, name=name) for name, sql in COVERED_LEVELS_CHECKS.items()]


def leave_request_fk():
    return mapped_column(ForeignKey(ops_fk("leave_request", "leave_request_id")))


def expense_claim_fk():
    return mapped_column(ForeignKey(ops_fk("expense_claim", "expense_claim_id")))


class ApprovalStep(Base):
    __tablename__ = "approval_step"

    approval_step_id: Mapped[str] = mapped_column(Text, primary_key=True)
    request_type: Mapped[str] = mapped_column(Text, nullable=False)
    leave_request_id: Mapped[str | None] = leave_request_fk()
    expense_claim_id: Mapped[str | None] = expense_claim_fk()
    submission_round: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)  # continues across rounds (AM-A5)
    approval_rule_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("approval_rule", "approval_rule_id")), nullable=False)
    required_level: Mapped[str] = mapped_column(Text, nullable=False)
    # Every level this one step covers, in level order; required_level is the highest (ASM-030, AMB-P3-03).
    # Added by migration 0002 (Phase 7A).
    covered_levels: Mapped[list] = mapped_column(JSONB, nullable=False)
    approver_employee_id: Mapped[str | None] = mapped_column(ForeignKey(ops_fk("employee", "employee_id")))
    delegated_from_employee_id: Mapped[str | None] = mapped_column(ForeignKey(ops_fk("employee", "employee_id")))
    step_status: Mapped[str] = mapped_column(Text, nullable=False, default=StepStatus.PENDING.value)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason_code: Mapped[str | None] = mapped_column(Text)
    decision_comment: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        id_check("approval_step_id", "approval_step"),
        enum_check("request_type", RequestType),
        enum_check("required_level", ApprovalLevel),
        enum_check("step_status", StepStatus),
        exactly_one_request_fk(),
        request_type_matches_fk(),
        CheckConstraint("submission_round >= 1 AND sequence_no >= 1", name="positive_counters"),
        *covered_levels_checks(),
        CheckConstraint(
            "decision_at IS NULL OR (assigned_at IS NOT NULL AND decision_at >= assigned_at)",
            name="decision_after_assignment",
        ),
        CheckConstraint(
            "(step_status IN ('APPROVED', 'REJECTED')) = (decision_at IS NOT NULL)", name="decided_has_timestamp"
        ),
        CheckConstraint(
            "delegated_from_employee_id IS NULL OR delegated_from_employee_id <> approver_employee_id",
            name="delegate_differs",
        ),
        CheckConstraint(
            "approval_step_id = 'APR-' || COALESCE(leave_request_id, expense_claim_id) || '-' || "
            "lpad(sequence_no::text, 2, '0')",
            name="id_matches_request_and_sequence",
        ),
    )


# One sequence number per request across all rounds (AM-A5): functional unique index on the populated FK.
Index(
    "uq_approval_step_request_sequence",
    func.coalesce(ApprovalStep.__table__.c.leave_request_id, ApprovalStep.__table__.c.expense_claim_id),
    ApprovalStep.__table__.c.sequence_no,
    unique=True,
)


class ApprovalEvent(Base):
    """Append-only record of something that happened to a step (AM-H1)."""

    __tablename__ = "approval_event"

    approval_event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    approval_step_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("approval_step", "approval_step_id")), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey(ops_fk("employee", "employee_id")))  # NULL = system
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    __table_args__ = (
        id_check("approval_event_id", "approval_event"),
        enum_check("event_type", ApprovalEventType),
    )


class ApprovalAttempt(Base):
    """Every attempted approve/reject/return, including blocked ones (AM-H2). Append-only."""

    __tablename__ = "approval_attempt"

    attempt_id: Mapped[str] = mapped_column(Text, primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("employee", "employee_id")), nullable=False)
    request_type: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[str] = mapped_column(Text, nullable=False)  # required by AM-H2; equals the populated FK
    leave_request_id: Mapped[str | None] = leave_request_fk()
    expense_claim_id: Mapped[str | None] = expense_claim_fk()
    submission_round: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_step_id: Mapped[str | None] = mapped_column(ForeignKey(ops_fk("approval_step", "approval_step_id")))
    attempted_action: Mapped[str] = mapped_column(Text, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    __table_args__ = (
        id_check("attempt_id", "approval_attempt"),
        enum_check("request_type", RequestType),
        enum_check("attempted_action", AttemptedAction),
        enum_check("outcome", AttemptOutcome),
        exactly_one_request_fk(),
        request_type_matches_fk(),
        CheckConstraint("request_id = COALESCE(leave_request_id, expense_claim_id)", name="request_id_matches_fk"),
        CheckConstraint("(outcome = 'ACCEPTED') = (reason_code IS NULL)", name="blocked_has_reason"),
        CheckConstraint("submission_round >= 1", name="round_positive"),
    )


_STATUS_LIST = ", ".join(f"'{v}'" for v in values(WorkflowStatus))


class RequestStatusEvent(Base):
    """Append-only workflow_status history, including the transient SUBMITTED and VALIDATING states (DEC-08)."""

    __tablename__ = "request_status_event"

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    request_type: Mapped[str] = mapped_column(Text, nullable=False)
    leave_request_id: Mapped[str | None] = leave_request_fk()
    expense_claim_id: Mapped[str | None] = expense_claim_fk()
    submission_round: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_status: Mapped[str | None] = mapped_column(Text)  # NULL for the creating event
    new_status: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey(ops_fk("employee", "employee_id")))  # NULL = system
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    calculated_values: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        id_check("event_id", "request_status_event"),
        enum_check("request_type", RequestType),
        enum_check("new_status", WorkflowStatus),
        CheckConstraint(f"previous_status IS NULL OR previous_status IN ({_STATUS_LIST})", name="previous_status_enum"),
        CheckConstraint("previous_status IS NULL OR previous_status <> new_status", name="status_changed"),
        exactly_one_request_fk(),
        request_type_matches_fk(),
        CheckConstraint("submission_round >= 1", name="round_positive"),
    )


class RequestException(Base):
    """Append-only exception codes per submission round; exception_class on the request is the summary (AM-D2)."""

    __tablename__ = "request_exception"

    exception_id: Mapped[str] = mapped_column(Text, primary_key=True)
    request_type: Mapped[str] = mapped_column(Text, nullable=False)
    leave_request_id: Mapped[str | None] = leave_request_fk()
    expense_claim_id: Mapped[str | None] = expense_claim_fk()
    submission_round: Mapped[int] = mapped_column(Integer, nullable=False)
    exception_code: Mapped[str] = mapped_column(ForeignKey(ops_fk("exception_code", "exception_code")), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detected_by: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    __table_args__ = (
        id_check("exception_id", "request_exception"),
        enum_check("request_type", RequestType),
        enum_check("detected_by", DetectedBy),
        exactly_one_request_fk(),
        request_type_matches_fk(),
        CheckConstraint("submission_round >= 1", name="round_positive"),
    )


# The same code is recorded at most once per request, round and detector.
Index(
    "uq_request_exception_once_per_round",
    func.coalesce(RequestException.__table__.c.leave_request_id, RequestException.__table__.c.expense_claim_id),
    RequestException.__table__.c.submission_round,
    RequestException.__table__.c.exception_code,
    RequestException.__table__.c.detected_by,
    unique=True,
)
