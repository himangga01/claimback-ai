"""M1-fix3 회귀 테스트 (리뷰 J1~J7)."""
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

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
from app.services.verification_gate import (
    DeterministicLegalCalculator,
    VerificationGateService,
)

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


# J1: 이어진 문장 검사 오탐 4건 + 평범한 문장 20건은 통과
J1_PASS = [
    "원금을 다 갚지 않았다",
    "필요 없다고 했다",
    "바쁘다 하며 전화를 끊었다",
    "갚겠다 말하고 연락이 끊겼다",
]

J1_NORMAL_20 = [
    "일부를 갚았다",
    "이후 연락이 없다",
    "그는 다시 연락하지 않았다",
    "돈을 빌려주었다",
    "약속한 날에 만나기로 했다",
    "서류를 준비하고 있다",
    "이야기를 나누었다",
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
]


def test_j1_runon_false_positives_pass():
    assert len(J1_PASS) == 4
    assert len(J1_NORMAL_20) == 20
    for text in J1_PASS + J1_NORMAL_20:
        d = _single(text + " [[EX:1]]", refs=["1"])
        res = check_g3(d, EXISTING)
        assert res.status == "pass", (text, [f.message for f in res.findings])


def test_j1_real_runon_still_blocked():
    for text in [
        "돈을 빌려주었다 갚지 않았다 [[EX:1]]",
        "연락을 받았다 만나기로 했다 [[EX:1]]",
    ]:
        res = check_g3(_single(text, refs=["1"]), EXISTING)
        assert res.status == "fail", text
        assert any("마침표" in f.message for f in res.findings), text


# J2: 날짜 단위 + 조사 차단
def test_j2_korean_month_day_year_with_josa_blocked():
    for text in [
        "삼월에 만났다",
        "삼월에도 만났다",
        "오일에 갚겠다",
        "오일에도 갚겠다",
        "오년에 빌려주었다",
        "오년에는 바빴다",
    ]:
        assert _g1a_status(text) == "fail", text


def test_j2_adverb_still_passes():
    assert _g1a_status("일일이 확인했다") == "pass"


# J3: 띄어 쓴 수사 + 조사 ('원' 없음) 차단
def test_j3_spaced_numeral_with_josa_blocked():
    for text in [
        "돈 오 백 만을 빌려주었다",
        "돈 삼 백 만을 기다렸다",
    ]:
        assert _g1a_status(text) == "fail", text


# J4: 법적 라벨
J4_BLOCK = [
    "갚을 의무를 인정했다",
    "시효 중단 사유에 해당한다",
    "편취하였다",
    "받을 권리가 있다",
    "변호인이 필요하다",
    "법률 전문가에게 물었다",
]


def test_j4_legal_labels_blocked():
    for text in J4_BLOCK:
        assert find_forbidden(text) != [], text
        assert check_draft(_single(text)).status == "fail", text


# J5: 상대 날짜 확장
def test_j5_relative_dates_extended():
    for text in [
        "두어 달 뒤에 갚겠다",
        "두어 달 후에 갚겠다",
        "반년 뒤에 갚겠다",
        "반년 안에 갚겠다",
    ]:
        assert _g1a_status(text) == "fail", text


# J6: 기준일 없이 /api/verify 호출
def _kr_fact_for_j6(principal="10000000"):
    return LoanFactSchema(
        creditor=PartyInfo(name="서가온(SAMPLE)"),
        debtor=PartyInfo(name="탁나루(SAMPLE)"),
        currency=CurrencyEnum.KRW,
        transaction_kind=TransactionKindEnum.CIVIL,
        principal_amount=Decimal(principal),
        loan_date=date(2026, 1, 1),
        due_date=date(2026, 6, 30),
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


def _draft_for(amount, jurisdiction="KR", facts="[갑 제1호증] [갑 제2호증]",
               cited=None):
    return GeneratedClaimDraft(
        jurisdiction=jurisdiction,
        claim_amount_claimed=Decimal(amount),
        statement_of_facts=facts,
        cited_evidence_ids=list(cited or ["갑 제1호증", "갑 제2호증"]),
        calculation_summary="Summary",
    )


def test_j6_no_target_date_leaves_reference_empty():
    fact = _kr_fact_for_j6()
    ver = VerificationGateService.verify_and_reconcile(fact, _draft_for("10000000"))
    assert ver.is_valid is True
    assert ver.reconciled_amount == Decimal("10000000")
    assert ver.calculated_interest == Decimal("0")
    assert ver.total_claim_amount == Decimal("10000000")
    assert ver.calculation is not None
    assert ver.calculation.reference_total.amount == Decimal("0")


def test_j6_no_target_date_compares_remaining_only():
    fact = LoanFactSchema(
        creditor=PartyInfo(name="Avery Linden (SAMPLE)"),
        debtor=PartyInfo(name="Rowan Hale (SAMPLE)"),
        currency=CurrencyEnum.USD,
        principal_amount=Decimal("5000.00"),
        loan_date=date(2026, 1, 10),
        due_date=date(2026, 4, 10),
        repayments=[RepaymentRecord(payment_date=date(2026, 5, 1), amount=Decimal("10.00"))],
        evidences=[
            EvidenceItem(
                id="Exhibit A", title="Wire",
                evidence_type=EvidenceTypeEnum.TRANSFER_RECEIPT,
                sha256_hash="1" * 64, source_filename="w.png",
                extracted_amount=Decimal("5000.00"),
            ),
            EvidenceItem(
                id="Exhibit B", title="Chat",
                evidence_type=EvidenceTypeEnum.MESSENGER_CHAT,
                sha256_hash="2" * 64, source_filename="c.png",
            ),
        ],
    )
    rem, acc, _over, _log, _bd = (
        DeterministicLegalCalculator.apply_repayments_and_calculate_balance(
            fact, calculation_date=date(2026, 5, 1)
        )
    )
    assert acc > Decimal("0")
    old_total = rem + acc
    assert old_total != rem
    bad = GeneratedClaimDraft(
        jurisdiction="US",
        claim_amount_claimed=old_total,
        statement_of_facts="[Exhibit A] [Exhibit B]",
        cited_evidence_ids=["Exhibit A", "Exhibit B"],
        calculation_summary="Summary",
    )
    res_bad = VerificationGateService.verify_and_reconcile(fact, bad)
    assert res_bad.is_valid is False
    assert any("청구 금액" in m for m in res_bad.missing_requirements)
    good = GeneratedClaimDraft(
        jurisdiction="US",
        claim_amount_claimed=rem,
        statement_of_facts="[Exhibit A] [Exhibit B]",
        cited_evidence_ids=["Exhibit A", "Exhibit B"],
        calculation_summary="Summary",
    )
    res_good = VerificationGateService.verify_and_reconcile(fact, good)
    assert res_good.is_valid is True
    assert res_good.reconciled_amount == rem


def test_j6_api_verify_without_target_date():
    samples = client.get("/api/demo/samples").json()
    kr = samples["korean_sample"]
    res = client.post("/api/verify", json={
        "loan_fact": kr["loan_fact"],
        "claim_draft": kr["claim_draft"],
    })
    assert res.status_code == 200
    data = res.json()
    assert str(data["reconciled_amount"]).startswith("10000000")
    ref = (data.get("calculation") or {}).get("reference_total")
    assert ref is None or str(ref["amount"]).startswith("0")


# J7: 날짜 슬롯 값은 점 형식으로 만든 뒤 조사 맞춤
def test_j7_iso_date_value_becomes_dotted():
    out = substitute_text("{{d}}는", {"d": "2026-03-12"})
    assert out == "2026. 3. 12.은"
    assert "2026-03-12" not in out
    assert substitute_text("{{d}}가", {"d": "2026-03-12"}) == "2026. 3. 12.이"
    assert substitute_text("{{d}}를", {"d": "2026-03-12"}) == "2026. 3. 12.을"
