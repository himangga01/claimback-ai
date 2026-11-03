# Demo video plan: ClaimBack My Money (English, 2:54)

- Written: 2026-11-04 00:10 KST by Claude Code (subagent). The user records the voice, edits and submits.
- Baseline: `main` at b559a62 (portal screen and English screen merged), working tree clean.
- Sources: `AGENTS.md` (product rules), `README.md`, `submission/demo-script.md` (earlier script),
  `submission/runbook.md`, `docs/analysis/plan-review.md` section 10 (rules, judging),
  `reports/M7-live-check.md`, `reports/portal-review.md`, `reports/polish-review.md`,
  `frontend/index.html` and `frontend/case.js` (labels and `data-testid`s), E2E screenshots in
  `e2e/artifacts/real/`, and a read-only look at `http://127.0.0.1:8010/?lang=en`.
- Replaces the earlier `submission/demo-script.md` for the English video. That script assumed the Korean
  six-file sample with a video file; this plan uses the new five-file English mock case.

Rules this video keeps:

| Rule | Where it comes from | How the plan keeps it |
|---|---|---|
| Show only work built during the hackathon (10-27 to 11-04); judges must be able to tell | Hackathon rules, `plan-review.md` section 10 | Only the case flow is shown. The video makes no claim about the screen's visual style (see section 6) |
| Not a lawyer or legal service; no win predictions; no "you can claim" | `AGENTS.md` product rules | The narration describes what the tool does with the user's evidence and ends with "Self-help draft. Not legal advice." |
| The user decides what to highlight; no legal labels on statements | `AGENTS.md` | The narration says "you pick". The tags shown are the screen's descriptive tags ("Promises to repay") |
| Synthetic SAMPLE data, no real brands | `AGENTS.md` | DemoTalk, SAMPLE Bank, "(SAMPLE)" names. A corner tag in scene 1 says so |
| Judging: Impact 30, Meta tooling 25, Technical depth 20, Demo 25 | `plan-review.md` section 10 | Problem in scene 1, three models named with live calls and cost in scene 3, code-only math and the G1a gate in scenes 7 and 8, an unbroken live run |

## 0. Before recording

**Server.** Use live mode as in `submission/runbook.md` section 3 (port 8000), opened at
`http://127.0.0.1:8000/?lang=en`. The 8010 server is replay only. Its English case has no recorded
responses, and replay footage would show "(replay)". Check before every take:

- The cover shows no "Replay" badge (`replay-badge` hidden).
- The board summary ends with "live calls", not "(replay)".

**Cost.** About $0.15 to $0.20 per take. This is an estimate from the M7 live run, which cost $0.1635 for
the six-file Korean sample. Plan for at most three full takes. Every call goes into `reports/cost_ledger.jsonl`.

**Browser and capture.**

- Screen 1920×1080, Chrome at 100% zoom, a clean profile with no bookmarks bar, no extension icons
  and notifications off.
- Record at 60 fps (30 is fine). Use a large visible cursor with a click-highlight ring.
- Move the cursor in smooth 300 to 600 ms paths and pause about 0.5 s before each click.
- Keep the address bar visible in shots 1 and 3 so `127.0.0.1` shows that the app runs locally.

**Privacy on screen.**

- Copy the evidence to a neutral folder, for example `C:\ClaimBackDemo\evidence\`, so the Windows
  file dialog does not show the user profile path.
- Point Chrome's download folder to `C:\ClaimBackDemo\out\`, or crop the address bar out of the PDF shots.
- Keep PowerShell, environment variables, dev tools and the cost ledger off screen.

**Evidence order.** Exhibit numbers follow upload order. The evidence is being made in
`submission/demo-evidence/` (`en_*.png`, in progress at 00:12 KST). Its alphabetical order would put the
IOU third, so name the copies in the recording folder with a number prefix as below. Check the evidence
list before each take and update the testids below if the order differs.

| Expected | Copy name (source file) | What it is | Evidence role to confirm (`role-EXn`) |
|---|---|---|---|
| EX1 | `1_chat.png` (`en_chat_01.png`) | DemoTalk chat screenshot | Other |
| EX2 | `2_chat_tall.png` (`en_chat_02_tall.png`) | DemoTalk chat screenshot (tall) | Other |
| EX3 | `3_transfer_loan.png` (`en_transfer_loan.png`) | SAMPLE Bank receipt, 2026-03-10, 5,000,000 | Loan transfer |
| EX4 | `4_transfer_repay.png` (`en_transfer_repay.png`) | SAMPLE Bank receipt, 2026-05-01, 1,000,000 | Repayment received |
| EX5 | `5_iou.png` (`en_iou.png`) | IOU: signature, red seal, phone number, ID-style number, borrower spelled "Alex J. Kim" | IOU |

**Fields to confirm (fact check).** Fill only what is empty or wrong, outside the camera's focus or
during a hover.

| Field | Value |
|---|---|
| Creditor name | Jordan Lee (SAMPLE) |
| Debtor name | the spelling you decide (see below) |
| Principal | 5000000 |
| Loan date | 2026-03-10 |
| Due date | 2026-04-10 |
| Agreed interest rate | empty ("None agreed") |
| Transaction type | Personal (not business) |
| Repayments received | 2026-05-01 / 1000000 |
| As of | 2026-06-01 |

The calculation sheet must then show principal left 4,014,383 won and a reference total of 4,031,430
won as of 2026-06-01. Any other number means a field is wrong. Stop and fix it before you continue.

**Decide before recording: the debtor name.** The plan types `Alex J. Kim (SAMPLE)`, the spelling on
the signed IOU, because a visible correction shows that the user chooses. If you prefer `Alex Kim (SAMPLE)`,
use it in every take. Keep the ` (SAMPLE)` ending on both names: the exhibit bundle prints its SAMPLE
footer only when both names end that way.

**Retake if any of these happens:**

- The "On hold" box appears.
- An exhibit you show is marked for review instead of having a confirmed redaction.
- No name-conflict question appears. You can also use the fallback line for scene 5 in section 2.
- G1b does not pass.
- "(replay)" appears.

## 1. Scene table (total 2:54)

Speed-ups are always labelled, and the label stays up for the whole segment. Model waits are never cut
out without a label. Only page navigation between scenes (a scroll or a tab jump) may be trimmed.
`<sid>` is the id of the draft sentence that holds `{{principal}}`. `EXn` follows the order table in section 0.

| # | Time | On screen | Cursor actions (exact) | Speed | Caption (title / lower-third) | SFX |
|---|---|---|---|---|---|---|
| 1 | 0:00.0–0:16.5 | Portal at `?lang=en` with no case loaded: header with EN pressed, breadcrumb badge "Self-help draft. Not legal advice.", hero "Your loan records, made clear.", five blue folder tabs, blue cover with "Upload files" and "Load the sample case". From 0:05 the five SAMPLE evidence images fan in over the right half (post overlay from the files). | No clicks. The cursor rests at the right edge of the hero, and at 0:15 it glides toward the "Upload files" tile. | — | Title 0:00.5–0:04.5: "ClaimBack My Money" / "Your loan records, made clear." Lower-third 0:05–0:15: "Jordan Lee (SAMPLE) lent Alex Kim (SAMPLE)" / "₩5,000,000 on 2026-03-10 · ₩1,000,000 back". Corner tag for the whole scene: "SAMPLE case: fictional people, apps, banks" | whoosh (title, 0:00.5); whoosh (thumbnails fan in, 0:05) |
| 2 | 0:16.5–0:27.5 | Blue cover → Windows "Open" dialog showing `C:\ClaimBackDemo\evidence\` and only the five files → cover with case ID and status → Agent board with the Intake row "5 files, SHA-256 recorded". | Click the "Upload files" tile (the label around `upload-input`) → click in the dialog's file list, Ctrl+A, click "Open" → click `run-case` ("Run") → click the folder tab `button[data-goto="board-section"]` ("01 Agent board"). | Dialog part 2× if it takes over 3 s (label "Sped up 2×") | Title 0:17–0:21: "1 · Upload your own evidence". Lower-third 0:23–0:27: "SHA-256 recorded for every file" | click (tile); click (Open); click (Run); whoosh (scroll to board) |
| 3 | 0:27.5–0:56.0 | Live Agent board with four cards (Forensic Visual, Fact-Timeline Chronology, Financial Auditor, Judicial Form Filler). Model badges `muse-spark-1.2 · N read`, `sam-3.1`, `muse-spark-1.3`. Rows go Waiting → Running → Done, with substeps per exhibit and their latency. Summary chip "Meta model calls: N · $X · live calls". Ends on the finished board with "Your checks: 6. Your fact check · Waiting for you". | No clicks while the case runs; park the cursor beside the summary chip. When the page scrolls itself to Fact check, click tab "01 Agent board" (trim the jump in the edit). Then hover, about 2 s each and timed to the voice: the Reader badge, the "Visual check (SAM)" row, the Fact organizer badge, the summary chip. | 0:31–0:45: about 65–70 s of reading at about 5× (label "Sped up 5×"; factor = real ÷ shown, rounded) | Title 0:28–0:33: "2 · Role agents on the Meta Model API". Chips timed to the voice: 0:34–0:42 "muse-spark-1.2 reads each image", with a small note 0:36–0:41 "Why 1.2 reads: both ≥95% on amounts/dates," / "1.2 faster (p95 8.8 s vs 33.2 s)"; 0:42.4–0:49 "sam-3.1 finds visual regions"; 0:49–0:52 "muse-spark-1.3 organizes the facts"; 0:52–0:56 "Live Meta API calls · cost on screen" | whoosh (speed-up starts); pop (call count stops, end of the sped-up part); click (tab 01) |
| 4 | 0:56.0–1:14.0 | "02 · Fact check, Checkpoint 1": evidence list ("Exhibit n · hash · Read"), "Original" viewer with blue Spark boxes, and the fields table (Field, Value, Source chips). The amount box on the receipt flashes. | Click tab `button[data-goto="checkpoint-section"]` ("02 Fact check") → click `evidence-EX3` → hover `field-principal` → click `source-chip-principal-EX3-item…` (the box flashes 4×) → click `source-chip-loan_date-EX3-item…` → scroll down → hover `field-due_date` → hover `field-repayments-0-date` and `field-repayments-0-amount` → click `source-chip-repayments-EX4-item…` (the viewer switches to the repayment receipt and flashes). Do not use the tall chat (EX2) for flashes. | — | Title 0:56.5–1:00: "3 · You confirm every fact". Lower-third 1:04–1:09: "Every value links to where it was read" | click + pop on each chip flash (3×) |
| 5 | 1:14.0–1:28.0 | "Conflicts · questions" with the conflict note (in Korean, from the backend) and "Please confirm the exact spelling."; the "Debtor name (conflict)" row; "Statements" with tags ("Promises to repay", "Mentions an amount") and the pre-checked highlight. | Scroll to `conflict-list` and hover the question for 2 s → scroll up to `field-debtor_name`, triple-click it, type `Alex J. Kim (SAMPLE)` → scroll to `utterance-list`, hover the pre-checked `highlight-EXn-itemk` and its "Promises to repay" tag, click it off and on again (it must end checked, so the drafts match the rehearsal). | — | Title 1:14.5–1:18: "It asks instead of guessing". Lower-third 1:18–1:24: "Name conflict: Alex Kim vs Alex J. Kim" | click (field); soft key clicks while typing (low); click ×2 (highlight box) |
| 6 | 1:28.0–1:44.0 | IOU: the "Original" viewer with blue Spark boxes and coral SAM boxes on the red seal and the signature box ("Areas found by SAM" legend), then its "Redacted copy" with the phone and ID-style number masked; then the loan receipt's redacted copy with the account number masked (last 4 digits kept). The screen stacks original and copy, so the editor places the two captures side by side and keeps the screen's own legends. | Scroll up to `evidence-list` → click `evidence-EX5` → hover the coral seal box, then the signature box → scroll to `redaction-col` ("Redacted copy"), hover the masked phone number, then the masked ID number → click `evidence-EX3` → scroll to its redacted copy and hover the masked account number. | — | Title 1:28.5–1:32: "4 · Redaction burned into the pixels". Labels over the split: "Original" / "Redacted copy". Lower-third 1:33–1:38: "Blue: read by Spark · Coral: found by SAM" | whoosh (copy slides in beside the original, 1:33) |
| 7 | 1:44.0–1:57.0 | End of Fact check (As of 2026-06-01, "Confirm and continue") → Agent board while Calculator turns Done and Drafter (`muse-spark-1.3`) runs → "03 · Calculation" sheet: Principal left 4,014,383원, Interest runs from 2026-05-02, Reference total 4,031,430원 as of 2026-06-01, the "Payments applied" row (1,000,000 → 14,383 to interest, 985,617 to principal), and the calculation steps. | Scroll to the end of Fact check → hover `asof` → click `confirm-facts` → click tab "01 Agent board" → wait; the page scrolls itself to Calculation → hover `remaining-principal`, then the `alloc-body` row, then `reference-total`. | Drafting wait (about 25–30 s) at about 7× (label "Sped up 7×"), 1:45.5–1:49.5 | Title 1:49.5–1:53: "5 · Code does the math". Lower-third 1:51–1:57: "Principal left ₩4,014,383" / "Total as of 2026-06-01: ₩4,031,430" | click (Confirm); whoosh (speed-up); pop (calculation sheet lands) |
| 8 | 1:57.0–2:23.0 | "04 · Draft approval": gate chips (all "✓ passed"), Korean sentence cards with "[Exhibit n]" or "(your statement)" tags, slot chips, the edit box; then the red G1a finding, "Fix the issues before approving.", the disabled Approve box and the gate row "Numbers and names only from your confirmed values (G1a): issues found"; then "No issues" again and every box approved. | Scroll to Draft approval → hover `gate-summary` → click `slots-toggle-<sid>` ("Show slots"), hold 2 s → click `edit-toggle-<sid>` ("Edit") → in `edit-<sid>` drag-select exactly `{{principal}}` and type `5,000,000원` (2:10.5–2:13.5) → click `update-<sid>` ("Re-check") at about 2:14.3 → hold 3 s on `findings-<sid>` → press Ctrl+Z until `{{principal}}` is back (fallback: Ctrl+A and type the original text you read first) → click `update-<sid>` → "No issues" → check every `approve-…` box from top to bottom → click `approve-continue`. | 2:19.5–2:23: revert and approvals at 2× (label "Sped up 2×") | Title 1:57.5–2:01: "6 · Slots, not numbers". Lower-third 2:03–2:09: "{{principal}} → filled from your facts". 2:15–2:19.5: "Gate G1a: numbers and names only" / "from your confirmed values" | click (Show slots); click (Edit); soft key clicks while typing; click (Re-check) + low pop as the red finding appears; low clicks on approvals |
| 9 | 2:23.0–2:43.0 | "05 · Filing package": Files (Demand letter (내용증명), Exhibit bundle (갑호증), Evidence list (증거목록)), then three PDF inserts (demand letter page 1; an exhibit page with the redacted IOU, the "갑 제n호증" mark and the SAMPLE footer; evidence list page 1), then "Claim (청구 취지)" with Copy → "Copied", then "Document checks: Final document check (G1b): ✓ passed". | Hover `file-list` (2:23.5) → PDF inserts from shot 13 at 2:28.3, 2:30.3 and 2:32.3 → back on the sheet: scroll to `claim-purpose`, click `copy-claim-purpose` (about 2:35.5) → hover `pkg-gate-list` (2:37.5–2:43). | — | Title 2:23.5–2:27: "7 · Your filing package". Lower-third 2:27–2:33: "Documents in Korean, for Korean courts". 2:38–2:42: "Final document check (G1b) ✓" | whoosh into each PDF insert (×3, low); click (Copy); success chime (G1b "✓ passed", 2:37.5) |
| 10 | 2:43.0–2:54.0 | End card made in the edit: the logo "claimback my money.", the line "muse-spark-1.2 · sam-3.1 · muse-spark-1.3 on the Meta Model API", "Built during the Meta Global AI Developer Hackathon 2026", "github.com/himangga01/claimback-ai", and fine print "All people, apps and banks shown are fictional (SAMPLE)." The stamp "Self-help draft. Not legal advice." appears at 2:50.7 with the voice and holds to the end. | — | — | The end card text above | whoosh (into the end card, 2:43); pop (the stamp appears, 2:50.7, low) |

## 2. Narration

The voice is plain and confident with no hype, the voice of someone explaining a tool to a friend. Aim
for 150 words per minute and leave half a second to a second between scenes. Record the voice first, then
cut the picture to it. The times below are the voice's start inside each scene.

Pronunciation: "Muse Spark one point two", "Sam three point one" (SAM said as the word), "G-one-A",
"SHA two-fifty-six", "I-O-U", "e-Court", "won" (the currency).

**Scene 1** (0:00.8–0:15.6, 36 words)
> You lent a friend five million won; one million came back. Hiring help can cost more than what's left,
> and your records are scattered: chats, receipts, an IOU. ClaimBack My Money helps you organize them
> yourself.

**Scene 2** (0:17.0–0:27.0, 22 words)
> Upload what you already have: two chat screenshots, two transfer receipts and the IOU. Each file gets a
> SHA-256 fingerprint on arrival.

**Scene 3** (0:28.0–0:54.8, 61 words)
> A rule-based coordinator runs the role agents, and three Meta models do the AI work. Muse Spark 1.2
> reads each image and returns text with its position; tall screenshots are read in overlapping tiles.
> SAM 3.1 finds visual regions: chat bubbles, profile pictures, the signature box, the red seal. Muse
> Spark 1.3 organizes the facts. Calls and cost are counted live.

**Scene 4** (0:56.4–1:13.2, 42 words)
> Nothing goes into a document until you confirm it. Each value links back to the spot it was read from:
> click a source, and that box on the evidence flashes. You check the principal, the dates and the
> repayment against the original.

**Scene 5** (1:14.4–1:26.8, 30 words)
> The IOU spells the borrower Alex J. Kim; the chats say Alex Kim. The tool doesn't guess. It asks. You
> choose the spelling, and you pick which statements to highlight.

Fallback if the take shows no name conflict (21 words, same timing). Its cues: "Where the evidence
disagrees," / "the tool doesn't guess. It asks." then "You choose the value, and you pick" / "which
statements to highlight." Drop the scene 5 name lower-third if you use it.
> Where the evidence disagrees, the tool doesn't guess. It asks. You choose the value, and you pick which
> statements to highlight.

**Scene 6** (1:28.6–1:41.8, 33 words)
> Account, ID and phone numbers are masked in the image pixels before anything is packaged, not hidden
> under a PDF layer. A pixel check confirms each mask; anything it can't confirm is flagged.

**Scene 7** (1:44.4–1:55.2, 27 words)
> Confirm, and the calculation is done by code, not AI: the repayment goes to late-payment interest
> first, then principal, and what's left is computed to the won.

**Scene 8** (49 words in four parts, voiced against the actions)
> (1:57.5) Next, Muse Spark 1.3 drafts the fact sentences, each citing its evidence. It never writes a
> number or a name, only slots, filled from the facts you confirmed.
> (2:10.5, while typing) Even a number typed by hand is caught:
> (2:14.5, on the Re-check click) re-check, and gate G1a blocks the sentence.
> (2:19.8) Put the slot back, and approve.

**Scene 9** (2:23.5–2:41.5, 44 words)
> Then your Korean drafts are ready to review, send and file yourself: a certified demand letter, an
> exhibit bundle with redacted copies, an evidence list, and the payment-order text to paste into Korean
> e-Court. Every PDF is checked again against the facts you confirmed.

**Scene 10** (2:43.5–2:52.7, 23 words)
> ClaimBack My Money. You confirm every fact; code does the math. Built during this hackathon with Meta's
> models. Self-help draft. Not legal advice.

Total: 367 written words (about 383 spoken, counting "one point two" and similar as several words).
That is 2:33 of voice at 150 wpm inside a 2:54 video. Each scene runs at 113 to 140 wpm when you
average over its full length.

Accuracy notes for whoever edits the words:

- "three Meta models do the AI work": intake, privacy, calculation, verification and packaging are rules.
  The three models are `muse-spark-1.2`, `sam-3.1` and `muse-spark-1.3`.
- "masked", not "removed": the masks are partial. An account keeps its last 4 digits and a Korean ID
  number its first 6, and a phone number has its middle 4 digits masked (`backend/app/services/redaction.py`).
- "each citing its evidence": the user-statement sentence cites "(your statement)", not an exhibit
  (`reports/M7-live-check.md`).
- "Every PDF is checked again": G1b checks each PDF against the confirmed values. The e-Court text is
  not a PDF.
- Do not add "get your money back", "you can claim", "win", "lawyer", "legal assistant" or "paralegal".

## 3. Captions

**Style**

- Font: Paperlogy (SIL OFL). The repo has only web fonts (`frontend/fonts/Paperlogy-*.woff2`), so the
  editor needs the TTF/OTF of the same family from the official Paperlogy release, or a woff2→ttf
  conversion, which the OFL allows.
- Subtitles: Paperlogy 5 Medium, about 46 px at 1080p, white text on a box in ink `#252722` at 72%
  opacity, radius 4 px, padding 10 by 18 px.
  - Placement: bottom center, 84 px above the bottom edge (inside the 5% safe area).
  - Text rules: at most 42 characters per line and at most two lines. Sentence case, no italics. Digits for
    numbers ("5 million won", "Muse Spark 1.2"), model IDs exactly as the badges show them.
  - Timing: show each cue for 1.2 to 6 s, leave a gap of at least 2 frames, and follow the recorded voice.
    The times below are targets.
- Scene titles: Paperlogy 7 Bold, 40 px, white on the screen's blue `#4162d9` in a folder-tab shape (like
  the portal tabs), top left at the safe margin.
- Lower-thirds: Paperlogy 6 SemiBold, 30 px, blue-ink `#2448bb` on blue-soft `#f0f3ff` with a 3 px left
  rule in `#4162d9` (the style of the board's summary chip). Bottom left, raised above the subtitles. At
  most two lines of 42 characters.
- Speed label: "▶▶ Sped up N×", Paperlogy 6 SemiBold 28 px, white on `#252722` at 80%, top right, for
  the whole sped-up segment.
- Notice stamp at the end: stamp-red `#ac3d32` text and border on `#fff2ee` (the screen's notice badge style).
- Burn the subtitles in and also export an `.srt` with the same cues for the upload.

**Subtitle cues** (line 1 / line 2; the longest line is 40 characters)

| Scene | In | Out | Line 1 | Line 2 |
|---|---|---|---|---|
| 1 | 0:00.8 | 0:05.2 | You lent a friend 5 million won; | 1 million came back. |
| 1 | 0:05.2 | 0:08.4 | Hiring help can cost more | than what's left, |
| 1 | 0:08.4 | 0:12.4 | and your records are scattered: | chats, receipts, an IOU. |
| 1 | 0:12.4 | 0:15.6 | ClaimBack My Money helps you | organize them yourself. |
| 2 | 0:17.0 | 0:20.2 | Upload what you already have: | two chat screenshots, |
| 2 | 0:20.2 | 0:23.0 | two transfer receipts and the IOU. | |
| 2 | 0:23.0 | 0:27.0 | Each file gets a SHA-256 fingerprint | on arrival. |
| 3 | 0:28.0 | 0:30.8 | A rule-based coordinator runs | the role agents, |
| 3 | 0:30.8 | 0:34.0 | and three Meta models | do the AI work. |
| 3 | 0:34.0 | 0:39.6 | Muse Spark 1.2 reads each image | and returns text with its position; |
| 3 | 0:39.6 | 0:42.4 | tall screenshots are read | in overlapping tiles. |
| 3 | 0:42.4 | 0:46.8 | SAM 3.1 finds visual regions: | chat bubbles, profile pictures, |
| 3 | 0:46.8 | 0:49.2 | the signature box, the red seal. | |
| 3 | 0:49.2 | 0:52.4 | Muse Spark 1.3 organizes the facts. | |
| 3 | 0:52.4 | 0:54.8 | Calls and cost are counted live. | |
| 4 | 0:56.4 | 1:00.0 | Nothing goes into a document | until you confirm it. |
| 4 | 1:00.0 | 1:04.4 | Each value links back to the spot | it was read from: |
| 4 | 1:04.4 | 1:08.4 | click a source, and that box | on the evidence flashes. |
| 4 | 1:08.4 | 1:13.2 | You check the principal, the dates | and the repayment against the original. |
| 5 | 1:14.4 | 1:20.0 | The IOU spells the borrower Alex J. Kim; | the chats say Alex Kim. |
| 5 | 1:20.0 | 1:22.4 | The tool doesn't guess. It asks. | |
| 5 | 1:22.4 | 1:26.8 | You choose the spelling, and you pick | which statements to highlight. |
| 6 | 1:28.6 | 1:33.0 | Account, ID and phone numbers are masked | in the image pixels |
| 6 | 1:33.0 | 1:37.0 | before anything is packaged, | not hidden under a PDF layer. |
| 6 | 1:37.0 | 1:41.8 | A pixel check confirms each mask; | anything it can't confirm is flagged. |
| 7 | 1:44.4 | 1:48.4 | Confirm, and the calculation is done | by code, not AI: |
| 7 | 1:48.4 | 1:52.0 | the repayment goes to late-payment | interest first, then principal, |
| 7 | 1:52.0 | 1:55.2 | and what's left is computed to the won. | |
| 8 | 1:57.5 | 2:01.5 | Next, Muse Spark 1.3 | drafts the fact sentences, |
| 8 | 2:01.5 | 2:03.1 | each citing its evidence. | |
| 8 | 2:03.1 | 2:07.1 | It never writes a number or a name, | only slots, |
| 8 | 2:07.1 | 2:09.5 | filled from the facts you confirmed. | |
| 8 | 2:10.5 | 2:13.7 | Even a number typed by hand is caught: | |
| 8 | 2:14.5 | 2:18.1 | re-check, and gate G1a | blocks the sentence. |
| 8 | 2:19.8 | 2:22.2 | Put the slot back, and approve. | |
| 9 | 2:23.5 | 2:28.3 | Then your Korean drafts are ready | to review, send and file yourself: |
| 9 | 2:28.3 | 2:32.3 | a certified demand letter, | an exhibit bundle with redacted copies, |
| 9 | 2:32.3 | 2:37.5 | an evidence list, and the payment-order | text to paste into Korean e-Court. |
| 9 | 2:37.5 | 2:41.5 | Every PDF is checked again | against the facts you confirmed. |
| 10 | 2:43.5 | 2:44.7 | ClaimBack My Money. | |
| 10 | 2:44.7 | 2:47.9 | You confirm every fact; | code does the math. |
| 10 | 2:47.9 | 2:50.7 | Built during this hackathon | with Meta's models. |
| 10 | 2:50.7 | 2:52.7 | Self-help draft. Not legal advice. | |

The scene 1 cue at 0:00.8 overlaps the title card (0:00.5–0:04.5). Put the title at the top left, as in
the style above, so the two do not collide.

## 4. Music brief

- **Mood**: warm, calm, quietly confident, like sorting a messy desk. No legal-thriller tension, no
  triumph and no vocals.
- **Instruments**: felt piano or soft Rhodes motif, light plucks or marimba, a soft shaker or kick pulse,
  and a warm pad.
- **Tempo and key**: 96 BPM, 4/4, major key (D or F). About 70 bars for 2:54.
- **Shape** (the swells come from the arrangement; the mix level stays at 20%):

| Time | Section | Music |
|---|---|---|
| 0:00–0:16.5 | Intro | Piano motif alone, sparse |
| 0:16.5–0:27.5 | Upload | Pulse enters |
| 0:27.5–0:56 | Agents run | Build: plucks join, and a light rising arpeggio carries the sped-up part. First small lift at 0:31, when the speed-up starts |
| 0:56–1:44 | Fact check, redaction | Pulls back to piano, pad and pulse under the most detailed narration |
| 1:44–1:57 | Calculation | Small lift as the numbers land |
| 1:57–2:23 | Drafts and G1a | Light. At 2:14.5–2:19.5 the pulse stops on one held chord for the G1a block (two bars), and it comes back on "Put the slot back" |
| 2:23–2:43 | Filing package | Main swell: full arrangement as the documents appear, peaking around 2:37 at "Every PDF is checked again" |
| 2:43–2:54 | End card | Resolves: the opening motif returns, and the last chord rings out by 2:54 |

- **Mix**: music at 20% of the voice level, about −14 dB under the voice, the whole time, including the
  voice-free beats. Voice at about −16 LUFS integrated with peaks at −1 dBTP. Sound effects sit 12 to 18 dB
  under the voice and never land on a stressed word.
- **Rights**: use a track with a written license for public, competition and online use, such as a
  royalty-free library track or one you own. Record its title, source and license in
  `submission/submission-notes.md`. Using assets without rights is a disqualification reason in the
  hackathon rules.

## 5. Shots for the screen-recording agent (in order)

Record each shot as its own clip at 1920×1080 against the live server. Keep every clip continuous: never
pause the recorder during a model wait, because the editor speeds those up with a label.

| Shot | For scene | Do | Must be visible | Reject if |
|---|---|---|---|---|
| 1 | 1 | Open `http://127.0.0.1:8000/?lang=en`, no case. Rest the cursor at the hero's right edge for 20 s, then glide toward "Upload files". | Address bar with `127.0.0.1`; EN pressed; badge "Self-help draft. Not legal advice."; hero; five folder tabs; blue cover with "Upload files" and "Load the sample case" | A case ID shows, the Replay badge shows, or a notification pops up |
| 2 | 1 | Export the five evidence files as stills (from the files, not the screen). | Each file whole, with its "SAMPLE" marks | Any file looks like a real brand |
| 3 | 2 | Click "Upload files" → dialog in `C:\ClaimBackDemo\evidence\` → Ctrl+A → Open → click `run-case` → click tab "01 Agent board". | Dialog with a neutral path and exactly five files; cover status with case ID; board Intake row "5 files, SHA-256 recorded" | The dialog shows the user profile path or other files |
| 4 | 3 | Record continuously from the Run click until the page scrolls itself to Fact check (about 80 s). Don't touch the page; park the cursor by the summary chip. | Summary chip with a rising count, a rising cost and "live calls"; Reader, Visual check (SAM) and Fact organizer rows with their badges | "(replay)" appears, the "On hold" box appears, or any exhibit is "On hold" |
| 5 | 3 | Click tab "01 Agent board", scroll so the summary chip is at the top, hover the Reader badge, the SAM row, the Fact organizer badge and the summary chip, 2 s each. | Final call count and cost, every row Done, "6. Your fact check · Waiting for you" | — |
| 6 | 4 | Click tab "02 Fact check" → `evidence-EX3` → hover `field-principal` → click the principal source chip on EX3 → click the loan-date chip → scroll → hover due date and repayment → click the repayment chip on EX4. | Blue boxes on the receipt; each flash; values 5000000, 2026-03-10, 2026-04-10, 2026-05-01 / 1000000 | A flash lands on empty space (retake with another chip) |
| 7 | 5 | Hover `conflict-list` → triple-click `field-debtor_name`, type the agreed name → hover `utterance-list` and toggle the pre-checked highlight off and on. Off camera afterwards: check every `role-EXn`, the transaction type and the empty interest rate against section 0. | "Debtor name (conflict)", the question "Please confirm the exact spelling.", the statement tags | No name conflict (use the fallback line for scene 5 or retake) |
| 8 | 6 | Click `evidence-EX5`, hover the coral seal box and the signature box. | "Original" legend, blue and coral boxes, "Areas found by SAM" legend | No coral boxes on the IOU |
| 9 | 6 | Scroll to `redaction-col` for EX5 and hover the masked phone and ID numbers; then click `evidence-EX3` and hover its masked account number. | "Redacted copy" legend; masks over the numbers; last 4 account digits kept | A number is still readable, or the exhibit is marked for review |
| 10 | 7 | Scroll to the end → hover `asof` → click `confirm-facts` → click tab "01 Agent board" → keep recording until the page scrolls itself to Calculation → hover `remaining-principal`, the `alloc-body` row and `reference-total`. | Drafter row `muse-spark-1.3` Running → Done; 4,014,383원; 4,031,430원; the 14,383 / 985,617 split | Other numbers (a field is wrong) |
| 11 | 8 | Follow the scene 8 cursor actions in order, from `gate-summary` to `approve-continue`. | Slot chips; the typed `5,000,000원`; the red G1a finding, the notice and the disabled Approve box; then "No issues"; every box checked | G3 or another gate also trips (retake, and change only the `{{principal}}` slot) |
| 12 | 9 | When Filing package lands: hover `file-list` → scroll to `claim-purpose`, click `copy-claim-purpose` → hover `pkg-gate-list`. | The three file links; "Copied"; "Final document check (G1b): ✓ passed" | G1b not passed |
| 13 | 9 | Click `file-content_proof.pdf`, `file-exhibits.pdf` and `file-evidence_list.pdf`, open each download in Chrome's PDF viewer at fit-to-width, and hold 4 s per page: demand letter page 1, the exhibit page with the redacted IOU, evidence list page 1. | Korean text; the "갑 제n호증" mark; the SAMPLE footer; masked numbers | The address bar shows the user profile path (change the download folder or crop the bar) |
| 14 | — | Off camera: click `delete-case`, stop the server (Ctrl+C) and close the window that holds the key. | — | — |

## 6. What not to show, and why

| Do not show or say | Why |
|---|---|
| Video evidence or a scroll recording | Video is stored and hashed but not read or redacted in this version (`README.md` Known limits, `reports/M4b-review.md`) |
| US SC-100 or California forms | The US path is partial; the backend accepts KR cases only (`reports/portal-review.md`) |
| Muse Image | It was tried only in the first spike and is not in the app (`submission/submission-notes.md`) |
| The header "Korean e-Court" button or the guide's e-Court link, clicked on camera | Both open the real court site. That is not hackathon work, and on camera it could look like an affiliation |
| Reading boxes or chip flashes on the tall chat screenshot | Boxes on very tall screenshots are still approximate (`README.md` Known limits). Use the receipts and the IOU |
| The portal's visual style, presented as new | The layout, colours, font and folder-tab look are adapted from the owner's pre-hackathon project 경매노트 (`README.md` "How it was built"). The video should present the case flow, agents and checks, which were built during the hackathon. You may add to the end card's fine print: "Screen style adapted from the author's earlier project; every feature shown was built during the hackathon." |
| Mixed replay and live footage | Replay shows "(replay)" and the Replay badge, which would contradict "Calls and cost are counted live" |
| Terminal, environment variables, dev tools, the cost ledger file | They risk showing a key or account details |

Expected and fine: some backend text stays Korean on the English screen. That includes the conflict
note, the G1a finding text and the package notices (`reports/portal-review.md`). The English lower-thirds
cover them.

## 7. Verification and limits

Checked in this session:

- Narration word counts, per-scene pacing and caption line lengths, computed by a script (not saved in
  the repo):
  - 367 written words, about 383 spoken
  - every scene's voice ends 0.5 to 2.2 s before the scene ends
  - longest subtitle line 40 characters; every lower-third 42 characters or fewer
- Every button label, legend and `data-testid` in the tables appears in `frontend/index.html` or
  `frontend/case.js` at b559a62 (for example `source-chip-…`, `slots-toggle-…`, `update-…`,
  `copy-claim-purpose`, `button[data-goto=…]`).
- Screen behavior read from code:
  - Re-check runs the rule gates only, so no model call.
  - The calculation sheet appears only after drafting finishes.
  - PDF links download the file.
  - The original and the redacted copy stack vertically.
- Layout from the E2E screenshots in `e2e/artifacts/real/` (Korean sample, replay, 2026-11-03 23:26).
- The cover at `http://127.0.0.1:8010/?lang=en`, viewed without loading a case, so the replay server
  was not changed.

Not checked:

- The English mock case on the live API. It was still being made, so the exhibit order, conflicts,
  sentence ids, call count, cost and PDF pages are expected values, not observed ones.
- Whether the IOU's ID-style number is detected and masked. The privacy rules were written for Korean
  formats.
- Whether the organizer raises the name-conflict question. Scene 5 has a fallback line.

## Update log

- 2026-11-04 00:10 KST: First version (Claude Code subagent). English 2:54 plan for the five-file
  Jordan Lee / Alex Kim mock case, recorded live.
- 2026-11-04 02:45 KST: The video was produced from this plan without a human recording or edit:
  Voicebox voice "Ryan", music and effects synthesized by the owner's own 네모썰 code (no
  third-party audio, so no licence entry needed), Remotion edit, live take 2 of 3. Deviations and
  measurements are in `submission/demo-video-production.md`.
