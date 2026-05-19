from __future__ import annotations

import mimetypes
import json
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app import db
    from app.config import DATA_ROOT, load_settings, public_settings, save_settings
    from app.schemas import (
        GlossaryExtractRequest,
        GlossaryTermPayload,
        GlossaryTermUpdate,
        ProjectAnalysisRequest,
        ProjectCreate,
        ProjectUpdate,
        RunCreate,
        SettingsUpdate,
        TranslateRequest,
    )
    from app.workflow import analyze_assets, extract_glossary, project_dir, run_translate_sync, write_project_prompt
else:
    from . import db
    from .config import DATA_ROOT, load_settings, public_settings, save_settings
    from .schemas import (
        GlossaryExtractRequest,
        GlossaryTermPayload,
        GlossaryTermUpdate,
        ProjectAnalysisRequest,
        ProjectCreate,
        ProjectUpdate,
        RunCreate,
        SettingsUpdate,
        TranslateRequest,
    )
    from .workflow import analyze_assets, extract_glossary, project_dir, run_translate_sync, write_project_prompt


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ = app
    db.init_db()
    yield


app = FastAPI(title="Localization Workflow Studio", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "data_root": str(DATA_ROOT)}


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return public_settings()


@app.patch("/api/settings")
def patch_settings(payload: SettingsUpdate) -> dict[str, Any]:
    current = load_settings()
    updates = payload.model_dump(exclude_none=True)
    if "api_key" in updates and updates["api_key"] in {"", "configured"}:
        updates.pop("api_key")
    current.update(updates)
    saved = save_settings(current)
    return public_settings(saved)


@app.get("/api/projects")
def get_projects() -> list[dict[str, Any]]:
    return [_with_project_stats(project) for project in db.list_projects()]


@app.post("/api/projects")
def create_project(payload: ProjectCreate) -> dict[str, Any]:
    project = db.insert_project(payload.name, payload.type, payload.description, payload.icon)
    project_dir(project["id"])
    return _with_project_stats(project)


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    try:
        return _with_project_stats(db.get_project(project_id), include_details=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.patch("/api/projects/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate) -> dict[str, Any]:
    try:
        updates = payload.model_dump(exclude_none=True)
        return _with_project_stats(db.update_project(project_id, updates), include_details=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.post("/api/projects/{project_id}/analyze")
def analyze_project(project_id: str, payload: ProjectAnalysisRequest) -> dict[str, Any]:
    try:
        project = db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    notes = analyze_assets(payload.asset_artifact_ids, load_settings())
    profile_path, prompt_path, prompt = write_project_prompt(project, payload.intro, notes)
    artifacts = [
        db.add_artifact(project_id, "Project profile", profile_path, "project_profile", mime="application/json"),
        db.add_artifact(project_id, "Translation prompt", prompt_path, "translation_prompt", mime="text/plain"),
    ]
    return {"project": _with_project_stats(db.get_project(project_id), include_details=True), "artifacts": artifacts, "prompt": prompt}


@app.post("/api/projects/{project_id}/files")
def upload_project_file(project_id: str, file: UploadFile = File(...), kind: str = "upload") -> dict[str, Any]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    safe_name = _safe_filename(file.filename or "upload.bin")
    destination = _unique_path(project_dir(project_id) / "uploads" / safe_name)
    with destination.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    mime = file.content_type or mimetypes.guess_type(str(destination))[0] or "application/octet-stream"
    artifact = db.add_artifact(project_id, safe_name, destination, kind, mime=mime)
    return artifact


@app.get("/api/projects/{project_id}/glossary")
def list_project_glossary(project_id: str) -> list[dict[str, Any]]:
    return db.list_glossary_terms(project_id)


@app.post("/api/projects/{project_id}/glossary")
def create_glossary_term(project_id: str, payload: GlossaryTermPayload) -> dict[str, Any]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    return db.insert_glossary_term(project_id, payload.model_dump())


@app.patch("/api/projects/{project_id}/glossary/{term_id}")
def update_glossary_term(project_id: str, term_id: str, payload: GlossaryTermUpdate) -> dict[str, Any]:
    _require_project_term(project_id, term_id)
    return db.update_glossary_term(term_id, payload.model_dump(exclude_unset=True))


@app.delete("/api/projects/{project_id}/glossary/{term_id}")
def delete_glossary_term(project_id: str, term_id: str) -> dict[str, bool]:
    _require_project_term(project_id, term_id)
    db.delete_glossary_term(term_id)
    return {"deleted": True}


@app.post("/api/projects/{project_id}/glossary/extract")
def extract_project_glossary(project_id: str, payload: GlossaryExtractRequest) -> dict[str, Any]:
    try:
        return extract_glossary(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project or artifact not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/runs")
def create_run(payload: RunCreate) -> dict[str, Any]:
    try:
        db.get_project(payload.project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    active = [
        run
        for run in db.list_runs(payload.project_id)
        if run["kind"] == payload.kind and run["status"] in {"queued", "running"}
    ]
    if active:
        raise HTTPException(status_code=409, detail=f"{payload.kind} run already active for this project")
    metadata = {
        "input_artifact_id": payload.input_artifact_id,
        "term_artifact_id": payload.term_artifact_id,
        "batch_size": payload.batch_size,
    }
    return db.insert_run(payload.project_id, payload.kind, payload.language, metadata)


@app.get("/api/runs")
def list_runs(project_id: str | None = None) -> list[dict[str, Any]]:
    return db.list_runs(project_id)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    try:
        run = db.get_run(run_id)
        run["events"] = db.list_events(run_id)
        run["artifacts"] = db.list_artifacts(run_id=run_id)
        return run
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc


@app.post("/api/runs/{run_id}/translate")
def translate(run_id: str, payload: TranslateRequest) -> dict[str, Any]:
    try:
        return run_translate_sync(run_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run or artifact not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/runs/{run_id}/qa")
def qa(run_id: str) -> dict[str, Any]:
    run = db.get_run(run_id)
    return {"run": run, "message": "QA is executed as part of /api/runs/{run_id}/translate in v1."}


@app.get("/api/runs/{run_id}/events")
def get_events(run_id: str) -> list[dict[str, Any]]:
    return db.list_events(run_id)


@app.get("/api/artifacts/{artifact_id}/download")
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


def _safe_filename(name: str) -> str:
    cleaned = "".join(ch for ch in name if ch not in '<>:"/\\|?*').strip()
    return cleaned or "upload.bin"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 2
    while True:
        candidate = parent / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _require_project_term(project_id: str, term_id: str) -> dict[str, Any]:
    try:
        term = db.get_glossary_term(term_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="glossary term not found") from exc
    if term["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="glossary term not found")
    return term


def _with_project_stats(project: dict[str, Any], include_details: bool = False) -> dict[str, Any]:
    artifacts = db.list_artifacts(project_id=project["id"])
    runs = db.list_runs(project["id"])
    terms = db.list_glossary_terms(project["id"])
    passed_translation_runs = [run for run in runs if run["kind"] == "translation" and run["status"] == "passed"]
    project["stats"] = {
        "tasks": len(runs),
        "words": str(_translated_word_count(artifacts)),
        "langs": len({run["language"] for run in passed_translation_runs}),
        "glossary": len(terms),
    }
    if include_details:
        project["artifacts"] = artifacts
        project["runs"] = runs
        project["glossary"] = terms
    return project


def _translated_word_count(artifacts: list[dict[str, Any]]) -> int:
    total = 0
    for artifact in artifacts:
        if artifact["kind"] != "translation_response":
            continue
        path = Path(artifact["path"])
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                translation = str(json.loads(line).get("translation", ""))
            except json.JSONDecodeError:
                continue
            total += len([word for word in translation.split() if word])
    return total


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False, app_dir=str(Path(__file__).resolve().parents[1]))
