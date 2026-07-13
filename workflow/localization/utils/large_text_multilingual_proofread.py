"""Suggestion-only deep proofreading with controller-owned audit and apply."""
from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
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
            "context": row.get("context", ""),
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
        "context": str(row.get("context") or ""),
        "protected_tokens": row.get("tokens") or [],
        "term_hits": row.get("term_hits") or [],
        "translations": {
            lang: str((row.get("translations") or {}).get(lang) or "") for lang in target_langs
        },
    }


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


def _validate_suggestions(
    request_rows: list[dict[str, object]],
    suggestions: list[dict[str, object]],
    target_langs: list[str],
) -> list[dict[str, Any]]:
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
    proof_dir = Path(manifest["work_dir"]) / "deep_proofread"
    proof_dir.mkdir(parents=True, exist_ok=True)
    suggestions_path = proof_dir / "review_suggestions.jsonl"
    audit_path = proof_dir / "audit_decisions.jsonl"
    final_cache = proof_dir / "final_cache.jsonl"
    summary_path = proof_dir / "proofread_apply_summary.json"

    review_started = time.perf_counter()
    start_phase(manifest, "subagent_review")
    try:
        suggestions: list[dict[str, object]] = []
        review_scope = hashlib.sha256(
            f"review-v1:{_client_checkpoint_identity(reviewer)}".encode("utf-8")
        ).hexdigest()[:16]
        review_checkpoint_dir = proof_dir / "review_batches" / review_scope
        review_checkpoint_dir.mkdir(parents=True, exist_ok=True)
        for index in range(0, len(review_rows), batch_size):
            batch = review_rows[index : index + batch_size]
            checkpoint = _batch_checkpoint(review_checkpoint_dir, "review-v1", batch)
            if checkpoint.exists():
                batch_suggestions = _read_jsonl(checkpoint)
            else:
                batch_suggestions = reviewer.review_batch(batch, target_langs)
                _validate_suggestions(batch, batch_suggestions, target_langs)
                _write_jsonl(checkpoint, batch_suggestions)
            _validate_suggestions(batch, batch_suggestions, target_langs)
            suggestions.extend(batch_suggestions)
        validated = _validate_suggestions(review_rows, suggestions, target_langs)
        _write_jsonl(suggestions_path, validated)
        complete_phase(
            manifest,
            "subagent_review",
            started=review_started,
            metrics={"reviewed_unique_rows": len(review_rows), "reviewed_cells": len(validated)},
        )
    except BaseException as exc:
        fail_phase(manifest, "subagent_review", exc)
        raise

    merge_started = time.perf_counter()
    start_phase(manifest, "controller_merge")
    try:
        fixes = [row for row in validated if row["status"] == "FIX"]
        decisions: list[dict[str, object]] = []
        audit_scope = hashlib.sha256(
            f"audit-v1:{_client_checkpoint_identity(auditor)}".encode("utf-8")
        ).hexdigest()[:16]
        audit_checkpoint_dir = proof_dir / "audit_batches" / audit_scope
        audit_checkpoint_dir.mkdir(parents=True, exist_ok=True)
        for index in range(0, len(fixes), batch_size):
            batch = fixes[index : index + batch_size]
            checkpoint = _batch_checkpoint(audit_checkpoint_dir, "audit-v1", batch)
            if checkpoint.exists():
                batch_decisions = _read_jsonl(checkpoint)
            else:
                batch_decisions = auditor.audit_batch(batch)
                _validate_audit(batch, batch_decisions)
                _write_jsonl(checkpoint, batch_decisions)
            _validate_audit(batch, batch_decisions)
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
                suggestion = suggestions_by_cell[(signature, lang)]
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
            reviewed_rows=len(rows),
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
            },
        )
        return summary
    except BaseException as exc:
        fail_phase(manifest, "controller_merge", exc)
        raise
