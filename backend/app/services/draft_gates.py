import re
import unicodedata
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
    "agreed_rate",
    "delay_rate",
    "contract_interest",
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


_HANJA_NUM_MAP: Dict[str, str] = {
    "\u3007": "0",
    "\u96f6": "0",
    "\u4e00": "일",
    "\u4e8c": "이",
    "\u4e09": "삼",
    "\u56db": "사",
    "\u4e94": "오",
    "\u516d": "육",
    "\u4e03": "칠",
    "\u516b": "팔",
    "\u4e5d": "구",
    "\u5341": "십",
    "\u767e": "백",
    "\u5343": "천",
    "\u842c": "만",
    "\u5104": "억",
    "\u5146": "조",
    "\u58f9": "일",
    "\u8cb3": "이",
    "\u53c3": "삼",
    "\u4f0d": "오",
    "\u62fe": "십",
    "\u4f70": "백",
    "\u4edf": "천",
}


def normalize_text(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Cf")
    if any(ch in _HANJA_NUM_MAP for ch in t):
        t = "".join(_HANJA_NUM_MAP.get(ch, ch) for ch in t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


_SLOT_RE = re.compile(r"\{\{(.*?)\}\}")
_TAG_RE = re.compile(r"\[\[(.*?)\]\]")
_EX_TAG_RE = re.compile(r"\[\[EX:([A-Za-z0-9]+)\]\]")
_USER_TAG = "[[USER]]"
_ARABIC_RE = re.compile(r"[0-9]")
_SINO_SMALL = "일이삼사오육\ub959칠팔구"
_SINO_SIZE = "십백천만억조"
_SINO_ALL = _SINO_SMALL + _SINO_SIZE
_SINO_ALL_SET = set(_SINO_ALL)
_SINO_SIZE_SET = set(_SINO_SIZE)
_ALLOWED_SUFFIX_RE = re.compile(
    r"(?:을|를|이|가|은|는|에|의|도|원|일|월|년|개월|번|차례|주)*"
)
_AMOUNT_RE = re.compile(
    r"(?:\d[\d,]*|[일이삼사오육\ub959칠팔구]*"
    r"[십백천만억조]"
    r"[일이삼사오육\ub959칠팔구십백천만억조]*)"
    r"\s*원"
)
_MONTH_RE = re.compile(r"[일이삼사오육유칠팔구십시]+월")
_DAY_RE = re.compile(r"[일이삼사오육\ub959칠팔구십]+일")
_YEAR_RE = re.compile(r"[일이삼사오육\ub959칠팔구십백천만억]+년")
_DOTTED_DATE_RE = re.compile(r"\d+\.\s*\d+\.\s*\d+\.?")
_RELATIVE_RE = re.compile(
    r"오늘|내일|모레|글피|어제|그제|그저께|엊그제|올해|작년|내년|이듬해"
    r"|(?:이번|다음|지난|다다음)\s?(?:주|달|해|날)"
    r"|(?:하루|이틀|사흘|나흘|닷새|열흘|보름|며칠|일주일|한\s?주|[한두세]\s?달)"
    r"\s?(?:뒤|후|안|내|만에)"
    r"|[월연주]말|[월연]초|[초중하]순|[월화수목금토일]요일"
)

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

_HONORIFICS = ("씨", "님", "군", "양", "모씨", "모 씨", "사장", "선생님", "대표")


def _strip_valid_slots_and_tags(text: str) -> str:
    no_slots = _SLOT_RE.sub(" ", text)
    no_ex = _EX_TAG_RE.sub(" ", no_slots)
    no_user = no_ex.replace(_USER_TAG, " ")
    return no_user


def _strip_slots_and_tags(text: str) -> str:
    return _strip_valid_slots_and_tags(text)


def _has_sino_numeral_word(outside: str) -> bool:
    for tok in re.findall(r"[가-힣]+", outside):
        if tok.startswith("만일") or tok.startswith("천천") or tok.startswith("만만"):
            continue
        i = 0
        while i < len(tok) and tok[i] in _SINO_ALL_SET:
            i += 1
        if i == 0:
            continue
        prefix = tok[:i]
        if not any(ch in _SINO_SIZE_SET for ch in prefix):
            continue
        rest = tok[i:]
        if rest == "" or _ALLOWED_SUFFIX_RE.fullmatch(rest) is not None:
            return True
    return False


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
    lowered_outside = text_outside.lower()
    for full in party_names:
        base = _base_name(normalize_text(full))
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
                if len(given) >= 2 and given and given in text_outside:
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
                    pat = re.compile(
                        r"(?<![가-힣])" + re.escape(family) + r"\s*" + re.escape(hon)
                    )
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
            base_low = base.lower()
            if base_low and base_low in lowered_outside:
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
                if len(part) >= 2 and part.lower() in lowered_outside:
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


def _quote_exhibit_no(middle: str) -> str:
    m = middle.strip()
    if m[:2].upper() == "EX" and len(m) > 2:
        return m[2:]
    return m


def check_g1a(
    draft: SlotDraft,
    allowed_slots: List[str],
    party_names: List[str],
    existing_exhibits: Optional[List[str]] = None,
) -> GateResult:
    findings: List[Finding] = []
    allowed = set(allowed_slots)
    existing = set(str(e) for e in (existing_exhibits or []))
    for s in draft.sentences:
        text = normalize_text(s.text_with_slots)
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
                elif existing:
                    parts = content.split(":")
                    if len(parts) == 3:
                        ex_no = _quote_exhibit_no(parts[1])
                        if ex_no not in existing:
                            findings.append(
                                Finding(
                                    sentence_id=s.sentence_id,
                                    field="text_with_slots",
                                    message=f"목록에 없는 호증의 인용입니다: {content}",
                                    fix_hint="호증 번호를 확인하세요.",
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
        tag_check = _SLOT_RE.sub(" ", text)
        tag_check = _EX_TAG_RE.sub(" ", tag_check)
        tag_check = tag_check.replace(_USER_TAG, " ")
        if "[[" in tag_check or "]]" in tag_check:
            findings.append(
                Finding(
                    sentence_id=s.sentence_id,
                    field="text_with_slots",
                    message="허용되지 않은 대괄호 태그가 있습니다.",
                    fix_hint="[[EX:번호]]와 [[USER]]만 쓰세요.",
                )
            )
        brace_check = _SLOT_RE.sub(" ", text)
        if "{" in brace_check or "}" in brace_check:
            findings.append(
                Finding(
                    sentence_id=s.sentence_id,
                    field="text_with_slots",
                    message="슬롯 밖에 중괄호가 있습니다.",
                    fix_hint="{{슬롯이름}} 형식을 확인하세요.",
                )
            )
        outside = _strip_valid_slots_and_tags(text)
        if _ARABIC_RE.search(outside):
            findings.append(
                Finding(
                    sentence_id=s.sentence_id,
                    field="text_with_slots",
                    message="슬롯 밖에 아라비아 숫자가 있습니다.",
                    fix_hint="숫자는 슬롯으로 넣으세요.",
                )
            )
        if _has_sino_numeral_word(outside):
            findings.append(
                Finding(
                    sentence_id=s.sentence_id,
                    field="text_with_slots",
                    message="슬롯 밖에 한글 수사가 있습니다.",
                    fix_hint="금액과 수량은 슬롯으로 넣으세요.",
                )
            )
        elif _AMOUNT_RE.search(outside):
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
        if _RELATIVE_RE.search(outside):
            mrel = _RELATIVE_RE.search(outside)
            rel = mrel.group(0) if mrel else ""
            findings.append(
                Finding(
                    sentence_id=s.sentence_id,
                    field="text_with_slots",
                    message=f"슬롯 밖에 상대 날짜가 있습니다: {rel}",
                    fix_hint="날짜는 슬롯으로 넣으세요.",
                )
            )
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


_LEADING_EX_RE = re.compile(r"^\s*((?:\[\[EX:[A-Za-z0-9]+\]\]\s*)+)")


def _split_fact_pieces(text: str) -> List[str]:
    raw = re.split(r"[.!?]+", text)
    filtered: List[str] = []
    for p in raw:
        if p.strip() == "" and "[[EX:" not in p:
            continue
        filtered.append(p)
    result: List[str] = []
    for p in filtered:
        no_tags = _EX_TAG_RE.sub(" ", p).replace(_USER_TAG, " ")
        if no_tags.strip() == "":
            if result:
                result[-1] = result[-1] + " " + p
            else:
                result.append(p)
            continue
        m = _LEADING_EX_RE.match(p)
        if m and result:
            leading = m.group(1)
            rest = p[m.end():]
            result[-1] = result[-1] + " " + leading
            if rest.strip() == "":
                continue
            result.append(rest)
        else:
            result.append(p)
    return result


def _piece_has_content(piece: str) -> bool:
    no_tags = _EX_TAG_RE.sub(" ", piece).replace(_USER_TAG, " ")
    return no_tags.strip() != ""


def check_g3(draft: SlotDraft, existing_exhibits: List[str]) -> GateResult:
    findings: List[Finding] = []
    existing = set(str(e) for e in existing_exhibits)
    for s in draft.sentences:
        text = normalize_text(s.text_with_slots)
        tags = _EX_TAG_RE.findall(text)
        tag_set = set(str(n) for n in tags)
        ref_set = set(str(r) for r in s.ex_refs)
        if s.type == "fact":
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
                pieces = _split_fact_pieces(text)
                for piece in pieces:
                    if not _piece_has_content(piece):
                        continue
                    if not _EX_TAG_RE.search(piece):
                        findings.append(
                            Finding(
                                sentence_id=s.sentence_id,
                                field="text_with_slots",
                                message="사실 문장의 일부에 근거 태그가 없습니다.",
                                fix_hint="문장마다 [[EX:번호]]를 넣으세요.",
                            )
                        )
                        break
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
            if tag_set != ref_set:
                findings.append(
                    Finding(
                        sentence_id=s.sentence_id,
                        field="ex_refs",
                        message="본문의 근거 태그와 ex_refs가 다릅니다.",
                        fix_hint="본문 태그와 ex_refs를 같게 하세요.",
                    )
                )
        else:
            if _USER_TAG not in text:
                findings.append(
                    Finding(
                        sentence_id=s.sentence_id,
                        field="text_with_slots",
                        message="사용자 진술 문장에 표시가 없습니다.",
                        fix_hint="[[USER]]를 넣으세요.",
                    )
                )
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
            if tag_set != ref_set:
                findings.append(
                    Finding(
                        sentence_id=s.sentence_id,
                        field="ex_refs",
                        message="본문의 근거 태그와 ex_refs가 다릅니다.",
                        fix_hint="본문 태그와 ex_refs를 같게 하세요.",
                    )
                )
    status: Literal["pass", "fail"] = "fail" if findings else "pass"
    return GateResult(gate="G3", status=status, findings=findings)


def _hangul_jong(code_ch: str) -> Optional[int]:
    o = ord(code_ch)
    if 0xAC00 <= o <= 0xD7A3:
        return (o - 0xAC00) % 28
    return None


def _value_ending(value: str) -> Optional[tuple]:
    v = value.strip()
    if v.endswith(")"):
        idx = v.rfind("(")
        if idx != -1:
            v = v[:idx].strip()
    for ch in reversed(v):
        jong = _hangul_jong(ch)
        if jong is not None:
            return ("hangul", jong != 0, jong == 8)
    for ch in reversed(v):
        if "0" <= ch <= "9":
            d = ord(ch) - ord("0")
            has = d in (0, 1, 3, 6, 7, 8)
            rieul = d in (1, 7, 8)
            return ("digit", has, rieul)
    return None


def _is_hangul(ch: str) -> bool:
    return "가" <= ch <= "힣"


def _detect_trailing_particle(after: str) -> Optional[str]:
    if after.startswith("이에요") or after.startswith("예요"):
        return None
    if after.startswith("으로"):
        nxt = after[2:3]
        if nxt == "" or not _is_hangul(nxt):
            return "으로"
        return None
    if not after:
        return None
    c0 = after[0]
    if c0 in ("은", "는", "이", "가", "을", "를", "과", "와", "로"):
        nxt = after[1:2]
        if nxt == "" or not _is_hangul(nxt):
            return c0
    return None


def _correct_particle(orig: str, ending: Optional[tuple]) -> Optional[str]:
    if ending is None:
        return None
    _, has, rieul = ending
    if orig in ("은", "는"):
        return "은" if has else "는"
    if orig in ("이", "가"):
        return "이" if has else "가"
    if orig in ("을", "를"):
        return "을" if has else "를"
    if orig in ("과", "와"):
        return "과" if has else "와"
    if orig in ("으로", "로"):
        return "으로" if (has and not rieul) else "로"
    return None


def substitute_text(
    text: str, values: Dict[str, str], quotes: Optional[Dict[str, str]] = None
) -> str:
    quotes = quotes or {}
    out_parts: List[str] = []
    last_end = 0
    for m in _SLOT_RE.finditer(text):
        content = m.group(1).strip()
        is_quote = content.startswith("quote:")
        if is_quote:
            if content in quotes:
                repl = quotes[content]
            else:
                short = content[len("quote:"):]
                if short in quotes:
                    repl = quotes[short]
                else:
                    raise ValueError(f"인용 원문이 없습니다: {content}")
        else:
            if content in values:
                repl = str(values[content])
            else:
                raise ValueError(f"확인값이 없습니다: {content}")
        out_parts.append(text[last_end:m.start()])
        out_parts.append(repl)
        if not is_quote:
            after = text[m.end():]
            orig_particle = _detect_trailing_particle(after)
            if orig_particle is not None:
                ending = _value_ending(repl)
                fixed = _correct_particle(orig_particle, ending)
                if fixed is not None:
                    out_parts.append(fixed)
                    last_end = m.end() + len(orig_particle)
                    continue
        last_end = m.end()
    out_parts.append(text[last_end:])
    out = "".join(out_parts)
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
