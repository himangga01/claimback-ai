"""G1b final value check (M5, rule-based, M5-fix1 per-doc).

Extracts amounts, dates, and names from the finished documents (content
proof PDF, exhibit bundle PDF, evidence list PDF, ecourt clipboard text)
and compares them against the user-confirmed values and the calculated
values. In-sentence numbers are normalized (``4,014,383원`` ->
``4014383``, ``2026. 5. 2.`` -> ``2026-05-02``).

M5-fix1 (K1/K2/K4):
- Per-document required table (DOC_REQUIRED_*): each expected field lists
  which docs must contain it. A value missing in any required doc fails,
  even when another doc still has the right value.
- Extra detection: amounts/dates in a doc that are not in expected
  (plus the allowlist, e.g. content-proof deadline as_of+7) fail.
- Expected amounts use only values actually rendered (K2): intermediate
  ``remaining_principal_after`` values are not required, only the last
  one (which equals ``remaining_principal``); overpayment is required
  when > 0.
- Leak patterns cover 10-14 digit accounts, spaced/en-dash forms, and
  whitespace-split numbers (second pass on whitespace-removed text).
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple, Union

from pypdf import PdfReader

from app.services.draft_gates import Finding, GateResult
from app.services.naming import find_forbidden

_AMOUNT_COMMA_RE = re.compile(r"(\d{1,3}(?:,\d{3})+)\s*원?")
_AMOUNT_WON_RE = re.compile(r"(\d{4,})\s*원")
_DATE_DOT_RE = re.compile(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.")
_DATE_ISO_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_DATE_KO_RE = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")

# Full account / resident numbers (P0 leak rule; phones are excluded by caller).
# K4: 10-14 digits, spaced groups, hyphen/en-dash/em-dash variants.
_DASH = r"[-\u2013\u2014\u2212]"
_LEAK_RESIDENT = re.compile(rf"\d{{6}}{_DASH}\d{{7}}")
_LEAK_RESIDENT_SPACE = re.compile(r"(?<!\d)\d{6}[ \t]+\d{7}(?!\d)")
_LEAK_ACCOUNT_DASH = re.compile(rf"\d{{2,6}}{_DASH}\d{{2,6}}{_DASH}\d{{4,}}")
_LEAK_ACCOUNT_SPACE = re.compile(r"(?<!\d)(?:\d{2,6}[ \t]+){2}\d{4,}(?!\d)")
_LEAK_PLAIN = re.compile(r"(?<!\d)\d{10,14}(?!\d)")
LEAK_PATTERNS = (
    _LEAK_RESIDENT,
    _LEAK_RESIDENT_SPACE,
    _LEAK_ACCOUNT_DASH,
    _LEAK_ACCOUNT_SPACE,
    _LEAK_PLAIN,
)


def find_sensitive_numbers(
    text: str, exclude: Any = None,
) -> List[str]:
    """Account/resident-number hits, ignoring ``exclude`` substrings (phones).

    Runs a second pass on whitespace-removed text so numbers split by
    newlines/spaces (e.g. ``123-\\n456789-01234``) are still caught.
    """
    blob = str(text or "")
    blob = re.sub(r"D:\d{14}", " ", blob)  # PDF metadata timestamps, not accounts
    if exclude:
        items = list(exclude) if isinstance(exclude, (list, tuple, set)) else [exclude]
        for item in items:
            needle = str(item or "").strip()
            if needle:
                blob = blob.replace(needle, " ")
    hits: List[str] = []
    for pattern in LEAK_PATTERNS:
        hits.extend(match.group(0) for match in pattern.finditer(blob))
    nospace = re.sub(r"\s+", "", blob)
    if nospace and nospace != blob:
        for pattern in LEAK_PATTERNS:
            for match in pattern.finditer(nospace):
                candidate = match.group(0)
                if candidate and candidate not in hits:
                    # Avoid flagging plain date fragments: the plain-digit
                    # pattern on nospace text could join unrelated short
                    # runs only when separators are whitespace. Commas,
                    # dots, and dashes still break the run, so normal
                    # amounts/dates (5,000,000 / 2026. 5. 1.) stay safe.
                    hits.append(candidate)
    return hits


def extract_pdf_text(pdf_path: Union[str, Path]) -> str:
    """Concatenated page text of a generated PDF ("" when unreadable)."""
    try:
        reader = PdfReader(str(pdf_path))
    except Exception:
        return ""
    parts: List[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    return "\n".join(parts)


def extract_pdf_metadata_text(pdf_path: Union[str, Path]) -> str:
    """Joined metadata values of a PDF ("" when unreadable)."""
    try:
        reader = PdfReader(str(pdf_path))
    except Exception:
        return ""
    try:
        metadata = reader.metadata
    except Exception:
        return ""
    if not metadata:
        return ""
    values: List[str] = []
    for value in metadata.values():
        if value is not None:
            values.append(str(value))
    return "\n".join(values)


def extract_amounts(text: str) -> set:
    """Normalized integer amounts (comma or 원 forms only)."""
    found: set = set()
    for match in _AMOUNT_COMMA_RE.finditer(text or ""):
        try:
            found.add(int(match.group(1).replace(",", "")))
        except ValueError:
            continue
    for match in _AMOUNT_WON_RE.finditer(text or ""):
        try:
            found.add(int(match.group(1)))
        except ValueError:
            continue
    return found


def _iso(year: str, month: str, day: str) -> str:
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def extract_dates(text: str) -> set:
    """Normalized ISO dates (year forms only; bare month-day ignored)."""
    found: set = set()
    blob = text or ""
    for pattern in (_DATE_DOT_RE, _DATE_ISO_RE, _DATE_KO_RE):
        for match in pattern.finditer(blob):
            try:
                found.add(_iso(*match.groups()))
            except ValueError:
                continue
    return found


def _amount_value(raw: Any) -> Union[int, None]:
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "").replace("원", "")
    if not text:
        return None
    try:
        return int(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


def build_expected_amounts(
    fields: Mapping[str, Any],
    calculation: Mapping[str, Any],
) -> Dict[str, int]:
    """Expected amounts from confirmed fields + calculation (zeros skipped).

    K2: only values actually rendered. Intermediate
    ``remaining_principal_after`` values are not required (the wording
    shows only the last remaining); overpayment is required when > 0.
    """
    expected: Dict[str, int] = {}
    fields = fields or {}
    calculation = calculation or {}

    def _put(name: str, raw: Any) -> None:
        value = _amount_value(raw)
        if value is not None and value > 0:
            expected[name] = value

    _put("principal", fields.get("principal"))
    repayments = fields.get("repayments", []) or []
    if isinstance(repayments, list):
        for index, entry in enumerate(repayments):
            if isinstance(entry, dict):
                _put(f"repayments[{index}].amount", entry.get("amount"))
    _put("remaining_principal", calculation.get("remaining_principal"))
    allocations = calculation.get("allocations", []) or []
    if isinstance(allocations, list):
        entries = [e for e in allocations if isinstance(e, dict)]
        for index, entry in enumerate(entries):
            _put(f"allocations[{index}].payment_amount", entry.get("payment_amount"))
            _put(f"allocations[{index}].applied_to_cost", entry.get("applied_to_cost"))
            _put(
                f"allocations[{index}].applied_to_interest",
                entry.get("applied_to_interest"),
            )
            _put(
                f"allocations[{index}].applied_to_principal",
                entry.get("applied_to_principal"),
            )
            # K2: only the last remaining_after is rendered ("남은 원금은 …").
            if index == len(entries) - 1:
                _put(
                    f"allocations[{index}].remaining_principal_after",
                    entry.get("remaining_principal_after"),
                )
    _put("accrued_interest", calculation.get("accrued_interest"))
    reference = calculation.get("reference_total", {}) or {}
    if isinstance(reference, dict):
        _put("reference_total.amount", reference.get("amount"))
    _put("overpayment_amount", calculation.get("overpayment_amount"))
    return expected


def _parse_iso_day(raw: Any) -> Union[date, None]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _plus_one_iso(day: date) -> str:
    return (day + timedelta(days=1)).isoformat()


def _agreed_active(fields: Mapping[str, Any]) -> bool:
    raw = (fields or {}).get("interest_rate")
    if raw is None:
        return False
    text = str(raw).strip().rstrip("%")
    if not text:
        return False
    try:
        return Decimal(text) != 0
    except (InvalidOperation, ValueError):
        return False


def build_expected_dates(
    fields: Mapping[str, Any],
    calculation: Mapping[str, Any],
    as_of: Any = None,
) -> Dict[str, str]:
    """Expected ISO dates from confirmed fields + calculation + as_of.

    K1/K7: allocation interest-period starts (agreed/delay) are expected
    because the repayment wording prints them. Only periods with actual
    interest (applied_to_interest > 0) are required.
    """
    expected: Dict[str, str] = {}

    def _put(name: str, raw: Any) -> None:
        text = str(raw or "").strip()
        if text:
            expected[name] = text

    fields = fields or {}
    calculation = calculation or {}
    _put("loan_date", fields.get("loan_date"))
    _put("due_date", fields.get("due_date"))
    demand = fields.get("demand_date")
    if demand:
        _put("demand_date", demand)
    repayments = fields.get("repayments", []) or []
    if isinstance(repayments, list):
        for index, entry in enumerate(repayments):
            if isinstance(entry, dict) and entry.get("date"):
                _put(f"repayments[{index}].date", entry.get("date"))
    accrual = calculation.get("accrual_start_date")
    if accrual:
        # calculation_to_json gives ISO strings; Calculation objects give dates.
        if hasattr(accrual, "isoformat"):
            try:
                _put("accrual_start_date", accrual.isoformat())
            except Exception:
                _put("accrual_start_date", accrual)
        else:
            _put("accrual_start_date", accrual)
    if as_of:
        if hasattr(as_of, "isoformat"):
            try:
                _put("as_of", as_of.isoformat())
            except Exception:
                _put("as_of", as_of)
        else:
            _put("as_of", as_of)

    # Interest-period starts per allocation (K7 wording prints them).
    loan_day = _parse_iso_day(fields.get("loan_date"))
    due_day = _parse_iso_day(fields.get("due_date"))
    agreed = _agreed_active(fields)
    allocations = calculation.get("allocations", []) or []
    if isinstance(allocations, list):
        prev_day: Union[date, None] = loan_day
        for index, entry in enumerate(allocations):
            if not isinstance(entry, dict):
                continue
            pay_day = _parse_iso_day(entry.get("payment_date"))
            interest = _amount_value(entry.get("applied_to_interest")) or 0
            if pay_day is None or prev_day is None or interest <= 0:
                if pay_day is not None:
                    prev_day = pay_day
                continue
            starts: List[str] = []
            # Agreed part: max(prev, loan) .. min(payment, due).
            if agreed and due_day is not None and loan_day is not None:
                o_start = max(prev_day, loan_day)
                o_end = min(pay_day, due_day)
                if o_end > o_start:
                    starts.append(_plus_one_iso(o_start))
            # Delay part: max(prev, due) .. payment.
            if due_day is not None:
                d_start = max(prev_day, due_day)
                if pay_day > d_start:
                    starts.append(_plus_one_iso(d_start))
            elif pay_day > prev_day:
                starts.append(_plus_one_iso(prev_day))
            for pos, start_iso in enumerate(starts):
                if len(starts) == 1:
                    _put(f"allocations[{index}].interest_period_start", start_iso)
                else:
                    _put(
                        f"allocations[{index}].interest_period_start_{pos}",
                        start_iso,
                    )
            prev_day = pay_day
    return expected


def build_expected_names(fields: Mapping[str, Any]) -> Dict[str, str]:
    expected: Dict[str, str] = {}
    for name in ("creditor_name", "debtor_name"):
        value = str((fields or {}).get(name, "") or "").strip()
        if value:
            expected[name] = value
    return expected


# --- K1 per-document required table -------------------------------------------
# Doc keys match packager.build_package: content_proof.pdf, exhibits.pdf,
# evidence_list.pdf, ecourt (claim_purpose + claim_cause_payment_order).
CONTENT_DOC = "content_proof.pdf"
EXHIBITS_DOC = "exhibits.pdf"
EVIDENCE_LIST_DOC = "evidence_list.pdf"
ECOURT_DOC = "ecourt"

# Amount fields required per doc (prefix match; [n] indices expand).
_AMOUNT_DOCS: List[Tuple[str, Tuple[str, ...]]] = [
    ("principal", (CONTENT_DOC, ECOURT_DOC, EVIDENCE_LIST_DOC)),
    ("repayments[", (CONTENT_DOC, ECOURT_DOC, EVIDENCE_LIST_DOC)),
    ("remaining_principal", (CONTENT_DOC, ECOURT_DOC)),
    ("allocations[", (CONTENT_DOC, ECOURT_DOC)),  # payment/interest/principal
    ("accrued_interest", (CONTENT_DOC,)),
    ("reference_total.amount", (CONTENT_DOC,)),
    ("overpayment_amount", (CONTENT_DOC, ECOURT_DOC)),
]

_DATE_DOCS: List[Tuple[str, Tuple[str, ...]]] = [
    ("loan_date", (CONTENT_DOC, ECOURT_DOC, EVIDENCE_LIST_DOC)),
    ("due_date", (CONTENT_DOC, ECOURT_DOC)),
    ("demand_date", (ECOURT_DOC,)),
    ("repayments[", (CONTENT_DOC, ECOURT_DOC, EVIDENCE_LIST_DOC)),
    ("accrual_start_date", (ECOURT_DOC,)),
    ("as_of", (CONTENT_DOC,)),
    ("allocations[", (CONTENT_DOC, ECOURT_DOC)),  # interest_period_start
]

_NAME_DOCS: List[Tuple[str, Tuple[str, ...]]] = [
    ("creditor_name", (CONTENT_DOC, EVIDENCE_LIST_DOC)),
    ("debtor_name", (CONTENT_DOC, EVIDENCE_LIST_DOC)),
]


def _required_docs(field: str, table: List[Tuple[str, Tuple[str, ...]]]) -> Tuple[str, ...]:
    for prefix, docs in table:
        if prefix.endswith("["):
            if field.startswith(prefix):
                return docs
        elif field == prefix:
            return docs
    return ()


def required_docs_for(field: str) -> Tuple[str, ...]:
    """Docs that must contain ``field`` (K1 table; empty = nowhere required)."""
    for table in (_AMOUNT_DOCS, _DATE_DOCS, _NAME_DOCS):
        docs = _required_docs(field, table)
        if docs:
            return docs
    return ()


def _allowlisted_dates(expected_dates: Mapping[str, str]) -> set:
    """Fixed dates that may appear without being expected (deadline)."""
    allowed: set = set()
    raw = (expected_dates or {}).get("as_of")
    day = _parse_iso_day(raw)
    if day is not None:
        allowed.add((day + timedelta(days=7)).isoformat())
    return allowed


def check_g1b(
    expected_amounts: Mapping[str, int],
    expected_dates: Mapping[str, str],
    expected_names: Mapping[str, str],
    docs: Mapping[str, str],
) -> GateResult:
    """Per-document G1b: missing required values + extra values + naming.

    For backward compatibility the missing message still names the whole
    doc set (old tests assert that) and then the specific missing docs.
    """
    findings: List[Finding] = []
    texts = {str(name): str(text or "") for name, text in (docs or {}).items()}
    doc_names = ", ".join(texts) if texts else "(서류 없음)"
    combined = "\n".join(texts.values())

    per_doc_amounts = {name: extract_amounts(text) for name, text in texts.items()}
    per_doc_dates = {name: extract_dates(text) for name, text in texts.items()}

    # --- missing (per-doc) ---
    for field, value in (expected_amounts or {}).items():
        required = _required_docs(str(field), _AMOUNT_DOCS)
        if not required:
            # Unknown field: fall back to combined presence (old behavior).
            if int(value) not in extract_amounts(combined):
                findings.append(Finding(
                    sentence_id="",
                    field=str(field),
                    message=(
                        f"서류({doc_names})에서 {field} 금액 "
                        f"{int(value):,}원을 찾을 수 없습니다."
                    ),
                    fix_hint="편철 출력을 확인하세요.",
                ))
            continue
        missing = [
            doc for doc in required
            if int(value) not in per_doc_amounts.get(doc, set())
        ]
        if missing:
            findings.append(Finding(
                sentence_id="",
                field=str(field),
                message=(
                    f"서류({doc_names})에서 {field} 금액 "
                    f"{int(value):,}원을 찾을 수 없습니다 "
                    f"(없는 서류: {', '.join(missing)})."
                ),
                fix_hint="편철 출력을 확인하세요.",
            ))
    for field, value in (expected_dates or {}).items():
        required = _required_docs(str(field), _DATE_DOCS)
        want = str(value).strip()
        if not required:
            if want not in extract_dates(combined):
                findings.append(Finding(
                    sentence_id="",
                    field=str(field),
                    message=(
                        f"서류({doc_names})에서 {field} 날짜 "
                        f"{want}을(를) 찾을 수 없습니다."
                    ),
                    fix_hint="편철 출력을 확인하세요.",
                ))
            continue
        missing = [
            doc for doc in required
            if want not in per_doc_dates.get(doc, set())
        ]
        if missing:
            findings.append(Finding(
                sentence_id="",
                field=str(field),
                message=(
                    f"서류({doc_names})에서 {field} 날짜 "
                    f"{want}을(를) 찾을 수 없습니다 "
                    f"(없는 서류: {', '.join(missing)})."
                ),
                fix_hint="편철 출력을 확인하세요.",
            ))
    for field, value in (expected_names or {}).items():
        required = _required_docs(str(field), _NAME_DOCS)
        needle = str(value)
        if not needle:
            continue
        if not required:
            if needle not in combined:
                findings.append(Finding(
                    sentence_id="",
                    field=str(field),
                    message=(
                        f"서류({doc_names})에서 {field} 이름 "
                        f"{needle}을(를) 찾을 수 없습니다."
                    ),
                    fix_hint="편철 출력을 확인하세요.",
                ))
            continue
        missing = [doc for doc in required if needle not in texts.get(doc, "")]
        if missing:
            findings.append(Finding(
                sentence_id="",
                field=str(field),
                message=(
                    f"서류({doc_names})에서 {field} 이름 "
                    f"{needle}을(를) 찾을 수 없습니다 "
                    f"(없는 서류: {', '.join(missing)})."
                ),
                fix_hint="편철 출력을 확인하세요.",
            ))

    # --- extra (per-doc) ---
    allowed_amounts = {int(v) for v in (expected_amounts or {}).values()}
    allowed_dates = {str(v).strip() for v in (expected_dates or {}).values()}
    allowed_dates |= _allowlisted_dates(expected_dates or {})
    for doc_name, seen in per_doc_amounts.items():
        for value in sorted(seen):
            if int(value) not in allowed_amounts:
                findings.append(Finding(
                    sentence_id="",
                    field=str(doc_name),
                    message=(
                        f"{doc_name}에 기대값에 없는 금액 "
                        f"{int(value):,}원이 있습니다."
                    ),
                    fix_hint="편철 출력을 확인하세요.",
                ))
    for doc_name, seen in per_doc_dates.items():
        for value in sorted(seen):
            if str(value) not in allowed_dates:
                findings.append(Finding(
                    sentence_id="",
                    field=str(doc_name),
                    message=(
                        f"{doc_name}에 기대값에 없는 날짜 "
                        f"{value}이(가) 있습니다."
                    ),
                    fix_hint="편철 출력을 확인하세요.",
                ))

    # --- naming (per-doc) ---
    for doc_name, text in texts.items():
        for hit in dict.fromkeys(find_forbidden(text)):
            findings.append(Finding(
                sentence_id="",
                field=str(doc_name),
                message=f"{doc_name}에 쓸 수 없는 표현이 있습니다: {hit}",
                fix_hint="사실대로 고쳐 쓰세요.",
            ))
    return GateResult(
        gate="G1b", status="fail" if findings else "pass", findings=findings,
    )


__all__ = [
    "LEAK_PATTERNS",
    "build_expected_amounts",
    "build_expected_dates",
    "build_expected_names",
    "check_g1b",
    "extract_amounts",
    "extract_dates",
    "extract_pdf_metadata_text",
    "extract_pdf_text",
    "find_sensitive_numbers",
    "required_docs_for",
]
