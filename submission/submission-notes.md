# 제출 준비 메모 (초안)

- 작성: 2026-11-03 14:16 KST, Claude. 제출 양식 작성과 제출은 사용자가 합니다.
- 마감: 2026-11-04 21:00 ET = **2026-11-05 11:00 KST**, 늦은 제출 불가. 목표: 11-05 07:00 KST 전.
- 근거: `docs/analysis/plan-review.md` 10장(대회 페이지·참가자 안내, 11-03 확인)

## 필수

- [x] 공개 GitHub 저장소: https://github.com/himangga01/claimback-ai (공개·MIT 11-04 확인, 첫 커밋 11-02)
- [x] 3분 데모 영상(대회 기간에 만든 기능만) — 2026-11-04 제작 완료, 2:59 영어. 시작 카드에 서비스 이름·설명·깃 주소·연락 메일(12:48)과 대회 전·대회 중 작업 한 줄(18:37, 주최측 요구). 파일 `C:\2026_project\claimback-demo-video\out\claimback-demo.mp4`, 기록 `submission/demo-video-production.md`. 배경음·효과음은 소유자 자체 합성 코드라 외부 음원 없음
- [x] 영상 올리고 링크 적기 — 사용자가 YouTube에 올림: https://www.youtube.com/watch?v=n8cqk2ZI_Xw (18:48 KST 쿠키 없이 재생 상태 OK, 공개). 제출 양식, README, 사이트 "데모 영상 보기" 링크에 넣음. GitHub Pages의 같은 파일(`docs/demo/claimback-demo.mp4`)은 예비 주소로 남김
- [x] 제출 양식 — **2026-11-04 18:49 KST 제출 완료**("Project Submitted"). 사용자 계정(로그인은 사용자가 함)으로 Claude가 채움. 사용자가 내용 리뷰를 요청해 Claude가 한 번 검토(대회 전 작업 표시 추가, 과장 문장 두 곳 수정), 공개 동의는 사용자가 승인. 제출 뒤 보기 화면에서 모든 항목이 저장된 것을 확인. 마감(11-05 11:00 KST) 전까지 "Update Project"로 고칠 수 있음. 제출한 설문 답(Claude가 근거를 두고 고르고 사용자에게 보여 줌, 이의 없음): Very likely, Somewhat favorable, 추천 4점(API)·4점(Muse Code), 가장 큰 어려움 Slow responses, 다른 모델과 비교 못 함, 가장 중요한 것 품질, 바꾸기 어려운 이유 모델·프롬프트에 맞춰져 있음, 실서비스 걸림돌 사용자 데이터 저장·사용
- [x] 참여자 명단 — 양식의 팀원 칸에 제출 계정 한 명(개인 참가, Indie 트랙)

## 대회 기간 작업 표시 (실격 방지)

- 기준 코드(커밋 76d9cce까지)는 2026-11-02(대회 기간 10-27~11-04 안)에 저장소 소유자가 작성.
- 2026-11-03 M-1부터는 Muse Code(`muse-spark-1.3`)가 구현하고 Claude Code가 명세·지시·리뷰.
- README에 같은 내용이 있음(M2b-fix1). 데모 영상에도 한 줄.

## YouTube 설명란 (영어, 붙여넣기용, 2026-11-04 18:45 KST)

사용자가 직접 올림(일부공개 또는 공개, "아동용 아님"). 장 시작 시각은 최종본(6차 렌더)의 장면 제목 시각에서 뽑았고, YouTube 규칙(0:00 시작, 장마다 10초 이상)에 맞춰 5·6장을 합쳤다. 설명란에는 꺾쇠괄호를 쓰지 않는다(YouTube가 거부). 면책 문구는 `DISCLAIMER_EN` 그대로.

- 제목: `ClaimBack My Money – demo | Meta Global AI Developer Hackathon 2026`

```text
ClaimBack My Money – Your loan records, made clear.

A free self-help agent for people who lent money to a friend and never got it back. It reads your own chat screenshots, transfer receipts and IOU with Meta models, has you confirm every fact, and fills Korean court-document drafts (a demand letter, the payment-order text and an exhibit bundle) that you file yourself. Every number comes from your confirmed facts and deterministic code, never from the AI.

Built during the Meta Global AI Developer Hackathon 2026 (Oct 27–Nov 4): the case flow, agents, Meta model calls and documents. Existed before: the screen's visual style, from the owner's earlier personal project.

The screen was recorded on live Meta Model API calls: 34 calls, $0.19 for the whole case (run case_e91e96da3a3c in the repo's cost ledger). Long model waits are sped up and marked on screen. All people, apps and banks are fictional SAMPLE data.

Meta models (all on the Meta Model API)
- muse-spark-1.2: reads each evidence image with bounding boxes
- sam-3.1: finds chat bubbles, profile pictures, stamps and signature boxes for redaction
- muse-spark-1.3: organizes the facts and drafts sentences with slots only
Built with Muse Code and Claude Code.

Chapters
0:00 Intro and the problem
0:18 1. Upload your own evidence
0:30 2. Role agents on the Meta Model API
1:00 3. You confirm every fact
1:18 It asks instead of guessing
1:31 4. Redaction burned into the pixels
1:53 5. Code does the math, the AI writes slots
2:27 6. Your filing package
2:45 Final check and recap

Links
GitHub (code, setup, architecture): https://github.com/himangga01/claimback-ai
Run it yourself, no key needed: https://github.com/himangga01/claimback-ai#quick-start-no-key-needed
Architecture and where each model runs: https://github.com/himangga01/claimback-ai#architecture
Run with your own Meta Model API key: https://github.com/himangga01/claimback-ai#run-with-your-own-meta-model-api-key
Hackathon: https://cerebralvalley.ai/e/meta-ai-developer-hackathon
Contact: himangga01@gmail.com

ClaimBack-AI is a free self-help tool for organizing your own evidence and filling standard court forms. It does not provide legal advice. Every fact in the documents is confirmed by you. For help, contact your court's self-help center or a small claims advisor.
```

## 제출 양식 답변 (영어, 붙여넣기용)

> 실제 제출본(11-04 18:49 KST)은 아래 초안을 양식 항목에 맞춰 나눈 것이고, 검토에서 세 곳을 고쳤다. (1) "Built during the hackathon"에 "during the hackathon"과 화면 스타일이 소유자의 이전 프로젝트에서 왔다는 문장을 넣음 (2) "Muse Spark 1.3 follows a strict slot-only drafting contract"를 "handles … well, and a rule-based verifier sends back any draft that slips"로 (3) "stopped by a per-run cap"을 "a per-run cost cap stops runaway loops"로. 영상 칸은 YouTube 주소, 파트너 기술 칸은 "We did not use Fireworks, Modal or Baseten for this project; everything runs on the Meta Model API."

2026-11-04 17:50 KST 갱신. 11-03 초안을 README·영상 기준으로 고쳐 양식 항목별로 정리했습니다. 양식 화면(Cerebral Valley "Submit Project")에서 확인한 항목은 팀 이름, 팀원, 트랙, 문제 주제, Most Viral용 X 게시물 링크입니다. 그 아래 항목은 로그인해야 보여서 아직 확인하지 못했고, 흔히 묻는 항목을 미리 준비했습니다. 팀 이름과 트랙은 사용자가 정합니다.

- **Team Name**: ClaimBack My Money
- **Track**: Indie Developer Track (혼자 참가, 개인 개발자. 사용자 확인)
- **Problem statement**: Build for Your World
- **X post link (Most Viral)**: 비워 둠(게시물 없음)
- **Project name**: ClaimBack My Money (ClaimBack-AI)
- **GitHub**: https://github.com/himangga01/claimback-ai
- **Demo video**: https://himangga01.github.io/claimback-ai/demo/claimback-demo.mp4 (2:59. 양식이 YouTube·Loom만 받으면 따로 올려야 함)
- **Live demo / how to try**: 호스팅된 백엔드는 없음. "Runs locally in replay mode with no API key: see Quick start in the README. The demo video was recorded on live Meta Model API calls."
- **Meta tools used**: Muse Spark 1.2, Muse Spark 1.3, SAM 3.1 (Meta Model API), Muse Code
- **Bonus prize**: Best Agentic Use-Case (고르는 칸이 있으면)

**Tagline**

> Your loan records, made clear.

**Short description (1~2문장)**

> ClaimBack My Money is a free self-help agent for people who lent money to a friend and never got it back. It reads your own chat screenshots, transfer receipts and IOU with Meta models, has you confirm every fact, and fills Korean court-document drafts that you file yourself — every number comes from your confirmed facts and deterministic code, never from the AI.

**Description (긴 설명)**

> **The problem.** In Korea, loans between friends are often made over chat with a bank transfer and maybe a handwritten IOU. When the money is not repaid, the cheapest route is to send a certified demand letter (내용증명) or file a payment order (지급명령) yourself. Turning scattered screenshots into a dated, numbered, redacted evidence set and consistent document text is where people give up or pay for help.
>
> **What it does.** Upload your chats, transfer receipts and IOU (or load the synthetic sample case). Role agents work through the files, and you check their work at two checkpoints:
> - Reader (Muse Spark 1.2) reads each image with bounding boxes; long screenshots are read in overlapping tiles.
> - Vision (SAM 3.1) finds chat bubbles, profile pictures, stamps and signature boxes.
> - Fact organizer (Muse Spark 1.3) proposes each value (people, amount, dates, repayments) tied to the exact reading it came from, flags conflicts and asks questions.
> - Privacy (rules) burns account, ID and phone numbers out of the image pixels and flags any mask it cannot confirm.
> - Checkpoint 1: you confirm or correct every value.
> - Calculator (deterministic code) splits repayments between interest and principal and applies statutory rates.
> - Drafter (Muse Spark 1.3) and Verifier (rules) loop: the drafter writes fact sentences with slots only ({{principal}}, {{quote:EX1:item10}}); the verifier rejects literal numbers or names, computed values posing as agreements, facts without evidence and quotes the evidence does not contain, and asks for a rewrite.
> - Draft approval: you approve or edit each sentence.
> - Packager renders the demand-letter PDF, the payment-order text to paste into the e-court form, and the exhibit bundle with "갑 제N호증" marks and an evidence list. A final check re-reads every PDF against your confirmed values.
>
> **Why Meta models.** Spark reads messy Korean screenshots with boxes, so every fact links back to a region of the original image. SAM 3.1 gives the regions used for redaction and for showing evidence. Model choice was measured: Muse Spark 1.2 and 1.3 both matched at least 95% of amounts and dates on our sample set, and 1.2 had the shorter p95 latency (8.8 s vs 33.2 s), so 1.2 reads and 1.3 organizes and drafts.
>
> **Safety by design.** It is not legal advice: no win predictions, no "you can claim" judgments, no legal labels on what people said. The AI writes slots, not values. Redaction is burned into pixels before any PDF is built. All sample evidence is synthetic and marked SAMPLE.
>
> **Built during the hackathon.** Code through 2026-11-02 was written by the owner. From 2026-11-03, Muse Code implemented most milestones while Claude Code wrote the specs and task briefs and reviewed each one; the final fixes were made by Claude Code with two reviewer agents cross-checking. Task briefs, reports, reviews and a ledger of every live Meta API call are in the repo. The demo video was recorded on live Meta Model API calls (34 calls, $0.19).

**How we built it (묻는 경우)**

> Python 3.12, FastAPI and Pydantic v2 on the backend; a zero-build vanilla JS screen in Korean and English; pypdf and reportlab for the PDFs; Pillow for pixel redaction; pytest and Playwright for tests. Meta Model API through the OpenAI SDK, with a per-run cost cap and a replay mode so the whole case runs offline from recorded model responses.

**Challenges (묻는 경우)**

> Very tall chat screenshots: we read them in overlapping tiles and merge the readings. Redaction boxes that landed on the wrong line: the privacy step now checks the mask edges in the pixels and holds anything it cannot confirm for the user. Keeping the model from writing numbers into legal text: slot-only drafting plus a rule-based verifier that sends drafts back.

**What's next (묻는 경우)**

> Finish the US small-claims path (SC-100 and a demand letter), read video evidence frame by frame, and offer a hosted version.

(11-03 초안의 One-liner·What's agentic 내용은 위 설명에 합쳤습니다. Muse Image는 첫 실험에서만 써 보았고 앱에는 없으므로 쓰지 않습니다.)

## 상태 (18:29)

- M4a(SAM·가림)·M4b(판독 모델·조각 읽기)·M5(갑호증·G1b)·M6(화면)·INT-3(통합·재기록) 모두 main에 병합(f4fad58). 실호출로 샘플 사건이 끝까지 통과(`reports/M7-live-check.md`).
- README·데모 대본·녹화 런북(`submission/runbook.md`) 갱신.
- 19:06 INT-3c(Claude 직접 구현, Meta 크레딧 0)로 차용증 쪽 잘림, G1b 실패 시 내려받기 차단, 당사자 블록 표시, 인용문 줄바꿈, 문안 규칙 후속을 고쳐 main에 병합(09090d7, `reports/INT-3c-review.md`). Meta 결제 화면은 18:08부터 계정 오류로 열리지 않음(API는 정상, 지원 티켓 문안 전달).
- 사용자: 영상 녹화(런북), 영상 링크를 이 파일과 제출 양식에, 제출.
