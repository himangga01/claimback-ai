# ClaimBack-AI

> **Meta Global AI Developer Hackathon 2026 — Build for Your World**
> A free self-help tool that organizes your own evidence for an unpaid personal loan and fills standard Korean court-document text with facts you confirm. See the notice below.

2026-11-02 기준 코드(커밋 76d9cce까지)는 대회 기간에 저장소 소유자가 작성했고, 2026-11-03 M-1부터는 Muse Code(`muse-spark-1.3`)가 구현하고 Claude Code가 명세·지시·리뷰했다.

Code up to 2026-11-02 (through commit 76d9cce) was written by the repository owner during the hackathon; from 2026-11-03 (milestone M-1) on, Muse Code (`muse-spark-1.3`) implemented every change and Claude Code wrote the specs and task briefs and reviewed each milestone.

---

## What it does

You lent a friend 5,000,000 won and got 1,000,000 back. ClaimBack-AI takes your chat screenshots, transfer receipts and IOU, and helps you prepare:

- a 내용증명 (certified demand letter) PDF,
- the 청구취지 / 청구원인 text to paste into the e-court payment-order form,
- a 갑호증 exhibit bundle (redacted copies, "갑 제N호증" marks) and an 증거목록 (evidence list).

Every fact in those documents is one you confirmed on screen. The AI never writes numbers or names into the documents directly.

## How it works

A rule-based coordinator runs role agents with two human checkpoints:

| Step | Agent | Model |
|---|---|---|
| Intake | records each file's SHA-256 and exhibit number | rules |
| Reading | reads each image with boxes; long screenshots are read in overlapping tiles | `muse-spark-1.2` (prompt `reader.v2`) |
| Vision | finds chat bubbles, profile pictures, stamps and signature boxes | `sam-3.1` |
| Fact organizing | proposes field values, each tied to the reading it came from; flags conflicts and asks questions | `muse-spark-1.3` (prompt `fact_organizer.v2`) |
| Privacy | burns account / ID / phone numbers out of the image pixels; checks the mask edges and flags anything it cannot confirm | rules |
| **Checkpoint 1** | you confirm or correct every value | you |
| Calculation | interest allocation, remaining principal, statutory rates | deterministic code |
| Drafting | writes fact sentences with **slots only** (`{{principal}}`, `{{quote:EX1:item10}}`) | `muse-spark-1.3` (prompt `drafter.v2`) |
| Verification | G1a no literal numbers/names, G3 every fact cites evidence, DRAFT no computed values or invented speech, NAMING no professional titles | rules |
| **Draft approval** | you approve or edit each sentence | you |
| Packaging | renders the documents from your confirmed values; G1b re-checks every PDF against them, per document | rules |

Model choices were measured, not guessed: `muse-spark-1.2` and `1.3` both matched ≥95% of amounts and dates on the sample set, and 1.2 had the shorter p95 latency (8.8 s vs 33.2 s), so 1.2 reads and 1.3 organizes and drafts (`reports/M4b.md`).

## Safety by design

- No legal evaluation: no win predictions, no "you can claim" judgments, no legal labels on what people said.
- The AI writes slots, not values. Values come from your confirmed facts and the deterministic calculator; a verifier rejects literal numbers, computed values posing as agreements, and speech the evidence does not quote.
- Redaction is burned into image pixels before any PDF is built. If the checker cannot confirm a redaction, the image is flagged "확인 필요" and left out of the exhibit bundle until you confirm it.
- Sample evidence is synthetic and marked "SAMPLE / 데모용".

## Quick start (Windows, PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd backend
$env:META_MODE = "replay"     # runs the sample case from recorded model responses, no API key needed
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Open `http://localhost:8000`, press **샘플 사건 불러오기**, then **실행**, and follow the two checkpoints.

To call the Meta Model API live, set `META_MODE=live`, put your key in `MODEL_API_KEY`, and point `META_LEDGER_PATH` at an absolute path for the cost ledger (`META_LEDGER_INIT=1` the first time). Every call's cost is recorded, and a run stops before it would exceed `META_RUN_CAP_USD` (default $2).

## Tests

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q          # offline, replay mode, no key
cd ..
..\.venv\Scripts\python.exe -m pytest -q e2e      # Playwright against the stub server
# against the real backend: start uvicorn as above, then set E2E_BASE_URL=http://127.0.0.1:8000
```

## How it was built

- Milestone briefs: `specs/tasks/`. Muse Code reports: `reports/M*.md`, `reports/INT-*.md`. Claude Code reviews (two independent reviewers per milestone, cross-checked): `reports/*-review.md`.
- Every live Meta API call made by the app during development is in `reports/cost_ledger.jsonl`.

## Known limits

- Korean track only in this version (the US SC-100 path is partial).
- Video evidence is stored and hashed, but frame reading is not in the case flow yet (it produced duplicates and timestamp drift in testing; see `reports/M4b-review.md`).
- Reading boxes on very tall screenshots are still approximate; the privacy step refines boxes from the image pixels and flags anything it cannot confirm.
- The draft-rule checker is word-based; it can still block a few harmless sentences you type yourself (for example a promise phrase next to a date slot). Review your own edits before approving (`reports/INT-3c-review.md`).
- Video evidence goes into the exhibit list as "submit the file separately" and is not redacted; check it yourself before filing.

---

## 🔔 Notice

ClaimBack-AI는 본인이 직접 소송 서류를 준비할 때 쓰는 무료 정리 도구입니다. 법률 자문을 제공하지 않으며, 서류에 들어가는 사실은 모두 사용자가 확인한 내용입니다. 법률 상담은 대한법률구조공단(132)이나 변호사에게 받으세요.

ClaimBack-AI is a free self-help tool for organizing your own evidence and filling standard court forms. It does not provide legal advice. Every fact in the documents is confirmed by you. For help, contact your court's self-help center or a small claims advisor.

---

## 📄 License

- Source code and generated sample files: MIT (see `LICENSE`).
- Bundled fonts (`backend/app/templates/fonts/NanumGothic-*.ttf`): SIL Open Font License 1.1 (see `backend/app/templates/fonts/OFL.txt`).
- `backend/app/templates/ca_sc100_blank.pdf`: a California Judicial Council Form SC-100 file included unmodified for form-filling; it is not covered by the MIT license above.
