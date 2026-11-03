# M3 리뷰 (Claude + 서브에이전트 교차 리뷰)

- 작성: 2026-11-03 13:05 KST, Claude Code
- 대상: 브랜치 `m3-samples`(커밋 6fdafe6, 기준 b2c4f61), `reports/M3.md`
- 실행: Muse Code 12:25~12:47(22분), 종료 코드 0, Meta 실호출 0회
- 리뷰 방식: Claude가 완료 기준 재실행과 이미지 육안 확인. 서브에이전트 2개가 따로 검토(① 정답 데이터를 이미지·영상 프레임 위에 그려 맞는지 확인, ② 제품 규칙·라이선스·심사위원이 볼 화면)한 뒤 서로의 결과를 교차 확인.
- 판정: **통과(병합), 수정 지시서 M3-fix1 즉시 진행.** 샘플 세트는 규칙(SAMPLE 띠, 가상 이름·은행·앱, 끝 4자리가 다른 계좌, 별도 칸의 번호, 여러 획 서명, 도장)을 지키고, 다시 만들어도 바이트가 같으며, 글자 박스는 그린 글자에 딱 맞습니다. 다만 정답 증거 번호가 약속 문서와 달라(EX7) 판독 정확도 채점을 망치므로 M4 전에 고칩니다. 기존 대시보드의 가짜처럼 보이는 문구는 M2b가 첫 화면을 사건 흐름으로 바꾸면서 정리합니다.

## 1. 완료 기준 재실행 (12:49 KST)

```powershell
cd C:\2026_project\claimback-wt\m3-samples\backend; & $PY -m pytest -q   # 53 passed
# 생성 전후 해시 비교: 차이 0건 (다시 만들어도 같은 바이트)
& $PY tools\secret_scan.py                                               # clean
Select-String … '토스','카카오','국민은행','Chase','iMessage','Zelle','Promissory Admission','입증','Tests Passed','Judicial Filer','non-profit' -CaseSensitive   # 0건
```

눈으로 확인: `chat_01.png`, `transfer_loan.png`, `iou.png` — SAMPLE 띠, 이름 서가온·탁나루, 실제 앱과 다른 색, 계좌 끝 1234·5678, 주민번호 자리 0, 여러 획 서명과 이름 도장.

## 2. 결함

| ID | 등급 | 내용 | 처리 |
|---|---|---|---|
| S1 | **차단** | 정답에 `iou.png`가 EX7로 따로 있어(약속 문서는 EX6의 미리보기) 완벽한 판독도 금액·날짜 90.7%로 95% 기준 미달. 영어 세트도 같은 중복 | M3-fix1 |
| S2 | 수정 | 영상 정답 시각·박스가 실제 프레임과 다름(70프레임·10fps, 일부 박스 IoU 0) | M3-fix1 |
| S3 | 수정 | `iou.pdf`가 `iou.png`와 다른 배치로 그려짐 | M3-fix1 |
| S4~S7 | 수정 | 대화 날짜 모순(4/25), 증거에 없는 연락처, 파형 같은 서명(잉크·틀 IoU 0.52), 영어 세트 이름표·금액 단위 | M3-fix1 |
| S8 | 수정 | `OFL.txt` 저작권 줄을 지어냄, 예약 글꼴 이름 누락(공식: 2010 NHN Corporation, Nanum 등 예약) | M3-fix1 |
| S9 | 수정 | 얕은 복제에서 `git show 76d9cce` 테스트 오류, 생성기·정답 JSON이 이름 검사에서 빠짐 | M3-fix1 |
| S10 | 수정 | README 과장("all 6 required checkboxes and Item 11 declaration signature", "Post-office standard", "1:1", "0-day drift"), 대회 기간 작업 명시 없음(실격 위험, plan-review 10장) | M3-fix1 |
| S12 | **차단(화면)** | 기존 대시보드에 고정 결과·법적 정확성 주장("Confidence: 99.8%", "Integrity Verified", "민법 제157조 초일불산입 준수", "SC-100 전 필드 주입 완료", 모든 증거에 녹색 "Verified") | M2b가 첫 화면을 사건 흐름으로 교체, 기존 화면은 링크 없는 `legacy-dashboard.html`로 |
| S13 | 수정(M6) | 미국 프리셋 Exhibit B가 한국 대화 해시를 씀, 미국 연락처 형식 | M6 |
| S14 | 사소 | 오른쪽 말풍선 화자, 워터마크 이중 기록, 계좌 가림 여백, x264 빌드 문자열 | M3-fix1 |

확인한 정상 동작: 고지 문구 `DISCLAIMER_KO/EN`과 배지가 계획서 6장과 글자까지 같음, `frontend/`와 `docs/` 해시 같음, `lucide@0.469.0` 실재, 서버 없이 JS 오류 없음, 이전 샘플 이름 8개가 M3가 만든 어떤 파일에도 없음, MIT 본문 표준, 계좌 `keep_box`가 정확히 끝 4자리, 주민번호 `mask_box`가 뒷 7자리, 계산 기대값(4,014,383원, 2026-05-02)이 이미지 내용과 일치.

## 3. 비용

앱 실호출 0. 크레딧 $128.96(12:52).
