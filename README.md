# ClaimBack-AI ⚖️

> **Meta Global AI Developer Hackathon (Theme 1: Build for Your World)**  
> Pro Se Visual Evidence Forensics & Deterministic Dual-Court Auto-Packager

ClaimBack-AI is a 100% free, non-profit, open-source legal empowerment tool that helps everyday citizens recover unpaid small loans without costly attorney fees. It combines **SAM 3.1 visual forensics**, **Muse Wonder chronology extraction**, and a **deterministic Python verification gate** to automatically generate court-ready filing packets for both **South Korea (전자소송 / 내용증명)** and the **United States (California Small Claims Form SC-100)**.

---

## 🌟 Key Features

1. **Agent 1. Forensic Visual Agent (SAM 3.1)**:
   - High-precision segmentation of loan amounts, debt acknowledgments, and handwritten signatures.
   - Automated PII redaction (account numbers, resident registration numbers).
   - Forensic judicial stamping (`[갑 제1호증]`, `[Exhibit A]`).

2. **Agent 2. Fact Chronology Agent (Muse Wonder)**:
   - Chronological fact timeline extraction from messy messenger screenshots and transfer receipts.
   - Dual-jurisdiction statutory pleading drafting (지급명령 청구원인 / SC-100 Statement of Facts).

3. **Agent 3. Financial Auditor Agent (Deterministic Python Gate)**:
   - Strict adherence to legal precedents: 초일불산입 (변제기 익일 기산) and 소촉법 제3조 제1항 (송달 익일 연 12% 기산).
   - Multi-year daily interest calculator crossing leap years with 0-day drift.
   - Zero-hallucination guarantee: ungrounded or altered numbers are forcefully reconciled against raw OCR receipts.
   - Automated statute of limitations calculation (KR 10yr/5yr, CA 4yr/2yr).

4. **Agent 4. Judicial Filer Agent (AcroForm & PDF Packager)**:
   - Direct AcroForm injection for California Judicial Council **Form SC-100 (Rev. Jan 1, 2026)** with all 6 required checkboxes and Item 11 declaration signature.
   - Post-office standard **내용증명 PDF** generation with embedded NanumGothic Korean fonts.
   - 대한민국 법원 전자소송(ecourt.scourt.go.kr) 1:1 one-click clipboard packets.

---

## 🚀 Quick Start (Zero Build Step)

### 1. Run the Backend & Interactive UI
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
Open **`http://localhost:8000`** in any web browser to access the 3-panel interactive forensic dashboard!

### 2. Standalone Frontend Mode
The frontend is a lightweight, zero-build modern SPA. You can also open `frontend/index.html` directly in your browser with offline fallback presets included!

### 3. Run Verification Tests
```bash
cd backend
PYTHONPATH=. pytest -v
```
All 25 unit and regression tests pass in under 3 seconds.
