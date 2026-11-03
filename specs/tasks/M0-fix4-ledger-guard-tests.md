# M0-fix4 원장 방어 빈틈·변이 테스트 (수정 지시서)

- 작성: 2026-11-03 14:25 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\m0-fix4`(브랜치 `m0-fix4`, `m0-fix3` 커밋 f1b5900에서 시작). INT-2와 동시에 진행합니다. **Meta 실호출 없음.**
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `reports/M0-fix3.md`, `reports/M0-fix3-review.md`(N1·N2·T1·T2)
- 배경: M0-fix3의 원장 누락 방어를 `files_delete`가 우회합니다. 변이 시험에서 테스트가 놓친 변이도 몇 개 남았습니다.

## 파일 범위

고쳐도 되는 파일: `backend/app/meta/client.py`, `backend/tests/test_meta_client.py`. 그 밖은 건드리지 않습니다. 공개 함수 이름·인자는 바꾸지 않습니다(INT-2·M4가 쓰는 중).

## 할 일

1. **N1(중간)** 무료 호출이 없는 원장을 만들지 못하게 합니다. `files_delete`(그리고 원장에 쓰는 다른 무료 경로가 있으면 그것도)는 원장 파일이 없고 `META_LEDGER_INIT=1`도 아니면 원장 기록을 건너뛰거나(경고 1줄) 같은 방어로 거부합니다. 어느 쪽이든 그 뒤 `responses_create`가 여전히 거부되는 테스트를 넣습니다(리뷰 3절 재현 순서 그대로).
2. **N2(낮음)** 오래된 잠금을 이름 바꿔 가져온 뒤, 가져온 파일의 시각·내용을 다시 보고 실제로 오래된 것일 때만 지웁니다. 아니면 되돌리거나 포기하고 재시도합니다.
3. **T1** 잠금·회전 관련 테스트마다 시간 한도를 둡니다(작업 스레드를 `join(timeout)`으로 기다리고 넘으면 실패). `pytest-timeout`은 새로 설치하지 않습니다.
4. **T2** 아래 변이를 각각 잡는 테스트를 더합니다.
   - 오래된 잠금 기준을 5초에서 9초로 바꾸면 실패(오래된 잠금 정리 시험의 한도를 기준+여유로 좁힘).
   - SDK 클라이언트 생성 잠금을 없애면 실패(생성 함수에 일부러 지연을 넣은 가짜로 경합을 만듦).
   - 잠금 획득이 소유 토큰을 돌려주지 않거나, 해제가 토큰을 확인하지 않으면 실패.
   - 상대 경로 `META_LEDGER_PATH`, `META_LEDGER_INIT=0`을 받아들이면 실패.
   - `images_generate`·`models_list`에서 원장 방어를 빼면 실패.
   - 요청 해시에서 `extra`(메타데이터)를 빼면 실패(메타데이터가 있는 요청의 해시 고정).
5. 리포트 `reports/M0-fix4.md`(AGENTS.md 형식, 끝까지 저장 확인): 고친 것, 각 변이를 잡는 테스트 이름.

## 완료 기준

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m0-fix4"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q                       # failed 0, 전체 시간 60초 이내
cd $WT; & $PY tools\m0_spike.py --mode replay --probes all  # 9/9, 종료 코드 0
git checkout -- reports/M0-spike.json
& $PY tools\secret_scan.py                                  # 0
```
