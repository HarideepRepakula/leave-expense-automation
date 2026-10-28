"""Leave services against the independent oracle, record by record (DEC-01, RK-15; Phase 5, routes from 7A).

The services (src/services, through leave_batch.replay_leave) and the oracle (src/reference) never import each
other; only this evaluation module reads both. For every leave request it compares:
- exception codes: submission codes plus leave batch-detector codes (services) vs the oracle's expected codes;
- the status right after validation: the services' outcome vs the oracle's submission codes mapped by severity
  (HARD -> REJECTED, CORRECTABLE -> RETURNED_FOR_CORRECTION, SOFT -> ESCALATED_FOR_REVIEW, else PENDING_APPROVAL),
  with the severities read straight from config/exception_codes.yaml;
- requested quantity and the per-year split (BR-LBAL-09);
- the approval rule and the route (Phase 7A): level, approver, covered levels and delegated_from of every step;
  when the services end in PENDING_APPROVAL their approval steps must be exactly that route, otherwise no steps;
- the status at the as-of instant (Phase 7B): the services' S6 simulation (decisions with timing) against the
  oracle's independent timing model, and the status written in the dataset against the services' simulation.

Routing codes (NO_VALID_APPROVAL_PATH, RULE_CONFLICT) are compared like every other code since Phase 7A, so the
Phase 5/6 result ROUTING_PHASE7 can no longer occur; it is still printed (always 0) so the report shows it.

    python -m src.evaluation.leave_service_vs_oracle [--raw data/raw] [--out data/validation]
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import json
from datetime import date

import yaml

from src.common.rng import RngStreams
from src.data.config_loader import load_config
from src.data.stages.outcomes import simulate
from src.reference.oracle import Expectation, Oracle
from src.services.approval_routing import ApprovalRouter, Routing
from src.services.calendar_service import HolidayCalendar
from src.services.expense_batch import ExpenseReplay
from src.services.leave_batch import LeaveReplay

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ("AGREE", "ROUTING_PHASE7", "DISAGREE")
STATUS_BY_SEVERITY = {"HARD": "REJECTED", "CORRECTABLE": "RETURNED_FOR_CORRECTION", "SOFT": "ESCALATED_FOR_REVIEW"}
COLUMNS = ["record_id", "employee_id", "kind", "expected_codes", "actual_codes", "expected_status", "actual_status",
           "oracle_final_status", "actual_status_asof", "dataset_status", "expected_quantity", "actual_quantity",
           "expected_parts", "actual_parts", "expected_route", "actual_route", "steps", "result"]


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


def _step(level: str, approver: str, covers, delegated_from: str | None) -> str:
    return f"{level} {approver} [{','.join(covers)}]" + (f" for {delegated_from}" if delegated_from else "")


def expected_route(x: Expectation) -> str:
    """'RULE-E-002: L2 EMP-000010 [L1,L2]; ...' from the oracle; '' when it does not route."""
    rule = x.facts.get("rule_id")
    if rule is None:
        return ""
    return f"{rule}: " + "; ".join(_step(s["level"], s["approver_id"], s["covers"], s["delegated_from"])
                                   for s in x.route or [])


def actual_route(routing: Routing | None) -> str:
    if routing is None or routing.rule_id is None:
        return ""
    return f"{routing.rule_id}: " + "; ".join(_step(s.level, s.approver_id, s.covered_levels, s.delegated_from)
                                              for s in routing.steps)


def steps_match(res, status: str) -> tuple[bool, str]:
    """(ok, count): PENDING_APPROVAL -> one PENDING step per route entry, in order, only the first assigned;
    any other outcome -> no steps."""
    steps = res.steps if res else []
    if status != "PENDING_APPROVAL":
        return not steps, str(len(steps))
    route = res.routing.steps if res.routing else ()
    ok = len(steps) == len(route) > 0 and all(
        (st["sequence_no"], st["required_level"], st["approver_employee_id"], tuple(st["covered_levels"]),
         st["delegated_from_employee_id"], st["approval_rule_id"], st["step_status"], st["assigned_at"] is not None)
        == (i, rs.level, rs.approver_id, rs.covered_levels, rs.delegated_from, res.routing.rule_id, "PENDING", i == 1)
        for i, (st, rs) in enumerate(zip(steps, route), start=1))
    return ok, str(len(steps))


def run_simulation(tables: dict[str, list[dict]], config_dir: Path, seed: int | None = None,
                   as_of: date | None = None) -> tuple[LeaveReplay, ExpenseReplay, int, date]:
    """The services' S6 run (routing, simulated decisions with timing, year-end rows) on the raw-input view of
    `tables`; seed and as-of default to config/generation.yaml (the generator's own values are in the manifest)."""
    cfg = load_config(config_dir)
    seed = cfg["generation"]["master_seed"] if seed is None else seed
    as_of = cfg["generation"]["as_of_date"] if as_of is None else as_of
    streams = RngStreams(seed, cfg["generation"]["streams"])
    calendar = HolidayCalendar.from_rows(cfg["calendar"]["weekend_days"], tables["country_holiday"])
    leave, expense = simulate(cfg, tables, calendar, lambda k, lo, hi: streams.keyed_integers("delays", k, lo, hi),
                              as_of)
    return leave, expense, seed, as_of


def manifest_run(raw: Path) -> tuple[int | None, date | None]:
    """(seed, as-of date) recorded by the generator next to the raw folder, else (None, None)."""
    path = raw.parent / "manifest.json"
    if not path.is_file():
        return None, None
    m = json.loads(path.read_text(encoding="utf-8"))
    return m.get("seed"), date.fromisoformat(m["as_of_date"]) if m.get("as_of_date") else None


def router_from(tables: dict[str, list[dict]]) -> ApprovalRouter:
    return ApprovalRouter.from_rows(tables["approval_rule"], tables["employee"], tables["department"],
                                    tables.get("delegation", []))


def compare(tables: dict[str, list[dict]], config_dir: Path, seed: int | None = None,
            as_of: date | None = None) -> Comparison:
    codes_cfg = yaml.safe_load((config_dir / "exception_codes.yaml").read_text(encoding="utf-8"))
    severity = {c["code"]: c["severity"] for c in codes_cfg["codes"]}

    replay, _, seed, as_of = run_simulation(tables, config_dir, seed, as_of)
    oracle = Oracle(tables, config_dir, seed=seed, as_of=as_of)
    expected = oracle.leave()
    employees = {e["employee_id"]: e for e in tables["employee"]}

    rows = []
    for r in sorted(tables["leave_request"], key=lambda r: r["leave_request_id"]):
        rid, x = r["leave_request_id"], expected[r["leave_request_id"]]
        country = employees[r["employee_id"]]["country"]
        exp_codes, act_codes = set(x.codes), replay.codes(rid)
        res = replay.store.results.get(rid)
        if r["workflow_status"] == "DRAFT":
            kind, exp_status, act_status = "DRAFT", "DRAFT", "DRAFT"
        elif rid in replay.legacy:
            kind, exp_status, act_status = "LEGACY", x.final_status, replay.store.requests[rid]["workflow_status"]
        else:
            kind = "SUBMITTED"
            sev = {severity[c] for c in x.submission_codes}
            exp_status = next((STATUS_BY_SEVERITY[s] for s in ("HARD", "CORRECTABLE", "SOFT") if s in sev),
                              "PENDING_APPROVAL")
            act_status = res.status
        exp_parts = {y: q for y, (_, q) in oracle.parts_by_year(r, country).items()}
        act_parts = res.validation.parts if res else exp_parts
        exp_qty = x.facts["quantity"]
        act_qty = res.validation.quantity if res else exp_qty
        exp_route, act_route = expected_route(x), actual_route(res.routing if res else None)
        steps_ok, steps = steps_match(res, act_status)
        asof = replay.store.requests[rid]["workflow_status"] if rid in replay.store.requests else "DRAFT"
        same = (exp_codes == act_codes and exp_status == act_status and exp_qty == act_qty
                and exp_parts == act_parts and exp_route == act_route and steps_ok
                and x.final_status == asof == r["workflow_status"])
        rows.append({
            "record_id": rid, "employee_id": r["employee_id"], "kind": kind,
            "expected_codes": "|".join(sorted(exp_codes)), "actual_codes": "|".join(sorted(act_codes)),
            "expected_status": exp_status, "actual_status": act_status, "oracle_final_status": x.final_status,
            "actual_status_asof": asof, "dataset_status": r["workflow_status"],
            "expected_quantity": str(exp_qty), "actual_quantity": str(act_qty),
            "expected_parts": _parts(exp_parts), "actual_parts": _parts(act_parts), "expected_route": exp_route,
            "actual_route": act_route, "steps": steps, "result": "AGREE" if same else "DISAGREE",
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


def print_summary(rows: list[dict]) -> None:
    summary = Counter(r["result"] for r in rows)
    for result in RESULTS:
        print(f"  {result:<15}{summary.get(result, 0):>5}")
    print(f"  routed {sum(bool(r['expected_route']) for r in rows)}; approval steps created at submission "
          f"{sum(int(r['steps'] or 0) for r in rows)} on "
          f"{sum(r['actual_status'] == 'PENDING_APPROVAL' for r in rows)} requests routed to PENDING_APPROVAL")
    at = Counter(r["actual_status_asof"] for r in rows)
    print("  status at as-of (services = oracle = dataset on every AGREE row): "
          + ", ".join(f"{k} {v}" for k, v in sorted(at.items())))


def main(argv: list[str] | None = None) -> int:
    from src.validation.reader import read_raw

    parser = argparse.ArgumentParser(prog="python -m src.evaluation.leave_service_vs_oracle")
    parser.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "validation")
    parser.add_argument("--config-dir", type=Path, default=ROOT / "config")
    args = parser.parse_args(argv)
    tables = read_raw(args.raw)
    comp = compare(tables, args.config_dir, *manifest_run(args.raw))
    path = args.out / "leave_service_vs_oracle.csv"
    write_csv(comp.rows, path)
    kinds = Counter(r["kind"] for r in comp.rows)
    print(f"Leave requests compared: {len(comp.rows)} ({', '.join(f'{k} {v}' for k, v in sorted(kinds.items()))})")
    print_summary(comp.rows)
    for r in comp.disagreements:
        print(f"  {r['result']} {r['record_id']} {r['kind']}: codes expected [{r['expected_codes']}] actual "
              f"[{r['actual_codes']}]; status after validation expected {r['expected_status']} actual "
              f"{r['actual_status']}; at as-of oracle {r['oracle_final_status']} services "
              f"{r['actual_status_asof']} dataset {r['dataset_status']}; quantity {r['expected_quantity']}/"
              f"{r['actual_quantity']}; parts {r['expected_parts']} / {r['actual_parts']}; route "
              f"[{r['expected_route']}] / [{r['actual_route']}]; steps {r['steps']}")
    c, n, cs, ns = cross_year(tables)
    print(f"Cross-year leave requests: {c} of {n} = {100 * c / n:.2f} percent "
          f"(submitted: {cs} of {ns} = {100 * cs / ns:.2f} percent); ASM-042 target about 3 percent")
    print(f"Detail: {path}")
    return 1 if comp.summary.get("DISAGREE") else 0


if __name__ == "__main__":
    sys.exit(main())
