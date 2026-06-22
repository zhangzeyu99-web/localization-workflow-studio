from __future__ import annotations

from typing import Any

from .announcement_shared import (
    _count_lookup_hits,
    _rank_translation_lookup_source,
    _suppress_overlapping_lookup_hits,
)


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
