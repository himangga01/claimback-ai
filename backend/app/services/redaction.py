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


def split_account_box(
    box: List[int], text: str
) -> Tuple[List[int], List[int]]:
    """Split an account box into (mask front, keep last 4 chars)."""
    x1, y1, x2, y2 = (int(v) for v in box)
    width = max(1, x2 - x1)
    total = max(1, len(str(text or "")))
    keep = 4 if total > 4 else 0
    if keep <= 0:
        return [x1, y1, x2, y2], [x2, y1, x2, y2]
    mask_chars = max(1, total - keep)
    split = x1 + int(round(width * mask_chars / total))
    split = _clip(split, x1 + 1, x2 - 1)
    return [x1, y1, split, y2], [split, y1, x2, y2]


def split_id_box(box: List[int], text: str) -> List[int]:
    """Mask box for the back 7 digits of an ID number."""
    x1, y1, x2, y2 = (int(v) for v in box)
    width = max(1, x2 - x1)
    total = max(1, len(str(text or "")))
    mask = 7 if total > 7 else total
    front = max(0, total - mask)
    start = x1 + int(round(width * front / total)) if total else x1
    start = _clip(start, x1, x2 - 1)
    return [start, y1, x2, y2]


def split_phone_box(box: List[int], text: str) -> List[int]:
    """Mask box for the middle 4 digits of a phone number."""
    x1, y1, x2, y2 = (int(v) for v in box)
    width = max(1, x2 - x1)
    total = max(1, len(str(text or "")))
    if total <= 4:
        return [x1, y1, x2, y2]
    front = (total - 4) // 2
    start = x1 + int(round(width * front / total))
    end = x1 + int(round(width * (front + 4) / total))
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


def burn_redacted_copy(
    original_path: Path,
    redacted_path: Path,
    mask_boxes: List[List[int]],
    label: str,
) -> Path:
    """Copy the original, paint mask boxes black, stamp the exhibit label.

    The original file is never modified. Masks use exclusive bounds
    (``[x1, y1, x2-1, y2-1]`` in Pillow) so a mask tiling a keep box never
    paints the keep edge. The label goes top-right below the margin band.
    """
    from PIL import Image, ImageDraw, ImageFont

    source = Image.open(original_path).convert("RGB")
    img_w, img_h = int(source.width), int(source.height)
    draw = ImageDraw.Draw(source)
    for box in mask_boxes or []:
        x1, y1, x2, y2 = clip_box([int(v) for v in box], img_w, img_h)
        if x2 > x1 and y2 > y1:
            draw.rectangle([x1, y1, x2 - 1, y2 - 1], fill=(0, 0, 0))
    text = str(label or "").strip()
    if text:
        try:
            size = 26 if img_w >= 1000 else 20
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
        margin = 12
        band_bottom = 40
        x = max(margin, img_w - text_w - margin - 6)
        y = min(max(band_bottom + 4, margin), max(margin, img_h - text_h - margin))
        draw.rectangle(
            [x - 6, y - 4, x + text_w + 6, y + text_h + 4], fill=(255, 255, 255))
        draw.rectangle(
            [x - 6, y - 4, x + text_w + 6, y + text_h + 4],
            outline=(24, 28, 32), width=2)
        draw.text((x, y), text, font=font, fill=(24, 28, 32))
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


def check_leak(
    original_path: Path,
    redacted_path: Path,
    plan_entries: List[Dict[str, Any]],
    expected_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Rule leak check without a re-read (P0).

    Fails when a mask is not fully black, a keep box differs, or the
    original file changed. A mask whose original area is blank white is a
    warning (likely misaligned box, needs a preview check), not a failure.
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
                        "message": "남긴 영역이 원본과 다릅니다."})
        mean, std = _gray_stats(original, mask_box)
        if mean > 250.0 and std < 10.0:
            findings.append({
                "ex_id": ex_id, "item_id": item_id,
                "message": "원본 가림 영역이 비어 있어 박스 확인이 필요합니다.",
                "warning": True})
    hard = [f for f in findings if not f.get("warning")]
    return {"status": "fail" if hard else "pass", "findings": findings}
