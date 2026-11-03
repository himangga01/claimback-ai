"""redaction-confirm: per-exhibit confirmation of flagged PII copies.

Replay sample (no key, recorded fixtures only). A flagged copy is held out
of exhibits.pdf until the user lists its exhibit in
``redaction_confirmed`` (PUT /facts, contract 6d); a confirmed copy goes
into the bundle and G1b still passes. Also pins the honest privacy note
and leak-check status, and that the Korean replay sample stays unflagged.
"""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.agents import case_state as case_state_mod
from app.agents import coordinator as coord
from app.agents import demo_inputs
from app.agents import packager as packager_mod
from app.agents import privacy_guard as privacy_mod
from app.main import app
from app.services import exhibit_bundle as exhibit_bundle_mod
from app.services import redaction as redact_mod


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(case_state_mod, "CASES_ROOT", tmp_path / "cases")
    monkeypatch.setenv("META_MODE", "replay")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
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


REVIEW_REASONS = {
    "EX4": f"계좌번호 끝 4자리 유지; {redact_mod.LINE_SHIFT_REVIEW_REASON}",
    "EX5": f"계좌번호 끝 4자리 유지; {redact_mod.UNMASKED_LINE_REASON}",
}


def _flag(case_id, ex_ids):
    """Mark real replay copies as flagged (what a live wrong-line run gives)."""
    path = Path(case_state_mod.files_dir(case_id)) / "redactions.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for preview in data["previews"]:
        if preview["ex_id"] in ex_ids:
            assert preview["status"] == "redacted" and preview["url"]
            preview["needs_review"] = True
            preview["reason"] = REVIEW_REASONS[preview["ex_id"]]
    for entry in data["plan"]:
        if entry["ex_id"] in ex_ids and entry["kind"] == "account_number":
            entry["needs_review"] = True
            entry["reason"] = REVIEW_REASONS[entry["ex_id"]]
    data["leak_check"]["status"] = "review"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _facts(client, case_id, confirmed=None):
    review = client.get(f"/api/cases/{case_id}/review").json()
    facts = demo_inputs.build_demo_confirmed_facts(review)
    if confirmed is not None:
        facts["redaction_confirmed"] = confirmed
    return facts


def _to_package(client, case_id, facts):
    res = client.put(f"/api/cases/{case_id}/facts", json=facts)
    assert res.status_code == 200, res.text
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.json()["state"] == "DRAFT_APPROVAL", res.text
    drafts = client.get(f"/api/cases/{case_id}/drafts").json()
    res = client.put(f"/api/cases/{case_id}/drafts", json={"sentences": [
        {"sentence_id": s["sentence_id"], "approved": True}
        for s in drafts["sentences"]]})
    assert all(s["approved"] for s in res.json()["sentences"]), res.text
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.json()["state"] == "CHECKPOINT_2", res.text
    return client.get(f"/api/cases/{case_id}/package").json()


def _norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _exhibit_pages(case_id):
    """{ex_id: [(text, image count), ...]} for the evidence pages."""
    state = coord.get_case(case_id)
    reader = PdfReader(str(Path(case_state_mod.files_dir(case_id))
                           / "exhibits.pdf"))
    pages = {}
    for page in reader.pages[1:]:  # page 0 is the cover
        text = _norm(page.extract_text() or "")
        for record in state.evidence:
            # Header "갑 제N호증[ (i/n)] <filename> · SHA-256 ..." after the
            # sample footer line.
            if re.search(re.escape(record.label) + r"( \(\d+/\d+\))? "
                         + re.escape(record.filename) + " ", text):
                pages.setdefault(record.ex_id, []).append(
                    (text, len(page.images)))
    return pages


def _g1b(package):
    return next(g for g in package["gate_results"] if g["gate"] == "G1b")


# --- privacy note and leak status ------------------------------------------------

def test_privacy_note_counts_exhibits_to_check():
    clean = {"plan": [{}] * 7, "previews": [
        {"ex_id": "EX1", "status": "redacted", "needs_review": False}],
        "leak_check": {"status": "pass", "findings": []}}
    assert privacy_mod.privacy_note(clean) == "가림 7개, 누출 검사 통과"
    flagged = {"plan": [{}] * 7, "previews": [
        {"ex_id": "EX1", "status": "redacted", "needs_review": False},
        {"ex_id": "EX4", "status": "redacted", "needs_review": True},
        {"ex_id": "EX5", "status": "redacted", "needs_review": True}],
        "leak_check": {"status": "review", "findings": [{"warning": True}]}}
    assert privacy_mod.privacy_note(flagged) == "가림 7개, 확인 필요 증거 2개"
    mixed = {"plan": [{}] * 3, "previews": [
        {"ex_id": "EX1", "status": "not_redacted", "needs_review": True},
        {"ex_id": "EX4", "status": "redacted", "needs_review": True}],
        "leak_check": {"status": "pass", "findings": []}}
    assert privacy_mod.privacy_note(mixed) == (
        "가림 3개, 확인 필요 증거 1개, 가린 사본 없는 증거 1개")
    # A review status never prints "통과", even with no flagged preview.
    odd = {"plan": [], "previews": [],
           "leak_check": {"status": "review", "findings": []}}
    assert privacy_mod.privacy_note(odd) == "가림 0개, 누출 검사 확인 필요"


def test_replay_sample_stays_unflagged_with_the_same_note(client):
    case_id = _to_checkpoint_1(client)
    body = client.get(f"/api/cases/{case_id}/redactions").json()
    assert body["leak_check"] == {"status": "pass", "findings": []}
    assert all(p["needs_review"] is False for p in body["previews"])
    view = client.get(f"/api/cases/{case_id}").json()
    privacy = next(s for s in view["steps"] if s["key"] == "privacy")
    assert privacy["note"] == f"가림 {len(body['plan'])}개, 누출 검사 통과"
    # The demo input sends no redaction key for an unflagged case.
    assert "redaction_confirmed" not in _facts(client, case_id)


# --- PUT /facts validation ---------------------------------------------------------

def test_redaction_confirmed_list_is_validated_and_normalized(client):
    case_id = _to_checkpoint_1(client)
    for bad in (["EX9"], [4], ["EX4", None], {"EX4": True}):
        res = client.put(f"/api/cases/{case_id}/facts",
                         json=_facts(client, case_id, bad))
        assert res.status_code == 400, bad
        assert res.json()["detail"]["code"] == "bad_request"
        assert client.get(f"/api/cases/{case_id}").json()["state"] == "CHECKPOINT_1"
    res = client.put(f"/api/cases/{case_id}/facts",
                     json=_facts(client, case_id, ["EX5", "EX4", "EX5"]))
    assert res.status_code == 200, res.text
    stored = coord.get_case(case_id).confirmed_facts["redaction_confirmed"]
    assert stored == ["EX4", "EX5"]
    case2 = _to_checkpoint_1(client)
    res = client.put(f"/api/cases/{case2}/facts",
                     json=_facts(client, case2, []))
    assert res.status_code == 200, res.text
    assert coord.get_case(case2).confirmed_facts["redaction_confirmed"] is False


# --- flagged -> held out; confirmed -> in the bundle --------------------------------

def test_flagged_copies_stay_out_until_confirmed(client):
    case_id = _to_checkpoint_1(client)
    _flag(case_id, {"EX4", "EX5"})
    body = client.get(f"/api/cases/{case_id}/redactions").json()
    flagged = {p["ex_id"] for p in body["previews"] if p["needs_review"]}
    assert flagged == {"EX4", "EX5"}
    assert body["leak_check"]["status"] == "review"
    package = _to_package(client, case_id, _facts(client, case_id))
    g1b = _g1b(package)
    assert g1b["status"] == "pass", g1b["findings"]
    assert g1b["findings"] == []
    notes = " ".join(g1b["notes"])
    assert "(EX4)" in notes and "(EX5)" in notes and "가림 확인" in notes
    pages = _exhibit_pages(case_id)
    for ex_id in ("EX4", "EX5"):
        assert len(pages[ex_id]) == 1
        text, images = pages[ex_id][0]
        assert exhibit_bundle_mod.NEEDS_REVIEW_LINE in text
        assert images == 0
    # Unflagged copies are in as before.
    assert all(images == 1 for _, images in pages["EX1"])


def test_confirmed_exhibit_enters_the_bundle_and_g1b_passes(client):
    case_id = _to_checkpoint_1(client)
    _flag(case_id, {"EX4", "EX5"})
    package = _to_package(client, case_id, _facts(client, case_id, ["EX4"]))
    g1b = _g1b(package)
    assert g1b["status"] == "pass", g1b["findings"]
    assert g1b["findings"] == []
    notes = " ".join(g1b["notes"])
    assert "(EX4)" not in notes
    assert "(EX5)" in notes and "가림 확인" in notes
    pages = _exhibit_pages(case_id)
    ex4_text, ex4_images = pages["EX4"][0]
    assert ex4_images == 1
    assert exhibit_bundle_mod.NEEDS_REVIEW_LINE not in ex4_text
    ex5_text, ex5_images = pages["EX5"][0]
    assert ex5_images == 0
    assert exhibit_bundle_mod.NEEDS_REVIEW_LINE in ex5_text


@pytest.mark.parametrize("confirmed", [["EX4"], True])
def test_not_redacted_stays_out_even_with_a_stale_copy(client, confirmed):
    """Review follow-up: a not_redacted preview never enters, even when
    confirmed and an old redacted_EX4.png is still on disk (privacy_guard
    ignores a failed delete)."""
    case_id = _to_checkpoint_1(client)
    path = Path(case_state_mod.files_dir(case_id)) / "redactions.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for preview in data["previews"]:
        if preview["ex_id"] == "EX4":
            preview.update(status="not_redacted", url=None, needs_review=True,
                           reason="판독이 보류되어 가림 대상을 알 수 없음")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    stale = Path(case_state_mod.files_dir(case_id)) / "redacted_EX4.png"
    assert stale.exists()
    package = _to_package(client, case_id, _facts(client, case_id, confirmed))
    valid, needs, _ = packager_mod.get_redaction_status(coord.get_case(case_id))
    assert "EX4" not in valid and "EX4" in needs
    text, images = _exhibit_pages(case_id)["EX4"][0]
    assert images == 0
    assert exhibit_bundle_mod.NEEDS_REVIEW_LINE in text
    g1b = _g1b(package)
    assert g1b["status"] == "pass", g1b["findings"]
    assert "(EX4)" in " ".join(g1b["notes"])


def test_case_wide_true_still_confirms_every_flagged_copy(client):
    """The demo input form (true) keeps working next to the list form."""
    case_id = _to_checkpoint_1(client)
    _flag(case_id, {"EX4", "EX5"})
    package = _to_package(client, case_id, _facts(client, case_id, True))
    g1b = _g1b(package)
    assert g1b["status"] == "pass", g1b["findings"]
    assert not any("가림 확인" in note for note in g1b["notes"])
    pages = _exhibit_pages(case_id)
    assert pages["EX4"][0][1] == 1 and pages["EX5"][0][1] == 1
