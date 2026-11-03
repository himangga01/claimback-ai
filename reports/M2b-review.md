# M2b 리뷰 (Claude + 서브에이전트 교차 리뷰)

- 작성: 2026-11-03 13:25 KST, Claude Code
- 대상: 브랜치 `m2b-ui`(기준 6a7c345), `reports/M2b.md`
- 실행: Muse Code 12:58~13:09(11분), 종료 코드 0, Meta 실호출 0회
- 리뷰 방식: Claude가 완료 기준 재실행과 스크린샷 육안 확인. 서브에이전트 2개가 따로 검토(① 데모 가치·화면 명료성·제품 규칙, ② 코드·약속 충실도·실제 백엔드에서의 E2E)한 뒤 서로의 결과를 교차 확인. 교차 과정에서 ①이 두 판단을 정정함(오프라인 Pages에 앱이 함께 보임, EX1 박스 어긋남은 예시 좌표가 아니라 렌더링 버그).
- 판정: **통과(병합), 수정 지시서 M2b-fix1을 M2a와 동시에 진행.** 첫 화면 교체, 에이전트 보드, 판독 박스 겹쳐 그리기, 계산 표, G1a 차단 장면, 서류 패키지, 가짜 서버, E2E가 동작하고 제품 규칙(배지·고지 문구 원문, 금지 명칭 0건)을 지킵니다. 다만 E2E가 실제 백엔드에서 깨질 고정 ID 가정과 병합 뒤 깨지는 테스트 4개, 데모에 보이는 박스 어긋남·`hidden` 무시는 `specs/tasks/M2b-fix1-ui-integration.md`로 고칩니다.

## 1. 완료 기준 재실행 (13:10 KST)

```powershell
cd C:\2026_project\claimback-wt\m2b-ui
& $PY -m pytest -q e2e          # 1 passed (8.3초, 두 번 돌려도 같음)
& $PY tools\secret_scan.py      # clean
(Get-ChildItem e2e\artifacts\*.png).Count   # 10
Select-String frontend\index.html,frontend\case.js 'cdn.','unpkg','jsdelivr'   # 0건
cd backend; & $PY -m pytest -q  # 4 failed (test_sample_evidence.py: frontend/app.js 이동), 109 passed
```

스크린샷 확인(01 보드, 02 체크포인트, 06 G1a 차단 등): 4개 역할 카드와 증거별 판독 진행, 이체증 위 박스, 충당 표(이자 14,383원·원본 985,617원·남은 원금 4,014,383원), "500만 원" 수정 시 G1a 지적과 승인 막힘.

## 2. 결함 (M2b-fix1로)

| ID | 등급 | 내용 |
|---|---|---|
| U1 | 차단 | E2E가 `highlight-EX1-item4`를 고정하고 전화번호만 채움 → 실제 백엔드에서 Spark 항목 ID가 달라 재생 요청이 맞지 않음 |
| U2 | 차단 | `frontend/app.js` 이동으로 `test_sample_evidence.py` 4개 실패, `test_naming.py` xfail이 파일 없음으로만 통과(검사 공백) |
| U3 | 수정(Pages에선 차단) | `.app{display:flex}`, `.viewer img{display:block}`가 `hidden`을 덮어 오프라인 Pages에 안내와 앱이 함께 보임 |
| U4 | 수정 | 박스 층이 스크롤되는 보기 영역만 덮어 긴 이미지(EX1·EX2·EX6)에서 박스가 약 21% 위로 어긋남 |
| U5 | 수정 | 문장 ID(s1~s4)·`item1`·`revisions` 존재 가정, 승인 체크와 PUT 경쟁, 폴링에 진행 중 보호 없음 |
| U6 | 수정 | 역할 선택지에 백엔드 스키마가 거부하는 값(`loan_agreement`, `chat`) |
| U7 | 수정 | 게이트 결과가 없어도 "G1a"로 표시 |
| U8 | 수정 | "지적 없음"이 빨간색, 차단 안내가 문장에서 2,700px 위, 표시 값 대신 원값(5000000), 영어 상태 이름 |
| U9 | 수정 | 보드에 "0.0초 · $0" 약 20개, 사용자 확인이 5번째 카드, 실행 비용·모델 이름 요약 없음, 게이트 코드만 표시 |
| U10 | 수정(규칙) | 증거 상태 "정상"(진본 확인처럼 읽힘), "사건 번호"(법원 사건번호처럼 읽힘) |
| U11 | 수정 | 링크 없는 예전 대시보드가 Pages에 공개(가짜 수치·법 준수 주장) → 삭제로 결정 |
| U12 | 수정 | 입력칸·체크박스 `aria-label` 없음, 박스 테두리 대비 1.4:1 |
| U13 | 사소 | 오류에 `missing_requirements` 미표시, 빈 `fix_hint` "()", 계산 섹션 번호, `reference_total` 미표시 |

확인한 정상 동작: 서버·모델 문자열은 모두 `textContent`로 넣어 XSS 없음, `frontend/`와 `docs/` 사본 바이트 동일, 실제 G1a도 "500만 원을 보냈습니다."를 막음(`draft_gates.py`), 화면 글자 금지 명칭 검사 10단계 0건.

## 3. 비용

앱 실호출 0. 크레딧 $116.35(13:20).
