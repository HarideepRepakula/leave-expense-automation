"""Session-scoped generated datasets shared by the generator tests (no database needed)."""
from __future__ import annotations

import pytest

from src.data.generate import generate

SEED = 20261022
FULL = {"employees": 400, "leave_requests": 800, "expense_claims": 1000}
STARTER = {"employees": 40, "leave_requests": 80, "expense_claims": 100}   # ASM-028


@pytest.fixture(scope="session")
def full_run():
    return generate(SEED, **FULL)


@pytest.fixture(scope="session")
def starter_run():
    return generate(SEED, **STARTER)


@pytest.fixture(scope="session", params=["full", "starter"])
def run(request, full_run, starter_run):
    """(scale name, volumes, dataset) for both scales: the same code serves both (spec section 6)."""
    if request.param == "full":
        return "full", FULL, full_run[0]
    return "starter", STARTER, starter_run[0]
