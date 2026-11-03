# M1-fix2 리포트: 검사 규칙·서류 마무리

- 작성: 2026-11-03, Muse Code (`muse-spark-1.3`)
- 작업 트리: `C:\2026_project\claimback-wt\m1-fix2` (브랜치 `m1-fix2`)

## 1. 지시서와 작업 요약

- 지시서: `specs/tasks/M1-fix2-gates-docs.md` (작성 2026-11-03 13:32 KST, Claude)
- 함께 읽은 문서: `AGENTS.md`, `reports/M1-fix1-review.md`(H1~H14)
- 수행 내용: 리뷰 잔여 항목 H1~H13(H13a 원칙 포함)을 지시서대로 구현하고, 공격 문자열표를
  회귀 테스트로 추가했으며, 기존 G1a 변조 100건 차단과 고정 예시 5건을 유지했다.
  Meta 실호출은 없다. `specs/`, `AGENTS.md`, `docs/`, 다른 리포트는 건드리지 않았다.

항목별 구현:

- H1: 수사+어림(`여|쯤|가량|정도|남짓|씩`)+단위(`_APPROX_RE`), 수사 낱말+단위 낱말
  (`_NUMERAL_UNIT_RE`, `원|일|개월|년|주|번|월`)을 `check_g1a`에서 차단한다.
- H2: 상대 날짜에 `몇|석|넉`+`달|주|해`, `[한두세네]`+`달|주|해`를 추가하고,
  접미사 앞에 `(?:쯤|정도)?`를 허용한다. `만에`는 기간 표현으로 보고 차단 대상에서 뺐다.
- H3: `만에` 단독 크기음절(단위 뒤에만 인정), 낱말 첫머리 `조` 제외, 날짜 규칙 한글 앞뒤
  확인, `그제(?!야|서)`, `주|달|해|날` 뒤 조사 확인, `승소`/`패소` 붙여 쓴 것만 차단한다.
- H4: 날짜값(`2026. 4. 2.`)은 `일` 읽기(받침 있음·리을)로, 값 끝이 숫자면 숫자 읽기,
  `%`는 `퍼센트`(받침 없음)로 판정한다. `X(Y)` 꼴 정리, `의|부터|서|라는|라고` 연결
  조사 처리(예: `으로부터`, `과의`, `이라는`→`라는`), 주소 끝 `0`은 `영`으로 처리한다.
- H5·13a: 초안 검사와 서류 검사가 같은 금지어 묶음(`_SHARED_PATTERNS`)을 쓴다.
- H6: `lawyers?`·`attorneys?`, `채무의? 존재를? (인정|승인)`, `사기(를|죄|꾼)`,
  `법적 (책임|의무)`, `청구할 수 있`을 추가하고, 영어 이름 부분일치는 ASCII 낱말 경계로
  검사한다(`bravery` 속 `Avery` 오탐 해소, `Avery가` 등은 계속 차단).
- H7: G3 분할을 따옴표 밖 ` [.!?](?=\s|$) ` 기준으로 바꾸고, 앞에 오는 `[[EX:n]]`은
  그 문장에 붙이며(뒤로 넘기지 않음), 마침표 없이 이어진 두 문장을 지적한다.
- H8: `check_g1a`의 `existing_exhibits`를 기본값 없는 필수 키워드 인자로 바꾸고,
  인용(`{{quote:..}}`) 검사를 항상 수행한다. 기존 테스트 호출부를 전수 갱신했다.
- H9: 약정 0%는 약정 없음으로 본다. 저율 약정 보류는 마지막 충당일이 변제기 전일 때만
  하고, 약정 이자가 이미 다 충당됐으면 보류하지 않는다.
- H10: `as_of` 없음은 계산 기준일 폴백을 쓰지 않고 이자·총액을 비운다(PDF `금 ____원`,
  전자소송 `____`, `(… 기준)` 미표시, 깨진 괄호 제거). 전자소송 경로도
  `as_of=req.target_date`를 넘긴다.
- H11: PDF에 넣기 전에 사용자·모델 문자열(이름·연락처·주소·`fact_sentences`)을 XML
  이스케이프한다. `fact_sentences`가 있어도 약정 이율 문장·남은 원금·변제기 절을
  유지한다(전자소송 문구는 평문 그대로, 13a).
- H12: `rate_clause` 이율값을 정수형 Decimal로 정규화해 문자열이 `5`·`12`·`20`이
  되게 한다(아래 5번 편차 참조). 비정수 약정(예: 7.5%)은 그대로 둔다.
- H13: `약정 변제기가 지났음에도 … 변제기 이후` 반복을 정리했다(기본 변제 독촉문을
  `채무자는 현재까지 …` 로 변경, 소제목 `3. 변제기 이후 상황`은 유지).
- H14: 공격 문자열표 전수를 `test_m1_fix2.py`에 넣었다.

## 2. 생성·변경 파일

- 변경: `backend/app/services/draft_gates.py` (H1·H2·H3·H4·H6 이름·H7·H8)
- 변경: `backend/app/services/naming.py` (H3 승패소·H5·H6)
- 변경: `backend/app/services/verification_gate.py` (H9·H12)
- 변경: `backend/app/services/pdf_compiler.py` (H10·H11·H13)
- 변경: `backend/app/api/routes.py` (전자소송 경로 `as_of` 전달 1줄, H10)
- 변경: `backend/tests/test_draft_gates.py`, `backend/tests/test_m1_fix1.py`
  (H8 호출부 갱신, K5 기준일 없음 단언 보강)
- 신규: `backend/tests/test_m1_fix2.py` (23개 테스트), `reports/M1-fix2.md` (본 문서)
- 참고: 편집 도구 줄바꿈 제약을 피하려고 위 7개 파일의 줄바꿈을 CRLF→LF로 정규화했다.
  `git diff` 내용에는 실제 변경만 표시된다(autocrlf). 커밋·푸시는 하지 않았다.

## 3. 실행 명령과 결과

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m1-fix2"
cd "$WT\backend"; & $PY -m pytest -q
# 결과: 169 passed, 1 xpassed, failed 0 (3.71초)

cd "$WT\backend"; & $PY -m pytest -q tests/test_draft_gates.py::test_g1a_100_tampers_all_blocked tests/test_calculation_kr.py -k "100_tampers or fixed_example"
# 결과: 6 passed (G1a 변조 100건 100% 차단 + 고정 예시 5건 유지)

cd $WT; & $PY tools\secret_scan.py
# 결과: secret_scan: clean (exit 0)

git status --short
# 결과: 위 2번의 변경·신규 파일만 표시, reports/M0-spike.json 변경 없음(복원 불필요)
```

- H4 조사 테스트는 24건(지시서 요구 15건 이상)을 `test_h4_josa_cases`에 넣었다.
- `1 xpassed`는 `test_naming_frontend_app_js_clean`(비strict xfail)이며 실패가 아니다.
  새 금지어 패턴으로도 `frontend/index.html`, `frontend/app.js`, `README.md`는 clean이다.

## 4. 실호출 내역

- Meta API 실호출 0회, 비용 $0. `META_MODE` 기본값(replay) 그대로 실행했고,
  `reports/cost_ledger.jsonl`에 추가한 내역이 없다.

## 5. 미해결 문제와 지시서·스펙과의 편차

1. H12 스키마형: 지시서는 `pre_service_rate`·`post_service_rate`를 "소수 없는 문자열"로
   적었으나, 스키마(`RateClause`)가 Decimal이고 스키마 파일이 작업 범위 밖이라 타입은
   유지했다. 대신 정수형 Decimal(`5`·`6`·`12`·`20`)과 `_canon_rate`로 `str()`이
   `5`·`12`·`20`이 되게 했다. 기존 `== Decimal("5.0")` 단언은 수치 동등이라 통과한다.
2. H10 검증 내부값: `target_date` 없음일 때 검증 게이트의 내부 계산(마지막 사건일 기준)은
   그대로 두고, 서류 표시만 비웠다. "마지막 사건일로 계산하지 않고"를 서류 기준일
   폴백 제거+공란 표시로 해석한 것이다. `/api/verify` 응답값 자체는 기존과 같다.
3. H7 경고 등급: `GateResult`에 경고 등급이 없어 "마침표 없이 이어진 두 문장" 지적을
   finding(불통과)으로 구현했다. 스키마 변경 없이 할 수 있는 유일한 형태다.
4. H8 호출 규격: `check_g1a(..., *, existing_exhibits)`로 바뀌어 위치인자 호출은
   `TypeError`가 난다. 같은 트리의 테스트는 전수 갱신했으나, M2a 쪽 호출부가 이 규격을
   따르면 병합 시 확인이 필요하다(brief의 "기존 호출부가 깨지지 않게"는 키워드 명시
   호출로 이해했다).
5. H4 bare `(Y)`: `X(Y)` 꼴(`은(는)` 등)만 정리했고, `X` 없는 `{{v}}(는)` 같은 입력은
   지시서 범위가 아니라 그대로 둔다.
6. H11 서류 중복: `fact_sentences`가 있어도 필수 문장을 살리려고 자동 생성 대여·변제
   문단(`lend_part`·`item2`)을 함께 싣는다. 대여일·변제기 등이 사실 문장과 중복될 수
   있으나 누락보다 낫다고 판단했다.
7. H2 `만에`: `열흘 만에` 같은 기간 표현도 이제 통과한다. 지시서 H3의 "(기간 표현은
   허용)"을 전체 `만에` 접미사에 적용한 것이다.
8. 작업 중 실수로 편집 스크립트 버그(`open(wb)` 후 같은 파일 읽기)로 위 7개 파일을
   비웠다가 즉시 `git checkout --` 으로 복원한 뒤 같은 편집을 재적용했다. 최종
   `git diff`에는 의도된 변경만 있으며, 커밋하지 않아 히스토리 오염은 없다.

## 6. 스펙 변경 제안 (직접 고치지 않음)

1. G1a 상대 날짜에서 `만에` 기간 표현(예: `몇 달 만에`, `열흘 만에`)을 허용으로 명시.
2. 약정 이율 0%는 약정 없음과 동등, 저율 약정 보류는 미충당 약정 이자 구간이 있을
   때(마지막 충당일이 변제기 전)로 한정.
3. 기준일 없음: 서류 이자·총액은 `금 ____원` 공란, `(… 기준)` 미표시, 깨진 괄호 금지.
4. 초안 검사와 서류 검사의 금지어 묶음 단일화(현행 `_SHARED_PATTERNS` 유지).
5. `rate_clause` 이율 표시 형식 `5`·`12`·`20`(스키마 Decimal 유지, 정수 정규화).
6. G3 문장 나누기: 따옴표 안 구두점 무시, 앞 태그는 해당 문장에 귀속, 마침표 없는
   연결 문장은 경고(finding) 명시.
7. `check_g1a(..., *, existing_exhibits)` 필수 키워드 인자화와 M2a 호출부 갱신을
   에이전트 설계·과제 brief에 반영.
