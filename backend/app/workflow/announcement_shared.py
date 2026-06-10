from __future__ import annotations

from typing import Any

ANNOUNCEMENT_STEP = {
    "source": 1,
    "constraints": 2,
    "languages": 3,
    "terms": 4,
    "lookup": 5,
    "prepare": 6,
    "translate": 7,
    "apply": 8,
    "deliver": 9,
}


def _count_lookup_hits(text: str, needle: str) -> tuple[int, int]:
    if not needle:
        return (0, -1)
    count = 0
    first = -1
    start = 0
    while True:
        index = text.find(needle, start)
        if index < 0:
            break
        if first < 0:
            first = index
        count += 1
        start = index + max(1, len(needle))
    return (count, first)


def _suppress_overlapping_lookup_hits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    spans: list[tuple[int, int]] = []
    for row in sorted(rows, key=lambda item: (int(item.get("first_position") or 0), -len(str(item.get("source") or "")), str(item.get("source") or ""))):
        start = int(row.get("first_position") or 0)
        end = start + len(str(row.get("source") or ""))
        if any(start < existing_end and end > existing_start for existing_start, existing_end in spans):
            continue
        accepted.append(row)
        spans.append((start, end))
    return accepted


def _rank_translation_lookup_source(source_type: str) -> int:
    priority = {
        "qa_passed": 0,
        "qa_final": 0,
        "manual": 1,
        "imported": 2,
        "archive": 2,
        "translation_archive": 2,
    }
    return priority.get(str(source_type or "").strip().lower(), 3)


def _announcement_task_metadata(task: dict[str, Any]) -> dict[str, Any]:
    metadata = task.get("metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}
