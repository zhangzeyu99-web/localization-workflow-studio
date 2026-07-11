from __future__ import annotations

from .. import db
from ..config import load_settings
from ..jobs import active_job_id_for_project, cancel_singleton_job, start_singleton_job
from ..schemas import (
    ManualFixRequest,
    ModelFixRequest,
    MultilingualQueueRequest,
)
from ..workflow import (
    QaCanceled,
    apply_manual_fixes,
    apply_model_fixes,
    create_manual_fix_qa_run,
    create_project_improvement,
    create_improvement_review,
    create_semantic_qa_context,
    list_improvements,
    list_quality_issues,
    model_fix_provider_settings,
    run_qa_sync,
    start_multilingual_qa_queue,
    user_facing_error,
)
from .shared import _job_conflict_detail
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
    """Start the QA pipeline for ``run_id`` as a background job.

    Shares the per-project lease with translation/model-fix/announcement
    jobs, so the same project serializes while other projects keep running.
    """
    run = db.get_run(run_id)  # KeyError -> caller maps to 404
    project_id = run["project_id"]
    job_id = f"qa:{run_id}"
    active = active_job_id_for_project(project_id)
    if active and active != job_id:
        raise HTTPException(status_code=409, detail=_job_conflict_detail({"reason": "project_busy", "active_job_id": active}))
    # Snapshot settings at the task entry point (same rule as model-fix /
    # multilingual jobs): a settings PATCH mid-job must not switch the
    # semantic QA provider halfway through this run.
    job_settings = load_settings()
    original_status = str(run.get("status") or "created")
    db.merge_run_metadata(run_id, {"queued_at": db.now_iso()})
    db.update_run(run_id, status="queued")

    def worker(cancel_event: Any) -> None:
        try:
            run_qa_sync(run_id, settings=job_settings, cancel_event=cancel_event)
        except QaCanceled:
            try:
                db.merge_run_metadata(run_id, {"canceled_at": db.now_iso()})
                db.update_run(run_id, status="canceled")
                db.add_event(run_id, "QA canceled before completion; no partial results were written")
            except Exception:
                pass
        except Exception as exc:
            try:
                friendly = user_facing_error(exc)
                db.merge_run_metadata(run_id, {"error": friendly})
                db.update_run(run_id, status="failed")
                db.add_event(run_id, f"qa failed: {friendly}", level="error")
            except Exception:
                pass

    started, conflict = start_singleton_job(project_id, job_id, worker)
    if not started and conflict:
        db.merge_run_metadata(run_id, {"queue_error": f"job start rejected: {conflict}"})
        db.update_run(run_id, status=original_status)
        raise HTTPException(status_code=409, detail=_job_conflict_detail(conflict))
    db.add_event(run_id, "qa background job started")
    return db.get_run(run_id)


@router.post("/api/runs/{run_id}/qa/start")
def qa_start(run_id: str) -> dict[str, Any]:
    try:
        return _start_background_qa(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run or artifact not found") from exc


@router.post("/api/runs/{run_id}/qa/cancel")
def qa_cancel(run_id: str) -> dict[str, Any]:
    try:
        run = db.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    cancel_singleton_job(run["project_id"], f"qa:{run_id}")
    db.merge_run_metadata(run_id, {"cancel_requested_at": db.now_iso()})
    db.add_event(run_id, "qa cancel requested; stops at the next pipeline stage boundary")
    return db.get_run(run_id)


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
        no_rerun = payload.model_copy(update={"rerun_qa": False})
        result = apply_manual_fixes(run_id, no_rerun)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run, artifact, sheet, or column not found") from exc
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
        run = db.get_run(run_id)
        # Snapshot settings once here (the task's entry point) and thread the
        # same snapshot through apply_model_fixes -> the QA rerun below, so a
        # concurrent settings PATCH mid-job can't change provider/model
        # partway through this one job's execution.
        job_settings, _provider = model_fix_provider_settings()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=user_facing_error(exc)) from exc
    project_id = run["project_id"]
    job_id = f"model-fix:{run_id}"
    active = active_job_id_for_project(project_id)
    if active and active != job_id:
        raise HTTPException(status_code=409, detail=_job_conflict_detail({"reason": "project_busy", "active_job_id": active}))
    original_status = str(run.get("status") or "failed")
    db.merge_run_metadata(
        run_id,
        {
            "model_fix_status": "running",
            "model_fix_started_at": db.now_iso(),
            "model_fix_max_issues": payload.max_issues,
            "model_fix_rerun_qa": payload.rerun_qa,
        },
    )
    db.update_run(run_id, status="running")

    def worker(cancel_event: Any) -> None:
        _ = cancel_event
        try:
            result = apply_model_fixes(run_id, payload, settings=job_settings)
            qa_result = result.get("qa_result") or {}
            qa_run = qa_result.get("run") or {}
            terminal_status = str(qa_run.get("status") or "needs_input")
            db.merge_run_metadata(
                run_id,
                {
                    "model_fix_status": terminal_status,
                    "model_fix_finished_at": db.now_iso(),
                    "model_fix_count": len(result.get("model_fixes") or []),
                    "model_fix_result_run_id": qa_run.get("id") or "",
                    "model_fix_fixed_artifact_id": (result.get("fixed_artifact") or {}).get("id") or "",
                    "model_fix_quality_summary": qa_result.get("quality_summary") or {},
                },
            )
            db.update_run(run_id, status=terminal_status)
            db.add_event(run_id, f"model fixes finished: status={terminal_status}, fixes={len(result.get('model_fixes') or [])}")
        except Exception as exc:
            friendly = user_facing_error(exc)
            db.merge_run_metadata(
                run_id,
                {
                    "model_fix_status": "failed",
                    "model_fix_finished_at": db.now_iso(),
                    "model_fix_error": friendly,
                    "error": friendly,
                },
            )
            db.update_run(run_id, status="failed")
            db.add_event(run_id, f"model fixes failed: {friendly}", level="error")

    started, conflict = start_singleton_job(project_id, job_id, worker)
    if not started and conflict:
        detail = _job_conflict_detail(conflict)
        db.merge_run_metadata(
            run_id,
            {
                "model_fix_status": "blocked",
                "model_fix_error": detail,
                "queue_error": f"job start rejected: {conflict}",
            },
        )
        db.update_run(run_id, status=original_status)
        raise HTTPException(status_code=409, detail=detail)
    db.add_event(run_id, "model fixes background job started")
    return db.get_run(run_id)


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
