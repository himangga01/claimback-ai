"""Case state: design 4-2 zones on a per-case JSON file (M2a task 2).

Layout: ``backend/data/cases/<case_id>/case.json`` plus ``evidence/`` and
``files/`` subdirectories. Every mutation goes through :func:`save_case`,
which bumps ``version`` and writes atomically (tmp + replace) so a UI poll
during a run always reads a complete file.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
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


_CASE_ID_RE = re.compile(r"^case_[0-9a-f]{12}$")


def valid_case_id(case_id: Any) -> bool:
    return isinstance(case_id, str) and _CASE_ID_RE.match(case_id) is not None


def _inside_root(root: Path, path: Path) -> bool:
    try:
        text_root = str(root.absolute())
        text_candidate = str(path.absolute())
        sep = "\\" if "\\" in text_root else "/"
        prefix = text_root.rstrip("\\/") + sep
        return text_candidate == text_root or text_candidate.startswith(prefix)
    except OSError:
        return False


def case_dir(case_id: str) -> Path:
    if not valid_case_id(case_id):
        raise ValueError(f"invalid case_id: {case_id!r}")
    root = get_cases_root()
    path = root / case_id
    if not _inside_root(root, path):
        raise ValueError(f"case path escapes root: {case_id!r}")
    return path


def evidence_dir(case_id: str) -> Path:
    return case_dir(case_id) / "evidence"


def files_dir(case_id: str) -> Path:
    return case_dir(case_id) / "files"


def case_file(case_id: str) -> Path:
    return case_dir(case_id) / "case.json"


def load_case(case_id: str) -> Optional[CaseState]:
    """Load a case, None when unknown; read errors raise (never 404)."""
    if not valid_case_id(case_id):
        return None
    try:
        path = case_file(case_id)
    except ValueError:
        return None
    if not path.exists():
        return None
    last: Optional[BaseException] = None
    for _ in range(6):
        try:
            return CaseState.model_validate_json(
                path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (PermissionError, OSError) as exc:
            last = exc
            time.sleep(0.02)
            continue
    if last is not None:
        raise last
    raise OSError(f"cannot read case file: {path}")


def save_case(state: CaseState) -> CaseState:
    """Bump version and persist atomically. Returns the state."""
    if not valid_case_id(state.case_id):
        raise ValueError(f"invalid case_id: {state.case_id!r}")
    with _save_lock(state.case_id):
        state.version += 1
        state.updated_at = utc_now_iso()
        target = case_file(state.case_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"case.json.tmp-{os.getpid()}")
        tmp.write_text(
            state.model_dump_json(ensure_ascii=False), encoding="utf-8"
        )
        last: Optional[BaseException] = None
        for _ in range(10):
            try:
                os.replace(tmp, target)
                last = None
                break
            except (PermissionError, OSError) as exc:
                last = exc
                time.sleep(0.02)
        if last is not None:
            raise last
    return state


def delete_case(case_id: str) -> bool:
    """Remove the whole case directory (uploads + generated files).

    INT-3 B2: verify the directory is really gone and retry a few
    times (an open file on Windows fails the first pass). Returns
    False only when there is nothing to delete; raises PermissionError
    (locked files) or OSError when remnants survive, so DELETE never
    reports success while evidence stays on disk.
    """
    if not valid_case_id(case_id):
        return False
    try:
        root = case_dir(case_id)
    except ValueError:
        return False
    if not root.exists():
        return False
    import shutil

    last_error: Optional[BaseException] = None
    for attempt in range(4):
        try:
            shutil.rmtree(root, ignore_errors=False)
        except (PermissionError, OSError) as exc:
            last_error = exc
        if not root.exists():
            return True
        time.sleep(0.05 * (attempt + 1))
    shutil.rmtree(root, ignore_errors=True)
    if not root.exists():
        return True
    if isinstance(last_error, PermissionError):
        raise PermissionError(f"case files are in use: {case_id!r}")
    raise OSError(f"cannot remove case directory: {case_id!r}")
