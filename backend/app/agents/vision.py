"""Vision worker (SAM 3.1): noun segmentation + box retry for signatures."""

from __future__ import annotations

import base64
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.agents import deps
from app.agents.spark import load_prompt
from app.services.redaction import is_dark_pixel

MODEL = "sam-3.1"
PROMPT_VERSION = "sam_nouns.v1"
PROMPT_FILE = "sam_nouns.v1.md"

# L7: the SAM parser validates every mask during push() by decoding its full
# raster (pure Python), then save_mask_png decoded it again. Decode once and
# reuse: the validation decode populates this cache for the later save.
_MASK_RASTER_CACHE: "OrderedDict[Tuple[Any, ...], bytes]" = OrderedDict()
_MASK_RASTER_LOCK = threading.Lock()
_MASK_RASTER_MAX = 512
_MASK_DECODE_ORIGINAL: Any = None


def _mask_cache_key(mask: Any) -> Tuple[Any, ...]:
    return (getattr(mask, "encoding", None),
            int(getattr(mask, "width", 0) or 0),
            int(getattr(mask, "height", 0) or 0),
            getattr(mask, "payload", None))


def _cached_decode_mask(mask: Any) -> bytes:
    """decode_mask_to_raster with a bounded memo (successes only)."""
    global _MASK_DECODE_ORIGINAL
    if _MASK_DECODE_ORIGINAL is None:  # pragma: no cover - installed below
        from meta_sam_parser import decode_mask_to_raster as _impl

        _MASK_DECODE_ORIGINAL = _impl
    key = _mask_cache_key(mask)
    with _MASK_RASTER_LOCK:
        hit = _MASK_RASTER_CACHE.get(key)
        if hit is not None:
            _MASK_RASTER_CACHE.move_to_end(key)
            return hit
    raster = bytes(_MASK_DECODE_ORIGINAL(mask))
    with _MASK_RASTER_LOCK:
        _MASK_RASTER_CACHE[key] = raster
        _MASK_RASTER_CACHE.move_to_end(key)
        while len(_MASK_RASTER_CACHE) > _MASK_RASTER_MAX:
            _MASK_RASTER_CACHE.popitem(last=False)
    return raster


def _install_mask_cache() -> None:
    """Route the parser's validation decode through the shared cache."""
    global _MASK_DECODE_ORIGINAL
    if _MASK_DECODE_ORIGINAL is not None:
        return
    try:
        from meta_sam_parser import decode_mask_to_raster as _impl
        import meta_sam_parser._segmentation as _segmentation
    except Exception:
        return
    _MASK_DECODE_ORIGINAL = _impl
    try:
        _segmentation.decode_mask_to_raster = _cached_decode_mask
    except Exception:
        pass


_install_mask_cache()

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


class VisionParseError(ValueError):
    """SAM output could not be parsed (an error, never 'not found')."""


def load_nouns() -> List[Tuple[str, str]]:
    """Noun phrases and contract targets from the prompts file."""
    text = load_prompt(PROMPT_FILE)
    pairs: List[Tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        body = stripped[2:].strip()
        if "->" not in body:
            continue
        noun, _, target = body.partition("->")
        noun = noun.strip()
        target = target.strip()
        if noun and target:
            pairs.append((noun, target))
    if not pairs:
        raise VisionParseError("SAM noun list is empty")
    return pairs


def build_sam_payload(
    prompt_text: str, image_bytes: bytes, filename: str
) -> List[Dict[str, Any]]:
    """Request payload: prompt text + inline image (no case metadata)."""
    suffix = Path(filename or "").suffix.lower()
    mime = _IMAGE_MIME.get(suffix, "image/png")
    encoded = base64.b64encode(bytes(image_bytes)).decode("ascii")
    return [{"role": "user", "content": [
        {"type": "input_text", "text": prompt_text},
        {"type": "input_image",
         "image_url": f"data:{mime};base64,{encoded}"},
    ]}]


def _clip_box(
    x1: float, y1: float, x2: float, y2: float, ref_w: int, ref_h: int
) -> List[int]:
    ix1 = max(0, min(int(round(x1)), int(ref_w)))
    iy1 = max(0, min(int(round(y1)), int(ref_h)))
    ix2 = max(0, min(int(round(x2)), int(ref_w)))
    iy2 = max(0, min(int(round(y2)), int(ref_h)))
    if ix2 < ix1:
        ix1, ix2 = ix2, ix1
    if iy2 < iy1:
        iy1, iy2 = iy2, iy1
    return [ix1, iy1, ix2, iy2]


def parse_sam_output(
    output_text: str,
    target: str,
    source: str,
    ref_w: int,
    ref_h: int,
) -> List[Dict[str, Any]]:
    """Parse one SAM response into objects (boxes in input-image pixels).

    Empty output means 'not found' (``[]``). A non-empty output that the
    parser rejects, or diagnostics with severity ``error``, raises
    :class:`VisionParseError` (an error, never 'not found').
    """
    from meta_sam_parser import (
        CompletedOutcome,
        image_segmentation_format,
    )

    text = output_text or ""
    if not text.strip():
        return []
    fmt = image_segmentation_format()
    parser = fmt.create_parser()
    pushed = text if text.endswith("\n") else text + "\n"
    try:
        parser.push(pushed)
        finished = parser.finish(CompletedOutcome())
    except Exception as exc:
        raise VisionParseError(f"SAM 출력 해석 실패: {type(exc).__name__}") from exc
    result = finished.result
    for diag in list(getattr(result, "diagnostics", None) or []):
        if getattr(diag, "severity", "") == "error":
            raise VisionParseError(f"SAM 출력 오류: {diag.message}")
    boxes: Dict[str, Any] = {}
    masks: Dict[str, Any] = {}
    for record in list(getattr(result, "records", None) or []):
        kind = getattr(record, "kind", "")
        if kind == "box":
            boxes[str(getattr(record, "object_id", ""))] = record
        elif kind == "mask":
            masks[str(getattr(record, "object_id", ""))] = record
    if not boxes and not masks:
        return []
    if set(boxes) != set(masks):
        # SAM grammar pairs one box with one mask per object; a half
        # record means the output was cut or malformed.
        raise VisionParseError("SAM 박스와 마스크 수가 맞지 않습니다.")
    objects: List[Dict[str, Any]] = []
    for object_id in sorted(boxes, key=lambda v: (len(v), v)):
        box = boxes[object_id]
        mask = masks[object_id]
        coords = _clip_box(
            float(getattr(box, "left", 0.0)),
            float(getattr(box, "top", 0.0)),
            float(getattr(box, "right", 0.0)),
            float(getattr(box, "bottom", 0.0)),
            int(ref_w),
            int(ref_h),
        )
        score = getattr(box, "confidence", None)
        if score is None:
            score = getattr(mask, "confidence", None)
        if score is None:
            score = 1.0
        try:
            score_f = float(score)
        except (TypeError, ValueError):
            score_f = 1.0
        objects.append({
            "target": str(target),
            "source": str(source),
            "box": {
                "x1": coords[0], "y1": coords[1],
                "x2": coords[2], "y2": coords[3],
                "system": "pixel",
                "ref_w": int(ref_w), "ref_h": int(ref_h),
            },
            "score": score_f,
            "mask": getattr(mask, "mask", None),
            "mask_bounds": getattr(mask, "bounds", None),
            "object_id": str(object_id),
        })
    return objects


def save_mask_png(mask: Any, path: Path) -> Path:
    """Decode one SAM mask and save it as a PNG for display.

    Reuses the parser's validation decode via the shared cache (L7) and
    maps the 0/1 raster to black/white with a C-speed translate table.
    """
    if mask is None:
        raise VisionParseError("마스크가 없습니다.")
    try:
        raster = _cached_decode_mask(mask)
    except Exception as exc:
        raise VisionParseError(
            f"마스크 해석 실패: {type(exc).__name__}"
        ) from exc
    width = int(getattr(mask, "width", 0) or 0)
    height = int(getattr(mask, "height", 0) or 0)
    if width <= 0 or height <= 0:
        raise VisionParseError("마스크 크기가 올바르지 않습니다.")
    raw = bytes(raster)
    if len(raw) != width * height:
        raise VisionParseError("마스크 크기와 픽셀 수가 맞지 않습니다.")
    from PIL import Image

    table = bytes([0] + [255] * 255)
    image = Image.frombytes("L", (width, height), raw.translate(table))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def run_sam_call(
    prompt_text: str,
    image_bytes: bytes,
    filename: str,
    meta_mode: str,
    run_id: str,
) -> Tuple[str, Dict[str, Any]]:
    """One SAM image call. Returns (output_text, info with cost/latency)."""
    payload = build_sam_payload(prompt_text, bytes(image_bytes), filename)
    client = deps.MetaClient(mode=meta_mode, run_id=run_id)
    try:
        started = time.perf_counter()
        body = client.responses_create(MODEL, payload, image_count=1)
        latency_ms = int((time.perf_counter() - started) * 1000)
    finally:
        try:
            client.close()
        except Exception:
            pass
    text = deps.extract_output_text(body)
    cost = deps.estimate_cost_from_body(MODEL, "responses", body)
    return text, {
        "latency_ms": latency_ms,
        "cost_usd": round(float(cost or 0.0), 6),
        "body": body,
    }


def build_signature_box_prompt(
    ref_w: int, ref_h: int, readings: List[Dict[str, Any]]
) -> Optional[str]:
    """Box prompt covering signature frames near '서명' reading boxes.

    Returns None when no reading mentions a signature (no retry needed).
    One prompt string may carry several boxes (a single retry call).
    """
    from meta_sam_parser import (
        FramePrompt,
        PromptBox,
        PromptObject,
        build_object_prompt,
    )

    candidates: List[Dict[str, Any]] = []
    for item in readings or []:
        verbatim = str(item.get("text_verbatim", "") or "")
        if "서명" not in verbatim and "signature" not in verbatim.lower():
            continue
        box = item.get("box") or {}
        try:
            x1 = int(box.get("x1", 0))
            y1 = int(box.get("y1", 0))
            x2 = int(box.get("x2", 0))
            y2 = int(box.get("y2", 0))
        except (TypeError, ValueError):
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        # The ink sits right of its label: prompt the frame area only,
        # excluding the label text itself (labels would pull SAM wide).
        prompt_box = [
            max(0, x2 + 20),
            max(0, y1 - 20),
            min(int(ref_w), x2 + 600),
            min(int(ref_h), y2 + 150),
        ]
        if prompt_box[2] <= prompt_box[0] or prompt_box[3] <= prompt_box[1]:
            continue
        candidates.append({"box": prompt_box})
        if len(candidates) >= 4:
            break
    if not candidates:
        return None
    objects = []
    for index, entry in enumerate(candidates, start=1):
        x1, y1, x2, y2 = (int(v) for v in entry["box"])
        objects.append(PromptObject(id=index, prompts=[
            FramePrompt(frame=0, box=PromptBox(
                left=x1, top=y1, right=x2, bottom=y2))]))
    return build_object_prompt(size=(int(ref_w), int(ref_h)), objects=objects)


def _mask_filename(ex_id: str, target: str, source: str, index: int) -> str:
    safe_target = "".join(
        ch if ch.isalnum() else "_" for ch in str(target))
    return f"mask_{ex_id}_{safe_target}_{source}{index}.png"


def run_vision_nouns(
    case_id: str,
    ex_id: str,
    image_bytes: bytes,
    filename: str,
    ref_w: int,
    ref_h: int,
    meta_mode: str,
    run_id: str,
    files_dir: Path,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Vision-1: noun calls for one evidence. Returns (objects, accounting)."""
    nouns = load_nouns()
    objects: List[Dict[str, Any]] = []
    total_cost = 0.0
    total_latency = 0
    calls = 0
    try:
        for noun, target in nouns:
            text, info = run_sam_call(
                noun, bytes(image_bytes), filename, meta_mode, run_id)
            total_cost += float(info.get("cost_usd", 0.0) or 0.0)
            total_latency += int(info.get("latency_ms", 0) or 0)
            calls += 1
            parsed = parse_sam_output(text, target, "noun", ref_w, ref_h)
            for position, entry in enumerate(parsed):
                mask_name = _mask_filename(
                    ex_id, target, "noun", len(objects))
                mask_path = Path(files_dir) / mask_name
                save_mask_png(entry.get("mask"), mask_path)
                stored: Dict[str, Any] = {
                    "target": entry["target"],
                    "source": "noun",
                    "box": entry["box"],
                    "score": entry["score"],
                    "mask_url": f"/api/cases/{case_id}/files/{mask_name}",
                }
                if str(entry.get("target", "")) == "signature":
                    stored["ink_box"] = refine_signature_ink_box(
                        bytes(image_bytes), dict(entry.get("box") or {}),
                        int(ref_w), int(ref_h))
                    stored["ink_source"] = "pixel_rule"
                objects.append(stored)
                _ = position
    except Exception as exc:
        # L7: a mid-loop failure still spent the calls so far; carry the
        # partial accounting on the exception for the step cost.
        try:
            exc._vision_partial = {  # type: ignore[attr-defined]
                "cost_usd": round(total_cost, 6),
                "latency_ms": total_latency,
                "calls": calls,
            }
        except Exception:
            pass
        raise
    return objects, {
        "cost_usd": round(total_cost, 6),
        "latency_ms": total_latency,
        "calls": calls,
    }


def refine_signature_ink_box(
    image_bytes: bytes,
    sam_box: Dict[str, Any],
    ref_w: int,
    ref_h: int,
    threshold: float = 120.0,
) -> Dict[str, Any]:
    """Tighten a SAM signature frame to its ink via dark pixels.

    SAM box prompts return the signature frame (rectangle border), not the
    ink strokes (frame IoU vs ink ~0.2). Within the frame, ink is dark
    (brightness <120) while the gray border (~126) and paper (255) are
    brighter, so the dark-pixel bbox is the ink (IoU 0.97+ on samples).
    Red stamp pixels are not ink (L6). Falls back to the SAM box when no
    dark pixels are found.
    """
    from PIL import Image
    import io

    try:
        x1 = int(sam_box.get("x1", 0)); y1 = int(sam_box.get("y1", 0))
        x2 = int(sam_box.get("x2", 0)); y2 = int(sam_box.get("y2", 0))
    except (TypeError, ValueError):
        return dict(sam_box)
    x1 = max(0, min(x1, int(ref_w))); y1 = max(0, min(y1, int(ref_h)))
    x2 = max(0, min(x2, int(ref_w))); y2 = max(0, min(y2, int(ref_h)))
    if x2 <= x1 or y2 <= y1:
        return dict(sam_box)
    try:
        image = Image.open(io.BytesIO(bytes(image_bytes))).convert("RGB")
    except Exception:
        return dict(sam_box)
    try:
        crop = image.crop((x1, y1, x2, y2))
    except Exception:
        return dict(sam_box)
    width, height = int(crop.width), int(crop.height)
    if width <= 0 or height <= 0:
        return dict(sam_box)
    pixels = crop.load()
    minx, miny, maxx, maxy = width, height, -1, -1
    for yy in range(height):
        for xx in range(width):
            try:
                r, g, b = pixels[xx, yy][:3]
            except Exception:
                continue
            if is_dark_pixel(r, g, b, float(threshold)):
                if xx < minx:
                    minx = xx
                if yy < miny:
                    miny = yy
                if xx > maxx:
                    maxx = xx
                if yy > maxy:
                    maxy = yy
    if maxx < 0 or maxy < 0:
        return dict(sam_box)
    ink = {
        "x1": int(x1 + minx), "y1": int(y1 + miny),
        "x2": int(x1 + maxx + 1), "y2": int(y1 + maxy + 1),
        "system": "pixel", "ref_w": int(ref_w), "ref_h": int(ref_h),
    }
    # Sanity: ink must be smaller than the frame and non-trivial.
    try:
        frame_area = max(1, (x2 - x1) * (y2 - y1))
        ink_area = max(0, (ink["x2"] - ink["x1"]) * (ink["y2"] - ink["y1"]))
    except Exception:
        return dict(sam_box)
    if ink_area <= 0 or ink_area >= frame_area:
        return dict(sam_box)
    if (ink["x2"] - ink["x1"]) < 10 or (ink["y2"] - ink["y1"]) < 5:
        return dict(sam_box)
    return ink


def run_vision_signature_retry(
    case_id: str,
    ex_id: str,
    image_bytes: bytes,
    filename: str,
    ref_w: int,
    ref_h: int,
    readings: List[Dict[str, Any]],
    meta_mode: str,
    run_id: str,
    files_dir: Path,
    start_index: int = 0,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Vision-2: one box-prompt retry for a missing signature.

    Honest shape (L6): ``box`` is the SAM cell box with the SAM ``score``,
    ``ink_box`` is the pixel-rule ink box (``ink_source: "pixel_rule"``).
    The mask PNG is the SAM cell mask, aligned with ``box``.
    """
    prompt = build_signature_box_prompt(ref_w, ref_h, readings or [])
    if prompt is None:
        return [], {"cost_usd": 0.0, "latency_ms": 0, "calls": 0}
    text, info = run_sam_call(
        prompt, bytes(image_bytes), filename, meta_mode, run_id)
    spent = {
        "cost_usd": round(float(info.get("cost_usd", 0.0) or 0.0), 6),
        "latency_ms": int(info.get("latency_ms", 0) or 0),
        "calls": 1,
    }
    try:
        parsed = parse_sam_output(text, "signature", "box", ref_w, ref_h)
    except Exception as exc:
        try:
            exc._vision_partial = dict(spent)  # type: ignore[attr-defined]
        except Exception:
            pass
        raise
    objects: List[Dict[str, Any]] = []
    for entry in parsed:
        mask_name = _mask_filename(
            ex_id, "signature", "box", start_index + len(objects))
        mask_path = Path(files_dir) / mask_name
        save_mask_png(entry.get("mask"), mask_path)
        refined = refine_signature_ink_box(
            bytes(image_bytes), dict(entry.get("box") or {}),
            int(ref_w), int(ref_h))
        objects.append({
            "target": "signature",
            "source": "box",
            "box": dict(entry.get("box") or {}),
            "score": entry["score"],
            "ink_box": refined,
            "ink_source": "pixel_rule",
            "mask_url": f"/api/cases/{case_id}/files/{mask_name}",
        })
    return objects, spent
