"""Pixel redaction: burn copies, exhibit stamps, leak checks (M4a)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.agents.case_state import REPO_ROOT

FONT_BOLD = (
    REPO_ROOT / "backend" / "app" / "templates" / "fonts"
    / "NanumGothic-Bold.ttf"
)

# L1 leak band: 2px strips just outside a mask box. Sides per kind (the keep
# side is excluded: kept glyph legitimately touches the mask there).
BAND_WIDTH = 2
BAND_DARK = 128
BAND_THRESHOLD = 5
BAND_SIDES = {
    "account_number": ("top", "bottom", "left"),
    "id_number": ("top", "bottom", "right"),
    "phone": ("top", "bottom"),
    "face": ("top", "bottom", "left", "right"),
}
LEAK_REVIEW_REASON = "가림 상자 밖에 글자가 남아 있을 수 있음"

# L4 ink geometry: a box holds real glyph only with enough ink rows and a
# wide enough span (EX6 slivers: 3-7 rows, <10px wide, fall back to the box).
MIN_GLYPH_ROWS = 8
MIN_GLYPH_WIDTH = 20
RULE_COVERAGE = 0.8


def is_red_pixel(red: int, green: int, blue: int) -> bool:
    """Red stamp pixels are not ink (L6: excluded from ink rules)."""
    return red > 150 and (red - green) > 60 and (red - blue) > 60


def is_dark_pixel(red: int, green: int, blue: int,
                  threshold: float = BAND_DARK) -> bool:
    """Glyph ink: dark and not a red stamp pixel."""
    if is_red_pixel(red, green, blue):
        return False
    return (float(red) + float(green) + float(blue)) / 3.0 < float(threshold)


def compute_pad(box_height: int) -> int:
    """Padding: 20% of box height, at least 4px."""
    try:
        height = int(box_height)
    except (TypeError, ValueError):
        height = 0
    return max(4, int(round(max(0, height) * 0.2)))


def _clip(value: int, low: int, high: int) -> int:
    return max(int(low), min(int(value), int(high)))


def clip_box(
    box: List[int], img_w: int, img_h: int
) -> List[int]:
    x1, y1, x2, y2 = (int(v) for v in box)
    x1 = _clip(x1, 0, int(img_w))
    y1 = _clip(y1, 0, int(img_h))
    x2 = _clip(x2, 0, int(img_w))
    y2 = _clip(y2, 0, int(img_h))
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return [x1, y1, x2, y2]


def _nonspace_chars(text: str) -> List[int]:
    """Char indices holding glyph (spaces map to no segment)."""
    return [i for i, ch in enumerate(str(text or "")) if not ch.isspace()]


def _digit_chars(text: str) -> List[int]:
    """Char indices holding digits (ASCII and fullwidth)."""
    return [i for i, ch in enumerate(str(text or "")) if ch.isdigit()]


def analyze_text_box(
    image: Any, box: List[int], text: str
) -> Dict[str, Any]:
    """Rule-aware ink geometry of a reading box (L4).

    ``image`` is the original preview (PIL, RGB). Returns
    ``{"segments": [...]|None, "span": (gx1, gx2)|None}``: ``segments`` maps
    each non-space char (in order) to its ink ``(x_start, x_end)`` when the
    ink-run count matches exactly (receipt cell borders are dropped as
    edge-adjacent runs only when the count then matches); ``span`` is the
    ink range for proportional fallback when substantial, else None.
    """
    empty: Dict[str, Any] = {"segments": None, "span": None}
    try:
        x1, y1, x2, y2 = (int(v) for v in box)
    except (TypeError, ValueError):
        return empty
    img_w, img_h = int(image.width), int(image.height)
    x1 = _clip(x1, 0, img_w)
    y1 = _clip(y1, 0, img_h)
    x2 = _clip(x2, 0, img_w)
    y2 = _clip(y2, 0, img_h)
    width, height = x2 - x1, y2 - y1
    if width < 2 or height < 2:
        return empty
    pixels = image.load()
    cols = [0] * width
    rows = [0] * height
    for yy in range(height):
        for xx in range(width):
            try:
                r, g, b = pixels[x1 + xx, y1 + yy][:3]
            except Exception:
                continue
            if is_dark_pixel(r, g, b):
                cols[xx] += 1
                rows[yy] += 1
    # Form rules (cell borders, underlines) span the box; glyph rows never
    # reach 80% coverage (inter-char gaps stay blank).
    rule_rows = {i for i, count in enumerate(rows)
                if count >= RULE_COVERAGE * width}
    rule_cols = {j for j, count in enumerate(cols)
                 if count >= RULE_COVERAGE * height}
    cols_excl = [0] * width
    for xx in range(width):
        total = cols[xx]
        if total:
            for i in rule_rows:
                try:
                    r, g, b = pixels[x1 + xx, y1 + i][:3]
                except Exception:
                    continue
                if is_dark_pixel(r, g, b):
                    total -= 1
        cols_excl[xx] = max(0, total)
    rows_excl = [0] * height
    for yy in range(height):
        total = rows[yy]
        if total:
            for j in rule_cols:
                try:
                    r, g, b = pixels[x1 + j, y1 + yy][:3]
                except Exception:
                    continue
                if is_dark_pixel(r, g, b):
                    total -= 1
        rows_excl[yy] = max(0, total)
    ink_rows = sum(1 for count in rows_excl if count > 0)
    runs: List[List[int]] = []
    start: Optional[int] = None
    for j, count in enumerate(cols_excl):
        if count > 0 and start is None:
            start = j
        elif count == 0 and start is not None:
            runs.append([x1 + start, x1 + j])
            start = None
    if start is not None:
        runs.append([x1 + start, x1 + width])
    if runs:
        span_all: Optional[Tuple[int, int]] = (
            runs[0][0], runs[-1][1])
    else:
        span_all = None
    substantial = (
        span_all is not None
        and ink_rows >= MIN_GLYPH_ROWS
        and (span_all[1] - span_all[0]) >= MIN_GLYPH_WIDTH
    )
    out: Dict[str, Any] = {
        "segments": None,
        "span": span_all if substantial else None,
    }
    wanted = len(_nonspace_chars(text))
    if wanted <= 0 or not runs:
        return out
    if len(runs) == wanted:
        out["segments"] = runs
        return out
    # Border artifacts (rounded cell corners) hug the box edges; drop them
    # only when the remaining count matches the text exactly.
    trimmed = [run for run in runs
               if run[0] > x1 + 1 and run[1] < x2 - 1]
    if trimmed and len(trimmed) == wanted:
        out["segments"] = trimmed
    return out


def _geom_range(
    geom: Optional[Dict[str, Any]], x1: int, x2: int
) -> Tuple[int, int]:
    if geom:
        span = geom.get("span")
        if span:
            try:
                gx1, gx2 = int(span[0]), int(span[1])
            except (TypeError, ValueError):
                pass
            else:
                if gx2 > gx1:
                    return gx1, gx2
    return int(x1), int(x2)


def _exact_seg(
    geom: Optional[Dict[str, Any]], text: str, char_index: int
) -> Optional[List[int]]:
    """Ink segment of one char, or None without exact geometry."""
    if geom is None or char_index < 0:
        return None
    segments = geom.get("segments")
    if not segments:
        return None
    order = _nonspace_chars(text)
    if char_index not in order:
        return None
    position = order.index(char_index)
    if position >= len(segments):
        return None
    return list(segments[position])


def split_account_box(
    box: List[int], text: str, geom: Optional[Dict[str, Any]] = None
) -> Tuple[List[int], List[int]]:
    """Split an account box into (mask front, keep last 4 digits).

    Exact: the split is the blank column after the last masked char
    (exclusive ink end). Fallback: char-proportional on the ink span (L4).
    """
    x1, y1, x2, y2 = (int(v) for v in box)
    text = str(text or "")
    total = max(1, len(text))
    digits = _digit_chars(text)
    if total <= 4 or len(digits) <= 4:
        return [x1, y1, x2, y2], [x2, y1, x2, y2]
    first_kept = digits[len(digits) - 4]
    last_masked = first_kept - 1
    order = _nonspace_chars(text)
    masked = [c for c in order if c <= last_masked]
    if masked:
        seg = _exact_seg(geom, text, masked[-1])
        if seg:
            split = _clip(seg[1], x1 + 1, x2 - 1)
            return [x1, y1, split, y2], [split, y1, x2, y2]
    rx1, rx2 = _geom_range(geom, x1, x2)
    split = rx1 + int(round(max(1, rx2 - rx1) * first_kept / total))
    split = _clip(split, x1 + 1, x2 - 1)
    return [x1, y1, split, y2], [split, y1, x2, y2]


def split_id_box(
    box: List[int], text: str, geom: Optional[Dict[str, Any]] = None
) -> List[int]:
    """Mask box for the back 7 digits of an ID number (front 6 kept).

    Separators right after the 6th digit (hyphen/space) stay kept.
    """
    x1, y1, x2, y2 = (int(v) for v in box)
    text = str(text or "")
    total = max(1, len(text))
    digits = _digit_chars(text)
    if len(digits) <= 7:
        return [x1, y1, x2, y2]
    kept = digits[5] + 1
    while kept < len(text) and not text[kept].isdigit():
        kept += 1
    last_kept = kept - 1
    order = _nonspace_chars(text)
    kept_chars = [c for c in order if c <= last_kept]
    if kept_chars:
        seg = _exact_seg(geom, text, kept_chars[-1])
        if seg:
            start = _clip(seg[1], x1, x2 - 1)
            return [start, y1, x2, y2]
    rx1, rx2 = _geom_range(geom, x1, x2)
    start = rx1 + int(round(max(1, rx2 - rx1) * (last_kept + 1) / total))
    start = _clip(start, x1, x2 - 1)
    return [start, y1, x2, y2]


def split_phone_box(
    box: List[int], text: str, geom: Optional[Dict[str, Any]] = None
) -> List[int]:
    """Mask box for the middle 4 digits of a phone number.

    Digit-based (L4): "+82 10-1234-5678" masks 1234, like 010 numbers.
    """
    x1, y1, x2, y2 = (int(v) for v in box)
    text = str(text or "")
    total = max(1, len(text))
    digits = _digit_chars(text)
    count = len(digits)
    if count <= 4:
        return [x1, y1, x2, y2]
    first = (count - 4) // 2
    char_first, char_last = digits[first], digits[first + 3]
    seg_first = _exact_seg(geom, text, char_first)
    seg_last = _exact_seg(geom, text, char_last)
    if seg_first and seg_last:
        start = _clip(seg_first[0], x1, x2 - 1)
        end = _clip(seg_last[1], start + 1, x2)
        return [start, y1, end, y2]
    rx1, rx2 = _geom_range(geom, x1, x2)
    width = max(1, rx2 - rx1)
    start = rx1 + int(round(width * char_first / total))
    end = rx1 + int(round(width * (char_last + 1) / total))
    start = _clip(start, x1, x2 - 1)
    end = _clip(end, start + 1, x2)
    return [start, y1, end, y2]


def pad_box(
    box: List[int],
    pad: int,
    sides: Tuple[bool, bool, bool, bool],
    img_w: int,
    img_h: int,
) -> List[int]:
    """Pad (left, top, right, bottom) selectively, then clip."""
    x1, y1, x2, y2 = (int(v) for v in box)
    left, top, right, bottom = (bool(v) for v in sides)
    if left:
        x1 -= int(pad)
    if top:
        y1 -= int(pad)
    if right:
        x2 += int(pad)
    if bottom:
        y2 += int(pad)
    return clip_box([x1, y1, x2, y2], img_w, img_h)


def _as_box_dict(
    box: List[int], ref_w: int, ref_h: int
) -> Dict[str, Any]:
    x1, y1, x2, y2 = (int(v) for v in box)
    return {
        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        "system": "pixel", "ref_w": int(ref_w), "ref_h": int(ref_h),
    }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stamp_font_size(img_w: int) -> int:
    """Exhibit stamp size scales with image width (L8, min height kept)."""
    try:
        width = int(img_w)
    except (TypeError, ValueError):
        width = 0
    return max(20, min(44, int(round(max(0, width) / 40.0))))


def rects_overlap(first: List[int], second: List[int]) -> bool:
    """True when two [x1, y1, x2, y2] boxes share any pixel."""
    try:
        ax1, ay1, ax2, ay2 = (int(v) for v in first)
        bx1, by1, bx2, by2 = (int(v) for v in second)
    except (TypeError, ValueError):
        return False
    if ax2 < ax1:
        ax1, ax2 = ax2, ax1
    if ay2 < ay1:
        ay1, ay2 = ay2, ay1
    if bx2 < bx1:
        bx1, bx2 = bx2, bx1
    if by2 < by1:
        by1, by2 = by2, by1
    return ax1 < bx2 and bx1 < ax2 and ay1 < by2 and by1 < ay2


def place_stamp_avoiding(
    img_w: int,
    img_h: int,
    text_w: int,
    text_h: int,
    avoid: List[List[int]],
) -> List[int]:
    """White stamp rect: top-right, moved down past masks/keeps (L3)."""
    margin = 12
    band_bottom = 40
    x = max(margin, int(img_w) - int(text_w) - margin - 6)
    rect_h = int(text_h) + 8
    top = min(max(band_bottom + 4, margin),
              max(margin, int(img_h) - int(text_h) - margin))
    max_top = max(margin, int(img_h) - rect_h - margin)

    def _rect(at: int) -> List[int]:
        return [x - 6, at - 4, x + int(text_w) + 6, at + int(text_h) + 4]

    for _ in range(32):
        rect = _rect(top)
        blocked = [box for box in avoid or []
                   if rects_overlap(rect, box)]
        if not blocked:
            return rect
        below = max(int(box[3]) for box in blocked) + 6
        if below <= top or top >= max_top:
            return _rect(min(top, max_top))
        top = min(below, max_top)
    return _rect(min(top, max_top))


def burn_redacted_copy(
    original_path: Path,
    redacted_path: Path,
    mask_boxes: List[List[int]],
    label: str,
    keep_boxes: Optional[List[List[int]]] = None,
) -> Path:
    """Copy the original, stamp the exhibit label, then paint masks black.

    The original file is never modified. Masks use exclusive bounds
    (``[x1, y1, x2-1, y2-1]`` in Pillow) so a mask tiling a keep box never
    paints the keep edge. The label goes top-right below the margin band,
    moved down past any mask/keep (L3), and the masks are burned last so a
    stamp can never whiten a mask and deadlock the leak check.
    """
    from PIL import Image, ImageDraw, ImageFont

    source = Image.open(original_path).convert("RGB")
    img_w, img_h = int(source.width), int(source.height)
    draw = ImageDraw.Draw(source)
    clipped_masks = [clip_box([int(v) for v in box], img_w, img_h)
                     for box in mask_boxes or []]
    clipped_masks = [box for box in clipped_masks
                     if box[2] > box[0] and box[3] > box[1]]
    clipped_keeps = [clip_box([int(v) for v in box], img_w, img_h)
                     for box in keep_boxes or []]
    clipped_keeps = [box for box in clipped_keeps
                     if box[2] > box[0] and box[3] > box[1]]
    text = str(label or "").strip()
    if text:
        try:
            size = stamp_font_size(img_w)
            if FONT_BOLD.exists():
                font = ImageFont.truetype(str(FONT_BOLD), size)
            else:
                font = ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = int(bbox[2] - bbox[0])
            text_h = int(bbox[3] - bbox[1])
        except Exception:
            text_w, text_h = (len(text) * 12, 20)
        rect = place_stamp_avoiding(
            img_w, img_h, text_w, text_h, clipped_masks + clipped_keeps)
        draw.rectangle(rect, fill=(255, 255, 255))
        draw.rectangle(rect, outline=(24, 28, 32), width=2)
        draw.text((rect[0] + 6, rect[1] + 4), text, font=font,
                  fill=(24, 28, 32))
    for box in clipped_masks:
        x1, y1, x2, y2 = box
        draw.rectangle([x1, y1, x2 - 1, y2 - 1], fill=(0, 0, 0))
    redacted_path.parent.mkdir(parents=True, exist_ok=True)
    source.save(redacted_path)
    return redacted_path


def _crop_pixels(image: Any, box: List[int]) -> bytes:
    x1, y1, x2, y2 = (int(v) for v in box)
    if x2 <= x1 or y2 <= y1:
        return b""
    return bytes(image.crop((x1, y1, x2, y2)).convert("RGB").tobytes())


def _gray_stats(image: Any, box: List[int]) -> Tuple[float, float]:
    """Mean and std of grayscale pixels inside a box (0..255)."""
    x1, y1, x2, y2 = (int(v) for v in box)
    if x2 <= x1 or y2 <= y1:
        return 255.0, 0.0
    cropped = image.crop((x1, y1, x2, y2)).convert("L")
    data = bytes(cropped.tobytes())
    if not data:
        return 255.0, 0.0
    total = sum(data)
    count = len(data)
    mean = total / count
    variance = sum((b - mean) ** 2 for b in data) / count
    return mean, variance ** 0.5


def count_band_pixels(
    image: Any, box: List[int], sides: Tuple[str, ...]
) -> Dict[str, int]:
    """Dark original pixels in 2px strips just outside a mask box (L1)."""
    try:
        x1, y1, x2, y2 = (int(v) for v in box)
    except (TypeError, ValueError):
        return {side: 0 for side in sides}
    img_w, img_h = int(image.width), int(image.height)
    pixels = image.load()
    width = BAND_WIDTH

    def _dark(x: int, y: int) -> bool:
        try:
            r, g, b = pixels[x, y][:3]
        except Exception:
            return False
        return is_dark_pixel(r, g, b)

    counts: Dict[str, int] = {}
    if "top" in sides:
        counts["top"] = sum(
            1 for yy in range(max(0, y1 - width), max(0, min(y1, img_h)))
            for xx in range(max(0, x1), min(x2, img_w)) if _dark(xx, yy))
    if "bottom" in sides:
        counts["bottom"] = sum(
            1 for yy in range(max(0, y2), min(y2 + width, img_h))
            for xx in range(max(0, x1), min(x2, img_w)) if _dark(xx, yy))
    if "left" in sides:
        counts["left"] = sum(
            1 for yy in range(max(0, y1), min(y2, img_h))
            for xx in range(max(0, x1 - width), max(0, min(x1, img_w)))
            if _dark(xx, yy))
    if "right" in sides:
        counts["right"] = sum(
            1 for yy in range(max(0, y1), min(y2, img_h))
            for xx in range(max(0, x2), min(x2 + width, img_w))
            if _dark(xx, yy))
    for side in sides:
        counts.setdefault(side, 0)
    return counts


def band_sides_for(kind: str) -> Tuple[str, ...]:
    """Band sides for a plan kind (unknown kinds: all four, fail closed)."""
    return BAND_SIDES.get(str(kind or ""),
                          ("top", "bottom", "left", "right"))


def flag_leak_bands(
    original_path: Path, plan_entries: List[Dict[str, Any]]
) -> Dict[Tuple[str, str], Dict[str, int]]:
    """Per-entry band counts for entries with mask boxes (L1).

    Keys are ``(ex_id, item_id)``; every mask entry gets its counts
    (zeros included) so the report table can show them all.
    """
    from PIL import Image

    try:
        original = Image.open(original_path).convert("RGB")
    except Exception:
        return {}
    found: Dict[Tuple[str, str], Dict[str, int]] = {}
    for entry in plan_entries or []:
        ex_id = str(entry.get("ex_id", ""))
        item_id = str(entry.get("item_id", ""))
        mask = entry.get("mask_box") or {}
        try:
            box = [int(mask.get("x1", 0)), int(mask.get("y1", 0)),
                   int(mask.get("x2", 0)), int(mask.get("y2", 0))]
        except (TypeError, ValueError):
            continue
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        found[(ex_id, item_id)] = count_band_pixels(
            original, box, band_sides_for(entry.get("kind")))
    return found


def check_leak(
    original_path: Path,
    redacted_path: Path,
    plan_entries: List[Dict[str, Any]],
    expected_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Rule leak check without a re-read (P0).

    Fails only on real failures (L3): a mask that is not fully black, or a
    changed original file. A keep box that differs is over-redaction
    (privacy-safe direction), so it is a warning that flags a preview
    check instead of a HOLD. A mask whose original area is blank white is
    likewise a warning (likely misaligned box), not a failure.
    """
    from PIL import Image

    findings: List[Dict[str, Any]] = []
    try:
        original = Image.open(original_path).convert("RGB")
    except Exception as exc:
        return {"status": "fail", "findings": [{
            "ex_id": "", "item_id": "",
            "message": f"원본을 열 수 없습니다: {type(exc).__name__}"}]}
    try:
        redacted = Image.open(redacted_path).convert("RGB")
    except Exception as exc:
        return {"status": "fail", "findings": [{
            "ex_id": "", "item_id": "",
            "message": f"사본을 열 수 없습니다: {type(exc).__name__}"}]}
    if expected_sha256:
        try:
            actual = sha256_file(original_path)
        except OSError:
            actual = ""
        if actual != str(expected_sha256):
            findings.append({
                "ex_id": "", "item_id": "",
                "message": "원본 파일이 바뀌었습니다."})
    for entry in plan_entries or []:
        ex_id = str(entry.get("ex_id", ""))
        item_id = str(entry.get("item_id", ""))
        mask = entry.get("mask_box") or {}
        try:
            mask_box = [int(mask.get("x1", 0)), int(mask.get("y1", 0)),
                        int(mask.get("x2", 0)), int(mask.get("y2", 0))]
        except (TypeError, ValueError):
            findings.append({"ex_id": ex_id, "item_id": item_id,
                             "message": "가림 박스가 올바르지 않습니다."})
            continue
        if mask_box[2] <= mask_box[0] or mask_box[3] <= mask_box[1]:
            findings.append({"ex_id": ex_id, "item_id": item_id,
                             "message": "가림 박스 크기가 0입니다."})
            continue
        red_pixels = _crop_pixels(redacted, mask_box)
        if not red_pixels or any(b != 0 for b in red_pixels):
            findings.append({"ex_id": ex_id, "item_id": item_id,
                             "message": "가린 영역에 검정이 아닌 픽셀이 있습니다."})
        keep = entry.get("keep_box")
        if isinstance(keep, dict):
            try:
                keep_box = [int(keep.get("x1", 0)), int(keep.get("y1", 0)),
                            int(keep.get("x2", 0)), int(keep.get("y2", 0))]
            except (TypeError, ValueError):
                keep_box = [0, 0, 0, 0]
            if keep_box[2] > keep_box[0] and keep_box[3] > keep_box[1]:
                before = _crop_pixels(original, keep_box)
                after = _crop_pixels(redacted, keep_box)
                if before != after:
                    findings.append({
                        "ex_id": ex_id, "item_id": item_id,
                        "message": "남긴 영역이 원본과 다릅니다.",
                        "warning": True})
        mean, std = _gray_stats(original, mask_box)
        if mean > 250.0 and std < 10.0:
            findings.append({
                "ex_id": ex_id, "item_id": item_id,
                "message": "원본 가림 영역이 비어 있어 박스 확인이 필요합니다.",
                "warning": True})
    hard = [f for f in findings if not f.get("warning")]
    return {"status": "fail" if hard else "pass", "findings": findings}
