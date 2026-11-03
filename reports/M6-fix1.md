# M6-fix1 리포트: 화면 리뷰 반영 (Muse Code)

- 작성: 2026-11-03 (KST), Muse Code (`muse-spark-1.3`)
- 작업 트리: `C:\2026_project\claimback-wt\m6` (브랜치 `m6`, 시작 시점 깨끗함, `main` 병합済)
- Python: `C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe` (공유 venv, 신규 생성 없음)
- 지시서: `specs/tasks/M6-fix1-ui-review.md` (먼저 읽음: `AGENTS.md`, 지시서, `reports/M6.md`, `reports/M6-review.md`, `specs/case-api-contract.md`)

## 1. 지시서와 한 일

지시서 7개 항목을 화면·E2E 파일 범위 안에서 모두 처리했고 실호출 없음:

- 1 (차단, 금액 입력 변환): `parseAmountInput`이 `^\s*\d[\d,]*\s*원?\s*$`에 맞는 표시 형식("5,000,000원", "5000")일 때만 정수 문자열로 바꾸고, 그 밖("500만 원", "1억 2천만원", "-1000" 등)은 입력 그대로 보내 서버가 400으로 거부하게 고침. 400이면 서버 메시지를 해당 금액 칸 옆(`error-field-principal`, `error-field-repayments-*-amount`)에 표시(상태 줄도 유지). 세 예문은 실제 백엔드 전용 신규 E2E(`test_fix1_amount_rejected`)로 고정: PUT 본문이 원문 그대로인지, 400인지, 칸 옆 오류가 보이는지, 상태가 `CHECKPOINT_1`에 머무는지 확인 후 "5,000,000원"으로 정상 진행(`"5000000"` 전송, `DRAFT_APPROVAL` 도달).
- 2 (방어): `S.redactions.previews`·`S.segments`가 배열이 아니면 빈 배열 취급(`selectEvidence` 예외로 체크포인트 전체가 안 그려지는 일 방지). `conflictText`는 문자열·객체(`fields`+`note`·`message`)에서 건질 게 있으면 문장으로, 없으면 `null`을 돌려 그 줄을 그리지 않음(숫자·`null`·배열·빈 객체는 스킵).
- 3 (호출 수): `reading`·`vision`은 `substeps` 중 `done`만 세고, 나머지 모델 단계는 `attempts` 합산(보류된 판독 제외). E2E는 실제 백엔드에서 `CHECKPOINT_1` 뒤 6회·`DRAFT_APPROVAL` 뒤 8회를 숫자로 직접 확인(JS 규칙 복사 없음). 가짜 서버에서만 규칙 크로스체크 유지.
- 4 (실행 중 삭제): `approveAndContinue`(편철 실행)도 `S.running`+실행 중 UI(단추 비활성, 진행 표시)로 감싸 "사건 삭제"를 막음. 기존 메시지와 흐름은 유지.
- 5 (화면 표시): 게이트 통과 줄은 초록 "✓ 통과", 실패는 빨강·굵게 유지, 건너뜀은 회색, `skipped` G1b 줄은 숨김(패키지 검사 칸도 비면 숨김). 사용자 확인 칩은 대기 중 "확인 기다림"·종료 "완료"(`data-status`는 그대로). 재생 모드에서는 단계·하위단계 시간 숨김(비용만). 미리보기는 위아래 쌓기 + "원본"·"가린 사본" 이름표. 문구: `reminder` "갚아 달라는 말", "말한 사람 모름", "SAM이 찾은 영역", "실제 호출", 발화 줄 앞 "강조" 텍스트 제거(`aria-label` 유지). 새로 열린 칸으로 부드럽게 스크롤(`prefers-reduced-motion`은 즉시 이동).
- 5a (기대값 갱신): 패키지 G1b 단언을 "보이는 게이트만 확인, 없으면 칸 숨김"으로, "화자 미상" 단언을 "말한 사람 모름"으로 고침. G1a 장면은 `GET /drafts`에서 `{{principal}}`이 든 문장(실측 s1, stub·실측 모두), 없으면 첫 `fact` 문장 선택.
- 6 (E2E 보강): `Steps.shot`마다 보이는 글자 전체에 "null"·`{"`·"undefined" 검사 추가. G1a는 `{{principal}}` 자리(없으면 첫 슬롯)만 "500만 원"으로 바꿔 G1a만 걸리게 하고 G3 부재도 단언. `case_cleanup` 픽스처로 세 테스트 모두 실패해도 만든 사건을 API로 삭제.
- 7: 이 리포트.

## 2. 만든·고친 파일

새 파일:

- `reports/M6-fix1.md`: 이 리포트

고친 파일(지시서 범위 안만):

- `frontend/case.js`: 1~5항 전부(금액 정규식+칸 옆 오류, 배열 방어+충돌 스킵, 호출 수 규칙, 편철 실행 중 표시, 게이트·칩·시간·문구·스크롤)
- `frontend/case.css`: 통과 게이트 초록, 미리보기 세로 쌓기, `.field-error` 스타일
- `frontend/index.html`: "원본" 이름표 추가, "가린 사본"·"SAM이 찾은 영역" 문구
- `docs/case.js`, `docs/case.css`, `docs/index.html`: frontend와 바이트 동일하게 미러(해시 확인)
- `e2e/test_case_flow.py`: 호출 수 규칙 갱신+숫자 단언(6·8), 전 샷 금칙어 검사, 기대값 갱신(G1b·화자), G1a 장면 교체, `case_cleanup`, `test_fix1_amount_rejected` 추가

건드리지 않음: `e2e/stub_server.py`(범위 안이지만 변경 불필요 — 금액 미검증이라 신규 테스트는 실측 전용, G1a·G1b·6a 경로는 기존 stub으로 통과), `backend/`(검증 규칙 읽기만), `specs/`, `AGENTS.md`, `docs/analysis/`, 다른 리포트, `.env`(읽기·생성 없음).

## 3. 실행한 명령과 결과

공유 venv·키 없이(`MODEL_API_KEY` 제거 후 실행):

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd backend; & $PY -m pytest -q
# 273 passed in 22.28s (main 병합 뒤, failed 0)
cd ..; Remove-Item Env:E2E_BASE_URL -ErrorAction SilentlyContinue; & $PY -m pytest -q e2e
# 2 passed, 1 skipped in 20.99s (가짜 서버, skipped는 실측 전용 신규 테스트)
# 재생 서버(META_MODE=replay, META_LEDGER_PATH=%TEMP%\m6fix1-replay-ledger.jsonl, 빈 포트 자동 선택→127.0.0.1:52111, PID 30568, /health 확인)를 띄운 뒤:
$env:E2E_BASE_URL = "http://127.0.0.1:52111"; & $PY -m pytest -q e2e
# 3 passed in 17.37s (실제 백엔드)
Stop-Process -Id 30568 -Force  # 포트 종료 확인
& $PY tools\secret_scan.py
# secret_scan: clean
```

그 밖:

- `node --check frontend/case.js`, `node --check docs/case.js`: 통과
- 실제 함수 추출 검증(node, 임시 스크립트): `parseAmountInput` 7/7("5,000,000원"→"5000000", 세 예문 원문 유지 등), `conflictText` 9/9(정상 문장·9종 예외 스킵)
- 실측 사전 probe(샘플 사건 1건 생성·실행·삭제): `CHECKPOINT_1` 호출 5 done+1 organizing=6, 충돌 dict 1건, 화자 null 5건 확인
- `Get-FileHash`: `frontend/`↔`docs/` 3종 모두 동일(True)
- `git status --porcelain`: 위 7개 수정만. `reports/M0-spike.json`·원장 변경 없음(되돌리기 불필요), `backend/data/cases/` 잔여 0건, 뜨기 전·후 프로세스 잔존 없음
- 스크린샷: `e2e/artifacts/` 12장(가짜 서버), `e2e/artifacts/real/` 15장(기존 12 + `fix1-amount-*` 3장, git 제외)

## 4. 실호출 비용

- Meta 실호출 0회(지시서대로 실호출 없음). 모델·비용 없음.
- 작업 트리 원장(`reports/cost_ledger.jsonl`) 생성·변경 없음. 재생 서버 원장은 `%TEMP%\m6fix1-replay-ledger.jsonl`로 분리(재생은 기록 안 함).

## 5. 열린 문제와 지시서·약속 대비 차이

- 실행 중 삭제는 코드 가드(단추 비활성+`S.running` 검사)로 막았고, 타이밍 경합 자체를 재현하는 전용 테스트는 M6와 같은 이유(불안정 우려)로 넣지 않음.
- `repayments.amount` 400은 서버가 어느 행인지 알려주지 않아 보이는 모든 금액 칸에 같은 메시지를 표시함.
- 재생 모드 단계 시간 숨김은 stub의 0.3초 표시에도 적용됨(지시서 "재생 모드에서는 숨김" 그대로).
- G1a 폴백(문장에 `{{principal}}`이 없을 때 첫 슬롯만 교체)은 실측·stub 모두 s1 선택으로 타지 않았고, 코드 경로만 둠.
- 부드러운 스크롤은 `prefers-reduced-motion` 사용자에게는 즉시 이동으로 동작함.
- 가짜 서버 E2E 1 skipped는 실측 전용 신규 테스트의 정상 스킵임(지시서 1항 "E2E(실제 백엔드)로 고정"대로).
- 지시서와 스펙이 다투는 부분은 없음. 계약 5장의 `reminder` 표시명 "갚아 달라는 말"(15:16 변경)과 화면 수정이 일치함을 확인.

## 6. 명세 변경 제안

`specs/`는 직접 고치지 않음. 아래만 반영을 제안함(1·2항은 M6 리포트 제안의 정정):

1. 계약 5장 보드 머리 호출 수 계산 규칙을 고정: `reading`·`vision`은 `substeps` 중 `done` 개수, 나머지 모델 단계는 `attempts` 합, 재생 표시는 `(재생)`. (M6 제안 1항의 "`skipped` 제외"는 보류된 판독을 세는 결함이 있었음)
2. 계약 5장 `PUT /facts` 금액 입력 규칙에 명시: 화면은 쉼표·"원" 표시 형식(`^\s*\d[\d,]*\s*원?\s*$`)만 정수 문자열로 변환하고, 그 밖의 입력은 원문 그대로 보내 서버 400을 칸 옆에 표시. (M6 제안 3항의 "화면이 변환"은 V1 결함의 원인이었음)
3. 계약 5장 화면 규칙에 추가: 게이트 통과 줄은 초록 "✓ 통과", `skipped` G1b 줄은 숨김, 재생 모드에서는 단계 시간 숨김, 사용자 확인 칩은 대기 중 "확인 기다림"·종료 "완료".
