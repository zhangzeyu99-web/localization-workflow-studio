from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import db
from .config import DATA_ROOT, GLOSSARY_ROOT, LOCALIZATION_ROOT, load_settings
from .providers import translate_batch


def project_dir(project_id: str) -> Path:
    path = DATA_ROOT / "projects" / project_id
    path.mkdir(parents=True, exist_ok=True)
    for child in ("uploads", "profile", "glossary", "runs", "assets"):
        (path / child).mkdir(exist_ok=True)
    return path


def run_dir(run_id: str) -> Path:
    path = DATA_ROOT / "runs" / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_project_prompt(project: dict[str, Any], intro: str, asset_notes: list[str]) -> tuple[Path, Path, str]:
    root = project_dir(project["id"]) / "profile"
    profile = {
        "project_name": project["name"],
        "project_type": project.get("type", ""),
        "description": project.get("description", ""),
        "intro": intro,
        "asset_notes": asset_notes,
        "target_language": "en",
        "style": "Use concise, natural, production-readable game localization. Preserve variables, tags, numbers, and line breaks.",
    }
    prompt = (
        f"Project: {project['name']}\n"
        f"Type: {project.get('type', '')}\n"
        f"Description: {project.get('description', '')}\n"
        f"Intro: {intro}\n"
        "Rules: translate into natural English for game UI and narrative. "
        "Keep placeholders, variables, rich-text tags, numbers, and line breaks unchanged. "
        "Use project glossary terms when provided. Return only id + translation JSONL."
    )
    if asset_notes:
        prompt += "\nAssets: " + "; ".join(asset_notes)
    profile_path = root / "project_profile.json"
    prompt_path = root / "translation_prompt.txt"
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    prompt_path.write_text(prompt, encoding="utf-8")
    db.update_project(project["id"], {"profile": profile, "prompt_text": prompt})
    return profile_path, prompt_path, prompt


def analyze_assets(artifact_ids: list[str], settings: dict[str, Any]) -> list[str]:
    support = settings.get("multimodal", {})
    notes: list[str] = []
    for artifact_id in artifact_ids:
        artifact = db.get_artifact(artifact_id)
        suffix = Path(artifact["path"]).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            state = "analyzed" if support.get("images") else "archived_only:image_not_supported"
        elif suffix == ".pdf":
            state = "analyzed_text_first" if support.get("pdf") else "archived_only:pdf_not_supported"
        elif suffix in {".mp4", ".mov", ".mkv"}:
            state = "analyzed" if support.get("video") else "archived_only:video_not_supported"
        elif suffix in {".mp3", ".wav", ".m4a"}:
            state = "analyzed" if support.get("audio") else "archived_only:audio_not_supported"
        else:
            state = "archived_only:unknown_type"
        notes.append(f"{artifact['label']}={state}")
    return notes


def copy_upload(project_id: str, source_path: Path, label: str, kind: str) -> dict[str, Any]:
    destination_dir = project_dir(project_id) / "uploads"
    destination = destination_dir / source_path.name
    shutil.copy2(source_path, destination)
    return db.add_artifact(project_id, label=label, path=destination, kind=kind)


def run_subprocess(args: list[str], cwd: Path, run_id: str) -> subprocess.CompletedProcess[str]:
    db.add_event(run_id, "running: " + " ".join(args))
    proc = subprocess.run(
        args,
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if proc.stdout:
        db.add_event(run_id, proc.stdout.strip())
    if proc.stderr:
        db.add_event(run_id, proc.stderr.strip(), level="warn")
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(args)}\n{proc.stderr or proc.stdout}")
    return proc


def parse_key_output(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in text.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def extract_glossary(project_id: str, request: Any) -> dict[str, Any]:
    project = db.get_project(project_id)
    artifact = db.get_artifact(request.input_artifact_id)
    run = db.insert_run(project_id, kind="glossary", language="en", metadata={"input_artifact_id": request.input_artifact_id})
    db.update_run(run["id"], status="running")
    output_dir = run_dir(run["id"]) / "glossary"
    output_dir.mkdir(parents=True, exist_ok=True)
    input_path = Path(artifact["path"])
    detail_output = output_dir / f"{input_path.stem}_glossary_details.xlsx"
    final_output = output_dir / f"{input_path.stem}_ID_CN_EN_EN2.xlsx"
    brief_output = output_dir / "project_brief.md"
    prompt_output = output_dir / "translation_prompt.txt"
    args = [
        sys.executable,
        str(GLOSSARY_ROOT / "scripts" / "extract_glossary.py"),
        str(input_path),
        "--id-column",
        request.id_column,
        "--source-column",
        request.source_column,
        "--target-column",
        request.target_column,
        "--output",
        str(detail_output),
        "--final-output",
        str(final_output),
        "--project-name",
        request.project_name or project["name"],
        "--project-brief-output",
        str(brief_output),
        "--translation-prompt-output",
        str(prompt_output),
        "--curated-rules",
        str(project_dir(project_id) / "glossary" / "curated_terms.json"),
        "--observations-store",
        str(project_dir(project_id) / "glossary" / "observed_terms.json"),
    ]
    if request.sheet:
        args.extend(["--sheet", request.sheet])
    if request.source_only:
        args.append("--source-only")
    if request.include_empty_final_terms:
        args.append("--include-empty-final-terms")
    try:
        proc = run_subprocess(args, GLOSSARY_ROOT, run["id"])
        parsed = parse_key_output(proc.stdout)
        artifacts = [
            db.add_artifact(project_id, "Glossary details", detail_output, "glossary_detail", run_id=run["id"]),
            db.add_artifact(project_id, "ID CN EN EN2 glossary", final_output, "glossary_final", run_id=run["id"]),
            db.add_artifact(project_id, "Project brief", brief_output, "project_brief", run_id=run["id"], mime="text/markdown"),
            db.add_artifact(project_id, "Translation prompt", prompt_output, "translation_prompt", run_id=run["id"], mime="text/plain"),
        ]
        if prompt_output.exists():
            prompt = prompt_output.read_text(encoding="utf-8")
            db.update_project(project_id, {"prompt_text": prompt})
        db.update_run(run["id"], status="passed", metadata={"output": parsed})
        return {"run": db.get_run(run["id"]), "artifacts": artifacts, "output": parsed}
    except Exception as exc:
        db.add_event(run["id"], str(exc), level="error")
        db.update_run(run["id"], status="failed", metadata={"error": str(exc)})
        raise


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


async def translate_run(run_id: str, request: Any) -> dict[str, Any]:
    run = db.get_run(run_id)
    if run["language"] != "en":
        db.update_run(run_id, status="needs_input", metadata={**run.get("metadata", {}), "reason": "v1 supports EN translation only"})
        return {"run": db.get_run(run_id), "artifacts": []}
    project = db.get_project(run["project_id"])
    metadata = run.get("metadata", {})
    input_artifact = db.get_artifact(metadata["input_artifact_id"])
    term_artifact = db.get_artifact(metadata["term_artifact_id"]) if metadata.get("term_artifact_id") else None
    settings = load_settings()
    if request.provider:
        settings["provider"] = request.provider
    if request.protocol:
        settings["protocol"] = request.protocol
    batch_size = int(request.batch_size or metadata.get("batch_size") or settings.get("batch_size") or 90)
    batch_size = max(1, min(batch_size, 200))

    db.update_run(run_id, status="running")
    work_dir = run_dir(run_id) / "translation"
    work_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = project_dir(project["id"]) / "profile" / "translation_prompt.txt"
    if not prompt_path.exists():
        write_project_prompt(project, project.get("description", ""), [])
    prompt = prompt_path.read_text(encoding="utf-8")

    prepare_args = [
        sys.executable,
        str(LOCALIZATION_ROOT / "scripts" / "run_translation_harness.py"),
        "--input",
        input_artifact["path"],
        "--lang",
        "en",
        "--output-dir",
        str(work_dir),
        "--style-hint-file",
        str(prompt_path),
    ]
    if term_artifact:
        prepare_args.extend(["--term-base", term_artifact["path"]])
    try:
        run_subprocess(prepare_args, LOCALIZATION_ROOT, run_id)
        workpack_path = work_dir / "translation_workpack.jsonl"
        rows = read_jsonl(workpack_path)
        translated_rows: list[dict[str, Any]] = []
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            db.add_event(run_id, f"translating batch {start // batch_size + 1}: rows={len(batch)}")
            items = await translate_batch(batch, settings, prompt, provider_override=request.provider, protocol_override=request.protocol)
            translated_rows.extend([{"id": item.id, "translation": item.translation} for item in items])
        response_path = work_dir / "translation_response.jsonl"
        write_jsonl(response_path, translated_rows)
        db.add_artifact(project["id"], "Translation response JSONL", response_path, "translation_response", run_id=run_id, mime="application/jsonl")

        apply_args = [
            sys.executable,
            str(LOCALIZATION_ROOT / "scripts" / "run_translation_harness.py"),
            "--input",
            input_artifact["path"],
            "--lang",
            "en",
            "--output-dir",
            str(work_dir),
            "--response",
            str(response_path),
            "--run-qa",
        ]
        if term_artifact:
            apply_args.extend(["--term-base", term_artifact["path"]])
        apply_proc = run_subprocess(apply_args, LOCALIZATION_ROOT, run_id)
        parsed = parse_key_output(apply_proc.stdout)
        final_workbook = Path(parsed.get("final_workbook", ""))
        qa_report = Path(parsed.get("qa_report", ""))
        qa_result = Path(parsed.get("qa_result", ""))

        quality_args = [
            sys.executable,
            str(LOCALIZATION_ROOT / "scripts" / "run_quality_harness.py"),
            str(LOCALIZATION_ROOT / "fixtures" / "quality_regression.json"),
            "--workbook",
            str(final_workbook),
            "--json",
        ]
        quality_proc = run_subprocess(quality_args, LOCALIZATION_ROOT, run_id)
        quality = json.loads(quality_proc.stdout)
        status = "passed" if quality.get("passed") else "failed"
        artifacts = [
            db.add_artifact(project["id"], "Final workbook", final_workbook, "final_workbook", run_id=run_id),
            db.add_artifact(project["id"], "QA report", qa_report, "qa_report", run_id=run_id),
            db.add_artifact(project["id"], "QA result", qa_result, "qa_result", run_id=run_id),
            db.add_artifact(project["id"], "Translation manifest", work_dir / "translation_manifest.json", "translation_manifest", run_id=run_id, mime="application/json"),
        ]
        db.update_run(run_id, status=status, metadata={**metadata, "quality": quality, "batch_size": batch_size})
        return {"run": db.get_run(run_id), "artifacts": artifacts, "quality": quality}
    except Exception as exc:
        db.add_event(run_id, str(exc), level="error")
        db.update_run(run_id, status="failed", metadata={**metadata, "error": str(exc)})
        raise


def run_translate_sync(run_id: str, request: Any) -> dict[str, Any]:
    return asyncio.run(translate_run(run_id, request))

