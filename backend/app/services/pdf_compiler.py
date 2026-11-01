import os
from datetime import date
from decimal import Decimal
from typing import Dict, Any, Optional
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
    # 시스템 폰트 폴백
    sys_font = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
    if os.path.exists(sys_font):
        pdfmetrics.registerFont(TTFont("ZenHei", sys_font, subfontIndex=0))
        KO_FONT = "ZenHei"
        KO_FONT_BOLD = "ZenHei"
    else:
        KO_FONT = "Helvetica"
        KO_FONT_BOLD = "Helvetica-Bold"


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
    ) -> str:
        if not os.path.exists(cls.TEMPLATE_PATH):
            raise FileNotFoundError(f"Template not found at {cls.TEMPLATE_PATH}")

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
            f"Prejudgment interest accrued under Cal. Civ. Code § 3289(b) / § 3287(a): ${interest_amt_str} USD."
        )

        calc_explanation = (
            f"Principal Balance: ${principal_amt_str} USD. "
            f"Accrued Statutory Interest (10% p.a.): ${interest_amt_str} USD. "
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

            # -------------------------------------------------------------
            # 필수 체크박스 완벽 주입 (C-2 해결)
            # -------------------------------------------------------------
            # Item 4: Have you asked defendant to pay? (Yes: Checkbox50[0] = /1)
            "SC-100[0].Page3[0].List4[0].Item4[0].Checkbox50[0]": "/1",
            
            # Item 5: Venue Basis (a(1) Defendant lives here: Checkbox5cb[0] = /1)
            "SC-100[0].Page3[0].List5[0].Lia[0].Checkbox5cb[0]": "/1",

            # Item 7: Attorney-Client fee dispute? (No: Checkbox60[1] = /2)
            "SC-100[0].Page3[0].List7[0].item7[0].Checkbox60[1]": "/2",

            # Item 8: Suing public entity? (No: Checkbox61[1] = /2)
            "SC-100[0].Page3[0].List8[0].item8[0].Checkbox61[1]": "/2",

            # Item 9: Filed > 12 claims in last 12 months? (No: Checkbox62[1] = /2)
            "SC-100[0].Page4[0].List9[0].Item9[0].Checkbox62[1]": "/2",

            # Item 10: Claim > $2,500?
            "SC-100[0].Page4[0].List10[0].li10[0].Checkbox63[0]": "/1" if verification.total_claim_amount > Decimal("2500.00") else "/Off",
            "SC-100[0].Page4[0].List10[0].li10[0].Checkbox63[1]": "/2" if verification.total_claim_amount <= Decimal("2500.00") else "/Off",
        }

        # AcroForm 필드 업데이트
        for page_idx in range(len(writer.pages)):
            writer.update_page_form_field_values(writer.pages[page_idx], field_data)

        # NeedAppearances 활성화 (뷰어 호환성 확보)
        writer.set_need_appearances_writer(True)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            writer.write(f)

        return output_path


class KoreanLegalDocumentCompiler:
    """
    한국 트랙: 전자내용증명 PDF(한글 폰트 완비) 및 전자소송 1:1 클립보드 패키저
    """

    @classmethod
    def generate_content_proof_pdf(
        cls,
        loan_fact: LoanFactSchema,
        verification: VerificationResult,
        output_path: str,
    ) -> str:
        """
        우체국 전자내용증명 표준 규격 PDF 생성 (나눔고딕 한글 폰트 임베딩)
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
            [Paragraph("<b>제    목:</b>", bold_style), Paragraph("<b>대여금 반환 청구 및 최종 변제 독촉의 건</b>", bold_style)],
        ]
        info_table = Table(info_data, colWidths=[65, 430])
        info_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
            ('TOPPADDING', (0,0), (-1,-1), 2),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 15))

        amt_str = f"{verification.reconciled_amount:,.0f}원"
        interest_str = f"{verification.calculated_interest:,.0f}원"
        total_str = f"{verification.total_claim_amount:,.0f}원"

        elements.append(Paragraph(f"<b>[청구 금액 합계: 금 {total_str}]</b> (원금: {amt_str}, 현재 지연손해금: {interest_str})", bold_style))
        elements.append(Spacer(1, 10))

        # 적법한 법리 문구 (C-1 해결: 소제기 전 연 5%, 소장 송달 후 연 12%)
        body_text = (
            f"1. 귀하의 무궁한 발전을 기원합니다.<br/><br/>"
            f"2. 발신인은 귀하에게 <b>{loan_fact.loan_date}</b>에 금 <b>{amt_str}</b>을 대여하였으며, "
            f"귀하는 이를 <b>{loan_fact.due_date}</b>까지 전액 변제하기로 약정하였습니다.<br/><br/>"
            f"3. 그러나 귀하는 변제기가 경과하였음에도 현재까지 정당한 사유 없이 채무를 이행하지 않고 있습니다.<br/><br/>"
            f"4. 이에 발신인은 본 내용증명을 통하여 귀하에게 최종 변제를 촉구하오니, 본 서면을 수령한 날로부터 "
            f"<b>7일 이내</b>에 위 원리금 합계액(금 {total_str})을 완제하여 주시기 바랍니다.<br/><br/>"
            f"5. 만일 위 기한 내에 변제가 이루어지지 않을 경우, 발신인은 부득이 민사소송법상 <b>지급명령 신청 또는 소제기</b> 등 "
            f"법적 조치를 취할 것이며, 변제기 익일부터는 민법상 연 5%(상사 거래 연 6%), "
            f"소송 제기 후 소장/지급명령정본 송달 다음날부터 다 갚는 날까지는 소송촉진 등에 관한 특례법상 연 12%의 지연손해금이 "
            f"가산됨을 엄히 고지합니다."
        )
        elements.append(Paragraph(body_text, body_style))
        elements.append(Spacer(1, 25))

        today_str = date.today().strftime("%Y년 %m월 %d일")
        elements.append(Paragraph(f"<div align='center'>{today_str}</div>", body_style))
        elements.append(Spacer(1, 10))
        elements.append(Paragraph(f"<div align='right'><b>발신인: {p.name} (인/서명)</b></div>", bold_style))

        doc.build(elements)
        return output_path

    @classmethod
    def generate_ecourt_clipboard_packet(
        cls,
        loan_fact: LoanFactSchema,
        verification: VerificationResult,
    ) -> Dict[str, str]:
        """
        대한민국 법원 전자소송(ecourt.scourt.go.kr) 1:1 원클릭 복사용 텍스트 블록
        - C-1: 청구취지와 이자 금액의 법리적 일치
        - M-1: 지급명령용(호증 인용 제외)과 소액소장용(호증/입증취지 포함) 분리
        - M-2: 스키마 사실에 기반한 정밀한 문안 생성
        """
        p = loan_fact.creditor
        d = loan_fact.debtor

        amt_str = f"{verification.reconciled_amount:,.0f}"
        interest_str = f"{verification.calculated_interest:,.0f}"
        total_str = f"{verification.total_claim_amount:,.0f}"

        # 1. 당사자 표시
        parties_text = (
            f"채권자(원고): {p.name}\n"
            f"주소: {p.address or '주소 불명'}\n"
            f"연락처: {p.phone or '연락처 불명'}\n\n"
            f"채무자(피고): {d.name}\n"
            f"주소: {d.address or '주소 불명'}\n"
            f"연락처: {d.phone or '연락처 불명'}"
        )

        # 2. 청구 취지 (지급명령 표준: 법률상 2단계 분리)
        rate_pre = "연 6%" if loan_fact.transaction_kind.value == "commercial" else "연 5%"
        claim_purpose = (
            f"1. 채무자는 채권자에게 금 {amt_str}원 및 이에 대하여 {loan_fact.due_date}의 다음날부터 "
            f"이 사건 지급명령정본 송달일까지는 {rate_pre}, "
            f"그 다음날부터 다 갚는 날까지는 연 12%의 각 비율로 계산한 돈을 지급하라.\n"
            f"2. 독촉절차비용은 채무자의 부담으로 한다.\n"
            f"라는 명령을 구함."
        )

        # 3. 독촉 사실 문구 (M-2 해결: 스키마에 독촉일이 있는 경우에만 정확히 기재)
        if loan_fact.demand_date:
            demand_clause = f"채권자는 {loan_fact.demand_date}경 채무자에게 최종 변제를 최고(독촉)하였으나, 채무자는 현재까지 이를 이행하지 않고 있습니다."
        else:
            demand_clause = "채무자는 현재까지 정당한 사유 없이 채무의 이행을 지체하고 있습니다."

        # 4. 지급명령용 청구 원인 (M-1 해결: 지급명령 서식에 맞춰 호증 인용 생략)
        claim_cause_payment_order = (
            f"1. 당사자 관계\n"
            f"채권자는 채무자에게 금전을 대여한 자이며, 채무자는 이를 차용한 자입니다.\n\n"
            f"2. 대여사실 및 변제약정\n"
            f"채권자는 {loan_fact.loan_date}경 채무자에게 금 {amt_str}원을 대여하였고, "
            f"채무자는 이를 {loan_fact.due_date}까지 변제하기로 약정하였습니다.\n\n"
            f"3. 채무 불이행\n"
            f"약정 변제기가 도래하였음에도 {demand_clause}\n\n"
            f"4. 결론\n"
            f"따라서 채권자는 위 대여원금 및 법정 지연손해금을 지급받기 위하여 본 신청에 이르렀습니다."
        )

        # 5. 소액소장용 청구 원인 및 입증방법 (호증 및 입증취지 분리)
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
            "principal_amount": amt_str,
            "interest_amount": interest_str,
        }
