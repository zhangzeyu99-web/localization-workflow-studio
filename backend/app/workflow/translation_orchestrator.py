from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from .. import db
from ..config import normalize_provider_name
from ..jobs import lease_name_for_project
from ..providers import translate_batch
from ..translation_batches import (
    get_shared_rate_limiter as _get_shared_rate_limiter,
    load_or_create_batch_manifest as _load_or_create_batch_manifest,
    manage_project_prompt_context as _manage_project_prompt_context,
    project_context_summary as _project_context_summary,
    provider_retry_delay_seconds as _provider_retry_delay_seconds,
)
from .common import _looks_like_untranslated_seed
from .jsonl_helpers import read_jsonl, write_jsonl
from .qa import _normalize_translation_id
from .subprocess_runner import user_facing_error

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


def _provider_call_timeout_seconds(settings: dict[str, Any]) -> float:
    try:
        configured = float(settings.get("provider_timeout_seconds") or 120)
    except (TypeError, ValueError):
        configured = 120.0
    return max(1.0, configured)


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
    current_batch_status: str | None = None,
    current_batch_rows: int | None = None,
    current_attempt: int | None = None,
    max_attempts: int | None = None,
    provider_timeout_seconds: float | None = None,
    current_batch_started_at: str | None = None,
    message: str | None = None,
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
        "current_batch_status": current_batch_status,
        "current_batch_rows": current_batch_rows,
        "current_attempt": current_attempt,
        "max_attempts": max_attempts,
        "provider_timeout_seconds": provider_timeout_seconds,
        "current_batch_started_at": current_batch_started_at,
        "message": message or "",
        "batch_size": batch_size,
        "percent": percent,
        "elapsed_seconds": int(elapsed_seconds),
        "average_batch_seconds": round(average_batch_seconds, 2) if average_batch_seconds is not None else None,
        "eta_seconds": eta_seconds,
    }


def _update_translation_progress(run_id: str, progress: dict[str, Any], status: str = "running") -> None:
    db.merge_run_metadata(run_id, {"translation_progress": progress})
    db.update_run(run_id, status=status)


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
    run_id: str | None = None,
    current_batch: int | None = None,
    failed_batch: int | None = None,
    rate_limit_wait_seconds: float | None = None,
) -> dict[str, Any]:
    batches = manifest.get("batches") or []
    completed_batches = [batch for batch in batches if batch.get("status") == "passed"]
    completed_rows = sum(int(batch.get("row_count") or 0) for batch in completed_batches)
    current_meta = None
    if current_batch is not None:
        current_meta = next((batch for batch in batches if int(batch.get("batch_index") or 0) == int(current_batch)), None)
    current_status = str((current_meta or {}).get("status") or "")
    current_rows = int((current_meta or {}).get("row_count") or 0) if current_meta else None
    current_attempt = int((current_meta or {}).get("attempts") or 0) if current_meta else None
    max_attempts = int(manifest.get("max_batch_attempts") or 0) or None
    timeout_seconds = manifest.get("provider_timeout_seconds")
    started_at_iso = str((current_meta or {}).get("attempt_started_at") or "") if current_meta else ""
    lease_status = ""
    if run_id:
        try:
            project_id = db.get_run(run_id).get("project_id")
            lease = db.get_job_lease(lease_name_for_project(project_id)) if project_id else None
            lease_status = str((lease or {}).get("status") or "")
        except Exception:
            lease_status = ""
    if failed_batch:
        message = f"第 {failed_batch}/{len(batches)} 批失败；可点击继续，从已保存批次后恢复。"
    elif current_batch is not None and current_status == "running":
        message = f"正在调用 AI：第 {current_batch}/{len(batches)} 批，本批 {current_rows or 0} 行，第 {current_attempt or 1}/{max_attempts or '-'} 次。"
    elif rate_limit_wait_seconds:
        message = f"正在等待限流窗口，约 {round(rate_limit_wait_seconds, 1)} 秒后继续。"
    elif len(completed_batches) >= len(batches) and batches:
        message = "全部批次已完成，正在回填并进入 QA。"
    else:
        message = "后台处理中，已完成批次会实时保存，可断点继续。"
    progress = _translation_progress(
        total_rows=int(manifest.get("total_rows") or 0),
        total_batches=len(batches),
        completed_batches=len(completed_batches),
        completed_rows=completed_rows,
        batch_size=batch_size,
        started_at=started_at,
        current_batch=current_batch,
        failed_batch=failed_batch,
        current_batch_status=current_status or None,
        current_batch_rows=current_rows,
        current_attempt=current_attempt,
        max_attempts=max_attempts,
        provider_timeout_seconds=float(timeout_seconds) if timeout_seconds else None,
        current_batch_started_at=started_at_iso or None,
        message=message,
    )
    progress.update(
        {
            "max_concurrent_batches": int(manifest.get("max_concurrent_batches") or 1),
            "estimated_total_input_tokens": int(manifest.get("estimated_total_input_tokens") or 0),
            "rate_limit_wait_seconds": round(rate_limit_wait_seconds, 2) if rate_limit_wait_seconds else 0,
            "fingerprint": str(manifest.get("input_fingerprint") or ""),
            "lease_status": lease_status,
            "invalidated_reason": str(manifest.get("invalidated_reason") or ""),
            "term_audit": manifest.get("term_audit") or {},
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
    term_audit: dict[str, Any] | None = None,
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
    manifest["provider_timeout_seconds"] = _provider_call_timeout_seconds(settings)
    manifest["term_audit"] = term_audit or manifest.get("term_audit") or {}
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
        db.merge_run_metadata(
            run_id,
            {
                "reason": "api_budget_confirmation_required",
                "api_budget_estimate": {
                    "estimated_input_tokens": estimated_total,
                    "warning_tokens": budget_warning_tokens,
                    "estimated_batches": len(manifest.get("batches") or []),
                },
                "translation_progress": _manifest_progress(manifest, batch_size=batch_size, started_at=time.monotonic(), run_id=run_id),
            },
        )
        db.update_run(run_id, status="needs_input")
        db.add_event(run_id, f"translation paused for API budget confirmation: estimated_input_tokens={estimated_total}, warning={budget_warning_tokens}", level="warning")
        return []

    started_at = time.monotonic()
    limiter = _get_shared_rate_limiter(
        normalize_provider_name(settings.get("provider")),
        str(settings.get("api_key") or ""),
        int(settings.get("max_requests_per_minute") or 12),
        int(settings.get("max_estimated_tokens_per_minute") or 120000),
    )
    max_attempts = max(1, min(int(settings.get("max_batch_attempts") or 3), 5))
    concurrency = max(1, min(int(settings.get("max_concurrent_batches") or 2), 4))
    manifest["max_batch_attempts"] = max_attempts
    manifest["provider_timeout_seconds"] = _provider_call_timeout_seconds(settings)
    manifest["term_audit"] = term_audit or manifest.get("term_audit") or {}
    manifest["updated_at"] = db.now_iso()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
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
                _manifest_progress(manifest, batch_size=batch_size, started_at=started_at, run_id=run_id, current_batch=current_batch, failed_batch=failed_batch, rate_limit_wait_seconds=rate_wait),
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
            attempt_started_at = db.now_iso()
            batch_meta.update({"status": "running", "attempts": attempt, "attempt_started_at": attempt_started_at, "updated_at": attempt_started_at})
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
                items = await asyncio.wait_for(
                    translate_batch(batch, settings, prompt),
                    timeout=_provider_call_timeout_seconds(settings),
                )
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
            _update_translation_progress(run_id, _manifest_progress(manifest, batch_size=batch_size, started_at=started_at, run_id=run_id), status="canceled")
        raise failure

    translated_rows: list[dict[str, Any]] = []
    for item in sorted(manifest.get("batches") or [], key=lambda value: int(value.get("batch_index") or 0)):
        translated_rows.extend(read_jsonl(Path(item["response_path"])))
    await persist_manifest(status="running")
    return translated_rows
