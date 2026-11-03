"""M2c-fix1 draft-rule tests: D1/D3/D4/D5/D6/D11 pinned.

Extends ``test_draft_rules_m2c.py`` (left untouched): hearsay forms
(말했·말씀·하셨, 다며·라며·다면서·라면서, no-space, 문자/메시지/연락
보냈, 약속했/약속하였) block; non-promise 기로 (믿기로, 계기로) and
bare 물어 pass; user sentences use no sourced (amount/date) slots and
only amount/date overlap counts as duplication; neutral document
patterns pass; quote-exhibit/tag mismatches fail.
"""

from app.agents import draft_rules as rules
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


def _gate(entries):
    return rules.check_draft_rules([
        {"sentence_id": sid, "type": stype, "text_with_slots": text,
         "ex_refs": refs}
        for sid, stype, text, refs in entries
    ])


def _single(stype, text):
    return _gate([("s1", stype, text, [])])


# --- D1: must block -----------------------------------------------------------
D1_BLOCK = [
    ("malhaet", "fact", "빌린 돈을 갚는다고 말했습니다. [[EX:1]]"),
    ("nospace", "fact", "빌린 돈을 갚는다고말했습니다. [[EX:1]]"),
    ("hasyeot", "fact", "대출금을 주시겠다고 하셨습니다. [[EX:1]]"),
    ("damyeo", "fact", "다음 주에 갚는다며 전화를 끊었습니다. [[EX:2]]"),
    ("damyeonseo", "fact", "이미 받았다면서 잡아떼었습니다. [[EX:2]]"),
    ("ramyeonseo", "fact", "빨리 보내라면서 재촉했습니다. [[EX:2]]"),
    ("getdamyeo", "fact", "이번 달에 갚겠다며 다짐했습니다. [[EX:2]]"),
    ("yaksok", "fact", "변제를 약속했습니다. [[EX:6]]"),
    ("yaksok-at", "fact", "4월 안에 갚기로 약속하였습니다. [[EX:2]]"),
    ("munja", "user", "갚아 달라고 문자를 보냈습니다. [[USER]]"),
    ("message", "fact", "갚으라고 메시지를 보냈습니다. [[EX:1]]"),
    ("yeonlak", "user", "갚겠다고 연락을 보냈습니다. [[USER]]"),
]


def test_fix1_d1_hearsay_forms_block():
    for label, stype, text in D1_BLOCK:
        gate = _single(stype, text)
        assert gate.status == "fail", label
        assert gate.findings, label


def test_fix1_d1_markers():
    assert rules.has_speech("갚는다고 말했습니다") is not None
    assert rules.has_speech("갚는다고말했습니다") is not None
    assert rules.has_speech("간다고 하셨습니다") is not None
    assert rules.has_speech("갚겠다며 다짐했다") is not None
    assert rules.has_speech("받았다면서 잡아떼었다") is not None
    assert rules.has_speech("보내라면서 재촉했다") is not None
    assert rules.has_speech("변제를 약속했습니다") is not None
    assert rules.has_speech("갚기로 약속하였습니다") is not None
    assert rules.has_speech("달라고 문자를 보냈습니다") is not None
    assert rules.has_speech("갚으라고 메시지를 보냈습니다") is not None
    assert rules.has_speech("갚겠다고 연락을 보냈습니다") is not None


# --- D4: must pass -------------------------------------------------------------
D4_PASS = [
    ("mitgiro", "fact", "믿기로 하고 기다렸습니다. [[EX:1]]"),
    ("gyegiro", "fact", "이 일을 계기로 {{principal}}을 정리했습니다. [[EX:4]]"),
    ("muleo", "user", "이자를 물어 주지 않았습니다. [[USER]]"),
]


def test_fix1_d4_false_positives_pass():
    for label, stype, text in D4_PASS:
        gate = _single(stype, text)
        assert gate.status == "pass", (label, gate.findings)


def test_fix1_d4_giro_markers():
    for word in ("갚기로", "보내기로", "주기로", "드리기로",
                 "돌려주기로", "변제하기로", "지급하기로", "상환하기로"):
        assert rules.has_speech(f"돈을 {word} 했다") is not None, word
    assert rules.has_speech("믿기로 하고 기다렸다") is None
    assert rules.has_speech("이 일을 계기로 삼았다") is None
    assert rules.has_speech("사기로 고소했다") is None
    assert rules.has_speech("이자를 물어 주지 않았다") is None
    assert rules.has_speech("언제 갚을 수 있는지 물었다") is not None
    assert rules.has_speech("언제 갚겠냐고 물어봤다") is not None
    assert rules.has_speech("혼자 중얼거리며 물어봤다") is None


def test_fix1_send_verbs_need_quotative():
    assert rules.has_speech("돈을 보냈습니다") is None
    assert rules.has_speech("이체 확인증에는 보낸 기록이 있습니다") is None
    assert rules.has_speech("그 뒤로 연락을 받지 않았다") is None


# --- D3/D5: user sentences ------------------------------------------------------
def test_fix1_d3_name_only_user_passes():
    gate = _single(
        "user", "그 뒤로 {{debtor_name}}은 연락을 받지 않았습니다. [[USER]]")
    assert gate.status == "pass", gate.findings


def test_fix1_d3_name_only_overlap_passes():
    gate = _gate([
        ("s1", "fact",
         "{{debtor_name}}은 {{quote:EX1:item1}}라고 했습니다. [[EX:1]]", []),
        ("s2", "user",
         "그 뒤로 {{debtor_name}}은 연락을 받지 않았습니다. [[USER]]", []),
    ])
    assert gate.status == "pass", gate.findings


def test_fix1_d3_amount_date_overlap_still_fails():
    gate = _gate([
        ("s1", "fact",
         "{{creditor_name}}이 {{debtor_name}}에게 {{principal}}을 "
         "{{loan_date}}에 송금한 내역이 확인됩니다. [[EX:4]]", ["EX4"]),
        ("s4", "user",
         "{{due_date}}까지 {{principal}}을 받기로 하였다. [[USER]]", []),
    ])
    assert gate.status == "fail"
    assert any("같은 슬롯 조합" in f.message for f in gate.findings)


def test_fix1_d5_user_sourced_slot_fails():
    gate = _single(
        "user", "{{due_date}}까지 잔액을 지급하는 내용입니다. [[USER]]")
    assert gate.status == "fail"
    assert any("근거 있는 칸" in f.message for f in gate.findings)


def test_fix1_d5_explicit_sourced_slots():
    text = "{{repaid_amount}}을 현금으로 받았습니다. [[USER]]"
    assert _single("user", text).status == "fail"
    gate = rules.check_draft_rules(
        [{"sentence_id": "s1", "type": "user",
          "text_with_slots": text, "ex_refs": []}],
        sourced_slots=["due_date"],
    )
    assert gate.status == "pass", gate.findings
    gate = rules.check_draft_rules(
        [{"sentence_id": "s1", "type": "user",
          "text_with_slots": "그 뒤로 {{debtor_name}}은 연락을 받지 "
                             "않았습니다. [[USER]]",
          "ex_refs": []}],
        sourced_slots=["debtor_name", "due_date"],
    )
    assert gate.status == "pass", gate.findings


# --- D6: neutral document patterns pass ------------------------------------------
def test_fix1_d6_neutral_document_patterns_pass():
    first = _single(
        "fact", "차용증에는 변제기가 {{due_date}}로 적혀 있습니다. [[EX:6]]")
    assert first.status == "pass", first.findings
    second = _single(
        "fact", "이체 확인증에는 {{loan_date}}에 {{principal}}을 보낸 "
               "기록이 있습니다. [[EX:4]]")
    assert second.status == "pass", second.findings
    third = _single(
        "fact", "변제하기로 약정하였습니다. [[EX:6]]")
    assert third.status == "fail"


# --- D11: quote/tag exhibit match -------------------------------------------------
def test_fix1_d11_quote_tag_mismatch_fails():
    gate = _single(
        "fact", "{{debtor_name}}은 {{quote:EX1:item1}}라고 했습니다. [[EX:2]]")
    assert gate.status == "fail"
    assert any("인용 슬롯의 증거" in f.message for f in gate.findings)


def test_fix1_d11_quote_tag_match_passes():
    gate = _single(
        "fact", "{{debtor_name}}은 {{quote:EX1:item1}}라고 했습니다. [[EX:1]]")
    assert gate.status == "pass", gate.findings


def test_fix1_d11_lowercase_quote_matches():
    gate = _single(
        "fact", "{{debtor_name}}은 {{quote:ex1:item1}}라고 했습니다. [[EX:1]]")
    assert gate.status == "pass", gate.findings


# --- prompt ----------------------------------------------------------------------
def test_fix1_drafter_v2_prompt_content():
    text = load_prompt("drafter.v2.md")
    assert text.startswith("#")
    assert "drafter.v2" in text.splitlines()[2]
    assert "문서 증거(차용증·이체 확인증)는 모두 한 번 이상 인용한다" in text
    assert "차용증에는 변제기가 {{due_date}}로 적혀 있습니다" in text
    assert "보낸 기록이" in text and "있습니다" in text
    assert "대여 → 약정" in text and "변제" in text and "미지급" in text
    assert "근거가 있는 칸의 슬롯" in text
    assert "인용 슬롯의 증거 번호와 뒤의" in text
    for token in SAMPLE_TOKENS:
        assert token not in text, token
    assert find_forbidden_draft(text) == []
