from __future__ import annotations

from .. import db
from ..ai_input_audit import run_ai_input_summary
from ..jobs import (
    active_job_id,
    cancel_singleton_job,
    start_singleton_job,
)
from ..languages import require_supported_language
from ..schemas import (
    MultilingualQueueRequest,
    RunCreate,
    TranslateRequest,
)
from ..workflow import (
    cancel_translation_run,
    multilingual_status,
    run_translate_sync,
    start_multilingual_translation_queue,
    translation_batch_file,
    translation_run_progress,
    user_facing_error,
)
from .shared import (
    _resolve_task_code,
    _validate_run_input_artifact,
)
from fastapi import (
    APIRouter,
    HTTPException,
)
from fastapi.responses import FileResponse
from typing import Any

router = APIRouter()

@router.post("/api/runs")
def create_run(payload: RunCreate) -> dict[str, Any]:
    try:
        db.get_project(payload.project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    try:
        language = require_supported_language(payload.language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    _validate_run_input_artifact(payload)
    active = [
        run
        for run in db.list_runs(payload.project_id)
        if run["kind"] == payload.kind and run["status"] in {"queued", "running"}
    ]
    if active:
        raise HTTPException(status_code=409, detail=f"{payload.kind} run already active for this project")
    reference_artifact_ids = [str(item).strip() for item in payload.reference_artifact_ids if str(item).strip()]
    for artifact_id in reference_artifact_ids:
        try:
            artifact = db.get_artifact(artifact_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"reference artifact not found: {artifact_id}") from exc
        if artifact["project_id"] != payload.project_id:
            raise HTTPException(status_code=400, detail=f"reference artifact does not belong to project: {artifact_id}")
    metadata = {
        "input_artifact_id": payload.input_artifact_id,
        "term_artifact_id": payload.term_artifact_id,
        "reference_artifact_ids": reference_artifact_ids,
        "batch_size": payload.batch_size,
        "task_origin": payload.task_origin or ("direct_import" if payload.kind == "qa" else "translation_run"),
        "source_run_id": payload.source_run_id,
        "task_code": _resolve_task_code(payload),
    }
    return db.insert_run(payload.project_id, payload.kind, language, metadata)


@router.get("/api/runs")
def list_runs(project_id: str | None = None) -> list[dict[str, Any]]:
    return db.list_runs(project_id)


@router.get("/api/projects/{project_id}/multilingual/status")
def get_multilingual_status(project_id: str, input_artifact_id: str, languages: str) -> dict[str, Any]:
    try:
        return multilingual_status(project_id, input_artifact_id, languages)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc


@router.post("/api/projects/{project_id}/multilingual/translate/start")
def start_multilingual_translation(project_id: str, payload: MultilingualQueueRequest) -> dict[str, Any]:
    try:
        return start_multilingual_translation_queue(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc


@router.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    try:
        run = db.get_run(run_id)
        run["events"] = db.list_events(run_id)
        run["artifacts"] = db.list_artifacts(run_id=run_id)
        return run
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc


@router.get("/api/runs/{run_id}/ai-input-summary")
def get_run_ai_input_summary(run_id: str) -> dict[str, Any]:
    try:
        return run_ai_input_summary(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc


@router.post("/api/runs/{run_id}/translate")
def translate(run_id: str, payload: TranslateRequest) -> dict[str, Any]:
    try:
        return run_translate_sync(run_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run or artifact not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


def _start_translation_background(run_id: str, payload: TranslateRequest) -> dict[str, Any]:
    try:
        run = db.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    if run["kind"] != "translation":
        raise HTTPException(status_code=400, detail="run is not a translation run")
    active = active_job_id()
    job_id = f"run:{run_id}"
    if active and active != job_id:
        raise HTTPException(status_code=409, detail=f"another long-text AI job is active: {active}")
    if run["status"] == "running" and active == job_id:
        return get_run(run_id)
    db.merge_run_metadata(run_id, {"queued_at": db.now_iso()})
    db.update_run(run_id, status="queued")

    def worker(cancel_event: Any) -> None:
        try:
            run_translate_sync(run_id, payload, cancel_event=cancel_event)
        except Exception as exc:
            try:
                current = db.get_run(run_id)
                if current.get("status") not in {"failed", "canceled", "needs_input", "passed"}:
                    db.merge_run_metadata(run_id, {"error": user_facing_error(exc)})
                    db.update_run(run_id, status="failed")
            except Exception:
                pass

    started, active_conflict = start_singleton_job(job_id, worker)
    if not started and active_conflict:
        run = db.get_run(run_id)
        db.merge_run_metadata(run_id, {"queue_error": f"active job: {active_conflict}"})
        db.update_run(run_id, status=run.get("status") or "created")
        raise HTTPException(status_code=409, detail=f"another long-text AI job is active: {active_conflict}")
    db.add_event(run_id, "translation background job started")
    return get_run(run_id)


@router.post("/api/runs/{run_id}/translate/start")
def translate_start(run_id: str, payload: TranslateRequest) -> dict[str, Any]:
    return _start_translation_background(run_id, payload)


@router.post("/api/runs/{run_id}/translate/resume")
def translate_resume(run_id: str, payload: TranslateRequest) -> dict[str, Any]:
    return _start_translation_background(run_id, payload)


@router.post("/api/runs/{run_id}/translate/cancel")
def translate_cancel(run_id: str) -> dict[str, Any]:
    try:
        cancel_singleton_job(f"run:{run_id}")
        cancel_translation_run(run_id)
        return get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc


@router.get("/api/runs/{run_id}/translate/progress")
def translate_progress(run_id: str) -> dict[str, Any]:
    try:
        return translation_run_progress(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc


@router.get("/api/runs/{run_id}/translate/batches/{batch_index}/{kind}")
def translate_batch_download(run_id: str, batch_index: int, kind: str) -> FileResponse:
    try:
        path = translation_batch_file(run_id, batch_index, kind)
        return FileResponse(path, filename=path.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="batch file not found") from exc

@router.get("/api/runs/{run_id}/events")
def get_events(run_id: str) -> list[dict[str, Any]]:
    return db.list_events(run_id)
