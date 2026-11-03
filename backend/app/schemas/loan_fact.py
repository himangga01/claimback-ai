from datetime import date
from decimal import Decimal
from enum import Enum
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator


class CurrencyEnum(str, Enum):
    KRW = "KRW"
    USD = "USD"


class TransactionKindEnum(str, Enum):
    CIVIL = "civil"            # 민사 대여금 (연 5%, 송달 후 12%)
    COMMERCIAL = "commercial"  # 상사 대여금 (연 6%, 송달 후 12%)


class ContractFormEnum(str, Enum):
    WRITTEN = "written"        # 서면/차용증 계약
    ORAL = "oral"              # 구두/메신저 약속


class EvidenceTypeEnum(str, Enum):
    TRANSFER_RECEIPT = "transfer_receipt"      # 이체확인증
    MESSENGER_CHAT = "messenger_chat"          # 메신저 대화 캡처/영상
    LOAN_AGREEMENT = "loan_agreement"          # 차용증/계약서
    DEMAND_NOTICE = "demand_notice"            # 독촉장/내용증명


class VerificationStatusEnum(str, Enum):
    PASS = "PASS"
    RECONCILED = "RECONCILED"                  # 초안 금액과 계산값이 다름(이전 상태, 하위 호환용)
    HUMAN_CHECK_REQUIRED = "HUMAN_CHECK_REQUIRED"  # 확인할 칸이 비어 보류


class PartyInfo(BaseModel):
    name: str = Field(..., description="이름/상호")
    phone: Optional[str] = Field(None, description="연락처")
    address: Optional[str] = Field(None, description="주소")
    city: Optional[str] = Field(None, description="시/군/구")
    state: Optional[str] = Field(None, description="도/주 (예: CA, 경기)")
    zip_code: Optional[str] = Field(None, description="우편번호")
    id_number_masked: Optional[str] = Field(None, description="마스킹된 식별번호(주민번호/SSN)")


class RepaymentRecord(BaseModel):
    payment_date: date = Field(..., description="변제일")
    amount: Decimal = Field(..., gt=0, description="변제금액")
    currency: Optional[CurrencyEnum] = Field(None, description="변제 통화")
    evidence_id: Optional[str] = Field(None, description="변제 증거 ID")
    applied_to_cost: Decimal = Field(default=Decimal("0.00"), description="비용 충당액")
    applied_to_interest: Decimal = Field(default=Decimal("0.00"), description="이자 충당액")
    applied_to_principal: Decimal = Field(default=Decimal("0.00"), description="원금 충당액")


class EvidenceItem(BaseModel):
    id: str = Field(..., description="증거 식별자 (예: 갑 제1호증 / Exhibit A)")
    title: str = Field(..., description="증거 명칭")
    evidence_type: EvidenceTypeEnum = Field(..., description="증거 유형")
    sha256_hash: str = Field(..., min_length=64, max_length=64, description="SHA-256 해시값")
    source_filename: str = Field(..., description="원본 파일명")
    extracted_amount: Optional[Decimal] = Field(None, description="증거상 추출된 금액")
    currency: Optional[CurrencyEnum] = Field(None, description="추출 통화")
    extracted_date: Optional[date] = Field(None, description="증거상 추출된 일자")
    extracted_parties: List[str] = Field(default_factory=list, description="언급된 당사자 목록")
    raw_ocr_snippet: Optional[str] = Field(None, description="핵심 OCR 텍스트 스니펫")
    role: Optional[Literal["loan_transfer", "repayment", "other"]] = Field(
        default=None, description="사용자가 확인한 증거 역할"
    )


class LoanFactSchema(BaseModel):
    """
    금전소비대차 입력값 구조화 스키마
    - 대여사실 (원금, 대여일자, 이체증빙)
    - 반환약정 / 변제기 (변제기 일자)
    - 지연손해금 기산 (송달일 및 관할/거래유형별 2단계 이율 분리)
    """
    creditor: PartyInfo = Field(..., description="채권자 (Plaintiff)")
    debtor: PartyInfo = Field(..., description="채무자 (Defendant)")

    currency: CurrencyEnum = Field(default=CurrencyEnum.KRW, description="통화")
    transaction_kind: TransactionKindEnum = Field(
        default=TransactionKindEnum.CIVIL,
        description="거래 성격 (민사 대여금 또는 상사 거래)"
    )
    contract_form: ContractFormEnum = Field(
        default=ContractFormEnum.WRITTEN,
        description="계약 형식 (서면 계약 또는 구두/메신저 약속)"
    )

    principal_amount: Decimal = Field(..., gt=0, description="대여 원금")
    loan_date: date = Field(..., description="대여일 / 송금일")
    due_date: date = Field(..., description="변제기 (Due Date)")

    service_date: Optional[date] = Field(
        None,
        description="소장부본/지급명령정본 송달일 (연 12% 기산점)"
    )

    agreed_interest_rate: Optional[Decimal] = Field(
        default=None, ge=0, le=Decimal("100.0"),
        description="약정이율 (연 %, 20% 초과 입력은 20%로 계산하고 경고)"
    )
    statutory_interest_rate: Optional[Decimal] = Field(
        default=None, ge=0, le=Decimal("20.0"),
        description="법정이율 (연 %, 법정 최고이율 연 20% 한도)"
    )

    prior_claims_over_2500_this_year: int = Field(
        default=0, ge=0,
        description="캘리포니아 소액재판에서 당해 연도 $2,500 초과 소송 제기 횟수 (연 2회 한도)"
    )

    repayments: List[RepaymentRecord] = Field(default_factory=list, description="일부 변제 내역")
    demand_date: Optional[date] = Field(None, description="사전 독촉일 / 내용증명 발송일")

    evidences: List[EvidenceItem] = Field(default_factory=list, description="연계 증거 목록")

    @field_validator("due_date")
    @classmethod
    def validate_due_date(cls, v: date, info):
        loan_date = info.data.get("loan_date")
        if loan_date and v < loan_date:
            raise ValueError("변제기는 대여일 이후여야 합니다.")
        return v


class GeneratedClaimDraft(BaseModel):
    """청구 문서 초안"""
    jurisdiction: str = Field(..., description="KR 또는 US")
    claim_amount_claimed: Decimal = Field(..., description="청구 원금/합계")
    statement_of_facts: str = Field(..., description="청구원인 본문")
    cited_evidence_ids: List[str] = Field(default_factory=list, description="인용된 증거 ID 목록")
    calculation_summary: str = Field(..., description="원리금 계산 근거 설명")


class CalculationStep(BaseModel):
    """화면 표시용 계산 단계"""
    label: str = Field(..., description="단계 이름")
    formula: str = Field(..., description="계산식 표시")
    amount: Decimal = Field(..., description="단계 금액")


class AllocationItem(BaseModel):
    """변제 충당 내역"""
    payment_date: date = Field(..., description="변제일")
    payment_amount: Decimal = Field(..., description="변제액")
    applied_to_cost: Decimal = Field(default=Decimal("0"), description="비용 충당액")
    applied_to_interest: Decimal = Field(default=Decimal("0"), description="이자 충당액")
    applied_to_principal: Decimal = Field(default=Decimal("0"), description="원금 충당액")
    remaining_principal_after: Decimal = Field(..., description="충당 후 남은 원금")


class RateClause(BaseModel):
    """청구취지 이율 구간"""
    pre_service_rate: Decimal = Field(..., description="송달 전 연 이율(%)")
    post_service_rate: Decimal = Field(..., description="송달 후 연 이율(%)")
    sentence: str = Field(default="", description="완성된 청구취지 한 문장")


class ReferenceTotal(BaseModel):
    """기준일 참고 총액"""
    as_of: date = Field(..., description="기준일")
    amount: Decimal = Field(..., description="참고 총액")


class LimitCheck(BaseModel):
    """한도 확인 결과"""
    jurisdiction: str = Field(..., description="KR 또는 US")
    threshold: Decimal = Field(..., description="기준 금액")
    compared_amount: Decimal = Field(..., description="비교한 금액")
    exceeded: bool = Field(default=False, description="기준 초과 여부")
    message: Optional[str] = Field(default=None, description="안내 문구")


class Calculation(BaseModel):
    """한국 계산 결과 (M2 입력용)"""
    allocations: List[AllocationItem] = Field(default_factory=list, description="변제 충당 내역")
    remaining_principal: Decimal = Field(..., description="남은 원금")
    accrual_start_date: date = Field(..., description="지연손해금 기산일")
    rate_clause: RateClause = Field(..., description="이율 구간과 완성 문장")
    reference_total: ReferenceTotal = Field(..., description="기준일 참고 총액")
    limit_check: Optional[LimitCheck] = Field(default=None, description="한도 확인 결과")
    missing_fields: List[str] = Field(default_factory=list, description="비어 있는 입력 항목")
    warnings: List[str] = Field(default_factory=list, description="경고 문구")
    calculation_steps: List[CalculationStep] = Field(default_factory=list, description="화면 표시용 계산 단계")
    overpayment_amount: Decimal = Field(default=Decimal("0"), description="초과 변제액")
    accrued_interest: Decimal = Field(default=Decimal("0"), description="기준일까지 쌓인 이자(버림 후)")


class VerificationResult(BaseModel):
    """결정론적 검증 게이트 판정 결과"""
    status: VerificationStatusEnum = Field(..., description="최종 판정 상태")
    is_valid: bool = Field(..., description="법원 서류 생성 진행 가능 여부")
    reconciled_amount: Decimal = Field(..., description="확인된 잔여 원금")
    calculated_interest: Decimal = Field(default=Decimal("0.00"), description="계산된 지연손해금/이자")
    total_claim_amount: Decimal = Field(..., description="총 청구금액 (원금 + 이자)")

    overpayment_amount: Decimal = Field(default=Decimal("0.00"), description="과오납 변제 초과액")
    is_debt_fully_satisfied: bool = Field(default=False, description="원리금 전액 변제 완료 여부")

    citations_valid: bool = Field(..., description="증거 인용 유효성")
    missing_requirements: List[str] = Field(default_factory=list, description="확인할 칸 목록")
    tampering_reconciliations: List[str] = Field(default_factory=list, description="초안 금액과 계산값 차이 기록")
    audit_notes: List[str] = Field(default_factory=list, description="감사 로그")
    interest_breakdown: Dict[str, Any] = Field(default_factory=dict, description="구간별 이자 산출 내역")
    calculation: Optional[Calculation] = Field(default=None, description="한국 계산 상세")
