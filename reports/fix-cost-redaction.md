# fix-cost-redaction 리뷰 (비용 표시, 잘못된 줄 가림, 중복 인용)

- 작성: 2026-11-04 01:05 KST, Claude Code (서브에이전트, 워크트리 브랜치 `worktree-agent-af65ccd351ef46820`)
- 기준: main b559a62. 근거: 원장 `reports/cost_ledger.jsonl`(main 작업 트리, 1,453행, 읽기만 함), 2026-11-04 영어 사건 실호출 4회의 저장 결과(세션 scratchpad `demo-evidence/run1~run4`).
- Meta 호출 0. 재생 픽스처와 가짜 전송만 썼고 원장은 바꾸지 않음.

## 1. 화면 비용이 원장보다 약 3배 낮아 보임

### 무엇이 틀렸나

영어 사건 4회(case_1763d5ba3670, case_65e78295f641, case_f02928f08441, case_acdf706aede3)는 화면에 약 $0.20이 나왔다. 원장 행을 그대로 더하면 사건마다 $0.654~0.694, 70행(sam-3.1 42행)이다.

### 원인

- 원장은 호출 하나에 두 줄을 쓴다. 호출 전 예약 줄(`status: reserved`, `cost_usd` = 예상 최대값. Spark는 `max_output_tokens` 기준이라 실제보다 2~3배 큼)과 호출 뒤 완료 줄(`completed`, 실제 usage 비용)이다. `ledger_summary`와 예산 검사는 완료 줄이 있는 예약 줄을 상계한다. 행을 그냥 더하면 예약이 겹쳐 약 3배가 된다.
- 상계한 원장 합계는 0.228731 / 0.213321 / 0.199886 / 0.199959, 완료 줄은 35 / 35 / 35 / 34이다. 화면은 $0.2288 / $0.2133 / $0.2000 / $0.1999, 보드 호출 수는 35 / 35 / 35 / 34였다. 이 4회에서는 화면 비용과 원장이 사실상 같았다. 3배 차이는 원장 계산법에서 생겼다.
- 그래도 코드에는 실제로 어긋나는 경로가 있었다.
  1. 반올림: 단계 비용을 소수 4자리 문자열로 반올림한 다음 더했다. 실호출 3회차 화면은 $0.2000인데 원장은 0.199886(→0.1999)이었다. 재생 샘플 문안 뒤 화면은 $0.1694인데 원장은 0.169326(→0.1693)이었다.
  2. 재실행 덮어쓰기: `_reset_from` 주석은 "비용 유지"라고 하지만, 단계가 다시 돌면 `_mark_done`이 이번 실행 비용으로 덮어썼다. 해당 경로는 HOLD 뒤 PUT /facts로 다시 쓴 문안, 그리고 intake 재개 때의 판독·감식·사실 정리다. 호출 수(attempts)도 0으로 돌아갔다.
  3. 보류 경로의 호출 수: 판독에 실패한 증거는 substep `calls`가 0이었고(polish 리뷰가 남긴 한계), 사실 정리와 문안 HOLD는 attempts를 남기지 않았다.
  4. revision_exceeded HOLD에서는 문안 비용이 drafting과 verifying 두 단계에 모두 들어가 두 번 계산됐다.

### 수정

- `StepState`에 내부 필드를 더했다. `spent_usd`는 모든 실행의 정확한 비용이고, `kept_usd`·`kept_calls`는 이전 실행분으로 `_mark_running` 때 보관한다. `_mark_done`과 `_mark_hold`는 보관분에 이번 실행분을 더한다. `run_cost_usd`는 정확한 비용의 합을 한 번만 반올림한다. 세 필드는 API 보기에서 빼서 계약은 그대로다(`STEP_INTERNAL_FIELDS`). 필드가 없는 예전 사건은 `cost_usd`를 그대로 쓴다.
- `_reset_from`은 모델 단계의 attempts도 유지한다. 판독·감식은 이전 실행의 증거별 calls를 새 substep에 더한다.
- 판독 보류 substep, 사실 정리·문안 HOLD, 예외 HOLD가 호출 수를 남긴다. verifying HOLD에는 문안 비용을 넘기지 않는다.
- 화면 코드는 바꾸지 않았다(`countModelCalls` 그대로). 그래서 `docs/case.js` 미러도 필요 없다.

### 재생 확인

재생 샘플을, 기록 픽스처를 돌려주는 가짜 전송과 live 모드 `MetaClient`로 돌려 실제 원장 줄(예약+완료)을 임시 파일에 쓰게 했다.

| 시점 | 원장(상계) | 완료 줄 | 화면 비용 | 보드 호출 |
|---|---|---|---|---|
| 체크포인트 1 | 0.151564 | 33 | $0.1516 | 33 |
| 문안 뒤 | 0.169326 | 34 | $0.1693 (수정 전 $0.1694) | 34 |

E2E의 33회·34회 단언은 맞는 값이라 그대로 두었다.

## 2. 잘못된 줄의 가림이 누출 검사를 통과

### 무엇이 틀렸나

run1 EX4(영어 이체 확인증, 1080×1060, 오른쪽 정렬, 줄 간격 약 64px)에서 판독 상자가 실제 줄보다 위에 있었다. 계좌 item15는 (840,658,1025,688)인데 실제 줄은 약 727~757이고, item19는 (842,760,1025,791)인데 실제 줄은 약 855~887이다. 줄 맞춤(`refine_pii_box`)은 item15를 "SAMPLE Bank" 줄에 둔 채 약 4px만 옮겼고, item19는 약 32px 옮겨 "Jordan Lee (SAMPLE)" 줄에 맞췄다. 결과적으로 "SAMPLE Bank"와 이름 일부가 가려지고 계좌번호 두 개는 전부 보였다. 누출 검사는 가림 상자 둘레 2px 띠(계좌는 위·아래·왼쪽)와 상자 안이 검정인지만 봐서 통과했다. needs_review가 없어 G1b도 통과했고 `exhibits.pdf`에 그대로 들어갔다.

### 원인

1. 줄 맞춤은 위치·너비 점수만 보고, 그 줄의 글자가 판독한 번호인지는 확인하지 않는다.
2. 누출 검사는 가림 상자 주변의 얇은 띠만 본다. 근처 다른 줄에 번호가 그대로 있어도 알 수 없다.

### 수정 (`services/redaction.py`, `agents/privacy_guard.py`)

- 반 줄 규칙(`line_shift_too_far`): 줄 맞춤이 판독 상자 중심에서 줄 높이(판독 상자와 맞춘 줄 중 큰 쪽)의 절반 이상 옮기면 needs_review로 둔다. 사유는 "가림 상자가 판독 위치에서 반 줄 이상 옮겨져 확인 필요"다.
- 줄 확인(`glyph_signature`, `text_signature`, `signature_matches`, `pii_line_matches`): 가릴 칸의 잉크 열 묶음 하나를 글자 하나로 본다. 가장 흔한 큰 높이와 기준선에 맞으면 D, 그 높이의 0.6배 이하이면 S(구분자), 나머지(소문자, 괄호, 내림 글자)는 X다. 양 끝의 X는 칸 테두리로 보고 버린다. 판독 텍스트(숫자는 D, 그 밖은 S)와의 편집 거리가 max(1, 길이/8) 이하일 때만 판독한 줄로 인정한다. 숫자가 4개 미만이면 인정하지 않는다. 인정하지 못하면 needs_review로 두고 사유는 "가린 줄이 판독한 번호와 맞는지 확인할 수 없어 확인 필요"다.
- 누출 검사 강화(`check_leak(..., pii_items=...)`, `find_pii_lines`): 판독 상자 위아래 150px(줄 맞춤과 같은 창) 안에서 판독 번호와 모양이 같은 줄을 찾는다. 그 줄이 어떤 가림과도 겹치지 않으면 경고를 남기고, 해당 항목과 미리보기를 needs_review로 둔다. 이 경우 이미 있는 차단 경로를 탄다. 사용자가 `redaction_confirmed`로 확인하기 전에는 그 사본이 묶음에서 빠진다. fail(HOLD)로 하지 않은 이유가 있다. privacy_leak HOLD는 다시 실행해도 결과가 같아서, 사용자가 확인하고 넘어갈 길이 없다.
- `_ink_bands`·`_merged_cells`: `refine_pii_box`의 줄·칸 찾기 코드를 그대로 떼어 내 둘이 함께 쓴다. 동작은 같다.

### 한국어 샘플

재생 가림 7개(계좌 4, 전화 2, 주민번호 1)가 모두 그대로 인정된다. 이동은 최대 16.5px(주민번호, 상자 높이 77)이고 모양도 맞는다. 계좌의 경우 양 끝 칸 테두리를 버리면 DDDSDDDDSDDDD다. needs_review 0, 미리보기 5개 모두 검토 없음, 누출 경고 0이다. 기존 `test_m4a` 단언(골든 목표 덮음, needs_review False)도 그대로 통과한다.

## 3. 중복 인용

### 무엇이 틀렸나

run2·run3 `package.json` 전자소송 문구에 "...라고 했습니다(갑 제1호증)(갑 제1호증)."가 나왔다. 문안 s3는 `{{debtor_name}}은 [[EX:1]] {{quote:EX1:item13}}라고 했습니다[[EX:1]]`로, 같은 호증을 문장 가운데와 끝에서 두 번 인용했다.

### 원인

`format_ecourt_fact`는 문장 속 `[갑 제N호증]`을 모두 문장 끝으로 모으면서 중복을 없애지 않았다. `render_sentence`도 바로 이어진 같은 인용(`[[EX:1]][[EX:1]]`)을 그대로 두었다. 게이트(G1a·G3·DRAFT·G1b)는 인용 중복을 검사하지 않는다.

### 수정

- `pdf_compiler.collapse_repeated_cites`: 바로 이어진 같은 인용을 하나로 줄인다. 사이에 공백만 있는 경우이고 `[..]`와 `(..)` 둘 다 처리한다. `render_sentence`에서 이 함수를 쓴다.
- `format_ecourt_fact`: 문장 끝 인용 목록에서 순서는 유지하고 중복은 없앤다. 끝으로 모은 인용은 서로 붙어 있으므로 같은 호증이 두 번 나오면 바로 반복이 된다.
- 내용증명은 원래 인용을 지우므로 영향이 없다. 변환은 렌더 때만 하므로 모델 요청과 재생 픽스처(요청 해시)는 바뀌지 않는다.

## 바꾼 파일

`backend/app/agents/case_state.py`, `backend/app/agents/coordinator.py`, `backend/app/api/cases.py`, `backend/app/agents/privacy_guard.py`, `backend/app/services/redaction.py`, `backend/app/services/pdf_compiler.py`, `backend/app/agents/deps.py`, 새 테스트 `backend/tests/test_fix_cost_redaction.py`, 이 보고서, `AGENTS.md`(이 보고서 경로 한 줄).

## 테스트

- 새 `tests/test_fix_cost_redaction.py` 15개
  - 비용: 기록 샘플을 원장 쓰는 클라이언트로 돌려 화면 비용 = `fmt_cost(ledger_summary)`, 보드 호출 = 완료 줄(33, 34), 예약 줄 = 완료 줄. HOLD 뒤 재문안 비용·호출 누적, verifying 이중 계산 없음. 판독 실패 증거의 호출 2회와 비용 반영. substep 호출 합치기.
  - 가림: 64px 간격 오른쪽 정렬 합성 영수증(NanumGothic 30px)으로 확인. 판독 상자를 한 줄 위·한 줄 아래·반 줄 위·20px 위에 두면 모두 needs_review이고, 한 줄 어긋난 경우 누출 검사가 보이는 계좌번호 두 개를 찾는다. 정렬된 상자는 needs_review가 없다. 글자 모양 규칙(번호 줄과 "SAMPLE Bank", 이름, 날짜, 시각 구분), 반 줄 규칙, `check_leak`의 보이는 번호 찾기도 확인한다.
  - 인용: `render_sentence` 붙은 중복, 두 형식 줄이기, 실제 문장 그대로의 전자소송 문구.
- 기준 코드(b559a62)에 새 테스트만 넣어 돌리면 14개 실패, 1개 통과다. 실패 이유는 '0.1694' vs '0.1693', 보류 호출 0, 한 줄 어긋난 가림의 needs_review False, "(갑 제1호증)(갑 제1호증)"이다.
- 전체 결과(2026-11-04 01시 KST, 키 없이):
  - `cd backend; ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` → 497 passed (기존 482 + 새 15)
  - `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider e2e` → 7 passed, 1 skipped

## 한계와 남은 것

- 예약 뒤 실패한 호출(네트워크·5xx 재시도 소진)은 원장이 failed 줄에 예상 비용을 적지만 화면에는 0으로 나온다. 현재 원장 1,453행에는 failed 줄이 0개다. 맞추려면 클라이언트가 예외에 원장 비용을 실어야 한다(`client.py` 변경).
- 줄 확인은 글자 모양 규칙이라 다음 경우는 인정하지 못하고 needs_review로 둔다(안전한 쪽).
  - 숫자가 붙어 한 덩어리로 보이는 글꼴
  - 숫자 높이가 다른 옛 숫자체
  - 같은 칸 안에서 번호 앞에 글자가 붙은 판독(예: "Account: 000-...")
  - 숫자가 4개 미만인 판독
- 판독 상자가 150px보다 멀리 벗어나면 줄 맞춤과 누출 검사 모두 진짜 줄을 찾지 못한다. 이때 가림은 판독 위치에 하고, 모양 불일치로 needs_review가 된다.
- 같은 모양의 다른 번호(예: 다른 계좌)가 판독 상자 줄에 있으면 모양 확인은 통과한다. 이때 진짜 줄이 가려지지 않았다면 누출 검사의 보이는 번호 찾기가 잡는다.
- 반 줄 규칙은 줄 맞춤이 맞는 줄로 옮긴 경우(예: 20px 위 판독에서 정확한 줄로 이동)도 needs_review로 둔다. 지시를 따른 것이고, 사용자가 한 번 확인하면 된다.
- 실호출로 다시 확인하지는 않았다. run1의 원본 영수증은 생성기(`submission/demo-evidence/make_demo_evidence.py`, main 작업 트리)가 이미 배치를 바꿔 같은 픽셀로 재현할 수 없어서, 같은 배치의 합성 영수증으로 테스트했다.
- 화면의 개인정보 단계 메모는 경고가 있어도 "누출 검사 통과"로 남는다(미리보기는 "확인 필요"). 문구 변경은 하지 않았다.
