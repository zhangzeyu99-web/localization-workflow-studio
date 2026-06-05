from __future__ import annotations

import asyncio
import hashlib
import json
import math
import shutil
import time
from collections import deque
from pathlib import Path
from typing import Any

from . import db

RowId = int | str


def normalize_translation_id(value: Any) -> int | str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip()
    if text.lstrip("-").isdigit():
        return int(text)
    return text


def estimate_text_tokens(text: Any) -> int:
    value = str(text or "")
    if not value:
        return 1
    ascii_chars = sum(1 for char in value if ord(char) < 128)
    non_ascii = len(value) - ascii_chars
    return max(1, math.ceil(ascii_chars / 4 + non_ascii / 1.6))


def estimate_row_tokens(row: dict[str, Any]) -> int:
    return estimate_text_tokens(json.dumps(row, ensure_ascii=False, sort_keys=True)) + 12


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def project_context_token_budget(settings: dict[str, Any]) -> int:
    max_batch_tokens = max(1000, _positive_int(settings.get("max_batch_input_tokens"), 12000))
    configured = _positive_int(settings.get("max_project_context_tokens"), 6000)
    return max(200, min(configured, max_batch_tokens // 2))


def cap_context_text(text: Any, max_tokens: int, label: str = "context") -> str:
    value = str(text or "")
    if estimate_text_tokens(value) <= max_tokens:
        return value
    original_tokens = estimate_text_tokens(value)
    marker = f"\n[context trimmed: {label}; original_estimated_tokens={original_tokens}; max_tokens={max_tokens}]\n"
    marker_tokens = estimate_text_tokens(marker)
    remaining = max(20, max_tokens - marker_tokens)

    def take_prefix(source: str, budget: int) -> str:
        low, high = 0, len(source)
        while low < high:
            mid = (low + high + 1) // 2
            if estimate_text_tokens(source[:mid]) <= budget:
                low = mid
            else:
                high = mid - 1
        return source[:low].rstrip()

    def take_suffix(source: str, budget: int) -> str:
        low, high = 0, len(source)
        while low < high:
            mid = (low + high + 1) // 2
            if estimate_text_tokens(source[len(source) - mid :]) <= budget:
                low = mid
            else:
                high = mid - 1
        return source[len(source) - low :].lstrip()

    result = ""
    while remaining >= 20:
        head_budget = max(10, int(remaining * 0.65))
        tail_budget = max(10, remaining - head_budget)
        result = f"{take_prefix(value, head_budget)}{marker}{take_suffix(value, tail_budget)}"
        if estimate_text_tokens(result) <= max_tokens:
            return result
        remaining -= 20
    return marker.strip()


def manage_project_prompt_context(project_prompt: Any, settings: dict[str, Any]) -> str:
    return cap_context_text(project_prompt, project_context_token_budget(settings), "project context")


def project_context_summary(project_prompt: Any, settings: dict[str, Any]) -> dict[str, Any]:
    original = str(project_prompt or "")
    managed = manage_project_prompt_context(original, settings)
    original_tokens = estimate_text_tokens(original)
    managed_tokens = estimate_text_tokens(managed)
    return {
        "original_estimated_tokens": original_tokens,
        "managed_estimated_tokens": managed_tokens,
        "max_project_context_tokens": project_context_token_budget(settings),
        "trimmed": managed_tokens < original_tokens,
    }


def batch_input_fingerprint(
    rows: list[dict[str, Any]],
    project_prompt: str,
    settings: dict[str, Any],
    batch_size: int,
    language: str,
) -> str:
    safe_settings = {
        key: settings.get(key)
        for key in (
            "provider",
            "preset",
            "model",
            "reasoning_effort",
            "base_url",
            "batch_size",
            "max_concurrent_batches",
            "max_requests_per_minute",
            "max_estimated_tokens_per_minute",
            "max_batch_input_tokens",
            "max_batch_attempts",
            "max_output_tokens",
            "max_project_context_tokens",
        )
        if key in settings
    }
    managed_prompt = manage_project_prompt_context(project_prompt, settings)
    payload = {
        "language": language,
        "batch_size": batch_size,
        "project_prompt": managed_prompt,
        "project_prompt_sha256": hashlib.sha256(str(project_prompt or "").encode("utf-8")).hexdigest(),
        "settings": safe_settings,
        "rows": [
            {
                "id": normalize_translation_id(row.get("id")),
                "source": str(row.get("source") or ""),
                "term_hits": row.get("term_hits") or [],
                "reference_hits": row.get("reference_hits") or row.get("translation_hits") or [],
            }
            for row in rows
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_batch_manifest(rows: list[dict[str, Any]], project_prompt: str, settings: dict[str, Any], batch_size: int, language: str) -> dict[str, Any]:
    max_rows = max(1, min(int(batch_size or settings.get("batch_size") or 90), 200))
    max_tokens = max(1000, int(settings.get("max_batch_input_tokens") or 12000))
    fingerprint = batch_input_fingerprint(rows, project_prompt, settings, max_rows, language)
    managed_prompt = manage_project_prompt_context(project_prompt, settings)
    context_summary = project_context_summary(project_prompt, settings)
    prompt_tokens = estimate_text_tokens(managed_prompt) + 120
    batches: list[dict[str, Any]] = []
    current_rows: list[dict[str, Any]] = []
    current_tokens = prompt_tokens
    current_start = 0

    def flush() -> None:
        nonlocal current_rows, current_tokens, current_start
        if not current_rows:
            return
        index = len(batches) + 1
        row_ids = [normalize_translation_id(row.get("id")) for row in current_rows]
        batches.append(
            {
                "batch_index": index,
                "start": current_start,
                "row_count": len(current_rows),
                "row_ids": row_ids,
                "estimated_input_tokens": current_tokens,
                "status": "pending",
                "attempts": 0,
                "request_path": "",
                "response_path": "",
                "raw_response_path": "",
                "error_path": "",
                "updated_at": db.now_iso(),
            }
        )
        current_start += len(current_rows)
        current_rows = []
        current_tokens = prompt_tokens

    for row in rows:
        row_tokens = estimate_row_tokens(row)
        if current_rows and (len(current_rows) >= max_rows or current_tokens + row_tokens > max_tokens):
            flush()
        current_rows.append(row)
        current_tokens += row_tokens
    flush()
    return {
        "schema_version": 2,
        "kind": "translation_batch_manifest",
        "language": language,
        "input_fingerprint": fingerprint,
        "batch_size": max_rows,
        "max_batch_input_tokens": max_tokens,
        "project_context": context_summary,
        "total_rows": len(rows),
        "estimated_total_input_tokens": sum(int(batch["estimated_input_tokens"]) for batch in batches),
        "batches": batches,
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
    }


def manifest_matches_rows(
    manifest: dict[str, Any],
    rows: list[dict[str, Any]],
    project_prompt: str = "",
    settings: dict[str, Any] | None = None,
    batch_size: int | None = None,
    language: str | None = None,
) -> bool:
    if manifest.get("input_fingerprint") and settings is not None and batch_size is not None and language is not None:
        expected = batch_input_fingerprint(
            rows,
            project_prompt,
            settings,
            max(1, min(int(batch_size or settings.get("batch_size") or 90), 200)),
            language,
        )
        return str(manifest.get("input_fingerprint") or "") == expected
    manifest_ids: list[RowId] = []
    for batch in manifest.get("batches") or []:
        manifest_ids.extend([normalize_translation_id(value) for value in batch.get("row_ids") or []])
    row_ids = [normalize_translation_id(row.get("id")) for row in rows]
    return manifest_ids == row_ids


def load_or_create_batch_manifest(manifest_path: Path, rows: list[dict[str, Any]], project_prompt: str, settings: dict[str, Any], batch_size: int, language: str) -> dict[str, Any]:
    invalidated_reason = ""
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_matches_rows(manifest, rows, project_prompt, settings, batch_size, language):
                return manifest
            invalidated_reason = "input_fingerprint_changed" if manifest.get("input_fingerprint") else "legacy_manifest_missing_fingerprint"
        except Exception:
            invalidated_reason = "manifest_parse_failed"
    if invalidated_reason:
        old_batch_dir = manifest_path.parent / f"batches_{max(1, min(int(batch_size or settings.get('batch_size') or 90), 200))}"
        shutil.rmtree(old_batch_dir, ignore_errors=True)
    manifest = build_batch_manifest(rows, project_prompt, settings, batch_size, language)
    if invalidated_reason:
        manifest["invalidated_reason"] = invalidated_reason
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


class AsyncTokenRateLimiter:
    def __init__(self, requests_per_minute: int, tokens_per_minute: int) -> None:
        self.requests_per_minute = max(1, int(requests_per_minute or 12))
        self.tokens_per_minute = max(1000, int(tokens_per_minute or 120000))
        self._requests: deque[float] = deque()
        self._tokens: deque[tuple[float, int]] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int) -> float:
        waited = 0.0
        requested_tokens = min(max(1, int(tokens or 1)), self.tokens_per_minute)
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._requests and now - self._requests[0] >= 60:
                    self._requests.popleft()
                while self._tokens and now - self._tokens[0][0] >= 60:
                    self._tokens.popleft()
                token_sum = sum(item[1] for item in self._tokens)
                if len(self._requests) < self.requests_per_minute and token_sum + requested_tokens <= self.tokens_per_minute:
                    self._requests.append(now)
                    self._tokens.append((now, requested_tokens))
                    return waited
                waits = []
                if self._requests:
                    waits.append(60 - (now - self._requests[0]))
                if self._tokens:
                    waits.append(60 - (now - self._tokens[0][0]))
                sleep_for = max(0.25, min([value for value in waits if value > 0] or [1.0]))
            await asyncio.sleep(min(sleep_for, 5.0))
            waited += min(sleep_for, 5.0)


def provider_retry_delay_seconds(exc: Exception, attempt: int) -> float:
    text = str(exc).lower()
    base = 2 ** max(0, attempt - 1)
    if any(marker in text for marker in ("429", "rate limit", "too many requests", "timeout", "temporarily unavailable", " 500", " 502", " 503", " 504")):
        return float(min(30, max(3, base * 2)))
    return float(min(10, base))
