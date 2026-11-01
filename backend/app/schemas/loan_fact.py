from datetime import date
from decimal import Decimal
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator


class CurrencyEnum(str, Enum):
    KRW = "KRW"
    USD = "USD"


class EvidenceTypeEnum(str, Enum):
    TRANSFER_RECEIPT = "transfer_receipt"      # 이체확인증
    MESSENGER_CHAT = "messenger_chat"          # 메신저 대화 캡처/영상
    LOAN_AGREEMENT = "loan_agreement"          # 차용증/계약서
    DEMAND_NOTICE = "demand_notice"            # 독촉장/내용증명


class VerificationStatusEnum(str, Enum):
    PASS = "PASS"
    RECONCILED = "RECONCILED"                  # AI 수치 위변조 복원됨
    HUMAN_CHECK_REQUIRED = "HUMAN_CHECK_REQUIRED"  # 핵심 요건사실 결손 보류


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
    extracted_date: Optional[date] = Field(None, description="증거상 추출된 일자")
    extracted_parties: List[str] = Field(default_factory=list, description="언급된 당사자 목록")
    raw_ocr_snippet: Optional[str] = Field(None, description="핵심 OCR 텍스트 스니펫")


class LoanFactSchema(BaseModel):
    """
    금전소비대차 요건사실 구조화 스키마
    - 대여사실 (원금, 대여일자, 이체증빙)
    - 반환약정 / 변제기 (변제기 도래 사실)
    - 변제기 경과 후 미변제 (잔여원금 및 지연손해금)
    """
    creditor: PartyInfo = Field(..., description="채권자 / 원고 (Plaintiff)")
    debtor: PartyInfo = Field(..., description="채무자 / 피고 (Defendant)")
    
    currency: CurrencyEnum = Field(default=CurrencyEnum.KRW, description="통화")
    principal_amount: Decimal = Field(..., gt=0, description="대여 원금")
    loan_date: date = Field(..., description="대여일 / 송금일")
    due_date: date = Field(..., description="변제기 (Due Date)")
    
    agreed_interest_rate: Optional[Decimal] = Field(
        default=None, ge=0, le=Decimal("20.0"), 
        description="약정이율 (연 %, 법정 최고이율 연 20% 한도)"
    )
    statutory_interest_rate: Optional[Decimal] = Field(
        default=None, ge=0,
        description="법정이율 (연 %, 한국 민사 연 5% 또는 소촉법 12%, 미국 CA 연 10%)"
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
    """LLM이 생성한 청구 문서 초안"""
    jurisdiction: str = Field(..., description="KR 또는 US")
    claim_amount_claimed: Decimal = Field(..., description="청구 원금/합계")
    statement_of_facts: str = Field(..., description="청구원인 본문")
    cited_evidence_ids: List[str] = Field(default_factory=list, description="인용된 증거 ID 목록")
    calculation_summary: str = Field(..., description="원리금 계산 근거 설명")


class VerificationResult(BaseModel):
    """결정론적 검증 게이트 판정 결과"""
    status: VerificationStatusEnum = Field(..., description="최종 판정 상태")
    is_valid: bool = Field(..., description="법원 서류 생성 진행 가능 여부")
    reconciled_amount: Decimal = Field(..., description="검증 완료된 확정 원금")
    calculated_interest: Decimal = Field(default=Decimal("0.00"), description="계산된 확정 지연손해금/이자")
    total_claim_amount: Decimal = Field(..., description="총 청구금액 (원금 + 이자)")
    citations_valid: bool = Field(..., description="증거 인용 유효성")
    missing_requirements: List[str] = Field(default_factory=list, description="결손된 요건사실 목록")
    tampering_reconciliations: List[str] = Field(default_factory=list, description="복원된 위변조/할루시네이션 내역")
    audit_notes: List[str] = Field(default_factory=list, description="감사 로그")
