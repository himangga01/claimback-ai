# INT-3b 통합 마무리: 테스트 정리·재기록·E2E (좁은 지시서)

- 작성: 2026-11-03 17:45 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`), 작업 트리 `C:\2026_project\claimback-wt\int-3`(브랜치 `int-3`). INT-3 실행은 크레딧 때문에 17:44에 멈췄고, 그때까지의 변경은 커밋 a102fcf(WIP)에 있습니다.
- **크레딧이 거의 남지 않았습니다.** 다른 리포트·리뷰 문서는 읽지 말고 이 지시서, `AGENTS.md`, `git -C . log --oneline -8`, `git -C . diff fd9767b a102fcf --stat`와 실패하는 테스트만 보고 일합니다. 새 기능을 더하지 않습니다.
- 파일 범위: `backend/`, `e2e/`, `frontend/`·`docs/`(E2E가 요구하는 최소한만), `reports/cost_ledger.jsonl`, `reports/INT-3.md`.

## 할 일 (순서대로, 이것만)

1. 키 없이 `backend` pytest를 돌려 실패 목록을 봅니다.
2. INT-3 지시서 3단계 이후(G1b HOLD 연결, 백엔드 B1~B7, 문안 규칙 후속, 화면 후속)를 위해 새로 쓴 테스트 중 구현이 없는 것은 `@pytest.mark.xfail(reason="INT-3 deferred: <항목>", strict=False)`로 표시합니다(지우지 않음). 2단계(가림 후속)가 반쯤 된 상태면, 테스트가 통과하는 데 필요한 만큼만 마무리하고 나머지는 같은 방식으로 표시합니다.
3. M5 테스트 3개 수정(가림 사본이 이제 실제로 생김): `test_k3_discover_ignores_evidence_dir_user_files`는 시작할 때 사건의 `files/redacted_EX1.png`와 `redactions.json`을 지움, `test_k3_missing_redacted_line_and_g1b_findings`와 `test_exhibits_pages_cover_and_labels`는 편철 전에 `files/redacted_*.png`와 `redactions.json`을 지우는 선택을 써서 "사본 없음" 경로를 시험.
4. **전체 재기록**: `META_MODE=record`, `META_LEDGER_PATH=C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl`, `READER_CONCURRENCY=1`, `run_id` = 사건 ID로 샘플 사건을 `CHECKPOINT_2`까지 한 번(판독·감식·사실 정리·문안). 기존 기록 스크립트(`.local/` 아래 `m4b_record_run.py`·`m2c_record_run.py` 등)를 고쳐 쓰면 됩니다. 실호출은 이 한 번만(실패하면 원인만 고치고 한 번 더). 쓰이지 않는 fixture는 지웁니다. 바로 재생으로 다시 돌려 누락 0.
5. 데모 고정 입력(`build_demo_confirmed_facts`)이 `needs_review` 사본이 있으면 `redaction_confirmed: true`를 넣게 하고, E2E 호출 수 단언(`e2e/test_case_flow.py`의 7회)을 새 기록에 맞춥니다.
6. 완료 기준을 통과시킵니다: 키 없이 `backend` pytest 0 failed(xfail 허용), 가짜 서버 E2E 통과, 실제 백엔드(재생) E2E 통과, 재생 스파이크 9/9, 비밀값 검사 0. 띄운 서버는 끝냅니다.
7. 리포트 `reports/INT-3.md`(AGENTS.md 형식, 짧게): INT-3에서 한 것(커밋 a102fcf 포함)과 xfail로 미룬 항목 목록, 재기록 결과(EX6 주민번호·전화 가림이 덮였는지와 `needs_review`, 판독 상자 IoU를 잴 수 있으면), 실호출 수·비용.
