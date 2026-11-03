# 사건 API 예시 응답

`specs/case-api-contract.md`의 예시 응답입니다(Claude 작성, 2026-11-03).

- M2b 가짜 서버는 이 파일들을 그대로 돌려줍니다(`stub: true`를 붙여서).
- M2a 테스트는 실제 응답에 이 예시의 키가 모두 있는지 확인합니다(값은 다를 수 있음).
- `drafts.json`의 `calculation`은 병합된 M1 코드(`calculate_kr`, 고정 예시, 기준일 2026-06-01)의 실제 출력입니다.
- `readings.json`의 박스 좌표는 예시용 근삿값입니다. 정답 데이터(`backend/tests/golden/`)에서 가져오지 않았습니다.
- `confirmed_facts_kr.json`은 데모·테스트 고정 입력 규칙(계약서 5장)의 기준값과 빈 칸 채움값입니다.
