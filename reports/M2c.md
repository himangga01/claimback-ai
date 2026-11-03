# M2c 리포트: 문안 규칙·사실 정리 대조 보강 (Muse Code)

- 작성: 2026-11-03 (KST), Muse Code (`muse-spark-1.3`)
- 작업 트리: `C:\2026_project\claimback-wt\m2c` (브랜치 `m2c`)
- Python: `C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe` (공유 venv, 신규 생성 없음)
- 지시서: `specs/tasks/M2c-draft-facts-quality.md` (먼저 읽음: `AGENTS.md`, 지시서, `reports/INT-2.md`, `reports/INT-2-review.md` 문안·사실 정리 항목, `specs/case-api-contract.md` 6b절, 에이전트 설계 3-4·3-6·3-7·4-4)

## 1. 지시서와 한 일

- 1 (계산값 슬롯): `contract_interest`를 `draft_rules.CALCULATED_SLOTS`에 넣어 6종으로. `drafter_allowed_slots`에서 빠지므로 문안 입력 `slots`와 G1a 허용 슬롯에서 제외된다. 코디네이터 수정 없이 해결.
- 2 (문안 규칙): 인용 슬롯이나 말하기·약속 표현이 있는 문장에는 당사자 이름 슬롯만 허용하고 금액·날짜 7종(`principal`, `loan_date`, `due_date`, `repaid_amount`, `repaid_date`, `agreed_rate`, `demand_date`)을 거부. 발화 판정을 부분 문자열에서 어절 단위로 바꿈(인용 어미 `다고/라고/자고/냐고`+서술 동사 `했다/하였다/…`, `기로`, `주겠/갚겠/보내겠/드리겠`, `말하`, `언급하/언급했`, `답하/답했`, `묻/물었` 계열). 명사 `요청`·`약속`은 목록에서 빼 참 문장을 통과. 지시서·리뷰의 예문 전부를 테스트로 고정.
- 3 (문안 품질): `drafter.v2.md`에 완결된 한 문장·인용 뒤 서술(`…라고 했습니다.`)·`합니다`체·`user` 문장은 증거 미확인 사실에만·슬롯 조합 반복 금지를 명시. 규칙으로 잡히는 것(`user` 슬롯 조합 반복, 인용 뒤 끝맺음)은 `DRAFT` 게이트에 추가.
- 4 (사실 정리 값 대조): 근거 없는 값·잘못된 근거(없는 `ex_id`·`item_id`) 값은 충돌+질문. 이름·주소·전화번호도 인용 판독 원문과 대조(공백·괄호 무시, 전화는 숫자만). 코드가 찾은 충돌은 그 칸에 질문 자동 생성(모델 질문과 중복 방지). `normalized`가 없는 근거 항목은 원문 월·일로 대조.
- 5 (변제기 틀): 프롬프트에 문서 근거(차용증·이체확인증)만·대화 발화 인용 금지·`repay_promise` 분리·사실형 메모/질문을 명시. 코드 충돌 메모는 `증거에 나온 날짜가 서로 다릅니다: 2026. 4. 10.(갑 제6호증), 4월 25일(갑 제2호증 대화)` 형식.
- 6 (프롬프트 버전): v1 파일은 그대로 두고 `drafter.py`·`fact_organizer.py` 기본값만 v2로. 감사 기록에 `reader.v1`, `fact_organizer.v2`, `drafter.v2`가 남음을 기록 실행에서 확인.
- 7 (다시 기록): 판독 요청을 바꾸지 않고 판독 5건은 INT-2 기록을 재생으로 재사용(fixture 무변경), 사실 정리·문안만 실호출 기록. 구 fixture 3개 삭제·신규 2개. 재생 누락 0·두 사건 ID 동일성 통과.
- 8: 이 리포트.

### 규칙 예문 표 (전 = HEAD 코드 실측, 후 = 새 코드·테스트)

거짓 통과 8건 → 전원 차단, 참 차단 3건 → 전원 통과.

| 예문 | 기대 | 전 | 후 |
|---|---|---|---|
| `fact` "약정 이자율 {{contract_interest}}를 정했다" (A1) | 차단 | 통과 | 차단 |
| `fact` 인용 있는데 슬롯이 `due_date`·`principal` (인용 불일치) | 차단 | 통과 | 차단 |
| `user` "…까지 …을 보내기로 했다" | 차단 | 통과 | 차단 |
| `fact` "…까지 갚기로 하였다" | 차단 | 통과 | 차단 |
| `fact` "보내 준다고 했다" | 차단 | 통과 | 차단 |
| `fact` "보내겠다고 답했다" | 차단 | 통과 | 차단 |
| `user` "돌려 달라고 했다" | 차단 | 통과 | 차단 |
| `fact` "돌려드리겠다고 했다" | 차단 | 통과 | 차단 |
| `fact` "언제 갚을 수 있는지 물었다" | 차단 | 통과 | 차단 |
| INT-2 s2 "…갚겠다고 말하며 인용." (인용 끝맺음) | 차단 | 통과 | 차단 |
| INT-2 s4 `user` 문장 (s1과 같은 슬롯 조합) | 차단 | 통과 | 차단 |
| `user` "여러 차례 갚아 달라고 요청하였으나 받지 못했다" | 통과 | 차단 | 통과 |
| `fact` "약속한 대로 {{loan_date}}에 {{principal}}을 보냈다" | 통과 | 차단 | 통과 |
| `user` "약속한 돈을 보내지 않았다" | 통과 | 차단 | 통과 |

### 기록된 문안 (슬롯 채운 문장 그대로, `case_afe3f65d2045`)

- s1 `[fact]`: 탁나루는 "네, 병원비로 500만 원이 필요해요. 4월 10일까지 갚을게요."라고 했습니다[갑 제1호증].
- s2 `[fact]`: 서가온은 탁나루에게 2026. 3. 10.에 5,000,000원을 송금한 내역이 확인됩니다[갑 제4호증].
- s3 `[fact]`: 탁나루가 2026. 5. 1.에 1,000,000원을 지급한 내역이 확인됩니다[갑 제5호증].
- s4 `[user]`: 2026. 4. 10.까지 잔액을 지급하는 내용입니다(사용자 진술).

지시서 2·3·5 준수 여부: (2) 인용문 s1은 이름 슬롯만 사용, 인용·발화 문장의 금액·날짜 슬롯 0, 계산값 슬롯 0, 발화 묘사는 인용 있는 s1에만. (3) 4문장 모두 완결(`했습니다/확인됩니다/내용입니다`의 `합니다`체), s4는 증거 미확인 사실(잔액 지급 내용)이며 슬롯 조합 `{due_date}`가 유일. (5) `due_date` 근거는 `[EX6:item22]` 문서 하나뿐이고 `conflicts: []`, `questions: []`라 법적 판단 질문 없음. 초안이 6개 게이트를 수정 0회로 통과.

## 2. 만든·고친 파일

새 파일:

- `backend/app/agents/prompts/drafter.v2.md`, `fact_organizer.v2.md` (v1은 그대로)
- `backend/tests/test_draft_rules_m2c.py` (10개), `test_fact_check_m2c.py` (12개)
- `backend/tests/fixtures/meta/4a14271a*.json` (문안 v2), `93427d37*.json` (사실 정리 v2)
- `.local/m2c_record_run.py` (기록 스크립트, git 제외), `reports/M2c.md` (이 리포트)

고친 파일(지시서 범위 안만):

- `backend/app/agents/draft_rules.py`: 계산값 6종·어절 단위 발화 판정·인용문 슬롯 제한·`user` 중복·인용 끝맺음
- `backend/app/agents/fact_organizer.py`: 무근거·이름 대조·자동 질문·월일 대조·사실형 메모 + v2 전환
- `backend/app/agents/drafter.py`: 버전 2줄만 v2로
- `backend/tests/test_case_contract.py`: 가짜 s2와 P1 통과 예문 s1을 DRAFT 통과형으로 교체 3줄(인용문에 `{{due_date}}` 금지·인용 끝맺음 금지 때문)
- `backend/tests/fixtures/meta/` INT-2 사실 정리·문안 3개 삭제(`cc93db63*`, `47c6cd45*`, `5a8cab30*`)

건드리지 않음: `deps.py`(수정 불필요 — `contract_interest` 값은 편철 호환용으로 유지, 허용 슬롯에서만 제외), `coordinator.py`·`api/cases.py`(M4a), `reader.py`·`intake.py`·판독 프롬프트(M4b), `packager.py`(M5), `frontend/`·`docs/`·`e2e/`(M6), `backend/app/meta/`·`backend/app/services/`·`specs/`·다른 리포트·`.env`(읽기·생성 없음). 판독 fixture 5개 무변경.

## 3. 실행한 명령과 결과

공유 venv·키 없이(기록 1회만 키 사용, 값은 출력·기록 안 함):

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m2c"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q
# 285 passed in 22.99s (failed 0; 기록 전에는 v2 fixture가 없어 재생 2건만 failed가 정상)
cd "$WT\backend"; & $PY -m pytest -q tests/test_case_replay.py::test_replay_full_flow_to_checkpoint_2 tests/test_case_replay.py::test_replay_identical_across_case_ids
# 2 passed in 1.24s (누락 0, 두 사건 ID 동일)
cd $WT; & $PY tools\m0_spike.py --mode replay --probes all
# P0~P8 success=True (9/9), 종료 코드 0
git checkout -- reports/M0-spike.json
& $PY tools\secret_scan.py
# secret_scan: clean, 종료 코드 0
```

기록 실행 1회(작업 트리 `.local/` 스크립트, 판독은 재생 재사용):

```powershell
$env:META_MODE = "record"
$env:META_LEDGER_PATH = "C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl"
$env:READER_CONCURRENCY = "1"
& $PY C:\2026_project\claimback-wt\m2c\.local\m2c_record_run.py
# case: case_afe3f65d2045
# run1: CHECKPOINT_1 (due_date 근거 [EX6:item22]만, conflicts [], questions [])
# facts: CALCULATING
# run2: DRAFT_APPROVAL (revision_rounds 0, G2·G4·G1a·G3·NAMING·DRAFT 전부 pass)
# approved_all: True
# run3: CHECKPOINT_2
# run_cost: 0.0916
# prompt_versions: [drafter.v2, fact_organizer.v2, reader.v1]
```

## 4. 실호출 비용

- 모델: `muse-spark-1.3`만 2회(Standard, `-contributor` 없음). 사실 정리 1·문안 1(수정 0회). reasoning은 사실 정리 `low`·문안 `medium` 유지. 판독 5건은 INT-2 기록 재생이라 실호출 $0.
- 비용: $0.034511 (공유 원장 `C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl` 기준, `run_id`=case_afe3f65d2045, completed 2건: 0.017978·0.016533). 원장 +4줄(예약 2+확정 2). 단계 표시 `run_cost` 0.0916 = 재생 판독 0.0571 + 실호출 0.0345(반올림).
- 서버·백그라운드 프로세스를 띄우지 않아 정리할 것 없음.

## 5. 열린 문제와 지시서·약속 대비 차이

- `coordinator.py`의 `SLOT_DESCRIPTIONS["contract_interest"] = "약정 이자율(연 %)"` 설명이 남음(M4a 범위라 수정 불가). 허용 슬롯에서 빠져 모델에는 전달되지 않는 죽은 문자열이다.
- 기록된 s4(`user`, "…까지 잔액을 지급하는 내용입니다")가 다소 밋밋한 표현이다. 규칙은 통과하며 품질 판단은 데모(M5·M6)에 넘긴다.
- `기로` 판정은 `계기로`·`사기로` 같은 명사를 만나면 과차단할 수 있다(어절 단위 한계). 지시서 예문에는 없고 테스트로 고정하지 않았다.
- 모델이 낸 충돌 메모·질문 원문은 코드로 고치지 않는다(프롬프트로만 유도). 이번 기록은 충돌 0이라 검증 대상이 없었고, 코드 생성 메모·질문은 사실형 템플릿으로 고정했다.
- `deps.py`는 지시서 범위 안이었으나 변경이 불필요해 손대지 않았다.
- 지시서와 스펙이 다투는 부분은 없음.

## 6. 명세 변경 제안

`specs/`는 직접 고치지 않음. 아래만 반영을 제안함:

1. 계약 6b절 `DRAFT` 계산값 슬롯을 5종에서 6종으로(`contract_interest` 추가).
2. 계약 6b절 `DRAFT`에 M2c 규칙 추가: 인용·발화 문장은 당사자 이름 슬롯만(금액·날짜 7종 금지), `user` 문장의 슬롯 조합 반복 금지, 인용 뒤 끝맺음 금지.
3. 설계 3-7에 같은 `DRAFT` 규칙 반영.
4. 계약 5장 `Review`에 코드 대조 결과 반영을 명시: 무근거·불일치 값은 `conflict: true`+충돌 메모+그 칸 질문 자동 생성, 날짜 충돌 메모는 `증거에 나온 날짜가 서로 다릅니다: …(갑 제N호증)` 사실형.
5. 계약 6b절에 프롬프트 버전 `drafter.v2`·`fact_organizer.v2`(감사 기록) 명시.
6. INT-2 제안 유지: `gate_results` 순서·`null_reason`·`side`·오류 모양·업로드 제한 등.
