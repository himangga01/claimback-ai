# M-1 기준선 정리 (작업 지시서)

- 작성: 2026-11-03 07:20 KST, Claude / 갱신: 07:30 KST (코드 리뷰 `docs/code-analysis.md`의 F1~F3, F10 반영)
- 수행: Muse Code (`muse-spark-1.3`)
- 예상 시간: 1시간 안쪽
- 먼저 읽을 것: `AGENTS.md`, 이 지시서. 참조: 계획서 `specs/ClaimBack-AI_검토_및_구현테스트계획.md` 1-2(16)·4-9, 에이전트 설계 `specs/ClaimBack-AI_에이전트_설계.md` 원칙 1~3

## 배경

이 저장소(`github.com/himangga01/claimback-ai`, 커밋 76d9cce)에는 이미 계산기, 검증 게이트, PDF 생성(내용증명, SC-100), FastAPI 라우트, 바닐라 JS 화면이 있습니다. 새로 만들지 않고 이 코드를 이어서 씁니다. 기술 스택도 기존 것(바닐라 JS, pypdf, reportlab)을 유지합니다.

2026-11-03 Claude 기준선 측정 결과(Windows, Python 3.12.10, 루트의 `.venv`):

```powershell
cd backend; $env:PYTHONPATH = "."; ..\.venv\Scripts\python.exe -m pytest -q
# 3 failed, 22 passed
# FAILED tests/test_api_routes.py::test_api_verify_endpoint  (status 'HUMAN_CHECK_REQUIRED' != 'PASS')
# FAILED tests/test_api_routes.py::test_api_compile_sc100_endpoint  (400 != 200)
# FAILED tests/test_api_routes.py::test_api_compile_content_proof_endpoint  (400 != 200)
```

이 작업은 Meta API 연동 전에 저장소를 제품 규칙에 맞추고 테스트를 모두 통과시키는 것입니다.

## 할 일

1. **실패 테스트 3개 수정.** 리뷰에서 원인을 확인했습니다(`docs/code-analysis.md` F10): 이 PC의 `core.autocrlf=true`가 `sample_evidence/*.txt`를 CRLF로 바꿔 SHA-256이 선언값과 달라집니다. LF로 받은 복제본에서는 25개 모두 통과합니다. `.gitattributes`에 `sample_evidence/** -text`를 넣고, 해당 파일을 LF로 다시 받은 뒤(`git rm --cached -r sample_evidence; git checkout -- sample_evidence` 또는 동등한 방법) 테스트를 확인합니다. 테스트를 약하게 고치지 않습니다.
1a. **샘플 인적사항 교체 (F1).** 사용자 확인 결과 가짜 정보지만, 실제 사람처럼 보이므로 바꿉니다. `backend/app/api/routes.py`, `frontend/app.js`, `docs/app.js`, `backend/tests/test_verification_gate.py`의 샘플 채권자 이름, 휴대폰 번호, 주소, 우편번호를 가상 값으로 바꿉니다. 이름에 "SAMPLE" 또는 "(데모)"를 붙이고, 전화번호는 `010-0000-0000`처럼 실재할 수 없는 형식을 씁니다. 리포트에 원래 값을 적지 않습니다.
1b. **증거 금액 불일치는 보류 (F2).** `verification_gate.py`의 이체증 추출액과 원금 비교(현재 `:327-334`)에서 다르면 `missing_requirements`에 넣어 `HUMAN_CHECK_REQUIRED`가 되게 합니다. "강제 정렬", "복원" 문구를 지우고, 관련 테스트(`test_verification_tampering_reconciliation` 등)는 새 동작에 맞게 고치되 리포트에 이유를 적습니다. LLM 청구금액 비교(`:362-368`)는 이번에 손대지 않습니다.
1c. **전자소송 문구 API 게이트 적용 (F3).** `routes.py`의 `/api/compile/ecourt-packet`도 다른 두 API처럼 `is_valid`가 거짓이면 400과 `missing_requirements`를 돌려주게 하고, 보류 사건에서 400이 나오는 테스트를 추가합니다.
2. **소멸시효 판단 제거.** 제품 규칙상 "청구할 수 있는가" 판단을 하지 않습니다. 아래를 지웁니다.
   - `verification_gate.py`의 `calculate_statute_of_limitations`와 게이트의 소멸시효 검사, 청구 불가 문구
   - `loan_fact.py`의 `statute_of_limitations_date`, `is_statute_of_limitations_expired` 필드와 주석
   - `frontend/`의 소멸시효 표시, README의 소멸시효 기능 설명
   - 관련 테스트는 삭제하고 리포트에 삭제한 테스트 이름을 적습니다.
3. **Muse Wonder 제거.** Muse Wonder는 한국에서 쓸 수 없습니다. 코드, 화면, README의 Muse Wonder를 `muse-spark-1.3`(Muse Spark)으로 바꿉니다.
4. **법률 전문가 표현과 법적 라벨 제거.** 코드, 화면, README에서 아래를 고칩니다.
   - "채무 인정", "debt acknowledgment" → 사실 유형 이름(예: "갚겠다는 메시지", `repay_promise`). 에이전트 설계 3-4 발화 유형 참조(11/3 리뷰에서 절 번호 정정).
   - 실제 브랜드 이름(토스뱅크, 카카오톡, Chase, iMessage)을 가상 이름(예: "샘플은행", "샘플톡", "Sample Bank")으로 바꿉니다(F13). `sample_evidence/`도 포함합니다. 파일 내용을 바꾸면 선언된 SHA-256 값도 다시 계산해 맞춥니다.
   - "legal empowerment tool ... without costly attorney fees", "Zero-hallucination guarantee" 같은 과장·법률 서비스 표현 → "본인 증거를 정리하고 표준 양식을 채우는 무료 도구", "확인된 값과 다르면 서류를 만들지 않음" 같은 사실 설명.
   - 화면과 README의 에이전트 구성은 `specs/multi_agent_architecture.md`(4대 역할 에이전트, 2026-11-03 갱신)에 맞춥니다. 에이전트 이름 4개(Forensic Visual, Fact-Timeline Chronology, Financial Auditor, Judicial Filer)는 유지하고, 자격·공직 페르소나 문구와 Muse Wonder, 소멸시효 항목만 고칩니다.
   - SC-100의 `Item 7: No attorney fee dispute` 같은 **법원 양식 필드 이름은 그대로 둡니다.**
5. **Windows에서 테스트 실행 간소화.** `backend/pytest.ini`(또는 `pyproject.toml`)에 `pythonpath = .`를 넣어 `cd backend; ..\.venv\Scripts\python.exe -m pytest -q`만으로 돌게 합니다. README 실행 방법을 PowerShell 기준으로 고칩니다.
6. **비밀값 관리 기반.**
   - `.env.example` 추가: `MODEL_API_KEY=`(빈 값), `META_MODE=replay`
   - `.gitignore`에 `.local/`, `backend/data/`(사건 데이터)를 추가
   - `tools/secret_scan.py` 추가: 저장소 파일(또는 `git diff --cached` 대상)에서 키처럼 보이는 문자열(`LLM_` 뒤 20자 이상, `sk-` 뒤 20자 이상, `-----BEGIN` 개인키, `.env` 파일 추적 여부)을 찾아 있으면 종료 코드 1. 값은 출력하지 않고 파일과 줄 번호만 출력합니다.
7. **`frontend/`와 `docs/`(GitHub Pages 사본) 일치.** 4번에서 `frontend/`를 고치면 `docs/index.html`, `docs/app.js`, `docs/styles.css`에도 같은 변경을 반영합니다. `docs/MASTER_PLAN.md`는 지난 계획 기록이므로 내용은 고치지 말고 맨 위에 "이 문서는 지난 계획입니다. 현재 계획은 `specs/ClaimBack-AI_검토_및_구현테스트계획.md`" 한 줄만 넣습니다.
8. 리포트 `reports/M-1.md` 작성(`AGENTS.md`의 리포트 형식).

## 하지 않을 일

- Meta API 연동, 새 기능, React 전환, PDF 레이아웃 변경(소멸시효 제거 외)
- 계산기 수정(일수, 반올림, 약정이자, 일부 변제 문구: `docs/code-analysis.md` F4~F6). M1에서 따로 합니다.
- `specs/` 수정. 바꿀 점은 리포트 6번 항목에 제안
- `.env` 읽기·만들기, 키 출력
- 커밋과 푸시(사용자 승인 뒤 Claude가 처리)

## 완료 기준 (리뷰어가 그대로 다시 실행)

```powershell
cd C:\2026_project\claimback-ai-meta\backend
..\.venv\Scripts\python.exe -m pytest -q          # failed 0
cd ..
.\.venv\Scripts\python.exe tools\secret_scan.py    # 종료 코드 0
Select-String -Path backend\app\*.py,backend\app\*\*.py,frontend\*,docs\index.html,docs\app.js,README.md -Pattern 'Wonder','소멸시효','statute of limitations','채무 인정','debt acknowledg','Zero-hallucination','attorney fees','토스','카카오','Chase','iMessage'
# 결과 0건 (SC-100 양식 필드 이름 주석 제외. 남긴 것이 있으면 리포트에 이유)
git grep -n -E '010-[0-9]{4}-[0-9]{4}' -- . ':!*.ttf' ':!*.pdf'
# 결과는 010-0000-0000 같은 가상 번호만 (F1 확인). 주소는 리뷰어가 눈으로 확인. 원래 값은 리포트에 적지 않음
```
