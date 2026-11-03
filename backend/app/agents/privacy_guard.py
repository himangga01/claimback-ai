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


def _same_line(first: Dict[str, Any], second: Dict[str, Any]) -> bool:
    """Two mask boxes on one text line (half the shorter height shared)."""
    try:
        ax1, ay1, ax2, ay2 = (int(first[k]) for k in ("x1", "y1", "x2", "y2"))
        bx1, by1, bx2, by2 = (int(second[k]) for k in ("x1", "y1", "x2", "y2"))
    except (KeyError, TypeError, ValueError):
        return False
    shared_h = min(ay2, by2) - max(ay1, by1)
    shorter = max(1, min(ay2 - ay1, by2 - by1))
    return shared_h >= 0.5 * shorter and min(ax2, bx2) > max(ax1, bx1)


def _flag_shared_lines(
    plan: List[Dict[str, Any]], line_texts: List[Tuple[int, str]]
) -> None:
    """Two different PII readings masked on one line: review both.

    fix-cost-redaction review: when the reader puts the sender account's
    box on the receiver's line (further than the leak search reaches),
    both masks land on that line, its pattern matches, and the sender's
    number stays visible. One line cannot hold two different numbers.
    """
    def _digits(text: str) -> str:
        return "".join(ch for ch in str(text or "") if ch.isdigit())

    for pos, (first, first_text) in enumerate(line_texts):
        for second, second_text in line_texts[pos + 1:]:
            if _digits(first_text) == _digits(second_text):
                continue
            if not _same_line(plan[first]["mask_box"],
                              plan[second]["mask_box"]):
                continue
            for index in (first, second):
                entry = plan[index]
                entry["needs_review"] = True
                reason = str(entry.get("reason", "") or "")
                if redact_mod.SAME_LINE_REVIEW_REASON not in reason:
                    entry["reason"] = (
                        f"{reason}; {redact_mod.SAME_LINE_REVIEW_REASON}"
                        if reason else redact_mod.SAME_LINE_REVIEW_REASON)


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
        line_texts: List[Tuple[int, str]] = []  # (plan index, reading text)
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
            reader_coords = list(coords)
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
            # fix-cost bug 2: the mask must sit on the reading's own line;
            # a snap of a full line or more, or a line that does not spell
            # the reading's number, is needs_review (fail closed). No ink
            # mask means neither can be checked: review too.
            review_reasons: List[str] = []
            if reading_tripped:
                review_reasons.append(redact_mod.READING_BAND_REVIEW_REASON)
            line_mask = (ink_masks.get(ex_id)
                         if not inline and image is not None else None)
            if not inline and image is not None and line_mask is None:
                review_reasons.append(redact_mod.INK_UNCHECKED_REVIEW_REASON)
            if line_mask is not None:
                if coords != reader_coords and redact_mod.line_shift_too_far(
                        reader_coords, coords):
                    review_reasons.append(
                        redact_mod.LINE_SHIFT_REVIEW_REASON)
                elif not redact_mod.pii_line_matches(line_mask, coords, text):
                    review_reasons.append(
                        redact_mod.LINE_MATCH_REVIEW_REASON)
            line_texts.append((len(plan), text))
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
                reason = "; ".join(["계좌번호 끝 4자리 유지"] + review_reasons)
                plan.append({
                    "ex_id": ex_id, "item_id": item_id, "kind": kind,
                    "mask_box": redact_mod._as_box_dict(mask, ref_w, ref_h),
                    "keep_box": redact_mod._as_box_dict(keep, ref_w, ref_h),
                    "reason": reason,
                    "needs_review": bool(review_reasons),
                    "reading_band_counts": reading_counts or {},
                })
            elif kind == "id_number":
                raw = redact_mod.split_id_box(coords, text, geom)
                mask = redact_mod.pad_box(
                    raw, pad, (False, True, True, True), ref_w, ref_h)
                reason = "; ".join(["주민번호 뒷 7자리 가림"] + review_reasons)
                plan.append({
                    "ex_id": ex_id, "item_id": item_id, "kind": kind,
                    "mask_box": redact_mod._as_box_dict(mask, ref_w, ref_h),
                    "keep_box": None,
                    "reason": reason,
                    "needs_review": bool(review_reasons),
                    "reading_band_counts": reading_counts or {},
                })
            else:  # phone
                raw = redact_mod.split_phone_box(coords, text, geom)
                mask = redact_mod.pad_box(
                    raw, pad, (False, True, False, True), ref_w, ref_h)
                reason = "; ".join(["전화번호 가운데 4자리 가림"] + review_reasons)
                plan.append({
                    "ex_id": ex_id, "item_id": item_id, "kind": kind,
                    "mask_box": redact_mod._as_box_dict(mask, ref_w, ref_h),
                    "keep_box": None,
                    "reason": reason,
                    "needs_review": bool(review_reasons),
                    "reading_band_counts": reading_counts or {},
                })
        _flag_shared_lines(plan, line_texts)
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
        # fix-cost bug 2: the leak check also looks for each PII
        # reading's number still visible near its reading box.
        pii_items = []
        for item in reading.get("items", []) or []:
            coords = _box_list(item.get("box"))
            if str(item.get("kind", "")) in PII_KINDS and coords:
                pii_items.append({
                    "ex_id": ex_id, "item_id": str(item.get("item_id", "")),
                    "kind": str(item.get("kind", "")), "box": coords,
                    "text": str(item.get("text_verbatim", "")
                                or item.get("normalized", "") or "")})
        checked = redact_mod.check_leak(
            Path(original), redacted_path, entries, expected_sha256=None,
            pii_items=pii_items)
        if not file_ok:
            checked = {"status": "fail", "findings": list(
                checked.get("findings", [])) + [{
                    "ex_id": ex_id, "item_id": "",
                    "message": "원본 파일이 바뀌었습니다."}]}
        item_reasons = (redact_mod.UNMASKED_LINE_REASON,
                        redact_mod.LEAK_UNCHECKED_REASON)
        for finding in checked.get("findings", []) or []:
            leak_findings.append(finding)
            message = finding.get("message")
            if message not in item_reasons:
                continue
            for entry in entries:
                if str(entry.get("item_id", "")) != finding.get("item_id"):
                    continue
                entry["needs_review"] = True
                reason = str(entry.get("reason", "") or "")
                if message not in reason:
                    entry["reason"] = (f"{reason}; {message}"
                                       if reason else message)
        if checked.get("status") == "fail":
            status = "fail"
        elif checked.get("status") == "review" and status != "fail":
            # redaction-confirm: warnings are a review, never a pass.
            status = "review"
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
        # Per-item leak warnings already ride on their entry's reason.
        warn_msgs = [
            str(f.get("message", "")) for f in checked.get("findings", [])
            if f.get("warning") and f.get("message")
            and f.get("message") not in item_reasons]
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


def privacy_note(privacy_out: Dict[str, Any]) -> str:
    """Board note for a finished (not failed) privacy step.

    redaction-confirm: "누출 검사 통과" only when no copy is flagged and
    no copy is missing. Otherwise the note counts the exhibits the user
    must check (flagged copies, held out of exhibits.pdf until confirmed)
    and the exhibits that have no redacted copy at all.
    """
    plan = privacy_out.get("plan", []) or []
    previews = privacy_out.get("previews", []) or []
    leak = privacy_out.get("leak_check", {}) or {}
    flagged = [p for p in previews
               if isinstance(p, dict) and p.get("needs_review") is True
               and p.get("status") != "not_redacted"]
    missing = [p for p in previews
               if isinstance(p, dict) and p.get("status") == "not_redacted"]
    parts = [f"가림 {len(plan)}개"]
    if flagged:
        parts.append(f"확인 필요 증거 {len(flagged)}개")
    if missing:
        parts.append(f"가린 사본 없는 증거 {len(missing)}개")
    if not flagged and not missing:
        parts.append("누출 검사 통과" if str(leak.get("status", "pass")) == "pass"
                     else "누출 검사 확인 필요")
    return ", ".join(parts)
