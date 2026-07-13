"""Resumable OpenAI-compatible executor for large multilingual packs."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from utils.large_text_multilingual_runner import load_manifest, save_manifest


class TranslationClient(Protocol):
    def translate_batch(
        self,
        rows: list[dict[str, object]],
        target_langs: list[str],
    ) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class ExecutionSummary:
    cache_jsonl: Path
    metrics_json: Path
    source_rows: int
    unique_api_rows: int
    seeded_rows: int
    batch_count: int
    reused_batches: int
    elapsed_seconds: float


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    _atomic_write_text(
        path,
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
    )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def start_phase(manifest: dict[str, Any], phase: str) -> None:
    manifest.setdefault("phase_status", {})[phase] = "running"
    manifest.setdefault("phase_events", []).append(
        {"phase": phase, "event": "start", "at": _now()}
    )
    manifest["status"] = f"{phase}_running"
    save_manifest(manifest)


def complete_phase(
    manifest: dict[str, Any],
    phase: str,
    *,
    started: float,
    metrics: dict[str, Any] | None = None,
) -> None:
    elapsed = round(time.perf_counter() - started, 3)
    manifest.setdefault("phase_status", {})[phase] = "done"
    manifest.setdefault("phase_events", []).append(
        {"phase": phase, "event": "done", "at": _now(), "seconds": elapsed}
    )
    manifest.setdefault("phase_metrics", {})[phase] = {
        "seconds": elapsed,
        **(metrics or {}),
    }
    manifest["status"] = f"{phase}_done"
    save_manifest(manifest)


def fail_phase(manifest: dict[str, Any], phase: str, exc: BaseException) -> None:
    manifest.setdefault("phase_status", {})[phase] = "failed"
    manifest.setdefault("phase_events", []).append(
        {"phase": phase, "event": "failed", "at": _now(), "error": str(exc)[:500]}
    )
    manifest["status"] = f"{phase}_failed"
    save_manifest(manifest)


def _flatten_config(data: dict[str, Any]) -> dict[str, Any]:
    for key in ("lws_settings", "openai", "provider", "translation_provider"):
        nested = data.get(key)
        if isinstance(nested, dict):
            merged = dict(nested)
            for name in ("base_url", "model", "api_key"):
                if data.get(name) not in (None, ""):
                    merged[name] = data[name]
            return merged
    return data


class OpenAICompatibleClient:
    def __init__(self, config_path: Path, *, timeout: int = 180) -> None:
        config = _flatten_config(_read_json(config_path))
        self.base_url = str(config.get("base_url") or "").rstrip("/")
        self.model = str(config.get("model") or "")
        self.api_key = str(config.get("api_key") or "")
        self.checkpoint_identity = f"openai-compatible:{self.base_url}:{self.model}"
        self.timeout = timeout
        if not self.base_url or not self.model:
            raise ValueError("relay config requires base_url and model")

    def _endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return self.base_url + "/chat/completions"
        return self.base_url + "/v1/chat/completions"

    def _chat_json(self, system: str, user_payload: dict[str, object]) -> object:
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False),
                },
            ],
        }
        request = urllib.request.Request(
            self._endpoint(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"relay request failed: {exc}") from exc
        content = body["choices"][0]["message"]["content"]
        return json.loads(content) if isinstance(content, str) else content

    def translate_batch(
        self,
        rows: list[dict[str, object]],
        target_langs: list[str],
    ) -> list[dict[str, object]]:
        parsed = self._chat_json(
            (
                "You are a senior mobile-game localizer. Translate every row into every "
                "requested language. Preserve tokens, numbers, tags, and terminology. "
                "Return strict JSON: {\"rows\":[{\"request_key\":...,"
                "\"translations\":{LANG:TEXT}}]}. Do not omit or add rows."
            ),
            {"target_languages": target_langs, "rows": rows},
        )
        result = parsed.get("rows") if isinstance(parsed, dict) else parsed
        if not isinstance(result, list):
            raise ValueError("relay response must contain a rows array")
        return result

    def review_batch(
        self,
        rows: list[dict[str, object]],
        target_langs: list[str],
    ) -> list[dict[str, object]]:
        parsed = self._chat_json(
            (
                "Act as an independent line-by-line mobile-game localization reviewer. "
                "Check meaning, omissions, terminology, fluency, length, tokens, tags, and numbers. "
                "Do not rewrite correct text. Return strict JSON with one item per row and language: "
                "{\"rows\":[{\"review_key\":...,\"lang\":...,\"status\":\"KEEP|FIX\","
                "\"suggested\":...,\"reason\":...}]}."
            ),
            {"target_languages": target_langs, "rows": rows},
        )
        result = parsed.get("rows") if isinstance(parsed, dict) else parsed
        if not isinstance(result, list):
            raise ValueError("review response must contain a rows array")
        return result

    def audit_batch(
        self,
        suggestions: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        parsed = self._chat_json(
            (
                "Audit localization change suggestions conservatively. Revert changes that narrow "
                "meaning, force terminology into the wrong context, damage tokens/numbers, or are "
                "not a clear improvement. Return strict JSON: {\"rows\":[{\"review_key\":...,"
                "\"lang\":...,\"decision\":\"ACCEPT|REVERT|REVISE\",\"final\":...,"
                "\"reason\":...}]}."
            ),
            {"suggestions": suggestions},
        )
        result = parsed.get("rows") if isinstance(parsed, dict) else parsed
        if not isinstance(result, list):
            raise ValueError("audit response must contain a rows array")
        return result


def _request_signature(row: dict[str, Any]) -> str:
    raw = json.dumps(
        {
            "cn": row.get("cn", ""),
            "context": row.get("context", ""),
            "term_hits": row.get("term_hits") or [],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _request_row(row: dict[str, Any], request_key: str) -> dict[str, object]:
    return {
        "request_key": request_key,
        "cn": str(row.get("cn") or ""),
        "context": str(row.get("context") or ""),
        "protected_tokens": row.get("tokens") or [],
        "term_hits": row.get("term_hits") or [],
    }


def _validate_response(
    requested: list[dict[str, object]],
    response: list[dict[str, object]],
    target_langs: list[str],
) -> dict[str, dict[str, str]]:
    requested_keys = {str(row["request_key"]) for row in requested}
    response_keys = {str(row.get("request_key") or "") for row in response}
    if requested_keys != response_keys or len(response) != len(requested):
        raise ValueError(
            f"response keys do not match request keys: requested={sorted(requested_keys)}, "
            f"response={sorted(response_keys)}"
        )
    validated: dict[str, dict[str, str]] = {}
    for row in response:
        request_key = str(row["request_key"])
        translations = row.get("translations")
        if not isinstance(translations, dict):
            raise ValueError(f"missing translations object for {request_key}")
        normalized = {str(key).upper(): str(value or "").strip() for key, value in translations.items()}
        missing = [lang for lang in target_langs if not normalized.get(lang)]
        extras = sorted(set(normalized) - set(target_langs))
        if missing or extras:
            raise ValueError(
                f"language mismatch for {request_key}: missing={missing}, extras={extras}"
            )
        validated[request_key] = {lang: normalized[lang] for lang in target_langs}
    return validated


def _checkpoint_name(batch: list[dict[str, object]]) -> str:
    keys = "\n".join(str(row["request_key"]) for row in batch)
    return hashlib.sha256(keys.encode("utf-8")).hexdigest()[:20] + ".json"


def _partition_requests(
    rows: list[dict[str, object]],
    *,
    max_rows: int,
    max_chars: int,
) -> list[list[dict[str, object]]]:
    batches: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    current_chars = 0
    for row in rows:
        row_chars = len(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
        if current and (len(current) >= max_rows or current_chars + row_chars > max_chars):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(row)
        current_chars += row_chars
    if current:
        batches.append(current)
    return batches


def _execute_batch(
    client: TranslationClient,
    batch: list[dict[str, object]],
    target_langs: list[str],
    checkpoint_dir: Path,
    max_attempts: int,
) -> tuple[dict[str, dict[str, str]], bool]:
    checkpoint = checkpoint_dir / _checkpoint_name(batch)
    split_marker = checkpoint.with_suffix(".split.json")
    if checkpoint.exists():
        saved = _read_json(checkpoint)
        return _validate_response(batch, saved.get("rows") or [], target_langs), True
    if split_marker.exists() and len(batch) > 1:
        midpoint = len(batch) // 2
        left, left_reused = _execute_batch(
            client, batch[:midpoint], target_langs, checkpoint_dir, max_attempts
        )
        right, right_reused = _execute_batch(
            client, batch[midpoint:], target_langs, checkpoint_dir, max_attempts
        )
        return {**left, **right}, left_reused and right_reused
    last_error: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            response = client.translate_batch(batch, target_langs)
            validated = _validate_response(batch, response, target_langs)
            _atomic_write_text(
                checkpoint,
                json.dumps({"rows": response}, ensure_ascii=False, indent=2),
            )
            return validated, False
        except BaseException as exc:  # retries include malformed provider responses
            last_error = exc
            if attempt + 1 < max_attempts:
                time.sleep(min(0.25 * (2**attempt), 1.0))
    assert last_error is not None
    if len(batch) > 1:
        _atomic_write_text(
            split_marker,
            json.dumps({"split": len(batch) // 2, "rows": len(batch)}, indent=2),
        )
        midpoint = len(batch) // 2
        left, left_reused = _execute_batch(
            client, batch[:midpoint], target_langs, checkpoint_dir, max_attempts
        )
        right, right_reused = _execute_batch(
            client, batch[midpoint:], target_langs, checkpoint_dir, max_attempts
        )
        return {**left, **right}, left_reused and right_reused
    raise last_error


def translate_manifest(
    manifest_path: Path,
    *,
    relay_config: Path | None,
    client: TranslationClient | None = None,
    batch_size: int = 60,
    max_batch_chars: int = 24000,
    workers: int = 4,
    max_attempts: int = 3,
) -> ExecutionSummary:
    started = time.perf_counter()
    manifest = load_manifest(manifest_path)
    start_phase(manifest, "api_translate")
    try:
        work_dir = Path(manifest["work_dir"])
        items = _read_jsonl(Path(manifest["inputs"]["items_jsonl"]))
        target_langs = [str(lang).upper() for lang in manifest["inputs"]["target_languages"]]
        seed_memory = _read_json(work_dir / "seed_memory.json")
        representatives: dict[str, dict[str, Any]] = {}
        row_signatures: list[str] = []
        seeded: dict[str, dict[str, str]] = {}
        for row in items:
            signature = _request_signature(row)
            row_signatures.append(signature)
            source = str(row.get("cn") or "")
            seed = seed_memory.get(source)
            normalized_seed = (
                {str(key).upper(): str(value or "").strip() for key, value in seed.items()}
                if isinstance(seed, dict)
                else {}
            )
            if all(normalized_seed.get(lang) for lang in target_langs):
                seeded[signature] = {lang: normalized_seed[lang] for lang in target_langs}
            else:
                representatives.setdefault(signature, row)

        request_rows = [
            _request_row(row, signature)
            for signature, row in representatives.items()
            if signature not in seeded
        ]
        smoke_size = min(20, batch_size)
        smoke_candidates = _partition_requests(
            request_rows[:smoke_size],
            max_rows=smoke_size,
            max_chars=max_batch_chars,
        )
        smoke_batch = smoke_candidates[0] if smoke_candidates else []
        batches = _partition_requests(
            request_rows[len(smoke_batch):],
            max_rows=batch_size,
            max_chars=max_batch_chars,
        )
        if client is None:
            if relay_config is None:
                raise ValueError("relay_config is required when client is not injected")
            client = OpenAICompatibleClient(relay_config)
        client_identity = str(
            getattr(
                client,
                "checkpoint_identity",
                f"{type(client).__module__}.{type(client).__qualname__}",
            )
        )
        strategy = manifest.get("api_strategy") or {}
        model = str(strategy.get("model") or "injected")
        scope = hashlib.sha256(
            json.dumps(
                {
                    "model": model,
                    "provider_host": strategy.get("base_url_host", ""),
                    "provider_path": strategy.get("base_url_path", ""),
                    "client_identity": client_identity,
                    "target_langs": target_langs,
                    "prompt": "translate-v1",
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:16]
        checkpoint_dir = work_dir / "translation_batches" / scope
        checkpoint_dir.mkdir(parents=True, exist_ok=True)

        translated: dict[str, dict[str, str]] = {}
        reused_batches = 0
        batch_count = len(batches) + int(bool(smoke_batch))
        if smoke_batch:
            values, reused = _execute_batch(
                client,
                smoke_batch,
                target_langs,
                checkpoint_dir,
                max_attempts,
            )
            translated.update(values)
            reused_batches += int(reused)
            manifest.setdefault("phase_status", {})["api_smoke"] = "done"
            manifest["api_smoke"] = {
                "ok": True,
                "schema_ok": True,
                "rows": len(smoke_batch),
                "reused_checkpoint": reused,
                "recorded_at": _now(),
            }
            save_manifest(manifest)
        if batches:
            with ThreadPoolExecutor(max_workers=max(1, min(workers, len(batches)))) as pool:
                futures = {
                    pool.submit(
                        _execute_batch,
                        client,
                        batch,
                        target_langs,
                        checkpoint_dir,
                        max_attempts,
                    ): batch
                    for batch in batches
                }
                for future in as_completed(futures):
                    values, reused = future.result()
                    translated.update(values)
                    reused_batches += int(reused)
        resolved = {**translated, **seeded}
        output_rows: list[dict[str, Any]] = []
        for row, signature in zip(items, row_signatures, strict=True):
            if signature not in resolved:
                raise ValueError(f"missing translation for source row {row.get('key')}")
            output_rows.append({**row, "translations": resolved[signature]})

        cache_path = work_dir / "initial_cache.jsonl"
        metrics_path = work_dir / "translation_metrics.json"
        _write_jsonl(cache_path, output_rows)
        summary = ExecutionSummary(
            cache_jsonl=cache_path,
            metrics_json=metrics_path,
            source_rows=len(items),
            unique_api_rows=len(request_rows),
            seeded_rows=len(items) - sum(1 for signature in row_signatures if signature not in seeded),
            batch_count=batch_count,
            reused_batches=reused_batches,
            elapsed_seconds=round(time.perf_counter() - started, 3),
        )
        _atomic_write_text(
            metrics_path,
            json.dumps({**asdict(summary), "cache_jsonl": str(cache_path), "metrics_json": str(metrics_path)}, ensure_ascii=False, indent=2),
        )
        manifest.setdefault("artifacts", {})["initial_cache"] = str(cache_path)
        manifest["artifacts"]["translation_metrics"] = str(metrics_path)
        manifest.setdefault("phase_status", {})["api_smoke"] = "done"
        complete_phase(
            manifest,
            "api_translate",
            started=started,
            metrics={
                "source_rows": summary.source_rows,
                "unique_api_rows": summary.unique_api_rows,
                "batch_count": summary.batch_count,
                "reused_batches": summary.reused_batches,
            },
        )
        return summary
    except BaseException as exc:
        fail_phase(manifest, "api_translate", exc)
        raise
