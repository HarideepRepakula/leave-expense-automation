"""Reimbursements and reimbursement attempts."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from src.common.enums import (
    ActorType,
    Currency,
    EligibilityStatus,
    ReimbursementAction,
    ReimbursementAttemptOutcome,
    ReimbursementStatus,
)
from src.models.base import Base, enum_check, id_check, ops_fk


class Reimbursement(Base):
    """At most one active (non-CANCELLED) reimbursement per claim: partial unique index (AM-F5).

    Trigger fn_check_reimbursement_eligibility (sql/triggers.sql) additionally requires the claim to be
    APPROVED and the amount, currency and employee to match the claim.
    """

    __tablename__ = "reimbursement"

    reimbursement_id: Mapped[str] = mapped_column(Text, primary_key=True)
    expense_claim_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("expense_claim", "expense_claim_id")), nullable=False)
    employee_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("employee", "employee_id")), nullable=False)
    approved_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    eligibility_status: Mapped[str] = mapped_column(Text, nullable=False, default=EligibilityStatus.ELIGIBLE.value)
    reimbursement_status: Mapped[str] = mapped_column(Text, nullable=False, default=ReimbursementStatus.ELIGIBLE.value)
    approval_completion_step_id: Mapped[str] = mapped_column(
        ForeignKey(ops_fk("approval_step", "approval_step_id")), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payment_reference: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        id_check("reimbursement_id", "reimbursement"),
        enum_check("currency", Currency),
        enum_check("eligibility_status", EligibilityStatus),
        enum_check("reimbursement_status", ReimbursementStatus),
        CheckConstraint("approved_amount > 0", name="amount_positive"),
        CheckConstraint(
            "(reimbursement_status = 'COMPLETED') = (completed_at IS NOT NULL)", name="completed_has_timestamp"
        ),
        Index(
            "uq_reimbursement_active_per_claim",
            "expense_claim_id",
            unique=True,
            postgresql_where=text("reimbursement_status <> 'CANCELLED'"),
        ),
    )


class ReimbursementAttempt(Base):
    """Payment attempts, failures, retries and blocked duplicates (AM-C, AM-H2). Append-only."""

    __tablename__ = "reimbursement_attempt"

    attempt_id: Mapped[str] = mapped_column(Text, primary_key=True)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_employee_id: Mapped[str | None] = mapped_column(ForeignKey(ops_fk("employee", "employee_id")))
    expense_claim_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("expense_claim", "expense_claim_id")), nullable=False)
    reimbursement_id: Mapped[str | None] = mapped_column(ForeignKey(ops_fk("reimbursement", "reimbursement_id")))
    attempted_action: Mapped[str] = mapped_column(Text, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    __table_args__ = (
        id_check("attempt_id", "reimbursement_attempt"),
        enum_check("actor_type", ActorType),
        enum_check("attempted_action", ReimbursementAction),
        enum_check("outcome", ReimbursementAttemptOutcome),
        CheckConstraint(
            "(actor_type = 'EMPLOYEE') = (actor_employee_id IS NOT NULL)", name="employee_actor_has_id"
        ),
        CheckConstraint("outcome = 'ACCEPTED' OR reason_code IS NOT NULL", name="non_accepted_has_reason"),
    )
