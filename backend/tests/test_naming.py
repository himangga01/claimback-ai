import pathlib
from datetime import date
from decimal import Decimal

from pypdf import PdfReader

from app.schemas.loan_fact import (
    LoanFactSchema,
    PartyInfo,
    EvidenceItem,
    GeneratedClaimDraft,
    CurrencyEnum,
    EvidenceTypeEnum,
    TransactionKindEnum,
)
from app.services.verification_gate import VerificationGateService
from app.services.pdf_compiler import (
    CaliforniaSC100Compiler,
    KoreanLegalDocumentCompiler,
)
from app.services.naming import find_forbidden


def _kr_fact():
    return LoanFactSchema(
        creditor=PartyInfo(
            name="서가온(SAMPLE)",
            phone="010-0000-0000",
            address="서울특별시 샘플구 데모로 0",
            city="서울",
            state="서울",
            zip_code="00000",
        ),
        debtor=PartyInfo(
            name="탁나루(SAMPLE)",
            phone="010-0000-0000",
            address="경기도 샘플시 데모동 0",
            city="샘플시",
            state="경기",
            zip_code="00000",
        ),
        currency=CurrencyEnum.KRW,
        transaction_kind=TransactionKindEnum.CIVIL,
        principal_amount=Decimal("10000000"),
        loan_date=date(2026, 1, 1),
        due_date=date(2026, 6, 30),
        evidences=[
            EvidenceItem(
                id="갑 제1호증",
                title="샘플은행 계좌이체확인증",
                evidence_type=EvidenceTypeEnum.TRANSFER_RECEIPT,
                sha256_hash="e" * 64,
                source_filename="f.pdf",
                extracted_amount=Decimal("10000000"),
            ),
            EvidenceItem(
                id="갑 제2호증",
                title="샘플톡 대화록",
                evidence_type=EvidenceTypeEnum.MESSENGER_CHAT,
                sha256_hash="a" * 64,
                source_filename="f2.mp4",
            ),
        ],
    )


def _us_fact():
    return LoanFactSchema(
        creditor=PartyInfo(
            name="Avery Linden (SAMPLE)",
            phone="010-0000-0000",
            address="0 Sample Street",
            city="Sample City",
            state="CA",
            zip_code="00000",
        ),
        debtor=PartyInfo(
            name="Rowan Hale (SAMPLE)",
            phone="213-555-0144",
            address="1725 Slough Avenue",
            city="Los Angeles",
            state="CA",
            zip_code="90012",
        ),
        currency=CurrencyEnum.USD,
        principal_amount=Decimal("5000.00"),
        loan_date=date(2026, 1, 10),
        due_date=date(2026, 4, 10),
        evidences=[
            EvidenceItem(
                id="Exhibit A",
                title="Wire Transfer Confirmation",
                evidence_type=EvidenceTypeEnum.TRANSFER_RECEIPT,
                sha256_hash="1" * 64,
                source_filename="w.png",
                extracted_amount=Decimal("5000.00"),
            ),
            EvidenceItem(
                id="Exhibit B",
                title="Repayment promise message",
                evidence_type=EvidenceTypeEnum.MESSENGER_CHAT,
                sha256_hash="2" * 64,
                source_filename="c.png",
            ),
        ],
    )


def test_naming_generated_docs_clean(tmp_path):
    kr = _kr_fact()
    kr_draft = GeneratedClaimDraft(
        jurisdiction="KR",
        claim_amount_claimed=Decimal("10000000"),
        statement_of_facts="[갑 제1호증] [갑 제2호증]",
        cited_evidence_ids=["갑 제1호증", "갑 제2호증"],
        calculation_summary="Summary",
    )
    kr_ver = VerificationGateService.verify_and_reconcile(
        kr, kr_draft, target_date=date(2026, 10, 31)
    )
    assert kr_ver.is_valid is True
    out = str(tmp_path / "proof.pdf")
    KoreanLegalDocumentCompiler.generate_content_proof_pdf(
        kr, kr_ver, out, as_of=date(2026, 10, 31)
    )
    text = PdfReader(out).pages[0].extract_text()
    assert find_forbidden(text) == []

    packet = KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(kr, kr_ver)
    for key in ("parties", "claim_purpose", "claim_cause_payment_order", "claim_cause_lawsuit"):
        assert find_forbidden(packet[key]) == [], key

    us = _us_fact()
    us_draft = GeneratedClaimDraft(
        jurisdiction="US",
        claim_amount_claimed=Decimal("5000.00"),
        statement_of_facts="[Exhibit A] [Exhibit B]",
        cited_evidence_ids=["Exhibit A", "Exhibit B"],
        calculation_summary="Summary",
    )
    us_ver = VerificationGateService.verify_and_reconcile(
        us, us_draft, target_date=date(2026, 4, 10)
    )
    out2 = str(tmp_path / "sc100.pdf")
    CaliforniaSC100Compiler.compile_sc100(us, us_ver, out2, as_of=date(2026, 4, 10))
    fields = PdfReader(out2).get_fields()
    for name, field in fields.items():
        val = field.get("/V")
        if isinstance(val, str) and val:
            assert find_forbidden(val) == [], name


def _repo_root():
    return pathlib.Path(__file__).resolve().parents[2]


def test_naming_frontend_index_clean():
    text = (_repo_root() / "frontend" / "index.html").read_text(encoding="utf-8")
    assert find_forbidden(text) == []


def test_naming_frontend_case_js_clean():
    text = (_repo_root() / "frontend" / "case.js").read_text(encoding="utf-8")
    assert find_forbidden(text) == []


def test_naming_readme_clean():
    text = (_repo_root() / "README.md").read_text(encoding="utf-8")
    assert find_forbidden(text) == []
