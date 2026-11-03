# INT-2 리포트: 다시 기록하고 실제 백엔드로 E2E (Muse Code)

- 작성: 2026-11-03 (KST), Muse Code (`muse-spark-1.3`)
- 작업 트리: `C:\2026_project\claimback-wt\int-2` (브랜치 `int-2`)
- Python: `C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe` (공유 venv, 신규 생성 없음)
- 지시서: `specs/tasks/INT-2-rerecord-e2e.md` (먼저 읽음: `AGENTS.md`, 지시서, `reports/M2a.md`, `reports/M2a-review.md`, `reports/M2b-fix1-review.md` 3절, `reports/M0-fix3.md`, `reports/M1-fix3.md`, `specs/case-api-contract.md`)

## 1. 지시서와 한 일

- 0 (P1~P9, 기록 전): 거짓 사실 방지 규칙 모듈 `agents/draft_rules.py` 신설(계산값 슬롯 5종 거부, 말하기 동사 6종은 인용 슬롯 필수, `user` 문장은 발화 묘사·인용 금지), 문안 입력·허용 슬롯에서 계산값 제외, 판독·사실정리·문안 스키마에 열거형(`kind` 10종·`side`·태그 5종·역할 3종·문장 유형 2종)과 진짜 `null` 처리, 판독 `strict: true`·문안 `strict: true`(사실정리는 값 다형성으로 `strict: false` 유지), 판독 프롬프트에 연도 미표시를 `null`(연도 추정 금지)·`normalized`는 금액·날짜·전화·계좌만·`side` 명시, 사실정리 프롬프트에 `null_reason`·질문은 빈칸·충돌칸만·원문 되풀이 금지, 사실정리 토큰 8,000·reasoning `low`·문안 6,000, 사실정리 값을 인용 판독 `normalized`와 코드 대조(P5)해 다르면 충돌, `null_reason` 기본값과 질문 필터(P6), G2·G4를 고정 `pass`에서 실제 검증·계산 결과로(P8).
- 0b (C1~C12): 사건 ID를 `^case_[0-9a-f]{12}$`로만 받고 경로가 사건 루트 안인지 확인(C1), `POST /run`·`PUT`·`DELETE`를 스레드풀(`asyncio.to_thread`)로 돌려 폴링 가능(C2), `check_g1a` 키워드 인자·프롬프트 금지어 제거(C3), 증거 단위 예외 포획·`run_case` 전체 `internal_error` HOLD·중간 상태 재실행(C4), `case.json` 읽기·쓰기 짧은 재시도·읽기 오류를 404로 바꾸지 않음(C5), 사건 단위 잠금으로 변경·실행·삭제 직렬화·실행 중 삭제 409(C6), `PUT /drafts`에 명칭·DRAFT 검사·승인 해제·`rendered_text` 갱신(C7), 지나간 사용자 단계 `done`·`DRAFTING`·`VERIFYING` 상태 경유(C8), 호출별 응답 usage 비용·HOLD·되돌리기 비용 유지(C9), 명칭 통과 뒤 PDF 쓰기(C10), 업로드 20MB·10개·매직바이트(C11), `missing_requirements` 채움·500·없는 경로 약속 모양·NaN·전각 숫자 거부·보류 중복 제거(C12).
- 1 (호환): `deps.py`의 `check_g1a` 키워드 호출이 M1-fix2와 맞고, M1-fix3 강화 규칙(G1a·G3·명칭)·조사 맞춤·날짜 점 형식을 그대로 사용. M0-fix3 원장 가드(절대 경로·`INIT`)는 기록 실행이 기존 절대 원장을 써서 추가 작업 없음.
- 2: M2a 리뷰 차단·수정 중 파일 범위 안 항목을 모두 반영(위 0·0b). 범위 밖(`meta/`·`services/`·`main.py`)은 손대지 않고 5절에 적음.
- 3 (다시 기록): `META_MODE=record`, `META_LEDGER_PATH=C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl`, `READER_CONCURRENCY=1`, `run_id`=사건 ID로 샘플 사건을 `CHECKPOINT_2`까지 1회 기록. 기록 직후 재생으로 누락 0·두 사건 ID 동일성을 확인. 판독값은 정답과 일치(원금 500만·대여 2026-03-10·변제기 2026-04-10·변제 100만 2026-05-01). 문안⇄검증은 실제로 1회 수정(G3 이어진 문장, DRAFT는 통과).
- 4 (실제 백엔드 E2E): `META_MODE=replay` 서버를 `127.0.0.1` 빈 포트에 띄우고 `E2E_BASE_URL`로 `e2e/test_case_flow.py` 통과. 확인할 것 모두 충족: `PUT /drafts` 최상위 `gate_results`에 수정 지적(G1a `fail` 2건), `repayments`는 `[]`가 아니라 값이 있는 목록(빈칸이면 `[]`, `null` 아님), EX1 판독 박스 17개, `stub: false`(띠 없음), 계산 4,014,383·기산일 2026. 5. 2., 패키지에 `content_proof.pdf` 링크. 가짜 서버 E2E도 통과.
- 5: 실제 백엔드 스크린샷 10장을 `e2e/artifacts/real/`에 저장(`e2e/artifacts/`는 git 제외).

## 2. 만든·고친 파일

새 파일:

- `backend/app/agents/draft_rules.py`: P1 검사(계산값 5종·말하기 동사 6종·`user` 제한, 게이트 `DRAFT`)
- `backend/tests/fixtures/meta/*.json` 8개: 새 기록(판독 5·사실정리 1·문안 2=초안 1+수정 1)
- `reports/INT-2.md`: 이 리포트

고친 파일(지시서 범위 안만):

- `backend/app/agents/reader.py`: `READER_KINDS` 열거형·`side`·`strict: true`·`"null"`→`None`·`normalized`는 4종만
- `backend/app/agents/fact_organizer.py`: 토큰 8,000·`low`·열거형·`null_reason`·P5 대조·P6 질문 필터·`"null"` 처리
- `backend/app/agents/drafter.py`: 토큰 6,000·`type` 열거형·`strict: true`
- `backend/app/agents/prompts/reader.v1.md`: P3·P4·P7(연도 없으면 `null`·4종만·`side`·진짜 `null`)
- `backend/app/agents/prompts/fact_organizer.v1.md`: 금지어 제거(C3)·`null_reason`·질문 제한·되풀이 금지
- `backend/app/agents/prompts/drafter.v1.md`: 계산값 금지·인용만·`user` 제한
- `backend/app/agents/spark.py`: 호출별 usage 비용(C9, 원장 차이 폐기)·끊긴 본문 합산
- `backend/app/agents/coordinator.py`: P1·P8·C4·C6·C7·C8·C9·C12(상세는 1절)
- `backend/app/agents/case_state.py`: C1 검증·봉쇄·C5 재시도·읽기 오류 상파
- `backend/app/agents/deps.py`: `check_g1a` 키워드 인자(C3)
- `backend/app/agents/intake.py`: C11 상수·매직바이트
- `backend/app/agents/packager.py`: 명칭 통과 뒤 PDF(C10)
- `backend/app/api/cases.py`: C2 스레드풀·C6 잠금·C11 제한·C12 모양·500·없는 경로·`missing` 전달
- `backend/tests/test_case_contract.py`: 기존 11개 유지·업로드 MP4 매직 수정·신규 6개(C1·C2·P1·C7·C11·C12)
- `backend/tests/test_case_replay.py`: `"null"` 4건·신규 2개(P5·P6)
- `backend/tests/fixtures/meta/` M2a 기록 8개 삭제(10ddfb44·3d20569b·49df63df·4bc2b1e9·4f3a9d14·6b9ff541·8c342a61·91cb24c1)

건드리지 않음: `backend/app/meta/`·`backend/app/services/`·`specs/`·`sample_evidence/`·`frontend/case.js`·`docs/case.js`·`e2e/test_case_flow.py`(실제 백엔드와 어긋남 없음, 수정 불필요)·`.env`(읽기·생성 없음)·다른 리포트·작업 트리 안 `reports/cost_ledger.jsonl`(기록은 공유 원장으로). `specs/tasks/INT-2-rerecord-e2e.md`의 `M` 표시와 `reports/M2a-review.md`의 `??` 표시는 작업 시작 전부터 있던 Claude 쪽 변경이다.

## 3. 실행한 명령과 결과

공유 venv·키 없이(기록 1회만 키 사용, 값은 출력·기록 안 함):

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\int-2"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q
# 263 passed in 22.42s (failed 0; 시작 시 8 failed에서 전량 해결)
cd $WT; & $PY -m pytest -q e2e
# 1 passed in 12.32s (가짜 서버)
# 재생 서버(127.0.0.1:64399)를 띄운 뒤:
$env:E2E_BASE_URL = "http://127.0.0.1:64399"; & $PY -m pytest -q e2e
# 1 passed in 8.00s (실제 백엔드)
& $PY tools\m0_spike.py --mode replay --probes all
# 9/9, 종료 코드 0 (ledger_total=$0.4624 lines=69)
git checkout -- reports/M0-spike.json
& $PY tools\secret_scan.py
# secret_scan: clean, 종료 코드 0
```

기록 실행 1회(저장소 밖이 아니라 메인 repo `.local/` 스크립트, 작업 트리 오염 없음):

```powershell
$env:META_MODE = "record"
$env:META_LEDGER_PATH = "C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl"
$env:READER_CONCURRENCY = "1"
& $PY C:\2026_project\claimback-ai-meta\.local\int2_record_run.py
# case: case_c2759f534902
# run1: CHECKPOINT_1
# facts: CALCULATING
# run2: DRAFT_APPROVAL
# revision_rounds: 1
# revisions: 1
# gate G2: pass (0); G4: pass (0); G1a: pass (0); G3: pass (0); NAMING: pass (0); DRAFT: pass (0)
# approved_all: True
# run3: CHECKPOINT_2
# run_cost: 0.1203
# RECORD_OK
```

기록 직후 재생 확인(같은 명령, 키 없이):

```powershell
cd "$WT\backend"; & $PY -m pytest -q tests/test_case_replay.py::test_replay_full_flow_to_checkpoint_2 tests/test_case_replay.py::test_replay_identical_across_case_ids
# 2 passed in 1.17s (누락 0, 두 사건 ID 동일)
```

4절 체크리스트 API 확인(재생, TestClient):

```text
stub: False
EX1 items: 17 box0: pixel
repayments type: list value: [{'date': '2026-05-01', 'amount': '1000000'}]
remaining: 4014383 accrual: 2026-05-02
PUT drafts G1a: fail findings: 2
approved: True
package files: ['content_proof.pdf']
```

## 4. 실호출 비용

- 모델: `muse-spark-1.3`만 8회(Standard, `-contributor` 없음). 판독 5·사실정리 1·문안 2(초안 1+수정 1). reasoning은 판독 `low`·사실정리 `low`·문안 `medium`.
- 비용: $0.120174 (공유 원장 `C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl` 기준, `run_id`=case_c2759f534902, completed 8건). 호출별: 0.009967·0.016797·0.007904·0.007667·0.014719·0.020154·0.023052·0.019914. 단계별 표시값 합계는 $0.1203(응답 usage 추정, 원장과 $0.0001 차이·반올림). 원장 줄 수 53→69(+16=예약 8+확정 8).
- 지연(기록, `READER_CONCURRENCY=1` 순차): 전체 약 3분(판독 5건 순차+사실정리 1+문안 2). 재생 전체 흐름은 약 1초.
- `run_id`는 사건 ID 하나를 전 호출에 사용. 작업 트리 안 원장은 건드리지 않음.
- P9: 문안⇄검증이 실제로 1회 수정. 1라운드는 G3 `fail`(s2 이어진 문장), DRAFT는 `pass`. 일부러 실패를 만들지 않음.

## 5. 열린 문제와 지시서·약속 대비 차이

- 판독값은 정답과 일치해 프롬프트 개선(M4b)으로 넘길 큰 어긋남 없음. 다만 사실정리가 `due_date`에 `conflict: true`를 냄(메모: 최초 변제기와 이후 변경 약속일이 다르게 확인됨). 값 자체는 2026-04-10으로 맞고 계산·문안·E2E에 지장 없음. `transaction_kind`은 `null`(사유: 판독에 없음)이라 데모 고정 입력의 `fallback_fields` `civil`로 계산 성공(M2a와 같은 설계).
- P2(세로로 긴 이미지 박스 어긋남)는 M4a 범위라 손대지 않음. 기록된 EX1 17·EX2 25·EX4 14·EX5 14·EX6 28개 항목 모두 박스는 `pixel` 정상.
- 사실정리 스키마는 `strict: false` 유지. 사유: `value`가 문자열·`null`·배열 다형성이라 strict 스키마로 표현 불가. 열거형은 스키마와 코드 양쪽에서 강제. 판독·문안은 `strict: true`로 기록 성공.
- `PUT /drafts`의 `rendered_text`는 지적이 있어도 갱신 시도(C7). 슬롯 치환이 실패하면 이전 표시를 유지하고 `슬롯 값을 채울 수 없습니다.` 지적을 덧붙임.
- `DRAFT` 게이트를 `gate_results` 여섯째로 추가(G2·G4·G1a·G3·NAMING·DRAFT). 계약 예시는 4개지만 키 검사는 예시 키 존재만 보므로 통과. 화면은 게이트 목록을 `gate_results`에서만 읽어 추가 게이트를 그대로 표시.
- `Review.fields[]`에 `null_reason`을, `Readings.items[]`에 `side`를 추가. 계약 예시에 없는 키라 키 검사에 영향 없음. 화면은 두 키를 쓰지 않음.
- `repayments` 빈칸은 `[]` 유지(`null` 아님). 기록된 샘플은 값이 있어 `[]` 경로를 타지 않으나 정규화·검증 코드와 단위 테스트로 고정.
- 500·없는 경로는 `/api/cases/*` 안에서만 약속 모양으로 통일. `/api/cases/..`처럼 정규화되어 라우터를 벗어나는 경로는 `main.py`(범위 밖)를 못 건드려 기본 405가 남음. `D:`·`%2E`·`%2E%2E`·위조 ID는 404로 차단하고 삭제 없음을 테스트로 고정.
- `interest_rate` NaN·Inf·전각 숫자, `principal`·`repayments.amount` 전각 숫자를 400으로 거부. 서비스 함수가 필요한 동작을 안 한 경우는 없음.
- 계산값 슬롯은 문안에서 제거하고 편철 정형 문구(청구취지 이율 구간문)로만 노출. `contract_interest`는 지시서 5종에 없어 허용 유지(값은 `delay_rate`와 같은 출처).
- 지시서와 스펙이 다투는 부분은 없음. 계약 침묵 부분의 해석은: `DELETE` 실행 중 409·`PUT` 실행 중 409·중간 상태 재실행 허용·`internal_error` HOLD만 재실행·한국 G4 초과는 안내만(HOLD 아님).

## 6. 명세 변경 제안

`specs/`는 직접 고치지 않음. 아래만 반영을 제안함:

1. 계약 5장 `Drafts.gate_results`에 `NAMING`·`DRAFT` 포함을 명시(순서 G2·G4·G1a·G3·NAMING·DRAFT).
2. 계약 5장 `Review.fields[]`에 `null_reason`(빈칸 사유, 값 있으면 `null`), `Readings.items[]`에 `side`(`left`|`right`|`null`) 추가.
3. 계약 3장 `hold_reasons` 코드에 `internal_error`(처리 중 오류, 재실행 가능)·`schema_failed`·`revision_exceeded`·`naming_violation`을 고정하고, `missing_facts`의 `fields`는 양식 칸 이름으로 적재.
4. 계약 1장 오류 모양을 500·없는 경로에도 적용(`code: internal_error`·`not_found`).
5. 계약 6장 업로드 제한(파일당 20MB·사건당 10개·확장자+매직바이트)을 명시.
6. 설계 3-7에 문안 규칙을 명시: 계산값 5종 금지·말하기 동사는 인용 슬롯 필수·`user` 문장은 발화 묘사 금지(게이트 `DRAFT`).
7. 설계 6장 계산 담당에 G2(검증 `missing_requirements` 그대로)·G4(`limit_check.exceeded` 그대로) 도출 규칙을 명시. 한국 G4 초과는 HOLD가 아니라 안내.
8. M2a 제안 유지: `drafts.json` 예시 s2의 G3 조각별 태그·`EXn`↔bare 숫자 번역 위치·`claim_purpose` 범위·`transaction_kind` 기본값·인라인만 사용.
