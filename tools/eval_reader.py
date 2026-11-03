"""M4b reader eval: truth-box scoring + live/record/replay runs.

Usage:
  python tools\\eval_reader.py --mode live --models muse-spark-1.2,muse-spark-1.3 --runs 3
  python tools\\eval_reader.py --mode replay   # same tables from recorded results

Scoring is truth-box-based (M0 review 2): every golden item takes the
best same-kind prediction box (pixels). Metrics: amount/date value match
(target 95%), truth-box IoU>=0.3 rate, miss rate, schema-fail/incomplete
rates, verbatim rate, latency p50/p95, cost. ignore_regions (watermark
band) excluded. The golden file is read by this tool only, never by
runtime agents.

Results live in reports/M4b-reader-eval.json under experiment names
(--exp); --mode replay recomputes every table from those records without
any key or network access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.agents import reader as reader_mod  # noqa: E402
from app.agents.base import AgentSchemaError  # noqa: E402
from app.agents import deps  # noqa: E402
from app.meta.coords import box_iou  # noqa: E402

GOLDEN = ROOT / "backend" / "tests" / "golden" / "kr_truth.json"
SAMPLE = ROOT / "sample_evidence"
DEFAULT_OUT = ROOT / "reports" / "M4b-reader-eval.json"
DEFAULT_WORK = ROOT / ".local" / "m4b_eval"
STILL_EX = ["EX1", "EX2", "EX4", "EX5", "EX6"]


# --- golden -----------------------------------------------------------------

def load_golden(path: Path = GOLDEN) -> dict:
    """Golden answers (evals/tests only). Returns per-ex evidence + items."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    evidences = {}
    for entry in data["evidences"]:
        evidences[entry["ex_id"]] = {
            "file": entry["file"],
            "width": int(entry["width"]),
            "height": int(entry["height"]),
            "sha256": entry.get("sha256"),
            "ignore": [list(r) for r in entry.get("ignore_regions", [])],
            "coord_basis": entry.get("coord_basis"),
        }
    items: dict = {}
    for item in data["items"]:
        items.setdefault(item["ex_id"], []).append(item)
    return {"evidences": evidences, "items": items}


def _center_in(box, regions) -> bool:
    cx = (float(box[0]) + float(box[2])) / 2.0
    cy = (float(box[1]) + float(box[3])) / 2.0
    for x1, y1, x2, y2 in regions:
        if float(x1) <= cx <= float(x2) and float(y1) <= cy <= float(y2):
            return True
    return False


def _digits(text) -> str:
    return "".join(c for c in str(text or "") if c.isdigit())


def norm_equal(kind: str, pred, truth) -> bool:
    """Normalized-value equality for amount/date/phone/account_number."""
    if pred is None and truth is None:
        return True
    if pred is None or truth is None:
        return False
    if kind == "amount":
        try:
            return int(_digits(pred)) == int(truth)
        except (ValueError, TypeError):
            return False
    if kind == "date":
        return str(pred).strip() == str(truth).strip()
    if kind in ("phone", "account_number"):
        return _digits(pred) == _digits(truth) and bool(_digits(truth))
    return False


def _pred_box_list(item: dict) -> list:
    box = item.get("box") or {}
    return [box.get("x1", 0), box.get("y1", 0),
            box.get("x2", 0), box.get("y2", 0)]


def score_evidence(truth_items: list, pred_items: list,
                   ignore: list) -> dict:
    """Score one evidence: rows per truth item + aggregates.

    Each non-ignored truth item takes the best same-kind prediction box
    (max IoU, pixels). Predictions centered in ignore_regions never match.
    """
    scored = [t for t in truth_items
              if not _center_in(t["box"], ignore)]
    cands = [p for p in pred_items
             if not _center_in(_pred_box_list(p), ignore)]
    by_kind: dict = {}
    for pred in cands:
        by_kind.setdefault(str(pred.get("kind")), []).append(pred)
    rows = []
    for truth in scored:
        kind = str(truth.get("kind"))
        options = by_kind.get(kind, [])
        text = str(truth.get("text_verbatim", "")).strip()
        text_hit = any(str(p.get("text_verbatim", "")).strip() == text
                       for p in options)
        ious = [box_iou(truth["box"], _pred_box_list(p)) for p in options]
        best = max(ious) if ious else 0.0
        row = {
            "ex_id": truth.get("ex_id"), "item_id": truth.get("item_id"),
            "kind": kind, "text_hit": text_hit, "best_iou": round(best, 4),
            "box_ok": bool(best >= 0.3), "miss": bool(best <= 0.0),
            "value_ok": None, "frame_ok": None, "frame_err": None,
        }
        if kind in ("amount", "date"):
            row["value_ok"] = any(
                norm_equal(kind, p.get("normalized"), truth.get("normalized"))
                and (str(p.get("text_verbatim", "")).strip() == text
                     or box_iou(truth["box"], _pred_box_list(p)) >= 0.3)
                for p in options)
        if truth.get("frame_ts") is not None:
            diffs = [abs(float(p["frame_ts"]) - float(truth["frame_ts"]))
                     for p in options
                     if str(p.get("text_verbatim", "")).strip() == text
                     and p.get("frame_ts") is not None]
            if diffs:
                row["frame_err"] = round(min(diffs), 3)
                row["frame_ok"] = bool(min(diffs) <= 0.5)
        rows.append(row)

    def _rate(key: str, only: set | None = None) -> dict:
        pool = [r for r in rows if only is None or r["kind"] in only]
        vals = [r[key] for r in pool if r[key] is not None]
        if not vals:
            return {"n": 0, "rate": None}
        return {"n": len(vals),
                "rate": round(sum(1 for v in vals if v) / len(vals), 4)}

    framed = [r for r in rows if r["frame_ok"] is not None]
    return {
        "rows": rows,
        "n_truth": len(rows),
        "text_recall": _rate("text_hit"),
        "box03": _rate("box_ok"),
        "miss": _rate("miss"),
        "value": _rate("value_ok", {"amount", "date"}),
        "frame": {"n": len(framed),
                  "rate": (round(sum(1 for r in framed if r["frame_ok"])
                                 / len(framed), 4) if framed else None)},
    }


def _percentile(values: list, pct: float):
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct / 100.0
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return round(ordered[low] * (1 - frac) + ordered[high] * frac, 1)


def score_runs(runs: list, golden: dict) -> dict:
    """Aggregate scored runs into model/evidence/kind tables (pure)."""
    items = golden["items"]
    ignore = {ex: meta["ignore"] for ex, meta in golden["evidences"].items()}
    per_model: dict = {}
    per_evidence: dict = {}
    per_kind: dict = {}
    calls = {"n": 0, "schema_failed": 0, "incomplete": 0, "error": 0}
    model_calls: dict = {}
    lat: dict = {}
    cost: dict = {}
    for run in runs:
        model = run["model"]
        calls["n"] += 1
        slot_calls = model_calls.setdefault(
            model, {"n": 0, "schema_failed": 0, "incomplete": 0, "error": 0})
        slot_calls["n"] += 1
        status = run.get("status")
        if status != "ok":
            key = {"schema_failed": "schema_failed",
                   "incomplete": "incomplete"}.get(status, "error")
            calls[key] += 1
            slot_calls[key] += 1
            continue
        lat.setdefault(model, []).append(run.get("latency_ms", 0))
        cost[model] = cost.get(model, 0.0) + float(run.get("cost_usd", 0.0))
        scored = score_evidence(items.get(run["ex_id"], []),
                                run.get("items", []),
                                ignore.get(run["ex_id"], []))
        slot = per_model.setdefault(model, {"rows": [], "cost": 0.0})
        slot["rows"].extend(scored["rows"])
        slot["cost"] += float(run.get("cost_usd", 0.0))
        per_evidence.setdefault(run["ex_id"], {}).setdefault(
            model, {"rows": []})["rows"].extend(scored["rows"])
        for row in scored["rows"]:
            per_kind.setdefault(row["kind"], {}).setdefault(
                model, {"rows": []})["rows"].extend([row])

    def _agg(rows: list) -> dict:
        out = {}
        n = len(rows)
        out["n"] = n
        for key, kinds in (("text_hit", None), ("box_ok", None),
                           ("miss", None), ("value_ok", {"amount", "date"})):
            pool = [r for r in rows
                    if (kinds is None or r["kind"] in kinds)
                    and r[key] is not None]
            out[{"text_hit": "verbatim", "box_ok": "box03",
                 "miss": "miss", "value_ok": "value"}[key]] = {
                "n": len(pool),
                "rate": (round(sum(1 for r in pool if r[key]) / len(pool), 4)
                         if pool else None)}
        framed = [r for r in rows if r["frame_ok"] is not None]
        out["frame"] = {"n": len(framed),
                        "rate": (round(sum(1 for r in framed if r["frame_ok"])
                                       / len(framed), 4) if framed else None)}
        return out

    models = {}
    for model, slot in per_model.items():
        agg = _agg(slot["rows"])
        agg["cost"] = round(slot["cost"], 6)
        agg["p50_ms"] = _percentile(lat.get(model, []), 50)
        agg["p95_ms"] = _percentile(lat.get(model, []), 95)
        agg["calls"] = model_calls.get(model, {})
        models[model] = agg
    for model in model_calls:
        models.setdefault(model, {"n": 0, "cost": 0.0, "p50_ms": None,
                                  "p95_ms": None,
                                  "calls": model_calls[model]})
    evidence = {ex: {m: _agg(s["rows"]) for m, s in by_model.items()}
                for ex, by_model in per_evidence.items()}
    kinds = {k: {m: _agg(s["rows"]) for m, s in by_model.items()}
             for k, by_model in per_kind.items()}
    total = calls["n"] or 1
    return {
        "models": models,
        "evidence": evidence,
        "kinds": kinds,
        "calls": {**calls,
                  "schema_rate": round(calls["schema_failed"] / total, 4),
                  "incomplete_rate": round(calls["incomplete"] / total, 4)},
    }


def decide(summary: dict) -> dict:
    """M4b brief decision rule over the model table."""
    models = summary.get("models", {})
    if len(models) < 2:
        return {"model": None, "reason": "비교 대상이 2개 미만"}
    rows = sorted(models.items())
    passing = [(m, s) for m, s in rows
               if (s.get("value") or {}).get("rate") is not None
               and s["value"]["rate"] >= 0.95]
    if passing:
        best = min(passing, key=lambda kv: kv[1].get("p95_ms")
                   if kv[1].get("p95_ms") is not None else float("inf"))
        return {"model": best[0],
                "reason": "값 일치율 95% 이상 중 p95 지연이 가장 짧음"}
    best = max(rows, key=lambda kv: (kv[1].get("value") or {}).get("rate")
               if (kv[1].get("value") or {}).get("rate") is not None else -1)
    return {"model": best[0], "reason": "둘 다 95% 미달, 값 일치율이 높은 쪽"}


# --- live/record driver -------------------------------------------------------

def _preview_size(png_path: Path) -> tuple:
    from PIL import Image

    with Image.open(png_path) as image:
        return (int(image.width), int(image.height))


def _stage_ex6_preview(work_dir: Path) -> Path:
    """Case-like layout so the reader finds EX6_preview.png next to EX6 pdf."""
    staged = work_dir / "case_layout"
    staged.mkdir(parents=True, exist_ok=True)
    pdf = staged / "EX6_iou.pdf"
    png = staged / "EX6_preview.png"
    if not pdf.exists():
        pdf.write_bytes((SAMPLE / "kr" / "iou.pdf").read_bytes())
    if not png.exists():
        png.write_bytes((SAMPLE / "kr" / "iou.png").read_bytes())
    return pdf


def _slim_items(items: list) -> list:
    slim = []
    for item in items or []:
        row = {"kind": item.get("kind"),
               "text_verbatim": item.get("text_verbatim"),
               "normalized": item.get("normalized"),
               "box": item.get("box")}
        if item.get("frame_ts") is not None:
            row["frame_ts"] = item["frame_ts"]
        if item.get("box_warning") is not None:
            row["box_warning"] = item["box_warning"]
        slim.append(row)
    return slim


def run_one(model: str, run_index: int, ex_id: str, cfg: dict) -> dict:
    """One evidence read through the real reader (live/record)."""
    golden = cfg["golden"]
    meta = golden["evidences"][ex_id]
    prompt_version = Path(cfg["prompt_file"]).stem
    if cfg["exp"] == "compare":
        run_id = f"M4b-eval-{model}-{run_index}"
    else:
        run_id = f"M4b-eval-{cfg['exp']}-{model}-{run_index}"
    record = {"exp": cfg["exp"], "model": model, "run": run_index,
              "ex_id": ex_id, "prompt_version": prompt_version,
              "reader_mode": cfg["reader_mode_label"],
              "effort": cfg["effort"], "status": "ok", "items": []}
    try:
        if ex_id == "EX3":
            src = SAMPLE / meta["file"]
            output = reader_mod.run_video_reader(
                "eval", {"ex_id": ex_id, "kind": "video",
                         "filename": src.name},
                src, cfg["mode"], run_id,
                model=model, prompt_file=cfg["prompt_file"],
                tile_max_aspect=cfg["tile_max_aspect"],
                tile_overlap=cfg["tile_overlap"],
                square_pad=cfg["square_pad"],
                reasoning_effort=cfg["effort"],
                work_dir=cfg["work_dir"] / "keyframes",
            )
            record["keyframes"] = output.get("keyframes", [])
            record["tile_calls"] = output.get("tile_calls", 0)
        else:
            src = SAMPLE / meta["file"]
            if meta["file"].endswith(".pdf"):
                src = _stage_ex6_preview(cfg["work_dir"])
                preview = src.parent / "EX6_preview.png"
                size = _preview_size(preview)
                kind, filename = "pdf", "iou.pdf"
            else:
                size = _preview_size(src)
                kind, filename = "image", src.name
            output = reader_mod.run_reader(
                "eval", {"ex_id": ex_id, "kind": kind, "filename": filename},
                src, size, cfg["mode"], run_id,
                model=model, prompt_file=cfg["prompt_file"],
                tile_max_aspect=cfg["tile_max_aspect"],
                tile_overlap=cfg["tile_overlap"],
                square_pad=cfg["square_pad"],
                reasoning_effort=cfg["effort"],
            )
            record["tiles"] = output.get("tiles", 1)
        record.update({key: output.get(key, 0) for key in
                       ("latency_ms", "attempts", "tokens_in", "tokens_out",
                        "cost_usd")})
        record["items"] = _slim_items(output.get("items"))
    except AgentSchemaError as exc:
        from app.meta.client import IncompleteResponse

        record["status"] = ("incomplete"
                            if isinstance(exc.__cause__, IncompleteResponse)
                            else "schema_failed")
        record["error"] = str(exc)[:300]
    except Exception as exc:  # noqa: BLE001 - recorded, never raised
        record["status"] = "error"
        record["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    return record


def _mode_label(args) -> tuple:
    if args.reader_mode == "whole":
        return ("whole", 1e9, reader_mod.TILE_OVERLAP, False)
    if args.reader_mode == "pad":
        return ("pad", reader_mod.TILE_MAX_ASPECT, reader_mod.TILE_OVERLAP,
                True)
    if args.reader_mode == "tiles":
        aspect = (args.tile_aspect if args.tile_aspect is not None
                  else reader_mod.TILE_MAX_ASPECT)
        overlap = (args.tile_overlap if args.tile_overlap is not None
                   else reader_mod.TILE_OVERLAP)
        return (f"tiles@{aspect}/{overlap}", aspect, overlap, False)
    return ("auto", None, None, None)


def run_experiment(args, golden: dict, store: dict) -> dict:
    """Live/record experiment: call models, score, store under --exp."""
    label, aspect, overlap, pad = _mode_label(args)
    evidence = ([e for e in STILL_EX if e in args.evidence]
                + (["EX3"] if args.video else []))
    cfg = {"exp": args.exp, "mode": args.mode, "golden": golden,
           "prompt_file": args.prompt_file, "effort": args.effort,
           "reader_mode_label": label, "tile_max_aspect": aspect,
           "tile_overlap": overlap, "square_pad": pad,
           "work_dir": Path(args.work_dir)}
    jobs = []
    for model in args.models:
        for num in range(1, args.runs + 1):
            for ex_id in evidence:
                jobs.append((model, num, ex_id))
    runs: list = []
    if args.jobs <= 1:
        for model, num, ex_id in jobs:
            runs.append(run_one(model, num, ex_id, cfg))
            print(f"[{args.exp}] {model} run{num} {ex_id}: "
                  f"{runs[-1]['status']}", flush=True)
    else:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            pending = [pool.submit(run_one, model, num, ex_id, cfg)
                       for model, num, ex_id in jobs]
            for (model, num, ex_id), future in zip(jobs, pending):
                record = future.result()
                runs.append(record)
                print(f"[{args.exp}] {model} run{num} {ex_id}: "
                      f"{record['status']}", flush=True)
    runs.sort(key=lambda r: (r["model"], r["run"], r["ex_id"]))
    summary = score_runs(runs, golden)
    store["experiments"][args.exp] = {
        "config": {"models": args.models, "runs": args.runs,
                   "evidence": evidence, "prompt_file": args.prompt_file,
                   "effort": args.effort, "reader_mode": label,
                   "mode": args.mode},
        "runs": runs,
        "summary": summary,
        "decision": decide(summary),
    }
    return store["experiments"][args.exp]


# --- tables -------------------------------------------------------------------

def _pct(cell: dict) -> str:
    if not cell or cell.get("rate") is None:
        return "   -- "
    return f"{cell['rate'] * 100:6.1f}"


def format_experiment(name: str, exp: dict) -> str:
    """Human-readable tables for one experiment (replay-identical)."""
    cfg = exp.get("config", {})
    summary = exp.get("summary", {})
    lines = [f"== M4b reader eval: exp={name} "
             f"(prompt {cfg.get('prompt_file')}, {cfg.get('reader_mode')}, "
             f"effort {cfg.get('effort')}) =="]
    lines.append("model               runs   value%   box03%  verbatim%  "
                 "miss%  schema%  incompl%   p50ms   p95ms     cost")
    calls = summary.get("calls", {})
    total = calls.get("n", 0)
    for model in sorted(summary.get("models", {})):
        agg = summary["models"][model]
        mcalls = agg.get("calls", {})
        mt = mcalls.get("n", 0) or 1
        model_runs = sum(1 for r in exp.get("runs", [])
                         if r["model"] == model and r.get("status") == "ok")
        lines.append(
            f"{model:18s} {model_runs:4d}  {_pct(agg.get('value'))} "
            f"{_pct(agg.get('box03'))} {_pct(agg.get('verbatim'))} "
            f"{_pct(agg.get('miss'))} "
            f"{mcalls.get('schema_failed', 0) / mt * 100:6.1f} "
            f"{mcalls.get('incomplete', 0) / mt * 100:7.1f} "
            f"{str(agg.get('p50_ms')):>6s} {str(agg.get('p95_ms')):>6s} "
            f"${agg.get('cost', 0):.4f}")
    lines.append(f"calls: {total} total, {calls.get('schema_failed', 0)} "
                 f"schema_failed, {calls.get('incomplete', 0)} incomplete, "
                 f"{calls.get('error', 0)} error")
    decision = exp.get("decision", {})
    if decision.get("model"):
        lines.append(f"decision: {decision['model']} ({decision['reason']})")
    lines.append("-- per evidence (value% / box03%) --")
    for ex_id in sorted(summary.get("evidence", {})):
        cells = "  ".join(
            f"{m}: {_pct(a.get('value'))}/{_pct(a.get('box03'))}"
            for m, a in sorted(summary["evidence"][ex_id].items()))
        lines.append(f"  {ex_id}: {cells}")
    lines.append("-- per kind (verbatim% / box03%) --")
    for kind in sorted(summary.get("kinds", {})):
        cells = "  ".join(
            f"{m}: {_pct(a.get('verbatim'))}/{_pct(a.get('box03'))}"
            for m, a in sorted(summary["kinds"][kind].items()))
        lines.append(f"  {kind}: {cells}")
    framed = [(m, a.get("frame")) for m, a in
              summary.get("models", {}).items()
              if (a.get("frame") or {}).get("rate") is not None]
    if framed:
        cells = "  ".join(f"{m}: {_pct(f)} (n={f['n']})" for m, f in framed)
        lines.append(f"-- video frame_ts +-0.5s --  {cells}")
    return "\n".join(lines)


def load_store(path: Path) -> dict:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("experiments", {})
        return data
    return {"version": 1, "golden_sha256": None, "experiments": {}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="M4b reader eval")
    parser.add_argument("--mode", default="replay",
                        choices=["live", "record", "replay"])
    parser.add_argument("--exp", default="compare")
    parser.add_argument("--models", default="muse-spark-1.2,muse-spark-1.3")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--evidence", default=",".join(STILL_EX))
    parser.add_argument("--video", action="store_true")
    parser.add_argument("--prompt-file", default=reader_mod.PROMPT_FILE)
    parser.add_argument("--effort", default=reader_mod.REASONING_EFFORT)
    parser.add_argument("--reader-mode", default="auto",
                        choices=["auto", "whole", "tiles", "pad"])
    parser.add_argument("--tile-aspect", type=float, default=None)
    parser.add_argument("--tile-overlap", type=float, default=None)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--work-dir", default=str(DEFAULT_WORK))
    parser.add_argument("--golden", default=str(GOLDEN))
    args = parser.parse_args(argv)
    args.models = [m.strip() for m in str(args.models).split(",") if m.strip()]
    args.evidence = [e.strip().upper() for e in str(args.evidence).split(",")
                     if e.strip()]
    golden = load_golden(Path(args.golden))
    out_path = Path(args.out)
    store = load_store(out_path)
    if args.mode == "replay":
        if args.exp not in store["experiments"] and args.exp != "all":
            print(f"no experiment {args.exp!r} in {out_path}", file=sys.stderr)
            return 1
        names = ([args.exp] if args.exp != "all"
                 else sorted(store["experiments"]))
        for name in names:
            exp = store["experiments"][name]
            # Recompute from stored runs: identical tables, no key needed.
            exp["summary"] = score_runs(exp.get("runs", []), golden)
            print(format_experiment(name, exp))
            print()
        return 0
    if args.mode in ("live", "record") and not args.models:
        print("need --models for live/record mode", file=sys.stderr)
        return 1
    if not (args.models and all(
            (m in ("muse-spark-1.2", "muse-spark-1.3")) for m in args.models)):
        print("only muse-spark-1.2/1.3 Standard models allowed",
              file=sys.stderr)
        return 1
    exp = run_experiment(args, golden, store)
    store["golden_sha256"] = hashlib.sha256(
        Path(args.golden).read_bytes()).hexdigest()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(store, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print()
    print(format_experiment(args.exp, exp))
    if args.mode in ("live", "record"):
        try:
            from app.meta.client import ledger_summary

            summary = ledger_summary()
            hits = {k: v for k, v in summary.get("by_run_id", {}).items()
                    if str(k).startswith("M4b-eval-")}
            total = sum(float(v) for v in hits.values())
            print(f"ledger M4b-eval-* run_ids: {len(hits)}, "
                  f"total ${total:.4f}")
        except Exception as exc:  # noqa: BLE001 - info only
            print(f"(ledger summary unavailable: {exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
