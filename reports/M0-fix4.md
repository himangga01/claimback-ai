# M0-fix4 리포트 (Muse Code)

- 작성: 2026-11-03 (KST), Muse Code (`muse-spark-1.3`)
- 작업 트리: `C:\2026_project\claimback-wt\m0-fix4` (브랜치 `m0-fix4`)
- Python: `C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe` (공유 venv, 신규 생성 없음)
- Meta 실호출: 0회

## 1. 지시서와 한 일

- 지시서: `specs/tasks/M0-fix4-ledger-guard-tests.md` (먼저 읽음: `AGENTS.md`, 지시서, `reports/M0-fix3.md`, `reports/M0-fix3-review.md`의 N1·N2·T1·T2). 지시서-스펙 충돌은 없어 중단 없이 완료했다.
- N1(중간): `files_delete`가 live/record에서 원장 파일이 없을 때 원장을 새로 만들면서 E7 방어를 우회하던 문제를 고쳤다. 지시서가 허용한 두 방식 중 "같은 방어로 거부"를 택해, replay 분기 뒤에 `self._require_ledger_ready()` 한 줄을 넣었다. 다른 무료 경로(`models_list`, `files_create`)는 이미 방어가 있어 손대지 않았다. D11(상한 초과 후에도 정리 동작)은 방어가 상한을 보지 않으므로 유지되고, `cleanup_files`는 그대로 경고만 낸다.
- N2(낮음): 오래된 잠금을 이름 바꿔 가져온 뒤 가져온 파일의 시각(mtime)과 내용(소유 토큰)을 다시 확인한다. 여전히 오래된 것일 때만 지우고, 그 사이 바뀐 새 잠금이면 경로가 비었을 때 되돌리고(복원 불가면 버리고) 한도 안에서 재시도한다.
- T1: 잠금·회전 관련 테스트 8건에 시간 한도를 두었다. 작업 스레드는 데몬+`join(timeout)`으로 기다리고 넘으면 실패한다. `pytest-timeout`은 설치하지 않았다.
- T2: 리뷰가 지목한 생존 변이를 각각 잡는 테스트를 넣었다(아래 표). 기존 테스트 4건도 변이를 잡도록 고쳤다(한도 축소·경합 지연).
- 리포트 본문(`reports/M0-fix4.md`) 작성 후 다시 열어 끝까지 저장됐음을 확인했다.

변이-테스트 대응표:

| 변이 | 잡는 테스트 |
|---|---|
| 오래된 잠금 기준 5초→9초 | `test_stale_lock_cleaned` (잠금 나이=기준+1초, 경과 `< 2.0초`; 9초 변이는 약 3초 대기 후 실패) |
| SDK 클라이언트 생성 잠금 제거 | `test_sdk_client_single_under_threads` (생성자에 0.3초 지연, 잠금 없으면 8개 생성되어 실패) |
| 잠금 획득이 소유 토큰 미반환 | `test_acquire_returns_matching_owner_token` (파일 내용=반환값, 연속 획득 고유성) |
| 해제가 토큰 미확인 | `test_acquire_returns_matching_owner_token` (오답 토큰 해제 시 파일 유지) + 기존 `test_lock_release_checks_owner` |
| 상대 경로 `META_LEDGER_PATH` 허용 | `test_relative_ledger_path_refused_with_init` (INIT=1이어도, 파일이 있어도 거부) |
| `META_LEDGER_INIT=0` 허용 | `test_ledger_init_zero_refused` |
| `images_generate`·`models_list` 원장 방어 제거 | `test_ledger_guard_all_methods[images]`, `test_ledger_guard_all_methods[models]` (보너스로 responses·files_create·files_delete도 같은 테스트에서 고정) |
| 요청 해시에서 `extra` 제외 | `test_request_hash_includes_extra_metadata` (메타데이터 유무 해시 상이 + 고정값 `bc8f7f3f…`) |
| N1 우회 (`files_delete`가 없는 원장 생성) | `test_files_delete_does_not_create_missing_ledger` (리뷰 3절 재현 순서: 거부→삭제→여전히 거부) |

## 2. 생성·변경 파일

신규 1개(본 리포트), 수정 2개(지시서 파일 범위 내):

- `backend/app/meta/client.py`: N1 (`files_delete`에 `_require_ledger_ready`), N2 (가져온 잠금 재검증·복원·재시도). 공개 함수 이름·인자 무변경.
- `backend/tests/test_meta_client.py`: 신규 10건(N1 1건 + T2 9건, 가드 5개 parametrize 포함), 기존 8건 갱신(T1 스레드 한도 7건 + SDK 경합 지연·stale 한도 축소).
- `reports/M0-fix4.md`: 본 리포트.

편집 메모: 2개 파일은 CRLF라 LF로 바꾼 뒤 편집하고 CRLF로 복원했다. 최종 diff는 내용 변경만이다(`client.py` 44줄, 테스트 363줄).

## 3. 실행 명령과 결과

키 없이 실행(`Remove-Item Env:MODEL_API_KEY` 후). 실패 0.

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m0-fix4"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q
# 212 passed in 14.99s
cd $WT; & $PY tools\m0_spike.py --mode replay --probes all  # 9/9, 종료 코드 0
git checkout -- reports/M0-spike.json
& $PY tools\secret_scan.py                                  # secret_scan: clean, exit 0
```

- `tests/test_meta_client.py`만: 115 passed in 11.98s (기존 105 + 신규 10).
- 전체 스위트 212건 전부 통과, 전체 시간 15초로 60초 기준 이내. (M0-fix3 트리 200 passed + 1 xpassed에서 11건 증가: 신규 10건 + 본 트리에 병합된 main 쪽 1건. xpassed 표시 없이 전건 passed.)
- 변이 시뮬레이션(인라인 스크립트, 커밋 없음): 9초 기준으로 바꾸면 stale 획득에 3.02초(한도 2.0초라 테스트 실패), 생성 잠금을 빼면 8스레드에서 8개 생성(1개 단언 실패), stat-rename 사이 새 잠금 교체 시 N2가 새 잠금을 복원하고 한도까지 대기 후 거부. 모두 의도대로 잡힘을 확인했다.
- 재생 합계 `ledger_total=$0.3422 lines=53`은 본 트리 기준(main 병합분 포함)이며 내 실행 전후 `reports/cost_ledger.jsonl` 무변경이다. 재생 뒤 `reports/M0-spike.json`은 되돌렸고(`git status`로 범위 내 2개 파일 + 본 리포트만 변경 확인), `*.lock*` 잔재 없음.

## 4. Live API 호출

- 모델·횟수·비용: 없음. 0회, $0 (`reports/cost_ledger.jsonl` 무변경).
- 전부 가짜 전송 계층·재생 모드로 검증했다.

## 5. 열린 문제와 지시서·스펙에서의 이탈

이탈은 없고, 아래는 지시서가 값을 정하지 않아 해석한 부분이다(리뷰어 확인용):

- N1 방식 선택: "건너뛰거나(경고 1줄) 같은 방어로 거부" 중 거부를 택했다. 모든 live/record 메서드가 같은 검사를 쓰게 되어 일관되고, D11(상한 초과 후 정리)과 `cleanup_files` 경고-전용 동작은 그대로 유지된다. 명시 `ledger_path` 인자는 E7 설계대로 검사를 건너뛴다.
- N2 복원 경합: 복원 직전 `exists()` 확인과 `rename` 사이에는 좁은 틈이 남는다(POSIX에서 덮어쓰기 가능). 틈이 현실화될 확률은 무시할 수준으로 보고 두지 않았으며, 복원 실패 시에는 가져온 파일을 버리고(현재 보유자 우선) 한도 안에서 재시도한다.
- T1 범위: 즉시 끝나는 단위 테스트(`test_lock_release_checks_owner`, `test_release_lock_retries_permission_error`, 상수 단언)는 스레드가 없어 그대로 두었다. 그 외 잠금·회전 테스트 8건(`8x50`, 동시 예약, SDK 8스레드, stat/rename 한도, stale, 미래 시각, PermissionError 재시도)은 전부 데몬 스레드+`join(timeout)`+초과 실패로 바꿨다.
- T2 한도 수치: stale 정리 한도를 10.0초에서 2.0초로 좁혔다(정상 0.05초 내외, 9초 변이 약 3초). SDK 생성 지연은 0.3초(정상 전체 약 0.3초, 잠금 제거 변이에서 8개 생성 확정).
- 열린 문제: N2 복원은 단일 머신 잠금 기준이며 NFS 등 공유 파일시스템에서는 미검증이다. T1 한도 초과로 실패해도 데몬 스레드가 잠금 한도(15초)까지 백그라운드에서 돌 수 있으나 다음 테스트와 격리(tmp 분리)되어 있고 프로세스 종료 시 함께 끝난다.

## 6. 스펙 변경 제안 (specs/는 직접 고치지 않음)

- 제안 1 (에이전트 설계 또는 구현테스트계획 4-7): E7 원장 방어를 "모든 live/record 메서드의 공통 진입 검사"로 명시한다. 무료 메서드(`files_delete` 포함)도 예외가 아니며, 상한 초과 후 정리를 뜻하는 D11과는 직교한다(방어는 경로·존재만 보고 상한은 보지 않는다)는 점을 적는다.
- 제안 2 (에이전트 설계): 오래된 잠금 회수 시 "가져온 뒤 재검증(시각·내용) 후 삭제, 새 잠금이면 복원" 절차를 잠금 규격에 넣는다. 복원 실패 시 현재 보유자 우선·한도 내 재시도도 함께 명시한다.
- 제안 3 (구현테스트계획 테스트 기준): 잠금·회전 테스트는 작업 스레드를 `join(timeout)`으로 기다리고 초과 시 실패시키는 것을 기준으로 적는다. 테스트 라이브러리(`pytest-timeout` 등) 추가 없이 표준 스레드만으로 둔다.
