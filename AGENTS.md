# AGENTS.md — ClaimBack-AI (Meta Global AI Developer Hackathon 2026)

Shared instructions for every AI agent in this folder. Muse Code reads this file as its project
instructions (after you trust the workspace). Claude Code reads it through `CLAUDE.md`.

## Project

ClaimBack-AI is a free self-help tool that organizes a user's own evidence for an unpaid
personal loan and fills standard court documents (KR: 내용증명, 지급명령 문구, 갑호증;
US/CA: SC-100, demand letter) with facts the user confirms. Runtime AI uses Meta Model API
models (`muse-spark-1.3`, `sam-3.1`, `muse-image-1.0`). Not legal advice.

Service name on screen (user decision, 2026-11-03 before 23:00 KST): 클레임백 마이 머니 /
ClaimBack My Money (logo `claimback my money.`). "ClaimBack-AI" stays the project name and stays
verbatim in the disclaimers (`DISCLAIMER_KO`, `DISCLAIMER_EN`). The screen follows the user's
경매노트 portal design (Paperlogy font, paper sheets, blue cabinet) and has a KO/EN switch
(`?lang=en`); case content and the court documents stay Korean.

## Roles

| Agent | Does | Does not |
|---|---|---|
| Muse Code (`muse --model muse-spark-1.3`) | Implements tasks from `specs/tasks/`, writes and runs tests (including live Meta API tests), writes `reports/M<N>.md` | Change `specs/` (propose changes in the report), add features outside the task, commit or push |
| Claude Code | Maintains `specs/`, writes task briefs, runs Muse Code (`muse exec`), reviews (re-runs tests, reads diffs, checks rendered PDFs/UI) with independent Claude subagent reviewers that cross-check and critique each other, decides pass or fix, writes `reports/M<N>-review.md`, commits and pushes after each passing review | Write or edit product code |
| User | Gets API keys and credits, records the demo, submits. Decided 2026-11-03 12:05 KST: Claude proceeds without asking for approval and commits and pushes along the way. Decided 2026-11-03 evening (Meta credit low, dashboard unreachable from 18:08 KST): Claude Code implements the remaining fixes directly instead of Muse Code (first: INT-3c), still with two cross-checking subagent reviewers | — |

## Canonical documents (read before work, update after)

| Path | What it is |
|---|---|
| `specs/ClaimBack-AI_검토_및_구현테스트계획.md` | Implementation and test plan (v2.2): scope, milestones, test criteria, workflow (section 4) |
| `specs/ClaimBack-AI_에이전트_설계.md` | Runtime agent design (v1.1): agent contracts, state machine, prompt rules |
| `specs/tasks/` | Milestone task briefs (written by Claude) |
| `reports/` | Muse Code milestone reports and Claude reviews |
| `docs/analysis/plan-review.md` | Review of the specs (2026-11-02), findings A1–F3 and their status; section 9: repo baseline and billing screen (2026-11-03); section 10: official hackathon rules, judging, deadline, and billing dashboard (2026-11-03) |
| `docs/code-analysis.md` | Code review and implementation status of the repo (2026-11-03, commit 76d9cce), findings F1–F20 |
| `specs/multi_agent_architecture.md` | The four user-facing agents (Forensic Visual, Fact-Timeline Chronology, Financial Auditor, Judicial Form Filler) mapped to the agent design |
| `specs/case-api-contract.md`, `specs/case-api-examples/` | Case-flow API contract (v2) shared by the backend (M2a) and the UI/E2E (M2b); example responses served by the stub and checked by backend tests |
| `reports/M<N>-review.md` | Claude reviews with subagent cross-review; `reports/M0-review.md` holds the M0 spike decisions (coordinates, video keyframes, reader model pending); `reports/M4b-review.md` holds the reader model decision (muse-spark-1.2) and why video reading is deferred; `reports/INT-3-review.md` is the latest integration review |
| `reports/M7-live-check.md` | End-to-end run of the sample case on the live Meta API (2026-11-03 18:25 KST) |
| `reports/fix-cost-redaction.md` | Case cost vs. ledger (reservation rows offset; reruns keep spend), wrong-line PII masks made needs_review with a stronger leak check, duplicated citations (2026-11-04) |
| `reports/redaction-confirm.md` | Per-exhibit confirmation of flagged redacted copies on the fact-check sheet (`redaction_confirmed` ex_id list, contract 6d), honest leak-check status (`review`) and privacy step note (2026-11-04) |
| `reports/portal-review.md` | Portal redesign and English screen (2026-11-03): what changed, how the KO/EN switch works, tests, cross-review |
| `submission/` | Demo script (`demo-script.md`), recording runbook (`runbook.md`), submission notes and form drafts (`submission-notes.md`) |

Workflow:
- Before any task, read the task brief, the spec sections it cites, and this file.
- Before any analysis, read the specs and `docs/analysis/plan-review.md`. Check dates and baselines,
  and re-verify claims against current code instead of repeating old results.
- Update the existing report for a topic (add an update-log entry) instead of creating a competing
  copy. New topics go to `docs/analysis/<topic>.md`; add new canonical paths to the table above.
- Reports are written in Korean (the specs' language), except service-analysis reports, which are
  written in English (`docs/service-analysis.md`).

## Milestone report format (`reports/M<N>.md`, written by Muse Code)

1. Task brief path and summary of what was done
2. Files created or changed
3. Commands run and results (test pass/fail counts, exact commands so the reviewer can re-run them)
4. Live API calls: models, count, cost (from `reports/cost_ledger.jsonl`)
5. Open problems and deviations from the brief or specs
6. Proposed spec changes (do not edit `specs/` directly)

## Implementation rules (for Muse Code)

- Stack (follow the existing repo, decided 2026-11-03): Python 3.12, FastAPI, Pydantic v2, pytest;
  zero-build vanilla JS frontend in `frontend/` mirrored to `docs/` for GitHub Pages; pypdf and
  reportlab for PDFs; Pillow for pixel redaction; Playwright (Python) for E2E. NanumGothic (OFL)
  fonts live in `backend/app/templates/fonts/`. Do not introduce React, Vite, or PyMuPDF.
- Python environment: `.venv` at the repo root. Run tests with
  `cd backend; ..\.venv\Scripts\python.exe -m pytest -q`.
- This PC runs Windows. Commands run in PowerShell. Do not add bash-only scripts; use Python or
  npm scripts so every command works on Windows.
- Meta API: OpenAI SDK with base URL `https://api.meta.ai/v1`. The app reads its key from
  `MODEL_API_KEY`. Support `META_MODE=live|record|replay`; tests default to `replay`.
- Budget (user decision 2026-11-03 12:00 KST: the goal is to use the whole $150 credit, so there
  are no per-milestone spending caps; spend on live tests, golden-set runs, and higher reasoning
  where it improves the product). Meta spend limits only send alerts and do not stop usage, and
  usage past the credit is billed to the card. The client must record every call's cost in
  `reports/cost_ledger.jsonl` and refuse a call that would exceed the per-run cap
  (`META_RUN_CAP_USD`, default $2) or the total cap (`META_TOTAL_CAP_USD`, default $100). These
  caps only stop runaway loops; raise them through the environment when a task needs more.
- Muse Code itself runs on a pay-as-you-go API key and draws from the same $150 credit as the app.
  The app caps do not cover Muse Code. Stop at the end of the current milestone once the remaining
  credit reaches $10, which is kept for the demo recording (plan section 4-7).
- Use only Standard-tier model IDs. Never use `-contributor` IDs.
- Never read, print, log, or commit `.env` or any key. Use `.env.example` with empty values for
  keys; non-secret settings (`META_MODE`, cap defaults) may have default values.
  Run the secret scan before every commit.
- Golden-set answer files are for tests only; never pass them to runtime agents.
- Keep each task within its brief. If the brief and the specs disagree, stop and report.

## Product rules (everyone)

- Do not use VPNs or other means to reach models unavailable in South Korea (e.g., Muse Wonder).
- No legal evaluation: no win predictions, no "can you claim" judgments, no legal labels on
  utterances (e.g., 채무 승인). The user decides what to highlight.
- Agent names, product text, and generated documents must not present the tool as a lawyer, law
  firm, 법무사, paralegal, legal assistant, attorney, or lawyer. Referral text in disclaimers is
  allowed only through the allowlist (`DISCLAIMER_KO`, `DISCLAIMER_EN`).
- Sample evidence is synthetic, marked "SAMPLE / 데모용", with fictional apps, banks, and people.
  Do not imitate real brands (Toss, Zelle, KakaoTalk).
- Redactions are burned into image pixels before PDF assembly; never rely on PDF overlays.
- Official deadline (checked on the event page 2026-11-03): 2026-11-04 21:00 ET = 2026-11-05 11:00 KST.
  Late submissions are not accepted. Submission target: before 2026-11-05 07:00 KST.
- Submission needs a public GitHub repo, a 3-minute demo video that shows only work built during
  the hackathon, and the submission form. Details: `docs/analysis/plan-review.md` section 10.
