# INT-3 통합: 전체 재기록·남은 후속·실제 백엔드 E2E (작업 지시서)

- 작성: 2026-11-03 16:00 KST 초안, 16:34 확정, Claude
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\int-3`(브랜치 `int-3`). Claude가 main(4a7b294: M6·M6-fix1, M2c·M2c-fix1, M5·M5-fix1·M5-fix2)에 M4a(+fix1, b51c98f)와 M4b(242ca96)를 병합해 둠(8b77173). 이 지시서와 계약 6c절은 main에서 병합해 들어옴.
- 시작 상태(Claude 확인 16:32, 키 없이): `backend` 10 failed, 416 passed, 7 errors. 원인은 (1) 판독이 1.2·v2·조각 읽기로 바뀌어 사실 정리·문안·서명 재시도 요청의 재생 기록이 없음, (2) M5 테스트 3개가 가림 사본이 없다고 가정, (3) M4a 테스트가 옛 판독 상자에 묶임.
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `specs/case-api-contract.md`(6a·6b·6c절), `reports/INT-2-review.md` 4절 B, `reports/M2c-review.md` 6절, `reports/M4a-review.md` 6절, `reports/M4b.md`(5·6절)와 `reports/M4b-review.md`(있으면), `reports/M5-review.md` 7절, `reports/M6-review.md` 6절

## 파일 범위

`backend/`, `frontend/`와 같은 변경의 `docs/` 사본, `e2e/`, `tools/`(E2E·채점 도구), `reports/cost_ledger.jsonl`. `specs/`, `sample_evidence/`, `backend/tests/golden/`, `backend/app/meta/`는 건드리지 않습니다(필요하면 리포트에 제안).

## 할 일

1. **영상은 연결하지 않음(16:44 결정)**: M4b 코드 리뷰에서 영상 판독이 정답 24개에 52개 항목(스크롤 중복·글자 변형·잘린 조각), 가변 프레임률에서 `frame_ts` 최대 1초 오차, 재생에 ffmpeg 필요로 확인돼 이번에는 사건 흐름에 넣지 않습니다. EX3는 `skipped`(계약 2장 그대로), 화면 문구는 "영상 증거는 해시만 기록, 판독은 다음 버전". `keyframes.py`·`run_video_reader`는 코드로 남기되 ffmpeg가 없으면 관련 테스트는 skip.
1a. **가림 전 상자 다듬기(M4b 리뷰, 데모 차단)**: 재생에 쓰는 M4b 판독으로도 EX6 주민번호 상자는 IoU 0(실제 줄보다 약 50~150px 위), 전화는 0.16·0.42라 가림이 빗나갑니다. 개인정보 항목(`account_number`·`id_number`·`phone`)은 가림 계획을 만들기 전에 원본 이미지에서 판독 상자 주변(세로 ±150px, 같은 줄 가로 범위)을 찾아, 판독 원문의 글자 수에 맞는 너비의 실제 글자 줄(어두운 픽셀 행·열 분포)을 골라 그 줄의 상자를 씁니다(모델 호출 없음, 재생 결정적). 같은 이미지의 라벨("주민등록번호" 등) 오른쪽에 있는 값 칸을 우선. 정답 `redaction_targets`로 EX6 주민번호 뒤 7자리·전화 가운데 4자리·EX4·EX5 계좌가 100% 덮이고 유지 부분이 온전한지 테스트, 띠 검사 `needs_review`가 사라지는지 확인. 다듬기에 실패하면 지금처럼 `needs_review`.
1b. **조각 경계 합치기(M4b 리뷰 ①② 모두)**: 같은 항목이 경계에서 두 번 나옴(EX1 "타나루(SAMPLE)"·"탁나루(SAMPLE)", 줄바꿈만 다른 발화, EX6 이름 조각과 "…서명" 라벨, 주민번호·전화 중복)과 반대로 다른 항목이 하나로 합쳐짐(개수가 같을 때 거리 확인 없이 순서로 짝지음, `reader.py:503-504`). 상자 겹침(또는 중심 거리 한도)과 글자 유사도(0.8 이상, 공백·줄바꿈·문장부호 무시)로 종류가 달라도 합치고, 거리 한도를 넘으면 합치지 않음. 합친 상자는 평균이 아니라 합집합(가림이 덜 덮지 않게). 합친 뒤 위→아래·왼→오른 순으로 정렬하고 `item_id`를 다시 붙임. 조각 수 상한(예: 8, 넘으면 조각 크기를 키움), CMYK 이미지는 RGB로 바꿔 자름. 변이에 걸리는 테스트(경계 합치기 분기 제거, 거리 한도 제거).
2. **가림 후속(M4a 6절)**: 서명 재시도 실패는 그 증거를 `not_redacted`로 만들지 않음(서명은 가림 대상이 아님, 명사 호출 실패만 막음), `not_redacted`가 될 때 예전 `redacted_{ex}.png` 삭제, 가림 단계 전 `leak_check.status`는 `pending`, 띠 검사를 판독 항목 상자 네 면에도 적용(옆으로만 빗나간 가림도 `needs_review`).
3. **G1b와 HOLD(M5 7절)**: G1b `fail`(값·명칭·누출)은 편철 뒤 `HOLD`(`g1b_failed`), 고친 뒤 `POST /run`으로 편철부터 재실행. 이미지를 뺀 것은 `fail`이 아니라 `notes`. 전자소송 이름 확인이 늘 통과하는 문제(고정 문구에 역할어가 늘 있음), 전자소송 안 금액 맞바꾸기·금액 하나 삭제 테스트, 인용 뒤 `".`, 증거 역할 `loan_agreement`(차용증) 제안·사용, 가린 사본 비교를 픽셀 해시로.
4. **M5 테스트 3개(시험 병합에서 확인된 최소 수정)**: `test_k3_discover_ignores_evidence_dir_user_files`는 시작할 때 `files/redacted_EX1.png`와 `redactions.json`을 지움, `test_k3_missing_redacted_line_and_g1b_findings`·`test_exhibits_pages_cover_and_labels`는 편철 전에 가린 사본을 지우는 선택(`without_redacted`)을 쓰고, 사본이 있을 때 쪽 수 = 1 + 증거별 쪽 수·"(i/n)" 머리를 따로 확인. `test_fact_check_m2c_fix1.py`에 내용증명에는 "(SAMPLE)"이 남는지 단언 추가.
5. **백엔드 후속(INT-2 리뷰 B1~B7)**: B1 판독 담당의 예상 못 한 오류는 `internal_error`(키 없음은 `config_missing_key`), B2 `DELETE` 뒤 폴더가 실제로 사라졌는지 확인·재시도·실패면 409/500, B3 `VERIFYING` 저장, B4 업로드는 모두 검사한 뒤 쓰기·크기 먼저, B5 `missing_requirements` 전부·`interest_rate` 음수·`principal` 0 거부·HOLD 메시지에 pydantic 원문 금지, B6 재시도·끊긴 응답·파싱 실패 비용도 단계 비용에, B7 `naming_violation` HOLD는 고친 뒤 재실행 가능.
6. **문안 규칙 후속(M2c 6절)**: `fact` 문장의 "{{principal}}을 빌려 달라고 요청했습니다"·"부탁했습니다"·"…보겠다는 답장을 보냈습니다" 차단, 문서의 "갚기로 적혀 있습니다"·"주기로"(=마다) 통과, 코디네이터가 `check_draft_rules`에 근거 있는 칸 목록(`sourced_slots`)을 넘김, 이름·주소 포함 비교는 값이 근거 원문을 포함하는 쪽만(최소 길이), 문서 이름은 판독한 제목 그대로, 문장 끝 마침표, 편철 3항과 같은 사용자 진술은 빼기, `interest_rate` 근거(EX6 "이자 약정 없음") 유지, 검증 힌트에 "ex_refs"·"[[EX:번호]]" 같은 내부 표기 금지.
7. **화면 후속(M6 6절)**: 금액 오류 문구 "금액은 숫자로 적어 주세요(예: 5,000,000원)"(백엔드 메시지에 내부 키 금지, 화면은 칸 이름으로 매칭), 발화 목록 위 "서류에 강조할 말을 고르세요", 감식 호출 수는 `attempts`, `conflictText`의 문자열 `fields`도 칸 이름, 실행 중 실패한 테스트의 사건 정리. 가림 미리보기에 `needs_review` 배지와 "가림을 확인했습니다" 단추(`redaction_confirmed: true`로 `PUT /facts`), 영상 증거 미리보기에 핵심 프레임과 `frame_ts`.
8. **전체 재기록**: `META_MODE=record`, `META_LEDGER_PATH=C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl`, `READER_CONCURRENCY=1`, `run_id` = 사건 ID로 샘플 사건을 `CHECKPOINT_2`까지(판독·영상·감식·사실 정리·문안). `META_RUN_CAP_USD`는 필요하면 3으로. 더는 쓰이지 않는 fixture는 지웁니다. 바로 재생으로 다시 돌려 누락 0, 두 사건 ID 동일성 통과. 리포트에: 판독 상자 정답 IoU(EX1·EX2·EX6), 가림 대상별 덮음 여부와 `needs_review`(특히 EX6 주민번호·전화), 문안 문장(슬롯 채운 그대로), 서류 세 개의 텍스트 발췌, G1b 결과, 호출 수와 비용.
9. **데모 고정 입력과 E2E**: `build_demo_confirmed_facts`가 `needs_review` 사본이 있으면 `redaction_confirmed: true`를 넣고(E2E는 화면의 확인 단추를 눌러 같은 결과), 호출 수 단언을 새 기록에 맞춤(기록에서 직접 셀 수 있으면 그렇게). 가짜 서버와 실제 백엔드(재생) E2E 모두 통과, 스크린샷 `e2e/artifacts/real/`.
10. 리포트 `reports/INT-3.md`(AGENTS.md 형식, 끝까지 저장 확인).

## 완료 기준

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\int-3"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q                         # failed 0 (키 없이), 60초 이하
cd $WT; & $PY -m pytest -q e2e                                # 가짜 서버 대상 통과
# 재생 서버(META_MODE=replay, 127.0.0.1 빈 포트, 임시 원장 META_LEDGER_INIT=1)를 띄운 뒤:
$env:E2E_BASE_URL = "http://127.0.0.1:<포트>"; & $PY -m pytest -q e2e   # 실제 백엔드 대상 통과
& $PY tools\m0_spike.py --mode replay --probes all             # 9/9, 종료 코드 0
git checkout -- reports/M0-spike.json
& $PY tools\secret_scan.py                                     # 0
```
