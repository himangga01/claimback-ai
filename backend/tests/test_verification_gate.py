import os
import pytest
from datetime import date, timedelta
from decimal import Decimal

from app.schemas.loan_fact import (
    LoanFactSchema,
    PartyInfo,
    EvidenceItem,
    RepaymentRecord,
    GeneratedClaimDraft,
    CurrencyEnum,
    EvidenceTypeEnum,
    VerificationStatusEnum,
)
from app.services.verification_gate import (
    DeterministicLegalCalculator,
    VerificationGateService,
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
        principal_amount=Decimal("10000000"),  # 1,000만 원
        loan_date=date(2026, 1, 1),
        due_date=date(2026, 6, 30),
        statutory_interest_rate=Decimal("12.0"),  # 소촉법 연 12%
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
        principal_amount=Decimal("5000.00"),  # $5,000
        loan_date=date(2026, 1, 10),
        due_date=date(2026, 4, 10),
        statutory_interest_rate=Decimal("10.0"),  # Cal. Civ. Code 10%
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
# 1. Deterministic Legal Calculator Tests
# ---------------------------------------------------------------------------

def test_interest_calculation_zero_if_before_due():
    principal = Decimal("10000000")
    start = date(2026, 1, 1)
    end = date(2026, 1, 1)
    interest = DeterministicLegalCalculator.calculate_statutory_interest(
        principal, start, end, Decimal("12.0")
    )
    assert interest == Decimal("0.00")


def test_interest_calculation_precision_korea():
    principal = Decimal("10000000")
    start = date(2026, 1, 1)
    end = date(2026, 12, 31)  # 364 days
    interest = DeterministicLegalCalculator.calculate_statutory_interest(
        principal, start, end, Decimal("12.0")
    )
    # 10,000,000 * 0.12 * (364 / 365) = 1,196,712.328... -> 1,196,712.33
    expected = Decimal("1196712.33")
    assert interest == expected


def test_interest_calculation_us_california_exact_10_percent():
    principal = Decimal("5000.00")
    start = date(2026, 1, 1)
    end = date(2026, 1, 1) + timedelta(days=365)  # Exactly 1 year
    interest = DeterministicLegalCalculator.calculate_statutory_interest(
        principal, start, end, Decimal("10.0")
    )
    # 5,000 * 0.10 * (365 / 365) = 500.00
    assert interest == Decimal("500.00")


def test_repayment_allocation_interest_before_principal(sample_korean_loan_fact):
    # 변제기(2026-06-30) 이후 2026-08-01에 200만 원 일부변제
    calc_date = date(2026, 10, 31)
    rep_date = date(2026, 8, 1)  # 32 days after due date
    
    sample_korean_loan_fact.repayments.append(
        RepaymentRecord(payment_date=rep_date, amount=Decimal("2000000"))
    )

    remaining_p, accrued_i, log = (
        DeterministicLegalCalculator.apply_repayments_and_calculate_balance(
            sample_korean_loan_fact, calculation_date=calc_date
        )
    )

    assert remaining_p < Decimal("10000000")
    assert accrued_i > Decimal("0")
    assert any("변제액" in line for line in log)


def test_multiple_partial_repayments_chronological(sample_korean_loan_fact):
    # 2회 분할 변제
    calc_date = date(2026, 12, 31)
    sample_korean_loan_fact.repayments = [
        RepaymentRecord(payment_date=date(2026, 9, 1), amount=Decimal("3000000")),
        RepaymentRecord(payment_date=date(2026, 11, 1), amount=Decimal("4000000")),
    ]
    rem_p, acc_i, log = DeterministicLegalCalculator.apply_repayments_and_calculate_balance(
        sample_korean_loan_fact, calculation_date=calc_date
    )
    # 1,000만 원에서 총 700만 원 상당 변제 (이자 우선 충당 후 원금 차감)
    assert rem_p < Decimal("4000000")
    assert rem_p > Decimal("2000000")
    assert len(log) >= 4


def test_agreed_interest_rate_capped_at_20_percent():
    fact = LoanFactSchema(
        creditor=PartyInfo(name="A"),
        debtor=PartyInfo(name="B"),
        currency=CurrencyEnum.KRW,
        principal_amount=Decimal("1000000"),
        loan_date=date(2026, 1, 1),
        due_date=date(2026, 3, 1),
        agreed_interest_rate=Decimal("20.0"),  # 한도 20%
    )
    rem_p, acc_i, log = DeterministicLegalCalculator.apply_repayments_and_calculate_balance(
        fact, calculation_date=date(2026, 4, 1)
    )
    assert any("20.0%" in line for line in log)


def test_agreed_interest_rate_exceeding_cap_rejected():
    with pytest.raises(ValueError):
        LoanFactSchema(
            creditor=PartyInfo(name="A"),
            debtor=PartyInfo(name="B"),
            currency=CurrencyEnum.KRW,
            principal_amount=Decimal("1000000"),
            loan_date=date(2026, 1, 1),
            due_date=date(2026, 3, 1),
            agreed_interest_rate=Decimal("25.0"),  # 20% 초과 금지
        )


def test_due_date_before_loan_date_rejected():
    with pytest.raises(ValueError):
        LoanFactSchema(
            creditor=PartyInfo(name="A"),
            debtor=PartyInfo(name="B"),
            currency=CurrencyEnum.KRW,
            principal_amount=Decimal("1000000"),
            loan_date=date(2026, 5, 1),
            due_date=date(2026, 4, 1),  # 대여일 이전 변제기 금지
        )


# ---------------------------------------------------------------------------
# 2. Verification Gate Service Tests
# ---------------------------------------------------------------------------

def test_verification_pass_korean_clean(sample_korean_loan_fact):
    draft = GeneratedClaimDraft(
        jurisdiction="KR",
        claim_amount_claimed=Decimal("10000000"),
        statement_of_facts="채무자는 [갑 제1호증]에 의해 대여받았으며 [갑 제2호증]으로 변제 약정함.",
        cited_evidence_ids=["갑 제1호증", "갑 제2호증"],
        calculation_summary="원금 10,000,000원",
    )
    result = VerificationGateService.verify_and_reconcile(
        loan_fact=sample_korean_loan_fact,
        claim_draft=draft,
        target_date=date(2026, 6, 30),  # 변제기 당일 (이자 0)
    )
    assert result.status == VerificationStatusEnum.PASS
    assert result.is_valid is True
    assert result.reconciled_amount == Decimal("10000000")
    assert result.citations_valid is True


def test_verification_tampering_reconciliation(sample_korean_loan_fact):
    # LLM이 1,200만 원으로 수치 할루시네이션(위변조)을 일으킨 경우
    draft = GeneratedClaimDraft(
        jurisdiction="KR",
        claim_amount_claimed=Decimal("12000000"),  # 할루시네이션!
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
    assert result.reconciled_amount == Decimal("10000000")  # 원본 증거 기준으로 복원됨!
    assert len(result.tampering_reconciliations) == 1


def test_verification_blocks_missing_transfer_evidence(sample_korean_loan_fact):
    # 이체확인증 증거를 제거
    sample_korean_loan_fact.evidences = [
        e for e in sample_korean_loan_fact.evidences 
        if e.evidence_type != EvidenceTypeEnum.TRANSFER_RECEIPT
    ]
    draft = GeneratedClaimDraft(
        jurisdiction="KR",
        claim_amount_claimed=Decimal("10000000"),
        statement_of_facts="[갑 제2호증] 대화록만 있음.",
        cited_evidence_ids=["갑 제2호증"],
        calculation_summary="원금 10,000,000원",
    )
    result = VerificationGateService.verify_and_reconcile(
        loan_fact=sample_korean_loan_fact,
        claim_draft=draft,
        target_date=date(2026, 7, 1),
    )
    assert result.status == VerificationStatusEnum.HUMAN_CHECK_REQUIRED
    assert result.is_valid is False
    assert any("이체 증빙" in m for m in result.missing_requirements)


def test_verification_blocks_future_due_date(sample_korean_loan_fact):
    # 변제기가 미래인 경우
    draft = GeneratedClaimDraft(
        jurisdiction="KR",
        claim_amount_claimed=Decimal("10000000"),
        statement_of_facts="[갑 제1호증], [갑 제2호증]",
        cited_evidence_ids=["갑 제1호증", "갑 제2호증"],
        calculation_summary="원금",
    )
    result = VerificationGateService.verify_and_reconcile(
        loan_fact=sample_korean_loan_fact,
        claim_draft=draft,
        target_date=date(2026, 5, 1),  # 변제기(6/30) 이전!
    )
    assert result.is_valid is False
    assert any("변제기" in m for m in result.missing_requirements)


def test_verification_blocks_hallucinated_citations(sample_korean_loan_fact):
    # 본문에 없는 허구의 증거 [갑 제99호증] 인용
    draft = GeneratedClaimDraft(
        jurisdiction="KR",
        claim_amount_claimed=Decimal("10000000"),
        statement_of_facts="[갑 제1호증]과 허구의 [갑 제99호증]에 의하여 입증됨.",
        cited_evidence_ids=["갑 제1호증", "갑 제99호증"],
        calculation_summary="원금",
    )
    result = VerificationGateService.verify_and_reconcile(
        loan_fact=sample_korean_loan_fact,
        claim_draft=draft,
        target_date=date(2026, 7, 1),
    )
    assert result.citations_valid is False
    assert result.is_valid is False
    assert any("갑 제99호증" in m for m in result.missing_requirements)


def test_us_verification_pass_clean(sample_us_loan_fact):
    draft = GeneratedClaimDraft(
        jurisdiction="US",
        claim_amount_claimed=Decimal("5000.00"),
        statement_of_facts="[Exhibit A] wire receipt and [Exhibit B] admission.",
        cited_evidence_ids=["Exhibit A", "Exhibit B"],
        calculation_summary="Principal: $5,000",
    )
    result = VerificationGateService.verify_and_reconcile(
        loan_fact=sample_us_loan_fact,
        claim_draft=draft,
        target_date=date(2026, 4, 10),
    )
    assert result.status == VerificationStatusEnum.PASS
    assert result.is_valid is True
    assert result.reconciled_amount == Decimal("5000.00")


# ---------------------------------------------------------------------------
# 3. Document Compiler Tests
# ---------------------------------------------------------------------------

def test_california_sc100_pdf_generation(sample_us_loan_fact, tmp_path):
    out_pdf = str(tmp_path / "sc100_output.pdf")
    draft = GeneratedClaimDraft(
        jurisdiction="US",
        claim_amount_claimed=Decimal("5000.00"),
        statement_of_facts="Personal loan of $5,000 [Exhibit A] and promised repayment [Exhibit B].",
        cited_evidence_ids=["Exhibit A", "Exhibit B"],
        calculation_summary="Principal: $5,000",
    )
    verification = VerificationGateService.verify_and_reconcile(
        loan_fact=sample_us_loan_fact,
        claim_draft=draft,
        target_date=date(2026, 10, 10),
    )
    compiled_path = CaliforniaSC100Compiler.compile_sc100(
        loan_fact=sample_us_loan_fact,
        verification=verification,
        output_path=out_pdf,
    )
    assert os.path.exists(compiled_path)
    assert os.path.getsize(compiled_path) > 100000


def test_korean_content_proof_pdf_generation(sample_korean_loan_fact, tmp_path):
    out_pdf = str(tmp_path / "korean_proof.pdf")
    draft = GeneratedClaimDraft(
        jurisdiction="KR",
        claim_amount_claimed=Decimal("10000000"),
        statement_of_facts="[갑 제1호증] 및 [갑 제2호증]",
        cited_evidence_ids=["갑 제1호증", "갑 제2호증"],
        calculation_summary="원금 10,000,000원",
    )
    verification = VerificationGateService.verify_and_reconcile(
        loan_fact=sample_korean_loan_fact,
        claim_draft=draft,
        target_date=date(2026, 10, 31),
    )
    compiled_path = KoreanLegalDocumentCompiler.generate_content_proof_pdf(
        loan_fact=sample_korean_loan_fact,
        verification=verification,
        output_path=out_pdf,
    )
    assert os.path.exists(compiled_path)
    assert os.path.getsize(compiled_path) > 1000


def test_korean_ecourt_clipboard_packet(sample_korean_loan_fact):
    draft = GeneratedClaimDraft(
        jurisdiction="KR",
        claim_amount_claimed=Decimal("10000000"),
        statement_of_facts="[갑 제1호증] 및 [갑 제2호증]",
        cited_evidence_ids=["갑 제1호증", "갑 제2호증"],
        calculation_summary="원금 10,000,000원",
    )
    verification = VerificationGateService.verify_and_reconcile(
        loan_fact=sample_korean_loan_fact,
        claim_draft=draft,
        target_date=date(2026, 10, 31),
    )
    packet = KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(
        loan_fact=sample_korean_loan_fact,
        verification=verification,
    )
    assert "채권자(원고): 정재훈" in packet["parties"]
    assert "채무자(피고): 김채무" in packet["parties"]
    assert "지급을 구함" in packet["claim_purpose"] or "명령을 구함" in packet["claim_purpose"]
    assert "10,000,000" in packet["principal_amount"]
