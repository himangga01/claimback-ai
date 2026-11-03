"""Packager (rule): approved sentences -> PDFs + ecourt text + G1b."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

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


# M5-fix2 (1): per-document name voice via slot re-rendering (josa fitted).
LETTER_NAMES = {"creditor_name": "본인", "debtor_name": "귀하"}
ECOURT_NAMES = {"creditor_name": "채권자", "debtor_name": "채무자"}


def style_slot_values(
    base_values: Mapping[str, str], style: str
) -> Dict[str, str]:
    """Copy of slot values with only the party names switched per doc."""
    values = dict(base_values or {})
    overrides = LETTER_NAMES if str(style or "").lower().startswith("letter") else ECOURT_NAMES
    values.update(overrides)
    return values


def render_sentence_for_style(
    text_with_slots: str,
    base_values: Mapping[str, str],
    quotes: Mapping[str, str],
    style: str,
) -> str:
    """Re-render stored slots with per-doc names (quotes untouched)."""
    return deps.render_sentence(
        str(text_with_slots or ""),
        style_slot_values(base_values, style),
        dict(quotes or {}),
    )


def styled_fact_sentences(
    state: CaseState,
    calculation_json: Mapping[str, Any],
    style: str,
) -> List[str]:
    """Unprefixed fact sentences re-rendered for one doc style.

    Falls back to the stored ``rendered_text`` when a sentence has no
    slots or re-rendering fails (user-edited plain text).
    """
    confirmed = state.confirmed_facts or {}
    fields = confirmed.get("fields", {}) or {}
    try:
        base_values = deps.build_slot_values(fields, dict(calculation_json or {}))
    except Exception:
        base_values = deps.build_slot_values(fields, {})
    try:
        quotes = deps.build_quotes(list(state.readings or []))
    except Exception:
        quotes = {}
    out: List[str] = []
    sentences = (state.drafts or {}).get("sentences", []) or []
    for entry in sentences:
        slots = entry.get("text_with_slots", "") if isinstance(entry, dict) else ""
        stored = entry.get("rendered_text", "") if isinstance(entry, dict) else ""
        if slots:
            try:
                out.append(render_sentence_for_style(slots, base_values, quotes, style))
                continue
            except ValueError:
                pass
        out.append(str(stored or ""))
    return out


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


def _sha256_file(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def load_redaction_previews(state: CaseState) -> Dict[str, Dict[str, Any]]:
    """Previews by ex_id from files/redactions.json ({} when absent)."""
    target = files_dir(state.case_id) / "redactions.json"
    try:
        if not target.exists() or not target.is_file():
            return {}
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    previews = data.get("previews", []) if isinstance(data, dict) else []
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(previews, list):
        for entry in previews:
            if isinstance(entry, dict) and entry.get("ex_id"):
                out[str(entry["ex_id"])] = dict(entry)
    return out


def is_redaction_confirmed(state: CaseState) -> bool:
    """True only when the user set redaction_confirmed: true."""
    confirmed = state.confirmed_facts or {}
    return confirmed.get("redaction_confirmed") is True


def get_redaction_status(
    state: CaseState,
) -> Tuple[Dict[str, str], set, set]:
    """Valid redacted copies + needs-review/identical exclusions (M5-fix2).

    A copy whose SHA-256 equals the original (images) or the PDF preview
    PNG is not a redacted copy and is excluded. A preview flagged
    ``needs_review``/``not_redacted`` is excluded unless the user confirmed.
    """
    files_base = files_dir(state.case_id)
    evidence_base = evidence_dir(state.case_id)
    previews = load_redaction_previews(state)
    confirmed = is_redaction_confirmed(state)
    valid: Dict[str, str] = {}
    needs_review: set = set()
    identical: set = set()
    for record in state.evidence:
        kind = str(getattr(record, "kind", "image"))
        if kind not in ("image", "pdf"):
            continue
        ex_id = str(getattr(record, "ex_id", ""))
        if not ex_id:
            continue
        candidate = files_base / f"redacted_{ex_id}.png"
        try:
            if not candidate.exists() or not candidate.is_file():
                continue
        except OSError:
            continue
        preview = previews.get(ex_id, {})
        if (
            preview.get("needs_review") is True
            or preview.get("status") == "not_redacted"
        ) and not confirmed:
            needs_review.add(ex_id)
            continue
        red_hash = _sha256_file(candidate)
        if red_hash is not None:
            compare: List[Path] = []
            try:
                stored = str(getattr(record, "stored_name", "") or "")
                if stored:
                    compare.append(evidence_base / stored)
                if kind == "pdf":
                    compare.append(evidence_base / f"{ex_id}_preview.png")
            except OSError:
                compare = []
            for other in compare:
                try:
                    if other.exists() and other.is_file():
                        if _sha256_file(other) == red_hash:
                            identical.add(ex_id)
                            break
                except OSError:
                    continue
            if ex_id in identical:
                continue
        valid[ex_id] = str(candidate)
    return valid, needs_review, identical


def discover_redacted_paths(state: CaseState) -> Dict[str, str]:
    """Redacted copy per ex_id (K3 + M5-fix2 validation)."""
    valid, _, _ = get_redaction_status(state)
    return valid


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
    calc_json = deps.calculation_to_json(calc)
    # M5-fix2 (1): per-doc slot re-rendering (letter 본인/귀하, ecourt 채권자/채무자).
    letter_inputs = styled_fact_sentences(state, calc_json, "letter")
    ecourt_inputs = styled_fact_sentences(state, calc_json, "ecourt")
    # K6: both docs share pdf_compiler wording (no packager copies).
    packet = deps.KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(
        loan_fact, verification, as_of=as_of, fact_sentences=ecourt_inputs
    )
    claim_purpose = packet.get("claim_purpose", "")
    claim_cause = packet.get("claim_cause_payment_order", "")
    evidence_dicts = [record.model_dump() for record in state.evidence]
    # K5: pre-write naming screen covers names/addresses/phones/evidence names.
    letter_facts = [_format_letter_fact(s) for s in _ensure_numbered(letter_inputs)]
    ecourt_facts = [_format_ecourt_fact(s) for s in _ensure_numbered(ecourt_inputs)]
    pre_texts = [
        claim_purpose, claim_cause,
        *letter_inputs, *ecourt_inputs, *letter_facts, *ecourt_facts,
    ]
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
    redacted_map, needs_review_ids, identical_ids = get_redaction_status(state)
    still_map = discover_still_paths(state)
    content_pdf = target_dir / "content_proof.pdf"
    deps.KoreanLegalDocumentCompiler.generate_content_proof_pdf(
        loan_fact, verification, str(content_pdf), as_of=as_of,
        fact_sentences=letter_inputs,
    )
    exhibits_pdf = target_dir / "exhibits.pdf"
    evidence_list_pdf = target_dir / "evidence_list.pdf"
    exhibit_bundle_mod.build_exhibits_pdf(
        evidence_dicts, evidence_dir(state.case_id), str(exhibits_pdf),
        redacted=redacted_map,
        stills=still_map,
        needs_review=needs_review_ids,
        confirmed=confirmed,
    )
    exhibit_bundle_mod.build_evidence_list_pdf(
        evidence_dicts, confirmed, str(evidence_list_pdf),
        readings=state.readings,
        calculation=calc_json,
    )
    docs = {
        "content_proof.pdf": final_check_mod.extract_pdf_text(content_pdf),
        "exhibits.pdf": final_check_mod.extract_pdf_text(exhibits_pdf),
        "evidence_list.pdf": final_check_mod.extract_pdf_text(evidence_list_pdf),
        "ecourt": f"{claim_purpose}\n{claim_cause}",
    }
    g1b = final_check_mod.check_g1b(
        final_check_mod.build_expected_amounts(
            fields, calc_json, confirmed.get("as_of")),
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
    # K3 + M5-fix2: missing/identical/needs-review copies are G1b findings.
    for record in _missing_redacted_ex_ids(evidence_dicts, redacted_map):
        ex_id = str(record.get("ex_id", ""))
        label = str(record.get("label", ex_id))
        if ex_id in needs_review_ids:
            message = (
                f"exhibits.pdf: {label}({ex_id})의 가림 확인이 필요해 "
                f"이미지를 넣지 않았습니다."
            )
        elif ex_id in identical_ids:
            message = (
                f"exhibits.pdf: {label}({ex_id})의 가림 사본이 원본과 같아 "
                f"이미지를 넣지 않았습니다."
            )
        else:
            message = (
                f"exhibits.pdf: {label}({ex_id})의 가림 사본("
                f"files/redacted_{ex_id}.png)이 없어 이미지를 넣지 않았습니다."
            )
        findings.append(deps.Finding(
            sentence_id="",
            field=str(ex_id or "exhibits.pdf"),
            message=message,
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
