"""Shared Spark call helper for the three M2a AI workers.

One place for prompt loading, JSON parsing, per-call cost accounting
(usage estimate in every mode; ledger diff mixes parallel calls), and
the uniform IncompleteResponse policy (retry once with 8,000 tokens).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Tuple

from pydantic import ValidationError

from app.agents import deps

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str) -> str:
    """Load ``prompts/<name>`` (e.g. ``reader.v1.md``)."""
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def parse_json_text(text: str) -> Any:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    return json.loads(cleaned)


def field_summary(exc: ValidationError) -> str:
    """Field paths only (no exception text, no values) for schema retries."""
    paths = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", ()))
        paths.append(loc or "output")
    unique = sorted(set(paths))
    return ", ".join(unique[:12])


def run_spark_json(
    *,
    model: str,
    payload: Any,
    text_format: Dict[str, Any],
    reasoning_effort: str,
    meta_mode: str,
    run_id: str,
    max_output_tokens: int = 4000,
) -> Tuple[Any, Dict[str, Any]]:
    """Call Spark and parse the JSON output.

    Returns ``(parsed, info)`` where info holds latency_ms, attempts,
    tokens_in/out, cost_usd, and the final response body. Raises
    IncompleteResponse (after one 8,000-token retry), FixtureNotFound,
    or BudgetError. Costs always come from this call's own response
    usage so parallel calls never mix (C9).
    """
    client = deps.MetaClient(mode=meta_mode, run_id=run_id)
    info: Dict[str, Any] = {
        "latency_ms": 0, "attempts": 0, "tokens_in": 0,
        "tokens_out": 0, "cost_usd": 0.0, "body": None,
    }
    bodies: list = []
    latencies: list = []
    attempts = 0
    body: Any = None
    try:
        started = time.perf_counter()
        try:
            body = client.responses_create(
                model, payload, max_output_tokens=int(max_output_tokens),
                text_format=text_format,
                reasoning={"effort": reasoning_effort},
            )
        except deps.IncompleteResponse as exc:
            truncated = getattr(exc, "body", None)
            if truncated is not None:
                bodies.append(truncated)
            raise
        finally:
            latencies.append(int((time.perf_counter() - started) * 1000))
            attempts += 1
        bodies.append(body)
    except deps.IncompleteResponse:
        started = time.perf_counter()
        try:
            body = client.responses_create(
                model, payload, max_output_tokens=8000,
                text_format=text_format,
                reasoning={"effort": reasoning_effort},
            )
        finally:
            latencies.append(int((time.perf_counter() - started) * 1000))
            attempts += 1
        bodies.append(body)
    finally:
        try:
            client.close()
        except Exception:
            pass
    info["attempts"] = attempts
    assert body is not None
    tokens_in = 0
    tokens_out = 0
    for item in bodies:
        usage = deps.extract_usage(item)
        tokens_in += int(usage.get("input_tokens", 0) or 0)
        tokens_out += int(usage.get("output_tokens", 0) or 0)
    info["latency_ms"] = sum(latencies)
    info["tokens_in"] = tokens_in
    info["tokens_out"] = tokens_out
    info["body"] = body
    info["cost_usd"] = round(
        sum(deps.estimate_cost_from_body(model, "responses", item)
            for item in bodies), 6)
    return parse_json_text(deps.extract_output_text(body)), info
