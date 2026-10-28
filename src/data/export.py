"""Deterministic export (docs/07 section 10, amendment A8).

Canonical CSV: UTF-8, LF, header + rows sorted by PK, column order from the model, Decimal with the column's
scale, dates ISO-8601, timestamps ISO-8601 UTC with 'Z', booleans true/false, NULL as empty, JSON columns as
compact JSON. JSON: one array per table, same order and value text, sort_keys, 2-space indent, decimals as
strings (exact), booleans and integers native. manifest.json carries SHA-256 per file; only generated_at is
excluded from reproducibility comparisons (ASM-050).
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import timezone
from decimal import Decimal
from pathlib import Path

import sqlalchemy as sa

from src.common.clock import SystemClock
from src.data.dataset import TABLE_ORDER, Dataset, columns, sort_by_pk

GENERATOR_VERSION = "0.4.0"
EXCLUDED_FROM_CHECKSUM = ("generated_at",)


def canonical_text(col: sa.Column, value) -> str | None:
    """Canonical text of a value, or None for NULL."""
    if value is None:
        return None
    t = col.type
    if isinstance(t, sa.Boolean):
        return "true" if value else "false"
    if isinstance(t, sa.Numeric):
        return str(Decimal(value).quantize(Decimal(1).scaleb(-t.scale)))
    if isinstance(t, sa.DateTime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(t, sa.Date):
        return value.isoformat()
    if isinstance(t, sa.JSON):
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return str(value)


def json_value(col: sa.Column, value):
    if value is None:
        return None
    if isinstance(col.type, sa.Boolean):
        return bool(value)
    if isinstance(col.type, sa.Integer):
        return int(value)
    if isinstance(col.type, sa.JSON):
        return value
    return canonical_text(col, value)


def _sql_literal(col: sa.Column, value) -> str:
    text = canonical_text(col, value)
    if text is None:
        return "NULL"
    t = col.type
    if isinstance(t, sa.Boolean):
        return text.upper()
    if isinstance(t, (sa.Numeric, sa.Integer)):
        return text
    quoted = "'" + text.replace("'", "''") + "'"
    if isinstance(t, sa.JSON):
        return quoted + "::jsonb"
    return quoted


def insert_order(name: str, rows: list[dict]) -> list[dict]:
    """PK order, except employees: managers before reports so the self-FK holds row by row."""
    rows = sort_by_pk(name, rows)
    if name != "employee":
        return rows
    by_id = {r["employee_id"]: r for r in rows}
    depth: dict[str, int] = {}

    def depth_of(emp_id: str) -> int:
        if emp_id not in depth:
            manager = by_id[emp_id]["manager_id"]
            depth[emp_id] = 0 if manager is None else depth_of(manager) + 1
        return depth[emp_id]

    return sorted(rows, key=lambda r: (depth_of(r["employee_id"]), r["employee_id"]))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_dataset(dataset: Dataset, credentials: list[dict], out_dir: Path, meta: dict,
                  extra_files=None) -> dict:
    """Write the ops tables, then the manifest. `extra_files(out_dir) -> list[Path]` may write further files
    (ground truth, validation report) that must also be checksummed in the manifest."""
    written = write_tables(dataset, credentials, out_dir)
    if extra_files is not None:
        written += extra_files(out_dir)
    return write_manifest(out_dir, {**meta, "row_counts": {name: len(dataset[name]) for name in TABLE_ORDER}},
                          written)


def write_tables(dataset: Dataset, credentials: list[dict], out_dir: Path) -> list[Path]:
    raw = out_dir / "raw"
    processed = out_dir / "processed"
    raw.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for name in TABLE_ORDER:
        cols = columns(name)
        rows = sort_by_pk(name, dataset[name])
        csv_path = raw / f"{name}.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow([c.name for c in cols])
            for r in rows:
                w.writerow(["" if (v := canonical_text(c, r[c.name])) is None else v for c in cols])
        json_path = raw / f"{name}.json"
        payload = [{c.name: json_value(c, r[c.name]) for c in cols} for r in rows]
        json_path.write_text(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8", newline="\n")
        written += [csv_path, json_path]

    seed_path = processed / "seed.sql"
    seed_path.write_text(_seed_sql(dataset), encoding="utf-8", newline="\n")
    cred_path = processed / "dev_credentials.csv"
    with cred_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["user_id", "username", "password", "roles"])
        for c in sorted(credentials, key=lambda c: c["user_id"]):
            w.writerow([c["user_id"], c["username"], c["password"], c["roles"]])
    written += [seed_path, cred_path]
    return written


def write_manifest(out_dir: Path, meta: dict, written: list[Path]) -> dict:
    """manifest.json with SHA-256 per file. generated_at is the time the CONTENT was first generated: when an
    existing manifest is identical apart from generated_at, the file is left untouched, so re-running the same
    seed produces no change for git to report (ASM-050 still excludes generated_at from comparisons)."""
    manifest = {
        "generator_version": GENERATOR_VERSION,
        **meta,
        "files": {p.relative_to(out_dir).as_posix(): sha256_file(p) for p in sorted(written)},
    }
    path = out_dir / "manifest.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if {k: v for k, v in old.items() if k not in EXCLUDED_FROM_CHECKSUM} == json.loads(json.dumps(manifest)):
            return old
    manifest["generated_at"] = SystemClock().now().strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest


def _seed_sql(dataset: Dataset) -> str:
    """INSERTs in dependency order; department heads are set after employees exist (circular FK)."""
    out = ["-- Synthetic seed data generated by src.data.generate (illustrative synthetic, Phase 3).",
           "-- Load into an EMPTY ops schema, e.g. psql -d lea_dev -f data/processed/seed.sql", "BEGIN;"]
    for name in TABLE_ORDER:
        cols = [c for c in columns(name) if c.computed is None]
        col_list = ", ".join(c.name for c in cols)
        for r in insert_order(name, dataset[name]):
            values = ", ".join(
                "NULL" if (name == "department" and c.name == "head_employee_id") else _sql_literal(c, r[c.name])
                for c in cols
            )
            out.append(f"INSERT INTO ops.{name} ({col_list}) VALUES ({values});")
    head_col = next(c for c in columns("department") if c.name == "head_employee_id")
    for d in sort_by_pk("department", dataset["department"]):
        out.append(f"UPDATE ops.department SET head_employee_id = {_sql_literal(head_col, d['head_employee_id'])} "
                   f"WHERE department_id = '{d['department_id']}';")
    out.append("COMMIT;")
    return "\n".join(out) + "\n"


def compare_manifests(a: dict, b: dict) -> list[str]:
    """Differences between two manifests, ignoring EXCLUDED_FROM_CHECKSUM. Empty list = reproducible."""
    diffs = []
    for key in sorted(set(a) | set(b)):
        if key in EXCLUDED_FROM_CHECKSUM or a.get(key) == b.get(key):
            continue
        if isinstance(a.get(key), dict) and isinstance(b.get(key), dict):
            for sub in sorted(set(a[key]) | set(b[key])):
                if a[key].get(sub) != b[key].get(sub):
                    diffs.append(f"{key}.{sub}: {a[key].get(sub)} != {b[key].get(sub)}")
        else:
            diffs.append(f"{key}: {a.get(key)} != {b.get(key)}")
    return diffs


def dataset_fingerprint(manifest: dict) -> str:
    """One SHA-256 over all per-file checksums: a single value to compare two runs."""
    joined = "\n".join(f"{k}={v}" for k, v in sorted(manifest["files"].items()))
    return hashlib.sha256(joined.encode()).hexdigest()
