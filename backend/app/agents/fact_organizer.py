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

PROMPT_VERSION = "fact_organizer.v2"
PROMPT_FILE = "fact_organizer.v2.md"
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
_MD_RE = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_WS_RE = re.compile(r"\s+")
_EX_NUM_RE = re.compile(r"(?i)^EX(\d+)$")
# Leading labels stripped before name/address comparison ("채권자: ...").
_HEADER_RE = re.compile(
    r"^(채권자|채무자|성명|이름|주소|연락처|전화번호|전화)\s*[:：]?\s*")

# Fields compared against cited readings' verbatim text, not normalized.
NAME_FIELDS = ("creditor_name", "debtor_name", "creditor_address",
               "debtor_address", "creditor_phone")


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


def _norm_ex(ex_id: Any) -> str:
    """Case-insensitive exhibit id ('ex6' -> 'EX6')."""
    return str(ex_id or "").strip().upper()


def _readings_by_ref(
    readings: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    by_ref: Dict[str, Dict[str, Any]] = {}
    for reading in readings or []:
        for item in reading.get("items", []) or []:
            ref = f"{_norm_ex(reading.get('ex_id'))}:{item.get('item_id')}"
            by_ref[ref] = item if isinstance(item, dict) else {}
    return by_ref


def _ex_label(ex_id: str) -> str:
    """'EX2' -> '갑 제2호증' (unknown ids pass through)."""
    match = _EX_NUM_RE.match(str(ex_id or "").strip())
    if match:
        return f"갑 제{int(match.group(1))}호증"
    return str(ex_id)


def _verbatim_month_days(item: Dict[str, Any]) -> List[tuple]:
    """Every month/day in a cited item's verbatim (M2c-fix1 D10).

    A value matches when ANY of them agrees (first-only comparison
    missed later dates in the same utterance).
    """
    text = item.get("text_verbatim") if isinstance(item, dict) else None
    if not isinstance(text, str):
        return []
    return [(int(match.group(1)), int(match.group(2)))
            for match in _MD_RE.finditer(text)]


def _has_verbatim(item: Dict[str, Any]) -> bool:
    text = item.get("text_verbatim") if isinstance(item, dict) else None
    return isinstance(text, str) and bool(text.strip())


def _iso_month_day(iso: Any) -> Optional[tuple]:
    try:
        parts = str(iso).strip().split("-")
        return (int(parts[1]), int(parts[2]))
    except (ValueError, IndexError, AttributeError):
        return None


def _canon_text(raw: Any) -> str:
    """Compare form: header labels stripped, whitespace removed.

    Parentheses are KEPT (M2c-fix1 D2): "(SAMPLE)" and "(주)" are
    part of the name. Comparison is containment (D9), so a dropped
    paren still passes but a different paren does not.
    """
    return _WS_RE.sub("", _HEADER_RE.sub("", str(raw or "").strip()))


def _text_contains(left: str, right: str) -> bool:
    return bool(left) and bool(right) and (left in right or right in left)


def _canon_phone(raw: Any) -> str:
    return "".join(ch for ch in str(raw or "") if ch.isdigit())


def _date_conflict_note(
    value: str,
    agree: Optional[Dict[str, str]],
    differ: List[tuple],
) -> str:
    """Fact-only note: observed dates with exhibit labels (M2c task 5)."""
    parts = []
    if agree is not None:
        parts.append(f"{deps.fmt_kr_date(value)}({_ex_label(agree['ex_id'])})")
    else:
        parts.append(deps.fmt_kr_date(value))
    for display, source, item in differ:
        label = _ex_label(source["ex_id"])
        if isinstance(item, dict) and item.get("kind") == "utterance":
            label += " 대화"
        parts.append(f"{display}({label})")
    return "증거에 나온 날짜가 서로 다릅니다: " + ", ".join(parts)


def _unverifiable_note(name: str, refs: List[str]) -> str:
    """Note for cited items with no checkable content (M2c-fix1 D10)."""
    return (f"{FIELD_LABELS[name]} 값의 근거 확인 불가: "
            f"{', '.join(refs)}.")


def _cross_check_value(
    name: str, value: Any, sources: List[Dict[str, str]],
    by_ref: Dict[str, Dict[str, Any]],
) -> Optional[str]:
    """Compare a fact value with its cited readings (P5, M2c-fix1).

    Amounts/dates are compared with the cited items' machine values
    (``normalized``); date items without one fall back to EVERY
    verbatim month/day (a match on any one agrees). Names/addresses
    are compared with the cited verbatim text by containment
    (parentheses kept, header labels stripped); phones by digits.
    Cited items with neither a machine value nor verbatim text are
    reported as unverifiable.
    """
    if value is None or value == [] or not sources:
        return None

    def _item(source: Dict[str, str]) -> Dict[str, Any]:
        return by_ref.get(
            f"{_norm_ex(source['ex_id'])}:{source['item_id']}", {})

    if name == "principal":
        unverified: List[str] = []
        for source in sources:
            item = _item(source)
            normalized = item.get("normalized")
            if normalized is None or (isinstance(normalized, str)
                                      and not normalized.strip()):
                if not _has_verbatim(item):
                    unverified.append(
                        f"{source['ex_id']}:{source['item_id']}")
                continue
            try:
                cited = _digits_only(normalized, name)
            except _ValueError:
                continue
            if cited != value:
                return (f"원금 {value}와 인용한 판독값 {cited}가 다릅니다.")
        if unverified:
            return _unverifiable_note(name, unverified)
        return None
    if name in ("loan_date", "due_date"):
        agree: Optional[Dict[str, str]] = None
        differ: List[tuple] = []
        unverified: List[str] = []
        for source in sources:
            item = _item(source)
            normalized = item.get("normalized")
            cited_full: Optional[str] = None
            if normalized is not None and str(normalized).strip():
                try:
                    cited_full = _iso_date(normalized, name)
                except _ValueError:
                    cited_full = None
            if cited_full is not None:
                if cited_full == value:
                    agree = agree or source
                else:
                    differ.append((deps.fmt_kr_date(cited_full), source, item))
                continue
            month_days = _verbatim_month_days(item)
            if not month_days:
                if not _has_verbatim(item):
                    unverified.append(
                        f"{source['ex_id']}:{source['item_id']}")
                continue
            if _iso_month_day(value) in month_days:
                agree = agree or source
            else:
                for month, day in dict.fromkeys(month_days):
                    differ.append((f"{month}월 {day}일", source, item))
        if differ:
            return _date_conflict_note(str(value), agree, differ)
        if unverified:
            return _unverifiable_note(name, unverified)
        return None
    if name == "repayments":
        cited_amounts: set = set()
        cited_dates: set = set()
        cited_md: set = set()
        unverified: List[str] = []
        for source in sources:
            item = _item(source)
            normalized = item.get("normalized")
            if normalized is not None and str(normalized).strip():
                try:
                    cited_amounts.add(_digits_only(normalized, name))
                    continue
                except _ValueError:
                    pass
                try:
                    cited_dates.add(_iso_date(normalized, name))
                    continue
                except _ValueError:
                    pass
            month_days = _verbatim_month_days(item)
            if month_days:
                cited_md.update(month_days)
            elif not _has_verbatim(item):
                unverified.append(f"{source['ex_id']}:{source['item_id']}")
        for entry in value or []:
            if not isinstance(entry, dict):
                continue
            if (cited_amounts and entry.get("amount") not in cited_amounts):
                return (f"변제액 {entry.get('amount')}가 인용한 판독값과 "
                        "다릅니다.")
            if cited_dates and entry.get("date") not in cited_dates:
                return (f"변제일 {entry.get('date')}가 인용한 판독값과 "
                        "다릅니다.")
            if not cited_dates and cited_md:
                if _iso_month_day(entry.get("date")) not in cited_md:
                    return (f"변제일 {entry.get('date')}가 인용한 판독 "
                            "원문과 다릅니다.")
        if unverified:
            return _unverifiable_note(name, unverified)
        return None
    if name in NAME_FIELDS:
        if name == "creditor_phone":
            wanted = _canon_phone(value)
            if not wanted:
                return None
            unverified: List[str] = []
            for source in sources:
                item = _item(source)
                verbatim = item.get("text_verbatim")
                if not isinstance(verbatim, str) or not verbatim.strip():
                    unverified.append(
                        f"{source['ex_id']}:{source['item_id']}")
                    continue
                if _canon_phone(verbatim) == wanted:
                    return None
            if unverified:
                return _unverifiable_note(name, unverified)
            return (f"{FIELD_LABELS[name]} 값이 인용한 판독 원문과 "
                    "다릅니다.")
        wanted = _canon_text(value)
        if not wanted:
            return None
        unverified = []
        for source in sources:
            item = _item(source)
            verbatim = item.get("text_verbatim")
            if not isinstance(verbatim, str) or not verbatim.strip():
                unverified.append(f"{source['ex_id']}:{source['item_id']}")
                continue
            if _text_contains(wanted, _canon_text(verbatim)):
                return None
        if unverified and len(unverified) == len(sources):
            return _unverifiable_note(name, unverified)
        return (f"{FIELD_LABELS[name]} 값이 인용한 판독 원문과 "
                "다릅니다.")
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
    # Code-found conflicts (M2c task 4): field -> (note, question).
    code_found: Dict[str, tuple] = {}
    # Code-found questions without a conflict (M2c-fix1 D10).
    code_asked: Dict[str, str] = {}
    for name in KNOWN_FIELDS:
        entry = by_name.get(name)
        raw = entry.value if entry else None
        try:
            value = normalize_field_value(name, raw)
        except _ValueError as exc:
            raise AgentSchemaError(f"사실 정리 값 형식 오류: {name}") from exc
        raw_sources = list(entry.sources) if entry else []
        sources = []
        for source in raw_sources:
            ref = f"{_norm_ex(source.ex_id)}:{source.item_id}"
            if ref in known_refs:
                sources.append({"ex_id": _norm_ex(source.ex_id),
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
        if not empty:
            if not raw_sources:
                note = f"{FIELD_LABELS[name]} 값의 근거가 없습니다."
                question = f"{note} 올바른 값을 입력해 주세요."
                if name == "transaction_kind":
                    code_asked[name] = question
                else:
                    code_found[name] = (note, question)
                    conflict = True
            elif not sources:
                refs = ", ".join(f"{s.ex_id}:{s.item_id}"
                                 for s in raw_sources)
                note = (f"{FIELD_LABELS[name]} 값의 근거가 판독에 "
                        f"없습니다: {refs}.")
                question = f"{note} 올바른 값을 입력해 주세요."
                if name == "transaction_kind":
                    code_asked[name] = question
                else:
                    code_found[name] = (note, question)
                    conflict = True
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
            code_found.setdefault(
                entry["field"],
                (note, f"{note} 올바른 값을 입력해 주세요."))
    conflicts = [
        {"fields": [name for name in item.fields if name in KNOWN_FIELDS],
         "note": item.note}
        for item in output.conflicts
    ]
    for name in KNOWN_FIELDS:
        found = code_found.get(name)
        if found is None:
            continue
        note = found[0]
        if not any(name in item.get("fields", [])
                   and note in item.get("note", "")
                   for item in conflicts):
            conflicts.append({"fields": [name], "note": note})
    flagged = {entry["field"] for entry in fields
               if entry["conflict"] or entry["value"] is None
               or entry["value"] == []}
    questions = [
        {"field": item.field, "question": item.question}
        for item in output.questions
        if item.field in KNOWN_FIELDS and item.field in flagged
    ]
    asked = {item["field"] for item in questions}
    for name in KNOWN_FIELDS:
        found = code_found.get(name)
        if found is not None and name not in asked:
            questions.append({"field": name, "question": found[1]})
            asked.add(name)
    for name in KNOWN_FIELDS:
        only = code_asked.get(name)
        if only is not None and name not in asked:
            questions.append({"field": name, "question": only})
    utterances = []
    for item in output.utterances:
        if f"{_norm_ex(item.ex_id)}:{item.item_id}" not in known_refs:
            continue
        tags = [tag for tag in item.tags if tag in VALID_TAGS] or ["other"]
        utterances.append({
            "ex_id": _norm_ex(item.ex_id), "item_id": item.item_id,
            "speaker": item.speaker, "text": item.text, "tags": tags,
        })
    roles = {}
    for item in output.evidence_roles:
        role = item.suggested_role if item.suggested_role in VALID_ROLES else "other"
        roles.setdefault(_norm_ex(item.ex_id), role)
    wanted = [_norm_ex(ex_id) for ex_id in list(ex_ids or []) or sorted(
        {_norm_ex(reading.get("ex_id", "")) for reading in readings or []})]
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
