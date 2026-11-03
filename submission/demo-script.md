# 3분 데모 대본 (초안)

- 작성: 2026-11-03 14:16 KST, Claude. 녹화와 제출은 사용자가 합니다.
- 기준: 계획서 5장 데모 흐름, 대회 심사 기준(실제 효용 30, Meta 도구 활용 25, 기술 완성도 20, 데모 25 — `docs/analysis/plan-review.md` 10장)
- 원칙: 대회 기간에 만든 기능만 보여 줍니다. 법률 자문·승소 예측처럼 들리는 말을 하지 않습니다("돈을 받아 준다" X, "본인이 서류를 준비하도록 돕는다" O). 화면에 "SAMPLE / 데모용" 샘플만 씁니다.
- 표시: [완료] 지금 동작, [M4a]·[M4b]·[M5] 해당 작업이 병합된 뒤 녹화.
- 녹화 모드: 리허설은 재생 모드(`META_MODE=replay`), 본 녹화의 판독 장면 한 번은 실호출(`META_MODE=live`)로 찍고 화면 위 "재생" 배지가 없음을 보여 줌.

| 시간 | 화면 | 영어 내레이션(안) | 한국어 자막(안) |
|---|---|---|---|
| 0:00–0:15 | 제목, 샘플 사건 소개 | "A friend borrowed 5 million won and paid back only 1 million. Hiring help can cost more than what's left. ClaimBack-AI helps you organize your own evidence and fill the standard forms yourself." | 지인에게 500만 원을 빌려주고 100만 원만 돌려받았습니다. 남은 돈보다 대리 비용이 클 수 있습니다. ClaimBack-AI는 본인 증거를 정리해 표준 서류를 직접 쓰도록 돕습니다. |
| 0:15–0:35 | [완료] "샘플 사건 불러오기" → 증거 6개(갑 제1~6호증)와 SHA-256 | "Upload chats, a scroll video, transfer receipts and an IOU. Each file is hashed so you can show it hasn't changed since upload." | 대화 캡처, 스크롤 영상, 이체 확인증, 차용증을 올립니다. 올린 뒤 바뀌지 않았음을 보이도록 파일마다 해시를 남깁니다. |
| 0:35–1:05 | [완료] 에이전트 보드: 4개 역할 에이전트, 판독 담당이 증거별로 진행(긴 화면은 조각으로 나눠 읽음), 모델 배지 `muse-spark-1.2`(판독)·`muse-spark-1.3`(사실 정리·문안)·`sam-3.1`, 실제 호출 수·비용. 영상 증거는 해시만 기록하고 판독은 다음 버전(16:46 결정) | "A rule-based coordinator runs role agents. Muse Spark reads each piece of evidence and returns text with boxes; long screenshots are read in overlapping tiles." | 규칙 기반 코디네이터가 역할별 에이전트를 순서대로 돌립니다. Muse Spark가 증거를 읽고 위치 박스와 함께 원문을 냅니다. 긴 화면은 겹치는 조각으로 나눠 읽습니다. |
| 1:05–1:30 | [완료] 체크포인트 1: 이미지 위 Spark 판독 박스, 근거 칩, 사용자가 값을 확인하고 "갚겠다는 말"을 강조 | "Nothing goes into a document until you confirm it. Every value links back to where it was read." | 사용자가 확인한 값만 서류에 들어갑니다. 모든 값은 읽은 위치로 연결됩니다. |
| 1:30–1:55 | [M4a] SAM 3.1: 말풍선·프로필 사진·도장 마스크, 서명 칸, 계좌번호(끝 4자리 유지)·주민번호(앞 6자리만 유지) 픽셀 가림, "갑 제N호증" 표시, 가림이 의심스러우면 "확인 필요" | "SAM 3.1 finds the chat bubbles, profile pictures and the red stamp, and outlines each signature box; the ink inside is measured with a simple pixel rule. Account numbers are blacked out in the image pixels, keeping only the last four digits, and anything the checker can't confirm is flagged for review." | SAM 3.1이 말풍선·프로필 사진·도장을 찾고 서명 칸을 잡습니다(칸 안의 잉크는 픽셀 규칙으로 잼). 계좌번호는 끝 4자리만, 주민번호는 앞 6자리만 남기고 이미지 픽셀에서 가립니다. 확인이 안 된 가림은 "확인 필요"로 표시합니다. |
| 1:55–2:25 | [완료] 계산 단계(지연손해금 14,383원 → 원본 985,617원 충당 → 남은 원금 4,014,383원), 초안 문장을 "500만 원을 보냈습니다"로 고치면 G1a가 막는 장면 | "The math is deterministic code, not AI. And the AI never writes numbers or names — only slots. Type a number into a sentence and the verifier blocks it." | 계산은 AI가 아니라 규칙 코드가 합니다. AI는 숫자·이름을 직접 쓰지 않고 슬롯만 씁니다. 문장에 숫자를 넣으면 검증 담당이 막습니다. |
| 2:25–2:50 | [완료] 패키지: 지급명령 신청 문구(복사 버튼), 내용증명 PDF / [M5] 갑호증 통합 PDF, 증거 목록, G1b 최종 대조 | "You get the payment-order text to paste into the e-court form, a certified-letter PDF, and an exhibit bundle — checked once more against your confirmed values." | 전자소송에 붙여 넣을 지급명령 신청 문구, 내용증명 PDF, 갑호증 묶음이 나옵니다. 마지막에 확인한 값과 한 번 더 대조합니다. |
| 2:50–3:00 | 고지 문구, Meta 모델 목록, 개발 방식 | "Free self-help, not legal advice. Built during the hackathon with Muse Spark, SAM 3.1 and Muse Code — Claude Code wrote the specs and reviews." | 무료 본인 작성 도구이며 법률 자문이 아닙니다. 대회 기간에 Muse Spark, SAM 3.1, Muse Code로 만들었습니다. |

## 녹화 전 확인

- `main` 최신, 테스트·E2E 통과, 크레딧 $10 이상.
- 실호출 장면 1회 비용 예상: 판독 5~6회 + 사실 정리 + 문안 작성 ≈ $0.15~0.3.
- 화면 1920×1080, 브라우저 확대 100%, 알림 끄기.
- 영상 링크를 `frontend/index.html`·`docs/index.html`의 "데모 영상 보기"에 넣기(M8).
