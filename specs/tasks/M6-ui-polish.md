# M6 화면 마무리 (작업 지시서)

- 작성: 2026-11-03 14:47 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\m6`(브랜치 `m6`, INT-2가 병합된 `main`에서 시작). M4a·M4b·M5와 동시에 진행. **Meta 실호출 없음.**
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `specs/case-api-contract.md`(특히 5장, 6a절, 6b절), `reports/M2b-fix1-review.md` 3절, `reports/INT-2.md`, `reports/INT-2-review.md`(화면 항목)
- 배경: 실제 백엔드(재생)로 E2E가 통과했지만, 스크린샷에서 데모에 그대로 보이는 화면 결함이 나왔습니다. 화면만 고치며 모델 요청은 바꾸지 않습니다(재생 기록이 그대로 맞아야 함).

## 파일 범위

고쳐도 되는 파일: `frontend/case.js`, `frontend/case.css`, `frontend/index.html`, 같은 변경을 `docs/`의 같은 파일에, `e2e/test_case_flow.py`, `e2e/stub_server.py`(없는 엔드포인트에 404를 돌려주는 부분만), `e2e/` 아래 새 테스트.
건드리지 않는 파일: `backend/`(M4a·M4b·M5가 고치는 중), `specs/`, `sample_evidence/`. 백엔드 응답이 약속과 다르면 고치지 말고 리포트에 적습니다.

## 할 일

1. **화자 표시**: 발화 목록이 화자를 모를 때 "강조 null: …"로 보입니다. `speaker`가 `null`이면 같은 `ex_id`·`item_id`의 판독 항목 `side`로 "오른쪽 말풍선"/"왼쪽 말풍선", 그것도 없으면 "화자 미상"으로 보여 줍니다(이름을 추정해 넣지 않음). 문자열 `"null"`도 같은 처리.
2. **충돌 표시**: `Review.conflicts[]`가 객체(`{fields, note}`)라 JSON 원문이 보입니다. 칸 이름(`Review.fields[].label`)과 `note`로 "변제기: 최초 변제기와 이후 변경 약속일이 다르게 확인됨"처럼 문장으로. 문자열이 와도 그대로 표시.
3. **모델 호출 수**: 보드 머리 "Meta 모델 호출 N회"가 단계 수를 셉니다(실제 8회인데 3회). 판독은 증거별 `substeps` 중 모델을 쓴 것, 나머지는 `attempts`를 합해 실제 호출 수로. 재생이면 "(재생)"을 붙임.
4. **게이트 6종**: `gate_results`의 `NAMING`·`DRAFT`도 이름을 붙여 표시("금지 표현 검사", "문안 규칙 검사"). 실패 줄은 빨강, "지적 없음"은 회색으로 구분.
5. `reports/M2b-fix1-review.md` 3절 남은 항목: 실행이 끝난 뒤 도착한 폴링 응답이 화면을 되돌리지 않게(`!S.running` 확인), 실행 중 "사건 삭제" 비활성, 강조 발화는 첫 `repay_promise`를 미리 선택(약속 5장 고정 입력 규칙과 같게), 표시 형식 입력("5,000,000원")을 정수로 변환, 텍스트 칸에서 표시 값 중복 제거, 긴 모델 배지 줄바꿈, E2E `sentence-` 선택자가 목록 상자까지 잡는 문제.
6. 6a절 대비(M4a·M5가 더하는 응답이 오면 보여 주고, 없거나 404면 칸을 숨김): 가림 미리보기(`GET /redactions`의 `previews`, 원본과 나란히), 감식 결과(`GET /segments`의 박스를 미리보기 위에 판독 박스와 다른 색으로), 패키지의 `exhibits.pdf`·`evidence_list.pdf` 링크와 G1b 줄. 가짜 서버용 예시가 없으면 가짜 서버는 404를 돌려주고 화면은 숨김.
7. 첫 화면(`frontend/index.html`)의 고정 문구 "25/25 Tests Passed"(`reports/M-1-review.md` R10)를 빼거나 실제 값으로.
8. 테스트: 가짜 서버 E2E와 실제 백엔드(재생) E2E 모두 통과. 위 1~4를 E2E에서 확인(화면에 "null" 글자 없음, `{"` 글자 없음, 호출 수 = 사건 응답에서 계산한 값). 스크린샷을 `e2e/artifacts/real/`에(git 제외).
9. 리포트 `reports/M6.md`(AGENTS.md 형식, 끝까지 저장 확인).

## 하지 않을 일

- 백엔드·프롬프트 수정, 재기록, 실호출, `specs/` 수정, `.env`, 키 출력, 커밋·푸시

## 완료 기준

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m6"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q                         # failed 0
cd $WT; & $PY -m pytest -q e2e                                # 가짜 서버 대상 통과
# 재생 서버(META_MODE=replay, 127.0.0.1 빈 포트)를 띄운 뒤:
$env:E2E_BASE_URL = "http://127.0.0.1:<포트>"; & $PY -m pytest -q e2e   # 실제 백엔드 대상 통과
& $PY tools\secret_scan.py                                     # 0
```
