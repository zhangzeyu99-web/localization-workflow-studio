from __future__ import annotations

from .. import db
from ..archive_pagination import (
    ArchiveRevisionConflict,
    ArchiveSourceConflict,
    archive_source_summary,
    delete_archive_source,
    list_archive_wide_page,
    patch_archive_source,
)
from ..schemas import (
    ArchiveImportCommitRequest,
    ArchiveSourcePatchRequest,
    TranslationArchiveImportRequest,
    TranslationEntryPayload,
    TranslationEntryUpdate,
)
from ..translation_archive_batches import (
    ArchiveBatchError,
    analyze_translation_archive,
    commit_translation_archive,
    list_translation_import_batches,
    rollback_translation_import_batch,
)
from ..workflow import (
    ImportContractError,
    export_translation_archive,
    import_translation_archive,
    user_facing_error,
)
from .shared import (
    _query_language,
    _require_project_translation,
)
from fastapi import (
    APIRouter,
    HTTPException,
    Query,
)
from fastapi.responses import FileResponse
from typing import Any, Literal

router = APIRouter()

@router.get("/api/projects/{project_id}/translations")
def list_project_translations(project_id: str, language: str | None = None) -> list[dict[str, Any]]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    return db.list_translation_entries(project_id, language=_query_language(language))


@router.get("/api/projects/{project_id}/translations/wide")
def list_project_translations_wide(
    project_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    q: str = "",
    languages: str | None = None,
    sort: Literal["source", "id"] = "source",
) -> dict[str, Any]:
    try:
        return list_archive_wide_page(
            project_id,
            "translations",
            page=page,
            page_size=page_size,
            q=q,
            languages=languages,
            sort=sort,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/projects/{project_id}/translations")
def create_translation_entry(project_id: str, payload: TranslationEntryPayload) -> dict[str, Any]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    data = payload.model_dump()
    data["language"] = _query_language(data.get("language")) or "en"
    data.update({"source_type": "manual", "review_status": "approved", "active": 1})
    return db.upsert_translation_entry(project_id, data)


@router.get("/api/projects/{project_id}/translations/by-source-key")
def get_translation_source_summary(project_id: str, source_key: str) -> dict[str, Any]:
    try:
        return archive_source_summary(project_id, "translations", source_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/api/projects/{project_id}/translations/by-source-key")
def patch_translation_source(
    project_id: str,
    source_key: str,
    payload: ArchiveSourcePatchRequest,
) -> dict[str, Any]:
    try:
        return patch_archive_source(
            project_id,
            "translations",
            source_key,
            expected_revision=payload.expected_revision,
            shared=payload.shared,
            targets=payload.targets,
        )
    except ArchiveRevisionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "archive_revision_conflict",
                "message": "归档内容已变化，请刷新后重新编辑。",
                "expected_revision": exc.expected_revision,
                "current_revision": exc.current_revision,
            },
        ) from exc
    except ArchiveSourceConflict as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message}) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="archive source not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/api/projects/{project_id}/translations/by-source-key")
def delete_translation_source(
    project_id: str,
    source_key: str,
    expected_revision: str = Query(..., min_length=1),
) -> dict[str, Any]:
    try:
        return delete_archive_source(
            project_id,
            "translations",
            source_key,
            expected_revision=expected_revision,
        )
    except ArchiveRevisionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "archive_revision_conflict",
                "message": "归档内容已变化，请刷新后重新确认删除范围。",
                "expected_revision": exc.expected_revision,
                "current_revision": exc.current_revision,
            },
        ) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/api/projects/{project_id}/translations/{entry_id}")
def update_translation_entry(project_id: str, entry_id: str, payload: TranslationEntryUpdate) -> dict[str, Any]:
    _require_project_translation(project_id, entry_id)
    data = payload.model_dump(exclude_unset=True)
    if "language" in data:
        data["language"] = _query_language(data.get("language")) or "en"
    data.update({"source_type": "manual", "review_status": "approved", "active": 1})
    return db.update_translation_entry(entry_id, data)


@router.delete("/api/projects/{project_id}/translations/{entry_id}")
def delete_translation_entry(project_id: str, entry_id: str) -> dict[str, bool]:
    _require_project_translation(project_id, entry_id)
    db.delete_translation_entry(entry_id)
    return {"deleted": True}


@router.post("/api/projects/{project_id}/translations/import")
def import_project_translations(project_id: str, payload: TranslationArchiveImportRequest) -> dict[str, Any]:
    try:
        legacy_payload = payload
        if "override_protected" not in payload.model_fields_set:
            legacy_payload = payload.model_copy(update={"override_protected": True})
        return import_translation_archive(project_id, legacy_payload)
    except ArchiveBatchError as exc:
        detail = dict(exc.detail)
        if detail.get("code") == "sheet_selection_required" and "sheets" in detail:
            detail["candidates"] = detail.pop("sheets")
        detail.pop("batch_id", None)
        raise HTTPException(status_code=400, detail=detail) from exc
    except ImportContractError as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project or artifact not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc


@router.post("/api/projects/{project_id}/translations/import/analyze")
def analyze_project_translation_import(project_id: str, payload: TranslationArchiveImportRequest) -> dict[str, Any]:
    try:
        return analyze_translation_archive(project_id, payload)
    except ArchiveBatchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/projects/{project_id}/translations/import/commit")
def commit_project_translation_import(project_id: str, payload: ArchiveImportCommitRequest, compact: bool = False) -> dict[str, Any]:
    try:
        return commit_translation_archive(project_id, payload.token, compact=compact)
    except ArchiveBatchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/api/projects/{project_id}/translations/import/batches")
def list_project_translation_import_batches(project_id: str, compact: bool = False) -> dict[str, Any]:
    try:
        return list_translation_import_batches(project_id, compact=compact)
    except ArchiveBatchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/projects/{project_id}/translations/import/batches/{batch_id}/rollback")
def rollback_project_translation_import(project_id: str, batch_id: str) -> dict[str, Any]:
    try:
        return rollback_translation_import_batch(project_id, batch_id)
    except ArchiveBatchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


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
