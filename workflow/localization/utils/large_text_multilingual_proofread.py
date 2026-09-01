"""Suggestion-only deep proofreading with controller-owned audit and apply."""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from utils.large_text_multilingual_executor import (
    _atomic_write_text,
    _read_jsonl,
    _write_jsonl,
    complete_phase,
    fail_phase,
    start_phase,
)
from utils.large_text_multilingual_runner import load_manifest


class ReviewClient(Protocol):
    def review_batch(
        self,
        rows: list[dict[str, object]],
        target_langs: list[str],
    ) -> list[dict[str, object]]: ...


class AuditClient(Protocol):
    def audit_batch(
        self,
        suggestions: list[dict[str, object]],
    ) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class ProofreadSummary:
    final_cache: Path
    suggestions_jsonl: Path
    audit_jsonl: Path
    summary_json: Path
    reviewed_rows: int
    reviewed_cells: int
    suggested_changes: int
    reverted_changes: int
    changed_rows: int
    changed_cells: int
    elapsed_seconds: float


def _review_signature(row: dict[str, Any], target_langs: list[str]) -> str:
    raw = json.dumps(
        {
            "cn": row.get("cn", ""),
            "translation_source": row.get("translation_source", row.get("cn", "")),
            "source_mode": row.get("source_mode", "cn"),
            "reference_en": row.get("reference_en", ""),
            "reference_en_status": row.get("reference_en_status", "not_requested"),
            "context": row.get("context", ""),
            "risk_flags": row.get("risk_flags") or [],
            "tokens": row.get("tokens") or [],
            "term_hits": row.get("term_hits") or [],
            "translations": {
                lang: (row.get("translations") or {}).get(lang, "") for lang in target_langs
            },
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _review_row(row: dict[str, Any], review_key: str, target_langs: list[str]) -> dict[str, object]:
    return {
        "review_key": review_key,
        "cn": str(row.get("cn") or ""),
        "translation_source": str(row.get("translation_source") or row.get("cn") or ""),
        "source_mode": str(row.get("source_mode") or "cn"),
        "reference_en": str(row.get("reference_en") or ""),
        "reference_en_status": str(row.get("reference_en_status") or "not_requested"),
        "context": str(row.get("context") or ""),
        "risk_flags": row.get("risk_flags") or [],
        "protected_tokens": row.get("tokens") or [],
        "term_hits": row.get("term_hits") or [],
        "translations": {
            lang: str((row.get("translations") or {}).get(lang) or "") for lang in target_langs
        },
    }


def _is_high_risk_review_row(row: dict[str, object]) -> bool:
    source = str(row.get("translation_source") or row.get("cn") or "")
    explicit = row.get("risk_flags") or []
    if isinstance(explicit, str):
        explicit = [explicit]
    return bool(
        len(source) > 300
        or len(row.get("protected_tokens") or []) >= 3
        or len(row.get("term_hits") or []) >= 3
        or explicit
    )


def _select_sampled_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    high_risk = [row for row in rows if _is_high_risk_review_row(row)]
    low_risk = [row for row in rows if not _is_high_risk_review_row(row)]
    sample_count = max(1, (len(low_risk) + 9) // 10) if low_risk else 0
    sampled_low = sorted(low_risk, key=lambda row: str(row["review_key"]))[:sample_count]
    selected = {str(row["review_key"]) for row in [*high_risk, *sampled_low]}
    return [row for row in rows if str(row["review_key"]) in selected]


def _batch_checkpoint(path: Path, version: str, rows: list[dict[str, Any]]) -> Path:
    raw = json.dumps(
        {"version": version, "rows": rows},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return path / f"{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}.jsonl"


def _client_checkpoint_identity(client: object) -> str:
    return str(
        getattr(
            client,
            "checkpoint_identity",
            f"{type(client).__module__}.{type(client).__qualname__}",
        )
    )


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _acquire_proofread_lock(proof_dir: Path) -> Path:
    lock_path = proof_dir / "proofread.lock"
    payload = json.dumps({"pid": os.getpid(), "started_at": time.time()})
    for _ in range(2):
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                existing = json.loads(lock_path.read_text(encoding="utf-8"))
                existing_pid = int(existing.get("pid") or 0)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                existing_pid = 0
            if _pid_is_running(existing_pid):
                raise RuntimeError(
                    f"deep proofreading is already running under pid {existing_pid}"
                )
            lock_path.unlink(missing_ok=True)
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
        return lock_path
    raise RuntimeError("could not acquire deep proofreading lock")


def _release_proofread_lock(lock_path: Path) -> None:
    try:
        existing = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return
    if int(existing.get("pid") or 0) == os.getpid():
        lock_path.unlink(missing_ok=True)


def _load_review_item_checkpoints(
    checkpoint_dir: Path,
    target_langs: list[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    reusable: dict[tuple[str, str], dict[str, Any]] = {}
    conflicts: set[tuple[str, str]] = set()
    allowed_langs = set(target_langs)
    for checkpoint in sorted(checkpoint_dir.glob("*.jsonl")):
        try:
            rows = _read_jsonl(checkpoint)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        for row in rows:
            review_key = str(row.get("review_key") or "")
            lang = str(row.get("lang") or "").upper()
            if not review_key or lang not in allowed_langs:
                continue
            try:
                normalized = _validate_suggestions(
                    [{"review_key": review_key}],
                    [row],
                    [lang],
                )[0]
            except ValueError:
                continue
            item_key = (review_key, lang)
            previous = reusable.get(item_key)
            if previous is not None and previous != normalized:
                conflicts.add(item_key)
                continue
            reusable[item_key] = normalized
    for item_key in conflicts:
        reusable.pop(item_key, None)
    return reusable


def _validate_suggestions(
    request_rows: list[dict[str, object]],
    suggestions: list[dict[str, object]],
    target_langs: list[str],
) -> list[dict[str, Any]]:
    current_by_cell = {
        (str(row["review_key"]), lang): str(
            ((row.get("translations") or {}).get(lang) or "")
        ).strip()
        for row in request_rows
        for lang in target_langs
    }
    expected = {
        (str(row["review_key"]), lang) for row in request_rows for lang in target_langs
    }
    actual = {
        (str(row.get("review_key") or ""), str(row.get("lang") or "").upper())
        for row in suggestions
    }
    if expected != actual or len(suggestions) != len(expected):
        raise ValueError(
            f"review coverage mismatch: missing={sorted(expected - actual)}, extras={sorted(actual - expected)}"
        )
    validated: list[dict[str, Any]] = []
    for row in suggestions:
        status = str(row.get("status") or "").upper()
        if status not in {"KEEP", "FIX"}:
            raise ValueError(f"invalid review status: {status}")
        suggested = str(row.get("suggested") or "").strip()
        if not suggested:
            cell = (str(row["review_key"]), str(row["lang"]).upper())
            if status == "KEEP":
                suggested = current_by_cell.get(cell, "")
            if not suggested:
                raise ValueError("review suggestion cannot be blank")
        validated.append(
            {
                "review_key": str(row["review_key"]),
                "lang": str(row["lang"]).upper(),
                "status": status,
                "suggested": suggested,
                "reason": str(row.get("reason") or ""),
                "owner": str(row.get("owner") or "api"),
            }
        )
    return validated


def _validate_audit(
    fixes: list[dict[str, Any]],
    decisions: list[dict[str, object]],
) -> dict[tuple[str, str], dict[str, Any]]:
    expected = {(row["review_key"], row["lang"]) for row in fixes}
    actual = {
        (str(row.get("review_key") or ""), str(row.get("lang") or "").upper())
        for row in decisions
    }
    if expected != actual or len(decisions) != len(expected):
        raise ValueError(
            f"audit coverage mismatch: missing={sorted(expected - actual)}, extras={sorted(actual - expected)}"
        )
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in decisions:
        decision = str(row.get("decision") or "").upper()
        if decision not in {"ACCEPT", "REVERT", "REVISE"}:
            raise ValueError(f"invalid audit decision: {decision}")
        final = str(row.get("final") or "").strip()
        if decision in {"ACCEPT", "REVISE"} and not final:
            raise ValueError("accepted audit decision requires final text")
        normalized = {
            "review_key": str(row["review_key"]),
            "lang": str(row["lang"]).upper(),
            "decision": decision,
            "final": final,
            "reason": str(row.get("reason") or ""),
        }
        result[(normalized["review_key"], normalized["lang"])] = normalized
    return result


def run_deep_proofread(
    manifest_path: Path,
    *,
    initial_cache: Path,
    reviewer: ReviewClient,
    auditor: AuditClient,
    batch_size: int = 60,
    workers: int = 4,
) -> ProofreadSummary:
    overall_started = time.perf_counter()
    manifest = load_manifest(manifest_path)
    target_langs = [str(lang).upper() for lang in manifest["inputs"]["target_languages"]]
    rows = _read_jsonl(initial_cache)
    signatures = [_review_signature(row, target_langs) for row in rows]
    representatives: dict[str, dict[str, Any]] = {}
    for row, signature in zip(rows, signatures, strict=True):
        representatives.setdefault(signature, row)
    review_rows = [
        _review_row(row, signature, target_langs)
        for signature, row in representatives.items()
    ]
    if str(manifest.get("inputs", {}).get("proofread_mode") or "full") == "sampled":
        review_rows = _select_sampled_rows(review_rows)
    proof_dir = Path(manifest["work_dir"]) / "deep_proofread"
    proof_dir.mkdir(parents=True, exist_ok=True)
    proofread_lock = _acquire_proofread_lock(proof_dir)
    suggestions_path = proof_dir / "review_suggestions.jsonl"
    audit_path = proof_dir / "audit_decisions.jsonl"
    final_cache = proof_dir / "final_cache.jsonl"
    summary_path = proof_dir / "proofread_apply_summary.json"

    review_started = time.perf_counter()
    try:
        start_phase(manifest, "subagent_review")
        suggestions: list[dict[str, object]] = []
        review_scope = hashlib.sha256(
            f"review-v1:{_client_checkpoint_identity(reviewer)}".encode("utf-8")
        ).hexdigest()[:16]
        review_checkpoint_dir = proof_dir / "review_batches" / review_scope
        review_checkpoint_dir.mkdir(parents=True, exist_ok=True)
        reusable = _load_review_item_checkpoints(review_checkpoint_dir, target_langs)
        review_jobs: list[tuple[list[dict[str, object]], str, Path]] = []
        for lang in target_langs:
            missing = [
                row for row in review_rows if (str(row["review_key"]), lang) not in reusable
            ]
            for index in range(0, len(missing), batch_size):
                batch = missing[index : index + batch_size]
                checkpoint = _batch_checkpoint(
                    review_checkpoint_dir,
                    f"review-v2:{lang}",
                    batch,
                )
                review_jobs.append((batch, lang, checkpoint))

        def review_missing(
            job: tuple[list[dict[str, object]], str, Path],
        ) -> list[dict[str, Any]]:
            batch, lang, checkpoint = job
            validation_error: ValueError | None = None
            for _ in range(3):
                batch_suggestions = reviewer.review_batch(batch, [lang])
                try:
                    validated_batch = _validate_suggestions(batch, batch_suggestions, [lang])
                    break
                except ValueError as exc:
                    validation_error = exc
            else:
                assert validation_error is not None
                raise validation_error
            _write_jsonl(checkpoint, validated_batch)
            return validated_batch

        if review_jobs:
            with ThreadPoolExecutor(
                max_workers=max(1, min(workers, len(review_jobs)))
            ) as pool:
                for batch_suggestions in pool.map(review_missing, review_jobs):
                    for suggestion in batch_suggestions:
                        reusable[(suggestion["review_key"], suggestion["lang"])] = suggestion
        suggestions = [
            reusable[(str(row["review_key"]), lang)]
            for row in review_rows
            for lang in target_langs
        ]
        validated = _validate_suggestions(review_rows, suggestions, target_langs)
        _write_jsonl(suggestions_path, validated)
        complete_phase(
            manifest,
            "subagent_review",
            started=review_started,
            metrics={
                "reviewed_unique_rows": len(review_rows),
                "reviewed_cells": len(validated),
                "review_api_batches": len(review_jobs),
                "review_reused_cells": len(validated)
                - sum(len(batch) for batch, _, _ in review_jobs),
            },
        )
    except BaseException as exc:
        fail_phase(manifest, "subagent_review", exc)
        _release_proofread_lock(proofread_lock)
        raise

    merge_started = time.perf_counter()
    try:
        start_phase(manifest, "controller_merge")
        fixes = [row for row in validated if row["status"] == "FIX"]
        decisions: list[dict[str, object]] = []
        audit_scope = hashlib.sha256(
            f"audit-v1:{_client_checkpoint_identity(auditor)}".encode("utf-8")
        ).hexdigest()[:16]
        audit_checkpoint_dir = proof_dir / "audit_batches" / audit_scope
        audit_checkpoint_dir.mkdir(parents=True, exist_ok=True)
        audit_jobs: list[tuple[list[dict[str, Any]], Path]] = []
        for index in range(0, len(fixes), batch_size):
            batch = fixes[index : index + batch_size]
            checkpoint = _batch_checkpoint(audit_checkpoint_dir, "audit-v1", batch)
            if checkpoint.exists():
                batch_decisions = _read_jsonl(checkpoint)
                _validate_audit(batch, batch_decisions)
                decisions.extend(batch_decisions)
            else:
                audit_jobs.append((batch, checkpoint))

        def audit_missing(
            job: tuple[list[dict[str, Any]], Path],
        ) -> list[dict[str, object]]:
            batch, checkpoint = job
            validation_error: ValueError | None = None
            for _ in range(3):
                batch_decisions = auditor.audit_batch(batch)
                try:
                    _validate_audit(batch, batch_decisions)
                    break
                except ValueError as exc:
                    validation_error = exc
            else:
                assert validation_error is not None
                raise validation_error
            _write_jsonl(checkpoint, batch_decisions)
            return batch_decisions

        if audit_jobs:
            with ThreadPoolExecutor(
                max_workers=max(1, min(workers, len(audit_jobs)))
            ) as pool:
                for batch_decisions in pool.map(audit_missing, audit_jobs):
                    decisions.extend(batch_decisions)
        audit = _validate_audit(fixes, decisions)
        _write_jsonl(audit_path, list(audit.values()))
        suggestions_by_cell = {
            (row["review_key"], row["lang"]): row for row in validated
        }
        changed_rows = 0
        changed_cells = 0
        changed_by_lang: Counter[str] = Counter()
        output_rows: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        for row, signature in zip(rows, signatures, strict=True):
            translations = dict(row.get("translations") or {})
            row_changed = False
            for lang in target_langs:
                suggestion = suggestions_by_cell.get((signature, lang))
                if suggestion is None:
                    continue
                if suggestion["status"] != "FIX":
                    continue
                decision = audit[(signature, lang)]
                if decision["decision"] == "REVERT":
                    continue
                final_text = decision["final"] or suggestion["suggested"]
                if final_text != translations.get(lang):
                    issues.append(
                        {
                            "key": row.get("key"),
                            "lang": lang,
                            "before": translations.get(lang, ""),
                            "after": final_text,
                            "reason": suggestion["reason"],
                            "audit_reason": decision["reason"],
                        }
                    )
                    translations[lang] = final_text
                    changed_cells += 1
                    changed_by_lang[lang] += 1
                    row_changed = True
            changed_rows += int(row_changed)
            output_rows.append({**row, "translations": translations})
        _write_jsonl(final_cache, output_rows)
        elapsed = round(time.perf_counter() - overall_started, 3)
        summary = ProofreadSummary(
            final_cache=final_cache,
            suggestions_jsonl=suggestions_path,
            audit_jsonl=audit_path,
            summary_json=summary_path,
            reviewed_rows=len(review_rows),
            reviewed_cells=len(review_rows) * len(target_langs),
            suggested_changes=len(fixes),
            reverted_changes=sum(1 for row in audit.values() if row["decision"] == "REVERT"),
            changed_rows=changed_rows,
            changed_cells=changed_cells,
            elapsed_seconds=elapsed,
        )
        payload = {
            **asdict(summary),
            "final_cache": str(final_cache),
            "suggestions_jsonl": str(suggestions_path),
            "audit_jsonl": str(audit_path),
            "summary_json": str(summary_path),
            "changed_by_language": dict(sorted(changed_by_lang.items())),
            "issues": issues,
        }
        _atomic_write_text(summary_path, json.dumps(payload, ensure_ascii=False, indent=2))
        manifest.setdefault("artifacts", {})["final_cache"] = str(final_cache)
        manifest["artifacts"]["proofread_summary"] = str(summary_path)
        complete_phase(
            manifest,
            "controller_merge",
            started=merge_started,
            metrics={
                "suggested_changes": summary.suggested_changes,
                "reverted_changes": summary.reverted_changes,
                "changed_cells": summary.changed_cells,
                "audit_api_batches": len(audit_jobs),
            },
        )
        _release_proofread_lock(proofread_lock)
        return summary
    except BaseException as exc:
        fail_phase(manifest, "controller_merge", exc)
        _release_proofread_lock(proofread_lock)
        raise
