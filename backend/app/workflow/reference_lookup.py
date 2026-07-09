from __future__ import annotations

from typing import Any

from .. import db
from .announcement_shared import (
    _count_lookup_hits,
    _rank_translation_lookup_source,
    _suppress_overlapping_lookup_hits,
)

REFERENCE_HIT_MIN_LENGTH = 4
REFERENCE_HIT_LIMIT_PER_ROW = 20


def lookup_terms(text: str, terms: list[dict[str, Any]], *, min_length: int, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for term in terms:
        source = str(term.get("source") or "").strip()
        if len(source) < min_length or not (str(term.get("target") or "").strip() or str(term.get("target_alt") or "").strip()):
            continue
        hit_count, first_position = _count_lookup_hits(text, source)
        if not hit_count:
            continue
        rows.append(
            {
                "id": term.get("id"),
                "term_key": term.get("term_key", ""),
                "source": source,
                "target": term.get("target", ""),
                "target_alt": term.get("target_alt", ""),
                "language": term.get("language", "en"),
                "category": term.get("category", ""),
                "note": term.get("note", ""),
                "source_type": term.get("source_type", ""),
                "first_position": first_position,
                "hit_count": hit_count,
            }
        )
    return _suppress_overlapping_lookup_hits(rows)[:limit]


def lookup_translation_entries(text: str, entries: list[dict[str, Any]], *, min_length: int, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in entries:
        source = str(entry.get("source") or "").strip()
        if len(source) < min_length or not (str(entry.get("target") or "").strip() or str(entry.get("target_alt") or "").strip()):
            continue
        hit_count, first_position = _count_lookup_hits(text, source)
        if not hit_count:
            continue
        rows.append(
            {
                "id": entry.get("id"),
                "entry_key": entry.get("entry_key", ""),
                "source": source,
                "target": entry.get("target", ""),
                "target_alt": entry.get("target_alt", ""),
                "language": entry.get("language", "en"),
                "sheet": entry.get("sheet", ""),
                "row_number": entry.get("row_number", 0),
                "note": entry.get("note", ""),
                "source_type": entry.get("source_type", ""),
                "source_artifact_id": entry.get("source_artifact_id", ""),
                "first_position": first_position,
                "hit_count": hit_count,
                "_priority": _rank_translation_lookup_source(str(entry.get("source_type") or "")),
            }
        )
    rows.sort(key=lambda item: (int(item.get("first_position") or 0), item.get("_priority", 3), -len(str(item.get("source") or "")), str(item.get("source") or "")))
    accepted = _suppress_overlapping_lookup_hits(rows)[:limit]
    for row in accepted:
        row.pop("_priority", None)
    return accepted


def compact_reference_hit(hit: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": hit.get("source", ""),
        "target": hit.get("target", ""),
        "target_alt": hit.get("target_alt", ""),
        "source_type": hit.get("source_type", ""),
        "sheet": hit.get("sheet", ""),
        "row_number": hit.get("row_number", 0),
    }


def attach_reference_hits(rows: list[dict[str, Any]], project_id: str, language: str) -> dict[str, Any]:
    """Attach translation-archive ``reference_hits`` to workpack rows in place.

    Returns an audit summary. Rows with no archive match get an empty list so
    downstream consumers (prompt builder, batch fingerprint) see a stable shape.
    """
    archive_rows = db.list_translation_entries(project_id, language=language)
    hit_rows = 0
    total_hits = 0
    for row in rows:
        source = str(row.get("source") or "")
        hits = (
            lookup_translation_entries(source, archive_rows, min_length=REFERENCE_HIT_MIN_LENGTH, limit=REFERENCE_HIT_LIMIT_PER_ROW)
            if archive_rows
            else []
        )
        row["reference_hits"] = [compact_reference_hit(hit) for hit in hits]
        if hits:
            hit_rows += 1
            total_hits += len(hits)
    return {
        "language": language,
        "archive_entries": len(archive_rows),
        "total_rows": len(rows),
        "reference_hit_rows": hit_rows,
        "reference_hits": total_hits,
    }
