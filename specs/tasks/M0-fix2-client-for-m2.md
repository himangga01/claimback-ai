# M0-fix2 Meta 클라이언트: M2 연결 전 보강 (수정 지시서)

- 작성: 2026-11-03 12:50 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\m0-fix2`(브랜치 `m0-fix2`, M0-fix1·M1·M3가 병합된 `main`에서 시작). **Meta 실호출 없음.**
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `reports/M0-fix1-review.md`(D1~D8)
- 배경: M0-fix1 교차 리뷰에서 M2a(사건 백엔드)가 실호출을 기록하기 전에 고쳐야 할 결함이 나왔습니다.

## 파일 범위

고쳐도 되는 파일: `backend/app/meta/`(전부), `backend/tests/test_meta_client.py`, `tools/m0_spike.py`(원장 합계 부분만), `.gitignore`.
건드리지 않는 파일: 그 밖 전부.

## 할 일

1. **D1 파일 자동 삭제 시점**: 응답 직후 자동 삭제를 없애고, 호출자가 마지막 시도 뒤에 부르는 `cleanup_files(file_ids)`로 바꿉니다(실패는 경고). 끊긴 응답으로 재시도할 때 같은 `file_id`를 다시 쓸 수 있어야 합니다. 주석에 "PDF·이미지는 인라인 `file_data`/`image_url` 권장(M0 P3에서 동작 확인)"을 적습니다.
2. **D2 예약 줄이 확정되지 않음**: 키 확인과 전송 계층 생성을 예약 **전**에 합니다. 요청을 보낸 뒤 생긴 모든 예외(응답 해석 실패 `ValueError`·`ValidationError`·`JSONDecodeError` 포함)는 `failed` 줄로 확정한 뒤 다시 던집니다.
3. **D3 원장 합계 공개 함수**: `ledger_summary(run_id_prefix: str | None = None) -> { total_usd, by_run_id: {...}, by_status: {...} }`(예약은 확정 줄과 상쇄, 미확정 예약은 포함)를 공개하고, `m0_spike.py`의 단순 합산을 이것으로 바꿉니다. 재생 모드는 원장을 쓰지 않으므로, 재생에서도 비용을 보여 줄 수 있게 응답 usage와 단가로 비용을 계산하는 공개 함수 `estimate_cost_from_body(model, endpoint, body)`를 둡니다.
4. **D4 원장 경로 하나로**: 환경 변수 `META_LEDGER_PATH`(없으면 지금처럼 저장소 `reports/cost_ledger.jsonl`)를 읽습니다. 잠금 파일은 원장 옆에 둡니다. 작업 트리가 여러 개여도 같은 절대 경로를 쓰면 누적 상한이 한 원장으로 걸립니다.
5. **D5 Windows 잠금**: 오래된 잠금 판정 시간을 기다림 한도보다 짧게(예: 오래된 잠금 5초, 기다림 15초). 프로세스 안 `RLock`을 잡은 채 파일 잠금을 오래 기다리지 않게 순서를 정리합니다. 잠금 파일 삭제 실패는 다시 시도합니다. `BudgetLedgerError`를 `BudgetExceeded`의 하위 클래스로(또는 둘의 공통 부모 `BudgetError`를 두어) 호출자가 한 번에 잡을 수 있게 합니다. `.gitignore`에 `*.lock`.
6. **D6 SAM 이미지 `file_id`**: SAM 호출에서 `frame_count` 필수는 **영상**일 때만 적용합니다(이미지 `input_file`은 이미지 단가).
7. **D7 연결 재사용**: OpenAI SDK 클라이언트를 `MetaClient` 인스턴스(또는 모듈)에서 한 번 만들어 재사용하고, 닫는 함수(`close()`)를 둡니다.
7a. **D9 `extra` 허용 목록**: 금지 키 목록 대신 `extra`에는 `metadata`만 허용합니다(`extra_body`, `instructions` 등은 거부). 해시 구성은 바꾸지 않습니다(기존 fixture의 `extra`는 `metadata`만 씀 — 확인해서 리포트에).
7b. **D10 상한 값 해석**: `META_RUN_CAP_USD`·`META_TOTAL_CAP_USD`가 숫자가 아니거나(예: `"20usd"`), 음수거나, 무한대면 오류를 냅니다. `"0"`은 0으로 존중(모든 실호출 거부).
7c. **D11 원장**: `reports/cost_ledger.jsonl`의 git 추적은 유지하되(제출용 비용 기록), 실행 중 쓰는 원장은 `META_LEDGER_PATH`로 한 곳에 모읍니다. `files_delete`는 예산 검사 없이 동작합니다(상한을 넘은 뒤에도 정리는 되게). 오래된 잠금 정리는 원자적으로(잠금 파일 이름을 바꾼 뒤 지우기 등) 하고, 미래 시각 mtime도 오래된 것으로 봅니다. Windows에서 삭제 대기 중 `PermissionError`는 재시도.
8. 테스트: 위 항목마다 장치를 깨면 실패하는 테스트(가짜 전송 계층, 가짜 키만). M0-fix1 망가뜨리기 시험에서 테스트가 놓친 5가지를 잡는 테스트를 더합니다: 원장 읽기 `OSError` → 거부, 한글만 있는 문자열의 토큰 추정(글자당 1 이상), `META_RUN_CAP_USD` 환경 변수 반영, 실패 경로의 파일 정리 여부, 잠금 없이는 실패하는 느린 읽기 동시성 테스트. `time.sleep` 패치는 재시도 대기에만 적용되게 범위를 좁혀(동시성 테스트의 대기가 실제로 돌게). 끊긴 응답 → 같은 `file_id`로 재시도 성공, 해석 실패 후 `failed` 줄, `ledger_summary` 접두사 합계와 예약 상쇄, `META_LEDGER_PATH`, 오래된 잠금 5초 정리, `BudgetError` 한 번에 잡기, SAM 이미지 `file_id`.
9. 리포트 `reports/M0-fix2.md`(AGENTS.md 형식, 끝까지 저장 확인).

## 주의

- 요청 해시 구성과 계산 방식은 바꾸지 않습니다(기존 fixture 유지).
- `run_id`는 계속 live·record에서 필수입니다. M2a는 `run_id`로 사건 ID 하나를 씁니다(사건 전체에 실행당 상한).

## 완료 기준

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m0-fix2"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q                       # failed 0
cd $WT; & $PY tools\m0_spike.py --mode replay --probes all  # 9/9
git checkout -- reports/M0-spike.json                       # 재생이 바꾼 경로 되돌림
& $PY tools\secret_scan.py                                  # 0
```
