# M2a 리포트: 코디네이터·담당·사건 API (Muse Code)

- 작성: 2026-11-03 (KST), Muse Code (`muse-spark-1.3`)
- 작업 트리: `C:\2026_project\claimback-wt\m2a-backend` (브랜치 `m2a-backend`)
- Python: `C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe` (공유 venv, 신규 생성 없음)

## 1. 지시서와 한 일

- 지시서: `specs/tasks/M2a-coordinator-agents.md` (2판 + 12a 동시성 추가)
- 먼저 읽은 문서: `AGENTS.md`, 지시서, `specs/case-api-contract.md`(v2),
  `specs/case-api-examples/*.json` 6종, `reports/M0-review.md`,
  `reports/M0-fix1-review.md`, `reports/M0-fix2.md`, `reports/M1.md`,
  `reports/M1-fix1.md`, `reports/M3.md`, `reports/M3-fix1.md`,
  에이전트 설계 1장·2-1·3-1·3-4·3-6·3-7·3-9·4-1~4-4
- 단계 A(실호출 없음, 완료): 새 패키지 `backend/app/agents/`
  (`deps`·`base`·`case_state`·`intake`·`demo_inputs`·`coordinator`·`packager`),
  새 라우터 `backend/app/api/cases.py`, `main.py` 라우터 등록,
  계약 테스트 11개(가짜 담당 주입). 가짜 담당만으로 `CHECKPOINT_2`까지 도달.
- 단계 B(실호출, 완료): Spark 담당 3개(`reader`·`fact_organizer`·`drafter`)와
  공용 호출 헬퍼(`spark.py`), 프롬프트 3개(`prompts/*.v1.md`), 기록 실행 1회,
  재생 테스트 8개. 재생으로 같은 흐름을 다시 돌려 fixture 누락 없음을 확인했고,
  서로 다른 `case_id` 두 개로 `Review`·`Drafts`가 같음을 테스트로 확인.
- E2E(건너뜀): 이 작업 트리에 `e2e/`가 없어(지시서 예상대로) 실행하지 못함.
  병합 뒤 Claude가 실행. `e2e/` 부재는 `Test-Path`로 확인.

## 2. 만든·고친 파일

새 파일:

- `backend/app/agents/__init__.py`: 패키지 설명
- `backend/app/agents/deps.py`: M0-fix2·M1·M1-fix1 어댑터.
  `calculate_kr`, `check_g1a`·`check_g3`, `check_draft`(명칭),
  `substitute_text`(조사 맞춤), 서류 생성 `fact_sentences` 인자,
  `MetaClient`·`Box`·예산 오류를 여기서만 가져옴.
  호증 번호 번역(`EX4`↔`4`), 슬롯 표시값·인용 렌더,
  `LoanFactSchema` 구성, `Calculation` JSON 변환 포함
- `backend/app/agents/base.py`: 설계 4-1 `AgentTask`·`AuditRecord`(단계·`ex_id`·
  모델·프롬프트 버전·입력 해시·지연·토큰·비용)·`AgentResult`, `AgentSchemaError`
- `backend/app/agents/case_state.py`: 설계 4-2 구역 Pydantic 모델,
  `backend/data/cases/<case_id>/case.json` 저장(쓸 때마다 버전 증가,
  tmp+replace 원자 쓰기), 단계별 저장
- `backend/app/agents/intake.py`: SHA-256, 증거 번호(샘플 EX1~EX6 고정),
  종류 판별, 영상 `skipped`, PDF는 `iou.png`를 미리보기로
- `backend/app/agents/demo_inputs.py`: `build_demo_confirmed_facts(review)`
  (계약 5장 규칙 그대로, 빈 칸만 `fallback_fields`로, `as_of` 2026-06-01)
- `backend/app/agents/coordinator.py`: 계약 3장 전이표, 동시 `POST /run` 409,
  판독 증거별 병렬(스레드, 결과 `ex_id` 숫자 순 저장, `substeps` 기록),
  `READER_CONCURRENCY`(기본 4) 설정, 계산·문안⇄검증(최대 2회 수정) 흐름
- `backend/app/agents/packager.py`: 승인 문장 슬롯 치환·조사 맞춤 후
  `fact_sentences`로 내용증명 PDF·전자소송 문구 생성, 패키지 전체 명칭 검사
- `backend/app/agents/spark.py`: Spark 공용 호출(원장 diff·재생 usage 비용,
  `IncompleteResponse` 1회 8,000 재시도, JSON 파싱, 필드명 요약)
- `backend/app/agents/reader.py` + `prompts/reader.v1.md`: 설계 3-1 `Reading`
  구조화 출력, 이미지·PDF 인라인(`image_url` data URL, PDF `file_data`),
  `norm1000`→미리보기 픽셀 `Box`, `item_id` 출력 순서 재부여,
  `READER_MODEL`(기본 `muse-spark-1.3`), reasoning `low`, 4,000토큰
  (`IncompleteResponse`면 8,000으로 1회, 스키마 오류면 필드명 요약으로 1회
  재요청, 실패 시 그 증거만 `hold`)
- `backend/app/agents/fact_organizer.py` + `prompts/fact_organizer.v1.md`:
  판독 결과만 입력, 계약 5장 `Review` 생성(필드 이름표·표시값은 코드 상수,
  모델 출력은 값·근거·충돌·질문·태그만), reasoning `medium`
- `backend/app/agents/drafter.py` + `prompts/drafter.v1.md`: 설계 3-6·4-4
  머리말, 입력 `KR_SLOTS`(이름·설명만)·발화·강조·증거 목록, 출력 `SlotDraft`,
  검증 G1a+G3+명칭, 지적 반영 최대 2회 수정(`revisions[]` 기록), 초과 시 HOLD
- `backend/app/api/cases.py`: 계약 6장 엔드포인트·5장 응답·1장 오류 형식.
  요청 본문 직접 검사(422 대신 400), `FixtureNotFound`→`replay_fixture_missing`
  HOLD, `BudgetError`→`budget_exceeded` HOLD
- `backend/tests/test_case_contract.py`: 단계 A 계약 테스트 11개
- `backend/tests/test_case_replay.py`: 단계 B 재생·위생 테스트 8개
- `backend/tests/fixtures/meta/*.json` 8개: 기록 실행에서 추가
  (판독 5, 사실 정리 2(재시도 1 포함), 문안 작성 1)
- `reports/M2a.md`: 이 리포트

고친 파일(지시서 범위 안만):

- `backend/app/main.py`: `cases` 라우터를 정적 마운트보다 먼저 등록(2줄)
- `requirements.txt`: `uvicorn>=0.30.0` 1줄(공유 venv에 이미 설치됨 확인)

건드리지 않음: `specs/`, `AGENTS.md`, `frontend/`, `docs/`, `e2e/`,
`sample_evidence/`, `backend/tests/golden/`, `backend/app/meta/`,
`backend/app/services/`, `.env`(읽기·생성 없음), 다른 리포트.
`reports/M0-spike.json` 변경 없음(`git status` 확인).
`specs/tasks/M2a-coordinator-agents.md`가 `git status`에 `M`으로 보이나
내용 diff는 없음(줄바꿈 표시). 이 파일은 열람만 했고 고치지 않았다.

## 3. 실행한 명령과 결과

작업 트리와 Python(지시서 완료 기준과 동일):

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m2a-backend"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q
```

결과: `202 passed, 1 xpassed in 9.41s`, failed 0.
xpass 1건은 기존 `test_naming_frontend_app_js_clean`(M2b 영역, 범위 밖,
M3-fix1 리포트와 같은 상태).

```powershell
cd "$WT\backend"; & $PY -m pytest -q tests/test_case_contract.py
# 11 passed in 4.47s (단계 A: 전체 흐름·409·HOLD 5경로·업로드·golden 미참조)
cd "$WT\backend"; & $PY -m pytest -q tests/test_case_replay.py
# 8 passed in 1.11s (단계 B: 재생 전체 흐름·두 case_id 동일성·fixture 부재 HOLD·
#  프롬프트 위생·요청 무결성·정규화 3종)
cd $WT; & $PY tools\secret_scan.py
# secret_scan: clean, 종료 코드 0
```

E2E(지시서 13항): `Test-Path e2e` → False. 재생 서버+E2E는 실행하지 않았고
병합 뒤 Claude가 실행한다. 화면 `stub` 플래그는 실서버 응답에 `false`로 고정했고
계약 테스트에서 확인했다.

기록 실행(단계 B 마지막에 1회, 저장소 밖 스크립트 `C:\Users\Public\m2a_record_run.py`):

```powershell
$env:META_MODE = "record"
$env:META_LEDGER_PATH = "C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl"
$env:READER_CONCURRENCY = "1"
& $PY C:\Users\Public\m2a_record_run.py
# run1: CHECKPOINT_1, run2: DRAFT_APPROVAL (revision_rounds 0), run3: CHECKPOINT_2
```

기록 직후 같은 흐름을 재생으로 다시 돌려 누락 없음을 확인했고(위 재생 8개 통과),
`Review`·`Drafts` 두-`case_id` 동일성도 통과했다.

## 4. 실호출 비용

- 모델: `muse-spark-1.3`만 사용(Standard 등급, `-contributor` 없음).
- 횟수: 8회(판독 5, 사실 정리 2=최초 1+스키마 재시도 1, 문안 작성 1).
  reasoning은 판독 `low`, 사실 정리 `medium`, 문안 작성 `medium`.
- 비용: $0.128657 (공유 원장 `reports/cost_ledger.jsonl` 기준, `run_id`=기록
  `case_id` 요약: completed 8건·예약 8건 상쇄). 원장 줄 수 37→53(+16).
  단계별: 판독 $0.0588, 사실 정리 $0.0527, 문안 작성 $0.0171.
- 단계별 지연(기록, `READER_CONCURRENCY=1` 순차):
  판독 103,463ms, 사실 정리 76,189ms(재시도 포함), 문안 작성 34,100ms,
  검증 34,118ms(게이트 포함 벽시계), 편철 13ms, 계산 0ms.
  재생 전체 흐름은 테스트 8개 합계 약 1초(병렬 판독)다.
- `run_id`는 모든 호출에 `case_id` 하나를 썼고, 실행 중 원장은 환경 변수
  `META_LEDGER_PATH`가 가리키는 한 곳으로만 기록했다.
- 작업 트리 안 `reports/cost_ledger.jsonl`은 건드리지 않았다(기록은 공유 원장으로).

## 5. 열린 문제와 지시서·약속 대비 차이

- 계약 예시 `drafts.json`의 s2(`...했습니다. {{quote}} [[EX:1]] [[EX:6]]`)는
  M1-fix1 G3 조각별 태그 규칙을 통과하지 못한다(첫 조각에 태그 없음).
  예시는 키 확인용이므로, 가짜 문안과 문안 프롬프트는 조각마다 태그를 넣는
  형태로 썼다(`...했습니다 [[EX:1]]. {{quote}} [[EX:6]]`). 기록된 실제 문안도
  이 규칙을 첫 시도에 통과했다(`revision_rounds` 0).
- M1 `check_g1a`·`check_g3`는 호증 번호로 bare 숫자(`"4"`)를 쓴다(기존 테스트
  `EXISTING = ["1", "2"]`). 계약의 `EX4` 형식은 어댑터(`deps.py`)에서만 번역해
  호출하고 응답에는 계약 형식을 유지했다. 지적 문구 속 숫자는 bare 숫자다.
- `Drafts.gate_results`에 계약 예시의 G2·G4·G1a·G3 외에 `NAMING`을 다섯째로
  넣었다(지시서 10항 "검증 = G1a + G3 + 명칭 검사" 반영). 키 검사는 통과한다.
- 패키지 `gate_results`의 G1b는 `status: "skipped"`(M5 예정대로).
- HOLD 코드: 계약 1장 목록은 HTTP 오류용이고 `hold_reasons` 코드는
  `replay_fixture_missing`만 예시되어 있어, G2 결손 `missing_facts`,
  스키마 2회 실패 `schema_failed`, 수정 루프 초과 `revision_exceeded`를
  추가했다. `naming_violation`(편철 명칭 실패용)도 있으나 발생하지 않았다.
- 동시 `POST /run`은 409 `wrong_state`(계약에 별도 코드 없음).
- `PUT /facts`는 `CHECKPOINT_1` 또는 계산·초안 단계(`calculating`·`drafting`·
  `verifying`)에서 생긴 HOLD에서만 받고, 증거 업로드는 `INTAKE`에서만 받는다
  (계약 침묵 부분의 엄격 해석).
- 인용 렌더링은 원문을 큰따옴표로 감싼다. `fact_sentences`는 번호를 매겨
 (`"1. ..."`) PDF·전자소송 문구에 넣는다. `claim_purpose`는 M1 패킷의 정형문
  전체를 쓴다(계약 예시는 한 문장만 보임).
- 기록에서 모델이 `transaction_kind`을 비워 두었으나 데모 고정 입력의
  `fallback_fields`가 `civil`로 채워 계산까지 성공했다(fallback 설계대로).
- 사실 정리는 최초 1회가 스키마 오류로 재시도 후 성공했다. 재시도 요청의
  오류 요약에는 필드 이름만 넣었고(예외 문자열·값 없음), 재생도 같은 경로를
  탄다(두 번째 fixture로 고정).
- 미리보기 없는 일반 PDF 업로드의 박스 기준은 `pypdf` 첫 쪽 포인트 크기다
  (샘플 `iou.pdf`는 미리보기 PNG 기준). 해당 PDF의 `preview_url`은 `null`.
- 비용 표시는 0이면 `"0"`, 아니면 소수 4자리 문자열이다. 실호출은 호출 전후
  원장 요약 차이, 재생은 응답 usage 추정(`estimate_cost_from_body`)으로
  단계·실행 비용을 매긴다.
- G1a 허용 슬롯은 값이 있는 슬롯(`available_slots`)으로 제한해 빈칸 렌더를
  구조적으로 막았다. 존재하지 않는 인용(`quote:EX9...`)은 G1a 지적에 합산된다.
- `e2e/` 부재로 재생 E2E는 미실행(위 3절). 서버 기동(`uvicorn`) 확인도 병합 뒤로.

## 6. 명세 변경 제안

`specs/`는 직접 고치지 않았다. 아래만 반영을 제안한다:

1. 계약 5장 `drafts.json` 예시 s2를 G3 조각별 태그 규칙에 맞게 고친다
   (조각마다 `[[EX:n]]`, 예: `...했습니다 [[EX:1]]. {{quote}} [[EX:6]]`).
   또는 설계 3-7에 "인용 슬롯+태그 조각은 앞 조각에 귀속" 같은 예외를 명시한다.
2. 계약 3장 `hold_reasons` 코드 목록을 고정한다
   (`missing_facts`, `schema_failed`, `revision_exceeded`,
   `replay_fixture_missing`, `budget_exceeded`, `naming_violation`).
3. 설계 3-7에 G1a·G3 호증 번호 형식을 명시한다(M1은 bare 숫자, 계약은 `EXn`,
   번역은 어댑터 담당).
4. 계약 5장 `Drafts.gate_results`에 `NAMING` 포함 여부를 명시한다.
5. 계약 5장 `Package.ecourt.claim_purpose` 범위(한 문장 vs 패킷 정형문 전체)와
   `claim_cause_payment_order` 형태(번호 문장 vs 소제목+문장)를 명시한다.
6. 모델이 `transaction_kind`을 비울 때 기본값 규칙(현행: 데모 `fallback_fields`
   `civil`)을 계약 5장 고정 입력 규칙에 명시한다.
7. M0-fix2 제안 유지: Files API를 쓰지 않고 인라인(`file_data`·`image_url`)만
   쓰므로 업로드분 정리(`cleanup_files`)가 M2 사건 흐름에 불필요함을
   에이전트 설계에 명시한다.
