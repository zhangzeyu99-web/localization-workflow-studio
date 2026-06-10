from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from .. import db
from ..config import LOCALIZATION_ROOT, REAL_PROVIDERS, TEST_FAKE_PROVIDER, load_settings, normalize_provider_name, test_provider_enabled
from ..languages import require_supported_language
from ..providers import translate_batch
from ..translation_batches import (
    AsyncTokenRateLimiter as _AsyncTokenRateLimiter,
    load_or_create_batch_manifest as _load_or_create_batch_manifest,
    manage_project_prompt_context as _manage_project_prompt_context,
    project_context_summary as _project_context_summary,
    provider_retry_delay_seconds as _provider_retry_delay_seconds,
)
from .announcement import ANNOUNCEMENT_STEP
from .announcement_segments import _is_quick_text_path
from .common import _looks_like_untranslated_seed, run_dir
from .glossary import archive_translation_artifact, read_jsonl, write_jsonl
from .prompt_snapshots import (
    create_project_glossary_snapshot,
    create_prompt_and_harness_snapshots,
    create_quick_reference_snapshot,
)
from .qa import _normalize_translation_id, run_localization_qa
from .subprocess_runner import (
    UserFacingWorkflowError,
    _friendly_unsupported_language_file_message,
    parse_key_output,
    run_subprocess,
    user_facing_error,
)
from .translation_readiness import inspect_translation_readiness

def _completed_batch_rows(path: Path, batch: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    try:
        rows = read_jsonl(path)
    except Exception:
        return None
    expected_ids = [_normalize_translation_id(row.get("id")) for row in batch]
    actual_ids = [_normalize_translation_id(row.get("id")) for row in rows if "id" in row]
    if actual_ids != expected_ids:
        return None
    if any("translation" not in row or not str(row.get("translation") or "").strip() for row in rows):
        return None
    return rows


def _write_batch_error(path: Path, batch_index: int, attempt: int, exc: Exception) -> None:
    path.write_text(
        json.dumps(
            {
                "batch_index": batch_index,
                "attempt": attempt,
                "error": user_facing_error(exc),
                "created_at": db.now_iso(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _translation_progress(
    *,
    total_rows: int,
    total_batches: int,
    completed_batches: int,
    completed_rows: int,
    batch_size: int,
    started_at: float,
    current_batch: int | None = None,
    failed_batch: int | None = None,
) -> dict[str, Any]:
    elapsed_seconds = max(0.0, time.monotonic() - started_at)
    average_batch_seconds = elapsed_seconds / completed_batches if completed_batches else None
    remaining_batches = max(0, total_batches - completed_batches)
    eta_seconds = int(average_batch_seconds * remaining_batches) if average_batch_seconds is not None else None
    percent = round((completed_batches / total_batches) * 100, 2) if total_batches else 100.0
    return {
        "total_rows": total_rows,
        "completed_rows": completed_rows,
        "total_batches": total_batches,
        "completed_batches": completed_batches,
        "remaining_batches": remaining_batches,
        "current_batch": current_batch,
        "failed_batch": failed_batch,
        "batch_size": batch_size,
        "percent": percent,
        "elapsed_seconds": int(elapsed_seconds),
        "average_batch_seconds": round(average_batch_seconds, 2) if average_batch_seconds is not None else None,
        "eta_seconds": eta_seconds,
    }


def _update_translation_progress(run_id: str, progress: dict[str, Any], status: str = "running") -> None:
    current = db.get_run(run_id)
    db.update_run(run_id, status=status, metadata={**current.get("metadata", {}), "translation_progress": progress})


def _terminal_translation_progress(progress: Any, status: str) -> Any:
    if not isinstance(progress, dict):
        return progress
    normalized = dict(progress)
    normalized["current_batch"] = None
    if str(normalized.get("lease_status") or "").lower() == "running":
        normalized["lease_status"] = status
    return normalized


def _translation_cancel_path(work_dir: Path) -> Path:
    return work_dir / "cancel.requested"


def _cancel_requested(run_id: str, work_dir: Path, cancel_event: Any | None = None) -> bool:
    if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
        return True
    if _translation_cancel_path(work_dir).exists():
        return True
    try:
        return db.get_run(run_id).get("status") == "canceled"
    except KeyError:
        return True


def _structural_tokens(text: str) -> list[str]:
    patterns = [
        r"\{[^{}]+\}",
        r"%[sdif]",
        r"##\d+",
        r"\[(?!/?color\b)(?:[A-Za-z]+\d+|\d+)\]",
        r"\[[a-zA-Z]+[^\]]*\]",
        r"\[/[a-zA-Z]+\]",
        r"<[^>]+>",
        r"&[A-Za-z][A-Za-z0-9]+;",
    ]
    hits: list[str] = []
    for pattern in patterns:
        hits.extend(re.findall(pattern, str(text or "")))
    return hits


def _validate_translated_batch(batch: list[dict[str, Any]], rows: list[dict[str, Any]], language: str) -> list[dict[str, Any]]:
    expected_ids = [_normalize_translation_id(row.get("id")) for row in batch]
    actual_ids = [_normalize_translation_id(row.get("id")) for row in rows if "id" in row]
    if actual_ids != expected_ids:
        raise ValueError(f"response IDs mismatch: expected={expected_ids[:8]}, actual={actual_ids[:8]}")
    if len(set(map(str, actual_ids))) != len(actual_ids):
        raise ValueError("response contains duplicate IDs")
    validated: list[dict[str, Any]] = []
    for source_row, row in zip(batch, rows):
        translation = str(row.get("translation") or "")
        if not translation.strip():
            raise ValueError(f"row {source_row.get('id')} returned empty translation")
        source = str(source_row.get("source") or "")
        missing_tokens = [token for token in _structural_tokens(source) if token not in translation]
        if missing_tokens:
            raise ValueError(f"row {source_row.get('id')} lost structural token(s): {missing_tokens[:5]}")
        if source.count("\n") != translation.count("\n"):
            raise ValueError(f"row {source_row.get('id')} changed actual newline count")
        if source.count("\\n") != translation.count("\\n"):
            raise ValueError(f"row {source_row.get('id')} changed escaped newline count")
        if language in {"en", "ko"} and _looks_like_untranslated_seed(translation, language):
            raise ValueError(f"row {source_row.get('id')} still contains obvious Chinese text")
        validated.append({"id": _normalize_translation_id(row.get("id")), "translation": translation})
    return validated


def _manifest_progress(
    manifest: dict[str, Any],
    *,
    batch_size: int,
    started_at: float,
    current_batch: int | None = None,
    failed_batch: int | None = None,
    rate_limit_wait_seconds: float | None = None,
) -> dict[str, Any]:
    batches = manifest.get("batches") or []
    completed_batches = [batch for batch in batches if batch.get("status") == "passed"]
    completed_rows = sum(int(batch.get("row_count") or 0) for batch in completed_batches)
    progress = _translation_progress(
        total_rows=int(manifest.get("total_rows") or 0),
        total_batches=len(batches),
        completed_batches=len(completed_batches),
        completed_rows=completed_rows,
        batch_size=batch_size,
        started_at=started_at,
        current_batch=current_batch,
        failed_batch=failed_batch,
    )
    progress.update(
        {
            "max_concurrent_batches": int(manifest.get("max_concurrent_batches") or 1),
            "estimated_total_input_tokens": int(manifest.get("estimated_total_input_tokens") or 0),
            "rate_limit_wait_seconds": round(rate_limit_wait_seconds, 2) if rate_limit_wait_seconds else 0,
            "fingerprint": str(manifest.get("input_fingerprint") or ""),
            "lease_status": (db.get_job_lease("long_text") or {}).get("status", ""),
            "invalidated_reason": str(manifest.get("invalidated_reason") or ""),
        }
    )
    return progress


async def _translate_rows_with_orchestration(
    *,
    run_id: str,
    rows: list[dict[str, Any]],
    settings: dict[str, Any],
    project_prompt: str,
    work_dir: Path,
    batch_size: int,
    language: str,
    cancel_event: Any | None = None,
    confirm_api_budget: bool = False,
) -> list[dict[str, Any]]:
    batch_size = max(1, min(int(batch_size or settings.get("batch_size") or 90), 200))
    provider_prompt = _manage_project_prompt_context(project_prompt, settings)
    context_summary = _project_context_summary(project_prompt, settings)
    cancel_path = _translation_cancel_path(work_dir)
    if not (cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)()) and cancel_path.exists():
        cancel_path.unlink()
    manifest_path = work_dir / "batch_manifest.json"
    batches_dir = work_dir / f"batches_{batch_size}"
    manifest = _load_or_create_batch_manifest(manifest_path, rows, project_prompt, settings, batch_size, language)
    batches_dir.mkdir(parents=True, exist_ok=True)
    manifest["project_context"] = context_summary
    manifest["max_concurrent_batches"] = max(1, min(int(settings.get("max_concurrent_batches") or 2), 4))
    manifest["updated_at"] = db.now_iso()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if context_summary.get("trimmed"):
        db.add_event(
            run_id,
            "project context trimmed before provider call: "
            f"{context_summary.get('original_estimated_tokens')} -> {context_summary.get('managed_estimated_tokens')} estimated tokens",
            level="warning",
        )

    budget_warning_tokens = int(settings.get("api_budget_warning_tokens") or 1000000)
    estimated_total = int(manifest.get("estimated_total_input_tokens") or 0)
    if estimated_total > budget_warning_tokens and not confirm_api_budget:
        current = db.get_run(run_id)
        db.update_run(
            run_id,
            status="needs_input",
            metadata={
                **current.get("metadata", {}),
                "reason": "api_budget_confirmation_required",
                "api_budget_estimate": {
                    "estimated_input_tokens": estimated_total,
                    "warning_tokens": budget_warning_tokens,
                    "estimated_batches": len(manifest.get("batches") or []),
                },
                "translation_progress": _manifest_progress(manifest, batch_size=batch_size, started_at=time.monotonic()),
            },
        )
        db.add_event(run_id, f"translation paused for API budget confirmation: estimated_input_tokens={estimated_total}, warning={budget_warning_tokens}", level="warning")
        return []

    started_at = time.monotonic()
    limiter = _AsyncTokenRateLimiter(
        int(settings.get("max_requests_per_minute") or 12),
        int(settings.get("max_estimated_tokens_per_minute") or 120000),
    )
    max_attempts = max(1, min(int(settings.get("max_batch_attempts") or 3), 5))
    concurrency = max(1, min(int(settings.get("max_concurrent_batches") or 2), 4))
    manifest_lock = asyncio.Lock()
    failure: Exception | None = None

    def batch_rows(batch_meta: dict[str, Any]) -> list[dict[str, Any]]:
        start = int(batch_meta.get("start") or 0)
        count = int(batch_meta.get("row_count") or 0)
        return rows[start : start + count]

    async def persist_manifest(current_batch: int | None = None, failed_batch: int | None = None, status: str = "running", rate_wait: float | None = None) -> None:
        async with manifest_lock:
            manifest["updated_at"] = db.now_iso()
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            _update_translation_progress(
                run_id,
                _manifest_progress(manifest, batch_size=batch_size, started_at=started_at, current_batch=current_batch, failed_batch=failed_batch, rate_limit_wait_seconds=rate_wait),
                status=status,
            )

    async def process_batch(batch_meta: dict[str, Any]) -> None:
        nonlocal failure
        if failure is not None:
            return
        batch_index = int(batch_meta["batch_index"])
        batch = batch_rows(batch_meta)
        batch_path = batches_dir / f"batch_{batch_index:05d}.jsonl"
        request_path = batches_dir / f"batch_{batch_index:05d}.request.jsonl"
        raw_response_path = batches_dir / f"batch_{batch_index:05d}.raw_response.jsonl"
        error_path = batches_dir / f"batch_{batch_index:05d}.error.json"
        if not request_path.exists():
            write_jsonl(request_path, batch)
        batch_meta["request_path"] = str(request_path)
        completed = _completed_batch_rows(batch_path, batch)
        if completed is not None:
            batch_meta.update({"status": "passed", "response_path": str(batch_path), "error_path": "", "updated_at": db.now_iso()})
            db.add_event(run_id, f"resume: batch {batch_index}/{len(manifest.get('batches') or [])} already completed; rows={len(completed)}")
            await persist_manifest(current_batch=batch_index)
            return
        for attempt in range(int(batch_meta.get("attempts") or 0) + 1, max_attempts + 1):
            if _cancel_requested(run_id, work_dir, cancel_event):
                batch_meta.update({"status": "canceled", "attempts": attempt - 1, "updated_at": db.now_iso()})
                await persist_manifest(current_batch=batch_index, status="canceled")
                raise RuntimeError("translation canceled")
            batch_meta.update({"status": "running", "attempts": attempt, "updated_at": db.now_iso()})
            await persist_manifest(current_batch=batch_index)
            wait_seconds = await limiter.acquire(int(batch_meta.get("estimated_input_tokens") or 1))
            if wait_seconds:
                db.add_event(run_id, f"rate limit wait before batch {batch_index}: {round(wait_seconds, 2)}s")
                await persist_manifest(current_batch=batch_index, rate_wait=wait_seconds)
            db.add_event(run_id, f"translating batch {batch_index}/{len(manifest.get('batches') or [])}: rows={len(batch)}, attempt={attempt}/{max_attempts}")
            try:
                prompt = provider_prompt
                if attempt > 1:
                    prompt = f"{provider_prompt}\n\nRepair request: previous output for this batch failed local validation. Return the full corrected batch only, preserving IDs, order, placeholders, tags, entities, and newlines."
                items = await translate_batch(batch, settings, prompt)
                batch_output = [{"id": item.id, "translation": item.translation} for item in items]
                write_jsonl(raw_response_path, batch_output)
                batch_meta["raw_response_path"] = str(raw_response_path)
                validated = _validate_translated_batch(batch, batch_output, language)
                write_jsonl(batch_path, validated)
                if error_path.exists():
                    error_path.unlink()
                batch_meta.update({"status": "passed", "response_path": str(batch_path), "error_path": "", "updated_at": db.now_iso()})
                db.add_event(run_id, f"batch {batch_index}/{len(manifest.get('batches') or [])} completed and persisted: rows={len(validated)}")
                await persist_manifest(current_batch=batch_index)
                return
            except Exception as exc:
                _write_batch_error(error_path, batch_index, attempt, exc)
                batch_meta.update({"status": "failed", "error_path": str(error_path), "updated_at": db.now_iso()})
                db.add_event(run_id, f"batch {batch_index}/{len(manifest.get('batches') or [])} failed attempt {attempt}/{max_attempts}: {user_facing_error(exc)}", level="warning")
                await persist_manifest(current_batch=batch_index, failed_batch=batch_index, status="running" if attempt < max_attempts else "failed")
                if attempt >= max_attempts:
                    failure = exc
                    raise
                delay = _provider_retry_delay_seconds(exc, attempt)
                db.add_event(run_id, f"batch {batch_index}/{len(manifest.get('batches') or [])} retry backoff: {round(delay, 2)}s")
                await asyncio.sleep(delay)

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    for item in manifest.get("batches") or []:
        completed = _completed_batch_rows(Path(item.get("response_path") or ""), batch_rows(item)) if item.get("status") == "passed" else None
        if completed is not None:
            db.add_event(run_id, f"resume: batch {int(item.get('batch_index') or 0)}/{len(manifest.get('batches') or [])} already completed; rows={len(completed)}")
            continue
        item["status"] = "pending"
        await queue.put(item)

    if queue.empty():
        await persist_manifest(status="running")
    else:
        await persist_manifest()

    async def worker() -> None:
        nonlocal failure
        while failure is None:
            if _cancel_requested(run_id, work_dir, cancel_event):
                failure = RuntimeError("translation canceled")
                return
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                await process_batch(item)
            finally:
                queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
    try:
        await asyncio.gather(*workers)
    finally:
        for worker_task in workers:
            if not worker_task.done():
                worker_task.cancel()
    if failure is not None:
        if str(failure) == "translation canceled":
            db.add_event(run_id, "translation canceled")
            _update_translation_progress(run_id, _manifest_progress(manifest, batch_size=batch_size, started_at=started_at), status="canceled")
        raise failure

    translated_rows: list[dict[str, Any]] = []
    for item in sorted(manifest.get("batches") or [], key=lambda value: int(value.get("batch_index") or 0)):
        translated_rows.extend(read_jsonl(Path(item["response_path"])))
    await persist_manifest(status="running")
    return translated_rows

async def translate_run(run_id: str, request: Any, cancel_event: Any | None = None) -> dict[str, Any]:
    run = db.get_run(run_id)
    language = require_supported_language(run.get("language") or "en")
    project = db.get_project(run["project_id"])
    metadata = run.get("metadata", {})
    input_artifact = db.get_artifact(metadata["input_artifact_id"])
    settings = load_settings()
    if request.provider and str(request.provider).strip() == TEST_FAKE_PROVIDER and not test_provider_enabled():
        reason = "测试 provider 未启用；正式任务请使用已配置的 GPT / Claude API。"
        db.update_run(run_id, status="needs_input", metadata={**metadata, "reason": reason})
        db.add_event(run_id, reason)
        return {"run": db.get_run(run_id), "artifacts": [], "quality": None}
    if request.provider:
        settings["provider"] = normalize_provider_name(request.provider)
    if request.protocol:
        settings["protocol"] = request.protocol
    if getattr(request, "preset", None):
        settings["preset"] = request.preset
    batch_size = int(request.batch_size or metadata.get("batch_size") or settings.get("batch_size") or 90)
    batch_size = max(1, min(batch_size, 200))
    readiness = inspect_translation_readiness(input_artifact["id"], batch_size=batch_size, language=language)
    if _is_quick_text_path(Path(input_artifact["path"])) and metadata.get("task_origin") != "quick_task":
        reason = _friendly_unsupported_language_file_message(Path(input_artifact["path"]).suffix)
        db.update_run(
            run_id,
            status="needs_input",
            metadata={
                **metadata,
                "reason": reason,
                "translation_readiness": readiness,
            },
        )
        db.add_event(run_id, reason)
        return {"run": db.get_run(run_id), "artifacts": [], "quality": None, "translation_readiness": readiness}
    if readiness.get("reason") == "unsupported_file":
        reason = _friendly_unsupported_language_file_message(Path(input_artifact["path"]).suffix)
        db.update_run(
            run_id,
            status="needs_input",
            metadata={
                **metadata,
                "reason": reason,
                "translation_readiness": readiness,
            },
        )
        db.add_event(run_id, reason)
        return {"run": db.get_run(run_id), "artifacts": [], "quality": None, "translation_readiness": readiness}
    if readiness.get("reason") == "invalid_id_rows":
        reason = "language table ID column must be present and non-empty before translation or QA"
        db.update_run(
            run_id,
            status="needs_input",
            metadata={
                **metadata,
                "reason": reason,
                "translation_readiness": readiness,
            },
        )
        db.add_event(run_id, f"translation skipped: {reason}")
        return {"run": db.get_run(run_id), "artifacts": [], "quality": None, "translation_readiness": readiness}
    if readiness.get("ready_for_qa"):
        db.update_run(
            run_id,
            status="needs_input",
            metadata={
                **metadata,
                "reason": "input already contains target translations; run QA instead",
                "translation_readiness": readiness,
            },
        )
        db.add_event(run_id, "translation skipped: input already contains target translations; run QA instead")
        return {"run": db.get_run(run_id), "artifacts": [], "quality": None, "translation_readiness": readiness}
    effective_provider = normalize_provider_name(settings.get("provider"))
    if effective_provider in REAL_PROVIDERS and not settings.get("api_key"):
        db.update_run(
            run_id,
            status="needs_input",
            metadata={**metadata, "reason": f"{effective_provider} api_key is required for formal translation"},
        )
        return {"run": db.get_run(run_id), "artifacts": [], "quality": None}
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
    language = require_supported_language(run.get("language") or "en")
    glossary_snapshot = create_project_glossary_snapshot(project["id"], run_id, snapshot_dir, language=language)
    snapshots = create_prompt_and_harness_snapshots(project["id"], run_id, snapshot_dir, language=language)
    reference_snapshot = create_quick_reference_snapshot(project["id"], run_id, metadata.get("reference_artifact_ids"), snapshot_dir)
    prompt = snapshots["prompt"]
    prompt_snapshot = snapshots["prompt_artifact"]
    harness_snapshot_artifact = snapshots["harness_artifact"]
    harness_snapshot = snapshots["harness_snapshot"]
    prompt_path = snapshots["prompt_path"]
    if reference_snapshot and reference_snapshot.get("context"):
        raw_prompt = f"{prompt}\n\nQuick Task References:\n{reference_snapshot['context']}"
        settings = load_settings()
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
        )
        if not translated_rows and db.get_run(run_id).get("status") == "needs_input":
            return {"run": db.get_run(run_id), "artifacts": [], "quality": None, "translation_readiness": readiness}
        response_path = work_dir / "translation_response.jsonl"
        write_jsonl(response_path, translated_rows)
        db.add_artifact(project["id"], "Translation response JSONL", response_path, "translation_response", run_id=run_id, mime="application/jsonl")

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
        db.update_run(
            run_id,
            status=status,
            metadata={
                **final_metadata,
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
            },
        )
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
        db.update_run(run_id, status=status, metadata={**failed_metadata, "translation_progress": _terminal_translation_progress(failed_metadata.get("translation_progress"), status), "error": friendly})
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
    db.cancel_job_lease("long_text", run_id)
    metadata = run.get("metadata", {})
    db.update_run(run_id, status="canceled", metadata={**metadata, "cancel_requested_at": db.now_iso()})
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
    announcement_tasks = 0
    for run in db.list_runs():
        if run.get("kind") == "translation" and run.get("status") in {"queued", "running"}:
            metadata = dict(run.get("metadata") or {})
            metadata["reason"] = "background_job_interrupted"
            metadata["interrupted_at"] = db.now_iso()
            db.update_run(run["id"], status="needs_input", metadata=metadata)
            db.add_event(run["id"], "background translation job was interrupted; resume from saved batches")
            translation_runs += 1
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
    return {"translation_runs": translation_runs, "announcement_tasks": announcement_tasks}

__all__ = [name for name in globals() if not name.startswith("__")]
