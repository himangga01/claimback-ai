import os
import tempfile
from datetime import date
from decimal import Decimal
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.schemas.loan_fact import (
    LoanFactSchema,
    GeneratedClaimDraft,
    VerificationResult,
    PartyInfo,
    EvidenceItem,
    CurrencyEnum,
    EvidenceTypeEnum,
    TransactionKindEnum,
    ContractFormEnum,
)
from app.services.verification_gate import VerificationGateService
from app.services.pdf_compiler import CaliforniaSC100Compiler, KoreanLegalDocumentCompiler

router = APIRouter(prefix="/api")


class VerifyRequest(BaseModel):
    loan_fact: LoanFactSchema
    claim_draft: GeneratedClaimDraft
    target_date: Optional[date] = None


@router.post("/verify", response_model=VerificationResult)
def verify_claim(req: VerifyRequest):
    """
    결정론적 규칙 검증 게이트 엔드포인트
    - 법정이자 산출, 요건사실 대조, 수치 위변조 강제 복원
    """
    evidence_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../sample_evidence"))
    result = VerificationGateService.verify_and_reconcile(
        loan_fact=req.loan_fact,
        claim_draft=req.claim_draft,
        target_date=req.target_date,
        evidence_files_dir=evidence_dir if os.path.exists(evidence_dir) else None,
    )
    return result


@router.post("/compile/sc100")
def compile_sc100_pdf(req: VerifyRequest):
    """
    미국 캘리포니아 소액재판소 공식 Form SC-100 PDF 컴파일 다운로드
    """
    evidence_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../sample_evidence"))
    verification = VerificationGateService.verify_and_reconcile(
        loan_fact=req.loan_fact,
        claim_draft=req.claim_draft,
        target_date=req.target_date,
        evidence_files_dir=evidence_dir if os.path.exists(evidence_dir) else None,
    )

    if not verification.is_valid:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "법적 요건사실 결손으로 SC-100 PDF 생성이 차단되었습니다.",
                "missing_requirements": verification.missing_requirements,
            }
        )

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.close()

    try:
        CaliforniaSC100Compiler.compile_sc100(
            loan_fact=req.loan_fact,
            verification=verification,
            output_path=tmp.name,
        )
        return FileResponse(
            tmp.name,
            media_type="application/pdf",
            filename=f"SC-100_{req.loan_fact.debtor.name.replace(' ', '_')}.pdf",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compile/content-proof")
def compile_content_proof_pdf(req: VerifyRequest):
    """
    대한민국 우체국 전자내용증명 표준 규격 PDF 컴파일 다운로드
    """
    evidence_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../sample_evidence"))
    verification = VerificationGateService.verify_and_reconcile(
        loan_fact=req.loan_fact,
        claim_draft=req.claim_draft,
        target_date=req.target_date,
        evidence_files_dir=evidence_dir if os.path.exists(evidence_dir) else None,
    )

    if not verification.is_valid:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "법적 요건사실 결손으로 내용증명 생성이 차단되었습니다.",
                "missing_requirements": verification.missing_requirements,
            }
        )

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.close()

    try:
        KoreanLegalDocumentCompiler.generate_content_proof_pdf(
            loan_fact=req.loan_fact,
            verification=verification,
            output_path=tmp.name,
        )
        return FileResponse(
            tmp.name,
            media_type="application/pdf",
            filename=f"내용증명_{req.loan_fact.debtor.name}.pdf",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compile/ecourt-packet")
def compile_ecourt_packet(req: VerifyRequest) -> Dict[str, str]:
    """
    대한민국 법원 전자소송 1:1 클립보드 블록 패키지 반환
    """
    verification = VerificationGateService.verify_and_reconcile(
        loan_fact=req.loan_fact,
        claim_draft=req.claim_draft,
        target_date=req.target_date,
    )
    return KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(
        loan_fact=req.loan_fact,
        verification=verification,
    )


@router.get("/demo/samples")
def get_demo_samples():
    """
    해커톤 2분 라이브 데모용 한국/미국 표준 샘플 데이터 세트 즉시 반환
    """
    kr_sample = {
        "loan_fact": {
            "creditor": {"name": "정재훈", "phone": "010-4690-7547", "address": "서울 송파구 거여동 거여1단지 106-1104", "city": "서울", "state": "서울", "zip_code": "05753"},
            "debtor": {"name": "김채무", "phone": "010-1234-5678", "address": "경기 성남시 중원구 금광동 100", "city": "성남", "state": "경기", "zip_code": "13180"},
            "currency": "KRW",
            "transaction_kind": "civil",
            "principal_amount": "10000000",
            "loan_date": "2026-01-01",
            "due_date": "2026-06-30",
            "service_date": "2026-08-31",
            "evidences": [
                {"id": "갑 제1호증", "title": "토스뱅크 계좌이체확인증", "evidence_type": "transfer_receipt", "sha256_hash": "f350d3ac80739e28ef11285b9ede3724687a748d3d8a3663042b28ed63b1a361", "source_filename": "kr_transfer_receipt.txt", "extracted_amount": "10000000", "extracted_date": "2026-01-01"},
                {"id": "갑 제2호증", "title": "카카오톡 대화록", "evidence_type": "messenger_chat", "sha256_hash": "01ee74d4a1780b06715d6fe0261aa669e71d564c5c22c50843df44fd9e4ed6c8", "source_filename": "kr_chat_log.txt", "extracted_date": "2026-06-25"}
            ]
        },
        "claim_draft": {
            "jurisdiction": "KR",
            "claim_amount_claimed": "10000000",
            "statement_of_facts": "채무자는 채권자로부터 [갑 제1호증]에 의해 금전을 대여받았고 [갑 제2호증]으로 변제 약정하였으나 불이행함.",
            "cited_evidence_ids": ["갑 제1호증", "갑 제2호증"],
            "calculation_summary": "원금 10,000,000원 및 지연손해금"
        }
    }

    us_sample = {
        "loan_fact": {
            "creditor": {"name": "Jaehoon Jeong", "phone": "010-4690-7547", "address": "106-1104, Geoyeo 1-danji Apt, Songpa-gu", "city": "Seoul", "state": "KR", "zip_code": "05753"},
            "debtor": {"name": "Michael Scott", "phone": "213-555-0144", "address": "1725 Slough Avenue", "city": "Los Angeles", "state": "CA", "zip_code": "90012"},
            "currency": "USD",
            "contract_form": "written",
            "principal_amount": "5000.00",
            "loan_date": "2026-01-10",
            "due_date": "2026-04-10",
            "evidences": [
                {"id": "Exhibit A", "title": "Chase Wire Transfer Receipt", "evidence_type": "transfer_receipt", "sha256_hash": "1fa16c7e324d3ead0152aa835c7f2d939ab39ba06e08b3a13706e7d94ec4bc64", "source_filename": "us_wire_receipt.txt", "extracted_amount": "5000.00", "extracted_date": "2026-01-10"},
                {"id": "Exhibit B", "title": "Promissory Admission", "evidence_type": "messenger_chat", "sha256_hash": "01ee74d4a1780b06715d6fe0261aa669e71d564c5c22c50843df44fd9e4ed6c8", "source_filename": "kr_chat_log.txt", "extracted_date": "2026-04-01"}
            ]
        },
        "claim_draft": {
            "jurisdiction": "US",
            "claim_amount_claimed": "5000.00",
            "statement_of_facts": "Defendant received $5,000.00 as personal loan evidenced by [Exhibit A] and promised repayment in [Exhibit B].",
            "cited_evidence_ids": ["Exhibit A", "Exhibit B"],
            "calculation_summary": "Principal $5,000.00 plus 10% statutory interest"
        }
    }

    return {"korean_sample": kr_sample, "us_sample": us_sample}
