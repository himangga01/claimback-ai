# ClaimBack-AI ⚖️

> **Meta Global AI Developer Hackathon (Theme 1: Build for Your World)**  
> Pro Se Visual Evidence Forensics & Deterministic Dual-Court Auto-Packager

ClaimBack-AI is a 100% free, open-source self-help tool that organizes your own evidence for an unpaid small loan and fills standard court forms with facts you confirm. It combines **SAM 3.1 visual forensics**, **Muse Spark 1.3 (`muse-spark-1.3`) chronology extraction**, and a **deterministic Python verification gate** for both **South Korea (전자소송 / 내용증명)** and the **United States (California Small Claims Form SC-100)**.

---

## 🌟 Key Features

1. **Agent 1. Forensic Visual Agent (SAM 3.1)**:
   - Segmentation of loan amounts, repay promises (`repay_promise` utterances), and handwritten signatures.
   - Automated PII redaction (account numbers, resident registration numbers).
   - exhibit labels(갑 제N호증, Exhibit A).

2. **Agent 2. Fact-Timeline Chronology Agent (Muse Spark 1.3)**:
   - Chronological fact timeline extraction from messy messenger screenshots and transfer receipts.
   - Dual-jurisdiction statutory pleading drafting (지급명령 청구원인 / SC-100 Statement of Facts).

3. **Agent 3. Financial Auditor Agent (Deterministic Python Gate)**:
   - Multi-year daily interest calculator crossing leap years with 0-day drift.
   - Verified-values-only: if numbers differ from confirmed values, document generation is blocked.

4. **Agent 4. Judicial Form Filler Agent (AcroForm & PDF Packager)**:
   - Direct AcroForm injection for California Judicial Council **Form SC-100 (Rev. Jan 1, 2026)** with all 6 required checkboxes and Item 11 declaration signature.
   - Post-office standard **내용증명 PDF** generation with embedded NanumGothic Korean fonts.
   - 대한민국 법원 전자소송(ecourt.scourt.go.kr) 1:1 one-click clipboard packets.

---

## 🚀 Quick Start (Zero Build Step)

### 1. Run the Backend & Interactive UI
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```
Open **`http://localhost:8000`** in any web browser to access the 3-panel interactive forensic dashboard!

### 2. Standalone Frontend Mode
The frontend is a lightweight, zero-build modern SPA. You can also open `frontend/index.html` directly in your browser with offline fallback presets included!

### 3. Run Verification Tests
```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```
The offline unit and regression suite runs with pytest as shown above; no API key is needed for it.

---

## 🔔 Notice

ClaimBack-AI는 본인이 직접 소송 서류를 준비할 때 쓰는 무료 정리 도구입니다. 법률 자문을 제공하지 않으며, 서류에 들어가는 사실은 모두 사용자가 확인한 내용입니다. 법률 상담은 대한법률구조공단(132)이나 변호사에게 받으세요.

ClaimBack-AI is a free self-help tool for organizing your own evidence and filling standard court forms. It does not provide legal advice. Every fact in the documents is confirmed by you. For help, contact your court's self-help center or a small claims advisor.

---

## 📄 License

- Source code and generated sample files: MIT (see `LICENSE`).
- Bundled fonts (`backend/app/templates/fonts/NanumGothic-*.ttf`): SIL Open Font License 1.1 (see `backend/app/templates/fonts/OFL.txt`).
- `backend/app/templates/ca_sc100_blank.pdf`: a California Judicial Council Form SC-100 file included unmodified for form-filling; it is not covered by the MIT license above.
