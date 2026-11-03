"""G1b final value check (M5, rule-based).

Extracts amounts, dates, and names from the finished documents (content
proof PDF, exhibit bundle PDF, evidence list PDF, ecourt clipboard text)
and compares them against the user-confirmed values and the calculated
values. In-sentence numbers are normalized (``4,014,383원`` ->
``4014383``, ``2026. 5. 2.`` -> ``2026-05-02``). A missing expected value
fails with the document set and the field name. Document naming rules are
checked together.
"""

from __future__ import annotations

import re
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
LEAK_PATTERNS = (
    re.compile(r"\d{6}-\d{7}"),
    re.compile(r"\d{2,6}-\d{2,6}-\d{4,}"),
    re.compile(r"(?<!\d)\d{11,14}(?!\d)"),
)


def find_sensitive_numbers(
    text: str, exclude: Any = None,
) -> List[str]:
    """Account/resident-number hits, ignoring ``exclude`` substrings (phones)."""
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
    """Expected amounts from confirmed fields + calculation (zeros skipped)."""
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
        for index, entry in enumerate(allocations):
            if not isinstance(entry, dict):
                continue
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
            _put(
                f"allocations[{index}].remaining_principal_after",
                entry.get("remaining_principal_after"),
            )
    _put("accrued_interest", calculation.get("accrued_interest"))
    reference = calculation.get("reference_total", {}) or {}
    if isinstance(reference, dict):
        _put("reference_total.amount", reference.get("amount"))
    return expected


def build_expected_dates(
    fields: Mapping[str, Any],
    calculation: Mapping[str, Any],
    as_of: Any = None,
) -> Dict[str, str]:
    """Expected ISO dates from confirmed fields + calculation + as_of."""
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
        _put("accrual_start_date", accrual)
    if as_of:
        _put("as_of", as_of)
    return expected


def build_expected_names(fields: Mapping[str, Any]) -> Dict[str, str]:
    expected: Dict[str, str] = {}
    for name in ("creditor_name", "debtor_name"):
        value = str((fields or {}).get(name, "") or "").strip()
        if value:
            expected[name] = value
    return expected


def check_g1b(
    expected_amounts: Mapping[str, int],
    expected_dates: Mapping[str, str],
    expected_names: Mapping[str, str],
    docs: Mapping[str, str],
) -> GateResult:
    """Compare extracted values against expected; fail lists doc set + field."""
    findings: List[Finding] = []
    texts = {str(name): str(text or "") for name, text in (docs or {}).items()}
    doc_names = ", ".join(texts) if texts else "(서류 없음)"
    combined = "\n".join(texts.values())
    seen_amounts = extract_amounts(combined)
    seen_dates = extract_dates(combined)

    for field, value in (expected_amounts or {}).items():
        if int(value) not in seen_amounts:
            findings.append(Finding(
                sentence_id="",
                field=str(field),
                message=(
                    f"서류({doc_names})에서 {field} 금액 "
                    f"{int(value):,}원을 찾을 수 없습니다."
                ),
                fix_hint="편철 출력을 확인하세요.",
            ))
    for field, value in (expected_dates or {}).items():
        if str(value).strip() not in seen_dates:
            findings.append(Finding(
                sentence_id="",
                field=str(field),
                message=(
                    f"서류({doc_names})에서 {field} 날짜 "
                    f"{str(value).strip()}을(를) 찾을 수 없습니다."
                ),
                fix_hint="편철 출력을 확인하세요.",
            ))
    for field, value in (expected_names or {}).items():
        if str(value) and str(value) not in combined:
            findings.append(Finding(
                sentence_id="",
                field=str(field),
                message=(
                    f"서류({doc_names})에서 {field} 이름 "
                    f"{str(value)}을(를) 찾을 수 없습니다."
                ),
                fix_hint="편철 출력을 확인하세요.",
            ))
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
]
