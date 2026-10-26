"""Policies and rules: leave policies, expense policies, approval rules, exception code catalogue."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.common.enums import (
    AccrualMethod,
    Country,
    CountryScope,
    Currency,
    DefaultRoute,
    ExceptionClass,
    ExpenseCategory,
    LeaveType,
    RequestType,
    Severity,
)
from src.models.base import Base, enum_check, id_check


class LeavePolicy(Base):
    """One row per policy VERSION (DEC-04). policy_family groups versions; the ID ends in -V<n>."""

    __tablename__ = "leave_policy"

    leave_policy_id: Mapped[str] = mapped_column(Text, primary_key=True)
    policy_family: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_name: Mapped[str] = mapped_column(Text, nullable=False)
    leave_type: Mapped[str] = mapped_column(Text, nullable=False)
    country_scope: Mapped[str] = mapped_column(Text, nullable=False)
    annual_entitlement_days: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    accrual_method: Mapped[str] = mapped_column(Text, nullable=False)
    carry_forward_cap_days: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    negative_balance_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    negative_limit_days: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False, default=Decimal("0"))
    min_service_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requires_medical_cert_over_days: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    max_days_per_year: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    effective_start: Mapped[date] = mapped_column(Date, nullable=False)
    effective_end: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        id_check("leave_policy_id", "leave_policy"),
        enum_check("leave_type", LeaveType),
        enum_check("country_scope", CountryScope),
        enum_check("accrual_method", AccrualMethod),
        UniqueConstraint("policy_family", "version"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("annual_entitlement_days >= 0", name="entitlement_non_negative"),
        CheckConstraint("carry_forward_cap_days >= 0", name="carry_cap_non_negative"),
        CheckConstraint("negative_limit_days >= 0", name="negative_limit_non_negative"),
        CheckConstraint("negative_balance_allowed OR negative_limit_days = 0", name="negative_limit_requires_flag"),
        CheckConstraint("min_service_days >= 0", name="min_service_non_negative"),
        CheckConstraint("effective_end IS NULL OR effective_end >= effective_start", name="effective_dates"),
    )


class ExpensePolicy(Base):
    """One row per (category, country) VERSION. Limits are in the policy's local currency (DEC-05)."""

    __tablename__ = "expense_policy"

    expense_policy_id: Mapped[str] = mapped_column(Text, primary_key=True)
    policy_family: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_name: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    per_line_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    per_claim_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    receipt_threshold: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    requires_pre_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    effective_start: Mapped[date] = mapped_column(Date, nullable=False)
    effective_end: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        id_check("expense_policy_id", "expense_policy"),
        enum_check("country", Country),
        enum_check("category", ExpenseCategory),
        enum_check("currency", Currency),
        UniqueConstraint("policy_family", "version"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("per_line_limit > 0 AND per_claim_limit > 0", name="limits_positive"),
        CheckConstraint("receipt_threshold >= 0", name="receipt_threshold_non_negative"),
        CheckConstraint("effective_end IS NULL OR effective_end >= effective_start", name="effective_dates"),
    )


class ApprovalRule(Base):
    """Configurable, effective-dated routing rules (spec 7.9, AM-B8, AM-B10)."""

    __tablename__ = "approval_rule"

    approval_rule_id: Mapped[str] = mapped_column(Text, primary_key=True)
    request_type: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str | None] = mapped_column(Text)  # NULL = all countries
    category_or_leave_type: Mapped[str | None] = mapped_column(Text)  # NULL = all
    min_amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # exclusive lower bound
    max_amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # inclusive upper bound
    min_days: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))  # exclusive lower bound
    max_days: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))  # inclusive upper bound
    required_levels: Mapped[list] = mapped_column(JSONB, nullable=False)  # e.g. ["L1", "L2"]
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_start: Mapped[date] = mapped_column(Date, nullable=False)
    effective_end: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        id_check("approval_rule_id", "approval_rule"),
        enum_check("request_type", RequestType),
        CheckConstraint("country IS NULL OR country IN ('IN', 'US', 'GB')", name="country_enum"),
        CheckConstraint("priority >= 1", name="priority_positive"),
        CheckConstraint("jsonb_typeof(required_levels) = 'array'", name="levels_is_array"),
        CheckConstraint("jsonb_array_length(required_levels) >= 1", name="levels_not_empty"),
        CheckConstraint(
            "min_amount_usd IS NULL OR max_amount_usd IS NULL OR min_amount_usd < max_amount_usd",
            name="amount_band",
        ),
        CheckConstraint("min_days IS NULL OR max_days IS NULL OR min_days < max_days", name="days_band"),
        CheckConstraint(
            "(request_type = 'EXPENSE' AND min_days IS NULL AND max_days IS NULL) OR "
            "(request_type = 'LEAVE' AND min_amount_usd IS NULL AND max_amount_usd IS NULL)",
            name="band_matches_type",
        ),
        CheckConstraint(
            "(approval_rule_id LIKE 'RULE-L-%' AND request_type = 'LEAVE') OR "
            "(approval_rule_id LIKE 'RULE-E-%' AND request_type = 'EXPENSE')",
            name="id_prefix_matches_type",
        ),
        CheckConstraint("effective_end IS NULL OR effective_end >= effective_start", name="effective_dates"),
    )


class ExceptionCode(Base):
    """Catalogue of exception codes (docs/02 section 5, docs/05 section 9). Wording per AM-H3."""

    __tablename__ = "exception_code"

    exception_code: Mapped[str] = mapped_column(Text, primary_key=True)
    exception_class: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    default_route: Mapped[str] = mapped_column(Text, nullable=False)
    requester_message_template: Mapped[str] = mapped_column(Text, nullable=False)
    analyst_message_template: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        id_check("exception_code", "exception_code"),
        CheckConstraint(
            "exception_class IN ('POLICY_VIOLATION', 'SUSPICIOUS_PATTERN', 'DATA_QUALITY', "
            "'NO_VALID_APPROVAL_PATH', 'RULE_CONFLICT')",
            name="exception_class_enum",
        ),
        enum_check("severity", Severity),
        enum_check("default_route", DefaultRoute),
        CheckConstraint(
            "requester_message_template !~* '(fraud|misconduct)' AND analyst_message_template !~* '(fraud|misconduct)'",
            name="no_accusatory_wording",
        ),
        CheckConstraint(
            "(severity = 'HARD' AND default_route = 'REJECTED') OR "
            "(severity = 'CORRECTABLE' AND default_route = 'RETURNED_FOR_CORRECTION') OR "
            "(severity = 'SOFT' AND default_route = 'ESCALATED_FOR_REVIEW') OR "
            "(severity = 'INFO' AND default_route = 'NONE')",
            name="route_matches_severity",
        ),
    )


# Re-exported for readers of this module; ExceptionClass.NONE is valid on requests, not in the catalogue.
__all__ = ["LeavePolicy", "ExpensePolicy", "ApprovalRule", "ExceptionCode", "ExceptionClass"]
