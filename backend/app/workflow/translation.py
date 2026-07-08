from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from .. import db
from ..config import LOCALIZATION_ROOT, REAL_PROVIDERS, TEST_FAKE_PROVIDER, load_settings, normalize_provider_name, test_provider_enabled
from ..jobs import lease_name_for_project
from ..languages import require_supported_language
from ..translation_batches import (
    load_or_create_batch_manifest as _load_or_create_batch_manifest,
    manage_project_prompt_context as _manage_project_prompt_context,
    project_context_summary as _project_context_summary,
)
from .announcement_shared import ANNOUNCEMENT_STEP
from .announcement_segments import _is_quick_text_path
from .common import run_dir
from .asset_import_export import archive_translation_artifact
from .jsonl_helpers import read_jsonl, write_jsonl
from .large_text import (
    build_large_text_preflight,
    build_translation_cache_rows,
    cache_lint_rows,
    normalize_large_text_mode,
    render_large_text_retro,
)
from .translation_orchestrator import (
    _terminal_translation_progress,
    _translate_rows_with_orchestration,
    _translation_cancel_path,
)
from .prompt_snapshots import (
    create_project_glossary_snapshot,
    create_prompt_and_harness_snapshots,
    create_quick_reference_snapshot,
)
from .qa import run_localization_qa
from .subprocess_runner import (
    UserFacingWorkflowError,
    _friendly_unsupported_language_file_message,
    parse_key_output,
    run_subprocess,
    user_facing_error,
)
from .translation_readiness import inspect_translation_readiness

def _translation_preflight_blocker(
    *,
    run_id: str,
    metadata: dict[str, Any],
    input_artifact: dict[str, Any],
    settings: dict[str, Any],
    readiness: dict[str, Any],
    language: str,
) -> dict[str, Any] | None:
    input_path = Path(input_artifact["path"])
    if _is_quick_text_path(input_path) and metadata.get("task_origin") != "quick_task":
        reason = _friendly_unsupported_language_file_message(input_path.suffix)
        db.merge_run_metadata(run_id, {"reason": reason, "translation_readiness": readiness})
        db.update_run(run_id, status="needs_input")
        db.add_event(run_id, reason)
        return {"run": db.get_run(run_id), "artifacts": [], "quality": None, "translation_readiness": readiness}
    if readiness.get("reason") == "unsupported_file":
        reason = _friendly_unsupported_language_file_message(input_path.suffix)
        db.merge_run_metadata(run_id, {"reason": reason, "translation_readiness": readiness})
        db.update_run(run_id, status="needs_input")
        db.add_event(run_id, reason)
        return {"run": db.get_run(run_id), "artifacts": [], "quality": None, "translation_readiness": readiness}
    if readiness.get("reason") == "invalid_id_rows":
        reason = "language table ID column must be present and non-empty before translation or QA"
        db.merge_run_metadata(run_id, {"reason": reason, "translation_readiness": readiness})
        db.update_run(run_id, status="needs_input")
        db.add_event(run_id, f"translation skipped: {reason}")
        return {"run": db.get_run(run_id), "artifacts": [], "quality": None, "translation_readiness": readiness}
    if readiness.get("ready_for_qa"):
        db.merge_run_metadata(
            run_id,
            {"reason": "input already contains target translations; run QA instead", "translation_readiness": readiness},
        )
        db.update_run(run_id, status="needs_input")
        db.add_event(run_id, "translation skipped: input already contains target translations; run QA instead")
        return {"run": db.get_run(run_id), "artifacts": [], "quality": None, "translation_readiness": readiness}
    effective_provider = normalize_provider_name(settings.get("provider"))
    if effective_provider in REAL_PROVIDERS and not settings.get("api_key"):
        db.merge_run_metadata(run_id, {"reason": f"{effective_provider} api_key is required for formal translation"})
        db.update_run(run_id, status="needs_input")
        return {"run": db.get_run(run_id), "artifacts": [], "quality": None}
    return None


def _translation_settings_and_batch_size(request: Any, metadata: dict[str, Any]) -> tuple[dict[str, Any], int]:
    settings = load_settings()
    if request.provider:
        settings["provider"] = normalize_provider_name(request.provider)
    if request.protocol:
        settings["protocol"] = request.protocol
    if getattr(request, "preset", None):
        settings["preset"] = request.preset
    batch_size = int(request.batch_size or metadata.get("batch_size") or settings.get("batch_size") or 90)
    return settings, max(1, min(batch_size, 200))


def _create_translation_run_snapshots(
    *,
    project: dict[str, Any],
    run_id: str,
    metadata: dict[str, Any],
    language: str,
    snapshot_dir: Path,
    settings: dict[str, Any],
) -> dict[str, Any]:
    glossary_snapshot = create_project_glossary_snapshot(
        project["id"],
        run_id,
        snapshot_dir,
        language=language,
        extra_term_artifact_id=metadata.get("term_artifact_id"),
    )
    snapshots = create_prompt_and_harness_snapshots(project["id"], run_id, snapshot_dir, language=language)
    reference_snapshot = create_quick_reference_snapshot(project["id"], run_id, metadata.get("reference_artifact_ids"), snapshot_dir)
    prompt = snapshots["prompt"]
    prompt_snapshot = snapshots["prompt_artifact"]
    prompt_path = snapshots["prompt_path"]
    if reference_snapshot and reference_snapshot.get("context"):
        raw_prompt = f"{prompt}\n\nQuick Task References:\n{reference_snapshot['context']}"
        prompt = _manage_project_prompt_context(raw_prompt, settings)
        prompt_path = snapshot_dir / "compiled_project_harness_prompt_with_quick_refs.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        prompt_snapshot = db.add_artifact(
            project["id"],
            "Prompt snapshot with quick references",
            prompt_path,
            "prompt_snapshot",
            run_id=run_id,
            mime="text/plain",
            origin="generated",
            metadata={
                "source": "project_prompt_harness_and_quick_references",
                "language": language,
                "reference_artifact_ids": metadata.get("reference_artifact_ids") or [],
                "context_budget": _project_context_summary(raw_prompt, settings),
            },
        )
    return {
        "glossary_snapshot": glossary_snapshot,
        "prompt": prompt,
        "prompt_snapshot": prompt_snapshot,
        "harness_snapshot_artifact": snapshots["harness_artifact"],
        "harness_snapshot": snapshots["harness_snapshot"],
        "prompt_path": prompt_path,
        "reference_snapshot": reference_snapshot,
    }


def _translation_term_audit(project_id: str, language: str, glossary_snapshot: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    metadata = glossary_snapshot.get("metadata") or {}
    term_hit_rows = 0
    term_hits = 0
    for row in rows:
        hits = row.get("term_hits") or []
        if hits:
            term_hit_rows += 1
            term_hits += len(hits) if isinstance(hits, list) else 0
    pending_candidates = db.list_glossary_candidates(project_id, status="pending", language=language)
    ready_candidates = [item for item in pending_candidates if str(item.get("target") or "").strip()]
    term_count = int(metadata.get("term_count") or 0)
    extra_selected = bool(metadata.get("extra_term_artifact_selected"))
    extra_term_count = int(metadata.get("extra_term_count") or 0)
    extra_term_rows_read = int(metadata.get("extra_term_rows_read") or 0)
    project_term_count = int(metadata.get("project_term_count") or metadata.get("term_count") or 0)
    warning = ""
    if extra_selected and extra_term_rows_read == 0 and project_term_count == 0:
        warning = "selected_term_artifact_empty"
    elif len(ready_candidates) > 0 and term_count == 0:
        warning = "glossary_candidates_not_confirmed"
    elif term_count > 0 and term_hit_rows == 0:
        warning = "no_term_hits"
    return {
        "language": language,
        "term_count": term_count,
        "project_term_count": project_term_count,
        "extra_term_count": extra_term_count,
        "extra_term_rows_read": extra_term_rows_read,
        "extra_term_artifact_id": str(metadata.get("extra_term_artifact_id") or ""),
        "extra_term_artifact_selected": extra_selected,
        "extra_term_error": str(metadata.get("extra_term_error") or ""),
        "term_hit_rows": term_hit_rows,
        "term_hits": term_hits,
        "total_rows": len(rows),
        "pending_candidate_count": len(pending_candidates),
        "ready_candidate_count": len(ready_candidates),
        "needs_confirmation": warning in {"glossary_candidates_not_confirmed", "selected_term_artifact_empty"},
        "warning": warning,
    }


def _pause_for_unconfirmed_terms(run_id: str, metadata: dict[str, Any], term_audit: dict[str, Any], request: Any) -> dict[str, Any] | None:
    if term_audit.get("warning") == "selected_term_artifact_empty":
        reason = "已选择本次术语表，但没有读取到可用术语；请检查术语表格式和目标语言列，或返回 STEP 5 重新生成/确认术语。"
        db.merge_run_metadata(run_id, {"reason": "selected_term_artifact_empty", "user_message": reason, "term_audit": term_audit})
        db.update_run(run_id, status="needs_input")
        db.add_event(run_id, reason, level="warning")
        return {"run": db.get_run(run_id), "artifacts": [], "quality": None}
    if not term_audit.get("needs_confirmation") or bool(getattr(request, "confirm_term_gap", False)):
        return None
    reason = "已扫描到候选术语，但还没有确认加入项目术语库；本次翻译不会使用这些候选术语。请先在 STEP 5 确认术语，或明确选择继续无术语翻译。"
    db.merge_run_metadata(run_id, {"reason": "glossary_candidates_not_confirmed", "user_message": reason, "term_audit": term_audit})
    db.update_run(run_id, status="needs_input")
    db.add_event(run_id, reason, level="warning")
    return {"run": db.get_run(run_id), "artifacts": [], "quality": None}


async def translate_run(run_id: str, request: Any, cancel_event: Any | None = None) -> dict[str, Any]:
    run = db.get_run(run_id)
    language = require_supported_language(run.get("language") or "en")
    project = db.get_project(run["project_id"])
    metadata = run.get("metadata", {})
    input_artifact = db.get_artifact(metadata["input_artifact_id"])
    if request.provider and str(request.provider).strip() == TEST_FAKE_PROVIDER and not test_provider_enabled():
        reason = "测试 provider 未启用；正式任务请使用已配置的 GPT / Claude API。"
        db.merge_run_metadata(run_id, {"reason": reason})
        db.update_run(run_id, status="needs_input")
        db.add_event(run_id, reason)
        return {"run": db.get_run(run_id), "artifacts": [], "quality": None}
    settings, batch_size = _translation_settings_and_batch_size(request, metadata)
    readiness = inspect_translation_readiness(input_artifact["id"], batch_size=batch_size, language=language)
    preflight_blocker = _translation_preflight_blocker(
        run_id=run_id,
        metadata=metadata,
        input_artifact=input_artifact,
        settings=settings,
        readiness=readiness,
        language=language,
    )
    if preflight_blocker is not None:
        return preflight_blocker
    if metadata.get("task_origin") == "quick_task" and _is_quick_text_path(Path(input_artifact["path"])):
        from .quick_task import _translate_quick_text_run

        return await _translate_quick_text_run(
            run=run,
            input_artifact=input_artifact,
            settings=settings,
            batch_size=batch_size,
            language=language,
            readiness=readiness,
            request=request,
            cancel_event=cancel_event,
        )

    db.update_run(run_id, status="running")
    db.add_event(
        run_id,
        f"translation preflight: source_rows={readiness['source_rows']}, translated_rows={readiness['translated_rows']}, "
        f"empty_target_rows={readiness['empty_target_rows']}, cjk_target_rows={readiness['cjk_target_rows']}, "
        f"batch_size={batch_size}, estimated_batches={readiness['estimated_batches']}",
    )
    work_dir = run_dir(run_id) / "translation"
    work_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = work_dir / "snapshots"
    snapshot_data = _create_translation_run_snapshots(
        project=project,
        run_id=run_id,
        metadata=metadata,
        language=language,
        snapshot_dir=snapshot_dir,
        settings=settings,
    )
    glossary_snapshot = snapshot_data["glossary_snapshot"]
    prompt = snapshot_data["prompt"]
    prompt_snapshot = snapshot_data["prompt_snapshot"]
    harness_snapshot_artifact = snapshot_data["harness_snapshot_artifact"]
    harness_snapshot = snapshot_data["harness_snapshot"]
    prompt_path = snapshot_data["prompt_path"]
    reference_snapshot = snapshot_data["reference_snapshot"]

    prepare_args = [
        sys.executable,
        str(LOCALIZATION_ROOT / "scripts" / "run_translation_harness.py"),
        "--input",
        input_artifact["path"],
        "--lang",
        language,
        "--output-dir",
        str(work_dir),
        "--style-hint-file",
        str(prompt_path),
        "--term-base",
        glossary_snapshot["path"],
    ]
    try:
        db.add_event(run_id, "preparing translation workpack with localization workflow")
        run_subprocess(prepare_args, LOCALIZATION_ROOT, run_id)
        workpack_path = work_dir / "translation_workpack.jsonl"
        rows = read_jsonl(workpack_path)
        large_text_mode = normalize_large_text_mode(getattr(request, "large_text_mode", None) or metadata.get("large_text_mode"))
        large_text_preflight = build_large_text_preflight(
            rows,
            target_languages=[language],
            source_rows=int(readiness.get("source_rows") or len(rows)),
            workbook_count=1,
            full_proofread=False,
        )
        preflight_path = work_dir / "large_text_preflight.json"
        preflight_path.write_text(json.dumps(large_text_preflight, ensure_ascii=False, indent=2), encoding="utf-8")
        preflight_artifact = db.add_artifact(
            project["id"],
            "Large text preflight",
            preflight_path,
            "large_text_preflight",
            run_id=run_id,
            mime="application/json",
            origin="generated",
            metadata={"mode": large_text_mode, "large_pack": large_text_preflight["large_pack"]},
        )
        db.merge_run_metadata(
            run_id,
            {
                "large_text": {
                    "mode": large_text_mode,
                    "preflight": large_text_preflight,
                    "preflight_artifact_id": preflight_artifact["id"],
                },
            },
        )
        term_audit = _translation_term_audit(project["id"], language, glossary_snapshot, rows)
        db.merge_run_metadata(run_id, {"term_audit": term_audit})
        paused = _pause_for_unconfirmed_terms(run_id, db.get_run(run_id).get("metadata", {}), term_audit, request)
        if paused is not None:
            return paused
        manifest_preview = _load_or_create_batch_manifest(work_dir / "batch_manifest.json", rows, prompt, settings, batch_size, language)
        db.add_event(run_id, f"workpack prepared: rows={len(rows)}, dynamic_batches={len(manifest_preview.get('batches') or [])}, concurrency={settings.get('max_concurrent_batches')}")
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
            term_audit=term_audit,
        )
        if not translated_rows and db.get_run(run_id).get("status") == "needs_input":
            return {"run": db.get_run(run_id), "artifacts": [], "quality": None, "translation_readiness": readiness}
        response_path = work_dir / "translation_response.jsonl"
        write_jsonl(response_path, translated_rows)
        db.add_artifact(project["id"], "Translation response JSONL", response_path, "translation_response", run_id=run_id, mime="application/jsonl")

        cache_rows = build_translation_cache_rows(rows, translated_rows, language)
        cache_lint = cache_lint_rows(cache_rows, target_languages=[language])
        cache_lint_path = work_dir / "large_text_cache_lint.json"
        cache_lint_path.write_text(json.dumps(cache_lint, ensure_ascii=False, indent=2), encoding="utf-8")
        cache_artifact = db.add_artifact(
            project["id"],
            "Large text cache lint",
            cache_lint_path,
            "large_text_cache_lint",
            run_id=run_id,
            mime="application/json",
            origin="generated",
            metadata={"hard_blockers": cache_lint["hard_blockers"], "ok_to_apply": cache_lint["ok_to_apply"]},
        )
        should_enforce_cache_lint = large_text_mode == "strict" or (large_text_mode == "auto" and bool(large_text_preflight.get("large_pack")))
        large_text_state = {
            "mode": large_text_mode,
            "preflight": large_text_preflight,
            "preflight_artifact_id": preflight_artifact["id"],
            "cache_lint": {
                "status": "passed" if cache_lint["ok_to_apply"] else "failed",
                "hard_blockers": cache_lint["hard_blockers"],
                "artifact_id": cache_artifact["id"],
            },
        }
        if large_text_mode == "off":
            large_text_state["cache_lint"] = {"status": "skipped", "reason": "large_text_mode_off", "hard_blockers": cache_lint["hard_blockers"], "artifact_id": cache_artifact["id"]}
        elif not should_enforce_cache_lint:
            large_text_state["cache_lint"]["status"] = "skipped"
            large_text_state["cache_lint"]["reason"] = "not_large_pack"
        if should_enforce_cache_lint and not cache_lint["ok_to_apply"]:
            db.merge_run_metadata(run_id, {"large_text": large_text_state, "error": "大文本门禁未通过，未写入最终 workbook。"})
            db.update_run(run_id, status="failed")
            db.add_event(run_id, f"large text cache lint failed: hard_blockers={cache_lint['hard_blockers']}", level="error")
            return {
                "run": db.get_run(run_id),
                "artifacts": [preflight_artifact, cache_artifact],
                "quality": None,
                "quality_summary": {"passed": False, "hard_errors": cache_lint["hard_blockers"]},
            }
        db.merge_run_metadata(run_id, {"large_text": large_text_state})

        db.add_event(run_id, "applying translation response and running strict harness validation")
        apply_args = [
            sys.executable,
            str(LOCALIZATION_ROOT / "scripts" / "run_translation_harness.py"),
            "--input",
            input_artifact["path"],
            "--lang",
            language,
            "--output-dir",
            str(work_dir),
            "--response",
            str(response_path),
            "--term-base",
            glossary_snapshot["path"],
        ]
        apply_proc = run_subprocess(apply_args, LOCALIZATION_ROOT, run_id)
        parsed = parse_key_output(apply_proc.stdout)
        raw_workbook = Path(parsed.get("final_workbook", ""))
        raw_artifact = db.add_artifact(
            project["id"],
            "Raw translated workbook",
            raw_workbook,
            "raw_translated_workbook",
            run_id=run_id,
            origin="generated",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            metadata={"language": language, "source_workbook": input_artifact["id"]},
        )
        db.add_event(run_id, "running localization QA gate after translation")
        qa_result = run_localization_qa(
            project=project,
            run_id=run_id,
            workbook_path=raw_workbook,
            output_dir=work_dir / "qa",
            glossary_snapshot=glossary_snapshot,
            harness_snapshot=harness_snapshot,
            workbook_artifact=raw_artifact,
            run_metadata=metadata,
            language=language,
        )
        status = "passed" if qa_result["quality_summary"]["passed"] else "failed"
        artifacts = [
            raw_artifact,
            db.add_artifact(project["id"], "Translation manifest", work_dir / "translation_manifest.json", "translation_manifest", run_id=run_id, mime="application/json"),
            glossary_snapshot,
            prompt_snapshot,
            harness_snapshot_artifact,
            preflight_artifact,
            cache_artifact,
            *qa_result["artifacts"],
        ]
        input_artifacts = {
            "source_workbook": input_artifact["id"],
            "raw_translated_workbook": raw_artifact["id"],
            "translation_workbook": raw_artifact["id"],
            "glossary_snapshot": glossary_snapshot["id"],
            "prompt_snapshot": prompt_snapshot["id"],
            "harness_snapshot": harness_snapshot_artifact["id"],
        }
        if reference_snapshot:
            input_artifacts["quick_reference_snapshot"] = reference_snapshot["artifact"]["id"]
        if qa_result.get("qa_final_artifact"):
            input_artifacts["qa_final_workbook"] = qa_result["qa_final_artifact"]["id"]
            input_artifacts["translation_workbook"] = qa_result["qa_final_artifact"]["id"]
        archive_result = None
        if status == "passed" and qa_result.get("qa_final_artifact"):
            archive_result = archive_translation_artifact(
                project["id"],
                qa_result["qa_final_artifact"]["id"],
                language=run.get("language") or "en",
                source_type="qa_passed",
            )
            db.add_event(run_id, f"translation archive updated: rows={archive_result['imported_count']}")
        db.add_event(run_id, f"translation run finished: status={status}")
        final_metadata = db.get_run(run_id).get("metadata", {})
        final_progress = _terminal_translation_progress(final_metadata.get("translation_progress"), status)
        large_text_state = dict(final_metadata.get("large_text") or {})
        retro_text = render_large_text_retro(
            {
                "task": project["name"],
                "translation_progress": final_progress if isinstance(final_progress, dict) else {},
                "preflight": large_text_state.get("preflight") or {},
                "cache_lint": large_text_state.get("cache_lint") or {"status": "skipped", "reason": "not provided"},
                "readback_gate": large_text_state.get("readback_gate") or {"status": "skipped", "reason": "delivery not generated yet"},
            }
        )
        retro_path = work_dir / "large_text_retro.md"
        retro_path.write_text(retro_text, encoding="utf-8")
        retro_artifact = db.add_artifact(
            project["id"],
            "Large text retro",
            retro_path,
            "large_text_retro",
            run_id=run_id,
            mime="text/markdown",
            origin="generated",
        )
        large_text_state["retro_artifact_id"] = retro_artifact["id"]
        artifacts.append(retro_artifact)
        db.merge_run_metadata(
            run_id,
            {
                "translation_progress": final_progress,
                "task_origin": metadata.get("task_origin") or "translation_run",
                "input_artifacts": input_artifacts,
                "quality": qa_result["quality"],
                "project_harness_quality": qa_result["project_harness_quality"],
                "semantic_qa": qa_result["semantic_qa"],
                "quality_summary": qa_result["quality_summary"],
                "harness": harness_snapshot["summary"],
                "model": {
                    "provider": settings.get("provider"),
                    "protocol": settings.get("protocol"),
                    "preset": settings.get("preset"),
                    "model": settings.get("model"),
                    "reasoning_effort": settings.get("reasoning_effort"),
                },
                "batch_size": batch_size,
                "translation_readiness": readiness,
                "translation_archive": archive_result,
                "large_text": large_text_state,
            },
        )
        db.update_run(run_id, status=status)
        return {
            "run": db.get_run(run_id),
            "artifacts": artifacts,
            "quality": qa_result["quality"],
            "project_harness_quality": qa_result["project_harness_quality"],
            "quality_summary": qa_result["quality_summary"],
        }
    except Exception as exc:
        friendly = user_facing_error(exc)
        db.add_event(run_id, friendly, level="error")
        failed_metadata = db.get_run(run_id).get("metadata", {})
        status = "canceled" if str(exc) == "translation canceled" else "failed"
        db.merge_run_metadata(run_id, {"translation_progress": _terminal_translation_progress(failed_metadata.get("translation_progress"), status), "error": friendly})
        db.update_run(run_id, status=status)
        if isinstance(exc, UserFacingWorkflowError):
            raise
        raise UserFacingWorkflowError(friendly) from exc


def run_translate_sync(run_id: str, request: Any, cancel_event: Any | None = None) -> dict[str, Any]:
    return asyncio.run(translate_run(run_id, request, cancel_event=cancel_event))


def cancel_translation_run(run_id: str) -> dict[str, Any]:
    run = db.get_run(run_id)
    work_dir = run_dir(run_id) / "translation"
    work_dir.mkdir(parents=True, exist_ok=True)
    _translation_cancel_path(work_dir).write_text(db.now_iso(), encoding="utf-8")
    db.cancel_job_lease(lease_name_for_project(run["project_id"]), f"run:{run_id}")
    db.merge_run_metadata(run_id, {"cancel_requested_at": db.now_iso()})
    db.update_run(run_id, status="canceled")
    db.add_event(run_id, "translation cancel requested")
    return db.get_run(run_id)


def translation_run_progress(run_id: str) -> dict[str, Any]:
    run = db.get_run(run_id)
    metadata = run.get("metadata", {})
    progress = metadata.get("translation_progress")
    if run.get("status") in {"passed", "failed", "needs_input", "canceled"}:
        progress = _terminal_translation_progress(progress, str(run.get("status") or ""))
    return {
        "run": run,
        "progress": progress,
        "api_budget_estimate": metadata.get("api_budget_estimate"),
        "reason": metadata.get("reason"),
    }


def translation_batch_file(run_id: str, batch_index: int, kind: str) -> Path:
    if batch_index < 1:
        raise ValueError("batch_index must be positive")
    if kind not in {"request", "response", "raw-response", "error"}:
        raise ValueError("batch file kind must be request, response, raw-response, or error")
    run = db.get_run(run_id)
    metadata = run.get("metadata") or {}
    progress = metadata.get("translation_progress") or {}
    batch_size = int(progress.get("batch_size") or metadata.get("batch_size") or 90)
    suffix = {"request": ".request.jsonl", "response": ".jsonl", "raw-response": ".raw_response.jsonl", "error": ".error.json"}[kind]
    path = run_dir(run_id) / "translation" / f"batches_{batch_size}" / f"batch_{batch_index:05d}{suffix}"
    if not path.exists():
        raise KeyError(str(path))
    return path


def reconcile_interrupted_background_jobs() -> dict[str, int]:
    db.mark_running_job_leases_interrupted()
    translation_runs = 0
    local_runs = 0
    announcement_tasks = 0
    for run in db.list_runs():
        if run.get("kind") == "translation" and run.get("status") in {"queued", "running"}:
            db.merge_run_metadata(run["id"], {"reason": "background_job_interrupted", "interrupted_at": db.now_iso()})
            db.update_run(run["id"], status="needs_input")
            db.add_event(run["id"], "background translation job was interrupted; resume from saved batches")
            translation_runs += 1
        elif run.get("kind") != "translation" and run.get("status") in {"queued", "running"}:
            db.merge_run_metadata(
                run["id"],
                {
                    "reason": "background_job_interrupted",
                    "interrupted_at": db.now_iso(),
                    "error": "后台任务已中断，请重新运行当前步骤。",
                },
            )
            db.update_run(run["id"], status="failed")
            db.add_event(run["id"], "background local workflow job was interrupted; rerun the current step", level="warning")
            local_runs += 1
    for project in db.list_projects():
        for task in db.list_announcement_tasks(project["id"]):
            if task.get("status") in {"queued", "running"}:
                metadata = dict(task.get("metadata") or {})
                metadata["reason"] = "background_job_interrupted"
                metadata["interrupted_at"] = db.now_iso()
                db.update_announcement_task(task["id"], status="needs_input", current_step=ANNOUNCEMENT_STEP["translate"], metadata=metadata)
                for item in task.get("languages") or []:
                    if item.get("status") in {"queued", "running"}:
                        lang_meta = dict(item.get("metadata") or {})
                        lang_meta["reason"] = "background_job_interrupted"
                        db.upsert_announcement_task_language(
                            task["id"],
                            task["project_id"],
                            str(item["language"]),
                            status="prepared",
                            current_step=ANNOUNCEMENT_STEP["translate"],
                            metadata=lang_meta,
                        )
                announcement_tasks += 1
    return {"translation_runs": translation_runs, "announcement_tasks": announcement_tasks, "local_runs": local_runs}

__all__ = [name for name in globals() if not name.startswith("__")]
