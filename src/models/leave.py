"""Leave: balances (snapshot), requests, and the balance ledger."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.common.enums import ExceptionClass, LeaveTxnType, WorkflowStatus
from src.models.base import Base, enum_check, id_check, ops_fk


class LeaveBalance(Base):
    """Materialised snapshot per (employee, policy, leave year); reconciled against the ledger (AMB-01)."""

    __tablename__ = "leave_balance"

    leave_balance_id: Mapped[str] = mapped_column(Text, primary_key=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("employee", "employee_id")), nullable=False)
    leave_policy_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("leave_policy", "leave_policy_id")), nullable=False)
    leave_year: Mapped[int] = mapped_column(Integer, nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(6, 1), nullable=False)
    accrued: Mapped[Decimal] = mapped_column(Numeric(6, 1), nullable=False, default=Decimal("0"))
    adjustments: Mapped[Decimal] = mapped_column(Numeric(6, 1), nullable=False, default=Decimal("0"))
    used: Mapped[Decimal] = mapped_column(Numeric(6, 1), nullable=False, default=Decimal("0"))
    available_balance: Mapped[Decimal] = mapped_column(
        Numeric(6, 1), Computed("opening_balance + accrued + adjustments - used", persisted=True)
    )
    last_recalculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        id_check("leave_balance_id", "leave_balance"),
        UniqueConstraint("employee_id", "leave_policy_id", "leave_year"),
        CheckConstraint("leave_year BETWEEN 2000 AND 2100", name="leave_year_range"),
        CheckConstraint("used >= 0", name="used_non_negative"),
    )


class LeaveRequest(Base):
    __tablename__ = "leave_request"

    leave_request_id: Mapped[str] = mapped_column(Text, primary_key=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("employee", "employee_id")), nullable=False)
    leave_policy_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("leave_policy", "leave_policy_id")), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_half_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    end_half_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # NULL while DRAFT
    current_round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    business_day_count: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    requested_quantity: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    workflow_status: Mapped[str] = mapped_column(Text, nullable=False)
    exception_class: Mapped[str] = mapped_column(Text, nullable=False, default=ExceptionClass.NONE.value)
    medical_cert_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    decision_reason_code: Mapped[str | None] = mapped_column(Text)
    decision_reason_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        id_check("leave_request_id", "leave_request"),
        enum_check("workflow_status", WorkflowStatus),
        enum_check("exception_class", ExceptionClass),
        CheckConstraint("end_date >= start_date", name="date_order"),
        CheckConstraint("current_round >= 1", name="round_positive"),
        CheckConstraint("business_day_count >= 0 AND requested_quantity >= 0", name="quantities_non_negative"),
        CheckConstraint("business_day_count >= requested_quantity", name="quantity_within_business_days"),
        CheckConstraint(
            "start_date <> end_date OR NOT (start_half_day AND end_half_day)", name="single_day_one_half_flag"
        ),
        CheckConstraint(
            "(workflow_status = 'DRAFT') = (first_submitted_at IS NULL)", name="submitted_at_matches_status"
        ),
    )


class LeaveBalanceTransaction(Base):
    """Append-only ledger (AM-C). USAGE / USAGE_REVERSAL reference the request; others must not."""

    __tablename__ = "leave_balance_transaction"

    transaction_id: Mapped[str] = mapped_column(Text, primary_key=True)
    leave_balance_id: Mapped[str] = mapped_column(
        ForeignKey(ops_fk("leave_balance", "leave_balance_id")), nullable=False
    )
    leave_request_id: Mapped[str | None] = mapped_column(ForeignKey(ops_fk("leave_request", "leave_request_id")))
    txn_type: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(6, 1), nullable=False)  # signed
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    __table_args__ = (
        id_check("transaction_id", "leave_balance_transaction"),
        enum_check("txn_type", LeaveTxnType),
        CheckConstraint(
            "(txn_type IN ('USAGE', 'USAGE_REVERSAL')) = (leave_request_id IS NOT NULL)",
            name="usage_references_request",
        ),
        CheckConstraint("quantity <> 0", name="quantity_non_zero"),
    )
