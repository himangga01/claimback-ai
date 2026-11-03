# M2c 문안 규칙·사실 정리 대조 보강 (수정 지시서)

- 작성: 2026-11-03 14:49 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\m2c`(브랜치 `m2c`, INT-2가 병합된 `main`에서 시작). M4a·M4b·M5·M6와 동시에 진행.
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `reports/INT-2.md`, `reports/INT-2-review.md`(문안·사실 정리 항목), `specs/case-api-contract.md` 6b절, 에이전트 설계 3-4(사실 정리), 3-6(문안 작성), 3-7(검증)
- 배경: INT-2 기록에서 거짓 사실 초안은 사라졌지만, 새 문안 규칙(`DRAFT` 게이트)이 거짓 문장 몇 가지를 통과시키고 참인 문장 몇 가지를 막습니다. 사실 정리의 값 대조에도 빈틈이 있고, 변제기 충돌 질문이 법적 판단을 묻는 꼴입니다.

## 파일 범위

고쳐도 되는 파일: `backend/app/agents/draft_rules.py`, `backend/app/agents/drafter.py`, `backend/app/agents/fact_organizer.py`, `backend/app/agents/deps.py`, 새 프롬프트 파일 `backend/app/agents/prompts/drafter.v2.md`·`fact_organizer.v2.md`(v1은 그대로 두고 기본값만 v2로), 새 테스트 파일 `backend/tests/test_draft_rules_m2c.py`·`test_fact_check_m2c.py`, `backend/tests/fixtures/meta/`(사실 정리·문안 기록 교체), `reports/cost_ledger.jsonl`(기록이 추가).
건드리지 않는 파일: `coordinator.py`·`api/cases.py`(M4a), `reader.py`·`intake.py`·판독 프롬프트(M4b), `packager.py`(M5), `frontend/`·`docs/`·`e2e/`(M6), `backend/app/meta/`, `backend/app/services/`, `specs/`. 기존 테스트 파일은 기대값이 바뀌는 곳만 최소로 고칩니다. 코디네이터를 바꿔야만 되는 일은 하지 말고 리포트에 적습니다.

## 할 일

1. **계산값 슬롯 하나 더**: `contract_interest`(`deps.py:323`, 실제로는 송달 전 법정 이율 계산값)를 `draft_rules.CALCULATED_SLOTS`에 넣어 문안 작성 담당에게 주지 않습니다. 차용증에 이자 약정이 없는데 "약정 이자율 5%"라는 거짓 문장이 나올 수 있습니다.
2. **문안 규칙(`draft_rules.py`) 빈틈**:
   - 인용 슬롯이나 말하기 동사가 있는 문장에는 당사자 이름 슬롯만 허용하고 금액·날짜 슬롯은 거부(인용이 "5월 20일까지 400만 원"인데 슬롯이 4월 10일·500만 원인 문장이 지금 통과).
   - 말하기·약속 표현 목록을 넓힘: "했다/하기로/드리겠/보내겠/답했/물었/돌려드리" 등. `user` 문장의 "…까지 …을 보내기로 했다", `fact` 문장의 "…까지 갚기로 하였다"가 지금 통과.
   - 참인 문장을 막지 않음: `user` 문장의 명사 "요청"·"약속"(예: "여러 차례 갚아 달라고 요청하였으나 받지 못했다"), `fact` 문장의 "약속한 대로 {{loan_date}}에 {{principal}}을 보냈다". 사용자가 `PUT /drafts`로 고친 문장도 같은 규칙을 거치므로 오탐이 데모를 막습니다.
   - 코드 리뷰에서 나온 예문도: 인용 없는 `fact` 문장 "보내 준다고 했다", "보내겠다고 답했다", `user` 문장 "돌려 달라고 했다"는 막고, "약속한 돈을 보내지 않았다"는 통과. 부분 문자열 일치를 어절·어미 단위 판정으로 바꿉니다.
   - 위 예문 전부를 테스트로 고정(거짓 통과 0, 참 차단 0).
3. **문안 품질(`drafter.v2.md`)**: 문장마다 완결된 한 문장(INT-2 기록의 s2처럼 "…말하며 "인용"."으로 끝나지 않게), 서술은 "합니다"체(편철 문구와 같게), `user` 문장은 증거로 확인되지 않는 사실에만(증거 문장과 같은 내용을 되풀이하지 않음). 프롬프트에 샘플 이름·금액·날짜를 넣지 않습니다. 규칙 검사로도 잡을 수 있는 것(같은 슬롯 조합을 되풀이한 `user` 문장, 인용 뒤에 끝나는 문장)은 `DRAFT` 게이트에 넣습니다.
4. **사실 정리 값 대조(P5) 빈틈** `fact_organizer.py`:
   - 근거가 없거나 잘못된 근거(없는 `ex_id`·`item_id`)로 낸 값은 충돌로 표시하고 질문.
   - 이름·주소·전화번호도 인용한 판독 원문과 대조(공백·괄호 차이는 무시).
   - 코드가 찾은 충돌은 그 칸에 질문을 만들어 사용자에게 묻습니다.
   - 근거 항목에 기계값(`normalized`)이 없으면 원문의 월·일로 대조.
5. **변제기 충돌의 틀(제품 규칙)**: 나중에 한 "언제까지 갚겠다"는 말은 변제기 변경이 아니라 `repay_promise` 발화입니다. 변제기 칸의 근거로 그런 발화를 인용하지 않고(INT-2 기록은 "4월 25일" 발화를 2026-04-10의 근거로 듦), "변제기가 변경되었는지" 같은 법적 판단 질문을 만들지 않습니다. 충돌 메모와 질문은 "증거에 나온 날짜가 서로 다릅니다: 2026. 4. 10.(갑 제6호증), 4월 25일(갑 제2호증 대화)"처럼 사실만.
6. **프롬프트 버전**: 바뀐 프롬프트는 v2 파일로 두고 감사 기록(`audit_log`)에 버전이 남는지 확인(설계 4-4).
7. **다시 기록**: INT-2 판독 기록은 그대로 두고(판독 요청을 바꾸지 않음), `META_MODE=record`, `META_LEDGER_PATH=C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl`, `READER_CONCURRENCY=1`, `run_id` = 사건 ID로 샘플 사건을 `CHECKPOINT_2`까지 기록해 사실 정리·문안 fixture를 교체합니다(더는 안 쓰는 이전 것은 지움). 바로 재생으로 다시 돌려 누락 0, 두 사건 ID 동일성 테스트 통과. 기록된 문안을 리포트에 그대로 붙이고(슬롯 채운 문장), 위 2·3·5가 지켜졌는지 적습니다.
8. 리포트 `reports/M2c.md`(AGENTS.md 형식, 끝까지 저장 확인): 실호출 수·비용, 규칙 예문 표(거짓 통과·참 차단 전후).

## 하지 않을 일

- 판독·코디네이터·편철·화면 수정, `specs/` 수정, `.env`, 키 출력, 커밋·푸시

## 완료 기준

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m2c"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q                         # failed 0 (키 없이, 재생)
cd $WT; & $PY tools\m0_spike.py --mode replay --probes all     # 9/9, 종료 코드 0
git checkout -- reports/M0-spike.json
& $PY tools\secret_scan.py                                     # 0
```
