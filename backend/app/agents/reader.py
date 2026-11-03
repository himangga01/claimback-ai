"""Reader worker (Spark): verbatim reading with norm1000 boxes.

M4b additions: overlap tiling for tall images (3a), square padding
variant, keyframe video reading (item 4), and out-of-range box flagging
(no more silent clamping). Single-tile images use the original bytes, so
square evidence behaves exactly as before.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, field_validator

from app.agents import deps
from app.agents.base import AgentSchemaError
from app.agents.spark import field_summary, load_prompt, run_spark_json

PROMPT_VERSION = "reader.v2"
PROMPT_FILE = "reader.v2.md"
MAX_OUTPUT_TOKENS = 4000
REASONING_EFFORT = "low"

# M4b eval decision (reports/M4b.md): 1.2 and 1.3 both clear 95% value
# match, so the faster p95 wins (8.8s vs 33.2s). Env READER_MODEL still
# wins. deps.py is owned by another workstream, so the default lives in
# this module; the coordinator displays output["model"], which always
# carries this value.
READER_DEFAULT_MODEL = "muse-spark-1.2"

# Tiling (M4b 3a): split when h/w exceeds this; tiles overlap by
# TILE_OVERLAP and each tile keeps h/w <= TILE_MAX_ASPECT. Eval result:
# near-square tiles (1.0) beat 1.25/1.5/whole/pad on truth-box IoU
# (65.2% vs 45.8/25.4/14.9/3.0 on tall evidence, value 100% kept).
TILE_MAX_ASPECT = 1.0
TILE_OVERLAP = 0.10

# Merge: same (kind, text) boxes with IoU above this count as one item.
MERGE_IOU = 0.3
# Video merge: a box counts as fully visible this far (px) from frame edges.
FULLY_VISIBLE_MARGIN = 4

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


def default_model() -> str:
    """Effective reader model (env READER_MODEL wins, else M4b default)."""
    return ((os.environ.get("READER_MODEL") or "").strip()
            or READER_DEFAULT_MODEL)


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


def _iou(a: List[float], b: List[float]) -> float:
    """Intersection over union for [x1, y1, x2, y2] boxes."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0.0 else 0.0


def convert_box(
    norm4: List[float], width: int, height: int
) -> Tuple[List[int], bool]:
    """norm1000 box -> pixel box in a width x height image.

    Returns (box, warned). In-range boxes convert exactly as before.
    Out-of-range boxes are NOT clamped (M4b 3a): they convert raw (and
    ordered) so downstream sees the real values, with warned=True.
    """
    raw = [float(v) for v in norm4]
    warned = any(v < 0.0 or v > 1000.0 for v in raw)
    if warned:
        x1 = raw[0] / 1000.0 * width
        y1 = raw[1] / 1000.0 * height
        x2 = raw[2] / 1000.0 * width
        y2 = raw[3] / 1000.0 * height
        return ([int(round(min(x1, x2))), int(round(min(y1, y2))),
                 int(round(max(x1, x2))), int(round(max(y1, y2)))], True)
    clamped = [min(1000.0, max(0.0, v)) for v in raw]
    box = deps.Box(
        x1=clamped[0], y1=clamped[1], x2=clamped[2], y2=clamped[3],
        system="norm1000", ref_w=width, ref_h=height,
    )
    return (deps.box_to_pixels(box, width, height), False)


def _pixel_item(
    item: ModelReadingItem, ref_size: Tuple[int, int],
    offset: Tuple[float, float] = (0.0, 0.0),
    tile_size: Optional[Tuple[int, int]] = None,
) -> Dict[str, Any]:
    """One model item -> pixel item in original-image coordinates.

    ``offset``/``tile_size`` map tile-fraction boxes back to the original
    image: orig = offset + frac * tile_size. Whole images use offset
    (0, 0) and tile_size == ref_size.
    """
    width, height = int(ref_size[0]), int(ref_size[1])
    tw, th = tile_size if tile_size is not None else (width, height)
    ox, oy = float(offset[0]), float(offset[1])
    raw = [float(v) for v in item.box]
    warned = any(v < 0.0 or v > 1000.0 for v in raw)
    if warned:
        x1 = ox + raw[0] / 1000.0 * tw
        y1 = oy + raw[1] / 1000.0 * th
        x2 = ox + raw[2] / 1000.0 * tw
        y2 = oy + raw[3] / 1000.0 * th
        pixels = [int(round(min(x1, x2))), int(round(min(y1, y2))),
                  int(round(max(x1, x2))), int(round(max(y1, y2)))]
    else:
        clamped = [min(1000.0, max(0.0, v)) for v in raw]
        x1 = ox + clamped[0] / 1000.0 * tw
        y1 = oy + clamped[1] / 1000.0 * th
        x2 = ox + clamped[2] / 1000.0 * tw
        y2 = oy + clamped[3] / 1000.0 * th
        pixels = [int(round(x1)), int(round(y1)),
                  int(round(x2)), int(round(y2))]
        pixels[0], pixels[2] = min(pixels[0], pixels[2]), max(pixels[0], pixels[2])
        pixels[1], pixels[3] = min(pixels[1], pixels[3]), max(pixels[1], pixels[3])
    normalized = item.normalized
    if item.kind not in ("amount", "date", "phone", "account_number"):
        normalized = None
    out: Dict[str, Any] = {
        "kind": item.kind,
        "text_verbatim": item.text_verbatim,
        "normalized": normalized,
        "box": {"x1": pixels[0], "y1": pixels[1], "x2": pixels[2], "y2": pixels[3],
                "system": "pixel", "ref_w": width, "ref_h": height},
        "speaker": item.speaker,
        "side": item.side,
        "confidence": item.confidence,
    }
    if warned:
        # Not clamped: flag it so redaction treats it as low-confidence
        # (M4a preview "needs check"; preserved to the API in INT-3).
        out["box_warning"] = "out_of_range"
    return out


def model_items_to_pixels(
    items: List[ModelReadingItem], ref_size: Tuple[int, int]
) -> List[Dict[str, Any]]:
    """norm1000 model boxes -> preview-pixel items (item_id recoded later)."""
    return [_pixel_item(item, ref_size) for item in items]


def tile_items_to_pixels(
    items: List[ModelReadingItem],
    tile: Tuple[int, int, int, int],
    ref_size: Tuple[int, int],
    tile_pixels: Optional[Tuple[int, int]] = None,
) -> List[Dict[str, Any]]:
    """Tile-fraction boxes -> original-image pixel items.

    ``tile`` is the (x0, y0, x1, y1) crop in original pixels;
    ``tile_pixels`` is the pixel size the model saw (defaults to the crop
    size; square padding passes the padded side for both axes).
    """
    x0, y0, x1, y1 = (int(v) for v in tile)
    size = tile_pixels if tile_pixels is not None else (x1 - x0, y1 - y0)
    return [_pixel_item(item, ref_size, (x0, y0), size) for item in items]


def plan_tiles(
    width: int, height: int,
    max_aspect: float = TILE_MAX_ASPECT,
    overlap: float = TILE_OVERLAP,
) -> List[Tuple[int, int, int, int]]:
    """Vertical overlapping tiles covering a width x height image (M4b 3a).

    Images with h/w <= max_aspect read whole (one tile). Taller images
    split into evenly spaced full-width strips, each with h/w <=
    max_aspect and at least the given fractional overlap between
    neighbors (even spacing avoids a near-duplicate last tile).
    """
    import math

    width, height = int(width), int(height)
    if width <= 0 or height <= 0:
        raise ValueError(f"bad image size: {width}x{height}")
    if height / width <= max_aspect:
        return [(0, 0, width, height)]
    tile_h = max(1, int(width * max_aspect))
    overlap = min(max(float(overlap), 0.0), 0.9)
    min_overlap = tile_h * overlap
    count = max(2, int(math.ceil((height - min_overlap)
                                 / (tile_h - min_overlap))))
    if count <= 1:
        return [(0, 0, width, height)]
    tiles: List[Tuple[int, int, int, int]] = []
    for index in range(count):
        top = round(index * (height - tile_h) / (count - 1))
        tiles.append((0, top, width, top + tile_h))
    return tiles


def crop_tile_png(image_bytes: bytes, tile: Tuple[int, int, int, int]) -> bytes:
    """Crop one tile (PNG bytes, deterministic encoding)."""
    import io

    from PIL import Image

    x0, y0, x1, y1 = (int(v) for v in tile)
    with Image.open(io.BytesIO(bytes(image_bytes))) as image:
        cropped = image.crop((x0, y0, x1, y1))
        buffer = io.BytesIO()
        cropped.save(buffer, format="PNG")
        return buffer.getvalue()


def pad_to_square_png(image_bytes: bytes) -> Tuple[bytes, int]:
    """White-pad right/bottom to a square (origin unchanged, M4b 3a variant).

    Returns (png_bytes, side). Fractions of the padded square map back to
    original pixels by scale alone (no offset).
    """
    import io

    from PIL import Image

    with Image.open(io.BytesIO(bytes(image_bytes))) as image:
        width, height = int(image.width), int(image.height)
        side = max(width, height)
        if width == height:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return (buffer.getvalue(), side)
        canvas = Image.new("RGB", (side, side), (255, 255, 255))
        canvas.paste(image.convert("RGB"), (0, 0))
        buffer = io.BytesIO()
        canvas.save(buffer, format="PNG")
        return (buffer.getvalue(), side)


def merge_tile_items(
    per_tile: List[List[Dict[str, Any]]],
    tiles: List[Tuple[int, int, int, int]],
) -> List[Dict[str, Any]]:
    """Merge tile readings; boundary duplicates become one item (M4b 3a).

    Each tile read carries its own y bias, so the same item can come
    back up to ~180px apart from adjacent tiles (too far for IoU).
    Duplicates pair structurally instead: same (kind, text_verbatim)
    boxes that both touch one overlap band pair up in y order across
    the two tiles (leftovers stay). Paired boxes average: the two
    reads are independent noisy estimates, and averaging beats either
    single pick on held-out replay (reports/M4b.md). Same-tile model
    dupes merge by IoU the same way, and cut fragments
    (proper-substring text with an overlapping box) drop. Distant
    repeats are kept. Items tagged ``_tile`` use it; untagged items
    take their list index. The tag is stripped from the output.
    """
    cuts = sorted({int(top) for _, top, _, _ in tiles[1:]} |
                  {int(bottom) for _, _, _, bottom in tiles[:-1]})

    def margin(box: Dict[str, Any]) -> float:
        if not cuts:
            return float("inf")
        cy = (int(box["y1"]) + int(box["y2"])) / 2.0
        return min(abs(cy - cut) for cut in cuts)

    def shape(box: Dict[str, Any]) -> List[float]:
        return [float(box["x1"]), float(box["y1"]),
                float(box["x2"]), float(box["y2"])]

    def center_y(box: Dict[str, Any]) -> float:
        return (int(box["y1"]) + int(box["y2"])) / 2.0

    flat: List[Dict[str, Any]] = []
    for position, items in enumerate(per_tile):
        for item in items:
            item.setdefault("_tile", position)
            flat.append(item)
    # Same-tile model dupes by overlap; keep max-margin per cluster.
    groups: Dict[Tuple[str, str], List[int]] = {}
    for index, item in enumerate(flat):
        groups.setdefault((str(item.get("kind")), str(item.get("text_verbatim"))),
                          []).append(index)
    def average_into(keeper: int, absorbed: int) -> None:
        """Average absorbed's box into keeper's (paired-read calibration)."""
        keep_box = flat[keeper]["box"]
        drop_box = flat[absorbed]["box"]
        for key in ("x1", "y1", "x2", "y2"):
            keep_box[key] = int(round(
                (int(keep_box[key]) + int(drop_box[key])) / 2))
        confidences = [flat[keeper].get("confidence"),
                       flat[absorbed].get("confidence")]
        confidences = [c for c in confidences
                       if isinstance(c, (int, float))]
        if confidences:
            flat[keeper]["confidence"] = max(confidences)
        if flat[absorbed].get("box_warning") is not None:
            flat[keeper]["box_warning"] = flat[absorbed]["box_warning"]

    drop: set = set()
    for members in groups.values():
        if len(members) < 2:
            continue
        clusters: List[List[int]] = []
        for index in members:
            placed = False
            for cluster in clusters:
                if any(flat[index].get("_tile") == flat[other].get("_tile")
                       and _iou(shape(flat[index]["box"]),
                                shape(flat[other]["box"])) > MERGE_IOU
                       for other in cluster):
                    cluster.append(index)
                    placed = True
                    break
            if not placed:
                clusters.append([index])
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            keeper = max(cluster, key=lambda i: margin(flat[i]["box"]))
            boxes = [flat[i]["box"] for i in cluster]
            for key in ("x1", "y1", "x2", "y2"):
                flat[keeper]["box"][key] = int(round(
                    sum(int(box[key]) for box in boxes) / len(boxes)))
            confidences = [flat[i].get("confidence") for i in cluster]
            confidences = [c for c in confidences
                           if isinstance(c, (int, float))]
            if confidences:
                flat[keeper]["confidence"] = max(confidences)
            for index in cluster:
                if flat[index].get("box_warning") is not None:
                    flat[keeper]["box_warning"] = flat[index]["box_warning"]
                if index != keeper:
                    drop.add(index)
    # Cross-tile band pairing in y order (leftovers stay).
    bands: List[Tuple[int, int]] = []
    for left, right in zip(tiles, tiles[1:]):
        top = max(int(left[1]), int(right[1]))
        bottom = min(int(left[3]), int(right[3]))
        if bottom > top:
            bands.append((top, bottom))

    def touches(box: Dict[str, Any], band: Tuple[int, int]) -> bool:
        return int(box["y1"]) < band[1] and int(box["y2"]) > band[0]

    for members in groups.values():
        members = [i for i in members if i not in drop]
        if len(members) < 2:
            continue
        for left_no, band in enumerate(bands):
            sides: Dict[int, List[int]] = {left_no: [], left_no + 1: []}
            for index in members:
                if index in drop:
                    continue
                tile = flat[index].get("_tile")
                if tile in sides and touches(flat[index]["box"], band):
                    sides[tile].append(index)
            left = sorted(sides[left_no], key=lambda i: center_y(flat[i]["box"]))
            right = sorted(sides[left_no + 1],
                           key=lambda i: center_y(flat[i]["box"]))
            cap = min(float(band[1] - band[0]), 250.0)
            pairs: List[Tuple[int, int]] = []
            if left and right and len(left) == len(right):
                pairs = list(zip(left, right))
            else:
                remaining = list(right)
                for index in left:
                    if not remaining:
                        break
                    other = min(remaining, key=lambda j: abs(
                        center_y(flat[index]["box"])
                        - center_y(flat[j]["box"])))
                    if abs(center_y(flat[index]["box"])
                           - center_y(flat[other]["box"])) <= cap:
                        pairs.append((index, other))
                        remaining.remove(other)
            for first, second in pairs:
                keeper = (first if margin(flat[first]["box"])
                          >= margin(flat[second]["box"]) else second)
                average_into(keeper, second if keeper == first else first)
                drop.add(second if keeper == first else first)
    kept = [item for index, item in enumerate(flat) if index not in drop]
    # Cut-fragment drop: proper-substring text with an overlapping box.
    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    for item in kept:
        by_kind.setdefault(str(item.get("kind")), []).append(item)
    final: List[Dict[str, Any]] = []
    for item in kept:
        text = str(item.get("text_verbatim") or "")
        fragmented = False
        for other in by_kind[str(item.get("kind"))]:
            if other is item:
                continue
            other_text = str(other.get("text_verbatim") or "")
            if text and text != other_text and text in other_text:
                if _iou(shape(item["box"]), shape(other["box"])) > 0.1:
                    fragmented = True
                    break
        if not fragmented:
            final.append(item)
    for item in final:
        item.pop("_tile", None)
    return final


def merge_video_items(
    per_frame: List[Tuple[float, List[Dict[str, Any]]]],
    frame_size: Tuple[int, int],
) -> List[Dict[str, Any]]:
    """Merge keyframe readings into items with frame_ts (M4b item 4).

    Same (kind, text_verbatim) sightings cluster into occurrences: a new
    occurrence starts at a repeated timestamp (distinct on-screen
    instances in one frame) or after a keyframe gap with a disjoint box
    (the same text recurring later, e.g. a name label on another
    bubble). Each occurrence keeps the first keyframe where its box sits
    fully inside the frame (margin FULLY_VISIBLE_MARGIN); occurrences
    never fully visible keep their earliest ts. Output order is
    (frame_ts, y1, x1).
    """
    width, height = int(frame_size[0]), int(frame_size[1])
    margin = FULLY_VISIBLE_MARGIN

    def fully_visible(box: Dict[str, Any]) -> bool:
        return (int(box["x1"]) > margin and int(box["y1"]) > margin
                and int(box["x2"]) < width - margin
                and int(box["y2"]) < height - margin)

    def shape(box: Dict[str, Any]) -> List[float]:
        return [float(box["x1"]), float(box["y1"]),
                float(box["x2"]), float(box["y2"])]

    stamps = sorted({float(ts) for ts, _ in per_frame})
    diffs = sorted(b - a for a, b in zip(stamps, stamps[1:]) if b - a > 0)
    step = diffs[len(diffs) // 2] if diffs else 0.5
    gap = step * 1.5 + 1e-9

    groups: Dict[Tuple[str, str], List[Tuple[float, Dict[str, Any]]]] = {}
    for ts, items in per_frame:
        for item in items:
            key = (str(item.get("kind")), str(item.get("text_verbatim")))
            groups.setdefault(key, []).append((float(ts), item))
    merged: List[Dict[str, Any]] = []
    for members in groups.values():
        members.sort(key=lambda pair: pair[0])
        occurrences: List[List[Tuple[float, Dict[str, Any]]]] = []
        for ts, item in members:
            current = occurrences[-1] if occurrences else []
            split = True
            if current:
                same_frame = any(abs(ts - ots) < 1e-9 for ots, _ in current)
                recent = max(ots for ots, _ in current)
                disjoint = max(
                    _iou(shape(item["box"]), shape(other["box"]))
                    for _, other in current) < MERGE_IOU
                if not same_frame and not ((ts - recent) > gap and disjoint):
                    current.append((ts, item))
                    split = False
            if split:
                occurrences.append([(ts, item)])
        for occurrence in occurrences:
            picked = next((pair for pair in occurrence
                           if fully_visible(pair[1]["box"])), occurrence[0])
            item = dict(picked[1])
            item["frame_ts"] = round(float(picked[0]), 3)
            merged.append(item)
    merged.sort(key=lambda item: (float(item["frame_ts"]),
                                  int(item["box"]["y1"]), int(item["box"]["x1"])))
    return merged


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


def _read_raster(
    *,
    model: str,
    prompt: str,
    kind: str,
    data: bytes,
    filename: str,
    meta_mode: str,
    run_id: str,
    reasoning_effort: str = REASONING_EFFORT,
    max_output_tokens: int = MAX_OUTPUT_TOKENS,
) -> Tuple[ModelReading, Dict[str, Any]]:
    """One raster (image/PDF/tile) read with the uniform retry policy."""
    payload = build_reader_payload(prompt, kind, data, filename)
    total = {"latency_ms": 0, "attempts": 0, "tokens_in": 0,
             "tokens_out": 0, "cost_usd": 0.0}

    def _accumulate(info: Dict[str, Any]) -> None:
        total["latency_ms"] += info["latency_ms"]
        total["attempts"] += info["attempts"]
        total["tokens_in"] += info["tokens_in"]
        total["tokens_out"] += info["tokens_out"]
        total["cost_usd"] += info["cost_usd"]

    try:
        parsed, info = run_spark_json(
            model=model, payload=payload, text_format=READING_TEXT_FORMAT,
            reasoning_effort=reasoning_effort, meta_mode=meta_mode,
            run_id=run_id, max_output_tokens=max_output_tokens,
        )
    except deps.IncompleteResponse as exc:
        raise AgentSchemaError("판독 응답이 끊겼습니다(2회 시도).") from exc
    _accumulate(info)
    try:
        return (_validate(parsed), total)
    except AgentSchemaError:
        retry_prompt = (
            f"{prompt}\n\n이전 출력의 오류: {_retry_summary(parsed)}. "
            "같은 스키마로 다시 출력하세요."
        )
        payload = build_reader_payload(retry_prompt, kind, data, filename)
        try:
            parsed, info = run_spark_json(
                model=model, payload=payload, text_format=READING_TEXT_FORMAT,
                reasoning_effort=reasoning_effort, meta_mode=meta_mode,
                run_id=run_id, max_output_tokens=max_output_tokens,
            )
        except deps.IncompleteResponse as exc:
            raise AgentSchemaError("판독 응답이 끊겼습니다(2회 시도).") from exc
        _accumulate(info)
        return (_validate(parsed), total)


def run_reader(
    case_id: str,
    evidence: Dict[str, Any],
    evidence_path: Any,
    preview_size: Optional[Tuple[int, int]],
    meta_mode: str,
    run_id: str,
    *,
    model: Optional[str] = None,
    prompt_file: Optional[str] = None,
    tile_max_aspect: Optional[float] = None,
    tile_overlap: Optional[float] = None,
    square_pad: Optional[bool] = None,
    reasoning_effort: Optional[str] = None,
) -> Dict[str, Any]:
    """Read one image/pdf evidence file. Returns pixel items + accounting.

    Tall rasters split into overlap tiles (plan_tiles); PDFs with a
    preview PNG read through the preview raster (the box basis).
    Keyword overrides exist for the M4b eval; the case flow uses defaults.
    """
    kind = str(evidence.get("kind", "image"))
    filename = str(evidence.get("filename", "evidence"))
    path = Path(str(evidence_path))
    data = path.read_bytes()
    active_model = (model or "").strip() or default_model()
    active_prompt_file = prompt_file or PROMPT_FILE
    prompt = load_prompt(active_prompt_file)
    prompt_version = Path(active_prompt_file).stem
    effort = (reasoning_effort or "").strip() or REASONING_EFFORT
    max_aspect = TILE_MAX_ASPECT if tile_max_aspect is None else tile_max_aspect
    overlap = TILE_OVERLAP if tile_overlap is None else tile_overlap
    pad = bool(square_pad) if square_pad is not None else False

    # Raster to read: images as-is; pdf through its preview PNG when one
    # exists (the pixel basis of every box); otherwise the PDF itself.
    raster: Optional[bytes] = None
    ref_size = preview_size
    if kind == "image":
        raster = bytes(data)
    elif kind == "pdf":
        ex_id = str(evidence.get("ex_id", ""))
        preview = path.parent / f"{ex_id}_preview.png"
        if ex_id and preview.exists():
            raster = preview.read_bytes()
    if raster is None and kind == "pdf":
        ref_size = preview_size or _pdf_points_size(path)
    if ref_size is None:
        raise AgentSchemaError("미리보기 크기를 알 수 없어 박스를 변환할 수 없습니다.")
    width, height = int(ref_size[0]), int(ref_size[1])

    if raster is None:
        # No raster (plain PDF upload): whole-document read, as before.
        reading, total = _read_raster(
            model=active_model, prompt=prompt, kind="pdf", data=bytes(data),
            filename=filename, meta_mode=meta_mode, run_id=run_id,
            reasoning_effort=effort,
        )
        items = model_items_to_pixels(reading.items, (width, height))
        calls = 1
    else:
        pixels = bytes(raster)
        if pad and height > width:
            pixels, side = pad_to_square_png(pixels)
            tiles = [(0, 0, width, height)]
            tile_pixels: Optional[Tuple[int, int]] = (side, side)
        else:
            tiles = plan_tiles(width, height, max_aspect, overlap)
            tile_pixels = None
        per_tile: List[List[Dict[str, Any]]] = []
        total = {"latency_ms": 0, "attempts": 0, "tokens_in": 0,
                 "tokens_out": 0, "cost_usd": 0.0}
        calls = 0
        for tile in tiles:
            if len(tiles) == 1 and not pad:
                tile_bytes = pixels
            else:
                tile_bytes = crop_tile_png(pixels, tile)
            reading, info = _read_raster(
                model=active_model, prompt=prompt, kind="image",
                data=tile_bytes, filename="tile.png",
                meta_mode=meta_mode, run_id=run_id,
                reasoning_effort=effort,
            )
            calls += 1
            for key in ("latency_ms", "attempts", "tokens_in", "tokens_out",
                        "cost_usd"):
                total[key] += info[key]
            per_tile.append(tile_items_to_pixels(
                reading.items, tile, (width, height), tile_pixels))
            if pad and height > width:
                # Drop boxes whose center falls in the padded margin.
                kept = []
                for item in per_tile[-1]:
                    box = item["box"]
                    cx = (int(box["x1"]) + int(box["x2"])) / 2.0
                    if cx < width:
                        kept.append(item)
                per_tile[-1] = kept
        items = (per_tile[0] if len(per_tile) == 1
                 else merge_tile_items(per_tile, tiles))
    return {
        "items": items,
        "model": active_model,
        "prompt_version": prompt_version,
        "latency_ms": total["latency_ms"],
        "attempts": total["attempts"],
        "tokens_in": total["tokens_in"],
        "tokens_out": total["tokens_out"],
        "cost_usd": round(total["cost_usd"], 6),
        "tiles": calls,
    }


def run_video_reader(
    case_id: str,
    evidence: Dict[str, Any],
    evidence_path: Any,
    meta_mode: str,
    run_id: str,
    *,
    model: Optional[str] = None,
    prompt_file: Optional[str] = None,
    tile_max_aspect: Optional[float] = None,
    tile_overlap: Optional[float] = None,
    square_pad: Optional[bool] = None,
    reasoning_effort: Optional[str] = None,
    keyframe_threshold: Optional[int] = None,
    work_dir: Any = None,
) -> Dict[str, Any]:
    """Read one video evidence through ffmpeg keyframes (M4b item 4).

    Returns status ok + items carrying frame_ts (first fully-visible
    keyframe per bubble). Keyframes persist under ``work_dir`` (default:
    next to the video) with a manifest, so replays reuse the same bytes.
    """
    from app.agents import intake as intake_mod
    from app.agents import keyframes as keyframes_mod

    _ = case_id
    ex_id = str(evidence.get("ex_id", ""))
    path = Path(str(evidence_path))
    active_model = (model or "").strip() or default_model()
    active_prompt_file = prompt_file or PROMPT_FILE
    prompt = load_prompt(active_prompt_file)
    prompt_version = Path(active_prompt_file).stem
    effort = (reasoning_effort or "").strip() or REASONING_EFFORT
    max_aspect = TILE_MAX_ASPECT if tile_max_aspect is None else tile_max_aspect
    overlap = TILE_OVERLAP if tile_overlap is None else tile_overlap
    pad = bool(square_pad) if square_pad is not None else False
    threshold = (keyframes_mod.DEDUP_HAMMING if keyframe_threshold is None
                 else keyframe_threshold)

    try:
        stored = intake_mod.extract_video_keyframes(
            path, ex_id or "EX", dest_dir=work_dir)
    except RuntimeError as exc:
        raise AgentSchemaError(str(exc)) from exc
    frames = [{"frame_ts": entry["frame_ts"], "png": entry["png"],
               "width": entry["width"], "height": entry["height"]}
              for entry in stored]
    keyframes = keyframes_mod.select_keyframes(frames, threshold)
    if not keyframes:
        raise AgentSchemaError("영상에서 핵심 프레임을 고르지 못했습니다.")
    frame_size = (int(keyframes[0]["width"]), int(keyframes[0]["height"]))
    tiles = plan_tiles(frame_size[0], frame_size[1], max_aspect, overlap)

    per_frame: List[Tuple[float, List[Dict[str, Any]]]] = []
    total = {"latency_ms": 0, "attempts": 0, "tokens_in": 0,
             "tokens_out": 0, "cost_usd": 0.0}
    calls = 0
    for frame in keyframes:
        pixels = bytes(frame["png"])
        if pad and frame_size[1] > frame_size[0]:
            pixels, side = pad_to_square_png(pixels)
            frame_tiles = [(0, 0, frame_size[0], frame_size[1])]
            tile_pixels: Optional[Tuple[int, int]] = (side, side)
        else:
            frame_tiles = tiles
            tile_pixels = None
        frame_items: List[List[Dict[str, Any]]] = []
        for tile in frame_tiles:
            tile_bytes = pixels if len(frame_tiles) == 1 and not pad else \
                crop_tile_png(pixels, tile)
            reading, info = _read_raster(
                model=active_model, prompt=prompt, kind="image",
                data=tile_bytes, filename="frame.png",
                meta_mode=meta_mode, run_id=run_id,
                reasoning_effort=effort,
            )
            calls += 1
            for key in ("latency_ms", "attempts", "tokens_in", "tokens_out",
                        "cost_usd"):
                total[key] += info[key]
            frame_items.append(tile_items_to_pixels(
                reading.items, tile, frame_size, tile_pixels))
        merged = (frame_items[0] if len(frame_items) == 1
                  else merge_tile_items(frame_items, frame_tiles))
        per_frame.append((float(frame["frame_ts"]), merged))
    return {
        "status": "ok",
        "items": merge_video_items(per_frame, frame_size),
        "model": active_model,
        "prompt_version": prompt_version,
        "keyframes": [{"frame_ts": float(frame["frame_ts"])}
                      for frame in keyframes],
        "latency_ms": total["latency_ms"],
        "attempts": total["attempts"],
        "tokens_in": total["tokens_in"],
        "tokens_out": total["tokens_out"],
        "cost_usd": round(total["cost_usd"], 6),
        "tile_calls": calls,
    }
