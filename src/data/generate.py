"""Synthetic data generator CLI (spec section 6, docs/07).

Full baseline (default volumes from config/generation.yaml):
    python -m src.data.generate --seed 20261022 --employees 400 --leave-requests 800 --expense-claims 1000
Starter dataset (ASM-028, same code, one-tenth scale):
    python -m src.data.generate --seed 20261022 --employees 40 --leave-requests 80 --expense-claims 100 --out data/starter
Add --load to replace the contents of lea_dev (DATABASE_URL in .env) with the generated dataset and its ground
truth.

Stages (docs/07 section 2): S1 master, S2 balances, S3 leave, S4 expenses (valid baseline, Phase 3); S5 anomalies
and boundaries, S9 ground truth from the planted definitions and the independent oracle, then export and
validation (Phase 4). S6-S8 (outcomes, reimbursements, audit) arrive with the Phase 5-8 services.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.common.clock import FrozenClock
from src.common.rng import RngStreams
from src.data.config_loader import load_config
from src.data.dataset import TABLE_ORDER, Dataset, sort_by_pk
from src.data.stages import GenParams
from src.data.stages.anomalies import inject_anomalies
from src.data.stages.balances import build_balances
from src.data.stages.boundaries import inject_boundaries
from src.data.stages.expenses import build_expense_claims
from src.data.stages.ground_truth import GroundTruth, build_ground_truth, write_ground_truth
from src.data.stages.leave import build_leave_requests
from src.data.stages.master import build_master
from src.data.stages.workbench import Workbench
from src.services.calendar_service import HolidayCalendar
from src.services.exception_service import ExceptionCatalogue
from src.services.expense_batch import replay_expense
from src.services.expense_service import DetectionParams
from src.services.leave_batch import replay_leave

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
FIXTURES_DIR = ROOT / "tests" / "fixtures" / "negative"


@dataclass
class Generation:
    dataset: Dataset
    credentials: list[dict]
    meta: dict
    truth: GroundTruth | None
    config_dir: Path
    detections: list = field(default_factory=list)   # service findings (Phases 5-6), see service_detections()


def build(seed: int | None = None, employees: int | None = None, leave_requests: int | None = None,
          expense_claims: int | None = None, config_dir: Path = CONFIG_DIR, baseline_only: bool = False) -> Generation:
    """Run the stages in memory. baseline_only=True stops after S4 (the Phase 3 valid baseline)."""
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
        dataset["leave_balance_transaction"], dataset["leave_balance"])
    dataset.update(build_expense_claims(                                                         # S4
        cfg, p, streams, dataset["employee"], dataset["employee_cost_center_assignment"],
        dataset["expense_policy"], dataset["fx_rate"], dataset["cost_center"], dataset["cost_center_budget"]))
    stages = ["S1 master", "S2 balances (opening + accrual)", "S3 leave", "S4 expenses"]

    truth, detections = None, []
    if not baseline_only:
        wb = Workbench(cfg, p, dataset, calendar)                                                # S5
        inject_anomalies(cfg, p, wb, {"LEAVE": streams.get("anomalies"), "EXPENSE": streams.get("anomalies_expense")})
        inject_boundaries(cfg, p, wb, {"LEAVE": streams.get("boundaries"),
                                       "EXPENSE": streams.get("boundaries_expense")})
        leave_map, claim_map = wb.finalise()
        truth = build_ground_truth(cfg, p, dataset, wb.plants, wb.boundaries, leave_map, claim_map,  # S9
                                   config_dir, FIXTURES_DIR)
        stages += ["S5 anomalies + boundaries (in place)", "S9 ground truth (planted definitions + reference oracle)"]
        detections = service_detections(cfg, dataset, calendar)
        stages.append("leave and expense services replay -> validation/detections.csv (Phases 5-6)")

    missing = [t for t in TABLE_ORDER if t not in dataset]
    if missing:
        raise RuntimeError(f"stages did not produce: {missing}")
    meta = {
        "phase": 3 if baseline_only else 6,
        "stages": stages,
        "seed": p.seed,
        "parameters": {"employees": p.employees, "leave_requests": p.leave_requests,
                       "expense_claims": p.expense_claims},
        "as_of_date": p.as_of.isoformat(),
        "window_start": p.window_start.isoformat(),
    }
    if truth is not None:
        meta["ground_truth_counts"] = {name: len(rows) for name, rows in truth.tables.items()}
        meta["scenarios_not_reached"] = scenario_shortfalls(truth.tables["scenario"])
    return Generation(dataset, credentials, meta, truth, config_dir, detections)


def service_detections(cfg: dict, dataset: Dataset, calendar: HolidayCalendar) -> list:
    """System detections (docs/08: request_exception codes plus batch detectors). Until the Phase 7 engine runs
    S6, the codes come from replaying every submitted request through the leave (Phase 5) and expense (Phase 6)
    services in submission order; the dataset itself is not changed (AMB-P3-01)."""
    catalogue = ExceptionCatalogue.from_config(cfg["exception_codes"])
    leave = replay_leave(dataset["leave_request"], {e["employee_id"]: e for e in dataset["employee"]},
                         {x["leave_policy_id"]: x for x in dataset["leave_policy"]}, calendar,
                         dataset["leave_balance_transaction"], dataset["leave_balance"], catalogue)
    expense = replay_expense(dataset, catalogue, DetectionParams.from_config(cfg["expense_policies"]))
    found = leave.submission_detections() + leave.detections + expense.submission_detections() + expense.detections
    return sorted(found, key=lambda d: (d.record_type, d.record_id, d.exception_code, d.detected_by))


def scenario_shortfalls(scenarios: list[dict]) -> list[dict]:
    """Scenarios this dataset could not place in full (Phase 4 cleanup, owner 2026-10-28): actual < planned.
    Scenarios built by later phases (actual_count NULL) are not shortfalls. Recorded in the manifest."""
    return [{"scenario_id": s["scenario_id"], "planned": s["planned_count"], "actual": s["actual_count"],
             "status": "NOT_GENERATED" if s["actual_count"] == 0 else "PARTIAL"}
            for s in scenarios if s["actual_count"] is not None and s["actual_count"] < s["planned_count"]]


def generate(seed: int | None = None, employees: int | None = None, leave_requests: int | None = None,
             expense_claims: int | None = None, config_dir: Path = CONFIG_DIR) -> tuple[Dataset, list[dict], dict]:
    """Full pipeline; returns (dataset, dev_credentials, manifest metadata) for callers that only need ops data."""
    gen = build(seed, employees, leave_requests, expense_claims, config_dir)
    return gen.dataset, gen.credentials, gen.meta


def write_outputs(gen: Generation, out: Path) -> tuple[dict, list]:
    """Export ops tables, ground truth and the validation report; one manifest checksums all of them."""
    from src.data.export import write_dataset
    from src.validation.report import validate_folder, write_detections, write_report

    results: list = []

    def extra(out_dir: Path) -> list[Path]:
        files = write_ground_truth(gen.truth, out_dir / "ground_truth") if gen.truth is not None else []
        checks, metrics = validate_folder(out_dir / "raw", gen.config_dir)
        results.extend(checks)
        files += write_report(checks, metrics, out_dir / "validation")
        if gen.truth is not None:
            files.append(write_detections(gen.detections, out_dir / "validation"))
        return files

    return write_dataset(gen.dataset, gen.credentials, out, gen.meta, extra_files=extra), results


def _print_summary(gen: Generation, manifest: dict | None, out: Path | None, results: list,
                   load_counts: dict | None, db_name: str | None) -> None:
    dataset = gen.dataset
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
    if gen.truth is not None:
        print("Scenarios (planned / actual records):")
        for s in gen.truth.tables["scenario"]:
            actual = "-" if s["actual_count"] is None else s["actual_count"]
            print(f"  {s['scenario_id']:<8}{s['issue_type']:<36}{s['planned_count']:>5} /{actual!s:>5}")
        labels = gen.truth.tables["anomaly_label"]
        planted = [r for r in labels if r["is_planted"] and r["expected_detection"] == "DETECT"]
        natural = Counter(r["issue_type"] for r in labels if r["scenario_id"] == "NATURAL")
        print(f"Ground truth: {len(gen.truth.tables['record_expectation'])} record expectations, {len(labels)} labels "
              f"({len(planted)} planted positives, {sum(natural.values())} natural positives), "
              f"{len(gen.truth.tables['boundary_case'])} boundary cases")
        print("Natural (unplanted) positives by issue type: "
              + (", ".join(f"{k} {v}" for k, v in sorted(natural.items())) or "none"))
    if results:
        failed = [r for r in results if r.status == "FAIL"]
        print(f"Validation: {len(results)} checks, {len(failed)} failed, "
              f"{sum(r.status == 'NOT_APPLICABLE' for r in results)} not applicable (no rows yet)")
        for r in failed:
            print(f"  FAIL {r.check_id}: {r.violations} findings")
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
                        help="replace the ops and ground_truth data in DATABASE_URL (lea_dev) with this dataset")
    parser.add_argument("--database-url", help="override DATABASE_URL from .env")
    args = parser.parse_args(argv)

    gen = build(args.seed, args.employees, args.leave_requests, args.expense_claims, args.config_dir)
    manifest, results = (None, []) if args.no_export else write_outputs(gen, args.out)
    load_counts = db_name = None
    if args.load:
        from src.common.config import get_settings
        from src.data.loader import check_target, load_dataset
        from src.data.stages.ground_truth import load_ground_truth
        url = args.database_url or get_settings().database_url
        db_name = check_target(url)
        load_counts = load_dataset(gen.dataset, url)
        mismatched = [t for t in TABLE_ORDER if load_counts[t] != len(gen.dataset[t])]
        gt_counts = load_ground_truth(gen.truth, url)
        gt_mismatch = [t for t, n in gt_counts.items() if n != len(gen.truth.tables[t])]
        print(f"ground_truth schema rows in {db_name}: {gt_counts}")
        if mismatched or gt_mismatch:
            print(f"ERROR: database counts differ from generated counts for {mismatched + gt_mismatch}",
                  file=sys.stderr)
            return 1
    print(f"seed={gen.meta['seed']} parameters={gen.meta['parameters']} as_of={gen.meta['as_of_date']}")
    _print_summary(gen, manifest, args.out if manifest else None, results, load_counts, db_name)
    for s in gen.meta.get("scenarios_not_reached", []):
        print(f"WARNING: scenario {s['scenario_id']} {s['status'].replace('_', ' ').lower()}: "
              f"{s['actual']} of {s['planned']} planned records (too few candidates at this scale; "
              f"recorded in manifest.json under scenarios_not_reached)", file=sys.stderr)
    return 1 if any(r.status == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
