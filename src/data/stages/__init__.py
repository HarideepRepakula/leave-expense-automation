"""Generator stages (docs/07 section 2). Phase 3 implements S1-S4; later phases add S5-S9."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class GenParams:
    seed: int
    employees: int
    leave_requests: int
    expense_claims: int
    as_of: date
    window_start: date
    master_ts: datetime
