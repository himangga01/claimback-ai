# ClaimBack-AI 코드 리뷰와 구현 상태

- 분석 일시: 2026-11-03 07:00~07:30 KST (Asia/Seoul), Claude
- 범위: `github.com/himangga01/claimback-ai`의 제품 코드 전체(백엔드, 테스트, 프런트엔드, 샘플). 문서는 제품 규칙 위반 여부만 확인
- 기준: 커밋 `76d9cce` (`origin/main`과 같음, 2026-11-02 06:51 KST 푸시)
- 시작 시 작업 트리: 제품 코드 변경 없음. 이 세션의 문서만 추가됨(`AGENTS.md`, `CLAUDE.md`, `specs/ClaimBack-AI_*.md`, `specs/tasks/`, `docs/analysis/`, 수정된 `specs/multi_agent_architecture.md`)
- 비교 기준: 계획서 `specs/ClaimBack-AI_검토_및_구현테스트계획.md` v2.3, 에이전트 설계 `specs/ClaimBack-AI_에이전트_설계.md` v1.1, 4대 에이전트 구조 `specs/multi_agent_architecture.md`
- 관련 문서: 스펙 리뷰 `docs/analysis/plan-review.md` (9장에 저장소 기준선 요약)

## 1. 결론

**문제가 많습니다.** 결정론 계산기와 서류 틀(내용증명, 지급명령 문구, SC-100)은 동작하고 테스트도 있지만, 아래 두 가지가 큽니다.

1. **AI 부분이 하나도 없습니다.** Meta 모델 호출, 증거 업로드, SAM 분할, 판독, 가림, 호증 스탬프가 모두 없습니다. 화면의 SAM 캔버스와 가림은 고정 그림입니다. 해커톤의 핵심인 "Meta 모델 활용"은 0%입니다.
2. **이미 있는 계산과 서류에도 틀린 결과를 내는 버그가 있습니다.** 일부 변제가 있으면 내용증명과 지급명령 문구에 남은 원금을 "대여한 금액"으로 적고, 이자 기산일도 틀립니다. 증거 금액과 입력 금액이 다르면 막아야 하는데 "복원됨"이라고 표시하고 틀린 금액으로 서류를 만듭니다.

그 밖에 실제 사람으로 보이는 이름·휴대폰 번호·아파트 동호수가 공개 저장소에 들어 있습니다.

## 2. 구현 상태 (4대 에이전트 기준)

| 에이전트 | 계획한 기능 | 상태 | 근거 |
|---|---|---|---|
| 1. Forensic Visual | 증거 업로드 | 없음. 화면에 업로드 영역 그림만 있고 파일 입력이 없음 | `frontend/index.html:119-121` |
| | SAM 3.1 분할, Spark 비전 박스 | 없음. 고정 HTML 박스 | `frontend/index.html:160-210` |
| | 개인정보 가림(픽셀 굽기) | 없음. 화면 CSS 흐림 토글만 있음 | `frontend/app.js:92-104` |
| | SHA-256 해시 | 있음(함수). 검사 대상이 `sample_evidence/` 고정 | `verification_gate.py:21-29`, `routes.py:39` |
| | 호증 스탬프 | 없음. 화면 배지만 있음 | `frontend/app.js:106-110` |
| 2. Fact-Timeline Chronology | Spark 판독, 시간순 정리, 발화 유형, 슬롯 초안 | 없음. Meta API 코드와 OpenAI SDK 의존성이 없음 | `requirements.txt` |
| 3. Financial Auditor | 지연손해금, 일부 변제 충당 | 있음. 일수·반올림·약정이자 버그(4장 F5, F6) | `verification_gate.py:44-246` |
| | 검증 게이트 | 있음. 불일치를 통과시키는 버그(F2), 문장 단위 숫자·인용 검사(G1a, G1b, G3) 없음 | `verification_gate.py:259-415` |
| | 금액 한도 | 캘리포니아만 있음. 한국 소액사건 3,000만 원 확인 없음 | `verification_gate.py:351-360` |
| | 소멸시효 판정 | 있음. 제품 규칙상 제거 대상(F7) | `verification_gate.py:142-160, 274-280` |
| 4. Judicial Filer | 내용증명 PDF | 있음. 일부 변제 시 문구 틀림(F4) | `pdf_compiler.py:152-261` |
| | 지급명령 청구취지·청구원인 복사 블록 | 있음. 같은 문제, 게이트 우회(F3) | `pdf_compiler.py:263-335`, `routes.py:129-142` |
| | SC-100 AcroForm 기입 | 있음(Rev. January 1, 2026 양식). 선서 항목 자동 체크(F8), XFA 표시 미확인(F9) | `pdf_compiler.py:40-144` |
| | 갑호증 묶음, 증거설명서 | 없음 | — |
| 공통 | 코디네이터, 체크포인트(사용자 확인 화면), 에이전트 보드 | 없음 | — |
| | 화면 | 3분할 데모 화면 있음. 백엔드가 없으면 고정 "PASS" 결과를 보여 줌(F12) | `frontend/app.js:280-298` |
| | 테스트 | 25개. Windows에서는 22개 통과, 3개 실패(F10) | `backend/tests/` |

계획서 마일스톤 기준으로는 M1(결정론 코어)의 일부와 M5(편철)의 일부만 있습니다. M0, M2, M3(이미지 샘플), M4, M6~M8은 시작 전입니다.

## 3. 코드 구조

```text
backend/app/main.py                 FastAPI 앱, CORS, frontend/ 정적 서빙
backend/app/api/routes.py           /api/verify, /api/compile/{sc100,content-proof,ecourt-packet}, /api/demo/samples
backend/app/schemas/loan_fact.py    LoanFactSchema, GeneratedClaimDraft, VerificationResult (Pydantic v2)
backend/app/services/verification_gate.py  계산기(DeterministicLegalCalculator), 게이트(VerificationGateService)
backend/app/services/pdf_compiler.py       SC-100(pypdf), 내용증명 PDF(reportlab, NanumGothic), 전자소송 문구
backend/app/templates/              SC-100 빈 양식, NanumGothic 폰트
backend/tests/                      게이트·계산기 19개, API 6개
frontend/ (= docs/ 사본)             바닐라 JS, Tailwind CDN, 고정 데모 데이터
sample_evidence/                    텍스트 샘플 3개, manifest, 생성 스크립트 (이미지 없음)
```

데이터 흐름: 화면의 고정 프리셋(JSON) → `/api/verify`(계산과 게이트) → 통과하면 `/api/compile/*`가 `loan_fact`와 계산 결과로 서류 문구를 만듭니다. `claim_draft.statement_of_facts`(LLM 초안 자리)는 인용 개수 확인에만 쓰이고 서류에는 들어가지 않습니다.

## 4. 발견 사항

우선순위: P0 = 데모 전에 반드시 고칠 것(틀린 서류, 개인정보, 규칙 위반), P1 = 이번 해커톤 범위에서 고칠 것, P2 = 여유가 있으면.

### P0

**F1. 실제 사람으로 보이는 개인정보가 공개 저장소에 있음**
- 위치: `backend/app/api/routes.py:152, 176`, `frontend/app.js:14, 37`, `docs/app.js:14, 37`, `backend/tests/test_verification_gate.py`(5줄)
- 내용: 채권자 이름, 010 휴대폰 번호, 아파트 동·호수까지 있는 주소, 우편번호. 이 리포트에는 값을 옮기지 않았습니다.
- 영향: 저장소가 공개 상태이므로 이미 노출되었습니다. 실제 정보라면 파일만 고쳐서는 안 되고 git 기록에도 남아 있습니다. GitHub Pages는 꺼져 있습니다(`has_pages=false`, 2026-11-03 확인).
- 조치: 모든 샘플을 "SAMPLE" 표시가 있는 가상 인물로 바꿉니다. 실제 정보라면 기록 정리(히스토리 재작성)를 할지 사용자가 정합니다.
- (07:40 갱신) 사용자 확인: **가짜 정보입니다.** 개인정보 노출은 아니므로 git 기록 정리는 하지 않습니다. 다만 실제 사람처럼 보여 심사위원에게 오해를 줄 수 있고 제품 규칙(합성 샘플에 SAMPLE 표시)에도 맞지 않으므로, M-1에서 가상 값으로 바꾸는 작업은 그대로 둡니다. 우선순위는 P0에서 P1로 내립니다.

**F2. 증거 금액과 입력 원금이 달라도 서류가 만들어짐**
- 위치: `verification_gate.py:327-334`, `:389-398`
- 재현: 이체증 추출액 5,000,000원, 입력 원금 15,000,000원 → `status=RECONCILED`, `is_valid=True`, `reconciled_amount=15000000`. 메시지는 "증빙 수치로 강제 정렬됩니다"라고 하지만 실제로는 정렬하지 않고 15,000,000원으로 계산합니다.
- 영향: 판독 AI가 금액을 틀리면 틀린 금액이 그대로 서류에 들어가는데, 화면은 "복원됨"으로 보여 줍니다. 제품의 핵심 약속(확인된 값만 서류에)과 정반대입니다.
- 조치: 불일치는 보류(HOLD)로 처리하고 사용자 확인 화면으로 보냅니다. "강제 정렬", "복원" 문구를 지웁니다.

**F3. 전자소송 문구 API가 게이트를 우회함**
- 위치: `routes.py:129-142`
- 재현: 이체 증빙이 없어 `/api/verify`가 `HUMAN_CHECK_REQUIRED`를 돌려주는 사건에도 `/api/compile/ecourt-packet`은 HTTP 200과 완성된 청구취지를 돌려줍니다. 다른 두 PDF API와 달리 `is_valid`를 확인하지 않습니다.
- 조치: 다른 API처럼 `is_valid`가 거짓이면 400과 빈 항목 목록을 돌려줍니다.

**F4. 일부 변제가 있으면 서류 문구가 틀림**
- 위치: `pdf_compiler.py:242`(내용증명), `:293`(청구취지), `:311`(청구원인), `:75`(SC-100 설명)
- 재현: 5,000,000원 대여, 2026-05-01 1,000,000원 변제.
  - 내용증명: "2026-03-10에 금 4,013,699원을 대여하였으며" — 실제 대여액은 5,000,000원
  - 청구취지: "금 4,013,699원 및 이에 대하여 2026-04-11부터 …" — 남은 원금의 기산일은 변제 다음 날(2026-05-02)이어야 함
  - 청구원인: "금 4,013,699원을 대여하였고"
- 원인: 남은 원금(`reconciled_amount`)을 대여 원금 자리에 그대로 씁니다.
- 조치: 대여 원금, 변제 내역, 남은 원금, 기산일을 따로 받는 문구 틀로 바꿉니다(에이전트 설계의 `Calculation` 출력: `remaining_principal`, `accrual_start_date`).

**F5. 변제가 있으면 지연손해금 일수가 하루씩 모자람**
- 위치: `verification_gate.py:65-71`(끝 날짜 제외 계산), `:181-201`
- 재현: 계획서 1-2(8) 예시(5,000,000원, 변제기 2026-04-10, 2026-05-01에 1,000,000원 변제)
  - 코드: 4/11~5/1을 20일로 계산, 지연손해금 13,698.63원, 남은 원금 **4,013,699원**
  - 계획서 기대값: 21일, 14,383원, 남은 원금 **4,014,383원** (684원 차이)
- 원인: 구간 끝을 제외하고 세므로 변제일 당일이 빠집니다. 그 하루는 다음 구간에서 줄어든 원금으로 계산됩니다. 반올림도 계획서(원 미만 버림)와 달리 반올림(`ROUND_HALF_UP`, `:78`, `:242-244`)입니다.
- 조치: "변제일까지 포함, 남은 원금은 다음 날부터"로 고치고 원 미만 버림, 계획서 예시를 테스트로 고정합니다(M1).

### P1

**F6. 약정이자가 있으면 대여 기간 이자를 빼먹고, 청구취지에 법정이율을 씀**
- 위치: `verification_gate.py:181`(변제기 다음 날부터만 계산), `pdf_compiler.py:291`
- 재현: 약정이율 연 12% → 대여일~변제기 이자 0원. 청구취지에는 "연 5%"로 적힘.

**F7. 소멸시효 판정과 "청구가 불가합니다" 차단**
- 위치: `verification_gate.py:142-160, 274-280`, `loan_fact.py:19-20, 146-147`, 화면
- 문제: 청구 가능 여부 판단은 제품 규칙(법적 판단 금지) 위반입니다. 게다가 일부 변제나 상환 약속이 있으면 시효가 중단될 수 있는데 이를 반영하지 않아, 실제로는 청구할 수 있는 사건을 막을 수 있습니다. M-1 지시서에서 제거하도록 했습니다.

**F8. SC-100 선서 항목을 사용자 확인 없이 체크함**
- 위치: `pdf_compiler.py:122-128`
- 내용: Item 4 "지불을 요구했다"를 `demand_date`가 없어도 항상 "예"로 체크하고, Item 5(관할 사유), 7(변호사 보수 분쟁), 8(공공기관), 9(12개월 내 12건 초과)를 고정값으로 채웁니다. SC-100은 위증 처벌을 전제로 서명하는 양식이므로 사용자 답변으로 채워야 합니다.

**F9. SC-100 양식에 XFA가 있어 Adobe Reader에서 값이 안 보일 수 있음(미확인)**
- 위치: `backend/app/templates/ca_sc100_blank.pdf`(`/XFA` 있음), `pdf_compiler.py:135-138`
- 내용: pypdf는 AcroForm 값만 채웁니다. Adobe Reader가 XFA 층을 그리면 채운 값이 보이지 않을 수 있습니다. 현재 테스트는 pypdf로 값을 다시 읽는 것만 확인합니다. Adobe Reader와 브라우저 PDF 뷰어에서 직접 열어 확인해야 합니다.

**F10. Windows에서 테스트 3개 실패 (원인 확인)**
- 원인: 이 PC의 `core.autocrlf=true`가 `sample_evidence/*.txt`를 CRLF로 바꿔 받아 SHA-256이 선언값과 달라집니다. 그래서 "위변조 의심" → 보류 → 400이 됩니다. LF로 받은 복제본에서는 25개가 모두 통과합니다.
- 조치: `.gitattributes`에 `sample_evidence/** -text`를 넣고 다시 받습니다. 실제 증거(이미지)는 바이너리라 이 문제가 없지만, 해시 검사가 텍스트 줄바꿈에 약하다는 점은 남습니다.

**F11. Meta AI 연동이 전혀 없음**
- `requirements.txt`에 OpenAI SDK가 없고, 업로드 API, SAM·Spark 호출, record/replay, 예산 상한, 비용 원장이 없습니다. `GeneratedClaimDraft`는 자리만 있고 생성 코드가 없습니다. 게이트의 "LLM 수치 복원"(`:362-368`)은 상태 표시만 바꾸고, 서류는 원래 `loan_fact`로 만들어지므로 실제로 복원하는 것이 없습니다.

**F12. 화면이 고정 데이터와 가짜 검증 결과를 보여 줌**
- 위치: `frontend/app.js:228-232, 280-298`, `frontend/index.html`
- 내용: 백엔드에 연결되지 않으면 계산하지 않고 고정 숫자와 "PASS"를 보여 주며 "deterministic fallback engine"이라고 기록합니다. 업로드, SAM 캔버스, 가림은 동작하지 않는 그림입니다. 계산 기준일도 `2026-10-31`로 고정입니다(`:218`). 심사 데모에서 실제 동작처럼 보이면 신뢰를 잃습니다.

**F13. 실제 브랜드 이름 사용**
- 위치: 샘플과 화면의 "토스뱅크", "카카오톡", "Chase", "iMessage"(`routes.py:161-162, 184`, `frontend/app.js:23-24, 45-46`, `frontend/index.html:190, 199, 228, 264`, `sample_evidence/`)
- 제품 규칙(가상 앱·은행만)과 충돌합니다.

### P2

- **F14.** 한국 소액사건 3,000만 원 한도 확인이 없습니다(G4 한국 쪽).
- **F15.** 임시 PDF를 지우지 않습니다(`routes.py:71, 111`, `delete=False`). 오류 내용을 그대로 응답에 넣습니다(`:86, :126`). CORS가 모든 출처와 자격 증명을 허용합니다(`main.py:13-19`). 인증이 없는 데모라 영향은 작습니다.
- **F16.** 해시 검사 폴더가 `sample_evidence/`로 고정되어 실제 업로드에는 쓸 수 없습니다(`routes.py:39, 54, 94`).
- **F17.** `lucide@latest`처럼 버전이 고정되지 않은 CDN, 운영용이 아닌 Tailwind CDN을 씁니다(`frontend/index.html:8, 30`).
- **F18.** `frontend/`와 `docs/`를 손으로 복사해 두 벌을 유지합니다. 한쪽만 고치면 어긋납니다.
- **F19.** 과장 표현: README "Zero-hallucination guarantee", "All 25 tests pass"(Windows에서는 거짓), 코드 주석 "완벽 차단", "무결", 내용증명 "우체국 전자내용증명 표준 규격"(근거 없음), `docs/MASTER_PLAN.md` "변호사법 제109조 우회".
- **F20.** 윤년을 366일로 계산합니다(`verification_gate.py:72`). 계획서는 365일 기준이었습니다. 실무 관행 확인이 필요합니다(열린 질문).

## 5. 잘된 점

- 금액 계산을 `Decimal`로 하고, 송달 다음 날부터 연 12%로 바꾸는 구간 분할, 비용→이자→원금 충당 순서, 과오납 처리가 있습니다.
- 캘리포니아 한도($12,500, $2,500 초과 연 2회)를 총청구액 기준으로 확인합니다.
- SC-100은 2026-01-01 개정판이고, 체크박스 내보내기 값(`/1`, `/2`, `/Off`)이 양식의 실제 값과 맞습니다.
- 내용증명 PDF에 NanumGothic이 들어가고 한글 텍스트가 깨지지 않고 추출됩니다(테스트와 이번 확인).
- 보류 사유를 목록으로 돌려주는 구조는 계획서의 HOLD 설계와 맞아 그대로 살릴 수 있습니다.

## 6. 권장 순서

1. **M-1**(진행 대기): F10 수정, F7·F13·F19 정리, Muse Wonder 표기 제거, 비밀값 검사. 여기에 **F1(개인정보 교체), F2(불일치 보류), F3(게이트 우회)** 를 추가했습니다(`specs/tasks/M-1-baseline.md`).
2. **M0**: Meta 클라이언트(예산 상한, 비용 원장, record/replay)와 실호출 스파이크(F11).
3. **M1**: F4, F5, F6, F14 — 계산 출력을 `Calculation`(남은 원금, 기산일, 이율 문구 슬롯)으로 바꾸고 계획서 예시를 고정 테스트로.
4. **M2 이후**: 업로드 → 판독 → 사실 확인 화면 → 계산 → 슬롯 초안 → 서류의 실제 흐름으로 F12의 고정 화면을 대체. SC-100 선서 항목 질문(F8), XFA 확인(F9).

## 7. 열린 질문

1. ~~F1의 개인정보가 실제 정보인지~~ → 해결(2026-11-03 07:40): 사용자 확인 결과 가짜 정보. git 기록 정리 불필요.
2. 지연손해금 계산 관행: 변제일 포함 여부, 윤년 366일 여부, 원 미만 처리. 계획서는 "변제일 포함, 365일, 버림"으로 정했지만 법원 실무 자료로 다시 확인하지 않았습니다.
3. SC-100 Item 3b "언제 일어났는가"에 대여일(`loan_date`)을 넣고 있습니다. 미지급이 시작된 날(변제기)이 맞는지.

## 8. 검증 명령과 결과 (이 세션에서 실행)

```powershell
# 기준선
git fetch origin; git rev-parse HEAD origin/main          # 둘 다 76d9cce
python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd backend; $env:PYTHONPATH = "."; ..\.venv\Scripts\python.exe -m pytest -q
# 3 failed, 22 passed

# F10 원인 확인
git config --get core.autocrlf                            # true
# sample_evidence/kr_transfer_receipt.txt: 작업 트리(CRLF) 해시 522a1493…, git blob(LF) 해시 f350d3ac… (선언값과 같음)
git -c core.autocrlf=false clone <repo> <scratch>; cd <scratch>\backend; pytest -q
# 25 passed

# F2~F6 재현: scratchpad의 probe.py (리포지토리 밖, 커밋 안 함)
$env:PYTHONPATH = "backend"; .\.venv\Scripts\python.exe <scratchpad>\probe.py <scratchpad>
# P1 remaining_principal 4013699 (기대 4014383)
# P2 status RECONCILED is_valid True reconciled_amount 15000000
# P3 verify HUMAN_CHECK_REQUIRED / ecourt-packet HTTP 200
# P4·P6 청구취지·청구원인·내용증명에 "금 4,013,699원을 대여"
# P5 약정 12%: 대여 기간 이자 0.00, 청구취지 "연 5%"

# F9 양식 확인 (pypdf)
# pages 6, "Rev. January 1, 2026", /XFA 있음, 체크박스 상태값 /1·/2·/Off 확인

# 개인정보·브랜드 위치
git grep -c -I -E '<휴대폰·주소 일부 패턴>' -- . ':!*.ttf' ':!*.pdf'
# routes.py 2, tests 5, frontend/app.js 2, docs/app.js 2
```

## 9. 검증 한계

- PDF는 텍스트 추출로만 확인했습니다. 이 PC에 렌더러(poppler)가 없어 화면 모양, 줄바꿈, SC-100의 Adobe Reader 표시(F9)는 보지 못했습니다.
- 프런트엔드는 코드만 읽었고 브라우저에서 열지 않았습니다.
- Meta API는 연동 코드가 없어 호출하지 않았습니다.
- 법령과 계산 관행(F5, F6, F20, 열린 질문 2)은 원문을 다시 열어 확인하지 않았습니다.
- 개인정보가 실제 정보인지는 확인할 수 없습니다.

## 10. 갱신 기록

- 2026-11-03 07:30 KST: 최초 작성 (커밋 76d9cce 기준).
- 2026-11-03 07:40 KST: F1 샘플 개인정보는 가짜라는 사용자 확인 반영. P1로 낮추고 열린 질문 1 해결.
- 2026-11-03 11:40 KST: M-1(Muse Code) 결과 반영. 작업 트리(미커밋)에서 F2, F3, F7, F10 해결, F1·F13은 지시서에 적은 파일만 해결되고 화면 캔버스·샘플 증거에 남음, F19는 README·화면의 일부 과장 표현만 정리됨. 테스트 25개 통과(Windows). 남은 항목과 근거는 `reports/M-1-review.md` R1~R10. 이 문서의 본문 판정(76d9cce 기준)은 고치지 않음.
- 2026-11-03 13:15 KST: F19 후속. `docs/MASTER_PLAN.md`(폐기된 초기 계획)를 GitHub Pages로 공개되지 않도록 `specs/history/MASTER_PLAN-2026-11-02.md`로 옮기고, "변호사법 제109조 우회"·"UPL 우회" 두 줄을 지우고 폐기 표시를 붙임(M2b 화면 리뷰 지적).
