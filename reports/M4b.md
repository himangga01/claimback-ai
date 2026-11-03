# M4b 리포트 — 판독 모델 평가·긴 이미지 박스·영상 핵심 프레임

## 1. 작업 브리프와 요약

- 브리프: `specs/tasks/M4b-reader-eval-video.md` (M4 판독 결정 + R1 + 영상).
  함께 읽은 문서: `specs/ClaimBack-AI_에이전트_설계.md` 3-1/3-10,
  `specs/case-api-contract.md`, `reports/INT-2.md`, `reports/INT-2-review.md`,
  `reports/M0-review.md`, `reports/M2a.md`, `reports/M2a-review.md`.
- 한 일:
  1. 정답-박스 기준 채점기 `tools/eval_reader.py` 작성. 금액·날짜 값 일치율,
     정답 박스 IoU 0.3+ 비율, 누락률, 스키마 실패·incomplete 비율, 원문 일치율,
     지연 p50/p95, 비용을 표로 내고, `--mode replay`는
     `reports/M4b-reader-eval.json`에 기록된 결과만으로 같은 표를 낸다(키 불필요).
     채점기는 INT-2 기록 결과로 리뷰 수치(EX1 5/16, EX2 0/24, EX6 5/27)를
     정확히 재현함을 먼저 확인했다.
  2. 비교 실호출(1.2 vs 1.3, reasoning low, 4,000토큰, v1, 통째 읽기,
     EX1·EX2·EX4·EX5·EX6 각 3회): 둘 다 값 일치율 95% 이상
     (1.2: 98.8% = 80/81, 1.3: 97.5% = 79/81) → p95가 짧은
     **muse-spark-1.2**(8.8초 vs 33.2초)를 판독 모델로 결정.
     `READER_DEFAULT_MODEL`을 1.2로 바꿨다(브리프 규칙 그대로).
  3. 비교에서 드러난 한글 금액(`금 오백만 원` → normalized 포기, 3건) 누락을
     고친 `reader.v2.md` 작성(문장 안 금액·날짜 별도 항목 명시 포함).
     v2에서 양쪽 값 일치율 100%, 회귀 없음 → v2를 기본으로 채택.
  4. 3a 긴 이미지: 너비-정규화 가설을 실측으로 기각하고(§5),
     겹침 타일(가로세로비 1.0 이하, 겹침 10%, 균등 배치)을 기본으로 채택.
     통째 14.9% → 타일 57.5%(최종 코드, 값 100% 유지). 정사각 패딩은 실패.
     타일 경계 중복은 밴드+순서 매칭으로 합치고 쌍 박스는 평균한다.
     범위 밖 박스는 조용히 자르지 않고 `box_warning: out_of_range`로 표시한다.
  5. 영상: `keyframes.py`(ffmpeg 프레임-정확 추출, 초당 2장+tail, dHash 중복 제거)
     + `run_video_reader`(키프레임 판독, 출현 분리 병합, 첫 완전가시 frame_ts).
     EX3: 값 100%, 원문 100%, frame_ts ±0.5초 100%(24/24), 박스 54.2%.
     1.3-영상 대조도 동률이라 영상도 1.2로 통일한다.
  6. 결정 설정(1.2·v2·타일)으로 샘플 사건을 CHECKPOINT_2까지 다시 기록해
     재생 fixture를 갱신하고, 쓰이지 않는 이전 fixture 15개를 지웠다.
     전체 pytest 291개 통과, 비밀 스캔 깨끗함.

## 2. 만들거나 고친 파일

- 새로 만듦
  - `backend/app/agents/keyframes.py`: ffmpeg 프레임-정확 추출(`select`+ffprobe),
    dHash 지각 해시, 키프레임 선택. 모델 호출 없음, 정답 파일 읽기 없음.
  - `backend/app/agents/prompts/reader.v2.md`: v1 + 문장 안 금액·날짜 별도 항목 +
    한글 금액 환산. 샘플 토큰·금지 표현 없음(위생 테스트 통과).
  - `tools/eval_reader.py`: 채점+실행+표 출력. 정답 파일은 이 도구만 읽는다.
  - `backend/tests/test_m4b_reader.py`: 27개 테스트(아래 §3).
  - `reports/M4b-reader-eval.json`: 13개 실험, 83개 실행 기록 전부.
- 고침
  - `backend/app/agents/reader.py`: 타일 계획·크롭·매핑·병합(밴드+순서+평균),
    정사각 패드 변형, `run_video_reader`, 범위 밖 플래그,
    기본값 1.2·v2·TILE_MAX_ASPECT 1.0. 정사각 증거는 원본 바이트 단일 호출로
    이전과 동일하게 동작한다.
  - `backend/app/agents/intake.py`: `extract_video_keyframes`(증거 폴더 저장+
    manifest 캐시, 버전 `select-v2`)만 추가. 기존 등록·미리보기 동작 무변경
    (계약 테스트가 영상 `skipped`를 고정하므로 유지).
  - `backend/tests/fixtures/meta/`: INT-2 사건 fixture 8개 + 재기록 1~3차 고아 7개
    삭제, 영상 키프레임 30개 + 최종 사건 14개(판독 11·정리 1·문안 2,
    문안 1건은 incomplete→8,000 재시도) 추가. 최종 74개.
- 건드리지 않음(브리프 범위): `coordinator.py`(M4a),
  `specs/`, `AGENTS.md`, `docs/`, 기존 리포트. 영상 사건 흐름 연결은
  코디네이터 변경이 필요해 INT-3 제안으로 넘겼다(§5·§6).

## 3. 실행한 명령과 결과(재실행 가능)

- Python은 사용자 지시대로 메인 repo venv를 썼다(워크트리에는 `.venv`가 없음).
  키는 `MODEL_API_KEY` 환경변수에서만 읽었고 값을 출력·기록하지 않았다.
  원장은 `$env:META_LEDGER_PATH="C:\2026_project\claimback-ai-meta\reports\cost_ledger.jsonl"`.

### 3-1. 완료 기준

```
cd C:\2026_project\claimback-wt\m4b\backend
C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe -m pytest -q
→ 291 passed in 25s (키 없이 실행, 0 실패)
```

```
cd C:\2026_project\claimback-wt\m4b
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
Remove-Item Env:MODEL_API_KEY   # 키 제거 상태로 확인
& $PY tools\eval_reader.py --mode replay
→ exp=compare 표 출력, 종료 0. 13개 실험 전부 "기록 summary == 재계산" 동일 확인.
```

```
C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe tools/secret_scan.py
→ secret_scan: clean
```

- 서버·백그라운드 프로세스를 남기지 않았다(uvicorn 미사용, TestClient만 사용).
- `reports/M0-spike.json`은 변경되지 않았다(`git status` 확인).

### 3-2. 비교 표(브리프 항목 2·3·3a·4)

비교(v1, 통째 읽기, 증거당 3회, run_id `M4b-eval-<model>-<n>`):

| 모델 | 값% | 박스03% | 원문% | 누락% | 스키마% | p50ms | p95ms | 비용 |
|---|---|---|---|---|---|---|---|---|
| 1.2 | 98.8 (80/81) | 35.5 | 96.4 | 52.3 | 0.0 | 5927 | 8826 | $0.1443 |
| 1.3 | 97.5 (79/81) | 43.4 | 98.9 | 36.6 | 0.0 | 23804 | 33151 | $0.1635 |

둘 다 95% 이상 → p95가 짧은 1.2. 값 실패는 전부 `금 오백만 원` 정규화 포기
(1.2: 1회, 1.3: 2회). 1.3 medium 추가 실행은 불필요했다(이미 둘 다 통과라
결정이 안 바뀌고 p95만 나빠진다).

v2(통째 읽기, 각 1회): 양쪽 값 100%, 회귀 없음 → v2 채택.
1.2: 박스 38.7, p95 6449. 1.3: 박스 38.7, p95 22459. 결정 유지(1.2).

3a(1.2·v2, EX1·EX2·EX6, 값 100% 유지):

| 설정 | 박스03% | 비고 |
|---|---|---|
| 통째(v2) | 14.9 (10/67) | 기준 |
| 타일@1.5 | 25.4 | EX1·EX6은 단일 타일이라 그대로 |
| 타일@1.25 | 45.8 (92/201, 3회 합) | |
| 타일@1.0 | 65.2 (131/201, 3회 합) | 균등 배치 전, IoU 병합 |
| 정사각 패드 | 3.0 (값 56.5%) | 실패 — 내용이 얇은 띠가 되면 모델이 훑어읽음 |
| 타일@1.0 최종 코드 | **57.5 (77/134, 2회)** | 균등 배치+밴드+평균 병합(adopted) |
| 1.3 타일@1.0 참고 | 93.5 (1회) | 값 100, p95 53초. 박스는 앞서나 규칙상 1.2 유지 |

타일 수는 EX1 2장, EX2 5장, EX4·EX5 1장, EX6 2장이다.

영상(EX3, 15 키프레임×2타일=30호출, 2.3분):

| 모델 | 값% | 박스03% | 원문% | frame_ts ±0.5초 | 시간 | 비용 |
|---|---|---|---|---|---|---|
| 1.2 | 100 | 54.2 | 100 | **100 (24/24)** | 141초 | $0.1448 |
| 1.3 | 100 | 58.3 | 100 | 95.8 (23/24) | 397초 | $0.1759 |

스틸 박스에서 1.3이 크게 앞섰으나(93.5 vs 65) 영상에서는 동률이다.
압축 아티팩트가 지배적이라 모델 차이가 사라진다. 영상도 1.2로 통일한다.

### 3-3. 평가 실행 명령(대표)

```
# 비교 30회
& $PY tools/eval_reader.py --mode live --exp compare --runs 3 --reader-mode whole --jobs 2
# v2 10회
& $PY tools/eval_reader.py --mode live --exp prompt-v2 --runs 1 --reader-mode whole --prompt-file reader.v2.md --jobs 2
# 3a 변형(타일 종횡비·패드), 최종 설정, 영상(record, fixture 저장)
& $PY tools/eval_reader.py --mode live --exp tiles-1.0 --models muse-spark-1.2 --runs 1 --evidence EX1,EX2,EX6 --prompt-file reader.v2.md --reader-mode tiles --tile-aspect 1.0 --jobs 2
& $PY tools/eval_reader.py --mode live --exp adopted --models muse-spark-1.2 --runs 2 --evidence EX1,EX2,EX6 --prompt-file reader.v2.md --reader-mode auto --jobs 2
& $PY tools/eval_reader.py --mode record --exp video --models muse-spark-1.2 --runs 1 --evidence EX3 --video --prompt-file reader.v2.md --reader-mode auto --jobs 1
```

### 3-4. 사건 재기록(브리프 항목 5)

```
$env:META_MODE="record"; $env:READER_CONCURRENCY="1"
C:\...\python.exe .local/m4b_record_run.py   # 워크트리 .local, git 무시됨
```

4차 시도 `case_ed0593343e37`이 CHECKPOINT_2까지 통과했다(수정 0회, 게이트 전부
통과, `remaining_principal` 4014383 유지, 판독 수 EX1 18·EX2 25·EX4 14·EX5
14·EX6 30). 2차는 문안 G3 run-on 2회 초과로 HOLD였는데, 판독·정리·계산은 전부
정상이고 문안 생성 샘플링 문제(M2c 영역, INT-2 리뷰 A3 기재)라 재시도했다.
자세한 fixture 식별·삭제 과정은 §5를 본다.

### 3-5. 새 테스트 27개(`test_m4b_reader.py`, 전부 키 없이 통과)

타일 계획 3, 박스 변환·플래그 3, 타일 매핑·패드 2, 타일 병합 5(밴드 쌍·순서
매칭·절단 조각, 평균값 회귀 포함), 키프레임 추출·정확성·캐시 4, 영상 병합 3,
채점기 4(정규화·정답박스·누락·frame·결정 규칙), 기본값·v2 위생 2, eval 재생 1,
영상 재생 1. 전체 291개 중 새 테스트가 27개이며 기존 테스트는 무수정이다.

### 3-6. 측정한 사실(리뷰 후속)

- INT-2 리뷰 P4(연도 없는 날짜): 비교 6회 전체에서 연도 환각 0건.
  v2 `null` 유지 확인.
- INT-2 리뷰 R1(긴 이미지): 위 표대로 타일로 해결(14.9→57.5%).
- M2a 리뷰 P2(연속 쌍): `_validate`가 쌍을 강제하므로 발생 불가. 비교·영상·
  재기록 포함 400회 이상 호출에서 스키마 실패·incomplete 0건(문안 1건
  incomplete→재시도 성공은 판독이 아님).
- 1.2 OCR 노이즈(보고용, 결정 불변): EX1 작은 글씨에서 탁→타 혼동(4회 중
  1.2는 2회·1.3은 1회, EX2·EX4·EX5·EX6 이름은 항상 정확), 주민번호 끝자리
  탈락 1회, 발화 줄바꿈·문장부호 변형 수회. 사건 흐름에서는 EX2·EX4·EX5·EX6
  4개 증거가 올바른 이름을 주므로 정리 결과는 정확했다(§3-4,
  `debtor_name` 정확, conflict 플래그만 참).

## 4. 실호출(모델·횟수·비용, 원장 기준)

- 모델: `muse-spark-1.2` 324회, `muse-spark-1.3` 102회. 전부 Standard ID.
- 횟수: 원장 completed 426회(평가 live·record + 재기록 4차 + 스모크 1회).
  판독 호출은 타일·키프레임 단위로 센다(예: 영상 1회=30호출).
- 비용: 내 run_id 합계 **$2.894815**(원장). run_id별:
  M4b-eval-* 12개 $2.356721 + 내 사건 4개 $0.538094
  (case_bb09bc44fed1 $0.154566, case_1fa144fd87d1 $0.135649,
  case_af223bf2b7e2 $0.116113, case_ed0593343e37 $0.131766).
  JSON 안 호출별 cost_usd 합계와도 일치한다.
- 원장 전체 $3.566825(completed 538건, 전체 라인 130→1039).
  시작 시점 $0.580864에서 내 지출 $2.8948 + 타 에이전트 지출(동일 원장 공유)
  + 기존분이 합산된다. 남은 크레딧 약 $146로 $10 데모선과 무관하다.
  캡 차단·에러 0건(원장 상태 completed·reserved만 존재).

## 5. 열린 문제와 브리프·스펙과의 차이

1. 너비-정규화 가설 기각(브리프 "먼저 확인할 가설"). INT-2 기록 박스를 정답과
   대조한 결과 y_vs_widthnorm 중앙값은 EX1 0.75·EX2 0.41·EX6 0.74로 1.0이
   아니다. 축별 스케일(모델y/정답y)은 정사각 1.00, EX6 1.05, EX1 1.13,
   EX2 1.51로 이미지별·이미지 내부 위치별로 다르다. 싼 변환 수정은 불가하고
   타일이 정답이었다.
2. 1.3의 스틸 박스 우위(93.5% vs 65%, 1회 한정)에도 규칙대로 1.2를 유지했다.
   규칙이 값·지연만 보게 되어 있고 둘 다 값을 통과했기 때문이다.
   1.2 타일 박스 57.5%는 기준(14.9%)의 4배이며, 잔여 오차는 타일별 독립
   노이즈(쌍 평균으로 완화)다. 타일별 기울기 보정·더 작은 타일은 후속 과제다.
3. 1.2 OCR 노이즈(§3-6): EX1 탁→타(50%), 주민번호 1건 탈락. 사건 흐름에서는
   다수 증거가 교정했으나, 단일 증거 사건에서는 이름 오류가 그대로 갈 수
   있다. M2c 이름 교차 확인(A4) 후속과 연결된다.
4. 영상 사건 흐름 미연결(파일 범위 탓, 브리프 항목 4와의 차이). EX3은 사건
   흐름에서 여전히 `skipped`이며 기존 계약 테스트도 그것을 고정한다.
   `run_video_reader`·키프레임 저장·eval 채점은 완성했고, 코디네이터 연결
   3줄+검증 보존은 INT-3에서 한다(§6). 계약서 EX3 행·`readings.json` 예시도
   그때 함께 바뀐다.
5. `READER_MODEL` 기본값이 `reader.py`에 있다(`deps.py`는 다른 워크스트림 소유라
   범위 밖). env가 이기므로 동작은 같고, 단계표 표시 통일용 한 줄은 INT-3용(§6).
6. 재기록 2차 HOLD(문안 G3 run-on 2회 초과): 판독·정리·계산은 정상이었고
   문안 샘플링 문제라 재시도해 4차에 통과했다. 문안 fixture 1건은
   incomplete→8,000토큰 재시도 성공분이라 재생도 그 경로를 탄다(2개 파일).
7. fixture 정리 내역: INT-2 사건 8개 + 재기록 1~3차 고아 7개 삭제(계산서
   해시·mtime 윈도우·프롬프트 종류로 식별). 최종 74개=기존 30+영상 30+
   사건 14. 삭제 후 전체 pytest 통과로 무사용을 증명했다.
8. 평가 초반(n=1) 실험들은 run_id `M4b-eval-<model>-1`을 공유한다(브리프 지정
   run_id는 비교 실험에만 적용). 이후 실험은 `M4b-eval-<exp>-<model>-<n>`으로
   분리했다. 호출별 비용은 JSON에 있어 실험별 집계는 정확하다.
9. 브리프·스펙 충돌은 없었다. pytest는 사용자 지시대로 메인 venv로 실행했다
   (워크트리 `.venv` 없음).

## 6. 스펙 변경 제안(`specs/`는 직접 고치지 않음)

1. 설계 3-1 판독 모델: `muse-spark-1.2`(low, 4,000토큰, v2 프롬프트)로 확정.
   긴 이미지는 겹침 타일(종횡비 1.0 이하, 겹침 10%, 균등 배치, 경계 쌍 평균).
   박스 범위 밖은 자르지 않고 `box_warning` 표시.
2. 설계 3-1·3-10 영상: `select` 프레임-정확 추출(초당 2장+tail),
   dHash 중복 제거, 출현 분리 병합(첫 완전가시 frame_ts)을 명시.
3. 계약서: INT-3 연결 후 EX3 `status` ok·읽기 항목 `frame_ts` 포함으로 갱신,
   `readings.json` 예시에 영상 항목 추가.
4. INT-3 코디네이터 패치(참고용):
   - `_read_one`의 `video → skipped`를 `run_video_reader` 호출로 교체.
   - `validate_reading_items`가 `frame_ts`·`box_warning`을 보존.
   - `deps.READER_MODEL` 기본값을 1.2로(단계표 표시 통일).
5. M4a 연계: `box_warning` 항목·작은 박스(id·계좌·전화)는 교정 미리보기
   "확인 필요" 대상으로, G6 재독·유출 검사를 유지할 것.
