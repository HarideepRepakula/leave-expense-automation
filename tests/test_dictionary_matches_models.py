"""R-9.1 / R-P1-11: every table and column in the models is documented in docs/10_data_dictionary.md,
and the dictionary documents no column that the models lack. No database needed (needs SQLAlchemy installed)."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DICT = ROOT / "docs" / "10_data_dictionary.md"


def _dictionary_tables() -> dict[str, set[str]]:
    """Parse '### schema.table' headings and the first column of the following markdown table rows."""
    text = DICT.read_text(encoding="utf-8")
    tables: dict[str, set[str]] = {}
    current = None
    for line in text.splitlines():
        heading = re.match(r"^### (ops|ground_truth)\.([a-z_]+)", line)
        if heading:
            current = f"{heading.group(1)}.{heading.group(2)}"
            tables[current] = set()
            continue
        if current and line.startswith("| ") and not line.startswith("| Field") and not line.startswith("|---"):
            field = line.split("|")[1].strip().strip("`")
            if field and field != "Field":
                tables[current].add(field)
    return tables


def test_dictionary_file_exists():
    assert DICT.is_file()


def test_every_model_table_and_column_is_documented():
    sqlalchemy = pytest.importorskip("sqlalchemy")  # noqa: F841
    from src.models import Base, GroundTruthBase

    documented = _dictionary_tables()
    problems = []
    for md in (Base.metadata, GroundTruthBase.metadata):
        for key, table in md.tables.items():
            if key not in documented:
                problems.append(f"table {key} missing from dictionary")
                continue
            model_cols = {c.name for c in table.columns}
            missing = model_cols - documented[key]
            extra = documented[key] - model_cols
            if missing:
                problems.append(f"{key}: columns missing from dictionary: {sorted(missing)}")
            if extra:
                problems.append(f"{key}: dictionary documents unknown columns: {sorted(extra)}")
    assert not problems, "\n".join(problems)
