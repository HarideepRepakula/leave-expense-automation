"""In-memory dataset: table name -> list of row dicts keyed by the model's column names.

TABLE_ORDER is the dependency (insert) order of every table the Phase 3 generator produces. Column order and
types always come from the SQLAlchemy models, so exports and loads cannot drift from the schema.
"""
from __future__ import annotations

import sqlalchemy as sa

import src.models  # noqa: F401  (registers every table on Base.metadata)
from src.models.base import Base

Dataset = dict[str, list[dict]]

TABLE_ORDER: list[str] = [
    "department",
    "cost_center",
    "cost_center_budget",
    "employee",
    "employee_cost_center_assignment",
    "country_holiday",
    "fx_rate",
    "delegation",
    "leave_policy",
    "expense_policy",
    "approval_rule",
    "role",
    "application_user",
    "user_role",
    "leave_balance",
    "leave_request",
    "leave_balance_transaction",
    "receipt",
    "expense_claim",
    "expense_line",
]


def table(name: str) -> sa.Table:
    return Base.metadata.tables[f"ops.{name}"]


def columns(name: str) -> list[sa.Column]:
    return list(table(name).columns)


def pk_columns(name: str) -> list[str]:
    return [c.name for c in table(name).primary_key.columns]


def sort_by_pk(name: str, rows: list[dict]) -> list[dict]:
    keys = pk_columns(name)
    return sorted(rows, key=lambda r: tuple(r[k] for k in keys))
