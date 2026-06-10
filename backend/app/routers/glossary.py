from __future__ import annotations

# ruff: noqa: F403,F405
from .shared import *

router = APIRouter()

@router.get("/api/projects/{project_id}/glossary")
def list_project_glossary(project_id: str, language: str | None = None) -> list[dict[str, Any]]:
    return db.list_glossary_terms(project_id, language=_query_language(language))


@router.get("/api/projects/{project_id}/glossary/wide")
def list_project_glossary_wide(project_id: str) -> dict[str, Any]:
    try:
        return list_glossary_wide(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


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
    return db.upsert_glossary_term(project_id, data)


@router.patch("/api/projects/{project_id}/glossary/{term_id}")
def update_glossary_term(project_id: str, term_id: str, payload: GlossaryTermUpdate) -> dict[str, Any]:
    _require_project_term(project_id, term_id)
    data = payload.model_dump(exclude_unset=True)
    if "language" in data:
        data["language"] = _query_language(data.get("language")) or "en"
    updated = db.update_glossary_term(term_id, data)
    db.dedupe_project_glossary_terms(project_id, preferred_term_id=term_id, merge_duplicates=False, language=updated.get("language"))
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
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project, artifact, or column not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc


@router.post("/api/projects/{project_id}/glossary/import")
def import_project_glossary(project_id: str, payload: GlossaryImportRequest) -> dict[str, Any]:
    try:
        payload.language = _query_language(payload.language) or "en"
        return import_glossary(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project, artifact, or column not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc


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
        payload.language = _query_language(payload.language) or "en"
        return extract_glossary(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=user_facing_error(exc)) from exc
