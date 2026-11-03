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

# INT-3 1a: PII box refinement (snap to the true glyph line before
# planning). Search window around the reading box, single-line band
# limits, and the acceptance score floor.
REFINE_DY = 150
REFINE_MIN_BAND_H = 8
REFINE_MAX_BAND_H = 60
REFINE_MIN_INK_ROW = 3
REFINE_X_TOL = 20
REFINE_MIN_SCORE = 0.35


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


def build_ink_mask(image: Any) -> Any:
    """Binary ink mask (PIL "L": 255 = glyph ink, 0 = paper).

    Dark pixels below BAND_DARK count, except red stamp pixels (the
    same rule as is_dark_pixel). Pure C-speed Pillow ops so full pages
    cost milliseconds; row/column ink counts then come from bytes.
    """
    from PIL import ImageChops

    rgb = image.convert("RGB")
    ink = rgb.convert("L").point(
        lambda v: 255 if v < BAND_DARK else 0)
    red, green, blue = rgb.split()
    red_only = red.point(lambda v: 255 if v > 150 else 0)
    diff_green = ImageChops.difference(red, green).point(
        lambda v: 255 if v > 60 else 0)
    diff_blue = ImageChops.difference(red, blue).point(
        lambda v: 255 if v > 60 else 0)
    stamp = ImageChops.darker(
        ImageChops.darker(red_only, diff_green), diff_blue)
    return ImageChops.subtract(ink, stamp)


def _mask_row_counts(mask: Any) -> List[int]:
    """Ink pixels per row (C-speed bytes counting)."""
    width, height = int(mask.width), int(mask.height)
    blob = bytes(mask.tobytes())
    return [blob[row * width:(row + 1) * width].count(255)
            for row in range(height)]


def _mask_col_counts(mask: Any) -> List[int]:
    """Ink pixels per column (transpose, then C-speed row counting)."""
    from PIL import Image

    turned = mask.transpose(Image.ROTATE_90)
    width, height = int(turned.width), int(turned.height)
    blob = bytes(turned.tobytes())
    counts = [blob[row * width:(row + 1) * width].count(255)
              for row in range(height)]
    counts.reverse()  # ROTATE_90 flips the column order
    return counts


def _mask_row_span(mask: Any, row: int) -> Optional[Tuple[int, int]]:
    """(min_x, max_x) of ink in one mask row (None when blank)."""
    width = int(mask.width)
    blob = bytes(mask.tobytes())
    line = blob[row * width:(row + 1) * width]
    try:
        return (line.index(255), line.rindex(255))
    except ValueError:
        return None


def rule_rows_of_mask(mask: Any) -> set:
    """Row indexes holding table/cell border rules (INT-3 task 2).

    A rule row carries a long dense ink run (>= 40px, >= 100px wide,
    >= 85% dense); text rows always have inter-glyph gaps. Reading
    band checks skip these rows so a cell border next to the planning
    box is not mistaken for a leaked glyph.
    """
    width, height = int(mask.width), int(mask.height)
    blob = bytes(mask.tobytes())
    rules: set = set()
    for row in range(height):
        line = blob[row * width:(row + 1) * width]
        total = line.count(255)
        if total < 40:
            continue
        try:
            span = line.rindex(255) - line.index(255) + 1
        except ValueError:
            continue
        if span >= 100 and total / span >= 0.85:
            rules.add(row)
    return rules


def reading_band_counts(
    mask: Any, rule_rows: set, box: List[int]
) -> Dict[str, int]:
    """Ink pixels in 2px strips on all four sides of a box (INT-3 2).

    Unlike mask bands (which skip the keep side), every side counts:
    a glyph sitting beside the planning box means the box missed the
    line, even when the mask bands stay clean. Rule-row ink is
    skipped (cell borders are not leaked glyphs).
    """
    try:
        x1, y1, x2, y2 = (int(v) for v in box)
    except (TypeError, ValueError):
        return {"top": 0, "bottom": 0, "left": 0, "right": 0}
    width, height = int(mask.width), int(mask.height)
    blob = bytes(mask.tobytes())
    rules = set(rule_rows or ())

    def _row_count(row: int, left: int, right: int) -> int:
        if row < 0 or row >= height or row in rules:
            return 0
        left = max(0, left)
        right = min(width, right)
        if right <= left:
            return 0
        return blob[row * width + left:row * width + right].count(255)

    def _col_count(col: int, top: int, bottom: int) -> int:
        if col < 0 or col >= width:
            return 0
        total = 0
        for row in range(max(0, top), min(height, bottom)):
            if row in rules:
                continue
            if blob[row * width + col] == 255:
                total += 1
        return total

    thick = BAND_WIDTH
    counts = {
        "top": sum(_row_count(row, x1, x2)
                   for row in range(y1 - thick, y1)),
        "bottom": sum(_row_count(row, x1, x2)
                      for row in range(y2, y2 + thick)),
        "left": sum(_col_count(col, y1, y2)
                    for col in range(x1 - thick, x1)),
        "right": sum(_col_count(col, y1, y2)
                     for col in range(x2, x2 + thick)),
    }
    return counts


READING_BAND_REVIEW_REASON = "판독 상자 밖에 글자가 남아 있을 수 있음"


def _ink_bands(window: Any) -> List[Tuple[int, int]]:
    """Single text lines of a mask window as (top, bottom) row offsets.

    Rule rows (table/cell borders: long dense ink runs) are not text;
    small gaps inside a line are merged; bands outside the single-line
    height limits are dropped (INT-3 1a, shared by refine and the
    unmasked-line check).
    """
    row_counts = _mask_row_counts(window)
    is_rule = [False] * len(row_counts)
    for offset, total in enumerate(row_counts):
        if total < 40:
            continue
        span = _mask_row_span(window, offset)
        if span is None:
            continue
        width = span[1] - span[0] + 1
        if width >= 100 and total / width >= 0.85:
            is_rule[offset] = True
    bands: List[Tuple[int, int]] = []
    start: Optional[int] = None
    gap = 0
    for offset, total in enumerate(row_counts):
        ink = total >= REFINE_MIN_INK_ROW and not is_rule[offset]
        if ink:
            if start is None:
                start = offset
            gap = 0
        elif start is not None:
            gap += 1
            if gap >= 4:
                bands.append((start, offset - gap))
                start = None
                gap = 0
    if start is not None:
        bands.append((start, len(row_counts) - 1 - gap))
    return [(a, b) for (a, b) in bands
            if REFINE_MIN_BAND_H <= b - a + 1 <= REFINE_MAX_BAND_H]


def _merged_cells(
    col_counts: List[int], img_w: int, gap_min: int
) -> List[List[int]]:
    """Value cells of a line: ink columns split by wide gaps (label | value)."""
    cells: List[Tuple[int, int]] = []
    run: Optional[int] = None
    for pos, total in enumerate(col_counts):
        if total > 0 and run is None:
            run = pos
        elif total == 0 and run is not None:
            cells.append((run, pos - 1))
            run = None
    if run is not None:
        cells.append((run, img_w - 1))
    merged: List[List[int]] = []
    for cell_left, cell_right in cells:
        if merged and cell_left - merged[-1][1] - 1 < gap_min:
            merged[-1][1] = cell_right
        else:
            merged.append([cell_left, cell_right])
    return merged


def refine_pii_box(
    ink_mask: Any,
    box: List[int],
    text: str,
    label_boxes: Optional[List[List[int]]] = None,
) -> Optional[List[int]]:
    """Snap a PII reading box to the true glyph line (INT-3 1a).

    The reader's PII boxes can sit ~50-150px off the true line (M4b
    review B4-1: EX6 id IoU 0, phones 0.16/0.42), which misplaces the
    redaction masks. This searches the original-image ink around the
    box (vertical +-REFINE_DY, same text rows) for the value cell
    whose width fits the reading text's character count, preferring
    the cell right of a same-row label ("주민등록번호" etc.). Returns
    the refined [x1, y1, x2, y2] or None (keep the original box, which
    keeps the current needs_review behavior). Deterministic pixel
    rules, no model calls.
    """
    try:
        img_w, img_h = int(ink_mask.width), int(ink_mask.height)
        x1, y1, x2, y2 = (int(v) for v in box)
    except (TypeError, ValueError, AttributeError):
        return None
    chars = [ch for ch in str(text or "") if not ch.isspace()]
    count = len(chars)
    if count <= 0 or x2 <= x1 or y2 <= y1:
        return None
    box_w = x2 - x1
    box_cx = (x1 + x2) / 2.0
    box_cy = (y1 + y2) / 2.0
    char_est = max(1.0, box_w / count)
    gap_min = max(12, int(round(char_est)))
    win_top = max(0, y1 - REFINE_DY)
    win_bottom = min(img_h, y2 + REFINE_DY)
    if win_bottom - win_top < REFINE_MIN_BAND_H:
        return None
    window = ink_mask.crop((0, win_top, img_w, win_bottom))
    bands = _ink_bands(window)
    if not bands:
        return None
    best: Optional[List[int]] = None
    best_score = -1.0
    for top, bottom in bands:
        band_top = win_top + top
        band_bottom = win_top + bottom + 1  # exclusive
        band_cy = (band_top + band_bottom) / 2.0
        if abs(band_cy - box_cy) > REFINE_DY:
            continue
        strip = window.crop((0, top, img_w, bottom + 1))
        col_counts = _mask_col_counts(strip)
        merged = _merged_cells(col_counts, img_w, gap_min)
        # Beyond-band strips spot vertical cell borders (trimmed), as
        # does a full-height ink column (a border spans the whole band;
        # even a tall "1" leaves the band's sparse edge rows blank).
        above = window.crop((0, max(0, top - 8), img_w, top))
        below = window.crop((0, bottom + 1, img_w,
                             min(win_bottom - win_top, bottom + 9)))
        above_counts = _mask_col_counts(above) if above.height > 0 else [0] * img_w
        below_counts = _mask_col_counts(below) if below.height > 0 else [0] * img_w
        band_h = max(1, bottom - top + 1)

        def _is_border_col(pos: int) -> bool:
            if above_counts[pos] > 0 and below_counts[pos] > 0:
                return True
            return col_counts[pos] >= 0.9 * band_h

        for cell_left, cell_right in merged:
            left, right = cell_left, cell_right
            while left < right and _is_border_col(left):
                left += 1
            while right > left and _is_border_col(right):
                right -= 1
            cell_w = right - left + 1
            if cell_w <= 0:
                continue
            # Hard gates: same columns as the reading, sane width.
            if right < x1 - REFINE_X_TOL or left > x2 + REFINE_X_TOL:
                continue
            if not 0.4 * box_w <= cell_w <= 2.5 * box_w:
                continue
            char_w = cell_w / count
            if not 4.0 <= char_w <= 100.0:
                continue
            y_score = 1.0 - min(1.0, abs(band_cy - box_cy) / REFINE_DY)
            w_score = 1.0 - min(1.0, abs(cell_w - box_w) / box_w)
            score = 0.55 * y_score + 0.45 * w_score
            cell_cx = (left + right) / 2.0
            for label in label_boxes or []:
                try:
                    lx1, ly1, lx2, ly2 = (int(v) for v in label)
                except (TypeError, ValueError):
                    continue
                same_row = ly1 < band_bottom and ly2 > band_top
                if same_row and (lx1 + lx2) / 2.0 < cell_cx:
                    score += 0.15  # value cell right of its label
                    break
            if score > best_score:
                best_score = score
                best = [left, band_top, right + 1, band_bottom]
    if best is None or best_score < REFINE_MIN_SCORE:
        return None
    return [max(0, best[0]), max(0, best[1]),
            min(img_w, best[2]), min(img_h, best[3])]


# fix-cost bug 2: a PII mask must sit on the reading's own line. On a
# dense right-aligned receipt the reader's boxes sat 20-86px above the
# real line; the snap then masked "SAMPLE Bank" and left the account
# numbers visible while the strip checks passed. Fail closed instead:
# a snap of half a line or more, or a line whose glyphs do not spell
# the reading's digit pattern, is needs_review; the leak check also
# looks for a still-visible line with the reading's pattern.
LINE_SHIFT_MAX = 0.5
LINE_SHIFT_REVIEW_REASON = "가림 상자가 판독 위치에서 반 줄 이상 옮겨져 확인 필요"
LINE_MATCH_REVIEW_REASON = "가린 줄이 판독한 번호와 맞는지 확인할 수 없어 확인 필요"
UNMASKED_LINE_REASON = "판독한 번호와 같은 모양의 줄이 가려지지 않았을 수 있음"
LINE_MIN_DIGITS = 4


def line_shift_too_far(box: List[int], refined: List[int]) -> bool:
    """True when the snap moved a box half a text line or more."""
    try:
        bx1, by1, bx2, by2 = (int(v) for v in box)
        rx1, ry1, rx2, ry2 = (int(v) for v in refined)
    except (TypeError, ValueError):
        return True
    line_h = max(1, by2 - by1, ry2 - ry1)
    shift = abs((ry1 + ry2) / 2.0 - (by1 + by2) / 2.0)
    return shift >= LINE_SHIFT_MAX * line_h


def text_signature(text: str) -> str:
    """Glyph pattern of a reading: D per digit, S per other glyph."""
    return "".join("D" if ch.isdigit() else "S"
                   for ch in str(text or "") if not ch.isspace())


def glyph_signature(ink_mask: Any, box: List[int]) -> str:
    """Glyph pattern of the ink inside a box (D digit-like, S small, X other).

    Each ink column run is one glyph. The digit height is the most common
    run height among the taller runs; a run of that height on the common
    baseline is D (digits and capitals look alike, so the pattern, not
    one glyph, decides), a run at most 0.6 of it is S (separators), any
    other run is X (lowercase, descenders, brackets). X runs at either
    end are cell borders and are dropped.
    """
    try:
        x1, y1, x2, y2 = (int(v) for v in box)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(int(ink_mask.width), x2), min(int(ink_mask.height), y2)
    except (TypeError, ValueError, AttributeError):
        return ""
    if x2 - x1 < 2 or y2 - y1 < 2:
        return ""
    crop = ink_mask.crop((x1, y1, x2, y2))
    width, height = int(crop.width), int(crop.height)
    blob = bytes(crop.tobytes())
    cols = _mask_col_counts(crop)
    runs: List[Tuple[int, int, int]] = []
    start: Optional[int] = None
    for pos, total in enumerate(cols + [0]):
        if total > 0 and start is None:
            start = pos
        elif total == 0 and start is not None:
            rows = [row for row in range(height)
                    if 255 in blob[row * width + start:row * width + pos]]
            runs.append((start, rows[0], rows[-1]))
            start = None
    if not runs:
        return ""
    heights = [bottom - top + 1 for _, top, bottom in runs]
    tall = [h for h in heights if h >= 0.5 * max(heights)]

    def _near(a: int, b: int) -> bool:
        return abs(a - b) <= max(1, int(round(0.06 * b)))

    digit_h = max(tall, key=lambda h: (sum(1 for o in tall if _near(o, h)), h))
    tol = max(2, int(round(0.15 * digit_h)))
    bottoms = sorted(bottom for (_, top, bottom), h in zip(runs, heights)
                     if abs(h - digit_h) <= tol)
    base = bottoms[len(bottoms) // 2]
    tokens = []
    for (_, top, bottom), h in zip(runs, heights):
        if abs(h - digit_h) <= tol and abs(bottom - base) <= tol:
            tokens.append("D")
        elif h <= 0.6 * digit_h:
            tokens.append("S")
        else:
            tokens.append("X")
    return "".join(tokens).strip("X")


def signature_matches(observed: str, expected: str) -> bool:
    """Observed glyph pattern spells the reading (small edit distance).

    A separator in the reading matches an S or X run at no cost (a
    bracket is taller than a digit); anything else costs 1. Readings
    with fewer than LINE_MIN_DIGITS digits cannot be confirmed.
    """
    if expected.count("D") < LINE_MIN_DIGITS or not observed:
        return False
    prev = list(range(len(observed) + 1))
    for i, want in enumerate(expected, start=1):
        cur = [i] + [0] * len(observed)
        for j, got in enumerate(observed, start=1):
            same = got == want or (want == "S" and got == "X")
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (0 if same else 1))
        prev = cur
    return prev[-1] <= max(1, len(expected) // 8)


def pii_line_matches(ink_mask: Any, box: List[int], text: str) -> bool:
    """True when the box's ink spells the reading's digit pattern."""
    return signature_matches(glyph_signature(ink_mask, box),
                             text_signature(text))


def find_pii_lines(
    ink_mask: Any, box: List[int], text: str
) -> List[List[int]]:
    """Cells near a reading box whose ink spells the reading's pattern.

    Same window and bands as refine_pii_box (+-REFINE_DY); used by the
    leak check to spot the reading's number still visible on a line no
    mask covers.
    """
    try:
        img_w, img_h = int(ink_mask.width), int(ink_mask.height)
        x1, y1, x2, y2 = (int(v) for v in box)
    except (TypeError, ValueError, AttributeError):
        return []
    count = len(text_signature(text))
    if count <= 0 or x2 <= x1 or y2 <= y1:
        return []
    gap_min = max(12, int(round(max(1.0, (x2 - x1) / count))))
    win_top = max(0, y1 - REFINE_DY)
    win_bottom = min(img_h, y2 + REFINE_DY)
    if win_bottom - win_top < REFINE_MIN_BAND_H:
        return []
    window = ink_mask.crop((0, win_top, img_w, win_bottom))
    found: List[List[int]] = []
    for top, bottom in _ink_bands(window):
        strip = window.crop((0, top, img_w, bottom + 1))
        for left, right in _merged_cells(_mask_col_counts(strip), img_w,
                                         gap_min):
            cell = [left, win_top + top, right + 1, win_top + bottom + 1]
            if pii_line_matches(ink_mask, cell, text):
                found.append(cell)
    return found


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
    pii_items: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Rule leak check without a re-read (P0).

    Fails only on real failures (L3): a mask that is not fully black, or a
    changed original file. A keep box that differs is over-redaction
    (privacy-safe direction), so it is a warning that flags a preview
    check instead of a HOLD. A mask whose original area is blank white is
    likewise a warning (likely misaligned box), not a failure.
    fix-cost bug 2: ``pii_items`` ({ex_id, item_id, box, text} from the
    reading) are searched near their reading box; a line that spells the
    reading's number and touches no mask is a warning (preview review,
    the image stays out of the bundle until the user confirms).
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
    if pii_items:
        try:
            ink = build_ink_mask(original)
        except Exception:
            ink = None
        masks: List[List[int]] = []
        for entry in plan_entries or []:
            mask = entry.get("mask_box") or {}
            try:
                masks.append([int(mask.get("x1", 0)), int(mask.get("y1", 0)),
                              int(mask.get("x2", 0)), int(mask.get("y2", 0))])
            except (TypeError, ValueError, AttributeError):
                continue
        for item in pii_items:
            lines = (find_pii_lines(ink, list(item.get("box") or []),
                                    str(item.get("text", "")))
                     if ink is not None else [])
            if any(not any(rects_overlap(line, mask) for mask in masks)
                   for line in lines):
                findings.append({
                    "ex_id": str(item.get("ex_id", "")),
                    "item_id": str(item.get("item_id", "")),
                    "message": UNMASKED_LINE_REASON,
                    "warning": True})
    hard = [f for f in findings if not f.get("warning")]
    return {"status": "fail" if hard else "pass", "findings": findings}
