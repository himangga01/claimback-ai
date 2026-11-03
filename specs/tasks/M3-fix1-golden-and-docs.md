# M3-fix1 정답 데이터·샘플·라이선스·README 보강 (수정 지시서)

- 작성: 2026-11-03 13:05 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\m3-fix1`(브랜치 `m3-fix1`, M3가 병합된 `main`에서 시작). M2b(화면)와 동시에 진행합니다. **Meta 실호출 없음.**
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `reports/M3-review.md`(S1~S14), `specs/case-api-contract.md` 2장(증거 순서)

## 파일 범위

고쳐도 되는 파일: `sample_evidence/`(전부), `tools/make_sample_evidence.py`, `backend/tests/golden/`(전부), `backend/tests/test_sample_evidence.py`, `README.md`, `backend/app/templates/fonts/OFL.txt`, `backend/app/api/routes.py`의 `get_demo_samples()` 안(해시가 바뀌면 맞추는 것만).
건드리지 않는 파일: `frontend/`, `docs/`, `e2e/`(M2b가 고치는 중), `backend/app/services/`, `backend/app/meta/`, 그 밖 전부.

## 할 일

1. **S1(차단) 정답 증거 번호를 약속 문서와 같게**: `kr_truth.json`에서 EX7(`iou.png`)을 지우고 EX6(`iou.pdf`)의 박스 기준을 `iou.png`(미리보기) 픽셀로 둡니다(`coord_basis` 또는 `preview_file` 필드). EX1~EX6이 약속 문서 2장 표와 파일·순서가 같아야 합니다. 영어 세트의 중복(EX4 = EX3의 PNG)도 같은 방식으로 정리. 테스트: `ex_id → 파일` 대응이 약속 문서 표와 같음.
2. **S2 영상 정답 시각**: 실제 프레임 기준으로 다시 계산합니다. 각 말풍선이 **처음 완전히 보이는 프레임** i를 찾아 `frame_ts = i / FPS`, 박스는 그 프레임의 실제 스크롤 위치로 옮깁니다(생성기가 쓰는 프레임별 오프셋을 그대로 기록). 테스트: ffmpeg로 그 시각의 프레임을 뽑아 박스 영역이 잘리지 않았는지(이미지 경계 안, 말풍선 색 픽셀 포함) 확인.
3. **S3 차용증 PDF**: `iou.pdf`를 `iou.png`와 같은 배치로 그립니다(PNG 픽셀 좌표 × 72/150). 또는 PNG를 PDF 한 쪽에 그대로 넣습니다(텍스트 층이 필요하면 같은 위치에 글자 추가). 위 띠 높이 40px 규칙 준수.
4. **S4 날짜 모순**: EX2의 날짜 구분선 "2026년 4월 25일"을 "2026년 4월 26일"로(또는 메시지를 맞게) 고칩니다.
5. **S5 연락처**: 증거에 없는 사건 연락처는 `null`로 두거나, 차용증에 서로 다른 가짜 번호 칸(`010-0000-0001`, `010-0000-0002`)을 넣고 정답에 추가합니다.
6. **S6 서명**: 사람마다 모양이 다른 손글씨 흉내(펜을 뗀 획 3개 이상, 길이·높이 불규칙, 반복 파형 금지)로 다시 그리고, 잉크 박스가 틀 박스보다 확실히 작게(두 박스 IoU 0.4 이하) 합니다.
7. **S7 영어 세트**: 서명 이름표 박스가 서명 잉크와 겹치지 않게, 금액 단위를 한쪽으로 통일(정답 `normalized`는 센트 정수, 사건 값은 `"5000.00"` 문자열 — 어느 쪽인지 정답 파일 머리에 명시).
8. **S8 OFL**: `OFL.txt` 머리를 Google Fonts 공식 `ofl/nanumgothic/OFL.txt`의 저작권·예약 글꼴 이름 줄과 똑같이 바꾸고 출처 URL을 리포트에 적습니다. 지어낸 문구를 남기지 않습니다.
9. **S9 테스트**: `git show 76d9cce`가 실패하면(얕은 복제, zip 다운로드) 오류 대신 `pytest.skip`. 이름·브랜드 검사 대상에 `tools/make_sample_evidence.py`, `sample_evidence/generate_mock_evidence.py`, 정답 JSON을 추가.
10. **S10 README**: 과장 삭제("all 6 required checkboxes and Item 11 declaration signature" → 서명은 사용자가 직접, "Post-office standard", "1:1", "0-day drift", "statutory pleading drafting", 오프라인 프리셋 문구). 에이전트 설명은 하는 일만. "이 저장소의 코드는 Meta Global AI Developer Hackathon 기간(2026-10-27~11-04)에 만들었습니다"와 Muse Code로 구현하고 Claude Code로 지시·리뷰했다는 사실을 한 단락으로 적습니다. 실행 방법은 새 첫 화면(`frontend/index.html` = 사건 흐름, M2b)을 기준으로 짧게.
11. **S11 사소**: 오른쪽(보낸) 말풍선의 `speaker`는 `"creditor"`처럼 역할로도 적어 채점이 이름 대신 쓸 수 있게(`speaker_role` 추가), 워터마크는 `ignore_regions`에만(항목에서 제외), 계좌 `keep_box` 쪽에는 가림 여백을 주지 않는다는 주석, 리포트에 ffmpeg 버전 기록(바이트 동일성 조건).
12. 바뀐 파일의 SHA-256을 `manifest.json`에 맞추고, 기존 텍스트 샘플의 해시가 바뀌면 `get_demo_samples()`만 맞춥니다(화면 프리셋 `frontend/app.js`는 M2b가 `legacy-dashboard.js`로 옮기는 중이므로 건드리지 말고, 해시가 달라지면 리포트에 적음).
13. 리포트 `reports/M3-fix1.md`(AGENTS.md 형식, 끝까지 저장 확인).

## 완료 기준

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m3-fix1"
cd "$WT\backend"; & $PY -m pytest -q                      # failed 0
cd $WT
$before = Get-ChildItem -Recurse -File sample_evidence,backend\tests\golden | Get-FileHash | ForEach-Object { "$($_.Path)|$($_.Hash)" }
& $PY tools\make_sample_evidence.py
$after = Get-ChildItem -Recurse -File sample_evidence,backend\tests\golden | Get-FileHash | ForEach-Object { "$($_.Path)|$($_.Hash)" }
Compare-Object $before $after                               # 0건 (영상은 이 PC의 ffmpeg·x264 빌드에서만 바이트 동일, 버전을 리포트에 기록)
& $PY tools\secret_scan.py                                  # 0
```
