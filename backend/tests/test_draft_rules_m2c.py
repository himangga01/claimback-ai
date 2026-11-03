"""M2c draft-rule tests: brief examples pinned (false pass 0, true block 0).

Covers the INT-2-review A1/A2 gaps fixed in ``draft_rules.py``:
contract_interest ban, quote/speech sentences limited to party-name
slots, wider speech/promise detection with eojeol-level judgment,
user-sentence slot-combo repeats, and sentences ending after a quote.
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


# --- must block (each alone fails DRAFT) --------------------------------------
BLOCK_CASES = [
    ("contract-interest",
     "fact",
     "{{creditor_name}}은 약정 이자율 {{contract_interest}}를 정했다. [[EX:6]]"),
    ("quote-amount-date-mismatch",
     "fact",
     "{{debtor_name}}은 {{due_date}}까지 {{principal}}을 갚겠다고 말하며 "
     "{{quote:EX2:item23}} [[EX:2]]."),
    ("user-promise",
     "user",
     "{{debtor_name}}은 {{due_date}}까지 {{principal}}을 보내기로 했다. [[USER]]"),
    ("fact-promise-past",
     "fact",
     "{{due_date}}까지 갚기로 하였다. [[EX:1]]"),
    ("fact-quotative-haetda",
     "fact",
     "빌린 돈을 보내 준다고 했다. [[EX:1]]"),
    ("fact-answer",
     "fact",
     "바로 보내겠다고 답했다. [[EX:1]]"),
    ("user-quotative",
     "user",
     "돌려 달라고 했다. [[USER]]"),
    ("fact-future-give",
     "fact",
     "{{debtor_name}}은 돌려드리겠다고 했다. [[EX:1]]"),
    ("fact-ask",
     "fact",
     "언제 갚을 수 있는지 물었다. [[EX:2]]"),
    ("user-old-juggetda",
     "user",
     "{{debtor_name}}은 {{due_date}}까지 {{remaining_principal}}을 주겠다고. [[USER]]"),
    ("user-quote",
     "user",
     "직접 들었다 {{quote:EX1:item1}} [[USER]]"),
    ("int2-final-s2",
     "fact",
     "{{debtor_name}}은 {{due_date}}까지 {{principal}}을 갚겠다고 말하며 "
     "{{quote:EX1:item10}} [[EX:1]]."),
]


def test_m2c_block_cases_fail():
    for label, stype, text in BLOCK_CASES:
        gate = _single(stype, text)
        assert gate.status == "fail", label
        assert gate.findings, label


def test_m2c_quote_sentence_rejects_amount_date_slots():
    gate = _single(
        "fact",
        "{{debtor_name}}은 {{due_date}}까지 갚겠다고 했습니다 [[EX:1]]. "
        "{{quote:EX1:item1}} [[EX:6]]")
    assert gate.status == "fail"
    assert any("금액·날짜 슬롯" in f.message for f in gate.findings)


def test_m2c_contract_interest_is_calculated():
    assert "contract_interest" in rules.CALCULATED_SLOTS
    values = {name: "값" for name in (
        "creditor_name", "principal", "remaining_principal",
        "accrual_start_date", "total_claim_amount", "calculated_interest",
        "delay_rate", "contract_interest")}
    allowed = rules.drafter_allowed_slots(values)
    assert "creditor_name" in allowed
    assert "principal" in allowed
    for banned in rules.CALCULATED_SLOTS:
        assert banned not in allowed


def test_m2c_user_repeating_slot_combo_fails():
    gate = _gate([
        ("s1", "fact",
         "{{creditor_name}}이 {{debtor_name}}에게 {{principal}}을 "
         "{{loan_date}}에 송금한 내역이 확인됩니다. [[EX:4]]",
         ["EX4"]),
        ("s4", "user",
         "{{creditor_name}}이 {{debtor_name}}에게 {{principal}}을 "
         "{{loan_date}}에 송금하였다. [[USER]]",
         []),
    ])
    assert gate.status == "fail"
    assert any("같은 슬롯 조합" in f.message for f in gate.findings)
    assert all(f.sentence_id == "s4" for f in gate.findings
               if "같은 슬롯 조합" in f.message)


def test_m2c_sentence_ending_after_quote_fails():
    gate = _single(
        "fact",
        "{{debtor_name}}은 {{quote:EX1:item10}} [[EX:1]].")
    assert gate.status == "fail"
    assert any("인용 뒤에" in f.message for f in gate.findings)


# --- must pass -----------------------------------------------------------------
PASS_CASES = [
    ("user-request-noun",
     "user",
     "여러 차례 갚아 달라고 요청하였으나 받지 못했다. [[USER]]"),
    ("fact-as-promised",
     "fact",
     "약속한 대로 {{loan_date}}에 {{principal}}을 보냈다. [[EX:4]]"),
    ("user-promised-money",
     "user",
     "약속한 돈을 보내지 않았다. [[USER]]"),
    ("fact-quote-name-only",
     "fact",
     "{{debtor_name}}은 {{quote:EX1:item1}}라고 했습니다. [[EX:1]] [[EX:6]]"),
    ("fact-plain-amount-date",
     "fact",
     "{{creditor_name}}은 {{loan_date}} {{debtor_name}}에게 "
     "{{principal}}을 보냈습니다. [[EX:4]]"),
    ("user-no-slots",
     "user",
     "그 뒤로 남은 돈을 받지 못했습니다. [[USER]]"),
    ("fact-agreed-rate-plain",
     "fact",
     "약정 이율은 {{agreed_rate}}이다. [[EX:6]]"),
]


def test_m2c_pass_cases_pass_alone():
    for label, stype, text in PASS_CASES:
        gate = _single(stype, text)
        assert gate.status == "pass", (label, gate.findings)


def test_m2c_pass_cases_pass_together():
    entries = [(f"s{i}", stype, text, [])
               for i, (_, stype, text) in enumerate(PASS_CASES)]
    gate = _gate(entries)
    assert gate.status == "pass", gate.findings


def test_m2c_two_slotless_user_sentences_pass():
    gate = _gate([
        ("s1", "user", "그 뒤로 남은 돈을 받지 못했습니다. [[USER]]", []),
        ("s2", "user", "연락이 닿지 않았습니다. [[USER]]", []),
    ])
    assert gate.status == "pass", gate.findings


def test_m2c_has_speech_markers():
    assert rules.has_speech("보내기로 했다") is not None
    assert rules.has_speech("갚기로 하였다") is not None
    assert rules.has_speech("준다고 했다") is not None
    assert rules.has_speech("답했다") is not None
    assert rules.has_speech("돌려드리겠다") is not None
    assert rules.has_speech("여러 차례 갚아 달라고 요청하였으나 받지 못했다") is None
    assert rules.has_speech("약속한 대로 보냈다") is None
    assert rules.has_speech("약속한 돈을 보내지 않았다") is None


def test_m2c_drafter_v2_prompt_hygiene():
    text = load_prompt("drafter.v2.md")
    assert text.startswith("#")
    assert "drafter.v2" in text.splitlines()[2]
    assert "contract_interest" in text
    for token in SAMPLE_TOKENS:
        assert token not in text, token
    assert find_forbidden_draft(text) == []
