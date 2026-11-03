# M0-fix3 리포트 (Muse Code)

- 작성: 2026-11-03 (KST), Muse Code (`muse-spark-1.3`)
- 작업 트리: `C:\2026_project\claimback-wt\m0-fix3` (브랜치 `m0-fix3`)
- Python: `C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe` (공유 venv, 신규 생성 없음)
- Meta 실호출: 0회

## 1. 지시서와 한 일

- 지시서: `specs/tasks/M0-fix3-lock-and-incomplete.md` (먼저 읽음: `AGENTS.md`, 지시서, `reports/M0-fix2-review.md`의 E1~E6, `specs/case-api-contract.md`와 `specs/case-api-examples/`). 지시서-스펙 충돌은 없어 중단 없이 완료했다.
- E1(차단): Windows 잠금 생성의 `PermissionError`(삭제 대기 중인 이전 잠금)를 `FileExistsError`처럼 다루어 20ms씩 15초 한도까지 재시도. 과금 응답의 확정 기록이 잠금 실패로 안 되면 fixture를 먼저 저장하고 `RuntimeWarning`(메시지에 `NOT recorded`) 후 응답을 반환한다(끊긴 응답은 `body`를 담은 `IncompleteResponse`로 제기, 5절 해석 참조). 열린 예약 줄은 그대로 남아 보수적으로 계산된다.
- E2: 잠금 `stat` 실패·stale 이름바꾸기 실패 경로에 한도 확인과 20ms 쉼을 넣어 한도(15초) 안에서 멈추게 했다.
- E3: 공유 `MetaClient`의 SDK 클라이언트 생성을 인스턴스 잠금(`_sdk_lock`)으로 보호해 8스레드 동시 호출에도 1개만 만들고, `close()`도 같은 잠금으로 그 하나를 닫는다.
- E4: `IncompleteResponse`에 `body`를 담았다(`__init__(message, reason=None, body=None)`, 기존 호출 호환). `_check_incomplete`가 본문을 전달하므로 live/record/재생 모두 끊긴 시도의 비용을 `estimate_cost_from_body(model, "responses", exc.body)`로 계산할 수 있다.
- E6(사소): 잠금 파일에 소유 토큰(`pid.uuid`)을 기록하고 해제 때 확인(남의 잠금은 삭제 안 함). `estimate_cost_from_body`는 SAM 이미지 수를 `usage.images_processed`(없으면 1)로, Spark는 출력-전용 본문의 출력 비용도 계산해 실호출 기록과 같은 규칙으로 맞췄다(잔여 차이는 5절). `Box`·`box_to_pixels`를 `app.meta`에서 내보내기. `ledger_summary`는 잠금 없이 읽기만 하고 부분 줄은 건너뛰지 않고 `BudgetLedgerError`로 오류낸다.
- E7(망가뜨리기 시험): live/record에서 원장 경로가 명시 인자가 아닐 때 `META_LEDGER_PATH`는 절대 경로여야 하고, 파일이 없으면 `META_LEDGER_INIT=1` 없이는 `BudgetLedgerError`로 호출을 거부한다. 기본 경로도 파일 존재가 필요하다. 명시 `ledger_path`와 정리용 `files_delete`는 검사에서 제외한다(5절 해석 참조).
- E8: `images_generate`는 이미 D2 구조(예약 전 전송 생성, 전송 뒤 예외는 `failed` 줄 확정)였음을 확인하고 깨뜨림-감지 테스트 2건으로 고정했다. 기존 stale 정리 테스트에 10초 한도를 두고, 요청 해시 고정 2건(`responses` 1건 + `models.list` 1건, 후자는 커밋된 fixture `05f1ff6a`와 일치)을 추가했다. `tools/m0_spike.py`는 실패한 프로브(`success is not True`)가 있으면 종료 코드 1을 반환한다(종료 코드 부분만 수정).

## 2. 생성·변경 파일

신규 1개(본 리포트), 수정 4개(지시서 파일 범위 내):

- `backend/app/meta/client.py`: E1, E2, E3, E4, E6(소유 토큰·estimate·무잠금 요약), E7 가드, E1 보존용 fixture 저장 분리(`_save_response_fixture`·`_save_image_fixture`), SAM 실기록에 `images_processed` 반영.
- `backend/app/meta/__init__.py`: `Box`·`box_to_pixels` 내보내기(E6).
- `backend/tests/test_meta_client.py`: 기존 2건 갱신(`test_meta_ledger_path_env`에 `META_LEDGER_INIT=1`, `test_stale_lock_cleaned`에 10초 한도), 신규 17건(해시 고정 1, E1 4건, E2 2건, E3 1건, E4 1건, E6 5건, E7 1건, E8-images D2 2건).
- `tools/m0_spike.py`: `main()` 끝의 `return 0`만 실패-감지 종료 코드로 교체(E8).
- `reports/M0-fix3.md`: 본 리포트.

편집 메모: 4개 파일은 CRLF라 LF로 바꾼 뒤 편집하고 CRLF로 복원했다. 최종 diff는 내용 변경만이다(`client.py` 274줄, 테스트 412줄, `__init__.py` 2줄, `m0_spike.py` 3줄).

## 3. 실행 명령과 결과

키 없이 실행(`Remove-Item Env:MODEL_API_KEY` 후). 실패 0.

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m0-fix3"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q
# 200 passed, 1 xpassed in 15.11s
cd $WT; & $PY tools\m0_spike.py --mode replay --probes all  # 9/9, 종료 코드 0
git checkout -- reports/M0-spike.json
& $PY tools\secret_scan.py                                  # secret_scan: clean, exit 0
```

- `tests/test_meta_client.py`만: 105 passed in 11.87s (기존 88 + 신규 17). 동시 부하 테스트(8스레드 × 50회 = 400회)는 잠금 오류 0건, 예약 400·확정 400 짝 맞음, 잠금 잔재 없음.
- 전체 스위트의 xpassed 1건은 범위 밖 기존 항목(`test_naming.py`, M0-fix2 리포트에서 xfailed로 기재된 것과 같은 1건이 이번 트리에서 통과로 바뀜)이며 실패가 아니다(non-strict).
- 재생 합계 `ledger_total=$0.2135 lines=37`은 M0-fix2 리포트 값과 동일. 재생 뒤 `reports/M0-spike.json`은 되돌렸고(`git status`로 범위 내 4개 파일 + 본 리포트만 변경 확인), `*.lock*` 잔재 없음, `reports/cost_ledger.jsonl` 37줄 무변경.
- 기존 fixture 30개는 spike 재생 9/9로 전부 재생됨(해시 불변, 고정 테스트 2건 포함).

## 4. Live API 호출

- 모델·횟수·비용: 없음. 0회, $0 (`reports/cost_ledger.jsonl` 무변경, 37줄 유지).
- 전부 가짜 전송 계층·가짜 키(런타임 조립 문자열)·재생 모드로 검증했다.

## 5. 열린 문제와 지시서·스펙에서의 이탈

이탈은 없고, 아래는 지시서가 값을 정하지 않아 해석한 부분이다(리뷰어 확인용):

- E7 명시 경로 제외: "원장이 없으면 거부"를 `META_LEDGER_PATH`·기본 경로에만 적용하고, 명시 `ledger_path` 인자는 의도적인 경로로 보아 검사를 건너뛴다. 지시서가 환경 변수·기본 경로만 언급하고, 모든 기존 테스트와 M2a의 명시 경로 호출이 파일 생성에 의존하기 때문이다. 정리용 `files_delete`도 검사에서 제외했다(상한 초과 뒤에도 동작해야 한다는 D11과 같은 이유).
- estimate 입력-0 잔여 차이: 사용량이 완전히 비어 있을 때 live 기록은 `expected`(보수적, 호출이 과금됐으므로)이고 `estimate_cost_from_body`는 0.0이다. 사전 추정치 없이는 일치시킬 수 없어 남겼으며, 출력이 있는 본문은 양쪽 다 0이 아닌 비용을 낸다.
- spike 종료 코드: `success=None`(예산 건너뜀)도 `is not True`로 실패 취급해 종료 코드 1을 낸다. 조용한 통과를 막기 위함이며, 정상 재생 9/9에서는 0이다.
- E8 images D2: 코드는 M0-fix2에서 이미 D2를 갖춰 바꿀 것이 없어 테스트 2건(키 누락 시 예약 없음, 전송 실패 시 `failed` 줄)으로 고정했다.
- `specs/tasks/M0-fix3-lock-and-incomplete.md`의 워킹트리 변경분(5a/5b·spike 범위 추가)은 본 작업이 아니다. 작업 시작 전부터 있었고 본인은 `specs/`를 편집하지 않았다.
- 열린 문제: 8×50 부하는 로컬 tmp 잠금 기준이며 NFS 등 공유 파일시스템에서는 미검증이다. E1 보존이 일어나면 예약 줄이 열린 채 남아 후속 `run_total`이 보수적(높게)으로 계산된다. `ledger_summary` 무잠금 읽기는 동시 기록 중 torn 줄에서 `BudgetLedgerError`가 날 수 있어 호출자가 재시도해야 한다.

## 6. 스펙 변경 제안 (specs/는 직접 고치지 않음)

- 제안 1 (구현테스트계획 4-7 또는 `.env.example` 문서화): 새 환경의 첫 live/record 실행은 원장 파일이 없으면 거부되므로, `META_LEDGER_INIT=1`로 1회 실행해 원장을 만든 뒤 변수를 제거하라는 운용 규칙을 적는다. `META_LEDGER_PATH`는 절대 경로 필수도 함께 명시한다.
- 제안 2 (에이전트 설계·M2a 지시서): 확정-기록 실패 경고(`RuntimeWarning`, 메시지 `NOT recorded`)를 M2a 로그·화면에 노출하고, 끊긴 시도의 비용은 `IncompleteResponse.body`에 `estimate_cost_from_body`를 적용해 표시하라고 명시한다.
- 제안 3 (에이전트 설계): 예산 분기 예시에 `BudgetLedgerError` 처리를 더한다. 특히 E7 거부(상대 경로·원장 누락)는 설정 오류이므로 재시도가 아니라 중단·안내 대상으로 구분한다.
- 제안 4 (에이전트 설계, 선택): `ledger_summary`가 잠금을 잡지 않는 읽기 전용임을 명시하고, 동시 기록 중 torn 줄 오류 시 짧게 쉬고 재시도하라고 적는다.
