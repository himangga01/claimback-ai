# M3 합성 샘플 증거 세트와 정답 데이터 (작업 지시서)

- 작성: 2026-11-03 12:05 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `m3-samples` 브랜치에서. M1과 동시에 진행하므로 아래 "파일 범위" 밖의 파일은 건드리지 않습니다.
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `reports/M-1-review.md`(R1, R2, R3, R5, R10)
- 참조: 계획서 `specs/ClaimBack-AI_검토_및_구현테스트계획.md` 1-2(5)·(8)·(9)·(12), 4-5 M3행, 4-6 L3 판정 기준, 5장 데모 흐름 / 에이전트 설계 `specs/ClaimBack-AI_에이전트_설계.md` 3-1(판독 출력), 3-2(감식 대상), 3-3(가림 정책), 3-4(발화 유형)

## 배경

데모와 판독 정확도 측정(골든셋)에 쓸 합성 증거가 필요합니다. 지금 저장소에는 텍스트 샘플 3개뿐이고, 화면 그림과 샘플 파일에 이전 샘플 이름·실제 은행 이름·법적 라벨이 남아 있습니다(리뷰 R1, R2, R3, R5). M0 스파이크용 입력 생성기 `tools/make_spike_inputs.py`가 있으니 방식을 참고해도 됩니다(그 파일은 고치지 않음).

## 파일 범위 (M1과 겹치지 않게)

고쳐도 되는 파일:
- `sample_evidence/` 전체(새 하위 폴더 포함)
- 새 파일 `tools/make_sample_evidence.py`
- `backend/app/api/routes.py`의 **`get_demo_samples()` 함수 안만**(샘플 데이터, 해시). 오류 응답 등 나머지는 M1이 고칩니다.
- `frontend/index.html`, `frontend/app.js`(샘플 프리셋, 화면 그림 문구), `frontend/styles.css`, 그리고 같은 변경을 `docs/index.html`, `docs/app.js`, `docs/styles.css`에
- `backend/tests/test_api_routes.py`, 새 테스트 파일 `backend/tests/test_sample_evidence.py`
- `README.md`, 새 파일 `LICENSE`, `backend/app/templates/fonts/OFL.txt`

건드리지 않는 파일: `backend/app/services/`, `backend/app/schemas/`, `backend/app/meta/`, `backend/app/main.py`, `backend/tests/test_verification_gate.py`, `tools/secret_scan.py`, `tools/make_spike_inputs.py`, `tools/m0_spike.py`.

## 공통 규칙 (계획서 1-2(12), AGENTS.md)

- 모든 이미지·PDF·영상에 "SAMPLE / 데모용" 표시가 보여야 합니다.
- 사람 이름은 누가 봐도 가상인 이름에 `(SAMPLE)`을 붙입니다. 한국 세트: 채권자 `김샘플(SAMPLE)`, 채무자 `이데모(SAMPLE)`. 영어 세트: `Alex Sample (SAMPLE)`, `Jordan Demo (SAMPLE)`. 실존 인물, 유명 인물, 드라마·영화 인물 이름과 주소를 쓰지 않습니다.
- 앱·은행 이름은 "샘플톡", "샘플은행", "SampleChat", "Sample Bank"만. 실제 브랜드의 색 배합·로고·화면 배치를 흉내 내지 않습니다.
- 번호: 휴대폰 `010-0000-0000`, 미국 전화 `555-0100`~`555-0199`, 계좌 `000-0000-0000` 형식(끝 4자리만 다르게 해도 됨), 주민번호 자리는 `000000-0000000`.
- 생성은 Pillow, reportlab, ffmpeg로 하고 Meta 이미지 생성 모델은 쓰지 않습니다(정답 박스를 정확히 알아야 하므로).

## 할 일

### 1. 한국 세트 `sample_evidence/kr/` (P0)

사건(계산기 고정 예시와 같은 값, 계획서 1-2(8)): 대여일 2026-03-10, 원금 5,000,000원, 변제기 2026-04-10, 이자 약정 없음, 2026-05-01 1,000,000원 일부 변제, 그 뒤 연락 없음.

- `chat_01.png` 대화 캡처(2026-03-09~03-10): 빌려 달라는 요청, 금액 언급, "4월 10일까지 갚을게" 같은 날짜가 있는 상환 약속. 상대방 프로필에 간단히 그린 만화 얼굴(실사 아님) 1개.
- `chat_02.png` 대화 캡처(2026-04-20~05-01): 독촉, "오늘 100만 원 먼저 보냈어"(5/1), 남은 돈 상환 약속.
- `chat_02_scroll.mp4`: `chat_02`를 위로 스크롤하는 5~8초 영상, 720p 이하, 3 MB 이하.
- `transfer_loan.png` 이체 확인증: 2026-03-10, 5,000,000원, 보낸 사람·받는 사람, 계좌번호(끝 4자리만 보이게 가린 형태와 전체 번호가 보이는 형태 중 **전체 번호가 보이는 형태**로 만들어 가림 데모에 씁니다).
- `transfer_repay.png` 입금 확인증: 2026-05-01, 1,000,000원.
- `iou.pdf` 차용증 1쪽(+같은 내용 `iou.png`): 금액(아라비아 숫자와 "금 오백만 원"), 대여일, 변제기, 이자 없음, 양쪽 서명(손글씨 느낌 선), 빨간 도장 모양, 주민번호 자리 `000000-0000000`, 주소(가상).

### 2. 영어 세트 `sample_evidence/en/` (P1, 미국 트랙용)

사건: 2026-01-10 $5,000 대여, 변제기 2026-04-10, 이자 약정 없음. 캘리포니아 가상 도시 주소(`0 Sample St, Sample City, CA 90000`처럼). 파일: `chat_01.png`(상환 약속 포함), `wire_receipt.png`, `promissory_note.pdf`(+`.png`, 서명 포함).

### 3. 정답 데이터 `sample_evidence/golden/` (테스트 전용)

- `kr_truth.json`, `en_truth.json`: 파일마다 SHA-256, 판독 항목(설계 3-1 `Reading` 형식: `item_id`, `kind`, `text_verbatim`, `normalized`, `box[x1,y1,x2,y2]` 원본 픽셀, 영상은 `frame_ts`, `speaker`), 발화 유형 정답(설계 3-4 태그: `loan_request`, `amount_mention`, `repay_promise`, `reminder`, `other`), 감식 대상 박스(서명, 도장, 말풍선, 얼굴), 가림 대상 박스(전체 계좌번호, 주민번호 자리), 사건 기준값(당사자, 원금, 날짜, 변제)과 계산 기대값(남은 원금 4,014,383원, 기산일 2026-05-02).
- 파일 맨 위에 `"_note": "test-only golden answers. Never pass to runtime agents."`.
- 박스는 그릴 때 쓴 좌표에서 바로 기록합니다(눈대중 금지).

### 4. 생성기와 매니페스트

- `tools/make_sample_evidence.py`: 위 파일을 모두 다시 만듭니다. 글꼴은 `backend/app/templates/fonts/`의 NanumGothic.
- `sample_evidence/manifest.json`에 새 파일들의 SHA-256을 추가합니다(기존 텍스트 샘플 항목 유지).
- `.gitattributes`의 `sample_evidence/** -text`가 새 파일에도 적용되는지 확인합니다.

### 5. 기존 텍스트 샘플과 화면 정리 (리뷰 R1, R2, R3, R5, R10)

- `sample_evidence/*.txt`, `generate_mock_evidence.py`의 이전 샘플 이름과 그 계좌 끝자리를 새 가상 이름·번호로 바꾸고, 미국 채무자 이름·주소를 가상으로 바꿉니다. 금액과 날짜는 바꾸지 않습니다(기존 API 테스트 시나리오 유지). 바뀐 SHA-256을 `manifest.json`, `routes.py`의 `get_demo_samples()`, `frontend/app.js`·`docs/app.js` 프리셋에 맞춥니다.
- 증거 제목 "Promissory Admission"(법적 라벨) → "Repayment promise message"(`get_demo_samples()`, 프리셋).
- `frontend/index.html`(와 `docs/` 사본): 그림 속 이전 샘플 이름, 실제 은행 이름 1건, "변제기 합의 입증"(법적 평가) → 가상 이름, "샘플은행", "변제기 날짜가 적힌 메시지". 고정 문구 `25/25 Tests Passed`는 지웁니다.
- 화면 문구는 사실 묘사만(설계 원칙): 법률 전문가처럼 보이는 표현, 승소·패소 예측, "채무 인정"류 라벨을 넣지 않습니다.

### 6. 라이선스

- `LICENSE`: MIT, `Copyright (c) 2026 ClaimBack-AI contributors`.
- `backend/app/templates/fonts/OFL.txt`: NanumGothic의 SIL Open Font License 1.1 원문과 저작권 표시(공식 배포처에서 확인한 문구, 출처 URL을 리포트에).
- README에 "License" 절: 코드는 MIT, 글꼴은 OFL 1.1, SC-100 양식은 California Judicial Council 공개 양식.

### 7. 테스트 `backend/tests/test_sample_evidence.py`

- 매니페스트의 모든 파일이 있고 SHA-256이 일치
- 정답 JSON 형식 검사(필수 필드, 박스가 이미지 크기 안, 원금·날짜가 위 사건과 일치)
- 이미지 크기와 영상 길이·용량 범위
- 저장소의 샘플·화면 파일에 이전 샘플 이름, 실제 브랜드 이름(토스, 카카오, Chase, iMessage, 국민은행, Zelle), TV 인물 이름이 0건(값을 테스트 코드에 직접 적지 말고, 리포트에도 적지 않습니다. 검사할 문자열이 필요하면 SHA-256 해시로 비교하거나 `git show 76d9cce:<파일>`에서 읽어 오세요)

### 8. 리포트 `reports/M3.md`

`AGENTS.md` 형식. 만든 파일 목록과 크기, 정답 항목 수(종류별), 리뷰어가 눈으로 볼 이미지 목록.

## 하지 않을 일

- Meta API 호출(판독 정확도 측정은 M4), 계산기·게이트·서류 문구(M1), 업로드 화면·파이프라인(M2, M6)
- `specs/` 수정, `.env` 읽기·만들기, 커밋과 푸시

## 완료 기준 (리뷰어가 그대로 다시 실행)

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
cd $WT\backend
& $PY -m pytest -q                         # failed 0
cd $WT
& $PY tools\make_sample_evidence.py        # 다시 만들어도 오류 없음
git status --short sample_evidence         # PNG·PDF·JSON은 다시 만들어도 바뀌지 않음(영상은 바뀌면 리포트에 적음)
& $PY tools\secret_scan.py                 # 종료 코드 0
Select-String -Path frontend\*,docs\index.html,docs\app.js,README.md,sample_evidence\*.txt -Pattern '토스','카카오','Chase','iMessage','국민은행','Zelle','Promissory Admission','입증','Tests Passed'   # 0건
```
