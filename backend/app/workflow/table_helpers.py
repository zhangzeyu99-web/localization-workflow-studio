from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from ..languages import PROJECT_LANGUAGE_ORDER, SOURCE_HEADER_ALIASES, alt_aliases, require_supported_language, target_aliases

LANGUAGE_ORDER = PROJECT_LANGUAGE_ORDER
AUTO_LANGUAGE_TARGET_ALIASES = {code: tuple(target_aliases(code)) for code in LANGUAGE_ORDER}
AUTO_LANGUAGE_ALT_ALIASES = {code: tuple(alt_aliases(code)) for code in LANGUAGE_ORDER}


def _wide_source_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).casefold()


def _normalized_header_indices(headers: list[str]) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for index, header in enumerate(headers):
        key = str(header or "").strip().lower()
        if key and key not in normalized:
            normalized[key] = index
    return normalized


def _column_index(normalized_headers: dict[str, int], explicit: str | None, candidates: list[str], required: bool = True) -> int | None:
    if explicit:
        hit = normalized_headers.get(explicit.strip().lower())
        if hit is not None:
            return hit
        if required:
            raise KeyError(f"column not found: {explicit}")
    for candidate in candidates:
        hit = normalized_headers.get(candidate.lower())
        if hit is not None:
            return hit
    if required:
        raise KeyError(f"none of columns found: {', '.join(candidates)}")
    return None


def _value_at(row: tuple[Any, ...], index: int | None) -> str:
    if index is None or index < 0 or index >= len(row):
        return ""
    value = row[index]
    return "" if value is None else str(value).strip()


def _auto_language_indices(headers: list[str], reserved_indices: set[int] | None = None) -> dict[str, tuple[int, int | None]]:
    reserved = reserved_indices or set()
    normalized_headers: dict[str, int] = {}
    for index, header in enumerate(headers):
        if index in reserved:
            continue
        key = str(header or "").strip().lower()
        if key:
            normalized_headers[key] = index
    detected: dict[str, tuple[int, int | None]] = {}
    for code in LANGUAGE_ORDER:
        target_idx = _column_index(normalized_headers, None, list(AUTO_LANGUAGE_TARGET_ALIASES[code]), required=False)
        if target_idx is None:
            continue
        alt_idx = None
        if code == "en":
            alt_idx = _column_index(normalized_headers, None, list(AUTO_LANGUAGE_ALT_ALIASES["en"]), required=False)
        detected[code] = (target_idx, alt_idx)
    return detected


def _read_glossary_rows(
    path: Path,
    sheet: str | None = None,
    term_key_column: str | None = None,
    source_column: str | None = None,
    target_column: str | None = None,
    target_alt_column: str | None = None,
    category_column: str | None = None,
    note_column: str | None = None,
    language: str = "en",
    limit: int | None = 100,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    language = require_supported_language(language)
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        headers = [str(cell.value or "").strip() for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        normalized = {header.lower(): index for index, header in enumerate(headers) if header}
        term_key_idx = _column_index(normalized, term_key_column, ["id", "key", "编号", "序号"], required=False)
        source_idx = _column_index(normalized, source_column, list(SOURCE_HEADER_ALIASES))
        target_idx = _column_index(normalized, target_column, target_aliases(language))
        target_alt_idx = _column_index(normalized, target_alt_column, alt_aliases(language), required=False)
        category_idx = _column_index(normalized, category_column, ["category", "type", "分类", "类别", "类型"], required=False)
        note_idx = _column_index(normalized, note_column, ["note", "notes", "comment", "备注"], required=False)
        rows = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if limit is not None and len(rows) >= limit:
                break
            source = _value_at(row, source_idx)
            target = _value_at(row, target_idx)
            if not source and not target:
                continue
            rows.append(
                {
                    "term_key": _value_at(row, term_key_idx) if term_key_idx is not None else "",
                    "source": source,
                    "target": target,
                    "target_alt": _value_at(row, target_alt_idx) if target_alt_idx is not None else "",
                    "category": _value_at(row, category_idx) if category_idx is not None else "",
                    "note": _value_at(row, note_idx) if note_idx is not None else "",
                }
            )
        return rows, {
            "term_key": headers[term_key_idx] if term_key_idx is not None else "",
            "source": headers[source_idx],
            "target": headers[target_idx],
            "target_alt": headers[target_alt_idx] if target_alt_idx is not None else "",
            "category": headers[category_idx] if category_idx is not None else "",
            "note": headers[note_idx] if note_idx is not None else "",
        }
    finally:
        wb.close()
