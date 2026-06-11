from __future__ import annotations

from .. import db
from ..config import DATA_ROOT
from ..schemas import ArtifactUpdate
from fastapi import (
    APIRouter,
    HTTPException,
)
from fastapi.responses import FileResponse
from pathlib import Path
from typing import Any

router = APIRouter()

def _artifact_file_response(artifact_id: str, project_id: str | None = None) -> FileResponse:
    try:
        artifact = db.get_artifact(artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="artifact not found") from exc
    if project_id and artifact.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail="artifact not found in current project")
    path = Path(artifact["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="artifact file missing")
    try:
        path.resolve().relative_to(DATA_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="artifact path is outside data root") from exc
    return FileResponse(path, media_type=artifact["mime"], filename=path.name)


@router.get("/api/projects/{project_id}/artifacts/{artifact_id}/download")
def download_project_artifact(project_id: str, artifact_id: str) -> FileResponse:
    return _artifact_file_response(artifact_id, project_id=project_id)


@router.get("/api/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str, project_id: str | None = None) -> FileResponse:
    return _artifact_file_response(artifact_id, project_id=project_id)


@router.patch("/api/artifacts/{artifact_id}")
def patch_artifact(artifact_id: str, payload: ArtifactUpdate) -> dict[str, Any]:
    try:
        return db.update_artifact(artifact_id, payload.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="artifact not found") from exc
