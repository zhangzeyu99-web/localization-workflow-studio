from __future__ import annotations

from .. import background_jobs, db, operator_context
from ..ai_input_audit import announcement_ai_input_summary
from ..jobs import cancel_singleton_job
from ..schemas import (
    AnnouncementDocxApplyRequest,
    AnnouncementDocxDeliverRequest,
    AnnouncementDocxImportAiRequest,
    AnnouncementDocxPrepareRequest,
    AnnouncementLookupRequest,
    AnnouncementTaskActionRequest,
    AnnouncementTaskApplyRequest,
    AnnouncementTaskCancelRequest,
    AnnouncementTaskCreateRequest,
    AnnouncementTaskDeliverRequest,
    AnnouncementTaskImportAiRequest,
    AnnouncementTaskTermsRequest,
    AnnouncementTaskTranslateRequest,
    AnnouncementTermsRequest,
)
from ..workflow import (
    apply_announcement_task,
    create_announcement_task,
    deliver_announcement_task,
    extract_announcement_terms,
    fix_announcement_hard_blockers,
    generate_announcement_terms_package,
    get_announcement_task,
    import_announcement_ai_response,
    import_announcement_terms,
    inspect_announcement_constraints,
    legacy_apply_announcement_docx,
    legacy_deliver_announcement_docx,
    legacy_import_announcement_docx_ai,
    legacy_prepare_announcement_docx,
    list_announcement_tasks,
    lookup_announcement_translations,
    prepare_announcement_translation,
    run_announcement_lookup,
    translate_announcement_task,
    user_facing_error,
)
from .shared import _query_language
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from typing import Any

router = APIRouter()

@router.post("/api/projects/{project_id}/announcement-lookup", deprecated=True)
def create_announcement_lookup(project_id: str, payload: AnnouncementLookupRequest) -> dict[str, Any]:
    try:
        payload.language = _query_language(payload.language) or "en"
        return run_announcement_lookup(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


@router.post("/api/projects/{project_id}/announcement-terms")
def create_announcement_terms(project_id: str, payload: AnnouncementTermsRequest) -> dict[str, Any]:
    if payload.ai_supplement and not payload.ai_supplement_response_artifact_id:
        operator_context.require_operator_for_cloud()
    try:
        return generate_announcement_terms_package(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


@router.post("/api/projects/{project_id}/announcement-docx/prepare", deprecated=True)
def prepare_announcement_docx(project_id: str, payload: AnnouncementDocxPrepareRequest) -> dict[str, Any]:
    try:
        return legacy_prepare_announcement_docx(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project, run, or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


@router.post("/api/projects/{project_id}/announcement-docx/import-ai", deprecated=True)
def import_announcement_docx_ai(project_id: str, payload: AnnouncementDocxImportAiRequest) -> dict[str, Any]:
    try:
        return legacy_import_announcement_docx_ai(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project, run, or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


@router.post("/api/projects/{project_id}/announcement-docx/apply", deprecated=True)
def apply_announcement_docx(project_id: str, payload: AnnouncementDocxApplyRequest) -> dict[str, Any]:
    try:
        return legacy_apply_announcement_docx(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project, run, or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


@router.post("/api/projects/{project_id}/announcement-docx/deliver", deprecated=True)
def deliver_announcement_docx(project_id: str, payload: AnnouncementDocxDeliverRequest) -> dict[str, Any]:
    try:
        return legacy_deliver_announcement_docx(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project, run, or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


@router.get("/api/projects/{project_id}/announcement-tasks")
def list_project_announcement_tasks(project_id: str) -> list[dict[str, Any]]:
    try:
        return list_announcement_tasks(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@router.post("/api/projects/{project_id}/announcement-tasks")
def create_project_announcement_task(project_id: str, payload: AnnouncementTaskCreateRequest) -> dict[str, Any]:
    try:
        return create_announcement_task(project_id, payload)
    except db.UnfinishedAnnouncementTaskExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "unfinished_announcement_task_exists",
                "task_id": exc.task_id,
                "status": exc.status,
            },
        ) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


@router.get("/api/announcement-tasks/{task_id}")
def get_project_announcement_task(task_id: str) -> dict[str, Any]:
    try:
        return get_announcement_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="announcement task not found") from exc


@router.get("/api/announcement-tasks/{task_id}/ai-input-summary")
def get_announcement_task_ai_input_summary(task_id: str) -> dict[str, Any]:
    try:
        return announcement_ai_input_summary(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="announcement task or artifact not found") from exc


@router.post("/api/announcement-tasks/{task_id}/cancel")
def cancel_project_announcement_task(task_id: str, payload: AnnouncementTaskCancelRequest | None = None) -> dict[str, Any]:
    try:
        result = background_jobs.cancel_announcement_task(task_id, payload.expected_statuses if payload else None)
        cancel_singleton_job(result["task"]["project_id"], f"announcement:{task_id}")
        return result
    except db.AnnouncementTaskStatusConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "announcement_task_status_conflict",
                "task_id": exc.task_id,
                "status": exc.status,
            },
        ) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="announcement task not found") from exc


@router.post("/api/announcement-tasks/{task_id}/inspect-constraints")
def inspect_project_announcement_constraints(task_id: str, payload: AnnouncementTaskActionRequest) -> dict[str, Any]:
    try:
        return inspect_announcement_constraints(task_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="announcement task or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


@router.post("/api/announcement-tasks/{task_id}/extract-terms")
def extract_project_announcement_terms(task_id: str, payload: AnnouncementTaskActionRequest) -> dict[str, Any]:
    if payload.ai_supplement and not payload.ai_supplement_response_artifact_id:
        operator_context.require_operator_for_cloud()
    try:
        return extract_announcement_terms(task_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="announcement task or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


@router.post("/api/announcement-tasks/{task_id}/import-terms")
def import_project_announcement_terms(task_id: str, payload: AnnouncementTaskTermsRequest) -> dict[str, Any]:
    try:
        return import_announcement_terms(task_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="announcement task or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


@router.post("/api/announcement-tasks/{task_id}/lookup-translations")
def lookup_project_announcement_translations(task_id: str, payload: AnnouncementTaskActionRequest) -> dict[str, Any]:
    try:
        return lookup_announcement_translations(task_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="announcement task or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


@router.post("/api/announcement-tasks/{task_id}/prepare")
def prepare_project_announcement_translation(task_id: str, payload: AnnouncementTaskActionRequest) -> dict[str, Any]:
    try:
        return prepare_announcement_translation(task_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="announcement task or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


@router.post(
    "/api/announcement-tasks/{task_id}/translate",
    dependencies=[Depends(operator_context.require_operator_for_cloud)],
)
def translate_project_announcement(task_id: str, payload: AnnouncementTaskTranslateRequest) -> dict[str, Any]:
    try:
        return translate_announcement_task(task_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="announcement task or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


def _start_announcement_translation_background(task_id: str, payload: AnnouncementTaskTranslateRequest) -> dict[str, Any]:
    try:
        get_announcement_task(task_id)
        queued = background_jobs.start_announcement(task_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="announcement task not found") from exc
    except db.AnnouncementTaskStatusConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "announcement_task_status_conflict",
                "task_id": exc.task_id,
                "status": exc.status,
            },
        ) from exc
    return {"task": queued, "summary": {"status": queued["status"]}}


@router.post("/api/announcement-tasks/{task_id}/translate/start")
def translate_project_announcement_start(task_id: str, payload: AnnouncementTaskTranslateRequest) -> dict[str, Any]:
    return _start_announcement_translation_background(task_id, payload)


@router.post("/api/announcement-tasks/{task_id}/translate/resume")
def translate_project_announcement_resume(task_id: str, payload: AnnouncementTaskTranslateRequest) -> dict[str, Any]:
    return _start_announcement_translation_background(task_id, payload)


@router.post("/api/announcement-tasks/{task_id}/translate/cancel")
def translate_project_announcement_cancel(task_id: str) -> dict[str, Any]:
    try:
        get_announcement_task(task_id)
        canceled = background_jobs.cancel(f"announcement:{task_id}")
        if canceled is None:
            raise HTTPException(status_code=404, detail="active announcement job not found")
        return {"task": canceled["business_target"], "summary": {"status": canceled["business_target"]["status"], "reason": "announcement_translation_canceled"}}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="announcement task not found") from exc


@router.post("/api/announcement-tasks/{task_id}/import-ai")
def import_project_announcement_ai(task_id: str, payload: AnnouncementTaskImportAiRequest) -> dict[str, Any]:
    try:
        return import_announcement_ai_response(task_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="announcement task or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


@router.post("/api/announcement-tasks/{task_id}/apply")
def apply_project_announcement(task_id: str, payload: AnnouncementTaskApplyRequest) -> dict[str, Any]:
    try:
        return apply_announcement_task(task_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="announcement task or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


@router.post("/api/announcement-tasks/{task_id}/fix-hard-blockers")
def fix_project_announcement_hard_blockers(task_id: str, payload: AnnouncementTaskApplyRequest) -> dict[str, Any]:
    try:
        return fix_announcement_hard_blockers(task_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="announcement task or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc


@router.post("/api/announcement-tasks/{task_id}/deliver")
def deliver_project_announcement(task_id: str, payload: AnnouncementTaskDeliverRequest) -> dict[str, Any]:
    try:
        return deliver_announcement_task(task_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="announcement task or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc
