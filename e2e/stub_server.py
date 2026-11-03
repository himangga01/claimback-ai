"""M2b E2E stub server (FastAPI).

Serves the fixed example responses in specs/case-api-examples/*.json with
``stub: true`` so the case-flow UI and E2E test can be developed before the
M2a backend exists. Mimics state progression and per-step latency.

Reads only: specs/case-api-examples/*.json, sample_evidence/kr/*.
Never reads backend/tests/golden/.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "specs" / "case-api-examples"
SAMPLE_KR = ROOT / "sample_evidence" / "kr"
FRONTEND = ROOT / "frontend"

STEP_DELAY = 0.3  # seconds of fake latency per step
META_MODE = "replay"

EVIDENCE_ORDER = [
    ("EX1", "chat_01.png", "image"),
    ("EX2", "chat_02_tall.png", "image"),
    ("EX3", "chat_02_scroll.mp4", "video"),
    ("EX4", "transfer_loan.png", "image"),
    ("EX5", "transfer_repay.png", "image"),
    ("EX6", "iou.pdf", "pdf"),
]
EX6_PREVIEW = "iou.png"

STATE_ORDER = [
    "INTAKE",
    "READING",
    "ORGANIZING",
    "CHECKPOINT_1",
    "CALCULATING",
    "DRAFTING",
    "VERIFYING",
    "DRAFT_APPROVAL",
    "PACKAGING",
    "CHECKPOINT_2",
]


def _load(name: str) -> Any:
    with open(EXAMPLES / name, encoding="utf-8") as f:
        return json.load(f)


CASE_VIEW_EXAMPLE = _load("case_view.json")
READINGS_EXAMPLE = _load("readings.json")
REVIEW_EXAMPLE = _load("review.json")
DRAFTS_EXAMPLE = _load("drafts.json")
PACKAGE_EXAMPLE = _load("package.json")

STEP_DEFS = [
    {
        "key": s["key"],
        "agent": s["agent"],
        "group": s["group"],
        "model": s["model"],
        "note": s.get("note", ""),
    }
    for s in CASE_VIEW_EXAMPLE["steps"]
]
SUBSTEP_EX = next(
    s.get("substeps", []) for s in CASE_VIEW_EXAMPLE["steps"] if s["key"] == "reading"
)

G1A_DIGIT_RE = re.compile(r"[0-9]")
G1A_SNIPPET_RE = re.compile(r"[0-9][0-9,]*\s*만\s*원|[0-9][0-9,]*|만\s*원")
SLOT_RE = re.compile(r"\{\{.*?\}\}")
REF_RE = re.compile(r"\[\[.*?\]\]")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _fresh_steps() -> List[Dict[str, Any]]:
    steps = []
    for d in STEP_DEFS:
        steps.append(
            {
                "key": d["key"],
                "agent": d["agent"],
                "group": d["group"],
                "model": d["model"],
                "status": "waiting",
                "started_at": None,
                "ended_at": None,
                "latency_ms": 0,
                "attempts": 0,
                "cost_usd": "0",
                "note": d["note"] if d["key"] in ("vision", "privacy") else "",
                "substeps": [],
            }
        )
    return steps


def _sample_evidence(case_id: str) -> List[Dict[str, Any]]:
    evidence = []
    for ex_id, filename, kind in EVIDENCE_ORDER:
        status = "skipped" if ex_id == "EX3" else "ok"
        preview: Optional[str] = None
        if kind in ("image", "pdf"):
            preview = f"/api/cases/{case_id}/evidence/{ex_id}/preview"
        evidence.append(
            {
                "ex_id": ex_id,
                "label": f"갑 제{ex_id[2:]}호증",
                "filename": filename,
                "sha256": _sha256_file(SAMPLE_KR / filename),
                "kind": kind,
                "status": status,
                "url": f"/api/cases/{case_id}/evidence/{ex_id}/file",
                "preview_url": preview,
            }
        )
    return evidence


def _case_view(case: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "jurisdiction": case["jurisdiction"],
        "state": case["state"],
        "meta_mode": META_MODE,
        "run_cost_usd": CASE_VIEW_EXAMPLE["run_cost_usd"],
        "stub": True,
        "hold_reasons": case["hold_reasons"],
        "steps": case["steps"],
        "evidence": case["evidence"],
    }


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"code": code, "message": message, "missing_requirements": []},
    )


def _get_case(case_id: str) -> Dict[str, Any]:
    case = CASES.get(case_id)
    if case is None:
        raise _err(404, "not_found", "사건을 찾을 수 없습니다.")
    return case


def _step(case: Dict[str, Any], key: str) -> Dict[str, Any]:
    for s in case["steps"]:
        if s["key"] == key:
            return s
    raise KeyError(key)


def _mark_running(step: Dict[str, Any]) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%S+09:00", time.localtime())
    step["status"] = "running"
    step["started_at"] = now
    step["attempts"] = 1


def _mark_done(step: Dict[str, Any], note: str = "") -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%S+09:00", time.localtime())
    step["status"] = "done"
    step["ended_at"] = now
    step["latency_ms"] = int(STEP_DELAY * 1000)
    if note:
        step["note"] = note


def _mark_skipped(step: Dict[str, Any]) -> None:
    step["status"] = "skipped"
    step["note"] = "이 버전에서는 사용하지 않음"


def _run_sequence(case: Dict[str, Any], phases: List[Any]) -> None:
    """ phases: list of (state, step_key, kind, note) with kind in done|skipped|running. """
    for state, key, kind, note in phases:
        with case["lock"]:
            case["state"] = state
            step = _step(case, key)
            _mark_running(step)
            if key == "reading":
                subs = copy.deepcopy(SUBSTEP_EX)
                for sub in subs:
                    sub["latency_ms"] = (
                        0 if sub["status"] == "skipped" else int(STEP_DELAY * 1000)
                    )
                step["substeps"] = subs
        time.sleep(STEP_DELAY)
        with case["lock"]:
            step = _step(case, key)
            if kind == "done":
                _mark_done(step, note)
            elif kind == "skipped":
                _mark_skipped(step)
            # kind == "running": stays running (user checkpoint step)


CASES: Dict[str, Dict[str, Any]] = {}
CASES_LOCK = threading.Lock()


def _new_case(jurisdiction: str, with_sample: bool) -> Dict[str, Any]:
    case_id = "case_" + secrets.token_hex(6)
    case: Dict[str, Any] = {
        "case_id": case_id,
        "jurisdiction": jurisdiction,
        "state": "INTAKE",
        "hold_reasons": [],
        "steps": _fresh_steps(),
        "evidence": _sample_evidence(case_id) if with_sample else [],
        "uploads": {},
        "confirmed": None,
        "drafts": copy.deepcopy(DRAFTS_EXAMPLE),
        "lock": threading.RLock(),
        "run_lock": threading.Lock(),
    }
    with CASES_LOCK:
        CASES[case_id] = case
    return case


def _build_stub_pdf() -> bytes:
    lines = [
        "%PDF-1.4",
        "1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj",
        "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj",
        "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj",
        "4 0 obj<</Length 52>>stream",
        "BT /F1 18 Tf 72 780 Td (STUB DATA draft file) Tj ET",
        "endstream endobj",
        "5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj",
    ]
    out = bytearray()
    offsets = []
    for line in lines:
        if line.endswith("endobj") or line.startswith("BT "):
            pass
        if re.match(r"^\d+ 0 obj", line):
            offsets.append(len(out))
        out += line.encode("ascii") + b"\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(offsets) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer<</Size {len(offsets) + 1}/Root 1 0 R>>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)


STUB_PDF = _build_stub_pdf()


def _g1a_check(text_with_slots: str) -> Optional[str]:
    """Simple G1a rule: digits or '만 원' outside {{slots}}/[[refs]] are flagged."""
    stripped = SLOT_RE.sub("", text_with_slots)
    stripped = REF_RE.sub("", stripped)
    if "만 원" in stripped or "만원" in stripped or G1A_DIGIT_RE.search(stripped):
        m = G1A_SNIPPET_RE.search(stripped)
        return m.group(0) if m else "숫자"
    return None


app = FastAPI(title="ClaimBack-AI M2b stub server")


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "healthy", "stub": True}


@app.post("/api/cases")
def create_case(body: Dict[str, Any]) -> Dict[str, Any]:
    jurisdiction = body.get("jurisdiction", "KR")
    case = _new_case(jurisdiction, with_sample=False)
    return _case_view(case)


@app.post("/api/cases/sample")
def create_sample(body: Dict[str, Any]) -> Dict[str, Any]:
    if body.get("set", "kr") != "kr":
        raise _err(400, "bad_request", "이 가짜 서버는 kr 세트만 제공합니다.")
    case = _new_case("KR", with_sample=True)
    return _case_view(case)


@app.get("/api/cases/{case_id}")
def get_case(case_id: str) -> Dict[str, Any]:
    case = _get_case(case_id)
    with case["lock"]:
        return _case_view(case)


@app.delete("/api/cases/{case_id}")
def delete_case(case_id: str) -> Dict[str, Any]:
    with CASES_LOCK:
        if case_id not in CASES:
            raise _err(404, "not_found", "사건을 찾을 수 없습니다.")
        del CASES[case_id]
    return {"deleted": True}


@app.post("/api/cases/{case_id}/evidence")
async def upload_evidence(case_id: str, files: List[UploadFile] = File(...)) -> Dict[str, Any]:
    case = _get_case(case_id)
    with case["lock"]:
        existing = [e["ex_id"] for e in case["evidence"]]
        n = 1
        for f in files:
            data = await f.read()
            while f"EX{n}" in existing:
                n += 1
            ex_id = f"EX{n}"
            existing.append(ex_id)
            n += 1
            name = (f.filename or "upload").lower()
            if name.endswith(".mp4"):
                kind = "video"
            elif name.endswith(".pdf"):
                kind = "pdf"
            else:
                kind = "image"
            case["uploads"][ex_id] = bytes(data)
            case["evidence"].append(
                {
                    "ex_id": ex_id,
                    "label": f"갑 제{ex_id[2:]}호증",
                    "filename": f.filename or ex_id,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "kind": kind,
                    "status": "ok",
                    "url": f"/api/cases/{case_id}/evidence/{ex_id}/file",
                    "preview_url": (
                        f"/api/cases/{case_id}/evidence/{ex_id}/preview"
                        if kind in ("image", "pdf")
                        else None
                    ),
                }
            )
        return _case_view(case)


def _evidence_file(case: Dict[str, Any], ex_id: str, preview: bool) -> Response:
    ev = next((e for e in case["evidence"] if e["ex_id"] == ex_id), None)
    if ev is None:
        raise _err(404, "not_found", "증거를 찾을 수 없습니다.")
    if ex_id in case["uploads"]:
        data = case["uploads"][ex_id]
        name = ev["filename"].lower()
        media = "application/pdf" if name.endswith(".pdf") else "image/png"
        if ev["kind"] == "video":
            media = "video/mp4"
        return Response(content=data, media_type=media)
    filename = ev["filename"]
    if preview and ex_id == "EX6":
        filename = EX6_PREVIEW
    path = SAMPLE_KR / filename
    if not path.is_file():
        raise _err(404, "not_found", "증거 파일을 찾을 수 없습니다.")
    return FileResponse(path)


@app.get("/api/cases/{case_id}/evidence/{ex_id}/file")
def evidence_file(case_id: str, ex_id: str) -> Response:
    return _evidence_file(_get_case(case_id), ex_id, preview=False)


@app.get("/api/cases/{case_id}/evidence/{ex_id}/preview")
def evidence_preview(case_id: str, ex_id: str) -> Response:
    return _evidence_file(_get_case(case_id), ex_id, preview=True)


@app.post("/api/cases/{case_id}/run")
def run_case(case_id: str) -> Dict[str, Any]:
    case = _get_case(case_id)
    if not case["run_lock"].acquire(blocking=False):
        raise _err(409, "wrong_state", "같은 사건이 이미 실행 중입니다.")
    try:
        with case["lock"]:
            state = case["state"]
        if state == "INTAKE":
            _run_sequence(
                case,
                [
                    ("READING", "intake", "done", "증거 6개, SHA-256 기록"),
                    ("READING", "reading", "done", "5개 판독, 1개 건너뜀(영상)"),
                    ("READING", "vision", "skipped", ""),
                    ("ORGANIZING", "organizing", "done", "필드 11개, 충돌 0, 질문 1"),
                    ("ORGANIZING", "privacy", "skipped", ""),
                    ("CHECKPOINT_1", "checkpoint_1", "running", ""),
                ],
            )
            with case["lock"]:
                _step(case, "checkpoint_1")["note"] = "사실값 확인과 강조할 발화 선택"
        elif state == "CALCULATING":
            _run_sequence(
                case,
                [
                    ("CALCULATING", "calculating", "done", "일부 변제 충당"),
                    ("DRAFTING", "drafting", "done", "문장 4개 작성"),
                    ("VERIFYING", "verifying", "done", "G1a·G3 통과"),
                    ("DRAFT_APPROVAL", "draft_approval", "running", ""),
                ],
            )
            with case["lock"]:
                _step(case, "draft_approval")["note"] = "문장별 승인"
        elif state == "DRAFT_APPROVAL":
            with case["lock"]:
                drafts = case["drafts"]
                blocked = [
                    s["sentence_id"]
                    for s in drafts["sentences"]
                    if not s.get("approved") or s.get("findings")
                ]
            if blocked:
                raise _err(409, "unapproved_sentences", "승인되지 않은 문장이 있습니다.")
            _run_sequence(
                case,
                [
                    ("PACKAGING", "packaging", "done", "파일 1개, 복사 블록 2개"),
                    ("CHECKPOINT_2", "checkpoint_2", "running", ""),
                ],
            )
            with case["lock"]:
                _step(case, "checkpoint_2")["note"] = "서류 묶음 확인"
        else:
            raise _err(409, "wrong_state", f"상태 {state}에서는 실행할 수 없습니다.")
        with case["lock"]:
            return _case_view(case)
    finally:
        case["run_lock"].release()


@app.get("/api/cases/{case_id}/readings")
def get_readings(case_id: str) -> Any:
    _get_case(case_id)
    return copy.deepcopy(READINGS_EXAMPLE)


@app.get("/api/cases/{case_id}/redactions")
def get_redactions(case_id: str) -> Any:
    _get_case(case_id)
    raise _err(404, "not_found", "가림 미리보기가 없습니다.")


@app.get("/api/cases/{case_id}/segments")
def get_segments(case_id: str) -> Any:
    _get_case(case_id)
    raise _err(404, "not_found", "감식 결과가 없습니다.")


@app.get("/api/cases/{case_id}/review")
def get_review(case_id: str) -> Any:
    case = _get_case(case_id)
    with case["lock"]:
        if STATE_ORDER.index(case["state"]) < STATE_ORDER.index("CHECKPOINT_1"):
            raise _err(409, "wrong_state", "아직 확인할 사실이 없습니다.")
    return copy.deepcopy(REVIEW_EXAMPLE)


@app.put("/api/cases/{case_id}/facts")
def put_facts(case_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    case = _get_case(case_id)
    with case["lock"]:
        if case["state"] not in ("CHECKPOINT_1", "HOLD"):
            raise _err(409, "wrong_state", f"상태 {case['state']}에서는 사실을 확정할 수 없습니다.")
        missing = [k for k in ("fields", "evidence_roles", "highlight", "as_of") if k not in body]
        if missing:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "bad_request",
                    "message": "확정값이 모자랍니다.",
                    "missing_requirements": missing,
                },
            )
        case["confirmed"] = copy.deepcopy(body)
        case["drafts"] = copy.deepcopy(DRAFTS_EXAMPLE)
        case["state"] = "CALCULATING"
        for key in ("calculating", "drafting", "verifying", "draft_approval",
                    "packaging", "checkpoint_2"):
            step = _step(case, key)
            step["status"] = "waiting"
            step["latency_ms"] = 0
            step["attempts"] = 0
            step["note"] = ""
        _step(case, "checkpoint_1")["status"] = "done"
        return _case_view(case)


def _draft_gate(case: Dict[str, Any]) -> None:
    if STATE_ORDER.index(case["state"]) < STATE_ORDER.index("DRAFT_APPROVAL"):
        raise _err(409, "wrong_state", "아직 초안이 없습니다.")


@app.get("/api/cases/{case_id}/drafts")
def get_drafts(case_id: str) -> Any:
    case = _get_case(case_id)
    with case["lock"]:
        _draft_gate(case)
        return copy.deepcopy(case["drafts"])


@app.put("/api/cases/{case_id}/drafts")
def put_drafts(case_id: str, body: Dict[str, Any]) -> Any:
    case = _get_case(case_id)
    with case["lock"]:
        if case["state"] != "DRAFT_APPROVAL":
            raise _err(409, "wrong_state", f"상태 {case['state']}에서는 초안을 고칠 수 없습니다.")
        if "sentences" not in body or not isinstance(body["sentences"], list):
            raise _err(400, "bad_request", "sentences 목록이 필요합니다.")
        drafts = case["drafts"]
        by_id = {s["sentence_id"]: s for s in drafts["sentences"]}
        for item in body["sentences"]:
            sid = item.get("sentence_id")
            if sid not in by_id:
                raise _err(400, "bad_request", f"문장 {sid}이 없습니다.")
            sent = by_id[sid]
            if "text_with_slots" in item and item["text_with_slots"] is not None:
                sent["text_with_slots"] = item["text_with_slots"]
                sent["rendered_text"] = item["text_with_slots"]
                snippet = _g1a_check(item["text_with_slots"])
                if snippet is not None:
                    sent["findings"] = [
                        {
                            "sentence_id": sid,
                            "field": "text_with_slots",
                            "message": f"슬롯 밖에 숫자가 있습니다: {snippet}",
                            "fix_hint": "숫자는 {{...}} 슬롯으로 쓰세요.",
                        }
                    ]
                    sent["approved"] = False
                else:
                    sent["findings"] = []
                    if "approved" in item:
                        sent["approved"] = bool(item["approved"])
            elif "approved" in item:
                if sent.get("findings"):
                    sent["approved"] = False
                else:
                    sent["approved"] = bool(item["approved"])
        failing = [s for s in drafts["sentences"] if s.get("findings")]
        for gate in drafts["gate_results"]:
            if gate["gate"] == "G1a":
                gate["status"] = "fail" if failing else "pass"
                gate["findings"] = [f for s in failing for f in s["findings"]]
        return copy.deepcopy(drafts)


@app.get("/api/cases/{case_id}/package")
def get_package(case_id: str) -> Any:
    case = _get_case(case_id)
    with case["lock"]:
        if case["state"] != "CHECKPOINT_2":
            raise _err(409, "wrong_state", "아직 서류 묶음이 없습니다.")
        pkg = copy.deepcopy(PACKAGE_EXAMPLE)
        for f in pkg["files"]:
            f["url"] = f"/api/cases/{case_id}/files/{f['name']}"
        return pkg


@app.get("/api/cases/{case_id}/files/{name}")
def get_file(case_id: str, name: str) -> Response:
    _get_case(case_id)
    if name != "content_proof.pdf":
        raise _err(404, "not_found", "파일이 없습니다.")
    return Response(content=STUB_PDF, media_type="application/pdf")


if FRONTEND.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
