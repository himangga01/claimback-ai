# M4a 리포트: 시각 감식(SAM 3.1)·개인정보 가림·호증 표시 (Muse Code)

- 작성: 2026-11-03 (KST), Muse Code (`muse-spark-1.3`)
- 작업 트리: `C:\2026_project\claimback-wt\m4a` (브랜치 `m4a`, INT-2 병합 뒤 `main`에서 시작)
- Python: `C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe` (공유 venv, 신규 생성 없음)
- 지시서: `specs/tasks/M4a-vision-privacy.md` (먼저 읽음: `AGENTS.md`, 지시서, `reports/M2a.md`, `reports/M0-review.md`, `reports/INT-2.md`, `reports/INT-2-review.md`, `specs/case-api-contract.md` 6a절, 에이전트 설계 3-2·3-3, 계획서 1-2(9))

## 1. 지시서와 한 일

- 1 (시각 감식) `agents/vision.py` 신설: 명사구 `signature`, `red stamp`, `chat bubble`, `face`로 SAM 3.1 호출(이미지·PDF 미리보기, 영상 건너뜀). 출력은 `meta-sam-parser`로 해석하고 해석 오류(박스·마스크 짝 불일치, 마스크 복호 실패, `error` 진단)는 `VisionParseError`로 기록해 "못 찾음"과 구분. SAM 박스는 입력 이미지 픽셀(`system: "pixel"`). 마스크는 PNG로 복호해 `files/`에 저장(`mask_url`). 감식-2(판독 뒤): 명사구로 못 찾은 서명은 판독 `서명` 라벨 오른쪽 프레임 영역을 박스 프롬프트로 1회 재시도. SAM 박스 프롬프트는 잉크가 아니라 프레임(테두리)을 돌려줘 잉크 IoU 0.2에 그치므로, 프레임 안에서 밝기 120 미만 어두운 픽셀로 잉크 박스를 보정(프레임 IoU 0.88·0.63 → 잉크 IoU 0.97·1.0, 5절에 근거와 한계 기록). 명사구 목록 파일 `prompts/sam_nouns.v1.md` 신설.
- 2 (개인정보 보호) `agents/privacy_guard.py` + `services/redaction.py` 신설: 판독 `account_number`(끝 4자리 유지 `mask_box`+`keep_box`), `id_number`(뒷 7자리만), `phone`(가운데 4자리), 감식 `face`(전체). 별도 칸은 박스 높이 20%(최소 4px) 여백, `keep_box` 쪽은 여백 없음. 문장 안 숫자(말풍선 안)는 줄 단위 넓은 가림 + `needs_review`·"확인 필요" 사유. 원본은 그대로 두고 사본에만 픽셀 검정(PDF 덮개 금지), 사본 오른쪽 위 "갑 제N호증" 표시. 누출 검사(규칙, P0): 가린 영역 100% 검정, `keep_box` 원본 동일, 원본 해시 불변을 확인하고 실패하면 `HOLD`(`privacy_leak`). 원본 가림 영역이 빈 흰색이면 경고(보류 아님)로 빗나감 표시.
- 3 (연결): 코디네이터 `vision` 단계(증거별 병렬 `substeps`, 판독과 같은 병렬 패턴으로 순차 실행 — 판독 블록은 손대지 않고 건너뜀 두 줄만 실제 실행으로 교체)와 `privacy` 단계(사실 정리 뒤, 체크포인트 1 전)를 실제로 돌림. 약속 6a절 `GET /segments`, `GET /redactions`, `PUT /facts` 선택 키 `redaction_confirmed`(없으면 `false`) 추가. 기존 응답 키·전이표 변경 없음. `segments.json`·`redactions.json`·마스크·가린 사본은 `files/`에 저장해 `case_state.py`를 건드리지 않음.
- 4 (기록 실행): `META_MODE=record`, `META_LEDGER_PATH=C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl`, `run_id`=사건 ID(`case_0dcb2277807e`)로 샘플 사건 SAM 21회(명사 20+재시도 1) 기록. 판독·사실 정리·문안은 실호출하지 않아 INT-2 기록 8개 그대로(수정된 커밋済 fixture 0개). 기록 직후 새 사건으로 재생해 누락 0·서명 2개·누출 통과 확인. 최종 재기록은 병합 뒤 INT-3에서.
- 5 (테스트): `backend/tests/test_m4a.py` 15개 신설(재생, 키 없이). 정답은 테스트에서만 읽고 런타임에 전달 안 함. 서명 잉크 IoU 0.976·1.0, 도장 0.989(0.5 이상 통과), 말풍선 12/12·얼굴 2/2 모두 0.5 이상, 가린 영역 100% 검정·`keep_box` 동일·원본 해시 불변·누출 실패 경로 포함.
- 6: 이 리포트. 끝까지 저장 확인(다시 열어末尾 확인).

## 2. 만든·고친 파일

새 파일:

- `backend/app/agents/vision.py`: SAM 명사 호출·해석·마스크 저장·서명 박스 재시도·잉크 보정
- `backend/app/agents/privacy_guard.py`: 가림 계획(별도 칸 정밀·문장 안 넓게+확인 필요·얼굴) 
- `backend/app/services/redaction.py`: 픽셀 굽기·호증 표시·누출 검사(검정·유지·해시·빈칸 경고)
- `backend/app/agents/prompts/sam_nouns.v1.md`: SAM 명사구 4개 목록
- `backend/tests/test_m4a.py`: 15개 테스트(시각 7·가림 8)
- `backend/tests/fixtures/meta/*.json` 31개: SAM 기록(명사 20+정확한 재시도 1+탐색 10, 아래 4절)
- `backend/tests/fixtures/m4a_previews/`: `redacted_EX1.png`, `redacted_EX2.png`, `redacted_EX4.png`, `redacted_EX5.png`, `redacted_EX6.png`, `mask_EX1_chat_bubble_noun0.png`, `mask_EX1_face_noun5.png`, `mask_EX6_stamp_noun0.png`, `mask_EX6_signature_box1.png`, `mask_EX6_signature_box2.png`, `segments.json`, `redactions.json` (리뷰어 눈 확인용)
- `reports/M4a.md`: 이 리포트

고친 파일(지시서 범위 안만):

- `backend/app/agents/coordinator.py`: `vision` 실제 실행(증거별 병렬+서명 재시도+`segments.json` 저장)·`privacy` 실제 실행(가림+`redactions.json` 저장, 누출 실패 `HOLD`)·`PUT /facts` `redaction_confirmed` 검증·저장. 판독·정리·계산·문안·편철 로직 변경 없음
- `backend/app/api/cases.py`: `GET /{id}/segments`, `GET /{id}/redactions` 추가만

건드리지 않음: `agents/reader.py`·`intake.py`(M4b), `agents/packager.py`(M5), `services/`의 다른 파일, `backend/app/meta/`, `frontend/`, `docs/`, `e2e/`, `specs/`, `AGENTS.md`, 다른 리포트, 커밋済 fixture(수정 0개), `.env`(읽기·생성 없음), `reports/M0-spike.json`(변경 없음). `.local/` 헬퍼(`probe_*.py`, `m4a_record_run.py`, `m4a_previews.py`, `patch*.py`)는 작업 트리 안, git 제외.

## 3. 실행한 명령과 결과

공유 venv·키 없이(기록·탐색만 키 사용, 값 출력·기록 안 함):

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m4a"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q
# 278 passed in 71.36s (failed 0; 기존 263 + M4a 15)
cd "$WT\backend"; & $PY -m pytest -q tests/test_m4a.py
# 15 passed in 21.95s
cd $WT; & $PY tools\secret_scan.py
# secret_scan: clean, 종료 코드 0
```

기록 실행(작업 트리 `.local/m4a_record_run.py`, `run_id`=사건 ID, SAM만 실호출):

```powershell
$env:META_MODE = "record"
$env:META_LEDGER_PATH = "C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl"
& $PY .local/m4a_record_run.py
# case: case_0dcb2277807e
# run1 replay state: CHECKPOINT_1 (INT-2 판독 재사용)
# EX1 nouns: 6 objects / EX2 nouns: 8 / EX4: 0 / EX5: 0 / EX6 nouns: 1
# EX6 retry: 2 objects [518,1327,781,1377] [515,1535,754,1589]
# RECORD total calls=21 cost=0.052500 / RECORD_OK
# run2 replay state: CHECKPOINT_1 / segments ok / signatures 2 / redactions plan=9 leak=pass / REPLAY_OK
```

미리보기·IoU 산출(재생, 키 없이, reviewer용 번들 생성):

```powershell
& $PY .local/m4a_previews.py
# 서명 0.9763·1.0, 도장 0.9889, 말풍선 12/12 0.8459~0.9815, 얼굴 0.9518·0.9756
# segments EX1 ok 6, EX2 ok 8, EX3 skipped, EX4/EX5 not_found, EX6 ok 3
# redactions plan=9 leak=pass → backend/tests/fixtures/m4a_previews/에 12개 저장
```

서버(uvicorn)·백그라운드 프로세스는 띄우지 않음(TestClient만). `reports/M0-spike.json` 변경 없음(`git status` 확인, 복원 불필요).

## 4. 실호출 비용

- 모델: `sam-3.1`만 51회(Standard, `-contributor` 없음). 판독·정리·문안 실호출 0회(INT-2 기록 재사용).
- 내역: 탐색 `m4a-probe1` 30회 $0.075000(명사 20 + 박스·크롭 실험 10) + 본기록 `case_0dcb2277807e` 21회 $0.052500(명사 20 + 정확한 재시도 1). 합계 $0.127500(공유 원장 기준 completed 51건, 예약 51건 상쇄). 호출당 $0.0025(SAM 이미지 단가).
- 원장: `C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl` 69→257줄(+188=당 작업 102+타 작업 86, 동시 작업 트리 병행). 작업 트리 안 원장은 건드리지 않음.
- `run_id`는 본기록 21회에 사건 ID 하나(`case_0dcb2277807e`) 사용. 단계 비용은 응답 usage 추정치(`estimate_cost_from_body`, 재생도 동일 $0.0025/회)로 집계해 `vision` 단계에 표시. 지연(기록): 명사 0.4~2.5초/회, 재시도 3.8초, 전체 약 1분. 재생 전체 흐름은 약 2초.
- 대상별 검출률·IoU(정답 박스마다 같은 종류 최적 박스, EX3 영상 제외):
  - 서명 잉크 2/2 검출, IoU 0.9763·1.0000 (SAM 박스만이면 프레임 IoU 0.88·0.63, 잉크 환산 0.18·0.13 → 프레임 안 어두운 픽셀로 보정, 5절)
  - 도장 1/1, IoU 0.9889 (명사 `red stamp` 1회)
  - 말풍선 12/12, IoU 0.8459~0.9815 (EX1 5/5 0.9548~0.9815, EX2 7/7 0.8459~0.9583)
  - 얼굴 2/2, IoU 0.9518·0.9756
  - EX4·EX5(영수증)는 시각 대상 없음 → `not_found` 정상
- 가림 결과 이미지(리뷰어 눈 확인용, 작업 트리 안):
  - `C:\2026_project\claimback-wt\m4a\backend\tests\fixtures\m4a_previews\redacted_EX1.png` (얼굴 1 가림+호증)
  - `C:\2026_project\claimback-wt\m4a\backend\tests\fixtures\m4a_previews\redacted_EX2.png` (얼굴 1 가림+호증)
  - `C:\2026_project\claimback-wt\m4a\backend\tests\fixtures\m4a_previews\redacted_EX4.png` (계좌 2 끝4 유지+호증)
  - `C:\2026_project\claimback-wt\m4a\backend\tests\fixtures\m4a_previews\redacted_EX5.png` (계좌 2 끝4 유지+호증)
  - `C:\2026_project\claimback-wt\m4a\backend\tests\fixtures\m4a_previews\redacted_EX6.png` (전화 2·주민 1 가림+호증, R1 어긋남으로 일부 노출 — 5절)
  - 마스크 샘플 `mask_EX1_chat_bubble_noun0.png`, `mask_EX1_face_noun5.png`, `mask_EX6_stamp_noun0.png`, `mask_EX6_signature_box1.png`, `mask_EX6_signature_box2.png`와 `segments.json`, `redactions.json` 같은 폴더

## 5. 열린 문제와 지시서·약속 대비 차이

- 서명: SAM 명사 `signature`는 멀티획 합성 서명에도 빈 출력(0개). 박스 프롬프트도 잉크가 아니라 프레임(테두리)을 돌려줌. tight 프레임 프롬프트(이상적, 정답 프레임 사용·테스트용 1회)도 프레임 IoU 0.96·잉크 환산 0.19~0.20, 크롭+명사(`signature`·`handwriting`·`scribble`)도 빈 출력. 잉크 박스를 프롬프트로 주면 0.97(당연). 따라서 재시도는 판독 `서명` 라벨 오른쪽 프레임 영역을 박스 프롬프트로 찾아 프레임 IoU 0.88·0.63을 얻고, 프레임 안 밝기 120 미만 픽셀로 잉크를 보정해 0.97·1.0 달성. 테두리 회색(약 126)은 제외되고 파랑·검정 잉크(약 66·28)만 남음. 일반 필기 서명에도 통하는 방식(어두운 잉크+흰 종이 가정)이나, 색종이·도장 겹침·기울기에는 미검증. 마스크 PNG는 SAM 프레임 마스크 그대로(박스 잉크와 크기 다름, 리포트에 명시). SAM만으로 잉크를 못 찾는 점은 합성 서명이 기하학적 지그재그(필기체 아님)라 인식 실패한 것으로 보고 데모에서는 "SAM이 서명 영역을 찾고 잉크를 보정"으로 설명.
- 가림: EX4·EX5(정사각 영수증, R1 13/13)는 판독 박스가 맞아 가림이 정답을 완전히 덮음(다만 여백·비율 분할로 마스크가 정답보다 큼, `keep` 왼쪽 9px가 마스크에 잠식 — 미리보기에서 끝4 첫 자릿수 왼쪽 얇게 가려 보임). EX6(전화·주민)은 R1 어긋남(INT-2 리뷰 R1: EX6 5/27)으로 판독 박스가 빗나가 마스크가 정답에서 어긋남(주민 IoU 0.067, 전화 일부 노출). 누출 검사(마스크 검정·유지 동일·해시)는 우리 박스 기준이라 `pass`지만, 미리보기에서 노출이 드러남(지시서 의도대로). `needs_review`는 문장 안 숫자(샘플에 없음)와 원본 빈칸 경고에만 붙고, 어긋남 부분 커버(겹침 있음)는 경고 안 함 — M4b 박스 수정+INT-3 재기록 뒤 가림을 다시 맞춰야 함. 전화 `keep_box` 없음(가운데만 가림, 양쪽 유지 검증은 눈으로), 주민 앞자리 유지 검증 없음(약속 6a 모양 그대로).
- `vision` 단계는 판독 블록을 손대지 않기 위해 판독 뒤 순차 실행(증거별 병렬 `ThreadPoolExecutor`, 결과 `ex_id` 정렬). 설계 2-1의 "판독 ∥ 감식-1"을 스레드 동시 실행이 아니라 "같은 병렬 패턴·독립 입력(판독 결과 안 씀)"으로 해석. 지연은 순차라 판독+감식 합산(약 2초 재생, 실호출 약 1분). 동시 실행으로 바꾸려면 판독 블록을 건드려야 해 범위 밖으로 보고 안 함.
- 해석 오류 기록: 박스·마스크 짝 불일치·마스크 복호 실패·`error` 진단은 `segments` `status: "hold"`+`error` 문구·`substeps hold`로 기록하고 사건 `HOLD`는 안 함(약속 6a `ok|not_found|skipped`에 `hold` 추가, 6절 제안). 재생 fixture 없음·예산 초과도 증거별 `hold`로 계속 진행해 기존 계약 테스트(가짜 판독+신규 이미지) 통과. `hold` 증거는 `not_found`가 아니라 오류로 구분(지시서 준수).
- 누출 실패 `HOLD` 코드는 `privacy_leak` 신설(약속 목록에 없음, 6절 제안). 한국 G4처럼 안내가 아니라 `HOLD`가 맞음(지시서 "실패하면 HOLD").
- `redacted_*.png`는 `/files/{name}`으로 서빙돼 `application/octet-stream`으로 내려감(기존 `generated_file` 범위 밖이라 미디어 타입 안 고침, 브라우저·`<img>` 표시에는 지장 없음). PDF(EX6) 가림 사본은 미리보기 PNG 기준(`redacted_EX6.png`), 원본 PDF·미리보기 모두 불변. M5 `exhibits.pdf`는 이 PNG들을 쓰면 됨.
- 지시서와 스펙이 다투는 부분은 없음. 계약 침묵 부분 해석: `GET /segments`·`GET /redactions`는 실행 전 빈 값(`[]`·`plan: []`+`pass`), 404는 없는 사건만. `PUT /facts`에 `redaction_confirmed` 아닌 다른 추가 키는 무시(기존 동작 유지).

## 6. 명세 변경 제안

`specs/`는 직접 고치지 않음. 아래만 반영을 제안함:

1. 계약 6a `segments[].status`에 `hold`(해석 오류·호출 오류, "못 찾음" 아님) 추가. `objects[].mask_url`은 PNG(프레임 마스크, 박스 잉크와 다를 수 있음) 명시.
2. 계약 6a `redactions.previews[]`에 `needs_review`(문장 안 가림·빈칸 경고 시 `true`, 화면 "확인 필요" 배지용), `plan[]`에 `needs_review`·상세 `reason` 추가 명시.
3. 계약 3장 `hold_reasons` 코드에 `privacy_leak`(누출 검사 실패, 재실행 가능) 추가. `fields`는 `EXn:itemk` 형식.
4. 계약 6a `PUT /facts` `redaction_confirmed`(선택, 기본 `false`, `true|false` 아니면 400) 명시. `false`면 서류에 가린 사본만 사용 유지(M5).
5. 설계 3-2에 서명 재시도 명시: 판독 `서명` 라벨 오른쪽 프레임 영역 박스 프롬프트 1회 + 프레임 안 어두운 픽셀 잉크 보정(밝기 120 미만). SAM만으로 잉크 직접 검출 불가(합성 서명 한계) 기록.
6. 설계 3-3에 가림 분할 명시: 계좌 끝4 문자수 비례 분할+`keep` 쪽 여백 없음, 주민 뒷7·전화 가운데4 문자수 비례, 얼굴 전체+전면 여백. 문장 안 숫자는 말풍선 너비 줄 단위+`needs_review`.
7. M2a·INT-2 제안 유지: `drafts.json` s2 G3 태그·`EXn`↔bare 번역·`claim_purpose` 범위·`transaction_kind` 기본값·인라인만 사용, `gate_results` 순서·`null_reason`·`side`·오류 모양·업로드 제한·문안 규칙·G2·G4 도출.
