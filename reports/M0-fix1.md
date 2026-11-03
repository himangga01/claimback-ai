# M0-fix1 리포트 (Meta 클라이언트 보강)

## 1. 작업 지시서와 수행 요약

- 지시서: `specs/tasks/M0-fix1-client-hardening.md` (2026-11-03 12:30 KST, Claude)
- 같이 읽은 문서: `AGENTS.md`, `reports/M0-review.md` (C1~C14)
- 목표: M0 리뷰에서 확인된 예산 차단 우회 경로와 통과 위주 테스트를 M2 연결 전에 수정. Meta 실호출 없음, 가짜 전송 계층으로만 테스트.
- 사용 파이썬: `C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe` (새 venv 없음, 설치한 패키지 없음)

고친 항목과 장치를 깨면 실패하는 테스트:

- C1 재시도 중복: `OpenAI(..., max_retries=0)`, 재시도는 `_with_retry`만 (429·일시적 5xx, 최대 3회). 400은 재시도 없음. `Retry-After` 30초 상한. 전송 후 실패는 예상 비용으로 `status: "failed"` 기록.
  - `test_sdk_retries_off`, `test_400_is_not_retried`, `test_retry_429_then_success`, `test_retry_exhausted_after_three_records_failed`, `test_retry_after_capped_at_30s`, `test_stream_failure_records_failed`
- C2 `extra` 우회: `extra`에 `model`, `input`, `max_output_tokens`, `text`, `reasoning`, `stream`, `store`가 있으면 호출 전 거부. `-contributor` 검사는 대소문자 무시. `extra`는 해시에서 빼지 않음 (기존 fixture 유지).
  - `test_extra_forbidden_keys_rejected`, `test_extra_allowed_metadata_passes`, `test_contributor_rejected`, `test_contributor_case_insensitive`
- C3 원장 오류 시 통과: 읽기 실패나 한 줄이라도 해석 실패하면 `BudgetLedgerError`로 거부. 추가는 한 줄 단위 쓰기 후 flush (+fsync 시도).
  - `test_ledger_corrupted_refuses_call`, `test_ledger_missing_cost_refuses_call`, `test_ledger_append_flushes`
- C4 usage 없는 응답: Spark 응답에 usage가 없거나 입력 토큰이 0이면 호출 전 예상 비용을 기록.
  - `test_usage_missing_records_expected_cost`
- C5 스트림 재시도·기록 누락: 재시도가 스트리머 생성부터 `__enter__`(실제 전송)와 이벤트 소비까지 감쌈. 실패 시에도 원장에 실패 줄 기록.
  - `test_stream_retries_enter_then_succeeds`, `test_stream_failure_records_failed`
- C6 실행당 상한 우회: live·record 모드에서 `run_id` 필수 (없으면 `ValueError`). `m0_spike.py`는 프로브마다 고정 `run_id` (`M0-P0`~`M0-P8`).
  - `test_run_id_required_in_live_and_record`, `test_m0_spike_run_id_fixed`, `test_per_run_cap_ignores_other_runs`, `test_budget_per_run_refuses_before_call`
- C7 과소 추정: 텍스트는 ASCII/4 + 비ASCII(한국어 등) 글자당 1토큰. 첨부 파일은 크기 기반 넉넉히 추정 (인라인 `input_file`은 `max(4000, 바이트//4)`, `file_id` 참조는 12,000, 이미지는 `max(1500, 바이트//10)`). 근거: M0 P3 50,579바이트 2쪽 PDF 5,403토큰 (~2,700토큰/쪽, 0.11토큰/바이트) 대비 바이트//4 (0.25토큰/바이트, 약 2.3배). SAM 영상(`input_video` 또는 `input_file`로 보낸 영상)은 `frame_count` 필수, 최소 50프레임 과금.
  - `test_estimate_korean_chars_one_token_each`, `test_estimate_pdf_inline_overestimates_m0`, `test_estimate_file_id_fallback_large`, `test_sam_video_cost_min_50_and_frame_required`, `test_sam_video_via_input_file_uses_frames`, `test_sam_image_cost`
- C8 동시 실행: 예산 확인+예약을 프로세스 내 `threading.RLock`과 파일 잠금(`cost_ledger.jsonl.lock`, O_EXCL 방식, Windows 동작)으로 묶음. 호출 전 예상 비용을 `reserved` 줄로 남기고 끝나면 실제 비용 `completed` 줄 (실패 시 예상 비용 `failed` 줄)로 확정. 합계는 미확정 예약 포함, 확정된 예약은 상쇄 (제외).
  - `test_concurrent_reservation_blocks_overspend`, `test_ledger_fields_and_no_key`, `test_retry_429_then_success`
- 예산 환경 변수 (AGENTS.md 11/3 결정): `pricing.py`가 `META_RUN_CAP_USD`(기본 2), `META_TOTAL_CAP_USD`(기본 100)를 매 호출마다 읽음. `.env.example`에 두 줄 추가 (키 줄은 계속 빈 값).
  - `test_budget_total_refuses_before_call` (env 20에서 $19.99 거부), `test_total_cap_default_100_allows_20` (기본 100 확인), `test_budget_per_run_refuses_before_call`
- C9 비밀값 검사: 미추적(무시되지 않은) `.env.*`도 탐지 (`.env.example` 제외). `.gitignore`에 `.env.*`와 `!.env.example` 추가.
  - 단위 테스트 없음 (git 의존). 완료 기준 `tools\secret_scan.py` 종료 코드 0으로 확인.
- C11 키 유출 경로: `_to_jsonable`의 `vars(obj)` 대체 경로에서 `_`로 시작하는 속성 제외.
  - `test_to_jsonable_skips_private_attrs`, `test_key_via_require_key_path_not_leaked`, `test_ledger_fields_and_no_key`, `test_fixtures_have_no_key_strings`
- C12 업로드 파일 정리: `files_delete` 추가 (record 저장, replay 재생). `responses_create`가 `file_id`를 쓴 뒤 자동 삭제 호출, 실패는 경고만. replay에서는 자동 삭제 생략 (기존 fixture에 삭제 기록 없음).
  - `test_files_delete_roundtrip_and_auto_cleanup`, `test_auto_cleanup_warns_only_on_delete_failure`
- C13 끊긴 응답: `responses_create`가 응답 `status` 확인, `incomplete`면 `IncompleteResponse` 발생 (이유 포함, 비용은 실제 과금액으로 기록, record fixture도 저장). replay에서도 불완전 fixture면 발생. Spark 판독 권장 `max_output_tokens` 4,000 이상 주석.
  - `test_incomplete_raises_and_records_cost`
- C14 좌표계 표시: `coords.py`에 `Box { x1, y1, x2, y2, system: "norm1000"|"pixel", ref_w, ref_h }`와 `box_to_pixels` 추가. Spark는 `norm1000`, SAM은 입력 크기 기준 `pixel` (M0 리뷰). 다른 좌표계·기준 크기 섞으면 `box_iou_boxes`가 오류. 기존 `denormalize_box`·`box_iou` 유지.
  - `test_box_to_pixels_spark_and_sam`, `test_box_mixing_systems_errors`, `test_coords_denormalize_and_iou`
- C10 테스트 보강 전반: `cost_usd` 값 자체 검사 (캐시 입력 $0.15, 추론 토큰 이중 계산 없음. M0 `bc43d6ae`(max 300, 출력 300, 추론 298)와 `4051cfb1`(max 2000, 출력 2000, 추론 1998)이 출력 포함을 증명, `pricing.py` 주석), 요청 해시 안정성, 키 경로 무유출 (가짜 키만 사용), `time.sleep` 자동 패치.
  - `test_spark_cost_cached_and_reasoning_no_double_count`, `test_request_hash_stable_key_order`, `test_muse_image_cost_flat_despite_tokens`, `test_fixtures_have_no_key_strings` (`checked > 0` 수정), `test_record_replay_roundtrip`, `test_replay_missing_fixture_errors`, `test_live_missing_key_names_only`, `test_default_mode_is_replay_without_key`
- Muse Image 토큰 과금 확인: 가격 페이지(2026-11-03 재확인)는 "flat $0.01/image", "usage 토큰은 참고용이며 토큰 과금에 포함되지 않음" 명시. 현행 장당 $0.01 유지, `pricing.py` 주석에 근거와 M0 `5b8897d6`(입력 26,345, 출력 1,635) 기록.
  - `test_muse_image_cost_flat_despite_tokens`
- 요청 해시·계산 방식 변경 없음: 모델·엔드포인트·`store`·`max_output_tokens`·`text_format`·`reasoning`·`stream`·`extra`·요청 내용 구성과 SHA-256 계산 유지. SAM 영상 fixture(`98f20261`, `a5f3ffe0`) 포함 30개 replay 통과로 증명.

## 2. 생성·변경 파일

- 생성: `reports/M0-fix1.md` (이 리포트)
- 변경 (지시서 파일 범위 내):
  - `backend/app/meta/pricing.py`: 예산 env (`META_RUN_CAP_USD`/`META_TOTAL_CAP_USD`, 기본 2/100), 총액 기본 20→100, Muse Image 참고용 토큰 주석, 추론 포함 근거 주석 (`bc43d6ae`, `4051cfb1`)
  - `backend/app/meta/client.py`: C1 (SDK `max_retries=0`, `_with_retry`만, 400 비해시도, `Retry-After` 30초 상한, 실패 시 예상 비용 `failed` 기록), C2 (`extra` 금지 키 7종 거부, `-contributor` 대소문자 무시), C3 (`BudgetLedgerError`, 줄 단위 쓰기+flush), C4 (usage 없음 시 예상 비용), C5 (스트림 `__enter__`까지 재시도, 실패 기록), C6 (live·record `run_id` 필수), C7 (한국어·첨부 크기 기반 과대 추정, SAM 영상 `frame_count` 필수·최소 50), C8 (스레드+파일 잠금, 예약·확정), C11 (`_`-속성 제외), C12 (`files_delete`+자동 정리), C13 (`IncompleteResponse`), 해시 불변 유지
  - `backend/app/meta/coords.py`: `Box`, `box_to_pixels`, `box_iou_boxes` 추가 (C14), 기존 함수 유지
  - `backend/app/meta/__init__.py`: `BudgetLedgerError`, `IncompleteResponse` export 추가
  - `backend/tests/test_meta_client.py`: 51개 테스트 (C10 목록 전부, `time.sleep` 자동 패치, 가짜 키만 사용)
  - `tools/secret_scan.py`: `present_dotenv_files()`로 미추적 `.env.*` 탐지 (C9)
  - `tools/m0_spike.py`: `run_id_for`만 고정값으로 변경 (`M0-{probe}`, C6). 그 외 불변
  - `.gitignore`: `.env.*`, `!.env.example` 추가
  - `.env.example`: `META_RUN_CAP_USD=2`, `META_TOTAL_CAP_USD=100` 추가
- 도구 부수 변경 (완료 기준 실행 결과, 수동 편집 아님): `reports/M0-spike.json` P7 `detail.file` 절대 경로 1줄이 작업 트리 경로로 갱신. 성공 판정 9/9 불변, 원장 37줄 불변.

## 3. 실행 명령과 결과

지시서 완료 기준을 그대로 실행 (키 제거 후):

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m0-fix1"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"
& $PY -m pytest -q
cd $WT
& $PY tools\m0_spike.py --mode replay --probes all
& $PY tools\secret_scan.py
Select-String -Path backend\app\meta\client.py -Pattern 'max_retries=0' -SimpleMatch
```

결과:

- `pytest -q`: 76 passed (실패 0). 내역: `test_meta_client.py` 51개, `test_api_routes.py` 7개, `test_verification_gate.py` 18개. 소요 약 2.1초 (`time.sleep` 패치).
- `m0_spike.py --mode replay --probes all`: 종료 코드 0, P0~P8 success 9/9, `ledger_total=$0.2135 lines=37`. 키·네트워크 없이 재생. 기존 fixture 해시 불변 증명 (SAM 영상 `98f20261`·`a5f3ffe0` 포함 P6 통과).
- `secret_scan.py`: `secret_scan: clean`, 종료 코드 0.
- `Select-String ... 'max_retries=0'`: 1건 (`backend\app\meta\client.py:615`, `OpenAI(..., max_retries=0)`).

## 4. 실호출 내역

- Meta 실호출: 0회 (live·record 네트워크 호출 없음. 테스트는 가짜 전송 계층, 스파이크는 replay만).
- 모델·비용: 해당 없음.
- `reports/cost_ledger.jsonl`: 37줄, 합계 $0.21354로 M0와 동일 (이번 작업에서 추가·변경 없음).

## 5. 열린 문제와 지시서·스펙과의 차이

- 지시서와 스펙이 충돌해 중단한 부분 없음.
- C8 확정 방식: 지시서 "예약 포함, 확정 시 상쇄"를 예약 줄 제외+확정 줄 실액 기록(음수 없음, `failed` 줄 자체가 예상 비용)으로 구현. 단순 합산 리더(`tools/m0_spike.py`의 `ledger_total`)는 진행 중 예약과 확정을 이중 합산할 수 있으나 (안전 쪽) 과대 추정이며, replay 완료 기준에는 영향 없음. `m0_spike.py`는 지시서상 `run_id` 부분만 고칠 수 있어 `ledger_total`은 손대지 않음. 6절 제안 참조.
- C12 자동 정리: `file_id`를 쓴 `responses_create` 성공·실패 뒤 모두 시도하되 경고만 남김. replay에서는 생략하므로 기존 M0 삭제 fixture 없이도 9/9 통과. 명시적 `files_delete`는 record 저장·replay 재생 지원.
- C9는 `secret_scan.py` 실행과 코드로 확인 (git 의존 단위 테스트는 `test_meta_client.py`에 두지 않음).
- 편집 파일들의 줄 끝이 CRLF에서 LF로 정규화됨 (Windows `core.autocrlf=true` 환경, 내용 diff 없음).
- `.env`를 읽거나 만들지 않았고, 키를 출력·기록하지 않았음. 커밋·푸시 없음. 지시서 범위 밖 파일 수동 편집 없음.

## 6. 스펙 변경 제안 (직접 수정 안 함)

- 구현·테스트 계획 4-7 예산 총액 기본값을 20에서 100으로 갱신 (AGENTS.md 11/3 결정 반영, 이번 `pricing.py` 적용).
- `tools/m0_spike.py`의 `ledger_total` 단순 합산을 `MetaClient.ledger_totals` 예약 상쇄 로직 사용으로 교체 (M2, 파일 범위 허용 시).
- 런타임 에이전트 설계에 SAM 영상 `frame_count` 필수·최소 50프레임, Spark 판독 `max_output_tokens` 4,000 이상 권장, `incomplete` 시 상향 재시도, Files 업로드분 응답 후 삭제 (C12) 명시.
- `extra` 금지 키 7종 (`model`, `input`, `max_output_tokens`, `text`, `reasoning`, `stream`, `store`)과 `-contributor` 대소문자 무시 금지를 클라이언트 계약에 명시.
- 원장 손상 시 호출 거부 (`BudgetLedgerError`)와 예약·확정 2줄 기록 (상태 `reserved`·`completed`·`failed`, `reservation_id`·`expected_usd` 포함)을 원장 형식에 명시.
- 좌표 `Box` 형식 (`system`: `norm1000`(Spark)|`pixel`(SAM), `ref_w`·`ref_h`)과 `box_to_pixels` 단일 변환, 혼합 계산 금지를 M3·M4 채점·가림 규칙에 반영.
