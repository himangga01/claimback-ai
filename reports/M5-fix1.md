# M5-fix1 리포트: G1b 서류별 대조·가림·서류 문구 (Muse Code)

- 작성: 2026-11-03 (KST), Muse Code (`muse-spark-1.3`)
- 작업 트리: `C:\2026_project\claimback-wt\m5` (브랜치 `m5`)
- Python: `C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe` (공유 venv, 신규 생성 없음)
- 지시서: `specs/tasks/M5-fix1-g1b-privacy-docs.md` (먼저 읽음: `AGENTS.md`, 지시서, `reports/M5.md`, `reports/M5-review.md` K1~K11, `specs/case-api-contract.md`)

## 1. 지시서와 한 일

- K1 서류별 G1b: `final_check.py`에 서류별 필수값 표(`_AMOUNT_DOCS`·`_DATE_DOCS`·`_NAME_DOCS`)를 두고 내용증명·전자소송(청구취지+청구원인)·갑호증·증거목록별로 대조. 빠진 값은 없는 서류를 적시하고, 기대값에 없는 금액·날짜(내용증명 기한 `as_of+7일`만 허용 목록)도 지적. 단일 서류 조작 14가지를 `test_k1_single_doc_tampers_all_fail`로 고정(전부 `fail`, 정상은 `pass`).
- K2 변제 여러 번: `build_expected_amounts`는 중간 `remaining_principal_after`를 요구하지 않고 마지막 값만 요구(문구에 실제로 쓰는 값만). `overpayment_amount`는 0 초과 시 요구. 변제 2회 흐름(`600,000원+400,000원`, 증거 EX5·EX6에 각 1건)이 `pass`인 테스트.
- K3 가림 사본만: `discover_redacted_paths`는 `files/redacted_{ex_id}.png`만 인정(증거 폴더·사용자 파일명·상태맵 탐색 삭제). 가림 사본 없는 이미지·PDF는 그림을 넣지 않고 `MISSING_REDACTED_LINE` 한 줄만 넣으며, `Package.gate_results` G1b 지적에 증거(`EXn`·호증)를 적음. 원본 바이트가 갑호증 PDF에 0번 들어가는지 테스트(페이지 이미지 0개 + 바이트 카운트 0).
- K4 누출 검사 연결: 편철이 세 PDF(텍스트+메타데이터)와 전자소송 문구에 `find_sensitive_numbers`를 실행(전화번호 제외)하고 적발 시 G1b `fail`. 패턴에 10~14자리, 띄어쓰기 묶음, hyphen/en-dash/em-dash를 추가하고 공백 제거 2차 검사를 둠(줄바꿈 분리 번호 포착). 양성 예문 테스트.
- K5 명칭 사전 검사: PDF 쓰기 전 검사 대상에 채권자·채무자 이름·주소·전화, 증거 표시 이름·요약·작성일, 편지/전자소송 양식 사실문을 포함. 위반 시 `NamingViolation`으로 PDF를 하나도 쓰지 않음(이름·주소·전화 3종 테스트).
- K6 복사본 없애기: `kana_label`·`build_repayment_sentence`·사실문 서식(`format_letter_fact`·`format_ecourt_fact`·`ensure_numbered_facts`)을 `pdf_compiler.py`로 옮기고 내용증명·전자소송이 같은 함수를 쓰게 함. `packager.py`의 `generate_content_proof_pdf_fixed`·`patch_repayment_sentence`·`_old_repayment_fragment`와 미사용 소송용 청구원인 패치 계산을 삭제. `packager.build_repayment_sentence`·`kana_label`은 공유 함수로의 thin 래퍼로 유지(구 2인자 호출 호환).
- K7 충당 문구: 사실문 뒤·3항 앞 배치, 주어 포함, 지연손해금 기간·이율 표시. 표본: "채권자는 2026. 5. 1. 채무자로부터 받은 1,000,000원을 그때까지의 지연손해금(2026. 4. 11.~2026. 5. 1., 연 5%) 14,383원에 먼저 충당하고, 나머지 985,617원을 원금에 충당하여 남은 원금은 4,014,383원입니다." 숫자·기간·이율은 모두 계산값. 여러 변제는 "…충당하고, …"로 연결. 초과 변제("원금을 모두 갚고 ○원이 남습니다"), 이자보다 적은 변제("○원 중 ○원에 충당"), 약정이자/지연손해금(변제기 전후) 분기 테스트.
- K8 내용증명 문체: 편지형으로. 본문은 본인/귀하(고정 머리말 라벨·서명란의 "발신인" 표기는 유지), `[갑 제N호증]` 인용 삭제, 없는 연락처는 칸째 생략(`미기재` 없음), `(사용자 진술)`·`[[USER]]`는 서류에서 삭제. 전자소송 사실문은 이름 유지, 인용을 `(갑 제N호증)`으로 마침표 앞에 이동.
- K9 증거 목록: 증거 이름은 역할·종류로(송금확인증·대화 화면 캡처·대화 화면 녹화·차용증·문서 사본). 작성일은 확정값만(추정 금지, 그 외 `-`). 내용은 해당 증거의 확정 사실만(변제 여러 건은 증거별 1건씩, 단일 변제증거가 여러 변제를 covering할 때만 전건 표시). 도구 용어(`사용자 지정 발화` 등) 삭제.
- K10 긴 이미지: 너비 유지·높이 분할로 여러 쪽에 나눔(각 조각이 페이지에 들어가 10pt 이상 유지). 쪽마다 "갑 제N호증 (i/n)" 표시. 640×2400 표본은 3쪽으로 갈라짐(테스트).
- K11 다듬기: 전자소송 결론을 "남은 원금 4,014,383원 및 지연손해금"으로 명시(0원·초과 시 사실형 결론). `경` 통일(확정 날짜라 전부 삭제). 갑호증 표지에 "법원에 낼 때는 이 쪽을 빼세요" 안내 추가.
- 리포트: 이 파일. 재생 샘플 사건의 서류 발췌·조작 시험 전후 표·PDF 경로 포함.

## 2. 만든·고친 파일

새 파일:

- `backend/tests/test_m5_fix1.py`: 25개 테스트(K1 14조작 1, K2 2, K3 3, K4 2, K5 1, K6 2, K7 6, K8 2, K9 3, K10 1, K11 2)

고친 파일:

- `backend/app/services/final_check.py`: 서류별 필수값 표·서류별 미달 지적·기대외 금액/날짜 지적, 기대금액 K2(마지막 잔액만+초과), 기대날짜에 충당 이자구간 시작일, 누출 패턴 K4(10~14자리·띄어쓰기·en-dash·공백제거 2차)
- `backend/app/services/pdf_compiler.py`: K6 공유 함수(`kana_label`·`build_repayment_sentence`·`format_letter_fact`·`format_ecourt_fact`·`ensure_numbered_facts`), K7 충당 문구(기간·이율·다건 연결·초과·이자부족·약정), K8 편지 서식(본인/귀하·인용 삭제·연락처 생략·사용자 표시 삭제, 전자소송 인용 괄호), K11 결론·경 삭제
- `backend/app/services/exhibit_bundle.py`: K3 가림 사본만(원본·미리보기 미삽입+안내줄), K9 표시 이름·확정 작성일·증거별 내용, K10 긴 이미지 분할+쪽 표시, K11 표지 안내
- `backend/app/agents/packager.py`: K6 공유 함수 사용·복사본 삭제, K3 발견 경로 축소, K5 사전 검사 확대(이름·주소·전화·증거명), K4 누출 스캔+G1b 합산, K3 미보유 G1b 지적
- `backend/tests/test_m5_packaging.py`: 바뀐 동작에 맞게 5개 갱신(충당 문구 기대값, G1b 통과용 가림 더미, 갑호증 안내줄+표지 문구, 무가림 0이미지, 충당 숫자 조작 문자열) + `_run_to_package(with_redacted)`·`_make_redacted_dummies` 추가
- `backend/tests/test_case_contract.py`·`backend/tests/test_case_replay.py`: 전자소송 인용 기대값을 K8 형식(`(갑 제N호증)`)으로 각 1줄 갱신

건드리지 않음: `coordinator.py`·`cases.py`(M4a), `reader.py`·`intake.py`(M4b), `deps.py`·`draft_rules.py`·`fact_organizer.py`(M2c), `frontend/`·`docs/`·`e2e/`·`specs/`·`AGENTS.md`·`CLAUDE.md`·`docs/analysis/`·`docs/code-analysis.md`, 다른 리포트, `.env`(읽기·생성 없음). `reports/M0-spike.json` 변경 없음. 서버·백그라운드 프로세스를 띄우지 않음(리뷰어 PDF는 일회성 TestClient 재생으로 생성 후 종료).

리뷰어 재생 PDF(이번 수정으로 생성, `backend/data/cases`는 git 제외):

- `backend/data/cases/case_e7f140dc4ec7/files/content_proof.pdf` (1쪽)
- `backend/data/cases/case_e7f140dc4ec7/files/exhibits.pdf` (9쪽 = 표지 1 + 증거 8; EX2 640×2400을 3쪽으로 분할)
- `backend/data/cases/case_e7f140dc4ec7/files/evidence_list.pdf` (1쪽)

## 3. 실행한 명령과 결과

키 없이(공유 venv, 실호출 없음):

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m5"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q        # 311 passed in 37.56s (failed 0)
cd $WT; & $PY tools\secret_scan.py           # secret_scan: clean, 종료 코드 0
```

신규·갱신 테스트만:

```powershell
cd "$WT\backend"; & $PY -m pytest -q tests/test_m5_fix1.py
# 25 passed in 10.38s
cd "$WT\backend"; & $PY -m pytest -q tests/test_m5_packaging.py
# 13 passed in 7.00s
cd "$WT\backend"; & $PY -m pytest -q tests/test_m1_fix1.py tests/test_naming.py tests/test_m1_fix2.py
# 53 passed in 1.22s
```

K1 조작 시험 전후(14가지 단일 서류 조작; M5 전후 모두 `fail`이어야 정상):

| # | 조작(한 서류만) | M5(리뷰 ①) | M5-fix1 |
|---|---|---|---|
| 1 | 내용증명만 4,014,383→4,014,388 | pass(못 잡음) | fail |
| 2 | 전자소송만 4,014,383→4,014,388 | pass | fail |
| 3 | 증거목록만 5,000,000→5,000,001 | pass | fail |
| 4 | 갑호증에만 금 9,999,999원 추가 | pass | fail |
| 5 | 내용증명만 2026. 3. 10.→2026. 3. 11. | pass | fail |
| 6 | 전자소송만 2026. 4. 10.→2026. 4. 11. | pass | fail |
| 7 | 증거목록만 2026. 5. 1.→2026. 5. 2. | pass | fail |
| 8 | 내용증명만 서가온→서가은 | pass | fail |
| 9 | 증거목록만 탁나루→탁나래 | pass | fail |
| 10 | 전자소송에만 금 9,999,999원 추가 | pass | fail |
| 11 | 내용증명에만 금 9,999,999원 추가 | pass | fail |
| 12 | 증거목록에만 금 9,999,999원 추가 | pass | fail |
| 13 | 내용증명만 이자구간 2026. 4. 11.→2026. 4. 12. | pass | fail |
| 14 | 전자소송만 기산일 2026. 5. 2.→2026. 5. 3. | pass | fail |
| — | 정상 서류 | pass | pass |

바뀐 서류 텍스트 발췌(재생 샘플 사건 `case_e7f140dc4ec7`, G1b `pass`):

- 내용증명(편지, 인용·미기재·사용자 표시 없음): "2. 본인은 귀하에게 2026. 3. 10.에 금 5,000,000원을 대여하였으며… / 가. 본인이 귀하에게 5,000,000원을 2026. 3. 10.에 송금한 내역이 확인된다. / … / 다. 귀하가 본인에게 1,000,000원을 2026. 5. 1.에 송금한 내역이 확인된다. / 본인은 2026. 5. 1. 귀하로부터 받은 1,000,000원을 그때까지의 지연손해금(2026. 4. 11.~2026. 5. 1., 연 5%) 14,383원에 먼저 충당하고, 나머지 985,617원을 원금에 충당하여 남은 원금은 4,014,383원입니다."
- 전자소송 청구원인(괄호 인용·충당 후 결론): "채권자는 2026. 3. 10. 채무자에게 금 5,000,000원을 대여하였고… / 가. 서가온(SAMPLE)이 탁나루(SAMPLE)에게 … 확인된다(갑 제4호증). / … / 채권자는 2026. 5. 1. 채무자로부터 받은 1,000,000원을 … 14,383원에 먼저 충당하고, 나머지 985,617원을 원금에 충당하여 남은 원금은 4,014,383원입니다. / … / 4. 결론 / 따라서 채권자는 남은 원금 4,014,383원 및 지연손해금을 지급받기 위하여 본 신청에 이르렀습니다."
- 증거 목록: "갑 제1호증 대화 화면 캡처 - 대화 기록 / 갑 제2호증 대화 화면 캡처 - 대화 기록 / 갑 제3호증 대화 화면 녹화 - 대화 기록 / 갑 제4호증 송금확인증 2026. 3. 10. 서가온(SAMPLE) → 탁나루(SAMPLE), 2026. 3. 10. 5,000,000원 이체 기록 / 갑 제5호증 송금확인증 2026. 5. 1. 탁나루(SAMPLE) → 서가온(SAMPLE), 2026. 5. 1. 1,000,000원 이체 기록 / 갑 제6호증 차용증 - 차용증 사본"
- 갑호증: 표지에 "법원에 낼 때는 이 쪽을 빼세요." + 고지·면책. EX2는 "갑 제2호증 (1/3)·(2/3)·(3/3)" 3쪽. 가림 사본이 없는 쪽은 "가림 사본이 없어 이 쪽에 이미지를 넣지 않았습니다. 원본 파일은 따로 제출하세요."만 표시(이미지 0개).

## 4. 실호출 비용

- Meta 실호출 없음(지시서대로). 모델 0회, 비용 $0. 작업 트리 안 `reports/cost_ledger.jsonl`을 건드리지 않음.

## 5. 열린 문제와 지시서·약속 대비 차이

- 기존 테스트 3개 갱신: 지시서 파일 범위는 "4개 소스+새 테스트"이나, 완료 기준(`pytest 0 failed`)을 지키려면 바뀐 동작을 단정한 구 테스트를 고쳐야 했다. `test_m5_packaging.py`(5개, K3·K7·K11), `test_case_contract.py`·`test_case_replay.py`(각 1줄, K8 괄호 인용). 모두 서식 기대값 갱신뿐이며 제품 동작을 테스트에 맞추지 않았다.
- `claim_cause_lawsuit` 키 유지: 지시서는 "쓰지 않는 계산을 지움"이나, `test_naming.py`가 그 키의 무결성을 검사하고 계약 밖 호환을 깨지 않으려 키는 유지했다. 내용은 새 청구원인+입증방법(같은 공유 문구)이라 별도 패치 계산은 없다.
- 편지 충당문 주어: K7 예문은 "채권자는 … 채무자로부터"이나 K8 편지는 본인/귀하라 서식별 주어를 달리했다(내용증명 "본인은 … 귀하로부터", 전자소송 "채권자는 … 채무자로부터"). 숫자·기간·이율은 같은 공유 함수라 동일하다.
- `경` 통일 방향: 확정 날짜라 양쪽에서 삭제(내용증명 원래 없음, 전자소송 2곳 삭제). 근사 시점이 필요해지면 계약에 표기(`경` 유무·띄어쓰기)를 명시해야 한다.
- G1b 실패와 HOLD: 누출·미보유를 포함한 G1b `fail`은 `Package.gate_results`에만 적재하고 사건 상태 전이는 `coordinator.py`(범위 밖)라 손대지 않았다. 명칭 사전 위반은 기존대로 `NamingViolation`→`HOLD` 경로를 탄다.
- 영상 스틸컷 가림: K3은 이미지·PDF만 다루고 영상 스틸은 기존 발견 경로를 유지했다(리뷰 처리대로 INT-3에서 M4b 경로와 함께).
- 송달일 이후 이율 구간: 충당문 이율은 송달일 없는 흐름(표본·테스트 전부 해당)의 송달 전 이율로 계산한다. `service_date`가 있는 사건의 송달 후 분할 표시는 미구현.
- 줄 바꿈 파일 끝: 편집 4개 소스와 손댄 테스트를 LF로 통일했다(CRLF 혼합 방지). 동작 변경 없음.

## 6. 명세 변경 제안

`specs/`는 직접 고치지 않음. 아래만 반영을 제안함:

1. 설계 3-7 G1b에 서류별 필수값 표 고정(현 구현 `_AMOUNT_DOCS`·`_DATE_DOCS`·`_NAME_DOCS`: 내용증명=금액·날짜 대부분+이름, 전자소송=이름 제외·기산일 포함, 증거목록=원금·변제·대여일·변제일+이름, 갑호증=요구값 없음+추가값·누출·명칭만).
2. 계약 6a절에 가림 사본 경로 고정(`files/redacted_{ex_id}.png`만) 및 미보유 시 갑호증 안내줄·G1b 지적(현 구현 문구 그대로).
3. 계약 6a절 증거 목록 칸의 값 출처 고정(현 구현: 이름은 역할·종류 표, 작성일은 확정값만, 내용은 해당 증거 확정사실만).
4. 계약 6a절 `exhibits.pdf`에 표지 문구("법원에 낼 때는 이 쪽을 빼세요")와 긴 이미지 분할·쪽 표시(`갑 제N호증 (i/n)`) 명시.
5. 설계 3-9·계약 5장 `Drafts` 주변에 충당 문구 서식 고정(K7 예문+초과·이자부족·약정 분기, 편지/전자소송 주어 차이 포함).
6. 계약 5장 `Package.ecourt`에 `claim_cause_lawsuit` 키 유지 여부 결정(현 구현: 키 유지, 내용은 새 청구원인+입증방법).
7. 계약 3장·설계 4-3에 G1b `fail`(누출·미보유 포함)의 사건 상태 처리를 명시(현 구현: `gate_results`만 `fail`, 상태는 `CHECKPOINT_2` 유지).
