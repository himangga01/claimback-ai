"""Case state: design 4-2 zones on a per-case JSON file (M2a task 2).

Layout: ``backend/data/cases/<case_id>/case.json`` plus ``evidence/`` and
``files/`` subdirectories. Every mutation goes through :func:`save_case`,
which bumps ``version`` and writes atomically (tmp + replace) so a UI poll
during a run always reads a complete file.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.agents.base import AuditRecord

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CASES_ROOT = REPO_ROOT / "backend" / "data" / "cases"

# Patched by tests to a tmp dir (always read via get_cases_root()).
CASES_ROOT: Path = DEFAULT_CASES_ROOT

CASE_ID_ENV = "CASES_DIR"

_SAVE_LOCKS: Dict[str, threading.Lock] = {}
_SAVE_LOCKS_GUARD = threading.Lock()


def get_cases_root() -> Path:
    """Case storage root (tests patch CASES_ROOT; env CASES_DIR wins)."""
    env = os.environ.get(CASE_ID_ENV)
    if env and str(env).strip():
        return Path(str(env).strip())
    return Path(CASES_ROOT)


def _save_lock(case_id: str) -> threading.Lock:
    with _SAVE_LOCKS_GUARD:
        lock = _SAVE_LOCKS.get(case_id)
        if lock is None:
            lock = threading.Lock()
            _SAVE_LOCKS[case_id] = lock
        return lock


def utc_now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def new_case_id() -> str:
    return "case_" + secrets.token_hex(6)


StepStatus = Literal["waiting", "running", "done", "hold", "skipped"]
EvidenceStatus = Literal["ok", "hold", "skipped"]
EvidenceKind = Literal["image", "pdf", "video"]


class EvidenceRecord(BaseModel):
    ex_id: str = "EX1"
    label: str = "갑 제1호증"
    filename: str = ""
    stored_name: str = ""
    sha256: str = ""
    kind: EvidenceKind = "image"
    status: EvidenceStatus = "ok"
    url: str = ""
    preview_url: Optional[str] = None


class SubStep(BaseModel):
    ex_id: str = ""
    status: str = "waiting"
    latency_ms: int = 0


class StepState(BaseModel):
    key: str = ""
    agent: str = ""
    group: str = ""
    model: Optional[str] = None
    status: StepStatus = "waiting"
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    latency_ms: int = 0
    attempts: int = 0
    cost_usd: str = "0"
    note: str = ""
    substeps: List[SubStep] = Field(default_factory=list)


class HoldReason(BaseModel):
    step: str = ""
    code: str = ""
    message: str = ""
    fields: List[str] = Field(default_factory=list)


class CaseState(BaseModel):
    """Design 4-2 zones (M2 thin flow; vision/privacy/timeline skipped)."""

    case_id: str = ""
    jurisdiction: str = "KR"
    state: str = "INTAKE"
    version: int = 0
    meta_mode: str = "replay"
    run_cost_usd: float = 0.0
    evidence: List[EvidenceRecord] = Field(default_factory=list)
    readings: List[Dict[str, Any]] = Field(default_factory=list)
    review: Optional[Dict[str, Any]] = None
    confirmed_facts: Optional[Dict[str, Any]] = None
    calculation: Optional[Dict[str, Any]] = None
    drafts: Optional[Dict[str, Any]] = None
    package: Optional[Dict[str, Any]] = None
    steps: List[StepState] = Field(default_factory=list)
    hold_reasons: List[HoldReason] = Field(default_factory=list)
    audit_log: List[AuditRecord] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def step(self, key: str) -> StepState:
        for entry in self.steps:
            if entry.key == key:
                return entry
        raise KeyError(f"unknown step: {key}")


def case_dir(case_id: str) -> Path:
    return get_cases_root() / case_id


def evidence_dir(case_id: str) -> Path:
    return case_dir(case_id) / "evidence"


def files_dir(case_id: str) -> Path:
    return case_dir(case_id) / "files"


def case_file(case_id: str) -> Path:
    return case_dir(case_id) / "case.json"


def load_case(case_id: str) -> Optional[CaseState]:
    """Load a case, or None when the id is unknown/corrupt."""
    if not case_id or "/" in case_id or "\\" in case_id or ".." in case_id:
        return None
    path = case_file(case_id)
    if not path.exists():
        return None
    try:
        return CaseState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_case(state: CaseState) -> CaseState:
    """Bump version and persist atomically. Returns the state."""
    with _save_lock(state.case_id):
        state.version += 1
        state.updated_at = utc_now_iso()
        target = case_file(state.case_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"case.json.tmp-{os.getpid()}")
        tmp.write_text(
            state.model_dump_json(ensure_ascii=False), encoding="utf-8"
        )
        os.replace(tmp, target)
    return state


def delete_case(case_id: str) -> bool:
    """Remove the whole case directory (uploads + generated files)."""
    if not case_id or "/" in case_id or "\\" in case_id or ".." in case_id:
        return False
    root = case_dir(case_id)
    if not root.exists():
        return False
    import shutil

    shutil.rmtree(root, ignore_errors=True)
    return True
