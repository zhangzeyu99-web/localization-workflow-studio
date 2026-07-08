from __future__ import annotations

from .. import db
from ..ai_input_audit import announcement_ai_input_summary
from ..jobs import (
    active_job_id_for_project,
    cancel_singleton_job,
    start_singleton_job,
)
from ..schemas import (
    AnnouncementDocxApplyRequest,
    AnnouncementDocxDeliverRequest,
    AnnouncementDocxImportAiRequest,
    AnnouncementDocxPrepareRequest,
    AnnouncementLookupRequest,
    AnnouncementTaskActionRequest,
    AnnouncementTaskApplyRequest,
    AnnouncementTaskCreateRequest,
    AnnouncementTaskDeliverRequest,
    AnnouncementTaskImportAiRequest,
    AnnouncementTaskTermsRequest,
    AnnouncementTaskTranslateRequest,
    AnnouncementTermsRequest,
)
from ..workflow import (
    apply_announcement_task,
    cancel_announcement_task,
    cancel_announcement_translation_task,
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
from .shared import _job_conflict_detail, _query_language
from fastapi import (
    APIRouter,
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
def cancel_project_announcement_task(task_id: str) -> dict[str, Any]:
    try:
        return cancel_announcement_task(task_id)
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


@router.post("/api/announcement-tasks/{task_id}/translate")
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
        task = get_announcement_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="announcement task not found") from exc
    project_id = task["project_id"]
    active = active_job_id_for_project(project_id)
    job_id = f"announcement:{task_id}"
    if active and active != job_id:
        raise HTTPException(status_code=409, detail=_job_conflict_detail({"reason": "project_busy", "active_job_id": active}))
    db.merge_announcement_task_metadata(task_id, {"queued_at": db.now_iso()})
    db.update_announcement_task(task_id, status="queued", current_step=7)

    def worker(cancel_event: Any) -> None:
        try:
            translate_announcement_task(task_id, payload, cancel_event=cancel_event)
        except Exception as exc:
            try:
                current = db.get_announcement_task(task_id)
                if current.get("status") not in {"translated", "canceled", "needs_input", "awaiting_ai_response", "prepared"}:
                    db.merge_announcement_task_metadata(task_id, {"error": user_facing_error(exc)})
                    db.update_announcement_task(task_id, status="failed", current_step=7)
            except Exception:
                pass

    started, conflict = start_singleton_job(project_id, job_id, worker)
    if not started and conflict:
        raise HTTPException(status_code=409, detail=_job_conflict_detail(conflict))
    return {"task": get_announcement_task(task_id), "summary": {"status": "queued"}}


@router.post("/api/announcement-tasks/{task_id}/translate/start")
def translate_project_announcement_start(task_id: str, payload: AnnouncementTaskTranslateRequest) -> dict[str, Any]:
    return _start_announcement_translation_background(task_id, payload)


@router.post("/api/announcement-tasks/{task_id}/translate/resume")
def translate_project_announcement_resume(task_id: str, payload: AnnouncementTaskTranslateRequest) -> dict[str, Any]:
    return _start_announcement_translation_background(task_id, payload)


@router.post("/api/announcement-tasks/{task_id}/translate/cancel")
def translate_project_announcement_cancel(task_id: str) -> dict[str, Any]:
    try:
        task = get_announcement_task(task_id)
        cancel_singleton_job(task["project_id"], f"announcement:{task_id}")
        return {"task": cancel_announcement_translation_task(task_id)["task"], "summary": {"status": "prepared", "reason": "announcement_translation_canceled"}}
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
