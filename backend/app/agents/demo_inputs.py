"""Demo/test fixed inputs (contract 5장, M2a task 5).

``build_demo_confirmed_facts(review)`` is the single rule used by the record
run, the replay tests, and the E2E screen flow so replay builds identical
model requests: review values are kept, and only empty slots are filled from
``specs/case-api-examples/confirmed_facts_kr.json`` ``fallback_fields``.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from app.agents.case_state import REPO_ROOT
from app.agents import deps

FALLBACK_PATH = (
    REPO_ROOT / "specs" / "case-api-examples" / "confirmed_facts_kr.json"
)
DEMO_AS_OF = "2026-06-01"

_ITEM_RE = re.compile(r"^item(\d+)$")


def _item_num(item_id: str) -> int:
    match = _ITEM_RE.match(str(item_id or "").strip())
    return int(match.group(1)) if match else 10**9


@lru_cache(maxsize=1)
def fallback_fields() -> Dict[str, Any]:
    data = json.loads(FALLBACK_PATH.read_text(encoding="utf-8"))
    fields = data.get("fallback_fields", {})
    if not isinstance(fields, dict):
        raise ValueError("fallback_fields is not an object")
    return dict(fields)


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, list):
        return len(value) == 0
    if isinstance(value, dict):
        return len(value) == 0
    return False


def _as_dict(review: Any) -> Dict[str, Any]:
    if isinstance(review, dict):
        return review
    if hasattr(review, "model_dump"):
        return review.model_dump()
    raise TypeError(f"not a Review: {type(review)!r}")


def build_demo_confirmed_facts(
    review: Any, *, needs_review: bool = False
) -> Dict[str, Any]:
    """ConfirmedFacts from a Review by the fixed demo rule (contract 5장)."""
    data = _as_dict(review)
    fallback = fallback_fields()
    fields: Dict[str, Any] = {}
    for entry in data.get("fields", []) or []:
        if not isinstance(entry, dict) or "field" not in entry:
            continue
        name = str(entry["field"])
        value = entry.get("value")
        if _is_empty(value) and name in fallback:
            value = fallback[name]
        fields[name] = value
    for name, value in fallback.items():
        if name not in fields:
            fields[name] = value
    evidence_roles: Dict[str, str] = {}
    for entry in data.get("evidence_roles", []) or []:
        if isinstance(entry, dict) and entry.get("ex_id"):
            evidence_roles[str(entry["ex_id"])] = str(
                entry.get("suggested_role") or "other"
            )
    candidates: List[Dict[str, Any]] = []
    for utterance in data.get("utterances", []) or []:
        if not isinstance(utterance, dict):
            continue
        tags = utterance.get("tags", []) or []
        if "repay_promise" not in tags:
            continue
        ex_id = str(utterance.get("ex_id", ""))
        item_id = str(utterance.get("item_id", ""))
        if ex_id and item_id:
            candidates.append({"ex_id": ex_id, "item_id": item_id})
    candidates.sort(key=lambda c: (deps.ex_num(c["ex_id"]), _item_num(c["item_id"])))
    highlight = (
        [f"{candidates[0]['ex_id']}:{candidates[0]['item_id']}"] if candidates else []
    )
    out: Dict[str, Any] = {
        "fields": fields,
        "evidence_roles": evidence_roles,
        "highlight": highlight,
        "as_of": DEMO_AS_OF,
    }
    # INT-3b step 5: confirm redaction when needs-review copies exist.
    if needs_review:
        out["redaction_confirmed"] = True
    return out
