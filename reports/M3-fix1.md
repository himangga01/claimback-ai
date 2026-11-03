# M3-fix1 리포트 (정답 데이터·샘플·라이선스·README 보강)

- 작성: 2026-11-03, Muse Code (`muse-spark-1.3`)
- 작업 지시서: `specs/tasks/M3-fix1-golden-and-docs.md` (작성 2026-11-03 13:05 KST, Claude)
- 함께 읽은 문서: `AGENTS.md`, `reports/M3-review.md`(S1~S14), `specs/case-api-contract.md` 2장
- 작업 트리: `C:\2026_project\claimback-wt\m3-fix1` (브랜치 `m3-fix1`), Meta 실호출 없음
- 판정 요약: 지시서의 S1~S11을 전부 처리했다. 전체 테스트 120 passed + 1 xpassed(기존 `frontend` 건, 범위 밖), 재생성 바이트 동일(차이 0건), secret scan clean.

## 1. 한 일

- **S1 (차단) 증거 번호 정리**: `kr_truth.json`에서 EX7(`iou.png` 단독 항목)을 삭제하고 EX6(`iou.pdf`)만 남겼다. 박스 기준은 기존 `coord_basis: "kr/iou.png"`(미리보기 PNG 픽셀) 그대로 두었다. 영어 세트도 EX4(PNG 중복)를 삭제하고 EX3(PDF, `coord_basis: "en/promissory_note.png"`)만 남겼다. KR EX1~EX6의 `ex_id → 파일` 대응과 순서가 약속 문서(`specs/case-api-contract.md` 2장) 표와 일치한다. `test_truth_evidence_order_matches_contract` 테스트를 추가했다.
- **S2 영상 정답 재계산**: 말풍선·토큰·비전 항목마다 tall 이미지 박스가 뷰포트(고정 SAMPLE 띠 아래)에 **처음 완전히 들어오는 실제 프레임** i를 찾아 `frame_ts = i / FPS`, 박스는 그 프레임의 실제 스크롤 오프셋으로 옮겼다. 프레임 렌더링과 정답 계산이 같은 `frame_offset()` 함수를 쓰고, 70개 오프셋 전부를 증거 항목의 `video.frame_offsets`에 기록했다. `test_video_truth_matches_rendered_frames`는 tall→프레임 박스 일치, 경계·띠 아래 위치, 그리고 ffmpeg로 해당 프레임을 뽑아 말풍선 안의 말풍선색 픽셀 비율(≥0.5, 실측 0.88~0.92)을 확인한다.
- **S3 차용증 PDF 동일 배치**: `render_iou_pdf`를 전면 교체했다. 따로 레이아웃을 그리지 않고 미리보기 PNG를 A4 한 쪽에 그대로 넣어(`reportlab` invariant 모드 유지) PDF와 PNG의 배치가 구조적으로 같아졌다. 위 SAMPLE 띠도 PNG 그대로이므로 40px 규칙을 자동 준수한다. 텍스트 층은 넣지 않았다. 약속 문서 5장(Readings)이 "PDF는 `preview_url` 이미지 기준"이라고 못 박고 있어 채점은 미리보기 픽셀로 하기 때문이다. PDF는 여전히 1쪽, 내장 이미지 1개(PNG와 바이트 크기 동일)임을 확인했다.
- **S4 날짜 모순**: EX2 날짜 구분선 "2026년 4월 25일"을 "2026년 4월 26일"(정규값 `2026-04-26`)로 고쳤다. 이제 "4월 25일이 지났어요"라는 다음 날 독촉과 모순이 없다. 구분선 오름차순 테스트를 추가했다.
- **S5 연락처**: 증거에 근거를 두는 쪽을 택했다. 차용증에 "채권자 연락처 010-0000-0001", "채무자 연락처 010-0000-0002" 칸을, 영문 promissory note에 "Lender phone 555-0100", "Borrower phone 555-0111" 칸을 넣고(`phone` 종류 정답 항목), 사건 연락처를 그 번호와 같게 했다(KR `010-0000-0000` → `...-0001`/`...-0002`, EN은 기존 번호 유지). 사건 연락처가 증거 전화 항목에 그대로 나오는지 테스트한다.
- **S6 서명**: 사인파 4곡선 + 밑줄 흉내를 버리고 서명자별 손글씨 흉내 프로그램(`SIGNATURE_PROGRAMS`)으로 다시 그렸다. 서명자마다 모양이 다르고, 각 4개의 펜 뗀 획(길이·높이 불규칙, 파형 함수 없음)이며, 잉크 박스가 틀 안에 확실히 작게 들어간다(IoU KR 0.206/0.207, EN 0.206/0.207 — 기준 0.4 이하). 비전 정답에 획 수(`strokes`)를 기록하고, IoU·서로 다름·3획 이상을 테스트한다.
- **S7 영어 세트**: 서명 이름표를 틀 왼쪽이 아니라 틀 위로 옮겨 서명 잉크와 겹치지 않게 했다(KR 포함 공통 레이아웃, 페이지 넘침 assert 추가). 금액 단위는 지시서 괄호안 대로 통일했다. 정답 `normalized`는 센트 정수(500000), 사건 값은 `"5000.00"` 문자열이며, 어느 쪽인지를 정답 파일 머리(`amount_unit`)에 명시했다(KR 파일에도 "정수 원" 명시). 테스트 기대값과 달러→센트 비교를 맞췄다.
- **S8 OFL**: `OFL.txt`를 Google Fonts 공식 `ofl/nanumgothic/OFL.txt`와 바이트 동일하게 교체했다(저작권 `Copyright (c) 2010, NHN Corporation ...`, `with Reserved Font Name Nanum, ...` 포함, 지어낸 문구 없음). 출처 URL: `https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/OFL.txt` (브라우징: `https://github.com/google/fonts/blob/main/ofl/nanumgothic/OFL.txt`). 교체 파일 SHA-256: `EEACF16032901D0ED0456876EC77B8F0FDA6B3FECEC7D972F8543EB602E6C30F`.
- **S9 테스트**: `git show 76d9cce` 실패(호출 오류·git 없음) 시 `pytest.skip`으로 건너뛰게 했다(없는 커밋으로 skip 발생 확인). 이름·브랜드 검사 대상에 `tools/make_sample_evidence.py`, `sample_evidence/generate_mock_evidence.py`, 정답 JSON 2개를 추가했다.
- **S10 README**: 과장 문구를 삭제했다("all 6 required checkboxes and Item 11 declaration signature" → 서명은 사용자가 직접 한다는 문장, "Post-office standard", "1:1", "0-day drift", "statutory pleading drafting", 오프라인 프리셋 문구와 standalone 프리셋 안내). 에이전트 4종 설명은 하는 일만 적었다. "이 저장소의 코드는 Meta Global AI Developer Hackathon 기간(2026-10-27~11-04)에 만들었습니다. Muse Code로 구현하고 Claude Code로 지시·리뷰했습니다." 단락을 넣고, 실행 방법은 새 첫 화면(사건 흐름) 기준으로 짧게 적었다. 고지 문구(`DISCLAIMER_KO/EN`)는 글자 그대로 유지, 라이선스 절 유지.
- **S11 사소**: 채팅 말풍선·문장 안 토큰 항목에 `speaker_role`(`"creditor"`/`"debtor"`, 보낸 쪽=creditor)을 추가하고 화자와 1:1 대응을 테스트한다. 워터마크는 항목에서 빼고 `ignore_regions`에만 남겼다(없음 테스트 포함). 계좌 `keep_box` 쪽에 가림 여백을 주지 않는다는 주석을 생성기에 달았다. 테스트 스키마에 `speaker_role`·`frame_index`·`amount_unit`·`video` 검사를 넣었다.
- **매니페스트·해시(지시 12)**: 재생성이 `manifest.json`의 해시를 자동 갱신했다. 기존 텍스트 샘플 3종(`kr_chat_log.txt`, `kr_transfer_receipt.txt`, `us_wire_receipt.txt`)의 해시는 바뀌지 않아 `get_demo_samples()`를 고치지 않았고, `frontend/app.js`의 해시도 그대로 유효하다(M2b 작업이므로 손대지 않음).

## 2. 만들거나 고친 파일

- `tools/make_sample_evidence.py` — 위 S1~S7·S11 생성기 수정 전부 (+LF 줄바꿈 정규화, 내용 diff만 발생)
- `sample_evidence/kr/chat_02_tall.png`, `sample_evidence/kr/chat_02_scroll.mp4` — S4 구분선 수정 반영, 영상 정답 기준 프레임 재생성
- `sample_evidence/kr/iou.png`, `sample_evidence/kr/iou.pdf` — S5 연락처 칸, S6 서명, S7 이름표, S3 PDF 임베드 방식
- `sample_evidence/en/promissory_note.png`, `sample_evidence/en/promissory_note.pdf` — S5 전화 칸, S6 서명, S7 이름표, S3 PDF 임베드 방식
- `sample_evidence/manifest.json` — 바뀐 파일의 SHA-256 갱신(텍스트 3종 불변)
- `backend/tests/golden/kr_truth.json`, `backend/tests/golden/en_truth.json` — 재생성(EX7/EX4 삭제, 항목 스키마 확장, `amount_unit`·`video` 추가)
- `backend/tests/test_sample_evidence.py` — S1/S2/S4/S5/S6/S7/S9/S11 테스트 추가·수정
- `backend/app/templates/fonts/OFL.txt` — 공식 OFL과 바이트 동일하게 교체
- `README.md` — S10 개정
- 고치지 않은 파일: `backend/app/api/routes.py`(텍스트 해시 불변이라 불필요), `frontend/`, `docs/`, `backend/app/services/`, `backend/app/meta/`, 그 밖 전부

## 3. 실행한 명령과 결과

PowerShell, `C:\2026_project\claimback-wt\m3-fix1`에서 실행. Python은 지시대로 `C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe`만 사용했고, 패키지를 새로 설치하지 않았다(Pillow 13.0.0, reportlab 5.1.0, pypdf, pytest, ffmpeg 모두 기존).

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m3-fix1"

# 1) 전체 테스트
cd "$WT\backend"; & $PY -m pytest -q
# 결과: 120 passed, 1 xpassed in 3.05s (failed 0)
# xpass 1건 = tests/test_naming.py::test_naming_frontend_app_js_clean
# (xfail 표시된 기존 frontend 건으로, 이 작업 범위 밖이며 수정 전부터 같은 상태)

# 2) 샘플·정답 재생성 + 바이트 동일성
cd $WT
$before = Get-ChildItem -Recurse -File sample_evidence,backend\tests\golden | Get-FileHash | ForEach-Object { "$($_.Path)|$($_.Hash)" }
& $PY tools\make_sample_evidence.py
$after = Get-ChildItem -Recurse -File sample_evidence,backend\tests\golden | Get-FileHash | ForEach-Object { "$($_.Path)|$($_.Hash)" }
Compare-Object $before $after
# 결과: 차이 0건 (출력 "REGEN-DIFF: 0")

# 3) 비밀 스캔
& $PY tools\secret_scan.py
# 결과: "secret_scan: clean", 종료 코드 0
```

추가 확인(보고용, 일회성):

- `tests/test_sample_evidence.py` 단독: 23 passed. S2 프레임 테스트는 말풍선 7개 전부 통과(말풍선색 픽셀 비율 0.88~0.92, 기준 0.5).
- S9 skip 경로: 존재하지 않는 기준 커밋으로 `baseline_text`를 호출해 `pytest.skip`(Skipped 발생)을 확인.
- S3 PDF 확인: `kr/iou.pdf`, `en/promissory_note.pdf` 모두 1쪽·내장 이미지 1개, 내장 이미지 크기가 각 PNG와 바이트 단위로 동일.
- S6 IoU: KR 0.206/0.207, EN 0.206/0.207 (기준 0.4 이하), 두 서명 잉크 박스 서로 다름, 획 수 4/4.
- 리뷰(M3-review 1장)의 추가 grep(`토스|카카오|국민은행|Chase|iMessage|Zelle|Promissory Admission|입증|Tests Passed|Judicial Filer|non-profit`, 대소문자 구분)을 손댄 파일 6종에 재실행: 0건.
- 텍스트 샘플 해시 불변: `kr_chat_log.txt` 63e31fe5…, `kr_transfer_receipt.txt` 8fe6d6d4…, `us_wire_receipt.txt` 1bea6080… (앞 8자리, `get_demo_samples()`·`frontend/app.js`의 값과 일치).

바이트 동일성 조건(지시 S11): 영상 포함 재생성 동일성은 이 PC의 빌드에서 확인했다.

- `ffmpeg version 9.0.2-full_build-www.gyan.dev`, `built with gcc 16.2.0 (Rev3, Built by MSYS2 project)`, 인코더 `Lavc63.1.102 libx264` (`--enable-libx264` 포함 full 빌드)

## 4. 실 API 호출

- Meta 실호출 0회(지시서대로 호출 없음), 모델·비용 없음. `reports/cost_ledger.jsonl`에 추가한 항목 없음.

## 5. 열린 문제와 지시·스펙에서의 벗어남

- 지시와 스펙이 충돌하는 대목은 없었다. EN 금액 표기(정답 센트 정수 vs 사건 `"5000.00"` 문자열)는 지시서 S7 괄호안의 선택지를 그대로 따랐고, 약속 문서는 KR API 형상만 고정하므로 golden 전용인 EN 사건 표기와 충돌하지 않는다.
- S3에서 허용된 두 방식 중 "PNG를 PDF 한 쪽에 그대로 넣기"를 택했고 텍스트 층은 넣지 않았다. 약속 문서 5장이 PDF 박스 기준을 미리보기 이미지로 못 박고 있어 채점에 텍스트 층이 필요 없기 때문이다. 리뷰어가 PDF 텍스트 추출을 기대한다면 후속 작업에서 같은 위치 글자 층을 더하면 된다.
- 전체 테스트의 xpass 1건(`test_naming_frontend_app_js_clean`, xfail 표시)은 손대지 않은 `frontend/app.js` 건이다. M2b가 기존 화면을 `legacy-dashboard`로 옮기는 중이므로 그대로 두었다.
- 편집 도구가 CRLF 여러 줄 일치를 못 해, 고친 텍스트 파일 3종(`tools/make_sample_evidence.py`, `backend/tests/test_sample_evidence.py`, `README.md`)의 줄바꿈을 LF로 정규화했다. `git diff --stat`에 내용 변경만 찍히는 것을 확인했다(유령 diff 없음).
- 일회성 확인 스크립트 2개(`m3fix1_probe_video.py`, `m3fix1_probe_skip.py`)는 저장소 밖(`C:\Users\Public\`)에 두었고 커밋 대상이 아니다.

## 6. 스펙 변경 제안

- 없음. 이번 수정은 지시서와 `specs/case-api-contract.md`(2장 증거 순서, 5장 Readings의 PDF 미리보기 기준) 안에서 해결됐다.
