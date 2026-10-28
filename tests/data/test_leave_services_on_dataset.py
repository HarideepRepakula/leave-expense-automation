"""Phase 5 services on the generated dataset, at both scales (no database):
- the services agree with the independent oracle on every leave request; the only differences are the routing
  codes of the Phase 7 engine, and exactly on the planted S19-L records (reported as ROUTING_PHASE7);
- leave detections equal the planted leave labels (expected DETECT), apart from S19-L;
- the replay posts exactly the dataset's legacy USAGE rows (one usage rule, DEC-01);
- the cross-year share meets ASM-042 at full scale (about 3 percent);
- scenarios a scale cannot reach are warned about and recorded in the manifest (Phase 4 cleanup item).
"""
from __future__ import annotations

from pathlib import Path

from src.data.generate import main
from src.evaluation.leave_service_vs_oracle import compare, cross_year

ROOT = Path(__file__).resolve().parents[2]


def _s19_leave(gen) -> set[str]:
    return {r["affected_record_id"] for r in gen.truth.tables["anomaly_label"] if r["scenario_id"] == "S19-L"}


def test_services_agree_with_the_oracle_on_every_leave_request(gen):
    _, vol, g = gen
    comp = compare(g.dataset, ROOT / "config")
    assert len(comp.rows) == vol["leave_requests"]
    assert comp.summary.get("DISAGREE", 0) == 0, comp.disagreements
    routing = {r["record_id"] for r in comp.rows if r["result"] == "ROUTING_PHASE7"}
    assert routing == _s19_leave(g)


def test_leave_detections_equal_the_planted_leave_labels(gen):
    _, _, g = gen
    found = {(d.record_id, d.exception_code) for d in g.detections if d.record_type == "LEAVE"}
    expected = {(r["affected_record_id"], r["issue_type"]) for r in g.truth.tables["anomaly_label"]
                if r["affected_record_type"] == "LEAVE" and r["expected_detection"] == "DETECT"
                and r["scenario_id"] != "S19-L"}
    assert found == expected


def test_replay_posts_exactly_the_legacy_usage_of_the_dataset(gen):
    _, _, g = gen
    comp = compare(g.dataset, ROOT / "config")
    key = ("leave_balance_id", "leave_request_id", "quantity", "txn_date")
    posted = sorted(tuple(t[k] for k in key) for rows in comp.replay.store.ledger.values() for t in rows
                    if t["txn_type"] == "USAGE")
    stored = sorted(tuple(t[k] for k in key) for t in g.dataset["leave_balance_transaction"] if t["txn_type"] == "USAGE")
    assert posted == stored and stored


def test_cross_year_share_meets_asm_042(full_gen):
    c, n, _, _ = cross_year(full_gen.dataset)
    assert 0.025 <= c / n <= 0.035, f"{c} of {n}"


def test_full_scale_reaches_every_scenario(full_gen):
    assert full_gen.meta["scenarios_not_reached"] == []


def test_starter_scale_warns_and_records_scenarios_not_reached(starter_gen, capsys):
    short = starter_gen.meta["scenarios_not_reached"]
    assert short and all(s["actual"] < s["planned"] and s["status"] in ("PARTIAL", "NOT_GENERATED") for s in short)
    assert main(["--employees", "40", "--leave-requests", "80", "--expense-claims", "100", "--no-export"]) == 0
    err = capsys.readouterr().err
    for s in short:
        assert f"WARNING: scenario {s['scenario_id']} " in err and f"{s['actual']} of {s['planned']}" in err
