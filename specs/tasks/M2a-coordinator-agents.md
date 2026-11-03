# M2a 코디네이터·담당·사건 API (백엔드, 작업 지시서)

- 작성: 2026-11-03 12:35 KST, Claude / 2판 12:58 KST(교차 리뷰 반영: 단계 A/B 분리, 고정 입력, 어댑터, 실행 ID, 편철, 오류 형식)
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\m2a-backend`(브랜치 `m2a-backend`, **M0-fix2·M1-fix1·M3·M2b가 병합된 `main`**에서 시작).
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `specs/case-api-contract.md`(v2, 이 작업이 구현할 약속), `specs/case-api-examples/*.json`, `reports/M0-review.md`, `reports/M0-fix1-review.md`, `reports/M0-fix2.md`, `reports/M1.md`·`M1-fix1.md`, `reports/M3.md`·`M3-fix1.md`
- 참조: 에이전트 설계 `specs/ClaimBack-AI_에이전트_설계.md` 1장, 2-1, 3-1, 3-4, 3-6, 3-7, 3-9, 4-1~4-4 / 계획서 4-6 코디네이터 케이스

## 목표

한국 샘플 사건이 판독(Spark) → 사실 정리(Spark) → 체크포인트 1 → 계산(M1) → 문안 작성(Spark) ⇄ 검증(G1a·G3·명칭) → 문장 승인 → 편철(내용증명 PDF, 전자소송 문구) → 체크포인트 2까지 **재생 모드로 끝까지** 돕니다. M2b가 만든 E2E가 이 백엔드에서도 그대로 통과해야 합니다.

## 단계 (순서대로, A는 반드시 끝냄)

- **단계 A(실호출 없음)**: 사건 상태, 코디네이터, 사건 API 전체, 가짜 담당으로 도는 계약 테스트. 이것만으로 `CHECKPOINT_2`까지 갑니다.
- **단계 B(실호출)**: Spark 담당 3개(판독, 사실 정리, 문안 작성)와 기록 실행, 재생 테스트.
- 미룸: 판독 정확도·IoU 채점(M4), G1b(M5).

## 파일 범위

고쳐도 되는 파일: 새 패키지 `backend/app/agents/`, 새 라우터 `backend/app/api/cases.py`, `backend/app/main.py`(라우터를 정적 파일 마운트보다 먼저 등록), `requirements.txt`(`uvicorn`), 새 테스트 `backend/tests/test_case_*.py`, 새 fixture(`backend/tests/fixtures/meta/` 추가 기록), `reports/cost_ledger.jsonl`.
건드리지 않는 파일: `frontend/`, `docs/`, `e2e/`(실행만), `sample_evidence/`, `backend/tests/golden/`(테스트에서 읽기만, 에이전트·API는 절대 읽지 않음), `backend/app/meta/`, `backend/app/services/`(쓰기만).

## 할 일

1. **어댑터** `agents/deps.py`: M1·M1-fix1·M0-fix2가 만든 함수(계산 `calculate_kr`, G1a·G3, 명칭 검사, 슬롯 치환·조사 맞춤, 서류 생성의 `fact_sentences` 인자, Meta 클라이언트, `Box`, 예산 오류)를 여기서만 가져옵니다. 이름이 지시서와 다르면 여기서만 맞추고 리포트에 적습니다. 기능이 없으면 서비스 파일을 고치지 말고 해당 테스트를 `xfail`(이유 포함)로 둡니다.
2. **사건 상태** `agents/case_state.py`: 설계 4-2 구역을 가진 Pydantic 모델, 사건별 JSON 파일(`backend/data/cases/<case_id>/case.json`), 쓸 때마다 버전 증가, **단계가 끝날 때마다 저장**(화면이 진행을 봄).
3. **공통 형식** `agents/base.py`: 설계 4-1 `AgentTask`, `AuditRecord`(단계, `ex_id`, 모델, 프롬프트 버전, 입력 해시, 지연, 토큰, 비용), `AgentResult`.
4. **접수** `agents/intake.py`: SHA-256, 증거 번호(약속 2장 순서, 샘플은 EX1~EX6 고정), 종류, 영상은 `skipped`, PDF는 `iou.png`를 미리보기로.
5. **고정 입력** `agents/demo_inputs.py`: 약속 5장의 `build_demo_confirmed_facts(review)` 규칙 그대로(빈 칸만 `specs/case-api-examples/confirmed_facts_kr.json`의 `fallback_fields`로). 기록 실행, 재생 테스트가 이 함수를 씁니다.
6. **코디네이터** `agents/coordinator.py`: 약속 3장 전이표 그대로. 같은 사건에 동시 `POST /run`은 409. 판독은 증거별 병렬(스레드)이고 결과는 `ex_id` 숫자 순으로 저장, `substeps`에 증거별 상태·지연.
7. **API** `api/cases.py`: 약속 6장의 엔드포인트, 응답 모양(5장), 오류 형식(1장: 400·409·404, `code`). 요청 본문은 직접 검사해 FastAPI 422 대신 400으로. `FixtureNotFound`는 500이 아니라 `code: replay_fixture_missing` HOLD. 예산 오류(`BudgetError` 계열)는 `code: budget_exceeded` HOLD.
8. **비용 표시**: `steps[].cost_usd`와 `run_cost_usd`는 실호출이면 원장 요약(`ledger_summary`), 재생이면 응답 usage로 계산(`estimate_cost_from_body`).
9. **단계 A 계약 테스트**(가짜 담당 주입, 실호출 없음): 샘플 사건 생성 → run → readings/review → facts PUT(고정 입력) → run → drafts → 문장 하나를 "500만 원을 보냈습니다."로 PUT하면 G1a 지적·승인 불가 → 되돌림 → 전부 승인 → run → package → DELETE. 응답마다 `specs/case-api-examples/`의 같은 이름 예시의 키가 모두 있는지 확인. 전이표의 409 경로, HOLD 경로(G2 결손, 스키마 2회 실패, 수정 루프 초과, 예산 오류, fixture 없음) 확인.
10. **Spark 담당**(단계 B):
    - `agents/reader.py` + `prompts/reader.v1.md`: 설계 3-1 `Reading` 구조화 출력. 이미지·PDF는 **인라인**(`image_url` data URL, PDF `file_data`)으로 보냅니다(Files API를 쓰지 않음). 박스는 `norm1000`으로 받아 미리보기 픽셀 `Box`로 변환. `item_id`는 코드가 출력 순서로 다시 붙임. 모델 `READER_MODEL` 설정(기본 `muse-spark-1.3`), reasoning `low`, `max_output_tokens` 4,000. `IncompleteResponse`면 8,000으로 1회 재시도, 스키마 오류면 오류 요약(필드 이름만, 예외 문자열 전체는 넣지 않음)을 붙여 1회 재요청, 다시 실패하면 그 증거만 `hold`.
    - `agents/fact_organizer.py` + `prompts/fact_organizer.v1.md`: 판독 결과만 입력, 약속 5장 `Review` 생성(필드 이름표는 코드 상수, 모델 출력은 값·근거·충돌·질문·태그만). reasoning `medium`.
    - `agents/drafter.py` + `prompts/drafter.v1.md`: 설계 3-6·4-4 머리말. 입력은 `KR_SLOTS`(이름과 설명만), 사건 순서, 강조 발화(`ex_id:item_id`와 원문), 증거 목록. 출력 `SlotDraft`. 검증 = G1a + G3 + 명칭 검사(`check_draft`), 지적 목록을 넣어 최대 2회 수정(`revisions[]` 기록), 넘으면 HOLD.
    - 프롬프트 파일에 샘플 이름·금액·날짜를 넣지 않습니다(테스트로 확인). **모델 요청 안에 `case_id`, URL, 시각, 파일 경로를 넣지 않습니다**(재생 해시 고정).
    - 모든 호출의 `run_id` = `case_id`(사건 전체에 실행당 상한). 실행 중 원장은 환경 변수 `META_LEDGER_PATH`가 가리키는 한 곳(기록 실행 때 `C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl`로 지정).
11. **편철** `agents/packager.py`: 승인된 문장을 슬롯 치환·조사 맞춤한 뒤 `fact_sentences`로 내용증명 PDF와 전자소송 문구에 넣습니다. 계산값은 `calculate_kr`(확정값, `as_of`). `GeneratedClaimDraft`가 필요하면 `claim_amount_claimed = remaining_principal`. 패키지 문구 전체에 명칭 검사.
12. **기록 실행**(단계 B 마지막에 한 번): `META_MODE=record`, `META_LEDGER_PATH` 지정, 샘플 사건을 고정 입력으로 `CHECKPOINT_2`까지. 끝나면 **바로 재생으로 같은 흐름을 다시 돌려** fixture 누락이 없는지 확인. 누락이 있으면 그 단계만 다시 기록. 서로 다른 `case_id` 두 개로 재생해 `Review`·`Drafts`가 같음을 테스트로 확인.
13. **E2E 확인**: 재생 모드로 서버를 띄우고(`127.0.0.1`, 빈 포트) M2b의 `e2e/test_case_flow.py`를 `E2E_BASE_URL`로 이 서버에 돌려 통과시킵니다(실패하면 원인과 약속과의 차이를 리포트에).
14. 리포트 `reports/M2a.md`(AGENTS.md 형식, 끝까지 저장 확인): 단계 A·B 결과, 실호출 횟수·비용(원장 요약), 단계별 지연, 재생 E2E 결과, 약속과 다르게 만든 부분, 어댑터에서 맞춘 이름.

## 하지 않을 일

- 화면(M2b), 시각 감식·가림·영상·타임라인(M4 이후), 미국 트랙, 판독 모델 최종 결정(M4), G1b(M5)
- `specs/` 수정, `.env` 읽기·만들기, 키 출력, 커밋과 푸시

## 완료 기준

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m2a-backend"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q                         # failed 0 (키 없이 재생)
cd $WT; & $PY tools\secret_scan.py                            # 0
# 재생 서버 + E2E (M2b 테스트를 실제 백엔드에)
$env:META_MODE = "replay"; $env:E2E_BASE_URL = "http://127.0.0.1:<리포트에 적은 포트>"
& $PY -m pytest -q e2e                                        # failed 0, STUB DATA 띠 없음
```
