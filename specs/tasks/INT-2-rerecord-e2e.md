# INT-2 통합: 다시 기록하고 실제 백엔드로 E2E (작업 지시서)

- 작성: 2026-11-03 14:01 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\int-2`(브랜치 `int-2`). 이 브랜치에는 `main`(M2b-fix1까지) + M0-fix3 + M1-fix2·M1-fix3 + M2a가 이미 병합되어 있습니다(Claude가 병합).
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `reports/M2a.md`, `reports/M2a-review.md`, `reports/M2b-fix1-review.md` 3절(실제 백엔드와 맞출 점), `reports/M0-fix3.md`, `reports/M1-fix3.md`, `specs/case-api-contract.md`
- 배경: M2a의 재생 기록은 그 뒤 바뀐 샘플 PDF 바이트(M2b-fix1)와 강화된 검사 규칙(M1-fix2·3) 때문에 맞지 않습니다(`replay_fixture_missing`). 한 번 다시 기록하고, M2b의 E2E를 실제 백엔드에 돌려 통과시킵니다.

## 파일 범위

고쳐도 되는 파일: `backend/app/agents/`, `backend/app/api/cases.py`, `backend/tests/test_case_*.py`, `backend/tests/fixtures/meta/`(새 기록 추가, M2a 기록 중 더는 쓰이지 않는 것은 지움), `e2e/test_case_flow.py`(실제 백엔드 대응에 꼭 필요한 부분만), `frontend/case.js`(실제 백엔드 응답과 어긋나는 부분만, 같은 변경을 `docs/case.js`에), `reports/cost_ledger.jsonl`(기록이 추가).
건드리지 않는 파일: `backend/app/meta/`, `backend/app/services/`, `specs/`, `sample_evidence/`, 그 밖 전부. 서비스 함수가 필요한 동작을 안 하면 고치지 말고 리포트에 적습니다.

## 할 일

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
