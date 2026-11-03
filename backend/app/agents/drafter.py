"""Drafter worker (Spark): confirmed facts -> SlotDraft (design 3-6)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, ValidationError

from app.agents import deps
from app.agents.base import AgentSchemaError
from app.agents.spark import field_summary, load_prompt, run_spark_json

PROMPT_VERSION = "drafter.v1"
PROMPT_FILE = "drafter.v1.md"
MODEL = "muse-spark-1.3"
MAX_OUTPUT_TOKENS = 6000
REASONING_EFFORT = "medium"

DRAFTER_TEXT_FORMAT: Dict[str, Any] = {
    "type": "json_schema",
    "name": "slot_draft",
    "schema": {
        "type": "object",
        "properties": {
            "sentences": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "sentence_id": {"type": "string"},
                        "type": {"type": "string",
                                 "enum": ["fact", "user"]},
                        "text_with_slots": {"type": "string"},
                        "ex_refs": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["sentence_id", "type", "text_with_slots",
                                 "ex_refs"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["sentences"],
        "additionalProperties": False,
    },
    "strict": True,
}


class ModelDraftSentence(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sentence_id: str
    type: str
    text_with_slots: str
    ex_refs: List[str] = []

    @classmethod
    def _check_type(cls, value: str) -> str:
        if value not in ("fact", "user"):
            raise ValueError(f"type must be fact|user: {value}")
        return value

    def __init__(self, **data: Any) -> None:
        if "type" in data:
            data["type"] = self._check_type(data["type"])
        super().__init__(**data)


class ModelDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sentences: List[ModelDraftSentence]


def build_drafter_payload(
    prompt_text: str,
    draft_inputs: Dict[str, Any],
    findings: Optional[List[Dict[str, Any]]],
) -> Any:
    """Request payload: slots/utterances/evidence (+findings on revision)."""
    text = (f"{prompt_text}\n\nINPUTS:\n"
            f"{json.dumps(draft_inputs, ensure_ascii=False, sort_keys=True)}")
    if findings:
        text += ("\n\n이전 지적(FINDINGS):\n"
                 f"{json.dumps(findings, ensure_ascii=False, sort_keys=True)}\n"
                 "지적을 모두 고쳐 다시 출력하세요.")
    return [{"role": "user", "content": [{"type": "input_text", "text": text}]}]


def _validate(parsed: Any) -> ModelDraft:
    if not isinstance(parsed, dict):
        raise AgentSchemaError("문안 출력이 JSON 객체가 아닙니다.")
    try:
        return ModelDraft.model_validate(parsed)
    except ValidationError as exc:
        raise AgentSchemaError(
            f"문안 출력 형식 오류: {field_summary(exc)}"
        ) from exc


def run_drafter(
    case_id: str,
    draft_inputs: Dict[str, Any],
    findings: Optional[List[Dict[str, Any]]],
    meta_mode: str,
    run_id: str,
) -> Dict[str, Any]:
    """Draft slot sentences. Returns sentences + call accounting."""
    prompt = load_prompt(PROMPT_FILE)
    payload = build_drafter_payload(prompt, draft_inputs, findings)
    total_latency = 0
    total_attempts = 0
    total_in = 0
    total_out = 0
    total_cost = 0.0
    try:
        parsed, info = run_spark_json(
            model=MODEL, payload=payload, text_format=DRAFTER_TEXT_FORMAT,
            reasoning_effort=REASONING_EFFORT, meta_mode=meta_mode,
            run_id=run_id, max_output_tokens=MAX_OUTPUT_TOKENS,
        )
    except deps.IncompleteResponse as exc:
        raise AgentSchemaError("문안 응답이 끊겼습니다(2회 시도).") from exc
    total_latency += info["latency_ms"]
    total_attempts += info["attempts"]
    total_in += info["tokens_in"]
    total_out += info["tokens_out"]
    total_cost += info["cost_usd"]
    try:
        draft = _validate(parsed)
    except AgentSchemaError:
        summary = "sentences"
        if isinstance(parsed, dict):
            try:
                ModelDraft.model_validate(parsed)
            except ValidationError as exc:
                summary = field_summary(exc)
        retry_prompt = (f"{prompt}\n\n이전 출력의 오류: {summary}. "
                        "같은 스키마로 다시 출력하세요.")
        payload = build_drafter_payload(retry_prompt, draft_inputs, findings)
        try:
            parsed, info = run_spark_json(
                model=MODEL, payload=payload, text_format=DRAFTER_TEXT_FORMAT,
                reasoning_effort=REASONING_EFFORT, meta_mode=meta_mode,
                run_id=run_id, max_output_tokens=MAX_OUTPUT_TOKENS,
            )
        except deps.IncompleteResponse as exc:
            raise AgentSchemaError("문안 응답이 끊겼습니다(2회 시도).") from exc
        total_latency += info["latency_ms"]
        total_attempts += info["attempts"]
        total_in += info["tokens_in"]
        total_out += info["tokens_out"]
        total_cost += info["cost_usd"]
        draft = _validate(parsed)
    return {
        "sentences": [entry.model_dump() for entry in draft.sentences],
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "latency_ms": total_latency,
        "attempts": total_attempts,
        "tokens_in": total_in,
        "tokens_out": total_out,
        "cost_usd": round(total_cost, 6),
    }
