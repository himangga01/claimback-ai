"""Stage B replay tests: real Spark agents on recorded fixtures.

No live calls (META_MODE=replay, the default). The full-flow tests need the
fixtures written by the single record run (brief task 12); the hygiene and
normalizer tests run without fixtures.
"""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents import coordinator as coord
from app.agents import case_state as case_state_mod
from app.agents import demo_inputs
from app.agents import deps
from app.agents.drafter import build_drafter_payload
from app.agents.fact_organizer import (
    build_organizer_payload,
    normalize_field_value,
    normalize_review,
)
from app.agents.reader import build_reader_payload, model_items_to_pixels
from app.agents.spark import load_prompt
from app.main import app
from app.services.naming import find_forbidden_draft

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "specs" / "case-api-examples"


def load_example(name: str):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def assert_keys_subset(actual, example, path="root"):
    if isinstance(example, dict):
        assert isinstance(actual, dict), f"{path}: not an object"
        for key, value in example.items():
            if str(key).startswith("_"):
                continue
            assert key in actual, f"{path}: missing key {key!r}"
            assert_keys_subset(actual[key], value, f"{path}.{key}")
    elif isinstance(example, list):
        assert isinstance(actual, list), f"{path}: not a list"
        if example and actual and isinstance(example[0], dict):
            assert_keys_subset(actual[0], example[0], f"{path}[0]")


@pytest.fixture()
def replay_env(tmp_path, monkeypatch):
    monkeypatch.setattr(case_state_mod, "CASES_ROOT", tmp_path / "cases")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("META_MODE", "replay")
    for name in ("reader", "organizer", "drafter"):
        monkeypatch.setitem(coord.AGENTS, name, None)
    return TestClient(app)


def _run_full_flow(client: TestClient):
    """Sample case to CHECKPOINT_2 with fixed inputs. Returns snapshots."""
    res = client.post("/api/cases/sample", json={"set": "kr"})
    assert res.status_code == 200, res.text
    case_id = res.json()["case_id"]
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "CHECKPOINT_1", res.text
    readings = client.get(f"/api/cases/{case_id}/readings").json()
    review = client.get(f"/api/cases/{case_id}/review").json()
    facts = demo_inputs.build_demo_confirmed_facts(review)
    res = client.put(f"/api/cases/{case_id}/facts", json=facts)
    assert res.status_code == 200, res.text
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "DRAFT_APPROVAL", res.text
    drafts = client.get(f"/api/cases/{case_id}/drafts").json()
    approvals = {"sentences": [
        {"sentence_id": s["sentence_id"], "approved": True}
        for s in drafts["sentences"]]}
    res = client.put(f"/api/cases/{case_id}/drafts", json=approvals)
    assert res.status_code == 200, res.text
    assert all(s["approved"] for s in res.json()["sentences"])
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "CHECKPOINT_2", res.text
    package = client.get(f"/api/cases/{case_id}/package").json()
    final_drafts = client.get(f"/api/cases/{case_id}/drafts").json()
    return {
        "case_id": case_id, "readings": readings, "review": review,
        "drafts": final_drafts, "package": package,
    }


def test_replay_full_flow_to_checkpoint_2(replay_env):
    snapshots = _run_full_flow(replay_env)
    assert_keys_subset(snapshots["readings"], load_example("readings.json"))
    assert_keys_subset(snapshots["review"], load_example("review.json"))
    assert_keys_subset(snapshots["drafts"], load_example("drafts.json"))
    assert_keys_subset(snapshots["package"], load_example("package.json"))
    assert [r["ex_id"] for r in snapshots["readings"]] == [
        "EX1", "EX2", "EX4", "EX5", "EX6"]
    for reading in snapshots["readings"]:
        assert reading["items"], reading["ex_id"]
        for item in reading["items"]:
            assert item["box"]["system"] == "pixel"
    assert len(snapshots["review"]["fields"]) == 11
    assert len(snapshots["drafts"]["sentences"]) >= 3
    assert snapshots["drafts"]["calculation"]["remaining_principal"] == "4014383"
    assert snapshots["package"]["files"][0]["name"] == "content_proof.pdf"
    assert "[갑 제" in snapshots["package"]["ecourt"]["claim_cause_payment_order"]


def test_replay_identical_across_case_ids(replay_env):
    first = _run_full_flow(replay_env)
    second = _run_full_flow(replay_env)
    assert first["case_id"] != second["case_id"]
    assert first["readings"] == second["readings"]
    assert first["review"] == second["review"]
    assert first["drafts"] == second["drafts"]


def test_replay_missing_fixture_holds(replay_env, tmp_path):
    from PIL import Image

    novel = tmp_path / "novel.png"
    image = Image.new("RGB", (64, 32), (11, 22, 33))
    image.save(novel)
    client = replay_env
    res = client.post("/api/cases", json={"jurisdiction": "KR"})
    case_id = res.json()["case_id"]
    res = client.post(
        f"/api/cases/{case_id}/evidence",
        files=[("files", ("novel.png", novel.read_bytes(), "image/png"))],
    )
    assert res.status_code == 200
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200
    view = res.json()
    assert view["state"] == "HOLD"
    assert any(r["code"] == "replay_fixture_missing" for r in view["hold_reasons"])


# --- prompt + request hygiene (no fixtures needed) ---------------------------------
SAMPLE_TOKENS = [
    "서가온", "탁나루",
    "5000000", "5,000,000", "500만", "오백만",
    "1000000", "1,000,000", "100만",
    "4014383", "4,014,383",
    "2026-03-10", "2026-04-10", "2026-05-01", "2026-06-01",
    "2026. 3. 10", "2026. 4. 10", "2026. 5. 1",
    "010-0000", "555-0100",
    "샘플구", "샘플시", "데모로", "데모동",
]

PROMPT_FILES = ["reader.v1.md", "fact_organizer.v1.md", "drafter.v1.md"]


def test_prompts_carry_no_sample_data():
    for name in PROMPT_FILES:
        text = load_prompt(name)
        assert text.startswith("#"), name
        assert "v1" in text.splitlines()[2], name
        for token in SAMPLE_TOKENS:
            assert token not in text, f"{name} contains {token!r}"
        assert find_forbidden_draft(text) == [], name


def test_requests_carry_no_case_metadata():
    prompt = load_prompt("reader.v1.md")
    payload = build_reader_payload(prompt, "image", b"\x89PNG" + b"\x00" * 16,
                                   "shot.png")
    blob = json.dumps(payload, ensure_ascii=False)
    assert re.search(r"case_[0-9a-f]{12}", blob) is None
    assert "http" not in blob
    assert "backend" not in blob and "C:" not in blob and "/tmp" not in blob
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:", blob) is None

    readings = [{"ex_id": "EX1", "items": [
        {"item_id": "item1", "kind": "utterance", "text_verbatim": " 옛다 갚을게 ",
         "normalized": None, "speaker": "화자"}]}]
    payload = build_organizer_payload(load_prompt("fact_organizer.v1.md"),
                                      readings)
    blob = json.dumps(payload, ensure_ascii=False)
    assert re.search(r"case_[0-9a-f]{12}", blob) is None
    assert "http" not in blob

    payload = build_drafter_payload(
        load_prompt("drafter.v1.md"),
        {"slots": {"principal": "대여 원금"}, "utterances": [],
         "highlights": [], "evidence": []},
        [{"sentence_id": "s1", "message": "지적"}],
    )
    blob = json.dumps(payload, ensure_ascii=False)
    assert re.search(r"case_[0-9a-f]{12}", blob) is None
    assert "http" not in blob


# --- normalizers (no fixtures needed) ------------------------------------------------
def test_field_normalizers():
    assert normalize_field_value("principal", "5,000,000원") == "5000000"
    assert normalize_field_value("loan_date", "2026. 3. 10.") == "2026-03-10"
    assert normalize_field_value("due_date", "2026년 4월 10일") == "2026-04-10"
    assert normalize_field_value("interest_rate", "없음") is None
    assert normalize_field_value("interest_rate", None) is None
    assert normalize_field_value("transaction_kind", "민사") == "civil"
    assert normalize_field_value("repayments", None) == []
    assert normalize_field_value(
        "repayments", [{"date": "2026. 5. 1.", "amount": "1,000,000원"}]) == [
        {"date": "2026-05-01", "amount": "1000000"}]


def test_normalize_review_drops_bad_refs():
    readings = [{"ex_id": "EX1", "items": [
        {"item_id": "item1", "kind": "utterance", "text_verbatim": "안녕"}]}]
    parsed = {
        "fields": [
            {"field": "principal", "value": "5000000",
             "sources": [{"ex_id": "EX1", "item_id": "item1"},
                         {"ex_id": "EX9", "item_id": "item9"}],
             "conflict": False},
        ],
        "conflicts": [],
        "questions": [],
        "utterances": [
            {"ex_id": "EX1", "item_id": "item1", "speaker": None,
             "text": "안녕", "tags": ["other", "bogus"]},
            {"ex_id": "EX9", "item_id": "item9", "speaker": None,
             "text": "가짜", "tags": ["other"]},
        ],
        "evidence_roles": [{"ex_id": "EX1", "suggested_role": "bogus"}],
    }
    review = normalize_review(parsed, readings, ["EX1", "EX2"])
    principal = next(f for f in review["fields"] if f["field"] == "principal")
    assert principal["value"] == "5000000"
    assert principal["sources"] == [{"ex_id": "EX1", "item_id": "item1"}]
    assert len(review["fields"]) == 11
    assert [u["item_id"] for u in review["utterances"]] == ["item1"]
    assert review["utterances"][0]["tags"] == ["other"]
    assert {r["ex_id"]: r["suggested_role"]
            for r in review["evidence_roles"]} == {"EX1": "other", "EX2": "other"}


def test_model_boxes_to_pixels():
    from app.agents.reader import ModelReadingItem

    items = model_items_to_pixels(
        [ModelReadingItem(kind="amount", text_verbatim="5원",
                          box=[0, 0, 1000, 1000])],
        (640, 480),
    )
    assert items[0]["box"] == {"x1": 0, "y1": 0, "x2": 640, "y2": 480,
                               "system": "pixel", "ref_w": 640, "ref_h": 480}
