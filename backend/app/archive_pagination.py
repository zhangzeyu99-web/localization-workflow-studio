from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable

from . import db
from .languages import PROJECT_LANGUAGE_ORDER, normalize_language, require_supported_language


@dataclass(frozen=True)
class _ArchiveSpec:
    kind: str
    table: str
    key_field: str
    shared_fields: tuple[str, ...]
    visibility_sql: str
    search_fields: tuple[str, ...]


_SPECS = {
    "glossary": _ArchiveSpec(
        kind="glossary",
        table="glossary_terms",
        key_field="term_key",
        shared_fields=("term_key", "category", "note"),
        visibility_sql="active = 1 AND confirmed = 1",
        search_fields=("term_key", "source", "target", "category", "note"),
    ),
    "translations": _ArchiveSpec(
        kind="translations",
        table="translation_entries",
        key_field="entry_key",
        shared_fields=("entry_key", "note"),
        visibility_sql="active = 1",
        search_fields=("entry_key", "source", "target", "note"),
    ),
}


class ArchiveRevisionConflict(Exception):
    def __init__(self, expected_revision: str, current_revision: str) -> None:
        super().__init__(expected_revision, current_revision)
        self.expected_revision = expected_revision
        self.current_revision = current_revision


class ArchiveSourceConflict(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def list_archive_wide_page(
    project_id: str,
    kind: str,
    *,
    page: int = 1,
    page_size: int = 100,
    q: str = "",
    languages: str | Iterable[str] | None = None,
    sort: str = "source",
) -> dict[str, Any]:
    spec = _SPECS[kind]
    selected_languages = _selected_languages(languages)
    if page < 1:
        raise ValueError("page must be at least 1")
    if page_size < 1 or page_size > 200:
        raise ValueError("page_size must be between 1 and 200")
    if sort not in {"source", "id"}:
        raise ValueError("sort must be source or id")

    db.get_project(project_id)
    query = db.unicode_casefold(str(q or "").strip())
    pattern = f"%{_escape_like(query)}%"
    offset = (page - 1) * page_size
    with db.connect() as conn:
        page_rows, total_rows = _page_source_keys(
            conn,
            spec,
            project_id,
            query=query,
            pattern=pattern,
            sort=sort,
            limit=page_size,
            offset=offset,
        )
        grouped = _load_page_records(conn, spec, project_id, page_rows)
        coverage = _coverage(conn, spec, project_id)
        record_languages = _record_languages(conn, spec, project_id)
        revision = _revision(conn, project_id, spec.kind)

    rows = [
        _wide_row(page_row, grouped.get(str(page_row["source_key"]), []), spec, selected_languages)
        for page_row in page_rows
    ]
    global_languages = [code for code in PROJECT_LANGUAGE_ORDER if coverage.get(code, 0) > 0]
    total_pages = max(1, math.ceil(total_rows / page_size))
    return {
        "project_id": project_id,
        "rows": rows,
        "row_count": total_rows,
        "total_rows": total_rows,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "languages": global_languages,
        "record_languages": record_languages,
        "coverage": {code: coverage[code] for code in global_languages},
        "revision": str(revision),
    }


def archive_source_summary(project_id: str, kind: str, source_key: str) -> dict[str, Any]:
    spec = _SPECS[kind]
    key = str(source_key or "").strip()
    if not key:
        raise ValueError("source_key is required")
    db.get_project(project_id)
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT language FROM {spec.table} WHERE project_id = ? AND source_key = ? AND {spec.visibility_sql}",
            (project_id, key),
        ).fetchall()
        revision = _revision(conn, project_id, spec.kind)
    found = {normalize_language(row["language"]) for row in rows}
    languages = [code for code in PROJECT_LANGUAGE_ORDER if code in found]
    return {
        "project_id": project_id,
        "kind": kind,
        "source_key": key,
        "count": len(rows),
        "languages": languages,
        "revision": str(revision),
    }


def delete_archive_source(
    project_id: str,
    kind: str,
    source_key: str,
    *,
    expected_revision: str,
) -> dict[str, Any]:
    spec = _SPECS[kind]
    key = str(source_key or "").strip()
    if not key:
        raise ValueError("source_key is required")
    db.get_project(project_id)
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current_revision = str(_revision(conn, project_id, spec.kind))
        if str(expected_revision) != current_revision:
            raise ArchiveRevisionConflict(str(expected_revision), current_revision)
        rows = conn.execute(
            f"SELECT language FROM {spec.table} WHERE project_id = ? AND source_key = ? AND {spec.visibility_sql}",
            (project_id, key),
        ).fetchall()
        if kind == "translations":
            conn.execute(
                f"UPDATE {spec.table} SET active = 0, source_type = 'manual', review_status = 'approved', updated_at = ? "
                f"WHERE project_id = ? AND source_key = ? AND {spec.visibility_sql}",
                (db.now_iso(), project_id, key),
            )
        else:
            conn.execute(
                f"UPDATE {spec.table} SET active = 0, updated_at = ? "
                f"WHERE project_id = ? AND source_key = ? AND {spec.visibility_sql}",
                (db.now_iso(), project_id, key),
            )
        revision = _revision(conn, project_id, spec.kind)
    found = {normalize_language(row["language"]) for row in rows}
    languages = [code for code in PROJECT_LANGUAGE_ORDER if code in found]
    return {
        "project_id": project_id,
        "kind": kind,
        "source_key": key,
        "deleted_count": len(rows),
        "languages": languages,
        "revision": str(revision),
    }


def patch_archive_source(
    project_id: str,
    kind: str,
    source_key: str,
    *,
    expected_revision: str,
    shared: dict[str, str],
    targets: dict[str, str],
) -> dict[str, Any]:
    spec = _SPECS[kind]
    key = str(source_key or "").strip()
    if not key:
        raise ValueError("source_key is required")
    allowed_shared = {"source", *spec.shared_fields}
    unknown_shared = set(shared) - allowed_shared
    if unknown_shared:
        raise ValueError(f"unsupported shared fields: {', '.join(sorted(unknown_shared))}")
    normalized_targets = {
        require_supported_language(language): str(target or "")
        for language, target in targets.items()
    }
    db.get_project(project_id)
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current_revision = str(_revision(conn, project_id, spec.kind))
        if str(expected_revision) != current_revision:
            raise ArchiveRevisionConflict(str(expected_revision), current_revision)
        records = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM {spec.table} "
                f"WHERE project_id = ? AND source_key = ? AND {spec.visibility_sql} "
                "ORDER BY language, updated_at DESC, id DESC",
                (project_id, key),
            ).fetchall()
        ]
        if not records:
            raise KeyError(source_key)

        next_source = str(shared.get("source", _first_non_blank(records, "source")) or "").strip()
        if not next_source:
            raise ValueError("source is required")
        next_source_key = db.normalize_archive_source_key(next_source)
        if next_source_key != key:
            source_collision = conn.execute(
                f"SELECT 1 FROM {spec.table} "
                f"WHERE project_id = ? AND source_key = ? AND {spec.visibility_sql} LIMIT 1",
                (project_id, next_source_key),
            ).fetchone()
            if source_collision:
                raise ArchiveSourceConflict("source_key_conflict", "修改后的 CN 已存在于其他归档概念。")

        next_identity = str(shared.get(spec.key_field, "") or "").strip()
        if next_identity:
            identity_collision = conn.execute(
                f"SELECT 1 FROM {spec.table} "
                f"WHERE project_id = ? AND source_key <> ? AND TRIM({spec.key_field}) = ? "
                f"AND {spec.visibility_sql} LIMIT 1",
                (project_id, key, next_identity),
            ).fetchone()
            if identity_collision:
                raise ArchiveSourceConflict("identity_conflict", "修改后的 ID 已被其他归档概念使用。")

        records_by_language: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            records_by_language.setdefault(normalize_language(record.get("language") or "en"), []).append(record)
        for language in normalized_targets:
            matches = records_by_language.get(language, [])
            if not matches:
                raise ArchiveSourceConflict("language_missing", f"{language} 归档记录已不存在，请刷新后重试。")
            if len(matches) > 1:
                raise ArchiveSourceConflict("language_ambiguous", f"{language} 存在重复归档记录，请先处理冲突。")

        timestamp = db.now_iso()
        shared_updates = {field: str(shared[field] or "") for field in allowed_shared if field in shared}
        shared_updates["source"] = next_source
        shared_updates["source_key"] = next_source_key
        assignments = [f"{field} = ?" for field in shared_updates]
        assignments.extend(["source_type = 'manual'", "review_status = 'approved'", "updated_at = ?"])
        updated_ids: set[str] = set()
        for record in records:
            if any(str(record.get(field) or "") != value for field, value in shared_updates.items()):
                conn.execute(
                    f"UPDATE {spec.table} SET {', '.join(assignments)} WHERE id = ?",
                    [*shared_updates.values(), timestamp, record["id"]],
                )
                updated_ids.add(str(record["id"]))
        for language, target in normalized_targets.items():
            record = records_by_language[language][0]
            if str(record.get("target") or "") == target and not str(record.get("target_alt") or ""):
                continue
            conn.execute(
                f"UPDATE {spec.table} SET target = ?, target_alt = '', "
                "source_type = 'manual', review_status = 'approved', updated_at = ? WHERE id = ?",
                (target, timestamp, record["id"]),
            )
            updated_ids.add(str(record["id"]))
        revision = str(_revision(conn, project_id, spec.kind))
    return {
        "project_id": project_id,
        "kind": kind,
        "source_key": next_source_key,
        "updated_count": len(updated_ids),
        "updated_target_languages": [
            code for code in PROJECT_LANGUAGE_ORDER if code in normalized_targets
        ],
        "revision": revision,
    }


def _selected_languages(value: str | Iterable[str] | None) -> list[str]:
    raw = value.split(",") if isinstance(value, str) else list(value or ["en"])
    normalized = {require_supported_language(item) for item in raw if str(item or "").strip()}
    if not normalized:
        normalized = {"en"}
    return [code for code in PROJECT_LANGUAGE_ORDER if code in normalized]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _page_source_keys(
    conn: sqlite3.Connection,
    spec: _ArchiveSpec,
    project_id: str,
    *,
    query: str,
    pattern: str,
    sort: str,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    matches = " OR ".join(
        f"unicode_casefold(COALESCE({field}, '')) LIKE ? ESCAPE '\\'" for field in spec.search_fields
    )
    order_sql = (
        "source_sort COLLATE NOCASE, source_key"
        if sort == "source"
        else "CASE WHEN id_sort = '' THEN 1 ELSE 0 END, id_sort COLLATE NOCASE, source_sort COLLATE NOCASE, source_key"
    )
    sql = f"""
        WITH matching AS (
          SELECT
            source_key,
            MIN(source) AS source_sort,
            COALESCE(MIN(NULLIF(TRIM({spec.key_field}), '')), '') AS id_sort
          FROM {spec.table}
          WHERE project_id = ?
            AND {spec.visibility_sql}
            AND source_key <> ''
          GROUP BY source_key
          HAVING ? = '' OR MAX(CASE WHEN {matches} THEN 1 ELSE 0 END) = 1
        )
        SELECT source_key, source_sort, id_sort, COUNT(*) OVER() AS total_rows
        FROM matching
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
    """
    params: list[Any] = [project_id, query, *[pattern for _ in spec.search_fields], limit, offset]
    rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
    if rows:
        return rows, int(rows[0]["total_rows"] or 0)

    count_sql = f"""
        SELECT COUNT(*) AS total_rows
        FROM (
          SELECT source_key
          FROM {spec.table}
          WHERE project_id = ?
            AND {spec.visibility_sql}
            AND source_key <> ''
          GROUP BY source_key
          HAVING ? = '' OR MAX(CASE WHEN {matches} THEN 1 ELSE 0 END) = 1
        )
    """
    count = conn.execute(
        count_sql,
        [project_id, query, *[pattern for _ in spec.search_fields]],
    ).fetchone()
    return [], int(count["total_rows"] or 0)


def _load_page_records(
    conn: sqlite3.Connection,
    spec: _ArchiveSpec,
    project_id: str,
    page_rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    source_keys = [str(row["source_key"]) for row in page_rows]
    if not source_keys:
        return {}
    placeholders = ",".join("?" for _ in source_keys)
    records = conn.execute(
        f"""
        SELECT * FROM {spec.table}
        WHERE project_id = ?
          AND {spec.visibility_sql}
          AND source_key IN ({placeholders})
        ORDER BY source_key, language, updated_at DESC, id DESC
        """,
        [project_id, *source_keys],
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        payload = dict(record)
        grouped.setdefault(str(payload["source_key"]), []).append(payload)
    return grouped


def _coverage(conn: sqlite3.Connection, spec: _ArchiveSpec, project_id: str) -> dict[str, int]:
    rows = conn.execute(
        f"""
        SELECT language, COUNT(DISTINCT source_key) AS covered
        FROM {spec.table}
        WHERE project_id = ?
          AND {spec.visibility_sql}
          AND source_key <> ''
          AND TRIM(target) <> ''
        GROUP BY language
        """,
        (project_id,),
    ).fetchall()
    coverage: dict[str, int] = {}
    for row in rows:
        language = normalize_language(row["language"])
        coverage[language] = coverage.get(language, 0) + int(row["covered"] or 0)
    return coverage


def _record_languages(conn: sqlite3.Connection, spec: _ArchiveSpec, project_id: str) -> list[str]:
    rows = conn.execute(
        f"""
        SELECT DISTINCT language
        FROM {spec.table}
        WHERE project_id = ?
          AND {spec.visibility_sql}
          AND source_key <> ''
        """,
        (project_id,),
    ).fetchall()
    found = {normalize_language(row["language"]) for row in rows}
    return [code for code in PROJECT_LANGUAGE_ORDER if code in found]


def _revision(conn: sqlite3.Connection, project_id: str, kind: str) -> int:
    row = conn.execute(
        "SELECT version FROM archive_state_versions WHERE project_id = ? AND kind = ?",
        (project_id, kind),
    ).fetchone()
    return int(row["version"] if row else 0)


def _wide_row(
    page_row: dict[str, Any],
    records: list[dict[str, Any]],
    spec: _ArchiveSpec,
    selected_languages: list[str],
) -> dict[str, Any]:
    translations: dict[str, dict[str, Any]] = {}
    for code in selected_languages:
        selected = next(
            (
                record
                for record in records
                if normalize_language(record.get("language") or "en") == code
            ),
            None,
        )
        if selected:
            translations[code] = {
                "id": selected.get("id", ""),
                "language": code,
                "target": selected.get("target", ""),
                "target_alt": "",
                "source_type": selected.get("source_type", ""),
                "review_status": selected.get("review_status", ""),
            }
    shared = {field: _first_non_blank(records, field) for field in spec.shared_fields}
    return {
        "source_key": page_row["source_key"],
        "source": _first_non_blank(records, "source") or str(page_row.get("source_sort") or ""),
        **shared,
        "translations": translations,
        "languages": [code for code in selected_languages if code in translations],
        "conflicts": _wide_conflicts(records, ("source", *spec.shared_fields)),
    }


def _first_non_blank(rows: list[dict[str, Any]], field: str) -> str:
    for row in rows:
        value = str(row.get(field) or "").strip()
        if value and value != "-":
            return value
    return ""


def _wide_conflicts(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for field in fields:
        values = list(
            dict.fromkeys(
                value
                for row in rows
                for value in [str(row.get(field) or "").strip()]
                if value and value != "-"
            )
        )
        if len(values) > 1:
            conflicts.append({"field": field, "values": values})
    return conflicts
