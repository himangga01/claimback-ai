# M2b 사건 흐름 화면(첫 화면)과 E2E (작업 지시서)

- 작성: 2026-11-03 12:35 KST, Claude / 2판 12:55 KST(교차 리뷰와 M3 리뷰 반영: 첫 화면 교체, 판독 박스, 진행 표시, 수정 장면, 가짜 서버 표시, 명칭 검사)
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\m2b-ui`(브랜치 `m2b-ui`, M3가 병합된 `main`에서 시작). 백엔드(M2a)는 나중에 시작하므로 약속 문서대로 응답하는 **가짜 서버**로 개발·시험합니다.
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `specs/case-api-contract.md`(v2), `specs/case-api-examples/*.json`, `specs/multi_agent_architecture.md`, 계획서 5장(3분 데모 흐름)·6장(고지 문구), `reports/M3-review.md`(기존 대시보드 문제)

## 목표

심사위원이 처음 보는 화면을 사건 흐름으로 바꿉니다. 샘플 사건 불러오기 → 에이전트 보드(4개 역할 에이전트, 단계별 모델·상태·지연·비용, 판독은 증거별 진행) → 체크포인트 1(증거 이미지 위 Spark 판독 박스, 사실 확인, 갚겠다는 말 강조) → 계산 단계(일부 변제 충당) → 문장별 초안 승인(초안 수정 시 G1a가 막는 장면) → 서류 패키지.

## 파일 범위

고쳐도 되는 파일:
- `frontend/index.html`(새 사건 흐름 화면으로 교체), 새 파일 `frontend/case.js`, `frontend/case.css`, `frontend/legacy-dashboard.html`(기존 `index.html`·`app.js`를 옮긴 것, 링크하지 않음)
- 같은 변경을 `docs/`(GitHub Pages 사본)에. `docs/`에서는 서버가 없으므로 "로컬 서버를 켜야 동작합니다. 데모 영상 보기" 안내만 보이고 가짜 결과를 보여 주지 않습니다.
- 새 폴더 `e2e/`, 새 파일 `requirements-dev.txt`(`playwright`, `pytest-playwright`, `uvicorn` 버전 고정), `.gitignore`(`e2e/artifacts/` 추가만)

건드리지 않는 파일: `backend/`, `sample_evidence/`, `README.md`, `requirements.txt`, `specs/`.

## 할 일

1. **첫 화면** `frontend/index.html` + `case.js` + `case.css`(바닐라 JS, 빌드 없음, **외부 CDN 없음**. 아이콘이 필요하면 인라인 SVG):
   - 상단: 제품 이름, 배지 "본인 작성용 초안, 법률 자문 아님"(이 문자열 그대로). 하단: `DISCLAIMER_KO` 원문 그대로(계획서 6장). 법정 저울 같은 법률 서비스 상징은 쓰지 않습니다.
   - 가짜 서버(`stub: true`)면 화면 위에 빨간 "STUB DATA" 띠, `meta_mode`가 `replay`면 작은 "재생" 배지.
   - 시작: "샘플 사건 불러오기"(`POST /api/cases/sample`). 파일 올리기는 작게, E2E 대상 아님. 올린 파일은 서버에 저장된다는 한 줄 안내와 "사건 삭제" 버튼(`DELETE`).
   - **에이전트 보드**: 4개 역할 에이전트 카드(Forensic Visual, Fact-Timeline Chronology, Financial Auditor, Judicial Form Filler) 아래에 하는 일을 한국어 한 줄로(예: "증거 읽기와 사실 정리"). 카드 안에 `steps[]`를 `group`별로: 담당 이름, 모델 배지, 상태, 지연(초), 비용. 판독은 `substeps`로 증거별 진행을 보여 줍니다. `skipped`는 흐리게 "이 버전에서는 사용하지 않음". `HOLD`는 `hold_reasons[].message`와 확인할 칸. `code: replay_fixture_missing`이면 "기록된 응답이 없는 입력입니다" 안내.
   - 실행 중 진행 표시: `POST /run`을 보낸 뒤 응답이 올 때까지 `GET /api/cases/{id}`를 0.5초마다 불러 보드를 갱신합니다.
   - **체크포인트 1**: 왼쪽 증거 목록(호증 번호 "갑 제N호증", SHA-256 앞 8자리, 상태)과 선택한 증거 이미지(`preview_url`), 그 위에 `GET /readings`의 박스를 겹쳐 그립니다(필드 근거 칩을 누르면 해당 증거로 이동하고 박스가 깜빡임). 오른쪽 필드 확인 표(값 수정 가능), 충돌·질문, 발화 목록(태그 표시 이름은 계약서 5장, 강조 체크박스), 증거 역할 선택(기본값 = `suggested_role`), 기준일(기본 2026-06-01). "확인하고 계속" → `PUT /facts` → `POST /run`.
   - **계산 보기**: 제목 "입력한 사실 기준 계산(기준일 YYYY. M. D.)". `allocations[]`(변제 충당: 이자 14,383원, 원본 985,617원, 남은 원금 4,014,383원)와 `calculation_steps[].formula`를 단계별로, 남은 원금과 기산일 강조.
   - **초안 승인**: 문장마다 `rendered_text`, 슬롯 보기 전환(`text_with_slots`의 `{{…}}`를 칩으로), 근거 태그, 검사 결과(`findings`를 `gate_results[].gate`별로 묶어 표시), 수정 칸과 승인 체크. 수정하면 `PUT /drafts`로 다시 검사하고, 지적이 있으면 승인 체크를 막습니다. `revisions[]`가 있으면 "문안 작성 ⇄ 검증 N회" 표시.
   - **서류 패키지**: 파일 링크, 전자소송 문구 칸마다 "복사" 버튼, 고지 문구.
   - 모든 상호작용 요소에 `data-testid`.
   - 화면 문구는 사실 묘사만. 기존 대시보드의 문구(원고/피고, Debt Promise, Integrity Verified, Confidence %, "준수", "1:1", 우체국 표준)를 옮기지 않습니다.
2. **기존 화면 정리**: 기존 `index.html`·`app.js`를 `legacy-dashboard.html`(+`legacy-dashboard.js`)로 옮기고 맨 위에 "이전 정적 시안. 실제 결과가 아님" 띠를 붙입니다. 어디에서도 링크하지 않습니다. `docs/`도 같게.
3. **가짜 서버** `e2e/stub_server.py`(FastAPI): `specs/case-api-examples/*.json`만 읽어 돌려주고 `stub: true`를 붙입니다. 상태 진행(`INTAKE` → `CHECKPOINT_1` → `DRAFT_APPROVAL` → `CHECKPOINT_2`)과 단계 지연(단계당 0.3초)을 흉내 냅니다. 증거 파일은 `sample_evidence/kr/`에서 읽습니다. **`backend/tests/golden/`은 읽지 않습니다.** `PUT /drafts`에서 수정 문장에 숫자·"만 원"이 있으면 G1a 지적을 돌려주는 단순 규칙을 둡니다(실제 백엔드는 M1-fix1의 G1a).
4. **E2E** `e2e/test_case_flow.py`(pytest + Playwright, Chromium, 화면 1920×1080):
   - 대상은 환경 변수 `E2E_BASE_URL`, 없으면 테스트가 가짜 서버를 스레드 안 `uvicorn.Server`로 `127.0.0.1`의 빈 포트에 띄우고 끝나면 `should_exit`로 끕니다.
   - 흐름: 샘플 불러오기 → 보드 단계 표시 → 체크포인트 1에서 판독 박스 1개 이상 보임 → 고정 입력 규칙(계약서 5장: 첫 `repay_promise` 강조, 역할 = 제안값, 기준일 2026-06-01)대로 확인 → 계산에 "4,014,383" → 문장 하나를 "500만 원을 보냈습니다."로 고치면 G1a 지적과 승인 막힘 → 되돌리면 통과 → 모두 승인 → 패키지에서 내용증명 링크, `claim_purpose`에 "2026. 5. 2.", "복사" 버튼 → 사건 삭제.
   - 단계마다 화면 전체 스크린샷을 `e2e/artifacts/`(git 제외)에 저장.
   - 단계마다 화면 글자(`page.inner_text("body")`)를 `backend/app/services/naming.py`의 검사 함수로 확인해 금지 명칭 0건(고지 문구 허용 목록 적용).
   - 가짜 서버 대상이면 "STUB DATA" 띠가 보여야 하고, 실제 서버 대상이면 보이지 않아야 합니다(나중에 M2a 백엔드에 같은 테스트를 그대로 돌림).
5. 설치: `requirements-dev.txt`를 루트 `.venv`에 설치하고 `python -m playwright install chromium`(크기가 크면 `--only-shell` 시도). 설치 명령과 결과를 리포트에 적습니다.
6. 리포트 `reports/M2b.md`(AGENTS.md 형식, 끝까지 저장 확인): 화면 흐름, 스크린샷 목록, 약속과 다르게 만든 부분.

## 하지 않을 일

- 백엔드 구현(M2a), 미국 트랙, Meta API 호출, `specs/` 수정, `.env` 읽기·만들기, 커밋과 푸시

## 완료 기준

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m2b-ui"
cd $WT
& $PY -m pytest -q e2e                       # failed 0 (가짜 서버 대상)
& $PY tools\secret_scan.py                   # 종료 코드 0
(Get-ChildItem e2e\artifacts\*.png).Count    # 8장 이상
Select-String -Path frontend\index.html,frontend\case.js -Pattern 'cdn.','unpkg','jsdelivr' -SimpleMatch   # 0건
```
