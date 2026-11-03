"""Generate M3 synthetic sample evidence and golden truth data.

Creates (deterministically - same command yields identical bytes):
  sample_evidence/kr/chat_01.png        (640x960 chat capture)
  sample_evidence/kr/chat_02_tall.png   (640x2400 tall chat capture)
  sample_evidence/kr/chat_02_scroll.mp4 (640x960 scroll video, 7s)
  sample_evidence/kr/transfer_loan.png  (loan transfer receipt)
  sample_evidence/kr/transfer_repay.png (partial repayment receipt)
  sample_evidence/kr/iou.pdf            (1-page IOU: PNG embedded full-page)
  sample_evidence/kr/iou.png            (preview of iou.pdf, 150 DPI A4 render)
  sample_evidence/en/chat_01.png
  sample_evidence/en/wire_receipt.png
  sample_evidence/en/promissory_note.pdf (+ .png preview)
  backend/tests/golden/kr_truth.json    (test-only golden answers)
  backend/tests/golden/en_truth.json    (test-only golden answers)
and updates sample_evidence/manifest.json (keeps existing text entries,
recomputes their hashes, adds new file hashes).

Evidence numbering follows specs/case-api-contract.md section 2: KR EX1..EX6
(the PDF iou.pdf is EX6 with boxes in iou.png preview pixels declared via
coord_basis; iou.png itself is not a separate evidence). EN EX1..EX3
likewise (EX3 is the PDF with coord_basis at its PNG preview).

All people, apps, banks, numbers are fictional. Every image/PDF/video frame
carries a "SAMPLE / demo" margin band recorded only as ignore_regions in
truth (never as an item). Truth boxes come straight from the drawing
coordinates (Pillow textbbox); no eyeballing. Video items reference the
first fully visible frame (frame_index, frame_ts = index / FPS) and the
per-frame scroll offsets used while rendering are recorded on the video
evidence entry.

Only Pillow, reportlab and ffmpeg are used. PNGs are saved without
metadata, the PDF uses reportlab invariant mode, ffmpeg runs with bitexact
flags and a single thread.

Run: C:\\...\\.venv\\Scripts\\python.exe tools\\make_sample_evidence.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = ROOT / "sample_evidence"
KR_DIR = SAMPLE_DIR / "kr"
EN_DIR = SAMPLE_DIR / "en"
GOLDEN_DIR = ROOT / "backend" / "tests" / "golden"
FONT_DIR = ROOT / "backend" / "app" / "templates" / "fonts"
FONT_REG = FONT_DIR / "NanumGothic-Regular.ttf"
FONT_BOLD = FONT_DIR / "NanumGothic-Bold.ttf"

# --- Fictional identities (shared across worktrees, M3 brief) ---
KR_CREDITOR = "서가온(SAMPLE)"
KR_DEBTOR = "탁나루(SAMPLE)"
EN_CREDITOR = "Avery Linden (SAMPLE)"
EN_DEBTOR = "Rowan Hale (SAMPLE)"
KR_APP = "샘플톡"
KR_BANK = "샘플은행"
EN_APP = "SampleChat"
EN_BANK = "Sample Bank"
WATERMARK = "SAMPLE / 데모용"

# Distinct fictional account endings (leading zeros, last-4 all differ).
KR_ACCT_A = "000-0000-1234"
KR_ACCT_B = "000-0000-5678"
EN_ACCT_A = "000-0000-2468"
EN_ACCT_B = "000-0000-1357"
KR_ID_NUMBER = "000000-0000000"

# --- Style (deliberately NOT mimicking real messenger/bank apps) ---
WHITE = (255, 255, 255)
INK = (24, 28, 32)
GRAY = (110, 116, 122)
BUBBLE_LEFT = (0xE9, 0xEC, 0xEF)   # received: light gray
BUBBLE_RIGHT = (0xCF, 0xEF, 0xEA)  # sent: teal
BAND_FILL = (200, 30, 30)
BAND_TEXT = (255, 255, 255)
SIG_INK = (30, 40, 130)
STAMP_RED = (200, 30, 30)
BAND_H = 36  # margin band, inside the top 40px

KINDS = ("utterance", "amount", "date", "party_name", "account_number",
         "id_number", "phone", "address", "label", "header", "watermark")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else FONT_REG
    if not path.exists():
        raise FileNotFoundError(f"missing bundled font: {path}")
    return ImageFont.truetype(str(path), size)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)  # no metadata -> deterministic


def dump_json(obj: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def draw_band(img: Image.Image) -> list[int]:
    """Top margin band with the SAMPLE mark. Returns its box."""
    w = img.size[0]
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, w, BAND_H], fill=BAND_FILL)
    fnt = font(18, bold=True)
    tw = float(draw.textlength(WATERMARK, font=fnt))
    draw.text(((w - tw) / 2, 7), WATERMARK, font=fnt, fill=BAND_TEXT)
    return [0, 0, w, BAND_H]


def wrap_words(draw: ImageDraw.ImageDraw, text: str,
               tokens: list[tuple[str, str, object]],
               fnt: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """Greedy word wrap that never breaks inside a token span.

    Token occurrences become unbreakable atoms, so every token lands whole
    on exactly one line (all tokens are far shorter than max_w).
    """
    import re

    spans: list[tuple[int, int]] = []
    cursor = 0
    for tok, _kind, _norm in tokens:
        i = text.find(tok, cursor)
        assert i >= 0, f"token missing from bubble: {tok!r}"
        spans.append((i, i + len(tok)))
        cursor = i + len(tok)
    # Words overlapping a token span merge into one unbreakable atom, so a
    # span that starts or ends mid-word (e.g. "500만 원" in "500만 원만")
    # never breaks across lines.
    words = [(m.group(), m.start(), m.end())
             for m in re.finditer(r"\S+", text)]
    atoms: list[str] = []
    i = 0
    for s, e in spans:
        while i < len(words) and words[i][2] <= s:
            atoms.append(words[i][0])
            i += 1
        j = i
        while j < len(words) and words[j][1] < e:
            j += 1
        assert j > i, f"token aligns to no word: {text[s:e]!r}"
        atoms.append(text[words[i][1]:words[j - 1][2]])
        i = j
    while i < len(words):
        atoms.append(words[i][0])
        i += 1
    assert " ".join(atoms) == text, "atom split lost text"
    lines: list[str] = []
    cur = ""
    for at in atoms:
        trial = at if not cur else cur + " " + at
        if draw.textlength(trial, font=fnt) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = at
    if cur:
        lines.append(cur)
    return lines


def line_height(draw: ImageDraw.ImageDraw,
                fnt: ImageFont.FreeTypeFont) -> int:
    box = draw.textbbox((0, 0), "가Hgj", font=fnt)
    return box[3] - box[1]


def token_box_on_line(draw: ImageDraw.ImageDraw, origin: tuple[int, int],
                      line: str, token: str,
                      fnt: ImageFont.FreeTypeFont) -> list[int] | None:
    """Pixel box of `token` inside `line` drawn at origin (textbbox-based)."""
    idx = line.find(token)
    if idx < 0:
        return None
    x0, y0 = origin
    pre_w = float(draw.textlength(line[:idx], font=fnt))
    tok_w = float(draw.textlength(token, font=fnt))
    lh = line_height(draw, fnt)
    x1 = int(round(x0 + pre_w))
    x2 = int(round(x0 + pre_w + tok_w))
    return [x1, y0, max(x1 + 1, x2), y0 + lh]


def draw_face(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> list[int]:
    """Simple geometric profile face: circle plus line/dot features."""
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(205, 210, 216),
                 outline=(120, 126, 132), width=2)
    er = max(2, r // 7)
    ex = r * 4 // 10
    ey = r * 2 // 10
    draw.ellipse([cx - ex - er, cy - ey - er, cx - ex + er, cy - ey + er],
                 fill=INK)
    draw.ellipse([cx + ex - er, cy - ey - er, cx + ex + er, cy - ey + er],
                 fill=INK)
    draw.line([cx - r // 2, cy + r // 2, cx + r // 2, cy + r // 2],
              fill=INK, width=2)
    return [cx - r, cy - r, cx + r, cy + r]


# Handwriting-like scribble programs, one per signer. Each stroke is
# (pen width, [(rx, ry), ...]) with coordinates relative to the inner box.
# Every program lifts the pen between strokes (4 separate strokes), uses
# irregular lengths and heights, and stays inside part of the box so the ink
# stays clearly smaller than the signature frame (IoU <= 0.4). Hand-written
# coordinates only - no wave functions. Deterministic by construction.
SIGNATURE_PROGRAMS: tuple[tuple[tuple[int, list[tuple[float, float]]], ...], ...] = (
    (  # Signer 0: tall zigzag, hook, underline flourish, short tick.
        (3, [(0.06, 0.66), (0.16, 0.30), (0.24, 0.52), (0.33, 0.26),
             (0.40, 0.60)]),
        (2, [(0.44, 0.38), (0.50, 0.70), (0.57, 0.55), (0.62, 0.66)]),
        (4, [(0.08, 0.82), (0.30, 0.74), (0.52, 0.80)]),
        (2, [(0.58, 0.30), (0.66, 0.34), (0.64, 0.46)]),
    ),
    (  # Signer 1: peak with tail, m-shape, low underline, dot tick.
        (4, [(0.10, 0.55), (0.22, 0.24), (0.34, 0.58), (0.30, 0.74)]),
        (2, [(0.38, 0.62), (0.46, 0.36), (0.55, 0.60), (0.60, 0.44)]),
        (3, [(0.12, 0.80), (0.36, 0.86), (0.58, 0.78)]),
        (2, [(0.05, 0.40), (0.09, 0.52)]),
    ),
)


def draw_signature(draw: ImageDraw.ImageDraw, box: list[int],
                   signer_index: int) -> tuple[list[int], int]:
    """Draw one signer's scribble program. Returns (ink box, stroke count).

    The ink box tracks every plotted point plus half the pen width.
    """
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    program = SIGNATURE_PROGRAMS[signer_index % len(SIGNATURE_PROGRAMS)]
    ink = [x2, y2, x1, y1]  # minx, miny, maxx, maxy
    for width, rel in program:
        pts = [(x1 + rx * w, y1 + ry * h) for rx, ry in rel]
        draw.line(pts, fill=SIG_INK, width=width, joint="curve")
        hw = width / 2
        for x, y in pts:
            ink[0] = min(ink[0], x - hw)
            ink[1] = min(ink[1], y - hw)
            ink[2] = max(ink[2], x + hw)
            ink[3] = max(ink[3], y + hw)
    return [int(round(v)) for v in ink], len(program)


# ---------------------------------------------------------------------------
# Chat capture renderer
# ---------------------------------------------------------------------------

# A chat block is ("divider", text, normalized_date)
# or ("msg", speaker, side, text, tags, tokens) where tokens is a list of
# (substring, kind, normalized) with kind in ("amount", "date").

def render_chat(path: Path, width: int, height: int, header_title: str,
                blocks: list[tuple], spread: bool = False) -> dict:
    """Draw a chat capture and return recorded truth (items, vision, tags).

    Layout is computed first (wrapping needs no y), then drawn; every box is
    recorded from the coordinates actually used for drawing.
    """
    img = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(img)
    band_box = draw_band(img)

    f_header = font(20, bold=True)
    f_div = font(16)
    f_msg = font(20)
    f_name = font(14)
    lh_msg = line_height(draw, f_msg)
    line_gap = 7
    max_bw = 440
    pad_x, pad_y = 16, 12
    margin = 20
    face_r = 20

    items: list[dict] = []
    vision: list[dict] = []
    tags: dict[str, list[str]] = {}
    counter = [0]

    def add_item(kind: str, text: str, norm, box: list[int],
                 line_box=None, speaker=None, speaker_role=None) -> str:
        assert kind in KINDS, kind
        counter[0] += 1
        item_id = f"item{counter[0]}"
        items.append({"item_id": item_id, "kind": kind,
                      "text_verbatim": text, "normalized": norm,
                      "box": [int(v) for v in box],
                      "line_box": ([int(v) for v in line_box]
                                   if line_box else None),
                      "speaker": speaker, "speaker_role": speaker_role,
                      "frame_ts": None, "frame_index": None})
        return item_id

    # The SAMPLE band lives only in ignore_regions, never as an item.

    # Header row.
    header_y = BAND_H + 12
    draw.text((margin, header_y), header_title, font=f_header, fill=INK)
    hb = draw.textbbox((margin, header_y), header_title, font=f_header)
    add_item("header", header_title, header_title, list(hb))
    top_y = hb[3] + 14
    draw.line([margin, top_y - 6, width - margin, top_y - 6], fill=(210, 214, 218))

    # First pass: wrap messages, measure natural block heights.
    measured: list[dict] = []
    for blk in blocks:
        if blk[0] == "divider":
            _, text, norm = blk
            measured.append({"type": "divider", "text": text, "norm": norm,
                             "h": 30})
        else:
            _, speaker, side, text, btags, tokens = blk
            lines = wrap_words(draw, text, tokens, f_msg, max_bw - pad_x * 2)
            tw_max = max(float(draw.textlength(ln, font=f_msg)) for ln in lines)
            bw = int(tw_max + pad_x * 2)
            bh = len(lines) * lh_msg + (len(lines) - 1) * line_gap + pad_y * 2
            has_face = side == "left" and not any(
                m.get("face") for m in measured)
            label_h = 22 if side == "left" else 0
            measured.append({"type": "msg", "speaker": speaker, "side": side,
                             "text": text, "tags": btags, "tokens": tokens,
                             "lines": lines, "bw": bw, "bh": bh,
                             "face": has_face, "label_h": label_h,
                             "h": label_h + bh})

    base_gap = 16
    n_gaps = len(measured)  # gaps between blocks plus one at the end
    natural = sum(m["h"] for m in measured) + base_gap * (n_gaps - 1)
    bottom_margin = 40
    if spread:
        extra = max(0, height - bottom_margin - top_y - natural)
        gap = base_gap + extra / max(1, n_gaps - 1) if n_gaps > 1 else base_gap
    else:
        gap = base_gap
        assert top_y + natural + bottom_margin <= height, "chat overflow"

    # Second pass: draw.
    y = float(top_y)
    for m in measured:
        if m["type"] == "divider":
            fnt = f_div
            tw = float(draw.textlength(m["text"], font=fnt))
            tx = (width - tw) / 2
            ty = y + 4
            draw.text((tx, ty), m["text"], font=fnt, fill=(90, 96, 104))
            db = draw.textbbox((tx, ty), m["text"], font=fnt)
            add_item("date", m["text"], m["norm"], list(db))
        else:
            side = m["side"]
            if side == "left":
                bx = margin + (face_r * 2 + 10 if m["face"] else 0)
            else:
                bx = width - margin - m["bw"]
            by = int(round(y + m["label_h"]))
            fill = BUBBLE_LEFT if side == "left" else BUBBLE_RIGHT
            draw.rounded_rectangle([bx, by, bx + m["bw"], by + m["bh"]],
                                   radius=14, fill=fill)
            role = "creditor" if side == "right" else "debtor"
            if m["face"]:
                fbox = draw_face(draw, margin + face_r,
                                 by + m["bh"] // 2, face_r)
                vision.append({"target": "face", "box": fbox,
                               "frame_box": None, "item_id": None,
                               "frame_ts": None, "frame_index": None})
            if side == "left":
                nx, ny = bx + 2, by - 20
                draw.text((nx, ny), m["speaker"], font=f_name, fill=GRAY)
                nb = draw.textbbox((nx, ny), m["speaker"], font=f_name)
                add_item("party_name", m["speaker"], m["speaker"], list(nb))
            # Lines and token boxes.
            line_origin = []
            for li, ln in enumerate(m["lines"]):
                lx = bx + pad_x
                ly = by + pad_y + li * (lh_msg + line_gap)
                draw.text((lx, ly), ln, font=f_msg, fill=INK)
                line_origin.append((lx, ly))
            utt_id = add_item("utterance", m["text"], m["text"],
                              [bx, by, bx + m["bw"], by + m["bh"]],
                              speaker=m["speaker"], speaker_role=role)
            tags[utt_id] = list(m["tags"])
            vision.append({"target": "chat_bubble",
                           "box": [bx, by, bx + m["bw"], by + m["bh"]],
                           "frame_box": None, "item_id": utt_id,
                           "frame_ts": None, "frame_index": None})
            # In-sentence tokens: each must sit on exactly one line.
            for substr, kind, norm in m["tokens"]:
                found = None
                for ln, (lx, ly) in zip(m["lines"], line_origin):
                    tb = token_box_on_line(draw, (lx, ly), ln, substr, f_msg)
                    if tb:
                        lb = draw.textbbox((lx, ly), ln, font=f_msg)
                        found = (tb, list(lb))
                        break
                assert found, f"token not on one line: {substr!r} in {m['text']!r}"
                add_item(kind, substr, norm, found[0], line_box=found[1],
                         speaker=m["speaker"], speaker_role=role)
        y += m["h"] + gap

    save_png(img, path)
    return {"items": items, "vision": vision, "tags": tags,
            "ignore": [band_box], "size": [width, height]}


# ---------------------------------------------------------------------------
# Transfer receipt renderer
# ---------------------------------------------------------------------------

def render_receipt(path: Path, width: int, height: int, title: str,
                   rows: list[tuple[str, str, str, object]],
                   boxed_values: set[str]) -> dict:
    """Draw a receipt. rows: (label, value, value_kind, normalized).

    Values named in boxed_values are drawn inside a separate full-visibility
    box (for the redaction demo). Returns truth incl. redaction targets.
    """
    img = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(img)
    band_box = draw_band(img)

    f_title = font(30, bold=True)
    f_label = font(19)
    f_value = font(22)
    margin = 36
    value_x = 230

    items: list[dict] = []
    redactions: list[dict] = []
    counter = [0]

    def add_item(kind: str, text: str, norm, box: list[int]) -> str:
        assert kind in KINDS, kind
        counter[0] += 1
        item_id = f"item{counter[0]}"
        items.append({"item_id": item_id, "kind": kind,
                      "text_verbatim": text, "normalized": norm,
                      "box": [int(v) for v in box], "line_box": None,
                      "speaker": None, "speaker_role": None,
                      "frame_ts": None, "frame_index": None})
        return item_id

    # The SAMPLE band lives only in ignore_regions, never as an item.

    ty = BAND_H + 26
    draw.text((margin, ty), title, font=f_title, fill=INK)
    tb = draw.textbbox((margin, ty), title, font=f_title)
    add_item("header", title, title, list(tb))
    draw.line([margin, tb[3] + 14, width - margin, tb[3] + 14],
              fill=(140, 146, 152), width=2)

    y = tb[3] + 40
    row_h = 72
    for label, value, vkind, norm in rows:
        draw.text((margin, y + 4), label, font=f_label, fill=GRAY)
        lb = draw.textbbox((margin, y + 4), label, font=f_label)
        add_item("label", label, label, list(lb))
        vx = value_x
        if value in boxed_values:
            vb = draw.textbbox((vx, y), value, font=f_value)
            frame = [vb[0] - 12, vb[1] - 8, vb[2] + 12, vb[3] + 8]
            draw.rounded_rectangle(frame, radius=8, outline=(90, 96, 104),
                                   width=2)
        draw.text((vx, y), value, font=f_value, fill=INK)
        vb = draw.textbbox((vx, y), value, font=f_value)
        item_id = add_item(vkind, value, norm, list(vb))
        if vkind == "account_number":
            # mask_box: front part to hide; keep_box: last 4 digits to keep.
            # No redaction margin on the keep side: mask and keep tile the
            # account box end to end (mask end == keep start).
            last4 = value[-4:]
            pre = value[:-4]
            pre_w = float(draw.textlength(pre, font=f_value))
            last_w = float(draw.textlength(last4, font=f_value))
            x1 = vb[0]
            x_keep = int(round(vx + pre_w))
            redactions.append({"target": "account_number", "item_id": item_id,
                               "mask_box": [x1, vb[1], x_keep, vb[3]],
                               "keep_box": [x_keep, vb[1],
                                            int(round(x_keep + last_w)),
                                            vb[3]]})
            # Sanity: keep_box really covers the last 4 digits.
            kb = draw.textbbox((x_keep, y), last4, font=f_value)
            assert abs(kb[0] - x_keep) <= 2, (kb, x_keep)
        y += row_h

    save_png(img, path)
    return {"items": items, "vision": [], "tags": {}, "redactions": redactions,
            "ignore": [band_box], "size": [width, height]}


# ---------------------------------------------------------------------------
# IOU / promissory note renderers (PNG truth basis + PDF with PNG embedded)
# ---------------------------------------------------------------------------

IOU_W, IOU_H = 1240, 1754  # A4 at 150 DPI


def render_iou_png(path: Path, title: str,
                   rows: list[tuple[str, str, str, object]],
                   note_line: str, id_value: str | None,
                   signers: list[str], stamp_text: str | None) -> dict:
    """Draw the IOU PNG. rows: (label, value, value_kind, normalized).

    note_line is a standalone printed line (kind label, e.g. interest terms).
    id_value (or None) is drawn inside a separate box. signers get framed
    multi-stroke signatures. Returns truth with vision + redaction targets.
    """
    img = Image.new("RGB", (IOU_W, IOU_H), WHITE)
    draw = ImageDraw.Draw(img)
    band_box = draw_band(img)

    f_title = font(56, bold=True)
    f_label = font(30)
    f_value = font(34)
    f_small = font(28)
    margin = 120
    value_x = 470

    items: list[dict] = []
    vision: list[dict] = []
    redactions: list[dict] = []
    counter = [0]

    def add_item(kind: str, text: str, norm, box: list[int]) -> str:
        assert kind in KINDS, kind
        counter[0] += 1
        item_id = f"item{counter[0]}"
        items.append({"item_id": item_id, "kind": kind,
                      "text_verbatim": text, "normalized": norm,
                      "box": [int(v) for v in box], "line_box": None,
                      "speaker": None, "speaker_role": None,
                      "frame_ts": None, "frame_index": None})
        return item_id

    # The SAMPLE band lives only in ignore_regions, never as an item.

    tw = float(draw.textlength(title, font=f_title))
    tx = (IOU_W - tw) / 2
    tyy = BAND_H + 44
    draw.text((tx, tyy), title, font=f_title, fill=INK)
    tb = draw.textbbox((tx, tyy), title, font=f_title)
    add_item("header", title, title, list(tb))
    draw.line([margin, tb[3] + 20, IOU_W - margin, tb[3] + 20],
              fill=(140, 146, 152), width=3)

    y = tb[3] + 52
    row_h = 88
    for label, value, vkind, norm in rows:
        draw.text((margin, y + 6), label, font=f_label, fill=GRAY)
        lb = draw.textbbox((margin, y + 6), label, font=f_label)
        add_item("label", label, label, list(lb))
        draw.text((value_x, y), value, font=f_value, fill=INK)
        vb = draw.textbbox((value_x, y), value, font=f_value)
        add_item(vkind, value, norm, list(vb))
        y += row_h

    # Standalone printed note line (interest terms).
    draw.text((margin, y + 6), note_line, font=f_value, fill=INK)
    nb = draw.textbbox((margin, y + 6), note_line, font=f_value)
    add_item("label", note_line, note_line, list(nb))
    y += row_h

    # ID number in its own box (KR only).
    if id_value is not None:
        draw.text((margin, y + 6), "주민등록번호", font=f_label, fill=GRAY)
        lb = draw.textbbox((margin, y + 6), "주민등록번호", font=f_label)
        add_item("label", "주민등록번호", "주민등록번호", list(lb))
        vb = draw.textbbox((value_x, y), id_value, font=f_value)
        frame = [vb[0] - 14, vb[1] - 10, vb[2] + 14, vb[3] + 10]
        draw.rounded_rectangle(frame, radius=10, outline=(90, 96, 104),
                               width=2)
        draw.text((value_x, y), id_value, font=f_value, fill=INK)
        item_id = add_item("id_number", id_value, id_value, list(vb))
        # Mask the back 7 digits only (behind the hyphen).
        front, back = id_value.split("-")
        back_x = int(round(value_x + draw.textlength(front + "-", font=f_value)))
        redactions.append({"target": "id_number", "item_id": item_id,
                           "mask_box": [back_x, vb[1], vb[2], vb[3]],
                           "keep_box": None})
        y += row_h

    # Signature frames with per-signer scribbles. The name label sits above
    # its frame so it never overlaps the signature ink.
    sig_frames: list[list[int]] = []
    for si, signer in enumerate(signers):
        lab = f"{signer} 서명" if stamp_text else f"{signer} signature"
        draw.text((margin, y), lab, font=f_small, fill=INK)
        sb = draw.textbbox((margin, y), lab, font=f_small)
        add_item("label", lab, lab, list(sb))
        frame = [value_x, y + 40, value_x + 480, y + 170]
        draw.rectangle(frame, outline=(120, 126, 132), width=2)
        ink, strokes = draw_signature(
            draw, [frame[0] + 24, frame[1] + 24, frame[2] - 24, frame[3] - 24],
            si)
        vision.append({"target": "signature", "box": ink, "frame_box": frame,
                       "item_id": None, "frame_ts": None, "frame_index": None,
                       "strokes": strokes})
        sig_frames.append(frame)
        y += 210
    assert y <= IOU_H - 30, "IOU content overflows the page"

    # Red seal with the debtor name (KR only), right of the last frame.
    if stamp_text is not None:
        last = sig_frames[-1]
        sx1 = last[2] + 40
        sx2 = sx1 + 180
        assert sx2 <= IOU_W - 40, "stamp overflows page"
        sy1 = last[1] - 20
        sy2 = sy1 + 180
        draw.ellipse([sx1, sy1, sx2, sy2], outline=STAMP_RED, width=7)
        draw.ellipse([sx1 + 14, sy1 + 14, sx2 - 14, sy2 - 14],
                     outline=STAMP_RED, width=2)
        f_stamp = font(46, bold=True)
        # stamp_text is the short debtor name (fits the seal).
        st_txt = stamp_text
        sw = float(draw.textlength(st_txt, font=f_stamp))
        sb2 = draw.textbbox((0, 0), st_txt, font=f_stamp)
        cx = (sx1 + sx2 - sw) / 2
        cy = (sy1 + sy2 - (sb2[3] - sb2[1])) / 2 - sb2[1]
        draw.text((cx, cy), st_txt, font=f_stamp, fill=STAMP_RED)
        stb = draw.textbbox((cx, cy), st_txt, font=f_stamp)
        add_item("party_name", st_txt, st_txt, list(stb))
        vision.append({"target": "stamp", "box": [sx1, sy1, sx2, sy2],
                       "frame_box": None, "item_id": None, "frame_ts": None,
                       "frame_index": None})

    save_png(img, path)
    return {"items": items, "vision": vision, "tags": {}, "redactions": redactions,
            "ignore": [band_box], "size": [IOU_W, IOU_H],
            "sig_frames": sig_frames}


def render_iou_pdf(path: Path, png_path: Path) -> None:
    """PDF twin of the IOU PNG: the preview PNG embedded on one full page.

    Embedding keeps the PDF layout identical to the PNG (same band, rows,
    signatures, stamp) by construction. Truth coordinates always use the PNG
    pixel basis (see coord_basis), so no text layer is needed; readers score
    against the preview image. reportlab invariant mode keeps the bytes
    deterministic.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    assert png_path.is_file(), f"preview must be rendered first: {png_path}"
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    w, h = A4
    # The PNG is A4 at 150 DPI, so it covers the page exactly (72/150 scale).
    c.drawImage(str(png_path), 0, 0, width=w, height=h,
                preserveAspectRatio=True, anchor="c")
    c.showPage()
    c.save()


# ---------------------------------------------------------------------------
# Scroll video (tall capture -> fixed-viewport scroll with a fixed SAMPLE band)
# ---------------------------------------------------------------------------

VIDEO_FPS = 10
VIDEO_SECONDS = 7.0
VIDEO_FRAMES = int(VIDEO_FPS * VIDEO_SECONDS)
VIDEO_W, VIDEO_H = 640, 960


def frame_offset(frame_index: int, max_off: int) -> int:
    """Scroll offset actually used when rendering one video frame."""
    return int(round(max_off * frame_index / (VIDEO_FRAMES - 1)))


def first_full_frame(top: int, bottom: int, offsets: list[int]) -> int:
    """First frame where [top, bottom] is fully inside the viewport below
    the fixed SAMPLE band."""
    for i, off in enumerate(offsets):
        if top - off >= BAND_H and bottom - off <= VIDEO_H:
            return i
    raise AssertionError(f"item never fully visible: {(top, bottom)}")


def build_video(tall_path: Path, out_path: Path, tall_truth: dict) -> dict:
    """Render the scroll video and mirror the tall truth into viewport
    coordinates at each item's first-fully-visible frame (frame_index,
    frame_ts = index / FPS, seconds).
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to build chat_02_scroll.mp4")
    tall = Image.open(tall_path).convert("RGB")
    tw, th = tall.size
    assert (tw, th) == (640, 2400), tall.size
    max_off = th - VIDEO_H
    assert max_off == 1440
    # The exact per-frame offsets used below; recorded on the truth so
    # tests can map tall boxes to frame boxes without recomputing.
    offsets = [frame_offset(i, max_off) for i in range(VIDEO_FRAMES)]

    tmp = Path(tempfile.mkdtemp(prefix="m3_frames_"))
    try:
        fnt = font(18, bold=True)
        for i in range(VIDEO_FRAMES):
            off = offsets[i]
            frame = tall.crop((0, off, VIDEO_W, off + VIDEO_H))
            fd = ImageDraw.Draw(frame)
            fd.rectangle([0, 0, VIDEO_W, BAND_H], fill=BAND_FILL)
            twm = float(fd.textlength(WATERMARK, font=fnt))
            fd.text(((VIDEO_W - twm) / 2, 7), WATERMARK, font=fnt,
                    fill=BAND_TEXT)
            frame.save(tmp / f"frame_{i:03d}.png")
        cmd = ["ffmpeg", "-y", "-fflags", "+bitexact",
               "-framerate", str(VIDEO_FPS),
               "-i", str(tmp / "frame_%03d.png"),
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
               "-flags:v", "+bitexact", "-map_metadata", "-1",
               "-threads", "1", str(out_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {proc.stderr[-2000:]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    size = out_path.stat().st_size
    assert size <= 3 * 1024 * 1024, f"video too large: {size}"

    def shift(box: list[int] | None, off: int) -> list[int] | None:
        if box is None:
            return None
        return [box[0], box[1] - off, box[2], box[3] - off]

    items: list[dict] = []
    for it in tall_truth["items"]:
        y1, y2 = it["box"][1], it["box"][3]
        fi = first_full_frame(y1, y2, offsets)
        items.append({**it, "box": shift(it["box"], offsets[fi]),
                      "line_box": shift(it["line_box"], offsets[fi]),
                      "frame_ts": round(fi / VIDEO_FPS, 3),
                      "frame_index": fi})
    vision: list[dict] = []
    for v in tall_truth["vision"]:
        y1, y2 = v["box"][1], v["box"][3]
        fi = first_full_frame(y1, y2, offsets)
        vision.append({**v, "box": shift(v["box"], offsets[fi]),
                       "frame_ts": round(fi / VIDEO_FPS, 3),
                       "frame_index": fi})
    # At least one bubble must appear only after scrolling starts.
    late = [it for it in items
            if it["kind"] == "utterance" and (it["frame_ts"] or 0) > 1.0]
    assert late, "no bubble appears late in the scroll video"
    return {"items": items, "vision": vision, "tags": dict(tall_truth["tags"]),
            "redactions": [], "ignore": [[0, 0, VIDEO_W, BAND_H]],
            "size": [VIDEO_W, VIDEO_H],
            "video": {"fps": VIDEO_FPS, "frames": VIDEO_FRAMES,
                      "frame_offsets": offsets}}


# ---------------------------------------------------------------------------
# Case contents
# ---------------------------------------------------------------------------

KR_CHAT_01: list[tuple] = [
    ("divider", "2026년 3월 9일", "2026-03-09"),
    ("msg", KR_DEBTOR, "left",
     "서가온님, 급하게 500만 원만 빌려주실 수 있나요?",
     ["loan_request", "amount_mention"], [("500만 원", "amount", 5000000)]),
    ("msg", KR_CREDITOR, "right",
     "무슨 일이에요? 500만 원이 맞나요?",
     ["amount_mention"], [("500만 원", "amount", 5000000)]),
    ("msg", KR_DEBTOR, "left",
     "네, 병원비로 500만 원이 필요해요. 4월 10일까지 갚을게요.",
     ["amount_mention", "repay_promise"],
     [("500만 원", "amount", 5000000), ("4월 10일", "date", None)]),
    ("divider", "2026년 3월 10일", "2026-03-10"),
    ("msg", KR_CREDITOR, "right",
     "알겠어요. 오늘 5,000,000원 보낼게요.",
     ["amount_mention"], [("5,000,000원", "amount", 5000000)]),
    ("msg", KR_DEBTOR, "left",
     "정말 감사합니다!",
     ["other"], []),
]

KR_CHAT_02: list[tuple] = [
    ("divider", "2026년 4월 20일", "2026-04-20"),
    ("msg", KR_CREDITOR, "right",
     "탁나루님, 4월 10일이 지났어요. 확인 부탁드려요.",
     ["reminder"], [("4월 10일", "date", None)]),
    ("msg", KR_DEBTOR, "left",
     "죄송해요. 4월 25일까지 꼭 갚을게요.",
     ["repay_promise"], [("4월 25일", "date", None)]),
    ("divider", "2026년 4월 26일", "2026-04-26"),
    ("msg", KR_CREDITOR, "right",
     "4월 25일이 지났어요. 언제 보내주실 수 있나요?",
     ["reminder"], [("4월 25일", "date", None)]),
    ("msg", KR_DEBTOR, "left",
     "정말 죄송합니다. 5월 1일에는 꼭 보내드릴게요.",
     ["repay_promise"], [("5월 1일", "date", None)]),
    ("divider", "2026년 5월 1일", "2026-05-01"),
    ("msg", KR_DEBTOR, "left",
     "오늘 100만 원 먼저 보냈어.",
     ["amount_mention"], [("100만 원", "amount", 1000000)]),
    ("msg", KR_CREDITOR, "right",
     "100만 원 받았어요. 남은 400만 원은 언제 주실 수 있나요?",
     ["amount_mention", "reminder"],
     [("100만 원", "amount", 1000000), ("400만 원", "amount", 4000000)]),
    ("msg", KR_DEBTOR, "left",
     "5월 20일까지 남은 400만 원 다 갚을게요.",
     ["amount_mention", "repay_promise"],
     [("5월 20일", "date", None), ("400만 원", "amount", 4000000)]),
]

KR_LOAN_ROWS: list[tuple[str, str, str, object]] = [
    ("보낸 사람", KR_CREDITOR, "party_name", KR_CREDITOR),
    ("보낸 계좌", KR_ACCT_A, "account_number", KR_ACCT_A),
    ("받는 사람", KR_DEBTOR, "party_name", KR_DEBTOR),
    ("받는 계좌", KR_ACCT_B, "account_number", KR_ACCT_B),
    ("금액", "5,000,000원", "amount", 5000000),
    ("송금일", "2026-03-10", "date", "2026-03-10"),
]

KR_REPAY_ROWS: list[tuple[str, str, str, object]] = [
    ("받은 사람", KR_CREDITOR, "party_name", KR_CREDITOR),
    ("받은 계좌", KR_ACCT_A, "account_number", KR_ACCT_A),
    ("보낸 사람", KR_DEBTOR, "party_name", KR_DEBTOR),
    ("보낸 계좌", KR_ACCT_B, "account_number", KR_ACCT_B),
    ("금액", "1,000,000원", "amount", 1000000),
    ("입금일", "2026-05-01", "date", "2026-05-01"),
]

KR_IOU_ROWS: list[tuple[str, str, str, object]] = [
    ("채권자", KR_CREDITOR, "party_name", KR_CREDITOR),
    ("채권자 주소", "서울특별시 샘플구 데모로 0", "address",
     "서울특별시 샘플구 데모로 0"),
    ("채권자 연락처", "010-0000-0001", "phone", "010-0000-0001"),
    ("채무자", KR_DEBTOR, "party_name", KR_DEBTOR),
    ("채무자 주소", "경기도 샘플시 데모동 0", "address",
     "경기도 샘플시 데모동 0"),
    ("채무자 연락처", "010-0000-0002", "phone", "010-0000-0002"),
    ("금액", "5,000,000원", "amount", 5000000),
    ("금액(한글)", "금 오백만 원", "amount", 5000000),
    ("대여일", "2026-03-10", "date", "2026-03-10"),
    ("변제기", "2026-04-10", "date", "2026-04-10"),
]

EN_CHAT_01: list[tuple] = [
    ("divider", "January 9, 2026", "2026-01-09"),
    ("msg", EN_DEBTOR, "left",
     "Can you lend me $5,000?",
     ["loan_request", "amount_mention"], [("$5,000", "amount", 500000)]),
    ("msg", EN_CREDITOR, "right",
     "What happened? When can you pay it back?",
     ["other"], []),
    ("msg", EN_DEBTOR, "left",
     "I need $5,000 for rent. I will pay you back by April 10.",
     ["amount_mention", "repay_promise"],
     [("$5,000", "amount", 500000), ("April 10", "date", None)]),
    ("divider", "January 10, 2026", "2026-01-10"),
    ("msg", EN_CREDITOR, "right",
     "OK. I will send $5,000 today.",
     ["amount_mention"], [("$5,000", "amount", 500000)]),
]

EN_WIRE_ROWS: list[tuple[str, str, str, object]] = [
    ("Sender", EN_CREDITOR, "party_name", EN_CREDITOR),
    ("Sender account", EN_ACCT_A, "account_number", EN_ACCT_A),
    ("Receiver", EN_DEBTOR, "party_name", EN_DEBTOR),
    ("Receiver account", EN_ACCT_B, "account_number", EN_ACCT_B),
    ("Amount", "$5,000.00", "amount", 500000),
    ("Date", "January 10, 2026", "date", "2026-01-10"),
]

EN_NOTE_ROWS: list[tuple[str, str, str, object]] = [
    ("Lender", EN_CREDITOR, "party_name", EN_CREDITOR),
    ("Lender phone", "555-0100", "phone", "555-0100"),
    ("Borrower", EN_DEBTOR, "party_name", EN_DEBTOR),
    ("Borrower phone", "555-0111", "phone", "555-0111"),
    ("Borrower address", "0 Sample St, Sample City, CA 90000", "address",
     "0 Sample St, Sample City, CA 90000"),
    ("Amount", "$5,000.00", "amount", 500000),
    ("Amount in words", "Five thousand dollars", "amount", 500000),
    ("Loan date", "January 10, 2026", "date", "2026-01-10"),
    ("Due date", "April 10, 2026", "date", "2026-04-10"),
]

KR_CASE = {
    "creditor": {"name": KR_CREDITOR, "phone": "010-0000-0001",
                 "address": "서울특별시 샘플구 데모로 0"},
    "debtor": {"name": KR_DEBTOR, "phone": "010-0000-0002",
               "address": "경기도 샘플시 데모동 0"},
    "currency": "KRW",
    "transaction_kind": "civil",
    "contract_form": "written",
    "principal_amount": 5000000,
    "loan_date": "2026-03-10",
    "due_date": "2026-04-10",
    "agreed_interest_rate": None,
    "repayments": [{"payment_date": "2026-05-01", "amount": 1000000,
                    "evidence_id": "EX5"}],
    "remaining_principal": 4014383,
    "accrual_start_date": "2026-05-02",
}

EN_CASE = {
    "creditor": {"name": EN_CREDITOR, "phone": "555-0100"},
    "debtor": {"name": EN_DEBTOR, "phone": "555-0111",
               "address": "0 Sample St, Sample City, CA 90000"},
    "currency": "USD",
    "transaction_kind": "civil",
    "contract_form": "written",
    "principal_amount": "5000.00",
    "loan_date": "2026-01-10",
    "due_date": "2026-04-10",
    "agreed_interest_rate": None,
    "repayments": [],
    "remaining_principal": "5000.00",
    "accrual_start_date": "2026-04-11",
}


# ---------------------------------------------------------------------------
# Truth assembly + manifest
# ---------------------------------------------------------------------------

KR_AMOUNT_UNIT = "KRW: case amounts and item normalized are integer won."
EN_AMOUNT_UNIT = ("USD: item normalized are integer cents; case "
                 "principal_amount/remaining_principal are "
                 "decimal-dollar strings.")


def assemble_truth(case: dict, files: list[tuple[str, Path, dict]],
                   coord_basis: dict[str, str | None],
                   amount_unit: str) -> dict:
    """Combine per-file render results into one golden truth document.

    files: (ex_id, path, render_result). coord_basis maps ex_id to the file
    whose pixels the boxes use (PDF entries point at their PNG twin).
    Video render results carry their per-frame scroll offsets ("video"),
    which are recorded on the video evidence entry.
    """
    evidences: list[dict] = []
    items: list[dict] = []
    utterance_tags: dict[str, list[str]] = {}
    vision_targets: list[dict] = []
    redaction_targets: list[dict] = []
    for ex_id, path, res in files:
        basis = coord_basis.get(ex_id)
        w, h = res["size"]  # PDF entries reuse their PNG twin's pixels
        rel = path.relative_to(SAMPLE_DIR).as_posix()
        entry: dict = {"ex_id": ex_id, "file": rel,
                       "sha256": sha256_of(path),
                       "width": w, "height": h,
                       "coord_system": "pixel",
                       "coord_basis": basis,
                       "ignore_regions": res["ignore"]}
        if "video" in res:
            entry["video"] = res["video"]
        evidences.append(entry)
        for it in res["items"]:
            items.append({"ex_id": ex_id, **it})
        for item_id, tgs in res.get("tags", {}).items():
            utterance_tags[f"{ex_id}:{item_id}"] = list(tgs)
        for v in res.get("vision", []):
            vision_targets.append({"ex_id": ex_id, **v})
        for r in res.get("redactions", []):
            redaction_targets.append({"ex_id": ex_id, **r})
    return {
        "_note": "test-only golden answers. Never pass to runtime agents.",
        "amount_unit": amount_unit,
        "case": case,
        "evidences": evidences,
        "items": items,
        "utterance_tags": utterance_tags,
        "vision_targets": vision_targets,
        "redaction_targets": redaction_targets,
    }


def build_kr() -> None:
    r1 = render_chat(KR_DIR / "chat_01.png", 640, 960, KR_APP, KR_CHAT_01)
    r2 = render_chat(KR_DIR / "chat_02_tall.png", 640, 2400, KR_APP,
                     KR_CHAT_02, spread=True)
    last_top = max(it["box"][1] for it in r2["items"]
                   if it["kind"] == "utterance")
    assert last_top > 1000, "last tall bubble must start below 960 viewport"
    r3 = build_video(KR_DIR / "chat_02_tall.png",
                     KR_DIR / "chat_02_scroll.mp4", r2)
    r4 = render_receipt(KR_DIR / "transfer_loan.png", 640, 640,
                        f"{KR_BANK} 송금확인증", KR_LOAN_ROWS,
                        {KR_ACCT_A, KR_ACCT_B})
    r5 = render_receipt(KR_DIR / "transfer_repay.png", 640, 640,
                        f"{KR_BANK} 입금확인증", KR_REPAY_ROWS,
                        {KR_ACCT_A, KR_ACCT_B})
    r7 = render_iou_png(KR_DIR / "iou.png", "차 용 증", KR_IOU_ROWS,
                        "이자 약정 없음", KR_ID_NUMBER,
                        [KR_CREDITOR, KR_DEBTOR], "탁나루")
    render_iou_pdf(KR_DIR / "iou.pdf", KR_DIR / "iou.png")
    # The PDF twin reuses the PNG pixel boxes (declared via coord_basis).
    # iou.png stays on disk as the EX6 preview but is not an evidence.
    r6 = {"items": [dict(it) for it in r7["items"]],
          "vision": [dict(v) for v in r7["vision"]], "tags": {},
          "redactions": [dict(r) for r in r7["redactions"]],
          "ignore": [list(b) for b in r7["ignore"]], "size": list(r7["size"])}
    truth = assemble_truth(
        KR_CASE,
        [("EX1", KR_DIR / "chat_01.png", r1),
         ("EX2", KR_DIR / "chat_02_tall.png", r2),
         ("EX3", KR_DIR / "chat_02_scroll.mp4", r3),
         ("EX4", KR_DIR / "transfer_loan.png", r4),
         ("EX5", KR_DIR / "transfer_repay.png", r5),
         ("EX6", KR_DIR / "iou.pdf", r6)],
        {"EX6": "kr/iou.png"}, KR_AMOUNT_UNIT)
    dump_json(truth, GOLDEN_DIR / "kr_truth.json")


def build_en() -> None:
    r1 = render_chat(EN_DIR / "chat_01.png", 640, 960, EN_APP, EN_CHAT_01)
    r2 = render_receipt(EN_DIR / "wire_receipt.png", 640, 640,
                        f"{EN_BANK} Wire Receipt", EN_WIRE_ROWS,
                        {EN_ACCT_A, EN_ACCT_B})
    r4 = render_iou_png(EN_DIR / "promissory_note.png", "Promissory Note",
                        EN_NOTE_ROWS, "No interest", None,
                        [EN_CREDITOR, EN_DEBTOR], None)
    render_iou_pdf(EN_DIR / "promissory_note.pdf", EN_DIR / "promissory_note.png")
    # The PDF reuses the PNG pixel boxes; the PNG stays on disk as the EX3
    # preview but is not an evidence.
    r3 = {"items": [dict(it) for it in r4["items"]],
          "vision": [dict(v) for v in r4["vision"]], "tags": {},
          "redactions": [dict(r) for r in r4["redactions"]],
          "ignore": [list(b) for b in r4["ignore"]], "size": list(r4["size"])}
    truth = assemble_truth(
        EN_CASE,
        [("EX1", EN_DIR / "chat_01.png", r1),
         ("EX2", EN_DIR / "wire_receipt.png", r2),
         ("EX3", EN_DIR / "promissory_note.pdf", r3)],
        {"EX3": "en/promissory_note.png"}, EN_AMOUNT_UNIT)
    dump_json(truth, GOLDEN_DIR / "en_truth.json")


def update_manifest() -> None:
    manifest_path = SAMPLE_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def refresh(node: object) -> None:
        if isinstance(node, dict):
            if set(node) == {"file", "sha256"} and isinstance(node["file"], str):
                if node["file"].endswith(".txt"):
                    p = SAMPLE_DIR / node["file"]
                    node["sha256"] = sha256_of(p)
                return
            for v in node.values():
                refresh(v)

    refresh(manifest)
    for key, folder in (("kr_images", KR_DIR), ("en_images", EN_DIR)):
        group: dict[str, dict[str, str]] = {}
        for p in sorted(folder.iterdir()):
            if p.is_file():
                group[p.name] = {"file": p.relative_to(SAMPLE_DIR).as_posix(),
                                 "sha256": sha256_of(p)}
        manifest[key] = group
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def main() -> int:
    KR_DIR.mkdir(parents=True, exist_ok=True)
    EN_DIR.mkdir(parents=True, exist_ok=True)
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    build_kr()
    build_en()
    update_manifest()
    for p in sorted(KR_DIR.iterdir()) + sorted(EN_DIR.iterdir()):
        print(f"  {p.relative_to(ROOT).as_posix()}: {p.stat().st_size} bytes")
    for name in ("kr_truth.json", "en_truth.json"):
        p = GOLDEN_DIR / name
        print(f"  {p.relative_to(ROOT).as_posix()}: {p.stat().st_size} bytes")
    print("manifest.json updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
