from __future__ import annotations

from .. import db
from ..download_urls import attach_delivery_item_downloads
from ..workflow import (
    build_merged_delivery_package,
    build_delivery_package,
    list_project_deliverables,
    project_dir,
    user_facing_error,
)
from ..schemas import MultilingualQueueRequest
from .shared import (
    _attach_delivery_downloads,
    _safe_filename,
)
from fastapi import (
    APIRouter,
    HTTPException,
)
from fastapi.responses import FileResponse
from typing import Any

router = APIRouter()

@router.get("/api/projects/{project_id}/deliverables")
def get_project_deliverables(project_id: str) -> dict[str, Any]:
    try:
        deliverables = list_project_deliverables(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    for deliverable in deliverables:
        _attach_delivery_downloads(project_id, deliverable)
    return {"project_id": project_id, "deliverables": deliverables}


@router.post("/api/projects/{project_id}/delivery-package")
def create_project_delivery(project_id: str, run_id: str | None = None) -> dict[str, Any]:
    try:
        package = build_delivery_package(project_id, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=user_facing_error(exc)) from exc
    attach_delivery_item_downloads(project_id, package["files"])
    _attach_delivery_downloads(project_id, package["deliverable"])
    return package


@router.post("/api/projects/{project_id}/delivery-package/merged")
def create_project_merged_delivery(project_id: str, payload: MultilingualQueueRequest) -> dict[str, Any]:
    try:
        package = build_merged_delivery_package(
            project_id,
            payload.input_artifact_id,
            payload.languages,
            payload.translation_task_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=user_facing_error(exc)) from exc
    attach_delivery_item_downloads(project_id, package["files"])
    if package.get("deliverable"):
        _attach_delivery_downloads(project_id, package["deliverable"])
    return package


@router.get("/api/projects/{project_id}/delivery/{filename}")
def download_project_delivery(project_id: str, filename: str) -> FileResponse:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    safe_name = _safe_filename(filename)
    path = project_dir(project_id) / "delivery" / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="delivery file missing")
    media_type = "text/plain"
    if path.suffix.lower() == ".md":
        media_type = "text/markdown"
    elif path.suffix.lower() == ".xlsx":
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(path, media_type=media_type, filename=path.name)
