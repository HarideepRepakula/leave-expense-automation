"""Idempotency helpers shared by approval_service and reimbursement_service (docs/06 section 8). Moved out of
approval_service in Phase 8 so that both services can use them without importing each other."""
from __future__ import annotations

import hashlib
import json


class IdempotencyConflict(Exception):
    """The idempotency key was already used for a different request body (HTTP 409)."""


class IdempotentReplay(Exception):
    """A resubmission whose key is already recorded: nothing is written (HTTP 200 with the stored response in
    Phase 9). Carries the stored idempotency record."""

    def __init__(self, record: dict) -> None:
        super().__init__(f"idempotency key {record['idempotency_key'][:12]}... already completed")
        self.record = record


def sha256_hex(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def body_hash(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
