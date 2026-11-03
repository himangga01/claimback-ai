"""Generate M0 synthetic spike inputs (SAMPLE only, no real brands/people).

Outputs to backend/tests/fixtures/spike_inputs/:
  chat_capture.png, transfer_receipt.png, iou_2page.pdf,
  iou_page1.png, iou_page2.png, chat_scroll.mp4, truth.json

truth.json holds actual pixel boxes for scoring only; never pass it to models.
Run: .\\.venv\\Scripts\\python.exe tools\\make_spike_inputs.py
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "backend" / "tests" / "fixtures" / "spike_inputs"
FONT_DIR = ROOT / "backend" / "app" / "templates" / "fonts"
FONT_REG = FONT_DIR / "NanumGothic-Regular.ttf"
FONT_BOLD = FONT_DIR / "NanumGothic-Bold.ttf"

CREDITOR = "김샘플(SAMPLE)"
DEBTOR = "이샘플(SAMPLE)"
BANK = "샘플은행"
APP = "샘플톡"
PHONE = "010-0000-0000"
ACCOUNT_MASKED = "****-**-000000"
AMOUNT = "5,000,000원"
AMOUNT_NORM = "5000000"
DATE_LOAN = "2026-01-01"
DATE_DUE = "2026-04-10"
WATERMARK = "SAMPLE / 데모용"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else FONT_REG
    if not path.exists():
        return ImageFont.load_default()
    return ImageFont.truetype(str(path), size)


def draw_watermark(base: Image.Image, text: str = WATERMARK) -> None:
    draw = ImageDraw.Draw(base, "RGBA")
    w, h = base.size
    fnt = font(max(18, w // 22), bold=True)
    # Top banner.
    draw.rectangle([0, 0, w, 34], fill=(200, 30, 30, 255))
    draw.text((10, 6), f"{APP}  {text}", font=font(18, True), fill=(255, 255, 255, 255))
    # Diagonal light watermark.
    overlay = Image.new("RGBA", base.size, (255, 255, 255, 0))
    over = ImageDraw.Draw(overlay)
    diag = Image.new("RGBA", (w * 2, 80), (255, 255, 255, 0))
    dd = ImageDraw.Draw(diag)
    dd.text((10, 10), text * 3, font=fnt, fill=(200, 30, 30, 40))
    rot = diag.rotate(24, expand=True)
    overlay.alpha_composite(Image.new("RGBA", base.size, (255, 255, 255, 0)))
    base.paste(Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB"))


def substr_box(draw: ImageDraw.ImageDraw, origin, line: str, substr: str,
               fnt: ImageFont.FreeTypeFont) -> list[int] | None:
    idx = line.find(substr)
    if idx < 0:
        return None
    x0, y0 = origin
    try:
        prefix_w = float(draw.textlength(line[:idx], font=fnt))
        sub_w = float(draw.textlength(substr, font=fnt))
    except Exception:
        prefix_w = fnt.getlength(line[:idx])
        sub_w = fnt.getlength(substr)
    bbox = draw.textbbox((0, 0), "가Hgj", font=fnt)
    line_h = bbox[3] - bbox[1]
    x1 = int(round(x0 + prefix_w))
    x2 = int(round(x0 + prefix_w + sub_w))
    return [x1, int(y0), max(x1 + 1, x2), int(y0 + line_h)]


def make_chat() -> dict:
    W, H = 640, 960
    img = Image.new("RGB", (W, H), (176, 204, 226))
    draw = ImageDraw.Draw(img)
    draw_watermark(img)
    fnt = font(21)
    bubbles = [
        {"speaker": DEBTOR, "side": "left",
         "text": f"형, {AMOUNT}만 빌려줄 수 있어?"},
        {"speaker": CREDITOR, "side": "right",
         "text": f"응, 내일 보내줄게. {DATE_LOAN}에 송금할게."},
        {"speaker": DEBTOR, "side": "left",
         "text": f"고마워! {DATE_DUE}까지 꼭 갚겠다!"},
        {"speaker": CREDITOR, "side": "right",
         "text": f"{DATE_DUE} 확인했어. {AMOUNT} 맞지?"},
        {"speaker": DEBTOR, "side": "left",
         "text": f"응, {PHONE}으로 연락줘."},
    ]
    truth_bubbles = []
    truth_amounts: list[dict] = []
    truth_dates: list[dict] = []
    y = 60
    pad = 12
    max_bubble_w = 470
    line_gap = 6
    for i, b in enumerate(bubbles):
        text = b["text"]
        # Single line layout (all messages fit in max width at size 21).
        tw = float(draw.textlength(text, font=fnt))
        bbox = draw.textbbox((0, 0), "가Hgj", font=fnt)
        line_h = bbox[3] - bbox[1]
        bw = min(max_bubble_w, int(tw + pad * 2))
        bh = line_h + pad * 2
        if b["side"] == "left":
            x = 16
            fill = (255, 255, 255)
        else:
            x = W - 16 - bw
            fill = (255, 235, 170)
        draw.rounded_rectangle([x, y, x + bw, y + bh], radius=12, fill=fill,
                               outline=(180, 180, 180))
        tx, ty = x + pad, y + pad - 2
        draw.text((tx, ty), text, font=fnt, fill=(20, 20, 20))
        truth_bubbles.append({"id": i, "box": [x, y, x + bw, y + bh],
                              "speaker": b["speaker"], "text": text})
        for amt in (AMOUNT,):
            box = substr_box(draw, (tx, ty), text, amt, fnt)
            if box:
                truth_amounts.append({"box": box, "value": amt,
                                      "normalized": AMOUNT_NORM,
                                      "bubble_id": i})
        for dt, norm in ((DATE_LOAN, DATE_LOAN), (DATE_DUE, DATE_DUE)):
            box = substr_box(draw, (tx, ty), text, dt, fnt)
            if box:
                truth_dates.append({"box": box, "value": dt, "normalized": norm,
                                    "bubble_id": i})
        # Speaker tag above bubble.
        draw.text((x + 2, y - 20), b["speaker"], font=font(14),
                  fill=(60, 60, 60))
        y += bh + 34
    # Footer note.
    draw.text((16, H - 30), f"{PHONE}  {WATERMARK}", font=font(15),
              fill=(80, 80, 80))
    out = OUT_DIR / "chat_capture.png"
    img.save(out)
    return {"file": out.name, "size": [W, H], "bubbles": truth_bubbles,
            "amounts": truth_amounts, "dates": truth_dates}


def make_receipt() -> dict:
    W, H = 640, 800
    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw_watermark(img)
    fnt_title = font(30, True)
    fnt = font(22)
    fnt_label = font(19)
    draw.text((24, 60), BANK, font=fnt_title, fill=(20, 60, 120))
    draw.text((24, 100), "계좌이체확인증", font=font(24, True), fill=(20, 20, 20))
    draw.line([24, 140, W - 24, 140], fill=(20, 60, 120), width=3)
    rows = [
        ("보낸 사람", CREDITOR),
        ("받는 사람", DEBTOR),
        ("금액", AMOUNT),
        ("이체일", DATE_LOAN),
        ("출금계좌", ACCOUNT_MASKED),
        ("연락처", PHONE),
    ]
    y = 170
    truth_amounts = []
    truth_dates = []
    sender_box = receiver_box = None
    for label, value in rows:
        draw.text((30, y), label, font=fnt_label, fill=(90, 90, 90))
        vx = 190
        draw.text((vx, y - 2), value, font=fnt, fill=(10, 10, 10))
        if value == AMOUNT:
            box = substr_box(draw, (vx, y - 2), value, value, fnt)
            truth_amounts.append({"box": box, "value": value,
                                  "normalized": AMOUNT_NORM})
        if value == DATE_LOAN:
            box = substr_box(draw, (vx, y - 2), value, value, fnt)
            truth_dates.append({"box": box, "value": value, "normalized": value})
        if label == "보낸 사람":
            sender_box = substr_box(draw, (vx, y - 2), value, value, fnt)
        if label == "받는 사람":
            receiver_box = substr_box(draw, (vx, y - 2), value, value, fnt)
        y += 52
    draw.line([24, y + 6, W - 24, y + 6], fill=(200, 200, 200), width=1)
    draw.text((24, y + 16), WATERMARK, font=font(18, True), fill=(200, 30, 30))
    out = OUT_DIR / "transfer_receipt.png"
    img.save(out)
    return {"file": out.name, "size": [W, H], "amounts": truth_amounts,
            "dates": truth_dates,
            "sender": {"box": sender_box, "value": CREDITOR},
            "receiver": {"box": receiver_box, "value": DEBTOR}}


def _signature_stroke(draw: ImageDraw.ImageDraw, box) -> None:
    x1, y1, x2, y2 = box
    pts = []
    steps = 60
    for i in range(steps + 1):
        t = i / steps
        x = x1 + (x2 - x1) * t
        y = (y1 + y2) / 2 + math.sin(t * 9.0) * (y2 - y1) * 0.28
        pts.append((x, y))
    draw.line(pts, fill=(30, 30, 120), width=3)


def make_iou_images() -> dict:
    W, H = 800, 1130
    truths = {}
    for page in (1, 2):
        img = Image.new("RGB", (W, H), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw_watermark(img)
        fnt_title = font(34, True)
        fnt = font(23)
        fnt_small = font(19)
        if page == 1:
            draw.text((40, 70), "차 용 증", font=fnt_title, fill=(10, 10, 10))
            draw.text((40, 120), WATERMARK, font=font(20, True),
                      fill=(200, 30, 30))
            lines = [
                f"채권자: {CREDITOR}",
                f"채무자: {DEBTOR}",
                f"원금: {AMOUNT}",
                f"대여일: {DATE_LOAN}",
                f"변제기: {DATE_DUE}",
                "이자: 없음",
            ]
            y = 190
            amounts, dates = [], []
            for line in lines:
                draw.text((50, y), line, font=fnt, fill=(10, 10, 10))
                for needle, norm, bucket in (
                        (AMOUNT, AMOUNT_NORM, amounts),
                        (DATE_LOAN, DATE_LOAN, dates),
                        (DATE_DUE, DATE_DUE, dates)):
                    box = substr_box(draw, (50, y), line, needle, fnt)
                    if box:
                        bucket.append({"box": box, "value": needle,
                                       "normalized": norm})
                y += 48
            # Signature spot.
            draw.text((50, y + 20), "채무자 서명:", font=fnt, fill=(10, 10, 10))
            sig_box = [250, y + 14, 620, y + 90]
            draw.rectangle(sig_box, outline=(120, 120, 120), width=2)
            _signature_stroke(draw, [sig_box[0] + 12, sig_box[1] + 18,
                                     sig_box[2] - 12, sig_box[3] - 18])
            truths["iou_page1.png"] = {"file": "iou_page1.png", "size": [W, H],
                                       "amounts": amounts, "dates": dates,
                                       "signature": {"box": sig_box}}
        else:
            draw.text((40, 70), "확 인 서", font=fnt_title, fill=(10, 10, 10))
            draw.text((40, 120), WATERMARK, font=font(20, True),
                      fill=(200, 30, 30))
            draw.text((50, 190), f"위 금액 {AMOUNT}을 확인함.", font=fnt,
                      fill=(10, 10, 10))
            draw.text((50, 240), f"작성일: {DATE_LOAN}", font=fnt,
                      fill=(10, 10, 10))
            amounts = [{"box": substr_box(draw, (50, 190),
                                          f"위 금액 {AMOUNT}을 확인함.",
                                          AMOUNT, fnt),
                        "value": AMOUNT, "normalized": AMOUNT_NORM}]
            dates = [{"box": substr_box(draw, (50, 240), f"작성일: {DATE_LOAN}",
                                        DATE_LOAN, fnt),
                      "value": DATE_LOAN, "normalized": DATE_LOAN}]
            # Signature + red stamp.
            draw.text((50, 330), "서명:", font=fnt, fill=(10, 10, 10))
            sig_box = [150, 324, 420, 400]
            draw.rectangle(sig_box, outline=(120, 120, 120), width=2)
            _signature_stroke(draw, [sig_box[0] + 10, sig_box[1] + 14,
                                     sig_box[2] - 10, sig_box[3] - 14])
            stamp_box = [500, 320, 660, 480]
            draw.ellipse(stamp_box, outline=(210, 30, 30), width=6)
            draw.ellipse([stamp_box[0] + 12, stamp_box[1] + 12,
                          stamp_box[2] - 12, stamp_box[3] - 12],
                         outline=(210, 30, 30), width=2)
            sf = font(44, True)
            txt = "샘플"
            tw = float(draw.textlength(txt, font=sf))
            th = draw.textbbox((0, 0), txt, font=sf)
            cx = (stamp_box[0] + stamp_box[2]) / 2 - tw / 2
            cy = (stamp_box[1] + stamp_box[3]) / 2 - (th[3] - th[1]) / 2 - th[1]
            draw.text((cx, cy), txt, font=sf, fill=(210, 30, 30))
            draw.text((50, H - 60), fnt_small and WATERMARK, font=fnt_small,
                      fill=(200, 30, 30))
            truths["iou_page2.png"] = {"file": "iou_page2.png", "size": [W, H],
                                       "amounts": amounts, "dates": dates,
                                       "signature": {"box": sig_box},
                                       "stamp": {"box": stamp_box}}
        out = OUT_DIR / f"iou_page{page}.png"
        img.save(out)
    return truths


def make_iou_pdf() -> dict:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    if FONT_REG.exists():
        pdfmetrics.registerFont(TTFont("Nanum", str(FONT_REG)))
        pdfmetrics.registerFont(TTFont("NanumB", str(FONT_BOLD)))
        reg, bold = "Nanum", "NanumB"
    else:
        reg, bold = "Helvetica", "Helvetica-Bold"
    out = OUT_DIR / "iou_2page.pdf"
    c = canvas.Canvas(str(out), pagesize=A4)
    w, h = A4
    # Page 1.
    c.setFont(bold, 22)
    c.drawString(50, h - 70, "차 용 증")
    c.setFont(bold, 12)
    c.setFillColorRGB(0.8, 0.1, 0.1)
    c.drawString(50, h - 92, WATERMARK)
    c.setFillColorRGB(0, 0, 0)
    c.setFont(reg, 13)
    lines = [f"채권자: {CREDITOR}", f"채무자: {DEBTOR}", f"원금: {AMOUNT}",
             f"대여일: {DATE_LOAN}", f"변제기: {DATE_DUE}", "이자: 없음"]
    y = h - 130
    for line in lines:
        c.drawString(60, y, line)
        y -= 26
    c.drawString(60, y - 10, "채무자 서명:")
    c.rect(180, y - 40, 300, 50, stroke=1, fill=0)
    p = c.beginPath()
    for i in range(61):
        t = i / 60
        x = 195 + 270 * t
        yy = y - 15 + math.sin(t * 9.0) * 7
        if i == 0:
            p.moveTo(x, yy)
        else:
            p.lineTo(x, yy)
    c.setLineWidth(1.5)
    c.setStrokeColorRGB(0.1, 0.1, 0.5)
    c.drawPath(p, stroke=1, fill=0)
    c.setStrokeColorRGB(0, 0, 0)
    c.showPage()
    # Page 2.
    c.setFont(bold, 22)
    c.drawString(50, h - 70, "확 인 서")
    c.setFont(bold, 12)
    c.setFillColorRGB(0.8, 0.1, 0.1)
    c.drawString(50, h - 92, WATERMARK)
    c.setFillColorRGB(0, 0, 0)
    c.setFont(reg, 13)
    c.drawString(60, h - 130, f"위 금액 {AMOUNT}을 확인함.")
    c.drawString(60, h - 156, f"작성일: {DATE_LOAN}")
    c.drawString(60, h - 210, "서명:")
    c.rect(120, h - 250, 200, 50, stroke=1, fill=0)
    c.setStrokeColorRGB(0.82, 0.1, 0.1)
    c.setLineWidth(4)
    c.circle(420, h - 260, 55, stroke=1, fill=0)
    c.setLineWidth(1)
    c.circle(420, h - 260, 45, stroke=1, fill=0)
    c.setFont(bold, 26)
    c.drawCentredString(420, h - 268, "샘플")
    c.showPage()
    c.save()
    return {"file": out.name, "pages": 2, "amounts": [AMOUNT],
            "dates": [DATE_LOAN, DATE_DUE],
            "note": "PDF truth is values only; pixel boxes live in iou_pageN.png"}


def make_video() -> dict:
    src = OUT_DIR / "chat_capture.png"
    img = Image.open(src).convert("RGB")
    # Source for scrolling: width 360.
    sw = 360
    sh = int(img.height * sw / img.width)
    small = img.resize((sw, sh), Image.LANCZOS)
    vw, vh = 360, 400
    frames = 30
    fps = 10
    max_off = max(0, sh - vh)
    tmp = Path(tempfile.mkdtemp(prefix="spike_frames_"))
    try:
        for i in range(frames):
            off = int(round(max_off * i / max(1, frames - 1)))
            crop = small.crop((0, off, vw, off + vh))
            crop.save(tmp / f"frame_{i:03d}.png")
        out = OUT_DIR / "chat_scroll.mp4"
        cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i",
               str(tmp / "frame_%03d.png"), "-c:v", "libx264", "-pix_fmt",
               "yuv420p", "-crf", "28", "-movflags", "+faststart", str(out)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {proc.stderr[-2000:]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    size = out.stat().st_size
    if size > 1_000_000:
        raise RuntimeError(f"video too large: {size} bytes")
    duration = frames / fps
    if duration >= 5.0:
        raise RuntimeError("video too long")
    return {"file": out.name, "size": [vw, vh], "frames": frames, "fps": fps,
            "duration_s": duration, "bytes": size, "source": src.name}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    chat = make_chat()
    receipt = make_receipt()
    iou_imgs = make_iou_images()
    pdf = make_iou_pdf()
    video = make_video()
    truth = {
        "chat_capture.png": chat,
        "transfer_receipt.png": receipt,
        "iou_page1.png": iou_imgs["iou_page1.png"],
        "iou_page2.png": iou_imgs["iou_page2.png"],
        "iou_2page.pdf": pdf,
        "chat_scroll.mp4": video,
        "meta": {
            "watermark": WATERMARK,
            "note": "Synthetic SAMPLE inputs. truth.json is for tests/spike "
                    "scoring only; never pass it to models.",
        },
    }
    (OUT_DIR / "truth.json").write_text(json.dumps(truth, ensure_ascii=False,
                                                   indent=2), encoding="utf-8")
    print(f"wrote {OUT_DIR}")
    for name in ("chat_capture.png", "transfer_receipt.png", "iou_2page.pdf",
                 "iou_page1.png", "iou_page2.png", "chat_scroll.mp4",
                 "truth.json"):
        p = OUT_DIR / name
        print(f"  {name}: {p.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
