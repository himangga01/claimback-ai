# M2b-fix1 리포트: 화면 다듬기·E2E 실제 백엔드 대응·통합 정리

- 작성: 2026-11-03, Muse Code (`muse-spark-1.3`)
- 작업 트리: `C:\2026_project\claimback-wt\m2b-fix1` (브랜치 `m2b-fix1`)
- Meta 실호출: 0회

## 1. 지시서와 한 일

지시서 `specs/tasks/M2b-fix1-ui-integration.md`를 처음부터 끝까지 수행했다.
먼저 읽은 문서: `AGENTS.md`, 지시서, `reports/M2b-review.md`(U1~U20),
`reports/M3-fix1-review.md`(README·테스트 항목), `specs/case-api-contract.md`(v2),
`specs/case-api-examples/` 전체.

한 일 요약:

- **A. 차단 결함**: E2E가 `GET /review`를 직접 받아 약속 5장의
  `build_demo_confirmed_facts` 규칙 그대로 고정 입력을 계산한다(빈 칸은
  `confirmed_facts_kr.json`의 `fallback_fields`로, 역할은 `suggested_role`,
  강조는 `ex_id`·`item_id` 숫자 순 첫 `repay_promise`, 기준일 2026-06-01).
  `PUT /facts` 요청 본문이 계산값과 바이트 동등한지(`==`)까지 확인한다.
  문장 ID·`item1`·`revisions` 가정을 없앴다(`[data-testid^=approve-]` 순회,
  첫 `fact` 문장에서 수정 장면, 수정 라운드 표시는 있을 때만 확인).
  `test_sample_evidence.py`의 화면 파일 목록을
  `frontend/*.html|js|css`, `docs/*.html|js|css` glob으로 바꾸고, 사본 비교를
  `frontend` 파일 집합 기준으로 하면서 `docs/index.html`의 서버 없음 안내
  차이는 명시적 예외로 뒀다. 첫 화면 고지(`DISCLAIMER_KO`·`DISCLAIMER_EN`,
  하단)·한국어 배지 요구, 영어 배지 요구 삭제.
  `test_naming.py`의 xfail을 지우고 `frontend/case.js`를 실제로 검사한다.
- **B. 데모 결함**: 판독 박스 층을 이미지와 함께 스크롤되는
  `position:relative` 안쪽 요소(`viewer-inner`)로 감쌌다. 근거 칩 클릭 시
  해당 박스로 `scrollIntoView`, 박스 테두리는 진한 파랑(#0b3d91, 흰 배경 대비
  10.04:1) + 반투명 채우기, "Spark 판독 박스" 범례 추가.
  `[hidden]{display:none!important}` 추가, `<main hidden>` 초기 숨김,
  "데모 영상 보기"는 `#demo-video` 자리표시 링크로 변경.
  `legacy-dashboard.html/.js`와 `styles.css`를 `frontend/`·`docs/`에서 삭제.
  "지적 없음" 초록 / 지적 있음 빨강 / "사건을 삭제했습니다" 중립,
  G1a 차단 안내는 해당 문장 상자 안(`notice-{sid}`)에 표시,
  새 단계가 열리면 그 제목으로 스크롤·포커스.
  금액·날짜는 입력칸(원값 유지) 옆에 `display` 값(5,000,000원, 2026. 3. 10.)을
  함께 표시, 상태 한국어 이름(`CHECKPOINT_1` → "사실 확인 대기" 등),
  "문장 1" 표기, "작업 ID", 증거 상태 "읽음", 계산 섹션 번호 4,
  `reference_total`("기준일까지 참고 총액") 표시.
- **C. 에이전트 보드**: 대기·건너뜀 단계에서 "0.0초 · $0" 숨김(사용자 단계는
  카드에서 빼서 아래 가는 띠로 표시하므로 해당 없음). 맨 위 한 줄 요약
  "Meta 모델 호출 N회 · $X · 재생/실호출", 단계 실행 순서 번호(1~12),
  실행 중 강조, 모델 배지 확대("muse-spark-1.3 · 판독 5건").
  게이트 쉬운 이름(G1a "숫자·이름은 슬롯으로만", G3 "문장마다 증거 표시",
  G2 "필수 칸 확인", G4 "금액 범위 확인", NAMING "금지 표현 검사"),
  지적 표시는 `gate_results`에 실제로 있는 게이트만(없으면 "검사").
  수정 라운드는 "문안 작성 → 검증 → 수정 N회"로 표시.
  `{{…}}` 원문은 기본 접힘, "고치기"(`edit-toggle-{sentence_id}`)를 누르면
  `text_with_slots` 수정 칸이 열린다.
- **D. 동작 안정성**: 폴링을 `setTimeout` 연쇄 + 세대 번호로 바꾸고
  실행 중 버튼 비활성 및 "샘플 사건 불러오기" 차단. 초안 `PUT` 중에는
  승인 체크박스·"다시 검사"·"승인하고 계속" 비활성(E2E는 `expect_response`로
  응답 대기). 역할 선택지는 `loan_transfer`·`repayment`·`other`만, 모르는
  `suggested_role`은 `other`. 오류 표시에 `missing_requirements` 포함,
  빈 `fix_hint`는 괄호 없이 표시, 업로드한 사건도 "실행" 버튼으로 실행 가능.
  입력칸·체크박스에 `aria-label`(발화 체크박스는 발화 글 포함),
  흐린 단계는 불투명 처리(#40474f on #f1f3f5, 대비 8.46:1).
- **E. README**: 기여 표기를 사실대로 고치고(한·영),
  미구현 기능(SAM 분할·마스크, 픽셀 가림, 영상 판독, 타임라인 삽화)을
  "In progress (진행 중)"로 분리, 실행 방법에 `python -m venv .venv` 포함.
- **E2. 교차 리뷰**: E2E는 `data-state`·`data-gate`·`data-status` 속성으로
  확인하고, `PUT /facts` 본문 동등성으로 표시값/원값 분리를 검증한다.
  스크린샷은 스크롤 안정 후 촬영한다.
- **G. 샘플 생성기**: `drawImage`에 `ImageReader`를 감싸 PDF 바이트를
  경로와 무관하게 하고, 두 임시 폴더 비교 테스트를 추가한 뒤 다시 생성했다
  (매니페스트·정답 해시 갱신). ffmpeg 호출에
  `encoding="utf-8", errors="replace"` 추가(테스트의 ffmpeg·ffprobe 호출도
  동일). SAMPLE 띠 `ignore_regions`를 실제 띠 높이 37행(`[0,0,w,37]`)에
  맞추고(가시성 판정·테스트 상수 포함), 영어 서명에 별도 획 프로그램(2·3번)을
  배정해 한국 서명과 같은 픽셀이 되지 않게 했다.

지시서와 약속 문서가 어긋나는 부분은 없었다(추측이 필요한 충돌 없음).

## 2. 만들거나 고친 파일

- `frontend/index.html`: `<main hidden>`, 데모 영상 링크, "작업 ID",
  실행 버튼, 보드 요약·사용자 띠 자리, `viewer-inner`, 범례, 기준 참고 총액,
  제목 id·`tabindex`.
- `frontend/case.js`: 위 1절의 화면 동작 전부(약 520줄 변경).
- `frontend/case.css`: `[hidden]`, 판독 박스·범례, 지적 색, 실행 중 강조,
  순서 번호·모델 배지, 사용자 띠, 문장 안내, 표시값 힌트.
- `docs/index.html`, `docs/case.js`, `docs/case.css`: `frontend/`와 같은
  내용으로 미러 복사(바이트 동일).
- 삭제: `frontend/legacy-dashboard.html`, `frontend/legacy-dashboard.js`,
  `frontend/styles.css`, `docs/`의 같은 3개.
- `e2e/test_case_flow.py`: 고정 입력 계산·`PUT` 본문 검증·속성 기반 확인·
  `expect_response` 대기·스크롤 안정 후 촬영으로 재작성. 스텁 서버 변경 없음.
- `backend/tests/test_sample_evidence.py`: `screen_files()` glob,
  미러 비교(서버 없음 안내 예외), 고지·배지 요구, `BAND_TOP = 37`,
  ffmpeg·ffprobe 인코딩, PDF 경로 무관 테스트 추가.
- `backend/tests/test_naming.py`: xfail 삭제, `frontend/case.js` 검사.
- `README.md`: 기여 표기(한·영), 진행 중 분리, `python -m venv .venv`.
- `tools/make_sample_evidence.py`: `ImageReader`, ffmpeg 인코딩,
  `BAND_BOX_H`, 서명 프로그램 2종 추가 + 사람별 배정.
- 다시 생성한 결과: `sample_evidence/kr/iou.pdf`,
  `sample_evidence/en/promissory_note.pdf`,
  `sample_evidence/en/promissory_note.png`,
  `sample_evidence/manifest.json`, `backend/tests/golden/kr_truth.json`,
  `backend/tests/golden/en_truth.json`.

건드리지 않은 파일: `backend/app/`(M2a 작업 중), `specs/`, `AGENTS.md`,
`docs/analysis/`, `docs/code-analysis.md`, 다른 리포트.

## 3. 실행한 명령과 결과

파이썬은 지시대로 `C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe`만
사용했고, 새 venv를 만들지 않았다.

완료 기준(지시서 그대로, 2026-11-03 실행):

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m2b-fix1"
cd $WT; & $PY -m pytest -q e2e
# 1 passed in 12.44s (가짜 서버, failed 0)

cd "$WT\backend"; & $PY -m pytest -q
# 148 passed in 3.78s (failed 0, xfail 0)

cd $WT; & $PY tools\secret_scan.py
# secret_scan: clean

Test-Path frontend\legacy-dashboard.html, docs\legacy-dashboard.html
# False
# False
```

그 밖에 실행한 명령:

```powershell
cd $WT; & $PY tools\make_sample_evidence.py
# 3회 실행: 1회차에 샘플·정답·매니페스트 갱신, 2·3회차 해시 비교로
# 결정성 확인(18개 파일 전부 바이트 동일, deterministic)

cd "$WT\backend"; & $PY -m pytest -q tests/test_sample_evidence.py -k "signature or pdf_bytes or manifest or mirror or disclaimer"
# 6 passed, 18 deselected (G절·미러 집중 확인)
```

스크린샷(`e2e/artifacts/`, 1920×1080 전체 페이지, 10장):

1. `01-board.png` — 보드 요약·순서 번호·사용자 띠·판독 박스·범례
2. `02-checkpoint-evidence.png` — 갑 제4호증 전환(이체증 위 박스 정렬)
3. `03-checkpoint-filled.png` — 고정 입력(연락처·강조 체크)
4. `04-calculation.png` — 계산 4번·참고 총액·초안 목록
5. `05-drafts.png` — 접힌 원문·"고치기"로 열린 수정 칸
6. `06-g1a-blocked.png` — G1a 지적·문장 안 차단 안내·승인 비활성
7. `07-drafts-fixed.png` — 되돌리기 후 "지적 없음"(초록)
8. `08-drafts-approved.png` — 전 문장 승인
9. `09-package.png` — 서류 패키지·복사 블록
10. `10-deleted.png` — 삭제 후 중립 안내

매 촬영 단계에서 금지 표현 검사를 통과했고(`check_text` 0건),
스크린샷 6장을 직접 열어 박스 정렬·색·문구를 육안 확인했다.
`reports/`는 건드리지 않았다(`M0-spike.json` 재기록 없음).

## 4. 실호출

Meta API 실호출 0회(지시서대로 호출 없음). `reports/cost_ledger.jsonl`에
추가한 내역 없음. 모델별 호출·비용 모두 0.

## 5. 열린 문제와 지시서·약속에서의 벗어남

- 벗어남 없음. 지시서 20개 항목(A1~A3, B4~B8, C9~C12, D13~D17, E18, E2, G,
  F19~F20)을 모두 수행했고, 약속 문서와 어긋나는 부분은 없었다.
- `E2E_BASE_URL` 실제 백엔드 대상 실행은 이 작업 트리에서 할 수 없었다
  (`backend/app/`에 사건 API가 없음, M2a가 형제 트리에서 구현 중).
  E2E는 실제 백엔드에서도 깨지지 않게 썼다(고정 ID·개수 가정 제거,
  `PUT` 본문 동등성 검증, STUB 띠 숨김 확인). 병합 뒤 리뷰에서
  실제 백엔드 대상으로 재실행해 주기 바란다.
- 영어 세트 서명 획 프로그램(2·3번)은 새로 손으로 짠 좌표이며,
  기존 테스트(획 3개 이상, 틀 대비 IoU 0.4 이하, 사람별 상이)를 통과한다.
- 참고: 텍스트 파일 줄바꿈은 저장소 관례(CRLF, `core.autocrlf=true`)를
  유지했다. `git diff --stat` 기준 변경 23개 파일, +1328/−2153줄이며,
  삭제 6개는 예전 대시보드 제거분이다.

## 6. 약속 문서 변경 제안

제안 없음. 이번 작업에서 약속(`specs/case-api-contract.md` v2, 예시 JSON)을
바꿀 필요를 찾지 못했다. `specs/`는 건드리지 않았다.
