# 제출 준비 메모 (초안)

- 작성: 2026-11-03 14:16 KST, Claude. 제출 양식 작성과 제출은 사용자가 합니다.
- 마감: 2026-11-04 21:00 ET = **2026-11-05 11:00 KST**, 늦은 제출 불가. 목표: 11-05 07:00 KST 전.
- 근거: `docs/analysis/plan-review.md` 10장(대회 페이지·참가자 안내, 11-03 확인)

## 필수

- [ ] 공개 GitHub 저장소: https://github.com/himangga01/claimback-ai (공개 확인 11-03)
- [ ] 3분 데모 영상(대회 기간에 만든 기능만) — `submission/demo-script.md`
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
- **Meta tooling used**: Muse Spark 1.3 (evidence reading with boxes, fact organizing, slot-only drafting), SAM 3.1 (signature/stamp/chat-bubble segmentation, privacy masking) [M4a 병합 후 확정], Muse Image (textless timeline illustration) [P1, 쓰면 추가], Muse Code (all implementation from 2026-11-03).
- **What's agentic**: a rule-based coordinator runs role agents (reader, fact organizer, drafter, verifier, packager) with two human checkpoints; the drafter ⇄ verifier loop rejects drafts with literal numbers/names or missing evidence tags and asks for a rewrite.
- **Safety**: no legal advice or outcome prediction; the AI writes only slots, values come from user-confirmed facts and deterministic calculation; personal numbers are burned out of image pixels; synthetic SAMPLE data only.

## 남은 일 (Claude가 진행)

- M4a·M4b·M5 병합 후 대본의 [M4a]·[M4b]·[M5] 표시 정리
- M6: 화면 마무리(호출 수 표시, 게이트 줄 색, 폴링 등), Pages 처리
- M8: README 모델 표·실행 방법·런북 최종화, 영상 링크 자리
