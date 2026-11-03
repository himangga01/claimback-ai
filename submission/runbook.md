# 데모 녹화 런북

- 작성: 2026-11-03 18:14 KST, Claude. 녹화와 제출은 사용자가 합니다.
- 대본: `submission/demo-script.md`. 제출 메모: `submission/submission-notes.md`.
- 마감: 2026-11-04 21:00 ET = 2026-11-05 11:00 KST(늦은 제출 불가). 목표 11-05 07:00 KST 전.

## 1. 준비 (녹화 30분 전)

1. 최신 `main`을 받습니다: `git -C C:\2026_project\claimback-ai-meta pull`
2. 키 없이 테스트가 통과하는지 확인합니다.

```powershell
cd C:\2026_project\claimback-ai-meta\backend
..\.venv\Scripts\python.exe -m pytest -q
```

3. 결제 화면에서 남은 크레딧이 $1 이상인지 봅니다(실호출 장면 1회 약 $0.2~0.3).
4. 화면 1920×1080, 브라우저 확대 100%, 알림 끄기, 다른 탭 닫기.

## 2. 리허설 (재생 모드, 비용 0)

```powershell
cd C:\2026_project\claimback-ai-meta\backend
$env:META_MODE = "replay"
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

브라우저에서 `http://127.0.0.1:8000` → **샘플 사건 불러오기**(누르면 바로 실행됩니다). 대본 장면 순서대로 한 번 끝까지 갑니다. 끝나면 **사건 삭제**.

영어 화면으로 찍으려면 `http://127.0.0.1:8000/?lang=en`을 열거나 머리말의 **EN**을 누릅니다(버튼은 **Load the sample case**, 보드 머리는 "Meta model calls: N · $… · (replay)"). 증거 원문과 서류 본문은 한국 법원에 내는 것이라 영어 화면에서도 한국어로 나옵니다. 사건 진행 중에 언어를 바꿔도 입력한 값은 남습니다.

확인할 화면:

- 보드 머리 "Meta 모델 호출 N회 · $… · (재생)"
- 체크포인트 1: 증거 목록에서 **갑 제4호증**(송금확인증)을 눌러 판독 박스를 보여 줌(세로로 긴 대화 캡처보다 박스가 정확함)
- 가림 미리보기: 원본과 가린 사본이 위아래(재기록된 샘플에서는 "확인 필요" 없음, INT-3 리포트)
- 초안 승인: 문장 하나의 `{{principal}}` 자리에 "500만 원"을 넣고 다시 검사 → G1a가 막는 장면 → 되돌리기 → 모두 승인
- 패키지: 내용증명·갑호증·증거목록 링크, 청구취지 복사 단추, 최종 서류 검사 "✓ 통과"

## 3. 본 녹화

- 대부분의 장면은 재생 모드로 녹화합니다(같은 결과가 나와 다시 찍기 쉬움).
- 실호출 장면 한 번(대본 0:35~1:05 판독 장면)은 서버를 실호출로 다시 띄워 찍습니다. 화면에 "(재생)" 표시가 없어야 합니다.

```powershell
# 새 PowerShell 창에서. 키 값은 화면에 보이지 않게 사용자 환경 변수에서만 읽습니다.
cd C:\2026_project\claimback-ai-meta\backend
$env:META_MODE = "live"
$env:MODEL_API_KEY = [Environment]::GetEnvironmentVariable('MODEL_API_KEY','User')
$env:META_LEDGER_PATH = "C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl"
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- 실호출 판독은 약 80초가 걸립니다(18:25 실호출 확인, `reports/M7-live-check.md`). 대기 장면은 편집에서 줄입니다.
- 실호출에서는 판독이 이름을 증거마다 다르게 읽어 확인 화면에 이름 충돌 질문이 뜰 수 있습니다. 실호출 장면은 판독 보드까지만 찍고, 확인 화면부터는 재생 모드 녹화를 씁니다.
- 녹화가 끝나면 **사건 삭제**를 누르고 서버를 끕니다(Ctrl+C). 키를 쓴 창은 닫습니다.

## 4. 녹화 뒤

1. 영상 길이 3분 이하, 대회 기간에 만든 기능만 나왔는지, 화면에 키·계정 정보가 없는지 확인합니다.
2. 영상 링크를 `submission/submission-notes.md`와 제출 양식에 넣습니다.
3. 실호출로 늘어난 `reports/cost_ledger.jsonl`은 커밋해도 됩니다(비용 기록만 있고 비밀값 없음).

## 5. 문제가 생기면

| 증상 | 할 일 |
|---|---|
| 화면이 HOLD "replay_fixture_missing" | 재생 모드인데 샘플 증거나 코드가 기록과 달라진 것. `git status`로 바뀐 파일 확인, `main`으로 되돌림 |
| HOLD "budget_exceeded" | 실호출 상한. `$env:META_RUN_CAP_USD = "3"` 후 서버 재시작 |
| HOLD "config_missing_key" 또는 판독 전부 실패 | 실호출 창에 `MODEL_API_KEY`가 비어 있음. 위 명령으로 다시 설정 |
| 원장 오류 "ledger missing" | `META_LEDGER_PATH`가 절대 경로인지 확인. 새 파일이면 `$env:META_LEDGER_INIT = "1"` |
| 가림 "확인 필요"(실호출에서 판독 상자가 달라졌을 때) | 그 증거는 갑호증에서 빠짐. 가림 장면은 재생 모드로 찍음 |
