"""M4a vision + privacy tests (replay, no key) + fix1 (L1-L8).

Compares SAM segments against golden vision_targets and redaction copies
against golden redaction_targets (test-only reads, never passed to agents).
L1 band pins + L5 golden coverage encode CURRENT (misaligned EX6) behavior;
M4b/INT-3 will flip the EX6 pins when reader boxes are fixed.
"""
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.agents import case_state as case_state_mod
from app.agents import coordinator as coord
from app.agents import demo_inputs
from app.agents import deps
from app.agents import privacy_guard as privacy_mod
from app.agents import vision as vision_mod
from app.main import app
from app.meta.coords import box_iou
from app.services import redaction as redact_mod

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "backend" / "tests" / "golden" / "kr_truth.json"
SAMPLE = ROOT / "sample_evidence" / "kr"
NANUM_BOLD = (ROOT / "backend" / "app" / "templates" / "fonts"
              / "NanumGothic-Bold.ttf")


def load_golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


# --- shared module case (L7: one sample run for all read-only tests) ---
@pytest.fixture(scope="module")
def shared_home(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("m4a")
    old_root = case_state_mod.CASES_ROOT
    old_mode = os.environ.get("META_MODE")
    old_key = os.environ.get("MODEL_API_KEY")
    old_agents = dict(coord.AGENTS)
    case_state_mod.CASES_ROOT = tmp / "cases"
    os.environ["META_MODE"] = "replay"
    os.environ.pop("MODEL_API_KEY", None)
    for name in ("reader", "organizer", "drafter"):
        coord.AGENTS[name] = None
    try:
        yield tmp
    finally:
        case_state_mod.CASES_ROOT = old_root
        if old_mode is None:
            os.environ.pop("META_MODE", None)
        else:
            os.environ["META_MODE"] = old_mode
        if old_key is None:
            os.environ.pop("MODEL_API_KEY", None)
        else:
            os.environ["MODEL_API_KEY"] = old_key
        coord.AGENTS.clear()
        coord.AGENTS.update(old_agents)


@pytest.fixture(scope="module")
def shared_client(shared_home):
    return TestClient(app)


@pytest.fixture()
def env(shared_home, monkeypatch):
    monkeypatch.setattr(case_state_mod, "CASES_ROOT",
                        shared_home / "cases")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("META_MODE", "replay")
    for name in ("reader", "organizer", "drafter"):
        monkeypatch.setitem(coord.AGENTS, name, None)
    return TestClient(app)


@pytest.fixture(scope="module")
def shared_case(shared_client):
    return _to_checkpoint_1(shared_client)


def _to_checkpoint_1(client):
    res = client.post("/api/cases/sample", json={"set": "kr"})
    assert res.status_code == 200, res.text
    case_id = res.json()["case_id"]
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "CHECKPOINT_1", res.text
    return case_id


def _best_iou(pred_boxes, truth_box):
    if not pred_boxes:
        return 0.0
    return max(box_iou(pred, truth_box) for pred in pred_boxes)


# --- vision unit ------------------------------------------------------------
def test_sam_nouns_file_lists_four():
    nouns = vision_mod.load_nouns()
    assert [n for n, _ in nouns] == [
        "signature", "red stamp", "chat bubble", "face"]
    assert [t for _, t in nouns] == [
        "signature", "stamp", "chat_bubble", "face"]


def test_parse_empty_is_not_found():
    assert vision_mod.parse_sam_output("", "signature", "noun", 640, 960) == []
    assert vision_mod.parse_sam_output("   \n ", "face", "noun", 64, 64) == []


def test_parse_error_is_error_not_not_found():
    # Non-empty garbage that breaks the parser grammar in strict paths is
    # rare (plain text becomes text records); a half record (box without
    # mask) must raise, never return [].
    bad = "<0f>0<|box;x1=1;y1=2;x2=3;y2=4;w=10;h=10|>\n"
    with pytest.raises(vision_mod.VisionParseError):
        vision_mod.parse_sam_output(bad, "signature", "noun", 10, 10)


def test_signature_prompt_needs_label():
    assert vision_mod.build_signature_box_prompt(
        640, 960, [{"text_verbatim": "hello", "box": {"x1": 1, "y1": 1,
                                                     "x2": 5, "y2": 5}}]) is None
    prompt = vision_mod.build_signature_box_prompt(
        1240, 1754,
        [{"text_verbatim": "탁나루(SAMPLE) 서명",
          "box": {"x1": 105, "y1": 1438, "x2": 390, "y2": 1474}}])
    assert prompt is not None and "box;x1=" in prompt
    # Prompt stays right of the label (label text excluded).
    assert "x1=410" in prompt


def test_refine_ink_falls_back_without_dark_pixels():
    white = Image.new("RGB", (100, 60), (255, 255, 255))
    buf = io.BytesIO()
    white.save(buf, format="PNG")
    sam_box = {"x1": 10, "y1": 5, "x2": 90, "y2": 55,
               "system": "pixel", "ref_w": 100, "ref_h": 60}
    assert vision_mod.refine_signature_ink_box(
        buf.getvalue(), sam_box, 100, 60) == sam_box


def test_ink_rule_ignores_red_stamp():
    img = Image.new("RGB", (100, 60), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 30, 59, 39], fill=(0, 0, 0))
    draw.rectangle([60, 10, 89, 49], fill=(200, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    sam_box = {"x1": 10, "y1": 5, "x2": 95, "y2": 55,
               "system": "pixel", "ref_w": 100, "ref_h": 60}
    refined = vision_mod.refine_signature_ink_box(
        buf.getvalue(), sam_box, 100, 60)
    assert (refined["x1"], refined["y1"],
            refined["x2"], refined["y2"]) == (20, 30, 60, 40)


# --- vision golden (needs record fixtures) ----------------------------------
def test_vision_stamp_and_bubbles_match_golden(env, shared_case):
    segments = env.get(f"/api/cases/{shared_case}/segments").json()
    golden = load_golden()
    by_ex = {s["ex_id"]: s for s in segments}
    # Stamp EX6
    stamp_truth = next(v["box"] for v in golden["vision_targets"]
                       if v["ex_id"] == "EX6" and v["target"] == "stamp")
    stamp_preds = [[o["box"]["x1"], o["box"]["y1"], o["box"]["x2"], o["box"]["y2"]]
                   for o in by_ex["EX6"]["objects"]
                   if o["target"] == "stamp"]
    assert stamp_preds, "no stamp found"
    assert _best_iou(stamp_preds, stamp_truth) >= 0.5
    # Bubbles EX1 (every golden bubble has a close prediction).
    bubbles = [v["box"] for v in golden["vision_targets"]
               if v["ex_id"] == "EX1" and v["target"] == "chat_bubble"]
    preds = [[o["box"]["x1"], o["box"]["y1"], o["box"]["x2"], o["box"]["y2"]]
             for o in by_ex["EX1"]["objects"]
             if o["target"] == "chat_bubble"]
    assert len(preds) == len(bubbles)
    for truth in bubbles:
        assert _best_iou(preds, truth) >= 0.5, truth
    # Face EX1
    face_truth = next(v["box"] for v in golden["vision_targets"]
                      if v["ex_id"] == "EX1" and v["target"] == "face")
    face_preds = [[o["box"]["x1"], o["box"]["y1"], o["box"]["x2"], o["box"]["y2"]]
                  for o in by_ex["EX1"]["objects"]
                  if o["target"] == "face"]
    assert face_preds and _best_iou(face_preds, face_truth) >= 0.5
    # Video skipped, receipts not_found.
    assert by_ex["EX3"]["status"] == "skipped"
    assert by_ex["EX4"]["status"] in ("not_found", "ok")


def test_vision_signatures_match_ink(env, shared_case):
    segments = env.get(f"/api/cases/{shared_case}/segments").json()
    golden = load_golden()
    by_ex = {s["ex_id"]: s for s in segments}
    inks = [v["box"] for v in golden["vision_targets"]
            if v["ex_id"] == "EX6" and v["target"] == "signature"]
    assert len(inks) == 2
    sigs = [o for o in by_ex["EX6"]["objects"]
            if o["target"] == "signature"]
    assert len(sigs) >= 2, f"signatures found: {len(sigs)}"
    # L6: SAM cell box and pixel-rule ink box stored separately.
    for obj in sigs:
        assert obj["source"] == "box"
        assert obj["ink_source"] == "pixel_rule"
        assert obj["ink_box"] != obj["box"]
        assert isinstance(obj["score"], float)
    preds = [[o["ink_box"]["x1"], o["ink_box"]["y1"],
              o["ink_box"]["x2"], o["ink_box"]["y2"]] for o in sigs]
    for truth in inks:
        assert _best_iou(preds, truth) >= 0.5, truth
    # Masks saved and served.
    for obj in by_ex["EX6"]["objects"]:
        res = env.get(obj["mask_url"])
        assert res.status_code == 200
        assert res.content[:8] == b"\x89PNG\r\n\x1a\n"
        assert res.headers["content-type"] == "image/png"


def test_vision_steps_and_substeps(env, shared_case):
    view = env.get(f"/api/cases/{shared_case}").json()
    vision = next(s for s in view["steps"] if s["key"] == "vision")
    assert vision["status"] == "done"
    assert vision["model"] == "sam-3.1"
    assert [s["ex_id"] for s in vision["substeps"]] == [
        "EX1", "EX2", "EX3", "EX4", "EX5", "EX6"]
    assert float(vision["cost_usd"]) > 0
    privacy = next(s for s in view["steps"] if s["key"] == "privacy")
    assert privacy["status"] == "done"


# --- redaction unit ---------------------------------------------------------
def test_redaction_splits_tile_without_gap():
    mask, keep = redact_mod.split_account_box([230, 207, 389, 224],
                                              "000-0000-1234")
    assert mask[0] == 230 and keep[1] == 207
    assert mask[2] == keep[0]  # no gap, no overlap
    assert keep[2] == 389
    assert redact_mod.split_id_box([470, 1160, 755, 1185],
                                   "000000-0000000")[0] > 470
    phone = redact_mod.split_phone_box([470, 368, 725, 393], "010-0000-0001")
    assert 470 < phone[0] < phone[2] < 725
    # L4 digit-based fallback: "+82" numbers mask 1234 like 010 numbers.
    wide = redact_mod.split_phone_box([0, 0, 320, 40], "+82 10-1234-5678")
    assert wide == [140, 0, 220, 40]


def _render_composed(text, font, margin=15):
    """Render text char-by-char; return (image, box, char ink spans).

    Char spans are the test's independent oracle for split geometry.
    """
    img = Image.new("RGB", (900, 90), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    top, x = 20, 30
    spans = []
    for ch in text:
        if ch == " ":
            x += int(draw.textlength(" ", font=font)) + 2
            spans.append(None)
            continue
        probe = Image.new("RGB", (160, 90), (255, 255, 255))
        ImageDraw.Draw(probe).text((10, top), ch, font=font, fill=(0, 0, 0))
        char_box = probe.convert("L").point(lambda v: 255 - v).getbbox()
        assert char_box, f"blank render for {ch!r}"
        draw.text((x, top), ch, font=font, fill=(0, 0, 0))
        spans.append((x + char_box[0] - 10, x + char_box[2] - 10))
        x += int(draw.textlength(ch, font=font)) + 2
    full = img.convert("L").point(lambda v: 255 - v).getbbox()
    box = [full[0] - margin, full[1] - margin,
           full[2] + margin, full[3] + margin]
    return img, box, spans


def _check_split_pixels(orig, red, spans, masked_idx):
    """Masked chars' glyph fully black, kept chars' glyph intact."""
    opx, rpx = orig.load(), red.load()
    assert orig.size == red.size
    seen_masked, seen_kept = 0, 0
    for i, span in enumerate(spans):
        if span is None:
            continue
        for yy in range(orig.height):
            for xx in range(span[0], span[1]):
                r, g, b = opx[xx, yy][:3]
                if (r + g + b) / 3.0 >= 128:
                    continue
                rr, gg, bb = rpx[xx, yy][:3]
                if i in masked_idx:
                    seen_masked += 1
                    assert (rr, gg, bb) == (0, 0, 0), (i, xx, yy)
                else:
                    seen_kept += 1
                    assert (rr, gg, bb) == (r, g, b), (i, xx, yy)
    assert seen_masked > 50 and seen_kept > 50


def test_account_blank_split_synthetic(tmp_path):
    font = ImageFont.load_default(size=28)
    text = "000-0000-1234"
    img, box, spans = _render_composed(text, font)
    geom = redact_mod.analyze_text_box(img, box, text)
    assert geom["segments"] is not None  # exact path
    assert len(geom["segments"]) == len(text)
    mask, keep = redact_mod.split_account_box(box, text, geom)
    # Split in the blank column between char 8 (hyphen) and char 9 ("1").
    order = [i for i, ch in enumerate(text) if not ch.isspace()]
    last_masked = geom["segments"][order.index(8)]
    first_kept = geom["segments"][order.index(9)]
    assert mask[2] == keep[0] == last_masked[1]
    assert last_masked[1] <= first_kept[0]
    red_path = tmp_path / "red.png"
    redact_mod.burn_redacted_copy(_save_tmp(img, tmp_path), red_path,
                                  [mask], "")
    _check_split_pixels(img, Image.open(red_path).convert("RGB"),
                        spans, set(range(9)))


def test_id_front6_back7_synthetic(tmp_path):
    font = ImageFont.load_default(size=28)
    text = "000000-0000000"
    img, box, spans = _render_composed(text, font)
    geom = redact_mod.analyze_text_box(img, box, text)
    assert geom["segments"] is not None
    mask = redact_mod.split_id_box(box, text, geom)
    order = [i for i, ch in enumerate(text) if not ch.isspace()]
    hyphen = geom["segments"][order.index(6)]
    first_masked = geom["segments"][order.index(7)]
    assert mask[0] == hyphen[1]
    assert hyphen[1] <= first_masked[0]
    red_path = tmp_path / "red.png"
    redact_mod.burn_redacted_copy(_save_tmp(img, tmp_path), red_path,
                                  [mask], "")
    _check_split_pixels(img, Image.open(red_path).convert("RGB"),
                        spans, set(range(7, 14)))


def test_phone_middle4_shapes(tmp_path):
    cases = [
        ("010-1234-5678", ImageFont.load_default(size=28), {4, 5, 6, 7}),
        ("+82 10-1234-5678", ImageFont.load_default(size=28),
         {7, 8, 9, 10}),
        ("연락처 010-1234-5678",
         ImageFont.truetype(str(NANUM_BOLD), 28), {8, 9, 10, 11}),
    ]
    for text, font, masked in cases:
        img, box, spans = _render_composed(text, font)
        geom = redact_mod.analyze_text_box(img, box, text)
        assert geom["segments"] is not None, text
        mask = redact_mod.split_phone_box(box, text, geom)
        order = [i for i, ch in enumerate(text) if not ch.isspace()]
        first = geom["segments"][order.index(min(masked))]
        last = geom["segments"][order.index(max(masked))]
        assert mask[0] == first[0], text
        assert mask[2] == last[1], text
        assert "".join(text[i] for i in sorted(masked)) == "1234"
        red_path = tmp_path / "red.png"
        redact_mod.burn_redacted_copy(_save_tmp(img, tmp_path), red_path,
                                      [mask], "")
        _check_split_pixels(img, Image.open(red_path).convert("RGB"),
                            spans, masked)


def _save_tmp(img, tmp_path):
    path = tmp_path / "orig.png"
    img.save(path)
    return path


def test_redaction_padding_skips_keep_side():
    pad = redact_mod.compute_pad(17)
    assert pad == 4
    mask = redact_mod.pad_box([230, 207, 337, 224], pad,
                              (True, True, False, True), 640, 640)
    assert mask == [226, 203, 337, 228]


def _refine_iou(first, second):
    ix1, iy1 = max(first[0], second[0]), max(first[1], second[1])
    ix2, iy2 = min(first[2], second[2]), min(first[3], second[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    union = ((first[2] - first[0]) * (first[3] - first[1])
             + (second[2] - second[0]) * (second[3] - second[1]) - inter)
    return inter / union if union else 0.0


def test_refine_pii_box_snaps_shifted_boxes_to_golden():
    """INT-3 1a: replay-era shifted boxes snap to the true glyph line.

    No fixtures: the sample images plus the misaligned boxes stand in
    for the reader output. Phones land tight; account/id boxes keep
    the cell-border columns at their edges (analyze_text_box trims
    edge runs, so splits stay exact — pinned by the golden e2e test).
    """
    cases = [
        ("transfer_loan.png", [218, 198, 374, 234], "000-0000-1234",
         [230, 207, 389, 224], 0.45),
        ("transfer_loan.png", [218, 342, 374, 378], "000-0000-5678",
         [230, 351, 389, 367], 0.45),
        ("iou.png", [415, 383, 665, 414], "010-0000-0001",
         [470, 368, 725, 393], 0.80),
        ("iou.png", [415, 603, 667, 673], "010-0000-0002",
         [470, 631, 725, 657], 0.80),
        ("iou.png", [422, 1045, 768, 1195], "000000-0000000",
         [470, 1160, 755, 1185], 0.50),
    ]
    for name, box, text, golden, floor in cases:
        image = Image.open(SAMPLE / name).convert("RGB")
        mask = redact_mod.build_ink_mask(image)
        refined = redact_mod.refine_pii_box(mask, box, text)
        assert refined is not None, (name, text)
        assert _refine_iou(refined, golden) >= floor, (name, text, refined)
        # The golden glyph rows sit inside the refined box.
        assert refined[1] <= golden[1] and refined[3] >= golden[3] - 4, (
            name, text, refined)


def test_refine_pii_box_returns_none_without_match():
    """INT-3 1a: blank ink or an absurd width keeps the original box."""
    blank = Image.new("RGB", (640, 640), (255, 255, 255))
    mask = redact_mod.build_ink_mask(blank)
    assert redact_mod.refine_pii_box(
        mask, [100, 100, 300, 130], "000-0000-1234") is None
    image = Image.open(SAMPLE / "iou.png").convert("RGB")
    mask = redact_mod.build_ink_mask(image)
    assert redact_mod.refine_pii_box(
        mask, [422, 1045, 768, 1195], "1") is None


def test_reading_band_counts_flag_sideways_miss_only():
    """INT-3 task 2: four-side bands on the planning box (synthetic)."""
    image = Image.new("RGB", (200, 100), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle([80, 40, 119, 59], fill=(0, 0, 0))
    mask = redact_mod.build_ink_mask(image)
    rules = redact_mod.rule_rows_of_mask(mask)
    assert rules == set()
    aligned = redact_mod.reading_band_counts(mask, rules, [80, 40, 120, 60])
    assert max(aligned.values()) == 0
    shifted = redact_mod.reading_band_counts(mask, rules, [40, 40, 80, 60])
    assert shifted["right"] >= redact_mod.BAND_THRESHOLD
    # A cell-border rule next to the box is not a leaked glyph.
    ruled = Image.new("RGB", (200, 100), (255, 255, 255))
    ImageDraw.Draw(ruled).line([0, 38, 199, 38], fill=(0, 0, 0), width=1)
    ImageDraw.Draw(ruled).rectangle([80, 40, 119, 59], fill=(0, 0, 0))
    ruled_mask = redact_mod.build_ink_mask(ruled)
    ruled_rows = redact_mod.rule_rows_of_mask(ruled_mask)
    assert 38 in ruled_rows
    counts = redact_mod.reading_band_counts(
        ruled_mask, ruled_rows, [80, 40, 120, 60])
    assert max(counts.values()) == 0


def test_privacy_inline_is_wide_and_flagged():
    readings = [{"ex_id": "EX1", "items": [{
        "item_id": "item9", "kind": "account_number",
        "text_verbatim": "000-0000-1234",
        "box": {"x1": 100, "y1": 100, "x2": 200, "y2": 120}}]}]
    segments = [{"ex_id": "EX1", "objects": [{
        "target": "chat_bubble",
        "box": {"x1": 20, "y1": 80, "x2": 400, "y2": 140}}]}]
    plan = privacy_mod.build_plan(readings, segments, {"EX1": (640, 960)})
    assert len(plan) == 1
    assert plan[0]["needs_review"] is True
    assert plan[0]["keep_box"] is None
    assert "확인 필요" in plan[0]["reason"]
    assert plan[0]["mask_box"]["x1"] <= 20
    assert plan[0]["mask_box"]["x2"] >= 400


def test_leak_check_failure_paths(tmp_path):
    original = Image.new("RGB", (60, 40), (255, 255, 255))
    orig_path = tmp_path / "orig.png"
    red_path = tmp_path / "red.png"
    original.save(orig_path)
    # Gray (not black) mask must fail.
    bad = original.copy()
    from PIL import ImageDraw
    ImageDraw.Draw(bad).rectangle([10, 10, 29, 19], fill=(128, 128, 128))
    bad.save(red_path)
    plan = [{"ex_id": "EX1", "item_id": "item1", "kind": "phone",
             "mask_box": {"x1": 10, "y1": 10, "x2": 30, "y2": 20}}]
    assert redact_mod.check_leak(
        orig_path, red_path, plan)["status"] == "fail"
    # Keep box changed is over-redaction: warning, not a HOLD (L3).
    good = original.copy()
    ImageDraw.Draw(good).rectangle([10, 10, 29, 19], fill=(0, 0, 0))
    ImageDraw.Draw(good).point((50, 30), fill=(1, 2, 3))
    good.save(red_path)
    plan = [{"ex_id": "EX1", "item_id": "item1", "kind": "account_number",
             "mask_box": {"x1": 10, "y1": 10, "x2": 30, "y2": 20},
             "keep_box": {"x1": 40, "y1": 25, "x2": 55, "y2": 35}}]
    checked = redact_mod.check_leak(orig_path, red_path, plan)
    assert checked["status"] == "pass"
    assert any(f.get("warning") for f in checked["findings"])


def test_stamp_moves_down_past_masks(tmp_path):
    img = Image.new("RGB", (300, 200), (255, 255, 255))
    orig_path = tmp_path / "orig.png"
    red_path = tmp_path / "red.png"
    img.save(orig_path)
    mask = [200, 30, 290, 70]
    try:
        font = ImageFont.truetype(str(NANUM_BOLD), 20)
    except OSError:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), "갑 제1호증", font=font)
    rect = redact_mod.place_stamp_avoiding(
        300, 200, int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1]), [mask])
    assert not redact_mod.rects_overlap(rect, mask)
    assert rect[1] >= mask[3]  # moved down
    redact_mod.burn_redacted_copy(orig_path, red_path, [mask], "갑 제1호증")
    red = Image.open(red_path).convert("RGB")
    assert set(red.crop(tuple(mask)).tobytes()) <= {0}
    assert img.tobytes() != red.tobytes()


# --- redaction golden (needs record fixtures for faces) ---------------------
def test_redactions_burn_and_keep(env, shared_case):
    body = env.get(f"/api/cases/{shared_case}/redactions").json()
    assert body["leak_check"]["status"] == "pass", body["leak_check"]
    assert body["plan"], "empty redaction plan"
    assert {p["ex_id"] for p in body["previews"]} >= {
        "EX1", "EX2", "EX4", "EX5", "EX6"}
    for preview in body["previews"]:
        assert preview["status"] == "redacted"
    by_preview = {p["ex_id"]: p for p in body["previews"]}
    assert by_preview["EX6"]["needs_review"] is True
    assert redact_mod.LEAK_REVIEW_REASON in (by_preview["EX6"]["reason"] or "")
    for ex_id in ("EX1", "EX2", "EX4", "EX5"):
        assert by_preview[ex_id]["needs_review"] is False
        assert by_preview[ex_id]["reason"] is None
    # Every mask is fully black in its redacted copy; keeps equal originals.
    from app.agents.case_state import evidence_dir, files_dir
    from app.agents import intake as intake_mod
    state = coord.get_case(shared_case)
    by_ex = {r.ex_id: r for r in state.evidence}
    for entry in body["plan"]:
        ex_id = entry["ex_id"]
        record = by_ex[ex_id]
        preview = intake_mod.preview_path(state, record)
        redacted = Path(files_dir(shared_case)) / f"redacted_{ex_id}.png"
        assert redacted.exists()
        orig = Image.open(preview).convert("RGB")
        red = Image.open(redacted).convert("RGB")
        mask = entry["mask_box"]
        box = (mask["x1"], mask["y1"], mask["x2"], mask["y2"])
        assert set(red.crop(box).tobytes()) == {0}
        keep = entry.get("keep_box")
        if keep:
            kbox = (keep["x1"], keep["y1"], keep["x2"], keep["y2"])
            assert orig.crop(kbox).tobytes() == red.crop(kbox).tobytes()
    # Originals untouched.
    for record in state.evidence:
        if record.kind == "video":
            continue
        path = evidence_dir(shared_case) / record.stored_name
        assert redact_mod.sha256_file(path) == record.sha256
    # Exhibit stamp present (top-right pixels differ from original).
    record = by_ex["EX4"]
    preview = intake_mod.preview_path(state, record)
    redacted = Path(files_dir(shared_case)) / "redacted_EX4.png"
    orig = Image.open(preview).convert("RGB")
    red = Image.open(redacted).convert("RGB")
    assert orig.tobytes() != red.tobytes()
    # Redacted copies open inline as PNG (L7).
    res = env.get(by_preview["EX4"]["url"])
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert "content-disposition" not in res.headers


def test_leak_bands_pin_current_boxes(env, shared_case):
    """L1: EX6 three masks trip the band check, EX4/EX5 are clean zeros."""
    assert redact_mod.BAND_THRESHOLD == 5
    body = env.get(f"/api/cases/{shared_case}/redactions").json()
    by_key = {(e["ex_id"], e["item_id"]): e for e in body["plan"]}
    for key in [("EX4", "item6"), ("EX4", "item10"),
                ("EX5", "item6"), ("EX5", "item10")]:
        entry = by_key[key]
        assert entry["band_counts"] == {"top": 0, "bottom": 0, "left": 0}
        assert entry["needs_review"] is False
    for key in [("EX6", "item8"), ("EX6", "item14"), ("EX6", "item25")]:
        entry = by_key[key]
        assert max(entry["band_counts"].values()) >= 5, entry["band_counts"]
        assert entry["needs_review"] is True
        assert redact_mod.LEAK_REVIEW_REASON in entry["reason"]
    for key in [("EX1", "face1"), ("EX2", "face1")]:
        assert max(by_key[key]["band_counts"].values()) == 0


def _golden_mask_covered(orig, red, mask_box):
    """Every dark-original pixel inside a golden mask is black."""
    box = [int(v) for v in mask_box]
    opx, rpx = orig.load(), red.load()
    for yy in range(box[1], box[3]):
        for xx in range(box[0], box[2]):
            r, g, b = opx[xx, yy][:3]
            if (r + g + b) / 3.0 < 128:
                rr, gg, bb = rpx[xx, yy][:3]
                if (rr, gg, bb) != (0, 0, 0):
                    return False
    return True


def test_golden_masks_covered_and_kept(env, shared_case):
    """L5: EX4/EX5 glyph fully hidden, keeps identical (full pixels)."""
    from app.agents.case_state import files_dir
    from app.agents import intake as intake_mod
    state = coord.get_case(shared_case)
    by_ex = {r.ex_id: r for r in state.evidence}
    golden = load_golden()
    targets = [t for t in golden["redaction_targets"]
               if t["ex_id"] in ("EX4", "EX5")]
    assert len(targets) == 4
    for target in targets:
        record = by_ex[target["ex_id"]]
        orig = Image.open(
            intake_mod.preview_path(state, record)).convert("RGB")
        red = Image.open(
            Path(files_dir(shared_case))
            / f"redacted_{target['ex_id']}.png").convert("RGB")
        assert _golden_mask_covered(orig, red, target["mask_box"]), target
        keep = target["keep_box"]
        kbox = (keep[0], keep[1], keep[2], keep[3])
        assert orig.crop(kbox).tobytes() == red.crop(kbox).tobytes(), target


def test_mutation_shifted_masks_fail(env, shared_case, tmp_path):
    """L5: the golden check fails when mask boxes are moved (+300px)."""
    from app.agents import intake as intake_mod
    state = coord.get_case(shared_case)
    by_ex = {r.ex_id: r for r in state.evidence}
    body = env.get(f"/api/cases/{shared_case}/redactions").json()
    plan_by_ex = {}
    for entry in body["plan"]:
        plan_by_ex.setdefault(entry["ex_id"], []).append(entry)
    golden = load_golden()
    failed = 0
    for target in golden["redaction_targets"]:
        if target["ex_id"] not in ("EX4", "EX5"):
            continue
        record = by_ex[target["ex_id"]]
        preview = intake_mod.preview_path(state, record)
        shifted = []
        for entry in plan_by_ex[target["ex_id"]]:
            mask = entry["mask_box"]
            shifted.append([mask["x1"], mask["y1"] + 300,
                            mask["x2"], mask["y2"] + 300])
        red_path = tmp_path / f"mut_{target['ex_id']}.png"
        redact_mod.burn_redacted_copy(preview, red_path, shifted, "")
        orig = Image.open(preview).convert("RGB")
        red = Image.open(red_path).convert("RGB")
        if not _golden_mask_covered(orig, red, target["mask_box"]):
            failed += 1
    assert failed == 4


def test_redaction_confirmed_defaults_and_validates(env):
    case_id = _to_checkpoint_1(env)
    review = env.get(f"/api/cases/{case_id}/review").json()
    facts = demo_inputs.build_demo_confirmed_facts(review)
    assert "redaction_confirmed" not in facts
    res = env.put(f"/api/cases/{case_id}/facts", json=facts)
    assert res.status_code == 200
    state = coord.get_case(case_id)
    assert state.confirmed_facts["redaction_confirmed"] is False
    # New case for True + bad value.
    res = env.post("/api/cases/sample", json={"set": "kr"})
    case2 = res.json()["case_id"]
    env.post(f"/api/cases/{case2}/run", json={})
    review2 = env.get(f"/api/cases/{case2}/review").json()
    facts2 = demo_inputs.build_demo_confirmed_facts(review2)
    facts2["redaction_confirmed"] = True
    res = env.put(f"/api/cases/{case2}/facts", json=facts2)
    assert res.status_code == 200
    assert coord.get_case(case2).confirmed_facts["redaction_confirmed"] is True


def test_redaction_confirmed_rejects_non_bool(env):
    case_id = _to_checkpoint_1(env)
    review = env.get(f"/api/cases/{case_id}/review").json()
    facts = demo_inputs.build_demo_confirmed_facts(review)
    facts["redaction_confirmed"] = "yes"
    res = env.put(f"/api/cases/{case_id}/facts", json=facts)
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "bad_request"
    facts["redaction_confirmed"] = 1
    res = env.put(f"/api/cases/{case_id}/facts", json=facts)
    assert res.status_code == 400
    assert env.get(f"/api/cases/{case_id}").json()["state"] == "CHECKPOINT_1"


def test_vision_hold_path_is_fail_closed(env, monkeypatch):
    """L2+L7: vision errors hold the evidence, keep spent cost, continue."""
    ex1_bytes = (SAMPLE / "chat_01.png").read_bytes()
    ex2_bytes = (SAMPLE / "chat_02_tall.png").read_bytes()
    real = vision_mod.run_sam_call
    seen = {"ex2": 0}

    def fake(prompt_text, image_bytes, filename, meta_mode, run_id):
        if bytes(image_bytes) == ex1_bytes:
            raise deps.FixtureNotFound("probe: no EX1 fixture")
        if bytes(image_bytes) == ex2_bytes:
            seen["ex2"] += 1
            if seen["ex2"] > 2:
                raise deps.FixtureNotFound("probe: EX2 fails after 2")
        return real(prompt_text, image_bytes, filename, meta_mode, run_id)

    monkeypatch.setattr(vision_mod, "run_sam_call", fake)
    res = env.post("/api/cases/sample", json={"set": "kr"})
    case_id = res.json()["case_id"]
    res = env.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "CHECKPOINT_1", res.text
    segments = {s["ex_id"]: s
                for s in env.get(f"/api/cases/{case_id}/segments").json()}
    assert segments["EX1"]["status"] == "hold"
    assert "probe" in segments["EX1"]["error"]
    assert segments["EX2"]["status"] == "hold"
    # Spent calls stay on the step cost: EX2x2 + EX4x4 + EX5x4 + EX6x5.
    view = env.get(f"/api/cases/{case_id}").json()
    vision = next(s for s in view["steps"] if s["key"] == "vision")
    assert vision["cost_usd"] == "0.0375"
    assert [s["ex_id"] for s in vision["substeps"]
            if s["status"] == "hold"] == ["EX1", "EX2"]
    body = env.get(f"/api/cases/{case_id}/redactions").json()
    by_preview = {p["ex_id"]: p for p in body["previews"]}
    assert by_preview["EX1"]["status"] == "not_redacted"
    assert "시각 감식" in (by_preview["EX1"]["reason"] or "")
    assert by_preview["EX1"]["url"] is None
    assert by_preview["EX2"]["status"] == "not_redacted"
    assert body["leak_check"]["status"] == "pass"
    from app.agents.case_state import files_dir
    assert not (Path(files_dir(case_id)) / "redacted_EX1.png").exists()
    assert not (Path(files_dir(case_id)) / "redacted_EX2.png").exists()
    assert (Path(files_dir(case_id)) / "redacted_EX6.png").exists()
    assert by_preview["EX6"]["needs_review"] is True


def test_privacy_leak_hold_resumes(env):
    """L3: POST /run re-executes from the redaction stage after a leak."""
    real_burn = redact_mod.burn_redacted_copy

    def corrupting(original, redacted, masks, label, keeps=None):
        real_burn(original, redacted, masks, label, keeps)
        if masks:
            img = Image.open(redacted).convert("RGB")
            first = [int(v) for v in masks[0]]
            cx, cy = (first[0] + first[2]) // 2, (first[1] + first[3]) // 2
            ImageDraw.Draw(img).rectangle([cx, cy, cx + 2, cy + 2],
                                          fill=(255, 255, 255))
            img.save(redacted)

    redact_mod.burn_redacted_copy = corrupting
    try:
        res = env.post("/api/cases/sample", json={"set": "kr"})
        case_id = res.json()["case_id"]
        res = env.post(f"/api/cases/{case_id}/run", json={})
        assert res.status_code == 200, res.text
        assert res.json()["state"] == "HOLD", res.text
        reasons = res.json()["hold_reasons"]
        assert len(reasons) == 1 and reasons[0]["code"] == "privacy_leak"
    finally:
        redact_mod.burn_redacted_copy = real_burn
    review = env.get(f"/api/cases/{case_id}/review").json()
    facts = demo_inputs.build_demo_confirmed_facts(review)
    res = env.put(f"/api/cases/{case_id}/facts", json=facts)
    assert res.status_code == 409
    res = env.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "CHECKPOINT_1", res.text
    assert res.json()["hold_reasons"] == []
    view = env.get(f"/api/cases/{case_id}").json()
    privacy = next(s for s in view["steps"] if s["key"] == "privacy")
    assert privacy["status"] == "done"


def _privacy_unit_inputs(tmp_path, variant):
    import shutil
    previews = tmp_path / "prev"
    previews.mkdir(parents=True)
    files = tmp_path / "files"
    files.mkdir(parents=True)
    for name in ("chat_01.png", "transfer_loan.png"):
        shutil.copy(SAMPLE / name, previews / name)
    ref_w, ref_h = 640, 640
    item_box = {"x1": 218, "y1": 198, "x2": 403, "y2": 234,
                "system": "pixel", "ref_w": ref_w, "ref_h": ref_h}
    if variant == "bad_box":
        item_box = {"x1": 403, "y1": 198, "x2": 218, "y2": 234,
                    "system": "pixel", "ref_w": ref_w, "ref_h": ref_h}
    evidence = [
        SimpleNamespace(ex_id="EX1", kind="image", label="갑 제1호증",
                        sha256="x", stored_name="a.png",
                        status="ok", filename="chat_01.png"),
        SimpleNamespace(ex_id="EX4", kind="image", label="갑 제4호증",
                        sha256="x", stored_name="b.png",
                        status="hold" if variant == "reading_hold" else "ok",
                        filename="transfer_loan.png"),
    ]
    readings = [
        {"ex_id": "EX1", "items": []},
        {"ex_id": "EX4", "items": [
            {"item_id": "item6", "kind": "account_number",
             "text_verbatim": "000-0000-1234", "box": item_box}]},
    ]
    if variant == "reading_missing":
        readings = [r for r in readings if r["ex_id"] != "EX4"]
    segments = [
        {"ex_id": "EX1", "model": "sam-3.1", "objects": [],
         "status": "not_found"},
        {"ex_id": "EX4", "model": "sam-3.1", "objects": [],
         "status": "hold" if variant == "vision_hold" else "not_found",
         **({"error": "probe"} if variant == "vision_hold" else {})},
    ]
    preview_paths = {"EX1": previews / "chat_01.png",
                     "EX4": previews / "transfer_loan.png"}
    if variant == "preview_missing":
        (previews / "transfer_loan.png").unlink()
    preview_sizes = {"EX1": (640, 960), "EX4": (640, 640)}
    return evidence, readings, segments, preview_paths, preview_sizes, files


def test_run_privacy_fail_closed_variants(tmp_path):
    """L2 unit: every incomplete evidence becomes not_redacted, no copy."""
    for variant, needle in [
            ("preview_missing", "미리보기"),
            ("reading_hold", "판독"),
            ("reading_missing", "판독"),
            ("vision_hold", "시각 감식"),
            ("bad_box", "가림 계획")]:
        inputs = _privacy_unit_inputs(tmp_path / variant, variant)
        evidence, readings, segments, paths, sizes, files = inputs
        out = privacy_mod.run_privacy("case_000000000001", evidence,
                                      readings, segments, paths, sizes,
                                      files)
        by_preview = {p["ex_id"]: p for p in out["previews"]}
        assert by_preview["EX4"]["status"] == "not_redacted", variant
        assert needle in (by_preview["EX4"]["reason"] or ""), variant
        assert not (files / "redacted_EX4.png").exists(), variant
    inputs = _privacy_unit_inputs(tmp_path / "ok", "ok")
    out = privacy_mod.run_privacy("case_000000000001", *inputs)
    by_preview = {p["ex_id"]: p for p in out["previews"]}
    assert by_preview["EX4"]["status"] == "redacted"
    assert (inputs[5] / "redacted_EX4.png").exists()


def test_segments_redactions_404(env):
    assert env.get(
        "/api/cases/case_000000000000/segments").status_code == 404
    assert env.get(
        "/api/cases/case_000000000000/redactions").status_code == 404
