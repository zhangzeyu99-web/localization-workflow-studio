from __future__ import annotations

# ruff: noqa: F403,F405
from .shared import *

router = APIRouter()

@router.get("/api/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str) -> FileResponse:
    try:
        artifact = db.get_artifact(artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="artifact not found") from exc
    path = Path(artifact["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="artifact file missing")
    try:
        path.resolve().relative_to(DATA_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="artifact path is outside data root") from exc
    return FileResponse(path, media_type=artifact["mime"], filename=path.name)


@router.patch("/api/artifacts/{artifact_id}")
def patch_artifact(artifact_id: str, payload: ArtifactUpdate) -> dict[str, Any]:
    try:
        return db.update_artifact(artifact_id, payload.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="artifact not found") from exc
