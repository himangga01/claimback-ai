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


def _mark_running(step: StepState) -> None:
    step.status = "running"
    step.started_at = utc_now_iso()
    step.ended_at = None


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
    step.attempts = int(attempts)
    step.cost_usd = fmt_cost(cost)
    if note:
        step.note = note


def _mark_hold(step: StepState, latency_ms: int = 0, note: str = "",
               cost: Optional[float] = None) -> None:
    step.status = "hold"
    step.ended_at = utc_now_iso()
    step.latency_ms = int(latency_ms)
    if cost is not None:
        step.cost_usd = fmt_cost(cost)
    if note:
        step.note = note


def _mark_skipped(step: StepState, note: str = "") -> None:
    step.status = "skipped"
    step.attempts = 0
    step.cost_usd = "0"
    if note:
        step.note = note


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
            entry.attempts = 0
            # cost_usd is kept so HOLD/rollback never loses billed spend.
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
    total = 0.0
    for entry in state.steps:
        try:
            total += float(entry.cost_usd or 0.0)
        except ValueError:
            pass
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
        cleaned.append({
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
        })
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
        if not delete_case(case_id):
            raise CaseNotFound(case_id)
    finally:
        lock.release()


def _resume_step_for_hold(state: CaseState) -> Optional[str]:
    if state.state != "HOLD" or not state.hold_reasons:
        return None
    if not all(r.code == "internal_error" for r in state.hold_reasons):
        return None
    steps = {r.step for r in state.hold_reasons}
    if steps <= {"reading", "organizing", "intake"}:
        return "intake"
    if steps <= {"calculating", "drafting", "verifying"}:
        return "calc"
    if steps <= {"packaging"}:
        return "package"
    return None


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
            }.get(state.state, "reading")
            try:
                current = load_case(case_id)
                if current is not None:
                    state = current
            except Exception:
                pass
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
    save_case(state)
    phase_started = time.perf_counter()

    ordered = sorted(state.evidence, key=lambda r: deps.ex_num(r.ex_id))
    substeps: List[SubStep] = []
    readings: List[Dict[str, Any]] = []
    reading_cost = 0.0
    reading_attempts = 1
    hold_case = False

    def _read_one(record: Any) -> Dict[str, Any]:
        if record.kind == "video":
            return {"ex_id": record.ex_id, "skipped": True}
        started = time.perf_counter()
        try:
            output = reader(
                case_id=state.case_id,
                evidence=record.model_dump(),
                evidence_path=intake_mod.evidence_path(state, record),
                preview_size=intake_mod.preview_size(state, record),
                meta_mode=deps.meta_mode(),
                run_id=state.case_id,
            )
        except (deps.FixtureNotFound, deps.BudgetError, AgentSchemaError) as exc:
            return {"ex_id": record.ex_id, "error": exc,
                    "latency_ms": int((time.perf_counter() - started) * 1000)}
        except Exception as exc:
            return {"ex_id": record.ex_id,
                    "error": AgentSchemaError(f"판독 중 오류: {type(exc).__name__}"),
                    "latency_ms": int((time.perf_counter() - started) * 1000)}
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            items = validate_reading_items(output.get("items"))
        except ValueError:
            # schema retry (fake agents): one more call, then evidence hold
            try:
                output = reader(
                    case_id=state.case_id,
                    evidence=record.model_dump(),
                    evidence_path=intake_mod.evidence_path(state, record),
                    preview_size=intake_mod.preview_size(state, record),
                    meta_mode=deps.meta_mode(),
                    run_id=state.case_id,
                )
                items = validate_reading_items(output.get("items"))
                output["_retried"] = True
            except (deps.FixtureNotFound, deps.BudgetError, AgentSchemaError) as exc:
                return {"ex_id": record.ex_id, "error": exc, "latency_ms": latency_ms}
            except ValueError as exc:
                return {"ex_id": record.ex_id, "error": AgentSchemaError(str(exc)),
                        "latency_ms": latency_ms}
            except Exception as exc:
                return {"ex_id": record.ex_id,
                        "error": AgentSchemaError(
                            f"판독 중 오류: {type(exc).__name__}"),
                        "latency_ms": latency_ms}
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
            if isinstance(exc, (deps.FixtureNotFound, deps.BudgetError)):
                _agent_failed_hold(state, "reading", exc)
                hold_case = True
                substeps.append(SubStep(ex_id=ex_id, status="hold",
                                        latency_ms=result["latency_ms"]))
                continue
            record.status = "hold"
            substeps.append(SubStep(ex_id=ex_id, status="hold",
                                    latency_ms=result["latency_ms"]))
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
                                latency_ms=result["latency_ms"]))
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
    reading_step.substeps = substeps
    state.readings = readings
    reading_step.cost_usd = fmt_cost(reading_cost)
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

    _mark_skipped(state.step("vision"), "이 버전에서는 사용하지 않음")
    save_case(state)

    # organizing
    state.state = "ORGANIZING"
    organizing_step = state.step("organizing")
    _mark_running(organizing_step)
    save_case(state)
    phase_started = time.perf_counter()
    all_ex_ids = [record.ex_id for record in state.evidence]
    try:
        output = organizer(
            case_id=state.case_id, readings=readings,
            meta_mode=deps.meta_mode(), run_id=state.case_id,
            ex_ids=all_ex_ids,
        )
        try:
            review = validate_review(output.get("review"))
        except ValueError:
            output = organizer(
                case_id=state.case_id, readings=readings,
                meta_mode=deps.meta_mode(), run_id=state.case_id,
                ex_ids=all_ex_ids,
            )
            review = validate_review(output.get("review"))
            output["_retried"] = True
    except (deps.FixtureNotFound, deps.BudgetError, AgentSchemaError) as exc:
        return _agent_failed_hold(state, "organizing", exc)
    except ValueError as exc:
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

    _mark_skipped(state.step("privacy"), "이 버전에서는 사용하지 않음")
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
        return _hold(state, "calculating", "missing_facts", str(exc) or "입력값이 맞지 않습니다.")
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
    try:
        for attempt in range(3):
            try:
                output = drafter(
                    case_id=state.case_id, draft_inputs=draft_inputs,
                    findings=feedback, meta_mode=deps.meta_mode(),
                    run_id=state.case_id,
                )
            except (deps.FixtureNotFound, deps.BudgetError, AgentSchemaError) as exc:
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
            try:
                sentences = validate_draft_sentences(output.get("sentences"), ex_ids)
            except ValueError:
                try:
                    output = drafter(
                        case_id=state.case_id, draft_inputs=draft_inputs,
                        findings=feedback, meta_mode=deps.meta_mode(),
                        run_id=state.case_id,
                    )
                    sentences = validate_draft_sentences(output.get("sentences"), ex_ids)
                    draft_attempts += 1
                except (deps.FixtureNotFound, deps.BudgetError,
                        AgentSchemaError) as exc:
                    return _agent_failed_hold(state, "drafting", exc)
                except ValueError as exc:
                    return _hold(state, "drafting", "schema_failed",
                                  f"문안 출력 형식이 맞지 않습니다: {exc}")
            state.state = "VERIFYING"
            g1a = deps.check_g1a_case(sentences, allowed, parties, ex_ids)
            g3 = deps.check_g3_case(sentences, ex_ids)
            naming = deps.check_naming_case(sentences)
            draft_gate = draft_rules_mod.check_draft_rules(sentences)
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
            _mark_hold(drafting_step, draft_latency, cost=draft_cost)
            _mark_hold(verifying_step, failed_ms)
            return _hold(state, "verifying", "revision_exceeded",
                         "문안 수정 2회를 넘겨도 지적이 남았습니다.",
                         cost=draft_cost)
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
    draft_gate = draft_rules_mod.check_draft_rules(slim)
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
KNOWN_FACT_FIELDS = tuple(REVIEW_FIELD_ORDER)
VALID_ROLES = ("loan_transfer", "repayment", "other")


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
    for name in REQUIRED_FACT_FIELDS:
        raw = fields.get(name)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            raise BadRequest("missing_facts", f"확정값에 {name}이(가) 없습니다.",
                             missing=[name])
    principal = str(fields.get("principal", "")).strip()
    if _has_fullwidth_digits(principal):
        raise BadRequest("bad_request", "principal에 전각 숫자를 쓸 수 없습니다.")
    if not _is_ascii_digits(principal):
        raise BadRequest("bad_request", "principal은 숫자 문자열이어야 합니다.")
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
        if _has_fullwidth_digits(amount):
            raise BadRequest("bad_request", "repayments.amount에 전각 숫자를 쓸 수 없습니다.")
        if not _is_ascii_digits(amount):
            raise BadRequest("bad_request", "repayments.amount는 숫자 문자열이어야 합니다.")
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
    return {
        "fields": cleaned_fields,
        "evidence_roles": full_roles,
        "highlight": [str(ref) for ref in highlight],
        "as_of": str(as_of).strip(),
    }


def apply_facts(case_id: str, body: Any) -> CaseState:
    lock = _run_lock(case_id)
    if not lock.acquire(blocking=False):
        raise ConcurrentRun(case_id)
    try:
        state = get_case(case_id)
        if state.state != "CHECKPOINT_1" and not hold_from_calc_or_draft(state):
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
        if state.state != "DRAFT_APPROVAL":
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
        draft_gate = draft_rules_mod.check_draft_rules(slim)
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
        state.meta_mode = deps.meta_mode()
        save_case(state)
        return drafts
    finally:
        lock.release()
