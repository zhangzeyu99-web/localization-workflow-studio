from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook

from .. import db
from ..languages import alt_aliases, normalize_language, require_supported_language, target_aliases
from .common import project_dir
from .naming import _safe_delivery_name, _today_stamp, _visible_language_code
from .table_helpers import (
    LANGUAGE_ORDER,
    _auto_language_indices,
    _column_index,
    _normalized_header_indices,
    _read_glossary_rows,
    _value_at,
    _wide_source_key,
)

_LARGE_LANGUAGE_TABLE_ROW_THRESHOLD = 1000
COMPLETE_LANGUAGE_TABLE_GLOSSARY_IMPORT_MESSAGE = "这个文件看起来是完整语言表，不是项目术语表。请到「生成术语」或翻译流程 STEP5 做高频词扫描并生成术语候选，候选确认后才会进入项目术语库。"
COMPLETE_LANGUAGE_TABLE_PROJECT_MATERIAL_MESSAGE = "这个文件看起来是完整语言表，请上传到 STEP4「语言表」。它不会作为项目资料参与术语提取。"

def is_complete_language_table_for_glossary_import(path: Path, sheet: str | None = None, row_threshold: int = _LARGE_LANGUAGE_TABLE_ROW_THRESHOLD) -> bool:
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        return False
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        header_row = next(ws.iter_rows(min_row=1, max_row=1), None)
        if header_row is None:
            return False
        headers = [str(cell.value or "").strip() for cell in header_row]
        normalized = _normalized_header_indices(headers)
        term_key_idx = _column_index(normalized, None, ["id", "key", "编号", "序号"], required=False)
        source_idx = _column_index(normalized, None, ["source", "original", "cn", "zh", "chinese", "原文", "中文", "简体中文"], required=False)
        if term_key_idx is None or source_idx is None:
            return False
        reserved = {term_key_idx, source_idx}
        language_indices = _auto_language_indices(headers, reserved)
        if not language_indices:
            return False
        source_rows = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            if _value_at(row, source_idx):
                source_rows += 1
                if source_rows > row_threshold:
                    return True
        return False
    finally:
        wb.close()


def guard_complete_language_table_for_glossary_import(path: Path, sheet: str | None = None) -> None:
    if is_complete_language_table_for_glossary_import(path, sheet=sheet):
        raise ValueError(COMPLETE_LANGUAGE_TABLE_GLOSSARY_IMPORT_MESSAGE)


def guard_complete_language_table_for_project_material(path: Path, sheet: str | None = None) -> None:
    if is_complete_language_table_for_glossary_import(path, sheet=sheet):
        raise ValueError(COMPLETE_LANGUAGE_TABLE_PROJECT_MATERIAL_MESSAGE)


def preview_glossary_import(project_id: str, request: Any, import_all: bool = False) -> dict[str, Any]:
    project = db.get_project(project_id)
    _ = project
    artifact = db.get_artifact(request.artifact_id)
    path = Path(artifact["path"])
    guard_complete_language_table_for_glossary_import(path, sheet=getattr(request, "sheet", None))
    language = require_supported_language(getattr(request, "language", "en") or "en")
    auto_languages = bool(getattr(request, "auto_languages", True))
    if auto_languages and not getattr(request, "target_column", None) and not getattr(request, "target_alt_column", None):
        rows, columns, languages = _read_multilingual_glossary_rows(
            path,
            sheet=getattr(request, "sheet", None),
            term_key_column=getattr(request, "term_key_column", None),
            source_column=getattr(request, "source_column", None),
            category_column=getattr(request, "category_column", None),
            note_column=getattr(request, "note_column", None),
            limit=None if import_all else int(getattr(request, "limit", 100) or 100),
        )
        if languages:
            return {"artifact": artifact, "columns": columns, "rows": rows, "total_rows": len(rows), "language": "auto", "languages": languages}
    rows, columns = _read_glossary_rows(
        path,
        sheet=getattr(request, "sheet", None),
        term_key_column=getattr(request, "term_key_column", None),
        source_column=getattr(request, "source_column", None),
        target_column=getattr(request, "target_column", None),
        target_alt_column=getattr(request, "target_alt_column", None),
        category_column=getattr(request, "category_column", None),
        note_column=getattr(request, "note_column", None),
        language=language,
        limit=None if import_all else int(getattr(request, "limit", 100) or 100),
    )
    return {"artifact": artifact, "columns": columns, "rows": rows, "total_rows": len(rows), "language": language}


def import_glossary(project_id: str, request: Any) -> dict[str, Any]:
    preview = preview_glossary_import(project_id, request, import_all=True)
    language = preview["language"]
    payloads = []
    for row in preview["rows"]:
        if not row.get("source"):
            continue
        payloads.append(
            {
                "term_key": row.get("term_key", ""),
                "source": row.get("source", ""),
                "target": row.get("target", ""),
                "target_alt": row.get("target_alt", ""),
                "language": row.get("language") or language,
                "category": row.get("category", ""),
                "note": row.get("note", ""),
                "source_type": "imported",
                "confirmed": True,
            }
        )
    imported = db.upsert_glossary_terms_bulk(project_id, payloads)
    return {"imported_count": len(imported), "terms": imported, "preview": preview, "languages": preview.get("languages") or ([language] if language != "auto" else [])}


def export_glossary(project_id: str, fmt: str, language: str | None = None) -> dict[str, Any] | Path:
    project = db.get_project(project_id)
    language = require_supported_language(language or "en") if language else None
    terms = db.list_glossary_terms(project_id, language=language)
    if fmt == "json":
        return {
            "project_id": project_id,
            "language": language,
            "terms": [dict(zip(("term_key", "source", "target", "target_alt", "category", "note"), _glossary_export_row(term))) | {"language": term.get("language", "en")} for term in terms],
        }
    output_dir = project_dir(project_id) / "glossary" / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = _export_language_suffix(language)
    if language:
        columns = ["ID", "CN", _visible_language_code(language), *(["EN2"] if language == "en" else []), "分类", "备注"]
        rows = [_glossary_export_row(term, include_alt=language == "en") for term in terms]
    else:
        wide = list_glossary_wide(project_id)
        languages = list(wide.get("languages") or [])
        columns = ["ID", "CN", *_wide_language_columns(languages), "分类", "备注"]
        rows = _glossary_wide_export_rows(wide, languages)
    if fmt == "csv":
        path = output_dir / _export_filename(project, "glossary", suffix, "csv")
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(columns)
            writer.writerows(rows)
        return path
    path = output_dir / _export_filename(project, "glossary", suffix, "xlsx")
    wb = Workbook()
    ws = wb.active
    ws.title = "Glossary"
    ws.append(columns)
    for row in rows:
        ws.append(row)
    wb.save(path)
    wb.close()
    return path


def _export_language_suffix(language: str | None) -> str:
    return _visible_language_code(language) if language else "ALL"


def _export_filename(project: dict[str, Any], kind: str, suffix: str, ext: str) -> str:
    return f"{_safe_delivery_name(project['name'])}_{kind}_{suffix}_{_today_stamp()}.{ext}"


def _glossary_export_row(term: dict[str, Any], *, include_alt: bool = True) -> list[Any]:
    row = [
        term.get("term_key", ""),
        term.get("source", ""),
        term.get("target", ""),
    ]
    if include_alt:
        row.append(term.get("target_alt", ""))
    row.extend([term.get("category", ""), term.get("note", "")])
    return row


def _wide_language_columns(languages: list[str]) -> list[str]:
    columns: list[str] = []
    for code in languages:
        columns.append(_visible_language_code(code))
        if code == "en":
            columns.append("EN2")
    return columns


def _glossary_wide_export_rows(wide: dict[str, Any], languages: list[str]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for row in wide["rows"]:
        translations = row.get("translations") or {}
        values = [row.get("term_key", ""), row.get("source", "")]
        for code in languages:
            entry = translations.get(code) or {}
            values.append(entry.get("target", ""))
            if code == "en":
                values.append(entry.get("target_alt", ""))
        values.extend([row.get("category", ""), row.get("note", "")])
        rows.append(values)
    return rows


def import_translation_archive(project_id: str, request: Any, source_type: str = "imported") -> dict[str, Any]:
    language = require_supported_language(getattr(request, "language", "en") or "en")
    artifact = db.get_artifact(request.artifact_id)
    if artifact["project_id"] != project_id:
        raise KeyError("artifact")
    if bool(getattr(request, "auto_languages", True)) and not getattr(request, "target_column", None) and not getattr(request, "target_alt_column", None):
        rows = _read_multilingual_translation_rows(
            Path(artifact["path"]),
            sheet=getattr(request, "sheet", None),
            id_column=getattr(request, "id_column", None),
            source_column=getattr(request, "source_column", None),
            note_column=getattr(request, "note_column", None),
            source_artifact_id=artifact["id"],
            source_type=source_type,
        )
        if not rows:
            rows = _read_translation_rows(
                Path(artifact["path"]),
                sheet=getattr(request, "sheet", None),
                id_column=getattr(request, "id_column", None),
                source_column=getattr(request, "source_column", None),
                target_column=getattr(request, "target_column", None),
                target_alt_column=getattr(request, "target_alt_column", None),
                note_column=getattr(request, "note_column", None),
                language=language,
                source_artifact_id=artifact["id"],
                source_type=source_type,
            )
    else:
        rows = _read_translation_rows(
            Path(artifact["path"]),
            sheet=getattr(request, "sheet", None),
            id_column=getattr(request, "id_column", None),
            source_column=getattr(request, "source_column", None),
            target_column=getattr(request, "target_column", None),
            target_alt_column=getattr(request, "target_alt_column", None),
            note_column=getattr(request, "note_column", None),
            language=language,
            source_artifact_id=artifact["id"],
            source_type=source_type,
        )
    imported = db.upsert_translation_entries_bulk(project_id, [row for row in rows if row.get("source") or row.get("target")])
    languages = [code for code in LANGUAGE_ORDER if any(row.get("language") == code for row in rows)]
    return {"project_id": project_id, "artifact_id": artifact["id"], "imported_count": len(imported), "entries": imported, "languages": languages or [language]}


def archive_translation_artifact(project_id: str, artifact_id: str, language: str = "en", source_type: str = "qa_passed") -> dict[str, Any]:
    class Request:
        pass

    request = Request()
    request.artifact_id = artifact_id
    request.language = language
    request.sheet = None
    request.id_column = None
    request.source_column = None
    request.target_column = None
    request.target_alt_column = None
    request.note_column = None
    return import_translation_archive(project_id, request, source_type=source_type)


def export_translation_archive(project_id: str, fmt: str, language: str | None = None) -> dict[str, Any] | Path:
    project = db.get_project(project_id)
    language = require_supported_language(language or "en") if language else None
    entries = db.list_translation_entries(project_id, language=language)
    if fmt == "json":
        return {"project_id": project_id, "language": language, "entries": [_translation_export_payload(entry) for entry in entries]}
    output_dir = project_dir(project_id) / "translations" / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = _export_language_suffix(language)
    if language:
        columns = ["ID", "CN", _visible_language_code(language), *(["EN2"] if language == "en" else []), "备注"]
        rows = [_translation_export_row(entry, include_alt=language == "en") for entry in entries]
    else:
        wide = list_translation_archive_wide(project_id)
        languages = list(wide.get("languages") or [])
        columns = ["ID", "CN", *_wide_language_columns(languages), "备注"]
        rows = _translation_wide_export_rows(wide, languages)
    if fmt == "csv":
        path = output_dir / _export_filename(project, "translations", suffix, "csv")
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(columns)
            writer.writerows(rows)
        return path
    path = output_dir / _export_filename(project, "translations", suffix, "xlsx")
    wb = Workbook()
    ws = wb.active
    ws.title = "Translations"
    ws.append(columns)
    for row in rows:
        ws.append(row)
    wb.save(path)
    wb.close()
    return path


def list_glossary_wide(project_id: str) -> dict[str, Any]:
    db.get_project(project_id)
    rows = _wide_rows(
        db.list_glossary_terms(project_id),
        key_field="term_key",
        shared_fields=("term_key", "category", "note"),
    )
    return {"project_id": project_id, **rows}


def list_translation_archive_wide(project_id: str) -> dict[str, Any]:
    db.get_project(project_id)
    rows = _wide_rows(
        db.list_translation_entries(project_id),
        key_field="entry_key",
        shared_fields=("entry_key", "note"),
    )
    return {"project_id": project_id, **rows}


def _wide_rows(items: list[dict[str, Any]], *, key_field: str, shared_fields: tuple[str, ...]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        source_key = _wide_source_key(item.get("source"))
        if not source_key:
            continue
        grouped.setdefault(source_key, []).append(item)

    wide_rows: list[dict[str, Any]] = []
    coverage: dict[str, int] = {}
    for source_key, group in grouped.items():
        translations: dict[str, dict[str, Any]] = {}
        for code in LANGUAGE_ORDER:
            candidates = [item for item in group if normalize_language(item.get("language") or "en") == code and (str(item.get("target") or "").strip() or str(item.get("target_alt") or "").strip())]
            if not candidates:
                continue
            selected = sorted(candidates, key=lambda item: str(item.get("updated_at") or ""), reverse=True)[0]
            payload = {
                "id": selected.get("id", ""),
                "language": code,
                "target": selected.get("target", ""),
                "target_alt": selected.get("target_alt", ""),
            }
            translations[code] = payload
            coverage[code] = coverage.get(code, 0) + 1
        shared = {field: _first_non_blank(group, field) for field in shared_fields}
        wide_rows.append(
            {
                "source_key": source_key,
                "source": _first_non_blank(group, "source"),
                **shared,
                "translations": translations,
                "languages": [code for code in LANGUAGE_ORDER if code in translations],
                "conflicts": _wide_conflicts(group, ("source", *shared_fields)),
            }
        )

    languages = [code for code in LANGUAGE_ORDER if coverage.get(code, 0) > 0]
    wide_rows.sort(key=lambda row: (str(row.get("source") or ""), str(row.get(key_field) or "")))
    return {"languages": languages, "coverage": {code: coverage[code] for code in languages}, "row_count": len(wide_rows), "rows": wide_rows}



def _first_non_blank(rows: list[dict[str, Any]], field: str) -> str:
    for row in rows:
        value = str(row.get(field) or "").strip()
        if value and value != "-":
            return value
    return ""


def _wide_conflicts(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for field in fields:
        values: list[str] = []
        for row in rows:
            value = str(row.get(field) or "").strip()
            if value and value != "-" and value not in values:
                values.append(value)
        if len(values) > 1:
            conflicts.append({"field": field, "values": values})
    return conflicts



def _read_multilingual_glossary_rows(
    path: Path,
    sheet: str | None = None,
    term_key_column: str | None = None,
    source_column: str | None = None,
    category_column: str | None = None,
    note_column: str | None = None,
    limit: int | None = 100,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        return [], {}, []
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        headers = [str(cell.value or "").strip() for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        normalized = _normalized_header_indices(headers)
        term_key_idx = _column_index(normalized, term_key_column, ["id", "key", "编号", "序号"], required=False)
        source_idx = _column_index(normalized, source_column, ["source", "original", "cn", "zh", "chinese", "term", "原文", "中文", "术语"])
        category_idx = _column_index(normalized, category_column, ["category", "type", "分类", "类别", "类型"], required=False)
        note_idx = _column_index(normalized, note_column, ["note", "notes", "comment", "备注"], required=False)
        reserved = {index for index in (term_key_idx, source_idx, category_idx, note_idx) if index is not None}
        language_indices = _auto_language_indices(headers, reserved)
        if not language_indices:
            return [], {}, []
        rows: list[dict[str, Any]] = []
        source_rows = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            source = _value_at(row, source_idx)
            if not source:
                continue
            source_rows += 1
            if limit is not None and source_rows > limit:
                break
            for code, (target_idx, alt_idx) in language_indices.items():
                target = _value_at(row, target_idx)
                target_alt = _value_at(row, alt_idx) if code == "en" else ""
                if not target and not target_alt:
                    continue
                rows.append(
                    {
                        "term_key": _value_at(row, term_key_idx) if term_key_idx is not None else "",
                        "source": source,
                        "target": target,
                        "target_alt": target_alt,
                        "language": code,
                        "category": _value_at(row, category_idx) if category_idx is not None else "",
                        "note": _value_at(row, note_idx) if note_idx is not None else "",
                    }
                )
        return rows, {
            "term_key": headers[term_key_idx] if term_key_idx is not None else "",
            "source": headers[source_idx],
            "languages": {code: {"target": headers[target_idx], "target_alt": headers[alt_idx] if alt_idx is not None else ""} for code, (target_idx, alt_idx) in language_indices.items()},
            "category": headers[category_idx] if category_idx is not None else "",
            "note": headers[note_idx] if note_idx is not None else "",
        }, [code for code in LANGUAGE_ORDER if code in language_indices and any(row.get("language") == code for row in rows)]
    finally:
        wb.close()


def _read_multilingual_translation_rows(
    path: Path,
    sheet: str | None = None,
    id_column: str | None = None,
    source_column: str | None = None,
    note_column: str | None = None,
    source_artifact_id: str = "",
    source_type: str = "imported",
) -> list[dict[str, Any]]:
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        return []
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        headers = [str(cell.value or "").strip() for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        normalized = _normalized_header_indices(headers)
        id_idx = _column_index(normalized, id_column, ["id", "key", "编号", "序号"], required=False)
        source_idx = _column_index(normalized, source_column, ["source", "original", "cn", "zh", "chinese", "原文", "中文"])
        note_idx = _column_index(normalized, note_column, ["note", "notes", "comment", "备注"], required=False)
        reserved = {index for index in (id_idx, source_idx, note_idx) if index is not None}
        language_indices = _auto_language_indices(headers, reserved)
        if not language_indices:
            return []
        rows: list[dict[str, Any]] = []
        for row_index, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            source = _value_at(row, source_idx)
            if not source:
                continue
            for code, (target_idx, alt_idx) in language_indices.items():
                target = _value_at(row, target_idx)
                target_alt = _value_at(row, alt_idx) if code == "en" else ""
                if not target and not target_alt:
                    continue
                rows.append(
                    {
                        "entry_key": _value_at(row, id_idx) if id_idx is not None else "",
                        "source": source,
                        "target": target,
                        "target_alt": target_alt,
                        "language": code,
                        "sheet": ws.title,
                        "row_number": row_index,
                        "note": _value_at(row, note_idx) if note_idx is not None else "",
                        "source_type": source_type,
                        "source_artifact_id": source_artifact_id,
                    }
                )
        return rows
    finally:
        wb.close()


def _read_translation_rows(
    path: Path,
    sheet: str | None = None,
    id_column: str | None = None,
    source_column: str | None = None,
    target_column: str | None = None,
    target_alt_column: str | None = None,
    note_column: str | None = None,
    language: str = "en",
    source_artifact_id: str = "",
    source_type: str = "imported",
) -> list[dict[str, Any]]:
    language = require_supported_language(language)
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_rows = payload.get("entries") if isinstance(payload, dict) else payload
        rows = []
        for row in (raw_rows or []):
            if not isinstance(row, dict):
                continue
            normalized = {str(key or "").strip().lower(): value for key, value in row.items()}
            rows.append(_translation_row_from_mapping(normalized, int(row.get("row_number") or 0), str(row.get("sheet") or "").strip(), language, source_artifact_id, source_type))
        return rows
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = []
            for index, row in enumerate(reader, start=2):
                normalized = {str(key or "").strip().lower(): value for key, value in row.items()}
                rows.append(_translation_row_from_mapping(normalized, index, "", language, source_artifact_id, source_type))
            return rows

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        headers = [str(cell.value or "").strip() for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        normalized = {header.lower(): index for index, header in enumerate(headers) if header}
        id_idx = _column_index(normalized, id_column, ["id", "key", "编号", "序号"], required=False)
        source_idx = _column_index(normalized, source_column, ["source", "original", "cn", "zh", "chinese", "原文", "中文"])
        target_idx = _column_index(normalized, target_column, target_aliases(language))
        target_alt_idx = _column_index(normalized, target_alt_column, alt_aliases(language), required=False)
        note_idx = _column_index(normalized, note_column, ["note", "notes", "comment", "备注"], required=False)
        rows = []
        for row_index, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            source = _value_at(row, source_idx)
            target = _value_at(row, target_idx)
            if not source and not target:
                continue
            rows.append(
                {
                    "entry_key": _value_at(row, id_idx) if id_idx is not None else "",
                    "source": source,
                    "target": target,
                    "target_alt": _value_at(row, target_alt_idx) if target_alt_idx is not None else "",
                    "language": language,
                    "sheet": ws.title,
                    "row_number": row_index,
                    "note": _value_at(row, note_idx) if note_idx is not None else "",
                    "source_type": source_type,
                    "source_artifact_id": source_artifact_id,
                }
            )
        return rows
    finally:
        wb.close()


def _translation_row_from_mapping(
    row: dict[str, Any],
    row_number: int,
    sheet: str,
    language: str,
    source_artifact_id: str,
    source_type: str,
) -> dict[str, Any]:
    language = require_supported_language(language)
    def pick(*names: str) -> str:
        for name in names:
            value = row.get(name.lower())
            if value not in (None, ""):
                return str(value).strip()
        return ""

    return {
        "entry_key": pick("id", "key", "entry_key", "编号", "序号"),
        "source": pick("cn", "source", "original", "原文", "中文"),
        "target": pick("target", *target_aliases(language)),
        "target_alt": pick("target_alt", *alt_aliases(language)),
        "language": language,
        "sheet": sheet,
        "row_number": row_number,
        "note": pick("note", "notes", "comment", "备注"),
        "source_type": source_type,
        "source_artifact_id": source_artifact_id,
    }


def _translation_export_payload(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "entry_key": entry.get("entry_key", ""),
        "source": entry.get("source", ""),
        "target": entry.get("target", ""),
        "target_alt": entry.get("target_alt", ""),
        "language": entry.get("language", "en"),
        "note": entry.get("note", ""),
    }


def _translation_export_row(entry: dict[str, Any], *, include_alt: bool = True) -> list[Any]:
    row = [
        entry.get("entry_key", ""),
        entry.get("source", ""),
        entry.get("target", ""),
    ]
    if include_alt:
        row.append(entry.get("target_alt", ""))
    row.append(entry.get("note", ""))
    return row


def _translation_wide_export_rows(wide: dict[str, Any], languages: list[str]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for row in wide["rows"]:
        translations = row.get("translations") or {}
        values = [row.get("entry_key", ""), row.get("source", "")]
        for code in languages:
            entry = translations.get(code) or {}
            values.append(entry.get("target", ""))
            if code == "en":
                values.append(entry.get("target_alt", ""))
        values.append(row.get("note", ""))
        rows.append(values)
    return rows
