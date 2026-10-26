"""Simulated authentication (amendment F2): users, roles and the user_role bridge (spec section 9)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, id_check, ops_fk


class Role(Base):
    __tablename__ = "role"

    role_id: Mapped[str] = mapped_column(Text, primary_key=True)
    role_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (id_check("role_id", "role"),)


class ApplicationUser(Base):
    """One login identity. Linked 1:0..1 to an employee; admin users may have no employee (ASM-036)."""

    __tablename__ = "application_user"

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    employee_id: Mapped[str | None] = mapped_column(ForeignKey(ops_fk("employee", "employee_id")), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (id_check("user_id", "application_user"),)


class UserRole(Base):
    """Bridge table for the genuine many-to-many between users and roles."""

    __tablename__ = "user_role"

    user_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("application_user", "user_id")), primary_key=True)
    role_id: Mapped[str] = mapped_column(ForeignKey(ops_fk("role", "role_id")), primary_key=True)
