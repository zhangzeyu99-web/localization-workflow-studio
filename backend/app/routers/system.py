from __future__ import annotations

from ..config import (
    DATA_ROOT,
    load_settings,
    public_settings,
    save_settings,
)
from ..import_templates import build_import_template
from ..languages import language_payload
from ..schemas import SettingsUpdate
from ..workflow import user_facing_error
from fastapi import (
    APIRouter,
    HTTPException,
)
from fastapi.responses import FileResponse
from typing import Any

router = APIRouter()

@router.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "data_root": str(DATA_ROOT)}


@router.get("/api/import-templates/{kind}")
def download_import_template(kind: str) -> FileResponse:
    try:
        path = build_import_template(kind)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=user_facing_error(exc)) from exc
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=path.name,
    )


@router.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return public_settings()


@router.get("/api/languages")
def get_languages() -> dict[str, Any]:
    return language_payload()


@router.patch("/api/settings")
def patch_settings(payload: SettingsUpdate) -> dict[str, Any]:
    current = load_settings()
    updates = payload.model_dump(exclude_none=True)
    if "api_key" in updates and updates["api_key"] in {"", "configured"}:
        updates.pop("api_key")
    current.update(updates)
    saved = save_settings(current)
    return public_settings(saved)
