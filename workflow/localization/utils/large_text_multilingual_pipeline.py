"""One-command orchestration for large multilingual XLSX localization packs."""
from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from utils.large_text_multilingual_executor import (
    OpenAICompatibleClient,
    TranslationClient,
    _atomic_write_text,
    complete_phase,
    fail_phase,
    start_phase,
    translate_manifest,
)
from utils.large_text_multilingual_gate import apply_dry_run, cache_lint, readback_gate
from utils.large_text_multilingual_pack import prepare_pack
from utils.large_text_multilingual_proofread import AuditClient, ReviewClient, run_deep_proofread
from utils.large_text_multilingual_runner import build_manifest, load_manifest, save_manifest
from utils.xlsx_translation_writeback import verify_translation_cache, write_translation_workbooks


@dataclass(frozen=True)
class PipelineResult:
    manifest: Path
    delivery_dir: Path
    retro_metrics: Path
    source_rows: int
    unique_items: int
    hard_blockers: int
    elapsed_seconds: float


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _run_gate_phase(
    manifest_path: Path,
    phase: str,
    callback: Any,
) -> Any:
    manifest = load_manifest(manifest_path)
    started = time.perf_counter()
    start_phase(manifest, phase)
    try:
        result = callback()
        complete_phase(manifest, phase, started=started)
        return result
    except BaseException as exc:
        fail_phase(manifest, phase, exc)
        raise


def _qa_summary(
    path: Path,
    *,
    source_rows: int,
    unique_items: int,
    target_langs: list[str],
    cache_result: dict[str, Any],
    readback_result: dict[str, Any] | None,
    proof_summary: Any,
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Summary"
    sheet.append(["Metric", "Value"])
    values = [
        ("Source rows", source_rows),
        ("Unique items", unique_items),
        ("Target languages", ", ".join(target_langs)),
        ("Estimated target cells", source_rows * len(target_langs)),
        ("Cache hard blockers", cache_result.get("hard_blockers", 0)),
        ("Readback hard blockers", (readback_result or {}).get("hard_blockers", "pending")),
        ("Deep proofreading", "completed" if proof_summary else "not triggered"),
        ("Suggested changes", getattr(proof_summary, "suggested_changes", 0)),
        ("Reverted changes", getattr(proof_summary, "reverted_changes", 0)),
        ("Final changed cells", getattr(proof_summary, "changed_cells", 0)),
    ]
    for row in values:
        sheet.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()


def run_pipeline(
    *,
    inputs: list[Path],
    term_base: Path | None,
    history_dirs: list[Path],
    target_langs: list[str],
    task_dir: Path,
    relay_config: Path | None,
    proofread_mode: str,
    translation_client: TranslationClient | None = None,
    reviewer: ReviewClient | None = None,
    auditor: AuditClient | None = None,
    delivery_dir: Path | None = None,
    batch_size: int = 60,
    workers: int = 4,
    proofread_batch_size: int | None = None,
    proofread_workers: int | None = None,
    source_mode: str = "cn",
) -> PipelineResult:
    started = time.perf_counter()
    target_langs = [str(lang).upper() for lang in target_langs]
    reserved_names = {"qa摘要.xlsx", "qa_summary.xlsx"}
    conflicts = sorted(path.name for path in inputs if path.name.casefold() in reserved_names)
    if conflicts:
        raise ValueError(f"input uses reserved delivery file name: {conflicts}")
    work_dir = task_dir / "_work" / "large_text_multilingual"
    pack = prepare_pack(
        inputs=inputs,
        term_base=term_base,
        history_dirs=history_dirs,
        target_langs=target_langs,
        work_dir=work_dir,
        source_mode=source_mode,
    )
    manifest = build_manifest(
        work_dir=work_dir,
        items_jsonl=pack.items_jsonl,
        source_rows_jsonl=pack.source_rows_jsonl,
        target_langs=target_langs,
        workbook_count=len(inputs),
        relay_config=relay_config,
        proofread_mode=proofread_mode,
        source_mode=source_mode,
    )
    manifest_path = Path(manifest["manifest_path"])
    shared_client = translation_client
    if shared_client is None:
        if relay_config is None:
            raise ValueError("relay_config is required for a real pipeline run")
        shared_client = OpenAICompatibleClient(relay_config)
    translation = translate_manifest(
        manifest_path,
        relay_config=relay_config,
        client=shared_client,
        batch_size=batch_size,
        workers=workers,
    )

    initial_lint_path = work_dir / "cache_lint.json"

    def lint_initial() -> dict[str, Any]:
        result = cache_lint(
            translation.cache_jsonl,
            target_langs=target_langs,
            term_base=term_base,
        )
        _write_json(initial_lint_path, result)
        if result["hard_blockers"]:
            raise ValueError(f"cache-lint failed with {result['hard_blockers']} hard blockers")
        return result

    lint_result = _run_gate_phase(manifest_path, "incremental_cache_lint", lint_initial)
    final_cache = translation.cache_jsonl
    proof_summary = None
    if proofread_mode in {"sampled", "full"}:
        effective_reviewer = reviewer or shared_client
        effective_auditor = auditor or shared_client
        if not hasattr(effective_reviewer, "review_batch") or not hasattr(effective_auditor, "audit_batch"):
            raise ValueError("deep proofreading requires reviewer and auditor clients")
        proof_summary = run_deep_proofread(
            manifest_path,
            initial_cache=translation.cache_jsonl,
            reviewer=effective_reviewer,  # type: ignore[arg-type]
            auditor=effective_auditor,  # type: ignore[arg-type]
            batch_size=proofread_batch_size or batch_size,
            workers=proofread_workers or workers,
        )
        final_cache = proof_summary.final_cache
        final_lint_path = work_dir / "final_cache_lint.json"

        def lint_final() -> dict[str, Any]:
            result = cache_lint(
                final_cache,
                target_langs=target_langs,
                term_base=term_base,
            )
            _write_json(final_lint_path, result)
            if result["hard_blockers"]:
                raise ValueError(
                    f"final cache-lint failed with {result['hard_blockers']} hard blockers"
                )
            return result

        lint_result = _run_gate_phase(manifest_path, "final_cache_lint", lint_final)

    dry_dir = work_dir / "apply_dry_run"
    dry_dir.mkdir(parents=True, exist_ok=True)

    def dry_run_all() -> list[dict[str, Any]]:
        results = [
            apply_dry_run(source, dry_dir / source.name)
            for source in inputs
        ]
        _write_json(work_dir / "apply_dry_run.json", {"ok": True, "files": results})
        return results

    _run_gate_phase(manifest_path, "apply_dry_run", dry_run_all)

    if delivery_dir is None:
        delivery_dir = task_dir / (
            f"{task_dir.name}_multilingual_delivery_{datetime.now():%Y%m%d_%H%M%S}"
        )
    if delivery_dir.exists() and any(delivery_dir.iterdir()):
        raise FileExistsError(f"delivery directory is not empty: {delivery_dir}")

    def write_outputs() -> Any:
        return write_translation_workbooks(
            inputs=inputs,
            cache_jsonl=final_cache,
            target_langs=target_langs,
            output_dir=delivery_dir,
        )

    write_result = _run_gate_phase(manifest_path, "write_outputs", write_outputs)
    qa_path = delivery_dir / "QA摘要.xlsx"
    _qa_summary(
        qa_path,
        source_rows=pack.source_rows,
        unique_items=pack.unique_items,
        target_langs=target_langs,
        cache_result=lint_result,
        readback_result=None,
        proof_summary=proof_summary,
    )

    readback_path = work_dir / "readback_gate.json"

    def verify_delivery() -> dict[str, Any]:
        result = readback_gate(delivery_dir, target_langs=target_langs)
        exact = verify_translation_cache(delivery_dir, final_cache, target_langs)
        result["cache_readback"] = exact
        result["issues"].extend(exact["issues"])
        result["hard_blockers"] += exact["hard_blockers"]
        result["hard_by_type"] = dict(
            sorted(Counter(issue["type"] for issue in result["issues"]).items())
        )
        result["readback_verified"] = result["hard_blockers"] == 0
        _write_json(readback_path, result)
        if result["hard_blockers"]:
            raise ValueError(
                f"readback-gate failed with {result['hard_blockers']} hard blockers"
            )
        return result

    readback_result = _run_gate_phase(manifest_path, "readback_gate", verify_delivery)
    _qa_summary(
        qa_path,
        source_rows=pack.source_rows,
        unique_items=pack.unique_items,
        target_langs=target_langs,
        cache_result=lint_result,
        readback_result=readback_result,
        proof_summary=proof_summary,
    )

    retro_dir = work_dir / "retro"
    retro_path = retro_dir / "large_text_multilingual_retro_metrics.json"
    manifest = load_manifest(manifest_path)
    retro_started = time.perf_counter()
    start_phase(manifest, "retro_metrics")
    complete_phase(manifest, "retro_metrics", started=retro_started)
    manifest = load_manifest(manifest_path)
    manifest["status"] = "complete"
    manifest["delivery_dir"] = str(delivery_dir)
    manifest.setdefault("artifacts", {})["retro_metrics"] = str(retro_path)
    save_manifest(manifest)
    retro = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_rows": pack.source_rows,
        "unique_items": pack.unique_items,
        "target_languages": target_langs,
        "estimated_target_cells": pack.estimated_target_cells,
        "prepare_seconds": pack.elapsed_seconds,
        "translation": asdict(translation),
        "proofread": asdict(proof_summary) if proof_summary else {"status": "not_triggered"},
        "writeback": asdict(write_result),
        "cache_lint": lint_result,
        "readback_gate": readback_result,
        "phase_metrics": manifest.get("phase_metrics", {}),
        "total_seconds": round(time.perf_counter() - started, 3),
    }
    _write_json(retro_path, retro)
    return PipelineResult(
        manifest=manifest_path,
        delivery_dir=delivery_dir,
        retro_metrics=retro_path,
        source_rows=pack.source_rows,
        unique_items=pack.unique_items,
        hard_blockers=int(readback_result["hard_blockers"]),
        elapsed_seconds=round(time.perf_counter() - started, 3),
    )
