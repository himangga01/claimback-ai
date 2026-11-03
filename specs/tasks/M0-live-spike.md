# M0 실호출 스파이크 + Meta 클라이언트 (작업 지시서)

- 작성: 2026-11-03 11:42 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`)
- 목표 시각: 11/3 14:00 KST (계획서 v2.3 압축 일정)
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `reports/M-1-review.md`. 참조: 계획서 `specs/ClaimBack-AI_검토_및_구현테스트계획.md` 2장 모델 표와 공통 설정, 4-5 M0행, 4-6 L2·L3, 4-7 / 에이전트 설계 `specs/ClaimBack-AI_에이전트_설계.md` 3-1(판독), 3-2(시각 감식), 4-1(AuditRecord)
- 공식 문서: https://dev.meta.ai/docs/models 와 그 안의 API 문서, https://pypi.org/project/meta-sam-parser/ . 쓴 문서 URL은 리포트에 적습니다.

## 배경

M-1이 끝나 테스트 25개가 모두 통과합니다(`reports/M-1-review.md`). 아직 Meta API 연동은 없습니다. 이번 작업은 두 가지입니다.

1. 앱이 쓸 Meta 클라이언트: 예산 상한, 비용 원장, `META_MODE=live|record|replay`
2. 실제 호출 스파이크: 이후 마일스톤 설계에 필요한 사실(좌표 형식, 판독 모델, 영상·PDF 입력 방식, SAM 출력 파싱)을 확인하고, 응답을 재생 fixture로 저장

키는 환경 변수 `MODEL_API_KEY`에 이미 들어 있습니다. 값을 읽어 출력하거나 파일에 쓰지 않습니다.

## 할 일

### 1. Meta 클라이언트 (`backend/app/meta/`)

- OpenAI Python SDK(`openai`, 버전 고정), base URL `https://api.meta.ai/v1`, 키는 호출 시점에 `MODEL_API_KEY`에서 읽음. live·record 모드에서 키가 없으면 키 이름만 적은 오류.
- 모델 ID에 `-contributor`가 들어 있으면 호출 전에 거부.
- 모드(`META_MODE`, 기본 `replay`):
  - `replay`: fixture에서 응답을 읽음. fixture가 없으면 오류(실호출로 넘어가지 않음). 키 불필요.
  - `record`: 실호출 후 fixture 저장.
  - `live`: 실호출만, 저장 안 함.
- fixture: `backend/tests/fixtures/meta/<요청 해시>.json`. 요청 해시는 모델, 엔드포인트, 파라미터, 메시지(첨부 파일은 바이트 대신 SHA-256)를 정렬한 JSON의 SHA-256. 파일에는 요청 요약, 응답 본문, usage, 지연 시간을 넣고 키·인증 헤더는 넣지 않습니다.
- 비용 원장 `reports/cost_ledger.jsonl`: 실호출(live, record)마다 한 줄. 시각, `run_id`, 모델, 엔드포인트, 입력·캐시 입력·출력 토큰(추론 토큰이 따로 오면 따로), 이미지 수·프레임 수, 추정 비용(USD), 지연 시간.
- 예산 상한: 호출 전에 예상 비용을 계산해 같은 `run_id` 누적 + 예상 > $2, 또는 원장 전체 누적 + 예상 > $20이면 호출하지 않고 `BudgetExceeded`. 예상 비용은 입력 추정 토큰 × 입력 단가 + `max_output_tokens` × 출력 단가(호출자는 `max_output_tokens`를 반드시 지정), SAM은 이미지·프레임 수(영상은 요청당 최소 50프레임)로 계산.
- 단가표 `backend/app/meta/pricing.py`: 계획서 4-7 값(Spark 입력 $1.25 / 출력 $4.25, SAM 이미지 1,000장당 $2.50, 영상 1,000프레임당 $0.20, Muse Image 장당 $0.01)과 캐시 입력 단가. Meta 공식 가격 페이지에서 확인한 값과 URL, 확인 날짜를 주석으로 적고, 공식 페이지에서 못 찾은 값은 "미확인"으로 표시합니다.
- 429와 일시적 5xx는 지수 백오프로 최대 3회 재시도.
- 원장, fixture, 로그, 예외 메시지 어디에도 키가 나오지 않게 합니다.

### 2. 스파이크 입력 생성 (`tools/make_spike_inputs.py`)

Pillow, reportlab, ffmpeg(이 PC에 설치됨)로 합성 입력을 만듭니다. 모두 "SAMPLE / 데모용" 표시, 가상 이름(`(SAMPLE)` 붙임), 가상 은행·앱 이름("샘플은행", "샘플톡"), 번호는 `010-0000-0000`과 `0000-00-000000` 형식만 씁니다. 실존 인물, 브랜드, TV 인물을 흉내 내지 않습니다.

- 대화 캡처 이미지 1장: 말풍선 4~6개, 금액·날짜가 들어간 "갚겠다" 메시지 포함
- 이체 확인증 이미지 1장: 금액, 날짜, 보낸 사람·받는 사람, 가린 계좌번호
- 차용증 2쪽 PDF 1개: 금액, 날짜, 서명 자리(손글씨 느낌 선), 빨간 도장 모양
- 대화 스크롤 영상 1개: 위 대화 이미지를 위로 스크롤하는 5초 안쪽, 작은 해상도(1 MB 이하)
- 정답 박스 파일 `backend/tests/fixtures/spike_inputs/truth.json`: 말풍선, 금액, 날짜, 서명, 도장의 실제 픽셀 박스. 테스트·스파이크 채점에만 쓰고 모델에 넘기지 않습니다(골든셋 규칙).

출력 위치: `backend/tests/fixtures/spike_inputs/`

### 3. 스파이크 실행 (`tools/m0_spike.py`)

`python tools\m0_spike.py --mode record --probes all` 형태. 프로브마다 `run_id`를 따로 씁니다. 결과는 `reports/M0-spike.json`(프로브별 성공 여부, 모델, 사용한 API, 지연, 토큰, 추정 비용, 판정 근거)에 저장합니다. 같은 명령을 `--mode replay`로 돌리면 키와 네트워크 없이 같은 결과가 나와야 합니다.

| 프로브 | 내용 | 확인할 것 |
|---|---|---|
| P0 | `GET /models` | 쓸 모델 ID(`muse-spark-1.1`, `1.2`, `1.3`, `sam-3.1`, `muse-image-1.0`)가 목록에 있는지. `-contributor`가 아닌 Standard ID |
| P1 | Spark 1.3 텍스트, JSON 스키마 출력 | Responses API 동작, usage 필드 이름(캐시·추론 토큰 포함) |
| P2 | Spark 1.3 이미지 판독(대화 캡처, 이체 확인증) | 설계 3-1 `Reading` 형식으로 발화·금액·날짜와 박스. **좌표 형식 판정**: 반환 박스를 픽셀, 0~1000 정규화, 0~1 정규화로 각각 해석해 `truth.json`과 IoU를 비교하고 가장 맞는 해석을 고름 |
| P3 | Spark 1.3 PDF 직접 입력(차용증) | 받는지, 어떤 방식(파일 업로드, 입력 파트)인지, 금액·날짜를 읽는지 |
| P4 | Spark 1.3 영상 직접 입력(스크롤 영상) | 받는지, 발화를 읽는지, 지연과 비용. 설계 3-1의 영상 (가)/(나) 판단 근거 |
| P5 | SAM 3.1 이미지: 명사구("signature", "red stamp", "chat bubble")와 박스 프롬프트 | 호출 방식(Responses + Files API), `meta-sam-parser`(0.1.0)로 파싱, `truth.json` 대비 IoU |
| P6 | SAM 3.1 영상: 말풍선 1개 추적 | 동작 여부, 과금 프레임 수(최소 50), 결과 형식 |
| P7 | Muse Image 1.0: 글자 없는 타임라인 삽화 1장 | 이미지 저장(`backend/tests/fixtures/spike_outputs/`), 프롬프트에 "글자 없음"을 넣었을 때 글자가 들어가는지는 리뷰어가 눈으로 확인 |
| P8 | 판독 속도 비교: 1.1, 1.2, 1.3에 같은 대화 캡처를 2회씩 | 평균 지연, 금액·날짜 일치 여부(`truth.json`) |

- M0 실호출 합계는 **$3 이하**로 잡습니다. 넘을 것 같으면 남은 프로브를 건너뛰고 리포트에 적습니다. (11/3 12:00 사용자 결정으로 이 상한은 해제했습니다. 이미 실행 중인 Muse Code에는 전달되지 않았으므로, $3 때문에 건너뛴 프로브가 있으면 리뷰 뒤 다시 돌립니다.)
- 실패한 프로브는 오류 종류(HTTP 상태, 메시지 요약)를 기록하고 다음 프로브로 넘어갑니다. 같은 프로브는 최대 2회까지만 다시 시도합니다.
- 응답 본문을 리포트에 길게 붙이지 않습니다. 판정에 필요한 값만 적습니다.

### 4. 테스트 (네트워크 없이)

`backend/tests/test_meta_client.py` 등. 가짜 전송 계층(가짜 OpenAI 클라이언트)을 주입해 다음을 확인합니다.

- 실행당 $2, 누적 $20 상한에서 호출 전 거부(임시 원장 사용)
- 원장 한 줄의 필드, 키가 들어가지 않음
- record → replay 왕복, replay에서 fixture가 없으면 오류
- `-contributor` ID 거부
- live 모드에서 키가 없으면 오류 메시지에 키 이름만 나옴
- 429 재시도 후 성공, 3회 넘으면 실패
- 좌표 변환 함수(정규화 → 원본 픽셀)
- 저장된 fixture 전체에 키 형식 문자열이 없음(`tools/secret_scan.py` 규칙 재사용)

pytest는 기본으로 `META_MODE=replay`로 돌고 키가 없어도 통과해야 합니다.

### 5. 비밀값 검사 보완 (리뷰 R6)

`tools/secret_scan.py`가 `.env`뿐 아니라 `.env.*`(`.env.example` 제외)도 추적·스테이징 여부를 검사하게 합니다.

### 6. 의존성

`requirements.txt`에 `openai`, `meta-sam-parser==0.1.0`, `Pillow`를 버전 고정으로 추가하고 루트 `.venv`에 설치합니다.

### 7. 리포트 `reports/M0.md`

`AGENTS.md` 형식에 더해 다음을 적습니다.

- 프로브 결과 표(성공 여부, 모델, API, 지연, 비용)
- 제안: 좌표 형식과 근거(IoU 수치), 판독 모델(속도·정확도), 영상 입력 방식 (가)/(나), PDF 입력 방식, SAM 호출·파싱 방식
- 원장 합계(M0 실호출 총비용)
- 이후 마일스톤이 알아야 할 API 특이사항(필드 이름, 제한, 오류)

## 하지 않을 일

- 판독·사실 정리 담당 구현, 파이프라인·화면 연결(M2 이후), 프롬프트 파일 체계(`backend/app/agents/prompts/`)
- 계산기·게이트 문구 수정(M1), 샘플 증거 세트 교체(M3)
- `specs/` 수정(제안은 리포트 6번), `.env` 읽기·만들기, 키 출력
- 커밋과 푸시
- Muse Wonder 등 한국에서 쓸 수 없는 모델, `-contributor` 모델

## 완료 기준 (리뷰어가 그대로 다시 실행)

```powershell
cd C:\2026_project\claimback-ai-meta
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue   # 키 없이
cd backend
..\.venv\Scripts\python.exe -m pytest -q          # failed 0
cd ..
.\.venv\Scripts\python.exe tools\m0_spike.py --mode replay --probes all   # 키·네트워크 없이 reports\M0-spike.json과 같은 판정
.\.venv\Scripts\python.exe tools\secret_scan.py    # 종료 코드 0
Get-Content reports\cost_ledger.jsonl | Measure-Object -Line   # 실호출 수와 리포트 값 일치, 합계 $3 이하
```
