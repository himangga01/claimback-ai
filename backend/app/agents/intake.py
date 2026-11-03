"""Intake worker (rule): hashes, exhibit numbers, kinds (M2a task 4)."""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import List, Optional, Tuple

from app.agents.case_state import (
    REPO_ROOT,
    CaseState,
    EvidenceRecord,
    evidence_dir,
)

SAMPLE_DIR = REPO_ROOT / "sample_evidence" / "kr"

# Contract 2장 fixed order. iou.png is the EX6 preview, not evidence.
SAMPLE_ORDER: List[Tuple[str, str, str]] = [
    ("EX1", "chat_01.png", "image"),
    ("EX2", "chat_02_tall.png", "image"),
    ("EX3", "chat_02_scroll.mp4", "video"),
    ("EX4", "transfer_loan.png", "image"),
    ("EX5", "transfer_repay.png", "image"),
    ("EX6", "iou.pdf", "pdf"),
]
PDF_PREVIEW_SOURCE = "iou.png"

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_PDF_SUFFIXES = {".pdf"}
_VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".webm", ".mkv"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(bytes(data)).hexdigest()


def label_for(number: int) -> str:
    return f"갑 제{number}호증"


def kind_for(filename: str) -> Optional[str]:
    suffix = Path(filename or "").suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    if suffix in _PDF_SUFFIXES:
        return "pdf"
    if suffix in _VIDEO_SUFFIXES:
        return "video"
    return None


def _next_number(state: CaseState) -> int:
    biggest = 0
    for record in state.evidence:
        text = record.ex_id.upper()
        if text.startswith("EX"):
            try:
                biggest = max(biggest, int(text[2:]))
            except ValueError:
                pass
    return biggest + 1


def _safe_name(filename: str) -> str:
    return Path(filename or "upload").name or "upload"


def register_file(
    state: CaseState,
    filename: str,
    data: bytes,
    kind: str,
    ex_id: Optional[str] = None,
    preview_data: Optional[bytes] = None,
) -> EvidenceRecord:
    """Store one evidence file and append its record (status by kind)."""
    number = int(ex_id[2:]) if ex_id and ex_id.upper().startswith("EX") else None
    if ex_id is None:
        number = _next_number(state)
        ex_id = f"EX{number}"
    if number is None:
        try:
            number = int(str(ex_id)[2:])
        except ValueError:
            number = _next_number(state)
    target_dir = evidence_dir(state.case_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{ex_id}_{_safe_name(filename)}"
    (target_dir / stored).write_bytes(bytes(data))
    preview_url: Optional[str] = None
    if kind == "image":
        preview_url = f"/api/cases/{state.case_id}/evidence/{ex_id}/preview"
    elif kind == "pdf" and preview_data is not None:
        preview_name = f"{ex_id}_preview.png"
        (target_dir / preview_name).write_bytes(bytes(preview_data))
        preview_url = f"/api/cases/{state.case_id}/evidence/{ex_id}/preview"
    record = EvidenceRecord(
        ex_id=ex_id,
        label=label_for(number),
        filename=_safe_name(filename),
        stored_name=stored,
        sha256=sha256_bytes(data),
        kind=kind,  # type: ignore[arg-type]
        status="skipped" if kind == "video" else "ok",
        url=f"/api/cases/{state.case_id}/evidence/{ex_id}/file",
        preview_url=preview_url,
    )
    state.evidence.append(record)
    return record


def intake_sample(state: CaseState) -> CaseState:
    """Attach the fixed KR sample set EX1~EX6 (contract 2장)."""
    for ex_id, filename, kind in SAMPLE_ORDER:
        data = (SAMPLE_DIR / filename).read_bytes()
        preview = None
        if ex_id == "EX6":
            preview = (SAMPLE_DIR / PDF_PREVIEW_SOURCE).read_bytes()
        register_file(state, filename, data, kind, ex_id=ex_id, preview_data=preview)
    return state


def evidence_path(state: CaseState, record: EvidenceRecord) -> Path:
    return evidence_dir(state.case_id) / record.stored_name


def preview_path(state: CaseState, record: EvidenceRecord) -> Optional[Path]:
    """Local preview file (images: original; pdf: preview png; video: none)."""
    target_dir = evidence_dir(state.case_id)
    if record.kind == "image":
        path = target_dir / record.stored_name
        return path if path.exists() else None
    if record.kind == "pdf":
        path = target_dir / f"{record.ex_id}_preview.png"
        return path if path.exists() else None
    return None


def preview_size(state: CaseState, record: EvidenceRecord) -> Optional[tuple]:
    """Pixel (w, h) of the preview image (images + pdf previews)."""
    path = preview_path(state, record)
    if path is None:
        return None
    try:
        from PIL import Image

        with Image.open(path) as image:
            return (int(image.width), int(image.height))
    except Exception:
        return None


def guess_media_type(filename: str) -> str:
    guessed, _ = mimetypes.guess_type(filename or "")
    return guessed or "application/octet-stream"
