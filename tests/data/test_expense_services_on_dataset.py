"""Phase 6 expense services on the generated dataset, at both scales (no database):
- the services agree with the independent oracle on every claim; the only differences are Phase 7 routing codes,
  exactly on the planted S19-E claims (ROUTING_PHASE7);
- expense detections equal the expense labels expected DETECT (planted and natural), apart from S19-E;
- every line carries quantity x unit amount = line amount (ASM-P6-02, V-ARITH-03).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from src.evaluation.expense_service_vs_oracle import compare

ROOT = Path(__file__).resolve().parents[2]


def test_services_agree_with_the_oracle_on_every_claim(gen):
    _, vol, g = gen
    comp = compare(g.dataset, ROOT / "config")
    assert len(comp.rows) == vol["expense_claims"]
    assert comp.summary.get("DISAGREE", 0) == 0, comp.disagreements
    routing = {r["record_id"] for r in comp.rows if r["result"] == "ROUTING_PHASE7"}
    assert routing == {r["affected_record_id"] for r in g.truth.tables["anomaly_label"] if r["scenario_id"] == "S19-E"}


def test_expense_detections_equal_the_expense_labels(gen):
    _, _, g = gen
    found = {(d.record_id, d.exception_code) for d in g.detections if d.record_type == "EXPENSE"}
    expected = {(r["affected_record_id"], r["issue_type"]) for r in g.truth.tables["anomaly_label"]
                if r["affected_record_type"] == "EXPENSE" and r["expected_detection"] == "DETECT"
                and r["scenario_id"] != "S19-E"}
    assert found == expected


def test_every_line_has_quantity_times_unit_equal_to_the_amount(gen):
    _, _, g = gen
    lines = g.dataset["expense_line"]
    assert all(ln["quantity"] is not None and ln["unit_amount"] is not None for ln in lines)
    assert all((ln["quantity"] * ln["unit_amount"]).quantize(Decimal("0.01"), ROUND_HALF_UP) == ln["line_amount"]
               for ln in lines)
    assert any(ln["quantity"] > 1 for ln in lines)
