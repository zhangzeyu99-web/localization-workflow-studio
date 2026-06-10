from __future__ import annotations

from .. import db
from ..schemas import (
    TranslationArchiveImportRequest,
    TranslationEntryPayload,
    TranslationEntryUpdate,
)
from ..workflow import (
    export_translation_archive,
    import_translation_archive,
    list_translation_archive_wide,
    user_facing_error,
)
from .shared import (
    _query_language,
    _require_project_translation,
)
from fastapi import (
    APIRouter,
    HTTPException,
)
from fastapi.responses import FileResponse
from typing import Any

router = APIRouter()

@router.get("/api/projects/{project_id}/translations")
def list_project_translations(project_id: str, language: str | None = None) -> list[dict[str, Any]]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    return db.list_translation_entries(project_id, language=_query_language(language))


@router.get("/api/projects/{project_id}/translations/wide")
def list_project_translations_wide(project_id: str) -> dict[str, Any]:
    try:
        return list_translation_archive_wide(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@router.post("/api/projects/{project_id}/translations")
def create_translation_entry(project_id: str, payload: TranslationEntryPayload) -> dict[str, Any]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    data = payload.model_dump()
    data["language"] = _query_language(data.get("language")) or "en"
    return db.upsert_translation_entry(project_id, data)


@router.patch("/api/projects/{project_id}/translations/{entry_id}")
def update_translation_entry(project_id: str, entry_id: str, payload: TranslationEntryUpdate) -> dict[str, Any]:
    _require_project_translation(project_id, entry_id)
    data = payload.model_dump(exclude_unset=True)
    if "language" in data:
        data["language"] = _query_language(data.get("language")) or "en"
    return db.update_translation_entry(entry_id, data)


@router.delete("/api/projects/{project_id}/translations/{entry_id}")
def delete_translation_entry(project_id: str, entry_id: str) -> dict[str, bool]:
    _require_project_translation(project_id, entry_id)
    db.delete_translation_entry(entry_id)
    return {"deleted": True}


@router.post("/api/projects/{project_id}/translations/import")
def import_project_translations(project_id: str, payload: TranslationArchiveImportRequest) -> dict[str, Any]:
    try:
        return import_translation_archive(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project or artifact not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc


@router.get("/api/projects/{project_id}/translations/export")
def export_project_translations(project_id: str, format: str = "xlsx", language: str | None = None) -> Any:
    try:
        exported = export_translation_archive(project_id, format, language=_query_language(language))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    if isinstance(exported, dict):
        return exported
    media_type = "text/csv" if exported.suffix.lower() == ".csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(exported, media_type=media_type, filename=exported.name)
