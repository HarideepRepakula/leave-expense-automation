"""Audit events, technical processing failures and idempotency records (spec 15, amendments C, D3, F4)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.common.enums import IdempotencyOperation, IdempotencyStatus, ResolutionStatus
from src.models.base import Base, enum_check, id_check, ops_fk


class AuditEvent(Base):
    """Cross-entity append-only audit. Polymorphic (entity_type, entity_id) by design: it references any
    entity and must survive entity deletion in tests (docs/04). Hash-chain columns are a stretch item
    (DEC-20) and are not present in this version."""

    __tablename__ = "audit_event"

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    previous_state: Mapped[str | None] = mapped_column(Text)
    new_state: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[str | None] = mapped_column(Text)  # employee id, user id or 'SYSTEM'; no FK by design
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rule_id: Mapped[str | None] = mapped_column(Text)
    policy_version_id: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    calculated_values: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        id_check("event_id", "audit_event"),
        Index("ix_audit_event_entity", "entity_type", "entity_id"),
        Index("ix_audit_event_correlation", "correlation_id"),
    )


class ProcessingFailure(Base):
    """Technical failures, separate from business exceptions (amendment D3)."""

    __tablename__ = "processing_failure"

    failure_id: Mapped[str] = mapped_column(Text, primary_key=True)
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(Text)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    resolution_status: Mapped[str] = mapped_column(Text, nullable=False, default=ResolutionStatus.OPEN.value)

    __table_args__ = (
        id_check("failure_id", "processing_failure"),
        enum_check("resolution_status", ResolutionStatus),
    )


class IdempotencyRecord(Base):
    """Prevents repeated submission or processing (AM-C, docs/06 section 8). Scope = (actor, key).

    Never deleted; after insert only status, response_hash, completed_at and the request FKs may change
    (trigger fn_idempotency_update_guard).
    """

    __tablename__ = "idempotency_record"

    actor_user_id: Mapped[str] = mapped_column(
        ForeignKey(ops_fk("application_user", "user_id")), primary_key=True
    )
    idempotency_key: Mapped[str] = mapped_column(Text, primary_key=True)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    leave_request_id: Mapped[str | None] = mapped_column(ForeignKey(ops_fk("leave_request", "leave_request_id")))
    expense_claim_id: Mapped[str | None] = mapped_column(ForeignKey(ops_fk("expense_claim", "expense_claim_id")))
    status: Mapped[str] = mapped_column(Text, nullable=False, default=IdempotencyStatus.IN_PROGRESS.value)
    response_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("idempotency_key ~ '^[0-9a-f]{64}$'", name="key_is_sha256_hex"),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="request_hash_is_sha256_hex"),
        enum_check("operation", IdempotencyOperation),
        enum_check("status", IdempotencyStatus),
        CheckConstraint("num_nonnulls(leave_request_id, expense_claim_id) <= 1", name="at_most_one_request_fk"),
        CheckConstraint("(status = 'COMPLETED') = (completed_at IS NOT NULL)", name="completed_has_timestamp"),
    )
