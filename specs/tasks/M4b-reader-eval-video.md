# M4b 판독 모델 비교·영상 핵심 프레임 판독 (작업 지시서)

- 작성: 2026-11-03 13:46 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\m4b`(브랜치 `m4b`, M2a가 병합된 `main`에서 시작). M4a·M5와 동시에 진행.
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `reports/M2a.md`와 리뷰(판독 담당 구조), `reports/M0-review.md` 2절(채점 방식, 1.2/1.3, 영상 (나)), 에이전트 설계 3-1, 3-10(접수: 영상 프레임 추출)

## 목표

1. 판독 모델을 근거로 정합니다(1.2 vs 1.3). 2. 영상 증거(EX3)를 핵심 프레임으로 읽어 발화마다 `frame_ts`를 남깁니다(지금은 `skipped`).

## 파일 범위

고쳐도 되는 파일: `backend/app/agents/reader.py`, `backend/app/agents/intake.py`, `backend/app/agents/prompts/reader.v*.md`(새 버전), 새 파일 `tools/eval_reader.py`, `backend/app/agents/keyframes.py`, 새 테스트, 새 fixture, `reports/M4b-reader-eval.json`.
건드리지 않는 파일: `coordinator.py`·`vision.py`·`privacy_guard.py`(M4a), `packager.py`(M5), `services/`, `backend/app/meta/`, `frontend/`, `docs/`, `e2e/`.

## 할 일

1. **채점기** `tools/eval_reader.py`: 정답(`backend/tests/golden/kr_truth.json`)과 판독 결과를 **정답 박스 기준**으로 채점합니다(정답 항목마다 같은 `kind`의 가장 잘 맞는 판독 박스, 좌표는 픽셀로 변환). 지표: 금액·날짜 값 일치율(목표 95%), 정답 박스 IoU 0.3 이상 비율, 누락률, 스키마 실패·`incomplete` 비율, 원문 일치율, 지연 p50/p95, 비용. `ignore_regions`(워터마크 띠)는 제외. 정답 파일은 이 도구만 읽고 판독 담당에게 넘기지 않습니다.
2. **비교 실행(실호출)**: `muse-spark-1.2`와 `muse-spark-1.3`을 실제 쓸 설정(reasoning `low`, `max_output_tokens` 4,000)으로 EX1·EX2·EX4·EX5·EX6에 각 3회. 필요하면 1.3 `medium`도 1회. 결과를 `reports/M4b-reader-eval.json`에 쓰고 리포트에 표로. **결정 규칙**: 값 일치율 95% 이상인 모델 중 p95 지연이 짧은 것, 둘 다 미달이면 일치율이 높은 것. 결정한 모델을 `READER_MODEL` 기본값으로 바꾸고 이유를 리포트에.
3. **프롬프트 개선**(필요하면 `reader.v2.md`): 비교에서 드러난 누락(문장 안 금액·날짜를 별도 항목으로 내지 않음 등)을 고치고 같은 채점으로 다시 확인. 프롬프트에 샘플 이름·금액·날짜를 넣지 않습니다.
4. **영상 핵심 프레임** `agents/keyframes.py` + `intake.py`·`reader.py`: ffmpeg로 초당 2장 추출(시각 유지) → 비슷한 프레임 제거(지각 해시 등) → 핵심 프레임을 판독하고, 같은 말풍선은 처음 완전히 보인 프레임의 `frame_ts`로 합칩니다. 영상 증거의 `status`를 `ok`로, 판독 항목에 `frame_ts`. 채점: 정답 영상 항목의 `frame_ts` ±0.5초, 박스 IoU.
5. **기록**: 결정한 모델·프롬프트로 샘플 사건 판독(영상 포함)을 다시 기록해 재생 fixture를 갱신하고, 바로 재생으로 사건 흐름 테스트(M2a 테스트)를 돌려 누락이 없는지 확인. `run_id` = 비교 실행은 `M4b-eval-<model>-<n>`, 사건 기록은 사건 ID. `META_LEDGER_PATH`는 메인 저장소 원장.
6. 리포트 `reports/M4b.md`(AGENTS.md 형식, 끝까지 저장 확인): 비교 표, 결정과 이유, 영상 채점, 실호출 비용(원장 요약).

## 하지 않을 일

- SAM·가림(M4a), 편철(M5), 화면(M6), `specs/` 수정, `.env`, 키 출력, 커밋·푸시

## 완료 기준

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m4b"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q        # failed 0 (재생)
cd $WT; & $PY tools\eval_reader.py --mode replay   # 기록된 결과로 같은 표가 나옴
& $PY tools\secret_scan.py                   # 0
```
