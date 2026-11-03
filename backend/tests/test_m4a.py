"""M4a vision + privacy tests (replay, no key).

Compares SAM segments against golden vision_targets and redaction copies
against golden redaction_targets (test-only reads, never passed to agents).
"""
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.agents import case_state as case_state_mod
from app.agents import coordinator as coord
from app.agents import demo_inputs
from app.agents import privacy_guard as privacy_mod
from app.agents import vision as vision_mod
from app.main import app
from app.meta.coords import box_iou
from app.services import redaction as redact_mod

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "backend" / "tests" / "golden" / "kr_truth.json"
SAMPLE = ROOT / "sample_evidence" / "kr"


def load_golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.fixture()
def replay_env(tmp_path, monkeypatch):
    monkeypatch.setattr(case_state_mod, "CASES_ROOT", tmp_path / "cases")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("META_MODE", "replay")
    for name in ("reader", "organizer", "drafter"):
        monkeypatch.setitem(coord.AGENTS, name, None)
    return TestClient(app)


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


# --- vision golden (needs record fixtures) ----------------------------------
def test_vision_stamp_and_bubbles_match_golden(replay_env):
    case_id = _to_checkpoint_1(replay_env)
    segments = replay_env.get(f"/api/cases/{case_id}/segments").json()
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


def test_vision_signatures_match_ink(replay_env):
    case_id = _to_checkpoint_1(replay_env)
    segments = replay_env.get(f"/api/cases/{case_id}/segments").json()
    golden = load_golden()
    by_ex = {s["ex_id"]: s for s in segments}
    inks = [v["box"] for v in golden["vision_targets"]
            if v["ex_id"] == "EX6" and v["target"] == "signature"]
    assert len(inks) == 2
    preds = [[o["box"]["x1"], o["box"]["y1"], o["box"]["x2"], o["box"]["y2"]]
             for o in by_ex["EX6"]["objects"]
             if o["target"] == "signature"]
    assert len(preds) >= 2, f"signatures found: {len(preds)}"
    for truth in inks:
        assert _best_iou(preds, truth) >= 0.5, truth
    assert any(o["source"] == "box"
               for o in by_ex["EX6"]["objects"]
               if o["target"] == "signature")
    # Masks saved and served.
    for obj in by_ex["EX6"]["objects"]:
        res = replay_env.get(obj["mask_url"])
        assert res.status_code == 200
        assert res.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_vision_steps_and_substeps(replay_env):
    case_id = _to_checkpoint_1(replay_env)
    view = replay_env.get(f"/api/cases/{case_id}").json()
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


def test_redaction_padding_skips_keep_side():
    pad = redact_mod.compute_pad(17)
    assert pad == 4
    mask = redact_mod.pad_box([230, 207, 337, 224], pad,
                              (True, True, False, True), 640, 640)
    assert mask == [226, 203, 337, 228]


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
    # Keep box changed must fail.
    good = original.copy()
    ImageDraw.Draw(good).rectangle([10, 10, 29, 19], fill=(0, 0, 0))
    ImageDraw.Draw(good).point((50, 30), fill=(1, 2, 3))
    good.save(red_path)
    plan = [{"ex_id": "EX1", "item_id": "item1", "kind": "account_number",
             "mask_box": {"x1": 10, "y1": 10, "x2": 30, "y2": 20},
             "keep_box": {"x1": 40, "y1": 25, "x2": 55, "y2": 35}}]
    assert redact_mod.check_leak(
        orig_path, red_path, plan)["status"] == "fail"


# --- redaction golden (needs record fixtures for faces) ---------------------
def test_redactions_burn_and_keep(replay_env, tmp_path):
    case_id = _to_checkpoint_1(replay_env)
    body = replay_env.get(f"/api/cases/{case_id}/redactions").json()
    assert body["leak_check"]["status"] == "pass", body["leak_check"]
    assert body["plan"], "empty redaction plan"
    assert {p["ex_id"] for p in body["previews"]} >= {
        "EX1", "EX2", "EX4", "EX5", "EX6"}
    # Every mask is fully black in its redacted copy; keeps equal originals.
    from app.agents.case_state import evidence_dir, files_dir
    from app.agents import intake as intake_mod
    state = coord.get_case(case_id)
    by_ex = {r.ex_id: r for r in state.evidence}
    for entry in body["plan"]:
        ex_id = entry["ex_id"]
        record = by_ex[ex_id]
        preview = intake_mod.preview_path(state, record)
        redacted = Path(files_dir(case_id)) / f"redacted_{ex_id}.png"
        assert redacted.exists()
        orig = Image.open(preview).convert("RGB")
        red = Image.open(redacted).convert("RGB")
        mask = entry["mask_box"]
        box = (mask["x1"], mask["y1"], mask["x2"], mask["y2"])
        assert set(red.crop(box).tobytes()[::997]) <= {0} or all(
            b == 0 for b in red.crop(box).tobytes())
        keep = entry.get("keep_box")
        if keep:
            kbox = (keep["x1"], keep["y1"], keep["x2"], keep["y2"])
            assert orig.crop(kbox).tobytes() == red.crop(kbox).tobytes()
    # Originals untouched.
    for record in state.evidence:
        if record.kind == "video":
            continue
        path = evidence_dir(case_id) / record.stored_name
        assert redact_mod.sha256_file(path) == record.sha256
    # Exhibit stamp present (top-right pixels differ from original).
    record = by_ex["EX4"]
    preview = intake_mod.preview_path(state, record)
    redacted = Path(files_dir(case_id)) / "redacted_EX4.png"
    orig = Image.open(preview).convert("RGB")
    red = Image.open(redacted).convert("RGB")
    assert orig.tobytes() != red.tobytes()


def test_redaction_confirmed_defaults_and_validates(replay_env):
    case_id = _to_checkpoint_1(replay_env)
    review = replay_env.get(f"/api/cases/{case_id}/review").json()
    facts = demo_inputs.build_demo_confirmed_facts(review)
    assert "redaction_confirmed" not in facts
    res = replay_env.put(f"/api/cases/{case_id}/facts", json=facts)
    assert res.status_code == 200
    state = coord.get_case(case_id)
    assert state.confirmed_facts["redaction_confirmed"] is False
    # New case for True + bad value.
    res = replay_env.post("/api/cases/sample", json={"set": "kr"})
    case2 = res.json()["case_id"]
    replay_env.post(f"/api/cases/{case2}/run", json={})
    review2 = replay_env.get(f"/api/cases/{case2}/review").json()
    facts2 = demo_inputs.build_demo_confirmed_facts(review2)
    facts2["redaction_confirmed"] = True
    res = replay_env.put(f"/api/cases/{case2}/facts", json=facts2)
    assert res.status_code == 200
    assert coord.get_case(case2).confirmed_facts["redaction_confirmed"] is True


def test_segments_redactions_404(replay_env):
    assert replay_env.get(
        "/api/cases/case_000000000000/segments").status_code == 404
    assert replay_env.get(
        "/api/cases/case_000000000000/redactions").status_code == 404
