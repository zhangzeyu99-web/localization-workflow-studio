from __future__ import annotations

# ruff: noqa: F403,F405
from .shared import *

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
    for item in package["files"]:
        item["download_url"] = f"/api/projects/{project_id}/delivery/{item['filename']}"
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
