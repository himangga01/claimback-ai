# INT-2 통합: 다시 기록하고 실제 백엔드로 E2E (작업 지시서)

- 작성: 2026-11-03 14:01 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\int-2`(브랜치 `int-2`). 이 브랜치에는 `main`(M2b-fix1까지) + M0-fix3 + M1-fix2·M1-fix3 + M2a가 이미 병합되어 있습니다(Claude가 병합).
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `reports/M2a.md`, `reports/M2a-review.md`, `reports/M2b-fix1-review.md` 3절(실제 백엔드와 맞출 점), `reports/M0-fix3.md`, `reports/M1-fix3.md`, `specs/case-api-contract.md`
- 배경: M2a의 재생 기록은 그 뒤 바뀐 샘플 PDF 바이트(M2b-fix1)와 강화된 검사 규칙(M1-fix2·3) 때문에 맞지 않습니다(`replay_fixture_missing`). 한 번 다시 기록하고, M2b의 E2E를 실제 백엔드에 돌려 통과시킵니다.

## 파일 범위

고쳐도 되는 파일: `backend/app/agents/`(프롬프트 포함), `backend/app/api/cases.py`, `backend/tests/test_case_*.py`, `backend/tests/fixtures/meta/`(새 기록 추가, M2a 기록 중 더는 쓰이지 않는 것은 지움), `e2e/test_case_flow.py`(실제 백엔드 대응에 꼭 필요한 부분만), `frontend/case.js`(실제 백엔드 응답과 어긋나는 부분만, 같은 변경을 `docs/case.js`에), `reports/cost_ledger.jsonl`(기록이 추가).
건드리지 않는 파일: `backend/app/meta/`, `backend/app/services/`, `specs/`, `sample_evidence/`, 그 밖 전부. 서비스 함수가 필요한 동작을 안 하면 고치지 말고 리포트에 적습니다.

## 할 일

0. **M2a 프롬프트·규칙 리뷰 반영(먼저, 기록 전에)** — `reports/M2a-review.md` P1~P9:
   - **P1(차단) 거짓 사실 방지**: 문안 작성 담당이 계산값 슬롯(`remaining_principal`, `accrual_start_date`, `total_claim_amount`, `calculated_interest`, `delay_rate`)을 쓰지 못하게 허용 슬롯에서 빼고(편철 담당이 정형 문구로 넣음), 누군가 한 말은 반드시 인용 슬롯(`{{quote:EXn:itemN}}`)으로만 쓰게 합니다. `user` 문장은 발화를 묘사하지 못하게 합니다. 규칙 검사 추가: 말하기 동사(말하/언급/주겠다/갚겠다/약속/요청)가 있는 `fact` 문장은 인용 슬롯이 있어야 하고, 계산값 슬롯은 거부. 이 검사는 `agents/` 안(예: `agents/draft_rules.py`)에 두고 G1a·G3와 함께 돌립니다.
   - **P3** 판독·사실 정리 스키마에서 빈 값은 진짜 `null`(문자열 "null" 금지), `kind`·태그·역할·문장 유형은 열거형, API가 받으면 `strict`. 말풍선에 `side: left|right`.
   - **P4** 판독 프롬프트: 연도가 보이지 않으면 `normalized`는 `null`(연도 추정 금지).
   - **P5** 사실 정리 결과의 원금·날짜·변제를 인용한 판독 항목의 `normalized`와 코드로 대조, 다르면 충돌 표시.
   - **P6** `null_reason` 필드, 질문은 비었거나 충돌한 칸에만.
   - **P7** 토큰 한도: 사실 정리 8,000(또는 reasoning low, 발화 원문 되풀이 금지), 문안 작성 6,000, 판독 `normalized`는 금액·날짜·전화·계좌만.
   - **P8** 코디네이터의 G2·G4를 고정 "pass" 대신 실제 계산·검증 결과로.
   - 기록 뒤 문안 작성 ⇄ 검증이 실제로 한 번 이상 돌았는지(수정 라운드) 리포트에 적습니다(P9). 일부러 실패를 만들지는 않습니다.
0b. **M2a 코드 리뷰 반영(14:12 추가)** — `reports/M2a-review.md` C1~C12:
   - **C1(차단, 보안)** `DELETE /api/cases/%2E`가 사건 폴더 전체를 지움. `case_dir`·`load_case`·`delete_case`에서 사건 ID를 `^case_[0-9a-f]{12}$`로만 받고, 계산한 경로가 사건 루트 안인지 확인. 이 공격을 막는 테스트.
   - **C2(차단)** 처리 함수가 `async def`인데 막히는 코드를 불러 실행 중 서버 전체가 멈춤(진행 표시 폴링 불가). 일반 `def` 처리 함수로 바꾸거나 스레드풀에서 실행. 실행 중 `GET /api/cases/{id}`가 바로 응답하는 테스트(느린 가짜 판독).
   - **C3(차단)** `deps.py`의 `check_g1a` 호출을 키워드 인자로, `prompts/fact_organizer.v1.md`의 금지어("시효") 제거.
   - **C4** 처리하지 않은 예외로 사건이 멈춤 → 증거 단위로 잡아 그 증거만 보류, `run_case` 전체를 감싸 `internal_error` HOLD, 잠금이 없으면 중간 상태에서 다시 실행 가능.
   - **C5** Windows에서 `case.json` 바꿔 쓰기가 읽는 중 `PermissionError`(300번 중 264번) → 짧게 쉬며 재시도(쓰기·읽기 모두), 읽기 오류를 404로 바꾸지 않음.
   - **C6** 사건 단위 잠금으로 `PUT /facts`·`PUT /drafts`·업로드·`DELETE`와 `POST /run`을 직렬화, 실행 중 `DELETE`는 409.
   - **C7** `PUT /drafts` 수정 문장에도 명칭 검사, `approved` 없이 고치면 승인 해제, 지적이 있으면 `rendered_text` 갱신.
   - **C8** 끝난 단계의 상태(`checkpoint_1`·`draft_approval`은 `done`), `DRAFTING`·`VERIFYING` 상태를 실제로 거침.
   - **C9** 비용: 실호출 비용은 호출별 응답 usage로(원장 차이 대신), HOLD·되돌리기에서 단계 비용 유지.
   - **C10** 명칭 검사를 통과한 뒤에만 PDF를 씀.
   - **C11** 업로드 크기·개수 제한(파일당 20MB, 10개), 확장자와 내용(매직 바이트) 확인.
   - **C12** 사소: `missing_facts`의 `missing_requirements` 채움, 500·없는 경로도 약속 오류 모양, `interest_rate` NaN 거부, 전각 숫자 거부, 같은 보류 이유 중복 제거.
1. **호환 정리**: M0-fix3(실호출 시 `META_LEDGER_PATH` 절대 경로 필수, 새 임시 원장은 `META_LEDGER_INIT=1`), M1-fix2·3(`check_g1a`의 `existing_exhibits` 키워드 인자, 강해진 G1a·G3·명칭 규칙, 조사 맞춤, 날짜 슬롯 점 형식)과 맞지 않는 곳을 `agents/deps.py` 중심으로 고칩니다. 테스트가 임시 원장을 쓰면 `META_LEDGER_INIT=1`.
2. **M2a 리뷰 반영**: `reports/M2a-review.md`의 차단·수정 항목 중 이 파일 범위에 있는 것.
3. **다시 기록**: `META_MODE=record`, `META_LEDGER_PATH=C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl`(있는 파일이므로 INIT 불필요), `READER_CONCURRENCY=1`, `run_id` = 사건 ID. 샘플 사건을 고정 입력 규칙으로 `CHECKPOINT_2`까지. 끝나면 바로 재생으로 다시 돌려 누락 0 확인, 두 사건 ID 동일성 테스트 통과. 판독 결과가 정답과 크게 다르면(금액·날짜가 틀림) 리포트에 적습니다(프롬프트 개선은 M4b).
4. **실제 백엔드 E2E**: `META_MODE=replay`로 서버를 `127.0.0.1` 빈 포트에 띄우고 `E2E_BASE_URL`로 `e2e/test_case_flow.py`를 돌려 통과시킵니다. 어긋나면 원인(백엔드 응답 vs 화면 vs 테스트)을 찾아 약속 문서에 맞는 쪽으로 고칩니다. 확인할 것: `PUT /drafts` 응답의 최상위 `gate_results`에 수정 문장 지적 포함, `repayments`는 `[]`(null 아님), EX1에 판독 박스, "STUB DATA" 띠 없음, 계산 4,014,383·기산일 2026. 5. 2., 패키지에 내용증명 링크. 가짜 서버 대상 E2E도 계속 통과.
5. 스크린샷(실제 백엔드 대상)을 `e2e/artifacts/real/`에 저장(git 제외 폴더 아래).
6. 리포트 `reports/INT-2.md`(AGENTS.md 형식, 끝까지 저장 확인): 실호출 수·비용, 재생 E2E 결과, 고친 호환 문제 목록.

## 완료 기준

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\int-2"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q                         # failed 0 (키 없이)
cd $WT; & $PY -m pytest -q e2e                                # 가짜 서버 대상 통과
# 재생 서버를 띄운 뒤: $env:E2E_BASE_URL = "http://127.0.0.1:<포트>"; & $PY -m pytest -q e2e   # 실제 백엔드 대상 통과
& $PY tools\m0_spike.py --mode replay --probes all             # 9/9, 종료 코드 0
git checkout -- reports/M0-spike.json
& $PY tools\secret_scan.py                                     # 0
```
