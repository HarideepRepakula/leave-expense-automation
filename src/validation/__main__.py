"""Validate an exported dataset folder and write the report.

    python -m src.validation                      # data/raw -> data/validation
    python -m src.validation --data data/starter  # <folder>/raw -> <folder>/validation

Exit code 0 when no applicable check fails, 1 otherwise.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.validation.report import validate_folder, write_report

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.validation")
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--config-dir", type=Path, default=ROOT / "config")
    args = parser.parse_args(argv)
    results, metrics = validate_folder(args.data / "raw", args.config_dir)
    write_report(results, metrics, args.data / "validation")
    for r in results:
        print(f"  {r.check_id:<11}{r.status:<15}subjects={r.subjects:<7}violations={r.violations:<4}{r.name}")
    for k, m in metrics.items():
        print(f"  {k} {m['name']}: {m['numerator']}/{m['denominator']} = {m['value']}")
    return 0 if all(r.status != "FAIL" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
