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
VIDEO_PLACEHOLDER = (
    "영상 증거, 파일 별도 제출. 이 영상은 판독·가림을 하지 않은 원본이므로 "
    "제출 전에 계좌·주민번호·연락처·얼굴이 보이는지 직접 확인하세요."
)
SAMPLE_FOOTER = "SAMPLE / 데모용 · 합성 예시 자료"


def is_sample_case(confirmed: Optional[Mapping[str, Any]]) -> bool:
    """True for the synthetic sample set (both party names end in "(SAMPLE)")."""
    fields = (confirmed or {}).get("fields", {}) or {}
    return all(str(fields.get(key, "") or "").strip().endswith("(SAMPLE)")
               for key in ("creditor_name", "debtor_name"))


def _sample_footer(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setFont(KO_FONT, 8)
    canvas.setFillColor(colors.HexColor("#b00020"))
    canvas.drawCentredString(A4[0] / 2.0, 22, SAMPLE_FOOTER)
    canvas.restoreState()
PDF_PLACEHOLDER = "PDF 증거, 파일 별도 제출"
# K3: images/PDF previews without a redacted copy embed no picture.
MISSING_REDACTED_LINE = "가림 사본이 없어 이 쪽에 이미지를 넣지 않았습니다. 원본 파일은 따로 제출하세요."
# M5-fix2: flagged previews wait for user confirmation (no picture either).
NEEDS_REVIEW_LINE = "가림 확인이 필요해 이 쪽에 이미지를 넣지 않았습니다."
# K11: cover guide (remove before filing).
COVER_REMOVE_GUIDE = "법원에 낼 때는 이 쪽을 빼세요."

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
    needs_review: Optional[Any] = None,
) -> Tuple[Optional[Path], bool, Optional[str]]:
    """Pick the file to embed for one evidence (K3: redacted copies only).

    Returns ``(path, used_redacted, placeholder)``. Images and PDF previews
    without a redacted copy embed no picture (``MISSING_REDACTED_LINE``,
    or ``NEEDS_REVIEW_LINE`` when the preview awaits user confirmation);
    original bytes never enter the bundle. Video without a still keeps
    ``VIDEO_PLACEHOLDER``.
    """
    base = Path(evidence_dir)
    ex_id = str(_field(record, "ex_id", ""))
    kind = str(_field(record, "kind", "image"))

    def _exists(candidate: Any) -> Optional[Path]:
        if candidate is None:
            return None
        path = Path(str(candidate))
        if not path.is_absolute():
            direct = Path(str(candidate))
            if direct.exists() and direct.is_file():
                return direct
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
    red = _exists((redacted or {}).get(ex_id)) if redacted else None
    if red is not None:
        return (red, True, None)
    try:
        pending = ex_id in (needs_review or set())
    except TypeError:
        pending = False
    if pending:
        return (None, False, NEEDS_REVIEW_LINE)
    return (None, False, MISSING_REDACTED_LINE)


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


# INT-3c F3: document-shaped images (A4 is 1.41) stay on one page so a
# signature box or stamp is never cut; only long screenshots are sliced.
DOCUMENT_MAX_ASPECT = 1.6
# Any pixel darker than near-white counts (light-gray timestamps and chat
# bubbles too), so cuts fall on plain background rows and only truly empty
# slices are dropped.
INK_THRESHOLD = 235
BLANK_SLICE_MIN_INK = 20     # a slice with fewer marked pixels is empty paper
CUT_SEARCH_FRACTION = 0.3    # look for a blank row in the last 30% of a slice


def _row_ink(gray: Any, width: int, height: int) -> List[int]:
    buf = gray.tobytes()
    return [sum(1 for value in buf[y * width:(y + 1) * width]
                if value < INK_THRESHOLD)
            for y in range(height)]


def _cut_rows(row_ink: Sequence[int], max_slice_h: int) -> List[Tuple[int, int]]:
    """Slice bounds that end on the emptiest row near each page limit."""
    height = len(row_ink)
    bounds: List[Tuple[int, int]] = []
    top = 0
    while top < height:
        limit = top + max_slice_h
        if limit >= height:
            bounds.append((top, height))
            break
        start = max(top + 1, limit - int(max_slice_h * CUT_SEARCH_FRACTION))
        window = range(limit, start - 1, -1)
        cut = min(window, key=lambda y: row_ink[y])
        bounds.append((top, cut))
        top = cut
    return bounds


def _slice_tall_image(path: Path, max_w: float, max_h: float) -> List[Path]:
    """Split a tall image so each slice stays legible (K10).

    Slices keep full width; each slice height fits ``max_h`` when scaled to
    ``max_w``. Single-slice images return ``[path]`` (no temp files).
    Document-shaped images are not sliced, cuts fall on the emptiest row
    near the page limit, and near-blank slices are dropped (INT-3c F3).
    """
    size = _image_size(path)
    if not size or size[0] <= 0 or size[1] <= 0:
        return [path]
    width, height = size
    if width <= 0:
        return [path]
    if height / float(width) <= DOCUMENT_MAX_ASPECT:
        return [path]
    scale_w = max_w / float(width)
    if scale_w <= 0:
        return [path]
    max_slice_h = int(max_h / scale_w)
    if max_slice_h <= 0 or height <= max_slice_h:
        return [path]
    try:
        from PIL import Image as _PILImage
        import tempfile as _tempfile
    except Exception:
        return [path]
    try:
        tmpdir = Path(_tempfile.mkdtemp(prefix="exhibit_slice_"))
    except Exception:
        return [path]
    try:
        with _PILImage.open(path) as image:
            mode = image.mode
            row_ink = _row_ink(image.convert("L"), width, height)
            bounds = [(top, bottom) for top, bottom in _cut_rows(row_ink, max_slice_h)
                      if sum(row_ink[top:bottom]) >= BLANK_SLICE_MIN_INK]
            if not bounds or bounds == [(0, height)]:
                return [path]
            total = len(bounds)
            out: List[Path] = []
            for idx, (top, bottom) in enumerate(bounds):
                crop = image.crop((0, top, width, bottom))
                target = tmpdir / f"{path.stem}_p{idx + 1}of{total}.png"
                save_mode = mode if mode in ("RGB", "RGBA", "L") else "RGB"
                try:
                    crop.convert(save_mode).save(target)
                except Exception:
                    crop.save(target)
                out.append(target)
            return out
    except Exception:
        return [path]


def build_exhibits_pdf(
    evidence: Sequence[EvidenceLike],
    evidence_dir: Union[str, Path],
    output_path: Union[str, Path],
    redacted: Optional[Mapping[str, Union[str, Path]]] = None,
    stills: Optional[Mapping[str, Union[str, Path]]] = None,
    needs_review: Optional[Any] = None,
    confirmed: Optional[Mapping[str, Any]] = None,
) -> str:
    """Write the exhibit bundle (cover + evidence pages, K3/K10/K11)."""
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
    guide_style = ParagraphStyle(
        "ExGuide", fontName=KO_FONT_BOLD, fontSize=10, leading=14, alignment=1,
        textColor=colors.HexColor("#333333"), spaceBefore=16,
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
        # M5-fix2: cover shows the role/kind display name (same as list).
        shown = str(_field(record, "filename", ""))
        if confirmed is not None:
            try:
                shown = evidence_display_name(record, confirmed)
            except Exception:
                pass
        rows.append([
            Paragraph(label, meta_style),
            Paragraph(_xml_escape(shown), meta_style),
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
    elements.append(Paragraph(_xml_escape(COVER_REMOVE_GUIDE), guide_style))
    elements.append(Paragraph(_xml_escape(NOTICE_KO), notice_style))
    elements.append(Paragraph(_xml_escape(DISCLAIMER_KO), disclaimer_style))

    temp_dirs: set = set()
    try:
        for position, record in enumerate(ordered):
            label = str(_field(record, "label", ""))
            filename = str(_field(record, "filename", ""))
            sha = _sha_short(str(_field(record, "sha256", "")))
            sub = _xml_escape(f"{filename} · SHA-256 앞 8자리 {sha}" if sha else filename)
            source, _used_redacted, placeholder = resolve_evidence_source(
                record, evidence_dir, redacted=redacted, stills=stills,
                needs_review=needs_review,
            )
            if source is None:
                elements.append(PageBreak())
                elements.append(Paragraph(_xml_escape(label), head_style))
                if sub:
                    elements.append(Paragraph(sub, meta_style))
                elements.append(Spacer(1, 40))
                elements.append(Paragraph(
                    _xml_escape(placeholder or MISSING_REDACTED_LINE), body_style,
                ))
                continue
            slices = _slice_tall_image(source, usable_w, usable_h - 120)
            try:
                for candidate in slices:
                    if candidate != source:
                        temp_dirs.add(str(candidate.parent))
            except Exception:
                pass
            total = len(slices)
            for idx, part in enumerate(slices, start=1):
                elements.append(PageBreak())
                header = label if total <= 1 else f"{label} ({idx}/{total})"
                elements.append(Paragraph(_xml_escape(header), head_style))
                if sub:
                    elements.append(Paragraph(sub, meta_style))
                elements.append(_scaled_image(part, usable_w, usable_h - 120))
            _ = position
        if is_sample_case(confirmed):
            # Every page of a sample bundle says it is synthetic, not only
            # the first slice's image band.
            doc.build(elements, onFirstPage=_sample_footer, onLaterPages=_sample_footer)
        else:
            doc.build(elements)
    finally:
        import shutil as _shutil

        for tmp in temp_dirs:
            try:
                _shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass
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


def _repayment_ex_ids_sorted(confirmed: Mapping[str, Any]) -> List[str]:
    roles = _roles_of(confirmed)
    ids = [ex_id for ex_id, role in roles.items() if role == "repayment"]
    return sorted(ids, key=ex_num)


def _as_of_day(confirmed: Mapping[str, Any]):
    raw = (confirmed or {}).get("as_of", "")
    match = _ISO_DATE_RE.match(str(raw or "").strip())
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _repayments_of(confirmed: Mapping[str, Any]) -> List[Dict[str, Any]]:
    fields = _fields_of(confirmed)
    repayments = fields.get("repayments", []) or []
    if not isinstance(repayments, list):
        return []
    entries = [entry for entry in repayments if isinstance(entry, dict)]
    # M5-fix2: repayments after as_of are never rendered (calculation drops
    # them, so the evidence list hides their details to match G1b).
    as_of = _as_of_day(confirmed)
    if as_of is None:
        return entries
    kept: List[Dict[str, Any]] = []
    for entry in entries:
        match = _ISO_DATE_RE.match(str(entry.get("date", "") or "").strip())
        if not match:
            kept.append(entry)
            continue
        try:
            pay = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            kept.append(entry)
            continue
        if pay <= as_of:
            kept.append(entry)
    return kept


def _own_repayments(
    record: EvidenceLike, confirmed: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    """Repayments belonging to this evidence (K9: per-evidence only)."""
    ex_id = str(_field(record, "ex_id", ""))
    repayments = _repayments_of(confirmed)
    ordered = _repayment_ex_ids_sorted(confirmed)
    if ex_id not in ordered:
        return []
    # Single repayment evidence covers every repayment (mapping unknown).
    if len(ordered) == 1:
        return repayments
    try:
        position = ordered.index(ex_id)
    except ValueError:
        return []
    if 0 <= position < len(repayments):
        return [repayments[position]]
    return []


def evidence_display_name(
    record: EvidenceLike,
    confirmed: Mapping[str, Any],
) -> str:
    """증거 이름 cell by role/kind only (M5-fix2; never filenames)."""
    roles = _roles_of(confirmed)
    ex_id = str(_field(record, "ex_id", ""))
    kind = str(_field(record, "kind", ""))
    role = roles.get(ex_id, "other")
    if role == "loan_agreement":
        return "차용증"
    if kind == "video":
        return "대화 화면 녹화"
    if kind == "pdf":
        return "문서 사본"
    if role in ("loan_transfer", "repayment"):
        return "송금 기록 화면"
    return "대화 화면 캡처"


def evidence_created_label(
    record: EvidenceLike,
    confirmed: Mapping[str, Any],
    readings: Optional[Sequence[Mapping[str, Any]]] = None,
) -> str:
    """작성일 cell: confirmed dates only (K9, no estimation)."""
    _ = readings
    fields = _fields_of(confirmed)
    roles = _roles_of(confirmed)
    ex_id = str(_field(record, "ex_id", ""))
    role = roles.get(ex_id, "other")
    if role == "loan_transfer" and fields.get("loan_date"):
        return fmt_kr_date(fields["loan_date"])
    if role == "repayment":
        own = _own_repayments(record, confirmed)
        if own and own[0].get("date"):
            return fmt_kr_date(own[0].get("date"))
        return "-"
    return "-"


def evidence_summary(
    record: EvidenceLike,
    confirmed: Mapping[str, Any],
) -> str:
    """내용 cell: confirmed facts for this evidence only (K9)."""
    fields = _fields_of(confirmed)
    roles = _roles_of(confirmed)
    ex_id = str(_field(record, "ex_id", ""))
    kind = str(_field(record, "kind", ""))
    role = roles.get(ex_id, "other")
    creditor = str(fields.get("creditor_name", "") or "").strip()
    debtor = str(fields.get("debtor_name", "") or "").strip()
    parties = f"{creditor} → {debtor}" if creditor and debtor else ""
    legs = f"{debtor} → {creditor}" if creditor and debtor else ""
    if role == "loan_transfer":
        loan_date = fmt_kr_date(fields.get("loan_date", ""))
        amount = fmt_amount_won(fields.get("principal", ""))
        core = f"{loan_date} {amount} 이체 기록".strip()
        return f"{parties}, {core}" if parties else core
    if role == "repayment":
        own = _own_repayments(record, confirmed)
        if len(own) == 1:
            when = fmt_kr_date(own[0].get("date", ""))
            amount = fmt_amount_won(own[0].get("amount", ""))
            core = f"{when} {amount} 이체 기록".strip()
            return f"{legs}, {core}" if legs else core
        if len(own) > 1:
            parts = [
                f"{fmt_kr_date(entry.get('date', ''))} "
                f"{fmt_amount_won(entry.get('amount', ''))}".strip()
                for entry in own
            ]
            joined = "; ".join(part for part in parts if part)
            core = f"변제 이체 기록 {len(parts)}건({joined})" if joined else "변제 이체 기록"
            return f"{legs}, {core}" if legs else core
        return "변제 이체 기록"
    if role == "loan_agreement":
        return "차용증 사본"
    if kind == "video":
        return "대화 기록"
    if kind == "pdf":
        return "문서 사본"
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
        ev_name = _xml_escape(evidence_display_name(record, confirmed))
        created = _xml_escape(evidence_created_label(record, confirmed, readings))
        summary = _xml_escape(evidence_summary(record, confirmed))
        rows.append([
            Paragraph(label, cell_style),
            Paragraph(ev_name, cell_style),
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
    "COVER_REMOVE_GUIDE",
    "MISSING_REDACTED_LINE",
    "NEEDS_REVIEW_LINE",
    "PDF_PLACEHOLDER",
    "PRE_REDACTION_MARK",
    "VIDEO_PLACEHOLDER",
    "build_evidence_list_pdf",
    "build_exhibits_pdf",
    "evidence_created_label",
    "evidence_display_name",
    "evidence_summary",
    "ex_num",
    "fmt_amount_won",
    "fmt_kr_date",
    "resolve_evidence_source",
]
