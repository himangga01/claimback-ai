# M1-fix3 이어진 문장 오탐·날짜 단위 회귀·법적 라벨 (수정 지시서)

- 작성: 2026-11-03 13:47 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\m1-fix3`(브랜치 `m1-fix3`, `m1-fix2` 브랜치 위). **Meta 실호출 없음.** 작은 수정이므로 20분 안에 끝냅니다.
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `reports/M1-fix2-review.md`(J1~J7)

## 파일 범위

고쳐도 되는 파일: `backend/app/services/draft_gates.py`, `backend/app/services/naming.py`, `backend/app/services/verification_gate.py`(J6만), 관련 테스트(`test_draft_gates.py`, `test_naming.py`, `test_m1_fix2.py`, 새 테스트). 함수 이름·인자는 바꾸지 않습니다.

## 할 일

1. **J1(차단) 이어진 문장 검사 오탐**: `draft_gates.py`의 `[다요]\s+\S` 규칙이 "원금을 다 갚지 않았다", "필요 없다고 했다", "바쁘다 하며", "갚겠다 말하고"를 막습니다. 문장 끝 어미만 잡게 바꿉니다(참고: `(?:[았었였했겠]다|니다|어요|아요|해요)(?=\s+(?!고|며|하|말|라)\S)`). 이 검사는 실패가 아니라 경고(`fix_hint`만)로 낮춰도 됩니다. 위 4개 문장과 평범한 문장 20개가 통과하는 테스트.
2. **J2(회귀) 날짜 단위**: 월·일·년 규칙이 단위 뒤에 한글이 오면 아예 통과시켜 "삼월에", "오일에", "오년에"가 다시 통과합니다. 단위 뒤에 끝이거나 한글이 아닌 글자 또는 조사(에·의·을·를·이·가·은·는·도·부터·까지·말·초·중)가 올 때 막습니다.
3. **J3(회귀)** "오 백 만을"(띄어 쓴 수사 + 조사, '원' 없음) 다시 막기.
4. **J4 법적 라벨**: `의무를?\s*인정`, `시효`, `편취|기망|횡령`, `권리가\s*있`, `에\s*해당(?:한다|함|하므로)`, `변호인`, `법률\s*(?:비서|전문가)`를 명칭 검사(초안·서류 같은 묶음)에 추가.
5. **J5 상대 날짜**: "두어 달 뒤", "반년 뒤".
6. **J6** `/api/verify`가 `target_date` 없이 호출되면 참고 총액을 채우지 않고(`reference_total` 없음 또는 금액 빈 값) 초안 금액은 남은 원금과만 비교. 기존 `test_api_routes.py`(데모 PASS, `reconciled_amount` 10000000, 400 모양)는 그대로 통과.
7. **J7** 날짜 슬롯 값은 점 형식("2026. 3. 12.")으로 만든 뒤 조사를 맞춤(ISO "2026-03-12"를 넣지 않음). `test_naming.py`의 화면 파일 검사 xfail 표시가 남아 있으면 지움.
8. 리포트 `reports/M1-fix3.md`(AGENTS.md 형식, 끝까지 저장 확인).

## 완료 기준

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m1-fix3"
cd "$WT\backend"; & $PY -m pytest -q          # failed 0, xpass 0
cd $WT; & $PY tools\secret_scan.py             # 0
```
