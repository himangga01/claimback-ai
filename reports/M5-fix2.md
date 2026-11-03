# M5-fix2 리포트: 서류 문장 렌더링·가림 사본 확인 (Muse Code)

- 작성: 2026-11-03 (KST), Muse Code (`muse-spark-1.3`)
- 작업 트리: `C:\2026_project\claimback-wt\m5` (브랜치 `m5`)
- Python: `C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe` (공유 venv, 신규 생성 없음)
- 지시서: `specs/tasks/M5-fix2-letter-render.md` (먼저 읽음: `AGENTS.md`, 지시서, `reports/M5-fix1.md`, `reports/M5-review.md` 6절, `specs/case-api-contract.md`)

## 1. 지시서와 한 일

- 1 슬롯 렌더링: `format_letter_fact`의 이름 글자 치환을 없애고(서명은 유지, 인자는 무시), `packager`가 저장된 `text_with_slots`를 `deps.render_sentence`로 서류별로 다시 렌더링. 이름값만 교체(내용증명 채권자 "본인"·채무자 "귀하", 전자소송 "채권자"·"채무자"), 조사 맞춤은 `substitute_text`가 담당, 인용 슬롯 원문은 손대지 않음. 슬롯이 없거나 재렌더 실패(사용자 평문 수정) 시 저장된 `rendered_text`로 폴백.
- 2 가림 사본 확인: `files/redacted_{ex_id}.png`의 SHA-256이 원본(이미지) 또는 PDF 미리보기(`evidence/{ex_id}_preview.png`)와 같으면 가림 사본이 아닌 것으로 제외. `files/redactions.json` 미리보기가 `needs_review: true` 또는 `status: "not_redacted"`이면 `confirmed.redaction_confirmed is True`가 아닌 한 제외하고 갑호증에 "가림 확인이 필요해 이 쪽에 이미지를 넣지 않았습니다." 한 줄 + G1b 지적. `get_redaction_status`가 (유효·확인필요·동일) 세 집합을 반환하고 `discover_redacted_paths`는 유효분만(기존 호출 호환).
- 3 증거 이름: 파일 이름 추정을 전부 삭제하고 역할·종류만. `loan_agreement`→"차용증", 영상→"대화 화면 녹화", PDF→"문서 사본", `loan_transfer`·`repayment` 이미지→"송금 기록 화면", 그 밖 이미지→"대화 화면 캡처". 내용 칸도 역할·종류만(`loan_agreement`→"차용증 사본", 일반 PDF→"문서 사본"). 갑호증 표지 목록도 `confirmed`를 받아 같은 이름으로(없으면 기존 파일 이름 폴백).
- 4 G1b 보강: `_NAME_DOCS`에 전자소송 추가. 전자소송은 실명 또는 역할어("채권자"·"채무자") 중 하나면 통과. 대여일·변제기는 날짜 뒤 40자 안에 "대여"·"변제"가 오는지 방향성으로 대조해 같은 서류 안 맞바꾸기를 탐지. 단일값 삭제(내용증명 대여일 전부 삭제) 테스트 추가.
- 5 다듬기: 전자소송 겹인용을 `(갑 제1호증)(갑 제6호증).` 하나로 합쳐 `".(` 잔재 제거. 여러 변제는 두 번째 이후 주어 삭제("…충당하고, 2026. 5. 20. …"). 초과 변제는 "…하여 받은 돈이 원금과 지연손해금을 넘어 ○원이 더 들어왔습니다" 사실형으로. 편지·전자소송 사실문 모두 마침표 보장(사용자 진술 포함). 기준일 뒤 변제는 `build_expected_*`와 증거 목록에서 제외(계산이 빼므로).
- 6 리포트: 이 파일. 아래 재생 샘플 사건 전문과 조사 테스트 결과 포함.

재생 샘플 사건 `case_e57785220daf`(실제 재생 fixture, 5문장, 가림 더미로 G1b `pass`) 전문. UTF-8로 `backend/data/cases/case_e57785220daf/files/content_proof.txt`·`claim_cause.txt`에 저장(git 제외)하고 아래에 붙임.

내용증명 PDF 텍스트 전문:

```
본인 작성용 초안, 법률 자문 아님
 내 용 증 명 서
발 신 인:
서가온(SAMPLE) (연락처: 010-0000-0001)
주소: 서울특별시 샘플구 데모로 0
수 신 인:
탁나루(SAMPLE)
주소: 경기도 샘플시 데모동 0
제 목:
대여금 반환 청구의 건
[청구 금액 합계: 금 4,031,430원 (2026. 6. 1. 기준)] (남은 원금: 4,014,383원, 현재 지연손해금: 17,047원
(2026. 6. 1. 기준))
1. 귀하의 무궁한 발전을 기원합니다.
2. 본인은 귀하에게 2026. 3. 10.에 금 5,000,000원을 대여하였으며, 귀하는 이를 2026. 4. 10.까지 전액
변제하기로 약정하였습니다.
가. 이체 확인증에는 2026. 3. 10.에 5,000,000원을 보낸 기록이 있습니다.
나. 차용증에는 변제기가 2026. 4. 10.로 적혀 있습니다.
다. 귀하가 "네, 병원비로 500만 원이 필요해요. 4월 10일까지 갚을게요."라고 했습니다.
라. 이체 확인증에는 2026. 5. 1.에 1,000,000원을 받은 기록이 있습니다.
마. 귀하가 본인에게 남은 돈을 지급하지 않고 있습니다.
본인은 2026. 5. 1. 귀하로부터 받은 1,000,000원을 그때까지의 지연손해금(2026. 4. 11.~2026. 5. 1., 연 5%)
14,383원에 먼저 충당하고, 나머지 985,617원을 원금에 충당하여 남은 원금은 4,014,383원입니다.
3. 본인은 변제기 이후 현재까지 남은 돈을 받지 못했습니다.
4. 이에 본인은 본 내용증명을 통하여 귀하에게 2026. 6. 8.까지 위 원리금 합계액(금 4,031,430원 (2026. 6. 1.
기준))을 보내 주시기 바랍니다.
 2026년 6월 1일
 발신인: 서가온(SAMPLE) (인/서명)
```

전자소송 청구취지·청구원인 전문:

```
1. 채무자는 채권자에게 4,014,383원 및 이에 대하여 2026. 5. 2.부터 이 사건 지급명령 정본 송달일까지는 연 5%, 그 다음 날부터 다 갚는 날까지는 연 12%의 각 비율로 계산한 돈을 지급하라.
2. 독촉절차비용은 채무자의 부담으로 한다.
라는 명령을 구함.

1. 당사자 관계
채권자는 채무자에게 금전을 대여한 자이며, 채무자는 이를 차용한 자입니다.

2. 대여사실 및 변제약정
채권자는 2026. 3. 10. 채무자에게 금 5,000,000원을 대여하였고, 채무자는 이를 2026. 4. 10.까지 변제하기로 약정하였습니다.
가. 이체 확인증에는 2026. 3. 10.에 5,000,000원을 보낸 기록이 있습니다(갑 제4호증).
나. 차용증에는 변제기가 2026. 4. 10.로 적혀 있습니다(갑 제6호증).
다. 채무자가 "네, 병원비로 500만 원이 필요해요. 4월 10일까지 갚을게요."라고 했습니다(갑 제1호증).
라. 이체 확인증에는 2026. 5. 1.에 1,000,000원을 받은 기록이 있습니다(갑 제5호증).
마. 채무자가 채권자에게 남은 돈을 지급하지 않고 있습니다.
채권자는 2026. 5. 1. 채무자로부터 받은 1,000,000원을 그때까지의 지연손해금(2026. 4. 11.~2026. 5. 1., 연 5%) 14,383원에 먼저 충당하고, 나머지 985,617원을 원금에 충당하여 남은 원금은 4,014,383원입니다.

3. 변제기 이후 상황
약정 변제기가 지났음에도 채무자는 현재까지 남은 돈을 지급하지 않고 있습니다.

4. 결론
따라서 채권자는 남은 원금 4,014,383원 및 지연손해금을 지급받기 위하여 본 신청에 이르렀습니다.
```

1의 조사 테스트 결과(4 passed): "김하나"(받침 없음)·"박민준"(받침 있음) 기준. 편지는 "본인은 … 귀하에게", "귀하는 …", 전자는 "채권자는 … 채무자에게", "채무자는 …"로 조사 맞춤. 인용 `"박민준이 김하나에게 빌려줘"`는 두 서류 모두 원문 그대로(인용 안 이름 미교체). `format_letter_fact`은 인자를 무시하고 인용을 건드리지 않음. 종단 흐름(확정값 김하나·박민준 오버라이드)에서도 내용증명 "본인은 2026. 3. 10. 귀하에게"·"귀하는 2026. 5. 1.", 전자소송 "채권자는 2026. 3. 10. 채무자에게"·"채무자는 2026. 5. 1." 확인, "본인는"·"귀하은"·"채권자은" 없음.

## 2. 만든·고친 파일

새 파일:

- `backend/tests/test_m5_fix2.py`: 17개 테스트(1: 4, 2: 4, 3: 2, 4: 3, 5: 4)

고친 파일(지시서 범위 4개):

- `backend/app/services/pdf_compiler.py`: `format_letter_fact` 글자 치환 삭제·마침표 보장, `format_ecourt_fact` 겹인용 병합·마침표 보장, `build_repayment_sentence` 다건 주어 삭제·초과 사실형, 내용증명 내부 호출 정리
- `backend/app/agents/packager.py`: `LETTER_NAMES`·`ECOURT_NAMES`·`style_slot_values`·`render_sentence_for_style`·`styled_fact_sentences` 추가, `build_package` 서류별 입력 분리, `_sha256_file`·`load_redaction_previews`·`is_redaction_confirmed`·`get_redaction_status` 추가, `discover_redacted_paths` 검증 포함, 갑호증 `needs_review`·`confirmed` 전달, G1b 확인필요·동일 사본 지적, 기대금액에 기준일 전달
- `backend/app/services/exhibit_bundle.py`: `NEEDS_REVIEW_LINE` 추가, `resolve_evidence_source`·`build_exhibits_pdf`에 `needs_review`·`confirmed` 인자, 표지 표시 이름, `evidence_display_name`·`evidence_summary` 역할·종류만, `_as_of_day`·`_repayments_of` 기준일 필터
- `backend/app/services/final_check.py`: `build_expected_amounts` 기준일 인자·기준일 뒤 변제 제외, `build_expected_dates` 동일, `_NAME_DOCS` 전자소송 추가·`_ECOURT_NAME_ALIASES`, `_date_occurrences`·`_date_has_keyword_near`(날짜 뒤 40자 방향성), `check_g1b` 이름 별칭·날짜 문맥 검사

지시서 범위 밖이지만 완료 기준(`pytest 0 failed`)을 위해 갱신(5절 참조):

- `backend/tests/test_m5_fix1.py`: 4개(다건 주어·초과 문구·증거 이름·문서 사본 기대값)
- `backend/tests/test_fact_check_m2c_fix1.py`: 1개(전자소송 SAMPLE→역할어 기대값, CRLF 유지)

건드리지 않음: `coordinator.py`·`cases.py`·`deps.py`(읽어서 `render_sentence`만 사용)·`draft_rules.py`·`fact_organizer.py`·`reader.py`·`intake.py`, `frontend/`·`docs/`·`e2e/`·`specs/`·`AGENTS.md`·`CLAUDE.md`·`docs/analysis/`·`docs/code-analysis.md`, 다른 리포트, `.env`(읽기·생성 없음). `reports/M0-spike.json`은 재생 실행 뒤 `git checkout`으로 복원. 서버·백그라운드 프로세스를 띄우지 않음(E2E 가짜 서버는 pytest 안에서 뜨고 끝남).

리뷰어 재생 산출물(`backend/data/cases`는 git 제외, G1b `pass`):

- `backend/data/cases/case_e57785220daf/files/content_proof.pdf`
- `backend/data/cases/case_e57785220daf/files/exhibits.pdf`
- `backend/data/cases/case_e57785220daf/files/evidence_list.pdf`
- `backend/data/cases/case_e57785220daf/files/content_proof.txt` (UTF-8 전문)
- `backend/data/cases/case_e57785220daf/files/claim_cause.txt` (UTF-8 전문)

## 3. 실행한 명령과 결과

키 없이(공유 venv, 실호출 없음):

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m5"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q        # 378 passed in 46.19s (failed 0)
cd $WT; & $PY -m pytest -q e2e              # 2 passed, 1 skipped in 21.26s (가짜 서버)
cd $WT; & $PY tools\m0_spike.py --mode replay --probes all  # P0~P8 success 9/9, 종료 코드 0
cd $WT; git checkout -- reports/M0-spike.json
cd $WT; & $PY tools\secret_scan.py          # secret_scan: clean, 종료 코드 0
```

신규·관련 테스트만:

```powershell
cd "$WT\backend"; & $PY -m pytest -q tests/test_m5_fix2.py
# 17 passed in 7.24s
cd "$WT\backend"; & $PY -m pytest -q tests/test_m5_fix2.py -k "letter_render or ecourt_render or does_not_touch or replay_names" -vv
# 4 passed (조사·인용)
cd "$WT\backend"; & $PY -m pytest -q tests/test_m5_fix1.py tests/test_m5_packaging.py
# 38 passed (25+13, 갱신분 포함)
```

조작·흐름 확인(신규 고정): 내용증명·전자소송 각각 대여일·변제기 맞바꾸기 `fail`(뒤바뀜 지적), 내용증명 대여일 삭제 `fail`, 전자소송 역할어 삭제 `fail`, 동일 SHA 사본 제외·확인필요 차단·확인 후 해제, 기준일 뒤 변제 흐름 `pass`(증거 목록에도 미표시).

## 4. 실호출 비용

- Meta 실호출 없음(지시서대로). 모델 0회, 비용 $0. 작업 트리 안 `reports/cost_ledger.jsonl`을 건드리지 않음.

## 5. 열린 문제와 지시서·약속 대비 차이

- 기존 테스트 5개 갱신: 지시서 파일 범위는 "4개 소스+새 테스트"이나, 바꾼 동작을 단정한 구 테스트를 고치지 않으면 완료 기준(0 failed)을 만족할 수 없다. `test_m5_fix1.py` 4개(다건 주어·초과·증거 이름·요약), `test_fact_check_m2c_fix1.py` 1개(전자소송 역할어). 모두 서식 기대값 갱신뿐이며 제품 동작을 테스트에 맞추지 않았다(M5-fix1 선례와 같고 리뷰에서 받아들여짐).
- 증거 내용 칸도 파일 추정 삭제: 지시서 3은 "증거 이름"만 명시하나, "파일 이름으로 문서 종류를 추정하지 않음"을 지키려면 요약 칸의 `iou`·`차용`·`loan` 분기도 함께 고쳐야 했다. 일반 PDF 요약은 "문서 사본", `loan_agreement`만 "차용증 사본".
- 초과 문구 확정형: 지시서 "…처럼"을 `…하여 받은 돈이 원금과 지연손해금을 넘어 ○원이 더 들어왔습니다`로 고정. 결론 문구(0원·초과)는 K11 그대로.
- 겹인용 병합형: 지시서가 형식을 안 정해 `(갑 제1호증)(갑 제6호증).` 이어붙이기로 고정(`, ` 구분 아님).
- 날짜 문맥 방향성: 지시서 "앞뒤 낱말"이나, 양방향 120자는 같은 항의 다른 쪽 낱말까지 보여 맞바꾸기를 놓친다. 날짜 뒤 40자만 보는 방향성으로 구현하고 메시지도 "뒤에"로 적었다.
- 증거 목록 기준일 필터: 지시서 5는 "G1b 기대값에서 제외"만 명시하나, 목록이 기준일 뒤 변제를 계속 표시하면 기대값 제외분과 어긋나 `extra` 실패가 난다. 목록의 변제 상세도 기준일 이전만 표시(증거 쪽 자체는 유지, 단일 변제증거 매핑은 필터 뒤 목록 기준).
- `loan_transfer`·`repayment` PDF는 "문서 사본": 지시서가 이미지 경우만 명시해 PDF 분기를 먼저 두었다. 송금 PDF도 "송금 기록 화면"으로 하려면 계약에 명시 필요.
- `redaction_confirmed` 엄격 판정: `is True`만 인정("yes"·1은 M4a-fix1에서 400 대상). 이 트리의 `coordinator.py`(범위 밖)는 아직 그 키를 받지 않아 `packager`가 `confirmed`에 있을 때만 읽는 순방향 호환으로 두었다.
- 표지 폴백: `confirmed` 없이 `build_exhibits_pdf`를 직접 부르면 기존처럼 파일 이름을 표시(구 호출 호환). 편철 경로는 항상 `confirmed`를 넘긴다.
- 줄 바꿈: 고친 4개 소스·새 테스트·`test_m5_fix1.py`는 LF. `test_fact_check_m2c_fix1.py`만 CRLF 유지(최소 diff).
- G1b 실패와 HOLD: 확인필요·동일 사본 지적은 `Package.gate_results`에만 적재하고 상태 전이는 `coordinator.py`(범위 밖)라 손대지 않았다.

## 6. 명세 변경 제안

`specs/`는 직접 고치지 않음. 아래만 반영을 제안함:

1. 계약 6a절에 가림 사본 검증 고정: SHA-256 동일 시 제외, `redactions.json` 미리보기 `needs_review`·`status: "not_redacted"` 시 `redaction_confirmed: true` 전까지 제외, 갑호증 문구("가림 확인이 필요해 …"·기존 미보유 문구)와 G1b 지적 문구(현 구현 그대로).
2. 계약 5장 `Drafts`·`Package.ecourt` 주변에 서류별 슬롯 재렌더 고정: 내용증명 "본인"·"귀하", 전자소송 "채권자"·"채무자", 이름값만 교체·인용 원문 불변·조사 맞춤, 슬롯 없음·실패 시 저장 렌더 폴백.
3. 계약 6a절 증거 이름표 고정(현 구현 매핑 그대로): `loan_agreement`→차용증, 영상→대화 화면 녹화, PDF→문서 사본, `loan_transfer`·`repayment` 이미지→송금 기록 화면, 그 밖→대화 화면 캡처. 갑호증 표지도 같은 이름. `loan_transfer` PDF 취급과 `VALID_ROLES`에 `loan_agreement` 추가 여부 결정.
4. 설계 3-7 G1b에 전자소송 이름 별칭(실명 또는 역할어)과 날짜 문맥 규칙(대여일 뒤 "대여"·변제기 뒤 "변제", 40자) 고정.
5. 계약·설계에 기준일 뒤 변제 취급 고정: 기대값·충당 문구·증거 목록 상세 모두 제외(현 구현).
6. 계약 5장·설계 3-9 주변에 문구 고정: 다건 주어 1회, 초과 사실형(`받은 돈이 원금과 지연손해금을 넘어 ○원이 더 들어왔습니다`), 겹인용 `(갑 제1호증)(갑 제6호증).` 병합, 사실문 마침표 보장.
