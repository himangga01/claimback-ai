# M3 합성 샘플 증거 세트와 정답 데이터 (작업 지시서)

- 작성: 2026-11-03 12:05 KST, Claude / 갱신 12:21 KST(서브에이전트 교차 리뷰와 M0 결과 반영)
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\m3-samples`(브랜치 `m3-samples`). M0-fix1·M1과 동시에 진행하므로 아래 "파일 범위" 밖은 건드리지 않습니다.
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `reports/M-1-review.md`(R1, R2, R3, R5, R10), `reports/M0-review.md`(M3에 넘긴 항목)
- 참조: 계획서 `specs/ClaimBack-AI_검토_및_구현테스트계획.md` 1-2(8)·(9)·(12), 4-6 L3, 5장 데모, 6장 고지 문구 / 에이전트 설계 `specs/ClaimBack-AI_에이전트_설계.md` 3-1(판독 출력), 3-2(감식 대상), 3-3(가림 정책), 3-4(발화 유형)
- 이 지시서와 명세가 다르게 보이면 이 지시서의 결정이 11/3 결정입니다(정답 데이터 위치는 계획서 4-9보다 이 지시서가 우선). 그래도 모순이 있으면 멈추고 리포트에 적습니다.

## 파일 범위

고쳐도 되는 파일:
- `sample_evidence/`(기존 텍스트 샘플, `generate_mock_evidence.py`, `manifest.json`, 새 하위 폴더 `kr/`, `en/`)
- 새 폴더 `backend/tests/golden/`(정답 데이터), 새 파일 `tools/make_sample_evidence.py`
- `backend/app/api/routes.py`의 **`get_demo_samples()` 함수 안만**
- `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`와 같은 변경을 `docs/index.html`, `docs/app.js`, `docs/styles.css`에
- `backend/tests/test_api_routes.py`, 새 파일 `backend/tests/test_sample_evidence.py`
- `README.md`, 새 파일 `LICENSE`, `backend/app/templates/fonts/OFL.txt`

건드리지 않는 파일: `backend/app/services/`, `backend/app/schemas/`, `backend/app/meta/`, `backend/app/main.py`, `routes.py`의 `get_demo_samples()` 밖, `backend/tests/test_verification_gate.py`, `backend/tests/test_meta_client.py`, `tools/secret_scan.py`, `tools/make_spike_inputs.py`, `tools/m0_spike.py`, `.gitignore`, `.env.example`.

## 다른 작업 트리와의 계약

- `test_api_routes.py`에는 계산값·게이트 상태·메시지 문구를 새로 검사하는 assert를 **추가하지 않습니다**(M1이 계산과 문구를 바꾸는 중). 기존 assert는 유지합니다.
- 기존 텍스트 샘플 시나리오(한국 10,000,000원, 2026-01-01, 변제기 2026-06-30, 초안 `claim_amount_claimed` 10,000,000 / 미국 $5,000)의 금액·날짜는 바꾸지 않습니다.

## 공통 규칙

- 모든 이미지·PDF·영상의 **여백 띠**(위 또는 아래 40px 안쪽)에 "SAMPLE / 데모용"을 넣고, 정답 데이터에 `ignore_regions`로 그 띠의 박스를 적습니다(판독 채점에서 제외).
- 사람 이름(두 작업 트리 공통): 한국 채권자 `서가온(SAMPLE)`, 채무자 `탁나루(SAMPLE)` / 영어 `Avery Linden (SAMPLE)`(채권자), `Rowan Hale (SAMPLE)`(채무자). 실존·유명 인물, 드라마·영화·소설 인물(예: 홍길동) 이름과 주소를 쓰지 않습니다.
- 앱·은행 이름: "샘플톡", "샘플은행", "SampleChat", "Sample Bank"만.
- 화면 모양: 실제 메신저·은행 앱의 색과 배치를 흉내 내지 않습니다. 대화 캡처는 흰 배경, 받은 말풍선 연회색(#E9ECEF), 보낸 말풍선 청록(#CFEFEA), 상단에 휴대폰 상태 표시줄·통신사 이름 없음. 프로필 그림은 원과 선으로 그린 단순한 기하학 얼굴. 도장 글자는 채무자 성명(예: "탁나루").
- 번호: 휴대폰 `010-0000-0000`, 미국 전화 `555-0100`~`555-0199`, 계좌 `000-0000-1234`처럼 앞자리는 0이고 **끝 4자리는 서로 다른 숫자**(가림 데모에서 "끝 4자리 유지"가 보이게), 주민번호 자리 `000000-0000000`.
- 생성은 Pillow, reportlab, ffmpeg로만 합니다(Meta 이미지 생성 모델 사용 안 함). 같은 명령으로 다시 만들면 바이트가 같아야 합니다: reportlab `Canvas(..., invariant=1)`, ffmpeg `-fflags +bitexact -flags:v +bitexact -map_metadata -1 -threads 1`, PNG는 메타데이터 없이 저장.
- 화면·README 문구는 사실 묘사만. 아래 "금지어"를 쓰지 않습니다.

## 할 일

### 1. 한국 세트 `sample_evidence/kr/` (P0, 먼저 끝냄)

사건(계산기 고정 예시와 같음): 대여일 2026-03-10, 원금 5,000,000원, 변제기 2026-04-10, 이자 약정 없음, 2026-05-01 1,000,000원 일부 변제, 그 뒤 연락 없음.

- `chat_01.png`(640×960): 2026-03-09~03-10. 빌려 달라는 요청, 금액 언급, "4월 10일까지 갚을게"처럼 날짜가 있는 상환 약속. 상대 프로필에 기하학 얼굴 1개.
- `chat_02_tall.png`(640×2400, 세로로 긴 휴대폰 캡처): 2026-04-20~05-01. 독촉, "오늘 100만 원 먼저 보냈어"(5/1), 남은 돈 상환 약속. 문장 안 숫자가 들어간 말풍선 포함.
- `chat_02_scroll.mp4`: `chat_02_tall.png`를 위에서 아래로 스크롤하는 6~8초, 640×960, 30fps 이하, 3 MB 이하. 처음 화면에 보이지 않던 말풍선이 나중에 나타나야 합니다.
- `transfer_loan.png`: 2026-03-10, 5,000,000원, 보낸 사람·받는 사람, 계좌번호 **전체가 보이는 별도 칸**(가림 데모용).
- `transfer_repay.png`: 2026-05-01, 1,000,000원 입금.
- `iou.pdf`(1쪽)와 같은 내용의 `iou.png`(150 DPI 렌더): 금액(아라비아 숫자와 "금 오백만 원"), 대여일, 변제기, 이자 없음, 주소(가상), 주민번호 자리 `000000-0000000`(별도 칸), 양쪽 서명, 빨간 도장.
  - **서명**: 펜으로 쓴 것처럼 여러 획(곡선 3개 이상, 굵기 변화, 겹침)으로 그립니다. 매끈한 곡선 하나는 안 됩니다(M0에서 SAM이 서명으로 찾지 못함).

### 2. 정답 데이터 `backend/tests/golden/` (테스트 전용)

- 위치를 `sample_evidence/` 밖으로 둡니다(런타임 에이전트가 읽는 폴더와 분리). `kr_truth.json`(필수), `en_truth.json`(영어 세트를 만들면).
- 파일 맨 위 `"_note": "test-only golden answers. Never pass to runtime agents."`
- 형식:
  - `evidences[]`: `ex_id`(EX1, EX2 … 파일마다 하나, 위 목록 순서), `file`, `sha256`, `width`, `height`, `coord_system: "pixel"`(PDF는 `iou.png` 기준 픽셀), `ignore_regions[]`
  - `items[]`(판독 정답, 설계 3-1): `item_id`(파일 안에서 `item1`부터), `kind`(아래 목록), `text_verbatim`, `normalized`, `box[x1,y1,x2,y2]`, `line_box`(문장 안 숫자일 때 그 줄 전체 박스), `speaker`(대화만), `frame_ts`(영상만, 그 말풍선이 처음 다 보이는 시각, 초)
  - `kind` 목록: `utterance`, `amount`, `date`, `party_name`, `account_number`, `id_number`, `phone`, `address`, `label`(인쇄된 항목 이름), `header`, `watermark`
  - `normalized`: 금액은 원 단위 정수(미국은 센트 정수), 날짜는 화면에 연도까지 있을 때만 `YYYY-MM-DD`, 없으면 `null`(연도 추정 금지)
  - `utterance_tags`(설계 3-4): 말풍선 `item_id`마다 `loan_request`, `amount_mention`, `repay_promise`, `reminder`, `other` 중 해당 태그
  - `vision_targets[]`(설계 3-2): `signature`(잉크가 실제로 칠해진 영역 박스와 `frame_box` 따로), `stamp`, `chat_bubble`, `face`
  - `redaction_targets[]`(설계 3-3): 계좌번호는 `mask_box`(가릴 앞자리)와 `keep_box`(남길 끝 4자리) 둘 다, 주민번호 자리는 뒷 7자리 `mask_box`만
  - `case`: `LoanFactSchema`와 같은 필드 이름의 기준값(당사자, 원금, 날짜, 변제)과 계산 기대값(`remaining_principal` 4014383, `accrual_start_date` "2026-05-02")
- 박스는 그릴 때 쓴 좌표에서 바로 기록합니다(눈대중 금지). 글자 박스는 Pillow `textbbox`로 계산합니다.

### 3. 영어 세트 `sample_evidence/en/` (P1, 한국 세트와 테스트가 모두 통과한 뒤에만)

사건: 2026-01-10 $5,000 대여, 변제기 2026-04-10, 이자 약정 없음, 주소 `0 Sample St, Sample City, CA 90000`. 파일: `chat_01.png`(상환 약속 포함), `wire_receipt.png`, `promissory_note.pdf`(+`.png`, 여러 획 서명). 시간이 부족하면 건너뛰고 리포트에 적습니다.

### 4. 생성기와 매니페스트

- `tools/make_sample_evidence.py`가 위 파일과 정답 데이터를 모두 다시 만듭니다. 글꼴은 `backend/app/templates/fonts/`의 NanumGothic.
- `sample_evidence/manifest.json`에 새 파일의 SHA-256을 추가합니다(기존 텍스트 샘플 항목 유지).
- `.gitattributes`의 `sample_evidence/** -text`가 새 파일에 적용되는지 확인합니다.

### 5. 기존 텍스트 샘플과 화면 정리

- `sample_evidence/*.txt`, `generate_mock_evidence.py`: 이전 샘플 이름과 그 계좌 끝자리, 미국 채무자 이름·주소를 위 가상 이름·번호로 바꿉니다(금액·날짜는 그대로). 바뀐 SHA-256을 `manifest.json`, `get_demo_samples()`, `frontend/app.js`·`docs/app.js` 프리셋에 맞춥니다. 프리셋과 `get_demo_samples()`의 `홍길동(SAMPLE)`, `김채무(SAMPLE)`, `SAMPLE Creditor`, 미국 채무자 이름도 위 이름으로 바꿉니다.
- 증거 제목 "Promissory Admission" → "Repayment promise message"(`get_demo_samples()`, 프리셋).
- `frontend/index.html`(와 `docs/` 사본):
  - 그림 속 이전 샘플 이름, 실제 은행 이름 1건 → 가상 이름, "샘플은행"
  - "변제기 합의 입증" → "변제기 날짜가 적힌 메시지", "Debt Promise" → "Repayment promise"
  - 에이전트 4 표시 이름 "Judicial Filer" → **"Judicial Form Filler"**(서류를 대신 제출하는 것처럼 읽히지 않게, 11/3 결정)
  - 고정 문구 `25/25 Tests Passed` 삭제
  - `lucide@latest`를 고정 버전으로(예: `lucide@0.469.0`, 실제 존재하는 버전을 확인)
- `frontend/app.js`(와 `docs/` 사본): 서버 없이 보여 주는 대체 계산(`runFallbackCalculation`)과 고정 문구(예: "민법 제157조 초일불산입 … 연산 무결", "총 청구 한도 검증 통과", 고정 숫자)를 지우고 "서버에 연결하면 계산 결과가 표시됩니다."로 바꿉니다. 화면에 법적 정확성을 주장하는 문구를 남기지 않습니다.
- 고지 문구: 화면 하단(footer)과 README에 계획서 6장 `DISCLAIMER_KO`, `DISCLAIMER_EN`을 **글자 그대로** 넣고, 화면 상단 작은 배지로 "본인 작성용 초안, 법률 자문 아님"을 넣습니다.
- README: "Judicial Filer" → "Judicial Form Filler", "Forensic judicial stamping" → "exhibit labels(갑 제N호증, Exhibit A)", "Strict adherence to legal precedents" 문장 삭제, "non-profit" 삭제, "court-ready" 같은 과장 삭제. 에이전트 설명은 하는 일만 사실대로.

### 6. 라이선스

- `LICENSE`: MIT, `Copyright (c) 2026 ClaimBack-AI contributors`. 첫 줄 아래에 "MIT applies to the source code and generated sample files. Bundled fonts and the SC-100 form are covered by their own terms (see README)."
- `backend/app/templates/fonts/OFL.txt`: NanumGothic 배포처의 SIL Open Font License 1.1 원문과 저작권 표시. 배포처에서 저작권 줄을 확인하지 못하면 지어내지 말고 `TODO: copyright line unverified`와 시도한 URL을 리포트에 적습니다.
- README "License" 절: 코드와 생성 샘플은 MIT, 글꼴은 OFL 1.1, `ca_sc100_blank.pdf`는 Judicial Council of California 양식을 수정 없이 포함한 것으로 MIT 대상이 아님("공개 양식"이라고 단정하지 않음).

### 7. 테스트 `backend/tests/test_sample_evidence.py`

- 매니페스트의 모든 파일이 있고 SHA-256 일치
- 정답 데이터 형식(필수 필드, 박스가 이미지 안, `kind` 목록 안, `case`의 원금·날짜·기대값이 위 사건과 일치, 계좌 `keep_box`가 끝 4자리)
- 이미지 크기, 영상 길이·용량
- 런타임 코드(`backend/app/`)가 `golden` 경로를 참조하지 않음
- 브랜드·금지어: 화면·README·샘플 텍스트에 실제 브랜드(토스, 카카오, 국민은행, Chase, iMessage, Zelle, 대소문자 구분)와 아래 금지어가 0건(단순 목록으로 검사)
- 이전 샘플 이름·TV 인물 이름: 테스트 코드에 그 이름을 직접 적지 말고 `git show 76d9cce:<파일>`에서 읽어 와 비교합니다(실제 사람처럼 보이는 이름을 저장소에 다시 남기지 않기 위해)

## 금지어 (M1의 `naming.py`와 같은 목록, 화면·README·샘플에 쓰지 않음)

변호사, 법무사, 법률사무소, 법무법인, 로펌, 법률 대리, 법률 자문, lawyer, attorney, law firm, paralegal, legal assistant, counsel, legal advice, 승소, 패소, you will win, win your case, chance of winning, 채무 인정, 채무 승인, debt acknowledgment, acknowledgment of debt, Promissory Admission, 정당한 사유 없이, 청구권이 발생, 법적 청구 대상, 요건사실 결손, 입증할. 단, 고지 문구 4개(`DISCLAIMER_KO`, `DISCLAIMER_EN`, "본인 작성용 초안, 법률 자문 아님", "Self-help draft. Not legal advice.")는 글자 그대로일 때만 허용됩니다.

## 리포트 `reports/M3.md`

`AGENTS.md` 형식. 만든 파일 목록과 크기, 정답 항목 수(종류별), 리뷰어가 눈으로 볼 이미지 목록, 영어 세트를 건너뛰었다면 그 사실. 리포트는 한 번에 끝까지 쓰고, 쓴 뒤 파일을 다시 열어 마지막 절까지 저장됐는지 확인합니다(M0 리포트가 중간에 잘려 저장됨).

## 하지 않을 일

- Meta API 호출(판독 정확도 측정과 실호출 fixture 기록은 M4·M2), 계산기·게이트·서류 문구(M1), 클라이언트(M0-fix1), 업로드 화면·파이프라인(M2, M6), 화면 프리셋을 새 이미지 사건으로 바꾸는 일(M2·M6)
- `specs/` 수정, `.env` 읽기·만들기, 커밋과 푸시

## 완료 기준 (리뷰어가 그대로 다시 실행)

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m3-samples"
cd "$WT\backend"
& $PY -m pytest -q                                   # failed 0
cd $WT
$before = Get-ChildItem -Recurse -File sample_evidence,backend\tests\golden | Get-FileHash | ForEach-Object { "$($_.Path)|$($_.Hash)" }
& $PY tools\make_sample_evidence.py                  # 오류 없음
$after = Get-ChildItem -Recurse -File sample_evidence,backend\tests\golden | Get-FileHash | ForEach-Object { "$($_.Path)|$($_.Hash)" }
Compare-Object $before $after                        # 차이 0건 (다시 만들어도 바이트가 같음)
& $PY tools\secret_scan.py                           # 종료 코드 0
Select-String -Path frontend\*,docs\index.html,docs\app.js,README.md,sample_evidence\*.txt -Pattern '토스','카카오','국민은행','Chase','iMessage','Zelle','Promissory Admission','입증','Tests Passed','Judicial Filer','non-profit' -CaseSensitive   # 0건
```
