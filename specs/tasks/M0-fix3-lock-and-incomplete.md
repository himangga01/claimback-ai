# M0-fix3 Windows 잠금 재시도·끊긴 응답 비용 (수정 지시서)

- 작성: 2026-11-03 13:23 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\m0-fix3`(브랜치 `m0-fix3`, M0-fix2가 병합된 `main`에서 시작). M2a·M1-fix2·M2b-fix1과 동시에 진행합니다. **Meta 실호출 없음.**
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `reports/M0-fix2-review.md`(E1~E6)
- 배경: M2a가 실호출을 기록하기 전에, Windows에서 동시 호출 때 이미 과금된 응답을 잃을 수 있는 잠금 결함을 고칩니다.

## 파일 범위

고쳐도 되는 파일: `backend/app/meta/`(전부), `backend/tests/test_meta_client.py`, `tools/m0_spike.py`(종료 코드만). 그 밖은 건드리지 않습니다. 공개 함수 이름·인자는 바꾸지 않습니다(M2a가 쓰는 중).

## 할 일

1. **E1(차단)** 잠금 파일을 만들 때 Windows의 `PermissionError`(삭제 대기 중인 이전 잠금 파일)를 `FileExistsError`처럼 다루어, 짧게 쉬고(예: 20ms) 기다림 한도(15초)까지 재시도합니다. 과금된 응답을 원장에 확정 기록하는 단계는 잠금을 못 얻어도 한도까지 재시도하고, 그래도 실패하면 응답·fixture는 먼저 저장하고 원장 미기록 사실을 경고로 남깁니다(응답을 버리지 않음).
2. **E2** 오래된 잠금의 이름 바꾸기·`stat` 실패 경로에서도 한도 확인과 짧은 쉼(20ms)을 넣어, 한도를 넘겨 CPU를 돌리지 않게 합니다.
3. **E3** 공유 `MetaClient`의 SDK 클라이언트 생성을 잠금으로 보호해 하나만 만들고, `close()`가 그 하나를 닫게 합니다.
4. **E4** `IncompleteResponse`에 응답 `body`(또는 usage)를 담아, 재생에서도 끊긴 시도의 비용을 `estimate_cost_from_body`로 계산할 수 있게 합니다.
5. **E6 사소** 잠금 해제 때 자기 잠금인지 확인(잠금 파일에 소유 토큰 기록), `estimate_cost_from_body`의 SAM 이미지 수·입력 0 처리를 실호출 기록과 같게, `Box`·`box_to_pixels`를 `app.meta`에서 내보내기, `ledger_summary`는 잠금 없이 읽기 전용으로(파일을 읽기만 하고 부분 줄은 무시하지 않고 오류).
5a. **E7(망가뜨리기 시험) 원장이 없으면 $0**: live·record 모드에서는 `META_LEDGER_PATH`가 절대 경로여야 하고, 그 파일이 없으면 "새 원장을 만들겠다"는 명시 설정(`META_LEDGER_INIT=1`) 없이는 호출을 거부합니다(오타·상대 경로로 지난 사용액이 0이 되는 것 방지). 기본 저장소 경로를 쓸 때도 파일이 있어야 합니다.
5b. **E8** `images_generate`에도 D2(키 확인·전송 계층 생성을 예약 전에, 실패는 `failed` 줄)를 적용하고 테스트를 더합니다. 오래된 잠금 정리 테스트에 시간 한도를 두고, 요청 해시 고정 테스트(알려진 요청 → 알려진 해시)를 `test_meta_client.py`에 넣습니다. `tools/m0_spike.py`는 실패한 프로브가 있으면 종료 코드 1(이 파일은 종료 코드 부분만 수정 허용).
6. 테스트: 동시 스레드(8개) × 호출 50회에서 잠금 오류 0건(가짜 `PermissionError`를 주입하는 테스트 포함), 오래된 잠금 정리 중 CPU가 한도 안에서 멈춤, SDK 클라이언트 1개, `IncompleteResponse.body`로 비용 계산.
7. 리포트 `reports/M0-fix3.md`(AGENTS.md 형식, 끝까지 저장 확인).

## 완료 기준

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m0-fix3"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q                       # failed 0
cd $WT; & $PY tools\m0_spike.py --mode replay --probes all  # 9/9
git checkout -- reports/M0-spike.json
& $PY tools\secret_scan.py                                  # 0
```
