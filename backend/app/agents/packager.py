"""Packager (rule): approved sentences -> content proof PDF + ecourt text."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

from app.agents import deps
from app.agents.case_state import CaseState, files_dir


class NamingViolation(ValueError):
    """Package text tripped the document naming check."""


def approved_fact_sentences(state: CaseState) -> List[str]:
    """Numbered rendered sentences (already substituted at draft time)."""
    sentences = (state.drafts or {}).get("sentences", []) or []
    return [
        f"{position}. {entry.get('rendered_text', '')}"
        for position, entry in enumerate(sentences, start=1)
    ]


def build_package(state: CaseState) -> Dict[str, Any]:
    """Write content_proof.pdf and build the Package response dict."""
    confirmed = state.confirmed_facts or {}
    fields = confirmed.get("fields", {}) or {}
    roles = confirmed.get("evidence_roles", {}) or {}
    as_of = date.fromisoformat(str(confirmed.get("as_of")).strip())
    loan_fact = deps.build_loan_fact(
        fields, roles, [record.model_dump() for record in state.evidence]
    )
    calc = deps.calculate_kr(loan_fact, as_of)
    if calc.remaining_principal <= Decimal("0"):
        remaining: Decimal = calc.remaining_principal
    else:
        remaining = calc.remaining_principal
    verification = deps.VerificationGateService.verify_and_reconcile(
        loan_fact=loan_fact,
        claim_draft=deps.synthetic_claim_draft(loan_fact, remaining),
        target_date=as_of,
    )
    fact_sentences = approved_fact_sentences(state)

    target_dir = files_dir(state.case_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = target_dir / "content_proof.pdf"
    deps.KoreanLegalDocumentCompiler.generate_content_proof_pdf(
        loan_fact, verification, str(pdf_path), as_of=as_of,
        fact_sentences=fact_sentences,
    )
    packet = deps.KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(
        loan_fact, verification, as_of=as_of, fact_sentences=fact_sentences
    )
    claim_purpose = packet.get("claim_purpose", "")
    claim_cause = packet.get("claim_cause_payment_order", "")
    whole = "\n".join([claim_purpose, claim_cause, *fact_sentences,
                       packet.get("claim_cause_lawsuit", "")])
    forbidden = deps.find_forbidden_doc(whole)
    if forbidden:
        raise NamingViolation(
            f"서류 문구에 쓸 수 없는 표현이 있습니다: {forbidden[0]}"
        )
    g1b = deps.GateResult(gate="G1b", status="pass", findings=[])
    g1b_dump = g1b.model_dump(mode="json")
    g1b_dump["status"] = "skipped"  # G1b lands in M5
    return {
        "files": [{
            "name": "content_proof.pdf",
            "label": "내용증명",
            "url": f"/api/cases/{state.case_id}/files/content_proof.pdf",
        }],
        "ecourt": {
            "claim_purpose": claim_purpose,
            "claim_cause_payment_order": claim_cause,
        },
        "notices": {
            "notice_ko": deps.NOTICE_KO,
            "disclaimer_ko": deps.DISCLAIMER_KO,
        },
        "gate_results": [g1b_dump],
    }
