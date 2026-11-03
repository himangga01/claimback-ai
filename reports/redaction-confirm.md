# redaction-confirm (확인 필요 가림 사본의 증거별 확인, 누출 검사 문구)

- 작성: 2026-11-04 02:20 KST, Claude Code (서브에이전트, 워크트리 브랜치 `worktree-agent-aa07646c711d38a67`)
- 기준: main aa8af2d(작업 트리 깨끗한 상태에서 시작). 근거: `reports/fix-cost-redaction.md`, 2026-11-04 녹화 실호출 3회 중 2회에서 생긴 확인 필요 표시(지시 내용).
- Meta 호출 0. 재생 픽스처만 썼고, 실제 백엔드 E2E는 임시 원장(세션 scratchpad)으로 돌렸다.

## 업데이트 기록

- 2026-11-04 02:20 KST, e443a83: 첫 구현(아래 1~5절).
- 2026-11-04 02:40 KST, 후속 커밋: e443a83 독립 리뷰 2건(코드 리뷰는 병합 + 작은 수정 1건, 화면 리뷰는 먼저 수정)을 반영했다. 자세한 내용은 6절. 1~5절은 첫 구현 기록으로 남기되, 문구와 잠금 규칙은 6절이 우선한다.

## 1. 문제

1. **확인할 길이 없음.** fix-cost-redaction 이후 가림이 한 줄 어긋나거나 줄 모양이 판독과 다르면 그 가린 사본은 `needs_review`가 되고, 사용자가 `redaction_confirmed`로 확인하기 전에는 `exhibits.pdf`에서 빠진다. 그런데 화면은 이 키를 보내지 않았고 미리보기에 표시도 없었다. 그래서 확인 필요 증거는 사용자 모르게 묶음에서 빠졌다(그 쪽에는 안내 한 줄, G1b `notes`만 남음).
2. **계약이 증거별 확인을 못 함.** `redaction_confirmed`는 `true|false` 하나라, 두 증거 중 하나만 확인하는 경우를 나타낼 수 없었다. `true`를 보내면 확인하지 않은 증거까지 들어간다.
3. **누출 검사 문구가 정직하지 않음.** `check_leak`은 가려지지 않은 번호 줄을 찾아도 경고로만 두고 `status: "pass"`를 돌려줬다. `privacy` 단계 문구도 항상 "가림 N개, 누출 검사 통과"였다.

## 2. 설계

- **확인 경로는 기존 `PUT /facts`의 `redaction_confirmed`.** 계약이 이 키를 `PUT /facts`에만 두고 있고, 사실 확인 장의 다른 입력(값, 강조할 말, 증거 역할)도 모두 "확인하고 계속"에서 한꺼번에 보내므로 따로 엔드포인트를 만들지 않았다. 증거별 확인을 위해 값에 **증거 번호 목록**(`["EX4"]`)을 더했다(계약 6d). `true|false`의 뜻은 그대로이고, `true`는 데모 고정 입력(`build_demo_confirmed_facts`)용으로 남는다. 화면은 `true`를 보내지 않는다.
- **명시적 확인만.** 화면은 증거마다 "가림 확인"을 누른 경우에만 그 번호를 목록에 넣는다. 한꺼번에 확인하는 단추나 자동 확인은 없다. 확인한 증거가 없으면 키를 아예 보내지 않으므로, 확인 필요가 없는 한국어 재생 샘플의 요청 본문은 그대로다.
- **누출 검사 상태 `review`.** 하드 실패 없이 경고만 있으면 `pass` 대신 `review`. HOLD는 지금처럼 `fail`만이다. 사본이 없는 증거(`not_redacted`)나 계획 단계 표시(한 줄 이동 등)는 누출 검사 결과가 아니므로 상태를 바꾸지 않지만, 단계 문구에는 센다.

## 3. 바꾼 것

### 백엔드

- `backend/app/agents/coordinator.py`: `_validate_redaction_confirmed`. `true|false|null` 또는 아는 증거 번호 문자열 목록. 모르는 번호, 문자열이 아닌 항목, 그 밖의 형식은 400 `bad_request`. 중복은 하나로, 증거 번호 순으로 저장하고 빈 목록은 `false`. `privacy` 단계 `note`는 `privacy_guard.privacy_note`로 만든다.
- `backend/app/agents/packager.py`: `is_redaction_confirmed(state, ex_id=None)`. `true`면 전부, 목록이면 그 증거만. `get_redaction_status`가 증거별로 판정한다. `not_redacted`는 넣을 사본이 없으니 확인해도 빠진다(기존 동작).
- `backend/app/services/redaction.py`: `check_leak`이 경고만 있으면 `review`.
- `backend/app/agents/privacy_guard.py`: `run_privacy`가 `fail` > `review` > `pass`로 모은다. `privacy_note`는 확인 필요 사본도 사본 없는 증거도 없을 때만 "가림 N개, 누출 검사 통과"이고, 아니면 "가림 N개, 확인 필요 증거 M개[, 가린 사본 없는 증거 K개]"다.

### 화면 (`frontend/` → `docs/` 바이트 동일 복사)

- `index.html`: "가린 사본" 범례 바로 아래 `#redaction-notice`(`data-testid="redaction-notice"`), 이미지 칸에 `#redaction-viewer`.
- `case.js`:
  - 선택한 증거의 미리보기가 `needs_review`면 알림을 보여 준다. 제목은 "가림 확인 필요"이고, 백엔드 `reason`을 항목별 한 줄로 쓴다(예: "계좌번호: 가림 상자가 판독 위치에서 한 줄 이상 옮겨져 확인 필요"). 이어서 "확인하기 전까지 이 증거의 이미지는 갑호증 묶음(exhibits.pdf)에 들어가지 않습니다" 안내와 "가림 확인"·"묶음에서 빼기" 단추가 온다. 고르면 알림이 "가림 확인함" 또는 "묶음에서 뺌"으로 바뀐다(`data-state`, `aria-pressed`).
  - 사본이 없는 증거(`not_redacted`)는 단추 없이 "가린 사본 없음"과 사유만 보여 주고 이미지 칸을 숨긴다.
  - 증거 목록 단추 끝에 "가림 확인 필요 / 가림 확인함 / 묶음에서 뺌 / 가린 사본 없음"을 붙이고 `data-redaction`, 왼쪽 빨간 띠를 단다.
  - "확인하고 계속"은 확인한 증거만 `redaction_confirmed: ["EX4", …]`로 보낸다. 보내는 중과 보낸 뒤(상태가 `CHECKPOINT_1`·`HOLD`가 아니면)에는 단추가 잠기고 문구가 바뀐다.
  - 영어: `L()`로 모든 알림 문구, 고정 사유 문구 사전(`REDACTION_REASON_EN`), `tx()`에 "확인 필요 증거 N개" → "N exhibits to check", "가린 사본 없는 증거 N개", "누출 검사 확인 필요" 패턴.
  - 보드: `privacy` 문구에 "확인 필요"나 "사본 없는"이 있으면 빨간 글씨(`is-review`). 단계 문구에 `data-testid="step-note-<key>"`.
- `case.css`: 알림 상자(확인 필요는 빨강, 확인함은 파랑, 뺌은 회색), 단추 줄, 목록 표시.

### 계약과 가짜 서버

- `specs/case-api-contract.md` 6d(v2.3): 목록 형식, `not_redacted`, 화면 동작, `leak_check.status` `review`, 단계 문구. 6c의 해당 줄에 6d 참조를 달고, 7절에 가짜 서버 시나리오를 적었다.
- `e2e/stub_server.py`: 시험 전용 `PUT /__stub/scenario {"redactions": "none"|"flagged"}`. 그 뒤에 만든 사건에 적용되고 기본값은 `none`이라 기존 동작은 그대로다. `flagged`는 EX4(한 줄 이동)와 EX5(줄 모양 불일치 + 보이는 번호 줄)를 확인 필요로 돌려주고, `privacy` 단계를 "가림 7개, 확인 필요 증거 2개"로 끝낸다. `PUT /facts`는 `redaction_confirmed` 형식을 검사한다.

## 4. 테스트

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-ai-meta\.claude\worktrees\agent-aa07646c711d38a67"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q -p no:cacheprovider      # 509 passed
cd $WT; & $PY -m pytest -q -p no:cacheprovider e2e            # 가짜 서버: 8 passed, 1 skipped
# 재생 실제 백엔드(META_MODE=replay, 임시 META_LEDGER_PATH, 127.0.0.1:58731, 끝난 뒤 종료):
$env:E2E_BASE_URL="http://127.0.0.1:58731"; & $PY -m pytest -q -p no:cacheprovider e2e   # 8 passed, 1 skipped
& $PY tools\secret_scan.py                                    # 커밋 전
```

- 새 `backend/tests/test_redaction_confirm.py`(6개, 재생 샘플):
  - 단계 문구 규칙(통과, 확인 필요 2, 확인 필요 1 + 사본 없음 1, `review`인데 표시 없음).
  - 한국어 재생 샘플은 그대로다. 미리보기 `needs_review` 0, `leak_check` `pass`, 문구 "가림 N개, 누출 검사 통과", 데모 입력에 키 없음.
  - 목록 검증: `["EX9"]`, `[4]`, `None` 섞임, 객체는 400이고 상태는 `CHECKPOINT_1` 유지. 중복과 순서는 정리(`["EX5","EX4","EX5"]` → `["EX4","EX5"]`), `[]`는 `false`.
  - **확인 필요 → 제외**: 재생 사본 EX4·EX5를 확인 필요로 표시하고 편철까지 간다. 두 쪽 모두 이미지 0에 `NEEDS_REVIEW_LINE`이 있고, G1b는 `pass`, findings 0, notes에 두 증거가 있다.
  - **확인 → 포함**: `redaction_confirmed: ["EX4"]`. EX4 쪽 이미지 1에 안내 줄이 없고, EX5는 여전히 제외된다. G1b `pass`, findings 0, notes에는 EX5만 있다.
  - `true`는 확인 필요 사본 전부를 넣는다(데모 입력 호환).
- 기존 테스트에서 고친 단언은 3곳이다. 경고만 있으면 `pass`가 아니라 `review`(`test_m4a.py` 1, `test_fix_cost_redaction.py` 2). 한 줄 위 가림 테스트에는 `review`와 단계 문구 단언을 더했다.
- 새 E2E `test_redaction_confirm_flow`(가짜 서버 `flagged`, 실제 백엔드에서는 건너뜀):
  - 보드 문구가 "가림 7개, 확인 필요 증거 2개"이고 "누출 검사 통과"는 없다.
  - 목록에서 EX4·EX5만 "가림 확인 필요"다.
  - EX4 알림에 사유와 묶음 안내가 있다. **"가림 확인" 클릭 → 표시가 "가림 확인함"으로 바뀌고 EX5는 그대로**다.
  - EX5에서 "묶음에서 빼기"를 고른다.
  - 영어 화면에서 알림, 사유, 단추, 보드 문구를 확인한다.
  - 375px 폭에서 가로 스크롤이 없다.
  - `PUT /facts` 본문의 `redaction_confirmed == ["EX4"]`, 나머지는 데모 고정 입력과 같다.
  - 보낸 뒤 단추가 잠긴다.
  - 스크린샷 `e2e/artifacts/0N-redaction-*.png`(git 제외)을 눈으로 확인했다. 알림이 범례 바로 아래에 있고 보드 문구가 빨간 글씨다.
- 재생 실제 백엔드 E2E의 본 흐름(`test_case_flow`)은 체크포인트 1에서 33회, 문안 뒤 34회 단언과 `PUT /facts` 본문 == 데모 고정 입력 단언을 그대로 통과했다. 화면이 키를 더하지 않았고 모델 요청도 바뀌지 않았다(재생 픽스처 누락 HOLD 없음). `redaction_confirmed`는 문안 입력(`_build_inputs_for_drafter`)에 들어가지 않는다.
- 기준 코드(aa8af2d)에서는 `["EX4"]`가 bool이 아니라 400이고 `privacy_note`도 없다. 그래서 새 백엔드 테스트 중 목록·포함·문구 테스트는 기준 코드에서 실패한다. 기준 코드에 직접 돌려 보지는 않았고, 코드를 읽고 판단했다.

## 5. 한계와 남은 일

- 화면의 선택은 "확인하고 계속" 전까지 브라우저 메모리에만 있다. 사건을 다시 여는 경로가 없어 새로고침하면 사건 자체가 화면에서 사라지므로(기존 한계) 서버에 따로 저장하지 않았다. `GET /redactions`에 확인 여부(`confirmed`)는 더하지 않았다.
- 편철 화면은 G1b `notes`(어느 증거를 이미지 없이 넣었는지)를 보여 주지 않는다(기존 동작). 사실 확인 장의 알림이 그 사실을 미리 알려 주지만, 최종 확인 장에서도 보이게 하려면 `gateRow`에 notes를 더해야 한다.
- 체크포인트 1을 지난 뒤(문안 승인, 최종 확인)에는 확인을 바꿀 수 없다. 바꾸려면 `PUT /facts`를 다시 해야 하고, 그러면 계산과 문안이 지워진다(계약 3장). 녹화 흐름에서는 체크포인트 1에서 확인하는 장면을 넣으면 된다.
- 알림의 사유는 백엔드 문구를 그대로 나눈 것이다. 영어 사전에 없는 새 사유 문구는 한국어로 보인다.
- 가짜 서버 `flagged` 시나리오의 "가린 사본"은 원본 미리보기 이미지를 그대로 쓴다(픽셀을 태우지 않음, STUB DATA 띠 표시). 화면 흐름 시험용이다.
- 실호출 녹화 데이터(확인 필요가 실제로 생긴 2회)로 화면을 다시 돌려 보지는 않았다. 백엔드 경로는 재생 사본에 표시를 넣어 확인했다.
- 커밋만 하고 push·병합은 하지 않았다(지시). 서브에이전트 교차 리뷰는 하지 않았다(코디네이터가 e443a83 뒤에 따로 리뷰함, 6절).

## 6. 리뷰 후속 (2026-11-04 02:40 KST)

### 코드

1. **`not_redacted`가 확인으로 들어가던 문제(실제 결함).** `packager.get_redaction_status`는 "확인 필요 또는 사본 없음, 그리고 확인 안 함"일 때만 뺐다. 그래서 `not_redacted`라도 확인(`["EX4"]`이나 `true`)하면 검사를 지나갔다. 보통은 사본 파일이 없어 빠지지만, `privacy_guard`가 예전 `redacted_EX4.png`를 지우다 실패하면(OSError 무시) 그 파일이 묶음에 들어갔다. 이제 미리보기가 `not_redacted`이면 확인과 무관하게 먼저 뺀다. 리뷰어 탐침과 같은 조건(사본 남김 + 확인)을 `test_not_redacted_stays_out_even_with_a_stale_copy[["EX4"]/True]`로 고정했다. e443a83의 packager로 돌리면 두 경우 모두 실패하고, 지금은 통과한다. 따라서 `true`의 같은 구멍은 M5-fix2부터 있던 것이다.
2. 계약 6a 표의 `leak_check.status`를 `pass|review|fail|pending`으로 고쳤다. 6d에는 "목록이든 `true`이든, 남은 파일이 있어도 미리보기 상태로 판정"을 적었다.
3. **잠금.** 단추는 이제 `CHECKPOINT_1`에서만 열린다. 전에는 이후 `HOLD`에서 다시 열렸지만, `PUT /drafts`로 고치는 길에서는 바뀐 선택이 서버에 가지 않으면서 알림만 "확인함"이라고 했다. 사실값을 다시 보내는 `HOLD`에서는 처음 고른 값이 그대로 다시 간다. E2E가 `HOLD` 상태를 흉내 내 잠김을 확인한다.

### 화면

4. **서류 패키지 장에 뺀 이미지 표시(높음).** "묶음에서 빼기"를 고르면 패키지 장에는 "최종 서류 검사(G1b): ✓ 통과"만 보였고, 청구원인은 여전히 [갑 제5호증]을 인용했다. 이제 G1b `notes`를 서류 검사 아래 "갑호증 묶음에서 이미지를 뺀 증거" 상자에 한 줄씩 보여 준다(영어 "exhibits.pdf: Exhibit 5, image left out (redaction not confirmed)."). 같은 상자에 다음 할 일 문장도 붙인다. notes가 없으면 숨기므로 재생 샘플 화면은 그대로다. 가짜 서버 `flagged`도 백엔드처럼 넣지 않은 증거를 G1b `notes`로 돌려준다.
5. "확인하고 계속" 위에 한 줄: "확인 필요 증거 N개(갑 제4호증, 갑 제5호증)가 아직 남아 있어 묶음에서 빠집니다."(영어 단수·복수 구분). 다 고르거나 보낸 뒤에는 숨긴다.
6. 단추 문구는 "묶음에 넣기 / Include it", "묶음에서 빼기 / Leave it out"이다. 안내는 "아래 가린 사본에서 계좌·주민번호·전화번호가 모두 가려졌는지 보고 고르세요."이고, 영어는 리뷰 문구 그대로다. 상태 제목은 "가림 확인 필요 / Check this redaction", "묶음에 넣음 / Included in the bundle", "묶음에서 뺌 / Left out of the bundle"이다. 목록 표시는 "묶음에 넣음 / Included"이다.
7. 이미지가 빠지는 모든 경우에 "서류에는 이 증거가 계속 인용됩니다. 직접 가린 사본을 만들어 제출 전에 더하세요."를 붙인다. 뺌, 사본 없음, 고르지 않고 보냄이 해당한다.
8. 사유는 사유마다 한 줄이다(종류 이름을 줄마다 붙임). ";"로 잇지 않는다.
9. (선택 항목, 반영) `plan[]`의 확인 필요 `mask_box`를 가린 사본 위에 빨간 테두리로 그린다. "가린 사본 크게 보기" 링크로 새 탭에서 원래 크기로 볼 수 있다.
- 영어 보드 문구: 확인 필요나 사본 없음이 있으면 "7 masks · 2 exhibits need your check" 형식이다. 깨끗한 경우는 "N masks, leak check passed"이다(전에는 "redactions").

### 테스트 (후속 커밋 기준)

- 백엔드: 511 passed(새 not_redacted 테스트 2개 포함).
- 가짜 서버 E2E: 8 passed, 1 skipped. `test_redaction_confirm_flow`에 다음을 더했다. 남은 증거 줄(2개 → 1개 → 숨김), 단추·안내 문구, 사유 2줄, 빨간 테두리 2개와 크게 보기 링크, 뺌의 다음 할 일, 영어 "7 masks · 2 exhibits need your check", 보낸 뒤 `HOLD`에서도 잠김, 패키지 장의 EX5 줄(EX4 없음)과 영어 줄.
- 재생 실제 백엔드 E2E: 8 passed, 1 skipped. 33회·34회와 `PUT /facts` 본문 == 데모 고정 입력이 그대로다.
- 스크린샷(`e2e/artifacts/0N-redaction-*.png`, git 제외)으로 알림, 테두리, 남은 증거 줄, 패키지 장 상자를 눈으로 확인했다.

### 남은 한계

- 가짜 서버의 빨간 테두리 위치는 자리표시 상자라 실제 번호 위치와 맞지 않는다. 실제 백엔드에서는 `plan[].mask_box` 원본 픽셀 좌표를 쓴다.
- 체크포인트 1을 지난 뒤에는 선택을 바꿀 수 없다(일부러 잠금). 바꾸려면 사실값을 다시 보내야 하고, 그러면 계산·문안이 지워진다.
- 실호출 녹화 데이터로 화면을 다시 돌려 보지는 않았다.
