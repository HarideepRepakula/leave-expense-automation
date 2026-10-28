"""DEC-01 / docs/07 section 9.2: the reference oracle shares no code with the engine it checks. No database.

- src/reference imports nothing from src.services, src.data, src.validation, src.api, src.repositories, src.models.
- The services, validation and other operational packages never import src.reference.
- Within the generator only the S9 ground-truth stage imports the oracle; the injector (S5) plants by
  construction and must not ask the oracle what to plant.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def imported_modules(path: Path) -> set[str]:
    mods = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    return mods


def test_reference_imports_no_engine_code():
    forbidden = ("src.services", "src.data", "src.validation", "src.api", "src.repositories", "src.models")
    bad = [(p.name, m) for p in (SRC / "reference").rglob("*.py") for m in imported_modules(p)
           if m.startswith(forbidden)]
    assert not bad, bad


def test_engine_never_imports_reference():
    bad = []
    for folder in ("services", "validation", "api", "repositories", "analytics", "dashboard", "common", "models"):
        for p in (SRC / folder).rglob("*.py"):
            bad += [(str(p.relative_to(ROOT)), m) for m in imported_modules(p) if m.startswith("src.reference")]
    assert not bad, bad


def test_only_ground_truth_stage_uses_the_oracle_in_the_generator():
    users = sorted(p.relative_to(ROOT).as_posix() for p in (SRC / "data").rglob("*.py")
                   if any(m.startswith("src.reference") for m in imported_modules(p)))
    assert users == ["src/data/stages/ground_truth.py"]
