"""Master data: departments, cost centers, employees, assignments, holidays, FX rates, delegations."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.common.enums import Country, Currency, EmploymentStatus, Grade
from src.models.base import Base, enum_check, id_check, ops_fk


class Department(Base):
    __tablename__ = "department"

    department_id: Mapped[str] = mapped_column(Text, primary_key=True)
    department_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # Circular reference with employee.department_id; created with ALTER TABLE after both tables exist.
    head_employee_id: Mapped[str | None] = mapped_column(
        ForeignKey(ops_fk("employee", "employee_id"), use_alter=True, name="fk_department_head_employee")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (id_check("department_id", "department"),)


class CostCenter(Base):
    __tablename__ = "cost_center"

    cost_center_id: Mapped[str] = mapped_column(Text, primary_key=True)
    cost_center_name: Mapped[str] = mapped_column(Text, nullable=False)
    department_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("department", "department_id")), nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        id_check("cost_center_id", "cost_center"),
        enum_check("country", Country),
        enum_check("currency", Currency),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="effective_dates"),
    )


class CostCenterBudget(Base):
    """One budget period (calendar year) per cost center (DEC-17, ASM-016)."""

    __tablename__ = "cost_center_budget"

    cost_center_budget_id: Mapped[str] = mapped_column(Text, primary_key=True)
    cost_center_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("cost_center", "cost_center_id")), nullable=False)
    budget_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    budget_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    budget_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    committed_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"))
    actual_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"))

    __table_args__ = (
        id_check("cost_center_budget_id", "cost_center_budget"),
        enum_check("currency", Currency),
        UniqueConstraint("cost_center_id", "budget_period_start"),
        CheckConstraint("budget_period_end >= budget_period_start", name="period_dates"),
        CheckConstraint("budget_amount >= 0", name="budget_non_negative"),
        CheckConstraint("committed_amount >= 0 AND actual_amount >= 0", name="snapshots_non_negative"),
    )


class Employee(Base):
    __tablename__ = "employee"

    employee_id: Mapped[str] = mapped_column(Text, primary_key=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    manager_id: Mapped[str | None] = mapped_column(ForeignKey(ops_fk("employee", "employee_id")))
    department_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("department", "department_id")), nullable=False)
    job_title: Mapped[str] = mapped_column(Text, nullable=False)
    grade: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    employment_start: Mapped[date] = mapped_column(Date, nullable=False)
    employment_end: Mapped[date | None] = mapped_column(Date)
    employment_status: Mapped[str] = mapped_column(Text, nullable=False)
    default_cost_center_id: Mapped[str] = mapped_column(
        ForeignKey(ops_fk("cost_center", "cost_center_id")), nullable=False
    )
    is_department_head: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_finance_controller: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        id_check("employee_id", "employee"),
        enum_check("grade", Grade),
        enum_check("country", Country),
        enum_check("currency", Currency),
        enum_check("employment_status", EmploymentStatus),
        CheckConstraint("manager_id IS NULL OR manager_id <> employee_id", name="not_own_manager"),
        CheckConstraint("employment_end IS NULL OR employment_end >= employment_start", name="employment_dates"),
        CheckConstraint(
            "(employment_status = 'TERMINATED') = (employment_end IS NOT NULL)", name="terminated_has_end_date"
        ),
    )


class EmployeeCostCenterAssignment(Base):
    """Effective-dated cost center membership; claims use the assignment on the expense date (AM-C)."""

    __tablename__ = "employee_cost_center_assignment"

    assignment_id: Mapped[str] = mapped_column(Text, primary_key=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("employee", "employee_id")), nullable=False)
    cost_center_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("cost_center", "cost_center_id")), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        id_check("assignment_id", "employee_cost_center_assignment"),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="effective_dates"),
        UniqueConstraint("employee_id", "effective_from"),
    )


class CountryHoliday(Base):
    __tablename__ = "country_holiday"

    holiday_id: Mapped[str] = mapped_column(Text, primary_key=True)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    holiday_name: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        id_check("holiday_id", "country_holiday"),
        enum_check("country", Country),
        UniqueConstraint("country", "holiday_date"),
    )


class FxRate(Base):
    """Fixed illustrative rates (ASM-003): 1 unit of from_currency = rate units of to_currency."""

    __tablename__ = "fx_rate"

    fx_rate_id: Mapped[str] = mapped_column(Text, primary_key=True)
    from_currency: Mapped[str] = mapped_column(Text, nullable=False)
    to_currency: Mapped[str] = mapped_column(Text, nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)

    __table_args__ = (
        id_check("fx_rate_id", "fx_rate"),
        enum_check("from_currency", Currency),
        enum_check("to_currency", Currency),
        CheckConstraint("rate > 0", name="rate_positive"),
        UniqueConstraint("from_currency", "to_currency", "effective_from"),
    )


class Delegation(Base):
    __tablename__ = "delegation"

    delegation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    approver_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("employee", "employee_id")), nullable=False)
    delegate_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("employee", "employee_id")), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        id_check("delegation_id", "delegation"),
        CheckConstraint("approver_id <> delegate_id", name="distinct_people"),
        CheckConstraint("effective_to >= effective_from", name="effective_dates"),
    )


class IdSequence(Base):
    """Per-scope counters (e.g. 'LVE-2026') locked FOR UPDATE when the services allocate IDs (docs/06 8.1).

    The generator does not use this table (it assigns IDs deterministically after sorting); the API does.
    """

    __tablename__ = "id_sequence"

    sequence_scope: Mapped[str] = mapped_column(Text, primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (CheckConstraint("next_value >= 1", name="positive"),)
