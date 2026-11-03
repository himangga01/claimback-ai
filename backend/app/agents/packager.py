"""Packager (rule): approved sentences -> PDFs + ecourt text + G1b."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from app.agents import deps
from app.agents.case_state import CaseState, evidence_dir, files_dir
from app.services import exhibit_bundle as exhibit_bundle_mod
from app.services import final_check as final_check_mod
from app.services.pdf_compiler import (
    build_repayment_sentence as _shared_repayment_sentence,
)
from app.services.pdf_compiler import (
    ensure_numbered_facts as _ensure_numbered,
)
from app.services.pdf_compiler import (
    format_ecourt_fact as _format_ecourt_fact,
)
from app.services.pdf_compiler import (
    format_letter_fact as _format_letter_fact,
)
from app.services.pdf_compiler import (
    kana_label as _shared_kana_label,
)


class NamingViolation(ValueError):
    """Package text tripped the document naming check."""


# K6: single source lives in pdf_compiler; packager re-exports the same
# functions so content proof and ecourt wording cannot drift.
KANA_ORDER = ["가", "나", "다", "라", "마", "바", "사", "아", "자", "차",
              "카", "타", "파", "하"]


def kana_label(position: int) -> str:
    """1-based approval-sentence label (가. 나. 다. …, then (n))."""
    return _shared_kana_label(position)


def approved_fact_sentences(state: CaseState) -> List[str]:
    """Kana-numbered rendered sentences (already substituted at draft time)."""
    sentences = (state.drafts or {}).get("sentences", []) or []
    return [
        f"{kana_label(position)} {entry.get('rendered_text', '')}"
        for position, entry in enumerate(sentences, start=1)
    ]


def build_repayment_sentence(first: Any, second: Any = None, style: str = "ecourt") -> str:
    """Shared repayment wording (canonical in pdf_compiler, K6/K7)."""
    return _shared_repayment_sentence(first, second, style=style)


def _state_extra_map(state: CaseState, names: List[str]) -> Dict[str, str]:
    """Forward-compatible lookup for M4b path maps on the case state."""
    found: Dict[str, str] = {}
    try:
        dumped = state.model_dump()
    except Exception:
        dumped = {}
    if isinstance(dumped, dict):
        for name in names:
            value = dumped.get(name)
            if isinstance(value, dict):
                for key, path_value in value.items():
                    if path_value:
                        found[str(key)] = str(path_value)
    for name in names:
        try:
            value = getattr(state, name, None)
        except Exception:
            continue
        if isinstance(value, dict):
            for key, path_value in value.items():
                if path_value and str(key) not in found:
                    found[str(key)] = str(path_value)
    return found


def _first_existing(paths: List[Path]) -> Optional[Path]:
    for path in paths:
        try:
            if path.exists() and path.is_file():
                return path
        except OSError:
            continue
    return None


def discover_redacted_paths(state: CaseState) -> Dict[str, str]:
    """Redacted copy per ex_id (K3: only files/redacted_{ex_id}.png)."""
    files_base = files_dir(state.case_id)
    resolved: Dict[str, str] = {}
    for record in state.evidence:
        ex_id = record.ex_id
        candidate = files_base / f"redacted_{ex_id}.png"
        try:
            if candidate.exists() and candidate.is_file():
                resolved[ex_id] = str(candidate)
        except OSError:
            continue
    return resolved


def discover_still_paths(state: CaseState) -> Dict[str, str]:
    """Video still per ex_id (M4b state map or conventional filenames)."""
    extra = _state_extra_map(state, [
        "stills", "video_stills", "keyframes", "keyframe_stills",
        "frame_stills",
    ])
    evidence_base = evidence_dir(state.case_id)
    files_base = files_dir(state.case_id)
    resolved: Dict[str, str] = {}
    for record in state.evidence:
        if record.kind != "video":
            continue
        ex_id = record.ex_id
        candidates: List[Path] = []
        if ex_id in extra:
            candidates.append(Path(extra[ex_id]))
        for base in (evidence_base, files_base):
            for name in (
                f"{ex_id}_still.png", f"{ex_id}_still.jpg",
                f"{ex_id}_keyframe.png", f"{ex_id}_keyframe.jpg",
                f"{ex_id}_frame.png",
            ):
                candidates.append(base / name)
            try:
                if base.exists():
                    for child in sorted(base.glob(f"{ex_id}_keyframe_*.png")):
                        candidates.append(child)
                    for child in sorted(base.glob(f"{ex_id}_keyframe_*.jpg")):
                        candidates.append(child)
            except OSError:
                pass
        hit = _first_existing(candidates)
        if hit is not None:
            resolved[ex_id] = str(hit)
    return resolved


def _missing_redacted_ex_ids(
    evidence_dicts: List[Dict[str, Any]],
    redacted: Mapping[str, str],
) -> List[Dict[str, Any]]:
    missing: List[Dict[str, Any]] = []
    for record in evidence_dicts:
        kind = str(record.get("kind", "image"))
        if kind not in ("image", "pdf"):
            continue
        ex_id = str(record.get("ex_id", ""))
        if ex_id and ex_id not in redacted:
            missing.append(record)
    return missing


def build_package(state: CaseState) -> Dict[str, Any]:
    """Write content/exhibit/evidence-list PDFs and build Package + G1b."""
    confirmed = state.confirmed_facts or {}
    fields = confirmed.get("fields", {}) or {}
    roles = confirmed.get("evidence_roles", {}) or {}
    as_of = date.fromisoformat(str(confirmed.get("as_of")).strip())
    loan_fact = deps.build_loan_fact(
        fields, roles, [record.model_dump() for record in state.evidence]
    )
    calc = deps.calculate_kr(loan_fact, as_of)
    remaining: Decimal = calc.remaining_principal
    verification = deps.VerificationGateService.verify_and_reconcile(
        loan_fact=loan_fact,
        claim_draft=deps.synthetic_claim_draft(loan_fact, remaining),
        target_date=as_of,
    )
    fact_sentences = approved_fact_sentences(state)
    # K6: both docs share pdf_compiler wording (no packager copies).
    packet = deps.KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(
        loan_fact, verification, as_of=as_of, fact_sentences=fact_sentences
    )
    claim_purpose = packet.get("claim_purpose", "")
    claim_cause = packet.get("claim_cause_payment_order", "")
    evidence_dicts = [record.model_dump() for record in state.evidence]
    # K5: pre-write naming screen covers names/addresses/phones/evidence names.
    numbered = _ensure_numbered(fact_sentences)
    letter_facts = [
        _format_letter_fact(s, loan_fact.creditor.name, loan_fact.debtor.name)
        for s in numbered
    ]
    ecourt_facts = [_format_ecourt_fact(s) for s in numbered]
    pre_texts = [claim_purpose, claim_cause, *fact_sentences, *letter_facts, *ecourt_facts]
    for key in (
        "creditor_name", "creditor_address", "creditor_phone",
        "debtor_name", "debtor_address", "debtor_phone",
    ):
        pre_texts.append(str(fields.get(key, "") or ""))
    for record in evidence_dicts:
        pre_texts.append(str(record.get("label", "")))
        pre_texts.append(str(record.get("filename", "")))
        try:
            pre_texts.append(exhibit_bundle_mod.evidence_display_name(record, confirmed))
        except Exception:
            pass
        pre_texts.append(exhibit_bundle_mod.evidence_summary(record, confirmed))
        pre_texts.append(exhibit_bundle_mod.evidence_created_label(
            record, confirmed, state.readings,
        ))
    whole = "\n".join(pre_texts)
    forbidden = deps.find_forbidden_doc(whole)
    if forbidden:
        raise NamingViolation(
            f"서류 문구에 쓸 수 없는 표현이 있습니다: {forbidden[0]}"
        )
    target_dir = files_dir(state.case_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    redacted_map = discover_redacted_paths(state)
    still_map = discover_still_paths(state)
    content_pdf = target_dir / "content_proof.pdf"
    deps.KoreanLegalDocumentCompiler.generate_content_proof_pdf(
        loan_fact, verification, str(content_pdf), as_of=as_of,
        fact_sentences=fact_sentences,
    )
    exhibits_pdf = target_dir / "exhibits.pdf"
    evidence_list_pdf = target_dir / "evidence_list.pdf"
    exhibit_bundle_mod.build_exhibits_pdf(
        evidence_dicts, evidence_dir(state.case_id), str(exhibits_pdf),
        redacted=redacted_map,
        stills=still_map,
    )
    exhibit_bundle_mod.build_evidence_list_pdf(
        evidence_dicts, confirmed, str(evidence_list_pdf),
        readings=state.readings,
        calculation=deps.calculation_to_json(calc),
    )
    docs = {
        "content_proof.pdf": final_check_mod.extract_pdf_text(content_pdf),
        "exhibits.pdf": final_check_mod.extract_pdf_text(exhibits_pdf),
        "evidence_list.pdf": final_check_mod.extract_pdf_text(evidence_list_pdf),
        "ecourt": f"{claim_purpose}\n{claim_cause}",
    }
    calc_json = deps.calculation_to_json(calc)
    g1b = final_check_mod.check_g1b(
        final_check_mod.build_expected_amounts(fields, calc_json),
        final_check_mod.build_expected_dates(fields, calc_json, confirmed.get("as_of")),
        final_check_mod.build_expected_names(fields),
        docs,
    )
    findings = list(g1b.findings)
    # K4: leak scan over finished docs (phones excluded).
    phones = [fields.get("creditor_phone"), fields.get("debtor_phone")]
    leak_blobs = {
        "content_proof.pdf": docs["content_proof.pdf"] + "\n" + final_check_mod.extract_pdf_metadata_text(content_pdf),
        "exhibits.pdf": docs["exhibits.pdf"] + "\n" + final_check_mod.extract_pdf_metadata_text(exhibits_pdf),
        "evidence_list.pdf": docs["evidence_list.pdf"] + "\n" + final_check_mod.extract_pdf_metadata_text(evidence_list_pdf),
        "ecourt": docs["ecourt"],
    }
    for doc_name, blob in leak_blobs.items():
        for hit in dict.fromkeys(final_check_mod.find_sensitive_numbers(blob, exclude=phones)):
            findings.append(deps.Finding(
                sentence_id="",
                field=str(doc_name),
                message=f"{doc_name}에 계좌/주민번호로 보이는 값이 있습니다: {hit}",
                fix_hint="가림 사본을 확인하세요.",
            ))
    # K3: missing redacted copies are G1b findings naming the evidence.
    for record in _missing_redacted_ex_ids(evidence_dicts, redacted_map):
        ex_id = str(record.get("ex_id", ""))
        label = str(record.get("label", ex_id))
        findings.append(deps.Finding(
            sentence_id="",
            field=str(ex_id or "exhibits.pdf"),
            message=(
                f"exhibits.pdf: {label}({ex_id})의 가림 사본("
                f"files/redacted_{ex_id}.png)이 없어 이미지를 넣지 않았습니다."
            ),
            fix_hint="가림 사본을 확인하세요.",
        ))
    g1b = deps.GateResult(
        gate="G1b", status="fail" if findings else "pass", findings=findings,
    )
    return {
        "files": [
            {
                "name": "content_proof.pdf",
                "label": "내용증명",
                "url": f"/api/cases/{state.case_id}/files/content_proof.pdf",
            },
            {
                "name": "exhibits.pdf",
                "label": "갑호증",
                "url": f"/api/cases/{state.case_id}/files/exhibits.pdf",
            },
            {
                "name": "evidence_list.pdf",
                "label": "증거 목록",
                "url": f"/api/cases/{state.case_id}/files/evidence_list.pdf",
            },
        ],
        "ecourt": {
            "claim_purpose": claim_purpose,
            "claim_cause_payment_order": claim_cause,
        },
        "notices": {
            "notice_ko": deps.NOTICE_KO,
            "disclaimer_ko": deps.DISCLAIMER_KO,
        },
        "gate_results": [g1b.model_dump(mode="json")],
    }
