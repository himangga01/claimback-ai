import os
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional
from xml.sax.saxutils import escape as _xml_escape
from pypdf import PdfReader, PdfWriter

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.schemas.loan_fact import LoanFactSchema, VerificationResult, CurrencyEnum

try:
    from app.services.naming import NOTICE_KO
except Exception:
    NOTICE_KO = "본인 작성용 초안, 법률 자문 아님"


# 한글 폰트 등록 (NanumGothic 번들)
FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "fonts")
NANUM_REGULAR = os.path.join(FONT_DIR, "NanumGothic-Regular.ttf")
NANUM_BOLD = os.path.join(FONT_DIR, "NanumGothic-Bold.ttf")

if os.path.exists(NANUM_REGULAR):
    pdfmetrics.registerFont(TTFont("NanumGothic", NANUM_REGULAR))
    pdfmetrics.registerFont(TTFont("NanumGothic-Bold", NANUM_BOLD))
    KO_FONT = "NanumGothic"
    KO_FONT_BOLD = "NanumGothic-Bold"
else:
    sys_font = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
    if os.path.exists(sys_font):
        pdfmetrics.registerFont(TTFont("ZenHei", sys_font, subfontIndex=0))
        KO_FONT = "ZenHei"
        KO_FONT_BOLD = "ZenHei"
    else:
        KO_FONT = "Helvetica"
        KO_FONT_BOLD = "Helvetica-Bold"


def _fmt_kr_date(d: date) -> str:
    return f"{d.year}. {d.month}. {d.day}."


def _fmt_won(amount: Decimal) -> str:
    return f"{int(amount):,}"


def _fmt_rate(rate: Decimal) -> str:
    return format(rate.normalize(), "f")


# --- M5-fix1 K6: shared wording (single source for content proof + ecourt) ---

KANA_ORDER = ["가", "나", "다", "라", "마", "바", "사", "아", "자", "차",
              "카", "타", "파", "하"]


def kana_label(position: int) -> str:
    """1-based approval-sentence label (가. 나. 다. …, then (n))."""
    if 1 <= position <= len(KANA_ORDER):
        return f"{KANA_ORDER[position - 1]}."
    return f"({position})"


import re as _re


_BRACKET_CITE_RE = _re.compile(r"\[갑 제(\d+)호증\]")
_PAREN_CITE_RE = _re.compile(r"\(갑 제(\d+)호증\)")
_NUMBERED_RE = _re.compile(r"^((?:[가-하]\.|\(\d+\))\s+)")


def _split_number_prefix(text: str):
    m = _NUMBERED_RE.match(text or "")
    if m:
        return m.group(1), (text or "")[m.end():]
    return "", (text or "")


def _clean_spaces(text: str) -> str:
    out = _re.sub(r"[ \t]{2,}", " ", text or "")
    out = _re.sub(r"\s+\.", ".", out)
    return out.strip()


def format_letter_fact(text: str, creditor_name: str = "", debtor_name: str = "") -> str:
    """Letter-style fact: strip cites/user marks (M5-fix2: no char replace).

    Name voice (본인/귀하) comes from slot re-rendering in the packager;
    ``creditor_name``/``debtor_name`` are kept for backward compatibility
    and ignored so quotes keep their original wording.
    """
    _ = (creditor_name, debtor_name)
    prefix, body = _split_number_prefix(text)
    body = _BRACKET_CITE_RE.sub("", body)
    body = _PAREN_CITE_RE.sub("", body)
    body = body.replace("[[USER]]", "").replace("(사용자 진술)", "")
    body = _clean_spaces(body).strip()
    if body and not body.endswith((".", "?", "!")):
        body = f"{body}."
    return f"{prefix}{body}".strip()


def format_ecourt_fact(text: str) -> str:
    """Ecourt-style fact: (갑 제N호증) before period, no user marks (K8).

    M5-fix2: multiple cites merge into one tail
    (``(갑 제1호증)(갑 제6호증).``) so no ``.(`` is left behind.
    """
    prefix, body = _split_number_prefix(text)
    body = body.replace("[[USER]]", "").replace("(사용자 진술)", "")
    cites = _BRACKET_CITE_RE.findall(body)
    if cites:
        body = _BRACKET_CITE_RE.sub("", body)
        body = _clean_spaces(body).strip()
        if body.endswith("."):
            body = body[:-1].rstrip()
        cites_str = "".join(f"(갑 제{n}호증)" for n in cites)
        body = f"{body}{cites_str}." if body else f"{cites_str}."
        return f"{prefix}{body}".strip()
    body = _clean_spaces(body).strip()
    if body and not body.endswith((".", "?", "!")):
        body = f"{body}."
    return f"{prefix}{body}".strip()


def format_parties_text(creditor, debtor) -> str:
    """Ecourt parties block (real names; INT-3 task 3 checks this text)."""
    return (
        f"채권자: {creditor.name}\n"
        f"주소: {creditor.address or '주소 불명'}\n"
        f"연락처: {creditor.phone or '연락처 불명'}\n\n"
        f"채무자: {debtor.name}\n"
        f"주소: {debtor.address or '주소 불명'}\n"
        f"연락처: {debtor.phone or '연락처 불명'}"
    )


def ensure_numbered_facts(sentences) -> List[str]:
    """Prefix kana labels when missing; keep existing labels (K6)."""
    out: List[str] = []
    for idx, raw in enumerate(list(sentences or []), start=1):
        text = str(raw or "")
        if _NUMBERED_RE.match(text):
            out.append(text)
        else:
            out.append(f"{kana_label(idx)} {text}".strip())
    return out


def _alloc_value(entry: Any, name: str) -> Decimal:
    from typing import Mapping as _Mapping

    if isinstance(entry, _Mapping):
        raw = entry.get(name, 0)
    else:
        raw = getattr(entry, name, 0)
    if isinstance(raw, Decimal):
        return raw
    try:
        return Decimal(str(raw))
    except Exception:
        return Decimal("0")


def _alloc_date_iso(entry: Any) -> str:
    from typing import Mapping as _Mapping

    if isinstance(entry, _Mapping):
        raw = entry.get("payment_date", "")
    else:
        raw = getattr(entry, "payment_date", "")
    if hasattr(raw, "isoformat"):
        try:
            return str(raw.isoformat())
        except Exception:
            return str(raw)
    return str(raw or "")


def _calc_list(calculation: Any, name: str) -> list:
    from typing import Mapping as _Mapping

    if isinstance(calculation, _Mapping):
        value = calculation.get(name, [])
    else:
        value = getattr(calculation, name, [])
    return list(value or [])


def _calc_field(calculation: Any, name: str, default: Any = None) -> Any:
    from typing import Mapping as _Mapping

    if isinstance(calculation, _Mapping):
        return calculation.get(name, default)
    return getattr(calculation, name, default)


def _floored_totals(calculation: Any) -> List[Decimal]:
    """'충당 시 이자 합계' floored totals in allocation order (less-than check)."""
    totals: List[Decimal] = []
    for step in _calc_list(calculation, "calculation_steps"):
        from typing import Mapping as _Mapping

        if isinstance(step, _Mapping):
            label = str(step.get("label", ""))
            amount = step.get("amount", 0)
        else:
            label = str(getattr(step, "label", ""))
            amount = getattr(step, "amount", 0)
        if label == "충당 시 이자 합계":
            if isinstance(amount, Decimal):
                totals.append(amount)
            else:
                try:
                    totals.append(Decimal(str(amount)))
                except Exception:
                    totals.append(Decimal("0"))
    return totals


def _interest_parts(loan_fact: Any, calculation: Any, index: int):
    """Agreed/delay interest periods for allocation ``index`` (K7)."""
    allocations = _calc_list(calculation, "allocations")
    if index < 0 or index >= len(allocations):
        return []
    entry = allocations[index]
    pay_raw = _alloc_date_iso(entry)
    try:
        pay = date.fromisoformat(pay_raw)
    except ValueError:
        return []
    loan_d = getattr(loan_fact, "loan_date", None)
    due_d = getattr(loan_fact, "due_date", None)
    if not isinstance(loan_d, date) or not isinstance(due_d, date):
        return []
    if index == 0:
        prev = loan_d
    else:
        try:
            prev = date.fromisoformat(_alloc_date_iso(allocations[index - 1]))
        except ValueError:
            prev = loan_d
    agreed = getattr(loan_fact, "agreed_interest_rate", None)
    capped = None
    if agreed is not None:
        try:
            agreed_d = agreed if isinstance(agreed, Decimal) else Decimal(str(agreed))
        except Exception:
            agreed_d = None
        if agreed_d is not None and agreed_d != 0:
            capped = Decimal("20") if agreed_d > Decimal("20") else agreed_d
    try:
        from app.schemas.loan_fact import TransactionKindEnum as _Kind
    except Exception:
        _Kind = None  # type: ignore
    kind = getattr(loan_fact, "transaction_kind", None)
    statutory = Decimal("6") if (_Kind is not None and kind == _Kind.COMMERCIAL) else Decimal("5")
    if capped is not None and capped > statutory:
        pre_rate = capped
    else:
        pre_rate = statutory
    parts = []
    if capped is not None:
        o_start = max(prev, loan_d)
        o_end = min(pay, due_d)
        if o_end > o_start:
            parts.append(("약정이자", o_start + timedelta(days=1), o_end, capped))
    d_start = max(prev, due_d)
    if pay > d_start:
        parts.append(("지연손해금", d_start + timedelta(days=1), pay, pre_rate))
    return parts


def _interest_phrase(parts) -> str:
    """'지연손해금(기간, 연 5%)' style phrase from interest parts (K7)."""
    cleaned = list(parts or [])
    if not cleaned:
        return "지연손해금"
    rates = {_fmt_rate(rate) for _, _, _, rate in cleaned}
    periods = ", ".join(
        f"{_fmt_kr_date(start)}~{_fmt_kr_date(end)}" for _, start, end, _ in cleaned
    )
    if len(cleaned) == 1:
        label = cleaned[0][0]
        return f"{label}({periods}, 연 {next(iter(rates))}%)"
    labels = [label for label, _, _, _ in cleaned]
    if len(rates) == 1:
        return f"{' 및 '.join(labels)}({periods}, 연 {next(iter(rates))}%)"
    joined = " 및 ".join(
        f"{label}({_fmt_kr_date(start)}~{_fmt_kr_date(end)}, 연 {_fmt_rate(rate)}%)"
        for label, start, end, rate in cleaned
    )
    return joined


def _simple_repayment_sentence(allocations: Any, remaining: Any) -> str:
    """Legacy allocation wording (kept for old 2-arg callers)."""
    items = list(allocations or [])
    try:
        rem_d = remaining if isinstance(remaining, Decimal) else Decimal(str(remaining))
    except Exception:
        rem_d = Decimal("0")
    remaining_disp = f"{_fmt_won(rem_d)}원"

    def _clause(entry: Any) -> str:
        raw_d = _alloc_date_iso(entry)
        try:
            when = _fmt_kr_date(date.fromisoformat(raw_d))
        except ValueError:
            when = raw_d
        amount = f"{_fmt_won(_alloc_value(entry, 'payment_amount'))}원"
        cost = _alloc_value(entry, "applied_to_cost")
        interest = _alloc_value(entry, "applied_to_interest")
        principal_part = _alloc_value(entry, "applied_to_principal")
        cost_disp = f"{_fmt_won(cost)}원"
        interest_disp = f"{_fmt_won(interest)}원"
        principal_disp = f"{_fmt_won(principal_part)}원"
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

    if not items:
        return ""
    if len(items) == 1:
        return f"{_clause(items[0])}하여 남은 원금은 {remaining_disp}입니다"
    joined = "; ".join(_clause(entry) for entry in items)
    return f"{joined}하여 남은 원금은 {remaining_disp}입니다"


def build_repayment_sentence(first: Any, second: Any = None, style: str = "ecourt") -> str:
    """Shared repayment wording (K6/K7).

    New: ``build_repayment_sentence(loan_fact, calculation, style)`` with
    periods/rates, multi-join, overpayment, less-than-interest, and
    agreed-interest branches. Old 2-arg ``(allocations, remaining)`` callers
    keep the legacy wording.
    """
    is_new = hasattr(first, "creditor") and hasattr(first, "debtor")
    if not is_new:
        return _simple_repayment_sentence(first, second)
    loan_fact = first
    calculation = second
    use_letter = str(style or "ecourt").lower().startswith("letter")
    subject = "본인은" if use_letter else "채권자는"
    source = "귀하로부터" if use_letter else "채무자로부터"
    allocations = _calc_list(calculation, "allocations")
    if not allocations:
        return ""
    remaining_raw = _calc_field(calculation, "remaining_principal", Decimal("0"))
    over_raw = _calc_field(calculation, "overpayment_amount", Decimal("0"))
    try:
        remaining = remaining_raw if isinstance(remaining_raw, Decimal) else Decimal(str(remaining_raw))
    except Exception:
        remaining = Decimal("0")
    try:
        overpayment = over_raw if isinstance(over_raw, Decimal) else Decimal(str(over_raw))
    except Exception:
        overpayment = Decimal("0")
    remaining_disp = f"{_fmt_won(remaining)}원"
    over_disp = f"{_fmt_won(overpayment)}원"
    floored = _floored_totals(calculation)

    def _one(index: int, entry: Any) -> str:
        raw_d = _alloc_date_iso(entry)
        try:
            when = _fmt_kr_date(date.fromisoformat(raw_d))
        except ValueError:
            when = raw_d
        pay_disp = f"{_fmt_won(_alloc_value(entry, 'payment_amount'))}원"
        cost = _alloc_value(entry, "applied_to_cost")
        interest = _alloc_value(entry, "applied_to_interest")
        principal_part = _alloc_value(entry, "applied_to_principal")
        interest_disp = f"{_fmt_won(interest)}원"
        principal_disp = f"{_fmt_won(principal_part)}원"
        parts = _interest_parts(loan_fact, calculation, index) if interest > 0 else []
        phrase = _interest_phrase(parts) if parts else "지연손해금"
        total_due = floored[index] if 0 <= index < len(floored) else interest
        payment = _alloc_value(entry, "payment_amount")
        if principal_part <= 0 and cost <= 0 and total_due > payment > 0:
            total_disp = f"{_fmt_won(total_due)}원"
            return (
                f"{subject} {when} {source} 받은 {pay_disp}을 그때까지의 "
                f"{phrase} {total_disp} 중 {interest_disp}에 충당"
            )
        if cost > 0 and interest > 0:
            cost_disp = f"{_fmt_won(cost)}원"
            return (
                f"{subject} {when} {source} 받은 {pay_disp}을 비용 {cost_disp}, "
                f"그때까지의 {phrase} {interest_disp}에 먼저 충당하고, "
                f"나머지 {principal_disp}을 원금에 충당"
            )
        if cost > 0 and interest <= 0:
            cost_disp = f"{_fmt_won(cost)}원"
            return (
                f"{subject} {when} {source} 받은 {pay_disp}을 비용 {cost_disp}에 "
                f"먼저 충당하고, 나머지 {principal_disp}을 원금에 충당"
            )
        if interest > 0 and principal_part > 0:
            return (
                f"{subject} {when} {source} 받은 {pay_disp}을 그때까지의 "
                f"{phrase} {interest_disp}에 먼저 충당하고, "
                f"나머지 {principal_disp}을 원금에 충당"
            )
        if interest > 0:
            return (
                f"{subject} {when} {source} 받은 {pay_disp}을 그때까지의 "
                f"{phrase} {interest_disp}에 충당"
            )
        return f"{subject} {when} {source} 받은 {pay_disp}을 원금에 충당"

    clauses = [_one(idx, entry) for idx, entry in enumerate(allocations)]
    # M5-fix2: later clauses drop the repeated subject ("…충당하고, 2026. …").
    stripped = [clauses[0]]
    for clause in clauses[1:]:
        if clause.startswith(f"{subject} "):
            stripped.append(clause[len(subject) + 1:])
        else:
            stripped.append(clause)
    over_tail = (
        f"하여 받은 돈이 원금과 지연손해금을 넘어 "
        f"{over_disp}이 더 들어왔습니다"
    )
    if remaining <= 0 and overpayment > 0:
        if len(clauses) == 1:
            return f"{clauses[0]}{over_tail}"
        return f"{'하고, '.join(stripped)}{over_tail}"
    if len(clauses) == 1:
        return f"{clauses[0]}하여 남은 원금은 {remaining_disp}입니다"
    return f"{'하고, '.join(stripped)}하여 남은 원금은 {remaining_disp}입니다"


class CaliforniaSC100Compiler:
    """
    미국 캘리포니아 소액재판소 공식 Form SC-100 AcroForm 자동 주입 컴파일러 (Rev. Jan 1, 2026)
    """
    TEMPLATE_PATH = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "templates", "ca_sc100_blank.pdf"
    )

    @classmethod
    def compile_sc100(
        cls,
        loan_fact: LoanFactSchema,
        verification: VerificationResult,
        output_path: str,
        county_name: str = "Los Angeles",
        court_info: str = "Superior Court of California, County of Los Angeles",
        as_of: Optional[date] = None,
    ) -> str:
        if not os.path.exists(cls.TEMPLATE_PATH):
            raise FileNotFoundError(f"Template not found at {cls.TEMPLATE_PATH}")

        if loan_fact.currency != CurrencyEnum.USD:
            raise ValueError("California Form SC-100은 USD 통화 기반 사건에만 발급 가능합니다.")

        reader = PdfReader(cls.TEMPLATE_PATH)
        writer = PdfWriter()
        writer.append(reader)

        p = loan_fact.creditor
        d = loan_fact.debtor

        claim_amt_str = f"{verification.total_claim_amount:,.2f}"
        principal_amt_str = f"{verification.reconciled_amount:,.2f}"
        interest_amt_str = f"{verification.calculated_interest:,.2f}"

        explanation = (
            f"Unpaid personal loan of ${principal_amt_str} USD transferred on {loan_fact.loan_date}. "
            f"Defendant agreed to repay by {loan_fact.due_date} but failed to make full payment. "
            f"Prejudgment interest accrued under Cal. Civ. Code section 3289(b) / 3287(a): ${interest_amt_str} USD."
        )

        calc_explanation = (
            f"Principal Balance: ${principal_amt_str} USD. "
            f"Accrued Statutory Interest (10% p.a. from day after due date): ${interest_amt_str} USD. "
            f"Total Amount Claimed: ${claim_amt_str} USD."
        )

        # 텍스트 필드 매핑
        field_data: Dict[str, Any] = {
            # Page 1 Caption
            "SC-100[0].Page1[0].CaptionRight[0].County[0].CourtInfo[0]": f"County of {county_name}\n{court_info}",
            "SC-100[0].Page1[0].CaptionRight[0].CN[0].CaseName[0]": f"{p.name} v. {d.name}",

            # Page 2 Caption
            "SC-100[0].Page2[0].PxCaption[0].Plaintiff[0]": p.name,

            # Item 1: Plaintiff
            "SC-100[0].Page2[0].List1[0].Item1[0].PlaintiffName1[0]": p.name,
            "SC-100[0].Page2[0].List1[0].Item1[0].PlaintiffPhone1[0]": p.phone or "",
            "SC-100[0].Page2[0].List1[0].Item1[0].PlaintiffAddress1[0]": p.address or "",
            "SC-100[0].Page2[0].List1[0].Item1[0].PlaintiffCity1[0]": p.city or "",
            "SC-100[0].Page2[0].List1[0].Item1[0].PlaintiffState1[0]": p.state or "",
            "SC-100[0].Page2[0].List1[0].Item1[0].PlaintiffZip1[0]": p.zip_code or "",

            # Item 2: Defendant
            "SC-100[0].Page2[0].List2[0].item2[0].DefendantName1[0]": d.name,
            "SC-100[0].Page2[0].List2[0].item2[0].DefendantPhone1[0]": d.phone or "",
            "SC-100[0].Page2[0].List2[0].item2[0].DefendantAddress1[0]": d.address or "",
            "SC-100[0].Page2[0].List2[0].item2[0].DefendantCity1[0]": d.city or "",
            "SC-100[0].Page2[0].List2[0].item2[0].DefendantState1[0]": d.state or "",
            "SC-100[0].Page2[0].List2[0].item2[0].DefendantZip1[0]": d.zip_code or "",

            # Item 3: Claim Amount & Why
            "SC-100[0].Page2[0].List3[0].PlaintiffClaimAmount1[0]": claim_amt_str,
            "SC-100[0].Page2[0].List3[0].Lia[0].FillField2[0]": explanation,

            # Page 3: When & Calculation
            "SC-100[0].Page3[0].PxCaption[0].Plaintiff[0]": p.name,
            "SC-100[0].Page3[0].List3[0].Lib[0].Date1[0]": loan_fact.loan_date.strftime("%m/%d/%Y"),
            "SC-100[0].Page3[0].List3[0].Lic[0].FillField1[0]": calc_explanation,
            "SC-100[0].Page3[0].List6[0].item6[0].ZipCode1[0]": d.zip_code or "",

            # 체크박스
            "SC-100[0].Page3[0].List4[0].Item4[0].Checkbox50[0]": "/1",
            "SC-100[0].Page3[0].List5[0].Lia[0].Checkbox5cb[0]": "/1",
            "SC-100[0].Page3[0].List7[0].item7[0].Checkbox60[1]": "/2",
            "SC-100[0].Page3[0].List8[0].item8[0].Checkbox61[1]": "/2",
            "SC-100[0].Page4[0].List9[0].Item9[0].Checkbox62[1]": "/2",
            "SC-100[0].Page4[0].List10[0].li10[0].Checkbox63[0]": "/1" if verification.total_claim_amount > Decimal("2500.00") else "/Off",
            "SC-100[0].Page4[0].List10[0].li10[0].Checkbox63[1]": "/2" if verification.total_claim_amount <= Decimal("2500.00") else "/Off",

            # Item 11 선언 서명부
            "SC-100[0].Page4[0].Sign[0].Date1[0]": as_of.strftime("%m/%d/%Y") if as_of else "",
            "SC-100[0].Page4[0].Sign[0].PlaintiffName1[0]": p.name,
        }

        for page_idx in range(len(writer.pages)):
            writer.update_page_form_field_values(writer.pages[page_idx], field_data)

        writer.set_need_appearances_writer(True)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            writer.write(f)

        return output_path


class KoreanLegalDocumentCompiler:
    """
    한국 트랙: 내용증명 PDF(한글 폰트) 및 전자소송 클립보드 패키지
    """

    @classmethod
    def generate_content_proof_pdf(
        cls,
        loan_fact: LoanFactSchema,
        verification: VerificationResult,
        output_path: str,
        as_of: Optional[date] = None,
        fact_sentences: Optional[List[str]] = None,
    ) -> str:
        """
        내용증명 PDF 생성 (나눔고딕 한글 폰트)
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=50, leftMargin=50,
            topMargin=50, bottomMargin=50,
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'ProofTitle',
            fontName=KO_FONT_BOLD,
            fontSize=18,
            leading=24,
            alignment=1,
            spaceAfter=20
        )
        body_style = ParagraphStyle(
            'ProofBody',
            fontName=KO_FONT,
            fontSize=10,
            leading=16,
            spaceAfter=10
        )
        bold_style = ParagraphStyle(
            'ProofBold',
            fontName=KO_FONT_BOLD,
            fontSize=10,
            leading=16,
            spaceAfter=5
        )
        center_style = ParagraphStyle(
            'ProofCenter',
            fontName=KO_FONT,
            fontSize=10,
            leading=16,
            alignment=1,
            spaceAfter=10
        )
        right_style = ParagraphStyle(
            'ProofRight',
            fontName=KO_FONT_BOLD,
            fontSize=10,
            leading=16,
            alignment=2,
            spaceAfter=5
        )
        notice_style = ParagraphStyle(
            'ProofNotice',
            fontName=KO_FONT,
            fontSize=7,
            leading=10,
            alignment=1,
            textColor=colors.grey,
            spaceBefore=30,
        )

        elements = []
        elements.append(Paragraph("<b>내 용 증 명 서</b>", title_style))
        elements.append(Spacer(1, 15))

        p = loan_fact.creditor
        d = loan_fact.debtor
        p_name = _xml_escape(p.name)
        d_name = _xml_escape(d.name)
        # K8: missing contacts are omitted cell-wise (no "(연락처: 미기재)").
        p_line = p_name if not (p.phone or "").strip() else f"{p_name} (연락처: {_xml_escape(p.phone)})"
        d_line = d_name if not (d.phone or "").strip() else f"{d_name} (연락처: {_xml_escape(d.phone)})"

        info_data = [
            [Paragraph("<b>발 신 인:</b>", bold_style), Paragraph(p_line, body_style)],
        ]
        if (p.address or "").strip():
            info_data.append(["", Paragraph(f"주소: {_xml_escape(p.address)}", body_style)])
        info_data.append(
            [Paragraph("<b>수 신 인:</b>", bold_style), Paragraph(d_line, body_style)]
        )
        if (d.address or "").strip():
            info_data.append(["", Paragraph(f"주소: {_xml_escape(d.address)}", body_style)])
        info_data.append(
            [Paragraph("<b>제    목:</b>", bold_style), Paragraph("<b>대여금 반환 청구의 건</b>", bold_style)]
        )
        info_table = Table(info_data, colWidths=[65, 430])
        info_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
            ('TOPPADDING', (0,0), (-1,-1), 2),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 15))

        principal_str = f"{_fmt_won(loan_fact.principal_amount)}원"
        remaining_str = f"{_fmt_won(verification.reconciled_amount)}원"
        if as_of is not None:
            base_s = _fmt_kr_date(as_of)
            interest_str = f"{_fmt_won(verification.calculated_interest)}원 ({base_s} 기준)"
            total_str = f"{_fmt_won(verification.total_claim_amount)}원"
            total_disp = f"{total_str} ({base_s} 기준)"
        else:
            interest_str = "____원"
            total_str = "____원"
            total_disp = "____원"

        elements.append(Paragraph(f"<b>[청구 금액 합계: 금 {total_disp}]</b> (남은 원금: {remaining_str}, 현재 지연손해금: {interest_str})", bold_style))
        elements.append(Spacer(1, 10))

        loan_d = _fmt_kr_date(loan_fact.loan_date)
        due_d = _fmt_kr_date(loan_fact.due_date)
        # K8: letter voice (본인/귀하). K7: repayment wording moves after facts.
        item2 = (
            f"2. 본인은 귀하에게 <b>{loan_d}</b>에 금 <b>{principal_str}</b>을 대여하였으며, "
            f"귀하는 이를 <b>{due_d}</b>까지 전액 변제하기로 약정하였습니다."
        )
        calc_obj = getattr(verification, "calculation", None)
        if calc_obj is not None:
            repay_sentence = build_repayment_sentence(loan_fact, calc_obj, style="letter")
        elif loan_fact.repayments:
            if as_of is not None:
                reps = sorted(
                    [r for r in loan_fact.repayments if r.payment_date <= as_of],
                    key=lambda r: r.payment_date,
                )
            else:
                reps = sorted(loan_fact.repayments, key=lambda r: r.payment_date)
            if len(reps) == 1:
                r = reps[0]
                r_d = _fmt_kr_date(r.payment_date)
                r_amt = _fmt_won(r.amount)
                repay_sentence = f"본인은 {r_d} 귀하로부터 받은 {r_amt}원을 원금에 충당하여 남은 원금은 {remaining_str}입니다."
            elif len(reps) > 1:
                total_repaid = sum((r.amount for r in reps), Decimal("0"))
                total_s = _fmt_won(total_repaid)
                repay_sentence = f"본인은 귀하로부터 총 {total_s}원을 {len(reps)}회에 나누어 받아 원금에 충당하여 남은 원금은 {remaining_str}입니다."
            else:
                repay_sentence = ""
        else:
            repay_sentence = ""

        if as_of is not None:
            deadline = as_of + timedelta(days=7)
            deadline_s = _fmt_kr_date(deadline)
            item4 = (
                f"4. 이에 본인은 본 내용증명을 통하여 귀하에게 "
                f"<b>{deadline_s}</b>까지 위 원리금 합계액(금 {total_disp})을 보내 주시기 바랍니다."
            )
        else:
            item4 = (
                f"4. 이에 본인은 본 내용증명을 통하여 귀하에게 "
                f"위 원리금 합계액(금 {total_str})을 보내 주시기 바랍니다."
            )

        item3 = "3. 본인은 변제기 이후 현재까지 남은 돈을 받지 못했습니다."
        # M5-fix2: letter voice comes from slot re-rendering (packager);
        # format_letter_fact only strips cites/marks (no char replacement).
        letter_facts = [
            format_letter_fact(s)
            for s in ensure_numbered_facts(fact_sentences or [])
        ]
        middle_parts: List[str] = []
        if letter_facts:
            middle_parts.append("<br/><br/>".join(_xml_escape(s) for s in letter_facts))
        if repay_sentence:
            middle_parts.append(_xml_escape(repay_sentence) + ".")
        middle = "<br/><br/>".join(middle_parts)
        if middle:
            body_text = (
                f"1. 귀하의 무궁한 발전을 기원합니다.<br/><br/>"
                f"{item2}<br/><br/>"
                f"{middle}<br/><br/>"
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

        def _footer(canvas, _doc):
            canvas.saveState()
            canvas.setFont(KO_FONT, 7)
            canvas.setFillColor(colors.grey)
            canvas.drawCentredString(A4[0] / 2, 30, NOTICE_KO)
            canvas.restoreState()

        doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
        return output_path

    @classmethod
    def generate_ecourt_clipboard_packet(
        cls,
        loan_fact: LoanFactSchema,
        verification: VerificationResult,
        as_of: Optional[date] = None,
        fact_sentences: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """
        대한민국 법원 전자소송 클립보드 블록
        """
        p = loan_fact.creditor
        d = loan_fact.debtor
        parties_text = format_parties_text(p, d)

        base_date = as_of
        remaining_str = f"{_fmt_won(verification.reconciled_amount)}"
        principal_str = f"{_fmt_won(loan_fact.principal_amount)}"
        if base_date is not None:
            base_s = _fmt_kr_date(base_date)
            interest_str = f"{_fmt_won(verification.calculated_interest)} ({base_s} 기준)"
            total_str = f"{_fmt_won(verification.total_claim_amount)} ({base_s} 기준)"
        else:
            interest_str = "____"
            total_str = "____"

        sentence = ""
        if verification.calculation is not None:
            sentence = verification.calculation.rate_clause.sentence or ""
        if sentence:
            claim_purpose = (
                f"1. {sentence}\n"
                f"2. 독촉절차비용은 채무자의 부담으로 한다.\n"
                f"라는 명령을 구함."
            )
        else:
            claim_purpose = ""

        # K11: drop approximate "경" (confirmed dates are exact).
        if loan_fact.demand_date:
            dem_s = _fmt_kr_date(loan_fact.demand_date)
            demand_clause = f"채권자는 {dem_s} 채무자에게 변제를 요청하였으나, 채무자는 현재까지 이를 지급하지 않고 있습니다."
        else:
            demand_clause = "채무자는 현재까지 남은 돈을 지급하지 않고 있습니다."

        loan_s = _fmt_kr_date(loan_fact.loan_date)
        due_s = _fmt_kr_date(loan_fact.due_date)
        lend_part = (
            f"채권자는 {loan_s} 채무자에게 금 {principal_str}원을 대여하였고, "
            f"채무자는 이를 {due_s}까지 변제하기로 약정하였습니다."
        )
        if loan_fact.agreed_interest_rate is not None:
            lend_part += f" 이자는 연 {_fmt_rate(loan_fact.agreed_interest_rate)}%로 정하였습니다."
        # K6/K7: shared repayment wording after facts (no inline short lines).
        calc_obj = getattr(verification, "calculation", None)
        if calc_obj is not None:
            repay_sentence = build_repayment_sentence(loan_fact, calc_obj, style="ecourt")
            if repay_sentence and not repay_sentence.endswith("."):
                repay_sentence = repay_sentence + "."
        elif loan_fact.repayments:
            if base_date is not None:
                reps = sorted(
                    [r for r in loan_fact.repayments if r.payment_date <= base_date],
                    key=lambda r: r.payment_date,
                )
            else:
                reps = sorted(loan_fact.repayments, key=lambda r: r.payment_date)
            if len(reps) == 1:
                r = reps[0]
                r_d = _fmt_kr_date(r.payment_date)
                r_amt = _fmt_won(r.amount)
                repay_sentence = f"채권자는 {r_d} 채무자로부터 받은 {r_amt}원을 원금에 충당하여 남은 원금은 {remaining_str}원입니다."
            elif len(reps) > 1:
                total_repaid = sum((r.amount for r in reps), Decimal("0"))
                total_s = _fmt_won(total_repaid)
                repay_sentence = f"채권자는 채무자로부터 총 {total_s}원을 {len(reps)}회에 나누어 받아 원금에 충당하여 남은 원금은 {remaining_str}원입니다."
            else:
                repay_sentence = ""
        else:
            repay_sentence = ""

        # K11: conclusion names the remaining principal explicitly.
        try:
            _rem = verification.reconciled_amount
            _rem_d = _rem if isinstance(_rem, Decimal) else Decimal(str(_rem))
        except Exception:
            _rem_d = Decimal("0")
        if _rem_d > 0:
            conclusion = (
                f"따라서 채권자는 남은 원금 {_fmt_won(_rem_d)}원 및 지연손해금을 "
                f"지급받기 위하여 본 신청에 이르렀습니다."
            )
        else:
            over_raw = _calc_field(calc_obj, "overpayment_amount", Decimal("0")) if calc_obj is not None else Decimal("0")
            try:
                over_d = over_raw if isinstance(over_raw, Decimal) else Decimal(str(over_raw))
            except Exception:
                over_d = Decimal("0")
            if over_d > 0:
                conclusion = (
                    f"따라서 채권자는 원금을 모두 변제받고 {_fmt_won(over_d)}원이 "
                    f"남았음을 밝힙니다."
                )
            else:
                conclusion = "따라서 채권자는 남은 원금 및 지연손해금을 지급받기 위하여 본 신청에 이르렀습니다."

        ecourt_facts = [format_ecourt_fact(s) for s in ensure_numbered_facts(fact_sentences or [])]
        section2_parts = [lend_part]
        if ecourt_facts:
            section2_parts.append("\n".join(ecourt_facts))
        if repay_sentence:
            section2_parts.append(repay_sentence)
        section2 = "\n".join(section2_parts)
        claim_cause_payment_order = (
            f"1. 당사자 관계\n"
            f"채권자는 채무자에게 금전을 대여한 자이며, 채무자는 이를 차용한 자입니다.\n\n"
            f"2. 대여사실 및 변제약정\n"
            f"{section2}\n\n"
            f"3. 변제기 이후 상황\n"
            f"약정 변제기가 지났음에도 {demand_clause}\n\n"
            f"4. 결론\n"
            f"{conclusion}"
        )

        evidence_citations = ", ".join([f"[{e.id} {e.title}]" for e in loan_fact.evidences])
        claim_cause_lawsuit = (
            f"{claim_cause_payment_order}\n\n"
            f"[입증 방법]\n"
            f"{evidence_citations}"
        )

        return {
            "parties": parties_text,
            "claim_purpose": claim_purpose,
            "claim_cause_payment_order": claim_cause_payment_order,
            "claim_cause_lawsuit": claim_cause_lawsuit,
            "total_claim_amount": total_str,
            "principal_amount": remaining_str,
            "interest_amount": interest_str,
        }
