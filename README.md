# ClaimBack-AI

> **Meta Global AI Developer Hackathon (Theme 1: Build for Your World)**
> Free self-help tool that organizes your own evidence for an unpaid small loan and fills standard court forms with facts you confirm.

이 저장소의 코드는 Meta Global AI Developer Hackathon 기간(2026-10-27~11-04)에 만들었습니다. Muse Code로 구현하고 Claude Code로 지시·리뷰했습니다.

---

## What it does

1. **Forensic Visual**: finds boxes for amounts, dates, signatures, and seals in your evidence images, and burns PII redaction (account numbers, resident registration numbers) into the pixels before building PDFs. Labels exhibits (갑 제N호증, Exhibit A).
2. **Fact-Timeline Chronology**: orders messenger and receipt text into a fact timeline, and drafts claim text (지급명령 청구원인 / SC-100 statement of facts) only from facts you confirm.
3. **Financial Auditor**: deterministic calculator for interest and totals; blocks document generation when numbers differ from your confirmed values.
4. **Judicial Form Filler**: fills 내용증명 and payment-order packets and SC-100 fields from your confirmed facts. You review everything and sign the declaration yourself.

---

## Quick Start

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Open **`http://localhost:8000`**. The first screen walks through the case flow: upload evidence, check the readings, confirm facts, then review the drafts.

Run the offline test suite (no API key needed):

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

---

## 🔔 Notice

ClaimBack-AI는 본인이 직접 소송 서류를 준비할 때 쓰는 무료 정리 도구입니다. 법률 자문을 제공하지 않으며, 서류에 들어가는 사실은 모두 사용자가 확인한 내용입니다. 법률 상담은 대한법률구조공단(132)이나 변호사에게 받으세요.

ClaimBack-AI is a free self-help tool for organizing your own evidence and filling standard court forms. It does not provide legal advice. Every fact in the documents is confirmed by you. For help, contact your court's self-help center or a small claims advisor.

---

## 📄 License

- Source code and generated sample files: MIT (see `LICENSE`).
- Bundled fonts (`backend/app/templates/fonts/NanumGothic-*.ttf`): SIL Open Font License 1.1 (see `backend/app/templates/fonts/OFL.txt`).
- `backend/app/templates/ca_sc100_blank.pdf`: a California Judicial Council Form SC-100 file included unmodified for form-filling; it is not covered by the MIT license above.
