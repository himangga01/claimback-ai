import json
import pathlib

import pytest

from app.services.draft_gates import (
    KR_SLOTS,
    SlotDraft,
    SlotSentence,
    check_g1a,
    check_g3,
    substitute_text,
)

PARTY_KR = ["서가온(SAMPLE)", "탁나루(SAMPLE)"]
PARTY_EN = ["Avery Linden (SAMPLE)", "Rowan Hale (SAMPLE)"]
EXISTING = ["1", "2"]


NORMAL_SENTENCES = [
    "일부를 갚았다",
    "이후 연락이 없다",
    "이 돈은",
    "그는 다시 연락하지 않았다",
    "돈을 빌려주었다",
    "약속한 날에 만나기로 했다",
    "서류를 준비하고 있다",
    "이야기를 나누었다",
    "갚겠다는 말을 들었다",
    "연락이 닿지 않았다",
    "빌려준 돈을 기억한다",
    "서로 이야기를 했다",
    "돈 문제로 다투었다",
    "기다리기로 했다",
    "만나서 이야기를 했다",
    "전화를 받지 않았다",
    "문자를 보내었다",
    "사정을 설명하였다",
    "오랫동안 기다렸다",
    "마음을 정하지 못했다",
    "대화를 나누고 헤어졌다",
    "약속을 지키지 않았다",
    "돈을 돌려받지 못했다",
    "연락처를 알고 있다",
]


def _single(text, sid="x1", stype="fact"):
    return SlotDraft(
        lang="ko",
        sentences=[SlotSentence(sentence_id=sid, type=stype, text_with_slots=text, ex_refs=[])],
    )


def test_g1a_normal_draft_passes():
    draft = SlotDraft(
        lang="ko",
        sentences=[
            SlotSentence(
                sentence_id="s1",
                type="fact",
                text_with_slots="채권자 {{creditor_name}}이 채무자 {{debtor_name}}에게 돈을 빌려주었다. [[EX:1]]",
                ex_refs=["1"],
            ),
            SlotSentence(
                sentence_id="s2",
                type="fact",
                text_with_slots="변제기는 {{due_date}}이다. [[EX:2]]",
                ex_refs=["2"],
            ),
            SlotSentence(
                sentence_id="s3",
                type="user",
                text_with_slots="아직 돈을 받지 못했다. [[USER]]",
                ex_refs=[],
            ),
        ],
    )
    res = check_g1a(draft, KR_SLOTS, PARTY_KR)
    assert res.status == "pass"
    assert res.findings == []
    res3 = check_g3(draft, EXISTING)
    assert res3.status == "pass"


def test_g1a_plain_korean_sentences_pass():
    assert len(NORMAL_SENTENCES) >= 20
    draft = SlotDraft(
        lang="ko",
        sentences=[
            SlotSentence(sentence_id=f"n{i}", type="user", text_with_slots=s, ex_refs=[])
            for i, s in enumerate(NORMAL_SENTENCES)
        ],
    )
    res = check_g1a(draft, KR_SLOTS, PARTY_KR)
    assert res.status == "pass", [f.message for f in res.findings]
    assert res.findings == []


def _tamper_cases():
    cases = []
    for i, amt in enumerate(
        ["5000000", "1000000", "350000", "42", "100", "9999", "123456", "777", "10000", "2500000"]
    ):
        cases.append((f"arabic_{i}", f"돈 {amt}원을 빌려주었다"))
    for i, phrase in enumerate(
        [
            "오백만 원",
            "오백만원",
            "백만원",
            "천만원",
            "삼백만원",
            "오천원",
            "일백만원",
            "이천만원",
            "구백만원",
            "십만원",
        ]
    ):
        cases.append((f"korean_amount_{i}", f"돈 {phrase}을 빌려주었다"))
    for i, phrase in enumerate(
        [
            "삼십일",
            "오십",
            "백오십",
            "삼백",
            "천이백",
            "오만",
            "십만",
            "백만",
            "천만",
            "일억",
        ]
    ):
        cases.append((f"korean_number_{i}", f"돈 {phrase}을 기다렸다"))
    for i, phrase in enumerate(
        [
            "4월 10일",
            "3월 11일",
            "5월 1일",
            "1월 1일",
            "12월 31일",
            "6월 30일",
            "8월 31일",
            "10월 31일",
            "2월 2일",
            "7월 10일",
        ]
    ):
        cases.append((f"date_mdy_{i}", f"{phrase}에 빌려주었다"))
    for i, phrase in enumerate(
        [
            "2026. 4. 10.",
            "2026.3.10.",
            "2026. 5. 1.",
            "2026.1.1.",
            "2026. 6. 30.",
            "2026. 8. 31.",
            "2026.10.31.",
            "2026. 2. 2.",
            "2026. 7. 10.",
            "2026.12.31.",
        ]
    ):
        cases.append((f"date_dotted_{i}", f"{phrase}에 빌려주었다"))
    for i, phrase in enumerate(
        [
            "다음 달",
            "지난주",
            "열흘 뒤",
            "다음주",
            "지난달",
            "내일",
            "모레",
            "어제",
            "올해",
            "내년",
        ]
    ):
        cases.append((f"relative_{i}", f"{phrase}에 갚겠다"))
    for i, name in enumerate(
        [
            "서가온",
            "탁나루",
            "서가온(SAMPLE)",
            "탁나루(SAMPLE)",
            "Avery Linden",
            "Rowan Hale",
            "Avery Linden (SAMPLE)",
            "Rowan Hale (SAMPLE)",
            "서가온",
            "탁나루",
        ]
    ):
        cases.append((f"name_full_{i}", f"{name}이 빌려갔다"))
    for i, part in enumerate(
        [
            "가온",
            "나루",
            "서씨",
            "탁씨",
            "서 씨",
            "탁 님",
            "Avery",
            "Linden",
            "Rowan",
            "Hale",
        ]
    ):
        cases.append((f"name_partial_{i}", f"{part}이 빌려갔다"))
    for i, bad in enumerate(
        ["bad_slot", "unknown", "foo", "bar", "invalid", "nope", "wrong", "bad", "oops", "xxx"]
    ):
        cases.append((f"bad_slot_{i}", "돈 {{%s}}을 빌려주었다" % bad))
    for i, phrase in enumerate(
        [
            "지급하라",
            "돈을 지급하라",
            "지금 지급하라",
            "빨리 지급하라",
            "반드시 지급하라",
            "독촉절차비용은 채무자 부담",
            "라는 명령을 구함",
            "지급하라는 명령",
            "지급하라.",
            "지급하라!",
        ]
    ):
        cases.append((f"fixed_{i}", f"돈을 {phrase}"))
    return cases


def test_g1a_100_tampers_all_blocked():
    cases = _tamper_cases()
    assert len(cases) == 100
    blocked = 0
    by_prefix = {}
    for label, text in cases:
        prefix = label.rsplit("_", 1)[0] if "_" in label else label
        if prefix.startswith("name"):
            prefix = "name"
        elif prefix.startswith("date"):
            prefix = "date"
        elif prefix.startswith("korean"):
            prefix = "korean"
        parties = PARTY_KR + PARTY_EN
        draft = _single(text, sid=label)
        res = check_g1a(draft, KR_SLOTS, parties)
        by_prefix.setdefault(prefix, {"total": 0, "blocked": 0})
        by_prefix[prefix]["total"] += 1
        if res.status == "fail" and res.findings:
            blocked += 1
            by_prefix[prefix]["blocked"] += 1
    assert blocked == 100
    for prefix, counts in by_prefix.items():
        assert counts["blocked"] == counts["total"], prefix


def test_g3_fact_requires_ex_tag():
    ok = SlotDraft(
        lang="ko",
        sentences=[
            SlotSentence(
                sentence_id="s1", type="fact",
                text_with_slots="돈을 빌려주었다. [[EX:1]]", ex_refs=["1"],
            )
        ],
    )
    assert check_g3(ok, EXISTING).status == "pass"
    missing = _single("돈을 빌려주었다.", sid="s1", stype="fact")
    assert check_g3(missing, EXISTING).status == "fail"
    bad_ex = SlotDraft(
        lang="ko",
        sentences=[
            SlotSentence(
                sentence_id="s1", type="fact",
                text_with_slots="돈을 빌려주었다. [[EX:9]]", ex_refs=["9"],
            )
        ],
    )
    assert check_g3(bad_ex, EXISTING).status == "fail"


def test_g3_user_requires_user_tag():
    ok = _single("아직 받지 못했다. [[USER]]", sid="u1", stype="user")
    assert check_g3(ok, EXISTING).status == "pass"
    missing = _single("아직 받지 못했다.", sid="u1", stype="user")
    assert check_g3(missing, EXISTING).status == "fail"


def test_slot_substitution_leaves_zero():
    text = "채권자 {{creditor_name}}에게 {{principal}}원을 빌려주었다. {{quote:EX1:item3}}"
    out = substitute_text(
        text,
        {"creditor_name": "서가온", "principal": "5,000,000"},
        {"quote:EX1:item3": "원문 인용"},
    )
    assert "{{" not in out
    assert "서가온" in out
    assert "원문 인용" in out
    with pytest.raises(ValueError):
        substitute_text("{{missing}}", {"other": "x"})


def test_demo_tampered_draft_fixture_blocks_one_sentence():
    path = pathlib.Path(__file__).parent / "fixtures" / "demo_tampered_draft_kr.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    normal = SlotDraft(**data["normal_draft"])
    tampered = SlotDraft(**data["tampered_draft"])
    assert check_g1a(normal, KR_SLOTS, PARTY_KR).status == "pass"
    res = check_g1a(tampered, KR_SLOTS, PARTY_KR)
    assert res.status == "fail"
    ids = {f.sentence_id for f in res.findings}
    assert ids == {"t1"}
