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
from app.agents import keyframes as keyframes_mod

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

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_EVIDENCE_COUNT = 10


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


def content_matches_kind(data: bytes, kind: str) -> bool:
    """Magic-byte check that upload bytes match the claimed kind (C11)."""
    head = bytes(data or b"")[:16]
    if kind == "pdf":
        return head.startswith(b"%PDF")
    if kind == "image":
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return True
        if head.startswith(b"\xff\xd8\xff"):
            return True
        if head.startswith((b"GIF87a", b"GIF89a")):
            return True
        if head.startswith(b"BM"):
            return True
        if head.startswith(b"RIFF") and b"WEBP" in bytes(data or b"")[:32]:
            return True
        return False
    if kind == "video":
        if len(head) >= 8 and head[4:8] == b"ftyp":
            return True
        if head.startswith(b"RIFF"):
            return True
        if head.startswith(b"\x1a\x45\xdf\xa3"):
            return True
        return False
    return False


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
# --- video keyframes (M4b item 4) ------------------------------------------------
# Design 3-10: ffmpeg pulls KEYFRAME_FPS frames/second, near-duplicates are
# filtered by keyframes.select_keyframes, and the reader reads the rest.
# Stored next to the video (or under dest_dir) with a manifest so replays
# reuse byte-identical frames. Registration/preview behavior above is
# unchanged (video stays status "skipped" until INT-3 wires the reader).

VIDEO_KEYFRAME_FPS = 2.0
EXTRACTOR_VERSION = "select-v2"


def keyframes_dir(video_path, ex_id, dest_dir=None):
    """Directory holding one video's extracted keyframes + manifest."""
    root = Path(str(dest_dir)) if dest_dir else Path(str(video_path)).parent
    safe = "".join(c if (c.isalnum() or c in ("-", "_")) else "_"
                   for c in str(ex_id or "EX"))
    return root / f"{safe}_keyframes"


def extract_video_keyframes(video_path, ex_id, dest_dir=None,
                            fps=VIDEO_KEYFRAME_FPS):
    """Extract 2fps frames for a video; cache by source sha256 (M4b item 4).

    Returns [{frame_ts, filename, png, width, height, sha256}]. When the
    manifest in the keyframes dir matches the current video bytes, stored
    PNGs load instead of re-running ffmpeg (replay-stable).
    """
    import json as _json

    src = Path(str(video_path))
    data = src.read_bytes()
    digest = sha256_bytes(data)
    target = keyframes_dir(src, ex_id, dest_dir)
    manifest = target / "manifest.json"
    if manifest.exists():
        try:
            saved = _json.loads(manifest.read_text(encoding="utf-8"))
            if saved.get("video_sha256") == digest and saved.get("extractor") == EXTRACTOR_VERSION:
                entries = []
                for row in saved.get("frames", []):
                    png = (target / row["filename"]).read_bytes()
                    entries.append({
                        "frame_ts": float(row["frame_ts"]),
                        "filename": row["filename"],
                        "png": bytes(png),
                        "width": int(row["width"]),
                        "height": int(row["height"]),
                        "sha256": sha256_bytes(png),
                    })
                if entries:
                    return entries
        except (OSError, ValueError, KeyError):
            pass
    frames = keyframes_mod.extract_frames(src, fps)
    target.mkdir(parents=True, exist_ok=True)
    rows = []
    entries = []
    for index, frame in enumerate(frames):
        name = f"kf_{index:03d}_ts{frame['frame_ts']:.1f}.png"
        (target / name).write_bytes(bytes(frame["png"]))
        rows.append({"frame_ts": frame["frame_ts"], "filename": name,
                     "width": frame["width"], "height": frame["height"],
                     "sha256": sha256_bytes(frame["png"])})
        entries.append({"frame_ts": float(frame["frame_ts"]), "filename": name,
                        "png": bytes(frame["png"]), "width": frame["width"],
                        "height": frame["height"],
                        "sha256": sha256_bytes(frame["png"])})
    manifest.write_text(_json.dumps(
        {"video_sha256": digest, "fps": float(fps), "extractor": EXTRACTOR_VERSION, "frames": rows},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return entries
