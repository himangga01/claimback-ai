# M0-fix2 리포트 (Muse Code)

- 작성: 2026-11-03 (KST), Muse Code (`muse-spark-1.3`)
- 작업 트리: `C:\2026_project\claimback-wt\m0-fix2` (브랜치 `m0-fix2`)
- Python: `C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe` (공유 venv, 신규 생성 없음)
- Meta 실호출: 0회

## 1. 지시서와 한 일

- 지시서: `specs/tasks/M0-fix2-client-for-m2.md` (먼저 읽음: `AGENTS.md`, 지시서, `reports/M0-fix1-review.md`의 D1~D11)
- M0-fix1 교차 리뷰(D1~D11)를 M2a 실호출 전에 고치는 작업. D1~D11 전 항목과 놓친 5가지 테스트를 구현했고, 지시서-스펙 충돌은 없어 중단 없이 완료했다.
- D1: 응답 직후 자동 삭제 제거 → 호출자가 마지막 시도 뒤에 부르는 `cleanup_files(file_ids)`(실패는 경고). 끊긴 응답 재시도가 같은 `file_id`를 재사용한다. 주석에 "PDF·이미지는 인라인 `file_data`/`image_url` 권장 (M0 P3에서 동작 확인)" 기재.
- D2: 키 확인·전송 계층 생성을 예약 앞으로 이동. 전송 뒤 모든 예외(응답 해석 `ValueError`·`ValidationError`·`JSONDecodeError` 포함)는 `failed` 줄 확정 후 재발생. `responses_create`·`images_generate`에 적용.
- D3: 공개 함수 `ledger_summary(run_id_prefix=None, ledger_path=None)`(`{total_usd, by_run_id, by_status}`; 예약은 확정 줄과 상쇄, 미확정 예약은 포함, 상태 없는 구 원장은 completed 비용으로 계산)와 `estimate_cost_from_body(model, endpoint, body)`(응답 usage+단가, 실패 시 0.0, 예외 없음) 추가. `m0_spike.py`의 단순 합산을 `ledger_summary`로 교체.
- D4: `META_LEDGER_PATH` 환경 변수(없으면 저장소 `reports/cost_ledger.jsonl`)로 원장 경로 단일화. 잠금 파일은 원장 옆(`<원장>.lock`).
- D5: 오래된 잠금 5초·기다림 15초, 파일 잠금을 RLock 없이 먼저 획득(순서 정리), 삭제 실패 재시도(`_unlink_best_effort`, 최대 6회), `BudgetError` 공통 부모(`BudgetExceeded`·`BudgetLedgerError`가 상속), `.gitignore`에 `*.lock`.
- D6: SAM `frame_count` 필수는 영상(`input_video` 블록 또는 `frame_count` 전달)일 때만. `input_file` 단독은 이미지 단가.
- D7: OpenAI SDK 클라이언트를 `MetaClient` 인스턴스에 캐시해 재사용, `close()` 추가(반복 호출 안전, 주입된 전송 계층은 닫지 않음).
- D9: `extra`는 `metadata`만 허용(allowlist). 기존 fixture 30개 전수 확인: `responses` 25개 중 `metadata`를 쓴 것은 `98f20261`·`a5f3ffe0`(P6) 2개뿐이고, 나머지 파라미터는 표준 키뿐이라 해시 구성을 바꾸지 않았다(확인용 테스트 `test_fixtures_extra_only_metadata` 추가).
- D10: 상한 값이 숫자가 아니거나 음수·무한대·NaN이면 `ValueError`. `"0"`은 0으로 존중(과금 실호출 전부 거부).
- D11: `reports/cost_ledger.jsonl` git 추적 유지, 실행 원장은 `META_LEDGER_PATH`로 단일화. `files_delete`는 예산 검사 없이 동작. 오래된 잠금은 원자적 claim(이름 변경 후 삭제, victim도 `.lock` 접미), 미래 mtime은 stale(1초 유예, 5절 참조). Windows `PermissionError`는 재시도.
- 테스트: 항목별 깨뜨림-감지 테스트와 놓친 5가지(원장 읽기 `OSError`→거부, 한글 전용 토큰 추정, `META_RUN_CAP_USD` 반영, 실패 경로 파일 정리, 느린 읽기 동시성) 추가. `time.sleep` 패치를 `_sleep_retry`(재시도 대기)에만 적용. 기존 타이밍 경합 동시성 테스트는 같은 이름의 결정적 테스트로 교체(5절 참조).

## 2. 생성·변경 파일

신규 없음. 수정 6개(지시서 파일 범위 내) + 본 리포트:

- `backend/app/meta/client.py`: D1, D2, D3(공개 함수 2개+내부 헬퍼), D4, D5, D6, D7, D9, D11. 요청 해시·`run_id` 필수 규칙 무변경.
- `backend/app/meta/pricing.py`: D10 상한 해석(`ValueError`, 0 존중).
- `backend/app/meta/__init__.py`: `BudgetError`, `ledger_summary`, `estimate_cost_from_body`, `resolve_ledger_path`, `LEDGER_PATH_ENV` 공개.
- `backend/tests/test_meta_client.py`: 기존 4건 갱신(수면 패치 범위, SAM 영상/file, 자동 정리→명시 정리, 동시성 교체), 신규 37건(파라미터 전개 포함).
- `tools/m0_spike.py`: 원장 합계 부분만. `ledger_total()`이 `ledger_summary()` 사용, 하드코딩 `LEDGER` 상수 제거.
- `.gitignore`: `*.lock` 1줄.
- `reports/M0-fix2.md`: 본 리포트.

편집 메모: 편집 도구의 여러 줄 찾기가 LF에서만 동작해 대상 5개 파일을 LF로 바꾼 뒤 편집하고 CRLF로 복원했다. 최종 `git diff --stat`는 6개 파일, 938 insertions, 194 deletions이며 줄바꿈 정규화 노이즈가 없다.

## 3. 실행 명령과 결과

키 없이 실행(`Remove-Item Env:MODEL_API_KEY` 후). 실패 0.

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m0-fix2"
cd "$WT\backend"; & $PY -m pytest -q
# 134 passed, 1 xfailed in 4.09s (xfailed 1건은 범위 밖 기존 항목: 아래 참조)
cd $WT; & $PY tools\m0_spike.py --mode replay --probes all
# mode=replay ... ledger_total=$0.2135 lines=37, P0~P8 success 9/9
git checkout -- reports/M0-spike.json   # 재생이 바꾼 P7 경로 되돌림 (git status로 6개 파일만 변경 확인)
& $PY tools\secret_scan.py              # secret_scan: clean, exit 0
```

- `tests/test_meta_client.py`만: 88 passed. 전체 스위트의 xfailed 1건은 `test_naming.py::test_naming_frontend_app_js_clean`(사유 "M3에서 수정, 병합 후 통과해야 함", M1 리포트 기재)이며 본 작업 범위 밖이다.
- 재생 합계 `ledger_total=$0.2135 lines=37`은 M0-fix1 리포트 값과 동일(구 37줄 원장, 상태 필드 없음, naive 합계와 일치).
- 추가 검증(커밋 없음, 일회성): `_holding_ledger_lock`을 no-op으로 바꾼 변이에서 새 동시성 테스트가 실패함을 확인 후 원복(`Select-String`으로 변이 잔재 없음 확인, 테스트 재통과). `request_hash`·`canonicalize_for_hash`·`extract_*`·`estimate_input_tokens`는 diff상 무변경. 작업 트리에 `*.lock*` 잔재 없음. `py_compile` 5개 파일 통과.
- 기존 fixture 30개는 spike 재생 9/9로 전부 재생됨(해시 불변).

## 4. Live API 호출

- 모델·횟수·비용: 없음. 0회, $0 (`reports/cost_ledger.jsonl` 무변경, 37줄 유지).
- 전부 가짜 전송 계층·가짜 키(런타임 조립 문자열, 정적 스캔 미검출)·재생 모드로 검증했다.

## 5. 열린 문제와 지시서·스펙에서의 이탈

이탈은 없고, 아래는 지시서가 값을 정하지 않아 해석한 부분이다(리뷰어 확인용):

- 미래 mtime 1초 유예(D11): "미래 시각 mtime도 오래된 것으로"를 `age < -1.0`일 때 stale로 처리했다. 파일시스템 정밀도·시계 granularity로 방금 만든 잠금이 0보다 작은 age로 보이는 경우의 오탈취를 막기 위함이며, 1시간 뒤 같은 실제 미래 시각은 그대로 정리된다(테스트 `test_future_mtime_lock_is_stale`).
- 상한 `"0"`의 범위(D10): "모든 실호출 거부"를 과금 호출 기준으로 해석했다. `0 + expected > 0`이므로 과금 호출은 전부 거부되지만, 원장이 비어 있을 때 무료 호출(`models_list`, `files_create`)은 통과한다. `files_delete`는 예산 검사가 없어 상한과 무관하다.
- `by_status` 값 형태(D3): 지시서가 값 형태를 안 정해 `{count, cost_usd}`로 했다. `count`는 상쇄분 포함 전 줄 수(`m0_spike`의 lines와 일치), `cost_usd`는 상쇄 후 금액이다.
- `m0_spike` 파손 원장 처리 변경: 기존 `ledger_total`은 깨진 줄을 조용히 건너뛰었으나, 교체 후에는 `BudgetLedgerError`로 중단한다(fail-closed, 클라이언트와 같은 철학). 정상 원장에서는 동작이 같다.
- 기존 동시성 테스트 교체: 구 테스트는 "T2 검사 vs T1 완료 기록"의 타이밍 경합이라(신 코드에서 5회 중 3회 실패, M0-fix1 리뷰도 "우연히 잡힘"으로 지적) 같은 이름으로 결정적 테스트(읽기 후 0.3초 유지+전송 게이트, 실제 sleep)로 교체했다. 구 테스트의 통과 조건(한쪽 거부, `run_total < 2.0`)은 유지·강화했고, 잠금 제거 변이에서 실패함을 확인했다. 삭제가 아니라 사양 강화 목적의 교체다.
- 후속 필요(M2a·spike, 본 작업 범위 밖이라 미수정): 응답 뒤 자동 삭제가 사라져 live/record에서 P4·P6 등이 올린 파일이 서버에 남는다. M2a는 사건 종료 시 `cleanup_files(file_ids)`를 호출해야 하고, spike도 언젠가 같은 정리를 해야 한다. `MetaClient.close()` 역시 spike가 호출하지 않는다(파일 범위상 미수정).

## 6. 스펙 변경 제안 (specs/는 직접 고치지 않음)

- 제안 1 (에이전트 설계·M2a 지시서): "Files API 업로드분은 사건 종료(또는 마지막 재시도) 뒤 `MetaClient.cleanup_files(file_ids)`로 정리, 인라인 `file_data`/`image_url`은 정리 불필요(M0 P3 확인)" 규칙을 명시한다. D1으로 런타임이 자동 정리하지 않게 바뀌었기 때문이다.
- 제안 2 (구현테스트계획 4-7 또는 `.env.example` 문서화): 운영·다중 작업 트리에서 `META_LEDGER_PATH` 절대 경로를 한 곳으로 모으라는 운용 규칙을 적는다. 코드는 준비됐고(`resolve_ledger_path`), 기본값·예시 경로 문서만 남았다.
- 제안 3 (에이전트 설계): 예산 거부·원장 오류를 한 번에 잡는 `BudgetError` 공통 부모가 생겼으므로, M2a의 budget-failure 분기 예시가 `BudgetExceeded`만 잡고 있다면 `BudgetError`로 넓히는 것을 검토한다.
