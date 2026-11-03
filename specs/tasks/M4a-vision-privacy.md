# M4a 시각 감식(SAM 3.1)·개인정보 가림·호증 표시 (작업 지시서)

- 작성: 2026-11-03 13:46 KST, Claude
- 수행: Muse Code (`muse-spark-1.3`), git 작업 트리 `C:\2026_project\claimback-wt\m4a`(브랜치 `m4a`, M2a가 병합된 `main`에서 시작). M4b·M5와 동시에 진행.
- 먼저 읽을 것: `AGENTS.md`, 이 지시서, `reports/M2a.md`와 그 리뷰(코디네이터·담당 구조), `reports/M0-review.md`(SAM 결과, 좌표계, 문장 안 숫자 박스), `specs/case-api-contract.md` 6a절, 에이전트 설계 3-2(시각 감식), 3-3(개인정보 보호), 계획서 1-2(9)(가림 근거)

## 목표

SAM 3.1로 서명·도장·말풍선·얼굴을 찾고, 계좌번호·주민번호 자리·연락처·얼굴을 **이미지 픽셀에 굽는 방식**으로 가린 사본을 만들어 서류에 쓰게 합니다. 데모에서 "SAM이 증거 객체를 찾고, 개인정보는 픽셀로 가린다" 장면이 나와야 합니다.

## 파일 범위

고쳐도 되는 파일: 새 파일 `backend/app/agents/vision.py`, `backend/app/agents/privacy_guard.py`, `backend/app/services/redaction.py`(픽셀 굽기·호증 표시·누출 검사), `backend/app/agents/coordinator.py`(vision·privacy 단계 연결만), `backend/app/api/cases.py`(약속 6a절 엔드포인트 추가만), `backend/app/agents/prompts/`(SAM 명사구 목록 파일), 새 테스트, 새 fixture.
건드리지 않는 파일: `agents/reader.py`·`intake.py`(M4b), `agents/packager.py`(M5), `services/`의 다른 파일, `backend/app/meta/`, `frontend/`, `docs/`, `e2e/`.

## 할 일

1. **시각 감식** `agents/vision.py`:
   - 감식-1(판독과 병렬): 명사구 `signature`, `red stamp`, `chat bubble`, `face`로 SAM 3.1 호출(이미지·PDF 미리보기). 출력은 `meta-sam-parser`로 해석하고, 해석 오류는 "못 찾음"이 아니라 오류로 기록합니다. SAM 박스는 입력 이미지 픽셀(`Box(system="pixel")`).
   - 감식-2(판독 뒤): 명사구로 못 찾은 서명은 판독 박스 근처를 박스 프롬프트로 1회 재시도. 그래도 없으면 `not_found`.
   - 마스크는 해석해 PNG로 저장(`mask_url`), 화면 표시용.
2. **개인정보 보호** `agents/privacy_guard.py` + `services/redaction.py`:
   - 가림 계획: 판독 항목 `account_number`(끝 4자리 유지: `mask_box` + `keep_box`), `id_number`(뒷 7자리만), `phone`(가운데 4자리), 감식 `face`(전체). 별도 칸 글자 박스에는 여백(박스 높이 20%, 최소 4px, `keep_box` 쪽에는 여백 없음).
   - 문장 안 숫자(말풍선 안 계좌·전화번호)는 M0 결과대로 줄 단위로 넓게 가리고 미리보기에 "확인 필요" 표시.
   - **원본은 그대로 두고 사본에만** 픽셀을 검정으로 칠합니다(PDF 위 덮개 금지). 사본에 오른쪽 위 "갑 제N호증" 표시.
   - 누출 검사(규칙, P0): 가린 영역 픽셀이 모두 검정인지, 사본에서 Spark 재판독 없이 검사할 수 있는 항목(가린 영역 평균 밝기, 남긴 끝 4자리 영역은 원본과 같음)을 확인. 실패하면 `HOLD`.
3. **연결**: 코디네이터의 `vision` 단계(판독과 병렬 실행, `substeps` 증거별)와 `privacy` 단계(사실 정리 뒤, 체크포인트 1 전)를 실제로 돌리고, 약속 6a절의 `GET /segments`, `GET /redactions`, `PUT /facts`의 `redaction_confirmed`를 더합니다. 기존 응답 키·전이표는 바꾸지 않습니다.
4. **기록 실행**: `META_MODE=record`(`META_LEDGER_PATH`는 메인 저장소 원장, `run_id` = 사건 ID), 샘플 사건의 SAM 호출을 기록하고 바로 재생으로 다시 돌려 누락 없음 확인. 재생 테스트는 키 없이.
5. **테스트**: 정답 데이터(`backend/tests/golden/kr_truth.json`의 `vision_targets`, `redaction_targets`)와 비교(테스트에서만 읽음): 서명 잉크 박스·도장 IoU 0.5 이상(못 미치면 실제 값과 이유를 리포트), 가린 영역 픽셀 100% 검정, `keep_box` 픽셀은 원본과 동일, 원본 파일 해시 불변, 누출 검사 실패 경로.
6. 리포트 `reports/M4a.md`(AGENTS.md 형식, 끝까지 저장 확인): SAM 호출 수·비용, 대상별 검출률·IoU, 가림 결과 이미지 경로(리뷰어가 눈으로 봄).

## 하지 않을 일

- 영상 추적(P1), 판독 모델 변경(M4b), 서류 묶음(M5), 화면 수정(M6), `specs/` 수정, `.env`, 키 출력, 커밋·푸시

## 완료 기준

```powershell
$PY = "C:\2026_project\claimback-ai-meta\.venv\Scripts\python.exe"
$WT = "C:\2026_project\claimback-wt\m4a"
Remove-Item Env:MODEL_API_KEY -ErrorAction SilentlyContinue
cd "$WT\backend"; & $PY -m pytest -q        # failed 0 (재생)
cd $WT; & $PY tools\secret_scan.py           # 0
```
