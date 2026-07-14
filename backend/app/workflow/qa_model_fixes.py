from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .. import db
from ..config import REAL_PROVIDERS, load_settings, normalize_provider_name
from .common import run_dir
from .qa import (
    _append_improvement_items,
    _apply_workbook_fixes,
    _improvement_item,
    _model_fix_prompt,
    _model_fix_row_context,
    _normalize_model_fixes,
    _workbook_artifact_for_quality_run,
    list_quality_issues,
    run_qa_sync,
)
from .semantic_qa import _call_semantic_provider, _parse_semantic_qa_payload
from .translation_tasks import translation_task_continuation_metadata


def model_fix_provider_settings() -> tuple[dict[str, Any], str]:
    settings = load_settings()
    provider = normalize_provider_name(settings.get("provider"))
    if provider not in REAL_PROVIDERS or not settings.get("api_key"):
        raise ValueError("模型修复需要配置 GPT / Claude / GPT 中转站 API key，不能在未配置真实 API 时生成可交付修复。")
    return settings, provider


def apply_model_fixes(run_id: str, request: Any, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply AI model fixes for a run's QA issues.

    ``settings`` lets the background job entry point (``routers/qa.py``'s
    ``model_fixes_start`` worker) load once at task start and pass the same
    snapshot through to the optional QA rerun below, instead of each step
    reloading settings from disk mid-task. The direct sync endpoint
    (``/api/runs/{id}/model-fixes``) omits it and gets one fresh load here.
    """
    run = db.get_run(run_id)
    project = db.get_project(run["project_id"])
    if settings is not None:
        provider = normalize_provider_name(settings.get("provider"))
        if provider not in REAL_PROVIDERS or not settings.get("api_key"):
            raise ValueError("模型修复需要配置 GPT / Claude / GPT 中转站 API key，不能在未配置真实 API 时生成可交付修复。")
    else:
        settings, provider = model_fix_provider_settings()

    max_issues = max(1, min(int(getattr(request, "max_issues", 80) or 80), 200))
    issue_payload = list_quality_issues(run_id)
    issues = [
        issue
        for issue in issue_payload.get("issues", [])
        if issue.get("sheet") and int(issue.get("row") or 0) > 1 and issue.get("severity") in {"hard", "soft"}
    ][:max_issues]
    if not issues:
        raise ValueError("没有可交给模型修复的行级 QA 问题。")

    source_artifact = _workbook_artifact_for_quality_run(run)
    source_path = Path(source_artifact["path"])
    if not source_path.exists():
        raise FileNotFoundError(str(source_path))
    rows = [_model_fix_row_context(source_path, issue) for issue in issues]
    prompt = _model_fix_prompt(project, run, rows, settings)
    text = _call_semantic_provider(settings, prompt)
    payload = _parse_semantic_qa_payload(text)
    fixes = _normalize_model_fixes(payload, rows)
    if not fixes:
        raise ValueError("模型没有返回可应用的修复。")

    output_dir = run_dir(run_id) / "model_fixes"
    output_dir.mkdir(parents=True, exist_ok=True)
    fixed_path = output_dir / f"{source_path.stem}_model_fixed.xlsx"
    shutil.copy2(source_path, fixed_path)
    applied = _apply_workbook_fixes(fixed_path, fixes, run_id)
    fixed_artifact = db.add_artifact(
        project["id"],
        "Model fixed workbook",
        fixed_path,
        "manual_fixed_workbook",
        run_id=run_id,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        origin="provider",
        metadata={
            "source_run_id": run_id,
            "source_artifact_id": source_artifact["id"],
            "model_fix_count": len(applied),
            "provider": provider,
            "model": settings.get("model") or "",
        },
    )
    _append_improvement_items(
        project["id"],
        [
            _improvement_item(
                "project_harness",
                run_id,
                "Review model fixes for reusable project rules",
                "Model QA fixes were applied; review whether repeated fixes should become project terms, fixed names, or project-specific rules.",
            )
        ],
    )

    result: dict[str, Any] = {
        "source_run": run,
        "fixed_artifact": fixed_artifact,
        "model_fixes": applied,
        "qa_result": None,
    }
    if getattr(request, "rerun_qa", True):
        qa_run = db.insert_run(
            project["id"],
            kind="qa",
            language=run.get("language", "en"),
            metadata={
                "input_artifact_id": fixed_artifact["id"],
                "model_fix_source_run_id": run_id,
                "model_fix_source_artifact_id": source_artifact["id"],
                "model_fix_count": len(applied),
                "manual_fixes": applied,
                "task_origin": "model_fix_continuation",
                "task_code": (run.get("metadata") or {}).get("task_code"),
                **translation_task_continuation_metadata(run),
            },
        )
        result["qa_result"] = run_qa_sync(qa_run["id"], settings=settings)
    return result
