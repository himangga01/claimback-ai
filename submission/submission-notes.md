# 제출 준비 메모 (초안)

- 작성: 2026-11-03 14:16 KST, Claude. 제출 양식 작성과 제출은 사용자가 합니다.
- 마감: 2026-11-04 21:00 ET = **2026-11-05 11:00 KST**, 늦은 제출 불가. 목표: 11-05 07:00 KST 전.
- 근거: `docs/analysis/plan-review.md` 10장(대회 페이지·참가자 안내, 11-03 확인)

## 필수

- [ ] 공개 GitHub 저장소: https://github.com/himangga01/claimback-ai (공개 확인 11-03)
- [x] 3분 데모 영상(대회 기간에 만든 기능만) — 2026-11-04 제작 완료, 2:58 영어. 파일 `C:\2026_project\claimback-demo-video\out\claimback-demo.mp4`, 기록 `submission/demo-video-production.md`. 배경음·효과음은 소유자 자체 합성 코드라 외부 음원 없음
- [ ] 영상 올리고 링크 적기(제출 양식, 이 파일, "데모 영상 보기" 링크)
- [ ] 제출 양식(질문이 많음, 일찍 작성)
- [ ] 참여자 명단

## 대회 기간 작업 표시 (실격 방지)

- 기준 코드(커밋 76d9cce까지)는 2026-11-02(대회 기간 10-27~11-04 안)에 저장소 소유자가 작성.
- 2026-11-03 M-1부터는 Muse Code(`muse-spark-1.3`)가 구현하고 Claude Code가 명세·지시·리뷰.
- README에 같은 내용이 있음(M2b-fix1). 데모 영상에도 한 줄.

## 제출 양식 답변 초안 (영어, 사용자가 다듬기)

- **Track**: Indie developer (사용자 확인 필요)
- **Problem statement**: Build for Your World
- **One-liner**: A free self-help agent that turns your own messy loan evidence (chats, transfer receipts, an IOU, a screen recording) into confirmed facts and filled Korean court-document text — with every number checked by code, not by the AI.
- **Meta tooling used** (18:29 확정): Muse Spark 1.2 (evidence reading with boxes; long screenshots in overlapping tiles — chosen over 1.3 by measured accuracy and latency), Muse Spark 1.3 (fact organizing with evidence links, slot-only drafting), SAM 3.1 (chat bubbles, profile pictures, stamps, signature boxes), Muse Code (all implementation from 2026-11-03). Muse Image was only tried in the first spike and is not in the app.
- **What's agentic**: a rule-based coordinator runs role agents (reader, fact organizer, drafter, verifier, packager) with two human checkpoints; the drafter ⇄ verifier loop rejects drafts with literal numbers/names or missing evidence tags and asks for a rewrite.
- **Safety**: no legal advice or outcome prediction; the AI writes only slots, values come from user-confirmed facts and deterministic calculation; personal numbers are burned out of image pixels; synthetic SAMPLE data only.

## 상태 (18:29)

- M4a(SAM·가림)·M4b(판독 모델·조각 읽기)·M5(갑호증·G1b)·M6(화면)·INT-3(통합·재기록) 모두 main에 병합(f4fad58). 실호출로 샘플 사건이 끝까지 통과(`reports/M7-live-check.md`).
- README·데모 대본·녹화 런북(`submission/runbook.md`) 갱신.
- 19:06 INT-3c(Claude 직접 구현, Meta 크레딧 0)로 차용증 쪽 잘림, G1b 실패 시 내려받기 차단, 당사자 블록 표시, 인용문 줄바꿈, 문안 규칙 후속을 고쳐 main에 병합(09090d7, `reports/INT-3c-review.md`). Meta 결제 화면은 18:08부터 계정 오류로 열리지 않음(API는 정상, 지원 티켓 문안 전달).
- 사용자: 영상 녹화(런북), 영상 링크를 이 파일과 제출 양식에, 제출.
