"""Effective-dated policy version resolution (BR-POL-01, BR-POL-02).

Phase 3 brings forward the pure lookup so the generator resolves versions the same way the services will
(DEC-01, RK-01). Phase 6 adds the DB-backed resolver and the POLICY_NOT_APPLICABLE / POLICY_VERSION_EXPIRED
exception handling.
"""
from __future__ import annotations

from datetime import date


class PolicyResolutionError(LookupError):
    pass


def is_effective(row: dict, on: date) -> bool:
    end = row["effective_end"]
    return row["is_active"] and row["effective_start"] <= on and (end is None or on <= end)


def resolve_version(rows: list[dict], family: str, on: date) -> dict:
    """Exactly one active version of `family` must be effective on `on`; zero or several raise."""
    matches = [r for r in rows if r["policy_family"] == family and is_effective(r, on)]
    if len(matches) != 1:
        raise PolicyResolutionError(f"{len(matches)} effective versions of {family} on {on}")
    return matches[0]
