# INT-3 통합 마무리 리포트 (INT-3b)

## 1. 작업 지시서와 한 일

- 지시서: `specs/tasks/INT-3b-finish-rerecord.md` (그대로만 수행, 새 기능 없음).
- INT-3(a102fcf: 1·1a·1b, 가림 후속 일부, G1b·HOLD·B1~B7·M5테스트3·문안 containment) 위에
  마무리만 했다. 새로 쓴 테스트는 전부 통과해 **xfail 0개**이며, 대신 새 동작에
  뒤처진 기존 테스트 6개의 기대값을 수정했다(삭제 없음).
- 재기록 1회 성공(`case_cba57b44bb09`, CHECKPOINT_2), 구 fixture 5개 삭제,
  데모 입력 `redaction_confirmed` 조건 추가, E2E 호출 수·역할·문구 수정.

## 2. 생성·변경 파일

- `backend/app/agents/demo_inputs.py`: `needs_review=True`일 때만
  `redaction_confirmed: true` 포함(선택 인자, 기존 호출 무변경).
- 테스트 기대값 수정: `backend/tests/test_fact_check_m2c.py`(parens 탈락 충돌),
  `test_m4a.py`(EX6 needs_review 소멸·신규 item id), `test_m5_fix2.py`
  (parties 블록·G1b notes·실명 필수).
- `e2e/test_case_flow.py`: 호출 수 6→11·7→12, `loan_agreement` 역할 허용,
  실백엔드 가림열 표시, 금액 오류 문구(`금액은 숫자로 적어 주세요`).
- `frontend/case.js`·`docs/case.js`: 역할 선택에 `loan_agreement`(차용증) 추가.
- Fixture: 31 수정·3 추가·5 삭제(구 review/slot_draft).

## 3. 실행 명령과 결과

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\int-3"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q            # 464 passed, 0 failed
cd $WT; & $PY -m pytest -q e2e                   # stub: 2 passed, 1 skipped
# 재생 실백엔드(임시 원장, 빈 포트, 종료 확인):
$env:E2E_BASE_URL="http://127.0.0.1:<포트>"; & $PY -m pytest -q e2e  # 3 passed
& $PY tools\m0_spike.py --mode replay --probes all  # P0~P8 전부 success, exit 0
git checkout -- reports/M0-spike.json
& $PY tools\secret_scan.py                        # clean
```

## 4. 실호출 (원장 `.../claimback-ai-meta/reports/cost_ledger.jsonl`)

- 1회, 34 calls: `muse-spark-1.2` 11(판독), `sam-3.1` 21(감식),
  `muse-spark-1.3` 2(정리·문안). 비용 $0.1693, run cap 이내. 재시도 없음.

## 5. 재기록 결과·미룬 항목·이탈

- EX6: 주민번호·전화 3 마스크 밴드 전부 0, `needs_review` 전면 소멸(5개 미리보기
  전부 False), leak pass, 소각·유지 테스트 통과. 판독 상자 IoU는 별도 미측정
  (밴드 0·needs_review 소멸로 대체 확인).
- xfail로 미룬 항목 없음. 화면 후속(needs_review 배지·확인 단추·문구)은 손대지
  않음(E2E는 현 화면으로 통과).
- 이탈: 지시서 3단계 M5 3개는 a102fcf에 이미 반영돼 있어 추가 수정 없음.
  구 fixture는 이번에 대체된 5개만 삭제(읽기·감식 구본은 단위·eval 테스트가
  여전히 사용). a102fcf 커밋 메시지의 "step 2에서 중단"과 달리 B·G1b·문안
  일부가 이미 구현돼 있어 xfail 대신 기대값 수정을 택함.

## 6. 스펙 변경 제안

- 없음.
