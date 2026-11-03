"""Draft truthfulness rules (INT-2 P1).

The drafter must not invent speech or computed numbers:

- Calculated slots (remaining_principal, accrual_start_date,
  total_claim_amount, calculated_interest, delay_rate) are forbidden in
  drafts. The packager inserts computed values with fixed phrases.
- Someone's speech may only appear as a quote slot
  (``{{quote:EXn:itemN}}``). A ``fact`` sentence that describes speech
  (speaking verbs) must contain at least one quote slot.
- A ``user`` sentence must not describe utterances at all.

Run together with G1a/G3 in the drafting loop, PUT /drafts, and the
pre-packaging check.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from app.agents import deps

CALCULATED_SLOTS = (
    "remaining_principal",
    "accrual_start_date",
    "total_claim_amount",
    "calculated_interest",
    "delay_rate",
)

SPEECH_VERBS = ("말하", "언급", "주겠다", "갚겠다", "약속", "요청")

_SLOT_RE = re.compile(r"\{\{\s*([^}]*?)\s*\}\}")
_QUOTE_RE = re.compile(r"\{\{\s*quote:[A-Za-z0-9_]+:[A-Za-z0-9_]+\s*\}\}")

__all__ = [
    "CALCULATED_SLOTS",
    "SPEECH_VERBS",
    "drafter_allowed_slots",
    "check_draft_rules",
]


def drafter_allowed_slots(values: Dict[str, str]) -> List[str]:
    """Allowed slots for the drafter (calculated slots excluded)."""
    available = deps.available_slots(values)
    banned = set(CALCULATED_SLOTS)
    return [slot for slot in available if slot not in banned]


def _has_speech_verb(text: str) -> str | None:
    for verb in SPEECH_VERBS:
        if verb in text:
            return verb
    return None


def check_draft_rules(sentences: List[Dict[str, Any]]) -> Any:
    """P1 truthfulness gate (gate name ``DRAFT``)."""
    findings: List[Any] = []
    for entry in sentences or []:
        sid = str(entry.get("sentence_id", ""))
        stype = str(entry.get("type", "fact"))
        text = str(entry.get("text_with_slots", ""))
        for match in _SLOT_RE.finditer(text):
            name = match.group(1).strip()
            if name in CALCULATED_SLOTS:
                findings.append(deps.Finding(
                    sentence_id=sid,
                    field="text_with_slots",
                    message=f"계산값 슬롯은 쓸 수 없습니다: {name}",
                    fix_hint="계산값은 편철 담당이 정형 문구로 넣습니다.",
                ))
        verb = _has_speech_verb(text)
        has_quote = _QUOTE_RE.search(text) is not None
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
    status = "fail" if findings else "pass"
    return deps.GateResult(gate="DRAFT", status=status, findings=findings)
