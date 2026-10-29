"""Plain-language explanation of one request (DEC-29 revised, DEC-P9-01..05; docs/05 section 10).

Display only: it reads a small fact set built from the request's own operational rows and returns text. It never
changes a decision, status, amount, route or stored row, and nothing it returns is stored, exported, checksummed or
audited. The deterministic template is always built first; the Groq rewording is used only when the flag is on, a
key is set, the call succeeds and the output check passes. Every other case returns the template (source
"template"). The key is never logged or returned.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

import httpx

FORBIDDEN_WORDS = ("fraud", "misconduct")
SYSTEM_PROMPT = (
    "You explain the status of an employee's leave request or expense claim in plain, neutral language, in at most "
    "five short sentences. Use only the facts given. Copy every exception code, rule id and amount exactly as "
    "written. Do not guess causes, do not judge the employee, do not give advice beyond the facts.")


@dataclass(frozen=True)
class LlmConfig:
    enabled: bool
    api_key: str
    model: str
    endpoint: str
    timeout_seconds: float
    retries: int
    max_completion_tokens: int
    temperature: float

    @classmethod
    def from_config(cls, llm_cfg: dict, enabled: bool, api_key: str, model: str) -> "LlmConfig":
        return cls(enabled, api_key, model or llm_cfg["default_model"], llm_cfg["endpoint"],
                   float(llm_cfg["timeout_seconds"]), int(llm_cfg["retries_on_transient_error"]),
                   int(llm_cfg["max_completion_tokens"]), float(llm_cfg["temperature"]))


@dataclass(frozen=True)
class Explanation:
    text: str
    source: str                  # "llm" or "template"
    model: str | None
    fallback_reason: str | None  # why the template was returned (None when source is "llm")


class RateLimited(Exception):
    pass


def facts_of(request_type: str, request: dict, steps: list[dict], exceptions: list[dict]) -> dict:
    """The fact set sent to the model (DEC-29 revised): codes, statuses, steps, amount; no names, emails or
    free-text comments. Only the current round's steps and exceptions."""
    rnd = request["current_round"]
    if request_type == "LEAVE":
        rid, raw, unit = request["leave_request_id"], request.get("requested_quantity"), "days"
        amount = None if raw is None else f"{Decimal(raw)}"
    else:
        rid, unit = request["expense_claim_id"], request["currency"]
        raw = request.get("approved_amount") if request.get("approved_amount") is not None \
            else request.get("total_amount")
        amount = None if raw is None else f"{Decimal(raw):.2f}"
    return {
        "request_type": request_type,
        "request_id": rid,
        "status": request["workflow_status"],
        "exception_class": request.get("exception_class"),
        "decision_reason_code": request.get("decision_reason_code"),
        "exception_codes": sorted({e["exception_code"] for e in exceptions if e["submission_round"] == rnd}),
        "steps": [{"level": s["required_level"], "status": s["step_status"], "rule_id": s["approval_rule_id"],
                   "decision_at": s["decision_at"].isoformat() if s.get("decision_at") else None}
                  for s in steps if s["submission_round"] == rnd],
        "amount": amount,
        "unit": unit,
    }


def template_text(f: dict) -> str:
    kind = "Leave request" if f["request_type"] == "LEAVE" else "Expense claim"
    parts = [f"{kind} {f['request_id']} is {f['status']}."]
    if f["amount"] is not None:
        parts.append(f"Amount: {f['amount']} {f['unit']}.")
    if f["exception_codes"]:
        parts.append(f"Exception codes: {', '.join(f['exception_codes'])} (class {f['exception_class']}).")
    else:
        parts.append("No exception codes were raised.")
    if f["decision_reason_code"]:
        parts.append(f"Decision reason: {f['decision_reason_code']}.")
    for s in f["steps"]:
        when = f" on {s['decision_at']}" if s["decision_at"] else ""
        parts.append(f"Approval step {s['level']} under rule {s['rule_id']}: {s['status']}{when}.")
    return " ".join(parts)


def required_tokens(f: dict) -> list[str]:
    """DEC-P9-02: every exception code, rule id and the amount must appear in the model's text."""
    tokens = list(f["exception_codes"]) + sorted({s["rule_id"] for s in f["steps"] if s["rule_id"]})
    if f["amount"] is not None:
        tokens.append(f["amount"])
    return tokens


def output_ok(text: str, f: dict) -> bool:
    lowered = text.lower()
    if not text.strip() or any(re.search(rf"\b{w}", lowered) for w in FORBIDDEN_WORDS):
        return False
    return all(t in text for t in required_tokens(f))


def _call_groq(cfg: LlmConfig, f: dict, template: str, client: httpx.Client) -> str:
    """One call plus cfg.retries retries on a timeout or 5xx; a 429 is never retried (DEC-P9-03)."""
    body = {"model": cfg.model, "temperature": cfg.temperature, "max_completion_tokens": cfg.max_completion_tokens,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": f"Facts: {f}\nTemplate: {template}"}]}
    headers = {"Authorization": f"Bearer {cfg.api_key}"}
    last: Exception = RuntimeError("no response")
    for _ in range(cfg.retries + 1):
        try:
            resp = client.post(cfg.endpoint, json=body, headers=headers, timeout=cfg.timeout_seconds)
        except httpx.TimeoutException as exc:
            last = exc
            continue
        if resp.status_code == 429:
            raise RateLimited()
        if resp.status_code >= 500:
            last = RuntimeError(f"HTTP {resp.status_code}")
            continue
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"] or ""
    raise last


def explain(f: dict, cfg: LlmConfig, client: httpx.Client | None = None) -> Explanation:
    """Template first; the model's rewording only when everything succeeds. Never raises for the caller."""
    template = template_text(f)
    if not cfg.enabled:
        return Explanation(template, "template", None, "disabled")
    if not cfg.api_key:
        return Explanation(template, "template", None, "no_api_key")
    own = client is None
    client = client or httpx.Client()
    try:
        text = _call_groq(cfg, f, template, client).strip()
    except RateLimited:
        return Explanation(template, "template", None, "rate_limited")
    except httpx.TimeoutException:
        return Explanation(template, "template", None, "timeout")
    except Exception:  # noqa: BLE001 - any failure falls back (DEC-P9-03); the error is not shown (may echo data)
        return Explanation(template, "template", None, "call_failed")
    finally:
        if own:
            client.close()
    if not output_ok(text, f):
        return Explanation(template, "template", None, "output_check_failed")
    return Explanation(text, "llm", cfg.model, None)
