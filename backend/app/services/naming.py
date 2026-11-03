from typing import List


DISCLAIMER_KO = (
    "ClaimBack-AI는 본인이 직접 소송 서류를 준비할 때 쓰는 무료 정리 도구입니다. "
    "법률 자문을 제공하지 않으며, 서류에 들어가는 사실은 모두 사용자가 확인한 내용입니다. "
    "법률 상담은 대한법률구조공단(132)이나 변호사에게 받으세요."
)

DISCLAIMER_EN = (
    "ClaimBack-AI is a free self-help tool for organizing your own evidence and filling "
    "standard court forms. It does not provide legal advice. Every fact in the documents "
    "is confirmed by you. For help, contact your court's self-help center or a small claims advisor."
)

NOTICE_KO = "본인 작성용 초안, 법률 자문 아님"
NOTICE_EN = "Self-help draft. Not legal advice."

ALLOWLIST = [DISCLAIMER_KO, DISCLAIMER_EN, NOTICE_KO, NOTICE_EN]

FORBIDDEN = [
    "변호사",
    "법무사",
    "법률사무소",
    "법무법인",
    "로펌",
    "법률 대리",
    "법률 자문",
    "lawyer",
    "attorney",
    "law firm",
    "paralegal",
    "legal assistant",
    "counsel",
    "legal advice",
    "승소",
    "패소",
    "you will win",
    "win your case",
    "chance of winning",
    "채무 인정",
    "채무 승인",
    "debt acknowledgment",
    "acknowledgment of debt",
    "Promissory Admission",
    "정당한 사유 없이",
    "청구권이 발생",
    "법적 청구 대상",
    "요건사실 결손",
    "입증할",
]


def _remove_allowlist(text: str) -> str:
    out = text
    for allow in ALLOWLIST:
        if allow and allow in out:
            out = out.replace(allow, " ")
    return out


def _is_ascii_phrase(phrase: str) -> bool:
    return any("a" <= ch <= "z" or "A" <= ch <= "Z" for ch in phrase)


def find_forbidden(text: str) -> List[str]:
    cleaned = _remove_allowlist(text)
    lowered = cleaned.lower()
    found: List[str] = []
    for phrase in FORBIDDEN:
        if _is_ascii_phrase(phrase):
            if phrase.lower() in lowered:
                found.append(phrase)
        else:
            if phrase in cleaned:
                found.append(phrase)
    return found


def check_text(text: str) -> List[str]:
    return find_forbidden(text)
