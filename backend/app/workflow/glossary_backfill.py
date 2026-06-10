from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .. import db
from ..languages import require_supported_language
from .glossary_keys import _fill_blank_glossary_fields, _glossary_source_key, _glossary_term_rank
from .table_helpers import _read_glossary_rows


def backfill_project_glossary_from_final(project_id: str, final_output: Path, run_id: str | None = None, language: str = "en") -> dict[str, Any]:
    """Stage generated high-frequency terms for review without changing the project glossary."""
    language = require_supported_language(language)
    result = {
        "candidates": 0,
        "unique_candidates": 0,
        "inserted": 0,
        "updated": 0,
        "skipped_existing": 0,
        "skipped_empty": 0,
        "skipped_duplicate": 0,
        "conflicts": 0,
        "pending_confirmation": 0,
        "batch_id": "",
    }
    if not final_output.exists():
        if run_id:
            db.add_event(run_id, "Glossary backfill skipped: generated ID/CN/EN/EN2 file was not found.", level="warn")
        return result

    # The embedded glossary extractor keeps legacy output headers as EN/EN2 even
    # when the source target column is KR/JP/etc. Interpret those generated
    # columns as the current run language only in this controlled backfill path.
    rows, _columns = _read_glossary_rows(final_output, limit=None, language=language, target_column="EN", target_alt_column="EN2")
    result["candidates"] = len(rows)

    existing: dict[str, dict[str, Any]] = {}
    for term in db.list_glossary_terms(project_id, language=language):
        source_key = _glossary_source_key(term.get("source"))
        if not source_key:
            continue
        current = existing.get(source_key)
        if current is None or _glossary_term_rank(term) < _glossary_term_rank(current):
            existing[source_key] = term

    deduped_rows: dict[str, dict[str, Any]] = {}
    for row in rows:
        source = str(row.get("source") or "").strip()
        source_key = _glossary_source_key(source)
        if not source_key:
            result["skipped_empty"] += 1
            continue
        current = deduped_rows.get(source_key)
        if current:
            result["skipped_duplicate"] += 1
            _fill_blank_glossary_fields(current, row)
            continue
        deduped_rows[source_key] = dict(row, source=source)

    result["unique_candidates"] = len(deduped_rows)
    batch = db.create_glossary_batch(
        project_id,
        run_id=run_id,
        source_artifact_id="",
        label=f"Glossary scan {datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d%H%M')}",
        metadata={"strategy": "stage_candidates_then_accept", "source": str(final_output)},
        language=language,
    )
    result["batch_id"] = batch["id"]
    if run_id:
        db.add_event(
            run_id,
            "Glossary backfill strategy: dedupe by normalized CN; stage only missing CN as review candidates; "
            "existing project glossary terms are skipped and never auto-filled.",
        )

    for source_key, row in deduped_rows.items():
        source = str(row.get("source") or "").strip()
        target = str(row.get("target") or "").strip()
        target_alt = str(row.get("target_alt") or "").strip()
        current = existing.get(source_key)
        if current:
            result["skipped_existing"] += 1
            existing[source_key] = current
            continue

        db.add_glossary_candidate(
            project_id,
            batch["id"],
            {
                "term_key": row.get("term_key", ""),
                "source": source,
                "target": target,
                "target_alt": target_alt,
                "language": language,
                "category": row.get("category", ""),
                "note": row.get("note", "") or ("高频词候选，需补译后人工确认" if not target and not target_alt else "高频词候选，需人工确认"),
                "action": "new",
            },
        )
        result["inserted"] += 1
        result["pending_confirmation"] += 1

    if run_id:
        db.add_event(
            run_id,
            "Glossary backfill result: "
            f"candidates={result['candidates']}, unique={result['unique_candidates']}, inserted={result['inserted']}, "
            f"updated={result['updated']}, existing={result['skipped_existing']}, duplicates={result['skipped_duplicate']}, "
            f"conflicts={result['conflicts']}, empty={result['skipped_empty']}.",
        )
    return result

