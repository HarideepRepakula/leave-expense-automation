"""Declarative bases and constraint helpers shared by all models."""
from __future__ import annotations

from enum import StrEnum

from sqlalchemy import CheckConstraint, MetaData
from sqlalchemy.orm import DeclarativeBase

from src.common.enums import values
from src.common.ids import ID_PATTERNS

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Operational schema."""

    metadata = MetaData(schema="ops", naming_convention=NAMING_CONVENTION)


class GroundTruthBase(DeclarativeBase):
    """Ground-truth schema. No foreign keys to or from ops (amendment E1)."""

    metadata = MetaData(schema="ground_truth", naming_convention=NAMING_CONVENTION)


def enum_check(column: str, enum_cls: type[StrEnum], name: str | None = None) -> CheckConstraint:
    """CHECK (column IN (...)) generated from an enum so DB and Python never drift."""
    quoted = ", ".join(f"'{v}'" for v in values(enum_cls))
    return CheckConstraint(f"{column} IN ({quoted})", name=name or f"{column}_enum")


def id_check(column: str, entity: str) -> CheckConstraint:
    """CHECK (column ~ pattern) using the shared ID pattern table."""
    return CheckConstraint(f"{column} ~ '{ID_PATTERNS[entity]}'", name=f"{column}_format")


def ops_fk(table: str, column: str) -> str:
    return f"ops.{table}.{column}"
