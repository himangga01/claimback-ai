"""Stage A contract tests: case flow with fake agents, no live calls.

Covers the brief task 9 flow (sample -> run -> review -> facts -> run ->
drafts tamper -> revert -> approve -> run -> package -> delete), response
key checks against specs/case-api-examples/, 409 paths, and HOLD paths.
"""

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents import coordinator as coord
from app.agents import case_state as case_state_mod
from app.agents import demo_inputs
from app.agents import deps
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "specs" / "case-api-examples"

QUOTE_TEXT = "네, 병원비로 500만 원이 필요해요. 4월 10일까지 갚을게요."


def load_example(name: str):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def assert_keys_subset(actual, example, path="root"):
    """Every key in the contract example exists in the actual response."""
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


# --- fakes ----------------------------------------------------------------------
READER_IDENTS: set = set()


def _box(ref_w, ref_h, x1=10, y1=10, x2=100, y2=60):
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "system": "pixel",
            "ref_w": int(ref_w), "ref_h": int(ref_h)}


def fake_reader(case_id, evidence, evidence_path, preview_size, meta_mode,
                run_id, **kwargs):
    READER_IDENTS.add(threading.get_ident())
    time.sleep(0.2)
    ref_w, ref_h = preview_size or (640, 640)
    ex_id = evidence["ex_id"]

    def _item(kind, text, normalized=None, speaker=None):
        return {"kind": kind, "text_verbatim": text, "normalized": normalized,
                "box": _box(ref_w, ref_h), "speaker": speaker, "confidence": 0.9}

    if ex_id == "EX1":
        items = [
            _item("utterance", QUOTE_TEXT, None, "탁나루(SAMPLE)"),
            _item("amount", "500만 원", "5000000", "탁나루(SAMPLE)"),
        ]
    elif ex_id == "EX2":
        items = [_item("utterance", "약속한 4월 10일이 지났는데 언제 보내 줄 수 있어요?",
                       None, "서가온(SAMPLE)")]
    elif ex_id == "EX4":
        items = [
            _item("party_name", "서가온(SAMPLE)"),
            _item("amount", "5,000,000원", "5000000"),
            _item("date", "2026-03-10", "2026-03-10"),
        ]
    elif ex_id == "EX5":
        items = [
            _item("amount", "1,000,000원", "1000000"),
            _item("date", "2026-05-01", "2026-05-01"),
        ]
    elif ex_id == "EX6":
        items = [
            _item("party_name", "서가온(SAMPLE)"),
            _item("address", "서울특별시 샘플구 데모로 0"),
            _item("party_name", "탁나루(SAMPLE)"),
            _item("address", "경기도 샘플시 데모동 0"),
            _item("amount", "5,000,000원", "5000000"),
            _item("date", "2026-03-10", "2026-03-10"),
            _item("date", "2026-04-10", "2026-04-10"),
        ]
    else:
        items = [_item("utterance", "테스트 발화", None, "테스트화자")]
    return {"items": items, "model": "fake-reader", "latency_ms": 1,
            "attempts": 1, "cost_usd": 0.0}


FIELD_LABELS = {
    "creditor_name": "채권자 이름",
    "creditor_address": "채권자 주소",
    "creditor_phone": "채권자 연락처",
    "debtor_name": "채무자 이름",
    "debtor_address": "채무자 주소",
    "principal": "원금",
    "loan_date": "대여일",
    "due_date": "변제기",
    "interest_rate": "약정 이율(연 %)",
    "transaction_kind": "거래 종류",
    "repayments": "받은 돈",
}


def _display(name, value):
    if name == "principal":
        return deps.fmt_amount_won(value)
    if name in ("loan_date", "due_date"):
        return deps.fmt_kr_date(value)
    if name == "interest_rate":
        return "약정 없음" if value in (None, "") else deps.fmt_rate_pct(value)
    if name == "transaction_kind":
        return "개인 간 거래" if value == "civil" else "상거래"
    if name == "repayments":
        parts = [f"{deps.fmt_kr_date(r['date'])} {deps.fmt_amount_won(r['amount'])}"
                 for r in (value or [])]
        return ", ".join(parts)
    return "" if value is None else str(value)


def fake_organizer(case_id, readings, meta_mode, run_id, **kwargs):
    fallback = demo_inputs.fallback_fields()
    sources = {
        "creditor_name": [{"ex_id": "EX4", "item_id": "item1"},
                          {"ex_id": "EX6", "item_id": "item1"}],
        "creditor_address": [{"ex_id": "EX6", "item_id": "item2"}],
        "creditor_phone": [],
        "debtor_name": [{"ex_id": "EX6", "item_id": "item3"}],
        "debtor_address": [{"ex_id": "EX6", "item_id": "item4"}],
        "principal": [{"ex_id": "EX4", "item_id": "item2"},
                      {"ex_id": "EX6", "item_id": "item5"}],
        "loan_date": [{"ex_id": "EX4", "item_id": "item3"},
                      {"ex_id": "EX6", "item_id": "item6"}],
        "due_date": [{"ex_id": "EX6", "item_id": "item7"},
                     {"ex_id": "EX1", "item_id": "item1"}],
        "interest_rate": [],
        "transaction_kind": [],
        "repayments": [{"ex_id": "EX5", "item_id": "item1"}],
    }
    fields = [
        {"field": name, "label": FIELD_LABELS[name], "value": fallback[name],
         "display": _display(name, fallback[name]),
         "sources": sources[name], "conflict": False}
        for name in coord.REVIEW_FIELD_ORDER
    ]
    review = {
        "fields": fields,
        "conflicts": [],
        "questions": [],
        "utterances": [
            {"ex_id": "EX1", "item_id": "item1", "speaker": "탁나루(SAMPLE)",
             "text": QUOTE_TEXT, "tags": ["amount_mention", "repay_promise"]},
            {"ex_id": "EX2", "item_id": "item1", "speaker": "서가온(SAMPLE)",
             "text": "약속한 4월 10일이 지났는데 언제 보내 줄 수 있어요?",
             "tags": ["reminder"]},
        ],
        "evidence_roles": [
            {"ex_id": "EX1", "suggested_role": "other"},
            {"ex_id": "EX2", "suggested_role": "other"},
            {"ex_id": "EX3", "suggested_role": "other"},
            {"ex_id": "EX4", "suggested_role": "loan_transfer"},
            {"ex_id": "EX5", "suggested_role": "repayment"},
            {"ex_id": "EX6", "suggested_role": "other"},
        ],
    }
    return {"review": review, "model": "fake-organizer", "latency_ms": 1,
            "attempts": 1, "cost_usd": 0.0}


def fake_drafter(case_id, draft_inputs, findings, meta_mode, run_id, **kwargs):
    sentences = [
        {"sentence_id": "s1", "type": "fact",
         "text_with_slots": "{{creditor_name}}은 {{loan_date}} {{debtor_name}}에게 "
                            "{{principal}}을 보냈습니다. [[EX:4]]",
         "ex_refs": ["EX4"]},
        {"sentence_id": "s2", "type": "fact",
         "text_with_slots": "{{debtor_name}}은 {{due_date}}까지 갚겠다고 했습니다 "
                            "[[EX:1]]. {{quote:EX1:item1}} [[EX:6]]",
         "ex_refs": ["EX1", "EX6"]},
        {"sentence_id": "s3", "type": "fact",
         "text_with_slots": "{{debtor_name}}은 {{repaid_date}} {{repaid_amount}}을 "
                            "보냈습니다. [[EX:5]]",
         "ex_refs": ["EX5"]},
        {"sentence_id": "s4", "type": "user",
         "text_with_slots": "그 뒤로 남은 돈을 받지 못했습니다. [[USER]]",
         "ex_refs": []},
    ]
    return {"sentences": sentences, "model": "fake-drafter", "latency_ms": 1,
            "attempts": 1, "cost_usd": 0.0}


@pytest.fixture()
def case_env(tmp_path, monkeypatch):
    monkeypatch.setattr(case_state_mod, "CASES_ROOT", tmp_path / "cases")
    monkeypatch.setenv("READER_CONCURRENCY", "4")
    monkeypatch.setitem(coord.AGENTS, "reader", fake_reader)
    monkeypatch.setitem(coord.AGENTS, "organizer", fake_organizer)
    monkeypatch.setitem(coord.AGENTS, "drafter", fake_drafter)
    READER_IDENTS.clear()
    client = TestClient(app)
    return client


def _sample(client: TestClient) -> str:
    res = client.post("/api/cases/sample", json={"set": "kr"})
    assert res.status_code == 200, res.text
    return res.json()["case_id"]


def _to_checkpoint_1(client: TestClient, case_id: str):
    view = client.get(f"/api/cases/{case_id}").json()
    if view["state"] != "CHECKPOINT_1":
        res = client.post(f"/api/cases/{case_id}/run", json={})
        assert res.status_code == 200, res.text
        assert res.json()["state"] == "CHECKPOINT_1"
        return res.json()
    return view


def _to_draft_approval(client: TestClient, case_id: str):
    _to_checkpoint_1(client, case_id)
    review = client.get(f"/api/cases/{case_id}/review").json()
    facts = demo_inputs.build_demo_confirmed_facts(review)
    res = client.put(f"/api/cases/{case_id}/facts", json=facts)
    assert res.status_code == 200, res.text
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "DRAFT_APPROVAL"
    return res.json()


# --- full flow ------------------------------------------------------------------
def test_full_flow_to_checkpoint_2(case_env):
    client = case_env
    case_view_ex = load_example("case_view.json")

    res = client.post("/api/cases/sample", json={"set": "kr"})
    assert res.status_code == 200, res.text
    view = res.json()
    assert_keys_subset(view, case_view_ex)
    assert view["state"] == "INTAKE"
    assert view["stub"] is False
    assert [e["ex_id"] for e in view["evidence"]] == [
        "EX1", "EX2", "EX3", "EX4", "EX5", "EX6"]
    assert view["evidence"][2]["status"] == "skipped"
    assert view["evidence"][2]["preview_url"] is None
    assert view["evidence"][5]["kind"] == "pdf"
    assert view["evidence"][5]["preview_url"] is not None
    case_id = view["case_id"]

    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200, res.text
    view = res.json()
    assert_keys_subset(view, case_view_ex)
    assert view["state"] == "CHECKPOINT_1"
    reading_step = next(s for s in view["steps"] if s["key"] == "reading")
    assert reading_step["status"] == "done"
    assert [s["ex_id"] for s in reading_step["substeps"]] == [
        "EX1", "EX2", "EX3", "EX4", "EX5", "EX6"]
    assert len(READER_IDENTS) > 1  # per-evidence parallel threads

    res = client.get(f"/api/cases/{case_id}/readings")
    assert res.status_code == 200
    readings = res.json()
    assert_keys_subset(readings, load_example("readings.json"))
    assert [r["ex_id"] for r in readings] == ["EX1", "EX2", "EX4", "EX5", "EX6"]

    res = client.get(f"/api/cases/{case_id}/review")
    assert res.status_code == 200
    review = res.json()
    assert_keys_subset(review, load_example("review.json"))

    facts = demo_inputs.build_demo_confirmed_facts(review)
    example_request = load_example("confirmed_facts_kr.json")["example_request"]
    assert_keys_subset(facts, example_request)
    assert facts["highlight"] == ["EX1:item1"]
    assert facts["as_of"] == "2026-06-01"
    res = client.put(f"/api/cases/{case_id}/facts", json=facts)
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "CALCULATING"

    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "DRAFT_APPROVAL"

    res = client.get(f"/api/cases/{case_id}/drafts")
    assert res.status_code == 200
    drafts = res.json()
    assert_keys_subset(drafts, load_example("drafts.json"))
    assert drafts["calculation"]["remaining_principal"] == "4014383"
    assert all(g["status"] == "pass" for g in drafts["gate_results"])
    original = {s["sentence_id"]: s["text_with_slots"] for s in drafts["sentences"]}

    # tamper one sentence: G1a flags it and approval is refused
    res = client.put(f"/api/cases/{case_id}/drafts", json={"sentences": [
        {"sentence_id": "s1", "text_with_slots": "500만 원을 보냈습니다.",
         "approved": True}]})
    assert res.status_code == 200, res.text
    tampered = res.json()
    s1 = next(s for s in tampered["sentences"] if s["sentence_id"] == "s1")
    assert s1["approved"] is False
    assert s1["findings"]
    g1a = next(g for g in tampered["gate_results"] if g["gate"] == "G1a")
    assert g1a["status"] == "fail"

    # revert then approve everything
    res = client.put(f"/api/cases/{case_id}/drafts", json={"sentences": [
        {"sentence_id": "s1", "text_with_slots": original["s1"], "approved": True}]})
    assert res.status_code == 200
    s1 = next(s for s in res.json()["sentences"] if s["sentence_id"] == "s1")
    assert s1["approved"] is True
    assert s1["findings"] == []
    res = client.put(f"/api/cases/{case_id}/drafts", json={"sentences": [
        {"sentence_id": sid, "approved": True} for sid in original]})
    assert res.status_code == 200
    assert all(s["approved"] for s in res.json()["sentences"])

    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "CHECKPOINT_2"

    res = client.get(f"/api/cases/{case_id}/package")
    assert res.status_code == 200
    package = res.json()
    assert_keys_subset(package, load_example("package.json"))
    assert "4,014,383원" in package["ecourt"]["claim_purpose"]
    assert "(갑 제4호증)" in package["ecourt"]["claim_cause_payment_order"]  # M5-fix1 K8

    res = client.get(f"/api/cases/{case_id}/files/content_proof.pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert len(res.content) > 1000

    res = client.delete(f"/api/cases/{case_id}")
    assert res.status_code == 200
    assert res.json() == {"deleted": True}
    res = client.get(f"/api/cases/{case_id}")
    assert res.status_code == 404


# --- 409 / 400 / 404 paths ----------------------------------------------------------
def test_wrong_state_paths(case_env):
    client = case_env
    case_id = _sample(client)
    for path in ("review", "drafts", "package"):
        res = client.get(f"/api/cases/{case_id}/{path}")
        assert res.status_code == 409, path
        assert res.json()["detail"]["code"] == "wrong_state"
    res = client.put(f"/api/cases/{case_id}/facts", json={})
    assert res.status_code == 409
    res = client.put(f"/api/cases/{case_id}/drafts", json={"sentences": []})
    assert res.status_code == 409

    _to_checkpoint_1(client, case_id)
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "wrong_state"
    res = client.get(f"/api/cases/{case_id}/drafts")
    assert res.status_code == 409
    res = client.get(f"/api/cases/{case_id}/package")
    assert res.status_code == 409

    _to_draft_approval(client, case_id)
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "unapproved_sentences"
    res = client.get(f"/api/cases/{case_id}/package")
    assert res.status_code == 409


def test_bad_request_and_not_found(case_env):
    client = case_env
    res = client.post("/api/cases", json={"jurisdiction": "US"})
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "bad_request"
    res = client.post("/api/cases/sample", json={"set": "us"})
    assert res.status_code == 400
    res = client.post("/api/cases/sample", content="{bad json",
                      headers={"content-type": "application/json"})
    assert res.status_code == 400
    res = client.get("/api/cases/case_000000000000")
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "not_found"
    res = client.delete("/api/cases/case_000000000000")
    assert res.status_code == 404
    res = client.get("/api/cases/case_000000000000/readings")
    assert res.status_code == 404

    case_id = _sample(client)
    res = client.get(f"/api/cases/{case_id}/evidence/EX9/file")
    assert res.status_code == 404
    res = client.get(f"/api/cases/{case_id}/evidence/EX3/preview")
    assert res.status_code == 404
    res = client.get(f"/api/cases/{case_id}/files/nope.pdf")
    assert res.status_code == 404
    res = client.post(f"/api/cases/{case_id}/evidence", files={})
    assert res.status_code == 400
    res = client.post(f"/api/cases/{case_id}/evidence",
                      files={"files": ("note.txt", b"hello", "text/plain")})
    assert res.status_code == 400

    _to_checkpoint_1(client, case_id)
    res = client.put(f"/api/cases/{case_id}/facts", json={"fields": {}})
    assert res.status_code == 400
    res = client.put(f"/api/cases/{case_id}/facts", json={
        "fields": {}, "evidence_roles": {}, "highlight": [], "as_of": "2026-06-01"})
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "missing_facts"

    _to_draft_approval(client, case_id)
    res = client.put(f"/api/cases/{case_id}/drafts", json={"sentences": [
        {"sentence_id": "s9", "approved": True}]})
    assert res.status_code == 400
    res = client.put(f"/api/cases/{case_id}/drafts", json={"sentences": [
        {"sentence_id": "s1", "approved": "yes"}]})
    assert res.status_code == 400


def test_concurrent_run_is_409(case_env):
    client = case_env
    case_id = _sample(client)
    lock = coord._run_lock(case_id)
    assert lock.acquire(blocking=False)
    try:
        res = client.post(f"/api/cases/{case_id}/run", json={})
        assert res.status_code == 409
        assert res.json()["detail"]["code"] == "wrong_state"
    finally:
        lock.release()


# --- HOLD paths -----------------------------------------------------------------------
def test_hold_g2_missing_and_recovery(case_env):
    client = case_env
    case_id = _sample(client)
    _to_checkpoint_1(client, case_id)
    review = client.get(f"/api/cases/{case_id}/review").json()
    facts = demo_inputs.build_demo_confirmed_facts(review)
    facts["evidence_roles"] = {ex_id: "other" for ex_id in facts["evidence_roles"]}
    res = client.put(f"/api/cases/{case_id}/facts", json=facts)
    assert res.status_code == 200
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200
    view = res.json()
    assert view["state"] == "HOLD"
    assert any(r["code"] == "missing_facts" and r["step"] == "calculating"
               for r in view["hold_reasons"])
    # recover with good roles
    facts = demo_inputs.build_demo_confirmed_facts(review)
    res = client.put(f"/api/cases/{case_id}/facts", json=facts)
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "CALCULATING"
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200
    assert res.json()["state"] == "DRAFT_APPROVAL"


def test_hold_schema_failure_twice(case_env, monkeypatch):
    calls = []

    def _bad_organizer(case_id, readings, meta_mode, run_id, **kwargs):
        calls.append(1)
        return {"review": {"bogus": True}, "model": "fake-bad"}

    monkeypatch.setitem(coord.AGENTS, "organizer", _bad_organizer)
    client = case_env
    case_id = _sample(client)
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200
    view = res.json()
    assert view["state"] == "HOLD"
    assert any(r["code"] == "schema_failed" and r["step"] == "organizing"
               for r in view["hold_reasons"])
    assert len(calls) == 2


def test_hold_revision_loop_exceeded(case_env, monkeypatch):
    calls = []

    def _bad_drafter(case_id, draft_inputs, findings, meta_mode, run_id, **kwargs):
        calls.append(1)
        return {"sentences": [
            {"sentence_id": "s1", "type": "fact",
             "text_with_slots": "500만 원을 보냈습니다.",
             "ex_refs": []}], "model": "fake-bad"}

    monkeypatch.setitem(coord.AGENTS, "drafter", _bad_drafter)
    client = case_env
    case_id = _sample(client)
    _to_checkpoint_1(client, case_id)
    review = client.get(f"/api/cases/{case_id}/review").json()
    facts = demo_inputs.build_demo_confirmed_facts(review)
    client.put(f"/api/cases/{case_id}/facts", json=facts)
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200
    view = res.json()
    assert view["state"] == "HOLD"
    assert any(r["code"] == "revision_exceeded" and r["step"] == "verifying"
               for r in view["hold_reasons"])
    assert len(calls) == 3  # initial + 2 revisions


def test_hold_budget_error(case_env, monkeypatch):
    def _rich_reader(**kwargs):
        raise deps.BudgetExceeded("run budget exceeded")

    monkeypatch.setitem(coord.AGENTS, "reader", _rich_reader)
    client = case_env
    case_id = _sample(client)
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200
    view = res.json()
    assert view["state"] == "HOLD"
    assert any(r["code"] == "budget_exceeded" for r in view["hold_reasons"])


def test_hold_fixture_missing(case_env, monkeypatch):
    def _missing_reader(**kwargs):
        raise deps.FixtureNotFound("fixture abc.json not found")

    monkeypatch.setitem(coord.AGENTS, "reader", _missing_reader)
    client = case_env
    case_id = _sample(client)
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200
    view = res.json()
    assert view["state"] == "HOLD"
    assert any(r["code"] == "replay_fixture_missing" for r in view["hold_reasons"])


# --- uploads + static guards --------------------------------------------------------------
def test_evidence_upload_and_serving(case_env):
    client = case_env
    res = client.post("/api/cases", json={"jurisdiction": "KR"})
    assert res.status_code == 200
    case_id = res.json()["case_id"]
    assert res.json()["evidence"] == []
    png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    mp4 = (b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32)
    res = client.post(
        f"/api/cases/{case_id}/evidence",
        files=[("files", ("shot.png", png, "image/png")),
               ("files", ("clip.mp4", mp4, "video/mp4"))],
    )
    assert res.status_code == 200, res.text
    evidence = res.json()["evidence"]
    assert [e["ex_id"] for e in evidence] == ["EX1", "EX2"]
    assert evidence[0]["kind"] == "image"
    assert evidence[1]["status"] == "skipped"
    assert evidence[0]["sha256"] and len(evidence[0]["sha256"]) == 64
    res = client.get(f"/api/cases/{case_id}/evidence/EX1/file")
    assert res.status_code == 200
    assert res.content == png
    res = client.get(f"/api/cases/{case_id}/evidence/EX1/preview")
    assert res.status_code == 200
    assert res.content == png
    res = client.post(f"/api/cases/{case_id}/run", json={})
    assert res.status_code == 200
    assert res.json()["state"] == "CHECKPOINT_1"


def test_agents_never_reference_golden():
    for path in (ROOT / "backend" / "app" / "agents").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "golden" not in text.lower(), path.name
    text = (ROOT / "backend" / "app" / "api" / "cases.py").read_text(encoding="utf-8")
    assert "golden" not in text.lower()


# --- INT-2 security + liveness ------------------------------------------------------
def test_c1_delete_dot_does_not_remove_cases_root(case_env, tmp_path, monkeypatch):
    client = case_env
    case_id = _sample(client)
    root = Path(case_state_mod.get_cases_root())
    assert root.exists()
    before = sorted(p.name for p in root.iterdir())
    assert case_id in before
    for evil in ("%2E", "%2e", "D:", "%2E%2E", "case_zzzzzzzzzzzz"):
        res = client.delete(f"/api/cases/{evil}")
        assert res.status_code == 404, evil
        assert res.json()["detail"]["code"] == "not_found"
    after = sorted(p.name for p in root.iterdir())
    assert after == before
    res = client.get(f"/api/cases/{case_id}")
    assert res.status_code == 200


def test_c2_get_responds_during_slow_run(tmp_path, monkeypatch):
    import time as _time

    monkeypatch.setattr(case_state_mod, "CASES_ROOT", tmp_path / "cases")
    monkeypatch.setenv("READER_CONCURRENCY", "1")

    def _slow_reader(case_id, evidence, evidence_path, preview_size,
                     meta_mode, run_id, **kwargs):
        _time.sleep(2.0)
        ref_w, ref_h = preview_size or (64, 64)
        return {"items": [{
            "kind": "utterance", "text_verbatim": "느린 판독",
            "normalized": None,
            "box": _box(ref_w, ref_h), "speaker": None, "confidence": 0.9,
        }], "model": "slow-reader", "latency_ms": 2000,
            "attempts": 1, "cost_usd": 0.0}

    monkeypatch.setitem(coord.AGENTS, "reader", _slow_reader)
    monkeypatch.setitem(coord.AGENTS, "organizer", fake_organizer)
    monkeypatch.setitem(coord.AGENTS, "drafter", fake_drafter)
    client = TestClient(app)
    res = client.post("/api/cases", json={"jurisdiction": "KR"})
    case_id = res.json()["case_id"]
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    res = client.post(f"/api/cases/{case_id}/evidence",
                      files=[("files", ("shot.png", png, "image/png"))])
    assert res.status_code == 200
    outcome: dict = {}

    def _run():
        outcome["res"] = client.post(f"/api/cases/{case_id}/run", json={})

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    _time.sleep(0.5)
    started = _time.perf_counter()
    res = client.get(f"/api/cases/{case_id}")
    elapsed = _time.perf_counter() - started
    assert res.status_code == 200
    assert elapsed < 1.5, f"GET blocked {elapsed:.2f}s during run"
    thread.join(timeout=20)
    assert outcome["res"].status_code == 200
    assert outcome["res"].json()["state"] == "CHECKPOINT_1"


def test_p1_draft_rules_reject_calculated_and_speech():
    from app.agents import draft_rules as rules

    bad = [
        {"sentence_id": "s1", "type": "fact",
         "text_with_slots": "{{creditor_name}}이 {{remaining_principal}}을 언급하였다. [[EX:4]]",
         "ex_refs": ["EX4"]},
        {"sentence_id": "s2", "type": "user",
         "text_with_slots": "{{debtor_name}}은 {{due_date}}까지 {{remaining_principal}}을 주겠다고. [[USER]]",
         "ex_refs": []},
    ]
    gate = rules.check_draft_rules(bad)
    assert gate.status == "fail"
    assert len(gate.findings) >= 3
    good = [
        {"sentence_id": "s1", "type": "fact",
         "text_with_slots": "{{debtor_name}}은 {{due_date}}까지 갚겠다고 했습니다 [[EX:1]]. {{quote:EX1:item1}} [[EX:1]]",
         "ex_refs": ["EX1"]},
        {"sentence_id": "s2", "type": "user",
         "text_with_slots": "그 뒤로 남은 돈을 받지 못했습니다. [[USER]]",
         "ex_refs": []},
    ]
    assert rules.check_draft_rules(good).status == "pass"


def test_c7_put_drafts_naming_and_approval_reset(case_env):
    client = case_env
    case_id = _sample(client)
    _to_draft_approval(client, case_id)
    drafts = client.get(f"/api/cases/{case_id}/drafts").json()
    original = {s["sentence_id"]: s["text_with_slots"] for s in drafts["sentences"]}
    # naming violation on edit
    res = client.put(f"/api/cases/{case_id}/drafts", json={"sentences": [
        {"sentence_id": "s1",
         "text_with_slots": original["s1"].replace("보냈습니다", "보냈습니다 변호사")} ]})
    assert res.status_code == 200
    s1 = next(s for s in res.json()["sentences"] if s["sentence_id"] == "s1")
    assert s1["approved"] is False
    assert s1["findings"]
    naming = next(g for g in res.json()["gate_results"] if g["gate"] == "NAMING")
    assert naming["status"] == "fail"
    # edit without approved clears a previous approval
    res = client.put(f"/api/cases/{case_id}/drafts", json={"sentences": [
        {"sentence_id": "s1", "text_with_slots": original["s1"], "approved": True}]})
    assert next(s for s in res.json()["sentences"]
                if s["sentence_id"] == "s1")["approved"] is True
    res = client.put(f"/api/cases/{case_id}/drafts", json={"sentences": [
        {"sentence_id": "s1", "text_with_slots": original["s1"] + " "}]})
    assert res.status_code == 200
    s1 = next(s for s in res.json()["sentences"] if s["sentence_id"] == "s1")
    assert s1["approved"] is False


def test_c11_upload_limits_and_magic(case_env):
    client = case_env
    res = client.post("/api/cases", json={"jurisdiction": "KR"})
    case_id = res.json()["case_id"]
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    # content/extension mismatch
    res = client.post(f"/api/cases/{case_id}/evidence",
                      files=[("files", ("fake.png", b"hello world", "image/png"))])
    assert res.status_code == 400
    # too many files
    many = [("files", (f"f{i}.png", png, "image/png")) for i in range(11)]
    res = client.post(f"/api/cases/{case_id}/evidence", files=many)
    assert res.status_code == 400


def test_c12_facts_validations(case_env):
    client = case_env
    case_id = _sample(client)
    _to_checkpoint_1(client, case_id)
    review = client.get(f"/api/cases/{case_id}/review").json()
    facts = demo_inputs.build_demo_confirmed_facts(review)
    bad = json.loads(json.dumps(facts))
    bad["fields"]["interest_rate"] = "NaN"
    res = client.put(f"/api/cases/{case_id}/facts", json=bad)
    assert res.status_code == 400
    bad = json.loads(json.dumps(facts))
    bad["fields"]["principal"] = "５００００００"
    res = client.put(f"/api/cases/{case_id}/facts", json=bad)
    assert res.status_code == 400
    res = client.put(f"/api/cases/{case_id}/facts", json={"fields": {}})
    assert res.status_code == 400
    assert res.json()["detail"]["missing_requirements"]
    res = client.get(f"/api/cases/{case_id}/no-such-path")
    assert res.status_code == 404
    assert set(res.json()["detail"]) == {"code", "message", "missing_requirements"}
