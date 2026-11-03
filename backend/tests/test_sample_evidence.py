"""M3 sample evidence and golden truth tests (offline, no API calls).

Covers the M3 brief section 7 plus the M3-fix1 review findings (S1~S11):
- manifest files exist and SHA-256 matches
- golden truth format (fields, boxes inside the image, kind vocabulary,
  case values match the case, account keep_box covers the last 4 digits)
- evidence numbering matches specs/case-api-contract.md section 2 (S1)
- video truth matches the rendered frames (S2)
- IOU/PDF layout, divider dates, case phones, signatures (S3~S7)
- image sizes, video duration/size
- runtime code (backend/app/) never references the golden path
- real-brand and forbidden-word scan of screen/README/sample texts,
  the generator, and the golden files (S9)
- previous sample person names must not reappear (names are read from
  git history at runtime, never written in this file; skipped when the
  baseline commit is unavailable)
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLE_DIR = ROOT / "sample_evidence"
GOLDEN_DIR = ROOT / "backend" / "tests" / "golden"
MANIFEST = SAMPLE_DIR / "manifest.json"

KINDS = {"utterance", "amount", "date", "party_name", "account_number",
         "id_number", "phone", "address", "label", "header", "watermark"}
VISION_TARGETS = {"signature", "stamp", "chat_bubble", "face"}
UTTERANCE_TAGS = {"loan_request", "amount_mention", "repay_promise",
                  "reminder", "other"}
BASELINE_COMMIT = "76d9cce"

DISCLAIMER_KO = ("ClaimBack-AI는 본인이 직접 소송 서류를 준비할 때 쓰는 무료 정리 도구입니다. "
                 "법률 자문을 제공하지 않으며, 서류에 들어가는 사실은 모두 사용자가 확인한 내용입니다. "
                 "법률 상담은 대한법률구조공단(132)이나 변호사에게 받으세요.")
DISCLAIMER_EN = ("ClaimBack-AI is a free self-help tool for organizing your own evidence "
                 "and filling standard court forms. It does not provide legal advice. "
                 "Every fact in the documents is confirmed by you. For help, contact your "
                 "court's self-help center or a small claims advisor.")
BADGE_KO = "본인 작성용 초안, 법률 자문 아님"
BADGE_EN = "Self-help draft. Not legal advice."
ALLOWLIST = (DISCLAIMER_KO, DISCLAIMER_EN, BADGE_KO, BADGE_EN)

BRANDS = ("토스", "카카오", "국민은행", "Chase", "iMessage", "Zelle")

FORBIDDEN = (
    "변호사", "법무사", "법률사무소", "법무법인", "로펌",
    "법률 대리", "법률 자문",
    "lawyer", "attorney", "law firm", "paralegal", "legal assistant",
    "counsel", "legal advice",
    "승소", "패소", "you will win", "win your case", "chance of winning",
    "채무 인정", "채무 승인", "debt acknowledgment", "acknowledgment of debt",
    "Promissory Admission",
    "정당한 사유 없이", "청구권이 발생", "법적 청구 대상",
    "요건사실 결손", "입증할",
)

SCREEN_FILES = ("frontend/index.html", "frontend/app.js",
                "frontend/styles.css", "docs/index.html", "docs/app.js",
                "docs/styles.css", "README.md")

EXPECTED_SAMPLE_FILES = {
    "kr_transfer_receipt.txt", "kr_chat_log.txt", "us_wire_receipt.txt",
    "kr/chat_01.png", "kr/chat_02_tall.png", "kr/chat_02_scroll.mp4",
    "kr/transfer_loan.png", "kr/transfer_repay.png", "kr/iou.pdf",
    "kr/iou.png",
    "en/chat_01.png", "en/wire_receipt.png", "en/promissory_note.pdf",
    "en/promissory_note.png",
}

EXPECTED_CASE = {
    "kr": {"principal_amount": 5000000, "loan_date": "2026-03-10",
           "due_date": "2026-04-10",
           "repayments": [{"payment_date": "2026-05-01", "amount": 1000000}],
           "remaining_principal": 4014383,
           "accrual_start_date": "2026-05-02"},
    "en": {"principal_amount": "5000.00", "loan_date": "2026-01-10",
           "due_date": "2026-04-10", "repayments": [],
           "remaining_principal": "5000.00",
           "accrual_start_date": "2026-04-11"},
}


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_entries(node):
    """Yield (file, sha256) pairs from the nested manifest structure."""
    if isinstance(node, dict):
        if set(node) == {"file", "sha256"}:
            yield node["file"], node["sha256"]
            return
        for value in node.values():
            yield from manifest_entries(value)


def load_truth(lang: str) -> dict:
    path = GOLDEN_DIR / f"{lang}_truth.json"
    assert path.exists(), f"missing golden truth: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def inside(box, width: int, height: int) -> bool:
    x1, y1, x2, y2 = box
    return 0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height


# --- 1. manifest ------------------------------------------------------------

def test_manifest_files_exist_and_match():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = dict(manifest_entries(manifest))
    assert EXPECTED_SAMPLE_FILES <= set(entries), (
        "manifest missing files: "
        f"{sorted(EXPECTED_SAMPLE_FILES - set(entries))}")
    for rel, expected in sorted(entries.items()):
        path = SAMPLE_DIR / rel
        assert path.is_file(), f"manifest file missing: {rel}"
        assert sha256_of(path) == expected, f"hash mismatch: {rel}"


def test_frontend_docs_mirrors_match():
    for name in ("index.html", "app.js", "styles.css"):
        left = (ROOT / "frontend" / name).read_bytes()
        right = (ROOT / "docs" / name).read_bytes()
        assert left == right, f"frontend/{name} differs from docs/{name}"


# --- 2. golden truth format -------------------------------------------------

@pytest.mark.parametrize("lang", ["kr", "en"])
def test_truth_schema_and_boxes(lang):
    truth = load_truth(lang)
    assert truth["_note"] == (
        "test-only golden answers. Never pass to runtime agents.")
    assert list(truth) and "_note" in truth
    # S7: the header states which amount unit each side uses.
    assert isinstance(truth.get("amount_unit"), str) and truth["amount_unit"]

    dims: dict[str, tuple[int, int]] = {}
    video_meta: dict[str, dict] = {}
    for ev in truth["evidences"]:
        assert {"ex_id", "file", "sha256", "width", "height",
               "coord_system", "coord_basis", "ignore_regions"} <= set(ev)
        assert ev["coord_system"] == "pixel"
        path = SAMPLE_DIR / ev["file"]
        assert path.is_file(), f"truth file missing: {ev['file']}"
        assert sha256_of(path) == ev["sha256"], f"hash mismatch: {ev['file']}"
        dims[ev["ex_id"]] = (ev["width"], ev["height"])
        for region in ev["ignore_regions"]:
            assert inside(region, ev["width"], ev["height"]), region
        assert ev["ignore_regions"], f"no ignore_regions: {ev['ex_id']}"
        if ev["file"].endswith(".mp4"):
            assert set(ev["video"]) >= {"fps", "frames", "frame_offsets"}
            assert len(ev["video"]["frame_offsets"]) == ev["video"]["frames"]
            video_meta[ev["ex_id"]] = ev["video"]
    assert len({e["ex_id"] for e in truth["evidences"]}) == len(
        truth["evidences"])

    seen: set[tuple[str, str]] = set()
    utterances: set[tuple[str, str]] = set()
    boxes: dict[tuple[str, str], list] = {}
    texts: dict[tuple[str, str], str] = {}
    for it in truth["items"]:
        assert {"ex_id", "item_id", "kind", "text_verbatim", "normalized",
                "box", "line_box", "speaker", "speaker_role",
                "frame_ts", "frame_index"} <= set(it)
        key = (it["ex_id"], it["item_id"])
        assert key not in seen, f"duplicate item: {key}"
        seen.add(key)
        boxes[key] = it["box"]
        texts[key] = it["text_verbatim"]
        assert it["kind"] in KINDS, it["kind"]
        # S11: the SAMPLE band lives only in ignore_regions, never as an item.
        assert it["kind"] != "watermark", key
        assert isinstance(it["text_verbatim"], str) and it["text_verbatim"]
        w, h = dims[it["ex_id"]]
        assert inside(it["box"], w, h), key
        if it["line_box"] is not None:
            assert inside(it["line_box"], w, h), key
        if it["kind"] == "utterance":
            utterances.add(key)
            assert it["speaker"], key
        # S11: a role tag always accompanies a speaker and vice versa, so
        # scoring can use the role instead of the person name.
        assert (it["speaker"] is None) == (it["speaker_role"] is None), key
        if it["speaker_role"] is not None:
            assert it["speaker_role"] in ("creditor", "debtor"), key
        # S2: video items point at an exact frame; stills have neither field.
        if it["ex_id"] in video_meta:
            fps = video_meta[it["ex_id"]]["fps"]
            assert isinstance(it["frame_index"], int), key
            assert it["frame_ts"] == round(it["frame_index"] / fps, 3), key
        else:
            assert it["frame_ts"] is None and it["frame_index"] is None, key
        if it["kind"] == "amount":
            assert isinstance(it["normalized"], int) and it["normalized"] > 0
        elif it["kind"] == "date":
            norm = it["normalized"]
            assert norm is None or re.fullmatch(r"\d{4}-\d{2}-\d{2}", norm), key
        else:
            assert it["normalized"] == it["text_verbatim"], key

    for tag_key, tags in truth["utterance_tags"].items():
        ex_id, _, item_id = tag_key.partition(":")
        assert (ex_id, item_id) in utterances, tag_key
        assert tags and set(tags) <= UTTERANCE_TAGS, tag_key
    assert {(k.partition(":")[0], k.partition(":")[2])
            for k in truth["utterance_tags"]} == utterances

    for v in truth["vision_targets"]:
        assert {"ex_id", "target", "box", "frame_box", "item_id",
                "frame_ts", "frame_index"} <= set(v)
        assert v["target"] in VISION_TARGETS, v["target"]
        w, h = dims[v["ex_id"]]
        assert inside(v["box"], w, h), v
        if v["ex_id"] in video_meta:
            fps = video_meta[v["ex_id"]]["fps"]
            assert isinstance(v["frame_index"], int), v
            assert v["frame_ts"] == round(v["frame_index"] / fps, 3), v
        else:
            assert v["frame_ts"] is None and v["frame_index"] is None, v
        if v["target"] == "signature":
            assert v["frame_box"] and inside(v["frame_box"], w, h), v
            fx1, fy1, fx2, fy2 = v["frame_box"]
            x1, y1, x2, y2 = v["box"]
            assert fx1 <= x1 and fy1 <= y1 and x2 <= fx2 and y2 <= fy2, v
        if v["target"] == "chat_bubble" and v["item_id"] is not None:
            assert v["box"] == boxes[(v["ex_id"], v["item_id"])], v

    # Each chat evidence carries exactly one geometric profile face.
    faces = Counter(v["ex_id"] for v in truth["vision_targets"]
                    if v["target"] == "face")
    for ev in truth["evidences"]:
        if "chat" in ev["file"]:
            assert faces[ev["ex_id"]] == 1, ev["ex_id"]

    for r in truth["redaction_targets"]:
        assert {"ex_id", "target", "item_id", "mask_box", "keep_box"} <= set(r)
        w, h = dims[r["ex_id"]]
        item_box = boxes[(r["ex_id"], r["item_id"])]
        if r["target"] == "account_number":
            assert r["mask_box"] and r["keep_box"], r
            assert inside(r["mask_box"], w, h) and inside(r["keep_box"], w, h)
            mx1, my1, mx2, my2 = r["mask_box"]
            kx1, ky1, kx2, ky2 = r["keep_box"]
            ix1, iy1, ix2, iy2 = item_box
            # mask (front) + keep (last 4) tile the account box end to end.
            assert abs(mx1 - ix1) <= 2 and abs(kx2 - ix2) <= 2, r
            assert abs(mx2 - kx1) <= 2, r
            assert my1 == iy1 and my2 == iy2 and ky1 == iy1 and ky2 == iy2, r
        elif r["target"] == "id_number":
            assert r["mask_box"] and r["keep_box"] is None, r
            assert inside(r["mask_box"], w, h), r
            mx1, _, mx2, _ = r["mask_box"]
            ix1, _, ix2, _ = item_box
            assert mx1 > ix1 and abs(mx2 - ix2) <= 2, r  # back digits only
        else:
            raise AssertionError(f"unknown redaction target: {r['target']}")


@pytest.mark.parametrize("lang", ["kr", "en"])
def test_truth_case_values(lang):
    truth = load_truth(lang)
    case = truth["case"]
    expected = EXPECTED_CASE[lang]
    for field in ("principal_amount", "loan_date", "due_date",
                  "remaining_principal", "accrual_start_date"):
        assert case[field] == expected[field], field
    assert [{"payment_date": r["payment_date"], "amount": r["amount"]}
            for r in case["repayments"]] == expected["repayments"]
    for party in ("creditor", "debtor"):
        assert case[party]["name"], party

    # Account endings are fictional (leading zeros) and pairwise distinct.
    endings = set()
    for it in truth["items"]:
        if it["kind"] != "account_number":
            continue
        text = it["text_verbatim"]
        assert text.startswith("000"), text
        last4 = text[-4:]
        assert last4.isdigit() and len(set(last4)) == 4, text
        endings.add(last4)
    # Two distinct fictional accounts per language.
    assert len(endings) == 2, endings


@pytest.mark.parametrize("lang", ["kr", "en"])
def test_truth_case_matches_evidence_values(lang):
    """Case principal/loan date agree with the transfer receipt truth."""
    truth = load_truth(lang)
    case = truth["case"]
    by_file = {e["ex_id"]: e["file"] for e in truth["evidences"]}
    receipt_ex = next(ex for ex, f in by_file.items()
                      if "transfer_loan" in f or "wire_receipt" in f)
    amounts = [it["normalized"] for it in truth["items"]
               if it["ex_id"] == receipt_ex and it["kind"] == "amount"]
    dates = [it["normalized"] for it in truth["items"]
             if it["ex_id"] == receipt_ex and it["kind"] == "date"]
    principal = case["principal_amount"]
    if lang == "en":
        # S7: case holds decimal-dollar strings, items hold integer cents.
        assert isinstance(principal, str)
        principal = int(round(float(principal) * 100))
    assert principal in amounts
    assert case["loan_date"] in dates


# --- 2b. M3-fix1 finding tests (S1, S4-S7, S11) -------------------------------

# S1: ex_id -> file mapping fixed by specs/case-api-contract.md section 2.
CONTRACT_EX_FILES = {
    "kr": [("EX1", "kr/chat_01.png"),
           ("EX2", "kr/chat_02_tall.png"),
           ("EX3", "kr/chat_02_scroll.mp4"),
           ("EX4", "kr/transfer_loan.png"),
           ("EX5", "kr/transfer_repay.png"),
           ("EX6", "kr/iou.pdf")],
    "en": [("EX1", "en/chat_01.png"),
           ("EX2", "en/wire_receipt.png"),
           ("EX3", "en/promissory_note.pdf")],
}


def test_truth_evidence_order_matches_contract():
    for lang, expected in CONTRACT_EX_FILES.items():
        truth = load_truth(lang)
        got = [(e["ex_id"], e["file"]) for e in truth["evidences"]]
        assert got == expected, lang
        for ev in truth["evidences"]:
            if ev["file"].endswith(".pdf"):
                # Boxes use the preview PNG pixels (S1, S3).
                assert ev["coord_basis"], ev["ex_id"]
                preview = SAMPLE_DIR / ev["coord_basis"]
                assert preview.is_file(), ev["coord_basis"]
                with Image.open(preview) as img:
                    assert img.size == (ev["width"], ev["height"])
            else:
                assert ev["coord_basis"] is None, ev["ex_id"]


def test_ex2_dividers_increasing():
    """S4: the tall chat date dividers run forward in time."""
    truth = load_truth("kr")
    dividers = [it for it in truth["items"]
                if it["ex_id"] == "EX2" and it["kind"] == "date"
                and it["speaker"] is None]
    assert len(dividers) >= 2
    norms = [d["normalized"] for d in dividers]
    assert norms == sorted(norms) and len(set(norms)) == len(norms)
    texts = [d["text_verbatim"] for d in dividers]
    assert "2026년 4월 26일" in texts  # the day after the missed promise


def test_case_phones_appear_in_evidence():
    """S5: every case contact phone is printed on the IOU/promissory note."""
    for lang, note_ex in (("kr", "EX6"), ("en", "EX3")):
        truth = load_truth(lang)
        phones = {truth["case"]["creditor"].get("phone"),
                  truth["case"]["debtor"].get("phone")} - {None}
        assert len(phones) == 2, lang  # distinct fictional numbers
        printed = [it["text_verbatim"] for it in truth["items"]
                   if it["ex_id"] == note_ex and it["kind"] == "phone"]
        for phone in phones:
            assert phone in printed, (lang, phone)


def _box_iou(a: list, b: list) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    union = ((a[2] - a[0]) * (a[3] - a[1])
             + (b[2] - b[0]) * (b[3] - b[1]) - inter)
    return inter / union


def _boxes_overlap(a: list, b: list) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0]
                or a[3] <= b[1] or b[3] <= a[1])


def test_signature_ink_small_and_distinct():
    """S6: pen-lift scribbles, clearly smaller than the frame, differ."""
    for lang, note_ex in (("kr", "EX6"), ("en", "EX3")):
        truth = load_truth(lang)
        sigs = [v for v in truth["vision_targets"]
                if v["ex_id"] == note_ex and v["target"] == "signature"]
        assert len(sigs) == 2, lang
        assert sigs[0]["box"] != sigs[1]["box"], lang
        for sig in sigs:
            assert sig.get("strokes", 0) >= 3, sig
            assert _box_iou(sig["box"], sig["frame_box"]) <= 0.4, sig


def test_signature_labels_clear_of_ink():
    """S7: signer name labels never touch the signature ink."""
    for lang, note_ex in (("kr", "EX6"), ("en", "EX3")):
        truth = load_truth(lang)
        labels = [it for it in truth["items"]
                  if it["ex_id"] == note_ex and it["kind"] == "label"]
        sigs = [v for v in truth["vision_targets"]
                if v["ex_id"] == note_ex and v["target"] == "signature"]
        assert labels and sigs
        for label in labels:
            for sig in sigs:
                assert not _boxes_overlap(label["box"], sig["box"]), (
                    lang, label["text_verbatim"])


def test_speaker_roles_match_case_parties():
    """S11: sent bubbles are the creditor, received ones the debtor."""
    for lang in ("kr", "en"):
        truth = load_truth(lang)
        creditor = truth["case"]["creditor"]["name"]
        debtor = truth["case"]["debtor"]["name"]
        seen = set()
        for it in truth["items"]:
            if it["kind"] != "utterance":
                continue
            if it["speaker"] == creditor:
                assert it["speaker_role"] == "creditor", it
            elif it["speaker"] == debtor:
                assert it["speaker_role"] == "debtor", it
            else:
                raise AssertionError(f"unknown speaker: {it['speaker']}")
            seen.add(it["speaker_role"])
        assert seen == {"creditor", "debtor"}, lang


# --- 3. image sizes and video ------------------------------------------------

IMAGE_SIZES = {
    "kr/chat_01.png": (640, 960),
    "kr/chat_02_tall.png": (640, 2400),
    "kr/transfer_loan.png": (640, 640),
    "kr/transfer_repay.png": (640, 640),
    "kr/iou.png": (1240, 1754),
    "en/chat_01.png": (640, 960),
    "en/wire_receipt.png": (640, 640),
    "en/promissory_note.png": (1240, 1754),
}


def test_image_sizes():
    for rel, expected in IMAGE_SIZES.items():
        with Image.open(SAMPLE_DIR / rel) as img:
            assert img.size == expected, rel


def test_pdfs_single_page():
    for rel in ("kr/iou.pdf", "en/promissory_note.pdf"):
        reader = PdfReader(str(SAMPLE_DIR / rel))
        assert len(reader.pages) == 1, rel


def ffprobe_stream(path: Path) -> dict:
    exe = shutil.which("ffprobe")
    if exe is None:
        pytest.skip("ffprobe not available")
    proc = subprocess.run(
        [exe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,avg_frame_rate,duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)["streams"][0]


def test_scroll_video_specs():
    path = SAMPLE_DIR / "kr" / "chat_02_scroll.mp4"
    assert path.stat().st_size <= 3 * 1024 * 1024
    stream = ffprobe_stream(path)
    assert (stream["width"], stream["height"]) == (640, 960)
    num, _, den = stream["avg_frame_rate"].partition("/")
    assert float(num) / float(den or 1) <= 30
    assert 6.0 <= float(stream["duration"]) <= 8.0


def test_scroll_video_late_bubble():
    truth = load_truth("kr")
    video_ex = next(e["ex_id"] for e in truth["evidences"]
                    if e["file"].endswith(".mp4"))
    late = [it for it in truth["items"]
            if it["ex_id"] == video_ex and it["kind"] == "utterance"
            and (it["frame_ts"] or 0) > 1.0]
    assert late, "no bubble first appears after scrolling starts"


BUBBLE_COLORS = ((0xE9, 0xEC, 0xEF), (0xCF, 0xEF, 0xEA))
BAND_TOP = 36  # fixed SAMPLE band height; boxes must sit below it


def extract_frame(video: Path, index: int, out: Path) -> None:
    exe = shutil.which("ffmpeg")
    if exe is None:
        pytest.skip("ffmpeg not available")
    proc = subprocess.run(
        [exe, "-y", "-v", "error", "-i", str(video),
         "-vf", f"select=eq(n\\,{index})", "-frames:v", "1", str(out)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def bubble_fraction(img: Image.Image, box: list) -> float:
    """Share of sampled box pixels close to a bubble fill color.

    x264 quantization shifts colors, so closeness uses a Manhattan
    tolerance instead of exact equality.
    """
    x1, y1, x2, y2 = box
    good = total = 0
    for y in range(y1 + 4, y2 - 4, 3):
        for x in range(x1 + 4, x2 - 4, 3):
            r, g, b = img.getpixel((x, y))
            total += 1
            for cr, cg, cb in BUBBLE_COLORS:
                if abs(r - cr) + abs(g - cg) + abs(b - cb) <= 90:
                    good += 1
                    break
    return good / max(1, total)


def test_video_truth_matches_rendered_frames(tmp_path):
    """S2: each video box is the tall box scrolled to its first full frame.

    Boxes must sit inside the frame below the fixed band, and the frame
    extracted at frame_ts must show bubble color inside utterance boxes.
    """
    truth = load_truth("kr")
    ev = next(e for e in truth["evidences"]
              if e["file"].endswith(".mp4"))
    video_ex = ev["ex_id"]
    fps = ev["video"]["fps"]
    offsets = ev["video"]["frame_offsets"]
    tall = {it["item_id"]: it for it in truth["items"]
            if it["ex_id"] == "EX2"}

    video_items = [it for it in truth["items"] if it["ex_id"] == video_ex]
    assert video_items
    for it in video_items:
        fi = it["frame_index"]
        assert it["frame_ts"] == round(fi / fps, 3), it["item_id"]
        base = tall[it["item_id"]]
        off = offsets[fi]
        expected = [base["box"][0], base["box"][1] - off,
                    base["box"][2], base["box"][3] - off]
        assert it["box"] == expected, it["item_id"]
        assert inside(it["box"], ev["width"], ev["height"]), it["item_id"]
        assert it["box"][1] >= BAND_TOP, it["item_id"]

    video_path = SAMPLE_DIR / ev["file"]
    for it in video_items:
        if it["kind"] != "utterance":
            continue
        out = tmp_path / f"{it['item_id']}.png"
        extract_frame(video_path, it["frame_index"], out)
        with Image.open(out) as frame:
            rgb = frame.convert("RGB")
            assert rgb.size == (ev["width"], ev["height"])
            assert bubble_fraction(rgb, it["box"]) >= 0.5, it["item_id"]


# --- 4. runtime must not read golden answers --------------------------------

def test_runtime_code_has_no_golden_reference():
    app_dir = ROOT / "backend" / "app"
    hits = []
    for path in sorted(app_dir.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "golden" in text:
            hits.append(str(path.relative_to(ROOT)))
    assert not hits, f"runtime references golden answers: {hits}"


# --- 5. brands and forbidden words ------------------------------------------

def scanned_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    for allowed in ALLOWLIST:
        text = text.replace(allowed, "")
    return text


EXTRA_SCAN_FILES = ("tools/make_sample_evidence.py",
                    "sample_evidence/generate_mock_evidence.py",
                    "backend/tests/golden/kr_truth.json",
                    "backend/tests/golden/en_truth.json")


def test_no_brands_or_forbidden_words():
    files = [ROOT / rel for rel in SCREEN_FILES]
    files += sorted(SAMPLE_DIR.glob("*.txt"))
    files += [ROOT / rel for rel in EXTRA_SCAN_FILES]
    assert files, "no files scanned"
    hits = []
    for path in files:
        text = scanned_text(path)
        for term in BRANDS + FORBIDDEN:
            if term in text:
                hits.append(f"{path.relative_to(ROOT)}: {term}")
    assert not hits, f"brand/forbidden hits: {hits}"


def test_disclaimers_present_verbatim():
    for rel in ("frontend/index.html", "README.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert DISCLAIMER_KO in text, rel
        assert DISCLAIMER_EN in text, rel
    header = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert BADGE_KO in header
    assert BADGE_EN in header


# --- 6. previous sample person names must not reappear ----------------------

def baseline_text(rel_path: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "show", f"{BASELINE_COMMIT}:{rel_path}"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("baseline commit unavailable "
                    "(shallow clone, zip download, or no git)")
    return proc.stdout


def baseline_person_tokens() -> list[str]:
    """Person names and addresses from the pre-cleanup baseline tree.

    Parsed generically from field shapes so this file never spells the
    old real-looking values.
    """
    tokens: list[str] = []
    app_js = baseline_text("docs/app.js")
    # Only creditor/debtor objects (evidence filename fields share the
    # key shape but legitimately persist as source_filename values).
    for line in app_js.splitlines():
        if re.match(r"\s*(creditor|debtor):", line):
            tokens += re.findall(r'name: "([^"]+)"', line)
            tokens += re.findall(r'address: "([^"]+)"', line)
    kr_transfer = baseline_text("sample_evidence/kr_transfer_receipt.txt")
    tokens += re.findall(r"보낸 분: (\S+)", kr_transfer)
    tokens += re.findall(r"받는 분: (\S+)", kr_transfer)
    kr_chat = baseline_text("sample_evidence/kr_chat_log.txt")
    tokens += re.findall(r"\] ([^]:]+):", kr_chat)
    us_wire = baseline_text("sample_evidence/us_wire_receipt.txt")
    tokens += [s.strip() for s in re.findall(r"Sender: ([^(]+)", us_wire)]
    tokens += [s.strip() for s in re.findall(r"Beneficiary: ([^(,]+)", us_wire)]
    seen: list[str] = []
    for tok in tokens:
        tok = tok.strip()
        if len(tok) >= 2 and tok not in seen:
            seen.append(tok)
    assert len(seen) >= 4, "baseline parse found no person tokens"
    return seen


def test_previous_sample_names_absent():
    tokens = baseline_person_tokens()
    targets = [ROOT / rel for rel in SCREEN_FILES]
    targets += sorted(SAMPLE_DIR.glob("*.txt"))
    targets.append(ROOT / "backend" / "app" / "api" / "routes.py")
    targets += [ROOT / rel for rel in EXTRA_SCAN_FILES]
    hits = []
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for tok in tokens:
            if tok and tok in text:
                hits.append(f"{path.relative_to(ROOT)}: <baseline token>")
    assert not hits, f"previous sample names reappear: {hits}"
