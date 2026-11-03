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
    preview_images: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Redaction plan (separate cells precise, inline wide + review flag).

    ``preview_images`` maps ex_id to the opened original preview (L4 ink
    geometry); without it splits fall back to box-proportional.
    INT-3 1a: non-inline PII boxes first snap to the true glyph line
    (refine_pii_box); a failed snap keeps the original box and the
    current needs_review behavior.
    """
    plan: List[Dict[str, Any]] = []
    label_boxes: Dict[str, List[List[int]]] = {}
    for reading in readings or []:
        boxes: List[List[int]] = []
        for entry in reading.get("items", []) or []:
            if str(entry.get("kind", "")) not in ("label", "header"):
                continue
            parsed = _box_list(entry.get("box"))
            if parsed:
                boxes.append(parsed)
        label_boxes[str(reading.get("ex_id", ""))] = boxes
    ink_masks: Dict[str, Any] = {}
    rule_rows_cache: Dict[str, set] = {}
    for reading in readings or []:
        ex_id = str(reading.get("ex_id", ""))
        size = preview_sizes.get(ex_id)
        if not size:
            continue
        ref_w, ref_h = int(size[0]), int(size[1])
        bubbles = _bubble_boxes(segments or [], ex_id)
        image = (preview_images or {}).get(ex_id)
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
            if not inline and image is not None:
                mask = ink_masks.get(ex_id, "missing")
                if mask == "missing":
                    try:
                        mask = redact_mod.build_ink_mask(image)
                    except Exception:
                        mask = None
                    ink_masks[ex_id] = mask
                if mask is not None:
                    try:
                        refined = redact_mod.refine_pii_box(
                            mask, coords, text,
                            label_boxes.get(ex_id))
                    except Exception:
                        refined = None
                    if refined is not None:
                        coords = refined
            # INT-3 task 2: bands on all four sides of the planning box
            # (a glyph sitting beside it means the box missed the line,
            # even a sideways-only miss the mask bands skip).
            reading_counts: Optional[Dict[str, int]] = None
            reading_tripped = False
            if not inline and image is not None:
                band_mask = ink_masks.get(ex_id)
                if band_mask is not None:
                    if ex_id not in rule_rows_cache:
                        try:
                            rule_rows_cache[ex_id] = (
                                redact_mod.rule_rows_of_mask(band_mask))
                        except Exception:
                            rule_rows_cache[ex_id] = set()
                    try:
                        reading_counts = redact_mod.reading_band_counts(
                            band_mask, rule_rows_cache[ex_id], coords)
                    except Exception:
                        reading_counts = None
                    if reading_counts and max(reading_counts.values()) >= \
                            redact_mod.BAND_THRESHOLD:
                        reading_tripped = True
            pad = redact_mod.compute_pad(coords[3] - coords[1])
            geom = None
            if image is not None and not inline:
                try:
                    geom = redact_mod.analyze_text_box(image, coords, text)
                except Exception:
                    geom = None
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
                raw_mask, raw_keep = redact_mod.split_account_box(
                    coords, text, geom)
                mask = redact_mod.pad_box(
                    raw_mask, pad, (True, True, False, True), ref_w, ref_h)
                keep = redact_mod.clip_box(raw_keep, ref_w, ref_h)
                reason = "계좌번호 끝 4자리 유지"
                if reading_tripped:
                    reason = f"{reason}; {redact_mod.READING_BAND_REVIEW_REASON}"
                plan.append({
                    "ex_id": ex_id, "item_id": item_id, "kind": kind,
                    "mask_box": redact_mod._as_box_dict(mask, ref_w, ref_h),
                    "keep_box": redact_mod._as_box_dict(keep, ref_w, ref_h),
                    "reason": reason,
                    "needs_review": reading_tripped,
                    "reading_band_counts": reading_counts or {},
                })
            elif kind == "id_number":
                raw = redact_mod.split_id_box(coords, text, geom)
                mask = redact_mod.pad_box(
                    raw, pad, (False, True, True, True), ref_w, ref_h)
                reason = "주민번호 뒷 7자리 가림"
                if reading_tripped:
                    reason = f"{reason}; {redact_mod.READING_BAND_REVIEW_REASON}"
                plan.append({
                    "ex_id": ex_id, "item_id": item_id, "kind": kind,
                    "mask_box": redact_mod._as_box_dict(mask, ref_w, ref_h),
                    "keep_box": None,
                    "reason": reason,
                    "needs_review": reading_tripped,
                    "reading_band_counts": reading_counts or {},
                })
            else:  # phone
                raw = redact_mod.split_phone_box(coords, text, geom)
                mask = redact_mod.pad_box(
                    raw, pad, (False, True, False, True), ref_w, ref_h)
                reason = "전화번호 가운데 4자리 가림"
                if reading_tripped:
                    reason = f"{reason}; {redact_mod.READING_BAND_REVIEW_REASON}"
                plan.append({
                    "ex_id": ex_id, "item_id": item_id, "kind": kind,
                    "mask_box": redact_mod._as_box_dict(mask, ref_w, ref_h),
                    "keep_box": None,
                    "reason": reason,
                    "needs_review": reading_tripped,
                    "reading_band_counts": reading_counts or {},
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


def _boxes_for(
    plan: List[Dict[str, Any]], ex_id: str, key: str
) -> List[List[int]]:
    boxes: List[List[int]] = []
    for entry in plan or []:
        if str(entry.get("ex_id", "")) != str(ex_id):
            continue
        box = entry.get(key) or {}
        if not isinstance(box, dict):
            continue
        try:
            boxes.append([int(box.get("x1", 0)), int(box.get("y1", 0)),
                          int(box.get("x2", 0)), int(box.get("y2", 0))])
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
    """Build redacted copies + leak check (rule only, no model calls).

    Fail closed (L2): an evidence whose redaction cannot be completed
    (preview missing, reading on hold, vision error, uncovered PII) gets
    no copy at all — its preview carries ``status: "not_redacted"`` with a
    reason instead of an original-plus-stamp lookalike.
    """
    from PIL import Image
    from app.agents.case_state import evidence_dir as _evidence_dir

    preview_images: Dict[str, Any] = {}
    for ex_id, path in (preview_paths or {}).items():
        try:
            preview_images[str(ex_id)] = Image.open(
                Path(path)).convert("RGB")
        except Exception:
            continue
    plan = build_plan(readings or [], segments or [],
                      preview_sizes or {}, preview_images)
    previews: List[Dict[str, Any]] = []
    leak_findings: List[Dict[str, Any]] = []
    status = "pass"
    by_ex: Dict[str, Any] = {}
    for record in evidence or []:
        ex_id = str(getattr(record, "ex_id", ""))
        if ex_id:
            by_ex[ex_id] = record
    readings_by_ex = {str(r.get("ex_id", "")): r for r in readings or []}
    segments_by_ex = {str(s.get("ex_id", "")): s for s in segments or []}

    def _not_redacted(ex_id: str, reason: str) -> None:
        # INT-3 task 2: a stale copy from an earlier run must not
        # survive next to a not_redacted preview (fail closed).
        try:
            stale = Path(files_dir) / f"redacted_{ex_id}.png"
            if stale.exists():
                stale.unlink()
        except OSError:
            pass
        previews.append({
            "ex_id": ex_id,
            "url": None,
            "status": "not_redacted",
            "reason": reason,
            "needs_review": True,
        })

    ordered = sorted(by_ex, key=lambda v: (len(v), v))
    for ex_id in ordered:
        record = by_ex.get(ex_id)
        if record is None:
            continue
        if str(getattr(record, "kind", "")) == "video":
            continue
        original = preview_paths.get(ex_id)
        if original is None or not Path(original).exists():
            _not_redacted(ex_id, "미리보기가 없어 가린 사본을 만들 수 없음")
            continue
        reading = readings_by_ex.get(ex_id)
        if reading is None or str(getattr(record, "status", "")) == "hold":
            _not_redacted(ex_id, "판독이 보류되어 가림 대상을 알 수 없음")
            continue
        segment = segments_by_ex.get(ex_id)
        # INT-3 task 2: only noun-call failure blocks redaction (faces
        # unknown). A signature-retry-only hold keeps its noun objects,
        # and signatures are not redaction targets, so redaction
        # proceeds. Segments without the scope marker stay fail-closed.
        if segment is None or (
                str(segment.get("status", "")) == "hold"
                and segment.get("hold_scope") != "signature_retry"):
            detail = ""
            if isinstance(segment, dict) and segment.get("error"):
                detail = f": {str(segment['error'])[:80]}"
            _not_redacted(ex_id, f"시각 감식에 실패해 얼굴 가림을 확인할 수 없음{detail}")
            continue
        entries = [e for e in plan if str(e.get("ex_id", "")) == str(ex_id)]
        wanted_pii = {
            str(item.get("item_id", ""))
            for item in reading.get("items", []) or []
            if str(item.get("kind", "")) in PII_KINDS
        }
        planned_pii = {
            str(e.get("item_id", "")) for e in entries
            if str(e.get("kind", "")) in PII_KINDS
        }
        uncovered = sorted(wanted_pii - planned_pii)
        if uncovered:
            _not_redacted(
                ex_id,
                "가림 계획이 없어(" + ", ".join(uncovered) + ")")
            continue
        redacted_name = f"redacted_{ex_id}.png"
        redacted_path = Path(files_dir) / redacted_name
        redact_mod.burn_redacted_copy(
            Path(original), redacted_path,
            _boxes_for(plan, ex_id, "mask_box"),
            str(getattr(record, "label", ex_id)),
            _boxes_for(plan, ex_id, "keep_box"))
        expected = str(getattr(record, "sha256", "") or "")
        # Leak check compares the preview pixels; the stored hash guards the
        # original evidence file itself (untouched).
        try:
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
        # L1 bands: glyph outside a mask flags the entry and its preview
        # (never a HOLD; the case continues with "확인 필요").
        pre_reasons = [str(e.get("reason", "")) for e in entries
                       if e.get("needs_review") and e.get("reason")]
        band_counts = redact_mod.flag_leak_bands(Path(original), entries)
        band_hit = False
        for entry in entries:
            counts = band_counts.get(
                (str(entry.get("ex_id", "")), str(entry.get("item_id", ""))),
                {})
            entry["band_counts"] = counts
            if counts and max(counts.values()) >= redact_mod.BAND_THRESHOLD:
                band_hit = True
                entry["needs_review"] = True
                reason = str(entry.get("reason", "") or "")
                if redact_mod.LEAK_REVIEW_REASON not in reason:
                    entry["reason"] = (
                        f"{reason}; {redact_mod.LEAK_REVIEW_REASON}"
                        if reason else redact_mod.LEAK_REVIEW_REASON)
        warn_msgs = [
            str(f.get("message", "")) for f in checked.get("findings", [])
            if f.get("warning") and f.get("message")]
        reason_parts = ([redact_mod.LEAK_REVIEW_REASON] if band_hit else [])
        reason_parts.extend(pre_reasons)
        reason_parts.extend(warn_msgs)
        seen: List[str] = []
        for part in reason_parts:
            if part and part not in seen:
                seen.append(part)
        needs_review = bool(band_hit or pre_reasons or warn_msgs)
        previews.append({
            "ex_id": ex_id,
            "url": f"/api/cases/{case_id}/files/{redacted_name}",
            "status": "redacted",
            "reason": " / ".join(seen) if seen else None,
            "needs_review": needs_review,
        })
    previews.sort(key=lambda e: (len(str(e.get("ex_id", ""))),
                                 str(e.get("ex_id", ""))))
    for image in preview_images.values():
        try:
            image.close()
        except Exception:
            pass
    return {
        "plan": plan,
        "previews": previews,
        "leak_check": {"status": status, "findings": leak_findings},
    }
