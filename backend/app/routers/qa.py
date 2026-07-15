from __future__ import annotations

from .. import background_jobs, db, operator_context
from ..schemas import (
    ManualFixRequest,
    ModelFixRequest,
    MultilingualQueueRequest,
)
from ..workflow import (
    apply_manual_fixes,
    apply_model_fixes,
    create_manual_fix_qa_run,
    create_project_improvement,
    create_improvement_review,
    create_semantic_qa_context,
    list_improvements,
    list_quality_issues,
    run_qa_sync,
    start_multilingual_qa_queue,
    user_facing_error,
)
from fastapi import (
    APIRouter,
    HTTPException,
)
from typing import Any

router = APIRouter()

@router.post("/api/runs/{run_id}/qa")
def qa(run_id: str) -> dict[str, Any]:
    try:
        return run_qa_sync(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run or artifact not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


def _start_background_qa(run_id: str) -> dict[str, Any]:
    db.get_run(run_id)  # KeyError -> caller maps to 404
    return background_jobs.start_qa(run_id)


@router.post("/api/runs/{run_id}/qa/start")
def qa_start(run_id: str) -> dict[str, Any]:
    try:
        return _start_background_qa(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run or artifact not found") from exc


@router.post("/api/runs/{run_id}/qa/cancel")
def qa_cancel(run_id: str) -> dict[str, Any]:
    try:
        db.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    canceled = background_jobs.cancel(f"qa:{run_id}")
    if canceled is None:
        raise HTTPException(status_code=404, detail="active QA job not found")
    return canceled["business_target"]


@router.post("/api/projects/{project_id}/multilingual/qa/start")
def start_multilingual_qa(project_id: str, payload: MultilingualQueueRequest) -> dict[str, Any]:
    try:
        return start_multilingual_qa_queue(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc


@router.get("/api/runs/{run_id}/quality-issues")
def quality_issues(run_id: str) -> dict[str, Any]:
    try:
        return list_quality_issues(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc


@router.post("/api/runs/{run_id}/manual-fixes")
def manual_fixes(run_id: str, payload: ManualFixRequest) -> dict[str, Any]:
    try:
        return apply_manual_fixes(run_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run, artifact, sheet, or column not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


@router.post("/api/runs/{run_id}/manual-fixes/start")
def manual_fixes_start(run_id: str, payload: ManualFixRequest) -> dict[str, Any]:
    """Apply manual fixes synchronously (fast) and rerun QA in the background.

    The sync ``/manual-fixes`` endpoint reruns the whole QA pipeline inside
    the request, which blocks the UI for minutes on large workbooks. This
    variant returns the created QA run immediately; the frontend follows it
    with the normal run-status polling.
    """
    try:
        source_run = db.get_run(run_id)
        if payload.rerun_qa:
            operator_context.require_operator_for_cloud()
        no_rerun = payload.model_copy(update={"rerun_qa": False})
        result = apply_manual_fixes(run_id, no_rerun)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run, artifact, sheet, or column not found") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc
    response: dict[str, Any] = {
        "source_run": result["source_run"],
        "fixed_artifact": result["fixed_artifact"],
        "manual_fixes": result["manual_fixes"],
        "qa_run": None,
    }
    if payload.rerun_qa:
        source_artifact = {"id": (result["fixed_artifact"].get("metadata") or {}).get("source_artifact_id") or ""}
        qa_run = create_manual_fix_qa_run(source_run, result["fixed_artifact"], source_artifact, result["manual_fixes"])
        response["qa_run"] = _start_background_qa(qa_run["id"])
    return response


@router.post("/api/runs/{run_id}/model-fixes")
def model_fixes(run_id: str, payload: ModelFixRequest) -> dict[str, Any]:
    try:
        return apply_model_fixes(run_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run, artifact, sheet, or column not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc




@router.post("/api/runs/{run_id}/model-fixes/start")
def model_fixes_start(run_id: str, payload: ModelFixRequest) -> dict[str, Any]:
    try:
        db.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    return background_jobs.start_model_fix(run_id, payload)


@router.post("/api/runs/{run_id}/semantic-qa")
def semantic_qa(run_id: str) -> dict[str, Any]:
    try:
        return create_semantic_qa_context(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc

@router.get("/api/projects/{project_id}/improvements")
def get_project_improvements(project_id: str) -> list[dict[str, Any]]:
    try:
        db.get_project(project_id)
        return list_improvements(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@router.post("/api/projects/{project_id}/improvements")
def add_project_improvement(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return create_project_improvement(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@router.post("/api/runs/{run_id}/improvement-review")
def improvement_review(run_id: str) -> dict[str, Any]:
    try:
        return create_improvement_review(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
