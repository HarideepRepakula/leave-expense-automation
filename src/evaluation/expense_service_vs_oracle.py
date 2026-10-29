"""Expense services against the independent oracle, claim by claim (DEC-01, RK-15; Phase 6, routes from 7A).

Only this evaluation package reads both src/services (through expense_batch.replay_expense) and src/reference. For
every claim it compares: exception codes (submission incl. routing + batch detectors), the status right after
validation and routing (oracle submission codes mapped by severity, as in leave_service_vs_oracle), the USD total,
the primary category, when the oracle expects APPROVED the approved amount (BR-EX-14), and (Phase 7A) the approval
rule, the route and the approval steps (exactly the route when PENDING_APPROVAL, none otherwise), and (Phase 7B) the
status at the as-of instant (services' S6 simulation vs the oracle's timing model vs the dataset) and the approved
amount stored at approval. ROUTING_PHASE7 can no longer occur; it is printed (always 0) so the report shows it.

    python -m src.evaluation.expense_service_vs_oracle [--raw data/raw] [--out data/validation]
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

from datetime import date

from src.evaluation.leave_service_vs_oracle import ROOT, STATUS_BY_SEVERITY, actual_route, expected_route, \
    manifest_run, print_summary, run_simulation, steps_match
from src.reference.oracle import Oracle
from src.services.expense_batch import ExpenseReplay

COLUMNS = ["record_id", "employee_id", "kind", "expected_codes", "actual_codes", "expected_status", "actual_status",
           "oracle_final_status", "actual_status_asof", "dataset_status", "expected_usd", "actual_usd", "expected_approved", "actual_approved",
           "expected_route", "actual_route", "steps", "expected_reimbursement", "actual_reimbursement",
           "dataset_reimbursement", "result"]


def reimbursement_text(rows: list[dict], claim_id: str) -> str:
    """'<status at as-of> <amount> <currency>' of the claim's active reimbursements ('' when none)."""
    return "; ".join(f"{b['reimbursement_status']} {b['approved_amount']} {b['currency']}"
                     for b in sorted(rows, key=lambda b: b["reimbursement_id"])
                     if b["expense_claim_id"] == claim_id and b["reimbursement_status"] != "CANCELLED")


@dataclass
class Comparison:
    rows: list[dict]
    replay: ExpenseReplay

    @property
    def summary(self) -> Counter:
        return Counter(r["result"] for r in self.rows)

    @property
    def disagreements(self) -> list[dict]:
        return [r for r in self.rows if r["result"] != "AGREE"]


def compare(tables: dict[str, list[dict]], config_dir: Path, seed: int | None = None,
            as_of: date | None = None) -> Comparison:
    codes_cfg = yaml.safe_load((config_dir / "exception_codes.yaml").read_text(encoding="utf-8"))
    severity = {c["code"]: c["severity"] for c in codes_cfg["codes"]}
    _, replay, seed, as_of = run_simulation(tables, config_dir, seed, as_of)
    expected = Oracle(tables, config_dir, seed=seed, as_of=as_of).expenses()

    rows = []
    services_rmb, dataset_rmb = list(replay.store.reimbursements.values()), tables.get("reimbursement", [])
    for c in sorted(tables["expense_claim"], key=lambda c: c["expense_claim_id"]):
        cid, x = c["expense_claim_id"], expected[c["expense_claim_id"]]
        # Phase 8B-1: one reimbursement exactly for the claims approved at as-of, its status at as-of and amount.
        exp_rmb = (f"{x.facts['reimbursement_status_at_asof']} {x.approved_amount} {c['currency']}"
                   if x.eligible else "")
        act_rmb, ds_rmb = reimbursement_text(services_rmb, cid), reimbursement_text(dataset_rmb, cid)
        res = replay.store.results.get(cid)
        exp_codes, act_codes = set(x.codes), replay.codes(cid)
        exp_route, act_route = expected_route(x), actual_route(res.routing if res else None)
        sim = replay.store.claims.get(cid)
        asof = sim["workflow_status"] if sim else "DRAFT"
        if res is None:
            kind, exp_status, act_status = "DRAFT", "DRAFT", "DRAFT"
            exp_usd = act_usd = exp_appr = act_appr = ""
            steps_ok, steps = steps_match(res, act_status)
            same = exp_codes == act_codes and exp_route == act_route
        else:
            kind = "SUBMITTED"
            sev = {severity[k] for k in x.submission_codes}
            exp_status = next((STATUS_BY_SEVERITY[s] for s in ("HARD", "CORRECTABLE", "SOFT") if s in sev),
                              "PENDING_APPROVAL")
            act_status, v = res.status, res.validation
            exp_usd, act_usd = str(x.facts["usd"]), str(v.usd)
            exp_appr = "" if x.approved_amount is None else str(x.approved_amount)
            act_appr = "" if sim.get("approved_amount") is None else str(sim["approved_amount"])
            steps_ok, steps = steps_match(res, act_status)
            same = (exp_codes == act_codes and exp_status == act_status and exp_usd == act_usd
                    and x.facts["primary_category"] == v.primary_category and exp_appr == act_appr
                    and exp_route == act_route and steps_ok
                    and x.final_status == asof == c["workflow_status"]
                    and str(c.get("approved_amount") or "") == act_appr)
        rows.append({"record_id": cid, "employee_id": c["employee_id"], "kind": kind,
                     "expected_codes": "|".join(sorted(exp_codes)), "actual_codes": "|".join(sorted(act_codes)),
                     "expected_status": exp_status, "actual_status": act_status, "oracle_final_status": x.final_status,
                     "actual_status_asof": asof, "dataset_status": c["workflow_status"],
                     "expected_usd": exp_usd, "actual_usd": act_usd, "expected_approved": exp_appr,
                     "actual_approved": act_appr, "expected_route": exp_route, "actual_route": act_route,
                     "steps": steps, "expected_reimbursement": exp_rmb, "actual_reimbursement": act_rmb,
                     "dataset_reimbursement": ds_rmb,
                     "result": "AGREE" if same and steps_ok and exp_rmb == act_rmb == ds_rmb else "DISAGREE"})
    return Comparison(rows, replay)


def main(argv: list[str] | None = None) -> int:
    from src.validation.reader import read_raw

    parser = argparse.ArgumentParser(prog="python -m src.evaluation.expense_service_vs_oracle")
    parser.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "validation")
    parser.add_argument("--config-dir", type=Path, default=ROOT / "config")
    args = parser.parse_args(argv)
    comp = compare(read_raw(args.raw), args.config_dir, *manifest_run(args.raw))
    path = args.out / "expense_service_vs_oracle.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(comp.rows)
    kinds = Counter(r["kind"] for r in comp.rows)
    print(f"Expense claims compared: {len(comp.rows)} ({', '.join(f'{k} {v}' for k, v in sorted(kinds.items()))})")
    print_summary(comp.rows)
    for r in comp.disagreements:
        print(f"  {r['result']} {r['record_id']}: codes expected [{r['expected_codes']}] actual [{r['actual_codes']}]; "
              f"status after validation expected {r['expected_status']} actual {r['actual_status']}; at as-of "
              f"oracle {r['oracle_final_status']} services {r['actual_status_asof']} dataset {r['dataset_status']}; usd {r['expected_usd']}/{r['actual_usd']}; approved "
              f"{r['expected_approved'] or '-'}/{r['actual_approved'] or '-'}; route [{r['expected_route']}] / "
              f"[{r['actual_route']}]; steps {r['steps']}")
    print(f"Detail: {path}")
    return 1 if comp.summary.get("DISAGREE") else 0


if __name__ == "__main__":
    sys.exit(main())
