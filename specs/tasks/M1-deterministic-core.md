# M1 결정론 코어: 계산기·검증 게이트·서류 문구 (작업 지시서)

- 작성: 2026-11-03 12:05 KST, Claude / 갱신 12:35 KST(서브에이전트 교차 리뷰 반영, 아래 "갱신 이유")
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\m1-core`(브랜치 `m1-core`). M0-fix1·M3와 동시에 진행하므로 아래 "파일 범위" 밖은 건드리지 않습니다.
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `reports/M-1-review.md`(R3, R4), `docs/code-analysis.md`(F4~F6, F14, F15, F20)
- 참조: 계획서 `specs/ClaimBack-AI_검토_및_구현테스트계획.md` 1-1(3) 한도, 1-2(8) 이자 규칙과 고정 예시, 4-6 L1 케이스, 6장 고지 문구 / 에이전트 설계 `specs/ClaimBack-AI_에이전트_설계.md` 3-5(계산), 3-6(문안 슬롯), 3-7(검증), 4-3 HOLD 목록과 11/3 보충(G4)
- 이 지시서와 명세가 다르게 보이면 이 지시서의 "결정" 항목이 11/3 결정입니다(명세에도 반영됨). 그래도 모순이 있으면 멈추고 리포트에 적습니다.

갱신 이유(12:35): 교차 리뷰에서 계산 규칙의 빈칸(약정 이자 일수, 버림 시점, 송달 후 이율), 다른 작업 트리 테스트와의 계약, 샘플 이름과 G1a 충돌, 서류 본문의 법적 평가 문구, 금지 명칭 목록의 오탐·누락이 지적됐습니다. 예산 환경 변수 작업은 M0-fix1로 옮겼습니다.

## 파일 범위

고쳐도 되는 파일:
- `backend/app/services/verification_gate.py`, `backend/app/services/pdf_compiler.py`, `backend/app/schemas/loan_fact.py`
- `backend/app/api/routes.py` 중 **`get_demo_samples()` 함수 밖** 전부(오류 응답, 예외 처리, 문서 문자열, import). `get_demo_samples()` 안은 M3가 고칩니다.
- `backend/app/main.py`
- 새 파일: `backend/app/services/draft_gates.py`(G1a, G3, 슬롯), `backend/app/services/naming.py`(명칭 검사, 고지 문구)
- `backend/tests/test_verification_gate.py`, 새 테스트 파일, 새 fixture `backend/tests/fixtures/demo_tampered_draft_kr.json`

건드리지 않는 파일: `backend/app/meta/`, `backend/tests/test_meta_client.py`, `tools/`, `frontend/`, `docs/`, `sample_evidence/`, `README.md`, `backend/tests/test_api_routes.py`, `.env.example`, `.gitignore`.

## 다른 작업 트리와의 계약 (병합 뒤 깨지지 않게)

- `backend/tests/test_api_routes.py`(M3 소유)는 다음을 기대합니다. 그대로 유지하세요.
  - 한국 데모 샘플(원금 10,000,000원, 변제 없음, 초안 `claim_amount_claimed` 10,000,000)로 `/api/verify` → `status == "PASS"`, `is_valid is True`, `reconciled_amount`가 `10000000`으로 시작.
  - `/api/compile/ecourt-packet` 응답 키 `claim_purpose`, `claim_cause_payment_order`, `claim_cause_lawsuit`.
  - 400 응답 `detail`은 `{ "message": ..., "missing_requirements": [...] }` 형태.
- 응답·스키마 필드 이름은 바꾸지 않습니다. 새 필드는 모두 선택값(기본값 있음)으로 추가합니다.
- 초안 금액 비교(R4): `claim_amount_claimed`가 남은 원금(`remaining_principal`) 또는 참고 총액과 같으면 통과, 둘 다 아니면 보류.

## 결정 사항 (11/3, Claude 판정)

### 계산 규칙 (한국)
- 모든 기간은 **초일불산입, 말일 포함**: 시작 사건(대여일, 변제기, 변제일) 다음 날부터 끝 날까지.
  - 약정 이자: 대여일 다음 날 ~ 변제기(고정 예시 기준 2026-03-11 ~ 2026-04-10, 31일).
  - 지연손해금: 변제기 다음 날 ~ 변제일 또는 기준일.
- 1년 365일 고정(윤년도 365). `Decimal`만 사용.
- **버림 시점**: 구간별 이자는 버리지 않고 정확한 값으로 더하고, 충당할 때마다(변제일마다) 그때까지 쌓인 이자 합계를 한 번 원 미만 버림합니다. 참고 총액도 마지막에 한 번 버림.
- 충당 순서: 비용 → 이자·지연손해금 → 원본.
- 지연손해금 이율: 약정 이율이 법정이율보다 높으면 약정 이율, 아니면 민사 연 5%, 상사 연 6%(`transaction_kind`). 약정 이율이 연 20%를 넘으면 20%로 계산하고 경고를 남깁니다.
- 송달 다음 날부터의 이율: 연 12%와 (상한 적용 후) 약정 이율 중 높은 값. 청구취지에는 **이율 숫자만** 쓰고 근거·판례는 쓰지 않습니다. 코드 주석의 판례 번호는 주석으로만 둡니다.
- 송달 전후 이율이 같으면 한 구간 문장("…부터 다 갚는 날까지 연 12%의 비율로 계산한 돈을 지급하라.")으로 씁니다.
- 변제액이 그때까지의 이자보다 작아 원본이 줄지 않는 경우: 이번에는 문구를 만들지 않고 보류합니다. 메시지: "이 변제 형태(이자보다 적은 변제)의 청구취지 문구는 아직 지원하지 않습니다. 확인할 칸: 변제 내역".
- 캘리포니아 계산 함수(연 10%, 센트 단위)와 그 테스트는 **바꾸지 않습니다**.

### 기대값 (테스트에 그대로)

| 케이스 | 남은 원금 | 기산일 | 비고 |
|---|---|---|---|
| 고정 예시: 5,000,000원, 대여 2026-03-10, 변제기 2026-04-10, 약정 없음, 2026-05-01 1,000,000원 변제 | **4,014,383** | 2026-05-02 | 지연손해금 21일 14,383.56 → 14,383, 원본 충당 985,617 |
| 같은 사건, 상사 연 6% | 4,017,260 | 2026-05-02 | 21일 17,260.27 → 17,260 |
| 같은 사건, 약정 연 12% | 4,085,479 | 2026-05-02 | 약정 이자 31일 50,958.90 + 지연 21일 34,520.55 = 85,479.45 → 85,479 |
| 같은 사건, 약정 연 24% 입력 | 4,142,465 | 2026-05-02 | 20%로 계산(84,931.51 + 57,534.25 = 142,465.75 → 142,465), 경고 1건 |
| 변제 없음, 기준일 2026-06-01 | 5,000,000 | 2026-04-11 | 참고 총액은 기준일과 함께 표시 |

고정 예시 청구취지(한 글자도 다르지 않게):
> 채무자는 채권자에게 4,014,383원 및 이에 대하여 2026. 5. 2.부터 이 사건 지급명령 정본 송달일까지는 연 5%, 그 다음 날부터 다 갚는 날까지는 연 12%의 각 비율로 계산한 돈을 지급하라.

약정 12% 케이스 청구취지: "채무자는 채권자에게 4,085,479원 및 이에 대하여 2026. 5. 2.부터 다 갚는 날까지 연 12%의 비율로 계산한 돈을 지급하라."

다른 기존 테스트의 기대값은 위 규칙 때문에 바뀌는 것만 고치고, 리포트에 손 계산식을 적습니다.

### 계산 결과 형식 (M2가 씀)
- 진입 함수: `calculate_kr(loan_fact: LoanFactSchema, as_of: date) -> Calculation`.
- `Calculation`(새 Pydantic 모델, `schemas/loan_fact.py`): `allocations[]`, `remaining_principal`, `accrual_start_date`, `rate_clause`(송달 전 이율, 송달 후 이율, 완성 문장), `reference_total { as_of, amount }`, `limit_check`, `missing_fields[]`, `warnings[]`, `calculation_steps[ { label, formula, amount } ]`(화면 데모용, 예: "지연손해금 = 5,000,000 × 5% × 21/365 = 14,383.56 → 14,383원").
- 기존 `VerificationResult`에는 선택 필드 `calculation: Optional[Calculation]`만 추가합니다.
- 한국 슬롯 이름 상수 `KR_SLOTS`(예: `creditor_name`, `debtor_name`, `principal`, `loan_date`, `due_date`, `repaid_amount`, `repaid_date`, `remaining_principal`, `accrual_start_date`)를 `draft_gates.py`에 둡니다.

### 게이트 (G2, G4, R4)
- G2: 이체 증빙, 변제기 근거, 당사자 이름이 없으면 보류와 빈 칸 목록. 대여 이체 증빙은 `EvidenceItem`의 새 선택 필드 `role`(`loan_transfer`|`repayment`|`other`, 사용자가 확인한 값)이 `loan_transfer`인 것을 쓰고, `role`이 없으면 기존처럼 첫 번째 이체 증빙을 씁니다.
- G4 한국: 비교 기준은 **청구 원금(남은 원금)**. 30,000,000원을 넘어도 보류하지 않고 경고만: "청구 원금 X원이 소액사건 기준 금액 30,000,000원보다 큽니다. 확인할 칸: 원금".
- G4 미국: $12,500 초과는 보류. 메시지: "청구 금액 $X가 이 도구의 SC-100 작성 범위($12,500 이하)를 넘어 서류를 만들지 않습니다." 법 조문 인용은 메시지에서 뺍니다. 연간 건수 안내는 "SC-100 양식의 연간 청구 건수 항목을 확인하세요."로 바꿉니다. 관련 테스트(`test_verification_gate.py`)도 맞춥니다.
- 모든 게이트 메시지는 양식 칸 기준 사실 문장입니다. 지울 표현: "청구권이 발생하지 않았습니다", "법적 청구 대상이 존재하지 않습니다", "요건사실 결손", "복원", "강제", "할루시네이션", "접수가 불가". 예: "변제기(2026-06-30)가 기준일(2026-06-01)보다 뒤입니다. 확인할 칸: 변제기", "입력한 변제 합계가 원리금 이상입니다. 확인할 칸: 변제 내역", 400 응답 message "서류를 만들 수 없습니다. 아래 칸을 확인하세요."
- R4: 초안 금액이 계산값과 다르면 보류(`missing_requirements`에 "초안의 금액이 계산값과 다릅니다. 확인할 칸: 청구 금액"). 응답 필드 이름(`tampering_reconciliations`, `reconciled_amount` 등)은 유지하고 설명(description)만 사실대로 고칩니다.
- 20% 상한 경고 문장: "입력한 약정 이율(연 N%)이 계산 상한 연 20%보다 높아 연 20%로 계산했습니다. 확인할 칸: 약정 이율".

### 서류 문구 (pdf_compiler.py)
- "금 X원을 대여"의 X는 처음 빌려준 원금. 일부 변제가 있으면 "그중 Y원을 YYYY. M. D. 받았고 남은 원금은 Z원입니다"처럼 사실만 씁니다.
- 지울 표현(법적 평가·위협): "정당한 사유 없이"(`:244`, `:304`), "채무 불이행" 제목(`:313`), "법적 조치를 취할 것이며 … 엄히 고지합니다"(`:247-250`). 대신 사실 문장(예: "변제기 이후 현재까지 남은 돈을 받지 못했습니다.")과 요청 문장("YYYY. M. D.까지 아래 계좌로 보내 주시기 바랍니다.")만 씁니다.
- 지급명령 문구의 "채권자(원고)", "채무자(피고)"(`:281`, `:284`) → "채권자", "채무자".
- `date.today()`(`:131`, `:255`, `verification_gate.py:247`) 대신 호출자가 넘긴 기준일(`as_of`, API의 `target_date`)을 씁니다. 없으면 오류가 아니라 서류에 날짜 칸을 비웁니다.
- 고지 문구는 서류 **본문**(내용증명 본문, 전자소송 붙여넣기 문구)에 넣지 않습니다(11/3 결정, 에이전트 설계 3-9 보충). 내용증명 PDF는 마지막 쪽 아래 여백에 작은 글씨로 `NOTICE_KO`만 넣습니다.

### 초안 검사 G1a·G3와 슬롯 (`draft_gates.py`)
- 입력: `SlotDraft { lang, sentences[ { sentence_id, type: fact|user, text_with_slots, ex_refs[] } ] }`, 허용 슬롯 목록, 기준값 당사자 이름 목록, 존재하는 호증 번호 목록. 출력: `GateResult { gate, status, findings[ { sentence_id, field, message, fix_hint } ] }`.
- 슬롯 문법: 값 슬롯 `{{principal}}`, 인용 슬롯 `{{quote:EX1:item3}}`, 근거 태그 `[[EX:1]]`, 사용자 진술 `[[USER]]`.
- G1a 거부(슬롯 밖): 아라비아 숫자, 한글 수사("오백만 원", "5백만원", "삼십일"), 날짜("4월 10일", "2026. 4. 10.")와 상대 날짜("다음 달", "지난주", "열흘 뒤"), 당사자 이름(아래 규칙), 허용 목록에 없는 슬롯 이름, 정형 문구("지급하라").
- **이름 규칙**(샘플 이름과 조사 충돌 방지): 전체 이름 일치, 이름(성 뺀 부분)만 일치는 거부. 성만 있는 경우는 바로 뒤에 호칭(씨, 님, 군, 양, 모씨)이 붙을 때만 거부. 샘플 이름은 `서가온(SAMPLE)`(채권자), `탁나루(SAMPLE)`(채무자), 영어 `Avery Linden (SAMPLE)`, `Rowan Hale (SAMPLE)`이며, 테스트도 이 이름을 씁니다.
- G3 거부: `fact` 문장에 `[[EX:n]]` 없음, 없는 호증 번호, `user` 문장에 `[[USER]]` 없음.
- 슬롯 치환 함수: 확인값으로 치환 후 남은 `{{...}}` 0개 확인, 인용 슬롯은 넘겨받은 원문으로.
- 테스트: 정상 초안 통과, 유형별로 고르게 섞은 변조 100건 자동 생성 → 100% 차단, 평범한 한국어 문장 20개 이상 통과("일부를 갚았다", "이후 연락이 없다", "이 돈은", "그는 다시 연락하지 않았다" 등).
- 데모용 fixture `backend/tests/fixtures/demo_tampered_draft_kr.json`: 정상 초안과, 금액을 숫자로 직접 쓴 문장 1개가 섞인 변조 초안. 테스트로 변조 초안이 G1a에서 그 문장 하나 때문에 막히는지 확인.

### 명칭 검사와 고지 문구 (`naming.py`)
- 고지 문구 상수(허용 목록 ID, 원문 그대로):
  - `DISCLAIMER_KO`, `DISCLAIMER_EN`: 계획서 6장 문구.
  - `NOTICE_KO` = "본인 작성용 초안, 법률 자문 아님"(계획서 1-1(2)), `NOTICE_EN` = "Self-help draft. Not legal advice."
- 검사 방법: 허용 목록 문구를 **정확히 일치하는 문자열로 먼저 지운 뒤** 금지어를 찾습니다(일반 부정문 예외는 두지 않음).
- 금지어(짧게 유지): 자기 지칭·대리(변호사, 법무사, 법률사무소, 법무법인, 로펌, 법률 대리, 법률 자문, lawyer, attorney, law firm, paralegal, legal assistant, counsel, legal advice), 결과 예측(승소, 패소, you will win, win your case, chance of winning), 법적 라벨·평가(채무 인정, 채무 승인, debt acknowledgment, acknowledgment of debt, Promissory Admission, 정당한 사유 없이, 청구권이 발생, 법적 청구 대상, 요건사실 결손, 입증할). "입증"은 단독으로 막지 않습니다(서류 제목 "[입증 방법]"은 정상).
- 검사 대상: 생성 서류 텍스트(내용증명 PDF 추출 텍스트, 전자소송 문구, SC-100 기입 값 — 양식 필드 이름은 대상 아님), `frontend/index.html`, `frontend/app.js`, `README.md`. 화면·README는 M3가 고치는 중이므로 이 작업에서는 그 파일을 고치지 말고, 이 테스트가 지금 작업 트리에서 실패하면 그 파일 부분만 `xfail(reason="M3에서 수정, 병합 후 통과해야 함")`로 표시합니다. 생성 서류 부분은 반드시 통과해야 합니다.

### 기타 (F15)
- `routes.py`: 예외 응답에 `str(e)`를 내보내지 않고 일반 문장 + 서버 로그. 임시 PDF는 응답 뒤 삭제(`BackgroundTask`). 모듈 문서 문자열의 "위변조 강제 복원" 같은 표현도 사실대로.
- `main.py`: CORS `allow_origins=["https://himangga01.github.io"]` + `allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"`, `allow_credentials=False`.
- 테스트의 샘플 이름을 위 이름으로 바꾸고, 미국 채무자(TV 인물 이름, 리뷰 R5)와 증거 제목 "Promissory Admission"을 `test_verification_gate.py` 안에서 바꿉니다("Rowan Hale (SAMPLE)", "Repayment promise message").

## 리포트 `reports/M1.md`

`AGENTS.md` 형식. 바뀐 기대값마다 손 계산식, G1a 변조 100건의 유형별 개수와 차단율, 통과시킨 평범한 문장 수, xfail로 남긴 테스트와 이유. 리포트는 한 번에 끝까지 쓰고, 쓴 뒤 파일을 다시 열어 마지막 절까지 저장됐는지 확인합니다(M0 리포트가 중간에 잘려 저장됨).

## 하지 않을 일

- Meta API 호출, 화면·샘플·README 수정(M3), 클라이언트 수정(M0-fix1), 판독·사실 정리·문안 작성 담당(M4·M5), 코디네이터(M2)
- 미국 SC-100 항목 4·5·7·8·9 고정값(F8), 윤년 366일(근거를 찾으면 리포트 6번에 제안만)
- `specs/` 수정, `.env` 읽기·만들기, 커밋과 푸시

## 완료 기준 (리뷰어가 그대로 다시 실행)

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m1-core"
cd "$WT\backend"
& $PY -m pytest -q                                            # failed 0 (xfail은 리포트에 이유)
& $PY -m pytest -q -k "4014383 or fixed_example"              # 고정 예시 테스트 존재·통과
cd $WT
& $PY tools\secret_scan.py                                    # 종료 코드 0
Select-String -Path backend\app\*.py,backend\app\*\*.py -Pattern '청구권이 발생','법적 청구 대상','요건사실 결손','복원','강제 정렬','할루시네이션','정당한 사유','엄히','접수가 불가','(원고)','(피고)' -SimpleMatch   # 0건 (naming.py의 금지어 목록 자체는 제외하고 리포트에 적음)
Select-String -Path backend\app\*.py,backend\app\*\*.py -Pattern 'date.today()' -SimpleMatch   # 0건
```
