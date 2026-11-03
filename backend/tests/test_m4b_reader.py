"""M4b tests: tiling, box flags, keyframes, video merge, scorer, eval replay.

All keyless (replay/fixtures only). The eval replay test needs
reports/M4b-reader-eval.json from the live comparison runs; the video
replay test needs the record-mode keyframe fixtures.
"""

import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import eval_reader  # noqa: E402
from app.agents import keyframes as keyframes_mod  # noqa: E402
from app.agents import intake as intake_mod  # noqa: E402
from app.agents import reader as reader_mod  # noqa: E402
from app.agents.reader import ModelReadingItem  # noqa: E402
from app.agents.spark import load_prompt  # noqa: E402
from app.services.naming import find_forbidden_draft  # noqa: E402
from test_case_replay import SAMPLE_TOKENS  # noqa: E402

GOLDEN = ROOT / "backend" / "tests" / "golden" / "kr_truth.json"
EVAL_JSON = ROOT / "reports" / "M4b-reader-eval.json"
EX3 = ROOT / "sample_evidence" / "kr" / "chat_02_scroll.mp4"

needs_ffmpeg = pytest.mark.skipif(
    __import__("shutil").which("ffmpeg") is None,
    reason="ffmpeg이 없어 영상 핵심 프레임 테스트를 건너뜁니다(INT-3 1).")


def _item(kind="utterance", text="가나다", box=None, **kw):
    row = {"kind": kind, "text_verbatim": text, "normalized": None,
           "box": dict(box or {"x1": 10, "y1": 10, "x2": 100, "y2": 40,
                               "system": "pixel", "ref_w": 640,
                               "ref_h": 960}),
           "speaker": None, "side": None, "confidence": 0.9}
    row.update(kw)
    return row


# --- tiling planner ----------------------------------------------------------

def test_plan_tiles_square_reads_whole():
    assert reader_mod.plan_tiles(640, 640) == [(0, 0, 640, 640)]
    assert reader_mod.plan_tiles(1240, 900) == [(0, 0, 1240, 900)]


def test_plan_tiles_tall_covers_with_overlap():
    tiles = reader_mod.plan_tiles(640, 2400, 1.0, 0.1)
    assert len(tiles) == 5
    assert tiles[0][1] == 0 and tiles[-1][3] == 2400
    for x0, y0, x1, y1 in tiles:
        assert (x0, x1) == (0, 640)
        assert (y1 - y0) / (x1 - x0) <= 1.0 + 1e-9
    for (_, _, _, bottom), (_, top, _, _) in zip(tiles, tiles[1:]):
        assert bottom - top >= 64  # >= 10% of 640
    tops = [top for _, top, _, _ in tiles]
    assert tops == [0, 440, 880, 1320, 1760]  # evenly spaced


def test_plan_tiles_ex1_splits_at_default():
    tiles = reader_mod.plan_tiles(640, 960)
    assert len(tiles) == 2
    assert tiles[0] == (0, 0, 640, 640)
    assert tiles[1][1] > 0 and tiles[1][3] == 960


# --- box conversion + flags ---------------------------------------------------

def test_convert_box_in_range_matches_pixels():
    box, warned = reader_mod.convert_box([0, 0, 1000, 1000], 640, 480)
    assert (box, warned) == ([0, 0, 640, 480], False)
    box, warned = reader_mod.convert_box([100, 250, 200, 500], 640, 960)
    assert (box, warned) == ([64, 240, 128, 480], False)


def test_convert_box_out_of_range_flags_without_clamp():
    box, warned = reader_mod.convert_box([20, 833, 732, 1479], 640, 2400)
    assert warned is True
    assert box == [13, 1999, 468, 3550]


def test_model_items_flag_only_out_of_range():
    items = reader_mod.model_items_to_pixels(
        [ModelReadingItem(kind="amount", text_verbatim="5원",
                          normalized="5", box=[0, 0, 100, 100]),
         ModelReadingItem(kind="amount", text_verbatim="6원",
                          normalized="6", box=[0, 0, 100, 1479])],
        (640, 2400),
    )
    assert "box_warning" not in items[0]
    assert items[1]["box_warning"] == "out_of_range"
    assert items[1]["box"]["y2"] > 2400  # raw, not clamped
    # normalized kept for amount, dropped for other kinds
    utter = reader_mod.model_items_to_pixels(
        [ModelReadingItem(kind="utterance", text_verbatim="말",
                          normalized="말", box=[0, 0, 10, 10])], (640, 640))
    assert utter[0]["normalized"] is None


def test_tile_items_map_back_to_original_pixels():
    tile = (0, 960, 640, 1920)
    items = reader_mod.tile_items_to_pixels(
        [ModelReadingItem(kind="label", text_verbatim="칸",
                          box=[0, 0, 1000, 1000])],
        tile, (640, 2400),
    )
    assert items[0]["box"]["x1"] == 0
    assert items[0]["box"]["y1"] == 960
    assert items[0]["box"]["x2"] == 640
    assert items[0]["box"]["y2"] == 1920


def test_pad_to_square_keeps_origin_mapping():
    from PIL import Image

    image = Image.new("RGB", (640, 960), (10, 20, 30))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    padded, side = reader_mod.pad_to_square_png(buffer.getvalue())
    assert side == 960
    with Image.open(io.BytesIO(padded)) as reopened:
        assert reopened.size == (960, 960)
        assert reopened.getpixel((0, 0)) == (10, 20, 30)
        assert reopened.getpixel((959, 959)) == (255, 255, 255)


# --- tile merge ----------------------------------------------------------------

def test_merge_tile_items_dedupes_boundary_dupes():
    tiles = [(0, 0, 640, 640), (0, 576, 640, 1216)]
    same = {"x1": 100, "y1": 590, "x2": 300, "y2": 640,
            "system": "pixel", "ref_w": 640, "ref_h": 1216}
    per_tile = [[_item(text="같은 말", box=same)],
                [_item(text="같은 말", box=dict(same))]]
    merged = reader_mod.merge_tile_items(per_tile, tiles)
    assert len(merged) == 1


def test_merge_tile_items_keeps_distant_repeats():
    tiles = [(0, 0, 640, 640), (0, 576, 640, 1216)]
    top = {"x1": 72, "y1": 130, "x2": 176, "y2": 144,
           "system": "pixel", "ref_w": 640, "ref_h": 1216}
    bottom = {"x1": 22, "y1": 1000, "x2": 126, "y2": 1014,
              "system": "pixel", "ref_w": 640, "ref_h": 1216}
    per_tile = [[_item(kind="party_name", text="탁나루(SAMPLE)", box=top)],
                [_item(kind="party_name", text="탁나루(SAMPLE)", box=bottom)]]
    merged = reader_mod.merge_tile_items(per_tile, tiles)
    assert len(merged) == 2


def test_merge_tile_items_pairs_biased_band_dupes():
    tiles = [(0, 0, 1240, 1240), (0, 514, 1240, 1754)]
    upper = {"x1": 441, "y1": 600, "x2": 806, "y2": 636,
             "system": "pixel", "ref_w": 1240, "ref_h": 1754}
    lower = {"x1": 415, "y1": 528, "x2": 724, "y2": 549,
             "system": "pixel", "ref_w": 1240, "ref_h": 1754}
    per_tile = [[_item(kind="address", text="경기도 샘플시 데모동 0",
                       box=upper)],
                [_item(kind="address", text="경기도 샘플시 데모동 0",
                       box=lower)]]
    merged = reader_mod.merge_tile_items(per_tile, tiles)
    assert len(merged) == 1
    assert "_tile" not in merged[0]
    box = merged[0]["box"]
    # INT-3 1b: union, never the average (less cover would leak redaction).
    assert [box["x1"], box["y1"], box["x2"], box["y2"]] == [415, 528, 806, 636]


def test_merge_tile_items_pairs_two_by_two_in_order():
    tiles = [(0, 0, 640, 640), (0, 320, 640, 960)]
    first_a = {"x1": 72, "y1": 360, "x2": 176, "y2": 374,
               "system": "pixel", "ref_w": 640, "ref_h": 960}
    second_a = {"x1": 72, "y1": 500, "x2": 176, "y2": 514,
                "system": "pixel", "ref_w": 640, "ref_h": 960}
    first_b = {"x1": 70, "y1": 372, "x2": 174, "y2": 386,
               "system": "pixel", "ref_w": 640, "ref_h": 960}
    second_b = {"x1": 70, "y1": 512, "x2": 174, "y2": 526,
                "system": "pixel", "ref_w": 640, "ref_h": 960}
    per_tile = [[_item(kind="party_name", text="탁나루(SAMPLE)", box=first_a),
                 _item(kind="party_name", text="탁나루(SAMPLE)", box=second_a)],
                [_item(kind="party_name", text="탁나루(SAMPLE)", box=first_b),
                 _item(kind="party_name", text="탁나루(SAMPLE)", box=second_b)]]
    merged = reader_mod.merge_tile_items(per_tile, tiles)
    assert len(merged) == 2


def test_merge_tile_items_drops_cut_fragments():
    tiles = [(0, 0, 640, 640), (0, 576, 640, 1216)]
    whole = {"x1": 20, "y1": 585, "x2": 420, "y2": 660,
             "system": "pixel", "ref_w": 640, "ref_h": 1216}
    fragment = {"x1": 20, "y1": 585, "x2": 420, "y2": 635,
                "system": "pixel", "ref_w": 640, "ref_h": 1216}
    per_tile = [[_item(text="오늘 100만 원 먼저 보냈어.", box=whole)],
                [_item(text="오늘 100만 원 먼저", box=fragment)]]
    merged = reader_mod.merge_tile_items(per_tile, tiles)
    assert [m["text_verbatim"] for m in merged] == ["오늘 100만 원 먼저 보냈어."]


# --- INT-3 1b: boundary merge, union, order, caps --------------------------------

def test_merge_tile_items_merges_cross_kind_typo_dupes():
    """EX1 타나루/탁나루: kinds differ, one-char OCR typo -> one union item.

    Kills the merge-branch-removal mutation (no merge -> 2 items).
    """
    tiles = [(0, 0, 640, 640), (0, 320, 640, 960)]
    upper = {"x1": 70, "y1": 400, "x2": 250, "y2": 430,
             "system": "pixel", "ref_w": 640, "ref_h": 960}
    lower = {"x1": 74, "y1": 408, "x2": 246, "y2": 434,
             "system": "pixel", "ref_w": 640, "ref_h": 960}
    per_tile = [[_item(kind="party_name", text="탁나루(SAMPLE)", box=upper)],
                [_item(kind="label", text="타나루(SAMPLE)", box=lower)]]
    merged = reader_mod.merge_tile_items(per_tile, tiles)
    assert len(merged) == 1
    box = merged[0]["box"]
    assert (box["x1"], box["y1"], box["x2"], box["y2"]) == (70, 400, 250, 434)


def test_merge_tile_items_merges_linebreak_only_utterances():
    tiles = [(0, 0, 640, 640), (0, 320, 640, 960)]
    upper = {"x1": 60, "y1": 420, "x2": 400, "y2": 470,
             "system": "pixel", "ref_w": 640, "ref_h": 960}
    lower = {"x1": 62, "y1": 424, "x2": 398, "y2": 472,
             "system": "pixel", "ref_w": 640, "ref_h": 960}
    per_tile = [[_item(text="내일까지\n꼭 갚을게요.", box=upper)],
                [_item(text="내일까지 꼭 갚을게요.", box=lower)]]
    merged = reader_mod.merge_tile_items(per_tile, tiles)
    assert len(merged) == 1


def test_merge_tile_items_keeps_pairs_beyond_distance_limit():
    """Same text 80px apart (beyond the 64px band cap) never merges (B4-8).

    Both boxes touch the overlap band, so only the distance limit keeps
    them apart. Kills the distance-limit-removal mutation (-> 1 item).
    """
    tiles = [(0, 0, 640, 640), (0, 576, 640, 1216)]
    upper = {"x1": 70, "y1": 550, "x2": 250, "y2": 600,
             "system": "pixel", "ref_w": 640, "ref_h": 1216}
    lower = {"x1": 70, "y1": 630, "x2": 250, "y2": 680,
             "system": "pixel", "ref_w": 640, "ref_h": 1216}
    per_tile = [[_item(kind="amount", text="300,000원", box=upper)],
                [_item(kind="amount", text="300,000원", box=lower)]]
    merged = reader_mod.merge_tile_items(per_tile, tiles)
    assert len(merged) == 2


def test_merge_tile_items_pairs_nearest_not_zip_order():
    """B4-8: equal counts must not zip-pair different lines by order.

    Left reads lines A and B; right reads only B's twin. A must stay,
    B must merge with its twin (not with A).
    """
    tiles = [(0, 0, 640, 640), (0, 320, 640, 960)]
    line_a = {"x1": 70, "y1": 340, "x2": 250, "y2": 366,
              "system": "pixel", "ref_w": 640, "ref_h": 960}
    line_b = {"x1": 70, "y1": 500, "x2": 250, "y2": 526,
              "system": "pixel", "ref_w": 640, "ref_h": 960}
    line_b_twin = {"x1": 72, "y1": 508, "x2": 248, "y2": 532,
                   "system": "pixel", "ref_w": 640, "ref_h": 960}
    per_tile = [[_item(text="네", box=line_a),
                 _item(text="네", box=line_b)],
                [_item(text="네", box=line_b_twin)]]
    merged = reader_mod.merge_tile_items(per_tile, tiles)
    assert len(merged) == 2
    tops = sorted(m["box"]["y1"] for m in merged)
    assert tops[0] <= 340 and tops[1] >= 500


def test_merge_tile_items_never_merges_different_numbers():
    """EX6 phones one digit apart are two redaction targets, not one."""
    tiles = [(0, 0, 1240, 1240), (0, 514, 1240, 1754)]
    first = {"x1": 470, "y1": 600, "x2": 725, "y2": 625,
             "system": "pixel", "ref_w": 1240, "ref_h": 1754}
    second = {"x1": 470, "y1": 700, "x2": 725, "y2": 725,
              "system": "pixel", "ref_w": 1240, "ref_h": 1754}
    per_tile = [[_item(kind="phone", text="010-0000-0001", box=first)],
                [_item(kind="phone", text="010-0000-0002", box=second)]]
    merged = reader_mod.merge_tile_items(per_tile, tiles)
    assert len(merged) == 2


def test_merge_tile_items_keeps_amount_inside_utterance():
    """An amount box inside its utterance box is not a fragment."""
    tiles = [(0, 0, 640, 640), (0, 320, 640, 960)]
    utter = {"x1": 60, "y1": 420, "x2": 460, "y2": 470,
             "system": "pixel", "ref_w": 640, "ref_h": 960}
    amount = {"x1": 70, "y1": 425, "x2": 190, "y2": 465,
              "system": "pixel", "ref_w": 640, "ref_h": 960}
    per_tile = [[_item(text="300,000원을 빌렸습니다.", box=utter)],
                [_item(kind="amount", text="300,000원", box=amount)]]
    merged = reader_mod.merge_tile_items(per_tile, tiles)
    assert len(merged) == 2


def test_merge_tile_items_sorts_top_bottom_left_right():
    tiles = [(0, 0, 640, 640)]
    low_right = {"x1": 300, "y1": 500, "x2": 500, "y2": 540,
                 "system": "pixel", "ref_w": 640, "ref_h": 640}
    high_right = {"x1": 300, "y1": 100, "x2": 500, "y2": 140,
                  "system": "pixel", "ref_w": 640, "ref_h": 640}
    high_left = {"x1": 40, "y1": 100, "x2": 200, "y2": 140,
                 "system": "pixel", "ref_w": 640, "ref_h": 640}
    per_tile = [[_item(text="낮음", box=low_right),
                 _item(text="높음오른쪽", box=high_right),
                 _item(text="높음왼쪽", box=high_left)]]
    merged = reader_mod.merge_tile_items(per_tile, tiles)
    assert [m["text_verbatim"] for m in merged] == [
        "높음왼쪽", "높음오른쪽", "낮음"]


def test_plan_tiles_caps_very_tall_images():
    """B4-10: a 1080x20000 strip costs at most MAX_TILES calls."""
    tiles = reader_mod.plan_tiles(1080, 20000)
    assert 1 < len(tiles) <= reader_mod.MAX_TILES
    assert tiles[0][1] == 0 and tiles[-1][3] == 20000
    for _, top, _, bottom in tiles:
        assert bottom > top
    for (_, _, _, bottom), (_, top, _, _) in zip(tiles, tiles[1:]):
        assert bottom > top  # still overlapping


def test_crop_tile_png_converts_cmyk():
    """B4-11: CMYK JPEG crops save as PNG instead of raising."""
    from PIL import Image

    image = Image.new("CMYK", (64, 96), (0, 128, 128, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    cropped = reader_mod.crop_tile_png(
        buffer.getvalue(), (0, 0, 64, 96))
    with Image.open(io.BytesIO(cropped)) as reopened:
        assert reopened.format == "PNG"
        assert reopened.size == (64, 96)


# --- keyframes -----------------------------------------------------------------

@needs_ffmpeg
def test_keyframe_extraction_matches_golden_video():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    ex3 = next(e for e in golden["evidences"] if e["ex_id"] == "EX3")
    assert hashlib.sha256(EX3.read_bytes()).hexdigest() == ex3["sha256"]
    frames = keyframes_mod.extract_frames(EX3)
    assert [f["frame_ts"] for f in frames] == (
        [round(k * 0.5, 3) for k in range(14)] + [6.9])
    assert {(f["width"], f["height"]) for f in frames} == {(640, 960)}
    again = keyframes_mod.extract_frames(EX3)
    assert [f["png"] for f in again] == [f["png"] for f in frames]


@needs_ffmpeg
def test_keyframe_extraction_is_frame_exact():
    """Regression: the fps filter once shifted every frame by +2 (M4b)."""
    from PIL import Image, ImageChops

    frames = keyframes_mod.extract_frames(EX3)
    first = Image.open(io.BytesIO(frames[0]["png"])).convert("RGB")
    tall = Image.open(
        ROOT / "sample_evidence" / "kr" / "chat_02_tall.png").convert("RGB")

    def _diff(offset):
        crop = tall.crop((0, offset, 640, offset + 960))
        diff = ImageChops.difference(first, crop)
        px = diff.load()
        vals = []
        for y in range(45, 960, 13):
            for x in range(0, 640, 13):
                r, g, b = px[x, y]
                vals.append((r + g + b) / 3)
        return sum(vals) / len(vals)

    assert _diff(0) < 1.0
    assert _diff(0) < _diff(42)


def test_select_keyframes_dedupes_near_dupes():
    from PIL import Image, ImageDraw

    def _png(left_black):
        image = Image.new("RGB", (64, 64), (255, 255, 255))
        draw = ImageDraw.Draw(image)
        if left_black:
            draw.rectangle([0, 0, 31, 63], fill=(0, 0, 0))
        else:
            draw.rectangle([32, 0, 63, 63], fill=(0, 0, 0))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    dark_left, dark_right = _png(True), _png(False)
    assert keyframes_mod.hamming(keyframes_mod.dhash(dark_left),
                                 keyframes_mod.dhash(dark_left)) == 0
    assert keyframes_mod.hamming(keyframes_mod.dhash(dark_left),
                                 keyframes_mod.dhash(dark_right)) > 6
    frames = [{"frame_ts": 0.0, "png": dark_left, "width": 64, "height": 64},
              {"frame_ts": 0.5, "png": dark_left, "width": 64, "height": 64},
              {"frame_ts": 1.0, "png": dark_right, "width": 64, "height": 64}]
    kept = keyframes_mod.select_keyframes(frames)
    assert [f["frame_ts"] for f in kept] == [0.0, 1.0]


@needs_ffmpeg
def test_extract_video_keyframes_caches_by_manifest(tmp_path):
    first = intake_mod.extract_video_keyframes(EX3, "EX3", dest_dir=tmp_path)
    assert len(first) == 15
    assert (tmp_path / "EX3_keyframes" / "manifest.json").exists()
    second = intake_mod.extract_video_keyframes(EX3, "EX3", dest_dir=tmp_path)
    assert [f["png"] for f in second] == [f["png"] for f in first]


# --- video merge -----------------------------------------------------------------

def test_merge_video_items_keeps_first_fully_visible_ts():
    size = (640, 960)
    partial = {"x1": 20, "y1": 930, "x2": 400, "y2": 958,
               "system": "pixel", "ref_w": 640, "ref_h": 960}
    full = {"x1": 20, "y1": 850, "x2": 400, "y2": 900,
            "system": "pixel", "ref_w": 640, "ref_h": 960}
    merged = reader_mod.merge_video_items(
        [(0.5, [_item(text="말풍선", box=partial)]),
         (1.0, [_item(text="말풍선", box=full)]),
         (1.5, [_item(text="말풍선", box=full)])],
        size,
    )
    assert len(merged) == 1
    assert merged[0]["frame_ts"] == 1.0
    assert merged[0]["box"]["y1"] == 850


def test_merge_video_items_splits_recurring_text():
    size = (640, 960)
    early = {"x1": 72, "y1": 565, "x2": 176, "y2": 579,
             "system": "pixel", "ref_w": 640, "ref_h": 960}
    late = {"x1": 22, "y1": 926, "x2": 126, "y2": 940,
            "system": "pixel", "ref_w": 640, "ref_h": 960}
    grid = [(round(k * 0.5, 3), []) for k in range(9)]
    grid[0] = (0.0, [_item(kind="party_name", text="탁나루(SAMPLE)",
                           box=early)])
    grid[8] = (4.0, [_item(kind="party_name", text="탁나루(SAMPLE)",
                           box=late)])
    merged = reader_mod.merge_video_items(grid, size)
    assert len(merged) == 2
    assert [m["frame_ts"] for m in merged] == [0.0, 4.0]


def test_merge_video_items_orders_by_ts_then_position():
    size = (640, 960)
    box = {"x1": 20, "y1": 100, "x2": 400, "y2": 150,
           "system": "pixel", "ref_w": 640, "ref_h": 960}
    lower = dict(box, y1=300, y2=350)
    merged = reader_mod.merge_video_items(
        [(1.0, [_item(text="나중", box=box)]),
         (0.5, [_item(text="먼저", box=lower)])],
        size,
    )
    assert [m["text_verbatim"] for m in merged] == ["먼저", "나중"]


# --- scorer (synthetic golden) -----------------------------------------------------

def _truth(ex_id="EX9", item_id="item1", kind="amount", text="5원", norm=5,
           box=None, frame_ts=None):
    return {"ex_id": ex_id, "item_id": item_id, "kind": kind,
            "text_verbatim": text, "normalized": norm,
            "box": list(box or [100, 100, 200, 130]), "frame_ts": frame_ts}


def test_norm_equal_amount_date_phone():
    assert eval_reader.norm_equal("amount", "5000000", 5000000)
    assert eval_reader.norm_equal("amount", "5,000,000", 5000000)
    assert not eval_reader.norm_equal("amount", None, 5000000)
    assert eval_reader.norm_equal("date", None, None)
    assert not eval_reader.norm_equal("date", "2026-04-10", None)
    assert eval_reader.norm_equal("date", "2026-03-10", "2026-03-10")
    assert eval_reader.norm_equal("phone", "010-0000-0001", "010-0000-0001")
    assert not eval_reader.norm_equal("phone", None, "010-0000-0001")


def test_score_evidence_truth_box_basis_and_ignore():
    truth = [_truth(box=[100, 100, 200, 130]),
             _truth(item_id="item2", text="띠글",
                    box=[300, 5, 400, 20])]
    preds = [{"kind": "amount", "text_verbatim": "5원", "normalized": "5",
              "box": {"x1": 100, "y1": 100, "x2": 200, "y2": 130}},
             {"kind": "amount", "text_verbatim": "띠글", "normalized": None,
              "box": {"x1": 300, "y1": 5, "x2": 400, "y2": 20}}]
    scored = eval_reader.score_evidence(truth, preds, [[0, 0, 640, 37]])
    assert scored["n_truth"] == 1  # band item excluded
    assert scored["text_recall"]["rate"] == 1.0
    assert scored["box03"]["rate"] == 1.0
    assert scored["value"]["rate"] == 1.0
    assert scored["miss"]["rate"] == 0.0


def test_score_evidence_miss_and_frame():
    truth = [_truth(box=[100, 100, 200, 130], frame_ts=2.0)]
    elsewhere = {"x1": 400, "y1": 400, "x2": 500, "y2": 430}
    preds = [{"kind": "amount", "text_verbatim": "5원", "normalized": "5",
              "box": elsewhere, "frame_ts": 2.4}]
    scored = eval_reader.score_evidence(truth, preds, [])
    row = scored["rows"][0]
    assert row["text_hit"] is True
    assert row["box_ok"] is False
    assert row["miss"] is True
    assert row["frame_ok"] is True  # |2.4-2.0| <= 0.5
    assert row["value_ok"] is True  # right text + value, misplaced box
    wrong = [{"kind": "amount", "text_verbatim": "6원", "normalized": "6",
              "box": elsewhere, "frame_ts": 2.4}]
    row = eval_reader.score_evidence(truth, wrong, [])["rows"][0]
    assert row["text_hit"] is False
    assert row["value_ok"] is False


def test_decide_rule_prefers_fast_when_both_pass():
    summary = {"models": {
        "muse-spark-1.2": {"value": {"rate": 0.96}, "p95_ms": 8000.0},
        "muse-spark-1.3": {"value": {"rate": 0.99}, "p95_ms": 33000.0}}}
    assert eval_reader.decide(summary)["model"] == "muse-spark-1.2"
    low = {"models": {
        "muse-spark-1.2": {"value": {"rate": 0.90}, "p95_ms": 8000.0},
        "muse-spark-1.3": {"value": {"rate": 0.94}, "p95_ms": 33000.0}}}
    assert eval_reader.decide(low)["model"] == "muse-spark-1.3"


# --- reader defaults ---------------------------------------------------------------

def test_reader_defaults_follow_m4b_decision(monkeypatch):
    monkeypatch.delenv("READER_MODEL", raising=False)
    assert reader_mod.default_model() == "muse-spark-1.2"
    monkeypatch.setenv("READER_MODEL", "muse-spark-1.3")
    assert reader_mod.default_model() == "muse-spark-1.3"
    assert reader_mod.PROMPT_FILE == "reader.v2.md"


def test_reader_v2_prompt_hygiene():
    text = load_prompt("reader.v2.md")
    assert text.startswith("#")
    assert "v2" in text.splitlines()[2]
    for token in SAMPLE_TOKENS:
        assert token not in text
    assert find_forbidden_draft(text) == []


# --- eval replay + video replay (needs recorded artifacts) ----------------------------

def test_eval_replay_reproduces_compare_table(monkeypatch, capsys):
    assert EVAL_JSON.exists(), "reports/M4b-reader-eval.json missing"
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    code = eval_reader.main(["--mode", "replay", "--exp", "compare"])
    assert code == 0
    out = capsys.readouterr().out
    assert "muse-spark-1.2" in out and "muse-spark-1.3" in out
    assert "decision: muse-spark-1.2" in out


@needs_ffmpeg
def test_video_reader_replays_recorded_keyframes(monkeypatch, tmp_path):
    assert EVAL_JSON.exists(), "reports/M4b-reader-eval.json missing"
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("META_MODE", "replay")
    output = reader_mod.run_video_reader(
        "eval", {"ex_id": "EX3", "kind": "video",
                 "filename": "chat_02_scroll.mp4"},
        EX3, "replay", "run-test", work_dir=tmp_path,
    )
    assert output["status"] == "ok"
    assert len(output["keyframes"]) == 15
    assert output["items"]
    assert all(item.get("frame_ts") is not None
               for item in output["items"])
    # INT-3 1b changed per-frame tile merging, so the replayed item list
    # no longer matches the M4b-era recording in the eval JSON item for
    # item. Replay must still be deterministic: run twice, same bytes.
    again = reader_mod.run_video_reader(
        "eval", {"ex_id": "EX3", "kind": "video",
                 "filename": "chat_02_scroll.mp4"},
        EX3, "replay", "run-test", work_dir=tmp_path,
    )
    assert again["items"] == output["items"]
    assert again["keyframes"] == output["keyframes"]
