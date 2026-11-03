"""Privacy worker (rule): redaction plans from readings + faces."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.agents import intake as intake_mod
from app.services import redaction as redact_mod

PII_KINDS = ("account_number", "id_number", "phone")


def _box_list(box: Any) -> Optional[List[int]]:
    if not isinstance(box, dict):
        return None
    try:
        coords = [int(box.get("x1", 0)), int(box.get("y1", 0)),
                  int(box.get("x2", 0)), int(box.get("y2", 0))]
    except (TypeError, ValueError):
        return None
    if coords[2] <= coords[0] or coords[3] <= coords[1]:
        return None
    return coords


def _center_inside(inner: List[int], outer: List[int]) -> bool:
    cx = (int(inner[0]) + int(inner[2])) / 2.0
    cy = (int(inner[1]) + int(inner[3])) / 2.0
    return (int(outer[0]) <= cx <= int(outer[2])
            and int(outer[1]) <= cy <= int(outer[3]))


def _bubble_boxes(segments: List[Dict[str, Any]], ex_id: str) -> List[List[int]]:
    boxes: List[List[int]] = []
    for entry in segments or []:
        if str(entry.get("ex_id", "")) != str(ex_id):
            continue
        for obj in entry.get("objects", []) or []:
            if str(obj.get("target", "")) != "chat_bubble":
                continue
            coords = _box_list(obj.get("box"))
            if coords:
                boxes.append(coords)
    return boxes


def _face_objects(
    segments: List[Dict[str, Any]], ex_id: str
) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    for entry in segments or []:
        if str(entry.get("ex_id", "")) != str(ex_id):
            continue
        for obj in entry.get("objects", []) or []:
            if str(obj.get("target", "")) != "face":
                continue
            if _box_list(obj.get("box")):
                found.append(obj)
    return found


def build_plan(
    readings: List[Dict[str, Any]],
    segments: List[Dict[str, Any]],
    preview_sizes: Dict[str, Tuple[int, int]],
) -> List[Dict[str, Any]]:
    """Redaction plan (separate cells precise, inline wide + review flag)."""
    plan: List[Dict[str, Any]] = []
    for reading in readings or []:
        ex_id = str(reading.get("ex_id", ""))
        size = preview_sizes.get(ex_id)
        if not size:
            continue
        ref_w, ref_h = int(size[0]), int(size[1])
        bubbles = _bubble_boxes(segments or [], ex_id)
        for item in reading.get("items", []) or []:
            kind = str(item.get("kind", ""))
            if kind not in PII_KINDS:
                continue
            coords = _box_list(item.get("box"))
            if not coords:
                continue
            item_id = str(item.get("item_id", ""))
            text = str(item.get("text_verbatim", "")
                       or item.get("normalized", "") or "")
            inline = any(_center_inside(coords, bubble) for bubble in bubbles)
            pad = redact_mod.compute_pad(coords[3] - coords[1])
            if inline:
                if bubbles:
                    # Widest covering bubble at this line.
                    covering = [b for b in bubbles
                                if _center_inside(coords, b)] or bubbles
                    bubble = max(covering,
                                 key=lambda b: int(b[2]) - int(b[0]))
                    mask = [int(bubble[0]), int(coords[1]),
                            int(bubble[2]), int(coords[3])]
                else:
                    mask = [int(coords[0]) - 60, int(coords[1]),
                            int(coords[2]) + 60, int(coords[3])]
                mask = redact_mod.pad_box(
                    mask, pad, (False, True, False, True), ref_w, ref_h)
                plan.append({
                    "ex_id": ex_id, "item_id": item_id, "kind": kind,
                    "mask_box": redact_mod._as_box_dict(mask, ref_w, ref_h),
                    "keep_box": None,
                    "reason": "문장 안 숫자: 줄 단위로 넓게 가림, 확인 필요",
                    "needs_review": True,
                })
                continue
            if kind == "account_number":
                raw_mask, raw_keep = redact_mod.split_account_box(coords, text)
                mask = redact_mod.pad_box(
                    raw_mask, pad, (True, True, False, True), ref_w, ref_h)
                keep = redact_mod.clip_box(raw_keep, ref_w, ref_h)
                plan.append({
                    "ex_id": ex_id, "item_id": item_id, "kind": kind,
                    "mask_box": redact_mod._as_box_dict(mask, ref_w, ref_h),
                    "keep_box": redact_mod._as_box_dict(keep, ref_w, ref_h),
                    "reason": "계좌번호 끝 4자리 유지",
                    "needs_review": False,
                })
            elif kind == "id_number":
                raw = redact_mod.split_id_box(coords, text)
                mask = redact_mod.pad_box(
                    raw, pad, (False, True, True, True), ref_w, ref_h)
                plan.append({
                    "ex_id": ex_id, "item_id": item_id, "kind": kind,
                    "mask_box": redact_mod._as_box_dict(mask, ref_w, ref_h),
                    "keep_box": None,
                    "reason": "주민번호 뒷 7자리 가림",
                    "needs_review": False,
                })
            else:  # phone
                raw = redact_mod.split_phone_box(coords, text)
                mask = redact_mod.pad_box(
                    raw, pad, (False, True, False, True), ref_w, ref_h)
                plan.append({
                    "ex_id": ex_id, "item_id": item_id, "kind": kind,
                    "mask_box": redact_mod._as_box_dict(mask, ref_w, ref_h),
                    "keep_box": None,
                    "reason": "전화번호 가운데 4자리 가림",
                    "needs_review": False,
                })
    for reading in readings or []:
        ex_id = str(reading.get("ex_id", ""))
        size = preview_sizes.get(ex_id)
        if not size:
            continue
        ref_w, ref_h = int(size[0]), int(size[1])
        for position, obj in enumerate(_face_objects(segments or [], ex_id),
                                       start=1):
            coords = _box_list(obj.get("box"))
            if not coords:
                continue
            pad = redact_mod.compute_pad(coords[3] - coords[1])
            mask = redact_mod.pad_box(
                coords, pad, (True, True, True, True), ref_w, ref_h)
            plan.append({
                "ex_id": ex_id, "item_id": f"face{position}", "kind": "face",
                "mask_box": redact_mod._as_box_dict(mask, ref_w, ref_h),
                "keep_box": None,
                "reason": "얼굴 가림",
                "needs_review": False,
            })
    # Readings without a matching segment entry still need face checks when
    # segments exist for other evidences; faces are covered above per ex_id.
    return plan


def _masks_for(
    plan: List[Dict[str, Any]], ex_id: str
) -> List[List[int]]:
    boxes: List[List[int]] = []
    for entry in plan or []:
        if str(entry.get("ex_id", "")) != str(ex_id):
            continue
        mask = entry.get("mask_box") or {}
        try:
            boxes.append([int(mask.get("x1", 0)), int(mask.get("y1", 0)),
                          int(mask.get("x2", 0)), int(mask.get("y2", 0))])
        except (TypeError, ValueError):
            continue
    return boxes


def run_privacy(
    case_id: str,
    evidence: List[Any],
    readings: List[Dict[str, Any]],
    segments: List[Dict[str, Any]],
    preview_paths: Dict[str, Path],
    preview_sizes: Dict[str, Tuple[int, int]],
    files_dir: Path,
) -> Dict[str, Any]:
    """Build redacted copies + leak check (rule only, no model calls)."""
    plan = build_plan(readings or [], segments or [], preview_sizes or {})
    previews: List[Dict[str, Any]] = []
    leak_findings: List[Dict[str, Any]] = []
    status = "pass"
    by_ex: Dict[str, Any] = {}
    for record in evidence or []:
        ex_id = str(getattr(record, "ex_id", ""))
        if ex_id:
            by_ex[ex_id] = record
    for ex_id in sorted(preview_paths, key=lambda v: (len(v), v)):
        original = preview_paths.get(ex_id)
        record = by_ex.get(ex_id)
        if original is None or record is None:
            continue
        if str(getattr(record, "kind", "")) == "video":
            continue
        entries = [e for e in plan if str(e.get("ex_id", "")) == str(ex_id)]
        redacted_name = f"redacted_{ex_id}.png"
        redacted_path = Path(files_dir) / redacted_name
        redact_mod.burn_redacted_copy(
            Path(original), redacted_path,
            _masks_for(plan, ex_id), str(getattr(record, "label", ex_id)))
        expected = str(getattr(record, "sha256", "") or "")
        # Leak check compares the preview pixels; the stored hash guards the
        # original evidence file itself (untouched).
        try:
            from app.agents.case_state import evidence_dir as _evidence_dir

            stored = _evidence_dir(str(case_id)) / str(
                getattr(record, "stored_name", ""))
            file_ok = (redact_mod.sha256_file(stored) == expected
                       if stored.exists() and expected else True)
        except OSError:
            file_ok = True
        checked = redact_mod.check_leak(
            Path(original), redacted_path, entries, expected_sha256=None)
        if not file_ok:
            checked = {"status": "fail", "findings": list(
                checked.get("findings", [])) + [{
                    "ex_id": ex_id, "item_id": "",
                    "message": "원본 파일이 바뀌었습니다."}]}
        for finding in checked.get("findings", []) or []:
            leak_findings.append(finding)
        if checked.get("status") == "fail":
            status = "fail"
        needs_review = any(e.get("needs_review") for e in entries)
        needs_review = bool(needs_review or any(
            str(f.get("ex_id", "")) == str(ex_id) and f.get("warning")
            for f in checked.get("findings", []) or []))
        previews.append({
            "ex_id": ex_id,
            "url": f"/api/cases/{case_id}/files/{redacted_name}",
            "needs_review": needs_review,
        })
    previews.sort(key=lambda e: (len(str(e.get("ex_id", ""))),
                                 str(e.get("ex_id", ""))))
    return {
        "plan": plan,
        "previews": previews,
        "leak_check": {"status": status, "findings": leak_findings},
    }
