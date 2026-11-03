from datetime import date
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
    TransactionKindEnum,
)
from app.services.verification_gate import calculate_kr, VerificationGateService


def _base_fact(
    principal="5000000",
    loan=(2026, 3, 10),
    due=(2026, 4, 10),
    agreed=None,
    kind=TransactionKindEnum.CIVIL,
    repayments=None,
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


def test_fixed_example_4014383_remaining_accrual_and_sentence():
    fact = _base_fact(
        repayments=[RepaymentRecord(payment_date=date(2026, 5, 1), amount=Decimal("1000000"))]
    )
    calc = calculate_kr(fact, date(2026, 5, 1))
    assert calc.remaining_principal == Decimal("4014383")
    assert calc.accrual_start_date == date(2026, 5, 2)
    assert calc.rate_clause.pre_service_rate == Decimal("5.0")
    assert calc.rate_clause.post_service_rate == Decimal("12.0")
    assert calc.rate_clause.sentence == (
        "채무자는 채권자에게 4,014,383원 및 이에 대하여 2026. 5. 2.부터 "
        "이 사건 지급명령 정본 송달일까지는 연 5%, 그 다음 날부터 다 갚는 날까지는 "
        "연 12%의 각 비율로 계산한 돈을 지급하라."
    )
    assert len(calc.allocations) == 1
    assert calc.allocations[0].applied_to_interest == Decimal("14383")
    assert calc.allocations[0].applied_to_principal == Decimal("985617")
    assert any("지연손해금" in s.label for s in calc.calculation_steps)


def test_fixed_example_commercial_4017260():
    fact = _base_fact(
        kind=TransactionKindEnum.COMMERCIAL,
        repayments=[RepaymentRecord(payment_date=date(2026, 5, 1), amount=Decimal("1000000"))],
    )
    calc = calculate_kr(fact, date(2026, 5, 1))
    assert calc.remaining_principal == Decimal("4017260")
    assert calc.accrual_start_date == date(2026, 5, 2)
    assert calc.allocations[0].applied_to_interest == Decimal("17260")


def test_fixed_example_agreed12_single_rate_sentence():
    fact = _base_fact(
        agreed="12",
        repayments=[RepaymentRecord(payment_date=date(2026, 5, 1), amount=Decimal("1000000"))],
    )
    calc = calculate_kr(fact, date(2026, 5, 1))
    assert calc.remaining_principal == Decimal("4085479")
    assert calc.accrual_start_date == date(2026, 5, 2)
    assert calc.rate_clause.sentence == (
        "채무자는 채권자에게 4,085,479원 및 이에 대하여 2026. 5. 2.부터 "
        "다 갚는 날까지 연 12%의 비율로 계산한 돈을 지급하라."
    )
    assert calc.allocations[0].applied_to_interest == Decimal("85479")


def test_fixed_example_agreed24_capped_to_20_with_warning():
    fact = _base_fact(
        agreed="24",
        repayments=[RepaymentRecord(payment_date=date(2026, 5, 1), amount=Decimal("1000000"))],
    )
    calc = calculate_kr(fact, date(2026, 5, 1))
    assert calc.remaining_principal == Decimal("4142465")
    assert calc.accrual_start_date == date(2026, 5, 2)
    assert len(calc.warnings) == 1
    assert "연 20%로 계산" in calc.warnings[0]
    assert "약정 이율" in calc.warnings[0]
    assert calc.allocations[0].applied_to_interest == Decimal("142465")


def test_fixed_example_no_repayment_reference_total():
    fact = _base_fact()
    calc = calculate_kr(fact, date(2026, 6, 1))
    assert calc.remaining_principal == Decimal("5000000")
    assert calc.accrual_start_date == date(2026, 4, 11)
    assert calc.reference_total.as_of == date(2026, 6, 1)
    assert calc.reference_total.amount == Decimal("5035616")


def test_unsupported_small_repayment_hold():
    fact = _base_fact(
        repayments=[RepaymentRecord(payment_date=date(2026, 5, 1), amount=Decimal("10000"))]
    )
    calc = calculate_kr(fact, date(2026, 5, 1))
    assert calc.rate_clause.sentence == ""
    assert "repayments" in calc.missing_fields
    res = VerificationGateService.verify_and_reconcile(
        fact, _draft_for("5000000"), target_date=date(2026, 5, 1)
    )
    assert res.is_valid is False
    assert res.status == VerificationStatusEnum.HUMAN_CHECK_REQUIRED
    assert any("이자보다 적은 변제" in m for m in res.missing_requirements)


def test_g4_kr_over_30m_warns_without_hold():
    fact = _base_fact(principal="35000000")
    res = VerificationGateService.verify_and_reconcile(
        fact, _draft_for("35000000"), target_date=date(2026, 6, 1)
    )
    assert res.is_valid is True
    assert res.status == VerificationStatusEnum.PASS
    assert res.calculation is not None
    assert res.calculation.limit_check is not None
    assert res.calculation.limit_check.exceeded is True
    assert any("소액사건 기준 금액" in w for w in res.calculation.warnings)


def test_g2_role_loan_transfer_selection():
    fact = _base_fact()
    fact.evidences = [
        EvidenceItem(
            id="갑 제1호증",
            title="변제 이체증",
            evidence_type=EvidenceTypeEnum.TRANSFER_RECEIPT,
            sha256_hash="a" * 64,
            source_filename="f.txt",
            extracted_amount=Decimal("1000000"),
            role="repayment",
        ),
        EvidenceItem(
            id="갑 제2호증",
            title="대여 이체증",
            evidence_type=EvidenceTypeEnum.TRANSFER_RECEIPT,
            sha256_hash="b" * 64,
            source_filename="f2.txt",
            extracted_amount=Decimal("5000000"),
            role="loan_transfer",
        ),
        EvidenceItem(
            id="갑 제3호증",
            title="대화록",
            evidence_type=EvidenceTypeEnum.MESSENGER_CHAT,
            sha256_hash="c" * 64,
            source_filename="f3.txt",
        ),
    ]
    draft = GeneratedClaimDraft(
        jurisdiction="KR",
        claim_amount_claimed=Decimal("5000000"),
        statement_of_facts="[갑 제1호증] [갑 제3호증]",
        cited_evidence_ids=["갑 제1호증", "갑 제3호증"],
        calculation_summary="Summary",
    )
    res = VerificationGateService.verify_and_reconcile(
        fact, draft, target_date=date(2026, 6, 1)
    )
    assert res.is_valid is True
    assert not any("이체증빙 추출액" in m for m in res.missing_requirements)


def test_g2_role_only_repayment_missing_transfer():
    fact = _base_fact()
    fact.evidences = [
        EvidenceItem(
            id="갑 제1호증",
            title="변제 이체증",
            evidence_type=EvidenceTypeEnum.TRANSFER_RECEIPT,
            sha256_hash="a" * 64,
            source_filename="f.txt",
            extracted_amount=Decimal("1000000"),
            role="repayment",
        ),
        EvidenceItem(
            id="갑 제2호증",
            title="대화록",
            evidence_type=EvidenceTypeEnum.MESSENGER_CHAT,
            sha256_hash="b" * 64,
            source_filename="f2.txt",
        ),
    ]
    res = VerificationGateService.verify_and_reconcile(
        fact, _draft_for("5000000"), target_date=date(2026, 6, 1)
    )
    assert res.is_valid is False
    assert any("이체 내역" in m for m in res.missing_requirements)


def test_r4_reference_total_match_passes():
    fact = _base_fact()
    calc = calculate_kr(fact, date(2026, 6, 1))
    ref = calc.reference_total.amount
    assert ref == Decimal("5035616")
    res = VerificationGateService.verify_and_reconcile(
        fact, _draft_for(str(ref)), target_date=date(2026, 6, 1)
    )
    assert res.is_valid is True
    assert res.status == VerificationStatusEnum.PASS


def test_due_date_after_target_hold_message():
    fact = _base_fact()
    res = VerificationGateService.verify_and_reconcile(
        fact, _draft_for("5000000"), target_date=date(2026, 3, 1)
    )
    assert res.is_valid is False
    assert any("기준일" in m and "변제기" in m for m in res.missing_requirements)
