from __future__ import annotations

import hashlib
import mimetypes
import shutil
from pathlib import Path
from .. import db, operator_context
from ..ai_input_audit import project_ai_input_summary
from ..config import (
    DATA_ROOT,
    load_settings,
)
from ..delivery_naming import safe_filename
from ..languages import require_supported_language
from ..schemas import (
    ProjectAnalysisRequest,
    ProjectCreate,
    ProjectHarnessUpdate,
    ProjectUpdate,
)
from ..jobs import active_job_id_for_project, describe_job
from ..upload_storage import (
    UploadTooLargeError,
    max_upload_bytes,
    stream_upload,
)
from ..workflow import (
    build_project_material_packet,
    guard_complete_language_table_for_glossary_import,
    guard_complete_language_table_for_project_material,
    harness_overview,
    inspect_translation_readiness,
    inspect_translation_targets,
    project_dir,
    user_facing_error,
    write_project_harness,
    write_project_prompt,
)
from .shared import (
    _find_duplicate_project_upload,
    _unique_path,
    _validate_upload_kind_filename,
    _with_project_stats,
)
from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from typing import Any

router = APIRouter()


def _sync_project_prompt_files(project_id: str, profile: dict[str, Any]) -> None:
    prompts = profile.get("prompts_by_language")
    if not isinstance(prompts, dict):
        return
    prompt_root = project_dir(project_id) / "profile"
    prompt_root.mkdir(parents=True, exist_ok=True)
    for raw_language, raw_prompt in prompts.items():
        try:
            language = require_supported_language(str(raw_language))
        except ValueError:
            continue
        prompt = str(raw_prompt or "").strip()
        if not prompt:
            continue
        (prompt_root / f"translation_prompt_{language}.txt").write_text(prompt, encoding="utf-8")


def _finalize_project_upload(
    project_id: str,
    *,
    safe_name: str,
    kind: str,
    purpose: str,
    temp_path,
    digest: str,
    mime: str,
) -> dict[str, Any]:
    upload_root = project_dir(project_id) / "uploads"
    project_material_upload = kind == "asset" and purpose == "project_material"
    if kind == "asset" and not project_material_upload:
        duplicate = _find_duplicate_project_upload(project_id, kind, digest)
        if duplicate:
            temp_path.unlink(missing_ok=True)
            duplicate["duplicate"] = True
            return duplicate
    destination = _unique_path(upload_root / safe_name)
    temp_path.replace(destination)
    if project_material_upload:
        try:
            guard_complete_language_table_for_project_material(destination)
        except ValueError as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
        duplicate = _find_duplicate_project_upload(project_id, kind, digest)
        if duplicate:
            destination.unlink(missing_ok=True)
            duplicate["duplicate"] = True
            return duplicate
    if kind in {"term_base", "glossary_final"}:
        try:
            guard_complete_language_table_for_glossary_import(destination)
        except ValueError as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    try:
        with destination.open("rb") as fh:
            fh.read(1)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"上传后文件不可读：{user_facing_error(exc)}") from exc
    artifact = db.add_artifact(
        project_id,
        safe_name,
        destination,
        kind,
        mime=mime,
        origin="uploaded",
        metadata={"sha256": digest, "original_filename": safe_name, "readable": True, **({"purpose": purpose} if purpose else {})},
    )
    artifact["duplicate"] = False
    return artifact


def _validate_project_analysis_artifacts(project_id: str, artifact_ids: list[str]) -> None:
    for artifact_id in artifact_ids:
        try:
            artifact = db.get_artifact(artifact_id)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=f"资料文件不存在：{artifact_id}") from exc
        if artifact.get("project_id") != project_id:
            raise HTTPException(status_code=400, detail=f"资料文件不属于当前项目：{artifact.get('label') or artifact_id}")
        path = Path(artifact["path"])
        if not path.exists():
            raise HTTPException(status_code=400, detail=f"资料文件不存在或未挂载到当前后端：{artifact.get('label') or path.name}")
        try:
            with path.open("rb") as fh:
                fh.read(1)
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"资料文件不可读：{artifact.get('label') or path.name}；{user_facing_error(exc)}") from exc


def _material_enters_ai(material: dict[str, Any]) -> bool:
    status = str(material.get("status") or "")
    excerpt = str(material.get("excerpt") or "").strip()
    return bool(excerpt) and status.startswith(("parsed", "vision_analyzed"))


def _material_has_nonblocking_fallback(material: dict[str, Any]) -> bool:
    status = str(material.get("status") or "")
    excerpt = str(material.get("excerpt") or "").strip()
    return bool(excerpt) and status.startswith(("archived_only:image_api_key_missing", "archived_only:video_api_key_missing"))


def _reject_unreadable_analysis_packet(material_packet: dict[str, Any], artifact_count: int) -> None:
    if artifact_count <= 0:
        return
    materials = [item for item in material_packet.get("materials", []) if isinstance(item, dict)]
    if any(_material_enters_ai(item) for item in materials):
        return
    if any(_material_has_nonblocking_fallback(item) for item in materials):
        return
    reasons = []
    for item in materials:
        label = str(item.get("label") or item.get("filename") or "资料").strip()
        reason = str(item.get("warning") or item.get("status") or "未解析").strip()
        reasons.append(f"{label}：{reason}")
    detail = "；".join(reasons[:3]) if reasons else "没有资料进入 AI 输入"
    raise HTTPException(status_code=400, detail=f"上传资料没有成功解析进 AI 分析：{detail}")


@router.get("/api/projects")
def get_projects() -> list[dict[str, Any]]:
    return [_with_project_stats(project) for project in db.list_projects()]


@router.post("/api/projects")
def create_project(payload: ProjectCreate) -> dict[str, Any]:
    existing = db.find_project_by_name(payload.name)
    if existing:
        return {**_with_project_stats(existing), "duplicate": True}
    project = db.insert_project(payload.name, payload.type, payload.description, payload.icon)
    project_dir(project["id"])
    return {**_with_project_stats(project), "duplicate": False}


@router.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    try:
        return _with_project_stats(db.get_project(project_id), include_details=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@router.get("/api/projects/{project_id}/ai-input-summary")
def get_project_ai_input_summary(project_id: str) -> dict[str, Any]:
    try:
        return project_ai_input_summary(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@router.patch("/api/projects/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate) -> dict[str, Any]:
    try:
        current = db.get_project(project_id)
        updates = payload.model_dump(exclude_none=True)
        if "profile" in updates or "prompt_text" in updates:
            profile = dict(current.get("profile") or {})
            incoming_profile = updates.get("profile")
            if isinstance(incoming_profile, dict):
                profile.update(incoming_profile)
            if "prompt_text" in updates:
                prompts = dict(profile.get("prompts_by_language") or {})
                display_prompts = dict(profile.get("display_prompts_by_language") or {})
                prompts["en"] = updates["prompt_text"]
                display_prompts["en"] = updates["prompt_text"]
                profile["prompts_by_language"] = prompts
                profile["display_prompts_by_language"] = display_prompts
            elif isinstance(profile.get("prompts_by_language"), dict) and str(profile["prompts_by_language"].get("en") or "").strip():
                updates["prompt_text"] = str(profile["prompts_by_language"].get("en") or "")
            updates["profile"] = profile
            _sync_project_prompt_files(project_id, profile)
        return _with_project_stats(db.update_project(project_id, updates), include_details=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@router.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict[str, bool]:
    # A background job for this project (translation/QA/model-fix/etc.) may
    # still be reading/writing project files and artifacts on disk. Deleting
    # the project directory out from under it races the job's file IO, so
    # refuse the delete while a job is active instead of racing it.
    active_job_id = active_job_id_for_project(project_id)
    if active_job_id:
        raise HTTPException(
            status_code=409,
            detail=f"该项目正在执行任务（{describe_job(active_job_id)}），请先取消或等待任务完成再删除",
        )
    run_ids: list[str] = []
    existed = True
    project_name = ""
    try:
        project_name = db.get_project(project_id).get("name") or ""
        run_ids = [run["id"] for run in db.list_runs(project_id)]
        db.delete_project(project_id)
    except KeyError:
        existed = False
    # delete_project() deletes this project's own run events in the same
    # transaction, so a db.add_event() here would just be erased; record to
    # the durable operator audit log instead (no-op if no nickname is set).
    if existed:
        operator_context.record_operator_audit(DATA_ROOT, "delete_project", {"project_id": project_id, "project_name": project_name})
    shutil.rmtree(DATA_ROOT / "projects" / project_id, ignore_errors=True)
    for run_id in run_ids:
        shutil.rmtree(DATA_ROOT / "runs" / run_id, ignore_errors=True)
    return {"deleted": existed}


@router.get("/api/projects/{project_id}/harness")
def get_project_harness(project_id: str) -> dict[str, Any]:
    try:
        return harness_overview(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@router.patch("/api/projects/{project_id}/harness")
def patch_project_harness(project_id: str, payload: ProjectHarnessUpdate) -> dict[str, Any]:
    try:
        harness = write_project_harness(project_id, payload.model_dump(exclude_none=True))
        return {"global_harness": harness_overview(project_id)["global_harness"], "project_harness": harness}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@router.post("/api/projects/{project_id}/analyze")
def analyze_project(project_id: str, payload: ProjectAnalysisRequest) -> dict[str, Any]:
    try:
        project = db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    try:
        target_language = require_supported_language(payload.target_language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
    _validate_project_analysis_artifacts(project_id, payload.asset_artifact_ids)
    settings = load_settings()
    material_packet = build_project_material_packet(project_id, payload.asset_artifact_ids, settings, run_visual_analysis=True)
    _reject_unreadable_analysis_packet(material_packet, len(payload.asset_artifact_ids))
    notes = [str(material.get("note") or "") for material in material_packet.get("materials", []) if isinstance(material, dict)]
    profile_path, prompt_path, brief_path, packet_path, report_path, prompt = write_project_prompt(
        project,
        payload.intro,
        notes,
        target_language=target_language,
        material_packet=material_packet,
        settings=settings,
    )
    artifacts = [
        db.add_artifact(project_id, "Project profile", profile_path, "project_profile", mime="application/json"),
        db.add_artifact(project_id, "Translation prompt", prompt_path, "translation_prompt", mime="text/plain"),
        db.add_artifact(project_id, "Project brief", brief_path, "project_brief", mime="text/markdown"),
        db.add_artifact(project_id, "Project material packet", packet_path, "project_material_packet", mime="application/json"),
        db.add_artifact(project_id, "Project analysis report", report_path, "project_analysis_report", mime="text/markdown"),
    ]
    fresh_project = _with_project_stats(db.get_project(project_id), include_details=True)
    profile = fresh_project.get("profile") or {}
    return {
        "project": fresh_project,
        "artifacts": artifacts,
        "prompt": prompt,
        "analysis": {
            "source": profile.get("analysis_source") or "template",
            "warning": profile.get("analysis_warning") or "",
            "summary": material_packet.get("summary") or {},
            "materials": [
                {
                    "artifact_id": material.get("artifact_id"),
                    "label": material.get("label"),
                    "material_type": material.get("material_type"),
                    "status": material.get("status"),
                    "included_in_ai": _material_enters_ai(material),
                    "warning": material.get("warning") or "",
                    "language_table_candidate": bool(material.get("language_table_candidate")),
                    "project_brief_candidate": bool(material.get("project_brief_candidate")),
                    "detected_languages": material.get("detected_languages") or [],
                    "rows": material.get("rows"),
                }
                for material in material_packet.get("materials", [])
                if isinstance(material, dict)
            ],
            "language_table_candidates": material_packet.get("language_table_candidates") or [],
        },
    }


@router.post("/api/projects/{project_id}/files")
def upload_project_file(project_id: str, file: UploadFile = File(...), kind: str = "upload", purpose: str = "") -> dict[str, Any]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    safe_name = safe_filename(file.filename or "upload.bin")
    _validate_upload_kind_filename(kind, safe_name)
    upload_root = project_dir(project_id) / "uploads"
    upload_root.mkdir(parents=True, exist_ok=True)
    temp_path = _unique_path(upload_root / f".{safe_name}.uploading")
    try:
        digest, _ = stream_upload(file.file, temp_path)
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=user_facing_error(exc)) from exc
    mime = file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    return _finalize_project_upload(
        project_id,
        safe_name=safe_name,
        kind=kind,
        purpose=purpose,
        temp_path=temp_path,
        digest=digest,
        mime=mime,
    )


@router.post("/api/projects/{project_id}/files/chunk")
def upload_project_file_chunk(
    project_id: str,
    file: UploadFile = File(...),
    upload_id: str = Form(...),
    filename: str = Form(...),
    kind: str = Form(...),
    purpose: str = Form(""),
    index: int = Form(...),
    total: int = Form(...),
) -> dict[str, Any]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    safe_name = safe_filename(filename or file.filename or "upload.bin")
    _validate_upload_kind_filename(kind, safe_name)
    safe_upload_id = "".join(ch for ch in upload_id if ch.isalnum() or ch in "-_")[:80]
    if not safe_upload_id or safe_upload_id != upload_id:
        raise HTTPException(status_code=400, detail="invalid upload session")
    if total < 1 or total > 10000 or index < 0 or index >= total:
        raise HTTPException(status_code=400, detail="invalid upload chunk")
    upload_root = project_dir(project_id) / "uploads"
    chunk_dir = upload_root / ".chunks" / safe_upload_id
    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunk_path = chunk_dir / f"{index:06d}.part"
    try:
        stream_upload(file.file, chunk_path, max_bytes=max_upload_bytes())
    except UploadTooLargeError as exc:
        shutil.rmtree(chunk_dir, ignore_errors=True)
        raise HTTPException(status_code=413, detail=user_facing_error(exc)) from exc
    received = len(list(chunk_dir.glob("*.part")))
    if received < total:
        return {"complete": False, "received": received, "total": total}

    temp_path = _unique_path(upload_root / f".{safe_name}.uploading")
    digest_builder = hashlib.sha256()
    total_size = 0
    limit = max_upload_bytes()
    try:
        with temp_path.open("wb") as output:
            for part_index in range(total):
                part_path = chunk_dir / f"{part_index:06d}.part"
                if not part_path.exists():
                    temp_path.unlink(missing_ok=True)
                    return {"complete": False, "received": received, "total": total}
                with part_path.open("rb") as part:
                    for chunk in iter(lambda: part.read(1024 * 1024), b""):
                        total_size += len(chunk)
                        if total_size > limit:
                            raise UploadTooLargeError(limit)
                        digest_builder.update(chunk)
                        output.write(chunk)
        shutil.rmtree(chunk_dir, ignore_errors=True)
        mime = file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        artifact = _finalize_project_upload(
            project_id,
            safe_name=safe_name,
            kind=kind,
            purpose=purpose,
            temp_path=temp_path,
            digest=digest_builder.hexdigest(),
            mime=mime,
        )
        return {"complete": True, "artifact": artifact}
    except UploadTooLargeError as exc:
        temp_path.unlink(missing_ok=True)
        shutil.rmtree(chunk_dir, ignore_errors=True)
        raise HTTPException(status_code=413, detail=user_facing_error(exc)) from exc
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


@router.get("/api/projects/{project_id}/assets")
def list_project_assets(project_id: str, role: str | None = None, origin: str | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    return db.list_artifacts(project_id=project_id, run_id=run_id, role=role, origin=origin)


def _validate_artifact_owner(project_id: str, artifact_id: str) -> None:
    try:
        artifact = db.get_artifact(artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="artifact not found") from exc
    if artifact.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail="artifact not found in current project")


@router.get("/api/projects/{project_id}/artifacts/{artifact_id}/translation-readiness")
def project_artifact_translation_readiness(project_id: str, artifact_id: str, batch_size: int | None = None, language: str = "en") -> dict[str, Any]:
    _validate_artifact_owner(project_id, artifact_id)
    try:
        return inspect_translation_readiness(artifact_id, batch_size=batch_size, language=require_supported_language(language))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc


@router.get("/api/artifacts/{artifact_id}/translation-readiness")
def artifact_translation_readiness(artifact_id: str, batch_size: int | None = None, language: str = "en") -> dict[str, Any]:
    try:
        return inspect_translation_readiness(artifact_id, batch_size=batch_size, language=require_supported_language(language))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc


@router.get("/api/projects/{project_id}/artifacts/{artifact_id}/translation-targets")
def project_artifact_translation_targets(project_id: str, artifact_id: str) -> dict[str, Any]:
    _validate_artifact_owner(project_id, artifact_id)
    try:
        return inspect_translation_targets(artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc


@router.get("/api/artifacts/{artifact_id}/translation-targets")
def artifact_translation_targets(artifact_id: str) -> dict[str, Any]:
    try:
        return inspect_translation_targets(artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=user_facing_error(exc)) from exc
