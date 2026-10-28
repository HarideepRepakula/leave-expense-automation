"""Acceptance criterion 17 / metric M13: the fixed-seed generator is reproducible (amendment A8).

Generate twice into separate folders, then compare row counts and the SHA-256 of every exported file.
Also checks stream independence (AM-A8, CF-10) and that a different seed really changes the data.
"""
from __future__ import annotations

import json

import pytest

from src.data.export import compare_manifests, dataset_fingerprint, sha256_file, write_dataset
from src.data.generate import generate
from tests.data.conftest import FULL, SEED, STARTER


def _run_to(folder, seed, volumes):
    dataset, creds, meta = generate(seed, **volumes)
    return write_dataset(dataset, creds, folder, meta)


@pytest.mark.parametrize("volumes", [STARTER, FULL], ids=["starter", "full"])
def test_two_runs_identical_counts_and_checksums(tmp_path, volumes):
    a = _run_to(tmp_path / "run_a", SEED, volumes)
    b = _run_to(tmp_path / "run_b", SEED, volumes)
    assert a["row_counts"] == b["row_counts"]
    assert compare_manifests(a, b) == []
    assert dataset_fingerprint(a) == dataset_fingerprint(b)
    # The manifest checksums match the files actually on disk, in both folders.
    for rel, digest in a["files"].items():
        assert sha256_file(tmp_path / "run_a" / rel) == digest == sha256_file(tmp_path / "run_b" / rel)
    on_disk = json.loads((tmp_path / "run_a" / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk["files"] == a["files"]


def test_different_seed_changes_the_data(tmp_path):
    a = _run_to(tmp_path / "a", SEED, STARTER)
    b = _run_to(tmp_path / "b", SEED + 1, STARTER)
    assert a["row_counts"]["employee"] == b["row_counts"]["employee"]
    assert dataset_fingerprint(a) != dataset_fingerprint(b)


def test_csv_is_canonical(tmp_path):
    _run_to(tmp_path, SEED, STARTER)
    raw = (tmp_path / "raw" / "expense_claim.csv").read_bytes()
    assert b"\r\n" not in raw, "LF line endings only"
    header, first = raw.decode("utf-8").splitlines()[:2]
    assert header.startswith("expense_claim_id,employee_id,first_submitted_at,")
    assert first.startswith("EXP-2025-000001,EMP-")


def test_expense_volume_does_not_change_leave_or_master():
    """Changing --expense-claims must not reshuffle other stages (independent streams)."""
    base = generate(SEED, **STARTER)[0]
    other = generate(SEED, **{**STARTER, "expense_claims": 50})[0]
    for t in ("employee", "delegation", "application_user", "leave_balance_transaction", "leave_request"):
        assert base[t] == other[t], t
    assert len(other["expense_claim"]) == 50


def test_leave_volume_does_not_change_expenses():
    base = generate(SEED, **STARTER)[0]
    other = generate(SEED, **{**STARTER, "leave_requests": 40})[0]
    for t in ("employee", "receipt", "expense_claim", "expense_line"):
        assert base[t] == other[t], t
    assert len(other["leave_request"]) == 40
