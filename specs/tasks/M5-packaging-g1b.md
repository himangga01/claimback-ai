# M5 편철: 갑호증 통합 PDF·증거 목록·G1b 최종 값 대조 (작업 지시서)

- 작성: 2026-11-03 13:46 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\m5`(브랜치 `m5`, M2a가 병합된 `main`에서 시작). M4a·M4b와 동시에 진행. **Meta 실호출 없음.**
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `reports/M2a.md`와 리뷰(편철 담당), `specs/case-api-contract.md` 6a절, 에이전트 설계 3-7(G1b), 3-9(편철), 계획서 4-6(G1b·PDF 테스트), 6장(고지 문구)

## 목표

한국 패키지를 완성합니다: 내용증명 PDF(있음), 전자소송 붙여넣기 문구(있음), **갑호증 통합 PDF**와 **증거 목록**, 그리고 서류 값이 사용자 확정값·계산값과 같은지 마지막에 대조하는 **G1b**.

## 파일 범위

고쳐도 되는 파일: `backend/app/agents/packager.py`, 새 파일 `backend/app/services/exhibit_bundle.py`, `backend/app/services/final_check.py`, 새 테스트.
건드리지 않는 파일: `coordinator.py`(M4a), `reader.py`·`intake.py`(M4b), `vision.py`·`privacy_guard.py`·`redaction.py`(M4a), `services/`의 기존 파일(필요한 변경은 리포트에 제안), `backend/app/meta/`, `frontend/`, `docs/`, `e2e/`.

## 할 일

1. **갑호증 통합 PDF** `services/exhibit_bundle.py`: 증거 순서대로 한 쪽씩, 각 쪽 위에 "갑 제N호증"과 파일 이름·SHA-256 앞 8자리. 이미지는 **가린 사본이 있으면 그것**(M4a가 사건 상태에 넣는 경로, 이름이 다르면 `deps`·`packager`에서 맞춤), 없으면 원본을 쓰되 쪽 아래에 "가림 처리 전 사본" 표시(병합 뒤 M4a 사본으로 바뀜). 영상은 핵심 프레임이 있으면 그 스틸컷, 없으면 "영상 증거, 파일 별도 제출" 한 줄.
2. **증거 목록** PDF: 칸 "호증 번호, 증거 이름, 작성일, 내용". "내용"은 사용자가 확인한 사실만(예: "2026. 3. 10. 5,000,000원 이체 기록"), 법적 평가·"입증취지" 같은 판단 문구를 쓰지 않습니다.
3. **G1b** `services/final_check.py`: 생성한 PDF(내용증명, 갑호증, 증거 목록)에서 글자를 뽑고 전자소송 문구와 함께, 금액·날짜·이름이 확정값·계산값과 같은지 대조합니다(문장 안 숫자 정규화: "4,014,383원", "2026. 5. 2."). 다르면 `HOLD`와 어느 서류 어느 값인지. 명칭 검사도 함께.
4. **편철 연결** `agents/packager.py`: 위 두 PDF를 `Package.files`에 더하고(`exhibits.pdf`, `evidence_list.pdf`), G1b 결과를 `Package.gate_results`에 넣습니다. 고지 문구는 갑호증 표지와 패키지 화면에만(본문 금지, 설계 3-9 보충).
5. **테스트**: G1b 변조 주입 100% 차단(계획서 4-6: PDF 텍스트의 금액 4,014,383 → 4,014,388, 날짜, 이름 바꾸기), 정상 패키지 통과, 갑호증 쪽 수 = 증거 수, 쪽마다 호증 표시, 가린 사본을 쓸 때 원본 이미지가 PDF에 들어가지 않음(이미지 해시 비교), PDF 텍스트·메타데이터에 전체 계좌번호·주민번호 0건(정규식), 재생 모드로 사건 흐름 끝까지(M2a 테스트) 통과.
6. 리포트 `reports/M5.md`(AGENTS.md 형식, 끝까지 저장 확인): 만든 PDF 경로(리뷰어가 렌더해서 봄), G1b 변조 시험 결과.

## 하지 않을 일

- 미국 SC-100 수정(P1), 화면(M6), `specs/` 수정, Meta 호출, `.env`, 커밋·푸시

## 완료 기준

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m5"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q        # failed 0
cd $WT; & $PY tools\secret_scan.py           # 0
```
