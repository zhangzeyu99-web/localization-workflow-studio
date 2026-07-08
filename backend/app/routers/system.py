from __future__ import annotations

import os
import uuid
import json
import subprocess
from pathlib import Path

from .. import db
from .. import jobs
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
from ..delivery_naming import safe_filename
from ..upload_storage import UploadTooLargeError, stream_upload
from fastapi import (
    APIRouter,
    File,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse
from typing import Any

router = APIRouter()
INSTANCE_ID = os.environ.get("LWS_INSTANCE_ID") or uuid.uuid4().hex[:12]
DIAGNOSTICS_ROOT = DATA_ROOT / "diagnostics"
LATEST_UPLOAD_READABILITY = DIAGNOSTICS_ROOT / "latest_upload_readability.json"
APP_ROOT = Path(__file__).resolve().parents[3]


def _deployment_mode() -> str:
    raw_mode = os.environ.get("LWS_DEPLOYMENT_MODE")
    if raw_mode is None and (str(DATA_ROOT).replace("\\", "/").startswith("/data/web/") or str(APP_ROOT).replace("\\", "/").startswith("/data/web/")):
        raw_mode = "cloud"
    mode = (raw_mode or "local").strip().lower()
    return mode if mode in {"local", "cloud"} else "local"


def _is_writable(path: Path) -> bool:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".write-test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _database_connected() -> bool:
    try:
        db.list_projects()
        return True
    except Exception:
        return False


def _latest_upload_readability() -> dict[str, Any] | None:
    if not LATEST_UPLOAD_READABILITY.exists():
        return None
    try:
        payload = json.loads(LATEST_UPLOAD_READABILITY.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _write_latest_upload_readability(payload: dict[str, Any]) -> None:
    DIAGNOSTICS_ROOT.mkdir(parents=True, exist_ok=True)
    LATEST_UPLOAD_READABILITY.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _version_text() -> str:
    try:
        return (APP_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def _git_sha() -> str:
    env_sha = os.environ.get("LWS_GIT_SHA") or os.environ.get("GIT_COMMIT")
    if env_sha:
        return env_sha[:12]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=APP_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _frontend_assets() -> list[str]:
    assets_dir = APP_ROOT / "frontend" / "dist" / "assets"
    if not assets_dir.exists():
        return []
    return sorted(path.name for path in assets_dir.glob("*") if path.is_file())[:20]


@router.get("/api/version")
def version() -> dict[str, Any]:
    return {
        "version": _version_text(),
        "git_sha": _git_sha(),
        "deployment_mode": _deployment_mode(),
        "data_root": str(DATA_ROOT),
        "frontend_assets": _frontend_assets(),
    }

@router.get("/api/health")
def health() -> dict[str, Any]:
    settings = load_settings()
    provider = str(settings.get("provider") or "")
    return {
        "ok": True,
        "deployment_mode": _deployment_mode(),
        "instance_id": INSTANCE_ID,
        "data_root": str(DATA_ROOT),
        "storage": {
            "data_root": str(DATA_ROOT),
            "data_root_writable": _is_writable(DATA_ROOT),
            "uploads": str(DATA_ROOT / "uploads"),
            "uploads_writable": _is_writable(DATA_ROOT / "uploads"),
        },
        "database": {"connected": _database_connected()},
        "provider": {
            "provider": provider,
            "provider_configured": bool(settings.get("api_key")) and provider not in {"", "mock", "test-fake"},
        },
        "latest_upload_readability": _latest_upload_readability(),
    }


@router.post("/api/diagnostics/upload-readability")
def upload_readability_self_test(file: UploadFile = File(...)) -> dict[str, Any]:
    safe_name = safe_filename(file.filename or "diagnostic-upload.txt")
    destination = DATA_ROOT / "uploads" / "diagnostics" / f"{uuid.uuid4().hex[:12]}-{safe_name}"
    try:
        digest, size = stream_upload(file.file, destination)
        preview = destination.read_text(encoding="utf-8", errors="replace")[:500] if destination.suffix.lower() in {".txt", ".md", ".csv", ".json"} else ""
        payload = {
            "ok": True,
            "filename": safe_name,
            "sha256": digest,
            "size": size,
            "path": str(destination),
            "readable": destination.exists(),
            "preview": preview,
            "checked_at": db.now_iso(),
        }
        _write_latest_upload_readability(payload)
        return payload
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=user_facing_error(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"上传自检失败：{user_facing_error(exc)}") from exc


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


def _project_id_from_lease_name(lease_name: str) -> str:
    prefix = "long_text:"
    return lease_name[len(prefix):] if lease_name.startswith(prefix) else ""


@router.get("/api/system/active-jobs")
def get_active_jobs() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entry in jobs.active_jobs():
        lease_name = str(entry.get("lease_name") or "")
        job_id = str(entry.get("job_id") or "")
        project_id = _project_id_from_lease_name(lease_name)
        project_name = ""
        if project_id:
            try:
                project_name = db.get_project(project_id)["name"]
            except KeyError:
                project_name = ""
        result.append(
            {
                "lease_name": lease_name,
                "job_id": job_id,
                "job_kind": jobs.describe_job_kind(job_id),
                "project_id": project_id,
                "project_name": project_name,
                "started_at": entry.get("started_at"),
            }
        )
    return result


@router.get("/api/languages")
def get_languages() -> dict[str, Any]:
    return language_payload()


@router.patch("/api/settings")
def patch_settings(payload: SettingsUpdate) -> dict[str, Any]:
    if _deployment_mode() == "cloud":
        raise HTTPException(status_code=403, detail="\u7ebf\u4e0a\u73af\u5883\u4e0d\u652f\u6301\u524d\u7aef\u4fee\u6539 API \u914d\u7f6e\uff0c\u8bf7\u7f16\u8f91 settings.local.json \u540e\u91cd\u542f\u540e\u7aef\u3002")
    current = load_settings()
    updates = payload.model_dump(exclude_none=True)
    if "api_key" in updates and updates["api_key"] in {"", "configured"}:
        updates.pop("api_key")
    current.update(updates)
    saved = save_settings(current)
    return public_settings(saved)
