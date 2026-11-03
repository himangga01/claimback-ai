"""Build the English SAMPLE evidence set for the ClaimBack-AI demo video.

Creates (deterministic: the same fonts give identical bytes):
  submission/demo-evidence/en_chat_01.png        phone chat, 1080x1920
  submission/demo-evidence/en_chat_02_tall.png   long scroll capture, ~3 phone heights
  submission/demo-evidence/en_transfer_loan.png  SAMPLE Bank transfer receipt
  submission/demo-evidence/en_transfer_repay.png SAMPLE Bank deposit receipt
  submission/demo-evidence/en_iou.png            English IOU with signatures and a red seal

Story (all people, apps, banks and numbers are fictional):
  Jordan Lee (SAMPLE) lent Alex Kim (SAMPLE) KRW 5,000,000 on 2026-03-10,
  due 2026-04-10. Alex repaid KRW 1,000,000 on 2026-05-01; the rest is unpaid.
  The IOU spells the borrower "Alex J. Kim (SAMPLE)" on purpose, so the fact
  check shows a name question.

Every image carries a red "SAMPLE / DEMO" band. The chat app is the fictional
"DemoTalk" and the bank is the fictional "SAMPLE Bank"; neither copies a real
brand. Chats only mention amounts that are confirmed facts (5,000,000 and
1,000,000 won), so quoted lines never add a stray amount to the documents.

Fonts: Windows Segoe UI / Georgia / Segoe Script when present, otherwise the
repo's NanumGothic (backend/app/templates/fonts). Only Pillow is used.

Run from the repo root:
  .venv\\Scripts\\python.exe submission\\demo-evidence\\make_demo_evidence.py
"""

from __future__ import annotations

import hashlib
import math
import random
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
REPO_FONTS = ROOT / "backend" / "app" / "templates" / "fonts"
WIN_FONTS = Path("C:/Windows/Fonts")

W = 1080
BAND_H = 64

# --- Story constants (keep in sync with README.md) -------------------------
CREDITOR = "Jordan Lee (SAMPLE)"
DEBTOR = "Alex Kim (SAMPLE)"
DEBTOR_IOU = "Alex J. Kim (SAMPLE)"   # deliberate spelling variant
APP = "DemoTalk"
BANK = "SAMPLE Bank"
ACCT_CREDITOR = "000-012-480135"
ACCT_DEBTOR = "000-034-791246"
PHONE_CREDITOR = "010-0000-0147"
PHONE_DEBTOR = "010-0000-0258"
ID_DEBTOR = "900101-0000000"
ADDR_CREDITOR = "0 Sample-ro, Demo-gu, Seoul"
ADDR_DEBTOR = "0 Demo-gil, Sample-si, Gyeonggi-do"

# --- Colors -----------------------------------------------------------------
WHITE = (255, 255, 255)
INK = (17, 24, 39)
GRAY = (107, 114, 128)
LIGHT_GRAY = (150, 156, 166)
BAND_RED = (200, 30, 30)
CHAT_BG = (236, 240, 245)
BUBBLE_IN = (255, 255, 255)
BUBBLE_OUT = (76, 95, 213)       # DemoTalk indigo (sent)
DIVIDER_PILL = (218, 223, 231)
BANK_NAVY = (31, 59, 115)
OK_GREEN = (22, 163, 74)
PAPER = (253, 252, 248)
SIG_INK = (30, 42, 120)
SEAL_RED = (198, 40, 40)


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

def _first_font(candidates: Sequence[Path], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    raise FileNotFoundError(f"no font found among {candidates}")


def ui(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    names = {"regular": ["segoeui.ttf"], "semibold": ["seguisb.ttf", "segoeuib.ttf"],
             "bold": ["segoeuib.ttf"]}[weight]
    repo = REPO_FONTS / ("NanumGothic-Regular.ttf" if weight == "regular"
                         else "NanumGothic-Bold.ttf")
    return _first_font([WIN_FONTS / n for n in names] + [repo], size)


def serif(size: int, style: str = "regular") -> ImageFont.FreeTypeFont:
    # Cambria/Times have lining figures (Georgia's old-style "0" looks like
    # a lowercase "o", which a reader can misread inside phone/ID numbers).
    names = {"regular": ["cambria.ttc", "times.ttf"],
             "bold": ["cambriab.ttf", "timesbd.ttf"],
             "italic": ["cambriai.ttf", "timesi.ttf"]}[style]
    repo = REPO_FONTS / ("NanumGothic-Bold.ttf" if style == "bold"
                         else "NanumGothic-Regular.ttf")
    return _first_font([WIN_FONTS / n for n in names] + [repo], size)


def script(size: int, which: int = 0) -> ImageFont.FreeTypeFont:
    order = (["segoesc.ttf", "LHANDW.TTF", "Inkfree.ttf"] if which == 0
             else ["BRUSHSCI.TTF", "segoesc.ttf", "Inkfree.ttf"])
    return _first_font([WIN_FONTS / n for n in order]
                       + [REPO_FONTS / "NanumGothic-Regular.ttf"], size)


def text_w(draw: ImageDraw.ImageDraw, text: str, fnt) -> float:
    return float(draw.textlength(text, font=fnt))


def draw_band(img: Image.Image) -> None:
    """Red top band with the visible SAMPLE / DEMO mark."""
    d = ImageDraw.Draw(img)
    w = img.size[0]
    d.rectangle([0, 0, w - 1, BAND_H - 1], fill=BAND_RED)
    main = "SAMPLE / DEMO"
    sub = "  ·  synthetic evidence, fictional people"
    f_main, f_sub = ui(30, "bold"), ui(24)
    total = text_w(d, main, f_main) + text_w(d, sub, f_sub)
    x = (w - total) / 2
    d.text((x, 13), main, font=f_main, fill=WHITE)
    d.text((x + text_w(d, main, f_main), 19), sub, font=f_sub, fill=WHITE)


def save_png(img: Image.Image, path: Path) -> None:
    img.save(path, optimize=True)  # no metadata -> deterministic bytes


# ---------------------------------------------------------------------------
# DemoTalk chat capture
# ---------------------------------------------------------------------------

STATUS_TOP = BAND_H
STATUS_H = 64
APPBAR_H = 152
CHAT_TOP = STATUS_TOP + STATUS_H + APPBAR_H
INPUT_H = 140

F_MSG = 40
LINE_H = 54
MAX_TEXT_W = 690
PAD_X, PAD_Y = 32, 20
SIDE_MARGIN = 36
AVATAR_R = 30
LEFT_BUBBLE_X = SIDE_MARGIN + AVATAR_R * 2 + 18


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_w: int) -> List[str]:
    lines: List[str] = []
    cur = ""
    for word in text.split():
        trial = word if not cur else f"{cur} {word}"
        if text_w(draw, trial, fnt) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def draw_avatar(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    """Default profile picture: a plain silhouette (no initials to misread
    as a speaker name, no face features)."""
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(232, 145, 88))
    hr = int(r * 0.36)
    d.ellipse([cx - hr, cy - int(r * 0.58), cx + hr, cy - int(r * 0.58) + 2 * hr],
              fill=(253, 226, 204))
    d.pieslice([cx - int(r * 0.66), cy + int(r * 0.12), cx + int(r * 0.66),
                cy + int(r * 1.32)], start=180, end=360, fill=(253, 226, 204))


def tile_edges(width: int, height: int) -> List[int]:
    """Horizontal cut lines of the product reader's tiles for this size.

    Mirrors backend/app/agents/reader.py plan_tiles (near-square tiles,
    10% overlap, at most 8 tiles). Chat bubbles are kept off these lines
    so no tile sees half a bubble (the reader would return a fragment).
    """
    if height / width <= 1.0:
        return []
    tile_h = width
    min_overlap = tile_h * 0.10
    count = max(2, math.ceil((height - min_overlap) / (tile_h - min_overlap)))
    while count > 8 and tile_h < height:
        tile_h = min(height, math.ceil(tile_h * 1.5))
        min_overlap = tile_h * 0.10
        count = max(2, math.ceil((height - min_overlap) / (tile_h - min_overlap)))
    edges = set()
    for i in range(count):
        top = round(i * (height - tile_h) / (count - 1))
        if i > 0:
            edges.add(top)
        if i < count - 1:
            edges.add(top + tile_h)
    return sorted(edges)


def draw_status_and_appbar(img: Image.Image, contact: str, initials: str) -> None:
    d = ImageDraw.Draw(img)
    d.rectangle([0, STATUS_TOP, W, CHAT_TOP - 1], fill=WHITE)
    # Status bar: clock, signal, wifi, battery (plain shapes).
    sy = STATUS_TOP + 14
    d.text((56, sy), "9:41", font=ui(30, "semibold"), fill=INK)
    bx = 862
    for i in range(4):
        h = 10 + i * 6
        d.rounded_rectangle([bx + i * 12, sy + 30 - h, bx + i * 12 + 7, sy + 30],
                            radius=2, fill=INK)
    cx, cy = 938, sy + 32
    for r in (26, 18, 10):
        d.arc([cx - r, cy - r, cx + r, cy + r], start=225, end=315, fill=INK, width=4)
    d.ellipse([cx - 3, cy - 5, cx + 3, cy + 1], fill=INK)
    d.rounded_rectangle([972, sy + 6, 1022, sy + 30], radius=6, outline=INK, width=3)
    d.rectangle([977, sy + 11, 1008, sy + 25], fill=INK)
    d.rounded_rectangle([1024, sy + 13, 1029, sy + 23], radius=2, fill=INK)
    # App bar: back chevron, avatar, contact name, app name, icons.
    ay = STATUS_TOP + STATUS_H
    mid = ay + APPBAR_H // 2
    d.line([(60, mid - 24), (40, mid), (60, mid + 24)], fill=INK, width=5, joint="curve")
    draw_avatar(d, 136, mid, 44)
    d.text((204, mid - 46), contact, font=ui(36, "bold"), fill=INK)
    d.ellipse([206, mid + 16, 220, mid + 30], fill=OK_GREEN)
    d.text((230, mid + 6), f"{APP}  ·  online", font=ui(26), fill=GRAY)
    # Search + menu icons.
    d.ellipse([918, mid - 22, 954, mid + 14], outline=INK, width=4)
    d.line([(950, mid + 10), (966, mid + 26)], fill=INK, width=5)
    for k in (-16, 0, 16):
        d.ellipse([1022, mid + k - 4, 1030, mid + k + 4], fill=INK)
    d.line([(0, CHAT_TOP - 1), (W, CHAT_TOP - 1)], fill=(222, 226, 232), width=2)


def draw_input_bar(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    h = img.size[1]
    top = h - INPUT_H
    d.rectangle([0, top, W, h], fill=WHITE)
    d.line([(0, top), (W, top)], fill=(222, 226, 232), width=2)
    mid = top + INPUT_H // 2
    d.ellipse([36, mid - 30, 96, mid + 30], outline=GRAY, width=4)
    d.line([(66, mid - 14), (66, mid + 14)], fill=GRAY, width=4)
    d.line([(52, mid), (80, mid)], fill=GRAY, width=4)
    d.rounded_rectangle([116, mid - 40, 940, mid + 40], radius=40, fill=(241, 243, 246))
    d.text((148, mid - 22), "Message", font=ui(32), fill=LIGHT_GRAY)
    d.ellipse([962, mid - 40, 1042, mid + 40], fill=BUBBLE_OUT)
    d.polygon([(988, mid - 20), (1022, mid), (988, mid + 20), (994, mid)], fill=WHITE)


# Chat blocks: ("day", "Monday, March 9, 2026")
#              ("msg", "in" | "out", "10:12 AM" | None, text)

def layout_chat(draw: ImageDraw.ImageDraw, blocks: Sequence[tuple],
                contact: str) -> Tuple[List[dict], int]:
    f_msg = ui(F_MSG)
    out: List[dict] = []
    y = CHAT_TOP + 28
    prev: Optional[str] = None
    for blk in blocks:
        if blk[0] == "day":
            y += 18 if prev is not None else 0
            out.append({"type": "day", "text": blk[1], "y": y})
            y += 56 + 30
            prev = "day"
            continue
        _, side, when, text = blk
        lines = wrap(draw, text, f_msg, MAX_TEXT_W)
        tw = max(text_w(draw, ln, f_msg) for ln in lines)
        bw = int(math.ceil(tw)) + PAD_X * 2
        bh = len(lines) * LINE_H + PAD_Y * 2
        first_in_group = prev != side
        if prev in ("in", "out") and first_in_group:
            y += 22
        name_h = 38 if (side == "in" and first_in_group) else 0
        by = y + name_h
        bx = LEFT_BUBBLE_X if side == "in" else W - SIDE_MARGIN - bw
        out.append({"type": "msg", "side": side, "when": when, "lines": lines,
                    "x": bx, "y": by, "w": bw, "h": bh,
                    "avatar": side == "in" and first_in_group,
                    "name": contact if name_h else None,
                    "turn": first_in_group})
        y = by + bh + 12
        prev = side
    return out, y


def render_chat(path: Path, blocks: Sequence[tuple], contact: str,
                initials: str, height: Optional[int] = None,
                min_height: int = 0) -> Tuple[int, int]:
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    laid, end_y = layout_chat(probe, blocks, contact)
    natural = end_y + 24 + INPUT_H
    if height is None:
        height = max(natural, min_height)
    if natural > height:
        raise AssertionError(f"chat overflow: needs {natural}px, has {height}px")
    print(f"  {path.name}: natural height {natural}px")
    # Spread spare space only where the speaker changes or a new day starts
    # (same-speaker bubbles stay together), and push any bubble or day pill
    # that would straddle a reader tile edge to just below that edge.
    edges = tile_edges(W, height)
    base_y = [item["y"] for item in laid]
    breaks = [i for i, item in enumerate(laid)
              if i > 0 and (item["type"] == "day" or item.get("turn"))]
    limit = height - INPUT_H - 24

    def span(item: dict, y: float) -> Tuple[float, float]:
        if item["type"] == "day":
            return y - 6, y + 58
        top = y - 40 if item["name"] else y
        return top - 6, y + item["h"] + 6

    spare = float(height - natural)
    for _ in range(40):
        step = spare / len(breaks) if (breaks and spare > 0) else 0.0
        shift = 0.0
        placed = []
        for i, item in enumerate(laid):
            if i in breaks:
                shift += step
            y = base_y[i] + shift
            moved = True
            while moved:
                moved = False
                top, bottom = span(item, y)
                for e in edges:
                    if top < e < bottom:
                        delta = e - top + 2
                        y += delta
                        shift += delta
                        moved = True
            placed.append(int(round(y)))
        last = laid[-1]
        end = placed[-1] + (58 if last["type"] == "day" else last["h"])
        if end <= limit:
            break
        spare -= (end - limit)
    else:
        raise AssertionError(f"{path.name}: cannot keep bubbles off tile edges")
    if step > 110:
        raise AssertionError(f"too much spare space per gap: {step:.0f}px")
    for item, y in zip(laid, placed):
        item["y"] = y
    img = Image.new("RGB", (W, height), CHAT_BG)
    d = ImageDraw.Draw(img)
    f_msg, f_name, f_time, f_day = ui(F_MSG), ui(26), ui(24), ui(26, "semibold")
    for item in laid:
        if item["type"] == "day":
            tw = text_w(d, item["text"], f_day)
            px1, px2 = (W - tw) / 2 - 24, (W + tw) / 2 + 24
            d.rounded_rectangle([px1, item["y"], px2, item["y"] + 52], radius=26,
                                fill=DIVIDER_PILL)
            d.text(((W - tw) / 2, item["y"] + 10), item["text"], font=f_day,
                   fill=(84, 92, 106))
            continue
        x, y, w, h = item["x"], item["y"], item["w"], item["h"]
        incoming = item["side"] == "in"
        if item["avatar"]:
            draw_avatar(d, SIDE_MARGIN + AVATAR_R, y + AVATAR_R, AVATAR_R)
        if item["name"]:
            d.text((x + 6, y - 38), item["name"], font=f_name, fill=GRAY)
        d.rounded_rectangle([x, y, x + w, y + h], radius=30,
                            fill=BUBBLE_IN if incoming else BUBBLE_OUT)
        color = INK if incoming else WHITE
        for i, ln in enumerate(item["lines"]):
            d.text((x + PAD_X, y + PAD_Y + i * LINE_H + 2), ln, font=f_msg, fill=color)
        if item["when"]:
            tw = text_w(d, item["when"], f_time)
            tx = x + w + 12 if incoming else x - 12 - tw
            d.text((tx, y + h - 32), item["when"], font=f_time, fill=(138, 145, 156))
    draw_status_and_appbar(img, contact, initials)
    draw_input_bar(img)
    draw_band(img)
    save_png(img, path)
    return W, height


CHAT_01: List[tuple] = [
    ("day", "Monday, March 9, 2026"),
    ("msg", "in", "8:12 PM",
     "Hey Jordan, sorry to bother you. Could you lend me 5,000,000 won? "
     "My rent and a hospital bill are due."),
    ("msg", "out", "8:20 PM", "Wow, that's a lot. When could you pay it back?"),
    ("msg", "in", "8:23 PM",
     "I'll pay you back the full 5,000,000 won by April 10. I promise."),
    ("msg", "out", "8:31 PM", "OK. I'll send 5,000,000 won tomorrow."),
    ("day", "Tuesday, March 10, 2026"),
    ("msg", "out", "9:14 AM", "Just sent it. Please check your account."),
    ("msg", "in", "9:20 AM", "Got it. Thank you so much, Jordan!"),
]

CHAT_02: List[tuple] = [
    ("day", "Monday, April 20, 2026"),
    ("msg", "out", "10:05 AM",
     "Hi Alex, it's already April 20. The 5,000,000 won was due on April 10."),
    ("msg", "in", None, "I'm so sorry, Jordan. Work has been crazy."),
    ("msg", "in", "11:41 AM", "I'll pay you back by April 25. I promise."),
    ("msg", "out", "11:52 AM", "OK. Please don't forget this time."),
    ("day", "Sunday, April 26, 2026"),
    ("msg", "out", "9:15 AM", "Alex, April 25 has passed. When can you send the money?"),
    ("msg", "out", "6:30 PM", "Please reply when you see this."),
    ("msg", "out", "6:31 PM", "I really need that money back, Alex."),
    ("msg", "in", None, "Sorry, I was out all day. My car broke down too."),
    ("msg", "in", "9:03 PM", "I can send part of it on May 1, and the rest soon after."),
    ("msg", "out", "9:10 PM", "OK. I'll check on May 1."),
    ("day", "Friday, May 1, 2026"),
    ("msg", "in", "2:14 PM", "I sent 1,000,000 won today. Please check."),
    ("msg", "out", None, "Got it, I received 1,000,000 won. Thanks."),
    ("msg", "out", "2:31 PM", "When can you pay the rest?"),
    ("msg", "in", "3:05 PM", "I'll pay back all of the rest by May 20."),
    ("msg", "out", "3:12 PM", "OK, May 20. I'm counting on you."),
    ("day", "Monday, May 11, 2026"),
    ("msg", "out", "7:45 PM", "Hi Alex, just checking. Are we still OK for May 20?"),
    ("msg", "in", None, "Yes, May 20."),
    ("msg", "in", "8:02 PM", "Don't worry, I'll pay the rest then."),
    ("msg", "out", "8:05 PM", "Thanks. Talk soon."),
    ("day", "Thursday, May 21, 2026"),
    ("msg", "out", None, "Hi Alex, May 20 has passed and I haven't received the rest yet."),
    ("msg", "out", "10:01 AM", "Please let me know when you can send it."),
    ("msg", "in", None, "I know. I'm really sorry. Please give me a little more time."),
    ("msg", "in", "8:48 PM", "I will definitely pay the rest. I promise."),
    ("day", "Friday, May 29, 2026"),
    ("msg", "out", "9:20 AM",
     "Alex, I still haven't received the rest. Please send it as soon as possible."),
]


# ---------------------------------------------------------------------------
# SAMPLE Bank receipts
# ---------------------------------------------------------------------------

RECEIPT_H = 1060  # h/w < 1, so the reader reads each receipt in one piece

# Layout note: each FROM/TO section holds one row, the holder's name on the
# left and the full account number on the right, and the two account
# numbers sit ~160px apart with nothing else in that column between them.
# Reader boxes can land 30-90px off the true line; the product snaps a PII
# box to the nearest text line of similar width in the same columns, so an
# isolated account number is snapped correctly. (A dense right-aligned
# table made it mask the line above the account number in live run 1.)


def render_receipt(path: Path, title: str, amount: str, when: Tuple[str, str],
                   cards: Sequence[Tuple[str, str, str]], memo: str) -> dict:
    img = Image.new("RGB", (W, RECEIPT_H), WHITE)
    d = ImageDraw.Draw(img)
    draw_band(img)
    boxes: dict = {}
    # Bank header.
    top = BAND_H
    d.rectangle([0, top, W, top + 112], fill=BANK_NAVY)
    d.rounded_rectangle([48, top + 24, 112, top + 88], radius=16, fill=WHITE)
    f_logo = ui(44, "bold")
    d.text((80 - text_w(d, "S", f_logo) / 2, top + 26), "S", font=f_logo, fill=BANK_NAVY)
    d.text((132, top + 28), BANK, font=ui(40, "bold"), fill=WHITE)
    f_tag = ui(26)
    tag = "Transfer Receipt"
    d.text((W - 48 - text_w(d, tag, f_tag), top + 42), tag, font=f_tag,
           fill=(206, 216, 238))
    # Status block: icon, title, amount, date and time (centered).
    cy = top + 158
    d.ellipse([540 - 34, cy - 34, 540 + 34, cy + 34], fill=OK_GREEN)
    d.line([(524, cy + 2), (536, cy + 14), (558, cy - 11)], fill=WHITE, width=7,
           joint="curve")
    f_title, f_amt, f_when = ui(34, "semibold"), ui(60, "bold"), ui(28, "semibold")
    d.text(((W - text_w(d, title, f_title)) / 2, cy + 44), title, font=f_title, fill=INK)
    d.text(((W - text_w(d, amount, f_amt)) / 2, cy + 86), amount, font=f_amt, fill=INK)
    day, clock = when
    gap = 44
    total = text_w(d, day, f_when) + gap + text_w(d, clock, f_when)
    wx = (W - total) / 2
    wy = cy + 178
    d.text((wx, wy), day, font=f_when, fill=(55, 65, 81))
    dot_x = wx + text_w(d, day, f_when) + gap / 2
    d.ellipse([dot_x - 3, wy + 18, dot_x + 3, wy + 24], fill=LIGHT_GRAY)
    d.text((dot_x + gap / 2, wy), clock, font=f_when, fill=(55, 65, 81))
    assert wx + total < 740, "date line must stay left of the account column"
    line_y = wy + 60
    for x in range(48, W - 48, 22):
        d.line([(x, line_y), (x + 12, line_y)], fill=(203, 208, 216), width=2)
    # FROM / TO cards: name left, account number right, same row.
    f_head, f_name, f_acct = ui(24, "bold"), ui(32, "semibold"), ui(32, "semibold")
    y0 = line_y + 20
    for i, (head, name, account) in enumerate(cards):
        # Flat sections (no rounded card fill: the product's SAM step reads
        # a filled rounded box as a chat bubble and then treats the account
        # number as text inside a message).
        if i:
            d.line([(56, y0 - 33), (W - 56, y0 - 33)], fill=(229, 231, 235), width=2)
        d.text((68, y0 + 16), head, font=f_head, fill=GRAY)
        ry = y0 + 62
        d.text((68, ry), name, font=f_name, fill=INK)
        boxes[(head, "name")] = list(d.textbbox((68, ry), name, font=f_name))
        ax = W - 68 - text_w(d, account, f_acct)
        d.text((ax, ry), account, font=f_acct, fill=INK)
        boxes[(head, "account")] = list(d.textbbox((ax, ry), account, font=f_acct))
        assert boxes[(head, "name")][2] + 120 < boxes[(head, "account")][0]
        y0 += 124 + 66
    # Memo row, well below the last account number.
    my = y0 + 34
    d.text((68, my + 3), "Memo", font=ui(28), fill=GRAY)
    d.text((W - 68 - text_w(d, memo, f_name), my), memo, font=f_name, fill=INK)
    note = f"{BANK} is a fictional bank. This receipt is synthetic demo data."
    f_note = ui(22)
    assert my + 60 < RECEIPT_H - 60, f"receipt rows overflow: {my}"
    d.text(((W - text_w(d, note, f_note)) / 2, RECEIPT_H - 50), note, font=f_note,
           fill=LIGHT_GRAY)
    save_png(img, path)
    return {"size": (W, RECEIPT_H), "boxes": boxes}


LOAN_RECEIPT = dict(
    title="Transfer completed", amount="KRW 5,000,000", when=("2026-03-10", "09:12 KST"),
    cards=[(f"FROM  ·  {BANK}", CREDITOR, ACCT_CREDITOR),
           (f"TO  ·  {BANK}", DEBTOR, ACCT_DEBTOR)],
    memo="Loan")

REPAY_RECEIPT = dict(
    title="Deposit received", amount="KRW 1,000,000", when=("2026-05-01", "14:13 KST"),
    cards=[(f"FROM  ·  {BANK}", DEBTOR, ACCT_DEBTOR),
           (f"TO  ·  {BANK}", CREDITOR, ACCT_CREDITOR)],
    memo="Repayment (part)")


# ---------------------------------------------------------------------------
# IOU (paper document with signatures and a red seal)
# ---------------------------------------------------------------------------

IOU_H = 1800


def _signature(text: str, which: int, size: int, angle: float,
               seed: int) -> Image.Image:
    """Handwriting-like signature on a transparent layer with a flourish."""
    fnt = script(size, which)
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    box = probe.textbbox((0, 0), text, font=fnt)
    tw, th = box[2] - box[0], box[3] - box[1]
    layer = Image.new("RGBA", (tw + 80, th + 70), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text((30 - box[0], 18 - box[1]), text, font=fnt, fill=SIG_INK + (255,))
    rng = random.Random(seed)
    pts = []
    for i in range(41):
        t = i / 40
        x = 24 + t * (tw + 30)
        y = th + 34 + 10 * math.sin(t * math.pi * 1.6 + rng.random() * 0.2) - 14 * t
        pts.append((x, y))
    d.line(pts, fill=SIG_INK + (255,), width=3, joint="curve")
    return layer.rotate(angle, resample=Image.BICUBIC, expand=True)


def _scribble(width: int, angle: float, seed: int) -> Image.Image:
    """Illegible looped signature (no readable letters, so the reader does
    not pick it up as another spelling of the lender's name)."""
    rng = random.Random(seed)
    layer = Image.new("RGBA", (width + 80, 150), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    loops = 7
    pts = []
    steps = 360
    for i in range(steps + 1):
        th = i / steps * loops * 2 * math.pi
        t = i / steps
        heights = (1.25, 0.55, 0.95, 0.45, 0.8, 0.5, 0.65, 0.4)
        k = th / (2 * math.pi)
        lo = heights[min(int(k), len(heights) - 1)]
        hi = heights[min(int(k) + 1, len(heights) - 1)]
        frac = k - int(k)
        amp = 30 * (lo + (hi - lo) * frac) * (1.0 + 0.05 * rng.random())
        x = 24 + (width - 40) * t - 9 * math.sin(th)
        y = 70 - amp * math.cos(th) * (0.75 if i % 2 else 0.78)
        pts.append((x + 0.28 * (70 - y), y))
    d.line(pts, fill=SIG_INK + (255,), width=3, joint="curve")
    tail = [(24 + (width - 40) * (0.05 + 0.95 * k / 30),
             112 - 8 * math.sin(k / 30 * math.pi * 1.4) - 10 * k / 30) for k in range(31)]
    d.line(tail, fill=SIG_INK + (255,), width=3, joint="curve")
    d.line([(36, 40), (52, 104)], fill=SIG_INK + (255,), width=3)
    return layer.rotate(angle, resample=Image.BICUBIC, expand=True)


def _seal(lines: Sequence[str], size: int, angle: float, seed: int) -> Image.Image:
    """Round red personal seal with slightly uneven ink."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    ink = SEAL_RED + (230,)
    d.ellipse([4, 4, size - 5, size - 5], outline=ink, width=9)
    d.ellipse([20, 20, size - 21, size - 21], outline=ink, width=3)
    f = ui(int(size * 0.22), "bold")
    total_h = len(lines) * int(size * 0.24)
    y = (size - total_h) / 2 - 4
    for ln in lines:
        d.text(((size - text_w(d, ln, f)) / 2, y), ln, font=f, fill=ink)
        y += int(size * 0.24)
    rng = random.Random(seed)
    px = layer.load()
    for _ in range(size * size // 9):
        x, yy = rng.randrange(size), rng.randrange(size)
        r, g, b, a = px[x, yy]
        if a:
            px[x, yy] = (r, g, b, int(a * rng.choice((0.35, 0.6, 0.8))))
    return layer.rotate(angle, resample=Image.BICUBIC, expand=True)


def render_iou(path: Path) -> Tuple[int, int]:
    img = Image.new("RGB", (W, IOU_H), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle([28, BAND_H + 24, W - 29, IOU_H - 29], outline=(196, 190, 174), width=2)
    d.rectangle([36, BAND_H + 32, W - 37, IOU_H - 37], outline=(220, 215, 202), width=1)
    left, val_x, right = 84, 380, W - 84
    f_title, f_sub = serif(64, "bold"), serif(30, "italic")
    y = BAND_H + 52
    d.text(((W - text_w(d, "IOU", f_title)) / 2, y), "IOU", font=f_title, fill=INK)
    y += 84
    sub = "Personal Loan Note"
    d.text(((W - text_w(d, sub, f_sub)) / 2, y), sub, font=f_sub, fill=(70, 70, 70))
    y += 66
    f_body = serif(28)
    body = (f"I, {DEBTOR_IOU}, received the amount below from {CREDITOR} "
            "as a personal loan and will repay it in full by the due date below.")
    for ln in wrap(d, body, f_body, right - left):
        d.text((left, y), ln, font=f_body, fill=INK)
        y += 42
    y += 22

    f_sec, f_label, f_value = serif(24, "bold"), serif(27), serif(30)

    def section(title: str, rows: Sequence[Tuple[str, str]], y0: int) -> int:
        d.text((left, y0), title, font=f_sec, fill=(90, 84, 70))
        d.line([(left, y0 + 36), (right, y0 + 36)], fill=(196, 190, 174), width=2)
        yy = y0 + 54
        for label, value in rows:
            d.text((left, yy + 3), label, font=f_label, fill=(88, 88, 88))
            d.text((val_x, yy), value, font=f_value, fill=INK)
            yy += 56
        return yy + 14

    y = section("LOAN TERMS", [
        ("Amount", "KRW 5,000,000"),
        ("Amount in words", "Five million Korean won"),
        ("Loan date", "March 10, 2026"),
        ("Due date", "April 10, 2026"),
        ("Interest", "None"),
    ], y)
    y = section("LENDER", [
        ("Name", CREDITOR),
        ("Address", ADDR_CREDITOR),
        ("Phone", PHONE_CREDITOR),
    ], y)
    y = section("BORROWER", [
        ("Name", DEBTOR_IOU),
        ("Address", ADDR_DEBTOR),
        ("Phone", PHONE_DEBTOR),
        ("ID number", ID_DEBTOR),
    ], y)
    signed = "Signed in Seoul on March 10, 2026."
    d.text((left, y + 4), signed, font=serif(28, "italic"), fill=INK)
    y += 64

    # Signature rows: label on the left, cursive signature to its right on a
    # light line (the product looks for signature ink right of a
    # "signature" label), and the red seal right of the borrower's name.
    # The lender signs with an illegible scribble; the borrower's cursive
    # "Alex J. Kim" matches the IOU spelling (the deliberate name variant).
    rows = [("Lender signature", None, 0, 0, -3.0, 11),
            ("Borrower signature", "Alex J. Kim", 1, 62, 4.0, 23)]
    label_top = y + 40
    sig_box = None
    for label, name, which, size, angle, seed in rows:
        # Label gray stays lighter than the product's signature-ink threshold.
        d.text((left, label_top), label, font=f_label, fill=(128, 128, 128))
        sig = (_scribble(330, angle, seed) if name is None
               else _signature(name, which, size, angle, seed))
        ink = sig.getchannel("A").getbbox()
        sx = val_x + 10 - ink[0]
        sy = label_top - 6 - ink[1]
        line_y = sy + ink[3] - 12
        d.line([(val_x, line_y), (860, line_y)], fill=(176, 176, 176), width=2)
        img.paste(sig, (sx, sy), sig)
        sig_box = [sx + ink[0], sy + ink[1], sx + ink[2], sy + ink[3]]
        assert sig_box[2] < 860, f"signature too wide: {sig_box}"
        label_top += 210
    seal = _seal(["ALEX", "KIM"], 160, -8.0, 7)
    seal_cy = (sig_box[1] + sig_box[3]) // 2
    img.paste(seal, (872, seal_cy - seal.size[1] // 2), seal)
    assert sig_box[3] < IOU_H - 110, f"IOU content overflows: {sig_box}"

    foot = "SAMPLE / DEMO  ·  fictional document for the ClaimBack-AI demo"
    f_foot = ui(22)
    d.text(((W - text_w(d, foot, f_foot)) / 2, IOU_H - 82), foot, font=f_foot,
           fill=LIGHT_GRAY)
    draw_band(img)
    save_png(img, path)
    return W, IOU_H


# ---------------------------------------------------------------------------

def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    out = HERE
    made = []
    made.append(("en_chat_01.png",
                 render_chat(out / "en_chat_01.png", CHAT_01, DEBTOR, "AK", height=1920)))
    made.append(("en_chat_02_tall.png",
                 render_chat(out / "en_chat_02_tall.png", CHAT_02, DEBTOR, "AK",
                             min_height=5600)))
    made.append(("en_transfer_loan.png",
                 render_receipt(out / "en_transfer_loan.png", **LOAN_RECEIPT)["size"]))
    made.append(("en_transfer_repay.png",
                 render_receipt(out / "en_transfer_repay.png", **REPAY_RECEIPT)["size"]))
    made.append(("en_iou.png", render_iou(out / "en_iou.png")))
    for name, (w, h) in made:
        p = out / name
        print(f"{name}: {w}x{h}, {p.stat().st_size} bytes, sha256 {sha256_of(p)[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
