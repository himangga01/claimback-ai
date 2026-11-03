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
import threading
import time
import uuid
import warnings
from contextlib import contextmanager
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
RETRY_AFTER_MAX = 30.0
# Keys that must never arrive via extra: they would bypass the model guard,
# budget estimate, or request-hash parameters (M0-fix1 C2).
FORBIDDEN_EXTRA_KEYS = frozenset(
    {"model", "input", "max_output_tokens", "text", "reasoning", "stream",
     "store"}
)
# Pre-call token estimates are deliberately generous (overestimate).
# M0 evidence (2026-11-03): chat_capture.png (42KB) used ~800 input tokens
# beyond the prompt text, so 1,500 is ~1.9x. Video via file_id used 606
# tokens, so 6,000 is ~10x. PDF iou_2page.pdf (50,579 bytes, 2 pages) used
# 5,403 tokens (~2,700/page, ~0.11 tok/byte), so bytes//4 (~0.25 tok/byte)
# is ~2.3x and the 4,000 minimum exceeds 2,000/page for typical PDFs.
IMAGE_TOKEN_EST = 1500
VIDEO_TOKEN_EST = 6000
FILE_INLINE_MIN_TOKENS = 4000
FILE_BYTES_DIVISOR = 4
FILE_ID_FALLBACK_TOKENS = 12000
IMAGE_BYTES_DIVISOR = 10


class BudgetExceeded(RuntimeError):
    pass


class BudgetLedgerError(RuntimeError):
    """Ledger unreadable or corrupted: refuse the call (fail closed)."""


class FixtureNotFound(FileNotFoundError):
    pass


class MissingKeyError(RuntimeError):
    pass


class ContributorModelError(ValueError):
    pass


class IncompleteResponse(RuntimeError):
    """Response status is incomplete (e.g. max_output_tokens reached).

    The call was billed and its cost is already in the ledger. The caller
    should retry with a larger max_output_tokens. Attributes: reason.
    """

    def __init__(self, message: str, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason


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


def _data_url_bytes_estimate(value: str) -> int:
    """Estimate decoded bytes of a data: URL without full decode (over)."""
    try:
        header, _, payload = value.partition(",")
        if not payload:
            return 0
        if ";base64" in header:
            b64len = len(payload.strip())
            return max(0, (b64len * 3) // 4)
        return len(payload.encode("utf-8"))
    except Exception:
        return 0


def _estimate_text_tokens(obj: Any) -> int:
    """Text tokens: ASCII/4, non-ASCII (Korean etc.) 1 each (overestimate).

    Korean characters tokenize to ~1 token per 1-2 chars in practice, so 1
    per non-ASCII char is conservative. data: URLs and sha256: markers are
    attachment bytes, counted separately, not as text.
    """
    if isinstance(obj, str):
        if obj.startswith("data:") or obj.startswith("sha256:"):
            return 0
        ascii_chars = 0
        non_ascii = 0
        for ch in obj:
            if ord(ch) > 127:
                non_ascii += 1
            else:
                ascii_chars += 1
        return math.ceil(ascii_chars / 4) + non_ascii
    if isinstance(obj, dict):
        return sum(_estimate_text_tokens(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return sum(_estimate_text_tokens(v) for v in obj)
    return 0


def _collect_attachment_tokens(obj: Any) -> int:
    """Generous file-size-based attachment estimate (M0-fix1 C7)."""
    total = 0
    if isinstance(obj, dict):
        block_type = obj.get("type")
        if block_type == "input_image":
            url = obj.get("image_url", "")
            if isinstance(url, str) and url.startswith("data:"):
                size = _data_url_bytes_estimate(url)
                total += max(IMAGE_TOKEN_EST, size // IMAGE_BYTES_DIVISOR)
            else:
                total += IMAGE_TOKEN_EST
        elif block_type == "input_video":
            url = obj.get("video_url", "")
            if isinstance(url, str) and url.startswith("data:"):
                size = _data_url_bytes_estimate(url)
                total += max(VIDEO_TOKEN_EST, size // FILE_BYTES_DIVISOR)
            else:
                total += VIDEO_TOKEN_EST
        elif block_type == "input_file":
            data = obj.get("file_data", "")
            if isinstance(data, str) and data.startswith("data:"):
                size = _data_url_bytes_estimate(data)
                total += max(FILE_INLINE_MIN_TOKENS, size // FILE_BYTES_DIVISOR)
            else:
                # file_id reference: size unknown, assume a large PDF
                # (2.2x M0 P3 5,403 tokens).
                total += FILE_ID_FALLBACK_TOKENS
        for value in obj.values():
            if isinstance(value, (dict, list, tuple)):
                total += _collect_attachment_tokens(value)
        return total
    if isinstance(obj, (list, tuple)):
        return sum(_collect_attachment_tokens(v) for v in obj)
    return 0


def estimate_input_tokens(payload: Any) -> int:
    if not payload:
        return 1
    text_tokens = _estimate_text_tokens(payload)
    attachments = _collect_attachment_tokens(payload)
    return max(1, text_tokens + attachments)


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
            # Skip private attributes: SDK objects may carry credentials
            # (e.g. _api_key) that must never reach fixtures (M0-fix1 C11).
            public = {k: v for k, v in vars(obj).items()
                      if not str(k).startswith("_")}
            return _to_jsonable(public)
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


def _collect_file_ids(obj: Any) -> list[str]:
    """Collect file_id values from a request payload (for C12 cleanup)."""
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "file_id" and isinstance(value, str) and value:
                found.append(value)
            elif isinstance(value, (dict, list, tuple)):
                found.extend(_collect_file_ids(value))
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            found.extend(_collect_file_ids(value))
    seen: set[str] = set()
    ordered: list[str] = []
    for fid in found:
        if fid not in seen:
            seen.add(fid)
            ordered.append(fid)
    return ordered


def _check_incomplete(body: Any) -> None:
    """Raise IncompleteResponse when a Responses body is incomplete."""
    status = _get_field(body, "status", default=None)
    if status != "incomplete":
        if not (isinstance(body, dict) and body.get("status") == "incomplete"):
            return
    details = _get_field(body, "incomplete_details", default=None)
    if isinstance(details, dict):
        reason = str(details.get("reason") or "unknown")
    elif isinstance(body, dict) and isinstance(
            body.get("incomplete_details"), dict):
        reason = str(body["incomplete_details"].get("reason") or "unknown")
    else:
        reason = "unknown"
    raise IncompleteResponse(
        f"response incomplete (reason={reason}); increase max_output_tokens "
        "and retry",
        reason=reason,
    )


# -- ledger locking (M0-fix1 C8) -------------------------------------------
# Budget check + reservation must be atomic across threads and processes.
# threading.RLock guards threads in this process; a lock file
# (<ledger>.lock via O_CREAT|O_EXCL, Windows-compatible) guards processes.
_LEDGER_THREAD_LOCK = threading.RLock()
_LEDGER_FILE_STATE = threading.local()
_LOCK_TIMEOUT_S = 10.0
_LOCK_STALE_S = 30.0


def _ledger_lock_path(ledger_path: Path) -> Path:
    return Path(ledger_path).with_name(Path(ledger_path).name + ".lock")


def _acquire_file_lock(lock_path: Path) -> None:
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    deadline = time.monotonic() + _LOCK_TIMEOUT_S
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode("ascii"))
            finally:
                os.close(fd)
            return
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except OSError:
                age = 0.0
            if age > _LOCK_STALE_S:
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise BudgetLedgerError(
                    f"could not acquire ledger lock: {lock_path}"
                )
            time.sleep(0.02)
        except OSError as exc:
            raise BudgetLedgerError(
                f"could not acquire ledger lock: {exc}"
            ) from exc


def _release_file_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


@contextmanager
def _holding_ledger_lock(ledger_path: Path):
    _LEDGER_THREAD_LOCK.acquire()
    try:
        depth = int(getattr(_LEDGER_FILE_STATE, "depth", 0) or 0)
        if depth == 0:
            _acquire_file_lock(_ledger_lock_path(Path(ledger_path)))
            _LEDGER_FILE_STATE.depth = 1
            locked_here = True
        else:
            _LEDGER_FILE_STATE.depth = depth + 1
            locked_here = False
        try:
            yield
        finally:
            if locked_here:
                _LEDGER_FILE_STATE.depth = 0
                _release_file_lock(_ledger_lock_path(Path(ledger_path)))
            else:
                _LEDGER_FILE_STATE.depth = depth
    finally:
        _LEDGER_THREAD_LOCK.release()


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
        if normalized in ("live", "record") and not run_id:
            raise ValueError("run_id is required in live/record mode (C6)")
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
        if model and "-contributor" in str(model).lower():
            raise ContributorModelError(
                f"Contributor model IDs are not allowed: {model}"
            )

    @staticmethod
    def _reject_forbidden_extra(extra: dict | None) -> None:
        if not extra:
            return
        bad = sorted(set(extra) & FORBIDDEN_EXTRA_KEYS)
        if bad:
            raise ValueError(
                f"extra contains forbidden key(s): {', '.join(bad)}"
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
        # SDK retries off: _with_retry is the only retry (M0-fix1 C1).
        return OpenAI(api_key=self._require_key(), base_url=self.base_url,
                      timeout=self.timeout, max_retries=0)

    # -- ledger / budget ------------------------------------------------
    def _read_ledger_unlocked(self) -> list[dict]:
        """Read all ledger entries. Caller must hold _holding_ledger_lock."""
        if not self.ledger_path.exists():
            return []
        try:
            text = self.ledger_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BudgetLedgerError(
                f"cannot read ledger {self.ledger_path}: {exc}"
            ) from exc
        entries: list[dict] = []
        for lineno, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BudgetLedgerError(
                    f"ledger line {lineno} is not valid JSON"
                ) from exc
            if not isinstance(entry, dict) or "cost_usd" not in entry:
                raise BudgetLedgerError(
                    f"ledger line {lineno} is missing cost_usd"
                )
            try:
                float(entry.get("cost_usd") or 0.0)
            except (TypeError, ValueError) as exc:
                raise BudgetLedgerError(
                    f"ledger line {lineno} has invalid cost_usd"
                ) from exc
            if entry.get("status") == "reserved" and not entry.get(
                    "reservation_id"):
                raise BudgetLedgerError(
                    f"ledger line {lineno} is a reservation without id"
                )
            entries.append(entry)
        return entries

    @staticmethod
    def _sum_totals(entries: list[dict], run_id: str) -> tuple[float, float]:
        # Reservation lines count until their final (completed/failed) with
        # the same reservation_id is appended; then the reservation is
        # offset (excluded) and only the final counts (M0-fix1 C8).
        finalized = {e.get("reservation_id") for e in entries
                     if e.get("status") in ("completed", "failed")
                     and e.get("reservation_id")}
        run_total = 0.0
        grand_total = 0.0
        for entry in entries:
            if entry.get("status") == "reserved" and entry.get(
                    "reservation_id") in finalized:
                continue
            cost = float(entry.get("cost_usd") or 0.0)
            grand_total += cost
            if entry.get("run_id") == run_id:
                run_total += cost
        return (round(run_total, 6), round(grand_total, 6))

    def ledger_totals(self) -> tuple[float, float]:
        """Return (run_total_usd, grand_total_usd). Missing file means zeros.

        Raises BudgetLedgerError when the ledger cannot be read or any line
        is uninterpretable (M0-fix1 C3, fail closed).
        """
        with _holding_ledger_lock(self.ledger_path):
            entries = self._read_ledger_unlocked()
            return self._sum_totals(entries, self.run_id)

    def _check_budget_unlocked(self, expected_usd: float,
                               entries: list[dict]) -> None:
        run_total, grand_total = self._sum_totals(entries, self.run_id)
        expected = float(expected_usd or 0.0)
        run_cap = pricing.run_cap_usd()
        total_cap = pricing.total_cap_usd()
        if run_total + expected > run_cap:
            raise BudgetExceeded(
                f"run budget exceeded: run_id={self.run_id} "
                f"run_total=${run_total:.4f} + expected=${expected:.4f} "
                f"> ${run_cap:.2f}"
            )
        if grand_total + expected > total_cap:
            raise BudgetExceeded(
                f"total budget exceeded: total=${grand_total:.4f} "
                f"+ expected=${expected:.4f} > ${total_cap:.2f}"
            )

    def check_budget(self, expected_usd: float) -> None:
        with _holding_ledger_lock(self.ledger_path):
            entries = self._read_ledger_unlocked()
            self._check_budget_unlocked(expected_usd, entries)

    def _append_ledger_unlocked(self, entry: dict) -> None:
        """Append one JSONL line and flush. Caller must hold the lock."""
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass

    def _append_ledger(self, entry: dict) -> None:
        with _holding_ledger_lock(self.ledger_path):
            self._append_ledger_unlocked(entry)

    def _check_and_reserve_unlocked(self, expected_usd: float, model: str,
                                    endpoint: str) -> str | None:
        """Budget check + reservation append. Caller must hold the lock.

        Returns the reservation id, or None when expected <= 0 (no
        reservation needed for free calls).
        """
        entries = self._read_ledger_unlocked()
        self._check_budget_unlocked(expected_usd, entries)
        expected = round(float(expected_usd or 0.0), 6)
        if expected <= 0:
            return None
        rid = uuid.uuid4().hex
        self._append_ledger_unlocked({
            "ts": _utc_now_iso(),
            "run_id": self.run_id,
            "model": model,
            "endpoint": endpoint,
            "status": "reserved",
            "reservation_id": rid,
            "expected_usd": expected,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "image_count": 0,
            "frame_count": 0,
            "cost_usd": expected,
            "latency_ms": 0,
        })
        return rid

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
        status: str = "completed",
        reservation_id: str | None = None,
        expected_usd: float = 0.0,
    ) -> None:
        entry: dict[str, Any] = {
            "ts": _utc_now_iso(),
            "run_id": self.run_id,
            "model": model,
            "endpoint": endpoint,
            "status": status,
            "input_tokens": int(usage.get("input_tokens", 0)),
            "cached_input_tokens": int(usage.get("cached_input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
            "reasoning_tokens": int(usage.get("reasoning_tokens", 0)),
            "image_count": int(image_count),
            "frame_count": int(frame_count),
            "cost_usd": round(float(cost_usd), 6),
            "latency_ms": int(latency_ms),
        }
        if reservation_id:
            entry["reservation_id"] = reservation_id
        if expected_usd:
            entry["expected_usd"] = round(float(expected_usd), 6)
        self._append_ledger(entry)

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
        # The only retry: 429 and transient 5xx, at most max_retries
        # retries (default 3). 400 and friends are not retried (C1).
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
                else:
                    delay = min(delay, RETRY_AFTER_MAX)
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

        try:
            response = self._with_retry(_call, label=endpoint)
        except Exception:
            latency_ms = int((time.perf_counter() - started) * 1000)
            empty = {"input_tokens": 0, "cached_input_tokens": 0,
                     "output_tokens": 0, "reasoning_tokens": 0,
                     "video_frames_processed": 0, "total_tokens": 0}
            try:
                self._record(model="", endpoint=endpoint, usage=empty,
                             image_count=0, frame_count=0, cost_usd=0.0,
                             latency_ms=latency_ms, status="failed")
            except Exception:
                pass
            raise
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

        try:
            response = self._with_retry(_call, label=endpoint)
        except Exception:
            latency_ms = int((time.perf_counter() - started) * 1000)
            empty = {"input_tokens": 0, "cached_input_tokens": 0,
                     "output_tokens": 0, "reasoning_tokens": 0,
                     "video_frames_processed": 0, "total_tokens": 0}
            try:
                self._record(model="", endpoint=endpoint, usage=empty,
                             image_count=0, frame_count=0, cost_usd=0.0,
                             latency_ms=latency_ms, status="failed")
            except Exception:
                pass
            raise
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

    def files_delete(self, file_id: str) -> dict:
        """Delete an uploaded file (M0-fix1 C12). Free; warning-only by caller.

        Record mode saves the delete response as a fixture; replay replays it.
        """
        endpoint = "files.delete"
        params = {"file_id": str(file_id)}
        digest = request_hash("", endpoint, params, {"file_id": str(file_id)})
        if self.mode == "replay":
            fixture = self._load_fixture(digest)
            return fixture["response"]
        self.check_budget(0.0)
        client = self._live_transport()
        started = time.perf_counter()

        def _call():
            return client.files.delete(str(file_id))

        try:
            response = self._with_retry(_call, label=endpoint)
        except Exception:
            latency_ms = int((time.perf_counter() - started) * 1000)
            empty = {"input_tokens": 0, "cached_input_tokens": 0,
                     "output_tokens": 0, "reasoning_tokens": 0,
                     "video_frames_processed": 0, "total_tokens": 0}
            try:
                self._record(model="", endpoint=endpoint, usage=empty,
                             image_count=0, frame_count=0, cost_usd=0.0,
                             latency_ms=latency_ms, status="failed")
            except Exception:
                pass
            raise
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
                            "params": params,
                            "payload": {"file_id": str(file_id)}},
                "response": body, "usage": usage, "latency_ms": latency_ms,
            })
        return body

    def _cleanup_files_best_effort(self, payload: Any) -> None:
        if self.mode == "replay":
            return
        for file_id in _collect_file_ids(payload):
            try:
                self.files_delete(file_id)
            except Exception as exc:  # noqa: BLE001 - cleanup is warning-only
                warnings.warn(f"file delete failed for {file_id}: {exc}",
                              RuntimeWarning, stacklevel=3)

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
        Spark reading calls should use max_output_tokens >= 4,000: M0
        fixture 4051cfb1 truncated (status incomplete) at 2,000 (C13).
        For SAM the cost comes from image/frame counts instead; SAM video
        (input_video, or video sent as input_file) requires frame_count and
        is billed for at least 50 frames.
        """
        self._reject_contributor(model)
        self._reject_forbidden_extra(extra)
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
            _check_incomplete(fixture["response"])
            return fixture["response"]

        has_video_block = bool(_count_blocks(payload_input, "input_video"))
        has_file_block = bool(_count_blocks(payload_input, "input_file"))
        inferred_images = image_count or _count_blocks(payload_input, "input_image")
        inferred_images += _count_blocks(payload_input, "input_file")
        inferred_frames = int(frame_count or 0)
        is_sam_video = False
        if is_sam:
            if has_video_block or has_file_block or inferred_frames:
                is_sam_video = True
                if inferred_frames <= 0:
                    raise ValueError(
                        "frame_count is required for SAM video "
                        "(input_video or video as input_file)"
                    )
                expected = pricing.sam_video_cost_usd(
                    max(inferred_frames, pricing.SAM_VIDEO_MIN_FRAMES))
            else:
                expected = pricing.sam_image_cost_usd(
                    max(1, inferred_images or 1))
        else:
            input_est = estimate_input_tokens(payload_input)
            expected = pricing.estimate_spark_cost_usd(
                input_est, int(max_output_tokens or 0))
        with _holding_ledger_lock(self.ledger_path):
            reservation_id = self._check_and_reserve_unlocked(
                expected, model, endpoint)

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

        empty_usage = {"input_tokens": 0, "cached_input_tokens": 0,
                       "output_tokens": 0, "reasoning_tokens": 0,
                       "video_frames_processed": 0, "total_tokens": 0}

        def _fail(exc: BaseException) -> None:
            latency_ms = int((time.perf_counter() - started) * 1000)
            try:
                self._record(model=model, endpoint=endpoint, usage=empty_usage,
                             image_count=0, frame_count=0,
                             cost_usd=expected, latency_ms=latency_ms,
                             status="failed", reservation_id=reservation_id,
                             expected_usd=expected)
            except Exception:
                pass
            try:
                self._cleanup_files_best_effort(payload_input)
            except Exception:
                pass

        try:
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
        except (BudgetExceeded, BudgetLedgerError, ValueError,
                ContributorModelError, MissingKeyError):
            raise
        except Exception as exc:
            _fail(exc)
            raise

        usage = extract_usage(body)
        billed_frames = int(usage.get("video_frames_processed", 0) or 0)
        if is_sam:
            if is_sam_video or billed_frames:
                final_frames = max(billed_frames or inferred_frames or 50,
                                   pricing.SAM_VIDEO_MIN_FRAMES)
                cost = pricing.sam_video_cost_usd(final_frames)
                final_images = 0
            else:
                final_images = max(1, inferred_images or 1)
                cost = pricing.sam_image_cost_usd(final_images)
                final_frames = 0
        else:
            if int(usage.get("input_tokens", 0) or 0) <= 0:
                cost = expected
            else:
                cost = pricing.spark_cost_usd(
                    usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                    usage.get("cached_input_tokens", 0),
                    usage.get("reasoning_tokens", 0))
            final_images = inferred_images
            final_frames = billed_frames or inferred_frames
        self._record(model=model, endpoint=endpoint, usage=usage,
                     image_count=final_images, frame_count=final_frames,
                     cost_usd=cost, latency_ms=latency_ms,
                     status="completed", reservation_id=reservation_id,
                     expected_usd=expected)
        if self.mode == "record":
            self._save_fixture(digest, {
                "request": {"endpoint": endpoint, "model": model,
                            "params": _to_jsonable(canonicalize_for_hash(params)),
                            "payload": _to_jsonable(
                                canonicalize_for_hash(payload_input))},
                "response": body, "usage": usage, "latency_ms": latency_ms,
            })
        self._cleanup_files_best_effort(payload_input)
        _check_incomplete(body)
        return body

    def _stream_collect(self, client: Any, kwargs: dict) -> tuple[Any, str]:
        # Retry wraps streamer creation through __enter__ (where the real
        # request goes out) and event consumption (M0-fix1 C5). Failures
        # propagate to responses_create, which records a failed ledger line.
        texts: list[str] = []

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

        def _attempt():
            texts.clear()
            final_response: Any = None
            stream_fn = getattr(getattr(client, "responses", None), "stream", None)
            if callable(stream_fn):
                streamer = stream_fn(**kwargs)
            else:
                create_fn = getattr(getattr(client, "responses", None), "create")
                streamer = create_fn(**{**kwargs, "stream": True})
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

        final_response = self._with_retry(_attempt, label="responses.stream")
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
        with _holding_ledger_lock(self.ledger_path):
            reservation_id = self._check_and_reserve_unlocked(
                expected, model, endpoint)
        client = self._live_transport()
        started = time.perf_counter()
        kwargs: dict[str, Any] = {"model": model, "prompt": prompt, "n": int(n)}
        if size:
            kwargs["size"] = size
        if response_format:
            kwargs["response_format"] = response_format

        def _call():
            return client.images.generate(**kwargs)

        try:
            response = self._with_retry(_call, label=endpoint)
        except Exception:
            latency_ms = int((time.perf_counter() - started) * 1000)
            empty = {"input_tokens": 0, "cached_input_tokens": 0,
                     "output_tokens": 0, "reasoning_tokens": 0,
                     "video_frames_processed": 0, "total_tokens": 0}
            try:
                self._record(model=model, endpoint=endpoint, usage=empty,
                             image_count=0, frame_count=0, cost_usd=expected,
                             latency_ms=latency_ms, status="failed",
                             reservation_id=reservation_id,
                             expected_usd=expected)
            except Exception:
                pass
            raise
        latency_ms = int((time.perf_counter() - started) * 1000)
        body = _to_jsonable(response)
        data = body.get("data", []) if isinstance(body, dict) else []
        count = len(data) if isinstance(data, list) and data else int(n)
        usage = extract_usage(body)
        # Flat per image; usage tokens are reference only (pricing page).
        cost = pricing.image_cost_usd(count)
        self._record(model=model, endpoint=endpoint, usage=usage, image_count=count,
                     frame_count=0, cost_usd=cost, latency_ms=latency_ms,
                     status="completed", reservation_id=reservation_id,
                     expected_usd=expected)
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
