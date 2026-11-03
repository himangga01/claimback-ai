import re
import unicodedata
from typing import List, Tuple


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

_DRAFT_PATTERNS: List[Tuple[str, str]] = [
    ("debt-admission", r"채무\s*[를을]?\s*(?:인정|승인)"),
    ("legal-service", r"법률\s*(?:자문|대리)"),
    ("lawyer-ko", r"변\s*호\s*사"),
    ("legal-scrivener", r"법\s*무\s*사"),
    ("law-office", r"법률\s*사무소"),
    ("law-firm-ko", r"법무\s*법인"),
    ("lawfirm-short", r"로\s*펌"),
    ("lawyer", r"\blawyer\b"),
    ("attorney", r"\battorney\b"),
    ("law-firm", r"\blaw[\s-]+firm\b"),
    ("paralegal", r"\bparalegal\b"),
    ("legal-assistant", r"\blegal\s+assistant\b"),
    ("counsel", r"\bcounsel\b"),
    ("legal-advice", r"\blegal[\s-]+advice\b"),
    ("win-ko", r"승\s*소"),
    ("lose-ko", r"패\s*소"),
    ("you-win", r"\byou(?:'ll| will| are likely to)\s+win\b"),
    ("win-case", r"\bwin\s+your\s+case\b"),
    ("chance-winning", r"\bchance\s+of\s+winning\b"),
    ("debt-ack", r"\bdebt\s+acknowledgment\b"),
    ("ack-debt", r"\backnowledgment\s+of\s+debt\b"),
    ("promissory", r"\bpromissory\s+admission\b"),
    ("just-cause", r"정당한\s*사유\s*없이"),
    ("claim-right", r"청구권이\s*발생"),
    ("legal-claim", r"법적\s*청구\s*대상"),
    ("elements-lack", r"요건사실\s*결손"),
    ("prove-future", r"입증할"),
    ("can-win", r"이길\s*수"),
    ("wins", r"이깁니다"),
    ("win-chance", r"승산"),
    ("recoverable", r"돌려받을\s*수\s*있"),
    ("clearly-illegal", r"명백한\s*불법"),
]

_DOC_ONLY_PATTERNS: List[Tuple[str, str]] = [
    ("final-demand", r"최종\s*(?:변제|독촉|통고|경고)"),
    ("urge", r"촉구"),
]

_DRAFT_RES = [(name, re.compile(pat, re.IGNORECASE)) for name, pat in _DRAFT_PATTERNS]
_DOC_RES = [(name, re.compile(pat, re.IGNORECASE)) for name, pat in (_DRAFT_PATTERNS + _DOC_ONLY_PATTERNS)]


def normalize_text(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Cf")
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _remove_allowlist(text: str) -> str:
    out = text
    for allow in ALLOWLIST:
        norm_allow = normalize_text(allow) if allow else ""
        if norm_allow and norm_allow in out:
            out = out.replace(norm_allow, " ")
    return out


def _find_with(patterns, text: str) -> List[str]:
    cleaned = _remove_allowlist(normalize_text(text))
    found: List[str] = []
    for _name, rx in patterns:
        for m in rx.finditer(cleaned):
            s = m.group(0).strip()
            if s:
                found.append(s)
    return found


def find_forbidden(text: str) -> List[str]:
    return _find_with(_DOC_RES, text)


def check_text(text: str) -> List[str]:
    return find_forbidden(text)


def find_forbidden_draft(text: str) -> List[str]:
    return _find_with(_DRAFT_RES, text)


def check_draft(slot_draft):
    from app.services.draft_gates import GateResult, Finding

    findings = []
    for s in slot_draft.sentences:
        hits = _find_with(_DRAFT_RES, s.text_with_slots)
        if hits:
            findings.append(
                Finding(
                    sentence_id=s.sentence_id,
                    field="text_with_slots",
                    message=f"초안에 쓸 수 없는 표현이 있습니다: {hits[0]}",
                    fix_hint="사실대로 고쳐 쓰세요.",
                )
            )
    status = "fail" if findings else "pass"
    return GateResult(gate="NAMING", status=status, findings=findings)
