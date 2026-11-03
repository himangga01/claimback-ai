# M4a-fix1 리포트: 누출 검사·실패 시 닫기·가림 위치 (Muse Code)

- 작성: 2026-11-03 (KST), Muse Code (`muse-spark-1.3`)
- 작업 트리: `C:\2026_project\claimback-wt\m4a` (브랜치 `m4a`, M4a 커밋 cf994eb + main 병합 e871358 위)
- Python: `C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe` (공유 venv, 신규 생성 없음)
- 지시서: `specs/tasks/M4a-fix1-leak-failclosed.md` (먼저 읽음: `AGENTS.md`, 지시서, `reports/M4a.md`, `reports/M4a-review.md`, `specs/case-api-contract.md` 6a절)
- 파일 범위 준수: `vision.py`, `privacy_guard.py`, `services/redaction.py`, `coordinator.py`(감식·가림·HOLD 재개만), `api/cases.py`(파일 응답 형식만), SAM 명사 목록(변경 없음), 테스트, fixture만 손댐. `reader.py`·`intake.py`(M4b), `packager.py`·`exhibit_bundle.py`·`final_check.py`·`pdf_compiler.py`(M5-fix1), `frontend/`, `specs/`, 다른 리포트 손대지 않음.

## 1. 지시서와 한 일

- L1 (판독 상자를 믿지 않는 누출 검사): 가림 상자마다 원본에서 상자 바로 바깥 2px 띠(위·아래 항상, 계좌 왼쪽, 주민번호 오른쪽, 유지 쪽 제외)의 어두운 픽셀(밝기 128 미만, 빨간 도장 제외)을 셈. 5개 이상이면 그 항목과 그 증거 미리보기에 `needs_review: true` + 이유("가림 상자 밖에 글자가 남아 있을 수 있음"). 얼굴은 네 면 모두 검사(시료에서 0). 걸려도 HOLD 없이 사건 계속. EX6 세 상자는 모두 걸리고(위 띠 20·37·84, 주민번호 오른쪽 9) EX4·EX5 네 상자는 0(테스트로 고정).
- L2 (실패 시 닫기): 미리보기 없음·판독 보류·시각 감식 오류·가림 계획 누락 증거는 가린 사본을 만들지 않고 미리보기에 `status: "not_redacted"` + 이유(`url: null`, `needs_review: true`). 원본+표시만 붙인 가짜 "가린 사본" 제거. 사본이 없을 때 서류에서 빼는 것은 M5-fix1 범위라 손대지 않음.
- L3 (막다른 HOLD 없애기): 호증 표시를 가림·유지와 겹치지 않는 자리(겹치면 아래로 이동)에 먼저 그리고 가림을 마지막에 굽도록 순서 교체. `privacy_leak` HOLD는 진짜 실패(가림 안이 검정이 아님, 원본 해시 변경)에만 쓰고, 유지 영역 훼손은 과잉 가림이라 경고+확인 필요로 강등. `POST /run`으로 가림 단계부터 재실행(`_run_privacy_flow` 추출, `privacy_leak` HOLD 재개 경로).
- L4 (위치 맞추기): 판독 상자 안에서 원본 세로 열 잉크 분포로 글자 범위를 좁힘(서식 테두리 행·칸 모서리 제외). 문자 수와 잉크 덩어리 수가 맞으면 정확 분할(계좌는 끝 4자리 앞 글자 사이 빈 열, 주민번호 앞 6자리+구분자 유지·뒤 7자리, 전화는 숫자 위치 기준 가운데 4자리), 아니면 잉크 범위(희미하면 상자 전체) 비례 분할. EX4 분할 346→336으로 "1234" 첫 글자 복원. "+82 10-1234-5678", "연락처 010-1234-5678" 꼴 합성 테스트.
- L5 (테스트 강화): 정답 `redaction_targets`로 EX4·EX5 가린 글자 픽셀 전수 검사(샘플링 제거)+유지 상자 바이트 동일, 마스크 +300px 변이에서 4/4 실패. EX6은 어긋나 있어 `needs_review` 단언(M4b/INT-3에서 뒤집힐 핀). `privacy_leak` 재실행·감식 보류 코디네이터 테스트, `redaction_confirmed` "yes"·1 → 400 테스트.
- L6 (서명 정직하게): 서명 객체에 SAM 칸 상자(`box`, `source: "box"`, SAM `score`)와 잉크 상자(`ink_box`, `ink_source: "pixel_rule"`) 분리 저장. 마스크 PNG는 칸 마스크 그대로(칸 상자와 일치). 점 프롬프트(잉크 위 양성·칸 테두리 위 음성)와 명사 "handwritten signature"를 칸 잘라낸 이미지에 각 1회씩 실호출(4회): 점 IoU 0.68·0.74(부분만), 명사 빈 출력 → 픽셀 규칙 유지. 빨간 도장 픽셀을 잉크 규칙에서 제외. 명사 목록 파일 변경 없음.
- L7: 마스크 복호 1회(파서 검증 복호를 캐시해 저장 시 재사용)+바이트 변환 C속도화, M4a 테스트는 모듈 공유 사건 1개, 서명 재시도 오류는 `hold`+오류 문구, 감식 일부 실패에도 쓴 비용을 단계 비용·감사에 유지, PNG는 `image/png` 인라인. 전체 `backend` 73→30초.
- L8: 호증 표시 글자 크기를 이미지 너비 비례(`w/40`, 최소 20·최대 44).
- 기록: L6 탐침 4회만 `META_MODE=record`(원장은 메인 저장소, `run_id` = 사건 ID). 바뀐 감식 호출이 없어(명사·재시도 프롬프트 동일) 재기록 불필요, 재생으로 검증. 판독·사실 정리·문안 요청 untouched(재생 해시 유지). 최종 기록은 병합 뒤 INT-3.

## 2. 만든·고친 파일

고침(지시서 범위 안만):

- `backend/app/services/redaction.py`: L4 잉크 기하(`analyze_text_box`, 규칙 행·모서리 제외, 정확/대체 분할), L1 띠 계수(`count_band_pixels`, `flag_leak_bands`, 임계 5), L3 표시-먼저 굽기+겹침 회피(`place_stamp_avoiding`, `keep_boxes` 인자), 유지-훼손 경고 강등, L8 비례 글자(`stamp_font_size`), 빨강 제외 잉크 판정.
- `backend/app/agents/privacy_guard.py`: `build_plan`에 미리보기 이미지 인자(L4), `run_privacy` 실패 닫기(L2 `not_redacted`), L1 항목·미리보기 표시(`band_counts` 기록).
- `backend/app/agents/vision.py`: 서명 `box`/`ink_box` 분리(L6, 명사·재시도 공통), 마스크 1회 복호 캐시+고속 변환(L7), 호출 실패 시 부분 비용 전달(`_vision_partial`), 잉크 보정 빨강 제외.
- `backend/app/agents/coordinator.py`: 감식 오류 부분 비용·감사 유지, 재시도 오류 `hold`+문구, `_run_privacy_flow` 추출+`privacy_leak` HOLD 재개. 판독·정리·계산·문안·편철 로직 변경 없음.
- `backend/app/api/cases.py`: `.png` 생성 파일을 `image/png` 인라인으로(6a 마스크·가린 사본). PDF·기타 그대로.
- `backend/tests/test_m4a.py`: 15→27개. 모듈 공유 사건, 서명 `ink_box` 단언, 합성 분할 3종, L1 핀, L5 정답 덮기+변이, 감식 보류·누출 재개·400·실패 닫기 변형·스탬프 회피·빨강 제외·PNG 형식 테스트.
- `backend/tests/fixtures/m4a_previews/`: 재생성(가린 사본 5, 마스크 5, `segments.json`, `redactions.json`). EX4·EX5 분할 이동, EX6 표시 크기·`needs_review` 반영.

새 파일:

- `backend/tests/fixtures/meta/*.json` 4개: L6 탐침 기록(점 프롬프트 2+크롭 명사 2, 탐색용).
- `reports/M4a-fix1.md`: 이 리포트.

건드리지 않음: `agents/reader.py`·`intake.py`(M4b), `agents/packager.py`·`services/pdf_compiler.py` 등(M5-fix1), `services/`의 다른 파일, `backend/app/meta/`, `frontend/`, `docs/`, `e2e/`, `specs/`, `AGENTS.md`, 다른 리포트, 커밋済 fixture(수정 0개), `.env`(읽기·생성 없음), `reports/M0-spike.json`(재생 후 복원). `.local/` 헬퍼(`probe_fix1_*.py`, `m4a_previews.py` 수정은 `ink_box` 대응)는 작업 트리 안, git 제외. SAM 명사 목록(`prompts/sam_nouns.v1.md`) 변경 없음(탐침 부정적).

## 3. 실행한 명령과 결과

공유 venv·키 없이(탐침 4회만 키 사용, 값 출력·기록 안 함):

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m4a"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q
# 350 passed in 31.05s (failed 0; 기존 323 + M4a 27)
cd "$WT\backend"; & $PY -m pytest -q tests/test_m4a.py
# 27 passed in 5.32s (개별 실행 시)
cd $WT; & $PY tools\secret_scan.py
# secret_scan: clean, 종료 코드 0
$env:META_MODE = "replay"
& $PY tools\m0_spike.py --mode replay --probes all
# P0~P8 success=True 9/9 (ledger_total=$2.9528 lines=826)
git checkout -- reports/M0-spike.json
# 스파이크가 고친 파일 복원 (git status에서 사라짐 확인)
```

L6 탐침(실호출 4회, 기록 모드):

```powershell
$env:META_LEDGER_PATH = "C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl"
& $PY .local/probe_fix1_sig.py
# case: case_6273f752171f (run_id로 사용)
# cell0 point -> [53,47,296,83] (크롭 좌표), noun -> 빈 출력
# cell1 point -> [100,96,317,140] (크롭 좌표), noun -> 빈 출력
# PROBE_OK (원장 reserved 4 + completed 4)
```

미리보기 번들 재생성(재생, 키 없이):

```powershell
& $PY .local/m4a_previews.py
# signature bestIoU 0.9763·1.0000 (ink_box 기준, M4a와 동일)
# stamp 0.9889, bubble·face 동일, plan=9 leak=pass
```

서버(uvicorn)·백그라운드 프로세스는 띄우지 않음(TestClient만).

누출 검사 결과 표(재생 샘플 사건, `band_counts` 실측):

| 증거 | 항목 | 종류 | 위 | 아래 | 왼쪽 | 오른쪽 | needs_review |
|---|---|---|---|---|---|---|---|
| EX4 | item6 | 계좌 | 0 | 0 | 0 | —(유지 쪽) | false |
| EX4 | item10 | 계좌 | 0 | 0 | 0 | — | false |
| EX5 | item6 | 계좌 | 0 | 0 | 0 | — | false |
| EX5 | item10 | 계좌 | 0 | 0 | 0 | — | false |
| EX6 | item8 | 전화 | 20 | 0 | — | — | true |
| EX6 | item14 | 전화 | 37 | 0 | — | — | true |
| EX6 | item25 | 주민번호 | 84 | 0 | —(유지 쪽) | 9 | true |
| EX1 | face1 | 얼굴 | 0 | 0 | 0 | 0 | false |
| EX2 | face1 | 얼굴 | 0 | 0 | 0 | 0 | false |

(임계 5. EX6 미리보기 `needs_review: true` + 이유, 나머지는 `false`. `--`는 그 종류에서 검사하지 않는 면.)

서명 시도 결과:

| 칸 | 점 프롬프트 상자(이미지 좌표) | IoU(정답 잉크) | 명사 "handwritten signature" |
|---|---|---|---|
| 1 | [519,1327,762,1363] | 0.6814 | 빈 출력 |
| 2 | [536,1535,753,1579] | 0.7398 | 빈 출력 |

(픽셀 규칙 0.9763·1.0 유지. 점 프롬프트는 양성점 근처 한 획만 잡아 부분 상자.)

가린 사본 경로(작업 트리 안, 리뷰어 눈 확인용):

- `C:\2026_project\claimback-wt\m4a\backend\tests\fixtures\m4a_previews\redacted_EX1.png`
- `C:\2026_project\claimback-wt\m4a\backend\tests\fixtures\m4a_previews\redacted_EX2.png`
- `C:\2026_project\claimback-wt\m4a\backend\tests\fixtures\m4a_previews\redacted_EX4.png` (계좌 분할 336, "1234" 온전)
- `C:\2026_project\claimback-wt\m4a\backend\tests\fixtures\m4a_previews\redacted_EX5.png` (동일)
- `C:\2026_project\claimback-wt\m4a\backend\tests\fixtures\m4a_previews\redacted_EX6.png` (`needs_review`, 서류에서 제외 대상)
- 마스크 5개와 `segments.json`(칸/`ink_box` 분리), `redactions.json`(`status`·`reason`·`band_counts`) 같은 폴더.

## 4. 실호출 비용

- 모델: `sam-3.1`만 4회(Standard, `-contributor` 없음). 명사·재시도 호출은 프롬프트·이미지가 그대로라 재기록 없이 기존 기록 재사용(수정된 커밋済 fixture 0개).
- 내역: L6 탐침 `case_6273f752171f` 4회 $0.0100(점 2+크롭 명사 2). 합계 $0.0100(공유 원장 기준 completed 4건, 예약 4건 상쇄). 호출당 $0.0025.
- 원장: `C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl` 752→826줄(+74=당 작업 8+타 작업 66, 동시 작업 트리 병행). 작업 트리 안 원장은 건드리지 않음.
- `run_id`는 탐침 4회에 사건 ID 하나(`case_6273f752171f`) 사용. 판독·정리·문안 실호출 0회.
- 속도: 샘플 1회 실행 6.9→1.8초(마스크 1회 복호+고속 변환), 전체 스위트 약 73→31초.

## 5. 열린 문제와 지시서·약속 대비 차이

- EX6 판독 상자 어긋남은 M4b가 고치는 중이라 EX6 가림은 여전히 빗나감. 띠 검사가 세 항목을 잡아 미리보기에 "확인 필요"가 뜨고, M5-fix1이 사본을 서류에서 빼면 됨. L1 핀(EX6 true·EX4/EX5 0)과 L5 EX6 단언은 현재 상자 기준이라 M4b+INT-3에서 뒤집어야 함(테스트에 명시).
- L5 정답 덮기는 "정답 마스크 안의 글자(어두운) 픽셀이 전수 검정" + "정답 유지 상자 바이트 동일"로 구현. 정확 분할이 잉크 끝(336)에 맺혀 정답 경계(337)와 빈 1열이 달라 "마스크 전 픽셀 검정"이 아니라 글자 픽셀 기준임(지시서 "글자 픽셀이 실제로 검정" 문구대로). 변이(+300px)는 4/4 실패.
- 얼굴 띠 검사는 네 면 모두 적용(지시서가 면을 정하지 않아 실패 닫기 쪽으로 해석, 시료 0). 실제 사진에서 진한 배경이 옆에 있으면 "확인 필요"가 뜰 수 있음.
- 호증 표시 회피는 아래 이동+하단 고정이며, 화면 전체가 가림인 병적 경우 겹침을 감수하고 누출 HOLD(재개 가능)로 감. 시료 5개는 겹침 없음.
- `redacted_*.png`·마스크는 `image/png` 인라인으로 바뀌고 PDF 첨부 방식은 그대로. 미리보기 모양에 `status`·`reason`, 계획 항목에 `band_counts`, 서명에 `ink_box`·`ink_source`가 더해짐(기존 키 변경 없음).
- 지시서와 스펙이 다투는 부분은 없음. `redaction_confirmed` "yes"·1은 기존 bool 검사로 이미 400이라 코드 변경 없이 테스트만 추가.

## 6. 명세 변경 제안

`specs/`는 직접 고치지 않음. 아래만 반영을 제안함(4절 M4a 제안에 추가):

1. 계약 6a `redactions.previews[]`에 `status`(`redacted`|`not_redacted`, 사본 없음은 `url: null`)+`reason`(띠 이유·경고·미생성 사유) 명시. `not_redacted` 사본은 서류에 넣지 않음(M5).
2. 계약 6a `redactions.plan[]`에 `band_counts`(면별 띠 픽셀 수) 명시.
3. 계약 6a `segments` 서명 객체에 `ink_box`+`ink_source: "pixel_rule"` 명시(`box`는 SAM 칸 상자+SAM `score`, 마스크는 칸 마스크).
4. 계약 6a `segments[].status` `hold` 사유에 서명 재시도 오류 추가(이미 쓴 호출비는 단계 비용·감사에 유지).
5. 계약 3장 `POST /run` 재개에 `privacy_leak` HOLD→가림 단계 재실행 추가. `privacy_leak`는 마스크 비검정·원본 해시 변경에만, 유지 훼손은 경고.
6. 계약 6장 `GET /files/{name}` PNG는 `image/png` 인라인 명시.
7. 설계 3-2에 L4 분할 규칙 명시: 잉크 열 분포 축소(서식 테두리 제외)→정확 시 빈 열 분할(계좌 끝 4 앞·주민 뒤 7 앞·전화 숫자 기준 가운데 4), 실패 시 비례 대체.
8. M4a 6절 제안 유지(`hold` 상태, `needs_review`, `privacy_leak` 코드, `redaction_confirmed`, 서명 재시도+잉크 보정, M2a·INT-2 제안).
