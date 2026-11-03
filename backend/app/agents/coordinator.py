"""Coordinator: rule-based state machine + agent orchestration (M2a task 6).

Transition table (contract 3장)::

    POST /run from INTAKE        -> reading/organizing -> CHECKPOINT_1
    PUT  /facts                  -> CALCULATING (clears calc/drafts)
    POST /run from CALCULATING   -> calculating/drafting -> DRAFT_APPROVAL
    PUT  /drafts                 -> edit/approve (stays in DRAFT_APPROVAL)
    POST /run from DRAFT_APPROVAL -> packaging -> CHECKPOINT_2 (or 409)

HOLD outcomes are returned as ``CaseView(state=HOLD)`` (HTTP 200), never 500.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from app.agents import deps
from app.agents import draft_rules as draft_rules_mod
from app.agents.base import AgentSchemaError, AuditRecord
from app.agents.case_state import (
    CaseState,
    HoldReason,
    StepState,
    SubStep,
    delete_case,
    files_dir,
    load_case,
    save_case,
    utc_now_iso,
)
from app.agents import intake as intake_mod


# --- API-facing errors ----------------------------------------------------------
class CaseNotFound(KeyError):
    pass


class WrongState(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class BadRequest(Exception):
    def __init__(self, code: str, message: str,
                 missing: Optional[List[str]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.missing = list(missing or [])


class ConcurrentRun(Exception):
    pass


class DeleteConflict(Exception):
    """DELETE verified remnants (files in use) — retryable 409."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# --- steps (contract 4장) ---------------------------------------------------------
STEP_DEFS: List[Dict[str, Any]] = [
    {"key": "intake", "agent": "접수 담당", "group": "Forensic Visual", "model": None},
    {"key": "reading", "agent": "판독 담당", "group": "Fact-Timeline Chronology",
     "model": "READER_MODEL"},
    {"key": "vision", "agent": "시각 감식 담당", "group": "Forensic Visual", "model": "sam-3.1"},
    {"key": "organizing", "agent": "사실 정리 담당", "group": "Fact-Timeline Chronology",
     "model": "muse-spark-1.3"},
    {"key": "privacy", "agent": "개인정보 보호 담당", "group": "Forensic Visual", "model": None},
    {"key": "checkpoint_1", "agent": "사용자 확인", "group": "User", "model": None},
    {"key": "calculating", "agent": "계산 담당", "group": "Financial Auditor", "model": None},
    {"key": "drafting", "agent": "문안 작성 담당", "group": "Fact-Timeline Chronology",
     "model": "muse-spark-1.3"},
    {"key": "verifying", "agent": "검증 담당(G1a·G3)", "group": "Financial Auditor", "model": None},
    {"key": "draft_approval", "agent": "사용자 문장 승인", "group": "User", "model": None},
    {"key": "packaging", "agent": "편철 담당", "group": "Judicial Form Filler", "model": None},
    {"key": "checkpoint_2", "agent": "사용자 최종 확인", "group": "User", "model": None},
]


def fresh_steps() -> List[StepState]:
    steps: List[StepState] = []
    for entry in STEP_DEFS:
        model = entry["model"]
        if model == "READER_MODEL":
            model = deps.READER_MODEL
        steps.append(
            StepState(
                key=entry["key"], agent=entry["agent"],
                group=entry["group"], model=model,
            )
        )
    return steps


SLOT_DESCRIPTIONS: Dict[str, str] = {
    "creditor_name": "채권자 이름",
    "debtor_name": "채무자 이름",
    "principal": "대여 원금",
    "loan_date": "대여일",
    "due_date": "변제기",
    "repaid_amount": "받은 돈(첫 변제액)",
    "repaid_date": "받은 날(첫 변제일)",
    "remaining_principal": "남은 원금(계산값)",
    "accrual_start_date": "지연손해금 기산일(계산값)",
    "total_claim_amount": "기준일 참고 총액(계산값)",
    "calculated_interest": "기준일까지 쌓인 이자(계산값)",
    "demand_date": "독촉일",
    "creditor_phone": "채권자 연락처",
    "debtor_phone": "채무자 연락처",
    "creditor_address": "채권자 주소",
    "debtor_address": "채무자 주소",
    "agreed_rate": "약정 이율(연 %)",
    "delay_rate": "지연손해금 이율(연 %)",
    "contract_interest": "약정 이자율(연 %)",
}

REVIEW_FIELD_ORDER = [
    "creditor_name", "creditor_address", "creditor_phone",
    "debtor_name", "debtor_address",
    "principal", "loan_date", "due_date", "interest_rate",
    "transaction_kind", "repayments",
]


# --- agent injection (stage A fakes) ----------------------------------------------
AgentFn = Callable[..., Dict[str, Any]]
AGENTS: Dict[str, Optional[AgentFn]] = {"reader": None, "organizer": None, "drafter": None}


def _default_reader(**kwargs: Any) -> Dict[str, Any]:
    from app.agents.reader import run_reader

    return run_reader(**kwargs)


def _default_organizer(**kwargs: Any) -> Dict[str, Any]:
    from app.agents.fact_organizer import run_organizer

    return run_organizer(**kwargs)


def _default_drafter(**kwargs: Any) -> Dict[str, Any]:
    from app.agents.drafter import run_drafter

    return run_drafter(**kwargs)


_DEFAULTS: Dict[str, AgentFn] = {
    "reader": _default_reader,
    "organizer": _default_organizer,
    "drafter": _default_drafter,
}


def get_agent(name: str) -> AgentFn:
    return AGENTS.get(name) or _DEFAULTS[name]


# --- run locks (concurrent POST /run -> 409) ---------------------------------------
_RUN_LOCKS: Dict[str, threading.Lock] = {}
_RUN_LOCKS_GUARD = threading.Lock()


def _run_lock(case_id: str) -> threading.Lock:
    with _RUN_LOCKS_GUARD:
        lock = _RUN_LOCKS.get(case_id)
        if lock is None:
            lock = threading.Lock()
            _RUN_LOCKS[case_id] = lock
        return lock


# --- small helpers ------------------------------------------------------------------
def fmt_cost(cost: float) -> str:
    if not cost:
        return "0"
    return f"{float(cost):.4f}"


def sha_short(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# Steps whose model calls the board counts from substeps[].calls
# (frontend countModelCalls); the others count attempts.
_SUBSTEP_CALL_STEPS = ("reading", "vision")


def _step_spent(step: StepState) -> float:
    """Exact spend of every run of a step (cost_usd on old cases)."""
    if step.spent_usd is not None:
        return float(step.spent_usd)
    try:
        return float(step.cost_usd or 0.0)
    except ValueError:
        return 0.0


def _set_spend(step: StepState, cost: float) -> None:
    """This run's spend on top of the kept spend of earlier runs (fix-cost)."""
    step.spent_usd = round(float(step.kept_usd or 0.0) + float(cost or 0.0), 6)
    step.cost_usd = fmt_cost(step.spent_usd)


def _set_calls(step: StepState, calls: int) -> None:
    step.attempts = int(step.kept_calls or 0) + int(calls or 0)


def _substep_calls(step: StepState) -> Dict[str, int]:
    """Model calls per evidence of a step's earlier run (board rule)."""
    out: Dict[str, int] = {}
    for sub in step.substeps:
        calls = int(sub.calls or 0) or (1 if sub.status == "done" else 0)
        out[sub.ex_id] = out.get(sub.ex_id, 0) + calls
    return out


def _fold_calls(substeps: List[SubStep], prior: Dict[str, int]) -> None:
    """Add an earlier run's calls per evidence, so a rerun keeps them."""
    for sub in substeps:
        sub.calls = int(sub.calls or 0) + int(prior.get(sub.ex_id, 0) or 0)


def _mark_running(step: StepState) -> None:
    step.status = "running"
    step.started_at = utc_now_iso()
    step.ended_at = None
    # fix-cost: a rerun (HOLD resume, PUT /facts) keeps billed spend and
    # calls; reading/vision keep their calls per evidence in substeps.
    step.kept_usd = _step_spent(step)
    step.spent_usd = step.kept_usd
    step.kept_calls = (int(step.attempts or 0)
                       if step.model and step.key not in _SUBSTEP_CALL_STEPS
                       else 0)


def _mark_done(
    step: StepState,
    latency_ms: int = 0,
    attempts: int = 1,
    cost: float = 0.0,
    note: str = "",
) -> None:
    step.status = "done"
    step.ended_at = utc_now_iso()
    step.latency_ms = int(latency_ms)
    _set_calls(step, attempts)
    _set_spend(step, cost)
    if note:
        step.note = note


def _mark_hold(step: StepState, latency_ms: int = 0, note: str = "",
               cost: Optional[float] = None,
               calls: Optional[int] = None) -> None:
    step.status = "hold"
    step.ended_at = utc_now_iso()
    step.latency_ms = int(latency_ms)
    if cost is not None:
        _set_spend(step, cost)
    if calls is not None:
        _set_calls(step, calls)
    if note:
        step.note = note


def _mark_skipped(step: StepState, note: str = "") -> None:
    step.status = "skipped"
    step.attempts = 0
    step.cost_usd = "0"
    if note:
        step.note = note


def _partial_spend(exc: BaseException) -> Dict[str, Any]:
    """Spend riding on a failed call's ``_spark_partial`` (INT-3 B6)."""
    part = getattr(exc, "_spark_partial", None) or {}
    out: Dict[str, Any] = {}
    for key in ("cost_usd", "latency_ms", "attempts",
                "tokens_in", "tokens_out"):
        try:
            out[key] = part.get(key, 0) or 0
        except AttributeError:
            out[key] = 0
    return out


def _mark_hold_from_partial(step: StepState, exc: BaseException,
                             extra: Optional[Dict[str, Any]] = None) -> None:
    """Hold a step with the failed call's spend included (INT-3 B6)."""
    part = _partial_spend(exc)
    cost = float(part.get("cost_usd", 0.0) or 0.0)
    latency = int(part.get("latency_ms", 0) or 0)
    calls = int(part.get("attempts", 0) or 0)
    if extra:
        cost += float(extra.get("cost_usd", 0.0) or 0.0)
        latency += int(extra.get("latency_ms", 0) or 0)
        calls += int(extra.get("attempts", 0) or 0)
    _mark_hold(step, latency, cost=cost, calls=calls)


def _reset_from(state: CaseState, key: str) -> None:
    """Reset a step and every later step back to waiting (costs kept)."""
    keys = [entry["key"] for entry in STEP_DEFS]
    try:
        start = keys.index(key)
    except ValueError:
        return
    fresh = {entry.key: entry for entry in fresh_steps()}
    for entry in state.steps:
        if keys.index(entry.key) >= start:
            entry.status = "waiting"
            entry.started_at = None
            entry.ended_at = None
            entry.latency_ms = 0
            # cost_usd (and a model step's attempts, its calls) is kept so
            # HOLD/rollback never loses billed spend (fix-cost: the rerun
            # adds to it, see _mark_running).
            if not fresh[entry.key].model:
                entry.attempts = 0
            entry.note = ""
            entry.substeps = []
            entry.model = fresh[entry.key].model


def _hold(
    state: CaseState,
    step: str,
    code: str,
    message: str,
    fields: Optional[List[str]] = None,
    cost: Optional[float] = None,
) -> CaseState:
    state.state = "HOLD"
    candidate = HoldReason(step=step, code=code, message=message,
                           fields=list(fields or []))
    if not any(r.step == candidate.step and r.code == candidate.code
               and r.message == candidate.message
               and list(r.fields) == list(candidate.fields)
               for r in state.hold_reasons):
        state.hold_reasons.append(candidate)
    try:
        _mark_hold(state.step(step), note=message[:120], cost=cost)
    except KeyError:
        pass
    _recompute_run_cost(state)
    return save_case(state)


def _recompute_run_cost(state: CaseState) -> float:
    # fix-cost: sum the exact step spend (not the 4-decimal display), so
    # the shown total is the ledger sum for the run rounded once.
    total = sum(_step_spent(entry) for entry in state.steps)
    state.run_cost_usd = round(total, 6)
    return state.run_cost_usd


def _audit(
    state: CaseState,
    step: str,
    ex_id: Optional[str],
    model: Optional[str],
    prompt_version: Optional[str],
    input_hash: str,
    latency_ms: int,
    tokens_in: int,
    tokens_out: int,
    cost: float,
) -> None:
    state.audit_log.append(
        AuditRecord(
            step=step, ex_id=ex_id, model_id=model,
            prompt_version=prompt_version, input_hashes=[input_hash],
            latency_ms=int(latency_ms), tokens_in=int(tokens_in),
            tokens_out=int(tokens_out), cost_usd=float(cost),
        )
    )


def hold_from_calc_or_draft(state: CaseState) -> bool:
    """True when every hold reason comes from 계산·초안 단계."""
    if state.state != "HOLD" or not state.hold_reasons:
        return False
    allowed = {"calculating", "drafting", "verifying"}
    return all(reason.step in allowed for reason in state.hold_reasons)


def hold_from_packaging_fixable(state: CaseState) -> bool:
    """True for a packaging HOLD the user can fix (INT-3 B7 + task 3).

    naming_violation (values) and g1b_failed (values or sentences):
    PUT /facts re-enters at calculating, PUT /drafts (g1b only)
    re-enters at draft approval, and POST /run retries packaging.
    """
    if state.state != "HOLD" or not state.hold_reasons:
        return False
    return all(reason.step == "packaging"
               and reason.code in ("naming_violation", "g1b_failed")
               for reason in state.hold_reasons)


def hold_from_g1b(state: CaseState) -> bool:
    """True when every hold reason is a packaging g1b_failed (task 3)."""
    if state.state != "HOLD" or not state.hold_reasons:
        return False
    return all(reason.step == "packaging" and reason.code == "g1b_failed"
               for reason in state.hold_reasons)


# --- structural validators (agent outputs, real or fake) -------------------------------
def _valid_box(box: Any) -> bool:
    if not isinstance(box, dict):
        return False
    try:
        x1 = int(box["x1"]); y1 = int(box["y1"])
        x2 = int(box["x2"]); y2 = int(box["y2"])
        ref_w = int(box["ref_w"]); ref_h = int(box["ref_h"])
    except (KeyError, TypeError, ValueError):
        return False
    if box.get("system") != "pixel":
        return False
    return ref_w > 0 and ref_h > 0 and x2 >= x1 and y2 >= y1


def _clean_nullable(value: Any) -> Any:
    if isinstance(value, str) and value.strip().lower() in ("null", "none", ""):
        return None
    return value


def validate_reading_items(items: Any) -> List[Dict[str, Any]]:
    """Validate final (pixel) reading items; recode item_id by order."""
    if not isinstance(items, list):
        raise ValueError("items is not a list")
    cleaned: List[Dict[str, Any]] = []
    for position, raw in enumerate(items, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"items[{position}] is not an object")
        kind = raw.get("kind")
        verbatim = raw.get("text_verbatim")
        box = raw.get("box")
        if not kind or not isinstance(kind, str):
            raise ValueError(f"items[{position}].kind is missing")
        if verbatim is None or not isinstance(verbatim, str):
            raise ValueError(f"items[{position}].text_verbatim is missing")
        if not _valid_box(box):
            raise ValueError(f"items[{position}].box is not a pixel box")
        side = _clean_nullable(raw.get("side"))
        if side is not None and side not in ("left", "right"):
            raise ValueError(f"items[{position}].side must be left|right")
        entry: Dict[str, Any] = {
            "item_id": f"item{position}",
            "kind": str(kind),
            "text_verbatim": str(verbatim),
            "normalized": _clean_nullable(raw.get("normalized")),
            "box": {
                "x1": int(box["x1"]), "y1": int(box["y1"]),
                "x2": int(box["x2"]), "y2": int(box["y2"]),
                "system": "pixel",
                "ref_w": int(box["ref_w"]), "ref_h": int(box["ref_h"]),
            },
            "speaker": _clean_nullable(raw.get("speaker")),
            "side": side,
            "confidence": raw.get("confidence"),
        }
        # INT-3 (contract 6c, M4b 6.2): out-of-range boxes are flagged,
        # not clamped; the flag (and video frame_ts) ride to the API.
        if raw.get("box_warning") is not None:
            entry["box_warning"] = str(raw.get("box_warning"))
        if raw.get("frame_ts") is not None:
            try:
                entry["frame_ts"] = float(raw.get("frame_ts"))
            except (TypeError, ValueError):
                pass
        cleaned.append(entry)
    return cleaned


def validate_review(review: Any) -> Dict[str, Any]:
    if not isinstance(review, dict):
        raise ValueError("review is not an object")
    for key in ("fields", "conflicts", "questions", "utterances", "evidence_roles"):
        if key not in review:
            raise ValueError(f"review.{key} is missing")
    if not isinstance(review["fields"], list) or not review["fields"]:
        raise ValueError("review.fields is empty")
    for entry in review["fields"]:
        if not isinstance(entry, dict) or "field" not in entry or "value" not in entry:
            raise ValueError("review.fields[] entry is malformed")
        if "sources" not in entry or not isinstance(entry["sources"], list):
            raise ValueError(f"review.fields.{entry.get('field')}.sources is missing")
        if "null_reason" not in entry:
            value = entry.get("value")
            empty = value is None or value == []
            entry["null_reason"] = "판독에서 찾지 못함" if empty else None
    if not isinstance(review["utterances"], list):
        raise ValueError("review.utterances is not a list")
    if not isinstance(review["evidence_roles"], list):
        raise ValueError("review.evidence_roles is not a list")
    return review


def validate_draft_sentences(sentences: Any, ex_ids: List[str]) -> List[Dict[str, Any]]:
    if not isinstance(sentences, list) or not sentences:
        raise ValueError("sentences is empty")
    known = set(ex_ids)
    cleaned: List[Dict[str, Any]] = []
    seen: set = set()
    for position, raw in enumerate(sentences, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"sentences[{position}] is not an object")
        sid = raw.get("sentence_id") or f"s{position}"
        if sid in seen:
            raise ValueError(f"duplicate sentence_id: {sid}")
        seen.add(sid)
        stype = raw.get("type")
        if stype not in ("fact", "user"):
            raise ValueError(f"sentences[{position}].type must be fact|user")
        text = raw.get("text_with_slots")
        if not text or not isinstance(text, str):
            raise ValueError(f"sentences[{position}].text_with_slots is missing")
        refs = raw.get("ex_refs", [])
        if not isinstance(refs, list):
            raise ValueError(f"sentences[{position}].ex_refs is not a list")
        for ref in refs:
            if str(ref) not in known:
                raise ValueError(f"sentences[{position}].ex_refs has unknown {ref}")
        cleaned.append({
            "sentence_id": str(sid),
            "type": str(stype),
            "text_with_slots": str(text),
            "ex_refs": [str(ref) for ref in refs],
        })
    return cleaned


# --- case lifecycle --------------------------------------------------------------------
def create_case(jurisdiction: str, with_sample: bool) -> CaseState:
    from app.agents.case_state import new_case_id

    fresh = CaseState(
        case_id=new_case_id(),
        jurisdiction=jurisdiction,
        state="INTAKE",
        meta_mode=deps.meta_mode(),
        steps=fresh_steps(),
        created_at=utc_now_iso(),
    )
    if with_sample:
        intake_mod.intake_sample(fresh)
        step = fresh.step("intake")
        _mark_done(step, note=f"증거 {len(fresh.evidence)}개, SHA-256 기록")
    _recompute_run_cost(fresh)
    return save_case(fresh)


def get_case(case_id: str) -> CaseState:
    state = load_case(case_id)
    if state is None:
        raise CaseNotFound(case_id)
    return state


def remove_case(case_id: str) -> None:
    lock = _run_lock(case_id)
    if not lock.acquire(blocking=False):
        raise ConcurrentRun(case_id)
    try:
        try:
            deleted = delete_case(case_id)
        except PermissionError as exc:
            # INT-3 B2: locked files stay on disk — 409, not 200.
            raise DeleteConflict(
                "사건 파일이 사용 중이라 삭제하지 못했습니다.") from exc
        if not deleted:
            raise CaseNotFound(case_id)
    finally:
        lock.release()


def _resume_step_for_hold(state: CaseState) -> Optional[str]:
    if state.state != "HOLD" or not state.hold_reasons:
        return None
    # L3: a privacy_leak HOLD re-executes from the redaction stage.
    if all(r.step == "privacy" and r.code == "privacy_leak"
           for r in state.hold_reasons):
        return "privacy"
    # INT-3 B1/B7 + task 3: internal/config holds resume by step; a
    # packaging naming/G1b hold retries packaging after the fix.
    if all(r.code in ("internal_error", "config_missing_key")
           for r in state.hold_reasons):
        steps = {r.step for r in state.hold_reasons}
        if steps <= {"reading", "organizing", "intake"}:
            return "intake"
        if steps <= {"calculating", "drafting", "verifying"}:
            return "calc"
        if steps <= {"packaging"}:
            return "package"
        if steps <= {"privacy"}:
            return "privacy"
        return None
    if all(r.step == "packaging"
           and r.code in ("naming_violation", "g1b_failed")
           for r in state.hold_reasons):
        return "package"
    return None



# --- M4a vision/privacy helpers (6a) --------------------------------------------
def _segments_path(case_id: str) -> Any:
    from pathlib import Path as _Path

    return _Path(files_dir(case_id)) / "segments.json"


def _redactions_path(case_id: str) -> Any:
    from pathlib import Path as _Path

    return _Path(files_dir(case_id)) / "redactions.json"


def load_segments(case_id: str) -> List[Dict[str, Any]]:
    path = _segments_path(case_id)
    try:
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def load_redactions(case_id: str) -> Dict[str, Any]:
    path = _redactions_path(case_id)
    # INT-3 task 2 (contract 6c): before the privacy stage runs there
    # is no file, and the leak check reads pending (never pass).
    empty: Dict[str, Any] = {
        "plan": [], "previews": [],
        "leak_check": {"status": "pending", "findings": []},
    }
    try:
        if not path.exists():
            return empty
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return empty
        data.setdefault("plan", [])
        data.setdefault("previews", [])
        data.setdefault("leak_check", {"status": "pass", "findings": []})
        return data
    except (OSError, ValueError):
        return empty


def _vision_one(
    case_id: str,
    record: Any,
    preview_bytes: Optional[bytes],
    preview_size: Optional[tuple],
    filename: str,
    meta_mode: str,
) -> Dict[str, Any]:
    """Vision-1 noun calls for one evidence (parallel worker, no saves)."""
    from app.agents import vision as vision_mod

    ex_id = str(record.ex_id)
    if str(getattr(record, "kind", "")) == "video":
        return {"ex_id": ex_id, "skipped": True}
    if preview_bytes is None or preview_size is None:
        return {"ex_id": ex_id, "objects": [], "status": "not_found",
                "cost": 0.0, "latency_ms": 0, "calls": 0,
                "note": "preview missing"}
    started = time.perf_counter()
    try:
        objects, info = vision_mod.run_vision_nouns(
            case_id, ex_id, bytes(preview_bytes), filename,
            int(preview_size[0]), int(preview_size[1]),
            meta_mode, case_id, files_dir(case_id),
        )
    except (deps.FixtureNotFound, deps.BudgetError,
            vision_mod.VisionParseError) as exc:
        partial = getattr(exc, "_vision_partial", None) or {}
        return {"ex_id": ex_id, "error": exc,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "cost": float(partial.get("cost_usd", 0.0) or 0.0),
                "calls": int(partial.get("calls", 0) or 0)}
    except Exception as exc:
        partial = getattr(exc, "_vision_partial", None) or {}
        wrapped = vision_mod.VisionParseError(
            f"vision error: {type(exc).__name__}")
        return {"ex_id": ex_id, "error": wrapped,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "cost": float(partial.get("cost_usd", 0.0) or 0.0),
                "calls": int(partial.get("calls", 0) or 0)}
    latency_ms = int((time.perf_counter() - started) * 1000)
    status = "ok" if objects else "not_found"
    return {"ex_id": ex_id, "objects": objects, "status": status,
            "cost": float(info.get("cost_usd", 0.0) or 0.0),
            "latency_ms": latency_ms, "calls": int(info.get("calls", 0) or 0)}


# --- POST /run ----------------------------------------------------------------------------
def run_case(case_id: str) -> CaseState:
    lock = _run_lock(case_id)
    if not lock.acquire(blocking=False):
        raise ConcurrentRun(case_id)
    try:
        state = get_case(case_id)
        try:
            if state.state == "INTAKE":
                return _run_intake_flow(state)
            if state.state in ("READING", "ORGANIZING"):
                return _run_intake_flow(state)
            if state.state in ("CALCULATING", "DRAFTING", "VERIFYING"):
                return _run_calc_flow(state)
            if state.state == "DRAFT_APPROVAL":
                return _run_package_flow(state)
            if state.state == "PACKAGING":
                return _run_package_flow(state)
            if state.state == "HOLD":
                resume = _resume_step_for_hold(state)
                if resume == "intake":
                    state.hold_reasons = []
                    return _run_intake_flow(state)
                if resume == "calc":
                    state.hold_reasons = []
                    return _run_calc_flow(state)
                if resume == "package":
                    state.hold_reasons = []
                    return _run_package_flow(state)
                if resume == "privacy":
                    state.hold_reasons = []
                    _reset_from(state, "privacy")
                    return _run_privacy_flow(state)
            raise WrongState("wrong_state", f"지금 상태({state.state})에서는 실행할 수 없습니다.")
        except (CaseNotFound, WrongState, ConcurrentRun):
            raise
        except (deps.FixtureNotFound, deps.BudgetError, AgentSchemaError):
            raise
        except Exception as exc:
            step = {
                "READING": "reading", "ORGANIZING": "organizing",
                "CALCULATING": "calculating", "DRAFTING": "drafting",
                "VERIFYING": "verifying", "PACKAGING": "packaging",
                "PRIVACY": "privacy",
            }.get(state.state, "reading")
            try:
                current = load_case(case_id)
                if current is not None:
                    state = current
            except Exception:
                pass
            # INT-3 B6: a failed call's spend still lands on its step.
            # fix-cost review: on top of what the step saved for this run
            # (earlier drafter rounds, the organizer's first call), never
            # instead of it.
            part = _partial_spend(exc)
            running = next((entry for entry in state.steps
                            if entry.status == "running"), None)
            if running is not None:
                saved_cost = _step_spent(running) - float(running.kept_usd or 0.0)
                saved_calls = int(running.attempts or 0) - int(running.kept_calls or 0)
                _mark_hold(running,
                           int(part.get("latency_ms", 0) or 0),
                           cost=saved_cost + float(part.get("cost_usd", 0.0) or 0.0),
                           calls=(None if running.key in _SUBSTEP_CALL_STEPS
                                  else saved_calls
                                  + int(part.get("attempts", 0) or 0)))
            return _hold(state, step, "internal_error",
                         f"처리 중 오류가 생겨 멈췄습니다: {type(exc).__name__}")
    finally:
        lock.release()


def _agent_failed_hold(
    state: CaseState, step: str, exc: BaseException, note: str = ""
) -> CaseState:
    if isinstance(exc, deps.FixtureNotFound):
        return _hold(state, step, "replay_fixture_missing",
                      "기록된 응답이 없어 재생할 수 없습니다.")
    if isinstance(exc, deps.BudgetError):
        return _hold(state, step, "budget_exceeded", "예산 상한을 넘어 호출을 멈췄습니다.")
    # INT-3 B1: a missing model key is its own resumable code (not schema).
    if isinstance(exc, deps.MissingKeyError):
        return _hold(state, step, "config_missing_key",
                      "모델 호출 키가 없어 멈췄습니다.")
    if isinstance(exc, AgentSchemaError):
        return _hold(state, step, "schema_failed", str(exc) or "출력 형식이 맞지 않습니다.")
    raise exc


def _run_intake_flow(state: CaseState) -> CaseState:
    state.meta_mode = deps.meta_mode()
    reader = get_agent("reader")
    organizer = get_agent("organizer")

    # intake (evidence already registered at creation/upload)
    intake_step = state.step("intake")
    if intake_step.status != "done":
        _mark_done(intake_step, note=f"증거 {len(state.evidence)}개, SHA-256 기록")
        save_case(state)

    # reading (per-evidence parallel, results stored in ex_id order)
    state.state = "READING"
    reading_step = state.step("reading")
    _mark_running(reading_step)
    prior_reading_calls = _substep_calls(reading_step)
    save_case(state)
    phase_started = time.perf_counter()

    ordered = sorted(state.evidence, key=lambda r: deps.ex_num(r.ex_id))
    substeps: List[SubStep] = []
    readings: List[Dict[str, Any]] = []
    reading_cost = 0.0
    reading_attempts = 1
    hold_case = False
    unexpected_failed = False

    def _read_one(record: Any) -> Dict[str, Any]:
        # INT-3 B1: a missing key is its own case HOLD (config_missing_key,
        # resumable); other unexpected errors (network, ...) ride raw and
        # become a resumable internal_error when nothing was read — never
        # a dead-end schema_failed.
        # INT-3 B6: failures carry their spend ("partial") for the step cost.
        if record.kind == "video":
            return {"ex_id": record.ex_id, "skipped": True}
        started = time.perf_counter()

        def _spend_of(output: Any) -> Dict[str, Any]:
            if not isinstance(output, dict):
                return {}
            return {key: output.get(key, 0) or 0
                    for key in ("cost_usd", "latency_ms", "attempts")}

        def _failed(exc: BaseException,
                    extras: Any = (),
                    unexpected: bool = False) -> Dict[str, Any]:
            part = _partial_spend(exc)
            for extra in extras:
                for key in ("cost_usd", "latency_ms", "attempts"):
                    part[key] = (part.get(key, 0) or 0) + (extra.get(key, 0) or 0)
            result: Dict[str, Any] = {
                "ex_id": record.ex_id, "error": exc, "partial": part,
                "latency_ms": int((time.perf_counter() - started) * 1000)}
            if unexpected:
                result["unexpected"] = True
            return result

        try:
            output = reader(
                case_id=state.case_id,
                evidence=record.model_dump(),
                evidence_path=intake_mod.evidence_path(state, record),
                preview_size=intake_mod.preview_size(state, record),
                meta_mode=deps.meta_mode(),
                run_id=state.case_id,
            )
        except (deps.FixtureNotFound, deps.BudgetError, AgentSchemaError,
                deps.MissingKeyError) as exc:
            return _failed(exc)
        except Exception as exc:
            return _failed(exc, unexpected=True)
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            items = validate_reading_items(output.get("items"))
        except ValueError:
            # schema retry (fake agents): one more call, then evidence hold
            first_spend = _spend_of(output)
            retry_output: Any = None
            try:
                retry_output = reader(
                    case_id=state.case_id,
                    evidence=record.model_dump(),
                    evidence_path=intake_mod.evidence_path(state, record),
                    preview_size=intake_mod.preview_size(state, record),
                    meta_mode=deps.meta_mode(),
                    run_id=state.case_id,
                )
                items = validate_reading_items(retry_output.get("items"))
                retry_output["_retried"] = True
                for key in ("cost_usd", "latency_ms", "attempts"):
                    retry_output[key] = ((retry_output.get(key, 0) or 0)
                                         + (first_spend.get(key, 0) or 0))
                output = retry_output
            except (deps.FixtureNotFound, deps.BudgetError, AgentSchemaError,
                    deps.MissingKeyError) as exc:
                return _failed(exc, (first_spend,))
            except ValueError as exc:
                err = AgentSchemaError(str(exc))
                return _failed(err, (first_spend, _spend_of(retry_output)))
            except Exception as exc:
                return _failed(exc, (first_spend, _spend_of(retry_output)),
                               unexpected=True)
        return {"ex_id": record.ex_id, "output": output, "items": items,
                "latency_ms": latency_ms}

    workers = deps.reader_concurrency()
    if len(ordered) <= 1 or workers <= 1:
        results = [_read_one(record) for record in ordered]
    else:
        with ThreadPoolExecutor(max_workers=min(workers, len(ordered))) as pool:
            results = list(pool.map(_read_one, ordered))
    results.sort(key=lambda r: deps.ex_num(r["ex_id"]))

    by_ex = {record.ex_id: record for record in state.evidence}
    for result in results:
        ex_id = result["ex_id"]
        record = by_ex[ex_id]
        if result.get("skipped"):
            substeps.append(SubStep(ex_id=ex_id, status="skipped", latency_ms=0))
            continue
        if "error" in result:
            exc = result["error"]
            part = result.get("partial") or {}
            reading_cost += float(part.get("cost_usd", 0.0) or 0.0)
            # fix-cost: calls spent before the failure stay on the board.
            failed_calls = int(part.get("attempts", 0) or 0)
            if isinstance(exc, (deps.FixtureNotFound, deps.BudgetError,
                                deps.MissingKeyError)):
                _agent_failed_hold(state, "reading", exc)
                hold_case = True
                substeps.append(SubStep(ex_id=ex_id, status="hold",
                                        latency_ms=result["latency_ms"],
                                        calls=failed_calls))
                continue
            record.status = "hold"
            substeps.append(SubStep(ex_id=ex_id, status="hold",
                                    latency_ms=result["latency_ms"],
                                    calls=failed_calls))
            if result.get("unexpected") or not isinstance(
                    exc, AgentSchemaError):
                unexpected_failed = True
            continue
        output = result["output"]
        attempts = int(output.get("attempts", 2 if output.get("_retried") else 1))
        cost = float(output.get("cost_usd", 0.0) or 0.0)
        reading_cost += cost
        reading_attempts = max(reading_attempts, attempts)
        readings.append({
            "ex_id": ex_id,
            "model": str(output.get("model") or deps.READER_MODEL),
            "items": result["items"],
        })
        record.status = "ok"
        substeps.append(SubStep(ex_id=ex_id, status="done",
                                latency_ms=result["latency_ms"],
                                calls=max(1, attempts)))
        try:
            file_hash = intake_mod.sha256_bytes(
                intake_mod.evidence_path(state, record).read_bytes()
            )[:16]
        except OSError:
            file_hash = ex_id
        _audit(state, "reading", ex_id, str(output.get("model") or deps.READER_MODEL),
               output.get("prompt_version"), file_hash, result["latency_ms"],
               int(output.get("tokens_in", 0) or 0),
               int(output.get("tokens_out", 0) or 0), cost)
    _fold_calls(substeps, prior_reading_calls)
    reading_step.substeps = substeps
    state.readings = readings
    _set_spend(reading_step, reading_cost)
    reading_step.attempts = reading_attempts
    latency_ms = int((time.perf_counter() - phase_started) * 1000)
    if hold_case:
        _mark_hold(reading_step, latency_ms, cost=reading_cost)
        _recompute_run_cost(state)
        return save_case(state)
    if not state.evidence:
        _mark_hold(reading_step, latency_ms, cost=reading_cost)
        return _hold(state, "reading", "missing_facts", "증거가 없습니다.",
                      ["evidence"], cost=reading_cost)
    if not readings:
        _mark_hold(reading_step, latency_ms, cost=reading_cost)
        if unexpected_failed:
            return _hold(state, "reading", "internal_error",
                          "판독 중 오류가 생겨 멈췄습니다. 다시 실행해 주세요.",
                          cost=reading_cost)
        return _hold(state, "reading", "schema_failed",
                      "판독에 성공한 증거가 없습니다.", cost=reading_cost)
    skipped_count = sum(1 for s in substeps if s.status == "skipped")
    held_count = sum(1 for s in substeps if s.status == "hold")
    note = f"{len(readings)}개 판독"
    if skipped_count:
        note += f", {skipped_count}개 건너뜀(영상)"
    if held_count:
        note += f", {held_count}개 보류"
    _mark_done(reading_step, latency_ms, reading_attempts, reading_cost, note)
    save_case(state)

    # M4a vision: noun calls per evidence (parallel) + signature box retry.
    from app.agents import vision as vision_mod

    vision_step = state.step("vision")
    _mark_running(vision_step)
    prior_vision_calls = _substep_calls(vision_step)
    save_case(state)
    vision_started = time.perf_counter()
    vision_ordered = sorted(state.evidence, key=lambda r: deps.ex_num(r.ex_id))
    vision_previews: dict = {}
    for _record in vision_ordered:
        try:
            _ppath = intake_mod.preview_path(state, _record)
            _psize = intake_mod.preview_size(state, _record)
            _pbytes = _ppath.read_bytes() if _ppath and _ppath.exists() else None
        except OSError:
            _pbytes, _psize = None, None
        vision_previews[_record.ex_id] = (_pbytes, _psize, _record.filename)

    def _vision_one_local(_record: Any) -> Dict[str, Any]:
        _pbytes, _psize, _fname = vision_previews.get(
            _record.ex_id, (None, None, _record.filename))
        return _vision_one(
            state.case_id, _record, _pbytes, _psize, _fname, deps.meta_mode())

    _v_workers = deps.reader_concurrency()
    if len(vision_ordered) <= 1 or _v_workers <= 1:
        _vision_results = [_vision_one_local(_r) for _r in vision_ordered]
    else:
        with ThreadPoolExecutor(
                max_workers=min(_v_workers, len(vision_ordered))) as _v_pool:
            _vision_results = list(_v_pool.map(_vision_one_local, vision_ordered))
    _vision_results.sort(key=lambda r: deps.ex_num(r["ex_id"]))
    _segments: List[Dict[str, Any]] = []
    _vision_substeps: List[SubStep] = []
    _vision_cost = 0.0
    _readings_by_ex = {str(r.get("ex_id", "")): r for r in readings}
    for _result in _vision_results:
        _ex_id = str(_result["ex_id"])
        if _result.get("skipped"):
            _segments.append({"ex_id": _ex_id, "model": vision_mod.MODEL,
                              "objects": [], "status": "skipped"})
            _vision_substeps.append(SubStep(ex_id=_ex_id, status="skipped",
                                            latency_ms=0))
            continue
        if "error" in _result:
            _partial = float(_result.get("cost", 0.0) or 0.0)
            _segments.append({"ex_id": _ex_id, "model": vision_mod.MODEL,
                              "objects": [], "status": "hold",
                              "hold_scope": "nouns",
                              "error": str(_result["error"])[:200]})
            _vision_substeps.append(SubStep(
                ex_id=_ex_id, status="hold",
                latency_ms=int(_result.get("latency_ms", 0) or 0),
                calls=int(_result.get("calls", 0) or 0)))
            # L7: calls already spent stay on the step cost + audit log.
            _vision_cost += _partial
            _audit(state, "vision", _ex_id, vision_mod.MODEL,
                   vision_mod.PROMPT_VERSION, _ex_id,
                   int(_result.get("latency_ms", 0) or 0), 0, 0, _partial)
            continue
        _objects = list(_result.get("objects", []) or [])
        _cost = float(_result.get("cost", 0.0) or 0.0)
        _lat = int(_result.get("latency_ms", 0) or 0)
        _calls = int(_result.get("calls", 0) or 0)
        _retry_error: Optional[BaseException] = None
        _has_signature = any(str(o.get("target", "")) == "signature"
                             for o in _objects)
        if not _has_signature:
            _reading = _readings_by_ex.get(_ex_id, {})
            _items = list(_reading.get("items", []) or [])
            _pbytes, _psize, _fname = vision_previews.get(
                _ex_id, (None, None, "evidence"))
            if _pbytes is not None and _psize is not None and _items:
                try:
                    _retry_objects, _retry_info = (
                        vision_mod.run_vision_signature_retry(
                            state.case_id, _ex_id, bytes(_pbytes),
                            str(_fname), int(_psize[0]), int(_psize[1]),
                            _items, deps.meta_mode(), state.case_id,
                            files_dir(state.case_id),
                            start_index=len(_objects)))
                    _objects.extend(_retry_objects)
                    _cost += float(_retry_info.get("cost_usd", 0.0) or 0.0)
                    _lat += int(_retry_info.get("latency_ms", 0) or 0)
                    _calls += int(_retry_info.get("calls", 0) or 0)
                except (deps.FixtureNotFound, deps.BudgetError,
                        vision_mod.VisionParseError) as exc:
                    _retry_error = exc
                    _spent = getattr(exc, "_vision_partial", None) or {}
                    _cost += float(_spent.get("cost_usd", 0.0) or 0.0)
                    _lat += int(_spent.get("latency_ms", 0) or 0)
                    _calls += int(_spent.get("calls", 0) or 0)
                except Exception as exc:
                    _retry_error = vision_mod.VisionParseError(
                        f"vision error: {type(exc).__name__}")
        if _retry_error is not None:
            # L7: a failed signature retry is a hold with its message,
            # never a silent not_found; noun objects are still kept.
            # INT-3 task 2: signatures are not redaction targets, so a
            # retry-only hold (nouns fine) must not block redaction;
            # the scope marker lets privacy tell it from noun failure.
            _segments.append({"ex_id": _ex_id, "model": vision_mod.MODEL,
                              "objects": _objects, "status": "hold",
                              "hold_scope": "signature_retry",
                              "error": str(_retry_error)[:200]})
            _vision_cost += _cost
            _vision_substeps.append(SubStep(ex_id=_ex_id, status="hold",
                                            latency_ms=_lat, calls=_calls))
            _audit(state, "vision", _ex_id, vision_mod.MODEL,
                   vision_mod.PROMPT_VERSION, _ex_id, _lat, 0, 0, _cost)
            continue
        _status = "ok" if _objects else "not_found"
        _segments.append({"ex_id": _ex_id, "model": vision_mod.MODEL,
                          "objects": _objects, "status": _status})
        _vision_cost += _cost
        _vision_substeps.append(SubStep(ex_id=_ex_id, status="done",
                                        latency_ms=_lat, calls=_calls))
        _audit(state, "vision", _ex_id, vision_mod.MODEL,
               vision_mod.PROMPT_VERSION, _ex_id, _lat, 0, 0, _cost)
    try:
        _segments_path(state.case_id).write_text(
            json.dumps(_segments, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    _fold_calls(_vision_substeps, prior_vision_calls)
    vision_step.substeps = _vision_substeps
    _vision_latency = int((time.perf_counter() - vision_started) * 1000)
    _vision_ok = sum(1 for s in _segments if s.get("status") == "ok")
    _vision_none = sum(1 for s in _segments if s.get("status") == "not_found")
    _vision_skip = sum(1 for s in _segments if s.get("status") == "skipped")
    _vision_hold = sum(1 for s in _segments if s.get("status") == "hold")
    _vision_note = f"{_vision_ok}개 검출"
    if _vision_none:
        _vision_note += f", {_vision_none}개 미검출"
    if _vision_skip:
        _vision_note += f", {_vision_skip}개 건너뜀(영상)"
    if _vision_hold:
        _vision_note += f", {_vision_hold}개 오류"
    _mark_done(vision_step, _vision_latency, 1, _vision_cost, _vision_note)
    save_case(state)


    # organizing
    state.state = "ORGANIZING"
    organizing_step = state.step("organizing")
    _mark_running(organizing_step)
    save_case(state)
    phase_started = time.perf_counter()
    all_ex_ids = [record.ex_id for record in state.evidence]
    # INT-3 B6: the schema-retry spend (first call + retry) stays in
    # the step cost on success and on every failure below.
    first_org: Dict[str, Any] = {}
    try:
        output = organizer(
            case_id=state.case_id, readings=readings,
            meta_mode=deps.meta_mode(), run_id=state.case_id,
            ex_ids=all_ex_ids,
        )
        try:
            review = validate_review(output.get("review"))
        except ValueError:
            first_org = {
                "cost_usd": output.get("cost_usd", 0) or 0,
                "latency_ms": output.get("latency_ms", 0) or 0,
                "attempts": output.get("attempts", 0) or 0,
            }
            # fix-cost review: saved, so a raw error in the retry (run_case's
            # general handler reloads the case) keeps the first call.
            _set_spend(organizing_step, float(first_org["cost_usd"]))
            _set_calls(organizing_step, int(first_org["attempts"]))
            save_case(state)
            retry_out: Any = None
            try:
                retry_out = organizer(
                    case_id=state.case_id, readings=readings,
                    meta_mode=deps.meta_mode(), run_id=state.case_id,
                    ex_ids=all_ex_ids,
                )
                review = validate_review(retry_out.get("review"))
            except (deps.FixtureNotFound, deps.BudgetError, AgentSchemaError,
                    deps.MissingKeyError) as exc:
                _mark_hold_from_partial(organizing_step, exc,
                                         first_org or None)
                return _agent_failed_hold(state, "organizing", exc)
            except ValueError as exc:
                retry_spend = retry_out if isinstance(retry_out, dict) else {}
                _mark_hold_from_partial(
                    organizing_step, exc,
                    {"cost_usd": (first_org.get("cost_usd", 0) or 0)
                     + (retry_spend.get("cost_usd", 0) or 0),
                     "latency_ms": (first_org.get("latency_ms", 0) or 0)
                     + (retry_spend.get("latency_ms", 0) or 0),
                     "attempts": (first_org.get("attempts", 0) or 0)
                     + (retry_spend.get("attempts", 0) or 0)})
                return _hold(state, "organizing", "schema_failed",
                              f"사실 정리 출력 형식이 맞지 않습니다: {exc}")
            output = retry_out
            output["_retried"] = True
            for key in ("cost_usd", "latency_ms", "attempts"):
                output[key] = ((output.get(key, 0) or 0)
                               + (first_org.get(key, 0) or 0))
    except (deps.FixtureNotFound, deps.BudgetError, AgentSchemaError,
            deps.MissingKeyError) as exc:
        _mark_hold_from_partial(organizing_step, exc, first_org or None)
        return _agent_failed_hold(state, "organizing", exc)
    except ValueError as exc:
        _mark_hold_from_partial(organizing_step, exc, first_org or None)
        return _hold(state, "organizing", "schema_failed",
                      f"사실 정리 출력 형식이 맞지 않습니다: {exc}")
    cost = float(output.get("cost_usd", 0.0) or 0.0)
    attempts = int(output.get("attempts", 2 if output.get("_retried") else 1))
    latency_ms = int((time.perf_counter() - phase_started) * 1000)
    state.review = review
    field_count = len(review.get("fields", []))
    conflict_count = len(review.get("conflicts", []))
    question_count = len(review.get("questions", []))
    _mark_done(organizing_step, latency_ms, attempts, cost,
               f"필드 {field_count}개, 충돌 {conflict_count}, 질문 {question_count}")
    _audit(state, "organizing", None, str(output.get("model") or "muse-spark-1.3"),
           output.get("prompt_version"),
           sha_short(json.dumps(readings, ensure_ascii=False, sort_keys=True)),
           latency_ms, int(output.get("tokens_in", 0) or 0),
           int(output.get("tokens_out", 0) or 0), cost)
    save_case(state)

    return _run_privacy_flow(state)


def _run_privacy_flow(state: CaseState) -> CaseState:
    """M4a privacy: redaction plan + pixel copies + leak check (rule).

    Also the resume target of a ``privacy_leak`` HOLD (L3): ``POST /run``
    re-executes from the redaction stage with the saved readings/segments.
    """
    from app.agents import privacy_guard as privacy_mod

    state.meta_mode = deps.meta_mode()
    privacy_step = state.step("privacy")
    _mark_running(privacy_step)
    save_case(state)
    _privacy_started = time.perf_counter()
    _preview_paths: dict = {}
    _preview_sizes: dict = {}
    for _record in state.evidence:
        try:
            _ppath = intake_mod.preview_path(state, _record)
            _psize = intake_mod.preview_size(state, _record)
        except OSError:
            _ppath, _psize = None, None
        if _ppath is not None and _psize is not None:
            _preview_paths[str(_record.ex_id)] = _ppath
            _preview_sizes[str(_record.ex_id)] = (int(_psize[0]), int(_psize[1]))
    _segments_for_privacy = load_segments(state.case_id)
    _privacy_out = privacy_mod.run_privacy(
        state.case_id, list(state.evidence), list(state.readings),
        _segments_for_privacy, _preview_paths, _preview_sizes,
        files_dir(state.case_id))
    try:
        _redactions_path(state.case_id).write_text(
            json.dumps(_privacy_out, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    _privacy_latency = int((time.perf_counter() - _privacy_started) * 1000)
    _plan_count = len(_privacy_out.get("plan", []) or [])
    _leak = _privacy_out.get("leak_check", {}) or {}
    _audit(state, "privacy", None, None, None,
           sha_short(json.dumps(_privacy_out.get("plan", []),
                                ensure_ascii=False, sort_keys=True)),
           _privacy_latency, 0, 0, 0.0)
    if str(_leak.get("status", "pass")) == "fail":
        _mark_hold(privacy_step, _privacy_latency,
                   note=f"가림 {_plan_count}개, 누출 검사 실패")
        _recompute_run_cost(state)
        save_case(state)
        return _hold(state, "privacy", "privacy_leak",
                      "가린 사본에서 누출 검사가 실패했습니다.")
    _mark_done(privacy_step, _privacy_latency, 1, 0.0,
               f"가림 {_plan_count}개, 누출 검사 통과")
    save_case(state)
    checkpoint = state.step("checkpoint_1")
    checkpoint.status = "running"
    checkpoint.started_at = utc_now_iso()
    checkpoint.note = "사실값 확인과 강조할 발화 선택"
    state.state = "CHECKPOINT_1"
    _recompute_run_cost(state)
    return save_case(state)


def _hold_fields_from_messages(messages: List[str]) -> List[str]:
    fields: List[str] = []
    for message in messages:
        if "확인할 칸:" in message:
            tail = message.split("확인할 칸:", 1)[1].strip()
            if tail and tail not in fields:
                fields.append(tail)
    return fields


_CALC_FIELD_LABELS = {
    "principal": "원금",
    "interest_rate": "이율",
    "loan_date": "대여일",
    "due_date": "변제기",
    "repayments": "변제 내역",
    "creditor_name": "채권자 이름",
    "debtor_name": "채무자 이름",
    "creditor_address": "채권자 주소",
    "debtor_address": "채무자 주소",
    "creditor_phone": "채권자 연락처",
    "debtor_phone": "채무자 연락처",
}


def _confirmed_field_for(loc: Any) -> str:
    """pydantic error location -> confirmed-facts field name (B5)."""
    parts = tuple(str(p) for p in (loc or ()))
    if not parts:
        return ""
    head = parts[0]
    if head == "principal_amount":
        return "principal"
    if head == "agreed_interest_rate":
        return "interest_rate"
    if head in ("loan_date", "due_date", "repayments", "transaction_kind"):
        return head
    if head in ("creditor", "debtor") and len(parts) > 1:
        sub = {"name": "name", "address": "address",
               "phone": "phone"}.get(parts[1], "")
        if sub:
            return f"{head}_{sub}"
    return ""


def _calc_value_hold(state: CaseState, exc: BaseException) -> CaseState:
    """missing_facts HOLD for bad confirmed values (INT-3 B5).

    The raw error text (pydantic "validation error", Decimal
    "ConversionSyntax", ...) never reaches the HOLD message: only
    field labels and model-level Korean notes are shown.
    """
    fields: List[str] = []
    notes: List[str] = []
    errors = None
    try:
        errors = exc.errors() if callable(getattr(exc, "errors", None)) else None
    except Exception:
        errors = None
    if errors:
        for err in errors:
            if not isinstance(err, dict):
                continue
            loc = tuple(err.get("loc", ()))
            name = _confirmed_field_for(loc)
            if name and name not in fields:
                fields.append(name)
            if not loc:
                msg = str(err.get("msg", ""))
                if any("\uac00" <= ch <= "\ud7a3" for ch in msg):
                    if msg not in notes:
                        notes.append(msg)
    if notes:
        message = " ".join(notes)
        if not fields:
            fields = ["due_date"]
    elif fields:
        labels = [_CALC_FIELD_LABELS.get(name, name) for name in fields]
        message = f"확정값을 확인해 주세요: {', '.join(labels)}."
    else:
        message = "입력값이 맞지 않습니다."
    return _hold(state, "calculating", "missing_facts", message, fields)


def _build_inputs_for_drafter(
    state: CaseState,
    confirmed: Dict[str, Any],
    calculation: Dict[str, Any],
    readings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    fields = confirmed.get("fields", {}) or {}
    values = deps.build_slot_values(fields, calculation)
    utterances = []
    for entry in (state.review or {}).get("utterances", []) or []:
        if not isinstance(entry, dict):
            continue
        utterances.append({
            "ref": f"{entry.get('ex_id')}:{entry.get('item_id')}",
            "speaker": entry.get("speaker"),
            "text": entry.get("text"),
            "tags": entry.get("tags", []),
        })
    quotes = deps.build_quotes(readings)
    highlights = []
    for ref in confirmed.get("highlight", []) or []:
        verbatim = quotes.get(f"quote:{ref}")
        if verbatim is not None:
            highlights.append({"ref": ref, "text": verbatim.strip('"')})
    evidence = []
    roles = confirmed.get("evidence_roles", {}) or {}
    for record in state.evidence:
        evidence.append({
            "ex_id": record.ex_id, "label": record.label,
            "filename": record.filename, "kind": record.kind,
            "role": roles.get(record.ex_id, "other"),
        })
    return {
        "slots": {name: SLOT_DESCRIPTIONS.get(name, name)
                  for name in draft_rules_mod.drafter_allowed_slots(values)},
        "utterances": utterances,
        "highlights": highlights,
        "evidence": evidence,
    }


def _run_calc_flow(state: CaseState) -> CaseState:
    state.meta_mode = deps.meta_mode()
    confirmed = state.confirmed_facts or {}
    fields = confirmed.get("fields", {}) or {}
    roles = confirmed.get("evidence_roles", {}) or {}
    try:
        as_of = date.fromisoformat(str(confirmed.get("as_of")).strip())
    except ValueError:
        return _hold(state, "calculating", "missing_facts", "기준일(as_of)이 없습니다.",
                      ["as_of"])

    # calculating (G2/G4 via verify_and_reconcile + calculate_kr)
    calculating_step = state.step("calculating")
    _mark_running(calculating_step)
    save_case(state)
    phase_started = time.perf_counter()
    try:
        loan_fact = deps.build_loan_fact(
            fields, roles, [record.model_dump() for record in state.evidence]
        )
        calc = deps.calculate_kr(loan_fact, as_of)
        verification = deps.VerificationGateService.verify_and_reconcile(
            loan_fact=loan_fact,
            claim_draft=deps.synthetic_claim_draft(
                loan_fact, calc.remaining_principal
            ),
            target_date=as_of,
        )
    except ValueError as exc:
        return _calc_value_hold(state, exc)
    latency_ms = int((time.perf_counter() - phase_started) * 1000)
    if verification.missing_requirements:
        for message in verification.missing_requirements:
            candidate = HoldReason(
                step="calculating", code="missing_facts", message=message,
                fields=_hold_fields_from_messages([message]),
            )
            if not any(r.step == candidate.step and r.code == candidate.code
                       and r.message == candidate.message
                       for r in state.hold_reasons):
                state.hold_reasons.append(candidate)
        state.state = "HOLD"
        _mark_hold(calculating_step, latency_ms)
        _recompute_run_cost(state)
        return save_case(state)
    calculation_json = deps.calculation_to_json(calc)
    state.calculation = calculation_json
    _audit(state, "calculating", None, None, None,
           sha_short(json.dumps(confirmed, ensure_ascii=False, sort_keys=True)),
           latency_ms, 0, 0, 0.0)
    _mark_done(calculating_step, latency_ms, 1, 0.0,
               f"남은 원금 {int(calc.remaining_principal):,}원")
    save_case(state)

    # drafting <-> verifying (G1a + G3 + naming + DRAFT, max 2 revisions)
    drafter = get_agent("drafter")
    drafting_step = state.step("drafting")
    verifying_step = state.step("verifying")
    state.state = "DRAFTING"
    _mark_running(drafting_step)
    _mark_running(verifying_step)
    save_case(state)
    phase_started = time.perf_counter()

    values = deps.build_slot_values(fields, calculation_json)
    allowed = draft_rules_mod.drafter_allowed_slots(values)
    parties = [str(fields.get("creditor_name", "") or ""),
               str(fields.get("debtor_name", "") or "")]
    ex_ids = [record.ex_id for record in state.evidence]
    quotes = deps.build_quotes(state.readings)
    draft_inputs = _build_inputs_for_drafter(state, confirmed, calculation_json,
                                             state.readings)
    revisions: List[Dict[str, Any]] = []
    feedback: Optional[List[Dict[str, Any]]] = None
    final_gates: Optional[List[Any]] = None
    final_sentences: Optional[List[Dict[str, Any]]] = None
    draft_cost = 0.0
    draft_attempts = 0
    draft_latency = 0

    def _draft_hold_with_spend(exc: BaseException) -> None:
        # INT-3 B6: attempts so far plus the failed call's spend.
        part = _partial_spend(exc)
        _mark_hold(drafting_step,
                   draft_latency + int(part.get("latency_ms", 0) or 0),
                   cost=(draft_cost
                         + float(part.get("cost_usd", 0.0) or 0.0)),
                   calls=draft_attempts + int(part.get("attempts", 0) or 0))

    def _keep_draft_progress() -> None:
        # fix-cost review: save each round's spend, so a raw error in a
        # later round (run_case's general handler reloads the case)
        # keeps the rounds already billed.
        _set_spend(drafting_step, draft_cost)
        _set_calls(drafting_step, draft_attempts)
        save_case(state)

    try:
        for attempt in range(3):
            try:
                output = drafter(
                    case_id=state.case_id, draft_inputs=draft_inputs,
                    findings=feedback, meta_mode=deps.meta_mode(),
                    run_id=state.case_id,
                )
            except (deps.FixtureNotFound, deps.BudgetError, AgentSchemaError,
                    deps.MissingKeyError) as exc:
                _draft_hold_with_spend(exc)
                return _agent_failed_hold(state, "drafting", exc)
            draft_attempts += int(output.get("attempts", 1) or 1)
            draft_latency += int(output.get("latency_ms", 0) or 0)
            draft_cost += float(output.get("cost_usd", 0.0) or 0.0)
            _audit(state, "drafting", None,
                   str(output.get("model") or "muse-spark-1.3"),
                   output.get("prompt_version"),
                   sha_short(json.dumps(draft_inputs, ensure_ascii=False, sort_keys=True)
                             + json.dumps(feedback or [], ensure_ascii=False)),
                   int(output.get("latency_ms", 0) or 0),
                   int(output.get("tokens_in", 0) or 0),
                   int(output.get("tokens_out", 0) or 0),
                   float(output.get("cost_usd", 0.0) or 0.0))
            _keep_draft_progress()
            try:
                sentences = validate_draft_sentences(output.get("sentences"), ex_ids)
            except ValueError:
                retry_out: Any = None
                try:
                    retry_out = drafter(
                        case_id=state.case_id, draft_inputs=draft_inputs,
                        findings=feedback, meta_mode=deps.meta_mode(),
                        run_id=state.case_id,
                    )
                    sentences = validate_draft_sentences(
                        retry_out.get("sentences"), ex_ids)
                    draft_attempts += int(retry_out.get("attempts", 1) or 1)
                    draft_latency += int(retry_out.get("latency_ms", 0) or 0)
                    draft_cost += float(retry_out.get("cost_usd", 0.0) or 0.0)
                    _audit(state, "drafting", None,
                           str(retry_out.get("model") or "muse-spark-1.3"),
                           retry_out.get("prompt_version"),
                           sha_short(json.dumps(draft_inputs, ensure_ascii=False,
                                                sort_keys=True)
                                     + json.dumps(feedback or [], ensure_ascii=False)),
                           int(retry_out.get("latency_ms", 0) or 0),
                           int(retry_out.get("tokens_in", 0) or 0),
                           int(retry_out.get("tokens_out", 0) or 0),
                           float(retry_out.get("cost_usd", 0.0) or 0.0))
                except (deps.FixtureNotFound, deps.BudgetError,
                        AgentSchemaError, deps.MissingKeyError) as exc:
                    _draft_hold_with_spend(exc)
                    return _agent_failed_hold(state, "drafting", exc)
                except ValueError as exc:
                    if isinstance(retry_out, dict):
                        draft_attempts += int(retry_out.get("attempts", 1) or 1)
                        draft_latency += int(retry_out.get("latency_ms", 0) or 0)
                        draft_cost += float(retry_out.get("cost_usd", 0.0) or 0.0)
                    _mark_hold(drafting_step, draft_latency, cost=draft_cost,
                               calls=draft_attempts)
                    return _hold(state, "drafting", "schema_failed",
                                  f"문안 출력 형식이 맞지 않습니다: {exc}")
            _set_spend(drafting_step, draft_cost)
            _set_calls(drafting_step, draft_attempts)
            state.state = "VERIFYING"
            save_case(state)  # INT-3 B3: polling must see VERIFYING
            g1a = deps.check_g1a_case(sentences, allowed, parties, ex_ids)
            g3 = deps.check_g3_case(sentences, ex_ids)
            naming = deps.check_naming_case(sentences)
            draft_gate = draft_rules_mod.check_draft_rules(sentences, sourced_slots=draft_rules_mod.sourced_slots_from_review(state.review))
            quote_findings = _unresolved_quotes(sentences, quotes)
            if quote_findings:
                g1a.findings.extend(quote_findings)
                g1a.status = "fail"
            if (g1a.status == "pass" and g3.status == "pass"
                    and naming.status == "pass"
                    and draft_gate.status == "pass"):
                final_gates = [g1a, g3, naming, draft_gate]
                final_sentences = sentences
                break
            state.state = "DRAFTING"
            revisions.append({
                "round": attempt + 1,
                "gate_results": [
                    g1a.model_dump(mode="json"), g3.model_dump(mode="json"),
                    naming.model_dump(mode="json"),
                    draft_gate.model_dump(mode="json"),
                ],
            })
            feedback = []
            for gate in (g1a, g3, naming, draft_gate):
                for finding in gate.findings:
                    dumped = finding.model_dump(mode="json")
                    dumped["gate"] = gate.gate
                    feedback.append(dumped)
        else:
            failed_ms = int((time.perf_counter() - phase_started) * 1000)
            _mark_hold(drafting_step, draft_latency, cost=draft_cost,
                       calls=draft_attempts)
            _mark_hold(verifying_step, failed_ms)
            # fix-cost: the drafter spend sits on drafting only; passing
            # it to the verifying hold counted it twice.
            return _hold(state, "verifying", "revision_exceeded",
                         "문안 수정 2회를 넘겨도 지적이 남았습니다.")
    finally:
        pass
    assert final_gates is not None and final_sentences is not None
    latency_ms = int((time.perf_counter() - phase_started) * 1000)
    _mark_done(drafting_step, draft_latency or latency_ms, draft_attempts,
               draft_cost, f"{len(final_sentences)}개 문장")
    _mark_done(verifying_step, latency_ms, len(revisions) + 1, 0.0,
               "G1a·G3·명칭·DRAFT 통과" if not revisions else f"{len(revisions)}회 수정 후 통과")

    by_sentence: Dict[str, List[Dict[str, Any]]] = {}
    for gate in final_gates:
        for finding in gate.findings:
            by_sentence.setdefault(finding.sentence_id, []).append(
                finding.model_dump(mode="json")
            )
    stored_sentences = []
    for entry in final_sentences:
        rendered = deps.render_sentence(entry["text_with_slots"], values, quotes)
        stored_sentences.append({
            "sentence_id": entry["sentence_id"], "type": entry["type"],
            "text_with_slots": entry["text_with_slots"],
            "rendered_text": rendered, "ex_refs": entry["ex_refs"],
            "findings": by_sentence.get(entry["sentence_id"], []),
            "approved": False,
        })
    g2 = _g2_from_verification(verification)
    g4 = _g4_from_calculation(calculation_json)
    state.drafts = {
        "calculation": calculation_json,
        "gate_results": [
            g2.model_dump(mode="json"), g4.model_dump(mode="json"),
            final_gates[0].model_dump(mode="json"),
            final_gates[1].model_dump(mode="json"),
            final_gates[2].model_dump(mode="json"),
            final_gates[3].model_dump(mode="json"),
        ],
        "sentences": stored_sentences,
        "revision_rounds": len(revisions),
        "revisions": revisions,
    }
    approval = state.step("draft_approval")
    approval.status = "running"
    approval.started_at = utc_now_iso()
    approval.note = "문장별 수정·승인"
    state.state = "DRAFT_APPROVAL"
    _recompute_run_cost(state)
    return save_case(state)


def _g2_from_verification(verification: Any) -> Any:
    """G2 (required slots) from the real verification result (P8)."""
    missing = list(getattr(verification, "missing_requirements", []) or [])
    if not missing:
        return deps.GateResult(gate="G2", status="pass", findings=[])
    findings = [
        deps.Finding(
            sentence_id="",
            field="calculation",
            message=text,
            fix_hint="확인할 칸을 채우세요.",
        )
        for text in missing
    ]
    return deps.GateResult(gate="G2", status="fail", findings=findings)


def _g4_from_calculation(calculation: Dict[str, Any]) -> Any:
    """G4 (limits) from the real calculation output (P8)."""
    limit = (calculation or {}).get("limit_check") or {}
    if not limit.get("exceeded"):
        return deps.GateResult(gate="G4", status="pass", findings=[])
    compared = limit.get("compared_amount", "")
    threshold = limit.get("threshold", "")
    message = limit.get("message") or (
        f"청구 금액 {compared}원이 기준 {threshold}원을 넘습니다.")
    return deps.GateResult(
        gate="G4", status="fail",
        findings=[deps.Finding(
            sentence_id="", field="calculation", message=str(message),
            fix_hint="청구 범위를 확인하세요.")],
    )


_QUOTE_RE = re.compile(r"\{\{\s*(quote:[A-Za-z0-9_]+:[A-Za-z0-9_]+)\s*\}\}")


def _unresolved_quotes(
    sentences: List[Dict[str, Any]], quotes: Dict[str, str]
) -> List[Any]:
    findings: List[Any] = []
    for entry in sentences:
        for match in _QUOTE_RE.finditer(entry.get("text_with_slots", "")):
            key = match.group(1)
            if key not in quotes and key.split(":", 1)[1] not in quotes:
                findings.append(deps.Finding(
                    sentence_id=entry["sentence_id"],
                    field="text_with_slots",
                    message=f"인용 원문이 없습니다: {key}",
                    fix_hint="판독에 있는 발화만 인용하세요.",
                ))
    return findings


def _run_package_flow(state: CaseState) -> CaseState:
    from app.agents import packager as packager_mod

    drafts = state.drafts or {}
    sentences = drafts.get("sentences", []) or []
    if not sentences or any(not entry.get("approved") for entry in sentences):
        raise WrongState("unapproved_sentences", "승인되지 않은 문장이 있습니다.")
    confirmed = state.confirmed_facts or {}
    fields = confirmed.get("fields", {}) or {}
    values = deps.build_slot_values(fields, state.calculation or {})
    allowed = draft_rules_mod.drafter_allowed_slots(values)
    parties = [str(fields.get("creditor_name", "") or ""),
               str(fields.get("debtor_name", "") or "")]
    ex_ids = [record.ex_id for record in state.evidence]
    slim = [{"sentence_id": s["sentence_id"], "type": s["type"],
             "text_with_slots": s["text_with_slots"], "ex_refs": s["ex_refs"]}
            for s in sentences]
    g1a = deps.check_g1a_case(slim, allowed, parties, ex_ids)
    g3 = deps.check_g3_case(slim, ex_ids)
    naming = deps.check_naming_case(slim)
    draft_gate = draft_rules_mod.check_draft_rules(slim, sourced_slots=draft_rules_mod.sourced_slots_from_review(state.review))
    if (g1a.status != "pass" or g3.status != "pass"
            or naming.status != "pass" or draft_gate.status != "pass"):
        raise WrongState("unapproved_sentences", "검사를 통과하지 못한 문장이 있습니다.")

    try:
        approval_step = state.step("draft_approval")
        approval_step.status = "done"
        approval_step.ended_at = utc_now_iso()
    except KeyError:
        pass
    state.state = "PACKAGING"
    packaging_step = state.step("packaging")
    _mark_running(packaging_step)
    save_case(state)
    phase_started = time.perf_counter()
    try:
        package = packager_mod.build_package(state)
    except packager_mod.NamingViolation as exc:
        return _hold(state, "packaging", "naming_violation", str(exc))
    latency_ms = int((time.perf_counter() - phase_started) * 1000)
    state.package = package
    g1b_failed = [entry for entry in package.get("gate_results", []) or []
                  if entry.get("gate") == "G1b"
                  and entry.get("status") == "fail"]
    if g1b_failed:
        # INT-3 task 3: values/names/leak failures hold after packaging;
        # fix, then POST /run repackages. INT-3c F1: the failed PDFs are
        # deleted so a leak can never be downloaded.
        from pathlib import Path as _Path

        for file_entry in package.get("files", []) or []:
            name = _Path(str(file_entry.get("name", "") or "")).name
            if name.endswith(".pdf"):
                (_Path(files_dir(state.case_id)) / name).unlink(missing_ok=True)
        docs = sorted({str(finding.get("field", ""))
                       for entry in g1b_failed
                       for finding in entry.get("findings", []) or []
                       if finding.get("field")})
        count = sum(len(entry.get("findings", []) or [])
                    for entry in g1b_failed)
        where = "(" + ", ".join(docs) + ")" if docs else ""
        _mark_hold(packaging_step, latency_ms, cost=0.0)
        _audit(state, "packaging", None, None, None,
               sha_short(json.dumps(sentences, ensure_ascii=False,
                                    sort_keys=True)),
               latency_ms, 0, 0, 0.0)
        return _hold(state, "packaging", "g1b_failed",
                      f"최종 검사(G1b)를 통과하지 못했습니다"
                      f"({count}건{where}).",
                      docs)
    _audit(state, "packaging", None, None, None,
           sha_short(json.dumps(sentences, ensure_ascii=False, sort_keys=True)),
           latency_ms, 0, 0, 0.0)
    _mark_done(packaging_step, latency_ms, 1, 0.0, "내용증명 PDF, 전자소송 문구")
    checkpoint = state.step("checkpoint_2")
    checkpoint.status = "running"
    checkpoint.started_at = utc_now_iso()
    checkpoint.note = "최종 서류 확인"
    state.state = "CHECKPOINT_2"
    _recompute_run_cost(state)
    return save_case(state)


# --- PUT /facts ---------------------------------------------------------------------------
REQUIRED_FACT_FIELDS = (
    "creditor_name", "debtor_name", "principal", "loan_date", "due_date",
)
# INT-3 task 7: amount errors carry no internal key; the screen matches
# the field name from missing_requirements instead of the message text.
AMOUNT_ERROR_MESSAGE = "금액은 숫자로 적어 주세요(예: 5,000,000원)"
AMOUNT_POSITIVE_MESSAGE = "금액은 0보다 크게 적어 주세요(예: 5,000,000원)"
KNOWN_FACT_FIELDS = tuple(REVIEW_FIELD_ORDER)
# INT-3 task 3: loan_agreement (차용증) joins the evidence roles.
VALID_ROLES = ("loan_transfer", "repayment", "loan_agreement", "other")


def _has_fullwidth_digits(text: str) -> bool:
    return any("\uff10" <= ch <= "\uff19" for ch in text)


def _is_ascii_digits(text: str) -> bool:
    cleaned = text.replace(",", "")
    return bool(cleaned) and all("0" <= ch <= "9" for ch in cleaned)


def _validate_facts_body(
    body: Any, state: CaseState
) -> Dict[str, Any]:
    if not isinstance(body, dict):
        raise BadRequest("bad_request", "요청 본문이 올바르지 않습니다.")
    for key in ("fields", "evidence_roles", "highlight", "as_of"):
        if key not in body:
            raise BadRequest("missing_facts", f"요청에 {key}이(가) 없습니다.",
                             missing=[key])
    fields = body["fields"]
    roles = body["evidence_roles"]
    highlight = body["highlight"]
    as_of = body["as_of"]
    if not isinstance(fields, dict):
        raise BadRequest("bad_request", "fields가 올바르지 않습니다.")
    if not isinstance(roles, dict):
        raise BadRequest("bad_request", "evidence_roles가 올바르지 않습니다.")
    if not isinstance(highlight, list):
        raise BadRequest("bad_request", "highlight가 올바르지 않습니다.")
    # INT-3 B5: report every missing required field (not just the first).
    absent = [name for name in REQUIRED_FACT_FIELDS
              if fields.get(name) is None
              or (isinstance(fields.get(name), str)
                  and not str(fields.get(name)).strip())]
    if absent:
        raise BadRequest("missing_facts",
                         f"확정값에 {', '.join(absent)}이(가) 없습니다.",
                         missing=absent)
    principal = str(fields.get("principal", "")).strip()
    if _has_fullwidth_digits(principal) or not _is_ascii_digits(principal):
        raise BadRequest("bad_request", AMOUNT_ERROR_MESSAGE,
                         missing=["principal"])
    if int(principal.replace(",", "")) <= 0:
        raise BadRequest("bad_request", AMOUNT_POSITIVE_MESSAGE,
                         missing=["principal"])
    for name in ("loan_date", "due_date"):
        try:
            date.fromisoformat(str(fields.get(name)).strip())
        except ValueError:
            raise BadRequest("bad_request", f"{name}은 YYYY-MM-DD여야 합니다.")
    interest = fields.get("interest_rate")
    if interest is not None and str(interest).strip():
        raw_interest = str(interest).strip()
        if _has_fullwidth_digits(raw_interest):
            raise BadRequest("bad_request", "interest_rate에 전각 숫자를 쓸 수 없습니다.")
        try:
            parsed = Decimal(raw_interest.rstrip("%").strip())
        except Exception:
            raise BadRequest("bad_request", "interest_rate는 숫자 또는 null이어야 합니다.")
        if parsed.is_nan() or parsed.is_infinite():
            raise BadRequest("bad_request", "interest_rate는 숫자 또는 null이어야 합니다.")
        if parsed < 0:
            raise BadRequest("bad_request", "interest_rate는 0 이상이어야 합니다.")
    kind = fields.get("transaction_kind", "civil")
    if str(kind).strip().lower() not in ("civil", "commercial"):
        raise BadRequest("bad_request", "transaction_kind는 civil|commercial이어야 합니다.")
    repayments = fields.get("repayments", [])
    if repayments is None:
        repayments = []
    if not isinstance(repayments, list):
        raise BadRequest("bad_request", "repayments는 목록이어야 합니다.")
    for entry in repayments:
        if not isinstance(entry, dict):
            raise BadRequest("bad_request", "repayments 항목이 올바르지 않습니다.")
        try:
            date.fromisoformat(str(entry.get("date")).strip())
        except (ValueError, AttributeError):
            raise BadRequest("bad_request", "repayments.date는 YYYY-MM-DD여야 합니다.")
        amount = str(entry.get("amount", "")).strip()
        if _has_fullwidth_digits(amount) or not _is_ascii_digits(amount):
            raise BadRequest("bad_request", AMOUNT_ERROR_MESSAGE,
                             missing=["repayments"])
        if int(amount.replace(",", "")) <= 0:
            raise BadRequest("bad_request", AMOUNT_POSITIVE_MESSAGE,
                             missing=["repayments"])
    known_ex = {record.ex_id for record in state.evidence}
    for ex_id, role in roles.items():
        if ex_id not in known_ex:
            raise BadRequest("bad_request", f"알 수 없는 증거입니다: {ex_id}")
        if role not in VALID_ROLES:
            raise BadRequest("bad_request", f"역할이 올바르지 않습니다: {role}")
    known_refs = set()
    for reading in state.readings:
        for item in reading.get("items", []) or []:
            known_refs.add(f"{reading.get('ex_id')}:{item.get('item_id')}")
    for ref in highlight:
        if not isinstance(ref, str) or ":" not in ref:
            raise BadRequest("bad_request", f"highlight 형식이 올바르지 않습니다: {ref}")
        if ref not in known_refs:
            raise BadRequest("bad_request", f"판독에 없는 발화입니다: {ref}")
    try:
        date.fromisoformat(str(as_of).strip())
    except ValueError:
        raise BadRequest("bad_request", "as_of는 YYYY-MM-DD여야 합니다.")
    cleaned_fields = {name: fields.get(name) for name in KNOWN_FACT_FIELDS if name in fields}
    for name in REQUIRED_FACT_FIELDS:
        cleaned_fields.setdefault(name, fields.get(name))
    if "repayments" not in cleaned_fields:
        cleaned_fields["repayments"] = repayments
    full_roles = {record.ex_id: "other" for record in state.evidence}
    full_roles.update({str(key): str(value) for key, value in roles.items()})
    # M4a 6a: optional redaction confirmation (default False).
    redaction_confirmed = body.get("redaction_confirmed", False)
    if redaction_confirmed is None:
        redaction_confirmed = False
    if not isinstance(redaction_confirmed, bool):
        raise BadRequest("bad_request", "redaction_confirmed는 true|false여야 합니다.")
    return {
        "fields": cleaned_fields,
        "evidence_roles": full_roles,
        "highlight": [str(ref) for ref in highlight],
        "as_of": str(as_of).strip(),
        "redaction_confirmed": bool(redaction_confirmed),
    }


def apply_facts(case_id: str, body: Any) -> CaseState:
    lock = _run_lock(case_id)
    if not lock.acquire(blocking=False):
        raise ConcurrentRun(case_id)
    try:
        state = get_case(case_id)
        if (state.state != "CHECKPOINT_1"
                and not hold_from_calc_or_draft(state)
                and not hold_from_packaging_fixable(state)):
            raise WrongState("wrong_state",
                             f"지금 상태({state.state})에서는 확정값을 저장할 수 없습니다.")
        cleaned = _validate_facts_body(body, state)
        state.confirmed_facts = cleaned
        state.calculation = None
        state.drafts = None
        state.package = None
        state.hold_reasons = []
        try:
            done_step = state.step("checkpoint_1")
            done_step.status = "done"
            done_step.ended_at = utc_now_iso()
        except KeyError:
            pass
        _reset_from(state, "calculating")
        state.state = "CALCULATING"
        state.meta_mode = deps.meta_mode()
        _recompute_run_cost(state)
        return save_case(state)
    finally:
        lock.release()


# --- PUT /drafts ----------------------------------------------------------------------------
def apply_drafts(case_id: str, body: Any) -> Dict[str, Any]:
    lock = _run_lock(case_id)
    if not lock.acquire(blocking=False):
        raise ConcurrentRun(case_id)
    try:
        state = get_case(case_id)
        # INT-3 task 3: a g1b_failed HOLD re-enters here for sentence
        # fixes (naming violations need PUT /facts, not sentences).
        from_g1b = state.state == "HOLD" and hold_from_g1b(state)
        if state.state != "DRAFT_APPROVAL" and not from_g1b:
            raise WrongState("wrong_state",
                             f"지금 상태({state.state})에서는 문장을 고칠 수 없습니다.")
        if not isinstance(body, dict) or "sentences" not in body:
            raise BadRequest("bad_request", "요청에 sentences가 없습니다.")
        updates = body["sentences"]
        if not isinstance(updates, list):
            raise BadRequest("bad_request", "sentences는 목록이어야 합니다.")
        drafts = state.drafts or {}
        stored = {entry["sentence_id"]: dict(entry)
                  for entry in drafts.get("sentences", []) or []}
        if not stored:
            raise WrongState("wrong_state", "초안이 없습니다.")
        edited: set = set()
        for entry in updates:
            if not isinstance(entry, dict) or "sentence_id" not in entry:
                raise BadRequest("bad_request", "sentences 항목에 sentence_id가 없습니다.")
            sid = str(entry["sentence_id"])
            if sid not in stored:
                raise BadRequest("bad_request", f"알 수 없는 문장입니다: {sid}")
            if "text_with_slots" in entry and entry["text_with_slots"] is not None:
                if not isinstance(entry["text_with_slots"], str):
                    raise BadRequest("bad_request", "text_with_slots는 문자열이어야 합니다.")
                if entry["text_with_slots"] != stored[sid].get("text_with_slots"):
                    edited.add(sid)
                stored[sid]["text_with_slots"] = entry["text_with_slots"]
            if "approved" in entry and entry["approved"] is not None:
                if not isinstance(entry["approved"], bool):
                    raise BadRequest("bad_request", "approved는 true|false여야 합니다.")
                stored[sid]["_requested_approved"] = entry["approved"]
        confirmed = state.confirmed_facts or {}
        fields = confirmed.get("fields", {}) or {}
        values = deps.build_slot_values(fields, state.calculation or {})
        allowed = draft_rules_mod.drafter_allowed_slots(values)
        parties = [str(fields.get("creditor_name", "") or ""),
                   str(fields.get("debtor_name", "") or "")]
        ex_ids = [record.ex_id for record in state.evidence]
        quotes = deps.build_quotes(state.readings)
        slim = [{"sentence_id": sid, "type": stored[sid]["type"],
                 "text_with_slots": stored[sid]["text_with_slots"],
                 "ex_refs": stored[sid]["ex_refs"]} for sid in stored]
        g1a = deps.check_g1a_case(slim, allowed, parties, ex_ids)
        g3 = deps.check_g3_case(slim, ex_ids)
        naming = deps.check_naming_case(slim)
        draft_gate = draft_rules_mod.check_draft_rules(slim, sourced_slots=draft_rules_mod.sourced_slots_from_review(state.review))
        quote_findings = _unresolved_quotes(slim, quotes)
        if quote_findings:
            g1a.findings.extend(quote_findings)
            g1a.status = "fail"
        by_sentence: Dict[str, List[Dict[str, Any]]] = {}
        for gate in (g1a, g3, naming, draft_gate):
            for finding in gate.findings:
                by_sentence.setdefault(finding.sentence_id, []).append(
                    finding.model_dump(mode="json")
                )
        ordered = [stored[entry["sentence_id"]] for entry in drafts.get("sentences", [])]
        for entry in ordered:
            sid = entry["sentence_id"]
            findings = by_sentence.get(sid, [])
            entry["findings"] = findings
            if sid in edited and "_requested_approved" not in entry:
                requested: Any = False
            else:
                requested = entry.pop("_requested_approved",
                                      entry.get("approved", False))
            if findings:
                entry["approved"] = False
            else:
                entry["approved"] = bool(requested)
            try:
                entry["rendered_text"] = deps.render_sentence(
                    entry["text_with_slots"], values, quotes
                )
            except ValueError:
                entry["approved"] = False
                if not any(f.get("message") == "슬롯 값을 채울 수 없습니다."
                           for f in entry["findings"]):
                    entry["findings"] = findings + [{
                        "sentence_id": sid, "field": "text_with_slots",
                        "message": "슬롯 값을 채울 수 없습니다.",
                        "fix_hint": "슬롯 이름을 확인하세요.",
                    }]
        gate_results = list(drafts.get("gate_results", []) or [])
        gate_map = {gate.get("gate"): gate for gate in gate_results if isinstance(gate, dict)}
        gate_map["G1a"] = g1a.model_dump(mode="json")
        gate_map["G3"] = g3.model_dump(mode="json")
        gate_map["NAMING"] = naming.model_dump(mode="json")
        gate_map["DRAFT"] = draft_gate.model_dump(mode="json")
        order = ["G2", "G4", "G1a", "G3", "NAMING", "DRAFT"]
        drafts["gate_results"] = [gate_map[name] for name in order if name in gate_map]
        drafts["sentences"] = ordered
        state.drafts = drafts
        if from_g1b:
            state.hold_reasons = [
                reason for reason in state.hold_reasons
                if not (reason.step == "packaging"
                        and reason.code == "g1b_failed")]
            if not state.hold_reasons:
                _reset_from(state, "packaging")
                state.state = "DRAFT_APPROVAL"
        state.meta_mode = deps.meta_mode()
        save_case(state)
        return drafts
    finally:
        lock.release()
