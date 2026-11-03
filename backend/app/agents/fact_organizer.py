"""Fact organizer worker (Spark): readings -> Review (contract 5장)."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, ValidationError

from app.agents import deps
from app.agents.base import AgentSchemaError
from app.agents.spark import field_summary, load_prompt, run_spark_json

PROMPT_VERSION = "fact_organizer.v1"
PROMPT_FILE = "fact_organizer.v1.md"
MODEL = "muse-spark-1.3"
MAX_OUTPUT_TOKENS = 8000
REASONING_EFFORT = "low"

FIELD_LABELS: Dict[str, str] = {
    "creditor_name": "채권자 이름",
    "creditor_address": "채권자 주소",
    "creditor_phone": "채권자 연락처",
    "debtor_name": "채무자 이름",
    "debtor_address": "채무자 주소",
    "principal": "원금",
    "loan_date": "대여일",
    "due_date": "변제기",
    "interest_rate": "약정 이율(연 %)",
    "transaction_kind": "거래 종류",
    "repayments": "받은 돈",
}
KNOWN_FIELDS = tuple(FIELD_LABELS)
VALID_TAGS = ("loan_request", "amount_mention", "repay_promise", "reminder", "other")
VALID_ROLES = ("loan_transfer", "repayment", "other")

ORGANIZER_TEXT_FORMAT: Dict[str, Any] = {
    "type": "json_schema",
    "name": "review",
    # strict stays False: field values are polymorphic (string|null|array)
    # which strict schemas cannot express; enums are enforced below.
    "schema": {
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string",
                                  "enum": list(FIELD_LABELS)},
                        "value": {},
                        "sources": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "ex_id": {"type": "string"},
                                    "item_id": {"type": "string"},
                                },
                                "required": ["ex_id", "item_id"],
                                "additionalProperties": False,
                            },
                        },
                        "conflict": {"type": "boolean"},
                        "null_reason": {"type": ["string", "null"]},
                    },
                    "required": ["field", "value", "sources", "conflict",
                                 "null_reason"],
                    "additionalProperties": False,
                },
            },
            "conflicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "fields": {"type": "array", "items": {"type": "string"}},
                        "note": {"type": "string"},
                    },
                    "required": ["fields", "note"],
                    "additionalProperties": False,
                },
            },
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string",
                                  "enum": list(FIELD_LABELS)},
                        "question": {"type": "string"},
                    },
                    "required": ["field", "question"],
                    "additionalProperties": False,
                },
            },
            "utterances": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ex_id": {"type": "string"},
                        "item_id": {"type": "string"},
                        "speaker": {"type": ["string", "null"]},
                        "text": {"type": "string"},
                        "tags": {"type": "array",
                                 "items": {"type": "string",
                                           "enum": list(VALID_TAGS)}},
                    },
                    "required": ["ex_id", "item_id", "speaker", "text", "tags"],
                    "additionalProperties": False,
                },
            },
            "evidence_roles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ex_id": {"type": "string"},
                        "suggested_role": {"type": "string",
                                           "enum": list(VALID_ROLES)},
                    },
                    "required": ["ex_id", "suggested_role"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["fields", "conflicts", "questions", "utterances",
                     "evidence_roles"],
        "additionalProperties": False,
    },
    "strict": False,
}


class ModelSource(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ex_id: str
    item_id: str


class ModelField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field: str
    value: Any = None
    sources: List[ModelSource] = []
    conflict: bool = False
    null_reason: Optional[str] = None


class ModelConflict(BaseModel):
    model_config = ConfigDict(extra="ignore")

    fields: List[str] = []
    note: str = ""


class ModelQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field: str
    question: str


class ModelUtterance(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ex_id: str
    item_id: str
    speaker: Optional[str] = None
    text: str
    tags: List[str] = []

    @classmethod
    def _clean_speaker(cls, value: Any) -> Any:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned.lower() in ("null", "none", ":null", ""):
                return None
        return value

    def __init__(self, **data: Any) -> None:
        if "speaker" in data:
            data["speaker"] = self._clean_speaker(data["speaker"])
        super().__init__(**data)


class ModelEvidenceRole(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ex_id: str
    suggested_role: str


class ModelReview(BaseModel):
    model_config = ConfigDict(extra="ignore")

    fields: List[ModelField]
    conflicts: List[ModelConflict] = []
    questions: List[ModelQuestion] = []
    utterances: List[ModelUtterance] = []
    evidence_roles: List[ModelEvidenceRole] = []


_DATE_RE = re.compile(r"(\d{4})\D{0,3}(\d{1,2})\D{0,3}(\d{1,2})")


class _ValueError(ValueError):
    pass


def _digits_only(raw: Any, what: str) -> str:
    text = str(raw).strip().replace(",", "").replace(" ", "").replace("원", "")
    if not text or any(not ch.isdigit() for ch in text):
        raise _ValueError(f"{what} is not digits")
    return text.lstrip("0") or "0"


def _iso_date(raw: Any, what: str) -> str:
    text = str(raw).strip()
    match = _DATE_RE.search(text)
    if not match:
        raise _ValueError(f"{what} is not a date")
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError as exc:
        raise _ValueError(f"{what} is not a date") from exc


def _is_null_token(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("", "null", "none", "-", "없음")
    return False


def normalize_field_value(name: str, value: Any) -> Any:
    """Machine formats for one field (raises _ValueError when unfixable)."""
    if _is_null_token(value):
        return [] if name == "repayments" else None
    if name == "principal":
        return _digits_only(value, name)
    if name in ("loan_date", "due_date"):
        return _iso_date(value, name)
    if name == "interest_rate":
        text = str(value).strip().rstrip("%").strip()
        if text.lower() in ("", "없음", "null", "none", "-"):
            return None
        try:
            return format(Decimal(text).normalize(), "f")
        except (InvalidOperation, ValueError) as exc:
            raise _ValueError(f"{name} is not numeric") from exc
    if name == "transaction_kind":
        text = str(value).strip().lower()
        if text in ("civil", "민사"):
            return "civil"
        if text in ("commercial", "상사"):
            return "commercial"
        raise _ValueError(f"{name} is not civil|commercial")
    if name == "repayments":
        if isinstance(value, str) and _is_null_token(value):
            return []
        if not isinstance(value, list):
            raise _ValueError("repayments is not a list")
        cleaned = []
        for entry in value:
            if not isinstance(entry, dict):
                raise _ValueError("repayments[] is not an object")
            cleaned.append({
                "date": _iso_date(entry.get("date"), "repayments.date"),
                "amount": _digits_only(entry.get("amount"), "repayments.amount"),
            })
        return cleaned
    return str(value).strip() or None


def display_for(name: str, value: Any) -> str:
    if name == "principal":
        return deps.fmt_amount_won(value) if value not in (None, "") else ""
    if name in ("loan_date", "due_date"):
        return deps.fmt_kr_date(value) if value not in (None, "") else ""
    if name == "interest_rate":
        return "약정 없음" if value in (None, "") else deps.fmt_rate_pct(value)
    if name == "transaction_kind":
        if value is None or value == "":
            return ""
        return "개인 간 거래" if value == "civil" else "상거래"
    if name == "repayments":
        parts = [f"{deps.fmt_kr_date(r['date'])} {deps.fmt_amount_won(r['amount'])}"
                 for r in (value or [])]
        return ", ".join(parts)
    return "" if value is None else str(value)


def build_organizer_payload(prompt_text: str, readings: List[Dict[str, Any]]) -> Any:
    """Request payload: readings only (no case_id, URL, time, or path)."""
    slim = [
        {"ex_id": reading.get("ex_id"), "items": [
            {"item_id": item.get("item_id"), "kind": item.get("kind"),
             "text_verbatim": item.get("text_verbatim"),
             "normalized": item.get("normalized"),
             "speaker": item.get("speaker"), "side": item.get("side")}
            for item in reading.get("items", []) or []
        ]}
        for reading in readings or []
    ]
    text = (f"{prompt_text}\n\nREADINGS:\n"
            f"{json.dumps(slim, ensure_ascii=False, sort_keys=True)}")
    return [{"role": "user", "content": [{"type": "input_text", "text": text}]}]


def _readings_by_ref(
    readings: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    by_ref: Dict[str, Dict[str, Any]] = {}
    for reading in readings or []:
        for item in reading.get("items", []) or []:
            ref = f"{reading.get('ex_id')}:{item.get('item_id')}"
            by_ref[ref] = item if isinstance(item, dict) else {}
    return by_ref


def _cross_check_value(
    name: str, value: Any, sources: List[Dict[str, str]],
    by_ref: Dict[str, Dict[str, Any]],
) -> Optional[str]:
    """Compare a fact value with its cited readings' normalized (P5)."""
    if value is None or value == [] or not sources:
        return None
    if name == "principal":
        for source in sources:
            item = by_ref.get(f"{source['ex_id']}:{source['item_id']}", {})
            normalized = item.get("normalized")
            if normalized is None or (isinstance(normalized, str)
                                      and not normalized.strip()):
                continue
            try:
                cited = _digits_only(normalized, name)
            except _ValueError:
                continue
            if cited != value:
                return (f"원금 {value}와 인용한 판독값 {cited}가 다릅니다.")
        return None
    if name in ("loan_date", "due_date"):
        for source in sources:
            item = by_ref.get(f"{source['ex_id']}:{source['item_id']}", {})
            normalized = item.get("normalized")
            if normalized is None or (isinstance(normalized, str)
                                      and not normalized.strip()):
                continue
            try:
                cited = _iso_date(normalized, name)
            except _ValueError:
                continue
            if cited != value:
                return (f"{FIELD_LABELS[name]} {value}와 인용한 판독값 "
                        f"{cited}가 다릅니다.")
        return None
    if name == "repayments":
        cited_amounts: set = set()
        cited_dates: set = set()
        for source in sources:
            item = by_ref.get(f"{source['ex_id']}:{source['item_id']}", {})
            normalized = item.get("normalized")
            if normalized is None or (isinstance(normalized, str)
                                      and not normalized.strip()):
                continue
            try:
                cited_amounts.add(_digits_only(normalized, name))
                continue
            except _ValueError:
                pass
            try:
                cited_dates.add(_iso_date(normalized, name))
            except _ValueError:
                continue
        for entry in value or []:
            if not isinstance(entry, dict):
                continue
            if (cited_amounts and entry.get("amount") not in cited_amounts):
                return (f"변제액 {entry.get('amount')}가 인용한 판독값과 "
                        "다릅니다.")
            if cited_dates and entry.get("date") not in cited_dates:
                return (f"변제일 {entry.get('date')}가 인용한 판독값과 "
                        "다릅니다.")
        return None
    return None


def normalize_review(
    parsed: Any,
    readings: List[Dict[str, Any]],
    ex_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Model output -> full Review (code labels + displays, validated refs)."""
    if not isinstance(parsed, dict):
        raise AgentSchemaError("사실 정리 출력이 JSON 객체가 아닙니다.")
    try:
        output = ModelReview.model_validate(parsed)
    except ValidationError as exc:
        raise AgentSchemaError(
            f"사실 정리 출력 형식 오류: {field_summary(exc)}"
        ) from exc
    by_ref = _readings_by_ref(readings)
    known_refs = set(by_ref)
    by_name: Dict[str, ModelField] = {}
    for entry in output.fields:
        if entry.field in KNOWN_FIELDS and entry.field not in by_name:
            by_name[entry.field] = entry
    fields = []
    for name in KNOWN_FIELDS:
        entry = by_name.get(name)
        raw = entry.value if entry else None
        try:
            value = normalize_field_value(name, raw)
        except _ValueError as exc:
            raise AgentSchemaError(f"사실 정리 값 형식 오류: {name}") from exc
        sources = []
        if entry:
            for source in entry.sources:
                ref = f"{source.ex_id}:{source.item_id}"
                if ref in known_refs:
                    sources.append({"ex_id": source.ex_id,
                                    "item_id": source.item_id})
        empty = value is None or value == []
        model_reason = (entry.null_reason if entry else None)
        if isinstance(model_reason, str):
            model_reason = model_reason.strip() or None
        else:
            model_reason = None
        null_reason = model_reason if empty else None
        if empty and null_reason is None:
            null_reason = "판독에서 찾지 못함"
        conflict = bool(entry.conflict) if entry else False
        fields.append({
            "field": name, "label": FIELD_LABELS[name], "value": value,
            "display": display_for(name, value), "sources": sources,
            "conflict": conflict, "null_reason": null_reason,
        })
    for entry in fields:
        note = _cross_check_value(
            entry["field"], entry["value"], entry["sources"], by_ref)
        if note is not None:
            entry["conflict"] = True
    conflicts = [
        {"fields": [name for name in item.fields if name in KNOWN_FIELDS],
         "note": item.note}
        for item in output.conflicts
    ]
    for entry in fields:
        note = _cross_check_value(
            entry["field"], entry["value"], entry["sources"], by_ref)
        if note is not None and not any(
                entry["field"] in item.get("fields", [])
                and note in item.get("note", "")
                for item in conflicts):
            conflicts.append({"fields": [entry["field"]], "note": note})
    flagged = {entry["field"] for entry in fields
               if entry["conflict"] or entry["value"] is None
               or entry["value"] == []}
    questions = [
        {"field": item.field, "question": item.question}
        for item in output.questions
        if item.field in KNOWN_FIELDS and item.field in flagged
    ]
    utterances = []
    for item in output.utterances:
        if f"{item.ex_id}:{item.item_id}" not in known_refs:
            continue
        tags = [tag for tag in item.tags if tag in VALID_TAGS] or ["other"]
        utterances.append({
            "ex_id": item.ex_id, "item_id": item.item_id,
            "speaker": item.speaker, "text": item.text, "tags": tags,
        })
    roles = {}
    for item in output.evidence_roles:
        role = item.suggested_role if item.suggested_role in VALID_ROLES else "other"
        roles.setdefault(item.ex_id, role)
    wanted = list(ex_ids or []) or sorted(
        {reading.get("ex_id", "") for reading in readings or []})
    evidence_roles = [
        {"ex_id": ex_id, "suggested_role": roles.get(ex_id, "other")}
        for ex_id in wanted if ex_id
    ]
    return {
        "fields": fields,
        "conflicts": conflicts,
        "questions": questions,
        "utterances": utterances,
        "evidence_roles": evidence_roles,
    }


def run_organizer(
    case_id: str,
    readings: List[Dict[str, Any]],
    meta_mode: str,
    run_id: str,
    ex_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Organize readings into a Review. Returns review + call accounting."""
    prompt = load_prompt(PROMPT_FILE)
    payload = build_organizer_payload(prompt, readings)
    total_latency = 0
    total_attempts = 0
    total_in = 0
    total_out = 0
    total_cost = 0.0
    try:
        parsed, info = run_spark_json(
            model=MODEL, payload=payload, text_format=ORGANIZER_TEXT_FORMAT,
            reasoning_effort=REASONING_EFFORT, meta_mode=meta_mode,
            run_id=run_id, max_output_tokens=MAX_OUTPUT_TOKENS,
        )
    except deps.IncompleteResponse as exc:
        raise AgentSchemaError("사실 정리 응답이 끊겼습니다(2회 시도).") from exc
    total_latency += info["latency_ms"]
    total_attempts += info["attempts"]
    total_in += info["tokens_in"]
    total_out += info["tokens_out"]
    total_cost += info["cost_usd"]
    try:
        review = normalize_review(parsed, readings, ex_ids)
    except AgentSchemaError as first:
        summary = "fields"
        if isinstance(parsed, dict):
            try:
                ModelReview.model_validate(parsed)
            except ValidationError as exc:
                summary = field_summary(exc)
        retry_prompt = (f"{prompt}\n\n이전 출력의 오류: {summary}. "
                        "같은 스키마로 다시 출력하세요.")
        payload = build_organizer_payload(retry_prompt, readings)
        try:
            parsed, info = run_spark_json(
                model=MODEL, payload=payload, text_format=ORGANIZER_TEXT_FORMAT,
                reasoning_effort=REASONING_EFFORT, meta_mode=meta_mode,
                run_id=run_id, max_output_tokens=MAX_OUTPUT_TOKENS,
            )
        except deps.IncompleteResponse as exc:
            raise AgentSchemaError("사실 정리 응답이 끊겼습니다(2회 시도).") from exc
        total_latency += info["latency_ms"]
        total_attempts += info["attempts"]
        total_in += info["tokens_in"]
        total_out += info["tokens_out"]
        total_cost += info["cost_usd"]
        review = normalize_review(parsed, readings, ex_ids)
    return {
        "review": review,
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "latency_ms": total_latency,
        "attempts": total_attempts,
        "tokens_in": total_in,
        "tokens_out": total_out,
        "cost_usd": round(total_cost, 6),
    }
