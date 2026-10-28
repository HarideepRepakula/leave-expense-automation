"""Deterministic sampling helpers. Every draw goes through a numpy Generator from src.common.rng."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import numpy as np


def half_up_int(value: float | Decimal) -> int:
    """Round half-up to an int (Python's round() is banker's rounding, which surprises at .5)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def scaled_count(at_reference: int, n: int, reference: int, minimum: int = 1) -> int:
    """Count that scales with the employee volume (e.g. 10 delegations at 400 -> 1 at 40), never below minimum."""
    return max(minimum, half_up_int(Decimal(at_reference) * n / reference))


def largest_remainder(total: int, shares: dict[str, float], fixed: dict[str, int] | None = None,
                      minimums: dict[str, int] | None = None) -> dict[str, int]:
    """Exact integer quotas summing to `total`.

    `fixed` keys get exactly that count. Remaining keys share the rest by largest remainder; any key whose
    quota falls below its minimum is pinned at the minimum and the rest is recomputed. Ties break on key order.
    """
    fixed = dict(fixed or {})
    minimums = minimums or {}
    while True:
        free = [k for k in shares if k not in fixed]
        remaining = total - sum(fixed.values())
        if remaining < 0:
            raise ValueError("fixed counts exceed total")
        weight = sum(Decimal(str(shares[k])) for k in free)
        exact = {k: Decimal(str(shares[k])) * remaining / weight for k in free}
        quotas = {k: int(exact[k]) for k in free}
        leftover = remaining - sum(quotas.values())
        order = sorted(free, key=lambda k: (-(exact[k] - quotas[k]), list(shares).index(k)))
        for k in order[:leftover]:
            quotas[k] += 1
        below = [k for k in free if quotas[k] < minimums.get(k, 0)]
        if not below:
            return {k: (fixed[k] if k in fixed else quotas[k]) for k in shares}
        for k in below:
            fixed[k] = minimums[k]


def uniform_date(rng: np.random.Generator, lo: date, hi: date) -> date:
    return lo + timedelta(days=int(rng.integers(0, (hi - lo).days + 1)))


def weighted_date(rng: np.random.Generator, lo: date, hi: date, weekend_weight: float) -> date:
    """A date in [lo, hi] with weekdays weighted 1.0 and Saturday/Sunday `weekend_weight` (ASM-022)."""
    days = (hi - lo).days + 1
    weights = np.array(
        [weekend_weight if (lo + timedelta(days=i)).isoweekday() >= 6 else 1.0 for i in range(days)]
    )
    return lo + timedelta(days=int(rng.choice(days, p=weights / weights.sum())))


def timestamp_on(rng: np.random.Generator, d: date, hour_min: int, hour_max: int) -> datetime:
    hour = int(rng.integers(hour_min, hour_max + 1))
    minute = int(rng.integers(0, 60))
    return datetime.combine(d, time(hour, minute), tzinfo=timezone.utc)


def pick(rng: np.random.Generator, items: list):
    return items[int(rng.integers(0, len(items)))]


def weighted_pick(rng: np.random.Generator, weights: dict[str, float]) -> str:
    keys = list(weights)
    p = np.array([weights[k] for k in keys], dtype=float)
    return keys[int(rng.choice(len(keys), p=p / p.sum()))]
