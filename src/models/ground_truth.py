"""Ground-truth schema (spec 12, amendments E1-E4). No foreign keys to or from ops.

record_id values textually match ops IDs; the evaluation joins by value. Only src.evaluation, the
generator's ground-truth stage and the Alembic migration may import this module (tests enforce this
from Phase 4).
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.common.enums import ExpectedDetection, RequestType
from src.models.base import GroundTruthBase, enum_check, id_check


class RecordExpectation(GroundTruthBase):
    __tablename__ = "record_expectation"

    record_type: Mapped[str] = mapped_column(Text, primary_key=True)
    record_id: Mapped[str] = mapped_column(Text, primary_key=True)
    expected_route: Mapped[list | None] = mapped_column(JSONB)  # [{"level": "L1", "approver_id": "EMP-..."}] or null
    expected_final_status_at_asof: Mapped[str] = mapped_column(Text, nullable=False)
    expected_reimbursement_eligibility: Mapped[bool | None] = mapped_column(Boolean)
    expected_exception_codes: Mapped[list] = mapped_column(JSONB, nullable=False)  # [] when clean
    expected_approved_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    __table_args__ = (
        enum_check("record_type", RequestType),
        CheckConstraint("jsonb_typeof(expected_exception_codes) = 'array'", name="codes_is_array"),
        CheckConstraint("expected_route IS NULL OR jsonb_typeof(expected_route) = 'array'", name="route_is_array"),
    )


class AnomalyLabel(GroundTruthBase):
    __tablename__ = "anomaly_label"

    label_id: Mapped[str] = mapped_column(Text, primary_key=True)
    scenario_id: Mapped[str] = mapped_column(Text, nullable=False)
    affected_record_type: Mapped[str] = mapped_column(Text, nullable=False)  # LEAVE, EXPENSE, APPROVAL_ATTEMPT, ...
    affected_record_id: Mapped[str] = mapped_column(Text, nullable=False)
    issue_type: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    expected_detection: Mapped[str] = mapped_column(Text, nullable=False)
    expected_workflow_behaviour: Mapped[str] = mapped_column(Text, nullable=False)
    injection_reason: Mapped[str] = mapped_column(Text, nullable=False)
    is_planted: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        id_check("label_id", "anomaly_label"),
        enum_check("expected_detection", ExpectedDetection),
    )


class BoundaryCase(GroundTruthBase):
    __tablename__ = "boundary_case"

    case_id: Mapped[str] = mapped_column(Text, primary_key=True)
    record_type: Mapped[str] = mapped_column(Text, nullable=False)
    record_id: Mapped[str] = mapped_column(Text, nullable=False)
    boundary_type: Mapped[str] = mapped_column(Text, nullable=False)
    expected_outcome: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        id_check("case_id", "boundary_case"),
        enum_check("record_type", RequestType),
    )


class Scenario(GroundTruthBase):
    __tablename__ = "scenario"

    scenario_id: Mapped[str] = mapped_column(Text, primary_key=True)
    issue_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    planned_count: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_count: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (CheckConstraint("planned_count >= 0", name="planned_non_negative"),)
