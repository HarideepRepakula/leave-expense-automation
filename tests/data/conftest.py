"""Session-scoped generated datasets shared by the generator tests (no database needed).

`run` / `full_run` / `starter_run`: the Phase 3 VALID BASELINE (stages S1-S4 only), so the Phase 3 validity tests
keep testing exactly what they were written for. `gen` / `full_gen` / `starter_gen`: the full Phase 4 pipeline
(S5 anomalies and boundaries, S9 ground truth).
"""
from __future__ import annotations

import pytest

from src.data.generate import build

SEED = 20261022
FULL = {"employees": 400, "leave_requests": 800, "expense_claims": 1000}
STARTER = {"employees": 40, "leave_requests": 80, "expense_claims": 100}   # ASM-028


def _as_tuple(g):
    return g.dataset, g.credentials, g.meta


@pytest.fixture(scope="session")
def full_run():
    return _as_tuple(build(SEED, **FULL, baseline_only=True))


@pytest.fixture(scope="session")
def starter_run():
    return _as_tuple(build(SEED, **STARTER, baseline_only=True))


@pytest.fixture(scope="session", params=["full", "starter"])
def run(request, full_run, starter_run):
    """(scale name, volumes, baseline dataset) for both scales: the same code serves both (spec section 6)."""
    if request.param == "full":
        return "full", FULL, full_run[0]
    return "starter", STARTER, starter_run[0]


@pytest.fixture(scope="session")
def full_gen():
    return build(SEED, **FULL)


@pytest.fixture(scope="session")
def starter_gen():
    return build(SEED, **STARTER)


@pytest.fixture(scope="session", params=["full", "starter"])
def gen(request, full_gen, starter_gen):
    """(scale name, volumes, Generation) after S5 and S9."""
    if request.param == "full":
        return "full", FULL, full_gen
    return "starter", STARTER, starter_gen
