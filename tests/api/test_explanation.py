"""Groq explanation layer (DEC-29 revised, DEC-P9-01..05). The HTTP call is always mocked (httpx.MockTransport):
success, fallback on failure / timeout / 429 / failed output check, no key, flag off, and a DB test that decisions
and every stored row are identical with and without the explanation."""
from __future__ import annotations

import httpx
import pytest
import sqlalchemy as sa

from src.services.explanation_service import explain, template_text
from tests.api.conftest import DECIDE, SUBMIT, llm
from tests.db.test_approval_steps_db import _head

FACTS = {"request_type": "EXPENSE", "request_id": "EXP-2026-000912", "status": "RETURNED_FOR_CORRECTION",
         "exception_class": "DATA_QUALITY", "decision_reason_code": "MISSING_RECEIPT",
         "exception_codes": ["MISSING_RECEIPT"], "unit": "INR", "amount": "7000.00",
         "steps": [{"level": "L1", "status": "PENDING", "rule_id": "RULE-E-001", "decision_at": None}]}
GOOD = ("Your expense claim of 7000.00 INR was returned for correction because of MISSING_RECEIPT: please add the "
        "receipt. It was routed under RULE-E-001.")
KEY = "gsk_test_key_never_real"


def transport(*responses):
    """Answers in order; an Exception instance is raised instead. Records the requests."""
    seen: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def ok(text: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": text}}]})


def test_success_uses_the_model_text():
    client, seen = transport(ok(GOOD))
    e = explain(FACTS, llm(True, KEY), client)
    assert (e.source, e.model, e.text, e.fallback_reason) == ("llm", "openai/gpt-oss-20b", GOOD, None)
    assert len(seen) == 1 and seen[0].headers["Authorization"] == f"Bearer {KEY}"
    sent = seen[0].read().decode()
    assert "MISSING_RECEIPT" in sent and "openai/gpt-oss-20b" in sent and "@" not in sent   # facts, no emails


@pytest.mark.parametrize("responses, reason, calls", [
    ((httpx.Response(500), httpx.Response(503)), "call_failed", 2),          # one retry, then template
    ((httpx.Response(401),), "call_failed", 1),
    ((httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow")), "timeout", 2),
    ((httpx.Response(429, headers={"retry-after": "7"}),), "rate_limited", 1),   # never retried
    ((ok("Your claim was returned."),), "output_check_failed", 1),           # code, rule and amount missing
    ((ok(GOOD + " This may be fraud."),), "output_check_failed", 1),         # forbidden word
])
def test_every_failure_falls_back_to_the_template(responses, reason, calls):
    client, seen = transport(*responses)
    e = explain(FACTS, llm(True, KEY), client)
    assert (e.source, e.text, e.model, e.fallback_reason) == ("template", template_text(FACTS), None, reason)
    assert len(seen) == calls and KEY not in e.text


def test_no_key_and_flag_off_never_call_groq():
    for cfg, reason in ((llm(True, ""), "no_api_key"), (llm(False, KEY), "disabled")):
        client, seen = transport()
        e = explain(FACTS, cfg, client)
        assert (e.source, e.fallback_reason, len(seen)) == ("template", reason, 0)
    assert template_text(FACTS).startswith("Expense claim EXP-2026-000912 is RETURNED_FOR_CORRECTION. "
                                           "Amount: 7000.00 INR. Exception codes: MISSING_RECEIPT")


# --- through the API, on lea_test ---------------------------------------------------------------------------------

LEAVE = {"leave_policy_id": "LPOL-UNPAID-ALL-V1", "start_date": "2026-03-09", "end_date": "2026-03-10"}
TABLES = ("leave_request", "approval_step", "approval_event", "approval_attempt", "request_status_event",
          "request_exception", "idempotency_record", "audit_event", "leave_balance_transaction", "processing_failure")


def _snapshot(conn, tables) -> dict:
    out = {}
    for name in TABLES:
        t = tables[f"ops.{name}"]
        pk = list(t.primary_key.columns)
        out[name] = [dict(r) for r in conn.execute(sa.select(t).order_by(*pk)).mappings()]
    return out


def _scenario(client, ctx, requester, manager, explain_calls: bool) -> tuple[list, list]:
    ctx.clock.at = SUBMIT
    sub = client.post("/leave-requests", json=LEAVE, headers=requester).json()
    rid, step = sub["request"]["leave_request_id"], sub["steps"][0]["approval_step_id"]
    explanations = []
    if explain_calls:
        explanations.append(client.get(f"/requests/{rid}/explanation", headers=requester).json())
    ctx.clock.at = DECIDE
    dec = client.post(f"/requests/{rid}/steps/{step}/decision", json={"action": "APPROVE"},
                      headers={**manager, "Idempotency-Key": "same-key-1"}).json()
    if explain_calls:
        explanations.append(client.get(f"/requests/{rid}/explanation", headers=manager).json())
    return [sub["request"]["workflow_status"], dec], explanations


@pytest.mark.db
def test_decisions_and_stored_rows_identical_with_and_without_explanation(client, ctx, conn, users, requester,
                                                                          manager):
    _head(conn, users, "EMP-000001")
    sp = conn.begin_nested()
    plain, _ = _scenario(client, ctx, requester, manager, explain_calls=False)
    rows_plain = _snapshot(conn, users)
    sp.rollback()

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return ok("Leave request LVE-2026-000912 for 2.0 days follows rule RULE-L-004. No exception codes.")
    ctx.llm, ctx.http_client = llm(True, KEY), httpx.Client(transport=httpx.MockTransport(handler))
    sp = conn.begin_nested()
    explained, explanations = _scenario(client, ctx, requester, manager, explain_calls=True)
    rows_explained = _snapshot(conn, users)
    sp.rollback()

    assert plain == explained and plain[1]["workflow_status"] == "APPROVED"
    assert rows_plain == rows_explained                       # nothing stored or audited for an explanation
    assert len(calls) == 2 and [e["explanation"]["source"] for e in explanations] == ["llm", "llm"]
    assert all(KEY not in str(e) for e in explanations)
