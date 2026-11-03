"""Meta Model API client with budget cap, cost ledger, and record/replay.

Docs used (2026-11-03):
  https://dev.meta.ai/docs/models
  https://dev.meta.ai/docs/pricing-rate-limits
  https://dev.meta.ai/docs/protocols/responses
  https://dev.meta.ai/docs/image-understanding
  https://dev.meta.ai/docs/video-understanding
  https://dev.meta.ai/docs/file-handling
  https://dev.meta.ai/docs/structured-output
  https://dev.meta.ai/docs/media-segmentation
  https://dev.meta.ai/docs/sam/overview
  https://dev.meta.ai/docs/sam/segmenting
  https://dev.meta.ai/docs/sam/reading-segmentation
  https://dev.meta.ai/docs/sam/client-libraries
  https://dev.meta.ai/docs/image-generation
  https://pypi.org/project/meta-sam-parser/
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import random
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import pricing

BASE_URL = "https://api.meta.ai/v1"
KEY_ENV = "MODEL_API_KEY"
MODE_ENV = "META_MODE"
VALID_MODES = ("live", "record", "replay")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LEDGER_PATH = REPO_ROOT / "reports" / "cost_ledger.jsonl"
DEFAULT_FIXTURE_DIR = REPO_ROOT / "backend" / "tests" / "fixtures" / "meta"

RETRYABLE_STATUS = (429, 500, 502, 503, 504)
IMAGE_TOKEN_EST = 1500  # heuristic per image for pre-call budget estimates
VIDEO_TOKEN_EST = 6000  # heuristic per video for pre-call budget estimates


class BudgetExceeded(RuntimeError):
    pass


class FixtureNotFound(FileNotFoundError):
    pass


class MissingKeyError(RuntimeError):
    pass


class ContributorModelError(ValueError):
    pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_data_url(value: str) -> str:
    """Replace a data: URL payload with its byte SHA-256 for hashing/summaries."""
    try:
        header, _, payload = value.partition(",")
        if ";base64," in value or header.endswith(";base64"):
            raw = base64.b64decode(payload, validate=False)
        else:
            raw = payload.encode("utf-8")
        mime = header[5:].split(";")[0] if header.startswith("data:") else ""
        return f"sha256:{_sha256_hex(raw)}:{mime}"
    except Exception:
        return f"sha256:{_sha256_hex(value.encode('utf-8'))}"


def canonicalize_for_hash(obj: Any) -> Any:
    """Deep-copy input with attachment bytes replaced by SHA-256 markers."""
    if isinstance(obj, str):
        if obj.startswith("data:") and len(obj) > 64:
            return _hash_data_url(obj)
        return obj
    if isinstance(obj, bytes):
        return f"sha256:{_sha256_hex(bytes(obj))}"
    if isinstance(obj, dict):
        return {k: canonicalize_for_hash(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [canonicalize_for_hash(v) for v in obj]
    return obj


def request_hash(model: str, endpoint: str, params: dict, payload: Any) -> str:
    canonical = {
        "endpoint": endpoint,
        "model": model,
        "params": canonicalize_for_hash(params or {}),
        "payload": canonicalize_for_hash(payload),
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    return _sha256_hex(blob)


def _count_text_chars(obj: Any) -> int:
    if isinstance(obj, str):
        if obj.startswith("data:"):
            return 0
        if obj.startswith("sha256:"):
            return 0
        return len(obj)
    if isinstance(obj, dict):
        return sum(_count_text_chars(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return sum(_count_text_chars(v) for v in obj)
    return 0


def _count_blocks(payload: Any, block_type: str) -> int:
    count = 0
    if isinstance(obj := payload, dict):
        if obj.get("type") == block_type:
            count += 1
        count += sum(_count_blocks(v, block_type) for v in obj.values())
    elif isinstance(payload, (list, tuple)):
        count += sum(_count_blocks(v, block_type) for v in payload)
    return count


def estimate_input_tokens(payload: Any) -> int:
    text_tokens = math.ceil(_count_text_chars(payload) / 4) if payload else 1
    images = _count_blocks(payload, "input_image")
    videos = _count_blocks(payload, "input_video")
    files = _count_blocks(payload, "input_file")
    return max(1, text_tokens + images * IMAGE_TOKEN_EST
               + videos * VIDEO_TOKEN_EST + files * IMAGE_TOKEN_EST)


def _to_jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if hasattr(obj, "model_dump"):
        try:
            return _to_jsonable(obj.model_dump(mode="json"))
        except TypeError:
            return _to_jsonable(obj.model_dump())
    if hasattr(obj, "to_dict"):
        try:
            return _to_jsonable(obj.to_dict())
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        try:
            return _to_jsonable(vars(obj))
        except Exception:
            pass
    try:
        return str(obj)
    except Exception:
        return None


def _scrub_opaque(obj: Any) -> Any:
    """Remove opaque random blobs not needed for replay.

    Reasoning ``encrypted_content`` is long random text that can falsely
    match secret-scan rules. Single-shot replay only needs output text and
    usage, so drop it from fixtures.
    """
    if isinstance(obj, dict):
        return {k: ("<redacted>" if k == "encrypted_content"
                    else _scrub_opaque(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_opaque(v) for v in obj]
    return obj


def _get_field(obj: Any, *names: str, default=0) -> Any:
    for name in names:
        if isinstance(obj, dict) and name in obj:
            val = obj[name]
            if val is not None:
                return val
        elif hasattr(obj, name):
            try:
                val = getattr(obj, name)
            except Exception:
                continue
            if val is not None:
                return val
    return default


def extract_usage(response: Any) -> dict:
    """Normalize usage across Responses/Images/SAM shapes. Never raises."""
    usage = _get_field(response, "usage", default=None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
                "reasoning_tokens": 0, "video_frames_processed": 0,
                "total_tokens": 0}
    input_tokens = int(_get_field(usage, "input_tokens", default=0) or 0)
    output_tokens = int(_get_field(usage, "output_tokens", default=0) or 0)
    total_tokens = int(_get_field(usage, "total_tokens", default=0) or 0)
    cached = 0
    details = _get_field(usage, "input_tokens_details", "input_details", default=None)
    if details is not None:
        cached = int(_get_field(details, "cached_tokens", "cached_input_tokens",
                                default=0) or 0)
    if not cached:
        cached = int(_get_field(usage, "cached_tokens", "cached_input_tokens",
                                default=0) or 0)
    reasoning = 0
    out_details = _get_field(usage, "output_tokens_details", "output_details",
                             default=None)
    if out_details is not None:
        reasoning = int(_get_field(out_details, "reasoning_tokens", default=0) or 0)
    if not reasoning:
        reasoning = int(_get_field(usage, "reasoning_tokens", default=0) or 0)
    frames = int(_get_field(usage, "video_frames_processed", "frames_processed",
                            default=0) or 0)
    return {"input_tokens": input_tokens, "cached_input_tokens": cached,
            "output_tokens": output_tokens, "reasoning_tokens": reasoning,
            "video_frames_processed": frames, "total_tokens": total_tokens}


def extract_output_text(response: Any) -> str:
    text = _get_field(response, "output_text", default=None)
    if isinstance(text, str) and text:
        return text
    output = _get_field(response, "output", default=None)
    chunks: list[str] = []
    if isinstance(output, list):
        for item in output:
            content = _get_field(item, "content", default=None)
            if isinstance(content, list):
                for part in content:
                    t = _get_field(part, "text", default=None)
                    if isinstance(t, str):
                        chunks.append(t)
            t = _get_field(item, "text", default=None)
            if isinstance(t, str):
                chunks.append(t)
    if chunks:
        return "".join(chunks)
    if isinstance(response, dict):
        if isinstance(response.get("output_text"), str):
            return response["output_text"]
    return ""


def _status_of(exc: BaseException) -> int | None:
    for attr in ("status_code", "status"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    resp = getattr(exc, "response", None)
    if resp is not None:
        for attr in ("status_code", "status"):
            val = getattr(resp, attr, None)
            if isinstance(val, int):
                return val
    name = type(exc).__name__.lower()
    if "ratelimit" in name or "rate_limit" in name or "too_many_requests" in name:
        return 429
    return None


def _retry_after_seconds(exc: BaseException) -> float | None:
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) if resp is not None else None
    if isinstance(headers, dict):
        for key in ("Retry-After", "retry-after"):
            if key in headers:
                try:
                    return max(0.0, float(headers[key]))
                except (TypeError, ValueError):
                    return None
    else:
        get = getattr(headers, "get", None)
        if callable(get):
            try:
                val = get("retry-after") or get("Retry-After")
                if val is not None:
                    return max(0.0, float(val))
            except (TypeError, ValueError):
                return None
    return None


class MetaClient:
    """Budget-capped Meta client with live/record/replay modes."""

    def __init__(
        self,
        mode: str | None = None,
        run_id: str | None = None,
        ledger_path: str | Path | None = None,
        fixture_dir: str | Path | None = None,
        transport: Any = None,
        base_url: str = BASE_URL,
        timeout: float = 180.0,
        max_retries: int = 3,
    ) -> None:
        raw_mode = mode if mode is not None else os.environ.get(MODE_ENV, "replay")
        normalized = str(raw_mode).strip().lower() or "replay"
        if normalized not in VALID_MODES:
            raise ValueError(f"invalid {MODE_ENV}: {raw_mode!r}")
        self.mode = normalized
        self.run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
        self.ledger_path = Path(ledger_path) if ledger_path else DEFAULT_LEDGER_PATH
        self.fixture_dir = Path(fixture_dir) if fixture_dir else DEFAULT_FIXTURE_DIR
        self.transport = transport
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries

    # -- guards ---------------------------------------------------------
    @staticmethod
    def _reject_contributor(model: str) -> None:
        if model and "-contributor" in str(model):
            raise ContributorModelError(
                f"Contributor model IDs are not allowed: {model}"
            )

    @staticmethod
    def read_key() -> str | None:
        return os.environ.get(KEY_ENV)

    def _require_key(self) -> str:
        key = os.environ.get(KEY_ENV)
        if not key and self.mode in ("live", "record"):
            raise MissingKeyError(
                f"{KEY_ENV} is not set (set the {KEY_ENV} environment variable)"
            )
        return key or ""

    def _live_transport(self) -> Any:
        if self.transport is not None:
            return self.transport
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package is required for live/record mode") from exc
        return OpenAI(api_key=self._require_key(), base_url=self.base_url,
                      timeout=self.timeout)

    # -- ledger / budget ------------------------------------------------
    def ledger_totals(self) -> tuple[float, float]:
        """Return (run_total_usd, grand_total_usd). Missing file means zeros."""
        run_total = 0.0
        grand_total = 0.0
        try:
            if not self.ledger_path.exists():
                return (0.0, 0.0)
            for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    cost = float(entry.get("cost_usd", 0.0) or 0.0)
                except (TypeError, ValueError):
                    continue
                grand_total += cost
                if entry.get("run_id") == self.run_id:
                    run_total += cost
        except OSError:
            return (run_total, grand_total)
        return (round(run_total, 6), round(grand_total, 6))

    def check_budget(self, expected_usd: float) -> None:
        run_total, grand_total = self.ledger_totals()
        expected = float(expected_usd or 0.0)
        if run_total + expected > pricing.BUDGET_PER_RUN_USD:
            raise BudgetExceeded(
                f"run budget exceeded: run_id={self.run_id} "
                f"run_total=${run_total:.4f} + expected=${expected:.4f} "
                f"> ${pricing.BUDGET_PER_RUN_USD:.2f}"
            )
        if grand_total + expected > pricing.BUDGET_TOTAL_USD:
            raise BudgetExceeded(
                f"total budget exceeded: total=${grand_total:.4f} "
                f"+ expected=${expected:.4f} > ${pricing.BUDGET_TOTAL_USD:.2f}"
            )

    def _append_ledger(self, entry: dict) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _record(
        self,
        *,
        model: str,
        endpoint: str,
        usage: dict,
        image_count: int,
        frame_count: int,
        cost_usd: float,
        latency_ms: int,
    ) -> None:
        self._append_ledger({
            "ts": _utc_now_iso(),
            "run_id": self.run_id,
            "model": model,
            "endpoint": endpoint,
            "input_tokens": int(usage.get("input_tokens", 0)),
            "cached_input_tokens": int(usage.get("cached_input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
            "reasoning_tokens": int(usage.get("reasoning_tokens", 0)),
            "image_count": int(image_count),
            "frame_count": int(frame_count),
            "cost_usd": round(float(cost_usd), 6),
            "latency_ms": int(latency_ms),
        })

    # -- fixtures -------------------------------------------------------
    def _fixture_path(self, digest: str) -> Path:
        return self.fixture_dir / f"{digest}.json"

    def _save_fixture(self, digest: str, payload: dict) -> Path:
        self.fixture_dir.mkdir(parents=True, exist_ok=True)
        scrubbed = _scrub_opaque(payload)
        path = self._fixture_path(digest)
        path.write_text(json.dumps(scrubbed, ensure_ascii=False, indent=2,
                                   sort_keys=True), encoding="utf-8")
        return path

    def _load_fixture(self, digest: str) -> dict:
        path = self._fixture_path(digest)
        if not path.exists():
            raise FixtureNotFound(
                f"fixture {digest}.json not found (mode=replay, no live fallback)"
            )
        return json.loads(path.read_text(encoding="utf-8"))

    # -- retry ----------------------------------------------------------
    def _with_retry(self, func, *, label: str):
        last: BaseException | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return func()
            except Exception as exc:  # noqa: BLE001 - classify by status below
                status = _status_of(exc)
                if status not in RETRYABLE_STATUS or attempt >= self.max_retries:
                    raise
                delay = _retry_after_seconds(exc)
                if delay is None:
                    delay = 0.5 * (2 ** attempt) + random.uniform(0, 0.1)
                time.sleep(delay)
                last = exc
        if last is not None:
            raise last
        raise RuntimeError(f"{label} failed without an exception")

    # -- low-level API calls -------------------------------------------
    def models_list(self) -> dict:
        endpoint = "models.list"
        digest = request_hash("", endpoint, {}, {"op": "list"})
        if self.mode == "replay":
            fixture = self._load_fixture(digest)
            return fixture["response"]
        self.check_budget(0.0)
        client = self._live_transport()
        started = time.perf_counter()

        def _call():
            return client.models.list()

        response = self._with_retry(_call, label=endpoint)
        latency_ms = int((time.perf_counter() - started) * 1000)
        body = _to_jsonable(response)
        usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
                 "reasoning_tokens": 0, "video_frames_processed": 0,
                 "total_tokens": 0}
        self._record(model="", endpoint=endpoint, usage=usage, image_count=0,
                     frame_count=0, cost_usd=0.0, latency_ms=latency_ms)
        if self.mode == "record":
            self._save_fixture(digest, {
                "request": {"endpoint": endpoint, "model": "",
                            "params": {}, "payload": {"op": "list"}},
                "response": body, "usage": usage, "latency_ms": latency_ms,
            })
        return body

    def files_create(self, file_bytes: bytes, filename: str,
                     purpose: str = "user_data") -> dict:
        endpoint = "files.create"
        content_hash = _sha256_hex(bytes(file_bytes))
        params = {"filename": filename, "purpose": purpose,
                  "size": len(file_bytes), "sha256": content_hash}
        digest = request_hash("", endpoint, params, {"sha256": content_hash})
        if self.mode == "replay":
            fixture = self._load_fixture(digest)
            return fixture["response"]
        self.check_budget(0.0)
        client = self._live_transport()
        started = time.perf_counter()

        def _call():
            return client.files.create(file=(filename, bytes(file_bytes)),
                                       purpose=purpose)

        response = self._with_retry(_call, label=endpoint)
        latency_ms = int((time.perf_counter() - started) * 1000)
        body = _to_jsonable(response)
        usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
                 "reasoning_tokens": 0, "video_frames_processed": 0,
                 "total_tokens": 0}
        self._record(model="", endpoint=endpoint, usage=usage, image_count=0,
                     frame_count=0, cost_usd=0.0, latency_ms=latency_ms)
        if self.mode == "record":
            self._save_fixture(digest, {
                "request": {"endpoint": endpoint, "model": "", "params": params,
                            "payload": {"sha256": content_hash}},
                "response": body, "usage": usage, "latency_ms": latency_ms,
            })
        return body

    def responses_create(
        self,
        model: str,
        payload_input: Any,
        *,
        max_output_tokens: int | None = None,
        text_format: dict | None = None,
        reasoning: dict | None = None,
        store: bool = False,
        image_count: int = 0,
        frame_count: int = 0,
        stream: bool = False,
        extra: dict | None = None,
    ) -> dict:
        """Create a Responses API response. Returns JSON-able response dict.

        For Spark models ``max_output_tokens`` is required (budget estimate).
        For SAM the cost comes from image/frame counts instead.
        """
        self._reject_contributor(model)
        endpoint = "responses"
        is_sam = str(model).startswith("sam-")
        if not is_sam and max_output_tokens is None:
            raise ValueError("max_output_tokens is required")
        params: dict[str, Any] = {"store": bool(store)}
        if max_output_tokens is not None:
            params["max_output_tokens"] = int(max_output_tokens)
        if text_format is not None:
            params["text_format"] = text_format
        if reasoning is not None:
            params["reasoning"] = reasoning
        if stream:
            params["stream"] = True
        if extra:
            params.update(extra)
        digest = request_hash(model, endpoint, params, payload_input)
        if self.mode == "replay":
            fixture = self._load_fixture(digest)
            return fixture["response"]

        inferred_images = image_count or _count_blocks(payload_input, "input_image")
        inferred_images += _count_blocks(payload_input, "input_file")
        inferred_frames = frame_count or 0
        if is_sam:
            if inferred_frames or _count_blocks(payload_input, "input_video"):
                expected = pricing.sam_video_cost_usd(inferred_frames or 50)
            else:
                expected = pricing.sam_image_cost_usd(max(1, inferred_images or 1))
        else:
            input_est = estimate_input_tokens(payload_input)
            expected = pricing.estimate_spark_cost_usd(
                input_est, int(max_output_tokens or 0))
        self.check_budget(expected)

        client = self._live_transport()
        started = time.perf_counter()
        kwargs: dict[str, Any] = {"model": model, "input": payload_input,
                                  "store": bool(store)}
        if max_output_tokens is not None:
            kwargs["max_output_tokens"] = int(max_output_tokens)
        if text_format is not None:
            kwargs["text"] = {"format": text_format}
        if reasoning is not None:
            kwargs["reasoning"] = reasoning
        if extra:
            kwargs.update(extra)

        if stream:
            response, stream_text = self._stream_collect(client, kwargs)
            latency_ms = int((time.perf_counter() - started) * 1000)
            body = _to_jsonable(response)
            if stream_text and not extract_output_text(body):
                body["output_text"] = stream_text
        else:
            def _call():
                return client.responses.create(**kwargs)

            response = self._with_retry(_call, label=endpoint)
            latency_ms = int((time.perf_counter() - started) * 1000)
            body = _to_jsonable(response)

        usage = extract_usage(body)
        billed_frames = int(usage.get("video_frames_processed", 0) or 0)
        if is_sam:
            if billed_frames or inferred_frames or _count_blocks(payload_input,
                                                                 "input_video"):
                cost = pricing.sam_video_cost_usd(
                    billed_frames or inferred_frames or 50)
                final_frames = billed_frames or inferred_frames or 50
                final_images = 0
            else:
                final_images = max(1, inferred_images or 1)
                cost = pricing.sam_image_cost_usd(final_images)
                final_frames = 0
        else:
            cost = pricing.spark_cost_usd(
                usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                usage.get("cached_input_tokens", 0),
                usage.get("reasoning_tokens", 0))
            final_images = inferred_images
            final_frames = billed_frames or inferred_frames
        self._record(model=model, endpoint=endpoint, usage=usage,
                     image_count=final_images, frame_count=final_frames,
                     cost_usd=cost, latency_ms=latency_ms)
        if self.mode == "record":
            self._save_fixture(digest, {
                "request": {"endpoint": endpoint, "model": model,
                            "params": _to_jsonable(canonicalize_for_hash(params)),
                            "payload": _to_jsonable(
                                canonicalize_for_hash(payload_input))},
                "response": body, "usage": usage, "latency_ms": latency_ms,
            })
        return body

    def _stream_collect(self, client: Any, kwargs: dict) -> tuple[Any, str]:
        texts: list[str] = []
        final_response: Any = None

        def _run():
            nonlocal final_response
            streamer = None
            stream_fn = getattr(getattr(client, "responses", None), "stream", None)
            if callable(stream_fn):
                streamer = stream_fn(**kwargs)
            else:
                create_fn = getattr(getattr(client, "responses", None), "create")
                return create_fn(**{**kwargs, "stream": True})
            return streamer

        def _consume():
            nonlocal final_response
            streamer = self._with_retry(_run, label="responses.stream")
            if hasattr(streamer, "__enter__"):
                with streamer as active:
                    for event in active:
                        _handle_event(event)
                        resp = getattr(event, "response", None)
                        if resp is not None:
                            final_response = resp
                    final = getattr(active, "get_final_response", None)
                    if callable(final):
                        try:
                            final_response = final()
                        except Exception:
                            pass
            else:
                for event in streamer:
                    _handle_event(event)
                    resp = getattr(event, "response", None)
                    if isinstance(event, dict) and event.get("type") in (
                            "response.completed", "response.done"):
                        final_response = event.get("response", final_response)
                    if resp is not None:
                        final_response = resp
            return final_response

        def _handle_event(event: Any) -> None:
            if isinstance(event, dict):
                etype = event.get("type", "")
                if etype in ("response.output_text.delta", "response.output_text.done",
                             "response.content_part.done"):
                    delta = event.get("delta") or event.get("text") or ""
                    if isinstance(delta, str):
                        texts.append(delta)
                    part = event.get("part") or {}
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        texts.append(part["text"])
                return
            etype = getattr(event, "type", "") or ""
            if etype in ("response.output_text.delta", "response.output_text.done",
                         "response.content_part.done"):
                for attr in ("delta", "text"):
                    val = getattr(event, attr, None)
                    if isinstance(val, str) and val:
                        texts.append(val)
                        break
                part = getattr(event, "part", None)
                if part is not None:
                    val = getattr(part, "text", None)
                    if isinstance(val, str) and val:
                        texts.append(val)

        final_response = _consume()
        return (final_response or {"output_text": "".join(texts),
                                   "usage": {}}, "".join(texts))

    def images_generate(
        self,
        model: str,
        prompt: str,
        *,
        size: str | None = None,
        n: int = 1,
        response_format: str = "b64_json",
    ) -> dict:
        self._reject_contributor(model)
        endpoint = "images.generate"
        params = {"size": size or "auto", "n": int(n),
                  "response_format": response_format}
        digest = request_hash(model, endpoint, params, {"prompt": prompt})
        if self.mode == "replay":
            fixture = self._load_fixture(digest)
            return fixture["response"]
        expected = pricing.image_cost_usd(int(n))
        self.check_budget(expected)
        client = self._live_transport()
        started = time.perf_counter()
        kwargs: dict[str, Any] = {"model": model, "prompt": prompt, "n": int(n)}
        if size:
            kwargs["size"] = size
        if response_format:
            kwargs["response_format"] = response_format

        def _call():
            return client.images.generate(**kwargs)

        response = self._with_retry(_call, label=endpoint)
        latency_ms = int((time.perf_counter() - started) * 1000)
        body = _to_jsonable(response)
        data = body.get("data", []) if isinstance(body, dict) else []
        count = len(data) if isinstance(data, list) and data else int(n)
        usage = extract_usage(body)
        cost = pricing.image_cost_usd(count)
        self._record(model=model, endpoint=endpoint, usage=usage, image_count=count,
                     frame_count=0, cost_usd=cost, latency_ms=latency_ms)
        if self.mode == "record":
            # Redact image bytes from the fixture summary is unnecessary;
            # b64 bytes stay in "response" for replay use, never in "request".
            self._save_fixture(digest, {
                "request": {"endpoint": endpoint, "model": model, "params": params,
                            "payload": {"prompt": prompt,
                                        "prompt_sha256": _sha256_hex(
                                            prompt.encode("utf-8"))}},
                "response": body, "usage": usage, "latency_ms": latency_ms,
            })
        return body
