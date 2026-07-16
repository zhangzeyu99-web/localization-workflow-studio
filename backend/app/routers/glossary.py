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
    GlossaryBatchResolveRequest,
    GlossaryCandidateUpdate,
    GlossaryExtractRequest,
    GlossaryImportRequest,
    GlossaryTermPayload,
    GlossaryTermUpdate,
)
from ..archive_batch_engine import ArchiveBatchError
from ..glossary_archive_batches import (
    analyze_glossary_archive,
    commit_glossary_archive,
    list_glossary_import_batches,
    rollback_glossary_import_batch,
)
from ..workflow import (
    ImportContractError,
    export_glossary,
    extract_glossary,
    import_glossary,
    preview_glossary_import,
    translate_missing_glossary_candidates_sync,
    user_facing_error,
)
from .shared import (
    _query_language,
    _require_project_batch,
    _require_project_candidate,
    _require_project_term,
)
from fastapi import (
    APIRouter,
    HTTPException,
    Query,
)
from fastapi.responses import FileResponse
from typing import Any, Literal

router = APIRouter()

@router.get("/api/projects/{project_id}/glossary")
def list_project_glossary(project_id: str, language: str | None = None) -> list[dict[str, Any]]:
    return db.list_glossary_terms(project_id, language=_query_language(language))


@router.get("/api/projects/{project_id}/glossary/wide")
def list_project_glossary_wide(
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
            "glossary",
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


@router.get("/api/projects/{project_id}/glossary/by-source-key")
def get_glossary_source_summary(project_id: str, source_key: str) -> dict[str, Any]:
    try:
        return archive_source_summary(project_id, "glossary", source_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/api/projects/{project_id}/glossary/by-source-key")
def patch_glossary_source(
    project_id: str,
    source_key: str,
    payload: ArchiveSourcePatchRequest,
) -> dict[str, Any]:
    try:
        return patch_archive_source(
            project_id,
            "glossary",
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


@router.delete("/api/projects/{project_id}/glossary/by-source-key")
def delete_glossary_source(
    project_id: str,
    source_key: str,
    expected_revision: str = Query(..., min_length=1),
) -> dict[str, Any]:
    try:
        return delete_archive_source(
            project_id,
            "glossary",
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


@router.get("/api/projects/{project_id}/glossary/batches")
def list_project_glossary_batches(project_id: str, language: str | None = None) -> dict[str, Any]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    language_code = _query_language(language)
    batches = db.list_glossary_batches(project_id, language=language_code)
    latest = batches[0] if batches else None
    candidates = db.list_glossary_candidates(project_id, batch_id=latest["id"], language=language_code) if latest else []
    return {"batches": batches, "active_batch": latest, "candidates": candidates}


@router.patch("/api/projects/{project_id}/glossary/candidates/{candidate_id}")
def update_project_glossary_candidate(project_id: str, candidate_id: str, payload: GlossaryCandidateUpdate) -> dict[str, Any]:
    candidate = _require_project_candidate(project_id, candidate_id)
    _ = candidate
    data = payload.model_dump(exclude_unset=True)
    if "language" in data:
        data["language"] = _query_language(data.get("language")) or "en"
    return db.update_glossary_candidate(candidate_id, data)


@router.post("/api/projects/{project_id}/glossary/batches/{batch_id}/accept")
def accept_project_glossary_candidates(project_id: str, batch_id: str, payload: GlossaryBatchResolveRequest) -> dict[str, Any]:
    _require_project_batch(project_id, batch_id)
    return db.accept_glossary_candidates(project_id, batch_id, payload.candidate_ids or None)


@router.post("/api/projects/{project_id}/glossary/batches/{batch_id}/translate-missing")
def translate_missing_project_glossary_candidates(project_id: str, batch_id: str) -> dict[str, Any]:
    _require_project_batch(project_id, batch_id)
    try:
        return translate_missing_glossary_candidates_sync(project_id, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc


@router.post("/api/projects/{project_id}/glossary/batches/{batch_id}/reject")
def reject_project_glossary_candidates(project_id: str, batch_id: str, payload: GlossaryBatchResolveRequest) -> dict[str, Any]:
    _require_project_batch(project_id, batch_id)
    return db.reject_glossary_candidates(project_id, batch_id, payload.candidate_ids or None)


@router.post("/api/projects/{project_id}/glossary")
def create_glossary_term(project_id: str, payload: GlossaryTermPayload) -> dict[str, Any]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    data = payload.model_dump()
    data["language"] = _query_language(data.get("language")) or "en"
    data.update(
        {
            "target_alt": "",
            "source_type": "manual",
            "confirmed": True,
            "active": True,
            "review_status": "approved",
        }
    )
    return db.upsert_glossary_term(project_id, data)


@router.patch("/api/projects/{project_id}/glossary/{term_id}")
def update_glossary_term(project_id: str, term_id: str, payload: GlossaryTermUpdate) -> dict[str, Any]:
    _require_project_term(project_id, term_id)
    data = payload.model_dump(exclude_unset=True)
    if "language" in data:
        data["language"] = _query_language(data.get("language")) or "en"
    data.update(
        {
            "target_alt": "",
            "source_type": "manual",
            "confirmed": True,
            "active": True,
            "review_status": "approved",
        }
    )
    updated = db.update_glossary_term(term_id, data)
    return db.get_glossary_term(updated["id"])


@router.delete("/api/projects/{project_id}/glossary/{term_id}")
def delete_glossary_term(project_id: str, term_id: str) -> dict[str, bool]:
    _require_project_term(project_id, term_id)
    db.delete_glossary_term(term_id)
    return {"deleted": True}


@router.post("/api/projects/{project_id}/glossary/import-preview")
def preview_project_glossary_import(project_id: str, payload: GlossaryImportRequest) -> dict[str, Any]:
    try:
        return preview_glossary_import(project_id, payload)
    except ImportContractError as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project, artifact, or column not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc


@router.post("/api/projects/{project_id}/glossary/import")
def import_project_glossary(project_id: str, payload: GlossaryImportRequest) -> dict[str, Any]:
    try:
        payload.language = _query_language(payload.language) or "en"
        return import_glossary(project_id, payload)
    except ArchiveBatchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ImportContractError as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project, artifact, or column not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc


@router.post("/api/projects/{project_id}/glossary/import/analyze")
def analyze_project_glossary_import(project_id: str, payload: GlossaryImportRequest) -> dict[str, Any]:
    try:
        return analyze_glossary_archive(project_id, payload)
    except ArchiveBatchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/projects/{project_id}/glossary/import/commit")
def commit_project_glossary_import(project_id: str, payload: ArchiveImportCommitRequest, compact: bool = False) -> dict[str, Any]:
    try:
        return commit_glossary_archive(project_id, payload.token, compact=compact)
    except ArchiveBatchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/api/projects/{project_id}/glossary/import/batches")
def list_project_glossary_import_batches(project_id: str, compact: bool = False) -> dict[str, Any]:
    try:
        return list_glossary_import_batches(project_id, compact=compact)
    except ArchiveBatchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/projects/{project_id}/glossary/import/batches/{batch_id}/rollback")
def rollback_project_glossary_import(project_id: str, batch_id: str) -> dict[str, Any]:
    try:
        return rollback_glossary_import_batch(project_id, batch_id)
    except ArchiveBatchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/api/projects/{project_id}/glossary/export")
def export_project_glossary(project_id: str, format: str = "xlsx", language: str | None = None) -> Any:
    try:
        exported = export_glossary(project_id, format, language=_query_language(language))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    if isinstance(exported, dict):
        return exported
    media_type = "text/csv" if exported.suffix.lower() == ".csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(exported, media_type=media_type, filename=exported.name)

@router.post("/api/projects/{project_id}/glossary/extract")
def extract_project_glossary(project_id: str, payload: GlossaryExtractRequest) -> dict[str, Any]:
    try:
        db.get_project(project_id)
        artifact = db.get_artifact(payload.input_artifact_id)
        if artifact["project_id"] != project_id:
            raise KeyError(payload.input_artifact_id)
        payload.language = _query_language(payload.language) or "en"
        return extract_glossary(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc
