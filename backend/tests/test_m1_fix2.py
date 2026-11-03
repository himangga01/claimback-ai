"""M1-fix2 회귀 테스트 (리뷰 H1~H13, H13a 원칙, H14 공격 문자열표)."""
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.main import app
from app.schemas.loan_fact import (
    CurrencyEnum,
    EvidenceItem,
    EvidenceTypeEnum,
    GeneratedClaimDraft,
    LoanFactSchema,
    PartyInfo,
    RepaymentRecord,
    TransactionKindEnum,
)
from app.services.draft_gates import (
    KR_SLOTS,
    SlotDraft,
    SlotSentence,
    check_g1a,
    check_g3,
    substitute_text,
)
from app.services.naming import check_draft, find_forbidden
from app.services.pdf_compiler import KoreanLegalDocumentCompiler
from app.services.verification_gate import VerificationGateService, calculate_kr

PARTY_KR = ["서가온(SAMPLE)", "탁나루(SAMPLE)"]
EXISTING = ["1", "2"]
client = TestClient(app)


def _single(text, sid="x1", stype="fact", refs=None):
    return SlotDraft(
        lang="ko",
        sentences=[
            SlotSentence(
                sentence_id=sid, type=stype, text_with_slots=text, ex_refs=list(refs or [])
            )
        ],
    )


def _g1a_status(text):
    parties = PARTY_KR + ["Avery Linden (SAMPLE)", "Rowan Hale (SAMPLE)"]
    return check_g1a(_single(text), KR_SLOTS, parties, existing_exhibits=EXISTING).status


def _base_fact(principal="5000000", loan=(2026, 3, 10), due=(2026, 4, 10),
               agreed=None, repayments=None, demand=None):
    return LoanFactSchema(
        creditor=PartyInfo(name="서가온(SAMPLE)"),
        debtor=PartyInfo(name="탁나루(SAMPLE)"),
        currency=CurrencyEnum.KRW,
        transaction_kind=TransactionKindEnum.CIVIL,
        principal_amount=Decimal(principal),
        loan_date=date(*loan),
        due_date=date(*due),
        agreed_interest_rate=Decimal(agreed) if agreed is not None else None,
        repayments=repayments or [],
        demand_date=date(*demand) if demand else None,
        evidences=[
            EvidenceItem(
                id="갑 제1호증", title="이체증",
                evidence_type=EvidenceTypeEnum.TRANSFER_RECEIPT,
                sha256_hash="a" * 64, source_filename="f.txt",
                extracted_amount=Decimal(principal),
            ),
            EvidenceItem(
                id="갑 제2호증", title="대화록",
                evidence_type=EvidenceTypeEnum.MESSENGER_CHAT,
                sha256_hash="b" * 64, source_filename="f2.txt",
            ),
        ],
    )


def _draft_for(amount):
    return GeneratedClaimDraft(
        jurisdiction="KR",
        claim_amount_claimed=Decimal(amount),
        statement_of_facts="[갑 제1호증] [갑 제2호증]",
        cited_evidence_ids=["갑 제1호증", "갑 제2호증"],
        calculation_summary="Summary",
    )


# H1: 수사 + 어림 + 단위, 수사 낱말 + 단위 낱말은 차단
H1_BLOCK = [
    "돈 오백만여 원을 빌려주었다",
    "돈 오백만여원을 빌려주었다",
    "돈 삼십여 일을 기다렸다",
    "돈 오백만쯤 원을 빌려주었다",
    "돈 이백가량 원을 빌려주었다",
    "돈 삼십정도 일을 기다렸다",
    "돈 백남짓 원을 빌려주었다",
    "삼 개월을 기다렸다",
    "오 개월 뒤에 갚겠다",
]

# H2: 상대 날짜 확장
H2_BLOCK = [
    "몇 달 뒤에 갚겠다",
    "석 달 안에 갚겠다",
    "넉 달 뒤에 갚겠다",
    "일주일쯤 뒤에 갚겠다",
    "일주일 정도 뒤에 갚겠다",
    "두 해 뒤에 갚겠다",
    "한 주 뒤에 갚겠다",
    "네 해 뒤에 갚겠다",
    "몇 주 뒤에 갚겠다",
    "석 해 뒤에 갚겠다",
]

# H3: 오탐 7건은 통과
H3_PASS = [
    "몇 달 만에 만났다",
    "조사를 받았다",
    "일일이 확인했다",
    "회사일이 바빴다",
    "그제야 연락했다",
    "그제서야 연락했다",
    "다음 주소로 보냈다",
]

H3_BLOCK_STILL = [
    "그제에 만났다",
    "다음 주에 만났다",
    "다음 달에 갚겠다",
    "지난주에 만났다",
]


def test_h1_approx_and_numeral_unit_blocked():
    for text in H1_BLOCK:
        assert _g1a_status(text) == "fail", text


def test_h1_plain_words_without_numeral_pass():
    for text in ["여유가 없다", "정도가 심하다", "가량 짐작했다"]:
        assert _g1a_status(text) == "pass", text


def test_h2_extended_relative_dates_blocked():
    for text in H2_BLOCK:
        assert _g1a_status(text) == "fail", text


def test_h2_duration_without_suffix_passes():
    assert _g1a_status("한 주 동안 기다렸다") == "pass"


def test_h3_false_positives_pass():
    for text in H3_PASS:
        assert _g1a_status(text) == "pass", text


def test_h3_real_dates_still_blocked():
    for text in H3_BLOCK_STILL:
        assert _g1a_status(text) == "fail", text


def test_h3_fail_news_passes_naming():
    assert find_forbidden("실패 소식에 낙담했다") == []
    assert find_forbidden("승소했다") != []
    assert find_forbidden("패소했다") != []
    assert find_forbidden("승 소했다") == []
    assert find_forbidden("패 소했다") == []


# H4: 조사 맞춤 15건 이상
H4_CASES = [
    ("{{d}}는", {"d": "2026. 4. 2."}, "2026. 4. 2.은"),
    ("{{d}}가", {"d": "2026. 4. 2."}, "2026. 4. 2.이"),
    ("{{d}}를", {"d": "2026. 4. 2."}, "2026. 4. 2.을"),
    ("{{d}}와", {"d": "2026. 4. 2."}, "2026. 4. 2.과"),
    ("{{d}}으로", {"d": "2026. 4. 2."}, "2026. 4. 2.로"),
    ("{{v}}을", {"v": "20%"}, "20%를"),
    ("{{v}}은", {"v": "20%"}, "20%는"),
    ("{{v}}로", {"v": "서울특별시 샘플구 데모로 0"}, "서울특별시 샘플구 데모로 0으로"),
    ("{{v}}은", {"v": "서울특별시 샘플구 데모로 0"}, "서울특별시 샘플구 데모로 0은"),
    ("{{v}}은(는)", {"v": "탁나루"}, "탁나루는"),
    ("{{v}}은(는)", {"v": "서가온"}, "서가온은"),
    ("{{v}}을(를)", {"v": "탁나루"}, "탁나루를"),
    ("{{v}}을(를)", {"v": "서가온"}, "서가온을"),
    ("{{v}}이(가)", {"v": "서가온"}, "서가온이"),
    ("{{v}}과(와)", {"v": "서가온"}, "서가온과"),
    ("{{v}}으로(로)", {"v": "서가온"}, "서가온으로"),
    ("{{v}}으로(로)", {"v": "탁나루"}, "탁나루로"),
    ("{{v}}으로부터", {"v": "서가온"}, "서가온으로부터"),
    ("{{v}}으로부터", {"v": "탁나루"}, "탁나루로부터"),
    ("{{v}}과의", {"v": "탁나루"}, "탁나루와의"),
    ("{{v}}이라는", {"v": "서가온"}, "서가온이라는"),
    ("{{v}}이라는", {"v": "탁나루"}, "탁나루라는"),
    ("{{v}}이라고", {"v": "탁나루"}, "탁나루라고"),
    ("{{v}}로서", {"v": "서가온"}, "서가온으로서"),
]


def test_h4_josa_cases():
    assert len(H4_CASES) >= 15
    for template, values, expected in H4_CASES:
        assert substitute_text(template, values) == expected, template


# H5: 초안·서류 검사 일치
def test_h5_draft_blocks_urge_and_final():
    for text in [
        "변제를 촉구한다",
        "최종 변제를 요구한다",
        "최종 독촉의 건",
        "최종 통고를 보낸다",
        "최종 경고를 한다",
    ]:
        assert check_draft(_single(text)).status == "fail", text


# H6: 명칭 누락
def test_h6_naming_gaps_blocked():
    for text in [
        "lawyers are here",
        "attorneys are here",
        "채무의 존재를 인정했다",
        "채무 존재를 승인했다",
        "사기를 쳤다",
        "사기죄로 고소한다",
        "사기꾼이다",
        "법적 책임을 묻는다",
        "법적 의무가 있다",
        "청구할 수 있습니다",
    ]:
        assert find_forbidden(text) != [], text
        assert check_draft(_single(text)).status == "fail", text


def test_h6_english_partial_inside_word_passes():
    parties = ["Avery Linden (SAMPLE)"]
    res = check_g1a(_single("bravery를 보였다"), KR_SLOTS, parties,
                    existing_exhibits=EXISTING)
    assert res.status == "pass", [f.message for f in res.findings]
    res2 = check_g1a(_single("Avery가 빌려갔다"), KR_SLOTS, parties,
                     existing_exhibits=EXISTING)
    assert res2.status == "fail"


# H7: G3 문장 나누기
def test_h7_leading_tag_and_quotes():
    ok = SlotDraft(
        lang="ko",
        sentences=[
            SlotSentence(
                sentence_id="s1", type="fact",
                text_with_slots="[[EX:2]]에 따르면 돈을 빌려주었다.",
                ex_refs=["2"],
            )
        ],
    )
    assert check_g3(ok, EXISTING).status == "pass"
    quoted = _single('그는 "정말?"이라고 말했다. [[EX:1]]', refs=["1"])
    assert check_g3(quoted, EXISTING).status == "pass", [
        f.message for f in check_g3(quoted, EXISTING).findings
    ]


def test_h7_missing_period_warns():
    d = _single("돈을 빌려주었다 갚지 않았다 [[EX:1]]", refs=["1"])
    res = check_g3(d, EXISTING)
    assert res.status == "fail"
    assert any("마침표" in f.message for f in res.findings)


# H8: existing_exhibits 필수
def test_h8_existing_exhibits_required():
    with pytest.raises(TypeError):
        check_g1a(_single("돈을 빌려주었다"), KR_SLOTS, PARTY_KR)
    bad = check_g1a(
        _single("말 {{quote:EX9:item1}}을 빌려주었다"),
        KR_SLOTS, PARTY_KR, existing_exhibits=EXISTING,
    )
    assert bad.status == "fail"
    ok = check_g1a(
        _single("말 {{quote:EX1:item1}}을 빌려주었다"),
        KR_SLOTS, PARTY_KR, existing_exhibits=EXISTING,
    )
    assert ok.status == "pass", [f.message for f in ok.findings]


# H9: 약정 이율 보류 범위
def test_h9_zero_rate_means_no_agreed():
    calc = calculate_kr(_base_fact(agreed="0"), date(2026, 6, 1))
    assert "agreed_interest_rate" not in calc.missing_fields
    assert calc.rate_clause.sentence != ""


def test_h9_covered_agreed_interest_no_hold():
    fact = _base_fact(
        agreed="3",
        repayments=[RepaymentRecord(payment_date=date(2026, 5, 1),
                                    amount=Decimal("1000000"))],
    )
    calc = calculate_kr(fact, date(2026, 6, 1))
    assert "agreed_interest_rate" not in calc.missing_fields
    assert calc.rate_clause.sentence != ""


def test_h9_uncovered_low_rate_still_holds():
    calc = calculate_kr(_base_fact(agreed="3"), date(2026, 6, 1))
    assert calc.rate_clause.sentence == ""
    assert "agreed_interest_rate" in calc.missing_fields


# H10: 기준일 없음
def test_h10_blank_amounts_without_as_of(tmp_path):
    fact = _base_fact(principal="10000000", loan=(2026, 1, 1), due=(2026, 6, 30))
    ver = VerificationGateService.verify_and_reconcile(
        fact, _draft_for("10000000"), target_date=date(2026, 10, 31)
    )
    packet = KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(fact, ver)
    assert "기준" not in packet["total_claim_amount"]
    assert "기준" not in packet["interest_amount"]
    assert "____" in packet["total_claim_amount"]
    assert "____" in packet["interest_amount"]
    out = str(tmp_path / "proof.pdf")
    KoreanLegalDocumentCompiler.generate_content_proof_pdf(fact, ver, out, as_of=None)
    text = PdfReader(out).pages[0].extract_text()
    assert "기준" not in text
    assert "금 ]" not in text
    assert "(금 )" not in text
    assert "금 ____원" in text


def test_h10_ecourt_route_passes_as_of():
    samples = client.get("/api/demo/samples").json()
    kr = samples["korean_sample"]
    res = client.post("/api/compile/ecourt-packet", json={
        "loan_fact": kr["loan_fact"],
        "claim_draft": kr["claim_draft"],
        "target_date": "2026-10-31",
    })
    assert res.status_code == 200
    assert "2026. 10. 31. 기준" in res.json()["total_claim_amount"]
    res2 = client.post("/api/compile/ecourt-packet", json={
        "loan_fact": kr["loan_fact"],
        "claim_draft": kr["claim_draft"],
    })
    assert res2.status_code == 200
    assert "기준" not in res2.json()["total_claim_amount"]


# H11: 서류 문장 이스케이프 + 필수 문장 유지
def test_h11_fact_sentences_escaped_and_required_kept(tmp_path):
    fact = _base_fact(principal="10000000", loan=(2026, 1, 1), due=(2026, 6, 30),
                      agreed="12",
                      repayments=[RepaymentRecord(payment_date=date(2026, 7, 5),
                                                  amount=Decimal("1000000"))])
    ver = VerificationGateService.verify_and_reconcile(
        fact, _draft_for("9000000"), target_date=date(2026, 10, 31)
    )
    facts = ["<b>굵게?</b> & <br/> 확인된 첫 사실이다.", "확인된 둘째 사실이다."]
    packet = KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(
        fact, ver, as_of=date(2026, 10, 31), fact_sentences=facts
    )
    cause = packet["claim_cause_payment_order"]
    assert "확인된 첫 사실이다." in cause
    assert "이자는 연 12%로 정하였습니다." in cause
    assert "남은 원금" in cause
    assert "변제" in cause
    out = str(tmp_path / "proof.pdf")
    KoreanLegalDocumentCompiler.generate_content_proof_pdf(
        fact, ver, out, as_of=date(2026, 10, 31), fact_sentences=facts
    )
    text = PdfReader(out).pages[0].extract_text()
    assert "<b>" in text
    assert "&" in text
    assert "확인된 첫 사실이다." in text
    assert "변제기 이후" in text


# H12: 이율 문자열
def test_h12_rate_strings_without_decimals():
    calc = calculate_kr(_base_fact(), date(2026, 6, 1))
    assert str(calc.rate_clause.pre_service_rate) == "5"
    assert str(calc.rate_clause.post_service_rate) == "12"
    calc2 = calculate_kr(_base_fact(agreed="20"), date(2026, 6, 1))
    assert str(calc2.rate_clause.pre_service_rate) == "20"


# H13: 반복 문구
def test_h13_no_repeated_due_clause():
    fact = _base_fact()
    ver = VerificationGateService.verify_and_reconcile(
        fact, _draft_for("5000000"), target_date=date(2026, 6, 1)
    )
    packet = KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(
        fact, ver, as_of=date(2026, 6, 1)
    )
    cause = packet["claim_cause_payment_order"]
    assert "약정 변제기가 지났음에도 채무자는 현재까지" in cause
    assert "변제기 이후 현재까지" not in cause


# H14: 공격 문자열표 전수
H14_BLOCK = H1_BLOCK + H2_BLOCK + H3_BLOCK_STILL
H14_PASS = H3_PASS + [
    "이틀 동안 기다렸다",
    "한 주 동안 기다렸다",
    "조만간 만나기로 했다",
    "천천히 걸어갔다",
    "만일 비가 오면 연기한다",
    "영영 돌아오지 않았다",
    "만만한 상대가 아니다",
    "에서 양해를 구했다",
]


def test_h14_attack_table():
    for text in H14_BLOCK:
        assert _g1a_status(text) == "fail", text
    for text in H14_PASS:
        assert _g1a_status(text) == "pass", text
