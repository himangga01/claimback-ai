import os
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional
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

        info_data = [
            [Paragraph("<b>발 신 인:</b>", bold_style), Paragraph(f"{p.name} (연락처: {p.phone or '미기재'})", body_style)],
            ["", Paragraph(f"주소: {p.address or '미기재'}", body_style)],
            [Paragraph("<b>수 신 인:</b>", bold_style), Paragraph(f"{d.name} (연락처: {d.phone or '미기재'})", body_style)],
            ["", Paragraph(f"주소: {d.address or '미기재'}", body_style)],
            [Paragraph("<b>제    목:</b>", bold_style), Paragraph("<b>대여금 반환 청구의 건</b>", bold_style)],
        ]
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
            interest_str = f"{_fmt_won(verification.calculated_interest)}원"
            total_str = ""
            total_disp = ""

        elements.append(Paragraph(f"<b>[청구 금액 합계: 금 {total_disp}]</b> (남은 원금: {remaining_str}, 현재 지연손해금: {interest_str})", bold_style))
        elements.append(Spacer(1, 10))

        loan_d = _fmt_kr_date(loan_fact.loan_date)
        due_d = _fmt_kr_date(loan_fact.due_date)
        item2 = (
            f"2. 발신인은 귀하에게 <b>{loan_d}</b>에 금 <b>{principal_str}</b>을 대여하였으며, "
            f"귀하는 이를 <b>{due_d}</b>까지 전액 변제하기로 약정하였습니다."
        )
        if loan_fact.repayments:
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
                item2 += f"<br/>그중 {r_amt}원을 {r_d} 받았고 남은 원금은 {remaining_str}입니다."
            elif len(reps) > 1:
                total_repaid = sum((r.amount for r in reps), Decimal("0"))
                total_s = _fmt_won(total_repaid)
                last_d = _fmt_kr_date(reps[-1].payment_date)
                item2 += (
                    f"<br/>그중 총 {total_s}원을 {len(reps)}회에 나누어 받았고 "
                    f"남은 원금은 {remaining_str}입니다. (마지막 수령일 {last_d})"
                )

        if as_of is not None:
            deadline = as_of + timedelta(days=7)
            deadline_s = _fmt_kr_date(deadline)
            item4 = (
                f"4. 이에 발신인은 본 내용증명을 통하여 귀하에게 "
                f"<b>{deadline_s}</b>까지 위 원리금 합계액(금 {total_disp})을 보내 주시기 바랍니다."
            )
        else:
            item4 = (
                f"4. 이에 발신인은 본 내용증명을 통하여 귀하에게 "
                f"위 원리금 합계액(금 {total_str})을 보내 주시기 바랍니다."
            )

        if fact_sentences:
            fact_block = "<br/><br/>".join(fact_sentences)
            body_text = (
                f"1. 귀하의 무궁한 발전을 기원합니다.<br/><br/>"
                f"{fact_block}<br/><br/>"
                f"{item4}"
            )
        else:
            body_text = (
                f"1. 귀하의 무궁한 발전을 기원합니다.<br/><br/>"
                f"{item2}<br/><br/>"
                f"3. 발신인은 변제기 이후 현재까지 남은 돈을 받지 못했습니다.<br/><br/>"
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
        elements.append(Paragraph(f"<b>발신인: {p.name} (인/서명)</b>", right_style))

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

        base_date = as_of
        if base_date is None and verification.calculation is not None:
            base_date = verification.calculation.reference_total.as_of
        remaining_str = f"{_fmt_won(verification.reconciled_amount)}"
        principal_str = f"{_fmt_won(loan_fact.principal_amount)}"
        if base_date is not None:
            base_s = _fmt_kr_date(base_date)
            interest_str = f"{_fmt_won(verification.calculated_interest)} ({base_s} 기준)"
            total_str = f"{_fmt_won(verification.total_claim_amount)} ({base_s} 기준)"
        else:
            interest_str = f"{_fmt_won(verification.calculated_interest)}"
            total_str = ""

        parties_text = (
            f"채권자: {p.name}\n"
            f"주소: {p.address or '주소 불명'}\n"
            f"연락처: {p.phone or '연락처 불명'}\n\n"
            f"채무자: {d.name}\n"
            f"주소: {d.address or '주소 불명'}\n"
            f"연락처: {d.phone or '연락처 불명'}"
        )

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

        if loan_fact.demand_date:
            dem_s = _fmt_kr_date(loan_fact.demand_date)
            demand_clause = f"채권자는 {dem_s}경 채무자에게 변제를 요청하였으나, 채무자는 현재까지 이를 지급하지 않고 있습니다."
        else:
            demand_clause = "채무자는 변제기 이후 현재까지 남은 돈을 지급하지 않고 있습니다."

        loan_s = _fmt_kr_date(loan_fact.loan_date)
        due_s = _fmt_kr_date(loan_fact.due_date)
        lend_part = (
            f"채권자는 {loan_s}경 채무자에게 금 {principal_str}원을 대여하였고, "
            f"채무자는 이를 {due_s}까지 변제하기로 약정하였습니다."
        )
        if loan_fact.agreed_interest_rate is not None:
            lend_part += f" 이자는 연 {_fmt_rate(loan_fact.agreed_interest_rate)}%로 정하였습니다."
        if loan_fact.repayments:
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
                lend_part += f" 그중 {r_amt}원을 {r_d} 받았고 남은 원금은 {remaining_str}원입니다."
            elif len(reps) > 1:
                total_repaid = sum((r.amount for r in reps), Decimal("0"))
                total_s = _fmt_won(total_repaid)
                last_d = _fmt_kr_date(reps[-1].payment_date)
                lend_part += (
                    f" 그중 총 {total_s}원을 {len(reps)}회에 나누어 받았고 "
                    f"남은 원금은 {remaining_str}원입니다. (마지막 수령일 {last_d})"
                )

        if fact_sentences:
            fact_block = "\n".join(fact_sentences)
            claim_cause_payment_order = (
                f"1. 당사자 관계\n"
                f"채권자는 채무자에게 금전을 대여한 자이며, 채무자는 이를 차용한 자입니다.\n\n"
                f"2. 대여사실 및 변제약정\n"
                f"{fact_block}\n\n"
                f"3. 결론\n"
                f"따라서 채권자는 위 대여원금 및 지연손해금을 지급받기 위하여 본 신청에 이르렀습니다."
            )
        else:
            claim_cause_payment_order = (
                f"1. 당사자 관계\n"
                f"채권자는 채무자에게 금전을 대여한 자이며, 채무자는 이를 차용한 자입니다.\n\n"
                f"2. 대여사실 및 변제약정\n"
                f"{lend_part}\n\n"
                f"3. 변제기 이후 상황\n"
                f"약정 변제기가 지났음에도 {demand_clause}\n\n"
                f"4. 결론\n"
                f"따라서 채권자는 위 대여원금 및 지연손해금을 지급받기 위하여 본 신청에 이르렀습니다."
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
