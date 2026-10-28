"""Phase 5 check: the leave services against the independent oracle, record by record (DEC-01, RK-15).

The services (src/services, through leave_batch.replay_leave) and the oracle (src/reference) never import each
other; only this evaluation module reads both. For every leave request it compares:
- exception codes: submission codes plus leave batch-detector codes (services) vs the oracle's expected codes;
- the status right after validation: the services' outcome vs the oracle's submission codes mapped by severity
  (HARD -> REJECTED, CORRECTABLE -> RETURNED_FOR_CORRECTION, SOFT -> ESCALATED_FOR_REVIEW, else PENDING_APPROVAL),
  with the severities read straight from config/exception_codes.yaml;
- requested quantity and the per-year split (BR-LBAL-09).

Routing codes (NO_VALID_APPROVAL_PATH, RULE_CONFLICT) come from the Phase 7 engine. They are taken out of both
sides and every record that carries one in the oracle is reported as ROUTING_PHASE7, never counted as agreement.

    python -m src.evaluation.leave_service_vs_oracle [--raw data/raw] [--out data/validation]
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

from src.reference.oracle import Oracle
from src.services.calendar_service import HolidayCalendar
from src.services.exception_service import ExceptionCatalogue
from src.services.leave_batch import LeaveReplay, replay_leave

ROOT = Path(__file__).resolve().parents[2]
ROUTING_CODES = frozenset({"NO_VALID_APPROVAL_PATH", "RULE_CONFLICT"})
STATUS_BY_SEVERITY = {"HARD": "REJECTED", "CORRECTABLE": "RETURNED_FOR_CORRECTION", "SOFT": "ESCALATED_FOR_REVIEW"}
COLUMNS = ["record_id", "employee_id", "kind", "expected_codes", "actual_codes", "expected_status", "actual_status",
           "oracle_final_status", "expected_quantity", "actual_quantity", "expected_parts", "actual_parts", "result"]


@dataclass
class Comparison:
    rows: list[dict]
    replay: LeaveReplay

    @property
    def summary(self) -> Counter:
        return Counter(r["result"] for r in self.rows)

    @property
    def disagreements(self) -> list[dict]:
        return [r for r in self.rows if r["result"] != "AGREE"]


def _parts(parts: dict) -> str:
    return "|".join(f"{y}:{q}" for y, q in sorted(parts.items()))


def compare(tables: dict[str, list[dict]], config_dir: Path) -> Comparison:
    codes_cfg = yaml.safe_load((config_dir / "exception_codes.yaml").read_text(encoding="utf-8"))
    severity = {c["code"]: c["severity"] for c in codes_cfg["codes"]}
    weekend = yaml.safe_load((config_dir / "calendar.yaml").read_text(encoding="utf-8"))["weekend_days"]

    oracle = Oracle(tables, config_dir)
    expected = oracle.leave()
    employees = {e["employee_id"]: e for e in tables["employee"]}
    policies = {p["leave_policy_id"]: p for p in tables["leave_policy"]}
    replay = replay_leave(tables["leave_request"], employees, policies,
                          HolidayCalendar.from_rows(weekend, tables["country_holiday"]),
                          tables["leave_balance_transaction"], tables["leave_balance"],
                          ExceptionCatalogue.from_config(codes_cfg))

    rows = []
    for r in sorted(tables["leave_request"], key=lambda r: r["leave_request_id"]):
        rid, x = r["leave_request_id"], expected[r["leave_request_id"]]
        country = employees[r["employee_id"]]["country"]
        routing = set(x.codes) & ROUTING_CODES
        exp_codes = set(x.codes) - ROUTING_CODES
        act_codes = replay.codes(rid) - ROUTING_CODES
        res = replay.store.results.get(rid)
        if r["workflow_status"] == "DRAFT":
            kind, exp_status, act_status = "DRAFT", "DRAFT", "DRAFT"
        elif rid in replay.legacy:
            kind, exp_status, act_status = "LEGACY", x.final_status, replay.store.requests[rid]["workflow_status"]
        else:
            kind = "SUBMITTED"
            sev = {severity[c] for c in x.submission_codes - ROUTING_CODES}
            exp_status = next((STATUS_BY_SEVERITY[s] for s in ("HARD", "CORRECTABLE", "SOFT") if s in sev),
                              "PENDING_APPROVAL")
            act_status = res.status
        exp_parts = {y: q for y, (_, q) in oracle.parts_by_year(r, country).items()}
        act_parts = res.validation.parts if res else exp_parts
        exp_qty = x.facts["quantity"]
        act_qty = res.validation.quantity if res else exp_qty
        same = (exp_codes == act_codes and exp_status == act_status and exp_qty == act_qty
                and exp_parts == act_parts)
        result = "ROUTING_PHASE7" if routing and same else "AGREE" if same else "DISAGREE"
        rows.append({
            "record_id": rid, "employee_id": r["employee_id"], "kind": kind,
            "expected_codes": "|".join(sorted(exp_codes | routing)), "actual_codes": "|".join(sorted(act_codes)),
            "expected_status": exp_status, "actual_status": act_status, "oracle_final_status": x.final_status,
            "expected_quantity": str(exp_qty), "actual_quantity": str(act_qty),
            "expected_parts": _parts(exp_parts), "actual_parts": _parts(act_parts), "result": result,
        })
    return Comparison(rows, replay)


def cross_year(tables: dict[str, list[dict]]) -> tuple[int, int, int, int]:
    """(cross-year requests, all requests, cross-year submitted, submitted); ASM-042 targets about 3 percent."""
    reqs = tables["leave_request"]
    sub = [r for r in reqs if r["workflow_status"] != "DRAFT"]

    def count(rows: list[dict]) -> int:
        return sum(r["start_date"].year != r["end_date"].year for r in rows)

    return count(reqs), len(reqs), count(sub), len(sub)


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    from src.validation.reader import read_raw

    parser = argparse.ArgumentParser(prog="python -m src.evaluation.leave_service_vs_oracle")
    parser.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "validation")
    parser.add_argument("--config-dir", type=Path, default=ROOT / "config")
    args = parser.parse_args(argv)
    tables = read_raw(args.raw)
    comp = compare(tables, args.config_dir)
    path = args.out / "leave_service_vs_oracle.csv"
    write_csv(comp.rows, path)
    kinds = Counter(r["kind"] for r in comp.rows)
    print(f"Leave requests compared: {len(comp.rows)} ({', '.join(f'{k} {v}' for k, v in sorted(kinds.items()))})")
    for result, n in sorted(comp.summary.items()):
        print(f"  {result:<15}{n:>5}")
    for r in comp.disagreements:
        print(f"  {r['result']} {r['record_id']} {r['kind']}: codes expected [{r['expected_codes']}] actual "
              f"[{r['actual_codes']}]; status after validation expected {r['expected_status']} actual "
              f"{r['actual_status']} (oracle final {r['oracle_final_status']}); quantity {r['expected_quantity']}/{r['actual_quantity']}; parts {r['expected_parts']} / "
              f"{r['actual_parts']}")
    c, n, cs, ns = cross_year(tables)
    print(f"Cross-year leave requests: {c} of {n} = {100 * c / n:.2f} percent "
          f"(submitted: {cs} of {ns} = {100 * cs / ns:.2f} percent); ASM-042 target about 3 percent")
    print(f"Detail: {path}")
    return 1 if comp.summary.get("DISAGREE") else 0


if __name__ == "__main__":
    sys.exit(main())
