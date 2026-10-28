"""Money, quantity and FX helpers (RK-09: Decimal everywhere, half-up rounding)."""
from __future__ import annotations

from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
HALF_DAY = Decimal("0.5")


def money(value: Decimal | int | str) -> Decimal:
    """Round to 2 dp, half-up."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def round_to_unit(value: Decimal, unit: int) -> Decimal:
    """Round half-up to the nearest multiple of `unit` (e.g. 10 INR), returned with 2 dp."""
    step = Decimal(unit)
    return money((value / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step)


def floor_half(value: Decimal) -> Decimal:
    """Round DOWN to a multiple of 0.5 (ASM-007), returned with 1 dp."""
    return ((value / HALF_DAY).to_integral_value(rounding=ROUND_FLOOR) * HALF_DAY).quantize(Decimal("0.1"))


def fx_rate_on(fx_rows: list[dict], from_currency: str, to_currency: str, on: date) -> Decimal:
    """Rate effective on `on`: the latest row with effective_from <= on (ASM-031). Same currency -> 1."""
    if from_currency == to_currency:
        return Decimal("1")
    candidates = [
        r for r in fx_rows
        if r["from_currency"] == from_currency and r["to_currency"] == to_currency and r["effective_from"] <= on
    ]
    if not candidates:
        raise LookupError(f"no fx rate {from_currency}->{to_currency} effective on {on}")
    return max(candidates, key=lambda r: r["effective_from"])["rate"]
