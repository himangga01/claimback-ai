"""Exhibit bundle + evidence list PDFs (M5, rule-based).

``build_exhibits_pdf`` renders one page per evidence in ex_id order with a
cover page. ``build_evidence_list_pdf`` renders the "evidence list" table
(``호증 번호, 증거 이름, 작성일, 내용``) from user-confirmed facts only.
"""

from __future__ import annotations

import os
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Image as RLImage,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.naming import DISCLAIMER_KO, NOTICE_KO
from app.services.pdf_compiler import KO_FONT, KO_FONT_BOLD

_EX_RE = re.compile(r"^EX(\d+)$", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")

# Body copy markers (not legal notices).
PRE_REDACTION_MARK = "가림 처리 전 사본"
VIDEO_PLACEHOLDER = "영상 증거, 파일 별도 제출"
PDF_PLACEHOLDER = "PDF 증거, 파일 별도 제출"

EvidenceLike = Union[Mapping[str, Any], Any]


def ex_num(ex_id: str) -> int:
    match = _EX_RE.match(str(ex_id or "").strip())
    if not match:
        return 10**9
    try:
        return int(match.group(1))
    except ValueError:
        return 10**9


def _field(record: EvidenceLike, name: str, default: Any = "") -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _sorted_evidence(evidence: Sequence[EvidenceLike]) -> List[EvidenceLike]:
    return sorted(evidence, key=lambda r: ex_num(str(_field(r, "ex_id", ""))))


def fmt_amount_won(amount: Any) -> str:
    text = str(amount).strip().replace(",", "").replace("원", "")
    try:
        number = int(Decimal(text))
    except (InvalidOperation, ValueError, AttributeError):
        return f"{amount}원"
    return f"{number:,}원"


def fmt_kr_date(iso: Any) -> str:
    match = _ISO_DATE_RE.match(str(iso or "").strip())
    if not match:
        return str(iso)
    year, month, day = (int(part) for part in match.groups())
    return f"{year}. {month}. {day}."


def _sha_short(sha256: str) -> str:
    return str(sha256 or "")[:8]


def _image_size(path: Path) -> Optional[Tuple[int, int]]:
    try:
        from PIL import Image as PILImage

        with PILImage.open(path) as image:
            return (int(image.width), int(image.height))
    except Exception:
        return None


def _scaled_image(path: Path, max_w: float, max_h: float) -> RLImage:
    size = _image_size(path)
    image = RLImage(str(path))
    if not size or size[0] <= 0 or size[1] <= 0:
        image.drawWidth = max_w
        image.drawHeight = max_h
        return image
    width, height = size
    scale = min(max_w / width, max_h / height, 1.0)
    image.drawWidth = max(1.0, width * scale)
    image.drawHeight = max(1.0, height * scale)
    return image


def resolve_evidence_source(
    record: EvidenceLike,
    evidence_dir: Union[str, Path],
    redacted: Optional[Mapping[str, Union[str, Path]]] = None,
    stills: Optional[Mapping[str, Union[str, Path]]] = None,
) -> Tuple[Optional[Path], bool, Optional[str]]:
    """Pick the file to embed for one evidence.

    Returns ``(path, used_redacted, placeholder)``. ``path`` is None when a
    text placeholder should be rendered instead (video without a still, PDF
    without a preview).
    """
    base = Path(evidence_dir)
    ex_id = str(_field(record, "ex_id", ""))
    kind = str(_field(record, "kind", "image"))

    def _exists(candidate: Any) -> Optional[Path]:
        if candidate is None:
            return None
        path = Path(str(candidate))
        if not path.is_absolute():
            path = base / path.name if path.name else base / str(candidate)
            if not path.exists():
                alt = Path(str(candidate))
                path = alt if alt.exists() else path
        return path if path.exists() and path.is_file() else None

    if kind == "video":
        still = _exists((stills or {}).get(ex_id)) if stills else None
        if still is not None:
            return (still, False, None)
        return (None, False, VIDEO_PLACEHOLDER)
    if kind == "pdf":
        red = _exists((redacted or {}).get(ex_id)) if redacted else None
        if red is not None:
            return (red, True, None)
        preview = base / f"{ex_id}_preview.png"
        if preview.exists() and preview.is_file():
            return (preview, False, None)
        return (None, False, PDF_PLACEHOLDER)
    red = _exists((redacted or {}).get(ex_id)) if redacted else None
    if red is not None:
        return (red, True, None)
    stored = str(_field(record, "stored_name", "") or "")
    if stored:
        original = base / Path(stored).name
        if original.exists() and original.is_file():
            return (original, False, None)
    return (None, False, PDF_PLACEHOLDER)


def _doc_template(output_path: Union[str, Path]) -> SimpleDocTemplate:
    target = Path(str(output_path))
    target.parent.mkdir(parents=True, exist_ok=True)
    return SimpleDocTemplate(
        str(target),
        pagesize=A4,
        rightMargin=50,
        leftMargin=50,
        topMargin=50,
        bottomMargin=50,
    )


def build_exhibits_pdf(
    evidence: Sequence[EvidenceLike],
    evidence_dir: Union[str, Path],
    output_path: Union[str, Path],
    redacted: Optional[Mapping[str, Union[str, Path]]] = None,
    stills: Optional[Mapping[str, Union[str, Path]]] = None,
) -> str:
    """Write the exhibit bundle (cover + one page per evidence)."""
    ordered = _sorted_evidence(evidence)
    doc = _doc_template(output_path)
    usable_w = A4[0] - 100
    usable_h = A4[1] - 100

    title_style = ParagraphStyle(
        "ExTitle", fontName=KO_FONT_BOLD, fontSize=20, leading=28,
        alignment=1, spaceAfter=12,
    )
    subtitle_style = ParagraphStyle(
        "ExSubtitle", fontName=KO_FONT, fontSize=11, leading=16,
        alignment=1, spaceAfter=18,
    )
    head_style = ParagraphStyle(
        "ExHead", fontName=KO_FONT_BOLD, fontSize=14, leading=20, spaceAfter=4,
    )
    meta_style = ParagraphStyle(
        "ExMeta", fontName=KO_FONT, fontSize=9, leading=13,
        textColor=colors.HexColor("#444444"), spaceAfter=10,
    )
    body_style = ParagraphStyle(
        "ExBody", fontName=KO_FONT, fontSize=11, leading=17, spaceAfter=8,
    )
    warn_style = ParagraphStyle(
        "ExWarn", fontName=KO_FONT, fontSize=9, leading=13, alignment=1,
        textColor=colors.HexColor("#777777"), spaceBefore=10,
    )
    notice_style = ParagraphStyle(
        "ExNotice", fontName=KO_FONT, fontSize=7, leading=10, alignment=1,
        textColor=colors.grey, spaceBefore=24,
    )
    disclaimer_style = ParagraphStyle(
        "ExDisclaimer", fontName=KO_FONT, fontSize=7, leading=10, alignment=1,
        textColor=colors.grey, spaceBefore=6,
    )

    elements: List[Any] = []
    elements.append(Paragraph("갑 호 증", title_style))
    elements.append(Paragraph("증거 통합 사본", subtitle_style))
    rows: List[List[Any]] = [
        [Paragraph("<b>호증 번호</b>", meta_style),
         Paragraph("<b>증거 이름</b>", meta_style)]
    ]
    for record in ordered:
        label = _xml_escape(str(_field(record, "label", "")))
        filename = _xml_escape(str(_field(record, "filename", "")))
        rows.append([
            Paragraph(label, meta_style),
            Paragraph(filename, meta_style),
        ])
    index = Table(rows, colWidths=[140, usable_w - 140])
    index.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f2f2")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(index)
    elements.append(Paragraph(_xml_escape(NOTICE_KO), notice_style))
    elements.append(Paragraph(_xml_escape(DISCLAIMER_KO), disclaimer_style))

    for position, record in enumerate(ordered):
        elements.append(PageBreak())
        label = str(_field(record, "label", ""))
        filename = str(_field(record, "filename", ""))
        sha = _sha_short(str(_field(record, "sha256", "")))
        header = _xml_escape(label)
        sub = _xml_escape(f"{filename} · SHA-256 앞 8자리 {sha}" if sha else filename)
        elements.append(Paragraph(header, head_style))
        if sub:
            elements.append(Paragraph(sub, meta_style))
        source, used_redacted, placeholder = resolve_evidence_source(
            record, evidence_dir, redacted=redacted, stills=stills,
        )
        if source is not None:
            elements.append(_scaled_image(source, usable_w, usable_h - 120))
            if not used_redacted and str(_field(record, "kind", "")) != "video":
                elements.append(Paragraph(_xml_escape(PRE_REDACTION_MARK), warn_style))
        else:
            elements.append(Spacer(1, 40))
            elements.append(Paragraph(
                _xml_escape(placeholder or PDF_PLACEHOLDER), body_style,
            ))
        _ = position
    doc.build(elements)
    return str(output_path)


# --- evidence list ------------------------------------------------------------


def _roles_of(confirmed: Mapping[str, Any]) -> Dict[str, str]:
    roles = (confirmed or {}).get("evidence_roles", {}) or {}
    return {str(key): str(value) for key, value in roles.items()} if isinstance(roles, dict) else {}


def _fields_of(confirmed: Mapping[str, Any]) -> Dict[str, Any]:
    fields = (confirmed or {}).get("fields", {}) or {}
    return dict(fields) if isinstance(fields, dict) else {}


def _highlight_ex_ids(confirmed: Mapping[str, Any]) -> set:
    out: set = set()
    highlight = (confirmed or {}).get("highlight", []) or []
    if isinstance(highlight, list):
        for ref in highlight:
            text = str(ref or "")
            if ":" in text:
                out.add(text.split(":", 1)[0])
    return out


def _reading_dates(readings: Optional[Sequence[Mapping[str, Any]]]) -> Dict[str, str]:
    found: Dict[str, str] = {}
    for reading in readings or []:
        if not isinstance(reading, Mapping):
            continue
        ex_id = str(reading.get("ex_id", ""))
        if not ex_id or ex_id in found:
            continue
        for item in reading.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            normalized = item.get("normalized")
            if isinstance(normalized, str) and _ISO_DATE_RE.match(normalized.strip()):
                found[ex_id] = normalized.strip()
                break
    return found


def evidence_created_label(
    record: EvidenceLike,
    confirmed: Mapping[str, Any],
    readings: Optional[Sequence[Mapping[str, Any]]] = None,
) -> str:
    """작성일 cell: confirmed dates by role, readings fallback, else '-'."""
    fields = _fields_of(confirmed)
    roles = _roles_of(confirmed)
    ex_id = str(_field(record, "ex_id", ""))
    kind = str(_field(record, "kind", ""))
    role = roles.get(ex_id, "other")
    if kind == "video":
        return "-"
    if role == "loan_transfer" and fields.get("loan_date"):
        return fmt_kr_date(fields["loan_date"])
    if role == "repayment":
        repayments = fields.get("repayments", []) or []
        if isinstance(repayments, list) and repayments and isinstance(repayments[0], dict):
            first = repayments[0].get("date")
            if first:
                return fmt_kr_date(first)
        return "-"
    filename = str(_field(record, "filename", "")).lower()
    if kind == "pdf" or "iou" in filename or "차용" in filename:
        if fields.get("loan_date"):
            return fmt_kr_date(fields["loan_date"])
    fallback = _reading_dates(readings).get(ex_id)
    if fallback:
        return fmt_kr_date(fallback)
    return "-"


def evidence_summary(
    record: EvidenceLike,
    confirmed: Mapping[str, Any],
) -> str:
    """내용 cell: user-confirmed facts only, no legal evaluation."""
    fields = _fields_of(confirmed)
    roles = _roles_of(confirmed)
    ex_id = str(_field(record, "ex_id", ""))
    kind = str(_field(record, "kind", ""))
    role = roles.get(ex_id, "other")
    creditor = str(fields.get("creditor_name", "") or "").strip()
    debtor = str(fields.get("debtor_name", "") or "").strip()
    parties = f"{creditor} → {debtor}" if creditor and debtor else ""
    if kind == "video":
        return VIDEO_PLACEHOLDER
    if role == "loan_transfer":
        loan_date = fmt_kr_date(fields.get("loan_date", ""))
        amount = fmt_amount_won(fields.get("principal", ""))
        core = f"{loan_date} {amount} 이체 기록".strip()
        return f"{parties}, {core}" if parties else core
    if role == "repayment":
        repayments = fields.get("repayments", []) or []
        if isinstance(repayments, list) and len(repayments) == 1 and isinstance(repayments[0], dict):
            when = fmt_kr_date(repayments[0].get("date", ""))
            amount = fmt_amount_won(repayments[0].get("amount", ""))
            legs = f"{debtor} → {creditor}" if creditor and debtor else ""
            core = f"{when} {amount} 이체 기록".strip()
            return f"{legs}, {core}" if legs else core
        if isinstance(repayments, list) and len(repayments) > 1:
            parts = []
            for entry in repayments:
                if not isinstance(entry, dict):
                    continue
                parts.append(
                    f"{fmt_kr_date(entry.get('date', ''))} "
                    f"{fmt_amount_won(entry.get('amount', ''))}".strip()
                )
            joined = "; ".join(part for part in parts if part)
            return f"변제 이체 기록 {len(parts)}건({joined})" if joined else "변제 이체 기록"
        return "변제 이체 기록"
    filename = str(_field(record, "filename", "")).lower()
    if kind == "pdf" or "iou" in filename or "차용" in filename:
        loan_date = fmt_kr_date(fields.get("loan_date", ""))
        if loan_date and fields.get("loan_date"):
            return f"{loan_date} 작성 차용증 사본"
        return "차용증 사본"
    if ex_id in _highlight_ex_ids(confirmed):
        return "대화 기록(사용자 지정 발화 포함)"
    return "대화 기록"


def build_evidence_list_pdf(
    evidence: Sequence[EvidenceLike],
    confirmed: Mapping[str, Any],
    output_path: Union[str, Path],
    readings: Optional[Sequence[Mapping[str, Any]]] = None,
    calculation: Optional[Mapping[str, Any]] = None,
) -> str:
    """Write the evidence list table (no notices in the body)."""
    _ = calculation
    ordered = _sorted_evidence(evidence)
    doc = _doc_template(output_path)
    usable_w = A4[0] - 100

    title_style = ParagraphStyle(
        "EvListTitle", fontName=KO_FONT_BOLD, fontSize=18, leading=24,
        alignment=1, spaceAfter=16,
    )
    cell_style = ParagraphStyle(
        "EvListCell", fontName=KO_FONT, fontSize=9, leading=13,
    )
    head_cell_style = ParagraphStyle(
        "EvListHead", fontName=KO_FONT_BOLD, fontSize=9, leading=13,
        alignment=1,
    )
    _ = getSampleStyleSheet

    elements: List[Any] = [Paragraph("증 거 목 록", title_style)]
    rows: List[List[Any]] = [[
        Paragraph("호증 번호", head_cell_style),
        Paragraph("증거 이름", head_cell_style),
        Paragraph("작성일", head_cell_style),
        Paragraph("내용", head_cell_style),
    ]]
    for record in ordered:
        label = _xml_escape(str(_field(record, "label", "")))
        filename = _xml_escape(str(_field(record, "filename", "")))
        created = _xml_escape(evidence_created_label(record, confirmed, readings))
        summary = _xml_escape(evidence_summary(record, confirmed))
        rows.append([
            Paragraph(label, cell_style),
            Paragraph(filename, cell_style),
            Paragraph(created, cell_style),
            Paragraph(summary, cell_style),
        ])
    table = Table(rows, colWidths=[70, 110, 80, usable_w - 260], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#666666")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f2f2")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(table)
    doc.build(elements)
    return str(output_path)


__all__ = [
    "PRE_REDACTION_MARK",
    "VIDEO_PLACEHOLDER",
    "PDF_PLACEHOLDER",
    "build_evidence_list_pdf",
    "build_exhibits_pdf",
    "evidence_created_label",
    "evidence_summary",
    "ex_num",
    "fmt_amount_won",
    "fmt_kr_date",
    "resolve_evidence_source",
]
