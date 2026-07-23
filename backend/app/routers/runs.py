from __future__ import annotations

from .. import auth, background_jobs, db, operator_context
from ..ai_input_audit import run_ai_input_summary
from ..authz import require_project_access
from ..languages import require_supported_language
from ..schemas import (
    MultilingualQueueRequest,
    RunCreate,
    TranslateRequest,
)
from ..workflow import (
    abandon_legacy_translation_run,
    cancel_quick_task_run,
    cancel_translation_run,
    ensure_task_run_open,
    multilingual_status,
    mark_translation_task_state,
    run_translate_sync,
    start_multilingual_translation_queue,
    translation_batch_file,
    translation_run_progress,
    translation_task_continuation_metadata,
    user_facing_error,
)
from .shared import (
    _resolve_task_code,
    _validate_run_input_artifact,
)
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from fastapi.responses import FileResponse
from typing import Any

router = APIRouter()

@router.post("/api/runs")
def create_run(payload: RunCreate) -> dict[str, Any]:
    # project_id only lives in the request body here (the path is the bare
    # "/api/runs"), so the central route_capabilities gate -- which only
    # inspects path params -- cannot enforce membership on it. Do it
    # explicitly, the same way the /api/runs query-param case is handled in
    # list_runs() above.
    require_project_access(payload.project_id)
    try:
        db.get_project(payload.project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    try:
        language = require_supported_language(payload.language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    _validate_run_input_artifact(payload)
    reference_artifact_ids = [str(item).strip() for item in payload.reference_artifact_ids if str(item).strip()]
    for artifact_id in reference_artifact_ids:
        try:
            artifact = db.get_artifact(artifact_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"reference artifact not found: {artifact_id}") from exc
        if artifact["project_id"] != payload.project_id:
            raise HTTPException(status_code=400, detail=f"reference artifact does not belong to project: {artifact_id}")
    continuation_metadata: dict[str, Any] = {}
    if payload.source_run_id:
        try:
            source_run = db.get_run(payload.source_run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="source run not found") from exc
        if source_run["project_id"] != payload.project_id:
            raise HTTPException(status_code=400, detail="source run does not belong to project")
        if payload.kind == "qa":
            continuation_metadata = translation_task_continuation_metadata(source_run)
    metadata = {
        "input_artifact_id": payload.input_artifact_id,
        "term_artifact_id": payload.term_artifact_id,
        "reference_artifact_ids": reference_artifact_ids,
        "batch_size": payload.batch_size,
        "task_origin": payload.task_origin or ("direct_import" if payload.kind == "qa" else "translation_run"),
        "source_run_id": payload.source_run_id,
        "task_code": _resolve_task_code(payload),
        **continuation_metadata,
        "translation_task_id": (
            payload.translation_task_id
            if payload.translation_task_id is not None
            else continuation_metadata.get("translation_task_id")
        ),
    }
    try:
        run = db.insert_run(payload.project_id, payload.kind, language, metadata)
    except db.TranslationTaskClosedError as exc:
        raise HTTPException(status_code=409, detail=user_facing_error(exc)) from exc
    db.add_event(run["id"], operator_context.prefixed_message(f"run created (kind={payload.kind})"))
    return run


@router.get("/api/runs")
def list_runs(project_id: str | None = None) -> list[dict[str, Any]]:
    # project_id is a query param here, not a path param, so the central
    # route_capabilities gate (which only inspects path params) cannot
    # enforce membership on it -- do the same "admin sees all, everyone else
    # only their member projects" check this endpoint's own way.
    if project_id:
        require_project_access(project_id)
        return db.list_runs(project_id)
    user = auth.current_user()
    if user is None or user.get("role") == "admin":
        return db.list_runs(None)
    member_ids = db.list_member_project_ids(user["id"])
    return [run for run in db.list_runs(None) if run["project_id"] in member_ids]


@router.post("/api/runs/{run_id}/abandon-translation-task")
def abandon_legacy_run_translation_task(run_id: str) -> dict[str, Any]:
    try:
        return abandon_legacy_translation_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=user_facing_error(exc)) from exc


@router.get("/api/projects/{project_id}/multilingual/status")
def get_multilingual_status(
    project_id: str,
    input_artifact_id: str,
    languages: str,
    translation_task_id: str | None = None,
) -> dict[str, Any]:
    try:
        return multilingual_status(project_id, input_artifact_id, languages, translation_task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc


@router.post("/api/projects/{project_id}/translation-tasks/{translation_task_id}/abandon")
def abandon_translation_task(project_id: str, translation_task_id: str) -> dict[str, Any]:
    try:
        return mark_translation_task_state(project_id, translation_task_id, "abandoned")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="translation task not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=user_facing_error(exc)) from exc


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


@router.post(
    "/api/runs/{run_id}/translate",
    dependencies=[Depends(operator_context.require_operator_for_cloud)],
)
def translate(run_id: str, payload: TranslateRequest) -> dict[str, Any]:
    try:
        return run_translate_sync(run_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run or artifact not found") from exc
    except db.TranslationTaskClosedError as exc:
        raise HTTPException(status_code=409, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


def _start_translation_background(run_id: str, payload: TranslateRequest) -> dict[str, Any]:
    try:
        run = db.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    if run["kind"] != "translation":
        raise HTTPException(status_code=400, detail="run is not a translation run")
    try:
        ensure_task_run_open(run)
    except db.TranslationTaskClosedError as exc:
        raise HTTPException(status_code=409, detail=user_facing_error(exc)) from exc
    return background_jobs.start_translation(run_id, payload)


@router.post("/api/runs/{run_id}/translate/start")
def translate_start(run_id: str, payload: TranslateRequest) -> dict[str, Any]:
    return _start_translation_background(run_id, payload)


@router.post("/api/runs/{run_id}/translate/resume")
def translate_resume(run_id: str, payload: TranslateRequest) -> dict[str, Any]:
    return _start_translation_background(run_id, payload)


@router.post("/api/runs/{run_id}/translate/cancel")
def translate_cancel(run_id: str) -> dict[str, Any]:
    try:
        run = db.get_run(run_id)
        canceled = background_jobs.cancel(f"run:{run_id}")
        if canceled is None and run.get("status") in {"queued", "running"}:
            raise HTTPException(status_code=404, detail="active translation job not found")
        cancel_translation_run(run_id)
        cancel_quick_task_run(run_id)
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
