# M2b-fix1 화면 다듬기·E2E 실제 백엔드 대응·통합 정리 (수정 지시서)

- 작성: 2026-11-03 13:17 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\m2b-fix1`(브랜치 `m2b-fix1`, M0-fix2·M1-fix1·M2b·M3-fix1이 병합된 `main`에서 시작). M2a(백엔드)와 동시에 진행합니다. **Meta 실호출 없음.**
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `reports/M2b-review.md`(U1~U20), `reports/M3-fix1-review.md`(README·테스트 항목), `specs/case-api-contract.md`(v2), `specs/case-api-examples/`

## 파일 범위

고쳐도 되는 파일: `frontend/`, `docs/`(Pages 사본), `e2e/`, `backend/tests/test_sample_evidence.py`, `backend/tests/test_naming.py`, `README.md`, 그리고 G절 때문에 `tools/make_sample_evidence.py`, `sample_evidence/`, `backend/tests/golden/`(다시 생성한 결과만).
건드리지 않는 파일: `backend/app/`(M2a가 고치는 중), `specs/`, 그 밖 전부.

## 할 일

### A. 차단 결함
1. **E2E 고정 입력**: `e2e/test_case_flow.py`가 `highlight-EX1-item4`처럼 ID를 고정하지 말고, `page.request`로 `/review`를 받아 약속 5장의 규칙(`build_demo_confirmed_facts`) 그대로 계산합니다: 빈 칸 전부를 `confirmed_facts_kr.json`의 `fallback_fields`로, 역할 = `suggested_role`, 강조 = `ex_id` 숫자 순·`item_id` 숫자 순 첫 `repay_promise`, 기준일 2026-06-01. 화면에서도 같은 값이 선택되게 하고, 발화 항목에 `data-tags`를 붙입니다.
2. **E2E가 모델이 정하는 ID·개수에 기대지 않게**: 문장 ID(s1~s4), `item1`, `revisions` 존재를 가정하지 않습니다. `[data-testid^=approve-]`를 돌며 승인, 수정 장면은 첫 `fact` 문장으로, 수정 라운드 표시는 있을 때만 확인.
3. **테스트 경로(병합 뒤 실패 4건)**: `test_sample_evidence.py`의 화면 파일 목록을 `frontend/*.html|js|css`, `docs/*.html|js|css` glob으로 만들고, 사본 비교는 `frontend`의 파일 집합 기준(`docs/`의 서버 없음 안내 차이는 명시적 예외). 첫 화면에는 `DISCLAIMER_KO`·`DISCLAIMER_EN`(하단)과 한국어 배지가 있어야 하고 영어 배지는 요구하지 않습니다. `test_naming.py`의 xfail은 지우고 `frontend/case.js`, `frontend/index.html`을 실제로 검사합니다.

### B. 데모에서 바로 보이는 결함
4. **판독 박스 위치**: `.viewer`가 스크롤되면 박스가 어긋납니다. 이미지와 박스 층을 `position:relative` 안쪽 요소로 감싸 같이 스크롤되게 하고, 근거 칩을 누르면 그 박스로 `scrollIntoView`. 박스 테두리를 진한 색(대비 3:1 이상) + 반투명 채우기로, "Spark 판독 박스" 범례 표시.
5. **`hidden` 무시**: `[hidden]{display:none!important}`. `docs/` 서버 없음 상태에서는 안내만 보이고 앱은 처음부터 숨김(`<main hidden>`), "데모 영상 보기"는 링크(주소는 `#demo-video` 자리표시, M8에서 실제 주소).
6. **예전 대시보드 삭제**: `legacy-dashboard.html/.js`와 그것만 쓰던 `styles.css`를 `frontend/`·`docs/`에서 지웁니다(가짜 수치·법 준수 주장, M3 리뷰 S12).
7. **색과 위치**: "지적 없음"은 초록, 지적 있음은 빨강, 성공 안내("사건을 삭제했습니다")는 중립. G1a 차단 안내는 해당 문장 상자 안에 표시. 새 단계(체크포인트 1, 계산, 초안, 패키지)가 열리면 그 제목으로 스크롤·포커스.
8. **값 표시**: 금액·날짜는 `display` 값(5,000,000원, 2026. 3. 10.)을 함께 보여 줍니다(입력칸은 원값 유지). 상태는 한국어 이름(예: `CHECKPOINT_1` → "사실 확인 대기"), "문장 s1" → "문장 1", "사건 번호" → "작업 ID", 증거 상태 "정상" → "읽음", 계산 섹션 번호 4, `reference_total`("기준일까지 참고 총액")도 표시.

### C. 에이전트 보드 읽기 쉽게
9. 대기·건너뜀·사용자 단계에는 "0.0초 · $0"을 숨깁니다. 맨 위 한 줄 요약: "Meta 모델 호출 N회 · $X · 재생/실호출". 단계에 실행 순서 번호(1~12)와 실행 중 강조. 사용자 확인 단계는 5번째 카드 대신 카드 아래 가는 띠로. 모델 배지를 크게(예: "muse-spark-1.3 · 판독 5건").
10. 게이트에 쉬운 이름: G1a "숫자·이름은 슬롯으로만", G3 "문장마다 증거 표시", G2 "필수 칸 확인", G4 "금액 범위 확인", NAMING "금지 표현 검사". 지적 표시는 `gate_results`에 실제로 있는 게이트 이름만(없으면 "검사"로).
11. 문안 작성 ⇄ 검증 반복(`revisions[]`)을 "문안 작성 → 검증 → 수정 N회"로 보이게.
12. 초안의 `{{…}}` 원문은 기본으로 접고 "고치기"를 누르면 수정 칸이 열리게. E2E 수정 장면은 "고치기"를 누르고 진행.

### D. 동작 안정성
13. 폴링: `setTimeout` 연쇄 + 세대 번호로 오래된 응답 무시, 실행 중에는 버튼 비활성, 실행 중 "샘플 사건 불러오기" 막기.
14. 승인 체크: `PUT` 진행 중에는 체크박스·"승인하고 계속" 비활성, E2E는 `expect_response`로 응답을 기다림.
15. 증거 역할 선택지는 `loan_transfer`·`repayment`·`other`만(화면 이름: 대여 이체·변제 입금·기타). 모르는 `suggested_role`은 `other`.
16. 오류 표시에 `missing_requirements` 포함, 빈 `fix_hint`는 표시 안 함, 업로드한 사건도 "실행" 가능.
17. 접근성: 입력칸·체크박스에 `aria-label`(발화 체크박스는 발화 글을 라벨 안에), 흐린 단계 대비 4.5:1 이상.

### E. README (M3-fix1 리뷰)
18. 기여 표기를 사실대로: "2026-11-02 기준 코드(커밋 76d9cce까지)는 대회 기간에 저장소 소유자가 작성했고, 2026-11-03 M-1부터는 Muse Code(`muse-spark-1.3`)가 구현하고 Claude Code가 지시·리뷰했다"(영어 문장도). 아직 없는 기능(SAM 분할·마스크, 픽셀 가림, 영상 판독, 타임라인 삽화)은 "진행 중"으로 따로 적습니다. 실행 방법에 `python -m venv .venv` 포함, 첫 화면(사건 흐름)과 서버 실행을 기준으로.

### E2. 화면 개선과 E2E가 충돌하지 않게 (교차 리뷰)
- 화면에 보이는 값(5,000,000원, 한국어 상태 이름, 게이트 쉬운 이름, "지적 없음")은 바뀌어도, E2E는 `data-state`(원래 상태 값), `data-gate`(G1a 등), `data-status`(pass/fail) 속성으로 확인합니다.
- 사실 확인 칸은 쉼표·"원"이 붙은 표시 값을 보여 주더라도, `PUT /facts`에는 정수 문자열·ISO 날짜를 보냅니다(고정 입력 규칙과 같은 본문이어야 재생이 맞음).
- "고치기" 수정 칸은 `text_with_slots`를 고칩니다(`rendered_text`가 아님). E2E는 `edit-toggle-{sentence_id}`를 누른 뒤 고칩니다.
- 스크롤이 끝난 뒤 스크린샷을 찍습니다.

### G. 샘플 생성기 (M3-fix1 리뷰)
- PDF 바이트가 실행한 폴더 경로에 따라 달라집니다(`drawImage(str(path))`가 경로 해시로 이미지 이름을 붙임). `reportlab.lib.utils.ImageReader(...)`로 감싸 경로와 무관하게 하고, 두 임시 폴더에서 만든 PDF가 같은지 테스트를 더한 뒤 다시 생성합니다(매니페스트·정답 해시 갱신).
- ffmpeg 호출 `subprocess.run(..., text=True)`에 `encoding="utf-8", errors="replace"`(한글 경로에서 cp949 오류).
- SAMPLE 띠 `ignore_regions`를 실제 띠 높이(37행)와 맞춤. 영어 세트 서명이 한국 세트 서명과 같은 픽셀이 되지 않게 사람별 획 프로그램.

### F. E2E 대상
19. 가짜 서버 대상 E2E는 계속 통과. `E2E_BASE_URL`이 주어지면 실제 백엔드 대상으로 같은 흐름(STUB 띠 없음 확인). 스크린샷은 1920×1080 전체 페이지.
20. 리포트 `reports/M2b-fix1.md`(AGENTS.md 형식, 끝까지 저장 확인). 스크린샷 목록 포함.

## 완료 기준

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m2b-fix1"
cd $WT; & $PY -m pytest -q e2e                      # failed 0 (가짜 서버)
cd "$WT\backend"; & $PY -m pytest -q                 # failed 0, xfail 0
cd $WT; & $PY tools\secret_scan.py                   # 0
Test-Path frontend\legacy-dashboard.html, docs\legacy-dashboard.html   # 둘 다 False
```
