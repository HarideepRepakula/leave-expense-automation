"""Validation framework (docs/07 section 11, docs/08 M1-M3) on the real export and on negative fixtures.
No database needed."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from src.data.dataset import TABLE_ORDER, sort_by_pk
from src.data.generate import build, write_outputs
from src.validation.checks import summary_metrics, validate
from src.validation.reader import read_fixture, read_raw

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "negative"
WEEKEND = {"IN": [6, 7], "US": [6, 7], "GB": [6, 7]}
JSON_FIXTURES = sorted(FIXTURES.glob("*.json"))


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    gen = build(20261022, employees=400, leave_requests=800, expense_claims=1000)
    out = tmp_path_factory.mktemp("export")
    manifest, results = write_outputs(gen, out)
    return gen, out, manifest, results


def test_real_dataset_passes_every_applicable_check(exported):
    _, _, _, results = exported
    # V-WF-05 is reported by the xfail test below (known violation, owner decision AMB-P7B-11 pending).
    assert [r.check_id for r in results if r.status == "FAIL" and r.check_id != "V-WF-05"] == []
    by_id = {r.check_id: r for r in results}
    for check in ("V-PK-01", "V-FK-01", "V-ENUM-01", "V-ID-01", "V-ARITH-01", "V-ARITH-05", "V-ARITH-06",
                  "V-ARITH-08", "V-RULE-01", "V-WF-04"):
        assert by_id[check].subjects > 0, check
    # Checks over workflow rows have nothing to check until Phases 7-8 create those rows.
    assert {r.check_id for r in results if r.status == "NOT_APPLICABLE"} <= {
        "V-ARITH-02", "V-ARITH-03", "V-ARITH-04", "V-ARITH-07", "V-LIFE-01", "V-WF-01", "V-WF-02", "V-WF-03"}


@pytest.mark.xfail(strict=True, reason="AMB-P7B-06: APR-EXP-2025-000483-02 is decided 2025-12-17 by EMP-000190, "
                                       "employed until 2025-12-14; owner decision AMB-P7B-11 pending")
def test_no_decision_after_the_approvers_employment_end(exported):
    _, _, _, results = exported
    v = {r.check_id: r for r in results}["V-WF-05"]
    assert v.subjects > 0 and v.violations == 0


def test_m1_m2_m3_from_actual_results(exported):
    _, out, _, results = exported
    metrics = summary_metrics(results)
    assert metrics["M1"]["numerator"] == 0 and metrics["M1"]["denominator"] > 0
    assert metrics["M2"]["numerator"] == 0 and metrics["M2"]["denominator"] > 0
    assert metrics["M3"]["value"] == 1.0
    on_disk = json.loads((out / "validation" / "validation_report.json").read_text(encoding="utf-8"))
    assert on_disk["metrics"] == json.loads(json.dumps(metrics))


def test_reader_round_trips_the_export(exported):
    gen, out, _, _ = exported
    raw = read_raw(out / "raw")
    for name in TABLE_ORDER:
        assert sort_by_pk(name, raw[name]) == sort_by_pk(name, gen.dataset[name]), name


def test_ground_truth_files_written_and_checksummed(exported):
    _, out, manifest, _ = exported
    names = {"record_expectations.csv", "anomaly_labels.csv", "boundary_cases.csv", "scenarios.json",
             "ground_truth.json"}
    assert {p.name for p in (out / "ground_truth").iterdir()} == names
    assert {f"ground_truth/{n}" for n in names} | {"validation/validation_report.json"} <= set(manifest["files"])
    header = (out / "ground_truth" / "anomaly_labels.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == ("label_id,scenario_id,affected_record_type,affected_record_id,issue_type,label,"
                      "expected_detection,expected_workflow_behaviour,injection_reason,is_planted")


def test_fixture_inventory():
    names = [p.name for p in JSON_FIXTURES]
    assert sum(n.startswith("lifecycle_") for n in names) == 8          # S16
    assert sum(n.startswith("arithmetic_") for n in names) == 8         # S17
    assert sum(n.startswith("structural_") for n in names) == 3         # docs/07 7.3
    assert len(list(FIXTURES.glob("rules_conflict_*.yaml"))) == 2       # S20


@pytest.mark.parametrize("path", JSON_FIXTURES, ids=lambda p: p.stem)
def test_negative_fixture_is_detected(path):
    doc, tables = read_fixture(path)
    results = {r.check_id: r for r in validate(tables, WEEKEND)}
    for check in doc["expected_checks"]:
        assert results[check].status == "FAIL", f"{path.name}: {check} did not fire"


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("rules_conflict_*.yaml")), ids=lambda p: p.stem)
def test_rule_conflict_fixture_is_detected(path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))

    def dec(v):
        return None if v is None else Decimal(str(v))

    rows = [{"approval_rule_id": r["id"], "request_type": r["request_type"], "country": r.get("country"),
             "category_or_leave_type": r.get("category_or_leave_type"), "min_amount_usd": dec(r.get("min_amount_usd")),
             "max_amount_usd": dec(r.get("max_amount_usd")), "min_days": dec(r.get("min_days")),
             "max_days": dec(r.get("max_days")), "required_levels": r["levels"], "priority": r["priority"],
             "effective_start": None, "effective_end": None, "is_active": True} for r in doc["rules"]]
    results = {r.check_id: r for r in validate({"approval_rule": rows}, WEEKEND)}
    assert results["V-RULE-01"].status == "FAIL"
    assert {f.record_id for f in results["V-RULE-01"].findings} == {doc["rules"][-1]["id"]}


def test_fixtures_never_enter_the_dataset(exported):
    _, out, _, _ = exported
    assert "EXP-2026-000999" not in (out / "raw" / "expense_claim.csv").read_text(encoding="utf-8")
    assert "EMP-1," not in (out / "raw" / "employee.csv").read_text(encoding="utf-8")
