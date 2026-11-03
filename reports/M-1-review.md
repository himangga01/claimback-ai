# M-1 리뷰 (Claude)

- 작성: 2026-11-03 11:40 KST, Claude Code
- 대상: `reports/M-1.md`(Muse Code), 작업 트리 변경분. 기준 커밋 76d9cce, M-1 결과는 아직 커밋하지 않음
- 실행: `muse exec --model muse-spark-1.3 --contributor-mode off --yolo`(사용자 지시로 샌드박스 없이), 11:21:51~11:37, 종료 코드 0, 모델 호출 78회(실패 0)
- 판정: **통과.** 완료 기준 4개를 다시 실행해 리포트와 같은 결과를 얻었고 범위 밖 변경은 없습니다. 아래 R1~R3은 지시서가 범위를 좁게 잡아 남은 것으로, 다음 지시서(M1, M3)에 넣습니다.

## 1. 완료 기준 재실행 (11:40 KST, 이 세션)

```powershell
cd C:\2026_project\claimback-ai-meta\backend
..\.venv\Scripts\python.exe -m pytest -q
# 25 passed, 1 warning (Starlette httpx 사용 중단 경고), 종료 코드 0
cd ..
.\.venv\Scripts\python.exe tools\secret_scan.py
# secret_scan: clean, 종료 코드 0
Select-String -Path backend\app\*.py,backend\app\*\*.py,frontend\*,docs\index.html,docs\app.js,README.md -Pattern 'Wonder','소멸시효','statute of limitations','채무 인정','debt acknowledg','Zero-hallucination','attorney fees','토스','카카오','Chase','iMessage'
# 0건
git grep -n -E '010-[0-9]{4}-[0-9]{4}' -- . ':!*.ttf' ':!*.pdf'
# 12건, 고유값은 010-0000-0000 하나
```

추가 확인:
- `specs/`, `AGENTS.md`, `CLAUDE.md`, `docs/analysis/`, `docs/code-analysis.md`: M-1 전에 떠 둔 사본과 해시가 모두 같음(Muse Code가 건드리지 않음).
- `frontend/`와 `docs/`의 `app.js`, `index.html`, `styles.css`: 해시가 서로 같음.
- 비밀값 검사가 실제 키 형식을 잡는지: 사용자 환경 변수의 키를 값 출력 없이 `RULES`에 대 보니 `llm-key` 규칙에 걸림.
- `.env`는 `.gitignore`에 있음(`git check-ignore`).

## 2. 지시서 항목별 확인

| 항목 | 결과 | 근거 |
|---|---|---|
| 1 실패 테스트 3개 | 통과 | `.gitattributes`에 `sample_evidence/** -text`, LF로 다시 받음. 테스트 완화 없음 |
| 1a 샘플 인적사항 | 지시 범위는 통과, 남은 것 있음(R1) | 4개 파일은 `홍길동(SAMPLE)`, `010-0000-0000`, `00000`, 가상 주소로 바뀜 |
| 1b 증거 금액 불일치 보류 | 통과 | `verification_gate.py:298-306`이 `missing_requirements`에 넣음. 새 테스트 `test_transfer_amount_mismatch_requires_human_check` |
| 1c 전자소송 문구 게이트 | 통과 | `routes.py:134-149`이 `is_valid` 거짓이면 400. 새 테스트 `test_api_compile_ecourt_packet_blocked_when_hold` |
| 2 소멸시효 제거 | 통과 | 계산 함수, 게이트 검사, 스키마 필드 2개, 화면, README 제거. 테스트 2개 삭제(리포트에 이름 기록) |
| 3 Muse Wonder 제거 | 통과 | README, 화면 모두 Muse Spark 1.3 |
| 4 법적 라벨·브랜드·과장 | 대부분 통과, 남은 것 있음(R2, R3) | 목록의 4개 브랜드와 `0% Hallucination Proof`는 바뀜 |
| 5 pytest.ini | 통과 | `pythonpath = .`, README PowerShell 명령 |
| 6 비밀값 관리 | 통과 | `.env.example` 빈 값, `.gitignore`에 `.local/`, `backend/data/`, `tools/secret_scan.py` |
| 7 docs 사본 | 통과 | 해시 같음. `docs/MASTER_PLAN.md`는 첫 줄만 추가 |
| 8 리포트 | 통과 | `reports/M-1.md`, AGENTS.md 형식 6개 절 |

테스트 수: 기존 25개에서 2개 삭제, 2개 추가해 25개.

## 3. 발견 사항

| ID | 우선순위 | 내용 | 위치 | 처리 |
|---|---|---|---|---|
| R1 | P1 | 1a를 4개 파일로만 지정한 지시서 결함. 화면 캔버스, 샘플 증거 텍스트, 생성 스크립트에는 이전 샘플 이름과 그 번호 끝자리가 남아, 데모에서 증거 화면의 이름과 서류의 이름이 다르게 나옴. 값은 여기 적지 않음 | `frontend/index.html:138,199`(docs 사본 같음), `sample_evidence/kr_transfer_receipt.txt`, `kr_chat_log.txt`, `us_wire_receipt.txt`, `generate_mock_evidence.py:11,24,26,37` | M3(샘플 증거 재작성)에서 교체하고 해시를 다시 계산 |
| R2 | P1 | 실제 은행 이름 1건이 F13 목록에 없어 남음 | `frontend/index.html:203`(docs 같음) | M3 |
| R3 | P1 | 게이트 메시지와 화면에 법적 판단·라벨 표현이 남음: "청구권이 발생하지 않았습니다", "법적 청구 대상이 존재하지 않습니다", 400 응답의 "법적 요건사실 결손", 증거 제목 "Promissory Admission", 화면 "변제기 합의 입증" | `verification_gate.py:295,320`, `routes.py:66,106,146`, `routes.py:197`, `frontend/app.js:46`, `test_verification_gate.py:112`, `frontend/index.html:228` | M1에서 사실 문구로 바꿈(예: "변제기(날짜)가 기준일보다 뒤입니다. 확인할 칸: 변제기") |
| R4 | P2 | LLM 청구금액 경로의 "복원"과 `RECONCILED`, `tampering_reconciliations` 설명이 남음. 지시서가 이번에는 손대지 말라고 한 부분 | `routes.py:37`, `loan_fact.py:32,148`, `verification_gate.py:333,337,366` | M1에서 G3 규칙(차단 후 확인값으로 다시 채움)에 맞춰 정리 |
| R5 | P2 | 미국 샘플 채무자의 이름·주소가 유명 TV 드라마 인물·회사 주소와 같음. 실존 인물은 아니지만 "가상 인물" 규칙 취지상 바꾸는 편이 안전 | `routes.py:189`, `frontend/app.js:38`, `test_verification_gate.py:90` | M3 |
| R6 | P2 | 비밀값 검사가 `.env`만 보고 `.env.local` 같은 변형은 보지 않음 | `tools/secret_scan.py:46-47,81-89` | M0 지시서에 한 줄 추가 |
| R7 | 정보 | Muse Code가 편집한 파일의 줄바꿈을 LF로 바꿈. `core.autocrlf=true`라 내용 차이는 없고 `styles.css` 2개는 상태만 수정됨으로 보임. 커밋할 때 정규화됨 | 작업 트리 | 조치 없음 |
| R8 | 정보 | `.claude/scheduled_tasks.lock`은 Claude Code의 5분 예약 확인 파일. 커밋 대상 아님 | 작업 트리 | `.git/info/exclude`에 추가(로컬 설정) |
| R9 | 정보 | `requirements.txt`에 `uvicorn`이 없어 README 서버 실행 명령이 따로 설치를 가정함(Muse Code 보고) | `requirements.txt` | M2(서버를 띄우는 E2E)에서 추가 |
| R10 | P2 | 화면의 `25/25 Tests Passed` 고정 문구는 테스트 수가 바뀌면 틀림 | `frontend/index.html:98` | M6 UI 정리 때 빼거나 실제 값으로 |

## 4. Muse Code 제안(리포트 6번) 처리

- 지시서 인용 "에이전트 설계 4-3 발화 유형" → 3-4: 맞는 지적. `specs/tasks/M-1-baseline.md`를 고침.
- 계획서 4-5절 M-1행·4-9절의 React·Vite·PyMuPDF 언급: 받아들임. v2.3 머리말이 우선한다는 문장으로 당장은 충분하고, 시간이 날 때 표를 고침.
- 소멸시효 경고 문구: 계산·판단은 계속 하지 않음. 계획서 3장의 "경고 문구만"은 고지 허용 목록(`DISCLAIMER_KO`, `DISCLAIMER_EN`)에 고정 문장 하나를 두는 것으로 정함. 문장안: "청구할 수 있는 기간은 법으로 정해져 있습니다. 이 도구는 기간을 계산하지 않습니다." 넣는 시점은 M5(편철 고지)입니다.

## 5. 비용과 크레딧

- 앱 실호출: 0회, $0(리포트와 같음, `reports/cost_ledger.jsonl` 없음).
- Muse Code(M-1 실행 로그 `run.usage`): `muse-spark-1.3` 78회, 입력 12,797,258토큰(그중 캐시 12,589,821), 출력 80,406토큰(추론 50,144 포함 여부 미확인).
- 추정 사용액: 약 **$2.5~2.7**. 입력 $1.25, 캐시 입력 $0.15, 출력 $4.25(100만 토큰당)로 계산했습니다. 캐시 단가는 제3자 가격 정리(LiteLLM 등) 값이고 Meta 공식 페이지에서는 확인하지 못했습니다. 캐시 할인이 없다면 약 $16이 되므로 대시보드 값으로 확인해야 합니다(결제 데이터는 최대 1시간 늦게 반영).
- 남은 크레딧: **$144.92**(11:52 Billing 화면, Claude가 사용자 Chrome에서 확인. 반영은 최대 1시간 늦음). 멈춤 기준 $50까지 $94.92 남음. 같은 시점 Usage 합계(입력 20.3M, 캐시 95.8%, 출력 177.7k, 요청 190건)를 위 단가로 계산하면 약 $4.7로 차감액 $5.08과 비슷해, 캐시 할인 단가가 적용되는 것으로 봅니다(`docs/analysis/plan-review.md` 10장).
- 배분 재검토(계획서 4-7 "M-1 뒤 다시 나눔"): 추정이 맞다면 마일스톤당 $3 안팎이라 Muse Code 몫 $100 안에서 충분합니다. 지금 배분을 유지합니다.

## 6. 검증 한계

- 화면은 브라우저로 열어 보지 않았고(정적 파일 diff와 해시만 확인), PDF는 이번 변경과 무관해 다시 렌더하지 않았습니다.
- Muse Code 로그는 이벤트 종류와 첫 줄만 요약해 봤고, 모든 도구 출력을 읽지는 않았습니다.
- 비용은 추정입니다(5절).
