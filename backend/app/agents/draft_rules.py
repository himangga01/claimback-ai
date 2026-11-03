"""Draft truthfulness rules (INT-2 P1, M2c hardened, M2c-fix1).

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
- M2c-fix1: a ``user`` sentence must not use a slot of an
  evidence-backed field (amount/date slots by default; that fact
  belongs in a ``fact`` sentence), and must not share amount/date
  slots with another sentence (name-only overlap is fine).
- M2c: no sentence may end right after a quote slot
  (an unfinished "... 하며 "quote"." shape).
- M2c-fix1: a quote slot's exhibit must match the ``[[EX:n]]`` tag
  right after it.

Speech detection is done per eojeol (word unit), not by raw
substring: quotative endings (다고/라고/자고/냐고) followed by a
speech matrix verb (했다/하였다/말했/하셨/...), hearsay endings
(다며/라며/다면서/라면서), promise forms (verb-stem + 기로,
주겠/갚겠/보내겠/드리겠), speech verbs (말하/말했/말씀,
언급하/언급했, 답하/답했, 묻/물었..., 약속했/약속하였), and a
quotative ending followed by 문자/메시지/연락 ... 보내. Bare nouns
such as "요청" or "약속" (약속한 대로, 요청하였으나) do not
trigger, and neither do non-promise 기로 (믿기로, 계기로) or a bare
물어 (이자를 물어 주지 않았습니다).

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

# Standalone speech/promise markers matched inside one eojeol.
# Bare nouns ("요청", "약속") are deliberately absent: noun usages
# ("약속한 대로", "... 요청하였으나") must pass. Bare "기로" and
# bare "물어" are absent too (M2c-fix1 D4): "기로" only counts with
# a payment verb stem (GIRO_MARKERS), and "물어" only right after a
# quotative ending (SPEECH_MATRIX).
SPEECH_VERBS = (
    "주겠",
    "갚겠",
    "보내겠",
    "드리겠",
    "돌려드리",
    "말하",
    "말했",
    "말씀",
    "언급하",
    "언급했",
    "답하",
    "답했",
    "약속했",
    "약속하였",
    "약속하",
    "다며",
    "라며",
    "다면서",
    "라면서",
    "물었",
    "물으",
    "묻",
)

# Payment verb stems: only stem + "기로" counts as a promise
# (M2c-fix1 D4). "믿기로", "계기로" and the like pass.
GIRO_STEMS = (
    "갚",
    "보내",
    "주",
    "드리",
    "변제하",
    "지급하",
    "상환하",
    "입금하",
    "송금하",
    "전달하",
    "납부하",
    "지불하",
    "내",
)
GIRO_MARKERS = tuple(stem + "기로" for stem in GIRO_STEMS)

# Quotative endings: only count as speech together with a matrix verb
# in the same eojeol's remainder or the next eojeol, or together with
# a message noun + send verb in the next eojeols (M2c-fix1 D1).
SPEECH_QUOTATIVES = ("다고", "라고", "자고", "냐고")

# Matrix verb forms allowed right after a quotative eojeol. The match
# is a prefix match on the (punctuation-stripped) eojeol, so
# "요청하였으나" or "못했다" after a quotative do not trigger while
# "했다"/"하였다"/"말했습니다"/"하셨습니다" do.
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
    "말했",
    "말씀",
    "하셨",
    "답하",
    "답했",
    "물었",
    "물어",
    "물으",
    "묻",
)

# After a quotative ending, a message noun followed by a send verb
# ("... 달라고 문자를 보냈습니다") is reported speech (M2c-fix1 D1).
# These never trigger on their own: "보냈습니다" and "연락" pass.
MESSAGE_NOUNS = ("문자", "메시지", "연락")
SEND_VERBS = ("보내", "보냈", "보낸", "보냄")

_SLOT_RE = re.compile(r"\{\{\s*([^}]*?)\s*\}\}")
_QUOTE_RE = re.compile(r"\{\{\s*quote:[A-Za-z0-9_]+:[A-Za-z0-9_]+\s*\}\}")
_QUOTE_EX_RE = re.compile(r"\{\{\s*quote:([A-Za-z0-9_]+):([A-Za-z0-9_]+)\s*\}\}")
_TAG_RE = re.compile(r"\[\[[^\]]*\]\]")
_EX_TAG_RE = re.compile(r"\[\[EX:([A-Za-z0-9]+)\]\]")
_STRIP_CHARS = " \t\r\n.,!?\"'“”‘’·…:;"

__all__ = [
    "CALCULATED_SLOTS",
    "NAME_SLOTS",
    "AMOUNT_DATE_SLOTS",
    "SPEECH_VERBS",
    "GIRO_STEMS",
    "GIRO_MARKERS",
    "SPEECH_QUOTATIVES",
    "SPEECH_MATRIX",
    "MESSAGE_NOUNS",
    "SEND_VERBS",
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
        for marker in GIRO_MARKERS:
            if marker in word:
                return marker
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
            window = words[index + 1:index + 5]
            for pos2, cand in enumerate(window):
                if any(noun in cand for noun in MESSAGE_NOUNS):
                    for later in window[pos2:]:
                        if any(send in later for send in SEND_VERBS):
                            return quot + "+문자보냈"
                    break
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


def _quote_tag_mismatches(text: str) -> List[tuple]:
    """(quote ex_id, tag number) pairs where the tag after a quote differs."""
    out: List[tuple] = []
    quotes = list(_QUOTE_EX_RE.finditer(text))
    tags = list(_EX_TAG_RE.finditer(text))
    for pos, match in enumerate(quotes):
        end = match.end()
        next_start = quotes[pos + 1].start() if pos + 1 < len(quotes) else None
        tag = next(
            (cand for cand in tags
             if cand.start() >= end
             and (next_start is None or cand.start() < next_start)),
            None,
        )
        if tag is not None and (deps.ex_to_num(match.group(1))
                                != deps.ex_to_num(tag.group(1))):
            out.append((match.group(1), tag.group(1)))
    return out


def check_draft_rules(
    sentences: List[Dict[str, Any]],
    sourced_slots: Any = None,
) -> Any:
    """P1 truthfulness gate (gate name ``DRAFT``).

    ``sourced_slots`` lists the slots of evidence-backed fields; a
    ``user`` sentence must not use them (that fact belongs in a
    ``fact`` sentence). Callers that do not track sources get the
    default: every amount/date slot counts as sourced.
    """
    if sourced_slots is None:
        sourced = set(AMOUNT_DATE_SLOTS)
    else:
        sourced = {str(name).strip() for name in sourced_slots
                   if str(name).strip()}
    user_blocked = (sourced - set(NAME_SLOTS)) - set(CALCULATED_SLOTS)
    findings: List[Any] = []
    combos: List[set] = []
    for entry in sentences or []:
        text = str(entry.get("text_with_slots", ""))
        names = {
            name for name in _slot_names(text)
            if not name.startswith("quote:") and name not in CALCULATED_SLOTS
        }
        combos.append(names & set(AMOUNT_DATE_SLOTS))
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
            for name in sorted(set(_slot_names(text)) & user_blocked):
                findings.append(deps.Finding(
                    sentence_id=sid,
                    field="text_with_slots",
                    message=(f"근거 있는 칸의 슬롯을 사용자 진술 문장에 "
                             f"쓸 수 없습니다: {name}"),
                    fix_hint="그 사실은 증거(사실) 문장으로 쓰세요.",
                ))
            combo = combos[pos]
            if combo and any(combo & other for idx, other in enumerate(combos)
                             if idx != pos):
                findings.append(deps.Finding(
                    sentence_id=sid,
                    field="text_with_slots",
                    message=("다른 문장과 같은 슬롯 조합을 되풀이했습니다"
                               "(금액·날짜 슬롯 겹침)."),
                    fix_hint="사용자 진술 문장은 증거로 확인되지 않는 사실에만 쓰세요.",
                ))
        for quote_ex, tag_num in _quote_tag_mismatches(text):
            findings.append(deps.Finding(
                sentence_id=sid,
                field="text_with_slots",
                message=(f"인용 슬롯의 증거({quote_ex})와 뒤의 근거 태그"
                         f"([[EX:{tag_num}]])가 다릅니다."),
                fix_hint="인용한 증거와 같은 번호의 태그를 붙이세요.",
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
