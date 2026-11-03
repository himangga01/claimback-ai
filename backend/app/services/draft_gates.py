import re
from typing import List, Literal, Dict, Optional
from pydantic import BaseModel, Field


KR_SLOTS: List[str] = [
    "creditor_name",
    "debtor_name",
    "principal",
    "loan_date",
    "due_date",
    "repaid_amount",
    "repaid_date",
    "remaining_principal",
    "accrual_start_date",
    "total_claim_amount",
    "calculated_interest",
    "demand_date",
    "creditor_phone",
    "debtor_phone",
    "creditor_address",
    "debtor_address",
]


class SlotSentence(BaseModel):
    sentence_id: str = Field(..., description="문장 ID")
    type: Literal["fact", "user"] = Field(..., description="문장 유형")
    text_with_slots: str = Field(..., description="슬롯 포함 문장")
    ex_refs: List[str] = Field(default_factory=list, description="참조 호증 번호 목록")


class SlotDraft(BaseModel):
    lang: str = Field(default="ko", description="언어")
    sentences: List[SlotSentence] = Field(default_factory=list, description="문장 목록")


class Finding(BaseModel):
    sentence_id: str = Field(..., description="문장 ID")
    field: str = Field(default="text_with_slots", description="지적 위치")
    message: str = Field(..., description="지적 내용")
    fix_hint: str = Field(default="", description="수정 안내")


class GateResult(BaseModel):
    gate: str = Field(..., description="게이트 이름")
    status: Literal["pass", "fail"] = Field(..., description="통과 여부")
    findings: List[Finding] = Field(default_factory=list, description="지적 목록")


_SLOT_RE = re.compile(r"\{\{(.*?)\}\}")
_TAG_RE = re.compile(r"\[\[(.*?)\]\]")
_EX_TAG_RE = re.compile(r"\[\[EX:([A-Za-z0-9]+)\]\]")
_ARABIC_RE = re.compile(r"[0-9]")
_SINO_NUM_SEQ_RE = re.compile(r"[일이삼사오육륙칠팔구십백천만억조영공]{2,}")
_AMOUNT_UNIT_RE = re.compile(r"[0-9일이삼사오육륙칠팔구십백천만억조]+\s*원")
_MONTH_RE = re.compile(r"[일이삼사오육유칠팔구십시]+월")
_DAY_RE = re.compile(r"[일이삼사오육륙칠팔구십]+일")
_YEAR_RE = re.compile(r"[일이삼사오육륙칠팔구십백천만억]+년")
_DOTTED_DATE_RE = re.compile(r"\d+\.\s*\d+\.\s*\d+\.?")

RELATIVE_DATES: List[str] = [
    "다음 달", "다음달",
    "지난주", "지난 주",
    "열흘 뒤", "열흘 후",
    "다음 주", "다음주",
    "지난 달", "지난달",
    "이번 달", "이번달",
    "내일", "모레", "어제",
    "올해", "작년", "내년",
    "다음 해", "다음해",
    "지난 해", "지난해",
    "이틀 뒤", "사흘 뒤", "닷새 뒤",
    "한 달 뒤", "두 달 뒤",
    "일주일 뒤", "한 주 뒤",
    "다음 날", "다음날",
]

FIXED_PHRASES: List[str] = [
    "지급하라",
    "독촉절차비용",
    "라는 명령을 구함",
]

_HONORIFICS = ("씨", "님", "군", "양", "모씨")


def _strip_slots_and_tags(text: str) -> str:
    no_slots = _SLOT_RE.sub(" ", text)
    no_tags = _TAG_RE.sub(" ", no_slots)
    return no_tags


def _base_name(full: str) -> str:
    b = full.replace("(SAMPLE)", "").replace("(Sample)", "").replace("(sample)", "")
    b = b.strip()
    return b


def _is_korean_name(base: str) -> bool:
    return any("가" <= ch <= "힣" for ch in base) and " " not in base.strip()


def _check_names_outside(
    text_outside: str, party_names: List[str], sentence_id: str
) -> List[Finding]:
    findings: List[Finding] = []
    for full in party_names:
        base = _base_name(full)
        if not base:
            continue
        if _is_korean_name(base):
            if base in text_outside:
                findings.append(
                    Finding(
                        sentence_id=sentence_id,
                        field="text_with_slots",
                        message=f"당사자 이름이 슬롯 밖에서 발견되었습니다: {base}",
                        fix_hint="이름은 슬롯으로 넣으세요.",
                    )
                )
                continue
            if len(base) >= 2:
                given = base[1:]
                if given and given in text_outside:
                    findings.append(
                        Finding(
                            sentence_id=sentence_id,
                            field="text_with_slots",
                            message=f"당사자 이름 일부가 슬롯 밖에서 발견되었습니다: {given}",
                            fix_hint="이름은 슬롯으로 넣으세요.",
                        )
                    )
                    continue
            family = base[0] if base else ""
            if family:
                for hon in _HONORIFICS:
                    pat = re.compile(re.escape(family) + r"\s?" + re.escape(hon))
                    if pat.search(text_outside):
                        findings.append(
                            Finding(
                                sentence_id=sentence_id,
                                field="text_with_slots",
                                message=f"당사자 성과 호칭이 슬롯 밖에서 발견되었습니다: {family}+{hon}",
                                fix_hint="이름은 슬롯으로 넣으세요.",
                            )
                        )
                        break
        else:
            if base and base in text_outside:
                findings.append(
                    Finding(
                        sentence_id=sentence_id,
                        field="text_with_slots",
                        message=f"당사자 이름이 슬롯 밖에서 발견되었습니다: {base}",
                        fix_hint="이름은 슬롯으로 넣으세요.",
                    )
                )
                continue
            parts = [p for p in base.split() if p]
            for part in parts:
                if len(part) >= 2 and part in text_outside:
                    findings.append(
                        Finding(
                            sentence_id=sentence_id,
                            field="text_with_slots",
                            message=f"당사자 이름 일부가 슬롯 밖에서 발견되었습니다: {part}",
                            fix_hint="이름은 슬롯으로 넣으세요.",
                        )
                    )
                    break
    return findings


def check_g1a(
    draft: SlotDraft,
    allowed_slots: List[str],
    party_names: List[str],
) -> GateResult:
    findings: List[Finding] = []
    allowed = set(allowed_slots)
    for s in draft.sentences:
        text = s.text_with_slots
        for m in _SLOT_RE.finditer(text):
            content = m.group(1).strip()
            if not content:
                findings.append(
                    Finding(
                        sentence_id=s.sentence_id,
                        field="text_with_slots",
                        message="빈 슬롯이 있습니다.",
                        fix_hint="슬롯 이름을 확인하세요.",
                    )
                )
                continue
            if content.startswith("quote:"):
                if not re.fullmatch(r"quote:[A-Za-z0-9_]+:[A-Za-z0-9_]+", content):
                    findings.append(
                        Finding(
                            sentence_id=s.sentence_id,
                            field="text_with_slots",
                            message=f"인용 슬롯 형식이 올바르지 않습니다: {content}",
                            fix_hint="{{quote:EX번호:항목ID}} 형식을 쓰세요.",
                        )
                    )
                continue
            if content not in allowed:
                findings.append(
                    Finding(
                        sentence_id=s.sentence_id,
                        field="text_with_slots",
                        message=f"허용 목록에 없는 슬롯 이름입니다: {content}",
                        fix_hint="허용 슬롯 목록을 확인하세요.",
                    )
                )
        outside = _strip_slots_and_tags(text)
        if _ARABIC_RE.search(outside):
            findings.append(
                Finding(
                    sentence_id=s.sentence_id,
                    field="text_with_slots",
                    message="슬롯 밖에 아라비아 숫자가 있습니다.",
                    fix_hint="숫자는 슬롯으로 넣으세요.",
                )
            )
        if _SINO_NUM_SEQ_RE.search(outside):
            findings.append(
                Finding(
                    sentence_id=s.sentence_id,
                    field="text_with_slots",
                    message="슬롯 밖에 한글 수사가 있습니다.",
                    fix_hint="금액과 수량은 슬롯으로 넣으세요.",
                )
            )
        elif _AMOUNT_UNIT_RE.search(outside):
            findings.append(
                Finding(
                    sentence_id=s.sentence_id,
                    field="text_with_slots",
                    message="슬롯 밖에 금액 단위가 있습니다.",
                    fix_hint="금액은 슬롯으로 넣으세요.",
                )
            )
        if (
            _MONTH_RE.search(outside)
            or _DAY_RE.search(outside)
            or _YEAR_RE.search(outside)
            or _DOTTED_DATE_RE.search(outside)
        ):
            findings.append(
                Finding(
                    sentence_id=s.sentence_id,
                    field="text_with_slots",
                    message="슬롯 밖에 날짜 표현이 있습니다.",
                    fix_hint="날짜는 슬롯으로 넣으세요.",
                )
            )
        for rel in RELATIVE_DATES:
            if rel in outside:
                findings.append(
                    Finding(
                        sentence_id=s.sentence_id,
                        field="text_with_slots",
                        message=f"슬롯 밖에 상대 날짜가 있습니다: {rel}",
                        fix_hint="날짜는 슬롯으로 넣으세요.",
                    )
                )
                break
        findings.extend(_check_names_outside(outside, party_names, s.sentence_id))
        for phrase in FIXED_PHRASES:
            if phrase in outside:
                findings.append(
                    Finding(
                        sentence_id=s.sentence_id,
                        field="text_with_slots",
                        message=f"문안 작성 범위를 벗어난 정형 문구가 있습니다: {phrase}",
                        fix_hint="정형 문구는 편철 단계에서 넣습니다.",
                    )
                )
                break
    status: Literal["pass", "fail"] = "fail" if findings else "pass"
    return GateResult(gate="G1a", status=status, findings=findings)


def check_g3(draft: SlotDraft, existing_exhibits: List[str]) -> GateResult:
    findings: List[Finding] = []
    existing = set(str(e) for e in existing_exhibits)
    for s in draft.sentences:
        text = s.text_with_slots
        if s.type == "fact":
            tags = _EX_TAG_RE.findall(text)
            if not tags:
                findings.append(
                    Finding(
                        sentence_id=s.sentence_id,
                        field="text_with_slots",
                        message="사실 문장에 근거 태그가 없습니다.",
                        fix_hint="[[EX:번호]]를 넣으세요.",
                    )
                )
            else:
                for n in tags:
                    if str(n) not in existing:
                        findings.append(
                            Finding(
                                sentence_id=s.sentence_id,
                                field="text_with_slots",
                                message=f"목록에 없는 호증 번호입니다: {n}",
                                fix_hint="호증 번호를 확인하세요.",
                            )
                        )
            for ref in s.ex_refs:
                if str(ref) not in existing:
                    findings.append(
                        Finding(
                            sentence_id=s.sentence_id,
                            field="ex_refs",
                            message=f"목록에 없는 호증 번호입니다: {ref}",
                            fix_hint="호증 번호를 확인하세요.",
                        )
                    )
        else:
            if "[[USER]]" not in text:
                findings.append(
                    Finding(
                        sentence_id=s.sentence_id,
                        field="text_with_slots",
                        message="사용자 진술 문장에 표시가 없습니다.",
                        fix_hint="[[USER]]를 넣으세요.",
                    )
                )
    status: Literal["pass", "fail"] = "fail" if findings else "pass"
    return GateResult(gate="G3", status=status, findings=findings)


def substitute_text(
    text: str, values: Dict[str, str], quotes: Optional[Dict[str, str]] = None
) -> str:
    quotes = quotes or {}

    def _repl(m: re.Match) -> str:
        content = m.group(1).strip()
        if content.startswith("quote:"):
            if content in quotes:
                return quotes[content]
            short = content[len("quote:"):]
            if short in quotes:
                return quotes[short]
            raise ValueError(f"인용 원문이 없습니다: {content}")
        if content in values:
            return str(values[content])
        raise ValueError(f"확인값이 없습니다: {content}")

    out = _SLOT_RE.sub(_repl, text)
    if _SLOT_RE.search(out):
        raise ValueError("치환 후에도 슬롯이 남았습니다.")
    return out


def substitute_draft(
    draft: SlotDraft, values: Dict[str, str], quotes: Optional[Dict[str, str]] = None
) -> SlotDraft:
    quotes = quotes or {}
    new_sentences: List[SlotSentence] = []
    for s in draft.sentences:
        new_text = substitute_text(s.text_with_slots, values, quotes)
        new_sentences.append(
            SlotSentence(
                sentence_id=s.sentence_id,
                type=s.type,
                text_with_slots=new_text,
                ex_refs=list(s.ex_refs),
            )
        )
    return SlotDraft(lang=draft.lang, sentences=new_sentences)
