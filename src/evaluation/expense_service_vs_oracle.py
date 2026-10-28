"""Phase 6 check: the expense services against the independent oracle, claim by claim (DEC-01, RK-15).

Only this evaluation package reads both src/services (through expense_batch.replay_expense) and src/reference. For
every claim it compares: exception codes (submission + batch detectors), the status right after validation
(oracle submission codes mapped by severity, as in leave_service_vs_oracle), the USD total, the primary category
and, when the oracle expects APPROVED, the approved amount (BR-EX-14). Routing codes belong to Phase 7 and every
claim that carries one in the oracle is reported as ROUTING_PHASE7, never as agreement.

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

from src.evaluation.leave_service_vs_oracle import ROOT, ROUTING_CODES, STATUS_BY_SEVERITY
from src.reference.oracle import Oracle
from src.services.exception_service import ExceptionCatalogue
from src.services.expense_batch import ExpenseReplay, replay_expense
from src.services.expense_service import DetectionParams

COLUMNS = ["record_id", "employee_id", "kind", "expected_codes", "actual_codes", "expected_status", "actual_status",
           "oracle_final_status", "expected_usd", "actual_usd", "expected_approved", "actual_approved", "result"]


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


def compare(tables: dict[str, list[dict]], config_dir: Path) -> Comparison:
    codes_cfg = yaml.safe_load((config_dir / "exception_codes.yaml").read_text(encoding="utf-8"))
    severity = {c["code"]: c["severity"] for c in codes_cfg["codes"]}
    params = DetectionParams.from_config(
        yaml.safe_load((config_dir / "expense_policies.yaml").read_text(encoding="utf-8")))
    expected = Oracle(tables, config_dir).expenses()
    replay = replay_expense(tables, ExceptionCatalogue.from_config(codes_cfg), params)

    rows = []
    for c in sorted(tables["expense_claim"], key=lambda c: c["expense_claim_id"]):
        cid, x = c["expense_claim_id"], expected[c["expense_claim_id"]]
        res = replay.store.results.get(cid)
        routing = set(x.codes) & ROUTING_CODES
        exp_codes, act_codes = set(x.codes) - ROUTING_CODES, replay.codes(cid) - ROUTING_CODES
        if res is None:
            kind, exp_status, act_status = "DRAFT", "DRAFT", "DRAFT"
            exp_usd = act_usd = exp_appr = act_appr = ""
            same = exp_codes == act_codes
        else:
            kind = "SUBMITTED"
            sev = {severity[k] for k in x.submission_codes - ROUTING_CODES}
            exp_status = next((STATUS_BY_SEVERITY[s] for s in ("HARD", "CORRECTABLE", "SOFT") if s in sev),
                              "PENDING_APPROVAL")
            act_status, v = res.status, res.validation
            exp_usd, act_usd = str(x.facts["usd"]), str(v.usd)
            exp_appr = "" if x.approved_amount is None else str(x.approved_amount)
            act_appr = str(v.approved_amount) if x.approved_amount is not None else ""
            same = (exp_codes == act_codes and exp_status == act_status and exp_usd == act_usd
                    and x.facts["primary_category"] == v.primary_category and exp_appr == act_appr)
        result = "ROUTING_PHASE7" if routing and same else "AGREE" if same else "DISAGREE"
        rows.append({"record_id": cid, "employee_id": c["employee_id"], "kind": kind,
                     "expected_codes": "|".join(sorted(exp_codes | routing)), "actual_codes": "|".join(sorted(act_codes)),
                     "expected_status": exp_status, "actual_status": act_status, "oracle_final_status": x.final_status,
                     "expected_usd": exp_usd, "actual_usd": act_usd, "expected_approved": exp_appr,
                     "actual_approved": act_appr, "result": result})
    return Comparison(rows, replay)


def main(argv: list[str] | None = None) -> int:
    from src.validation.reader import read_raw

    parser = argparse.ArgumentParser(prog="python -m src.evaluation.expense_service_vs_oracle")
    parser.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "validation")
    parser.add_argument("--config-dir", type=Path, default=ROOT / "config")
    args = parser.parse_args(argv)
    comp = compare(read_raw(args.raw), args.config_dir)
    path = args.out / "expense_service_vs_oracle.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(comp.rows)
    kinds = Counter(r["kind"] for r in comp.rows)
    print(f"Expense claims compared: {len(comp.rows)} ({', '.join(f'{k} {v}' for k, v in sorted(kinds.items()))})")
    for result, n in sorted(comp.summary.items()):
        print(f"  {result:<15}{n:>5}")
    for r in comp.disagreements:
        print(f"  {r['result']} {r['record_id']}: codes expected [{r['expected_codes']}] actual [{r['actual_codes']}]; "
              f"status after validation expected {r['expected_status']} actual {r['actual_status']} (oracle final "
              f"{r['oracle_final_status']}); usd {r['expected_usd']}/{r['actual_usd']}; approved "
              f"{r['expected_approved'] or '-'}/{r['actual_approved'] or '-'}")
    print(f"Detail: {path}")
    return 1 if comp.summary.get("DISAGREE") else 0


if __name__ == "__main__":
    sys.exit(main())
