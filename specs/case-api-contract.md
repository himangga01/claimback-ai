# 사건 흐름 API 약속 (M2, v2)

- 작성: 2026-11-03 12:30 KST, Claude / v2 갱신 12:55 KST(서브에이전트 2개 교차 리뷰 반영: 증거 순서, 상태 전이표, 재생 고정 입력, 판독 박스, 진행 표시, 서식, 오류 형식)
- 목적: M2a(백엔드)와 M2b(화면·E2E)가 동시에 개발하도록 요청·응답 형식을 고정합니다. 예시 응답은 `specs/case-api-examples/*.json`(Claude 작성)이며, M2b 가짜 서버는 이 예시를 그대로 돌려주고, M2a 테스트는 실제 응답에 예시의 키가 모두 있는지 확인합니다. 바꿀 필요가 있으면 리포트에 제안합니다.
- 근거: 계획서 4-10, 에이전트 설계 2-1·4-2·4-3, M1 `Calculation`(`backend/app/schemas/loan_fact.py`), M0-fix1 `Box`(`backend/app/meta/coords.py`).
- 범위: 한국 트랙 얇은 흐름. 시각 감식(SAM), 가림, 영상 판독, 타임라인, G1b는 `skipped`(M4·M5).

## 1. 공통 서식

- 기본 경로 `/api/cases`(라우터는 정적 파일 마운트보다 먼저 등록).
- 금액(원)은 **정수 문자열**(`"4014383"`). 이율은 연 % 문자열(`"5"`, `"12"`) 또는 `null`. 날짜는 `YYYY-MM-DD`. 예외: `Drafts.calculation`은 M1 `Calculation`을 그대로 직렬화하므로 이율이 `"5.0"`, 계산 단계 금액(`calculation_steps[].amount`)이 소수 문자열일 수 있습니다(화면은 `formula`를 표시). `case-api-examples/drafts.json`의 `calculation`은 병합된 M1 코드의 실제 출력입니다.
- 화면 표시용 값(`rendered_text`, `display`)은 "5,000,000원", "2026. 3. 10." 형식. 근거 태그 `[[EX:4]]`는 "[갑 제4호증]"으로 바꿔 보여 줍니다.
- `ex_id`는 `EX1`, `EX2` …(숫자 순 정렬). 표시 이름 `label`은 "갑 제N호증".
- 오류: 요청 본문 검사 실패는 422가 아니라 **400**, 상태가 맞지 않는 요청은 **409**, 없는 사건은 404. 모양은 모두
  `{ "detail": { "code": str, "message": str, "missing_requirements": [str] } }`.
  `code` 목록: `bad_request`, `wrong_state`, `not_found`, `unapproved_sentences`, `missing_facts`, `replay_fixture_missing`, `budget_exceeded`.
- 사건 저장: `backend/data/cases/<case_id>/`(git 제외). `case_id` = `case_` + 12자리 16진수. **사건 ID, URL, 시각은 모델 요청 내용에 넣지 않습니다**(재생 해시가 바뀌므로).
- Meta 호출의 `run_id`는 `case_id` 하나(사건 전체에 실행당 상한 $2가 걸리게). 단계·증거는 `audit_log`에 따로 기록.

## 2. 샘플 사건 증거 순서 (고정)

| ex_id | 파일(`sample_evidence/kr/`) | kind | status | 비고 |
|---|---|---|---|---|
| EX1 | `chat_01.png` | image | ok | |
| EX2 | `chat_02_tall.png` | image | ok | |
| EX3 | `chat_02_scroll.mp4` | video | **skipped** | 영상 판독은 M4(핵심 프레임) |
| EX4 | `transfer_loan.png` | image | ok | 대여 이체 |
| EX5 | `transfer_repay.png` | image | ok | 일부 변제 입금 |
| EX6 | `iou.pdf` | pdf | ok | `preview_url`은 `iou.png`(같은 문서의 PNG). `iou.png`는 따로 증거로 올리지 않음 |

정답 데이터(`backend/tests/golden/`)는 어떤 엔드포인트도 읽지 않습니다.

## 3. 상태와 전이

상태: `INTAKE` → `READING` → `ORGANIZING` → `CHECKPOINT_1` → `CALCULATING` → `DRAFTING` → `VERIFYING` → `DRAFT_APPROVAL` → `PACKAGING` → `CHECKPOINT_2`(M2의 끝 상태). 그리고 `HOLD`.

| 요청 | 허용 상태 | 결과 |
|---|---|---|
| `POST /run` | `INTAKE` | 접수·판독·사실 정리 → `CHECKPOINT_1`. 증거 하나의 판독이 2회 실패하면 그 증거만 `status: "hold"`, 판독이 하나도 없으면 사건 `HOLD` |
| `PUT /facts` | `CHECKPOINT_1`, 또는 계산·초안 단계에서 생긴 `HOLD` | 확정값 저장, 이전 계산·초안 삭제 → `CALCULATING` |
| `POST /run` | `CALCULATING` | 계산(G2·G4) → 문안 작성 ⇄ 검증(최대 2회 수정) → `DRAFT_APPROVAL`. G2 결손·수정 루프 초과는 `HOLD` |
| `PUT /drafts` | `DRAFT_APPROVAL` | 문장 수정(G1a·G3 재검사)·승인 반영. 상태 유지 |
| `POST /run` | `DRAFT_APPROVAL` | 모든 문장이 승인되고 검사 통과면 편철 → `CHECKPOINT_2`. 아니면 409 `unapproved_sentences` |
| `GET /review` | `CHECKPOINT_1` 이후 | 그 전이면 409 `wrong_state` |
| `GET /drafts` | `DRAFT_APPROVAL` 이후 | 그 전이면 409 |
| `GET /package` | `CHECKPOINT_2` | 그 전이면 409 |

- `POST /run`은 동기 실행이지만 **단계가 끝날 때마다 사건 파일을 저장**합니다. 화면은 실행 중에 `GET /api/cases/{id}`를 0.5초마다 불러 진행을 보여 줍니다(같은 사건에 동시 `POST /run`은 409).
- `hold_reasons`: `[ { "step": str, "code": str, "message": str, "fields": [str] } ]`. fixture가 없는 재생 요청은 500이 아니라 `code: "replay_fixture_missing"`인 HOLD.

## 4. 단계 표 (`steps[]`, 화면 에이전트 보드)

| key | 담당(`agent`) | 묶음(`group`) | 모델 |
|---|---|---|---|
| `intake` | 접수 담당 | Forensic Visual | 규칙 |
| `reading` | 판독 담당 | Fact-Timeline Chronology | `READER_MODEL`(기본 `muse-spark-1.3`) |
| `vision` | 시각 감식 담당 | Forensic Visual | `sam-3.1`(이번엔 `skipped`) |
| `organizing` | 사실 정리 담당 | Fact-Timeline Chronology | `muse-spark-1.3` |
| `privacy` | 개인정보 보호 담당 | Forensic Visual | 규칙(이번엔 `skipped`) |
| `checkpoint_1` | 사용자 확인 | User | — |
| `calculating` | 계산 담당 | Financial Auditor | 규칙 |
| `drafting` | 문안 작성 담당 | Fact-Timeline Chronology | `muse-spark-1.3` |
| `verifying` | 검증 담당(G1a·G3) | Financial Auditor | 규칙 |
| `draft_approval` | 사용자 문장 승인 | User | — |
| `packaging` | 편철 담당 | Judicial Form Filler | 규칙 |
| `checkpoint_2` | 사용자 최종 확인 | User | — |

(묶음은 `specs/multi_agent_architecture.md`와 같게. 그 문서의 체크포인트 번호 표기와 다르면 이 표가 우선)

## 5. 응답 모양

### `CaseView` (예시 `case-api-examples/case_view.json`)
`case_id`, `jurisdiction`, `state`, `meta_mode`(`replay`|`record`|`live`), `run_cost_usd`(문자열), `hold_reasons[]`, `steps[ { key, agent, group, model, status: waiting|running|done|hold|skipped, started_at, ended_at, latency_ms, attempts, cost_usd, note, substeps[ { ex_id, status, latency_ms } ] } ]`, `evidence[ { ex_id, label, filename, sha256, kind, status: ok|hold|skipped, url, preview_url } ]`, `stub`(가짜 서버만 `true`).

### `Readings` — `GET /api/cases/{id}/readings` (예시 `readings.json`)
`[ { ex_id, model, items: [ { item_id, kind, text_verbatim, normalized, box: { x1, y1, x2, y2, system: "pixel", ref_w, ref_h }, speaker, confidence } ] } ]`
- 박스는 원본 이미지 픽셀(`system: "pixel"`, `ref_w/ref_h`는 이미지 크기). PDF는 `preview_url` 이미지 기준.
- `item_id`는 모델이 준 값이 아니라 **코드가 출력 순서대로 `item1`, `item2` …로 다시 붙인 값**입니다.

### `Review` — `GET /review` (예시 `review.json`)
`fields[ { field, label, value, display, sources[ { ex_id, item_id } ], conflict } ]`, `conflicts[]`, `questions[ { field, question } ]`, `utterances[ { ex_id, item_id, speaker, text, tags[] } ]`, `evidence_roles[ { ex_id, suggested_role } ]`.
- `field` 목록과 `LoanFactSchema` 대응:

| field | LoanFactSchema |
|---|---|
| `creditor_name`, `creditor_address`, `creditor_phone` | `creditor.name`, `.address`, `.phone` |
| `debtor_name`, `debtor_address` | `debtor.name`, `.address` |
| `principal` | `principal_amount` |
| `loan_date`, `due_date` | `loan_date`, `due_date` |
| `interest_rate` | `agreed_interest_rate`(없으면 `null`) |
| `transaction_kind` | `transaction_kind`(`civil`|`commercial`) |
| `repayments[ {date, amount} ]` | `repayments[ {payment_date, amount} ]` |
| `evidence_roles` | `evidences[]`: `id` = "갑 제N호증", `title` = 파일 종류 설명, `evidence_type` = 역할이 `loan_transfer`·`repayment`면 `transfer_receipt`, 대화면 `messenger_chat`, 차용증이면 `loan_agreement`, `role`, `source_filename`, `sha256_hash` |

- 태그는 설계 3-4 목록만. 화면 표시 이름: `loan_request` "빌려 달라는 말", `amount_mention` "금액 언급", `repay_promise` "갚겠다는 말", `reminder` "갚아 달라는 말"(15:16 변경, 법적 절차 이름 "독촉"과 헷갈리지 않게), `other` "기타".

### `ConfirmedFacts` — `PUT /facts` (예시 `confirmed_facts_kr.json`)
`{ fields: {...위 field...}, evidence_roles: { "EX4": "loan_transfer", ... }, highlight: [ "EX1:item4" ], as_of: "2026-06-01" }`

**데모·테스트 고정 입력 규칙**(재생이 같은 요청을 만들도록, 기록 실행·재생 테스트·E2E가 모두 같은 함수 `build_demo_confirmed_facts(review)`를 씀, M2a가 `backend/app/agents/demo_inputs.py`에 구현하고 M2b E2E도 같은 규칙을 화면에서 따라 함):
1. `fields`는 `Review.fields`의 값을 그대로 쓰되, 비어 있는 칸만 `confirmed_facts_kr.json`의 `fallback_fields` 값으로 채웁니다(주소 등).
2. `evidence_roles`는 `Review.evidence_roles[].suggested_role` 그대로.
3. `highlight`는 `utterances` 중 `ex_id` 숫자 순, `item_id` 순으로 처음 나오는 `repay_promise` 하나.
4. `as_of`는 `"2026-06-01"`.

### `Drafts` — `GET/PUT /drafts` (예시 `drafts.json`)
`calculation`(M1 `Calculation` 그대로: `allocations[ {payment_date, payment_amount, applied_to_cost, applied_to_interest, applied_to_principal, remaining_principal_after} ]`, `remaining_principal`, `accrual_start_date`, `rate_clause { pre_service_rate, post_service_rate, sentence }`, `reference_total { as_of, amount }`, `limit_check`, `missing_fields[]`, `warnings[]`, `calculation_steps[ {label, formula, amount} ]`, `overpayment_amount`, `accrued_interest`; 금액은 정수 문자열),
`gate_results[ { gate, status: pass|fail, findings[ { sentence_id, field, message, fix_hint } ] } ]`,
`sentences[ { sentence_id, type, text_with_slots, rendered_text, ex_refs[], findings[], approved } ]`,
`revision_rounds`, `revisions[ { round, gate_results[] } ]`.
- `PUT` 본문: `{ "sentences": [ { "sentence_id": "s2", "text_with_slots": "(수정할 때만)", "approved": true } ] }`. 수정한 문장은 G1a·G3를 다시 거치고, 지적이 있으면 그 문장의 `approved`는 `false`로 남습니다.

### `Package` — `GET /package` (예시 `package.json`)
`files[ { name, label, url } ]`, `ecourt { claim_purpose, claim_cause_payment_order }`, `notices { notice_ko, disclaimer_ko }`, `gate_results[]`(G1b는 M5까지 `skipped`).
- 승인된 문장은 `claim_cause_payment_order`와 내용증명 PDF 본문에 들어갑니다(M2a가 `pdf_compiler`에 선택 인자 `fact_sentences`를 더함).

## 6. 엔드포인트

| 메서드 | 경로 | 요청 | 응답 |
|---|---|---|---|
| POST | `/api/cases` | `{ "jurisdiction": "KR" }` | `CaseView`(INTAKE) |
| POST | `/api/cases/sample` | `{ "set": "kr" }` | 2장 순서로 증거를 올린 `CaseView` |
| POST | `/api/cases/{id}/evidence` | multipart `files[]` | `CaseView` |
| GET | `/api/cases/{id}/evidence/{ex_id}/file` | | 원본 파일 |
| GET | `/api/cases/{id}/evidence/{ex_id}/preview` | | PDF는 미리보기 PNG, 이미지는 원본 |
| POST | `/api/cases/{id}/run` | `{}` | `CaseView`(3장 전이표) |
| GET | `/api/cases/{id}` | | `CaseView` |
| GET | `/api/cases/{id}/readings` | | `Readings` |
| GET | `/api/cases/{id}/review` | | `Review` |
| PUT | `/api/cases/{id}/facts` | `ConfirmedFacts` | `CaseView` |
| GET / PUT | `/api/cases/{id}/drafts` | (PUT 본문은 5장) | `Drafts` |
| GET | `/api/cases/{id}/package` | | `Package` |
| GET | `/api/cases/{id}/files/{name}` | | 생성 파일 |
| DELETE | `/api/cases/{id}` | | `{ "deleted": true }`(올린 파일과 생성 파일 모두 삭제) |

## 6a. M4·M5 추가분 (13:46 KST, v3 예고)

M4a(시각 감식·가림)와 M5(편철)가 더하는 응답입니다. 기존 응답 키는 바꾸지 않고 새 키·엔드포인트만 더합니다.

| 메서드 | 경로 | 응답 |
|---|---|---|
| GET | `/api/cases/{id}/segments` | `[ { ex_id, model: "sam-3.1", objects: [ { target: "signature"\|"stamp"\|"chat_bubble"\|"face", source: "noun"\|"box", box: Box(pixel), score, mask_url } ], status: ok\|not_found\|skipped } ]` |
| GET | `/api/cases/{id}/redactions` | `{ plan: [ { ex_id, item_id, kind: "account_number"\|"id_number"\|"phone"\|"face", mask_box: Box, keep_box: Box\|null, reason } ], previews: [ { ex_id, url } ], leak_check: { status: pass\|fail, findings: [] } }` |
| PUT | `/api/cases/{id}/facts` | 기존 본문에 선택 키 `redaction_confirmed: true`(없으면 `false`로 보고 서류에 원본 대신 가린 사본만 쓰도록 유지) |

- 단계 표의 `vision`·`privacy`는 M4a 이후 `skipped`가 아니라 실제 단계가 됩니다. `vision` 담당 묶음은 Forensic Visual, 모델 `sam-3.1`.
- `Package.files`에 M5가 `exhibits.pdf`(갑호증 통합, 가린 사본 + "갑 제N호증" 표시), `evidence_list.pdf`(증거 목록)를 더하고, `Package.gate_results`의 G1b가 `skipped`에서 `pass`/`fail`로 바뀝니다.
- 증거 목록의 칸은 "호증 번호, 증거 이름, 작성일, 내용"이며 "내용"에는 사용자가 확인한 사실만 씁니다(법적 평가 문구 없음).

## 6b. INT-2 반영 (14:45 KST, v2.1)

INT-2(`reports/INT-2.md` 6절 제안)가 구현한 내용을 약속으로 고정합니다. 기존 키는 그대로이고 아래가 더해집니다.

- 오류: 1장 모양을 500과 `/api/cases/*` 안의 없는 경로에도 씁니다(`internal_error`, `not_found`). 사건 ID가 `^case_[0-9a-f]{12}$`가 아니면 404이고 아무것도 지우지 않습니다.
- 업로드(`POST /evidence`, 6장): 파일당 20MB, 사건당 10개, 확장자와 내용(매직 바이트)이 맞아야 함. 어기면 400 `bad_request`. `INTAKE`가 아니거나 실행 중이면 409 `wrong_state`.
- 실행 중 잠금: 같은 사건에 실행 중 `PUT /facts`·`PUT /drafts`·업로드·`DELETE`는 409 `wrong_state`. 실행 중에도 `GET /api/cases/{id}`는 바로 응답합니다.
- `hold_reasons[].code`: `replay_fixture_missing`, `budget_exceeded`, `missing_facts`(그 `fields`는 양식 칸 이름), `schema_failed`, `revision_exceeded`, `naming_violation`, `internal_error`(처리 중 오류, `POST /run`으로 다시 실행 가능).
- `Readings.items[]`에 `side`(`left`|`right`|`null`, 말풍선 위치). 비어 있는 값은 문자열 `"null"`이 아니라 JSON `null`. `normalized`는 금액·날짜·전화·계좌에만 채우고, 연도가 보이지 않는 날짜는 `null`.
- `Review.fields[]`에 `null_reason`(값이 있으면 `null`). `Review.conflicts[]`는 `{ "fields": [field], "note": str }`(화면은 `fields`의 칸 이름과 `note`를 문장으로 보여 줌). 질문은 비었거나 충돌한 칸에만.
- `Drafts.gate_results` 순서: `G2`, `G4`, `G1a`, `G3`, `NAMING`, `DRAFT`. `DRAFT`는 문안 규칙(`agents/draft_rules.py`): 계산값 슬롯(`remaining_principal`, `accrual_start_date`, `total_claim_amount`, `calculated_interest`, `delay_rate`) 금지, 말하기 동사가 있는 `fact` 문장은 인용 슬롯 필수, `user` 문장은 발화 묘사 금지. 계산값은 편철 담당이 정형 문구로만 넣습니다. G2는 검증 결과의 `missing_requirements`, G4는 `limit_check.exceeded`에서 나오며, 한국 G4 초과는 HOLD가 아니라 안내입니다.
- `PUT /drafts`: 고친 문장은 G1a·G3·NAMING·DRAFT를 다시 거치고, `approved` 없이 고치면 승인이 풀립니다. `rendered_text`는 고칠 때마다 다시 만듭니다.
- 단계 상태: 지나간 사용자 단계(`checkpoint_1`, `draft_approval`)는 `done`. 사건 상태는 `DRAFTING`·`VERIFYING`을 실제로 거칩니다. 단계 비용은 응답 usage로 계산하고 HOLD·되돌리기 뒤에도 남습니다.

## 6c. M4·M5·M6 반영 (16:33 KST, v2.2)

M4a·M4b·M5·M6과 그 수정 작업이 구현한 내용을 고정합니다. INT-3이 이 절에 맞춥니다.

- 판독(`Readings.items[]`): 기본 모델 `muse-spark-1.2`, 프롬프트 `reader.v2`. 세로로 긴 이미지는 겹치는 조각으로 읽어 원본 픽셀 상자로 합침. 상자가 이미지 밖이면 자르지 않고 `box_warning: "out_of_range"`. 영상 증거는 이번 버전에서 `skipped`(2장 그대로, 16:46 결정: 핵심 프레임 판독은 중복·시각 오차·ffmpeg 의존 때문에 사건 흐름에 넣지 않음, `reports/M4b-review.md`).
- 감식(`GET /segments`): `status`에 `hold`(호출·해석 오류, "못 찾음"과 구분)와 `error` 문구. 서명 객체는 SAM 칸 상자 `box`(`source: "box"`, SAM `score`)와 잉크 상자 `ink_box`(`ink_source: "pixel_rule"`)를 따로 둠. `mask_url`은 `image/png`.
- 가림(`GET /redactions`): `previews[]`에 `status: "redacted"|"not_redacted"`, `needs_review`(가림 상자 바깥 띠에 글자가 남았을 수 있음 등), `reason`. `not_redacted`면 `url: null`이고 가린 사본 파일이 없어야 함. 가림 단계 전에는 `leak_check.status`가 `pending`. `plan[]`의 `needs_review`·`reason`.
- `PUT /facts`의 `redaction_confirmed`: `true|false`만(그 밖은 400). `true`면 `needs_review` 사본도 서류에 씀. 데모 고정 입력은 `needs_review`가 있을 때 화면에서 사용자가 확인하는 장면으로 보여 주고 `true`를 보냄.
- `hold_reasons[].code` 추가: `privacy_leak`(가린 영역이 검정이 아님·원본 해시 변경, `POST /run`으로 가림부터 재실행), `g1b_failed`(값 불일치·명칭·누출, `POST /run`으로 편철부터 재실행), `config_missing_key`.
- `Package.files`: `content_proof.pdf`, `exhibits.pdf`(표지 1쪽 "법원에 낼 때는 이 쪽을 빼세요" + 증거별 쪽, 긴 이미지는 "갑 제N호증 (i/n)"로 나눔, 가린 사본만, 사본이 없거나 확인이 필요하면 그 쪽에 안내 한 줄), `evidence_list.pdf`(칸 "호증 번호, 증거 이름, 작성일, 내용", 증거 이름은 역할로). `Package.gate_results`의 G1b는 서류별 대조. 이미지를 뺀 것은 `fail`이 아니라 `notes`.
- 서류 문구: 내용증명은 "본인"·"귀하", 전자소송 청구원인은 "채권자"·"채무자"로 슬롯에서 렌더링(인용 원문은 그대로), 인용 표기는 "(갑 제N호증)."(내용증명에는 없음), 충당 문구는 계산값(기간·이율 포함).
- 화면: 게이트 한글 이름에 `DRAFT` "문안 규칙 검사", `G1b` "최종 서류 검사", 통과 줄 "✓ 통과", 건너뛴 G1b 숨김. 보드 머리 호출 수는 판독·감식 `substeps` 중 `done` + 나머지 모델 단계 `attempts`. 금액 입력은 "5,000,000원"처럼 쉼표·"원"만 붙은 정수만 변환.

## 7. 재생 모드와 가짜 서버

- `META_MODE=replay`(기본)에서 샘플 사건은 기록된 fixture만으로 `CHECKPOINT_2`까지 갑니다. 화면 수정 장면(문장에 "500만 원"을 넣으면 G1a가 막음)은 규칙만 쓰므로 재생에서도 됩니다.
- M2b 가짜 서버는 `specs/case-api-examples/`의 JSON만 돌려주고 `stub: true`를 붙입니다. 화면은 `stub`이면 빨간 "STUB DATA" 띠를 보여 줍니다. 데모 녹화는 가짜 서버로 하지 않습니다.
