import hashlib
import json
import os

SAMPLE_DIR = os.path.dirname(__file__)

def make_sample_files():
    # 1. 한국 샘플은행 이체확인증 모의 파일
    kr_transfer_text = """[샘플은행 송금확인증]
송금일시: 2026년 01월 01일 14:22:10
보낸 분: 정재훈 (샘플은행 1000-****-7547)
받는 분: 김채무 (샘플은행 3333-****-5678)
송금금액: 10,000,000원 (금 일천만 원)
송금메모: 대여금 (6월 30일 변제 약정)
상태: 정상 이체완료
거래번호: 20260101-SAMPLE-994821
"""
    p1 = os.path.join(SAMPLE_DIR, "kr_transfer_receipt.txt")
    with open(p1, "w", encoding="utf-8", newline="\n") as f:
        f.write(kr_transfer_text)
    h1 = hashlib.sha256(kr_transfer_text.encode("utf-8")).hexdigest()

    # 2. 샘플톡 대화록 모의 파일
    kr_chat_text = """[2026-06-25 18:30] 정재훈: 채무야, 6월 30일 약속한 천만 원 상환 준비 잘 되고 있어?
[2026-06-25 18:32] 김채무: 형님 죄송해요 사업 정산이 조금 늦어져서요.. 다음 달 15일까지는 무조건 꼭 갚을게요 진짜 죄송합니다
[2026-06-25 18:35] 정재훈: 약속대로 6월 30일까지 안 들어오면 법적 절차(지급명령) 들어갈 수밖에 없어.
[2026-06-25 18:36] 김채무: 네 무슨 말씀인지 잘 알겠습니다. 원금 1,000만 원이랑 지연손해금까지 다 책임지겠습니다.
"""
    p2 = os.path.join(SAMPLE_DIR, "kr_chat_log.txt")
    with open(p2, "w", encoding="utf-8", newline="\n") as f:
        f.write(kr_chat_text)
    h2 = hashlib.sha256(kr_chat_text.encode("utf-8")).hexdigest()

    # 3. 미국 Wire Transfer 모의 파일
    us_transfer_text = """[WIRE TRANSFER RECEIPT - SAMPLE BANK]
Date: January 10, 2026 10:15 AM PST
Sender: Jaehoon Jeong (Account Ending in 7547)
Beneficiary: Michael Scott (Account Ending in 0144, Sample Bank Los Angeles)
Amount: $5,000.00 USD
Memo: Personal bridge loan (Due April 10, 2026)
Reference Number: SAMPLE-WIRE-20260110-88192
Status: COMPLETED
"""
    p3 = os.path.join(SAMPLE_DIR, "us_wire_receipt.txt")
    with open(p3, "w", encoding="utf-8", newline="\n") as f:
        f.write(us_transfer_text)
    h3 = hashlib.sha256(us_transfer_text.encode("utf-8")).hexdigest()

    manifest = {
        "korean_sample": {
            "transfer_receipt": {"file": "kr_transfer_receipt.txt", "sha256": h1},
            "chat_log": {"file": "kr_chat_log.txt", "sha256": h2},
        },
        "us_sample": {
            "wire_receipt": {"file": "us_wire_receipt.txt", "sha256": h3},
        }
    }
    with open(os.path.join(SAMPLE_DIR, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print("Mock evidence generated successfully with SHA-256 hashes.")

if __name__ == "__main__":
    make_sample_files()
