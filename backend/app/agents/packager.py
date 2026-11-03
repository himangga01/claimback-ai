"""Packager (rule): approved sentences -> PDFs + ecourt text + G1b."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.agents import deps
from app.agents.case_state import CaseState, evidence_dir, files_dir
from app.services import exhibit_bundle as exhibit_bundle_mod
from app.services import final_check as final_check_mod
from app.services.pdf_compiler import KO_FONT, KO_FONT_BOLD


class NamingViolation(ValueError):
    """Package text tripped the document naming check."""


KANA_ORDER = ["가", "나", "다", "라", "마", "바", "사", "아", "자", "차",
              "카", "타", "파", "하"]


def kana_label(position: int) -> str:
    """1-based approval-sentence label (가. 나. 다. …, then (n))."""
    if 1 <= position <= len(KANA_ORDER):
        return f"{KANA_ORDER[position - 1]}."
    return f"({position})"


def approved_fact_sentences(state: CaseState) -> List[str]:
    """Kana-numbered rendered sentences (already substituted at draft time)."""
    sentences = (state.drafts or {}).get("sentences", []) or []
    return [
        f"{kana_label(position)} {entry.get('rendered_text', '')}"
        for position, entry in enumerate(sentences, start=1)
    ]


def _alloc_value(entry: Any, name: str) -> Decimal:
    if isinstance(entry, Mapping):
        raw = entry.get(name, 0)
    else:
        raw = getattr(entry, name, 0)
    if isinstance(raw, Decimal):
        return raw
    try:
        return Decimal(str(raw))
    except Exception:
        return Decimal("0")


def _alloc_date(entry: Any) -> str:
    if isinstance(entry, Mapping):
        raw = entry.get("payment_date", "")
    else:
        raw = getattr(entry, "payment_date", "")
    if hasattr(raw, "isoformat"):
        try:
            return str(raw.isoformat())
        except Exception:
            return str(raw)
    return str(raw or "")


def build_repayment_sentence(
    allocations: Any,
    remaining: Any,
) -> str:
    """Allocation sentence from calculation values only (no hardcoding).

    Single repayment (sample)::

        2026. 5. 1. 받은 1,000,000원은 그때까지의 지연손해금 14,383원에
        먼저, 나머지 985,617원은 원금에 충당하여 남은 원금은 4,014,383원입니다
    """
    items = list(allocations or [])
    if isinstance(remaining, Decimal):
        remaining_disp = deps.fmt_amount_won(str(remaining))
    else:
        remaining_disp = deps.fmt_amount_won(remaining)
    if not items:
        return ""

    def _clause(entry: Any) -> str:
        when = deps.fmt_kr_date(_alloc_date(entry))
        amount = deps.fmt_amount_won(str(_alloc_value(entry, "payment_amount")))
        cost = _alloc_value(entry, "applied_to_cost")
        interest = _alloc_value(entry, "applied_to_interest")
        principal_part = _alloc_value(entry, "applied_to_principal")
        cost_disp = deps.fmt_amount_won(str(cost))
        interest_disp = deps.fmt_amount_won(str(interest))
        principal_disp = deps.fmt_amount_won(str(principal_part))
        if cost > 0 and interest > 0:
            return (f"{when} 받은 {amount}은 비용 {cost_disp}, 그때까지의 "
                    f"지연손해금 {interest_disp}에 먼저, 나머지 {principal_disp}은 "
                    f"원금에 충당")
        if cost > 0 and interest <= 0:
            return (f"{when} 받은 {amount}은 비용 {cost_disp}에 먼저, 나머지 "
                    f"{principal_disp}은 원금에 충당")
        if interest > 0:
            return (f"{when} 받은 {amount}은 그때까지의 지연손해금 {interest_disp}에 "
                    f"먼저, 나머지 {principal_disp}은 원금에 충당")
        return f"{when} 받은 {amount}은 원금에 충당"

    if len(items) == 1:
        return f"{_clause(items[0])}하여 남은 원금은 {remaining_disp}입니다"
    joined = "; ".join(_clause(entry) for entry in items)
    return f"{joined}하여 남은 원금은 {remaining_disp}입니다"


def _old_repayment_fragment(loan_fact: Any, verification: Any, as_of: date) -> str:
    """Repayment suffix that pdf_compiler puts into lend_part (for replace)."""
    repayments = list(getattr(loan_fact, "repayments", []) or [])
    reps = sorted(
        [r for r in repayments if getattr(r, "payment_date", as_of) <= as_of],
        key=lambda r: getattr(r, "payment_date"),
    )
    if not reps:
        return ""
    remaining_str = f"{int(getattr(verification, 'reconciled_amount', 0)):,}"
    if len(reps) == 1:
        from app.services.pdf_compiler import _fmt_kr_date as _pdf_date
        from app.services.pdf_compiler import _fmt_won as _pdf_won

        r_d = _pdf_date(reps[0].payment_date)
        r_amt = _pdf_won(reps[0].amount)
        return f" 그중 {r_amt}원을 {r_d} 받았고 남은 원금은 {remaining_str}원입니다."
    from app.services.pdf_compiler import _fmt_kr_date as _pdf_date
    from app.services.pdf_compiler import _fmt_won as _pdf_won

    total_repaid = sum((r.amount for r in reps), Decimal("0"))
    total_s = _pdf_won(total_repaid)
    last_d = _pdf_date(reps[-1].payment_date)
    return (
        f" 그중 총 {total_s}원을 {len(reps)}회에 나누어 받았고 "
        f"남은 원금은 {remaining_str}원입니다. (마지막 수령일 {last_d})"
    )


def patch_repayment_sentence(
    text: str,
    loan_fact: Any,
    verification: Any,
    as_of: date,
    allocations: Any,
    remaining: Any,
) -> str:
    """Replace pdf_compiler's short repay line with the allocation sentence."""
    old = _old_repayment_fragment(loan_fact, verification, as_of)
    new = build_repayment_sentence(allocations, remaining)
    if not old or not new or old not in (text or ""):
        return text
    return str(text).replace(old, f" {new}.", 1)


def generate_content_proof_pdf_fixed(
    loan_fact: Any,
    verification: Any,
    output_path: str,
    as_of: Optional[date] = None,
    fact_sentences: Optional[List[str]] = None,
    allocations: Any = None,
    remaining: Any = None,
) -> str:
    """Content proof PDF with the allocation sentence (M5 4a).

    Mirrors ``KoreanLegalDocumentCompiler.generate_content_proof_pdf`` except
    the single/multi repayment suffix in item 2, which is replaced with
    :func:`build_repayment_sentence` (values from ``allocations`` only).
    """
    # Local imports mirror pdf_compiler's helpers without editing it.
    from datetime import timedelta as _timedelta

    from app.services.pdf_compiler import _fmt_kr_date as _pdf_date
    from app.services.pdf_compiler import _fmt_won as _pdf_won

    os_target = Path(output_path)
    os_target.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(os_target), pagesize=A4,
        rightMargin=50, leftMargin=50, topMargin=50, bottomMargin=50,
    )
    styles = getSampleStyleSheet()
    _ = styles
    title_style = ParagraphStyle(
        "ProofTitle", fontName=KO_FONT_BOLD, fontSize=18, leading=24,
        alignment=1, spaceAfter=20,
    )
    body_style = ParagraphStyle(
        "ProofBody", fontName=KO_FONT, fontSize=10, leading=16, spaceAfter=10,
    )
    bold_style = ParagraphStyle(
        "ProofBold", fontName=KO_FONT_BOLD, fontSize=10, leading=16, spaceAfter=5,
    )
    center_style = ParagraphStyle(
        "ProofCenter", fontName=KO_FONT, fontSize=10, leading=16,
        alignment=1, spaceAfter=10,
    )
    right_style = ParagraphStyle(
        "ProofRight", fontName=KO_FONT_BOLD, fontSize=10, leading=16,
        alignment=2, spaceAfter=5,
    )
    notice_style = ParagraphStyle(
        "ProofNotice", fontName=KO_FONT, fontSize=7, leading=10, alignment=1,
        textColor=colors.grey, spaceBefore=30,
    )
    _ = notice_style

    elements: List[Any] = []
    elements.append(Paragraph("<b>내 용 증 명 서</b>", title_style))
    elements.append(Spacer(1, 15))

    p = loan_fact.creditor
    d = loan_fact.debtor
    p_name = _xml_escape(p.name)
    p_phone = _xml_escape(p.phone or "미기재")
    p_addr = _xml_escape(p.address or "미기재")
    d_name = _xml_escape(d.name)
    d_phone = _xml_escape(d.phone or "미기재")
    d_addr = _xml_escape(d.address or "미기재")

    info_data = [
        [Paragraph("<b>발 신 인:</b>", bold_style),
         Paragraph(f"{p_name} (연락처: {p_phone})", body_style)],
        ["", Paragraph(f"주소: {p_addr}", body_style)],
        [Paragraph("<b>수 신 인:</b>", bold_style),
         Paragraph(f"{d_name} (연락처: {d_phone})", body_style)],
        ["", Paragraph(f"주소: {d_addr}", body_style)],
        [Paragraph("<b>제    목:</b>", bold_style),
         Paragraph("<b>대여금 반환 청구의 건</b>", bold_style)],
    ]
    info_table = Table(info_data, colWidths=[65, 430])
    info_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 15))

    principal_str = f"{_pdf_won(loan_fact.principal_amount)}원"
    remaining_str = f"{_pdf_won(verification.reconciled_amount)}원"
    if as_of is not None:
        base_s = _pdf_date(as_of)
        interest_str = f"{_pdf_won(verification.calculated_interest)}원 ({base_s} 기준)"
        total_str = f"{_pdf_won(verification.total_claim_amount)}원"
        total_disp = f"{total_str} ({base_s} 기준)"
    else:
        interest_str = "____원"
        total_str = "____원"
        total_disp = "____원"

    elements.append(Paragraph(
        f"<b>[청구 금액 합계: 금 {total_disp}]</b> (남은 원금: {remaining_str}, "
        f"현재 지연손해금: {interest_str})", bold_style,
    ))
    elements.append(Spacer(1, 10))

    loan_d = _pdf_date(loan_fact.loan_date)
    due_d = _pdf_date(loan_fact.due_date)
    item2 = (
        f"2. 발신인은 귀하에게 <b>{loan_d}</b>에 금 <b>{principal_str}</b>을 "
        f"대여하였으며, 귀하는 이를 <b>{due_d}</b>까지 전액 변제하기로 "
        f"약정하였습니다."
    )
    if as_of is not None and allocations is not None and remaining is not None:
        sentence = build_repayment_sentence(allocations, remaining)
        if sentence:
            item2 += f"<br/>{_xml_escape(sentence)}."
    elif getattr(loan_fact, "repayments", None):
        # Fallback keeps the old shape when no allocation data is passed.
        reps = sorted(
            [r for r in loan_fact.repayments if r.payment_date <= as_of]
            if as_of is not None else list(loan_fact.repayments),
            key=lambda r: r.payment_date,
        )
        if len(reps) == 1:
            r_d = _pdf_date(reps[0].payment_date)
            r_amt = _pdf_won(reps[0].amount)
            item2 += f"<br/>그중 {r_amt}원을 {r_d} 받았고 남은 원금은 {remaining_str}입니다."
        elif len(reps) > 1:
            total_repaid = sum((r.amount for r in reps), Decimal("0"))
            total_s = _pdf_won(total_repaid)
            last_d = _pdf_date(reps[-1].payment_date)
            item2 += (
                f"<br/>그중 총 {total_s}원을 {len(reps)}회에 나누어 받았고 "
                f"남은 원금은 {remaining_str}입니다. (마지막 수령일 {last_d})"
            )

    if as_of is not None:
        deadline = as_of + _timedelta(days=7)
        deadline_s = _pdf_date(deadline)
        item4 = (
            f"4. 이에 발신인은 본 내용증명을 통하여 귀하에게 "
            f"<b>{deadline_s}</b>까지 위 원리금 합계액(금 {total_disp})을 보내 "
            f"주시기 바랍니다."
        )
    else:
        item4 = (
            f"4. 이에 발신인은 본 내용증명을 통하여 귀하에게 "
            f"위 원리금 합계액(금 {total_str})을 보내 주시기 바랍니다."
        )

    item3 = "3. 발신인은 변제기 이후 현재까지 남은 돈을 받지 못했습니다."
    if fact_sentences:
        fact_block = "<br/><br/>".join(_xml_escape(s) for s in fact_sentences)
        body_text = (
            f"1. 귀하의 무궁한 발전을 기원합니다.<br/><br/>"
            f"{item2}<br/><br/>"
            f"{fact_block}<br/><br/>"
            f"{item3}<br/><br/>"
            f"{item4}"
        )
    else:
        body_text = (
            f"1. 귀하의 무궁한 발전을 기원합니다.<br/><br/>"
            f"{item2}<br/><br/>"
            f"{item3}<br/><br/>"
            f"{item4}"
        )
    elements.append(Paragraph(body_text, body_style))
    elements.append(Spacer(1, 25))

    if as_of is not None:
        date_str = f"{as_of.year}년 {as_of.month}월 {as_of.day}일"
    else:
        date_str = "____년 __월 __일"
    elements.append(Paragraph(date_str, center_style))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(f"<b>발신인: {p_name} (인/서명)</b>", right_style))

    def _footer(canvas: Any, _doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(KO_FONT, 7)
        canvas.setFillColor(colors.grey)
        canvas.drawCentredString(A4[0] / 2, 30, deps.NOTICE_KO)
        canvas.restoreState()

    doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
    return str(os_target)


def _state_extra_map(state: CaseState, names: List[str]) -> Dict[str, str]:
    """Forward-compatible lookup for M4a/M4b path maps on the case state."""
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
    """Redacted image per ex_id (M4a state map or conventional filenames)."""
    extra = _state_extra_map(state, [
        "redacted", "redactions", "redacted_files", "redacted_images",
        "redaction_paths", "privacy_redacted",
    ])
    evidence_base = evidence_dir(state.case_id)
    files_base = files_dir(state.case_id)
    resolved: Dict[str, str] = {}
    for record in state.evidence:
        ex_id = record.ex_id
        candidates: List[Path] = []
        if ex_id in extra:
            candidates.append(Path(extra[ex_id]))
        for base in (evidence_base, files_base):
            for name in (
                f"{ex_id}_redacted.png", f"{ex_id}_redacted.jpg",
                f"{ex_id}_redacted.jpeg", f"redacted_{ex_id}.png",
                f"{ex_id}_preview_redacted.png",
            ):
                candidates.append(base / name)
        hit = _first_existing(candidates)
        if hit is not None:
            resolved[ex_id] = str(hit)
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
    packet = deps.KoreanLegalDocumentCompiler.generate_ecourt_clipboard_packet(
        loan_fact, verification, as_of=as_of, fact_sentences=fact_sentences
    )
    claim_purpose = packet.get("claim_purpose", "")
    claim_cause = patch_repayment_sentence(
        packet.get("claim_cause_payment_order", ""), loan_fact, verification,
        as_of, calc.allocations, calc.remaining_principal,
    )
    claim_cause_lawsuit = patch_repayment_sentence(
        packet.get("claim_cause_lawsuit", ""), loan_fact, verification,
        as_of, calc.allocations, calc.remaining_principal,
    )
    evidence_dicts = [record.model_dump() for record in state.evidence]
    pre_texts = [claim_purpose, claim_cause, *fact_sentences, claim_cause_lawsuit]
    for record in evidence_dicts:
        pre_texts.append(str(record.get("label", "")))
        pre_texts.append(str(record.get("filename", "")))
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
    content_pdf = target_dir / "content_proof.pdf"
    generate_content_proof_pdf_fixed(
        loan_fact, verification, str(content_pdf), as_of=as_of,
        fact_sentences=fact_sentences, allocations=calc.allocations,
        remaining=calc.remaining_principal,
    )
    exhibits_pdf = target_dir / "exhibits.pdf"
    evidence_list_pdf = target_dir / "evidence_list.pdf"
    exhibit_bundle_mod.build_exhibits_pdf(
        evidence_dicts, evidence_dir(state.case_id), str(exhibits_pdf),
        redacted=discover_redacted_paths(state),
        stills=discover_still_paths(state),
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
