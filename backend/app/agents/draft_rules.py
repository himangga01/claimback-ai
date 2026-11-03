"""Draft truthfulness rules (INT-2 P1, M2c hardened).

The drafter must not invent speech or computed numbers:

- Calculated slots (remaining_principal, accrual_start_date,
  total_claim_amount, calculated_interest, delay_rate,
  contract_interest) are forbidden in drafts. The packager inserts
  computed values with fixed phrases.
- Someone's speech may only appear as a quote slot
  (``{{quote:EXn:itemN}}``). A ``fact`` sentence that describes speech
  must contain at least one quote slot.
- A ``user`` sentence must not describe utterances at all.
- M2c: a sentence with a quote slot or a speech/promise expression
  may only use party-name slots; amount/date slots are rejected
  (the quote content and the slots could otherwise disagree).
- M2c: a ``user`` sentence must not repeat another sentence's slot
  combination, and no sentence may end right after a quote slot
  (an unfinished "... 하며 "quote"." shape).

Speech detection is done per eojeol (word unit), not by raw
substring: quotative endings (다고/라고/자고/냐고) followed by a
speech matrix verb (했다/하였다/...), promise/future forms
(기로, 주겠/갚겠/보내겠/드리겠), and speech verbs
(말하, 언급하/언급했, 답하/답했, 묻/물었...). Bare nouns such as
"요청" or "약속" (약속한 대로, 요청하였으나) do not trigger.

Run together with G1a/G3 in the drafting loop, PUT /drafts, and the
pre-packaging check.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.agents import deps

CALCULATED_SLOTS = (
    "remaining_principal",
    "accrual_start_date",
    "total_claim_amount",
    "calculated_interest",
    "delay_rate",
    "contract_interest",
)

# Party-name slots: the only value slots allowed in a sentence that
# carries a quote slot or a speech/promise expression.
NAME_SLOTS = (
    "creditor_name",
    "debtor_name",
)

# Amount/date slots: rejected in quote/speech sentences (M2c task 2).
AMOUNT_DATE_SLOTS = (
    "principal",
    "loan_date",
    "due_date",
    "repaid_amount",
    "repaid_date",
    "agreed_rate",
    "demand_date",
)

# Standalone speech/promise markers matched inside one eojeol (M2c).
# Bare nouns ("요청", "약속") are deliberately absent: noun usages
# ("약속한 대로", "... 요청하였으나") must pass.
SPEECH_VERBS = (
    "기로",
    "주겠",
    "갚겠",
    "보내겠",
    "드리겠",
    "돌려드리",
    "말하",
    "언급하",
    "언급했",
    "답하",
    "답했",
    "물었",
    "물어",
    "물으",
    "묻",
)

# Quotative endings: only count as speech together with a matrix verb
# in the same eojeol's remainder or the next eojeol.
SPEECH_QUOTATIVES = ("다고", "라고", "자고", "냐고")

# Matrix verb forms allowed right after a quotative eojeol. The match
# is a prefix match on the (punctuation-stripped) eojeol, so
# "요청하였으나" or "못했다" after a quotative do not trigger while
# "했다"/"하였다" do.
SPEECH_MATRIX = (
    "하였",
    "했",
    "한다",
    "합니",
    "하여",
    "하고",
    "하며",
    "해서",
    "말하",
    "답하",
    "답했",
    "물었",
    "물어",
    "물으",
    "묻",
)

_SLOT_RE = re.compile(r"\{\{\s*([^}]*?)\s*\}\}")
_QUOTE_RE = re.compile(r"\{\{\s*quote:[A-Za-z0-9_]+:[A-Za-z0-9_]+\s*\}\}")
_TAG_RE = re.compile(r"\[\[[^\]]*\]\]")
_STRIP_CHARS = " \t\r\n.,!?\"'“”‘’·…:;"

__all__ = [
    "CALCULATED_SLOTS",
    "NAME_SLOTS",
    "AMOUNT_DATE_SLOTS",
    "SPEECH_VERBS",
    "SPEECH_QUOTATIVES",
    "SPEECH_MATRIX",
    "drafter_allowed_slots",
    "has_speech",
    "check_draft_rules",
]


def drafter_allowed_slots(values: Dict[str, str]) -> List[str]:
    """Allowed slots for the drafter (calculated slots excluded)."""
    available = deps.available_slots(values)
    banned = set(CALCULATED_SLOTS)
    return [slot for slot in available if slot not in banned]


def _eojeols(text: str) -> List[str]:
    return [part.strip(_STRIP_CHARS) for part in str(text).split()]


def _starts_with_matrix(word: str) -> Optional[str]:
    for form in SPEECH_MATRIX:
        if word.startswith(form):
            return form
    return None


def has_speech(text: str) -> Optional[str]:
    """Detect a speech/promise expression, or return None.

    Returns the matched marker for messages/tests.
    """
    words = [word for word in _eojeols(text) if word]
    for word in words:
        for verb in SPEECH_VERBS:
            if verb in word:
                return verb
    for index, word in enumerate(words):
        for quot in SPEECH_QUOTATIVES:
            pos = word.find(quot)
            if pos < 0:
                continue
            rest = word[pos + len(quot):].strip(_STRIP_CHARS)
            if rest:
                hit = _starts_with_matrix(rest)
                if hit is not None:
                    return quot + "+" + hit
            if index + 1 < len(words):
                hit = _starts_with_matrix(words[index + 1])
                if hit is not None:
                    return quot + "+" + hit
    return None


def _has_speech_verb(text: str) -> str | None:
    return has_speech(text)


def _slot_names(text: str) -> List[str]:
    return [match.group(1).strip() for match in _SLOT_RE.finditer(text)]


def _ends_after_quote(text: str) -> bool:
    """True when nothing but tags/punctuation follows the last quote."""
    matches = list(_QUOTE_RE.finditer(text))
    if not matches:
        return False
    tail = text[matches[-1].end():]
    tail = _TAG_RE.sub("", tail)
    return tail.strip(_STRIP_CHARS) == ""


def check_draft_rules(sentences: List[Dict[str, Any]]) -> Any:
    """P1 truthfulness gate (gate name ``DRAFT``)."""
    findings: List[Any] = []
    combos: List[tuple] = []
    for entry in sentences or []:
        text = str(entry.get("text_with_slots", ""))
        names = [
            name for name in _slot_names(text)
            if not name.startswith("quote:") and name not in CALCULATED_SLOTS
        ]
        combos.append(tuple(sorted(set(names))))
    for pos, entry in enumerate(sentences or []):
        sid = str(entry.get("sentence_id", ""))
        stype = str(entry.get("type", "fact"))
        text = str(entry.get("text_with_slots", ""))
        for name in _slot_names(text):
            if name in CALCULATED_SLOTS:
                findings.append(deps.Finding(
                    sentence_id=sid,
                    field="text_with_slots",
                    message=f"계산값 슬롯은 쓸 수 없습니다: {name}",
                    fix_hint="계산값은 편철 담당이 정형 문구로 넣습니다.",
                ))
        verb = _has_speech_verb(text)
        has_quote = _QUOTE_RE.search(text) is not None
        if has_quote or verb is not None:
            for name in _slot_names(text):
                if name in AMOUNT_DATE_SLOTS:
                    findings.append(deps.Finding(
                        sentence_id=sid,
                        field="text_with_slots",
                        message=(f"인용이나 발화가 있는 문장에 금액·날짜 "
                                 f"슬롯을 쓸 수 없습니다: {name}"),
                        fix_hint="금액·날짜 슬롯은 인용·발화 없는 별도 문장에 쓰세요.",
                    ))
        if stype == "fact":
            if verb is not None and not has_quote:
                findings.append(deps.Finding(
                    sentence_id=sid,
                    field="text_with_slots",
                    message="말한 내용은 인용 슬롯으로만 쓰세요.",
                    fix_hint="{{quote:EX번호:항목ID}}로 원문을 인용하세요.",
                ))
        else:  # user: must not describe utterances at all
            if verb is not None:
                findings.append(deps.Finding(
                    sentence_id=sid,
                    field="text_with_slots",
                    message="사용자 진술 문장에 발화 묘사를 쓸 수 없습니다.",
                    fix_hint="발화는 사실 문장의 인용 슬롯으로만 쓰세요.",
                ))
            elif has_quote:
                findings.append(deps.Finding(
                    sentence_id=sid,
                    field="text_with_slots",
                    message="사용자 진술 문장에 인용 슬롯을 쓸 수 없습니다.",
                    fix_hint="인용은 사실 문장에만 쓰세요.",
                ))
            combo = combos[pos]
            if combo and any(other == combo for idx, other in enumerate(combos)
                             if idx != pos):
                findings.append(deps.Finding(
                    sentence_id=sid,
                    field="text_with_slots",
                    message="다른 문장과 같은 슬롯 조합을 되풀이했습니다.",
                    fix_hint="사용자 진술 문장은 증거로 확인되지 않는 사실에만 쓰세요.",
                ))
        if _ends_after_quote(text):
            findings.append(deps.Finding(
                sentence_id=sid,
                field="text_with_slots",
                message="인용 뒤에 서술 없이 문장이 끝났습니다.",
                fix_hint="인용 뒤에 완결된 서술을 쓰세요(예: …라고 했습니다.).",
            ))
    status = "fail" if findings else "pass"
    return deps.GateResult(gate="DRAFT", status=status, findings=findings)
