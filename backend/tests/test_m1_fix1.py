import re
from datetime import date, timedelta
from decimal import Decimal

from pypdf import PdfReader

from app.schemas.loan_fact import (
    LoanFactSchema,
    PartyInfo,
    EvidenceItem,
    RepaymentRecord,
    GeneratedClaimDraft,
    CurrencyEnum,
    EvidenceTypeEnum,
    VerificationStatusEnum,
    TransactionKindEnum,
)
from app.services.draft_gates import (
    KR_SLOTS,
    SlotDraft,
    SlotSentence,
    check_g1a,
    check_g3,
    substitute_text,
    normalize_text,
)
from app.services.naming import find_forbidden, check_draft
from app.services.verification_gate import calculate_kr, VerificationGateService
from app.services.pdf_compiler import KoreanLegalDocumentCompiler

PARTY_KR = ["서가온(SAMPLE)", "탁나루(SAMPLE)"]
EXISTING = ["1", "2"]


def _single(text, sid="x1", stype="fact", refs=None):
    return SlotDraft(
        lang="ko",
        sentences=[
            SlotSentence(
                sentence_id=sid, type=stype, text_with_slots=text, ex_refs=list(refs or [])
            )
        ],
    )


def _base_fact(
    principal="5000000",
    loan=(2026, 3, 10),
    due=(2026, 4, 10),
    agreed=None,
    kind=TransactionKindEnum.CIVIL,
    repayments=None,
    demand=None,
    service=None,
):
    return LoanFactSchema(
        creditor=PartyInfo(name="서가온(SAMPLE)"),
        debtor=PartyInfo(name="탁나루(SAMPLE)"),
        currency=CurrencyEnum.KRW,
        transaction_kind=kind,
        principal_amount=Decimal(principal),
        loan_date=date(*loan),
        due_date=date(*due),
        agreed_interest_rate=Decimal(agreed) if agreed is not None else None,
        repayments=repayments or [],
        demand_date=date(*demand) if demand else None,
        service_date=date(*service) if service else None,
        evidences=[
            EvidenceItem(
                id="갑 제1호증",
                title="이체증",
                evidence_type=EvidenceTypeEnum.TRANSFER_RECEIPT,
                sha256_hash="a" * 64,
                source_filename="f.txt",
                extracted_amount=Decimal(principal),
            ),
            EvidenceItem(
                id="갑 제2호증",
                title="대화록",
                evidence_type=EvidenceTypeEnum.MESSENGER_CHAT,
                sha256_hash="b" * 64,
                source_filename="f2.txt",
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


def test_normalize_fullwidth_hanja_zerowidth():
    assert "5" in normalize_text("５００")
    assert normalize_text("五百萬") == "오백만"
    assert normalize_text("伍佰") == "오백"
    assert "0" in normalize_text("〇")
    assert "\u200b" not in normalize_text("서\u200b씨")
    assert normalize_text("a  b\nc") == "a b c"


def test_g1_bracket_bypass_blocked():
    for text in [
        "돈 [[오백만 원]]을 빌려주었다",
        "사람 [[서가온]]이 빌려갔다",
        "돈 {principal}을 빌려주었다",
        "돈 {{ 들었다",
    ]:
        res = check_g1a(_single(text), KR_SLOTS, PARTY_KR, existing_exhibits=EXISTING)
        assert res.status == "fail", text
    res = check_g1a(
        _single("말 {{quote:EX9:item99}}을 빌려주었다"),
        KR_SLOTS,
        PARTY_KR,
        existing_exhibits=EXISTING,
    )
    assert res.status == "fail"
    ok = check_g1a(
        _single("말 {{quote:EX1:item1}}을 빌려주었다"),
        KR_SLOTS,
        PARTY_KR,
        existing_exhibits=EXISTING,
    )
    assert ok.status == "pass", [f.message for f in ok.findings]


def test_g1_fullwidth_hanja_amount_blocked():
    for text in ["돈 ５００원을 빌려주었다", "돈 五百萬원을 빌려주었다"]:
        res = check_g1a(_single(text), KR_SLOTS, PARTY_KR, existing_exhibits=EXISTING)
        assert res.status == "fail", text


def test_g2_amount_won_requires_number():
    for text in [
        "{{debtor_name}}이 원금을 갚지 않았다",
        "회사원인 친구와 만났다",
        "그는 회사원이다",
        "원금을 돌려받았다",
    ]:
        res = check_g1a(_single(text), KR_SLOTS, PARTY_KR, existing_exhibits=EXISTING)
        assert res.status == "pass", (text, [f.message for f in res.findings])
    for text in ["돈 오백만 원을 빌려주었다", "돈 5000000원을 빌려주었다"]:
        res = check_g1a(_single(text), KR_SLOTS, PARTY_KR, existing_exhibits=EXISTING)
        assert res.status == "fail", text


def test_g3_sino_words_pass_but_real_numbers_blocked():
    for text in [
        "친구 사이이다",
        "이사를 했다",
        "일이 생겨서 늦었다",
        "조만간 만나기로 했다",
        "만일 비가 오면 연기한다",
        "천천히 걸어갔다",
        "영영 돌아오지 않았다",
        "만만한 상대가 아니다",
    ]:
        res = check_g1a(_single(text), KR_SLOTS, PARTY_KR, existing_exhibits=EXISTING)
        assert res.status == "pass", (text, [f.message for f in res.findings])
    for text in ["돈 삼십일을 기다렸다", "돈 오백만을 기다렸다"]:
        res = check_g1a(_single(text), KR_SLOTS, PARTY_KR, existing_exhibits=EXISTING)
        assert res.status == "fail", text


def test_g4_surname_honorific_lookbehind():
    res = check_g1a(_single("에서 양해를 구했다"), KR_SLOTS, PARTY_KR, existing_exhibits=EXISTING)
    assert res.status == "pass", [f.message for f in res.findings]
    for text in ["서 씨가 빌려갔다", "탁 사장이 빌려갔다", "서 선생님이 빌려갔다", "탁 대표가 빌려갔다"]:
        res = check_g1a(_single(text), KR_SLOTS, PARTY_KR, existing_exhibits=EXISTING)
        assert res.status == "fail", text


def test_g5_relative_dates():
    for text in ["한 달 후에 갚겠다", "월말에 갚겠다", "금요일까지 갚겠다", "다음 달에 갚겠다"]:
        res = check_g1a(_single(text), KR_SLOTS, PARTY_KR, existing_exhibits=EXISTING)
        assert res.status == "fail", text
    res = check_g1a(_single("이틀 동안 기다렸다"), KR_SLOTS, PARTY_KR, existing_exhibits=EXISTING)
    assert res.status == "pass", [f.message for f in res.findings]


def test_g6_english_case_insensitive_and_single_char_skip():
    parties = ["Avery Linden (SAMPLE)", "Rowan Hale (SAMPLE)"]
    for text in ["avery linden이 빌려갔다", "AVERY가 빌려갔다"]:
        res = check_g1a(_single(text), KR_SLOTS, parties, existing_exhibits=EXISTING)
        assert res.status == "fail", text
    res = check_g1a(_single("준이 왔다"), KR_SLOTS, ["서준(SAMPLE)"], existing_exhibits=EXISTING)
    assert res.status == "pass", [f.message for f in res.findings]


def test_g3_split_user_ex_and_refs_equality():
    multi = SlotDraft(
        lang="ko",
        sentences=[
            SlotSentence(
                sentence_id="s1",
                type="fact",
                text_with_slots="돈을 빌려주었다. 갚지 않았다. [[EX:1]]",
                ex_refs=["1"],
            )
        ],
    )
    assert check_g3(multi, EXISTING).status == "fail"
    ok = SlotDraft(
        lang="ko",
        sentences=[
            SlotSentence(
                sentence_id="s1",
                type="fact",
                text_with_slots="돈을 빌려주었다. [[EX:1]]",
                ex_refs=["1"],
            )
        ],
    )
    assert check_g3(ok, EXISTING).status == "pass"
    user_bad = _single("아직 받지 못했다. [[USER]] [[EX:9]]", sid="u1", stype="user", refs=[])
    assert check_g3(user_bad, EXISTING).status == "fail"
    mismatch = SlotDraft(
        lang="ko",
        sentences=[
            SlotSentence(
                sentence_id="s1",
                type="fact",
                text_with_slots="돈을 빌려주었다. [[EX:1]]",
                ex_refs=["2"],
            )
        ],
    )
    assert check_g3(mismatch, EXISTING).status == "fail"


def test_naming_variants_blocked_and_allowlist_pass():
    for text in [
        "변 호 사에게 맡기세요",
        "채무를 인정했다",
        "법률자문을 받았다",
        "이길 수 있다",
        "you will win",
        "You are likely to win this",
        "명백한 불법이다",
        "돌려받을 수 있다",
    ]:
        assert find_forbidden(text) != [], text
    for text in [
        "credit counseling을 받았다",
        "[입증 방법]",
        "독촉절차비용은 채무자의 부담으로 한다.",
        "지급하라.",
        "learning counselors meet here",
    ]:
        assert find_forbidden(text) == [], text
    assert "입증할" in "".join(find_forbidden("입증할 것이다"))
    for text in ["최종 변제를 요구한다", "최종 독촉의 건", "변제를 촉구하오니"]:
        assert find_forbidden(text) != [], text


def test_naming_check_draft_gate():
    bad = _single("변 호 사가 필요하다", sid="s1", stype="fact", refs=["1"])
    res = check_draft(bad)
    assert res.gate == "NAMING"
    assert res.status == "fail"
    ok = _single("돈을 빌려주었다. [[EX:1]]", sid="s1", stype="fact", refs=["1"])
    assert check_draft(ok).status == "pass"


def test_kr_slots_new_rate_slots():
    assert "agreed_rate" in KR_SLOTS
    assert "delay_rate" in KR_SLOTS
    assert "contract_interest" in KR_SLOTS
    res = check_g1a(_single("이율은 {{agreed_rate}}이다"), KR_SLOTS, PARTY_KR, existing_exhibits=EXISTING)
    assert res.status == "pass", [f.message for f in res.findings]


def test_josa_adjustment_cases():
    cases = [
        ("{{debtor_name}}은", {"debtor_name": "탁나루(SAMPLE)"}, "탁나루(SAMPLE)는"),
        ("{{creditor_name}}가", {"creditor_name": "서가온(SAMPLE)"}, "서가온(SAMPLE)이"),
        ("{{principal}}을", {"principal": "5,000,000원"}, "5,000,000원을"),
        ("{{principal}}를", {"principal": "5,000,000원"}, "5,000,000원을"),
        ("{{v}}은", {"v": "5,000,000"}, "5,000,000은"),
        ("{{v}}은", {"v": "5,000,002"}, "5,000,002는"),
        ("{{v}}으로", {"v": "서가온"}, "서가온으로"),
        ("{{v}}으로", {"v": "탁나루"}, "탁나루로"),
        ("{{v}}으로", {"v": "삼십일"}, "삼십일로"),
        ("{{v}}으로", {"v": "5,000,001"}, "5,000,001로"),
        ("{{v}}와", {"v": "서가온"}, "서가온과"),
        ("{{v}}과", {"v": "탁나루"}, "탁나루와"),
    ]
    assert len(cases) >= 10
    for template, values, expected in cases:
        assert substitute_text(template, values) == expected, template
    out = substitute_text("{{quote:EX1:item1}}은", {}, {"quote:EX1:item1": "탁나루"})
    assert out == "탁나루은"
    assert substitute_text("{{v}}이에요", {"v": "서가온"}) == "서가온이에요"
    assert substitute_text("{{v}}예요", {"v": "탁나루"}) == "탁나루예요"
    assert substitute_text("{{v}}은행", {"v": "탁나루"}) == "탁나루은행"


def test_k1_exact_integer_example():
    fact = _base_fact(principal="7300000", loan=(2026, 1, 1), due=(2026, 1, 1))
    calc = calculate_kr(fact, date(2026, 1, 1) + timedelta(days=39))
    assert calc.accrued_interest == Decimal("39000")


def test_k1_grid_matches_numer_floor():
    principals = ["100000", "500000", "1000000", "7300000"]
    for p in principals:
        for rate, kind, agreed in [
            ("5", TransactionKindEnum.CIVIL, None),
            ("6", TransactionKindEnum.COMMERCIAL, None),
            ("12", TransactionKindEnum.CIVIL, "12"),
            ("20", TransactionKindEnum.CIVIL, "20"),
        ]:
            fact = _base_fact(principal=p, loan=(2026, 1, 1), due=(2026, 1, 1), agreed=agreed, kind=kind)
            for days in range(1, 401):
                calc = calculate_kr(fact, date(2026, 1, 1) + timedelta(days=days))
                expected = (Decimal(p) * Decimal(rate) * Decimal(days)) // Decimal("36500")
                assert calc.accrued_interest == expected, (p, rate, days)


def test_k2_agreed12_no_repayment_single_sentence():
    fact = _base_fact(agreed="12")
    calc = calculate_kr(fact, date(2026, 6, 1))
    assert calc.remaining_principal == Decimal("5000000")
    assert calc.accrual_start_date == date(2026, 3, 11)
    assert calc.rate_clause.sentence == (
        "채무자는 채권자에게 5,000,000원 및 이에 대하여 2026. 3. 11.부터 "
        "다 갚는 날까지 연 12%의 비율로 계산한 돈을 지급하라."
    )
    assert calc.reference_total.amount == Decimal("5136438")


def test_k2_low_agreed_rate_hold():
    fact = _base_fact(agreed="3")
    calc = calculate_kr(fact, date(2026, 6, 1))
    assert calc.rate_clause.sentence == ""
    assert "agreed_interest_rate" in calc.missing_fields
    res = VerificationGateService.verify_and_reconcile(
        fact, _draft_for("5000000"), target_date=date(2026, 6, 1)
    )
    assert res.is_valid is False
    assert any("이 이율 조합의 청구취지 문구" in m for m in res.missing_requirements)


def test_k3_zero_remaining_sentence_empty():
    fact = _base_fact(
        principal="1000000",
        loan=(2026, 1, 1),
        due=(2026, 2, 1),
        repayments=[RepaymentRecord(payment_date=date(2026, 2, 2), amount=Decimal("2000000"))],
    )
    calc = calculate_kr(fact, date(2026, 3, 1))
    assert calc.remaining_principal == Decimal("0")
    assert calc.rate_clause.sentence == ""


def _kr_doc_fact(**kw):
    fact = _base_fact(principal="10000000", loan=(2026, 1, 1), due=(2026, 6, 30), **kw)
    return fact


def test_k4_content_proof_no_final_urge(tmp_path):
    fact = _kr_doc_fact()
    ver = VerificationGateService.verify_and_reconcile(
        fact, _draft_for("10000000"), target_date=date(2026, 10, 31)
    )
    assert ver.is_valid is True
    out = str(tmp_path / "proof.pdf")
    KoreanLegalDocumentCompiler.generate_content_proof_pdf(
        fact, ver, out, as_of=date(2026, 10, 31)
    )
    text = PdfReader(out).pages[0].extract_text()
    assert "최종" not in text
    assert "촉구" not in text
    assert "보내 주시기 바랍니다" in text
    assert "대여금 반환 청구" in text


def test_k4a_demand_clause_and_doc_patterns():
    fact = _kr_doc_fact(demand=(2026, 7, 1))
    ver = VerificationGateService.verify_and_reconcile(
        fact, _draft_for("10000000"), target_date=date(2026, 10, 31)
    )
    packet = KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(fact, ver)
    assert "최종" not in packet["claim_cause_payment_order"]
    assert "촉구" not in packet["claim_cause_payment_order"]
    assert "변제를 요청" in packet["claim_cause_payment_order"]


def test_k5_base_date_display_and_blank_total(tmp_path):
    fact = _kr_doc_fact()
    ver = VerificationGateService.verify_and_reconcile(
        fact, _draft_for("10000000"), target_date=date(2026, 10, 31)
    )
    out = str(tmp_path / "proof.pdf")
    KoreanLegalDocumentCompiler.generate_content_proof_pdf(
        fact, ver, out, as_of=date(2026, 10, 31)
    )
    text = PdfReader(out).pages[0].extract_text()
    assert "2026. 10. 31. 기준" in text
    out2 = str(tmp_path / "proof2.pdf")
    KoreanLegalDocumentCompiler.generate_content_proof_pdf(fact, ver, out2, as_of=None)
    text2 = PdfReader(out2).pages[0].extract_text()
    assert "기준" not in text2
    assert "금 ____원" in text2
    assert "금 ]" not in text2
    assert "(금 )" not in text2
    packet = KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(
        fact, ver, as_of=date(2026, 10, 31)
    )
    assert "기준" in packet["total_claim_amount"]
    assert "기준" in packet["interest_amount"]
    blank = KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(fact, ver)
    assert "기준" not in blank["total_claim_amount"]
    assert "기준" not in blank["interest_amount"]
    assert "____" in blank["total_claim_amount"]
    assert "____" in blank["interest_amount"]


def test_k6_post_base_repayment_warn_and_filter():
    fact = _kr_doc_fact(
        repayments=[RepaymentRecord(payment_date=date(2026, 8, 1), amount=Decimal("100000"))]
    )
    calc = calculate_kr(fact, date(2026, 6, 30))
    assert any("뒤의 변제" in w for w in calc.warnings)
    ver = VerificationGateService.verify_and_reconcile(
        fact, _draft_for("10000000"), target_date=date(2026, 6, 30)
    )
    packet = KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(
        fact, ver, as_of=date(2026, 6, 30)
    )
    assert "2026. 8. 1." not in packet["claim_cause_payment_order"]


def test_k7_empty_sentence_blank_purpose():
    fact = _base_fact(
        repayments=[RepaymentRecord(payment_date=date(2026, 5, 1), amount=Decimal("10000"))]
    )
    ver = VerificationGateService.verify_and_reconcile(
        fact, _draft_for("5000000"), target_date=date(2026, 5, 1)
    )
    assert ver.calculation is not None
    assert ver.calculation.rate_clause.sentence == ""
    packet = KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(fact, ver)
    assert packet["claim_purpose"] == ""


def test_k8_agreed_rate_fact_sentence():
    fact = _kr_doc_fact(agreed="12")
    ver = VerificationGateService.verify_and_reconcile(
        fact, _draft_for("10000000"), target_date=date(2026, 10, 31)
    )
    packet = KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(fact, ver)
    assert "이자는 연 12%로 정하였습니다." in packet["claim_cause_payment_order"]


def test_k9_footer_date_no_padding_and_rates(tmp_path):
    fact = _kr_doc_fact()
    ver = VerificationGateService.verify_and_reconcile(
        fact, _draft_for("10000000"), target_date=date(2026, 6, 1)
    )
    out = str(tmp_path / "proof.pdf")
    KoreanLegalDocumentCompiler.generate_content_proof_pdf(fact, ver, out, as_of=date(2026, 6, 1))
    text = PdfReader(out).pages[0].extract_text()
    assert "2026년 6월 1일" in text
    assert ver.calculation is not None
    assert format(ver.calculation.rate_clause.pre_service_rate.normalize(), "f") == "5"
    assert format(ver.calculation.rate_clause.post_service_rate.normalize(), "f") == "12"


def test_k10_fact_sentences_used(tmp_path):
    fact = _kr_doc_fact()
    ver = VerificationGateService.verify_and_reconcile(
        fact, _draft_for("10000000"), target_date=date(2026, 10, 31)
    )
    facts = ["승인된 첫 사실이다.", "승인된 둘째 사실이다."]
    packet = KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(
        fact, ver, fact_sentences=facts
    )
    assert "승인된 첫 사실이다." in packet["claim_cause_payment_order"]
    out = str(tmp_path / "proof.pdf")
    KoreanLegalDocumentCompiler.generate_content_proof_pdf(
        fact, ver, out, as_of=date(2026, 10, 31), fact_sentences=facts
    )
    text = PdfReader(out).pages[0].extract_text()
    assert "승인된 첫 사실이다." in text
