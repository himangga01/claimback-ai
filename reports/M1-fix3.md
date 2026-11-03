# M1-fix3 보고서 (이어진 문장 오탐·날짜 단위 회귀·법적 라벨)

- 작성: 2026-11-03, Muse Code (`muse-spark-1.3`), 브랜치 `m1-fix3`
- 지시서: `specs/tasks/M1-fix3-runon-labels.md` (참고: `reports/M1-fix2-review.md` J1~J7)
- Meta 실호출 없음.

## 1. 한 일

- J1(차단): G3 이어진 문장 검사를 `[다요]\s+\S`에서 문장 끝 어미 패턴
  `(?:[았었였했겠]다|니다|어요|아요|해요)(?=\s+(?!고|며|하|말|라)\S)`로 좁힘.
  "원금을 다 갚지 않았다", "필요 없다고 했다", "바쁘다 하며 전화를 끊었다",
  "갚겠다 말하고 연락이 끊겼다"와 평범한 문장 20개가 통과하고,
  실제 이어진 문장("돈을 빌려주었다 갚지 않았다")은 계속 차단됨. 실패 유지는
  H7 테스트가 요구하므로 경고로 낮추지 않음.
- J2(회귀): 월·일·년 규칙 뒤에 끝·비한글·조사(부터·까지·에·의·을·를·이·가·은·는·도·
  말·초·중)가 오면 차단. "삼월에", "오일에", "오년에" 차단. "일일이"는
  부정형 전방탐색으로 제외해 H3 통과 유지.
- J3(회귀): 수사-단위 규칙에 만·억·조를 넣어 "오 백 만을" 차단.
- J4: 명칭 검사(초안·서류 공통 묶음)에 7종 추가: `의무를?\s*인정`, `시효`,
  `편취|기망|횡령`, `권리가\s*있`, `에\s*해당(?:한다|함|하므로)`, `변호인`,
  `법률\s*(?:비서|전문가)`.
- J5: 상대 날짜에 "두어 달"(두어 + 달·주·해)과 "반년" 추가.
- J6: `target_date` 없이 검증하면 참고 총액을 비움
  (`calculation.reference_total.amount = 0`, 이자 0, 구간 이자 0)하고
  초안 금액은 남은 원금과만 비교. `total_claim_amount`는 남은 원금.
- J7: 슬롯 값이 ISO 날짜면 점 형식("2026. 3. 12.")으로 바꾼 뒤 조사 맞춤.
  `test_naming.py`의 화면 파일 검사 xfail 제거.

## 2. 바꾼 파일

- `backend/app/services/draft_gates.py`: J1(run-on 정규식), J2(`_DATE_JOSA`+
  월·일·년), J3(만·억·조), J5(두어·반년), J7(`_to_dotted_date`)
- `backend/app/services/naming.py`: J4 패턴 7종
- `backend/app/services/verification_gate.py`: J6 (`target_date is None` 분기)
- `backend/tests/test_m1_fix3.py`: 새 회귀 테스트 11개
- `backend/tests/test_naming.py`: xfail 1개 제거
- `reports/M1-fix3.md`: 이 문서

## 3. 실행 명령과 결과

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m1-fix3"
cd "$WT\backend"; & $PY -m pytest -q
# 181 passed in 3.88s (failed 0, xpass 0; 기존 169+1 xpass에서 11개 추가·1개 정상화)
cd $WT; & $PY tools\secret_scan.py
# secret_scan: clean (exit 0)
```

J6 확인: 데모 샘플로 `/api/verify`를 기준일 없이 호출하면 200,
`reconciled_amount` 10000000, `reference_total.amount` 0.
기존 `test_api_routes.py` 7개 전부 통과.

## 4. 실호출 비용

없음. 모델 호출 0회, 비용 $0 (`reports/cost_ledger.jsonl` 추가 없음).

## 5. 남은 문제와 지시서와의 차이

- J1을 경고로 낮추지 않고 실패로 유지 (H7 `test_h7_missing_period_warns`가
  실패를 요구; 지시서가 허용한 선택지 중 좁히기만 적용).
- J2에서 목록 외 조사(예: 로·으로) 뒤의 날짜는 통과 ("오일로부터" 통과).
  지시서 조사 목록을 그대로 따름.
- J6에서 `calculation` 객체는 유지하고 금액만 0으로 둠. 청구취지 문장
  (`rate_clause.sentence`)이 기준일 없이도 필요해서 `None`으로 지우지 않음.
- J7 변환은 값이 정확히 ISO(앞뒤 공백 허용)일 때만 적용.

## 6. 스펙 변경 제안

없음. 지시서 범위 안에서 해결됨.
