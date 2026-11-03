# M2b 사건 흐름 화면과 E2E (작업 지시서)

- 작성: 2026-11-03 12:35 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\m2b-ui`(브랜치 `m2b-ui`). M2a(백엔드)와 동시에 진행합니다. 백엔드가 아직 없으므로 약속 문서대로 응답하는 **가짜 서버**로 개발·시험합니다.
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `specs/case-api-contract.md`, `specs/multi_agent_architecture.md`(4개 역할 에이전트 묶음), 계획서 5장(3분 데모 흐름)·6장(고지 문구)
- 참조: 에이전트 설계 5장(에이전트 보드)

## 목표

심사위원이 3분 데모에서 볼 사건 화면을 만듭니다. 샘플 사건 불러오기 → 에이전트 보드(4개 역할 에이전트 아래 담당 단계, 모델 배지, 상태) → 체크포인트 1(사실 확인, 강조 발화 선택) → 계산 단계 보기 → 문장별 초안 승인 → 서류 패키지(내용증명 PDF, 전자소송 붙여넣기 문구)까지.

## 파일 범위

고쳐도 되는 파일: 새 파일 `frontend/case.html`, `frontend/case.js`, `frontend/case.css`, `frontend/index.html`(사건 화면으로 가는 링크 한 줄만), 새 폴더 `e2e/`(가짜 서버, 가짜 데이터, Playwright 테스트), 새 파일 `requirements-dev.txt`(`playwright`, `pytest-playwright` 버전 고정), `.gitignore`(`e2e/artifacts/` 추가만).
건드리지 않는 파일: `backend/`, `docs/`(GitHub Pages 사본은 M6에서 정함), `sample_evidence/`, `README.md`, `requirements.txt`.

## 할 일

1. **화면** `frontend/case.html` + `case.js`(바닐라 JS, 빌드 없음, 외부 라이브러리는 버전 고정 CDN만):
   - 상단: 제품 이름, "본인 작성용 초안, 법률 자문 아님" 배지. 하단: 계획서 6장 `DISCLAIMER_KO` 원문 그대로.
   - 시작: "샘플 사건 불러오기"(`POST /api/cases/sample`)와 파일 올리기(`POST /api/cases`, `/evidence`).
   - **에이전트 보드**: 4개 역할 에이전트(Forensic Visual, Fact-Timeline Chronology, Financial Auditor, Judicial Form Filler) 카드 아래에 `steps[]`를 `group`별로 보여 줍니다. 단계마다 이름, 모델 배지(`muse-spark-1.3`, `sam-3.1`, 규칙), 상태(대기·작업 중·완료·보류·건너뜀), 비용. `skipped` 단계는 흐리게 "다음 단계에서 연결" 표시. `HOLD`면 이유와 확인할 칸을 보여 줍니다.
   - **체크포인트 1**: 왼쪽 증거 이미지 목록, 오른쪽 필드 확인 표(값 수정 가능, 근거 칩 `EX1·item3`을 누르면 그 증거로 이동), 충돌·질문 표시, 발화 목록(태그 표시, 강조할 발화 체크박스), 증거 역할(대여 이체·변제·기타) 선택, 기준일 입력. "확인하고 계속" → `PUT /facts` → `POST /run`.
   - **계산 보기**: `calculation.calculation_steps[]`를 수식 그대로 단계별로(데모의 일부 변제 충당 장면), 남은 원금과 기산일 강조.
   - **초안 승인**: 문장마다 `rendered_text`, 근거 태그, 검사 결과(`findings`), 승인 체크와 수정(수정하면 다시 검사). 모두 승인하면 다음.
   - **서류 패키지**: 파일 다운로드 링크, 전자소송 문구 칸마다 "복사" 버튼, 고지 문구.
   - 화면 문구는 사실 묘사만. `naming.py` 금지어(M1 지시서 목록)를 쓰지 않습니다.
2. **가짜 서버** `e2e/stub_server.py`(FastAPI): `specs/case-api-contract.md` 모양 그대로의 응답을 `e2e/stub_data/*.json`에서 돌려주고 `frontend/`도 함께 서빙합니다. 상태 진행(INTAKE → CHECKPOINT_1 → … → CHECKPOINT_2)을 흉내 냅니다. 샘플 증거 이미지는 `sample_evidence/kr/`에서 읽어 줍니다(정답 데이터는 쓰지 않음). 가짜 데이터의 계산값은 고정 예시(남은 원금 4,014,383원, 기산일 2026-05-02)를 씁니다.
3. **E2E** `e2e/test_case_flow.py`(pytest + Playwright, Chromium): 환경 변수 `E2E_BASE_URL`(기본: 테스트가 띄운 가짜 서버)로 대상을 바꿀 수 있게 합니다. 샘플 불러오기 → 보드에 단계 표시 → 체크포인트 1에서 값 확인·강조 발화 1개 선택 → 계산 단계에 "4,014,383" 표시 → 문장 모두 승인 → 패키지에서 내용증명 링크와 "복사" 버튼 확인. 스크린샷을 `e2e/artifacts/`(git 제외)에 단계별로 저장합니다(리뷰어가 화면을 봄).
4. 설치: `requirements-dev.txt`를 루트 `.venv`에 설치하고 `python -m playwright install chromium`. 설치 명령과 결과를 리포트에 적습니다.
5. 리포트 `reports/M2b.md`(AGENTS.md 형식): 화면 흐름, 스크린샷 목록, 약속 문서와 다르게 만든 부분. 리포트는 한 번에 끝까지 쓰고 다시 열어 끝까지 저장됐는지 확인합니다.

## 하지 않을 일

- 백엔드 구현(M2a), 기존 대시보드(`index.html`) 재구성, `docs/` 사본, 미국 트랙
- Meta API 호출, `specs/` 수정, `.env` 읽기·만들기, 커밋과 푸시

## 완료 기준

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m2b-ui"
cd $WT
& $PY -m pytest -q e2e                       # failed 0 (가짜 서버 대상)
& $PY tools\secret_scan.py                   # 종료 코드 0
Get-ChildItem e2e\artifacts\*.png | Measure-Object | Select-Object -ExpandProperty Count   # 단계별 스크린샷 5장 이상
Select-String -Path frontend\case.* -Pattern '변호사','법무사','lawyer','attorney','승소','채무 인정' -SimpleMatch   # 0건(고지 문구 원문 안의 단어는 리포트에 표시)
```
