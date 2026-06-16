from __future__ import annotations

from .. import db
from ..jobs import active_job_id, start_singleton_job
from ..schemas import (
    ManualFixRequest,
    ModelFixRequest,
    MultilingualQueueRequest,
)
from ..workflow import (
    apply_manual_fixes,
    apply_model_fixes,
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
        model_fix_provider_settings()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=user_facing_error(exc)) from exc
    job_id = f"model-fix:{run_id}"
    active = active_job_id()
    if active and active != job_id:
        raise HTTPException(status_code=409, detail=f"another long-text AI job is active: {active}")
    original_status = str(run.get("status") or "failed")
    metadata = run.get("metadata") or {}
    db.update_run(
        run_id,
        status="running",
        metadata={
            **metadata,
            "model_fix_status": "running",
            "model_fix_started_at": db.now_iso(),
            "model_fix_max_issues": payload.max_issues,
            "model_fix_rerun_qa": payload.rerun_qa,
        },
    )

    def worker(cancel_event: Any) -> None:
        _ = cancel_event
        try:
            result = apply_model_fixes(run_id, payload)
            qa_result = result.get("qa_result") or {}
            qa_run = qa_result.get("run") or {}
            terminal_status = str(qa_run.get("status") or "needs_input")
            current = db.get_run(run_id)
            current_metadata = current.get("metadata") or {}
            db.update_run(
                run_id,
                status=terminal_status,
                metadata={
                    **current_metadata,
                    "model_fix_status": terminal_status,
                    "model_fix_finished_at": db.now_iso(),
                    "model_fix_count": len(result.get("model_fixes") or []),
                    "model_fix_result_run_id": qa_run.get("id") or "",
                    "model_fix_fixed_artifact_id": (result.get("fixed_artifact") or {}).get("id") or "",
                    "model_fix_quality_summary": qa_result.get("quality_summary") or {},
                },
            )
            db.add_event(run_id, f"model fixes finished: status={terminal_status}, fixes={len(result.get('model_fixes') or [])}")
        except Exception as exc:
            friendly = user_facing_error(exc)
            current = db.get_run(run_id)
            current_metadata = current.get("metadata") or {}
            db.update_run(
                run_id,
                status="failed",
                metadata={
                    **current_metadata,
                    "model_fix_status": "failed",
                    "model_fix_finished_at": db.now_iso(),
                    "model_fix_error": friendly,
                    "error": friendly,
                },
            )
            db.add_event(run_id, f"model fixes failed: {friendly}", level="error")

    started, active_conflict = start_singleton_job(job_id, worker)
    if not started and active_conflict:
        run = db.get_run(run_id)
        db.update_run(
            run_id,
            status=original_status,
            metadata={
                **(run.get("metadata") or {}),
                "model_fix_status": "blocked",
                "model_fix_error": "已有其他 AI 后台任务正在运行，请等待完成后再重试。",
                "queue_error": f"active job: {active_conflict}",
            },
        )
        raise HTTPException(status_code=409, detail=f"another long-text AI job is active: {active_conflict}")
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
