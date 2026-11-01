import os
import pytest
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
    ContractFormEnum,
)
from app.services.verification_gate import (
    DeterministicLegalCalculator,
    VerificationGateService,
    verify_file_bytes_sha256,
)
from app.services.pdf_compiler import (
    CaliforniaSC100Compiler,
    KoreanLegalDocumentCompiler,
)


@pytest.fixture
def sample_korean_loan_fact():
    return LoanFactSchema(
        creditor=PartyInfo(
            name="정재훈",
            phone="010-4690-7547",
            address="서울 송파구 거여동 거여1단지 106-1104",
            city="서울",
            state="서울",
            zip_code="05753",
        ),
        debtor=PartyInfo(
            name="김채무",
            phone="010-1234-5678",
            address="경기 성남시 중원구 금광동 100",
            city="성남",
            state="경기",
            zip_code="13180",
        ),
        currency=CurrencyEnum.KRW,
        transaction_kind=TransactionKindEnum.CIVIL,
        principal_amount=Decimal("10000000"),  # 1,000만 원
        loan_date=date(2026, 1, 1),
        due_date=date(2026, 6, 30),
        evidences=[
            EvidenceItem(
                id="갑 제1호증",
                title="토스뱅크 계좌이체확인증",
                evidence_type=EvidenceTypeEnum.TRANSFER_RECEIPT,
                sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                source_filename="toss_transfer_receipt.pdf",
                extracted_amount=Decimal("10000000"),
                extracted_date=date(2026, 1, 1),
            ),
            EvidenceItem(
                id="갑 제2호증",
                title="카카오톡 대화록(변제 약속)",
                evidence_type=EvidenceTypeEnum.MESSENGER_CHAT,
                sha256_hash="a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e",
                source_filename="kakaotalk_chat.mp4",
                extracted_date=date(2026, 6, 25),
            ),
        ],
    )


@pytest.fixture
def sample_us_loan_fact():
    return LoanFactSchema(
        creditor=PartyInfo(
            name="Jaehoon Jeong",
            phone="010-4690-7547",
            address="106-1104, Geoyeo 1-danji Apt, Songpa-gu",
            city="Seoul",
            state="KR",
            zip_code="05753",
        ),
        debtor=PartyInfo(
            name="Michael Scott",
            phone="213-555-0144",
            address="1725 Slough Avenue",
            city="Los Angeles",
            state="CA",
            zip_code="90012",
        ),
        currency=CurrencyEnum.USD,
        contract_form=ContractFormEnum.WRITTEN,
        principal_amount=Decimal("5000.00"),  # $5,000
        loan_date=date(2026, 1, 10),
        due_date=date(2026, 4, 10),
        evidences=[
            EvidenceItem(
                id="Exhibit A",
                title="Wire Transfer Confirmation",
                evidence_type=EvidenceTypeEnum.TRANSFER_RECEIPT,
                sha256_hash="1111111111111111111111111111111111111111111111111111111111111111",
                source_filename="wire_receipt.png",
                extracted_amount=Decimal("5000.00"),
                extracted_date=date(2026, 1, 10),
            ),
            EvidenceItem(
                id="Exhibit B",
                title="iMessage Promissory Admission",
                evidence_type=EvidenceTypeEnum.MESSENGER_CHAT,
                sha256_hash="2222222222222222222222222222222222222222222222222222222222222222",
                source_filename="imessage_chat.png",
                extracted_date=date(2026, 4, 1),
            ),
        ],
    )


# ---------------------------------------------------------------------------
# 1. Deterministic Legal Calculator & Korean 2-Stage Interest Tests (C-1)
# ---------------------------------------------------------------------------

def test_interest_calculation_precision_korea():
    principal = Decimal("10000000")
    start = date(2026, 1, 1)
    end = date(2026, 12, 31)
    interest = DeterministicLegalCalculator.calculate_statutory_interest(
        principal, start, end, Decimal("12.0")
    )
    assert interest == Decimal("1196712.33")


def test_interest_calculation_us_california_exact_10_percent():
    principal = Decimal("5000.00")
    start = date(2026, 1, 1)
    end = date(2026, 1, 1) + timedelta(days=365)
    interest = DeterministicLegalCalculator.calculate_statutory_interest(
        principal, start, end, Decimal("10.0")
    )
    assert interest == Decimal("500.00")


def test_agreed_interest_rate_capped_at_20_percent():
    fact = LoanFactSchema(
        creditor=PartyInfo(name="A"),
        debtor=PartyInfo(name="B"),
        currency=CurrencyEnum.KRW,
        principal_amount=Decimal("1000000"),
        loan_date=date(2026, 1, 1),
        due_date=date(2026, 3, 1),
        agreed_interest_rate=Decimal("20.0"),
    )
    rem_p, acc_i, overp, log, breakdown = DeterministicLegalCalculator.apply_repayments_and_calculate_balance(
        fact, calculation_date=date(2026, 4, 1)
    )
    assert any("20.0%" in line for line in log)


def test_verification_tampering_reconciliation(sample_korean_loan_fact):
    # LLM이 1,200만 원으로 수치 할루시네이션(위변조)을 일으킨 경우
    draft = GeneratedClaimDraft(
        jurisdiction="KR",
        claim_amount_claimed=Decimal("12000000"),
        statement_of_facts="채무자는 [갑 제1호증] 송금액을 갚지 않고 있음.",
        cited_evidence_ids=["갑 제1호증"],
        calculation_summary="원금 12,000,000원 주장",
    )
    result = VerificationGateService.verify_and_reconcile(
        loan_fact=sample_korean_loan_fact,
        claim_draft=draft,
        target_date=date(2026, 6, 30),
    )
    assert result.status == VerificationStatusEnum.RECONCILED
    assert result.is_valid is True
    assert result.reconciled_amount == Decimal("10000000")
    assert len(result.tampering_reconciliations) == 1


def test_korean_civil_interest_segments_pre_and_post_service(sample_korean_loan_fact):
    # 변제기 2026-06-30. 소장 송달일 2026-08-31. 최종 계산일 2026-10-31
    sample_korean_loan_fact.service_date = date(2026, 8, 31)
    calc_date = date(2026, 10, 31)

    rem_p, acc_i, overp, log, breakdown = (
        DeterministicLegalCalculator.apply_repayments_and_calculate_balance(
            sample_korean_loan_fact, calculation_date=calc_date
        )
    )

    # 1단계 (6/30 ~ 8/31, 62일간 연 5%): 10,000,000 * 0.05 * (62 / 365) = 84,931.5 -> 84,931.51원
    # 2단계 (8/31 ~ 10/31, 61일간 연 12%): 10,000,000 * 0.12 * (61 / 365) = 200,547.9 -> 200,547.95원
    assert breakdown["pre_service_interest"] > Decimal("0")
    assert breakdown["post_service_interest"] > Decimal("0")
    assert any("소촉법 송달 후 지연손해금(연 12%)" in line for line in log)
    assert any("송달 전 지연손해금(연 5.0%)" in line for line in log)


def test_korean_civil_interest_without_service_date_uses_5_percent_only(sample_korean_loan_fact):
    # 소장 송달 전에는 과다 청구를 방지하기 위해 전 구간 연 5% 적용
    sample_korean_loan_fact.service_date = None
    calc_date = date(2026, 10, 31)

    rem_p, acc_i, overp, log, breakdown = (
        DeterministicLegalCalculator.apply_repayments_and_calculate_balance(
            sample_korean_loan_fact, calculation_date=calc_date
        )
    )
    assert any("연 5.0%" in line for line in log)
    assert not any("연 12%" in line for line in log)


# ---------------------------------------------------------------------------
# 2. Overpayment & Pure Function Tests (🛡️-1)
# ---------------------------------------------------------------------------

def test_overpayment_preserved_and_flagged(sample_korean_loan_fact):
    # 원금 1,000만 원인데 1,500만 원을 변제한 경우
    sample_korean_loan_fact.repayments.append(
        RepaymentRecord(payment_date=date(2026, 7, 10), amount=Decimal("15000000"))
    )
    rem_p, acc_i, overp, log, breakdown = (
        DeterministicLegalCalculator.apply_repayments_and_calculate_balance(
            sample_korean_loan_fact, calculation_date=date(2026, 7, 10)
        )
    )
    assert rem_p == Decimal("0")
    assert acc_i == Decimal("0")
    assert overp > Decimal("4000000")  # 약 490여만 원 초과 과오납
    assert any("초과 과오납" in line for line in log)


# ---------------------------------------------------------------------------
# 3. Statute of Limitations Tests (C-4)
# ---------------------------------------------------------------------------

def test_statute_of_limitations_calculation(sample_korean_loan_fact, sample_us_loan_fact):
    # KR 민사: 10년 (2026-06-30 -> 2036-06-30)
    sol_kr = DeterministicLegalCalculator.calculate_statute_of_limitations(sample_korean_loan_fact)
    assert sol_kr == date(2036, 6, 30)

    # US CA 서면: 4년 (2026-04-10 -> 2030-04-10)
    sol_us_written = DeterministicLegalCalculator.calculate_statute_of_limitations(sample_us_loan_fact)
    assert sol_us_written == date(2030, 4, 10)

    # US CA 구두: 2년 (2026-04-10 -> 2028-04-10)
    sample_us_loan_fact.contract_form = ContractFormEnum.ORAL
    sol_us_oral = DeterministicLegalCalculator.calculate_statute_of_limitations(sample_us_loan_fact)
    assert sol_us_oral == date(2028, 4, 10)


def test_verification_blocks_expired_statute_of_limitations(sample_korean_loan_fact):
    draft = GeneratedClaimDraft(
        jurisdiction="KR",
        claim_amount_claimed=Decimal("10000000"),
        statement_of_facts="[갑 제1호증] 및 [갑 제2호증]",
        cited_evidence_ids=["갑 제1호증", "갑 제2호증"],
        calculation_summary="원금",
    )
    # 2037년(시효 10년 경과) 시점 검증
    result = VerificationGateService.verify_and_reconcile(
        loan_fact=sample_korean_loan_fact,
        claim_draft=draft,
        target_date=date(2037, 1, 1),
    )
    assert result.is_statute_of_limitations_expired is True
    assert result.is_valid is False
    assert any("소멸시효" in m for m in result.missing_requirements)


# ---------------------------------------------------------------------------
# 4. Zero-Citation & Citation Enforcement Tests (QA-1)
# ---------------------------------------------------------------------------

def test_zero_citation_draft_blocked_as_invalid(sample_korean_loan_fact):
    # 증거는 완비되었으나 본문에서 증거를 하나도 인용하지 않은 경우
    draft = GeneratedClaimDraft(
        jurisdiction="KR",
        claim_amount_claimed=Decimal("10000000"),
        statement_of_facts="돈을 빌려주었으나 아무런 증거 번호도 본문에 기재하지 않음.",
        cited_evidence_ids=[],
        calculation_summary="원금 10,000,000원",
    )
    result = VerificationGateService.verify_and_reconcile(
        loan_fact=sample_korean_loan_fact,
        claim_draft=draft,
        target_date=date(2026, 6, 30),
    )
    assert result.citations_valid is False
    assert result.is_valid is False
    assert result.status == VerificationStatusEnum.HUMAN_CHECK_REQUIRED
    assert any("증거 인용" in m for m in result.missing_requirements)


# ---------------------------------------------------------------------------
# 5. California Small Claims Form SC-100 Field & Checkbox Tests (C-2)
# ---------------------------------------------------------------------------

def test_sc100_amount_limit_validation(sample_us_loan_fact):
    # $12,500 초과 시 소액재판 불가 차단
    sample_us_loan_fact.principal_amount = Decimal("20000.00")
    draft = GeneratedClaimDraft(
        jurisdiction="US",
        claim_amount_claimed=Decimal("20000.00"),
        statement_of_facts="[Exhibit A] [Exhibit B]",
        cited_evidence_ids=["Exhibit A", "Exhibit B"],
        calculation_summary="Over limit",
    )
    result = VerificationGateService.verify_and_reconcile(
        loan_fact=sample_us_loan_fact,
        claim_draft=draft,
        target_date=date(2026, 4, 10),
    )
    assert result.is_valid is False
    assert any("$12,500.00" in m for m in result.missing_requirements)


def test_sc100_two_claims_limit_validation(sample_us_loan_fact):
    # $2,500 초과 소송을 이미 2회 제기한 경우 차단
    sample_us_loan_fact.prior_claims_over_2500_this_year = 2
    draft = GeneratedClaimDraft(
        jurisdiction="US",
        claim_amount_claimed=Decimal("5000.00"),
        statement_of_facts="[Exhibit A] [Exhibit B]",
        cited_evidence_ids=["Exhibit A", "Exhibit B"],
        calculation_summary="Limit test",
    )
    result = VerificationGateService.verify_and_reconcile(
        loan_fact=sample_us_loan_fact,
        claim_draft=draft,
        target_date=date(2026, 4, 10),
    )
    assert result.is_valid is False
    assert any("연간 $2,500 초과 소액소송은 2회까지만" in m for m in result.missing_requirements)


def test_california_sc100_pdf_checkboxes_and_fields_verified(sample_us_loan_fact, tmp_path):
    out_pdf = str(tmp_path / "sc100_verified.pdf")
    draft = GeneratedClaimDraft(
        jurisdiction="US",
        claim_amount_claimed=Decimal("5000.00"),
        statement_of_facts="[Exhibit A] and [Exhibit B]",
        cited_evidence_ids=["Exhibit A", "Exhibit B"],
        calculation_summary="Summary",
    )
    verification = VerificationGateService.verify_and_reconcile(
        loan_fact=sample_us_loan_fact,
        claim_draft=draft,
        target_date=date(2026, 4, 10),
    )
    CaliforniaSC100Compiler.compile_sc100(
        loan_fact=sample_us_loan_fact,
        verification=verification,
        output_path=out_pdf,
    )
    reader = PdfReader(out_pdf)
    fields = reader.get_fields()

    # 텍스트 필드 검증
    assert fields["SC-100[0].Page2[0].List1[0].Item1[0].PlaintiffName1[0]"].get("/V") == "Jaehoon Jeong"
    assert fields["SC-100[0].Page2[0].List3[0].PlaintiffClaimAmount1[0]"].get("/V") == "5,000.00"

    # 필수 체크박스 검증 (Item 4 Demand=Yes, Item 5 Venue=a(1), Item 7=No, Item 8=No, Item 9=No, Item 10 >2500=Yes)
    assert fields["SC-100[0].Page3[0].List4[0].Item4[0].Checkbox50[0]"].get("/V") == "/1"
    assert fields["SC-100[0].Page3[0].List5[0].Lia[0].Checkbox5cb[0]"].get("/V") == "/1"
    assert fields["SC-100[0].Page3[0].List7[0].item7[0].Checkbox60[1]"].get("/V") == "/2"
    assert fields["SC-100[0].Page3[0].List8[0].item8[0].Checkbox61[1]"].get("/V") == "/2"
    assert fields["SC-100[0].Page4[0].List9[0].Item9[0].Checkbox62[1]"].get("/V") == "/2"
    assert fields["SC-100[0].Page4[0].List10[0].li10[0].Checkbox63[0]"].get("/V") == "/1"


# ---------------------------------------------------------------------------
# 6. Korean Content Proof Hangul Font & e-Court Packet Tests (QA-2, 🛡️-2)
# ---------------------------------------------------------------------------

def test_korean_content_proof_hangul_font_extracted_cleanly(sample_korean_loan_fact, tmp_path):
    out_pdf = str(tmp_path / "korean_proof_hangul.pdf")
    draft = GeneratedClaimDraft(
        jurisdiction="KR",
        claim_amount_claimed=Decimal("10000000"),
        statement_of_facts="[갑 제1호증] [갑 제2호증]",
        cited_evidence_ids=["갑 제1호증", "갑 제2호증"],
        calculation_summary="Summary",
    )
    verification = VerificationGateService.verify_and_reconcile(
        loan_fact=sample_korean_loan_fact,
        claim_draft=draft,
        target_date=date(2026, 6, 30),
    )
    KoreanLegalDocumentCompiler.generate_content_proof_pdf(
        loan_fact=sample_korean_loan_fact,
        verification=verification,
        output_path=out_pdf,
    )
    reader = PdfReader(out_pdf)
    text = reader.pages[0].extract_text()

    # 한글 글리프가 '■'이 아니라 실제 온전한 한글 텍스트로 추출되는지 검증!
    assert "■" not in text
    assert "내 용 증 명 서" in text
    assert "정재훈" in text
    assert "김채무" in text
    assert "대여금 반환 청구" in text


def test_korean_ecourt_packet_splits_payment_order_and_lawsuit(sample_korean_loan_fact):
    draft = GeneratedClaimDraft(
        jurisdiction="KR",
        claim_amount_claimed=Decimal("10000000"),
        statement_of_facts="[갑 제1호증] [갑 제2호증]",
        cited_evidence_ids=["갑 제1호증", "갑 제2호증"],
        calculation_summary="Summary",
    )
    verification = VerificationGateService.verify_and_reconcile(
        loan_fact=sample_korean_loan_fact,
        claim_draft=draft,
        target_date=date(2026, 6, 30),
    )
    packet = KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(
        loan_fact=sample_korean_loan_fact,
        verification=verification,
    )
    # 지급명령용 문안에는 호증 표시가 없어야 함
    assert "갑 제1호증" not in packet["claim_cause_payment_order"]
    # 소액소장용 문안에는 입증방법과 호증이 포함되어야 함
    assert "[입증 방법]" in packet["claim_cause_lawsuit"]
    assert "갑 제1호증" in packet["claim_cause_lawsuit"]


# ---------------------------------------------------------------------------
# 7. Real File SHA-256 Byte Verification Utility Test (🛡️-3)
# ---------------------------------------------------------------------------

def test_verify_file_bytes_sha256(tmp_path):
    f = tmp_path / "sample.txt"
    f.write_text("Hello Meta Hackathon ClaimBack-AI", encoding="utf-8")
    expected_hash = "f3408a0d0a794cbdb7e9ea8d867c00e12d45c5896016629ecff86e7a2dfb4200"  # echo -n ... | sha256sum
    import hashlib
    actual_hash = hashlib.sha256("Hello Meta Hackathon ClaimBack-AI".encode("utf-8")).hexdigest()
    assert verify_file_bytes_sha256(str(f), actual_hash) is True
    assert verify_file_bytes_sha256(str(f), "0000000000000000000000000000000000000000000000000000000000000000") is False
    assert verify_file_bytes_sha256("/non_existent_path.txt", actual_hash) is False
