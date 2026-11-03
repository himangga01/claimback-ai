"""M2c fact cross-check tests: organizer P5 gaps (review A4/A5).

Values without (valid) sources, name/address/phone verbatim
comparison, code-found auto questions, verbatim month/day fallback,
and fact-only date-conflict notes.
"""

from app.agents.fact_organizer import normalize_review
from app.agents.spark import load_prompt
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
    return {"item_id": item_id, "kind": kind,
            "text_verbatim": verbatim, "normalized": normalized}


def _reading(ex_id, items):
    return {"ex_id": ex_id, "items": list(items)}


def test_m2c_value_without_sources_conflicts_and_asks():
    readings = [_reading("EX4", [
        _item("item2", "amount", "5,000,000원", "5000000")])]
    review = _review(
        [{"field": "principal", "value": "5000000", "sources": [],
          "conflict": False, "null_reason": None}],
        readings)
    principal = _field(review, "principal")
    assert principal["conflict"] is True
    assert any("principal" in c["fields"] and "근거가 없습니다" in c["note"]
               for c in review["conflicts"])
    assert any(q["field"] == "principal" for q in review["questions"])


def test_m2c_value_with_only_bad_refs_conflicts_and_lists_them():
    readings = [_reading("EX4", [
        _item("item2", "amount", "5,000,000원", "5000000")])]
    review = _review(
        [{"field": "principal", "value": "5000000",
          "sources": [{"ex_id": "EX9", "item_id": "item9"}],
          "conflict": False, "null_reason": None}],
        readings)
    principal = _field(review, "principal")
    assert principal["conflict"] is True
    assert principal["sources"] == []
    assert any("principal" in c["fields"] and "EX9:item9" in c["note"]
               for c in review["conflicts"])
    assert any(q["field"] == "principal" for q in review["questions"])


def test_m2c_empty_value_without_sources_is_not_a_conflict():
    readings = [_reading("EX1", [
        _item("item1", "utterance", "안녕")])]
    review = _review(
        [{"field": "transaction_kind", "value": None, "sources": [],
          "conflict": False, "null_reason": "판독에 없음"}],
        readings)
    kind = _field(review, "transaction_kind")
    assert kind["conflict"] is False
    assert kind["null_reason"] == "판독에 없음"
    assert [q for q in review["questions"]
            if q["field"] == "transaction_kind"] == []


def test_m2c_name_matches_verbatim_ignoring_parens_and_spaces():
    readings = [_reading("EX6", [
        _item("item4", "party_name", "서가온(SAMPLE)"),
        _item("item6", "address", "서울특별시  샘플구 데모로 0"),
        _item("item8", "phone", "010 0000 0001", "01000000001")])]
    review = _review(
        [{"field": "creditor_name", "value": "서가온",
          "sources": [{"ex_id": "EX6", "item_id": "item4"}],
          "conflict": False, "null_reason": None},
         {"field": "creditor_address", "value": "서울특별시 샘플구 데모로 0",
          "sources": [{"ex_id": "EX6", "item_id": "item6"}],
          "conflict": False, "null_reason": None},
         {"field": "creditor_phone", "value": "010-0000-0001",
          "sources": [{"ex_id": "EX6", "item_id": "item8"}],
          "conflict": False, "null_reason": None}],
        readings)
    for name in ("creditor_name", "creditor_address", "creditor_phone"):
        assert _field(review, name)["conflict"] is False, name
    assert review["conflicts"] == []
    assert review["questions"] == []


def test_m2c_name_mismatch_conflicts_and_asks():
    readings = [_reading("EX6", [
        _item("item10", "party_name", "탁나루(SAMPLE)")])]
    review = _review(
        [{"field": "debtor_name", "value": "홍길동",
          "sources": [{"ex_id": "EX6", "item_id": "item10"}],
          "conflict": False, "null_reason": None}],
        readings)
    debtor = _field(review, "debtor_name")
    assert debtor["conflict"] is True
    assert any("debtor_name" in c["fields"] and "판독 원문과 다릅니다" in c["note"]
               for c in review["conflicts"])
    assert any(q["field"] == "debtor_name" for q in review["questions"])


def test_m2c_code_conflict_keeps_model_question_without_dup():
    readings = [_reading("EX4", [
        _item("item2", "amount", "5,000,000원", "5000000")])]
    review = _review(
        [{"field": "principal", "value": "4000000",
          "sources": [{"ex_id": "EX4", "item_id": "item2"}],
          "conflict": False, "null_reason": None}],
        readings,
        questions=[{"field": "principal", "question": "원금을 확인하세요."}])
    principal = _field(review, "principal")
    assert principal["conflict"] is True
    mine = [q for q in review["questions"] if q["field"] == "principal"]
    assert [q["question"] for q in mine] == ["원금을 확인하세요."]


def test_m2c_month_day_agreeing_verbatim_is_no_conflict():
    readings = [
        _reading("EX6", [
            _item("item22", "date", "2026년 4월 10일", "2026-04-10")]),
        _reading("EX1", [
            _item("item12", "utterance", "4월 10일까지 갚을게요.")]),
    ]
    review = _review(
        [{"field": "due_date", "value": "2026-04-10",
          "sources": [{"ex_id": "EX6", "item_id": "item22"},
                      {"ex_id": "EX1", "item_id": "item12"}],
          "conflict": False, "null_reason": None}],
        readings)
    assert _field(review, "due_date")["conflict"] is False
    assert review["conflicts"] == []
    assert review["questions"] == []


def test_m2c_month_day_differing_verbatim_conflicts_fact_only():
    readings = [
        _reading("EX6", [
            _item("item22", "date", "2026년 4월 10일", "2026-04-10")]),
        _reading("EX2", [
            _item("item8", "utterance", "죄송해요. 4월 25일까지 꼭 갚을게요.")]),
    ]
    review = _review(
        [{"field": "due_date", "value": "2026-04-10",
          "sources": [{"ex_id": "EX6", "item_id": "item22"},
                      {"ex_id": "EX2", "item_id": "item8"}],
          "conflict": False, "null_reason": None}],
        readings)
    assert _field(review, "due_date")["conflict"] is True
    assert review["conflicts"] == [
        {"fields": ["due_date"],
         "note": "증거에 나온 날짜가 서로 다릅니다: 2026. 4. 10.(갑 제6호증), "
                 "4월 25일(갑 제2호증 대화)"}]
    assert [q["field"] for q in review["questions"]] == ["due_date"]
    assert "변경" not in review["conflicts"][0]["note"]
    assert "변경" not in review["questions"][0]["question"]


def test_m2c_verbatim_without_month_day_is_skipped():
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


def test_m2c_full_date_mismatch_note_format():
    readings = [_reading("EX4", [
        _item("item14", "date", "2026-03-11", "2026-03-11")])]
    review = _review(
        [{"field": "loan_date", "value": "2026-03-10",
          "sources": [{"ex_id": "EX4", "item_id": "item14"}],
          "conflict": False, "null_reason": None}],
        readings)
    assert _field(review, "loan_date")["conflict"] is True
    assert review["conflicts"] == [
        {"fields": ["loan_date"],
         "note": "증거에 나온 날짜가 서로 다릅니다: 2026. 3. 10., "
                 "2026. 3. 11.(갑 제4호증)"}]
    assert [q["field"] for q in review["questions"]] == ["loan_date"]


def test_m2c_repayments_month_day_fallback():
    readings = [_reading("EX2", [
        _item("item13", "utterance", "5월 1일에는 꼭 보내드릴게요.")])]
    review = _review(
        [{"field": "repayments",
          "value": [{"date": "2026-05-01", "amount": "1000000"}],
          "sources": [{"ex_id": "EX2", "item_id": "item13"}],
          "conflict": False, "null_reason": None}],
        readings)
    assert _field(review, "repayments")["conflict"] is False
    review = _review(
        [{"field": "repayments",
          "value": [{"date": "2026-05-02", "amount": "1000000"}],
          "sources": [{"ex_id": "EX2", "item_id": "item13"}],
          "conflict": False, "null_reason": None}],
        readings)
    assert _field(review, "repayments")["conflict"] is True
    assert any("repayments" in c["fields"] for c in review["conflicts"])
    assert any(q["field"] == "repayments" for q in review["questions"])


def test_m2c_fact_organizer_v2_prompt_hygiene():
    text = load_prompt("fact_organizer.v2.md")
    assert text.startswith("#")
    assert "fact_organizer.v2" in text.splitlines()[2]
    for token in SAMPLE_TOKENS:
        assert token not in text, token
    assert find_forbidden_draft(text) == []
