"""M2c-fix1 fact cross-check tests: D2/D7/D8/D9/D10 pinned.

Extends ``test_fact_check_m2c.py`` (left untouched): names keep their
parentheses ("(SAMPLE)", "(주)"), header labels ("채권자:") are
stripped before containment comparison, every verbatim month/day is
considered, ex_id matches case-insensitively, items without verbatim
ask "근거 확인 불가", and a sourceless transaction_kind asks without
a conflict.
"""

import pytest
from fastapi.testclient import TestClient

from app.agents import case_state as case_state_mod
from app.agents import coordinator as coord
from app.agents import demo_inputs
from app.agents.fact_organizer import normalize_review
from app.agents.spark import load_prompt
from app.main import app
from app.services.naming import find_forbidden_draft

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


def _review(fields, readings, questions=()):
    parsed = {
        "fields": fields,
        "conflicts": [],
        "questions": list(questions),
        "utterances": [],
        "evidence_roles": [],
    }
    ex_ids = sorted({r["ex_id"] for r in readings})
    return normalize_review(parsed, readings, ex_ids)


def _field(review, name):
    return next(f for f in review["fields"] if f["field"] == name)


def _item(item_id, kind, verbatim, normalized=None):
    entry = {"item_id": item_id, "kind": kind,
             "text_verbatim": verbatim}
    if normalized is not None:
        entry["normalized"] = normalized
    return entry


def _reading(ex_id, items):
    return {"ex_id": ex_id, "items": list(items)}


# --- D2: parentheses are part of the name ---------------------------------------
def test_fix1_d2_identical_parens_match():
    readings = [_reading("EX6", [
        _item("item4", "party_name", "서가온(SAMPLE)")])]
    review = _review(
        [{"field": "creditor_name", "value": "서가온(SAMPLE)",
          "sources": [{"ex_id": "EX6", "item_id": "item4"}],
          "conflict": False, "null_reason": None}],
        readings)
    assert _field(review, "creditor_name")["conflict"] is False
    assert review["conflicts"] == []
    assert review["questions"] == []


def test_fix1_d2_different_parens_conflict():
    readings = [_reading("EX6", [
        _item("item4", "party_name", "서가온(SAMPLE)")])]
    review = _review(
        [{"field": "creditor_name", "value": "서가온(채무자)",
          "sources": [{"ex_id": "EX6", "item_id": "item4"}],
          "conflict": False, "null_reason": None}],
        readings)
    assert _field(review, "creditor_name")["conflict"] is True
    assert any("creditor_name" in c["fields"] for c in review["conflicts"])
    assert any(q["field"] == "creditor_name" for q in review["questions"])


def test_fix1_d2_dropped_paren_still_passes():
    readings = [_reading("EX6", [
        _item("item4", "party_name", "서가온(SAMPLE)")])]
    review = _review(
        [{"field": "creditor_name", "value": "서가온",
          "sources": [{"ex_id": "EX6", "item_id": "item4"}],
          "conflict": False, "null_reason": None}],
        readings)
    assert _field(review, "creditor_name")["conflict"] is False


# --- D9: header labels + containment ---------------------------------------------
def test_fix1_d9_header_prefix_matches():
    readings = [_reading("EX6", [
        _item("item4", "party_name", "채권자: 서가온(SAMPLE)")])]
    review = _review(
        [{"field": "creditor_name", "value": "서가온(SAMPLE)",
          "sources": [{"ex_id": "EX6", "item_id": "item4"}],
          "conflict": False, "null_reason": None}],
        readings)
    assert _field(review, "creditor_name")["conflict"] is False
    assert review["conflicts"] == []


def test_fix1_d9_address_header_matches():
    readings = [_reading("EX6", [
        _item("item6", "address", "주소: 서울특별시 샘플구 데모로 0")])]
    review = _review(
        [{"field": "creditor_address", "value": "서울특별시 샘플구 데모로 0",
          "sources": [{"ex_id": "EX6", "item_id": "item6"}],
          "conflict": False, "null_reason": None}],
        readings)
    assert _field(review, "creditor_address")["conflict"] is False


# --- D10 --------------------------------------------------------------------------
def test_fix1_d10_any_month_day_match_agrees():
    readings = [_reading("EX2", [
        _item("item8", "utterance", "3월 10일에 빌려서 4월 10일까지 갚을게요.")])]
    review = _review(
        [{"field": "due_date", "value": "2026-04-10",
          "sources": [{"ex_id": "EX2", "item_id": "item8"}],
          "conflict": False, "null_reason": None}],
        readings)
    assert _field(review, "due_date")["conflict"] is False
    assert review["conflicts"] == []


def test_fix1_d10_all_month_days_differ_conflicts():
    readings = [_reading("EX2", [
        _item("item8", "utterance", "3월 10일에 빌려서 4월 10일까지 갚을게요.")])]
    review = _review(
        [{"field": "due_date", "value": "2026-05-01",
          "sources": [{"ex_id": "EX2", "item_id": "item8"}],
          "conflict": False, "null_reason": None}],
        readings)
    assert _field(review, "due_date")["conflict"] is True
    assert any("due_date" in c["fields"] for c in review["conflicts"])


def test_fix1_d10_ex_id_case_insensitive():
    readings = [_reading("EX4", [
        _item("item2", "amount", "5,000,000원", "5000000")])]
    review = _review(
        [{"field": "principal", "value": "5000000",
          "sources": [{"ex_id": "ex4", "item_id": "item2"}],
          "conflict": False, "null_reason": None}],
        readings)
    principal = _field(review, "principal")
    assert principal["conflict"] is False
    assert principal["sources"] == [{"ex_id": "EX4", "item_id": "item2"}]


def test_fix1_d10_missing_verbatim_asks_unverifiable():
    readings = [_reading("EX4", [
        {"item_id": "item2", "kind": "amount"}])]
    review = _review(
        [{"field": "principal", "value": "5000000",
          "sources": [{"ex_id": "EX4", "item_id": "item2"}],
          "conflict": False, "null_reason": None}],
        readings)
    assert _field(review, "principal")["conflict"] is True
    mine = [q for q in review["questions"] if q["field"] == "principal"]
    assert len(mine) == 1
    assert "근거 확인 불가" in mine[0]["question"]


def test_fix1_d10_verbatim_without_month_day_still_skipped():
    readings = [_reading("EX2", [
        _item("item17", "utterance", "오늘 100만 원 먼저 보냈어.")])]
    review = _review(
        [{"field": "due_date", "value": "2026-04-10",
          "sources": [{"ex_id": "EX2", "item_id": "item17"}],
          "conflict": False, "null_reason": None}],
        readings)
    assert _field(review, "due_date")["conflict"] is False
    assert review["conflicts"] == []
    assert review["questions"] == []


def test_fix1_d10_sourceless_kind_asks_without_conflict():
    readings = [_reading("EX1", [
        _item("item1", "utterance", "안녕")])]
    review = _review(
        [{"field": "transaction_kind", "value": "civil", "sources": [],
          "conflict": False, "null_reason": None}],
        readings)
    kind = _field(review, "transaction_kind")
    assert kind["conflict"] is False
    assert review["conflicts"] == []
    mine = [q for q in review["questions"] if q["field"] == "transaction_kind"]
    assert len(mine) == 1


# --- D7/D8 + prompt -----------------------------------------------------------------
def test_fix1_fact_organizer_v2_prompt_content():
    text = load_prompt("fact_organizer.v2.md")
    assert text.startswith("#")
    assert "fact_organizer.v2" in text.splitlines()[2]
    assert "괄호와 그 안 표시" in text and "그대로 둔다" in text
    assert "빼도 된다" not in text
    assert '"머리말만 빼고 값으로 옮긴다' in text or "머리말만 빼고" in text
    assert "문서 증거를 먼저 쓴다" in text
    assert "이전이나" in text and "당일 대화" in text
    assert "변경이 아니라" not in text
    assert "변제기 칸은 그대로 둔다" in text
    assert text.count('"evidence_roles"') == 1
    assert '"evidence_roles": [{"ex_id", "item_id"' not in text
    for token in SAMPLE_TOKENS:
        assert token not in text, token
    assert find_forbidden_draft(text) == []


# --- D2/D5: replayed names keep "(SAMPLE)" -------------------------------------------
@pytest.fixture()
def replay_env(tmp_path, monkeypatch):
    monkeypatch.setattr(case_state_mod, "CASES_ROOT", tmp_path / "cases")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("META_MODE", "replay")
    for name in ("reader", "organizer", "drafter"):
        monkeypatch.setitem(coord.AGENTS, name, None)
    return TestClient(app)


def test_fix1_replayed_documents_keep_sample_mark(replay_env):
    client = replay_env
    res = client.post("/api/cases/sample", json={"set": "kr"})
    assert res.status_code == 200, res.text
    case_id = res.json()["case_id"]
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "CHECKPOINT_1", res.text
    review = client.get(f"/api/cases/{case_id}/review").json()
    names = {f["field"]: f["value"] for f in review["fields"]
             if f["field"] in ("creditor_name", "debtor_name")}
    assert "(SAMPLE)" in (names.get("creditor_name") or ""), names
    assert "(SAMPLE)" in (names.get("debtor_name") or ""), names
    facts = demo_inputs.build_demo_confirmed_facts(review)
    res = client.put(f"/api/cases/{case_id}/facts", json=facts)
    assert res.status_code == 200, res.text
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "DRAFT_APPROVAL", res.text
    drafts = client.get(f"/api/cases/{case_id}/drafts").json()
    assert any("(SAMPLE)" in s["rendered_text"]
               for s in drafts["sentences"]), drafts["sentences"]
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
    # M5-fix2: ecourt facts use role terms, not names (names stay in drafts/header/list).
    cause = package["ecourt"]["claim_cause_payment_order"]
    assert "채권자" in cause and "채무자" in cause
    assert "(SAMPLE)" not in cause
