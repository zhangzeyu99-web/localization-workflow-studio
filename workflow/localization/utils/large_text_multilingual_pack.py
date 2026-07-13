"""Fast workbook extraction for large multilingual localization packs."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from openpyxl import load_workbook

from utils.language_config import SOURCE_HEADERS, normalize_language_code, target_header_candidates
from utils.large_text_multilingual_gate import protected_tokens


@dataclass(frozen=True)
class PackArtifacts:
    items_jsonl: Path
    source_rows_jsonl: Path
    prepare_stats: Path
    source_rows: int
    unique_items: int
    estimated_target_cells: int
    elapsed_seconds: float


def stable_row_key(source_file: str, sheet: str, row: int, row_id: object) -> str:
    return f"{source_file}::{sheet}::{row_id}::{row}"


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _normalize_headers(values: tuple[Any, ...]) -> list[str]:
    return [str(value or "").strip().lower() for value in values]


def _find_header(headers: list[str], candidates: set[str]) -> int | None:
    return next((index for index, header in enumerate(headers) if header in candidates), None)


def _language_columns(
    headers: list[str],
    target_langs: list[str],
    *,
    excluded_columns: set[int] | None = None,
) -> dict[str, int]:
    excluded_columns = excluded_columns or set()
    columns: dict[str, int] = {}
    for raw_lang in target_langs:
        lang = normalize_language_code(raw_lang)
        candidates = target_header_candidates(lang)
        column = next(
            (index for index, header in enumerate(headers) if index not in excluded_columns and header in candidates),
            None,
        )
        if column is None:
            raise ValueError(f"missing target language column: {raw_lang}")
        columns[str(raw_lang).upper()] = column
    return columns


def _load_terms(path: Path | None, target_langs: list[str]) -> list[dict[str, Any]]:
    if path is None:
        return []
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in workbook.worksheets:
            iterator = sheet.iter_rows(values_only=True)
            first = next(iterator, ())
            headers = _normalize_headers(first)
            id_col = _find_header(headers, {"id", "key", "索引id"})
            source_col = _find_header(headers, {header.lower() for header in SOURCE_HEADERS})
            if source_col is None:
                continue
            try:
                language_columns = _language_columns(
                    headers,
                    target_langs,
                    excluded_columns={id_col} if id_col is not None else set(),
                )
            except ValueError:
                continue
            terms: dict[str, dict[str, str]] = {}
            for values in iterator:
                source = values[source_col] if source_col < len(values) else None
                if source in (None, ""):
                    continue
                translations = {
                    lang: str((values[column] if column < len(values) else "") or "").strip()
                    for lang, column in language_columns.items()
                }
                if all(translations.values()):
                    terms[str(source).strip()] = translations
            return [
                {"source": source, "translations": translations, "required": False}
                for source, translations in sorted(terms.items(), key=lambda item: len(item[0]), reverse=True)
            ]
    finally:
        workbook.close()
    return []


def _load_history(history_dirs: list[Path], target_langs: list[str]) -> dict[str, dict[str, str]]:
    memory: dict[str, dict[str, str]] = {}
    conflicts: set[str] = set()
    for directory in history_dirs:
        for path in sorted(directory.glob("*.xlsx")):
            workbook = load_workbook(path, read_only=True, data_only=True)
            try:
                for sheet in workbook.worksheets:
                    iterator = sheet.iter_rows(values_only=True)
                    first = next(iterator, ())
                    headers = _normalize_headers(first)
                    id_col = _find_header(headers, {"id", "key", "索引id"})
                    source_col = _find_header(headers, {header.lower() for header in SOURCE_HEADERS})
                    if source_col is None:
                        continue
                    try:
                        language_columns = _language_columns(
                            headers,
                            target_langs,
                            excluded_columns={id_col} if id_col is not None else set(),
                        )
                    except ValueError:
                        continue
                    for values in iterator:
                        source = values[source_col] if source_col < len(values) else None
                        if source in (None, ""):
                            continue
                        translations = {
                            lang: str((values[column] if column < len(values) else "") or "").strip()
                            for lang, column in language_columns.items()
                        }
                        if not all(translations.values()):
                            continue
                        source_text = str(source)
                        if source_text in memory and memory[source_text] != translations:
                            conflicts.add(source_text)
                        else:
                            memory[source_text] = translations
            finally:
                workbook.close()
    for source in conflicts:
        memory.pop(source, None)
    return memory


def _term_hits(text: str, terms: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    for term in terms:
        source = term["source"]
        if len(source) < 2 and source != text:
            continue
        start = text.find(source)
        if start < 0:
            continue
        end = start + len(source)
        if any(start < used_end and end > used_start for used_start, used_end in occupied):
            continue
        hits.append(term)
        occupied.append((start, end))
        if len(hits) >= limit:
            break
    return hits


def prepare_pack(
    *,
    inputs: list[Path],
    term_base: Path | None,
    history_dirs: list[Path],
    target_langs: list[str],
    work_dir: Path,
) -> PackArtifacts:
    started = time.perf_counter()
    target_langs = [str(lang).upper() for lang in target_langs]
    terms = _load_terms(term_base, target_langs)
    history = _load_history(history_dirs, target_langs)
    exact_terms = {term["source"]: term["translations"] for term in terms}
    rows: list[dict[str, Any]] = []
    seed_memory: dict[str, dict[str, str]] = {}

    for input_path in inputs:
        workbook = load_workbook(input_path, read_only=True, data_only=False)
        try:
            for sheet in workbook.worksheets:
                iterator = sheet.iter_rows(values_only=True)
                first = next(iterator, ())
                headers = _normalize_headers(first)
                id_col = _find_header(headers, {"id", "key", "索引id"})
                source_col = _find_header(headers, {header.lower() for header in SOURCE_HEADERS})
                if source_col is None:
                    continue
                language_columns = _language_columns(
                    headers,
                    target_langs,
                    excluded_columns={id_col} if id_col is not None else set(),
                )
                context = "ui" if "ui" in f"{input_path.stem} {sheet.title}".lower() else "language"
                for row_index, values in enumerate(iterator, 2):
                    source = values[source_col] if source_col < len(values) else None
                    row_id = values[id_col] if id_col is not None and id_col < len(values) else row_index
                    if source in (None, "") and row_id in (None, ""):
                        continue
                    if source in (None, ""):
                        raise ValueError(f"blank source text: {input_path.name}:{sheet.title}!R{row_index}")
                    for lang, column in language_columns.items():
                        target = values[column] if column < len(values) else None
                        if target not in (None, ""):
                            raise ValueError(
                                f"target column is not empty: {input_path.name}:{sheet.title}!R{row_index}:{lang}"
                            )
                    source_text = str(source)
                    if source_text in history:
                        seed_memory[source_text] = history[source_text]
                        seed_origin = "history"
                    elif source_text in exact_terms:
                        seed_memory[source_text] = exact_terms[source_text]
                        seed_origin = "glossary_exact"
                    else:
                        seed_origin = "api"
                    row = {
                        "key": stable_row_key(input_path.name, sheet.title, row_index, row_id),
                        "id": str(row_id),
                        "source_file": input_path.name,
                        "sheet": sheet.title,
                        "row": row_index,
                        "context": context,
                        "cn": source_text,
                        "tokens": protected_tokens({"cn": source_text}),
                        "term_hits": _term_hits(source_text, terms),
                        "seed_origin": seed_origin,
                        "translations": {},
                    }
                    rows.append(row)
        finally:
            workbook.close()

    work_dir.mkdir(parents=True, exist_ok=True)
    items_path = work_dir / "items.jsonl"
    source_rows_path = work_dir / "source_rows.jsonl"
    stats_path = work_dir / "prepare_stats.json"
    _write_jsonl(items_path, rows)
    _write_jsonl(
        source_rows_path,
        [
            {key: row[key] for key in ("key", "id", "source_file", "sheet", "row", "cn")}
            for row in rows
        ],
    )
    (work_dir / "seed_memory.json").write_text(
        json.dumps(seed_memory, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    elapsed = time.perf_counter() - started
    result = PackArtifacts(
        items_jsonl=items_path,
        source_rows_jsonl=source_rows_path,
        prepare_stats=stats_path,
        source_rows=len(rows),
        unique_items=len({row["cn"] for row in rows}),
        estimated_target_cells=len(rows) * len(target_langs),
        elapsed_seconds=elapsed,
    )
    stats_path.write_text(
        json.dumps({**asdict(result), "items_jsonl": str(items_path), "source_rows_jsonl": str(source_rows_path), "prepare_stats": str(stats_path)}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return result
