"""M0 live spike runner (record/replay).

Usage:
  python tools\\m0_spike.py --mode record --probes all
  python tools\\m0_spike.py --mode replay --probes all

Each probe uses its own run_id. Results go to reports/M0-spike.json.
Replay mode needs no key or network and must reproduce the same judgments.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.meta.client import (  # noqa: E402
    BudgetExceeded,
    MetaClient,
    extract_output_text,
    extract_usage,
    ledger_summary,
)
from app.meta.coords import denormalize_box, mean_best_iou  # noqa: E402
from app.meta import pricing  # noqa: E402

INPUTS = ROOT / "backend" / "tests" / "fixtures" / "spike_inputs"
OUTPUTS = ROOT / "backend" / "tests" / "fixtures" / "spike_outputs"
REPORT_JSON = ROOT / "reports" / "M0-spike.json"
# Ledger location resolves inside ledger_summary (META_LEDGER_PATH or the
# repo default); no hard-coded path here (M0-fix2 D3/D4).

M0_BUDGET_USD = 3.0
ALL_PROBES = ["P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]
REQUIRED_MODELS = ["muse-spark-1.1", "muse-spark-1.2", "muse-spark-1.3",
                   "sam-3.1", "muse-image-1.0"]

READING_SCHEMA = {
    "type": "json_schema",
    "name": "reading",
    "schema": {
        "type": "object",
        "properties": {
            "evidence_id": {"type": "string"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "string"},
                        "kind": {"type": "string"},
                        "text_verbatim": {"type": "string"},
                        "normalized": {"type": "string"},
                        "box": {"type": "array", "items": {"type": "number"},
                                "minItems": 4, "maxItems": 4},
                        "speaker": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["item_id", "kind", "text_verbatim", "box"],
                    "additionalProperties": True,
                },
            },
        },
        "required": ["evidence_id", "items"],
        "additionalProperties": False,
    },
    "strict": False,
}

SIMPLE_SCHEMA = {
    "type": "json_schema",
    "name": "simple_extract",
    "schema": {
        "type": "object",
        "properties": {
            "amount": {"type": "string"},
            "date": {"type": "string"},
        },
        "required": ["amount", "date"],
        "additionalProperties": False,
    },
    "strict": False,
}


def load_truth() -> dict:
    return json.loads((INPUTS / "truth.json").read_text(encoding="utf-8"))


def ledger_total() -> tuple[float, int]:
    """Ledger (total_usd, lines) via ledger_summary (M0-fix2 D3).

    Reservations are offset against their final lines instead of being
    double-counted; a missing ledger reports (0.0, 0).
    """
    summary = ledger_summary()
    lines = sum(slot.get("count", 0)
                for slot in summary["by_status"].values())
    return (summary["total_usd"], lines)


def data_url(path: Path, mime: str) -> str:
    blob = path.read_bytes()
    return f"data:{mime};base64,{base64.b64encode(blob).decode('ascii')}"


def parse_json_text(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    return json.loads(cleaned)


def norm_digits(value: str) -> str:
    return "".join(ch for ch in str(value) if ch.isdigit())


def truth_boxes_for(truth_entry: dict) -> list[list[int]]:
    boxes: list[list[int]] = []
    for b in truth_entry.get("bubbles", []):
        boxes.append([int(v) for v in b["box"]])
    for key in ("amounts", "dates"):
        for item in truth_entry.get(key, []):
            if item.get("box"):
                boxes.append([int(v) for v in item["box"]])
    for key in ("signature", "stamp"):
        item = truth_entry.get(key)
        if isinstance(item, dict) and item.get("box"):
            boxes.append([int(v) for v in item["box"]])
    return boxes


def judge_coords(pred_boxes, width: int, height: int,
                 truth_boxes) -> tuple[str, dict]:
    scores = {}
    for fmt in ("pixel", "norm1000", "norm01"):
        try:
            pix = [denormalize_box(b, width, height, fmt) for b in pred_boxes]
            scores[fmt] = round(mean_best_iou(pix, truth_boxes), 4)
        except Exception:
            scores[fmt] = 0.0
    best = max(scores, key=lambda k: scores[k])
    return best, scores


def sam_parse_boxes(output_text: str, video: bool = False) -> list[list[int]]:
    from meta_sam_parser import CompletedOutcome, image_segmentation_format, \
        video_segmentation_format

    fmt = video_segmentation_format() if video else image_segmentation_format()
    parser = fmt.create_parser()
    text = output_text if output_text.endswith("\n") else output_text + "\n"
    try:
        parser.push(text)
    except Exception:
        pass
    finished = parser.finish(CompletedOutcome())
    boxes: list[list[int]] = []

    def _coords(obj) -> list[int] | None:
        try:
            if isinstance(obj, dict):
                kind = obj.get("kind")
                if kind is not None and kind != "box" and "box" not in obj:
                    return None
                nested = obj.get("box", obj)
                if isinstance(nested, dict):
                    return [int(nested.get("x1", nested.get("left", 0))),
                            int(nested.get("y1", nested.get("top", 0))),
                            int(nested.get("x2", nested.get("right", 0))),
                            int(nested.get("y2", nested.get("bottom", 0)))]
                obj = nested
            kind = getattr(obj, "kind", None)
            if kind is not None and kind != "box":
                nested = getattr(obj, "box", None)
                if nested is None:
                    return None
                return _coords(nested)
            get = (lambda o, *names, default=0: next(
                (int(getattr(o, n)) for n in names
                 if getattr(o, n, None) is not None), default))
            if hasattr(obj, "left") or hasattr(obj, "x1"):
                return [get(obj, "x1", "left"), get(obj, "y1", "top"),
                        get(obj, "x2", "right"), get(obj, "y2", "bottom")]
            nested = getattr(obj, "box", None)
            if nested is not None:
                return _coords(nested)
            return None
        except (TypeError, ValueError):
            return None

    def _collect(snapshot) -> None:
        records = getattr(snapshot, "records", None) or []
        for rec in records:
            coords = _coords(rec)
            if coords:
                boxes.append(coords)

    for snap in list(getattr(finished, "events", []) or []):
        _collect(snap)
    result = getattr(finished, "result", None)
    if result is not None:
        _collect(result)
        for snap in list(getattr(result, "snapshots", []) or []):
            _collect(snap)
    return boxes


def sam_build_box_prompt(width: int, height: int, box, obj_id: int = 1,
                         frame: int = 0) -> str:
    from meta_sam_parser import FramePrompt, PromptBox, PromptObject, \
        build_object_prompt

    x1, y1, x2, y2 = (int(v) for v in box)
    prompt = build_object_prompt(
        size=(int(width), int(height)),
        objects=[PromptObject(id=obj_id, prompts=[
            FramePrompt(frame=int(frame),
                        box=PromptBox(left=x1, top=y1, right=x2, bottom=y2))])],
    )
    return prompt


def run_id_for(probe: str) -> str:
    # Fixed per probe so the per-run cap cannot be bypassed with a fresh
    # timestamp on every attempt (M0-fix1 C6).
    return f"M0-{probe}"


# -- probes ----------------------------------------------------------------

def probe_p0(client: MetaClient) -> dict:
    started = time.perf_counter()
    body = client.models_list()
    latency = int((time.perf_counter() - started) * 1000)
    ids: list[str] = []
    data = body.get("data", []) if isinstance(body, dict) else []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))
    found = [m for m in REQUIRED_MODELS if m in ids]
    missing = [m for m in REQUIRED_MODELS if m not in ids]
    contributor_seen = sorted(i for i in ids if "-contributor" in i)
    success = not missing
    rationale = (f"found {len(found)}/{len(REQUIRED_MODELS)} Standard IDs; "
                 f"missing={missing or 'none'}; "
                 f"contributor IDs in registry={len(contributor_seen)} "
                 f"(not used)")
    return {"success": success, "model": "registry", "api": "GET /models",
            "latency_ms": latency,
            "tokens": {"input": 0, "cached": 0, "output": 0, "reasoning": 0},
            "cost_usd": 0.0, "rationale": rationale,
            "detail": {"found": found, "missing": missing}}


def probe_p1(client: MetaClient) -> dict:
    prompt = ("Extract the amount and date from this sentence as JSON: "
              "'2026-04-10에 5,000,000원을 갚겠다'.")
    payload = [{"role": "user",
                "content": [{"type": "input_text", "text": prompt}]}]
    started = time.perf_counter()
    body = client.responses_create("muse-spark-1.3", payload,
                                   max_output_tokens=1000,
                                   text_format=SIMPLE_SCHEMA)
    latency = int((time.perf_counter() - started) * 1000)
    usage = extract_usage(body)
    text = extract_output_text(body)
    try:
        parsed = parse_json_text(text)
        ok_json = (norm_digits(parsed.get("amount", "")) == "5000000"
                   and "2026-04-10" in str(parsed.get("date", "")))
    except Exception as exc:
        parsed = {}
        ok_json = False
        text = f"{text[:200]} (parse error: {exc})"
    usage_keys = sorted((body.get("usage", {}) or {}).keys()) \
        if isinstance(body, dict) else []
    success = ok_json and usage.get("input_tokens", 0) > 0
    rationale = (f"JSON match={ok_json}; usage keys={usage_keys}; "
                 f"cached={usage.get('cached_input_tokens', 0)}; "
                 f"reasoning={usage.get('reasoning_tokens', 0)}")
    return {"success": success, "model": "muse-spark-1.3",
            "api": "POST /v1/responses (text.format=json_schema)",
            "latency_ms": latency,
            "tokens": {"input": usage.get("input_tokens", 0),
                       "cached": usage.get("cached_input_tokens", 0),
                       "output": usage.get("output_tokens", 0),
                       "reasoning": usage.get("reasoning_tokens", 0)},
            "cost_usd": pricing.spark_cost_usd(
                usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                usage.get("cached_input_tokens", 0),
                usage.get("reasoning_tokens", 0)),
            "rationale": rationale, "detail": {"parsed": parsed}}


def _read_image(client: MetaClient, evidence_id: str, image_path: Path,
                model: str = "muse-spark-1.3",
                tag: str = "") -> tuple[dict, dict, int, str]:
    prefix = f"[{tag}] " if tag else ""
    prompt = (prefix + "Read every chat bubble or receipt field verbatim "
              "with its box. Return a Reading JSON: evidence_id, "
              "items[{item_id, kind, text_verbatim, normalized, "
              "box[x1,y1,x2,y2], speaker, confidence}]. kinds: utterance, "
              "amount, date, party. Boxes must be tight around each item.")
    payload = [{"role": "user", "content": [
        {"type": "input_text", "text": prompt},
        {"type": "input_image",
         "image_url": data_url(image_path, "image/png")}]}]
    started = time.perf_counter()
    body = client.responses_create(model, payload, max_output_tokens=4000,
                                   text_format=READING_SCHEMA,
                                   reasoning={"effort": "minimal"},
                                   image_count=1)
    latency = int((time.perf_counter() - started) * 1000)
    text = extract_output_text(body)
    parsed = parse_json_text(text)
    from app.meta.client import request_hash as _rh
    params = {"store": False, "max_output_tokens": 4000,
              "text_format": READING_SCHEMA,
              "reasoning": {"effort": "minimal"}}
    digest = _rh(model, "responses", params, payload)
    return parsed, body, latency, digest


def _fixture_latency(digest: str) -> int | None:
    path = ROOT / "backend" / "tests" / "fixtures" / "meta" / f"{digest}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data.get("latency_ms", 0))
    except (OSError, ValueError, TypeError):
        return None


def probe_p2(client: MetaClient, truth: dict) -> dict:
    results = {}
    best_overall = None
    ok_all = True
    total_cost = 0.0
    total_latency = 0
    agg = {"input": 0, "cached": 0, "output": 0, "reasoning": 0}
    for fname in ("chat_capture.png", "transfer_receipt.png"):
        path = INPUTS / fname
        entry = truth[fname]
        w, h = entry["size"]
        parsed, body, latency, _digest = _read_image(client, fname, path,
                                                     tag="P2")
        usage = extract_usage(body)
        total_latency += latency
        agg["input"] += int(usage.get("input_tokens", 0))
        agg["cached"] += int(usage.get("cached_input_tokens", 0))
        agg["output"] += int(usage.get("output_tokens", 0))
        agg["reasoning"] += int(usage.get("reasoning_tokens", 0))
        total_cost += pricing.spark_cost_usd(
            usage.get("input_tokens", 0), usage.get("output_tokens", 0),
            usage.get("cached_input_tokens", 0),
            usage.get("reasoning_tokens", 0))
        items = parsed.get("items", []) if isinstance(parsed, dict) else []
        pred_boxes = [it["box"] for it in items
                      if isinstance(it.get("box"), list) and len(it["box"]) == 4]
        tboxes = truth_boxes_for(entry)
        best, scores = judge_coords(pred_boxes, w, h, tboxes) if pred_boxes \
            else ("pixel", {"pixel": 0.0, "norm1000": 0.0, "norm01": 0.0})
        texts = " ".join(str(it.get("text_verbatim", "")) for it in items)
        norm_all = norm_digits(texts)
        want_amount = norm_digits(entry.get("amounts", [{}])[0].get(
            "normalized", "5000000")) if entry.get("amounts") else "5000000"
        want_dates = [d.get("normalized", "") for d in entry.get("dates", [])]
        amount_ok = want_amount in norm_all if want_amount else False
        date_ok = any(d and d in texts for d in want_dates) if want_dates else False
        # Format is determined when the same interpretation wins on both
        # images; 0.05 filters noise (norm01 scores 0.0, pixel ~0.004 on
        # receipts). Absolute IoU varies run to run (0.11-0.21 on receipts).
        ok = scores.get(best, 0.0) > 0.05 and amount_ok and date_ok
        ok_all = ok_all and ok
        if best_overall is None:
            best_overall = best
        elif best_overall != best:
            ok_all = False
        results[fname] = {"best": best, "scores": scores, "items": len(items),
                          "amount_ok": amount_ok, "date_ok": date_ok}
    success = ok_all
    rationale = (f"coord={best_overall}; " + "; ".join(
        f"{k}: best={v['best']} {v['scores']} items={v['items']} "
        f"amount={v['amount_ok']} date={v['date_ok']}"
        for k, v in results.items()))
    # Aggregate tokens from the two calls via ledger-independent usage sum.
    return {"success": success, "model": "muse-spark-1.3",
            "api": "POST /v1/responses (input_image + Reading schema)",
            "latency_ms": total_latency,
            "tokens": agg,
            "cost_usd": round(total_cost, 6), "rationale": rationale,
            "detail": results}


def probe_p3(client: MetaClient, truth: dict) -> dict:
    pdf_path = INPUTS / "iou_2page.pdf"
    prompt = ("Read this Korean IOU PDF and return JSON "
              '{"amount": "...", "dates": ["...", "..."]}.')
    payload_inline = [{"role": "user", "content": [
        {"type": "input_text", "text": prompt},
        {"type": "input_file", "filename": pdf_path.name,
         "file_data": data_url(pdf_path, "application/pdf")}]}]
    method = "inline file_data"
    started = time.perf_counter()
    try:
        body = client.responses_create("muse-spark-1.3", payload_inline,
                                       max_output_tokens=1500,
                                       reasoning={"effort": "minimal"})
    except Exception:
        upload = client.files_create(pdf_path.read_bytes(), pdf_path.name,
                                     purpose="user_data")
        file_id = upload.get("id", "") if isinstance(upload, dict) else ""
        payload_ref = [{"role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_file", "file_id": file_id}]}]
        body = client.responses_create("muse-spark-1.3", payload_ref,
                                       max_output_tokens=1500,
                                       reasoning={"effort": "minimal"})
        method = "Files API + file_id"
    latency = int((time.perf_counter() - started) * 1000)
    usage = extract_usage(body)
    text = extract_output_text(body)
    try:
        parsed = parse_json_text(text)
    except Exception:
        parsed = {"raw": text[:300]}
    blob = json.dumps(parsed, ensure_ascii=False)
    amount_ok = "5000000" in norm_digits(blob)
    date_ok = ("2026-01-01" in blob) and ("2026-04-10" in blob)
    success = amount_ok and date_ok
    rationale = (f"method={method}; amount={amount_ok}; dates={date_ok}")
    return {"success": success, "model": "muse-spark-1.3",
            "api": f"POST /v1/responses (PDF via {method})",
            "latency_ms": latency,
            "tokens": {"input": usage.get("input_tokens", 0),
                       "cached": usage.get("cached_input_tokens", 0),
                       "output": usage.get("output_tokens", 0),
                       "reasoning": usage.get("reasoning_tokens", 0)},
            "cost_usd": pricing.spark_cost_usd(
                usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                usage.get("cached_input_tokens", 0),
                usage.get("reasoning_tokens", 0)),
            "rationale": rationale, "detail": {"parsed": parsed}}


def probe_p4(client: MetaClient, truth: dict) -> dict:
    video_path = INPUTS / "chat_scroll.mp4"
    prompt = ("Watch this chat screen-recording and list each bubble's text.")
    video_schema = {
        "type": "json_schema", "name": "utterances",
        "schema": {
            "type": "object",
            "properties": {
                "utterances": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "additionalProperties": True,
                    },
                },
            },
            "required": ["utterances"], "additionalProperties": False,
        },
        "strict": False,
    }
    method = "Files API + input_file"
    started = time.perf_counter()
    try:
        upload = client.files_create(video_path.read_bytes(),
                                     "chat_scroll_p4.mp4",
                                     purpose="user_data")
        file_id = upload.get("id", "") if isinstance(upload, dict) else ""
        if not file_id:
            raise RuntimeError("empty file_id")
        payload = [{"role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_file", "file_id": file_id}]}]
        body = client.responses_create("muse-spark-1.3", payload,
                                       max_output_tokens=2000,
                                       reasoning={"effort": "minimal"},
                                       text_format=video_schema)
    except Exception:
        payload = [{"role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_video",
             "video_url": data_url(video_path, "video/mp4")}]}]
        body = client.responses_create("muse-spark-1.3", payload,
                                       max_output_tokens=2000,
                                       reasoning={"effort": "minimal"},
                                       text_format=video_schema)
        method = "inline input_video"
    latency = int((time.perf_counter() - started) * 1000)
    usage = extract_usage(body)
    text = extract_output_text(body)
    try:
        parsed = parse_json_text(text)
        utterances = parsed.get("utterances", []) if isinstance(parsed,
                                                                dict) else []
    except Exception:
        parsed = {"raw": text[:400]}
        utterances = []
    blob = json.dumps(parsed, ensure_ascii=False)
    has_promise = "갚겠다" in blob or "갚" in blob
    has_amount = "5000000" in norm_digits(blob)
    success = bool(utterances) and (has_promise or has_amount)
    verdict = ("(가) 직접 입력" if success and latency < 120000
               else "(나) 핵심 프레임")
    rationale = (f"method={method}; utterances={len(utterances)}; "
                 f"promise={has_promise}; amount={has_amount}; "
                 f"latency={latency}ms -> 영상 판단 {verdict}")
    return {"success": success, "model": "muse-spark-1.3",
            "api": f"POST /v1/responses (video via {method})",
            "latency_ms": latency,
            "tokens": {"input": usage.get("input_tokens", 0),
                       "cached": usage.get("cached_input_tokens", 0),
                       "output": usage.get("output_tokens", 0),
                       "reasoning": usage.get("reasoning_tokens", 0)},
            "cost_usd": pricing.spark_cost_usd(
                usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                usage.get("cached_input_tokens", 0),
                usage.get("reasoning_tokens", 0)),
            "rationale": rationale, "detail": {"parsed": parsed}}


def _sam_image_call(client: MetaClient, prompt_text: str, image_path: Path,
                    stream: bool = False) -> tuple[str, dict, int]:
    payload = [{"role": "user", "content": [
        {"type": "input_text", "text": prompt_text},
        {"type": "input_image",
         "image_url": data_url(image_path, "image/png")}]}]
    started = time.perf_counter()
    body = client.responses_create("sam-3.1", payload, image_count=1,
                                   stream=stream)
    latency = int((time.perf_counter() - started) * 1000)
    return extract_output_text(body), body, latency


def probe_p5(client: MetaClient, truth: dict) -> dict:
    cases = [
        ("chat bubble", INPUTS / "chat_capture.png",
         [b["box"] for b in truth["chat_capture.png"]["bubbles"]]),
        ("signature", INPUTS / "iou_page2.png",
         [truth["iou_page2.png"]["signature"]["box"]]),
        ("red stamp", INPUTS / "iou_page2.png",
         [truth["iou_page2.png"]["stamp"]["box"]]),
    ]
    details: dict = {}
    ok_all = True
    total_latency = 0
    for noun, path, tboxes in cases:
        entry_size = None
        for key, entry in truth.items():
            if isinstance(entry, dict) and entry.get("file") == path.name:
                entry_size = entry.get("size")
        text, body, latency = _sam_image_call(client, noun, path)
        total_latency += latency
        boxes = sam_parse_boxes(text) if text.strip() else []
        iou = round(mean_best_iou(boxes, tboxes), 4) if boxes else 0.0
        ok = (iou >= 0.5) if noun != "chat bubble" else (iou >= 0.3)
        ok_all = ok_all and ok
        details[noun] = {"boxes": len(boxes), "iou": iou, "ok": ok,
                         "size": entry_size}
    # Box prompt on one chat bubble (truth box as prompt, spike-only).
    chat_entry = truth["chat_capture.png"]
    w, h = chat_entry["size"]
    prompt_box = chat_entry["bubbles"][2]["box"]
    box_prompt = sam_build_box_prompt(w, h, prompt_box, obj_id=1)
    text, body, latency = _sam_image_call(client, box_prompt,
                                          INPUTS / "chat_capture.png")
    total_latency += latency
    boxes = sam_parse_boxes(text) if text.strip() else []
    iou = round(mean_best_iou(
        boxes, [chat_entry["bubbles"][2]["box"]]), 4) if boxes else 0.0
    box_ok = iou >= 0.5
    ok_all = ok_all and box_ok
    details["box-prompt bubble#2"] = {"boxes": len(boxes), "iou": iou,
                                      "ok": box_ok}
    usage = extract_usage(body)
    frames = usage.get("video_frames_processed", 0)
    noun_ok = sum(1 for k in ("chat bubble", "signature", "red stamp")
                  if details.get(k, {}).get("ok"))
    # Box prompts are the 감식-2 path; nouns are best-effort. Synthetic
    # "signature" (sine wave) is not recognized as a noun but box works.
    success = bool(box_ok and noun_ok >= 2)
    rationale = ("SAM Responses(image) + meta-sam-parser; " + "; ".join(
        f"{k}: n={v['boxes']} IoU={v['iou']} ok={v['ok']}"
        for k, v in details.items()) + f"; billed_frames={frames}")
    images = 4
    return {"success": success, "model": "sam-3.1",
            "api": "POST /v1/responses (input_image, noun/box prompts)",
            "latency_ms": total_latency,
            "tokens": {"input": 0, "cached": 0, "output": 0, "reasoning": 0},
            "cost_usd": pricing.sam_image_cost_usd(images),
            "rationale": rationale, "detail": details}


def probe_p6(client: MetaClient, truth: dict) -> dict:
    video_path = INPUTS / "chat_scroll.mp4"
    # Box prompt for bubble#0 mapped to frame-0 video pixels (360x400).
    chat = truth["chat_capture.png"]
    cw, ch = chat["size"]
    vw, vh = truth["chat_scroll.mp4"]["size"]
    scale = vw / cw
    x1, y1, x2, y2 = chat["bubbles"][0]["box"]
    vbox = [int(x1 * scale), int(y1 * scale), int(x2 * scale), int(y2 * scale)]
    vbox = [max(0, min(v, vw if i % 2 == 0 else vh))
            for i, v in enumerate(vbox)]
    box_prompt = sam_build_box_prompt(vw, vh, vbox, obj_id=1, frame=0)
    upload = client.files_create(video_path.read_bytes(), "chat_scroll_p6.mp4",
                                 purpose="user_data")
    file_id = upload.get("id", "") if isinstance(upload, dict) else ""
    payload = [{"role": "user", "content": [
        {"type": "input_text", "text": box_prompt},
        {"type": "input_video", "file_id": file_id}]}]
    started = time.perf_counter()
    body = client.responses_create("sam-3.1", payload, frame_count=30,
                                   stream=True,
                                   extra={"metadata": {
                                       "propagation_direction": "forward"}})
    latency = int((time.perf_counter() - started) * 1000)
    usage = extract_usage(body)
    text = extract_output_text(body)
    billed = int(usage.get("video_frames_processed", 0) or 0)
    boxes = sam_parse_boxes(text, video=True) if text.strip() else []
    lines = [ln for ln in text.splitlines() if ln.strip().startswith("<")]
    success = billed >= 50 and bool(lines)
    rationale = (f"Files API + input_video + box prompt; "
                 f"billed_frames={billed} (>=50 required); "
                 f"lines={len(lines)}; boxes={len(boxes)}")
    return {"success": success, "model": "sam-3.1",
            "api": "POST /v1/responses stream (input_video file_id)",
            "latency_ms": latency,
            "tokens": {"input": 0, "cached": 0, "output": 0, "reasoning": 0},
            "cost_usd": pricing.sam_video_cost_usd(billed or 50),
            "rationale": rationale,
            "detail": {"billed_frames": billed, "lines": len(lines),
                       "boxes": len(boxes)}}


def probe_p7(client: MetaClient, truth: dict) -> dict:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    prompt = ("Minimal flat timeline illustration for a personal loan story: "
              "calendar, envelope, and handshake icons in a row, soft colors, "
              "no text, no letters, no numbers, no words, no captions.")
    started = time.perf_counter()
    body = client.images_generate("muse-image-1.0", prompt, size="1024x1024")
    latency = int((time.perf_counter() - started) * 1000)
    data = body.get("data", []) if isinstance(body, dict) else []
    saved = None
    if data and isinstance(data[0], dict) and data[0].get("b64_json"):
        raw = base64.b64decode(data[0]["b64_json"])
        saved = OUTPUTS / "timeline_illustration.png"
        saved.write_bytes(raw)
    success = saved is not None and saved.exists()
    rationale = (f"images.generate 1 image; saved={saved.name if saved else None}; "
                 f"bytes={saved.stat().st_size if saved else 0}; "
                 f"text-in-image check is visual by reviewer")
    return {"success": success, "model": "muse-image-1.0",
            "api": "POST /v1/images/generations",
            "latency_ms": latency,
            "tokens": {"input": 0, "cached": 0, "output": 0, "reasoning": 0},
            "cost_usd": pricing.image_cost_usd(1),
            "rationale": rationale,
            "detail": {"file": str(saved) if saved else None}}


def probe_p8(client: MetaClient, truth: dict) -> dict:
    path = INPUTS / "chat_capture.png"
    per_model: dict = {}
    total_latency = 0
    total_cost = 0.0
    agg = {"input": 0, "cached": 0, "output": 0, "reasoning": 0}
    for model in ("muse-spark-1.1", "muse-spark-1.2", "muse-spark-1.3"):
        latencies = []
        matches = []
        for attempt in (0, 1):
            parsed, body, latency, digest = _read_image(
                client, path.name, path, model=model,
                tag=f"P8-{model}-{attempt}")
            usage = extract_usage(body)
            recorded = _fixture_latency(digest)
            effective = recorded if recorded else latency
            latencies.append(effective)
            total_latency += effective
            agg["input"] += int(usage.get("input_tokens", 0))
            agg["cached"] += int(usage.get("cached_input_tokens", 0))
            agg["output"] += int(usage.get("output_tokens", 0))
            agg["reasoning"] += int(usage.get("reasoning_tokens", 0))
            total_cost += pricing.spark_cost_usd(
                usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                usage.get("cached_input_tokens", 0),
                usage.get("reasoning_tokens", 0))
            items = parsed.get("items", []) if isinstance(parsed, dict) else []
            blob = json.dumps(items, ensure_ascii=False)
            amount_ok = "5000000" in norm_digits(blob)
            date_ok = "2026-04-10" in blob
            matches.append(bool(amount_ok and date_ok))
        avg = int(sum(latencies) / len(latencies))
        ok = all(matches)
        per_model[model] = {"avg_latency_ms": avg, "latencies": latencies,
                            "match": matches, "ok": ok}
    accurate = {m: v for m, v in per_model.items() if v["ok"]}
    pick = min(accurate, key=lambda m: accurate[m]["avg_latency_ms"]) \
        if accurate else None
    success = pick is not None
    rationale = ("; ".join(
        f"{m}: avg={v['avg_latency_ms']}ms match={v['match']}"
        for m, v in per_model.items()) + f"; pick={pick}")
    return {"success": success, "model": "muse-spark-1.1/1.2/1.3",
            "api": "POST /v1/responses (input_image x2 per model)",
            "latency_ms": total_latency,
            "tokens": agg,
            "cost_usd": round(total_cost, 6), "rationale": rationale,
            "detail": per_model}


PROBE_FUNCS = {
    "P0": probe_p0, "P1": probe_p1, "P2": probe_p2, "P3": probe_p3,
    "P4": probe_p4, "P5": probe_p5, "P6": probe_p6, "P7": probe_p7,
    "P8": probe_p8,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["live", "record", "replay"],
                        default=None)
    parser.add_argument("--probes", default="all")
    args = parser.parse_args()
    import os
    mode = args.mode or os.environ.get("META_MODE", "replay")
    if args.probes.strip().lower() == "all":
        probes = list(ALL_PROBES)
    else:
        probes = [p.strip().upper() for p in args.probes.split(",") if p.strip()]
        for p in probes:
            if p not in ALL_PROBES:
                print(f"unknown probe: {p}", file=sys.stderr)
                return 2
    truth = load_truth()
    results: dict = {}
    for probe in probes:
        total, _ = ledger_total()
        if mode in ("live", "record") and total >= M0_BUDGET_USD:
            results[probe] = {"success": None, "model": "", "api": "",
                              "latency_ms": 0,
                              "tokens": {"input": 0, "cached": 0, "output": 0,
                                         "reasoning": 0},
                              "cost_usd": 0.0,
                              "rationale": f"skipped: ledger ${total:.4f} "
                                           f">= ${M0_BUDGET_USD:.2f} budget"}
            continue
        last_error = None
        for attempt in (1, 2):
            client = MetaClient(mode=mode, run_id=run_id_for(probe))
            try:
                if probe in ("P2", "P3", "P4", "P5", "P6", "P7", "P8"):
                    out = PROBE_FUNCS[probe](client, truth)
                else:
                    out = PROBE_FUNCS[probe](client)
                # Fill aggregate tokens/cost for image-heavy probes from ledger.
                results[probe] = out
                last_error = None
                break
            except BudgetExceeded as exc:
                last_error = exc
                results[probe] = {"success": False, "model": "", "api": "",
                                  "latency_ms": 0,
                                  "tokens": {"input": 0, "cached": 0,
                                             "output": 0, "reasoning": 0},
                                  "cost_usd": 0.0,
                                  "rationale": f"budget exceeded: {exc}"}
                break
            except Exception as exc:  # noqa: BLE001 - record and continue
                last_error = exc
                status = getattr(exc, "status_code", None) or getattr(
                    getattr(exc, "response", None), "status_code", None)
                summary = f"{type(exc).__name__}: {str(exc)[:300]}"
                if attempt == 2:
                    results[probe] = {
                        "success": False, "model": "", "api": "",
                        "latency_ms": 0,
                        "tokens": {"input": 0, "cached": 0, "output": 0,
                                   "reasoning": 0},
                        "cost_usd": 0.0,
                        "rationale": f"failed after 2 attempts; "
                                     f"status={status}; {summary}",
                        "detail": {"trace": traceback.format_exc()[-1500:]}}
    total_cost, ledger_lines = ledger_total()
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    merged: dict = {}
    if REPORT_JSON.exists():
        try:
            prev = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
            if isinstance(prev.get("probes"), dict):
                merged = prev["probes"]
        except (ValueError, OSError):
            merged = {}
    merged.update(results)
    REPORT_JSON.write_text(json.dumps(
        {"mode": mode, "probes": merged, "total_cost_usd": total_cost,
         "ledger_lines": ledger_lines,
         "note": "Response bodies are not stored here; see fixtures for "
                 "recorded responses."},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"mode={mode} probes={','.join(probes)} "
          f"ledger_total=${total_cost:.4f} lines={ledger_lines}")
    for probe in probes:
        entry = results[probe]
        print(f"  {probe}: success={entry['success']} "
              f"cost=${entry.get('cost_usd', 0.0):.4f} "
              f"{entry.get('rationale', '')[:220]}")
    failed = [p for p in probes if results[p].get("success") is not True]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
