"""Reader worker (Spark): verbatim reading with norm1000 boxes."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, field_validator

from app.agents import deps
from app.agents.base import AgentSchemaError
from app.agents.spark import field_summary, load_prompt, run_spark_json

PROMPT_VERSION = "reader.v1"
PROMPT_FILE = "reader.v1.md"
MAX_OUTPUT_TOKENS = 4000
REASONING_EFFORT = "low"

READER_KINDS = (
    "utterance", "amount", "date", "party_name", "account_number",
    "id_number", "address", "phone", "label", "header",
)

READING_TEXT_FORMAT: Dict[str, Any] = {
    "type": "json_schema",
    "name": "reading",
    "schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": list(READER_KINDS)},
                        "text_verbatim": {"type": "string"},
                        "normalized": {"type": ["string", "null"]},
                        "box": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 4,
                            "maxItems": 4,
                        },
                        "speaker": {"type": ["string", "null"]},
                        "side": {"type": ["string", "null"],
                                 "enum": ["left", "right", None]},
                        "confidence": {"type": ["number", "null"]},
                    },
                    "required": ["kind", "text_verbatim", "normalized", "box",
                                 "speaker", "side", "confidence"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    },
    "strict": True,
}

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


class ModelReadingItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: str
    text_verbatim: str
    normalized: Optional[str] = None
    box: List[float]
    speaker: Optional[str] = None
    side: Optional[str] = None
    confidence: Optional[float] = None

    @field_validator("box")
    @classmethod
    def _box_len(cls, value: List[float]) -> List[float]:
        if len(value) != 4:
            raise ValueError("box must have 4 numbers")
        return [float(v) for v in value]

    @field_validator("normalized", "speaker", "side", mode="before")
    @classmethod
    def _null_string(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().lower() in ("null", "none", ""):
            return None
        return value

    @field_validator("kind")
    @classmethod
    def _kind_enum(cls, value: str) -> str:
        if value not in READER_KINDS:
            raise ValueError(f"unknown kind: {value}")
        return value

    @field_validator("side")
    @classmethod
    def _side_enum(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in ("left", "right"):
            raise ValueError(f"side must be left|right: {value}")
        return value


class ModelReading(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: List[ModelReadingItem]


def build_reader_payload(
    prompt_text: str, kind: str, data: bytes, filename: str
) -> List[Dict[str, Any]]:
    """Request payload: no case_id, URL, timestamp, or file path inside."""
    if kind == "pdf":
        encoded = base64.b64encode(bytes(data)).decode("ascii")
        attachment: Dict[str, Any] = {
            "type": "input_file",
            "filename": Path(filename or "evidence.pdf").name,
            "file_data": f"data:application/pdf;base64,{encoded}",
        }
    else:
        suffix = Path(filename or "").suffix.lower()
        mime = _IMAGE_MIME.get(suffix, "image/png")
        encoded = base64.b64encode(bytes(data)).decode("ascii")
        attachment = {
            "type": "input_image",
            "image_url": f"data:{mime};base64,{encoded}",
        }
    return [{"role": "user", "content": [
        {"type": "input_text", "text": prompt_text},
        attachment,
    ]}]


def _pdf_points_size(path: Path) -> Optional[Tuple[int, int]]:
    """First-page size in points (fallback ref when no preview PNG exists)."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        if not reader.pages:
            return None
        box = reader.pages[0].mediabox
        width = int(float(box.width))
        height = int(float(box.height))
        if width > 0 and height > 0:
            return (width, height)
    except Exception:
        return None
    return None


def model_items_to_pixels(
    items: List[ModelReadingItem], ref_size: Tuple[int, int]
) -> List[Dict[str, Any]]:
    """norm1000 model boxes -> preview-pixel items (item_id recoded later)."""
    width, height = int(ref_size[0]), int(ref_size[1])
    out: List[Dict[str, Any]] = []
    for item in items:
        clamped = [min(1000.0, max(0.0, float(v))) for v in item.box]
        box = deps.Box(
            x1=clamped[0], y1=clamped[1], x2=clamped[2], y2=clamped[3],
            system="norm1000", ref_w=width, ref_h=height,
        )
        x1, y1, x2, y2 = deps.box_to_pixels(box, width, height)
        normalized = item.normalized
        if item.kind not in ("amount", "date", "phone", "account_number"):
            normalized = None
        out.append({
            "kind": item.kind,
            "text_verbatim": item.text_verbatim,
            "normalized": normalized,
            "box": {"x1": x1, "y1": y1, "x2": x2, "y2": y2,
                    "system": "pixel", "ref_w": width, "ref_h": height},
            "speaker": item.speaker,
            "side": item.side,
            "confidence": item.confidence,
        })
    return out


def _validate(parsed: Any) -> ModelReading:
    if not isinstance(parsed, dict):
        raise AgentSchemaError("판독 출력이 JSON 객체가 아닙니다.")
    try:
        return ModelReading.model_validate(parsed)
    except Exception as exc:
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            raise AgentSchemaError(
                f"판독 출력 형식 오류: {field_summary(exc)}"
            ) from exc
        raise


def _retry_summary(parsed: Any) -> str:
    if not isinstance(parsed, dict):
        return "entire output (not an object)"
    try:
        ModelReading.model_validate(parsed)
    except Exception as exc:
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            return field_summary(exc)
    return "items"


def run_reader(
    case_id: str,
    evidence: Dict[str, Any],
    evidence_path: Any,
    preview_size: Optional[Tuple[int, int]],
    meta_mode: str,
    run_id: str,
) -> Dict[str, Any]:
    """Read one evidence file. Returns pixel items + call accounting."""
    kind = str(evidence.get("kind", "image"))
    filename = str(evidence.get("filename", "evidence"))
    path = Path(str(evidence_path))
    data = path.read_bytes()
    ref_size = preview_size
    if ref_size is None and kind == "pdf":
        ref_size = _pdf_points_size(path)
    if ref_size is None:
        raise AgentSchemaError("미리보기 크기를 알 수 없어 박스를 변환할 수 없습니다.")
    model = deps.READER_MODEL
    prompt = load_prompt(PROMPT_FILE)
    payload = build_reader_payload(prompt, kind, data, filename)
    total_latency = 0
    total_attempts = 0
    total_in = 0
    total_out = 0
    total_cost = 0.0
    try:
        parsed, info = run_spark_json(
            model=model, payload=payload, text_format=READING_TEXT_FORMAT,
            reasoning_effort=REASONING_EFFORT, meta_mode=meta_mode,
            run_id=run_id, max_output_tokens=MAX_OUTPUT_TOKENS,
        )
    except deps.IncompleteResponse as exc:
        raise AgentSchemaError("판독 응답이 끊겼습니다(2회 시도).") from exc
    total_latency += info["latency_ms"]
    total_attempts += info["attempts"]
    total_in += info["tokens_in"]
    total_out += info["tokens_out"]
    total_cost += info["cost_usd"]
    try:
        reading = _validate(parsed)
    except AgentSchemaError:
        retry_prompt = (
            f"{prompt}\n\n이전 출력의 오류: {_retry_summary(parsed)}. "
            "같은 스키마로 다시 출력하세요."
        )
        payload = build_reader_payload(retry_prompt, kind, data, filename)
        try:
            parsed, info = run_spark_json(
                model=model, payload=payload, text_format=READING_TEXT_FORMAT,
                reasoning_effort=REASONING_EFFORT, meta_mode=meta_mode,
                run_id=run_id, max_output_tokens=MAX_OUTPUT_TOKENS,
            )
        except deps.IncompleteResponse as exc:
            raise AgentSchemaError("판독 응답이 끊겼습니다(2회 시도).") from exc
        total_latency += info["latency_ms"]
        total_attempts += info["attempts"]
        total_in += info["tokens_in"]
        total_out += info["tokens_out"]
        total_cost += info["cost_usd"]
        reading = _validate(parsed)
    return {
        "items": model_items_to_pixels(reading.items, ref_size),
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "latency_ms": total_latency,
        "attempts": total_attempts,
        "tokens_in": total_in,
        "tokens_out": total_out,
        "cost_usd": round(total_cost, 6),
    }
