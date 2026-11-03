# M2c-fix1 리포트: 전언 판정·이름 보존·증거 인용 (Muse Code)

- 작성: 2026-11-03 (KST), Muse Code (`muse-spark-1.3`)
- 작업 트리: `C:\2026_project\claimback-wt\m2c` (브랜치 `m2c`)
- Python: `C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe` (공유 venv, 신규 생성 없음)
- 지시서: `specs/tasks/M2c-fix1-rules-names.md` (먼저 읽음: `AGENTS.md`, 지시서, `reports/M2c.md`, `reports/M2c-review.md` D1~D11, `specs/case-api-contract.md`)

## 1. 지시서와 한 일

- 1 (D1 전언 판정 보강): `말했`·`말씀` 독립 표지 + `하셨` 행렬 동사 추가, `다며`·`라며`·`다면서`·`라면서` 독립 표지 추가, 인용 어미 뒤 4어절 안 `문자`·`메시지`·`연락`+`보내` 꼴 판정, 동사 `약속했`·`약속하였`·`약속하` 추가. 띄어쓰기 없는 꼴("갚는다고말했습니다")은 어절 내 어미+행렬(prefix) 판정으로 차단. 리뷰 명시 12꼴(아래 표 D1-*) 전부 차단.
- 2 (D4 오탐 줄이기): `기로`는 지급 동사 어간 13종(`갚`·`보내`·`주`·`드리`·`변제하`·`지급하`·`상환하`·`입금하`·`송금하`·`전달하`·`납부하`·`지불하`·`내`)+`기로`만 판정. `물어`는 독립 표지에서 빼고 인용 어미 뒤 행렬로만. "믿기로 하고", "계기로", "이자를 물어 주지 않았습니다" 통과. `보내`·`보냈`도 인용 뒤에서만 보며 "보냈습니다" 단독은 통과.
- 3 (D3·D5 사용자 진술): 중복은 금액·날짜 슬롯 겹침으로만(기존 메시지 유지). `user` 문장은 근거 있는 칸의 슬롯 사용 금지 — `check_draft_rules(sentences, sourced_slots=None)`, 기본값은 금액·날짜 7종 전부, 이름 슬롯은 항상 허용. "그 뒤로 {{debtor_name}}은 연락을 받지 않았습니다" 통과(단독·이름겹침 쌍 모두).
- 4 (D6 문서 인용): 문안 프롬프트에 문서 증거 전부 1회 이상 인용, 중립 문형 2종, "변제하기로 약정…" 금지, 문장 순서(대여 → 약정 → 변제 → 미지급) 명시. 중립 문형 2종이 규칙을 통과함을 테스트로 고정.
- 5 (D2·D9 이름 보존): 사실 정리 프롬프트는 괄호 포함 원문 그대로(머리말만 제외). 코드 대조는 괄호를 지우지 않고 머리말(`채권자`·`채무자`·`성명`·`이름`·`주소`·`연락처`·`전화번호`·`전화`+`:`)을 뗀 뒤 포함 관계로 비교. 재생 서류에 "(SAMPLE)"이 남음을 리플레이 테스트로 고정(리뷰·사실정리값·문안 렌더·편철 문구 4곳).
- 6 (D7): `fact_organizer.v2.md`의 잘못된 `evidence_roles` 줄(61행) 삭제. `"evidence_roles"` 1회만 등장함을 테스트로 고정.
- 7 (D8 변제기 근거): 프롬프트를 문서 우선 + 문서 없을 때 대여 이체 이전·당일 대화 날짜 허용으로. "변경이 아니라" 결론 문구 삭제, 나중 약속은 `repay_promise`로만 기록하고 변제기 칸 그대로 둔다고 사실형으로.
- 8 (D10·D11): 발화 안 모든 월·일을 보고 하나라도 맞으면 일치. `ex_id` 대소문자 무시(정규형 대문자 저장). 원문 없는 근거 항목은 "근거 확인 불가"로 충돌+질문(질문에 문구 포함). 근거 없는 `transaction_kind`는 충돌 없이 질문만. 인용 슬롯 증거 번호와 바로 뒤 `[[EX:n]]`이 다르면 `DRAFT` 지적(다음 인용 전 첫 태그 기준, 대소문자 무시).
- 9 (다시 기록): 판독 INT-2 기록 재생 재사용, 사실 정리·문안만 `META_MODE=record` 1회. 기록 문안 아래 원문 그대로 + 1~8 준수 여부.
- 10: 이 리포트(규칙 예문표 전/후 포함).

### 기록된 문안 (슬롯 원문 그대로, `case_24954222fa6d`)

- s1 `[fact]`: 이체 확인증에는 {{loan_date}}에 {{principal}}을 보낸 기록이 있습니다[[EX:4]]
- s2 `[fact]`: 차용증에는 변제기가 {{due_date}}로 적혀 있습니다[[EX:6]]
- s3 `[fact]`: {{debtor_name}}이 {{quote:EX1:item10}}라고 했습니다[[EX:1]]
- s4 `[fact]`: 이체 확인증에는 {{repaid_date}}에 {{repaid_amount}}을 받은 기록이 있습니다[[EX:5]]
- s5 `[user]`: {{debtor_name}}이 {{creditor_name}}에게 남은 돈을 지급하지 않고 있습니다[[USER]]

1~8 준수 여부: (1) 새 전언 꼴 0개, 인용은 s3에만 있고 이름 슬롯만 사용. (2) `기로`·`물어` 오탐 0. (3) s5는 이름 슬롯만, 금액·날짜 슬롯 0·겹침 0. (4) 문서 증거 EX4·EX5·EX6 전부 인용(s1·s2·s4), 중립 문형 2종 사용, 순서 대여(s1)→약정(s2, 차용증 변제기)→강조 인용(s3)→변제(s4)→미지급(s5). (5) 이름에 "(SAMPLE)" 유지. (6) 해당 없음(프롬프트). (7) `due_date` 근거 `[EX6:item22]` 하나, 충돌·질문 없음, 나중 약속은 `repay_promise`로만(EX2:item7/13/23 등). (8) 인용 슬롯 EX1 뒤 태그 `[[EX:1]]` 일치. 초안이 6개 게이트를 수정 0회로 통과.

기록된 사실 정리: 이름 2건 모두 "(SAMPLE)" 유지, `due_date` 근거 EX6:item22 하나, `conflicts: []`, `questions: []`, `null_reason` 사실형("판독에 이자 약정 없음" 등). 감사 기록 `prompt_version`: `drafter.v2`, `fact_organizer.v2`, `reader.v1`.

### 규칙 예문 표 (전 = HEAD 실측, 후 = 새 코드·테스트)

리뷰는 ①의 25개 문장을 낱낱이 싣지 않아, 리뷰에 이름이 나온 문장(D1 7종·D4 3종·D3 1종·M2c 표 14종·D5·D6·D11) 전부와 같은 꼴의 변형 40건을 전/후 실측했다. 전 25/40 → 후 40/40. (D5 날짜 직접표기는 G1a 소관이라 DRAFT 통과가 정상.)

차단 예상:

| 예문 | 기대 | 전 | 후 |
|---|---|---|---|
| `fact` "약정 이자율 {{contract_interest}}를 정했다" (M2c A1) | 차단 | 차단 | 차단 |
| `fact` 인용+`due_date`·`principal` (인용 불일치) | 차단 | 차단 | 차단 |
| `user` "…까지 …을 보내기로 했다" | 차단 | 차단 | 차단 |
| `fact` "…까지 갚기로 하였다" | 차단 | 차단 | 차단 |
| `fact` "보내 준다고 했다" | 차단 | 차단 | 차단 |
| `fact` "보내겠다고 답했다" | 차단 | 차단 | 차단 |
| `user` "돌려 달라고 했다" | 차단 | 차단 | 차단 |
| `fact` "돌려드리겠다고 했다" | 차단 | 차단 | 차단 |
| `fact` "언제 갚을 수 있는지 물었다" | 차단 | 차단 | 차단 |
| INT-2 s2 인용 끝맺음 | 차단 | 차단 | 차단 |
| `fact` "갚는다고 말했습니다" (D1) | 차단 | 통과 | 차단 |
| `fact` "갚는다고말했습니다" (D1) | 차단 | 통과 | 차단 |
| `fact` "주시겠다고 하셨습니다" (D1) | 차단 | 통과 | 차단 |
| `fact` "갚는다며 …" (D1) | 차단 | 통과 | 차단 |
| `fact` "받았다면서 …" (D1) | 차단 | 통과 | 차단 |
| `fact` "보내라면서 …" (D1) | 차단 | 통과 | 차단 |
| `fact` "갚겠다며 …" (D1) | 차단 | 차단 | 차단 |
| `fact` "변제를 약속했습니다" (D1) | 차단 | 통과 | 차단 |
| `fact` "갚기로 약속하였습니다" (D1) | 차단 | 차단 | 차단 |
| `user` "갚아 달라고 문자를 보냈습니다" (D1) | 차단 | 통과 | 차단 |
| `fact` "갚으라고 메시지를 보냈습니다" (D1) | 차단 | 통과 | 차단 |
| `user` "갚겠다고 연락을 보냈습니다" (D1) | 차단 | 차단 | 차단 |
| `fact` 인용 EX1 뒤 `[[EX:2]]` (D11) | 차단 | 통과 | 차단 |
| `user` "{{due_date}}까지 잔액을 …" (D5) | 차단 | 통과 | 차단 |
| INT-2 s4 `user` 중복(쌍) | 차단 | 차단 | 차단 |

통과 예상:

| 예문 | 기대 | 전 | 후 |
|---|---|---|---|
| `user` "…요청하였으나 받지 못했다" | 통과 | 통과 | 통과 |
| `fact` "약속한 대로 {{loan_date}}에 …" | 통과 | 통과 | 통과 |
| `user` "약속한 돈을 보내지 않았다" | 통과 | 통과 | 통과 |
| `fact` 인용+이름 슬롯만 | 통과 | 통과 | 통과 |
| `fact` "…{{principal}}을 보냈습니다" | 통과 | 통과 | 통과 |
| `user` 슬롯 없음 | 통과 | 통과 | 통과 |
| `fact` "약정 이율은 {{agreed_rate}}이다" | 통과 | 통과 | 통과 |
| `fact` "믿기로 하고 …" (D4) | 통과 | 차단 | 통과 |
| `fact` "…계기로 {{principal}}을 …" (D4) | 통과 | 차단 | 통과 |
| `user` "이자를 물어 주지 않았습니다" (D4) | 통과 | 차단 | 통과 |
| `user` "그 뒤로 {{debtor_name}}은 연락을 받지 않았습니다" (D3) | 통과 | 통과 | 통과 |
| `fact` "차용증에는 변제기가 {{due_date}}로 적혀 있습니다" (D6) | 통과 | 통과 | 통과 |
| `fact` "이체 확인증에는 … 보낸 기록이 있습니다" (D6) | 통과 | 통과 | 통과 |
| 이름만 겹치는 쌍 (D3) | 통과 | 차단 | 통과 |
| `user` 날짜 직접표기 (G1a 소관) | 통과 | 통과 | 통과 |

사실 대조 전/후:

| 경우 | 전 | 후 |
|---|---|---|
| "서가온(SAMPLE)" 대 "서가온(SAMPLE)" | 충돌 없음 | 충돌 없음 |
| "서가온(채무자)" 대 "서가온(SAMPLE)" | 충돌 없음 | 충돌+질문 |
| "채권자: 서가온(SAMPLE)" 머리말 | 충돌 | 충돌 없음 |
| 발화 2개 월·일 중 1개 일치 | 충돌 | 충돌 없음 |
| 소문자 `ex4` 근거 | 충돌·근거 버림 | 충돌 없음·EX4로 저장 |
| 원문 없는 근거 항목 | 무시 | "근거 확인 불가" 충돌+질문 |
| 근거 없는 `transaction_kind` | 충돌+질문 | 질문만 |

## 2. 만든·고친 파일

새 파일:

- `backend/tests/test_draft_rules_m2c_fix1.py` (15개: D1 12문장·D4 3문장·D3·D5·D6·중립문형·D11·프롬프트)
- `backend/tests/test_fact_check_m2c_fix1.py` (13개: D2·D9·D10·D7·D8·프롬프트·재생 SAMPLE)
- `backend/tests/fixtures/meta/4f982e6d*.json`, `d61b819d*.json` (사실 정리·문안 fix1 기록)
- `.local/m2c_fix1_probe.py`, `.local/cmp_table.py`, `.local/probe_*.txt`, `.local/fixtures_*.txt` (탐침, git 제외), `reports/M2c-fix1.md` (이 리포트)

고친 파일(지시서 범위 안만):

- `backend/app/agents/draft_rules.py`: D1 전언 표지 확대·메시지 전언 판정, D4 `GIRO_MARKERS`·`물어` 행렬화, D3·D5 `sourced_slots` 인자+금액날짜 겹침, D11 인용-태그 대조
- `backend/app/agents/fact_organizer.py`: D2·D9 괄호 보존·머리말 제거·포함 비교, D10 전체 월일·소문자 무시·근거확인불가·거래종류 질문전용
- `backend/app/agents/prompts/drafter.v2.md`: D6 문서 인용·중립 문형·문장 순서, 발화 표지 목록·인용태그 일치·근거칸 금지
- `backend/app/agents/prompts/fact_organizer.v2.md`: D7 오기 삭제, D2 괄호 보존, D8 문서 우선·대화 보조
- `backend/tests/fixtures/meta/` M2c 사실 정리·문안 2개 삭제(`4a14271a*`, `93427d37*`)

건드리지 않음: `drafter.py`·`deps.py`(수정 불필요 — 서명 기본값이라 코디네이터 호출 그대로 동작), `coordinator.py`·`cases.py`·`reader.py`·`intake.py`·`packager.py`·`frontend/`·`e2e/`·`specs/`·다른 리포트·`.env`(읽기·생성 없음), 판독 fixture 5개 무변경(기록 실행에서 재생 재사용 확인).

## 3. 실행한 명령과 결과

공유 venv·키 없이(기록 1회만 키 사용, 값은 출력·기록 안 함):

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m2c"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q tests/test_draft_rules_m2c_fix1.py tests/test_draft_rules_m2c.py tests/test_fact_check_m2c.py tests/test_fact_check_m2c_fix1.py -k "not sample_mark"
# 49 passed, 1 deselected in 0.73s (기록 전 집중 실행)
cd "$WT\backend"; & $PY -m pytest -q
# 323 passed in 26.15s (failed 0)
cd $WT; & $PY tools\m0_spike.py --mode replay --probes all
# P0~P8 success=True (9/9), 종료 코드 0
git checkout -- reports/M0-spike.json
& $PY tools\secret_scan.py
# secret_scan: clean, 종료 코드 0
```

기록 실행 1회(기존 `.local/m2c_record_run.py` 재사용, 판독은 재생 재사용):

```powershell
$env:META_MODE = "record"
$env:META_LEDGER_PATH = "C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl"
$env:READER_CONCURRENCY = "1"
& $PY C:\2026_project\claimback-wt\m2c\.local\m2c_record_run.py
# case: case_24954222fa6d
# run1: CHECKPOINT_1 (due_date 근거 [EX6:item22]만, conflicts [], questions [])
# facts: CALCULATING
# run2: DRAFT_APPROVAL (revision_rounds 0, G2·G4·G1a·G3·NAMING·DRAFT 전부 pass)
# approved_all: True
# run3: CHECKPOINT_2
# run_cost: 0.0947
# prompt_versions: [drafter.v2, fact_organizer.v2, reader.v1] (케이스 감사 기록에서 별도 확인)
```

## 4. 실호출 비용

- 모델: `muse-spark-1.3`만 2회(Standard, `-contributor` 없음). 사실 정리 1·문안 1(수정 0회). 판독 5건은 INT-2 기록 재생이라 실호출 $0.
- 비용: $0.037628 (공유 원장 `C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl` 기준, `run_id`=case_24954222fa6d, completed 2건: 0.015812·0.021816). 원장 +4줄(예약 2+확정 2). 단계 표시 `run_cost` 0.0947 = 재생 판독 + 실호출.
- 서버·백그라운드 프로세스를 띄우지 않아 정리할 것 없음.

## 5. 열린 문제와 지시서·약속 대비 차이

- `sourced_slots`를 코디네이터가 아직 넘기지 않아(파일 범위 밖) 기본값(금액·날짜 7종)이 동작한다. 근거 없는 금액·날짜를 사용자 진술로 써야 하는 사건에서는 과차단이다. 배선은 6절에 제안.
- `라며`·`다며` 독립 판정은 "바라면서" 같은 말을 만나면 과차단할 수 있다. 문안 문체에서 드물어 허용하고 테스트로 고정하지 않았다.
- `하셨`은 단독 표지가 아니라 인용 어미 뒤 행렬로만 본다. "변제하셨습니다" 같은 존칭 서술을 전언으로 오판하지 않기 위해서다. 지시서의 "주시겠다고 하셨습니다" 꼴은 차단된다.
- 기록 스크립트 끝의 `prompt_versions` 출력에서 `AuditRecord.get` 오류가 난다(스크립트 표시 버그, 흐름은 CHECKPOINT_2까지 정상). 버전은 케이스 감사 기록에서 직접 읽어 위에 적었다.
- M2c 리포트의 열린 문제 중 "`기로` 과차단"은 해소. "s4 밋밋한 표현"은 해소(s5가 주어 있는 문장). `SLOT_DESCRIPTIONS["contract_interest"]` 잔여·모델 원문 미수정 원칙은 그대로.
- 지시서와 스펙이 다투는 부분은 없음.

## 6. 명세 변경 제안

`specs/`는 직접 고치지 않음. 아래만 반영을 제안함:

1. 계약 6b절 `DRAFT`에 fix1 규칙 추가: 전언 판정 확대(말했·말씀·하셨·다며·라며·다면서·라면서·약속했·약속하였·문자/메시지/연락 보냈), `기로` 지급어간 한정·`물어` 인용뒤 한정, `user` 근거칸 슬롯 금지+금액날짜 겹침 금지, 인용-태그 번호 일치.
2. 계약 5장 `Review`에 코드 대조 반영: 이름·주소는 괄호 보존·머리말 제거·포함 비교, 날짜는 전체 월일 중 1개 일치, `ex_id` 대소문자 무시, 원문 없는 근거는 "근거 확인 불가" 질문, 근거 없는 `transaction_kind`은 질문만.
3. 설계 3-6 문안 프롬프트 규칙에 반영: 문서 증거 전부 인용·중립 문형 2종·문장 순서(대여 → 약정 → 변제 → 미지급).
4. 설계 3-4 사실 정리 규칙에 반영: 이름 괄호 보존, 변제기 문서 우선·문서 없을 때 대여 이전·당일 대화 허용.
5. 코디네이터가 `check_draft_rules`에 `sourced_slots`(근거 있는 칸의 슬롯 집합)를 넘기도록 계약 6b절 또는 M4a 작업에 반영. 기본값 동작은 유지.
6. M2c 제안 1~6 유지(계약 6b절 계산값 6종·DRAFT 규칙·설계 3-7·Review 대조·v2 버전·INT-2 제안).
