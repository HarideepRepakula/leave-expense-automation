"""Single time source (amendment A7, docs/03 section 5).

Rules and generation use FrozenClock(AS_OF_DATE). SystemClock is the ONLY place the wall clock is read; it is
used for request-receipt timestamps in the API (Phase 9) and for manifest.generated_at, which is the one
field excluded from reproducibility checks (ASM-050). tests/test_no_wallclock_usage.py allows this file only.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    def today(self) -> date: ...


class FrozenClock:
    """Always returns the same instant: midnight UTC at the start of the as-of date."""

    def __init__(self, as_of: date) -> None:
        self._now = datetime.combine(as_of, time(0, 0), tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def today(self) -> date:
        return self._now.date()


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def today(self) -> date:
        return self.now().date()
