"""Case-flow API (contract 6장, M2a task 7).

Bodies are inspected by hand so validation failures return 400 with
``{detail: {code, message, missing_requirements}}`` instead of FastAPI 422.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from app.agents import deps
from app.agents import intake as intake_mod
from app.agents.case_state import CaseState, evidence_dir, files_dir, save_case
from app.agents import coordinator as coord

router = APIRouter(prefix="/api/cases")


def err(status: int, code: str, message: str,
        missing: Optional[List[str]] = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"detail": {
            "code": code, "message": message,
            "missing_requirements": list(missing or []),
        }},
    )


def _internal_error() -> JSONResponse:
    return err(500, "internal_error", "처리 중 오류가 생겼습니다.")


async def _read_json(request: Request) -> Any:
    try:
        raw = await request.body()
    except Exception:
        raise coord.BadRequest("bad_request", "요청 본문을 읽을 수 없습니다.")
    if not raw or not raw.strip():
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise coord.BadRequest("bad_request", "요청 본문이 JSON이 아닙니다.")


def case_view(state: CaseState) -> Dict[str, Any]:
    return {
        "case_id": state.case_id,
        "jurisdiction": state.jurisdiction,
        "state": state.state,
        "meta_mode": deps.meta_mode(),
        "run_cost_usd": coord.fmt_cost(state.run_cost_usd),
        "stub": False,
        "hold_reasons": [reason.model_dump(mode="json")
                         for reason in state.hold_reasons],
        "steps": [step.model_dump(mode="json") for step in state.steps],
        "evidence": [
            {
                "ex_id": record.ex_id, "label": record.label,
                "filename": record.filename, "sha256": record.sha256,
                "kind": record.kind, "status": record.status,
                "url": record.url, "preview_url": record.preview_url,
            }
            for record in state.evidence
        ],
    }


def _find_evidence(state: CaseState, ex_id: str) -> Optional[Any]:
    wanted = str(ex_id or "").upper()
    for record in state.evidence:
        if record.ex_id.upper() == wanted:
            return record
    return None


@router.post("")
async def create_case(request: Request) -> Any:
    try:
        try:
            body = await _read_json(request)
        except coord.BadRequest as exc:
            return err(400, exc.code, exc.message,
                       getattr(exc, "missing", None))
        if not isinstance(body, dict):
            return err(400, "bad_request", "요청 본문이 올바르지 않습니다.")
        jurisdiction = str(body.get("jurisdiction", "") or "").strip().upper()
        if jurisdiction != "KR":
            return err(400, "bad_request", "jurisdiction은 KR만 지원합니다.")
        state = await asyncio.to_thread(coord.create_case, "KR", False)
        return case_view(state)
    except Exception:
        return _internal_error()


@router.post("/sample")
async def create_sample_case(request: Request) -> Any:
    try:
        try:
            body = await _read_json(request)
        except coord.BadRequest as exc:
            return err(400, exc.code, exc.message,
                       getattr(exc, "missing", None))
        if not isinstance(body, dict):
            return err(400, "bad_request", "요청 본문이 올바르지 않습니다.")
        wanted = str(body.get("set", "") or "").strip().lower()
        if wanted != "kr":
            return err(400, "bad_request", "set은 kr만 지원합니다.")
        try:
            state = await asyncio.to_thread(coord.create_case, "KR", True)
        except FileNotFoundError:
            return err(400, "bad_request", "샘플 증거를 찾을 수 없습니다.")
        return case_view(state)
    except Exception:
        return _internal_error()


@router.post("/{case_id}/evidence")
async def upload_evidence(case_id: str, request: Request) -> Any:
    try:
        try:
            state = coord.get_case(case_id)
        except coord.CaseNotFound:
            return err(404, "not_found", "사건을 찾을 수 없습니다.")
        if state.state != "INTAKE":
            return err(409, "wrong_state",
                       f"지금 상태({state.state})에서는 증거를 올릴 수 없습니다.")
        try:
            form = await request.form()
        except Exception:
            return err(400, "bad_request", "multipart 요청이 아닙니다.")
        uploads = []
        for _key, value in form.multi_items():
            filename = getattr(value, "filename", None)
            if filename:
                uploads.append(value)
        if not uploads:
            return err(400, "bad_request", "올릴 파일이 없습니다.")
        if len(state.evidence) + len(uploads) > intake_mod.MAX_EVIDENCE_COUNT:
            return err(400, "bad_request",
                       f"증거는 {intake_mod.MAX_EVIDENCE_COUNT}개까지 올릴 수 있습니다.")
        lock = coord._run_lock(case_id)
        if not lock.acquire(blocking=False):
            return err(409, "wrong_state", "같은 사건이 이미 실행 중입니다.")
        try:
            state = coord.get_case(case_id)
            if state.state != "INTAKE":
                return err(409, "wrong_state",
                           f"지금 상태({state.state})에서는 증거를 올릴 수 없습니다.")
            if len(state.evidence) + len(uploads) > intake_mod.MAX_EVIDENCE_COUNT:
                return err(400, "bad_request",
                           f"증거는 {intake_mod.MAX_EVIDENCE_COUNT}개까지 올릴 수 있습니다.")
            for upload in uploads:
                filename = Path(upload.filename or "upload").name
                kind = intake_mod.kind_for(filename)
                if kind is None:
                    return err(400, "bad_request", f"지원하지 않는 파일 형식입니다: {filename}")
                try:
                    data = await upload.read()
                except Exception:
                    return err(400, "bad_request", f"파일을 읽을 수 없습니다: {filename}")
                if not data:
                    return err(400, "bad_request", f"빈 파일입니다: {filename}")
                if len(bytes(data)) > intake_mod.MAX_UPLOAD_BYTES:
                    return err(400, "bad_request",
                               f"파일이 너무 큽니다(20MB 이하): {filename}")
                if not intake_mod.content_matches_kind(bytes(data), kind):
                    return err(400, "bad_request",
                               f"파일 내용과 확장자가 맞지 않습니다: {filename}")
                intake_mod.register_file(state, filename, bytes(data), kind)
            step = state.step("intake")
            step.status = "done"
            step.note = f"증거 {len(state.evidence)}개, SHA-256 기록"
            state.meta_mode = deps.meta_mode()
            save_case(state)
            return case_view(state)
        finally:
            lock.release()
    except coord.CaseNotFound:
        return err(404, "not_found", "사건을 찾을 수 없습니다.")
    except Exception:
        return _internal_error()


@router.get("/{case_id}/evidence/{ex_id}/file")
async def evidence_file(case_id: str, ex_id: str) -> Any:
    try:
        try:
            state = coord.get_case(case_id)
        except coord.CaseNotFound:
            return err(404, "not_found", "사건을 찾을 수 없습니다.")
        record = _find_evidence(state, ex_id)
        if record is None:
            return err(404, "not_found", "증거를 찾을 수 없습니다.")
        path = evidence_dir(case_id) / record.stored_name
        if not path.exists():
            return err(404, "not_found", "증거 파일을 찾을 수 없습니다.")
        return FileResponse(
            str(path), media_type=intake_mod.guess_media_type(record.filename),
            filename=record.filename,
        )
    except Exception:
        return _internal_error()


@router.get("/{case_id}/evidence/{ex_id}/preview")
async def evidence_preview(case_id: str, ex_id: str) -> Any:
    try:
        try:
            state = coord.get_case(case_id)
        except coord.CaseNotFound:
            return err(404, "not_found", "사건을 찾을 수 없습니다.")
        record = _find_evidence(state, ex_id)
        if record is None:
            return err(404, "not_found", "증거를 찾을 수 없습니다.")
        path = intake_mod.preview_path(state, record)
        if path is None or not path.exists():
            return err(404, "not_found", "미리보기가 없습니다.")
        media = "image/png" if record.kind == "pdf" else intake_mod.guess_media_type(
            record.filename
        )
        return FileResponse(str(path), media_type=media)
    except Exception:
        return _internal_error()


@router.post("/{case_id}/run")
async def run(case_id: str, request: Request) -> Any:
    try:
        body = await _read_json(request)
    except coord.BadRequest as exc:
        return err(400, exc.code, exc.message,
                   getattr(exc, "missing", None))
    if body not in ({}, None) and not isinstance(body, dict):
        return err(400, "bad_request", "요청 본문이 올바르지 않습니다.")
    try:
        state = await asyncio.to_thread(coord.run_case, case_id)
    except coord.CaseNotFound:
        return err(404, "not_found", "사건을 찾을 수 없습니다.")
    except coord.ConcurrentRun:
        return err(409, "wrong_state", "같은 사건이 이미 실행 중입니다.")
    except coord.WrongState as exc:
        return err(409, exc.code, exc.message)
    except Exception:
        return _internal_error()
    return case_view(state)


@router.get("/{case_id}")
async def get_case_view(case_id: str) -> Any:
    try:
        try:
            state = coord.get_case(case_id)
        except coord.CaseNotFound:
            return err(404, "not_found", "사건을 찾을 수 없습니다.")
        return case_view(state)
    except Exception:
        return _internal_error()


@router.get("/{case_id}/readings")
async def get_readings(case_id: str) -> Any:
    try:
        try:
            state = coord.get_case(case_id)
        except coord.CaseNotFound:
            return err(404, "not_found", "사건을 찾을 수 없습니다.")
        return state.readings
    except Exception:
        return _internal_error()


@router.get("/{case_id}/review")
async def get_review(case_id: str) -> Any:
    try:
        try:
            state = coord.get_case(case_id)
        except coord.CaseNotFound:
            return err(404, "not_found", "사건을 찾을 수 없습니다.")
        if state.review is None:
            return err(409, "wrong_state", "아직 사실 정리가 끝나지 않았습니다.")
        return state.review
    except Exception:
        return _internal_error()


@router.put("/{case_id}/facts")
async def put_facts(case_id: str, request: Request) -> Any:
    try:
        body = await _read_json(request)
    except coord.BadRequest as exc:
        return err(400, exc.code, exc.message,
                   getattr(exc, "missing", None))
    try:
        state = await asyncio.to_thread(coord.apply_facts, case_id, body)
    except coord.CaseNotFound:
        return err(404, "not_found", "사건을 찾을 수 없습니다.")
    except coord.ConcurrentRun:
        return err(409, "wrong_state", "같은 사건이 이미 실행 중입니다.")
    except coord.WrongState as exc:
        return err(409, exc.code, exc.message)
    except coord.BadRequest as exc:
        return err(400, exc.code, exc.message,
                   getattr(exc, "missing", None))
    except Exception:
        return _internal_error()
    return case_view(state)


@router.get("/{case_id}/drafts")
async def get_drafts(case_id: str) -> Any:
    try:
        try:
            state = coord.get_case(case_id)
        except coord.CaseNotFound:
            return err(404, "not_found", "사건을 찾을 수 없습니다.")
        if state.drafts is None:
            return err(409, "wrong_state", "아직 문안 작성이 끝나지 않았습니다.")
        return state.drafts
    except Exception:
        return _internal_error()


@router.put("/{case_id}/drafts")
async def put_drafts(case_id: str, request: Request) -> Any:
    try:
        body = await _read_json(request)
    except coord.BadRequest as exc:
        return err(400, exc.code, exc.message,
                   getattr(exc, "missing", None))
    try:
        drafts = await asyncio.to_thread(coord.apply_drafts, case_id, body)
    except coord.CaseNotFound:
        return err(404, "not_found", "사건을 찾을 수 없습니다.")
    except coord.ConcurrentRun:
        return err(409, "wrong_state", "같은 사건이 이미 실행 중입니다.")
    except coord.WrongState as exc:
        return err(409, exc.code, exc.message)
    except coord.BadRequest as exc:
        return err(400, exc.code, exc.message,
                   getattr(exc, "missing", None))
    except Exception:
        return _internal_error()
    return drafts


@router.get("/{case_id}/package")
async def get_package(case_id: str) -> Any:
    try:
        try:
            state = coord.get_case(case_id)
        except coord.CaseNotFound:
            return err(404, "not_found", "사건을 찾을 수 없습니다.")
        if state.package is None:
            return err(409, "wrong_state", "아직 편철이 끝나지 않았습니다.")
        return state.package
    except Exception:
        return _internal_error()


@router.get("/{case_id}/files/{name}")
async def generated_file(case_id: str, name: str) -> Any:
    try:
        try:
            coord.get_case(case_id)
        except coord.CaseNotFound:
            return err(404, "not_found", "사건을 찾을 수 없습니다.")
        safe = Path(name or "").name
        if not safe or safe != name or "/" in name or "\\" in name:
            return err(404, "not_found", "파일을 찾을 수 없습니다.")
        path = files_dir(case_id) / safe
        if not path.exists() or not path.is_file():
            return err(404, "not_found", "파일을 찾을 수 없습니다.")
        media = "application/pdf" if safe.endswith(".pdf") else "application/octet-stream"
        return FileResponse(str(path), media_type=media, filename=safe)
    except Exception:
        return _internal_error()


@router.delete("/{case_id}")
async def delete(case_id: str) -> Any:
    try:
        await asyncio.to_thread(coord.remove_case, case_id)
    except coord.CaseNotFound:
        return err(404, "not_found", "사건을 찾을 수 없습니다.")
    except coord.ConcurrentRun:
        return err(409, "wrong_state", "같은 사건이 실행 중이라 삭제할 수 없습니다.")
    except Exception:
        return _internal_error()
    return {"deleted": True}


@router.get("/{case_id}/segments")
async def get_segments(case_id: str) -> Any:
    try:
        try:
            coord.get_case(case_id)
        except coord.CaseNotFound:
            return err(404, "not_found", "사건을 찾을 수 없습니다.")
        return coord.load_segments(case_id)
    except Exception:
        return _internal_error()


@router.get("/{case_id}/redactions")
async def get_redactions(case_id: str) -> Any:
    try:
        try:
            coord.get_case(case_id)
        except coord.CaseNotFound:
            return err(404, "not_found", "사건을 찾을 수 없습니다.")
        return coord.load_redactions(case_id)
    except Exception:
        return _internal_error()


@router.api_route("/{rest:path}", methods=["GET", "POST", "PUT", "DELETE",
                                           "PATCH", "OPTIONS"])
async def cases_fallback(rest: str) -> Any:
    return err(404, "not_found", "요청한 경로를 찾을 수 없습니다.")
