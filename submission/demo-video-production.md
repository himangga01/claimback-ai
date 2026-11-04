# 데모 영상 제작 기록 (영어, 2:59)

- 작성: 2026-11-04 02:45 KST, Claude Code (서브에이전트 병렬 작업을 Claude가 조율·검토)
- 기준: main 08171ee (가림 확인 기능까지 병합). 녹화한 실제 호출은 main aa8af2d(잘못된 줄 가림 수정 병합 뒤) 코드.
- 계획: `submission/demo-video-plan.md` (장면표, 내레이션, 자막, 음악 지시)
- 목업 증거: `submission/demo-evidence/` (`en_*.png` 5장, `make_demo_evidence.py`로 같은 바이트로 다시 만듦)

## 결과물

영상 파일은 크기 때문에 저장소에 넣지 않았다(11-04 낮에 바뀜: 맨 아래 "업데이트" 참고, 최종본과 자막은 `docs/demo/`에 있음). 제작 폴더는 `C:\2026_project\claimback-demo-video\`(git 저장소 아님)이다.

| 파일 | 내용 |
|---|---|
| `out\claimback-demo.mp4` | 최종본(6차 렌더, 11-04 19:10 KST: 시작 카드에 대회 전·대회 중 작업 한 줄. 맨 아래 절 참고). 1920×1080, 30 fps, H.264 + AAC, 179.48초, 52.6 MB. 저장소 `docs/demo/`에도 같은 파일 |
| `out\claimback-demo_v4_card_no_disclosure.mp4`, `out\claimback-demo_v5_disclosure_first.mp4` | 4차 렌더(12:48, 시작 카드), 5차 렌더(18:26, 한 줄 첫 판) |
| `out\claimback-demo_v3_no_intro.mp4` | 3차 렌더(02:58 KST 무렵, 시작 카드 없음). 177.88초, 53 MB |
| `out\claimback-demo.srt` | 영어 자막(영상에도 박혀 있음) |
| `out\claimback-demo_preview720.mp4` | 휴대폰용 720p 사본(약 7.5 MB) |
| `out\claimback-demo_v1_before_review.mp4`, `out\claimback-demo_v2.mp4` | 1차 렌더(리뷰 전), 2차 렌더 |

## 사용자 결정 (2026-11-04)

- 폰트 Paperlogy, 영어 자막, 마우스 포인터 보이게, 실제 호출로 녹화, 포털도 영어(`?lang=en`).
- 데모용 영어 목업 자료를 먼저 만들고, 기능을 하나씩 보여 줄 것.
- 네모썰 자동화 프로젝트(`C:\2026_project\minecraft-longform`)의 Remotion과 Voicebox 사용법을 따를 것. 배경음은 목소리 대비 20%, 효과음 포함.
- 목소리: Voicebox 영어 기본 목소리 Ryan, 따로 듣고 승인하는 단계 없음("목소리 나오면 그냥 사용해, 모두 승인").
- 지출 상한 없음("상한 걸지마 데모 찍어야 하니까 그냥 써", 00:15).

## 만드는 방식

| 부분 | 방식 |
|---|---|
| 화면 녹화 | Playwright + CDP 스크린캐스트(무손실 PNG 프레임, 브라우저 타임스탬프)를 ffmpeg로 30 fps H.264(CRF 14). Playwright 기본 녹화(VP9, 25 fps)보다 작은 글자가 선명함(같은 순간 스크린샷 대비 45.9 dB 대 41.2 dB) |
| 마우스 포인터 | 화면에 그리는 DOM 커서(화살표 + 클릭 때 산호색 고리). 주소창과 Windows 파일 창은 찍히지 않으므로 "Running locally (127.0.0.1)" 표시와 업로드 칸 클릭으로 대신함 |
| 실제 호출 | 라이브 서버(포트 8040, `META_MODE=live`, 키는 사용자 환경 변수에서만 읽음). 세 번 찍어 두 번째가 합격. 1·3번째는 새 가림 검사가 "확인 필요"로 막아 탈락(판독 박스가 한 줄 어긋난 경우와 전화번호 가림이 신분번호 줄에 들어간 경우) |
| 내레이션 | Voicebox v0.5.0, Qwen CustomVoice 1.7B 기본 목소리 Ryan(프로필 "ClaimBack EN Ryan"). 43줄, 줄마다 faster-whisper로 받아쓰기 검사, 실패하면 시드를 바꿔 다시 생성. −20 LUFS로 맞춤 |
| 배경음 | 네모썰의 자체 합성 코드(numpy, 샘플·외부 음원 없음, 저작권 표기 불필요). D장조 96 BPM, 피아노·플럭 반복구를 40초마다 번갈아 씀 |
| 효과음 | 같은 합성 코드로 만든 클릭·휙·팝·딩(배경음과 같은 D 조) |
| 믹스 | 배경음은 목소리 아래 −14 dB(20%, 네모썰 규칙), 효과음은 고정 크기, 최종 −14 LUFS·−1 dBTP 이하 |
| 편집 | Remotion 4.0.538(네모썰과 같은 버전). `edit\build_timeline.py`가 녹화 로그와 음성 길이로 타임라인·자막·믹스 순서표를 만듦. 모델 대기는 "Sped up N×" 표시와 함께 빨리 감음 |

## 측정값 (최종본)

- 길이 177.88초(3분 이하). 시작 카드를 넣은 4차 렌더는 179.48초(아래 "시작 카드" 참고)
- 통합 음량 −14.0 LUFS, 실제 피크 −2.8 dBTP
- 배경음은 목소리보다 13.6~13.9 dB 낮음
- 받아쓰기 오류율 약 2%(첫 렌더 기준). "won"은 "Korean won"으로, "confirmed"는 다시 녹음해 고침
- 화면의 Meta 호출 수와 비용 34회 · $0.1887은 원장의 완료된 줄과 정확히 같음

## 비용

원장에서 실제 호출이 끝난 줄만 셌다(호출마다 예약 줄이 하나 더 있어서 전부 더하면 두 배 넘게 나옴).

- 영어 증거 시험 4회: $0.84
- 녹화 3회: $0.55

## 리뷰

- 1차 렌더 뒤 화면·자막 리뷰어와 소리 리뷰어가 따로 봤다. 둘 다 "고친 뒤 확정"이었다.
- 화면 9개, 소리 5개 지적을 고쳐 2차 렌더를 했다. 두 리뷰어가 항목별로 다시 확인했고, 둘 다 "확정"이었다.
- 2차에서 새로 생긴 문제(장면 제목 겹침 두 곳, 계산 화면 설명 자막 위치, 스테레오 효과음이 3dB 크게 들어감)를 고쳐 3차 렌더를 했다.
- 3차 결과는 Claude가 프레임으로 확인했다. −13.9 LUFS, 배경음은 목소리보다 13.9 dB 낮음.
- 남은 것: 2:38에서 커서가 "Copied"를 가림(녹화 자체).

## 제작 중 찾아 고친 제품 문제

- 잘못된 줄 가림이 통과하던 문제: `reports/fix-cost-redaction.md`
- "확인 필요" 가림을 화면에서 승인할 수 없던 문제: `reports/redaction-confirm.md`

## 다시 만들기

```powershell
cd C:\2026_project\claimback-demo-video
record\.venv\Scripts\python.exe record\record.py --mode live --base http://127.0.0.1:8040 --debtor-name "Alex J. Kim (SAMPLE)"
python edit\build_timeline.py --clips public\clips
npx remotion render Demo out/claimback-demo.mp4 --props=public/timeline.json
python edit\check_video.py out\claimback-demo.mp4
```

음성은 `audio\tts.py audio\narration.json`(Voicebox가 켜져 있어야 함, 127.0.0.1:17493)으로 다시 만든다. `build_timeline.py`가 `audio\mix.py`를 불러 배경음과 효과음을 섞는다.

## 남은 일 (사용자)

- 영상을 올리기(YouTube 비공개 링크 등).
- 링크를 제출 양식과 `submission/submission-notes.md`에 적기.
- `frontend/index.html`·`docs/index.html`의 "데모 영상 보기" 링크에 넣기(주소를 주면 Claude가 넣음).

## 업데이트 (2026-11-04 낮)

- 최종본과 자막을 저장소 `docs/demo/`에 넣었다(사용자 요청). GitHub 파일 화면은 mp4를 재생하지 않고 내려받게 하므로(다른 공개 저장소로 확인), 브라우저에서 바로 보는 주소는 GitHub Pages의 `https://himangga01.github.io/claimback-ai/demo/claimback-demo.mp4`로 정했다. README 썸네일(`assets/demo/demo-poster.jpg`)과 사이트의 "데모 영상 보기" 링크가 이 주소를 가리킨다.
- Pages는 사용자가 켰다(Settings → Pages → Deploy from a branch → `main` / `/docs`; Claude가 쓸 수 있는 브라우저에는 GitHub 로그인이 없었음). `docs/.nojekyll`을 넣어 Jekyll 처리를 끔(Jekyll이 `docs/analysis/plan-review.md`의 `{{quote:EX1:item3}}`를 조용히 지워 렌더링하고 있었음. 이제 `docs/`의 파일이 그대로 나감).
- 위 "남은 일"의 "데모 영상 보기" 링크는 이때 넣었다. 영상 업로드와 제출 양식은 사용자 일로 남는다(양식이 YouTube만 받으면 따로 올림).

## 시작 카드 (2026-11-04 12:48 KST, 4차 렌더)

사용자 요청: 영상 맨 앞에 서비스 이름과 간단한 설명, 깃 주소, 사용자 메일 주소(himangga01@gmail.com)를 넣는다.

- 카드 내용: "META GLOBAL AI DEVELOPER HACKATHON 2026", 로고 `claimback my money.`, "Your loan records, made clear.", 한 줄 설명(무료 셀프 도구, 직접 제출할 한국 법원 서류 초안), GitHub `github.com/himangga01/claimback-ai`, Contact `himangga01@gmail.com`.
- 3분 안에 넣는 방법: 카드만 나오는 1.6초(배경음만)를 앞에 붙이고, 카드는 첫 내레이션 줄 동안에도 남아 있다가 편집 시각 4.2초부터 0.4초 동안 시작 화면으로 사라진다(증거 카드가 날아 들어오는 5.0초 전). 첫 줄 동안 뒤 화면은 움직임 없는 시작 화면이라 가려도 잃는 것이 없다. 길이는 177.87 + 1.6 = 179.47초.
- 만드는 법: `edit\add_intro.py`가 기존 편집(`public\timeline.json`)은 그대로 두고 `public\timeline_intro.json`(intro 블록), 1.6초 뒤로 민 믹스 목록(`edit\mix_timeline_intro.json`, 시작 휙 소리만 0초 유지), 다시 섞은 배경(`public\mix\bed_intro.wav`), 1.6초 민 자막(`out\claimback-demo.srt`)을 만든다. Remotion은 `src\components\IntroCard.tsx`와 `src\Demo.tsx`(편집·자막을 `<Sequence from>`으로 1.6초 늦춤)로 그린다.

```powershell
cd C:\2026_project\claimback-demo-video
python edit\add_intro.py
npx remotion render Demo out/claimback-demo.mp4 --props=public/timeline_intro.json
```

- 측정: 179.48초, −14.0 LUFS, 실제 피크 −2.8 dBTP, 배경음은 목소리보다 13.9 dB 낮음(mix.py 보고서). `check_video.py`는 1.6초 이동을 몰라서 싱크·음악 구간 수치는 이 파일에 맞지 않는다. 그래서 자막 전환을 프레임으로 확인했다(7.29초에 둘째 줄로 바뀜).
- 파일 크기 52,327,967바이트(49.9 MiB)라 GitHub 50 MB 경고 아래.
- README 썸네일은 같은 장면(10.6초)으로 다시 만들고 길이 표시를 2:59로 바꿨다.
- 리뷰(화면·소리 리뷰어 2명, 둘 다 "확정"):
  - 화면: 카드 뒤 5,198프레임 전부를 이전 영상의 48프레임 앞과 비교했다. 23.6초부터는 같고, 그 전은 인코딩 잡음 수준이다(평균 차이 최대 0.34/255). 자막 43개는 모두 정확히 1.600초 뒤로 갔다. 카드 글자와 첫 자막 사이는 120 px 떨어져 있다.
  - 소리: 목소리 43줄과 효과음 43개가 모두 표본 단위로 1.600초 뒤에 있다(시작 휙 소리만 0초). 배경음은 목소리보다 −13.8~−14.2 dB, 1.6초 지점과 끝에 잡음이 없고, 음성과 영상 길이 차이는 10 ms다.
  - 남긴 작은 점: 첫 프레임이 빈 종이색이다(글자는 3프레임부터). 카드만 나오는 앞 2.4초는 배경음만이라 조용하다(배경음 20% 규칙대로). 설명 문구 "receipts and IOU"는 관사 없이 둔다.

## 대회 전·대회 중 작업 한 줄 (2026-11-04 19시 KST, 5·6차 렌더)

주최측 Discord 답변(18:17 KST, 사용자 전달): 영상은 "대회 전에 있던 것과 이번에 만든 것"을 말하는 한 줄로 시작해야 하고, YouTube·Loom 같은 호스팅 링크로 로그인 없이 재생돼야 한다(`docs/analysis/plan-review.md` 10장).

- 시작 카드 Contact 줄 아래에 파란 상자 한 줄을 넣었다: "Built during the hackathon (Oct 27–Nov 4): the case flow, agents, Meta model calls and documents. Existed before: the screen's visual style, from the owner's earlier project." 근거는 README "How it was built"와 커밋 기록(첫 커밋 11-02), 경매노트 저장소의 첫 커밋(10-20).
- 자리를 내려고 카드 위 여백을 150 → 112 px로 줄였다. 상자는 y 726–831, 첫 자막 상자(y 856)와 24 px 떨어진다.
- 5차 렌더(18:26): 화면 리뷰어가 "확정"이라고 봤다. 카드 뒤 프레임 250부터 끝까지 4차와 차이 0, 소리는 표본 단위로 같음, 자막 파일 같음, −14.0 LUFS, −2.8 dBTP, 179.477초. 다만 상자가 온전히 보이는 시간이 4.4초뿐이라 읽기 빠듯하다고 지적했다. 내용 리뷰어는 문구는 정확하나 "only"는 빼라고 했다(배경음 합성 코드가 다른 개인 프로젝트에서 왔고 그 코드의 작성 시점을 증명할 수 없음).
- 6차 렌더(19:10, 최종본): "only"를 빼고 문구를 줄였으며, 상자가 프레임 6부터 올라오게 해 약 5초 동안 온전히 보이게 했다. 179.477초, 52,634,653바이트. Claude가 5차와 비교했다: 카드 뒤 프레임 186–249는 인코딩 잡음(평균 차이 최대 0.19/255), 250부터 끝까지 차이 0, 소리 PCM 해시 같음. 1초 프레임에서 상자가 이미 보인다.
- 백업: `out\claimback-demo_v4_card_no_disclosure.mp4`(4차), `out\claimback-demo_v5_disclosure_first.mp4`(5차).
