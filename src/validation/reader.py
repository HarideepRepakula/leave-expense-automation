"""Read exported canonical files (and negative fixtures) back into typed rows (docs/07 section 11).

The column types always come from the SQLAlchemy models, so validation reads exactly what the export wrote:
'' = NULL, true/false, ISO dates, ISO UTC timestamps with Z, decimals as text, JSON columns as compact JSON.
"""
from __future__ import annotations

import csv
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import sqlalchemy as sa

from src.data.dataset import TABLE_ORDER, columns


def parse_value(col: sa.Column, text):
    if text is None or text == "":
        return None
    t = col.type
    if isinstance(t, sa.Boolean):
        return text == "true" if isinstance(text, str) else bool(text)
    if isinstance(t, sa.Integer):
        return int(text)
    if isinstance(t, sa.Numeric):
        return Decimal(str(text))
    if isinstance(t, sa.DateTime):
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    if isinstance(t, sa.Date):
        return date.fromisoformat(str(text))
    if isinstance(t, sa.JSON):
        return json.loads(text) if isinstance(text, str) else text
    if isinstance(t, sa.Uuid):
        return uuid.UUID(str(text))
    return str(text)


def parse_rows(table_name: str, rows: list[dict]) -> list[dict]:
    """Typed rows; columns missing from the input are NULL (fixtures may give only the columns they need)."""
    cols = columns(table_name)
    return [{c.name: parse_value(c, r.get(c.name)) for c in cols} for r in rows]


def read_raw(folder: Path) -> dict[str, list[dict]]:
    """Every ops table exported as <folder>/<table>.csv."""
    out = {}
    for name in TABLE_ORDER:
        with (folder / f"{name}.csv").open(encoding="utf-8", newline="") as fh:
            out[name] = parse_rows(name, list(csv.DictReader(fh)))
    return out


def read_fixture(path: Path) -> tuple[dict, dict[str, list[dict]]]:
    """A negative fixture: (metadata, typed tables)."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc, {name: parse_rows(name, rows) for name, rows in doc["tables"].items()}
