import logging
import os
import tempfile
from datetime import date
from decimal import Decimal
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

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
logger = logging.getLogger(__name__)


def _remove_temp_file(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        logger.warning("임시 파일 삭제 실패")


class VerifyRequest(BaseModel):
    loan_fact: LoanFactSchema
    claim_draft: GeneratedClaimDraft
    target_date: Optional[date] = None


@router.post("/verify", response_model=VerificationResult)
def verify_claim(req: VerifyRequest):
    """
    결정론적 규칙 검증 게이트 엔드포인트
    - 이자 산출, 입력값 대조, 초안 금액과 계산값 비교
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
                "message": "서류를 만들 수 없습니다. 아래 칸을 확인하세요.",
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
            as_of=req.target_date,
        )
        return FileResponse(
            tmp.name,
            media_type="application/pdf",
            filename=f"SC-100_{req.loan_fact.debtor.name.replace(' ', '_')}.pdf",
            background=BackgroundTask(_remove_temp_file, tmp.name),
        )
    except Exception:
        logger.exception("SC-100 생성 실패")
        _remove_temp_file(tmp.name)
        raise HTTPException(status_code=500, detail="서류 생성 중 오류가 발생했습니다.")


@router.post("/compile/content-proof")
def compile_content_proof_pdf(req: VerifyRequest):
    """
    내용증명 PDF 컴파일 다운로드
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
                "message": "서류를 만들 수 없습니다. 아래 칸을 확인하세요.",
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
            as_of=req.target_date,
        )
        return FileResponse(
            tmp.name,
            media_type="application/pdf",
            filename=f"내용증명_{req.loan_fact.debtor.name}.pdf",
            background=BackgroundTask(_remove_temp_file, tmp.name),
        )
    except Exception:
        logger.exception("내용증명 생성 실패")
        _remove_temp_file(tmp.name)
        raise HTTPException(status_code=500, detail="서류 생성 중 오류가 발생했습니다.")


@router.post("/compile/ecourt-packet")
def compile_ecourt_packet(req: VerifyRequest) -> Dict[str, str]:
    """
    대한민국 법원 전자소송 클립보드 블록 패키지 반환
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
                "message": "서류를 만들 수 없습니다. 아래 칸을 확인하세요.",
                "missing_requirements": verification.missing_requirements,
            }
        )

    return KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(
        loan_fact=req.loan_fact,
        verification=verification,
        as_of=req.target_date,
    )


@router.get("/demo/samples")
def get_demo_samples():
    """
    해커톤 2분 라이브 데모용 한국/미국 표준 샘플 데이터 세트 즉시 반환
    """
    kr_sample = {
        "loan_fact": {
            "creditor": {"name": "서가온(SAMPLE)", "phone": "010-0000-0000", "address": "서울특별시 샘플구 데모로 0", "city": "서울", "state": "서울", "zip_code": "00000"},
            "debtor": {"name": "탁나루(SAMPLE)", "phone": "010-0000-0000", "address": "경기도 샘플시 데모동 0", "city": "샘플시", "state": "경기", "zip_code": "00000"},
            "currency": "KRW",
            "transaction_kind": "civil",
            "principal_amount": "10000000",
            "loan_date": "2026-01-01",
            "due_date": "2026-06-30",
            "service_date": "2026-08-31",
            "evidences": [
                {"id": "갑 제1호증", "title": "샘플은행 계좌이체확인증", "evidence_type": "transfer_receipt", "sha256_hash": "8fe6d6d4617185b96cdbbbcac3b9cad0e39f003e4c99977c586a7a4e149d6728", "source_filename": "kr_transfer_receipt.txt", "extracted_amount": "10000000", "extracted_date": "2026-01-01"},
                {"id": "갑 제2호증", "title": "샘플톡 대화록", "evidence_type": "messenger_chat", "sha256_hash": "63e31fe59bb5e7c25cd1ff528135e12488318d579c3ec9219e6b4d85dac42e25", "source_filename": "kr_chat_log.txt", "extracted_date": "2026-06-25"}
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
            "creditor": {"name": "Avery Linden (SAMPLE)", "phone": "010-0000-0000", "address": "0 Sample Street, Sample City", "city": "Sample City", "state": "CA", "zip_code": "00000"},
            "debtor": {"name": "Rowan Hale (SAMPLE)", "phone": "213-555-0144", "address": "0 Sample St, Sample City, CA 90000", "city": "Sample City", "state": "CA", "zip_code": "90000"},
            "currency": "USD",
            "contract_form": "written",
            "principal_amount": "5000.00",
            "loan_date": "2026-01-10",
            "due_date": "2026-04-10",
            "evidences": [
                {"id": "Exhibit A", "title": "Sample Bank Wire Transfer Receipt", "evidence_type": "transfer_receipt", "sha256_hash": "1bea6080d6dbd79e562e66a81fed0a7efa51081ee9cc8c8c4784cf87f66ea7c4", "source_filename": "us_wire_receipt.txt", "extracted_amount": "5000.00", "extracted_date": "2026-01-10"},
                {"id": "Exhibit B", "title": "Repayment promise message", "evidence_type": "messenger_chat", "sha256_hash": "63e31fe59bb5e7c25cd1ff528135e12488318d579c3ec9219e6b4d85dac42e25", "source_filename": "kr_chat_log.txt", "extracted_date": "2026-04-01"}
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
