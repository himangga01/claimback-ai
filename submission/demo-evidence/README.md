# English demo evidence (SAMPLE / DEMO)

Synthetic evidence for the English demo video. Every image carries a red
"SAMPLE / DEMO" band. All people, numbers and addresses are fictional.
"DemoTalk" (messenger) and "SAMPLE Bank" are made-up names, not real brands.
These files are not legal documents and the tests do not use them.

## Story

Jordan Lee (SAMPLE) lent Alex Kim (SAMPLE) KRW 5,000,000 on 2026-03-10, due
2026-04-10. Alex repaid KRW 1,000,000 on 2026-05-01, and the rest is unpaid.
Expected result as of 2026-06-01: principal left 4,014,383 won, total
4,031,430 won.

## Files (upload in this order: EX1 to EX5)

| Exhibit | File | What it shows in the product |
|---|---|---|
| EX1 | `en_chat_01.png` (1080x1920) | Reading a phone chat: the loan request, the amount (5,000,000 won) and the promise to repay by April 10. This first promise is the default highlight quoted in the documents. |
| EX2 | `en_chat_02_tall.png` (1080x5600) | Tiled reading of a long scroll capture (6 tiles): reminders after the due date, new promises, "I sent 1,000,000 won today", and promises for the rest. Utterance tags (reminder, repay_promise, amount_mention). |
| EX3 | `en_transfer_loan.png` (1080x1060) | Loan transfer receipt: 5,000,000 won on 2026-03-10, with full sender and recipient account numbers (pixel redaction keeps the last 4 digits). |
| EX4 | `en_transfer_repay.png` (1080x1060) | Repayment receipt: 1,000,000 won on 2026-05-01 (repayment and interest allocation). |
| EX5 | `en_iou.png` (1080x1800) | IOU with names, addresses, two phone numbers, an ID-style number, amount, dates, a looped lender signature, a cursive borrower signature and a red seal (SAM signature and stamp detection, phone and ID redaction). The borrower is spelled "Alex J. Kim (SAMPLE)" on purpose, so the fact check asks about the name. |

## Layout choices that the product depends on

- Chats only mention amounts that are confirmed facts (5,000,000 and
  1,000,000 won). A quoted line with another comma amount (for example
  "4,000,000 won") would fail the final document check (G1b).
- Chat bubbles stay off the reader's tile edges, so no tile sees half a
  bubble (that produced a stray "it back?" utterance in an earlier run).
- Avatars are plain silhouettes. Initials ("AK") were read as a speaker.
- Receipts: each account number is alone in its column, with about 190px
  to the next account and no other value of similar width nearby. A dense
  right-aligned table made the redaction mask the line above the account
  number. No filled rounded cards: SAM read them as chat bubbles, and the
  account numbers were then masked as in-message text, from the raw boxes.
- IOU: values use Cambria (lining figures; Georgia's old-style "0" looks
  like "o"). Signature labels sit left of the signature, in a gray lighter
  than the product's ink threshold. The lender's scribble has no readable
  letters, so it is not read as another spelling of the lender's name.

## Rebuild

From the repo root:

```powershell
.venv\Scripts\python.exe submission\demo-evidence\make_demo_evidence.py
```

The output is byte-identical on this PC. It uses Windows fonts (Segoe UI,
Cambria, Brush Script); without them it falls back to the repo's
NanumGothic, which changes the look and the hashes.

## Live check (2026-11-04, KST)

Four live runs on port 8030 (00:07 to 00:29 KST), $0.8419 in total. Runs 1
to 3 led to the layout changes above. Run 4 used the files in this folder
($0.2000, 34 calls) and reached `CHECKPOINT_2` with no HOLD:

- Fields: principal 5,000,000, loan 2026-03-10, due 2026-04-10, repayment
  2026-05-01 1,000,000; principal left 4,014,383 and total 4,031,430 as of
  2026-06-01. One conflict and question: the borrower's name.
- Redaction: all four account numbers (last 4 digits kept), both phone
  numbers (middle 4 digits) and the ID number (last 7 digits) masked, with
  no review flags and a passing leak check.
- SAM: both signatures and the seal found. 24 chat_bubble objects on EX2
  (24 messages) and 7 on EX1 (6 messages plus one date pill); nothing on
  the receipts.
- Drafts: all gates passed with no revision; G1b passed on the package.

The model output varies between runs (tags, wording of the conflict note,
drafted sentences). Check the screen before recording.
