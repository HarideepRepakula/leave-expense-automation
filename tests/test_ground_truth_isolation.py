"""Ground truth isolation (amendments E1/E2, docs/07 section 9.3). No database needed.

Operational code must never import or reference ground truth: no import of the ground-truth models or the S9
stage, and no code string naming the schema or folder. Docstrings and comments may mention it. Allowed: the
evaluation package, the S9 writer, the generator CLI that runs S9, and the model definitions themselves.
"""
from __future__ import annotations

import ast
from pathlib import Path

import src.models  # noqa: F401
from src.models.base import Base

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ALLOWED = {
    SRC / "data" / "stages" / "ground_truth.py",
    SRC / "data" / "generate.py",
    SRC / "models" / "ground_truth.py",
    SRC / "models" / "base.py",
    SRC / "models" / "__init__.py",
}
ALLOWED_DIRS = {SRC / "evaluation"}
FORBIDDEN_COLUMNS = {"is_anomaly", "issue_type", "scenario_id", "is_planted", "anomaly_label", "expected_detection"}


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def offences(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = _docstring_nodes(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "ground_truth" in node.module:
            found.append(f"imports {node.module}")
        elif isinstance(node, ast.Import) and any("ground_truth" in a.name for a in node.names):
            found.append("imports a ground_truth module")
        elif isinstance(node, ast.Name) and node.id == "GroundTruthBase":
            found.append("uses GroundTruthBase")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs \
                and "ground_truth" in node.value:
            found.append(f"string literal {node.value!r}")
    return found


def test_operational_code_never_references_ground_truth():
    bad = []
    for path in sorted(SRC.rglob("*.py")):
        if path in ALLOWED or any(d in path.parents for d in ALLOWED_DIRS):
            continue
        bad += [f"{path.relative_to(ROOT)}: {o}" for o in offences(path)]
    assert not bad, "\n".join(bad)


def test_scanner_catches_a_violation(tmp_path):
    """The scanner itself works: an import of the models and a path literal are reported; a docstring is not."""
    probe = tmp_path / "probe.py"
    probe.write_text('"""Mentions ground_truth in a docstring only."""\n'
                     'from src.models.ground_truth import AnomalyLabel\n'
                     'PATH = "data/ground_truth/anomaly_labels.csv"\n', encoding="utf-8")
    assert len(offences(probe)) == 2


def test_no_label_columns_in_ops_tables():
    cols = {c.name for t in Base.metadata.tables.values() for c in t.columns}
    assert not cols & FORBIDDEN_COLUMNS


def test_no_foreign_keys_leave_the_ops_schema():
    for t in Base.metadata.tables.values():
        assert all(fk.column.table.schema == "ops" for fk in t.foreign_keys), t.name
