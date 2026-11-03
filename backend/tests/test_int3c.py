"""INT-3c follow-ups: page slicing (F3), sentence rendering (F6), parties block (F2)."""

from pathlib import Path

from PIL import Image as PILImage

from app.agents import deps
from app.services import exhibit_bundle as exhibit_bundle_mod
from tests.test_case_replay import _run_full_flow, replay_env  # noqa: F401

MAX_W = 450.0
MAX_H = 600.0


def _png(path: Path, width: int, height: int, ink_rows=()) -> Path:
    image = PILImage.new("RGB", (width, height), (255, 255, 255))
    for top, bottom in ink_rows:
        image.paste((0, 0, 0), (20, top, width - 20, bottom))
    image.save(path)
    return path


# --- F3: exhibit slicing ---------------------------------------------------------------------


def test_document_shaped_image_is_not_sliced(tmp_path):
    # A4-like 1240x1754 page with a "signature box" near the bottom.
    page = _png(tmp_path / "iou.png", 1240, 1754, [(1500, 1620)])
    assert exhibit_bundle_mod._slice_tall_image(page, MAX_W, MAX_H) == [page]


def test_cuts_land_on_blank_rows_not_inside_ink(tmp_path):
    # 640x2400 screenshot; ink blocks that would straddle a naive cut.
    blocks = [(top, top + 60) for top in range(30, 2400, 90)]
    tall = _png(tmp_path / "chat.png", 640, 2400, blocks)
    slices = exhibit_bundle_mod._slice_tall_image(tall, MAX_W, MAX_H)
    assert len(slices) > 1
    offset = 0
    cuts = []
    for part in slices[:-1]:
        offset += PILImage.open(part).size[1]
        cuts.append(offset)
    for cut in cuts:
        assert not any(top < cut < bottom for top, bottom in blocks), cut


def test_near_blank_trailing_slice_is_dropped(tmp_path):
    # Content only in the first third; the rest is blank paper.
    tall = _png(tmp_path / "chat.png", 640, 2400, [(50, 700)])
    slices = exhibit_bundle_mod._slice_tall_image(tall, MAX_W, MAX_H)
    assert len(slices) <= 2
    for part in slices:
        with PILImage.open(part) as image:
            gray = image.convert("L")
            ink = sum(1 for value in gray.tobytes() if value < 160)
        assert ink > 0


# --- F6: sentence rendering ------------------------------------------------------------------


def test_quote_line_breaks_become_spaces():
    quotes = {"quote:EX1:item1": '"네, 병원비로 500만 원이 필요해요.\n4월 10일까지 갚을게요."'}
    text = deps.render_sentence(
        "{{debtor_name}}은 {{quote:EX1:item1}}라고 했습니다. [[EX:1]]",
        {"debtor_name": "탁나루(SAMPLE)"}, quotes)
    assert "\n" not in text
    assert '필요해요. 4월 10일까지' in text


def test_package_shows_parties_block_with_names(replay_env):
    snapshots = _run_full_flow(replay_env)
    ecourt = snapshots["package"]["ecourt"]
    names = {f["field"]: f["value"] for f in snapshots["review"]["fields"]}
    assert names["creditor_name"] in ecourt["parties"]
    assert names["debtor_name"] in ecourt["parties"]
    # the PDF the bundle links is downloadable at CHECKPOINT_2 (F1 gate open)
    case_id = snapshots["case_id"]
    res = replay_env.get(f"/api/cases/{case_id}/files/exhibits.pdf")
    assert res.status_code == 200


# --- F5: draft rules -------------------------------------------------------------------------

from app.agents import draft_rules  # noqa: E402


def _status(text: str, stype: str = "fact", sourced=None) -> str:
    sentence = {"sentence_id": "s1", "type": stype, "text_with_slots": text}
    return draft_rules.check_draft_rules([sentence], sourced_slots=sourced).status


def test_fact_request_speech_is_blocked():
    assert _status("{{debtor_name}}은 {{principal}}을 빌려 달라고 요청했습니다 [[EX:1]]") == "fail"
    assert _status("{{debtor_name}}은 기다려 달라고 부탁했습니다 [[EX:2]]") == "fail"
    assert _status("{{debtor_name}}은 {{due_date}}까지 마련해 보겠다는 답장을 보냈습니다 [[EX:2]]") == "fail"


def test_user_request_wording_still_allowed():
    assert _status("여러 차례 갚아 달라고 요청하였으나 받지 못했습니다 [[USER]]", "user", []) == "pass"


def test_document_and_period_wording_pass():
    assert _status("차용증에는 {{due_date}}까지 갚기로 적혀 있습니다 [[EX:6]]") == "pass"
    assert _status("{{creditor_name}}은 일주일 주기로 연락했습니다 [[EX:2]]") == "pass"
    assert _status("{{debtor_name}}은 {{principal}}을 갚기로 했습니다 [[EX:1]]") == "fail"


def test_review_follow_ups_on_exceptions():
    # "주기로" is "every" only after a duration
    assert _status("{{debtor_name}}은 내일 주기로 했습니다 [[EX:1]]") == "fail"
    assert _status("{{debtor_name}}은 다음 달 주기로 했습니다 [[EX:1]]") == "fail"
    assert _status("{{creditor_name}}은 한 달 주기로 연락했습니다 [[EX:2]]") == "pass"
    # the document exemption needs a document and no reported speech
    assert _status("대화에는 {{due_date}}까지 갚기로 했다고 적혀 있습니다 [[EX:2]]") == "fail"
    assert _status("차용증에 적힌 대로 {{principal}}을 갚기로 했으나 갚지 않았습니다 [[EX:6]]") == "pass"
    # receiving a message is reported speech too
    assert _status("{{creditor_name}}은 준다는 문자를 받았습니다 [[EX:2]]") == "fail"


def test_short_message_slice_is_kept(tmp_path):
    # One tiny reply alone in the middle third must not vanish.
    tall = _png(tmp_path / "chat.png", 640, 2400, [(50, 700), (1150, 1158), (1700, 2300)])
    slices = exhibit_bundle_mod._slice_tall_image(tall, MAX_W, MAX_H)
    heights = sum(PILImage.open(part).size[1] for part in slices)
    assert heights == 2400


def test_user_sentence_slot_allowed_only_without_evidence():
    text = "{{due_date}}이 지난 뒤에도 남은 돈을 받지 못했습니다 [[USER]]"
    assert _status(text, "user", ["due_date"]) == "fail"
    assert _status(text, "user", ["principal"]) == "pass"


def test_sourced_slots_from_review_maps_fields():
    review = {"fields": [
        {"field": "due_date", "sources": [{"ex_id": "EX6", "item_id": "item22"}]},
        {"field": "repayments", "sources": [{"ex_id": "EX5", "item_id": "item3"}]},
        {"field": "interest_rate", "sources": []},
    ]}
    assert set(draft_rules.sourced_slots_from_review(review)) == {
        "due_date", "repaid_amount", "repaid_date"}


def test_user_statement_ends_with_period():
    text = deps.render_sentence(
        "{{debtor_name}}에게 남은 금액을 받지 못했습니다 [[USER]]",
        {"debtor_name": "탁나루(SAMPLE)"}, {})
    assert text.endswith("(사용자 진술).")
