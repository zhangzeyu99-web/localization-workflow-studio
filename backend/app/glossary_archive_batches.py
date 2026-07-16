from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import db
from .archive_batch_engine import (
    ArchiveBatchError,
    ArchiveEntityAdapter,
    commit_archive_batch,
    file_checksum,
    hash_json,
    list_archive_import_batches,
    persist_archive_analysis,
    rollback_archive_import_batch,
)
from .languages import normalize_language, require_supported_language
from .workflow.asset_import_export import _read_multilingual_glossary_rows
from .workflow.table_helpers import LANGUAGE_ORDER, _read_glossary_rows


ARCHIVE_KIND = "glossary"
CHANGE_SAMPLE_LIMIT = 50
CSV_SHEET_KEY = "__csv__"
JSON_SHEET_KEY = "__json__"
DIRECT_GLOSSARY_KINDS = frozenset(
    {"term_base", "glossary_detail", "announcement_glossary", "glossary_final"}
)
PROTECTED_GLOSSARY_SOURCES = frozenset(
    {"manual", "curated", "qa_passed", "qa_final", "delivered_with_issues"}
)
GLOSSARY_FIELDS = (
    "id",
    "project_id",
    "term_key",
    "source",
    "source_key",
    "target",
    "target_alt",
    "language",
    "category",
    "note",
    "source_type",
    "confirmed",
    "active",
    "dataset_key",
    "last_import_batch_id",
    "review_status",
    "created_at",
    "updated_at",
)


@dataclass(frozen=True)
class ParsedGlossaryArtifact:
    rows: list[dict[str, Any]]
    columns: dict[str, Any]
    sheet: str
    languages: list[str]


def _source_key(value: Any) -> str:
    return "".join(str(value or "").split()).casefold()


def _request_payload(request: Any) -> dict[str, Any]:
    if hasattr(request, "model_dump"):
        return dict(request.model_dump())
    return {key: value for key, value in vars(request).items() if not key.startswith("_")}


def _glossary_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    normalized = {field: payload.get(field) for field in GLOSSARY_FIELDS}
    normalized["confirmed"] = bool(normalized["confirmed"])
    return normalized


def _glossary_hash(row: sqlite3.Row | dict[str, Any] | None) -> str:
    return hash_json(_glossary_row(row)) if row is not None else ""


def _state_checksum(rows: Iterable[sqlite3.Row | dict[str, Any]]) -> str:
    normalized = sorted((_glossary_row(row) for row in rows), key=lambda row: str(row.get("id") or ""))
    return hash_json(normalized)


def _sheet_key(path: Path, requested: str | None) -> str:
    if path.suffix.lower() == ".csv":
        return CSV_SHEET_KEY
    if path.suffix.lower() == ".json":
        return JSON_SHEET_KEY
    return str(requested or "Glossary").strip()


def _parse_artifact(artifact: dict[str, Any], request: Any) -> ParsedGlossaryArtifact:
    path = Path(artifact["path"])
    requested_languages: list[str] = []
    for value in getattr(request, "languages", None) or []:
        language = require_supported_language(str(value))
        if language not in requested_languages:
            requested_languages.append(language)
    requested_languages = [language for language in LANGUAGE_ORDER if language in requested_languages]

    rows: list[dict[str, Any]] = []
    columns: dict[str, Any] = {}
    languages: list[str] = []
    auto_languages = bool(getattr(request, "auto_languages", True))
    explicit_target = bool(getattr(request, "target_column", None) or getattr(request, "target_alt_column", None))
    if auto_languages and not explicit_target and not requested_languages:
        rows, columns, languages = _read_multilingual_glossary_rows(
            path,
            sheet=getattr(request, "sheet", None),
            term_key_column=getattr(request, "term_key_column", None),
            source_column=getattr(request, "source_column", None),
            category_column=getattr(request, "category_column", None),
            note_column=getattr(request, "note_column", None),
            limit=None,
        )

    if not languages:
        languages = requested_languages or [
            require_supported_language(getattr(request, "language", "en") or "en")
        ]
        rows = []
        language_columns: dict[str, Any] = {}
        for language in languages:
            language_rows, detected = _read_glossary_rows(
                path,
                sheet=getattr(request, "sheet", None),
                term_key_column=getattr(request, "term_key_column", None),
                source_column=getattr(request, "source_column", None),
                target_column=getattr(request, "target_column", None),
                target_alt_column=getattr(request, "target_alt_column", None),
                category_column=getattr(request, "category_column", None),
                note_column=getattr(request, "note_column", None),
                language=language,
                limit=None,
                include_empty=True,
            )
            rows.extend({**row, "language": language} for row in language_rows)
            language_columns[language] = detected
        columns = {"languages": language_columns}

    normalized_rows = [
        {
            "term_key": str(row.get("term_key") or "").strip(),
            "source": str(row.get("source") or "").strip(),
            "target": str(row.get("target") or "").strip(),
            "target_alt": "",
            "language": normalize_language(row.get("language") or "en"),
            "category": str(row.get("category") or "").strip(),
            "note": str(row.get("note") or "").strip(),
            "target_column_present": True,
        }
        for row in rows
        if str(row.get("source") or "").strip()
    ]
    if not normalized_rows:
        raise ArchiveBatchError(400, "invalid_glossary_template", "术语表没有可分析的中文源文行。")
    return ParsedGlossaryArtifact(
        rows=normalized_rows,
        columns=columns,
        sheet=_sheet_key(path, getattr(request, "sheet", None)),
        languages=languages,
    )


def _conflict(code: str, message: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "language": row.get("language", ""),
        "term_key": row.get("term_key", ""),
        "source": row.get("source", ""),
    }


def _input_conflicts(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    by_id: dict[tuple[str, str], list[int]] = {}
    by_concept_id: dict[str, list[int]] = {}
    by_source: dict[tuple[str, str], list[int]] = {}
    by_source_global: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        language = normalize_language(row.get("language") or "en")
        term_key = str(row.get("term_key") or "").strip()
        source_key = _source_key(row.get("source"))
        if term_key:
            by_id.setdefault((language, term_key), []).append(index)
            by_concept_id.setdefault(term_key, []).append(index)
        if source_key:
            by_source.setdefault((language, source_key), []).append(index)
            by_source_global.setdefault(source_key, []).append(index)

    result: dict[int, list[dict[str, Any]]] = {}
    for indices in by_id.values():
        if len(indices) > 1:
            for index in indices:
                result.setdefault(index, []).append(
                    _conflict("duplicate_id", "同一语言的输入包含重复术语 ID。", rows[index])
                )
    for indices in by_concept_id.values():
        shared_values = {
            (
                _source_key(rows[index].get("source")),
                str(rows[index].get("category") or "").strip(),
                str(rows[index].get("note") or "").strip(),
            )
            for index in indices
        }
        if len(shared_values) > 1:
            for index in indices:
                result.setdefault(index, []).append(
                    _conflict(
                        "shared_identity_mismatch",
                        "同一术语 ID 的跨语言行必须使用一致的中文源文、分类和备注。",
                        rows[index],
                    )
                )
    for indices in by_source.values():
        if len(indices) < 2:
            continue
        ids = {str(rows[index].get("term_key") or "").strip() for index in indices}
        nonblank_ids = {value for value in ids if value}
        code = "source_multiple_ids" if len(nonblank_ids) > 1 else "duplicate_source"
        message = "同一中文源文对应多个术语 ID。" if len(nonblank_ids) > 1 else "输入包含重复中文源文。"
        for index in indices:
            result.setdefault(index, []).append(_conflict(code, message, rows[index]))
    for indices in by_source_global.values():
        languages = {normalize_language(rows[index].get("language") or "en") for index in indices}
        if len(languages) < 2:
            continue
        ids = {str(rows[index].get("term_key") or "").strip() for index in indices}
        nonblank_ids = {value for value in ids if value}
        if len(nonblank_ids) > 1:
            code = "source_multiple_ids"
            message = "同一中文源文不能跨语言对应多个术语 ID。"
        elif nonblank_ids and "" in ids:
            code = "source_mixed_identity"
            message = "同一中文源文不能跨语言混用有 ID 和无 ID 身份。"
        else:
            continue
        for index in indices:
            result.setdefault(index, []).append(_conflict(code, message, rows[index]))
    return result


def _make_after(
    before: dict[str, Any] | None,
    row: dict[str, Any],
    *,
    entity_id: str,
    project_id: str,
    batch_id: str,
    dataset_key: str,
    timestamp: str,
    source_type: str = "imported",
    review_status: str = "approved",
    confirmed: bool = True,
) -> dict[str, Any]:
    created_at = str((before or {}).get("created_at") or timestamp)
    return {
        "id": entity_id,
        "project_id": project_id,
        "term_key": str(row.get("term_key") or (before or {}).get("term_key") or "").strip(),
        "source": str(row.get("source") or (before or {}).get("source") or "").strip(),
        "source_key": _source_key(row.get("source") or (before or {}).get("source")),
        "target": str(row.get("target") or "").strip(),
        "target_alt": "",
        "language": normalize_language(row.get("language") or (before or {}).get("language") or "en"),
        "category": str(row.get("category") or (before or {}).get("category") or "").strip(),
        "note": str(row.get("note") or (before or {}).get("note") or "").strip(),
        "source_type": source_type,
        "confirmed": confirmed,
        "active": 1,
        "dataset_key": dataset_key,
        "last_import_batch_id": batch_id,
        "review_status": review_status,
        "created_at": created_at,
        "updated_at": timestamp,
    }


def _shared_content_unchanged(before: dict[str, Any], shared: dict[str, Any]) -> bool:
    return (
        str(before.get("term_key") or "").strip() == str(shared.get("term_key") or "").strip()
        and str(before.get("source") or "").strip() == str(shared.get("source") or "").strip()
        and str(before.get("category") or "").strip() == str(shared.get("category") or "").strip()
        and str(before.get("note") or "").strip() == str(shared.get("note") or "").strip()
    )


def _make_shared_after(
    before: dict[str, Any],
    shared: dict[str, Any],
    *,
    batch_id: str,
    timestamp: str,
) -> dict[str, Any]:
    after = dict(before)
    source = str(shared.get("source") or "").strip()
    after.update(
        {
            "term_key": str(shared.get("term_key") or "").strip(),
            "source": source,
            "source_key": _source_key(source),
            "category": str(shared.get("category") or "").strip(),
            "note": str(shared.get("note") or "").strip(),
            "last_import_batch_id": batch_id,
            "updated_at": timestamp,
        }
    )
    return {field: after.get(field) for field in GLOSSARY_FIELDS}


def _content_unchanged(before: dict[str, Any], row: dict[str, Any]) -> bool:
    return (
        str(before.get("term_key") or "").strip() == str(row.get("term_key") or "").strip()
        and str(before.get("source") or "").strip() == str(row.get("source") or "").strip()
        and str(before.get("target") or "").strip() == str(row.get("target") or "").strip()
        and not str(before.get("target_alt") or "").strip()
        and normalize_language(before.get("language") or "en") == normalize_language(row.get("language") or "en")
        and str(before.get("category") or "").strip() == str(row.get("category") or "").strip()
        and str(before.get("note") or "").strip() == str(row.get("note") or "").strip()
        and int(before.get("active") or 0) == 1
    )


def _item(
    *,
    batch_id: str,
    ordinal: int,
    row: dict[str, Any],
    entity_id: str,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    conflicts: list[dict[str, Any]],
    timestamp: str,
) -> dict[str, Any]:
    term_key = str(row.get("term_key") or "").strip()
    source = str(row.get("source") or "").strip()
    return {
        "id": db.new_id("aii"),
        "batch_id": batch_id,
        "ordinal": ordinal,
        "entity_id": entity_id,
        "identity": {"language": row.get("language", "en"), "term_key": term_key, "source_key": _source_key(source)},
        "language": row.get("language", "en"),
        "entry_key": term_key,
        "source_key": _source_key(source),
        "source": source,
        "target": str(row.get("target") or "").strip(),
        "target_column_present": True,
        "explicit_empty": not str(row.get("target") or "").strip(),
        "planned_action": action,
        "before_hash": _glossary_hash(before),
        "expected_after": after or {},
        "conflicts": conflicts,
        "created_at": timestamp,
    }


def _plan_batch(
    project_id: str,
    parsed: ParsedGlossaryArtifact,
    request: Any,
    batch_id: str,
    timestamp: str,
    existing_rows: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], dict[str, int], list[dict[str, Any]]]:
    by_id: dict[tuple[str, str], list[dict[str, Any]]] = {}
    by_concept_id: dict[str, list[dict[str, Any]]] = {}
    by_source: dict[tuple[str, str], list[dict[str, Any]]] = {}
    by_source_global: dict[str, list[dict[str, Any]]] = {}
    for existing in existing_rows:
        language = normalize_language(existing.get("language") or "en")
        term_key = str(existing.get("term_key") or "").strip()
        source_key = _source_key(existing.get("source"))
        if term_key:
            by_id.setdefault((language, term_key), []).append(existing)
            by_concept_id.setdefault(term_key, []).append(existing)
        if source_key:
            by_source.setdefault((language, source_key), []).append(existing)
            by_source_global.setdefault(source_key, []).append(existing)

    row_conflicts = _input_conflicts(parsed.rows)
    matches: dict[int, dict[str, Any] | None] = {}
    concept_siblings: dict[int, list[dict[str, Any]]] = {}
    inferred_datasets: set[str] = set()
    for index, row in enumerate(parsed.rows):
        if row_conflicts.get(index):
            matches[index] = None
            continue
        language = normalize_language(row.get("language") or "en")
        term_key = str(row.get("term_key") or "").strip()
        source_key = _source_key(row.get("source"))
        source_matches = by_source.get((language, source_key), [])
        siblings = list(by_concept_id.get(term_key, [])) if term_key else []
        concept_siblings[index] = siblings
        if term_key:
            foreign_source_matches = [
                candidate
                for candidate in by_source_global.get(source_key, [])
                if str(candidate.get("term_key") or "").strip() != term_key
            ]
            if foreign_source_matches:
                row_conflicts.setdefault(index, []).append(
                    _conflict("concept_source_conflict", "修改后的中文源文已属于另一个术语概念。", row)
                )
        match: dict[str, Any] | None = None
        if term_key:
            id_matches = by_id.get((language, term_key), [])
            if len(id_matches) > 1:
                row_conflicts.setdefault(index, []).append(
                    _conflict("existing_identity_ambiguous", "现有术语 ID 对应多条记录。", row)
                )
            elif id_matches:
                match = id_matches[0]
                if any(candidate["id"] != match["id"] for candidate in source_matches):
                    row_conflicts.setdefault(index, []).append(
                        _conflict("id_source_cross_match", "ID 与中文源文命中了不同术语。", row)
                    )
            elif source_matches:
                row_conflicts.setdefault(index, []).append(
                    _conflict("new_id_source_exists", "新 ID 的中文源文已属于另一条术语。", row)
                )
        elif source_matches:
            keyed = [candidate for candidate in source_matches if str(candidate.get("term_key") or "").strip()]
            unkeyed = [candidate for candidate in source_matches if not str(candidate.get("term_key") or "").strip()]
            if keyed:
                row_conflicts.setdefault(index, []).append(
                    _conflict("source_owned_by_id", "无 ID 行的中文源文已属于有 ID 术语。", row)
                )
            elif len(unkeyed) == 1:
                match = unkeyed[0]
            elif len(unkeyed) > 1:
                row_conflicts.setdefault(index, []).append(
                    _conflict("existing_identity_ambiguous", "中文源文对应多条现有无 ID 术语。", row)
                )
        matches[index] = match
        for sibling in siblings or ([match] if match else []):
            if sibling and str(sibling.get("dataset_key") or "").strip():
                inferred_datasets.add(str(sibling["dataset_key"]).strip())

    requested_dataset = str(getattr(request, "dataset_key", None) or "").strip()
    if requested_dataset:
        dataset_key = requested_dataset
    elif len(inferred_datasets) == 1:
        dataset_key = next(iter(inferred_datasets))
    elif inferred_datasets:
        dataset_key = sorted(inferred_datasets)[0]
        for index, match in matches.items():
            if match:
                row_conflicts.setdefault(index, []).append(
                    _conflict("lineage_selection_required", "输入命中多个 dataset，请显式选择。", parsed.rows[index])
                )
    else:
        dataset_key = f"dataset_{batch_id.removeprefix('aib_')}"

    for index, row in enumerate(parsed.rows):
        scoped_rows = list(concept_siblings.get(index, []))
        match = matches.get(index)
        if match and all(str(candidate.get("id")) != str(match.get("id")) for candidate in scoped_rows):
            scoped_rows.append(match)
        existing_datasets = {
            str(candidate.get("dataset_key") or "").strip()
            for candidate in scoped_rows
            if str(candidate.get("dataset_key") or "").strip()
        }
        if any(existing_dataset != dataset_key for existing_dataset in existing_datasets):
            row_conflicts.setdefault(index, []).append(
                _conflict("cross_lineage_match", "术语身份已属于另一个 dataset。", row)
            )

    summary = {
        "source_rows": len(parsed.rows),
        "insert": 0,
        "update": 0,
        "unchanged": 0,
        "skip": 0,
        "protected": 0,
        "conflict": 0,
    }
    items: list[dict[str, Any]] = []
    all_conflicts: list[dict[str, Any]] = []
    override_protected = bool(getattr(request, "override_protected", False))
    for index, row in enumerate(parsed.rows):
        before = matches.get(index)
        conflicts = list(row_conflicts.get(index) or [])
        target = str(row.get("target") or "").strip()
        entity_id = str((before or {}).get("id") or db.new_id("term"))
        after: dict[str, Any] | None = None
        if conflicts:
            action = "conflict"
        elif not target:
            if before is not None and not _shared_content_unchanged(before, row):
                action = "update"
                after = _make_shared_after(
                    before,
                    row,
                    batch_id=batch_id,
                    timestamp=timestamp,
                )
            else:
                action = "skip"
                after = before
        elif before is None:
            action = "insert"
            after = _make_after(
                None,
                row,
                entity_id=entity_id,
                project_id=project_id,
                batch_id=batch_id,
                dataset_key=dataset_key,
                timestamp=timestamp,
            )
        elif _content_unchanged(before, row):
            action = "unchanged"
            after = before
        else:
            action = "update"
            after = _make_after(
                before,
                row,
                entity_id=entity_id,
                project_id=project_id,
                batch_id=batch_id,
                dataset_key=dataset_key,
                timestamp=timestamp,
            )

        protected = (
            before is not None
            and action == "update"
            and str(before.get("source_type") or "").strip().lower() in PROTECTED_GLOSSARY_SOURCES
        )
        if protected and after:
            if override_protected:
                summary["protected"] += 1
                after.update({"source_type": "imported", "review_status": "pending", "confirmed": False})
            else:
                conflicts.append(_conflict("protected_source", "人工或精选术语默认禁止覆盖。", row))
                action = "protected"

        summary[action if action in summary else "conflict"] += 1
        all_conflicts.extend(conflicts)
        items.append(
            _item(
                batch_id=batch_id,
                ordinal=len(items),
                row=row,
                entity_id=entity_id if before is not None or action == "insert" else "",
                action=action,
                before=before,
                after=after,
                conflicts=conflicts,
                timestamp=timestamp,
            )
        )

    planned_entity_ids = {str(item["entity_id"]) for item in items if str(item.get("entity_id") or "")}
    for index, item in enumerate(list(items)):
        term_key = str(item.get("entry_key") or "").strip()
        if (
            not term_key
            or item["planned_action"] not in {"insert", "update", "unchanged", "skip"}
            or item["conflicts"]
        ):
            continue
        shared = item["expected_after"] or parsed.rows[index]
        for before in concept_siblings.get(index, []):
            entity_id = str(before["id"])
            if entity_id in planned_entity_ids or _shared_content_unchanged(before, shared):
                continue
            after = _make_shared_after(
                before,
                shared,
                batch_id=batch_id,
                timestamp=timestamp,
            )
            sibling_row = {
                "term_key": after.get("term_key", ""),
                "source": after.get("source", ""),
                "target": before.get("target", ""),
                "language": before.get("language", "en"),
                "category": after.get("category", ""),
                "note": after.get("note", ""),
                "target_column_present": False,
            }
            conflicts: list[dict[str, Any]] = []
            action = "update"
            if str(before.get("source_type") or "").strip().lower() in PROTECTED_GLOSSARY_SOURCES:
                if override_protected:
                    summary["protected"] += 1
                    after.update({"source_type": "imported", "review_status": "pending", "confirmed": False})
                else:
                    conflicts.append(_conflict("protected_source", "人工或精选术语默认禁止覆盖。", sibling_row))
                    action = "protected"
            summary[action if action in summary else "conflict"] += 1
            all_conflicts.extend(conflicts)
            items.append(
                _item(
                    batch_id=batch_id,
                    ordinal=len(items),
                    row=sibling_row,
                    entity_id=entity_id,
                    action=action,
                    before=before,
                    after=after,
                    conflicts=conflicts,
                    timestamp=timestamp,
                )
            )
            planned_entity_ids.add(entity_id)

    summary["conflict"] = len(all_conflicts)
    return dataset_key, items, summary, all_conflicts


def analyze_glossary_archive(project_id: str, request: Any) -> dict[str, Any]:
    if getattr(request, "confirmed_glossary", None) is not True:
        raise ArchiveBatchError(400, "confirmed_glossary_required", "必须明确确认这是可直接导入的术语表。")
    if str(getattr(request, "mode", "merge") or "merge").strip().lower() != "merge":
        raise ArchiveBatchError(400, "unsupported_mode", "术语归档只支持 merge 模式。")
    try:
        db.get_project(project_id)
        artifact = db.get_artifact(request.artifact_id)
    except KeyError as exc:
        raise ArchiveBatchError(404, "project_or_artifact_not_found", "项目或 artifact 不存在。") from exc
    if artifact["project_id"] != project_id:
        raise ArchiveBatchError(404, "project_or_artifact_not_found", "项目或 artifact 不存在。")
    if artifact.get("kind") not in DIRECT_GLOSSARY_KINDS:
        raise ArchiveBatchError(
            400,
            "candidate_scan_required",
            "语言表只能进入术语候选扫描，不能直接写入术语库。",
        )

    batch_id = db.new_id("aib")
    token = f"ait_{uuid.uuid4().hex}"
    timestamp = db.now_iso()
    try:
        parsed = _parse_artifact(artifact, request)
    except ArchiveBatchError:
        raise
    except (KeyError, ValueError) as exc:
        raise ArchiveBatchError(400, "invalid_glossary_template", str(exc)) from exc
    path = Path(artifact["path"])
    checksum = file_checksum(path)
    with db.connect() as conn:
        rows = [
            _glossary_row(row)
            for row in conn.execute(
                "SELECT * FROM glossary_terms WHERE project_id = ?",
                (project_id,),
            ).fetchall()
        ]
        state_row = conn.execute(
            "SELECT version FROM archive_state_versions WHERE project_id = ? AND kind = ?",
            (project_id, ARCHIVE_KIND),
        ).fetchone()
        base_state_version = int(state_row["version"] if state_row else 0)
        base_state_checksum = _state_checksum(rows)
    dataset_key, items, summary, conflicts = _plan_batch(
        project_id,
        parsed,
        request,
        batch_id,
        timestamp,
        rows,
    )
    request_payload = _request_payload(request)
    persist_archive_analysis(
        kind=ARCHIVE_KIND,
        batch_id=batch_id,
        project_id=project_id,
        artifact=artifact,
        artifact_checksum=checksum,
        token=token,
        request_payload=request_payload,
        summary=summary,
        dataset_key=dataset_key,
        sheet_key=parsed.sheet,
        languages=parsed.languages,
        base_state_version=base_state_version,
        base_state_checksum=base_state_checksum,
        items=items,
        timestamp=timestamp,
    )
    changes = [
        {
            "ordinal": item["ordinal"],
            "action": item["planned_action"],
            "language": item["language"],
            "term_key": item["entry_key"],
            "source": item["source"],
            "target": item["target"],
            "explicit_empty": item["explicit_empty"],
        }
        for item in items[:CHANGE_SAMPLE_LIMIT]
    ]
    return {
        "batch_id": batch_id,
        "token": token,
        "artifact": {
            "id": artifact["id"],
            "label": artifact.get("label", ""),
            "kind": artifact.get("kind", ""),
            "checksum": checksum,
        },
        "sheet": parsed.sheet,
        "mode": "merge",
        "dataset_key": dataset_key,
        "languages": parsed.languages,
        "columns": parsed.columns,
        "summary": summary,
        "changes": changes,
        "conflicts": conflicts,
        "can_commit": not conflicts,
    }


def _insert_expected(conn: sqlite3.Connection, after: dict[str, Any]) -> dict[str, Any]:
    after = {**after, "source_key": _source_key(after.get("source"))}
    conn.execute(
        f"INSERT INTO glossary_terms ({', '.join(GLOSSARY_FIELDS)}) "
        f"VALUES ({', '.join('?' for _ in GLOSSARY_FIELDS)})",
        tuple(after.get(field) for field in GLOSSARY_FIELDS),
    )
    return _glossary_row(conn.execute("SELECT * FROM glossary_terms WHERE id = ?", (after["id"],)).fetchone())


def _replace_expected(conn: sqlite3.Connection, after: dict[str, Any]) -> dict[str, Any]:
    after = {**after, "source_key": _source_key(after.get("source"))}
    fields = [field for field in GLOSSARY_FIELDS if field != "id"]
    conn.execute(
        f"UPDATE glossary_terms SET {', '.join(f'{field} = ?' for field in fields)} WHERE id = ?",
        (*[after.get(field) for field in fields], after["id"]),
    )
    return _glossary_row(conn.execute("SELECT * FROM glossary_terms WHERE id = ?", (after["id"],)).fetchone())


def _preflight_rollback(conn: sqlite3.Connection, revisions: list[sqlite3.Row], batch_id: str) -> None:
    for revision in revisions:
        before = json.loads(revision["before_json"] or "{}")
        if not before or not int(before.get("active") or 0):
            continue
        term_key = str(before.get("term_key") or "").strip()
        if term_key:
            duplicate = conn.execute(
                "SELECT id FROM glossary_terms WHERE project_id = ? AND language = ? "
                "AND term_key = ? AND id <> ? AND active = 1 LIMIT 1",
                (before["project_id"], before["language"], term_key, before["id"]),
            ).fetchone()
            if duplicate:
                raise ArchiveBatchError(
                    409,
                    "rollback_constraint_conflict",
                    "回滚会造成术语 ID 冲突。",
                    batch_id=batch_id,
                )
        source_key = _source_key(before.get("source"))
        candidates = conn.execute(
            "SELECT id, source FROM glossary_terms WHERE project_id = ? AND language = ? "
            "AND id <> ? AND active = 1",
            (before["project_id"], before["language"], before["id"]),
        ).fetchall()
        if source_key and any(_source_key(candidate["source"]) == source_key for candidate in candidates):
            raise ArchiveBatchError(
                409,
                "rollback_constraint_conflict",
                "回滚会造成中文源文身份冲突。",
                batch_id=batch_id,
            )


def _adapter() -> ArchiveEntityAdapter:
    return ArchiveEntityAdapter(
        kind=ARCHIVE_KIND,
        table="glossary_terms",
        fields=GLOSSARY_FIELDS,
        collection_key="terms",
        normalize_row=_glossary_row,
        row_hash=_glossary_hash,
        state_checksum=_state_checksum,
        insert_expected=_insert_expected,
        replace_expected=_replace_expected,
        preflight_rollback=_preflight_rollback,
    )


def commit_glossary_archive(project_id: str, token: str, *, compact: bool = False) -> dict[str, Any]:
    return commit_archive_batch(project_id, token, _adapter(), compact=compact)


def list_glossary_import_batches(project_id: str, *, compact: bool = False) -> dict[str, Any]:
    return list_archive_import_batches(project_id, ARCHIVE_KIND, compact=compact)


def rollback_glossary_import_batch(project_id: str, batch_id: str) -> dict[str, Any]:
    return rollback_archive_import_batch(project_id, batch_id, _adapter())
