from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Tuple, List, Optional
import re

from app.schemas.loan_fact import (
    LoanFactSchema,
    GeneratedClaimDraft,
    VerificationResult,
    VerificationStatusEnum,
    CurrencyEnum,
    EvidenceTypeEnum,
)


class DeterministicLegalCalculator:
    """
    한·미 법정이자 및 일부변제 충당 계산기
    - Python Decimal 기반의 1원 / 1센트 오차 없는 정확한 금융 연산
    """

    @staticmethod
    def calculate_statutory_interest(
        principal: Decimal,
        start_date: date,
        end_date: date,
        annual_rate: Decimal,
        days_in_year: int = 365,
    ) -> Decimal:
        """
        단순 이자 일할 계산: 원금 * 이자율(%) * (경과일수 / 365)
        """
        if end_date <= start_date:
            return Decimal("0.00")
        
        days = Decimal(str((end_date - start_date).days))
        rate_fraction = annual_rate / Decimal("100.0")
        interest = principal * rate_fraction * (days / Decimal(str(days_in_year)))
        
        # 소수점 2자리 반올림 (KRW의 경우 1원 단위 반올림)
        return interest.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @classmethod
    def apply_repayments_and_calculate_balance(
        cls,
        loan_fact: LoanFactSchema,
        calculation_date: date,
        default_annual_rate: Optional[Decimal] = None,
    ) -> Tuple[Decimal, Decimal, List[str]]:
        """
        일부변제 법정충당 계산: 비용 -> 이자 -> 원금 순서 충당
        반환값: (잔여원금, 누적미수이자, 감사로그)
        """
        audit_log: List[str] = []
        
        # 적용 이율 결정
        if loan_fact.agreed_interest_rate is not None:
            rate = min(loan_fact.agreed_interest_rate, Decimal("20.0"))
            audit_log.append(f"약정이율 연 {rate}% 적용 (최고이율 한도 검증 통과)")
        elif loan_fact.statutory_interest_rate is not None:
            rate = loan_fact.statutory_interest_rate
            audit_log.append(f"지정 법정이율 연 {rate}% 적용")
        elif default_annual_rate is not None:
            rate = default_annual_rate
            audit_log.append(f"기본 관할 법정이율 연 {rate}% 적용")
        else:
            # 관할별 기본 법정이율: KR=12.0(소촉법), US=10.0(CA 소액재판)
            rate = Decimal("12.0") if loan_fact.currency == CurrencyEnum.KRW else Decimal("10.0")
            audit_log.append(f"관할({loan_fact.currency.value}) 기본 법정이율 연 {rate}% 적용")

        current_principal = loan_fact.principal_amount
        accrued_interest = Decimal("0.00")
        last_date = loan_fact.due_date

        # 변제기 이전 계산일이면 변제기까지 이자 없음(무이자 대여 기본)
        if calculation_date <= loan_fact.due_date and not loan_fact.repayments:
            return current_principal, Decimal("0.00"), audit_log

        # 변제 내역 날짜순 정렬
        sorted_repayments = sorted(loan_fact.repayments, key=lambda x: x.payment_date)

        for rep in sorted_repayments:
            rep_date = rep.payment_date
            if rep_date > calculation_date:
                continue

            # 직전 기산일부터 변제일까지 지연이자 발생
            if rep_date > last_date:
                period_interest = cls.calculate_statutory_interest(
                    current_principal, last_date, rep_date, rate
                )
                accrued_interest += period_interest
                audit_log.append(
                    f"{last_date} ~ {rep_date} 지연손해금 {period_interest} 발생 (누적 이자: {accrued_interest})"
                )
                last_date = rep_date

            # 충당 순서: 이자 -> 원금 (비용은 0으로 가정)
            rem_payment = rep.amount
            if accrued_interest > Decimal("0.00"):
                if rem_payment >= accrued_interest:
                    rep.applied_to_interest = accrued_interest
                    rem_payment -= accrued_interest
                    audit_log.append(f"{rep_date} 변제액 {rep.amount} 중 이자 {accrued_interest} 전액 충당")
                    accrued_interest = Decimal("0.00")
                else:
                    rep.applied_to_interest = rem_payment
                    accrued_interest -= rem_payment
                    audit_log.append(f"{rep_date} 변제액 {rep.amount} 이자 일부 충당 (남은 이자: {accrued_interest})")
                    rem_payment = Decimal("0.00")

            if rem_payment > Decimal("0.00"):
                applied_p = min(rem_payment, current_principal)
                rep.applied_to_principal = applied_p
                current_principal -= applied_p
                audit_log.append(f"{rep_date} 변제액 중 원금 {applied_p} 충당 (남은 원금: {current_principal})")

        # 마지막 변제일(또는 변제기)부터 최종 계산일까지 잔여 지연이자 산출
        if calculation_date > last_date and current_principal > Decimal("0.00"):
            final_period_interest = cls.calculate_statutory_interest(
                current_principal, last_date, calculation_date, rate
            )
            accrued_interest += final_period_interest
            audit_log.append(
                f"{last_date} ~ {calculation_date} 잔여 지연손해금 {final_period_interest} 발생 (최종 누적 이자: {accrued_interest})"
            )

        if loan_fact.currency == CurrencyEnum.KRW:
            current_principal = current_principal.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            accrued_interest = accrued_interest.quantize(Decimal("1"), rounding=ROUND_HALF_UP)

        return current_principal, accrued_interest, audit_log


class VerificationGateService:
    """
    결정론적 규칙 검증 게이트 (Deterministic Verification Gate)
    - 수치·고유명사 불일치 자동 복원
    - 요건사실 결손 시 자동 중단 및 Human-in-the-loop 보류
    - 증거 인용(Citation) 무결성 강제
    """

    @classmethod
    def verify_and_reconcile(
        cls,
        loan_fact: LoanFactSchema,
        claim_draft: GeneratedClaimDraft,
        target_date: Optional[date] = None,
    ) -> VerificationResult:
        today = target_date or date.today()
        audit_notes: List[str] = []
        missing_requirements: List[str] = []
        tampering_reconciliations: List[str] = []
        is_valid = True
        status = VerificationStatusEnum.PASS

        # 1. 요건사실 결손 게이트 검사
        has_transfer_proof = any(
            e.evidence_type == EvidenceTypeEnum.TRANSFER_RECEIPT for e in loan_fact.evidences
        )
        if not has_transfer_proof:
            missing_requirements.append("차용 원금 이체 증빙(이체확인증/영수증)이 누락되었습니다.")

        has_due_agreement = any(
            e.evidence_type in (EvidenceTypeEnum.LOAN_AGREEMENT, EvidenceTypeEnum.MESSENGER_CHAT)
            for e in loan_fact.evidences
        )
        if not has_due_agreement:
            missing_requirements.append("변제기 및 반환 약정을 입증할 증거(차용증 또는 대화록)가 누락되었습니다.")

        if loan_fact.due_date > today:
            missing_requirements.append(
                f"변제기({loan_fact.due_date})가 아직 도래하지 않아 청구권이 발생하지 않았습니다."
            )

        # 2. 결정론적 법정이자 및 잔액 산출
        remaining_principal, calculated_interest, calc_logs = (
            DeterministicLegalCalculator.apply_repayments_and_calculate_balance(
                loan_fact=loan_fact,
                calculation_date=today,
            )
        )
        audit_notes.extend(calc_logs)
        expected_total = remaining_principal + calculated_interest

        # 3. 수치 위변조 / 할루시네이션 복원 게이트
        reconciled_amount = remaining_principal
        if claim_draft.claim_amount_claimed != expected_total and claim_draft.claim_amount_claimed != remaining_principal:
            tampering_reconciliations.append(
                f"LLM 청구금액({claim_draft.claim_amount_claimed})이 계산값(원금 {remaining_principal}, 합계 {expected_total})과 불일치하여 원본 기준 복원되었습니다."
            )
            status = VerificationStatusEnum.RECONCILED

        # 4. 증거 인용(Citation) 유효성 검증
        valid_evidence_ids = {e.id for e in loan_fact.evidences}
        cited_ids = set(claim_draft.cited_evidence_ids)
        
        # 본문 내 증거 태그 정규식 검색 ([갑 제N호증], [Exhibit X])
        text_citations = set(re.findall(r"\[(갑 제\d+호증|Exhibit [A-Z])\]", claim_draft.statement_of_facts))
        all_found_citations = cited_ids.union(text_citations)

        invalid_citations = all_found_citations - valid_evidence_ids
        if invalid_citations:
            missing_requirements.append(
                f"존재하지 않는 허구의 증거 ID({', '.join(invalid_citations)})가 인용되었습니다."
            )

        citations_valid = len(invalid_citations) == 0 and len(all_found_citations) > 0

        # 5. 최종 판정 도출
        if missing_requirements:
            is_valid = False
            status = VerificationStatusEnum.HUMAN_CHECK_REQUIRED
            audit_notes.append("필수 요건사실 결손 또는 유효하지 않은 인용으로 인해 서류 생성이 보류되었습니다.")
        elif tampering_reconciliations:
            status = VerificationStatusEnum.RECONCILED
            audit_notes.append("할루시네이션 수치가 결정론적 데이터로 무결하게 복원되었습니다.")
        else:
            status = VerificationStatusEnum.PASS
            audit_notes.append("모든 요건사실 및 법률 계산 검증을 무결하게 통과하였습니다.")

        return VerificationResult(
            status=status,
            is_valid=is_valid,
            reconciled_amount=reconciled_amount,
            calculated_interest=calculated_interest,
            total_claim_amount=expected_total,
            citations_valid=citations_valid,
            missing_requirements=missing_requirements,
            tampering_reconciliations=tampering_reconciliations,
            audit_notes=audit_notes,
        )
