"""Adapter to M0-fix2 / M1 / M1-fix1 outputs (M2a task 1).

Everything the case flow needs from ``backend/app/meta`` and
``backend/app/services`` is imported here, and only here. Name or shape
differences between the case API contract and those modules are adapted in
this file (see ``ex_to_num`` and the ``*_case`` gate wrappers). The service
and meta packages themselves are never modified by M2a.
"""

from __future__ import annotations

import os
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

# --- M1-fix1: draft gates (G1a, G3, slots, substitution) ---------------------
from app.services.draft_gates import (
    KR_SLOTS,
    Finding,
    GateResult,
    SlotDraft,
    SlotSentence,
    check_g1a,
    check_g3,
    substitute_text,
)
# --- M1-fix1: naming checks ---------------------------------------------------
from app.services.naming import (
    DISCLAIMER_EN,
    DISCLAIMER_KO,
    NOTICE_EN,
    NOTICE_KO,
    check_draft as check_naming_draft,
    check_text as check_naming_text,
    find_forbidden as find_forbidden_doc,
    find_forbidden_draft,
)
# --- M1(-fix1): calculation + verification ------------------------------------
from app.services.verification_gate import (
    VerificationGateService,
    calculate_kr,
)
# --- M1-fix1: document generation (fact_sentences supported, K10) -------------
from app.services.pdf_compiler import KoreanLegalDocumentCompiler
# --- M0-fix2: Meta client, budget errors, cost helpers ------------------------
from app.meta.client import (
    BudgetError,
    BudgetExceeded,
    BudgetLedgerError,
    ContributorModelError,
    FixtureNotFound,
    IncompleteResponse,
    MetaClient,
    MissingKeyError,
    estimate_cost_from_body,
    extract_output_text,
    extract_usage,
    ledger_summary,
    request_hash,
)
from app.meta.coords import Box, box_to_pixels
# --- Schemas ------------------------------------------------------------------
from app.schemas.loan_fact import (
    CurrencyEnum,
    EvidenceItem,
    EvidenceTypeEnum,
    GeneratedClaimDraft,
    LoanFactSchema,
    PartyInfo,
    RepaymentRecord,
    TransactionKindEnum,
)

__all__ = [
    "KR_SLOTS", "Finding", "GateResult", "SlotDraft", "SlotSentence",
    "check_g1a", "check_g3", "substitute_text",
    "DISCLAIMER_EN", "DISCLAIMER_KO", "NOTICE_EN", "NOTICE_KO",
    "check_naming_draft", "check_naming_text",
    "find_forbidden_doc", "find_forbidden_draft",
    "VerificationGateService", "calculate_kr",
    "KoreanLegalDocumentCompiler",
    "BudgetError", "BudgetExceeded", "BudgetLedgerError",
    "ContributorModelError", "FixtureNotFound", "IncompleteResponse",
    "MetaClient", "MissingKeyError",
    "estimate_cost_from_body", "extract_output_text", "extract_usage",
    "ledger_summary", "request_hash",
    "Box", "box_to_pixels",
    "CurrencyEnum", "EvidenceItem", "EvidenceTypeEnum", "GeneratedClaimDraft",
    "LoanFactSchema", "PartyInfo", "RepaymentRecord", "TransactionKindEnum",
    "ex_to_num", "num_to_ex", "ex_num",
    "check_g1a_case", "check_g3_case", "check_naming_case",
    "fmt_amount_won", "fmt_kr_date", "fmt_rate_pct",
    "ex_tag_to_label", "render_sentence",
    "build_slot_values", "available_slots", "build_quotes",
    "build_loan_fact", "synthetic_claim_draft",
    "calculation_to_json",
    "READER_MODEL", "reader_concurrency", "meta_mode",
]


# --- settings -----------------------------------------------------------------
def meta_mode() -> str:
    """Current Meta mode (live|record|replay, default replay)."""
    return (os.environ.get("META_MODE") or "replay").strip().lower() or "replay"


READER_MODEL = (os.environ.get("READER_MODEL") or "muse-spark-1.3").strip()


def reader_concurrency() -> int:
    """Max parallel reading workers (default 4; record run uses 1)."""
    try:
        value = int((os.environ.get("READER_CONCURRENCY") or "4").strip())
    except ValueError:
        return 4
    return value if value >= 1 else 1


# --- exhibit number translation -----------------------------------------------
# The case API contract uses "EX4" style ids in ex_refs, while M1's
# check_g1a/check_g3 (and their tests) use bare numbers ("4") in ex_refs
# and existing_exhibits, and [[EX:4]] tags. Translate at the boundary.
_EX_RE = re.compile(r"^EX(\d+)$", re.IGNORECASE)


def ex_to_num(ex_id: str) -> str:
    """'EX4' -> '4' (bare numbers are passed through)."""
    match = _EX_RE.match(str(ex_id).strip())
    return match.group(1) if match else str(ex_id).strip()


def num_to_ex(num: str) -> str:
    """'4' -> 'EX4' ('EX4' is passed through)."""
    text = str(num).strip()
    return text if _EX_RE.match(text) else f"EX{text}"


def ex_num(ex_id: str) -> int:
    """Numeric part of an ex_id for ordering ('EX4' -> 4)."""
    try:
        return int(ex_to_num(ex_id))
    except ValueError:
        return 10**9


def check_g1a_case(
    sentences: List[Dict[str, Any]],
    allowed_slots: List[str],
    party_names: List[str],
    existing_ex_ids: List[str],
) -> GateResult:
    """G1a with contract-style ex ids (translated to bare numbers)."""
    draft = SlotDraft(
        lang="ko",
        sentences=[
            SlotSentence(
                sentence_id=s["sentence_id"],
                type=s.get("type", "fact"),
                text_with_slots=s.get("text_with_slots", ""),
                ex_refs=[ex_to_num(r) for r in s.get("ex_refs", [])],
            )
            for s in sentences
        ],
    )
    return check_g1a(
        draft,
        list(allowed_slots),
        list(party_names),
        existing_exhibits=[ex_to_num(e) for e in existing_ex_ids],
    )


def check_g3_case(
    sentences: List[Dict[str, Any]],
    existing_ex_ids: List[str],
) -> GateResult:
    """G3 with contract-style ex ids (translated to bare numbers)."""
    draft = SlotDraft(
        lang="ko",
        sentences=[
            SlotSentence(
                sentence_id=s["sentence_id"],
                type=s.get("type", "fact"),
                text_with_slots=s.get("text_with_slots", ""),
                ex_refs=[ex_to_num(r) for r in s.get("ex_refs", [])],
            )
            for s in sentences
        ],
    )
    return check_g3(draft, [ex_to_num(e) for e in existing_ex_ids])


def check_naming_case(sentences: List[Dict[str, Any]]) -> GateResult:
    """Naming gate (draft patterns) on contract-style sentences."""
    draft = SlotDraft(
        lang="ko",
        sentences=[
            SlotSentence(
                sentence_id=s["sentence_id"],
                type=s.get("type", "fact"),
                text_with_slots=s.get("text_with_slots", ""),
                ex_refs=list(s.get("ex_refs", [])),
            )
            for s in sentences
        ],
    )
    return check_naming_draft(draft)


# --- display formatting (contract 1장) -----------------------------------------
def fmt_amount_won(amount: Any) -> str:
    """'5000000' -> '5,000,000원'."""
    text = str(amount).strip().replace(",", "").replace("원", "")
    try:
        number = int(Decimal(text))
    except (InvalidOperation, ValueError):
        return f"{amount}원"
    return f"{number:,}원"


def fmt_kr_date(iso: Any) -> str:
    """'2026-03-10' -> '2026. 3. 10.'."""
    try:
        year, month, day = str(iso).strip().split("-")
        return f"{int(year)}. {int(month)}. {int(day)}."
    except (ValueError, AttributeError):
        return str(iso)


def fmt_rate_pct(rate: Any) -> str:
    """'5' / '5.0' -> '5%'."""
    try:
        normalized = Decimal(str(rate).strip())
    except (InvalidOperation, ValueError):
        return str(rate)
    text = format(normalized.normalize(), "f")
    return f"{text}%"


_EX_TAG_RE = re.compile(r"\[\[EX:([A-Za-z0-9]+)\]\]")


def ex_tag_to_label(text: str) -> str:
    """'[[EX:4]]' -> '[갑 제4호증]', '[[USER]]' -> '(사용자 진술)'."""
    def _one(match: re.Match) -> str:
        return f"[갑 제{ex_to_num(match.group(1))}호증]"
    return _EX_TAG_RE.sub(_one, text).replace("[[USER]]", "(사용자 진술)")


def render_sentence(
    text_with_slots: str,
    values: Dict[str, str],
    quotes: Dict[str, str],
) -> str:
    """Substitute slots+quotes (M1 josa fitting) then convert cite tags."""
    return ex_tag_to_label(substitute_text(text_with_slots, values, quotes))


# --- slot values ----------------------------------------------------------------
def _first_repayment(fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    repayments = fields.get("repayments") or []
    if isinstance(repayments, list) and repayments:
        first = repayments[0]
        if isinstance(first, dict):
            return first
    return None


def build_slot_values(
    confirmed_fields: Dict[str, Any],
    calculation: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Display strings for every KR slot that has a value.

    Slots without a value are omitted (see :func:`available_slots`); the
    drafter is only allowed to use available slots so rendering never
    leaves an empty hole.
    """
    fields = confirmed_fields or {}
    calc = calculation or {}
    values: Dict[str, str] = {}
    for key in (
        "creditor_name", "debtor_name", "creditor_phone", "debtor_phone",
        "creditor_address", "debtor_address",
    ):
        raw = fields.get(key)
        if raw is not None and str(raw).strip():
            values[key] = str(raw).strip()
    for key in ("principal", "repaid_amount"):
        raw = fields.get(key) if key == "principal" else None
        if key == "repaid_amount":
            first = _first_repayment(fields)
            raw = first.get("amount") if first else None
        if raw is not None and str(raw).strip():
            values[key] = fmt_amount_won(raw)
    for key in ("loan_date", "due_date", "repaid_date"):
        raw = fields.get(key) if key != "repaid_date" else None
        if key == "repaid_date":
            first = _first_repayment(fields)
            raw = first.get("date") if first else None
        if raw is not None and str(raw).strip():
            values[key] = fmt_kr_date(raw)
    if calc:
        remaining = calc.get("remaining_principal")
        if remaining is not None and str(remaining).strip():
            values["remaining_principal"] = fmt_amount_won(remaining)
        accrual = calc.get("accrual_start_date")
        if accrual is not None and str(accrual).strip():
            values["accrual_start_date"] = fmt_kr_date(accrual)
        ref_total = (calc.get("reference_total") or {}).get("amount")
        if ref_total is not None and str(ref_total).strip():
            values["total_claim_amount"] = fmt_amount_won(ref_total)
        accrued = calc.get("accrued_interest")
        if accrued is not None and str(accrued).strip():
            values["calculated_interest"] = fmt_amount_won(accrued)
        rate_clause = calc.get("rate_clause") or {}
        pre = rate_clause.get("pre_service_rate")
        post = rate_clause.get("post_service_rate")
        if pre is not None and str(pre).strip():
            values["delay_rate"] = fmt_rate_pct(pre)
            values["contract_interest"] = fmt_rate_pct(pre)
        if post is not None and str(post).strip():
            values["delay_rate"] = fmt_rate_pct(post)
    agreed = fields.get("interest_rate")
    if agreed is not None and str(agreed).strip():
        values["agreed_rate"] = fmt_rate_pct(agreed)
    # demand_date has no confirmed source in M2: omitted unless provided.
    demand = fields.get("demand_date")
    if demand is not None and str(demand).strip():
        values["demand_date"] = fmt_kr_date(demand)
    return values


def available_slots(values: Dict[str, str]) -> List[str]:
    """KR slots (in KR_SLOTS order) that have a non-empty value."""
    return [slot for slot in KR_SLOTS if values.get(slot)]


def build_quotes(readings: List[Dict[str, Any]]) -> Dict[str, str]:
    """Quote lookup: 'quote:EX1:item4' -> '"verbatim"' (with quotes)."""
    quotes: Dict[str, str] = {}
    for reading in readings or []:
        ex_id = reading.get("ex_id", "")
        for item in reading.get("items", []) or []:
            item_id = item.get("item_id", "")
            verbatim = item.get("text_verbatim", "")
            if ex_id and item_id:
                quotes[f"quote:{ex_id}:{item_id}"] = f'"{verbatim}"'
    return quotes


# --- LoanFact builder (contract 5장 Review -> LoanFactSchema) ----------------------
_ROLE_TO_TYPE = {
    "loan_transfer": EvidenceTypeEnum.TRANSFER_RECEIPT,
    "repayment": EvidenceTypeEnum.TRANSFER_RECEIPT,
}


def _evidence_type_for(filename: str, kind: str, role: Optional[str]) -> EvidenceTypeEnum:
    if role in _ROLE_TO_TYPE:
        return _ROLE_TO_TYPE[role]
    name = (filename or "").lower()
    if "iou" in name or "promissory" in name or "차용" in name:
        return EvidenceTypeEnum.LOAN_AGREEMENT
    if kind == "pdf":
        return EvidenceTypeEnum.LOAN_AGREEMENT
    if "transfer" in name or "wire" in name or "receipt" in name or "이체" in name:
        return EvidenceTypeEnum.TRANSFER_RECEIPT
    return EvidenceTypeEnum.MESSENGER_CHAT


_TYPE_TO_TITLE = {
    EvidenceTypeEnum.TRANSFER_RECEIPT: "이체확인증",
    EvidenceTypeEnum.MESSENGER_CHAT: "대화 캡처",
    EvidenceTypeEnum.LOAN_AGREEMENT: "차용증",
    EvidenceTypeEnum.DEMAND_NOTICE: "독촉장",
}


def build_loan_fact(
    confirmed_fields: Dict[str, Any],
    evidence_roles: Dict[str, str],
    evidence: List[Dict[str, Any]],
) -> LoanFactSchema:
    """Confirmed facts + case evidence -> LoanFactSchema (KR)."""
    fields = confirmed_fields or {}
    roles = evidence_roles or {}

    def _amount(raw: Any) -> Decimal:
        return Decimal(str(raw).strip().replace(",", "").replace("원", ""))

    repayments: List[RepaymentRecord] = []
    for entry in fields.get("repayments") or []:
        if not isinstance(entry, dict):
            continue
        repayments.append(
            RepaymentRecord(
                payment_date=date.fromisoformat(str(entry["date"]).strip()),
                amount=_amount(entry["amount"]),
            )
        )
    agreed_raw = fields.get("interest_rate")
    agreed = None
    if agreed_raw is not None and str(agreed_raw).strip():
        agreed = Decimal(str(agreed_raw).strip().rstrip("%"))
    kind_raw = str(fields.get("transaction_kind") or "civil").strip().lower()
    transaction_kind = (
        TransactionKindEnum.COMMERCIAL if kind_raw == "commercial"
        else TransactionKindEnum.CIVIL
    )
    items: List[EvidenceItem] = []
    for record in evidence or []:
        ex_id = str(record.get("ex_id", ""))
        role = roles.get(ex_id)
        evidence_type = _evidence_type_for(
            str(record.get("filename", "")), str(record.get("kind", "")), role
        )
        items.append(
            EvidenceItem(
                id=str(record.get("label", ex_id)),
                title=_TYPE_TO_TITLE[evidence_type],
                evidence_type=evidence_type,
                sha256_hash=str(record.get("sha256", "")),
                source_filename=str(record.get("filename", "")),
                role=role if role in ("loan_transfer", "repayment", "other") else None,
            )
        )
    creditor_phone = fields.get("creditor_phone")
    debtor_phone = fields.get("debtor_phone")
    return LoanFactSchema(
        creditor=PartyInfo(
            name=str(fields.get("creditor_name", "") or ""),
            phone=str(creditor_phone).strip() if creditor_phone else None,
            address=str(fields.get("creditor_address", "") or "") or None,
        ),
        debtor=PartyInfo(
            name=str(fields.get("debtor_name", "") or ""),
            phone=str(debtor_phone).strip() if debtor_phone else None,
            address=str(fields.get("debtor_address", "") or "") or None,
        ),
        currency=CurrencyEnum.KRW,
        transaction_kind=transaction_kind,
        principal_amount=_amount(fields.get("principal", "0")),
        loan_date=date.fromisoformat(str(fields.get("loan_date")).strip()),
        due_date=date.fromisoformat(str(fields.get("due_date")).strip()),
        agreed_interest_rate=agreed,
        repayments=repayments,
        evidences=items,
    )


def synthetic_claim_draft(
    loan_fact: LoanFactSchema,
    remaining_principal: Decimal,
) -> GeneratedClaimDraft:
    """Claim draft that cites every evidence (for G2/G4 checks).

    The calculating step has no user draft yet, so citation and amount
    agreement (R4) are satisfied by construction; only genuine missing
    requirements (G2) and limits (G4) remain.
    """
    ids = [item.id for item in loan_fact.evidences]
    statement = " ".join(f"[{item_id}]" for item_id in ids) or "증거 없음"
    return GeneratedClaimDraft(
        jurisdiction="KR",
        claim_amount_claimed=remaining_principal,
        statement_of_facts=statement,
        cited_evidence_ids=list(ids),
        calculation_summary="사건 API 계산 단계의 내부 확인용 초안",
    )


def calculation_to_json(calculation: Any) -> Dict[str, Any]:
    """M1 Calculation -> JSON-able dict (Decimals as strings)."""
    if hasattr(calculation, "model_dump"):
        return calculation.model_dump(mode="json")
    raise TypeError(f"not a Calculation: {type(calculation)!r}")
