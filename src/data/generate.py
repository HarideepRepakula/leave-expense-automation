"""Synthetic data generator CLI (spec section 6, docs/07).

Full baseline (default volumes from config/generation.yaml):
    python -m src.data.generate --seed 20261022 --employees 400 --leave-requests 800 --expense-claims 1000
Starter dataset (ASM-028, same code, one-tenth scale):
    python -m src.data.generate --seed 20261022 --employees 40 --leave-requests 80 --expense-claims 100 --out data/starter
Add --load to replace the contents of lea_dev (DATABASE_URL in .env) with the generated dataset.

Phase 3 runs stages S1-S4 (master, balances, leave, expenses) and exports. Later phases add S5-S9.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from src.common.clock import FrozenClock
from src.common.rng import RngStreams
from src.data.config_loader import load_config
from src.data.dataset import TABLE_ORDER, Dataset, sort_by_pk
from src.data.stages import GenParams
from src.data.stages.balances import build_balances, ledger_index
from src.data.stages.expenses import build_expense_claims
from src.data.stages.leave import build_leave_requests
from src.data.stages.master import build_master
from src.services.calendar_service import HolidayCalendar

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


def generate(seed: int | None = None, employees: int | None = None, leave_requests: int | None = None,
             expense_claims: int | None = None, config_dir: Path = CONFIG_DIR) -> tuple[Dataset, list[dict], dict]:
    """Run stages S1-S4 in memory. Returns (dataset, dev_credentials, manifest metadata)."""
    cfg = load_config(config_dir)
    g = cfg["generation"]
    vol = g["volumes"]
    clock = FrozenClock(g["as_of_date"])
    p = GenParams(
        seed=g["master_seed"] if seed is None else seed,
        employees=vol["employees"] if employees is None else employees,
        leave_requests=vol["leave_requests"] if leave_requests is None else leave_requests,
        expense_claims=vol["expense_claims"] if expense_claims is None else expense_claims,
        as_of=clock.today(),
        window_start=g["window_start"],
        master_ts=datetime.fromisoformat(g["master_load_timestamp"].replace("Z", "+00:00")),
    )
    if min(p.employees, p.leave_requests, p.expense_claims) < 1:
        raise ValueError("volumes must be positive")
    streams = RngStreams(p.seed, g["streams"])

    dataset, credentials = build_master(cfg, p, streams)                                         # S1
    calendar = HolidayCalendar.from_rows(cfg["calendar"]["weekend_days"], dataset["country_holiday"])
    years = list(range(p.window_start.year, p.as_of.year + 1))
    dataset.update(build_balances(p, streams, dataset["employee"], dataset["leave_policy"], years))  # S2
    dataset["leave_request"] = build_leave_requests(                                             # S3
        cfg, p, streams, dataset["employee"], dataset["leave_policy"], calendar,
        ledger_index(dataset["leave_balance_transaction"]))
    dataset.update(build_expense_claims(                                                         # S4
        cfg, p, streams, dataset["employee"], dataset["employee_cost_center_assignment"],
        dataset["expense_policy"], dataset["fx_rate"]))

    missing = [t for t in TABLE_ORDER if t not in dataset]
    if missing:
        raise RuntimeError(f"stages did not produce: {missing}")
    meta = {
        "phase": 3,
        "stages": ["S1 master", "S2 balances (opening + accrual)", "S3 leave", "S4 expenses"],
        "seed": p.seed,
        "parameters": {"employees": p.employees, "leave_requests": p.leave_requests,
                       "expense_claims": p.expense_claims},
        "as_of_date": p.as_of.isoformat(),
        "window_start": p.window_start.isoformat(),
    }
    return dataset, credentials, meta


def _print_summary(dataset: Dataset, manifest: dict | None, out: Path | None, load_counts: dict | None,
                   db_name: str | None) -> None:
    print("Row counts per table:")
    for name in TABLE_ORDER:
        line = f"  {name:<34}{len(dataset[name]):>7}"
        if load_counts is not None:
            line += f"   in {db_name}: {load_counts[name]:>7}"
        print(line)
    print("ID samples (first / last by primary key):")
    for name, pk in [("employee", "employee_id"), ("leave_request", "leave_request_id"),
                     ("expense_claim", "expense_claim_id"), ("expense_line", "expense_line_id"),
                     ("receipt", "receipt_id"), ("leave_balance_transaction", "transaction_id"),
                     ("leave_balance", "leave_balance_id")]:
        rows = sort_by_pk(name, dataset[name])
        print(f"  {name:<28}{rows[0][pk]}  ...  {rows[-1][pk]}")
    if manifest is not None:
        from src.data.export import dataset_fingerprint
        print(f"Exported {len(manifest['files'])} files to {out}; manifest: {out / 'manifest.json'}")
        print(f"Dataset fingerprint (SHA-256 over all file checksums): {dataset_fingerprint(manifest)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.data.generate",
                                     description="Generate the synthetic leave and expense dataset.")
    parser.add_argument("--seed", type=int, help="master seed (default from config: 20261022)")
    parser.add_argument("--employees", type=int, help="number of employees (default 400)")
    parser.add_argument("--leave-requests", type=int, help="number of leave requests (default 800)")
    parser.add_argument("--expense-claims", type=int, help="number of expense claims (default 1000)")
    parser.add_argument("--out", type=Path, default=ROOT / "data", help="output folder (default: data/)")
    parser.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    parser.add_argument("--no-export", action="store_true", help="skip writing files")
    parser.add_argument("--load", action="store_true",
                        help="replace the ops data in DATABASE_URL (lea_dev) with this dataset")
    parser.add_argument("--database-url", help="override DATABASE_URL from .env")
    args = parser.parse_args(argv)

    dataset, credentials, meta = generate(args.seed, args.employees, args.leave_requests, args.expense_claims,
                                          args.config_dir)
    manifest = None
    if not args.no_export:
        from src.data.export import write_dataset
        manifest = write_dataset(dataset, credentials, args.out, meta)
    load_counts = db_name = None
    if args.load:
        from src.common.config import get_settings
        from src.data.loader import check_target, load_dataset
        url = args.database_url or get_settings().database_url
        db_name = check_target(url)
        load_counts = load_dataset(dataset, url)
        mismatched = [t for t in TABLE_ORDER if load_counts[t] != len(dataset[t])]
        if mismatched:
            print(f"ERROR: database counts differ from generated counts for {mismatched}", file=sys.stderr)
            return 1
    print(f"seed={meta['seed']} parameters={meta['parameters']} as_of={meta['as_of_date']}")
    _print_summary(dataset, manifest, args.out if manifest else None, load_counts, db_name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
