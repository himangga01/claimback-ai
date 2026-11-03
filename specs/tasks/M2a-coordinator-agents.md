# M2a 코디네이터·담당·사건 API (백엔드, 작업 지시서)

- 작성: 2026-11-03 12:35 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\m2a-backend`(브랜치 `m2a-backend`). M2b(화면·E2E)와 동시에 진행합니다.
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `specs/case-api-contract.md`(이 작업이 구현할 약속), `reports/M0-review.md`, `reports/M1.md`·`M3.md`·`M0-fix1.md`와 그 리뷰(병합된 기능의 이름과 사용법)
- 참조: 에이전트 설계 `specs/ClaimBack-AI_에이전트_설계.md` 1장 원칙, 2-1 흐름, 3-1(판독), 3-4(사실 정리), 3-6(문안 작성), 3-7(검증), 3-9(편철), 4-1~4-4 / 계획서 4-6 코디네이터 케이스

## 목표

한국 샘플 사건이 업로드 → 판독(Spark) → 사실 정리(Spark) → 체크포인트 1(사용자 확정) → 계산(M1) → 문안 작성(Spark) ⇄ 검증(G1a·G3, M1) → 문장 승인 → 편철(내용증명 PDF, 전자소송 문구) → 체크포인트 2까지 **재생 모드로 끝까지** 돕니다. 실호출로 한 번 기록해 fixture를 만들고, 테스트와 화면은 그 fixture로 돕니다.

## 파일 범위

고쳐도 되는 파일: 새 패키지 `backend/app/agents/`(아래), 새 라우터 `backend/app/api/cases.py`, `backend/app/main.py`(라우터 등록만), `requirements.txt`(`uvicorn` 추가, R9), 새 테스트 `backend/tests/test_case_*.py`, 새 fixture(`backend/tests/fixtures/meta/` 추가 기록), `reports/cost_ledger.jsonl`(클라이언트가 추가).
건드리지 않는 파일: `frontend/`, `docs/`, `e2e/`, `sample_evidence/`, `backend/tests/golden/`(테스트에서 읽기만 가능), `backend/app/meta/`(쓰기만, 수정 금지), `backend/app/services/`(쓰기만. 꼭 필요한 수정은 리포트에 제안).

## 할 일

1. **사건 상태** `agents/case_state.py`: 설계 4-2 구역(`evidence`, `readings`, `fact_candidates`, `confirmed_facts`, `highlight_selection`, `calculations`, `drafts`, `draft_approvals`, `gate_results`, `packages`, `audit_log`, `state`)을 가진 Pydantic 모델. 사건별 JSON 파일에 쓰고 쓸 때마다 버전을 올립니다. 각 담당은 자기 구역에만 씁니다.
2. **공통 형식** `agents/base.py`: 설계 4-1 `AgentTask`, `AuditRecord`, `AgentResult`. 모든 AI 호출은 `backend/app/meta/` 클라이언트로, `run_id`는 `<case_id>:<step>:<ex_id>` 형식(M0-fix1에서 필수).
3. **접수** `agents/intake.py`: SHA-256, 호증 번호(EX1… 업로드 순서, 표시 "갑 제N호증"), 파일 종류. 영상은 이번에 `skipped`(M4에서 핵심 프레임).
4. **판독 담당** `agents/reader.py` + `agents/prompts/reader.v1.md`: 설계 3-1 `Reading` 스키마(구조화 출력), 이미지·PDF 입력, 박스는 `norm1000`으로 받아 원본 픽셀로 바꿔 저장(M0-fix1의 `Box`). 모델은 설정 상수 `READER_MODEL`(기본 `muse-spark-1.3`, M4에서 비교 후 결정), reasoning `low`, `max_output_tokens` 4,000 이상, 증거별 병렬(스레드), 결과는 `ex_id` 순으로 정렬해 저장. `incomplete`나 스키마 오류는 오류 내용을 붙여 1회 재요청, 다시 실패하면 그 증거 `HOLD`.
5. **사실 정리 담당** `agents/fact_organizer.py` + `prompts/fact_organizer.v1.md`: 설계 3-4. 판독 결과만 입력으로 받아 계약서의 `Review`를 만듭니다(필드 후보와 근거 `ex_id`/`item_id`, 충돌, 질문, 발화 태그, 증거 역할 제안). 법적 성격 표현 금지(설계 3-4 금지 목록). 모델 `muse-spark-1.3`, reasoning `medium`.
6. **문안 작성 담당** `agents/drafter.py` + `prompts/drafter.v1.md`: 설계 3-6과 4-4 머리말 예시. 입력은 M1의 `KR_SLOTS` 슬롯 목록(값 없이 이름과 설명), 사건 순서, 사용자가 고른 강조 발화, 증거 목록. 출력은 `SlotDraft`. 검증은 M1의 G1a·G3, 지적 목록을 넣어 최대 2회 수정, 넘으면 `HOLD`.
7. **계산·편철**: 계산은 M1의 `calculate_kr`(확정값과 `as_of`), G2·G4는 M1 게이트. 편철은 M1의 서류 생성 함수로 내용증명 PDF와 전자소송 문구를 만들고, 슬롯은 M1의 치환 함수로 사용자 확정값·계산값·확인된 판독 원문으로 바꿉니다. 승인되지 않은 문장은 서류에 넣지 않습니다.
8. **코디네이터** `agents/coordinator.py`: 설계 4-3 상태 기계(계약서 `state` 목록). `run`은 다음 체크포인트나 `HOLD`까지 동기로 진행하고 `steps[]`를 갱신합니다. 같은 입력이면 같은 순서와 결과.
9. **API** `api/cases.py`: `specs/case-api-contract.md`의 엔드포인트와 응답 모양 그대로. `/api/cases/sample`은 `sample_evidence/kr/`의 이미지·PDF만 올립니다(정답 데이터 `backend/tests/golden/`은 읽지 않음). 기존 `/api/verify` 등은 그대로 둡니다.
10. **기록(record) 실행**: `META_MODE=record`로 샘플 사건을 한 번 끝까지 돌려 fixture를 만듭니다(사용자 확정값은 테스트 데이터로 넣되, 정답 파일을 에이전트 입력으로 쓰지 않음). 비용 상한은 없지만 같은 단계를 불필요하게 반복하지 않습니다. 프롬프트를 고치면 다시 기록해야 하므로, 프롬프트를 확정한 뒤 마지막에 한 번 기록합니다.
11. **테스트**(재생 모드, 키 없이):
    - 사건 흐름 계약 테스트: `TestClient`로 샘플 사건 생성 → run → review → facts PUT(고정 예시 값, `as_of` 2026-06-01) → run → drafts → 전 문장 승인 → run → package. 내용증명 PDF 텍스트에 "4,014,383"과 "2026. 5. 2."가 있고, 남은 슬롯 0개, 금지 명칭 0건(M1 `naming.py`).
    - 판독 품질 기록(실패 기준 아님): 재생 결과를 `backend/tests/golden/kr_truth.json`과 비교한 금액·날짜 일치율, 정답 박스 기준 IoU 중앙값을 테스트 출력과 리포트에 남깁니다.
    - 코디네이터 경로(가짜 담당 주입): 정상, G2 `HOLD`, 스키마 2회 실패 `HOLD`, 수정 루프 초과 `HOLD`, 예산 초과 `HOLD`, 병렬 결과 정렬.
12. 리포트 `reports/M2a.md`(AGENTS.md 형식): 실호출 횟수·비용(원장), 판독 품질 기록, 단계별 지연, 계약서와 다르게 만든 부분. 리포트는 한 번에 끝까지 쓰고 다시 열어 끝까지 저장됐는지 확인합니다.

## 하지 않을 일

- 화면, E2E(M2b), 시각 감식·가림·영상·타임라인(M4 이후), 미국 트랙
- 판독 모델 최종 결정(M4), 다른 사건 형식 지원
- `specs/` 수정, `.env` 읽기·만들기, 키 출력, 커밋과 푸시

## 완료 기준

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m2a-backend"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"
& $PY -m pytest -q                                  # failed 0 (키 없이 재생)
cd $WT
& $PY tools\secret_scan.py                          # 종료 코드 0
$env:META_MODE = "replay"; Start-Process -FilePath $PY -ArgumentList '-m','uvicorn','app.main:app','--port','8765' -WorkingDirectory "$WT\backend" -PassThru   # 서버 기동 확인 후 종료
```
