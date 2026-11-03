# M0-fix1 Meta 클라이언트 보강 (수정 지시서)

- 작성: 2026-11-03 12:18 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `m0-fix1` 브랜치에서. M1·M3와 동시에 진행하므로 아래 "파일 범위" 밖은 건드리지 않습니다.
- 먼저 읽을 것: `AGENTS.md`(예산 항목), 이 지시서, `reports/M0-review.md`(C1~C12)
- 배경: M0 리뷰에서 클라이언트의 예산 차단이 뚫리는 경로와, 장치가 고장 나도 통과하는 테스트가 확인됐습니다. M2가 이 클라이언트를 API에 연결하기 전에 고칩니다. **Meta 실호출은 하지 않습니다**(가짜 전송 계층으로만 테스트).

## 파일 범위

고쳐도 되는 파일: `backend/app/meta/`(전부), `backend/tests/test_meta_client.py`, `tools/secret_scan.py`, `tools/m0_spike.py`(run_id 부분만), `.gitignore`, `.env.example`.
건드리지 않는 파일: 그 밖의 모든 파일(`backend/app/services/`, `schemas/`, `api/`, `main.py`, `frontend/`, `docs/`, `sample_evidence/`, `README.md`, 다른 테스트).

## 할 일 (리뷰 번호)

1. **C1 재시도 중복**: `OpenAI(...)`를 `max_retries=0`으로 만들어 SDK 자체 재시도를 끄고, 재시도는 `_with_retry` 하나만 둡니다(429와 일시적 5xx, 최대 3회 재시도). 400 등 다시 보내도 결과가 같은 오류는 재시도하지 않습니다. `Retry-After`는 최대 30초로 자릅니다. 요청이 보내진 뒤 실패하면 예상 비용으로 원장에 한 줄을 남깁니다(`status: "failed"`).
2. **C2 `extra` 우회**: `extra`에 `model`, `input`, `max_output_tokens`, `text`, `reasoning`, `stream`, `store`가 있으면 호출 전에 거부합니다. `-contributor` 검사는 대소문자를 가리지 않습니다.
3. **C3 원장 오류 시 통과**: 원장을 읽지 못하거나 한 줄이라도 해석하지 못하면 호출을 거부합니다(`BudgetLedgerError`). 원장 추가는 한 줄 단위로 쓰고 바로 flush합니다.
4. **C4 usage 없는 응답이 $0**: Spark 응답에 usage가 없거나 입력 토큰이 0이면 호출 전 예상 비용을 기록합니다.
5. **C5 스트림 재시도·기록 누락**: 스트림은 실제 요청이 나가는 `__enter__`까지 재시도로 감싸고, 실패 시에도 원장에 남깁니다.
6. **C6 실행당 상한 우회**: live·record 모드에서는 `run_id`를 반드시 받습니다(없으면 오류). `m0_spike.py`는 프로브마다 고정 `run_id`를 넘깁니다.
7. **C7 과소 추정**: 첨부 파일(PDF·이미지)은 파일 크기 기반으로 넉넉히 추정(예: PDF 쪽당 2,000토큰 이상, 근거를 주석에), 한국어 문자는 글자당 1토큰 이상으로 계산, SAM 영상은 `frame_count`를 필수로 받고 최소 50프레임, 영상을 `input_file`로 SAM에 보내는 경우도 프레임 기준으로 계산합니다. 추정은 실제보다 크게 잡는 쪽입니다.
8. **C8 동시 실행**: 예산 확인과 원장 기록 사이를 프로세스 안 잠금(`threading.Lock`)과 파일 잠금(Windows에서 동작하는 방식, 예: `msvcrt.locking` 또는 잠금 파일)으로 묶고, 호출 전에 예상 비용을 "예약" 줄로 남긴 뒤 끝나면 실제 비용 줄로 확정합니다(예약 줄은 합계 계산에 포함, 확정 시 상쇄).
9. **예산 환경 변수**(AGENTS.md 11/3 결정): `META_RUN_CAP_USD`(기본 2), `META_TOTAL_CAP_USD`(기본 100)를 `pricing.py`가 읽게 합니다. `.env.example`에 `META_RUN_CAP_USD=2`, `META_TOTAL_CAP_USD=100` 줄을 추가합니다(키 줄은 계속 빈 값).
10. **C9 비밀값 검사**: 추적되지 않은(무시되지 않은) `.env.*` 파일도 찾아내고(`.env.example` 제외), `.gitignore`에 `.env.*`와 `!.env.example`을 추가합니다.
11. **C11 키 유출 경로**: `_to_jsonable`의 `vars(obj)` 대체 경로를 없애거나 `_`로 시작하는 속성을 건너뜁니다.
12. **C12 업로드 파일 정리**: Files API로 올린 파일은 응답을 받은 뒤 삭제 호출을 합니다(record 모드에서는 삭제 응답도 fixture로 저장, replay에서는 재생). 삭제 실패는 경고로만 남깁니다.
12a. **C13 끊긴 응답**: `responses_create`가 응답 `status`를 확인해 `incomplete`(예: `max_output_tokens` 도달)면 성공으로 돌려주지 않고 `IncompleteResponse` 오류를 냅니다(비용은 원장에 기록). 호출자가 `max_output_tokens`를 올려 다시 시도할 수 있게 오류에 이유를 담습니다. Spark 판독 호출의 권장 `max_output_tokens`는 4,000 이상으로 주석에 적습니다.
12b. **C14 좌표계 표시**: `coords.py`에 박스와 좌표계를 함께 담는 형식(`Box { x1, y1, x2, y2, system: "norm1000" | "pixel", ref_w, ref_h }`)과 원본 픽셀로 바꾸는 함수 하나를 둡니다. Spark 박스는 `norm1000`, SAM 박스는 SAM이 알려 준 입력 크기 기준 `pixel`입니다(M0 리뷰). 다른 좌표계 박스를 섞어 계산하면 오류를 냅니다.
13. **C10 테스트 보강**: 아래가 실제로 장치를 깨면 실패하는 테스트여야 합니다.
    - 다른 `run_id`가 $1.99를 썼어도 이 실행의 호출은 허용(실행당 상한이 전체 합계를 쓰지 않음), 같은 `run_id` $1.99에서 $0.02 예상은 거부
    - 누적 상한: 환경 변수로 20을 주고 $19.99 원장에서 거부, 기본값 100 확인
    - `cost_usd` 값 자체를 검사(캐시 입력 $0.15, 추론 토큰 이중 계산 없음 — Meta 응답의 `output_tokens`에 추론 토큰이 포함되는지 M0 fixture로 확인해 주석으로 남김)
    - SAM 이미지·영상, Muse Image, 첨부 파일 추정 비용
    - 400은 재시도 안 함, 429는 3회 재시도 후 실패, SDK 재시도 꺼짐(`max_retries == 0`)
    - `extra` 금지 키 거부, 원장 손상 시 거부, usage 없는 응답이 예상 비용으로 기록
    - 요청 해시 안정성(키 순서를 바꿔도 같은 해시)
    - 키가 정말 코드에 들어가는 경로(`_require_key`를 거치는 생성 경로)에서 원장·fixture·예외 메시지에 키가 없음. 가짜 키 문자열로 시험하고 실제 키는 쓰지 않음
    - `time.sleep`은 패치해 테스트가 빨리 끝나게
14. 리포트 `reports/M0-fix1.md`(AGENTS.md 형식). 고친 항목마다 그 장치를 깨면 실패하는 테스트 이름을 적습니다.

## 주의 (기존 fixture 유지)

- 요청 해시에 들어가는 항목(모델, 엔드포인트, `store`, `max_output_tokens`, `text_format`, `reasoning`, `stream`, `extra`, 요청 내용)과 해시 계산 방식은 **바꾸지 않습니다**. 바꾸면 M0에서 기록한 fixture(특히 SAM 영상 `98f20261`, `a5f3ffe0`)가 재생되지 않습니다. C2는 `extra`의 금지 키를 거부만 하고 `extra`를 해시에서 빼지 않습니다.
- Muse Image는 지금 장당 $0.01로만 기록되는데 응답 usage에 토큰(입력 26,345, 출력 1,635)이 있습니다. 가격 페이지(https://dev.meta.ai/docs/pricing-rate-limits)에서 토큰도 과금되는지 확인해 단가표 주석에 적고, 과금된다면 그만큼 기록합니다.

## 하지 않을 일

- Meta 실호출, 기존 fixture 다시 기록(필요하면 리포트에 이유와 함께 제안)
- 위 파일 범위 밖 수정, `specs/` 수정, `.env` 읽기·만들기, 커밋과 푸시

## 완료 기준 (리뷰어가 그대로 다시 실행)

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m0-fix1"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"
& $PY -m pytest -q                                          # failed 0
cd $WT
& $PY tools\m0_spike.py --mode replay --probes all          # 9/9 success (키·네트워크 없이)
& $PY tools\secret_scan.py                                  # 종료 코드 0
Select-String -Path backend\app\meta\client.py -Pattern 'max_retries=0' -SimpleMatch   # 1건 이상
```
