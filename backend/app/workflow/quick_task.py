from __future__ import annotations

# ruff: noqa: F403,F405

from .common import *

async def _translate_quick_text_run(
    *,
    run: dict[str, Any],
    input_artifact: dict[str, Any],
    settings: dict[str, Any],
    batch_size: int,
    language: str,
    readiness: dict[str, Any],
    request: Any,
    cancel_event: Any | None = None,
) -> dict[str, Any]:
    run_id = run["id"]
    project = db.get_project(run["project_id"])
    metadata = run.get("metadata", {})
    input_path = Path(input_artifact["path"])
    rows = _quick_text_translation_rows(input_path)
    if not rows:
        reason = "TXT 文件没有检测到可翻译文本。"
        db.update_run(run_id, status="needs_input", metadata={**metadata, "reason": reason, "translation_readiness": readiness})
        db.add_event(run_id, reason)
        return {"run": db.get_run(run_id), "artifacts": [], "quality": None, "translation_readiness": readiness}

    db.update_run(run_id, status="running")
    db.add_event(run_id, f"quick TXT translation preflight: source_lines={len(rows)}, batch_size={batch_size}, estimated_batches={readiness.get('estimated_batches') or '-'}")
    work_dir = run_dir(run_id) / "quick_text_translation"
    work_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = work_dir / "snapshots"
    glossary_snapshot = create_project_glossary_snapshot(project["id"], run_id, snapshot_dir, language=language)
    snapshots = create_prompt_and_harness_snapshots(project["id"], run_id, snapshot_dir, language=language)
    reference_snapshot = create_quick_reference_snapshot(project["id"], run_id, metadata.get("reference_artifact_ids"), snapshot_dir)
    prompt = snapshots["prompt"]
    prompt_snapshot = snapshots["prompt_artifact"]
    harness_snapshot_artifact = snapshots["harness_artifact"]
    if reference_snapshot and reference_snapshot.get("context"):
        prompt = _manage_project_prompt_context(f"{prompt}\n\nQuick Task References:\n{reference_snapshot['context']}", settings)
    prompt = _manage_project_prompt_context(
        f"{prompt}\n\n快速 TXT 任务：逐行翻译 source 字段，保持每个 id 的顺序和结构。只返回 JSONL，每行包含 id 和 translation。",
        settings,
    )

    workpack_path = work_dir / "quick_text_workpack.jsonl"
    write_jsonl(workpack_path, rows)
    workpack_artifact = db.add_artifact(project["id"], "快速 TXT workpack", workpack_path, "translation_workpack", run_id=run_id, mime="application/jsonl", metadata={"language": language, "source_artifact_id": input_artifact["id"]})
    translated_rows = await _translate_rows_with_orchestration(
        run_id=run_id,
        rows=rows,
        settings=settings,
        project_prompt=prompt,
        work_dir=work_dir,
        batch_size=batch_size,
        language=language,
        cancel_event=cancel_event,
        confirm_api_budget=bool(getattr(request, "confirm_api_budget", False)),
    )
    if not translated_rows and db.get_run(run_id).get("status") == "needs_input":
        return {"run": db.get_run(run_id), "artifacts": [workpack_artifact], "quality": None, "translation_readiness": readiness}

    response_path = work_dir / "translation_response.jsonl"
    write_jsonl(response_path, translated_rows)
    response_artifact = db.add_artifact(project["id"], "快速 TXT translation response", response_path, "translation_response", run_id=run_id, mime="application/jsonl", metadata={"language": language, "source_artifact_id": input_artifact["id"]})
    output_path = _write_quick_text_output(input_path, translated_rows, language, work_dir)
    final_artifact = db.add_artifact(project["id"], "快速 TXT 最终译文", output_path, "final_text", run_id=run_id, mime="text/plain", role="delivery", origin="generated", metadata={"language": language, "source_artifact_id": input_artifact["id"]})
    manifest_path = work_dir / "quick_text_translation_manifest.json"
    manifest = {
        "kind": "quick_text_translation",
        "run_id": run_id,
        "project_id": project["id"],
        "language": language,
        "source_artifact_id": input_artifact["id"],
        "source_rows": len(rows),
        "final_artifact_id": final_artifact["id"],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_artifact = db.add_artifact(project["id"], "快速 TXT translation manifest", manifest_path, "translation_manifest", run_id=run_id, mime="application/json", metadata={"language": language})
    input_artifacts = {
        "source_text": input_artifact["id"],
        "final_text": final_artifact["id"],
        "translation_workpack": workpack_artifact["id"],
        "translation_response": response_artifact["id"],
        "prompt_snapshot": prompt_snapshot["id"],
        "harness_snapshot": harness_snapshot_artifact["id"],
        "glossary_snapshot": glossary_snapshot["id"],
    }
    if reference_snapshot:
        input_artifacts["quick_reference_snapshot"] = reference_snapshot["artifact"]["id"]
    quality_summary = {"passed": True, "hard_errors": 0, "soft_warnings": 0, "rows": len(rows), "format": input_path.suffix.lower().lstrip(".") or "txt"}
    final_metadata = db.get_run(run_id).get("metadata", {})
    db.update_run(
        run_id,
        status="passed",
        metadata={
            **final_metadata,
            "task_origin": metadata.get("task_origin") or "quick_task",
            "input_artifacts": input_artifacts,
            "quality_summary": quality_summary,
            "quality": {"passed": True, "issues": []},
            "translation_readiness": readiness,
            "translated_rows": len(rows),
            "source_rows": len(rows),
            "output_format": input_path.suffix.lower().lstrip(".") or "txt",
        },
    )
    db.add_event(run_id, f"quick TXT translation finished: rows={len(rows)}, output={output_path.name}")
    return {
        "run": db.get_run(run_id),
        "artifacts": [final_artifact, response_artifact, workpack_artifact, manifest_artifact, glossary_snapshot, prompt_snapshot, harness_snapshot_artifact],
        "quality": {"passed": True, "issues": []},
        "translation_readiness": readiness,
    }

__all__ = [name for name in globals() if not name.startswith("__")]
