# M2b 리포트: 사건 흐름 화면(첫 화면)과 E2E

- 작성: 2026-11-03, Muse Code (`muse-spark-1.3`)
- 작업 트리: `C:\2026_project\claimback-wt\m2b-ui` (브랜치 `m2b-ui`)

## 1. 지시서와 한 일

- 지시서: `specs/tasks/M2b-case-ui-e2e.md` (2판, 가짜 서버로 개발·시험)
- 읽은 문서: `AGENTS.md`, 지시서, `specs/case-api-contract.md`(v2),
  `specs/case-api-examples/*.json` 6종, `specs/multi_agent_architecture.md`,
  계획서 5장(3분 데모 흐름)·6장(고지 문구), `reports/M3-review.md`(S12 기존 대시보드 문제).
- 한 일: 첫 화면을 사건 흐름 화면으로 교체하고, 약속 문서대로 응답하는 가짜
  서버와 E2E 테스트를 만들어 지시서의 흐름을 끝까지 돌렸다.
- 화면 흐름: 샘플 사건 불러오기 → 에이전트 보드(4개 역할 + 사용자 확인,
  단계별 담당·모델·상태·지연·비용, 판독은 증거별 `substeps`) → 체크포인트 1
  (증거 목록·이미지 위 Spark 판독 박스, 근거 칩 클릭 시 해당 증거로 이동·박스
  깜빡임, 필드 확인·충돌·질문·발화 강조·증거 역할·기준일) → 계산 보기
  (변제 충당과 계산 단계) → 문장별 초안 승인(슬롯 보기 전환, 게이트별 검사
  결과, 수정 시 재검사, 지적이 있으면 승인 차단, 수정 장면) → 서류 패키지
  (파일 링크, 전자소송 복사 블록, 고지 문구) → 사건 삭제.
- `POST /run` 실행 중에는 0.5초마다 `GET /api/cases/{id}`로 보드를 갱신하고
  "실행 중…" 표시를 낸다. `stub: true`면 빨간 "STUB DATA" 띠,
  `meta_mode == replay`면 "재생" 배지를 보여 준다.

## 2. 만들거나 고친 파일

- `frontend/index.html` — 새 사건 흐름 화면으로 교체 (바닐라, 외부 참조 없음).
- `frontend/case.js` — 화면 동작 (신규).
- `frontend/case.css` — 화면 스타일 (신규, 시스템 글꼴만).
- `frontend/legacy-dashboard.html` — 기존 `index.html`을 옮긴 것. 맨 위에
  "이전 정적 시안. 실제 결과가 아님" 띠, 스크립트 참조를
  `legacy-dashboard.js`로 변경. 어디에서도 링크하지 않음.
- `frontend/legacy-dashboard.js` — 기존 `app.js`를 옮긴 것
  (기존 `frontend/app.js`는 이동 후 삭제). `frontend/styles.css`는 기존 화면용으로 그대로 둠.
- `docs/` — 위 5종을 그대로 미러 (`index.html`, `case.js`, `case.css`,
  `legacy-dashboard.html`, `legacy-dashboard.js`; 기존 `docs/app.js`는 이동 후
  삭제). 서버가 없으면 "로컬 서버를 켜야 동작합니다. 데모 영상 보기" 안내만
  보이고 가짜 결과를 보여 주지 않는다 (서버 확인 실패 시 `#app` 숨김).
- `e2e/stub_server.py` — 가짜 서버(FastAPI, 신규). 예시 JSON만 읽어
  `stub: true`를 붙여 돌려주고, 상태 진행과 단계당 0.3초 지연을 흉내 낸다.
  `PUT /drafts`에는 단순 G1a 규칙(슬롯·근거 표시 밖의 숫자·"만 원" 지적)을 둔다.
  `backend/tests/golden/`은 읽지 않는다.
- `e2e/test_case_flow.py` — E2E(pytest + Playwright, Chromium, 1920×1080, 신규).
- `requirements-dev.txt` — `playwright==1.64.1`, `pytest-playwright==0.10.0`,
  `uvicorn==0.54.0` (신규, 버전 고정).
- `.gitignore` — `e2e/artifacts/` 한 줄 추가.
- 건드리지 않음: `backend/`, `sample_evidence/`, `README.md`,
  `requirements.txt`, `specs/`, `AGENTS.md`, `docs/analysis/`,
  `docs/code-analysis.md`, 다른 리포트.

## 3. 실행한 명령과 결과

작업 트리 `C:\2026_project\claimback-wt\m2b-ui`에서, Python은
`C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe`만 사용 (새 venv 없음).

- 설치 (공유 venv에 설치, 설치 전 해당 3종 없음):
  `& $PY -m pip install -r requirements-dev.txt` →
  `playwright-1.64.1`, `pytest-playwright-0.10.0`, `uvicorn-0.54.0` 설치 성공
  (함께 들어온 의존성: `click-8.5.0`, `greenlet-3.5.6`, `pyee-14.0.0`,
  `python-slugify-9.1.3`, `text-unidecode-1.3`).
  `& $PY -m playwright install chromium` → 종료 코드 0 (전체 브라우저 설치,
  `--only-shell` 불필요).
- 완료 기준 (지시서 그대로):
  - `& $PY -m pytest -q e2e` → `1 passed` (failed 0, 가짜 서버 자동 기동,
    약 8초). `E2E_BASE_URL`을 주면 그 서버를 대상으로 같은 테스트를 돌린다.
  - `& $PY tools\secret_scan.py` → `secret_scan: clean`, 종료 코드 0.
  - `(Get-ChildItem e2e\artifacts\*.png).Count` → 10 (8장 이상).
    스크린샷 10장은 해시가 모두 다르다 (중복 없음):
    `01-board`, `02-checkpoint-evidence`(EX4 선택),
    `03-checkpoint-filled`, `04-calculation`, `05-drafts`(s1 슬롯 보기),
    `06-g1a-blocked`, `07-drafts-fixed`, `08-drafts-approved`,
    `09-package`, `10-deleted`.
  - `Select-String -Path frontend\index.html,frontend\case.js -Pattern
    'cdn.','unpkg','jsdelivr' -SimpleMatch` → 0건.
- 추가 확인:
  - 단계마다 `page.inner_text("body")`를
    `backend/app/services/naming.py`의 `check_text`로 검사 → 10단계 모두 0건.
  - 새 화면에서 `legacy-dashboard` 참조 0건, 기존 대시보드 문구
    (원고/피고, Debt Promise, Integrity Verified, Confidence, 준수, 1:1,
    우체국) 0건.
  - `frontend/`와 `docs/`의 5종 파일 해시 일치.
  - 스크린샷 육안 확인: STUB DATA 띠·재생 배지·고지 배지, 에이전트 보드,
    이체증 위 판독 박스 4개, 계산(남은 원금 4,014,383원, 기산일 2026. 5. 2.),
    초안 승인, 패키지(내용증명 링크·복사 버튼·고지 문구).

## 4. 실호출 (Meta API)

- 없음. 이 과제는 실호출 없이 가짜 서버 대상으로만 시험했다.
  (`reports/cost_ledger.jsonl`에 새 항목 없음.)

## 5. 열린 문제와 지시서·약속과의 차이

- 차이 없음이 목표였고, 지시서·약속 문서와 다르게 만든 부분은 아래 경미한
  판단 3건뿐이다:
  1. 에이전트 보드에 계약서 `group == "User"` 단계(사용자 확인·문장 승인·
     최종 확인)를 "사용자 확인" 칸으로 함께 보여 준다. 지시서는 4개 역할
     카드만 적고 있으나 `steps[]` 전체를 보여 주려면 필요한 칸이다.
  2. 증거 역할 선택지의 보기 이름(대여 이체·변제 입금·차용증·대화 기록·기타)은
     화면 표시용으로 정했다. 계약서는 값(`loan_transfer` 등)만 정하고 화면
     이름은 정하지 않았다. 기본값은 `suggested_role` 그대로이다.
  3. 증거 상태 `ok`는 화면에 "정상"으로 보여 준다 (계약서에 화면 이름 없음).
- 열린 문제: E2E를 실제 M2a 백엔드 대상으로는 아직 돌리지 못했다 (M2a 진행
  전). `E2E_BASE_URL`로 같은 테스트를 그대로 돌리면 된다.
- 지시서와 약속 문서가 어긋나는 부분은 없었다.

## 6. 약속 문서 변경 제안

- 없음. `specs/`를 고치지 않았다.
- 참고: 계약서 5장 `ConfirmedFacts`의 고정 입력 규칙을 화면이 그대로 따르도록
  했다 (빈 칸은 예시 파일의 `fallback_fields` 값으로 채움, 역할은 제안값,
  강조는 `ex_id`·`item_id` 순 첫 `repay_promise`, 기준일 2026-06-01).
  E2E도 같은 규칙을 화면에서 따라 한다.
