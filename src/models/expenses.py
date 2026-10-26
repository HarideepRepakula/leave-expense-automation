"""Expenses: receipts, claims, lines, and the cost-center budget ledger."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.common.enums import (
    BudgetTxnType,
    Country,
    Currency,
    ExceptionClass,
    ExpenseCategory,
    LineValidationResult,
    ReceiptStatus,
    WorkflowStatus,
)
from src.models.base import Base, enum_check, id_check, ops_fk


class Receipt(Base):
    """Owns the receipt hash (DEC-10). The hash is indexed but NOT unique: duplicates are an anomaly
    to detect (AM-B14), not a row to prevent."""

    __tablename__ = "receipt"

    receipt_id: Mapped[str] = mapped_column(Text, primary_key=True)
    receipt_hash: Mapped[str] = mapped_column(Text, nullable=False)
    receipt_number: Mapped[str | None] = mapped_column(Text)
    merchant: Mapped[str | None] = mapped_column(Text)
    receipt_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        id_check("receipt_id", "receipt"),
        CheckConstraint("receipt_hash ~ '^[0-9a-f]{64}$'", name="hash_is_sha256_hex"),
        CheckConstraint("currency IS NULL OR currency IN ('INR', 'USD', 'GBP')", name="currency_enum"),
        Index("ix_receipt_hash", "receipt_hash"),
    )


class ExpenseClaim(Base):
    __tablename__ = "expense_claim"

    expense_claim_id: Mapped[str] = mapped_column(Text, primary_key=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("employee", "employee_id")), nullable=False)
    first_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # NULL while DRAFT
    claim_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    claim_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable: NULL only allowed when exception_class <> 'NONE' (amendment A2).
    cost_center_id: Mapped[str | None] = mapped_column(ForeignKey(ops_fk("cost_center", "cost_center_id")))
    expense_policy_id: Mapped[str | None] = mapped_column(ForeignKey(ops_fk("expense_policy", "expense_policy_id")))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    approved_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    total_amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    fx_rate_used: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    workflow_status: Mapped[str] = mapped_column(Text, nullable=False)
    exception_class: Mapped[str] = mapped_column(Text, nullable=False, default=ExceptionClass.NONE.value)
    receipt_status: Mapped[str] = mapped_column(Text, nullable=False, default=ReceiptStatus.NOT_REQUIRED.value)
    current_round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    decision_reason_code: Mapped[str | None] = mapped_column(Text)
    decision_reason_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        id_check("expense_claim_id", "expense_claim"),
        enum_check("country", Country),
        enum_check("currency", Currency),
        enum_check("workflow_status", WorkflowStatus),
        enum_check("exception_class", ExceptionClass),
        enum_check("receipt_status", ReceiptStatus),
        CheckConstraint("cost_center_id IS NOT NULL OR exception_class <> 'NONE'", name="cost_center_or_exception"),
        CheckConstraint("total_amount >= 0", name="total_non_negative"),
        CheckConstraint(
            "approved_amount IS NULL OR (approved_amount >= 0 AND approved_amount <= total_amount)",
            name="approved_within_total",
        ),
        CheckConstraint("approved_amount IS NULL OR workflow_status = 'APPROVED'", name="approved_amount_only_when_approved"),
        CheckConstraint("claim_period_end >= claim_period_start", name="period_dates"),
        CheckConstraint("current_round >= 1", name="round_positive"),
        CheckConstraint(
            "(workflow_status = 'DRAFT') = (first_submitted_at IS NULL)", name="submitted_at_matches_status"
        ),
    )


class ExpenseLine(Base):
    """Lines are versioned by submission_round; the claim total is defined over the current round (DEC-11).

    Currency consistency with the claim is a SERVICE rule (CURRENCY_MISMATCH is a planted anomaly that must
    be able to exist in the dataset, amendment A2), so there is no DB constraint for it.
    """

    __tablename__ = "expense_line"

    expense_line_id: Mapped[str] = mapped_column(Text, primary_key=True)
    expense_claim_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("expense_claim", "expense_claim_id")), nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    submission_round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    merchant_description: Mapped[str] = mapped_column(Text, nullable=False)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    unit_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    line_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    receipt_id: Mapped[str | None] = mapped_column(ForeignKey(ops_fk("receipt", "receipt_id")))
    cost_center_id: Mapped[str | None] = mapped_column(ForeignKey(ops_fk("cost_center", "cost_center_id")))  # override
    expense_policy_id: Mapped[str | None] = mapped_column(ForeignKey(ops_fk("expense_policy", "expense_policy_id")))
    validation_result: Mapped[str] = mapped_column(Text, nullable=False, default=LineValidationResult.PENDING.value)
    validation_detail: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        id_check("expense_line_id", "expense_line"),
        enum_check("category", ExpenseCategory),
        enum_check("currency", Currency),
        enum_check("validation_result", LineValidationResult),
        UniqueConstraint("expense_claim_id", "line_number"),
        CheckConstraint("line_number BETWEEN 1 AND 99", name="line_number_range"),
        CheckConstraint("submission_round >= 1", name="round_positive"),
        CheckConstraint("line_amount > 0", name="amount_positive"),
        CheckConstraint("quantity IS NULL OR quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_amount IS NULL OR unit_amount > 0", name="unit_amount_positive"),
        CheckConstraint("(quantity IS NULL) = (unit_amount IS NULL)", name="quantity_and_unit_together"),
        CheckConstraint(
            "expense_line_id = 'EXPL-' || expense_claim_id || '-' || lpad(line_number::text, 2, '0')",
            name="id_matches_claim_and_line",
        ),
    )


class CostCenterTransaction(Base):
    """Append-only budget ledger: RESERVATION, RELEASE, ACTUAL, OVERRIDE (AM-B11, DEC-06)."""

    __tablename__ = "cost_center_transaction"

    transaction_id: Mapped[str] = mapped_column(Text, primary_key=True)
    cost_center_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("cost_center", "cost_center_id")), nullable=False)
    cost_center_budget_id: Mapped[str] = mapped_column(
        ForeignKey(ops_fk("cost_center_budget", "cost_center_budget_id")), nullable=False
    )
    expense_claim_id: Mapped[str | None] = mapped_column(ForeignKey(ops_fk("expense_claim", "expense_claim_id")))
    txn_type: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    __table_args__ = (
        id_check("transaction_id", "cost_center_transaction"),
        enum_check("txn_type", BudgetTxnType),
        enum_check("currency", Currency),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "txn_type = 'OVERRIDE' OR expense_claim_id IS NOT NULL", name="claim_required_unless_override"
        ),
    )
