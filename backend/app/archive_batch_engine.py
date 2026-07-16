from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from . import db


class ArchiveBatchError(ValueError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        batch_id: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail: dict[str, Any] = {"code": code, "message": message, **(extra or {})}
        if status_code == 409 or batch_id:
            self.detail["batch_id"] = batch_id


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_load(value: Any, default: Any) -> Any:
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def hash_json(value: Any) -> str:
    return hashlib.sha256(json_dump(value).encode("utf-8")).hexdigest()


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ArchiveEntityAdapter:
    kind: str
    table: str
    fields: tuple[str, ...]
    collection_key: str
    normalize_row: Callable[[sqlite3.Row | dict[str, Any]], dict[str, Any]]
    row_hash: Callable[[sqlite3.Row | dict[str, Any] | None], str]
    state_checksum: Callable[[Iterable[sqlite3.Row | dict[str, Any]]], str]
    insert_expected: Callable[[sqlite3.Connection, dict[str, Any]], dict[str, Any]]
    replace_expected: Callable[[sqlite3.Connection, dict[str, Any]], dict[str, Any]]
    preflight_rollback: Callable[[sqlite3.Connection, list[sqlite3.Row], str], None] | None = None
    artifact_checksum: Callable[[Path], str] = file_checksum


def persist_archive_analysis(
    *,
    kind: str,
    batch_id: str,
    project_id: str,
    artifact: dict[str, Any],
    artifact_checksum: str,
    token: str,
    request_payload: dict[str, Any],
    summary: dict[str, int],
    dataset_key: str,
    sheet_key: str,
    languages: list[str],
    base_state_version: int,
    base_state_checksum: str,
    items: list[dict[str, Any]],
    timestamp: str,
) -> None:
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO archive_import_batches
              (id, project_id, kind, artifact_id, artifact_checksum, token, request_json,
               summary_json, result_json, rollback_result_json, mode, dataset_key, sheet_key,
               languages_json, base_state_version, base_state_checksum, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', '{}', ?, ?, ?, ?, ?, ?, 'analyzed', ?, ?)
            """,
            (
                batch_id,
                project_id,
                kind,
                artifact["id"],
                artifact_checksum,
                token,
                json_dump(request_payload),
                json_dump(summary),
                str(request_payload.get("mode") or "merge").strip().lower(),
                dataset_key,
                sheet_key,
                json_dump(languages),
                base_state_version,
                base_state_checksum,
                timestamp,
                timestamp,
            ),
        )
        conn.executemany(
            """
            INSERT INTO archive_import_batch_items
              (id, batch_id, ordinal, kind, entity_id, identity_json, language, entry_key,
               source_key, source, target, target_column_present, explicit_empty,
               planned_action, before_hash, expected_after_json, conflict_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item["id"],
                    batch_id,
                    item["ordinal"],
                    kind,
                    item.get("entity_id", ""),
                    json_dump(item.get("identity", {})),
                    item.get("language", ""),
                    item.get("entry_key", ""),
                    item.get("source_key", ""),
                    item.get("source", ""),
                    item.get("target", ""),
                    1 if item.get("target_column_present") else 0,
                    1 if item.get("explicit_empty") else 0,
                    item["planned_action"],
                    item.get("before_hash", ""),
                    json_dump(item.get("expected_after", {})),
                    json_dump(item.get("conflicts", [])),
                    timestamp,
                )
                for item in items
            ],
        )


def batch_result(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["request"] = json_load(payload.pop("request_json", "{}"), {})
    payload["summary"] = json_load(payload.pop("summary_json", "{}"), {})
    payload["result"] = json_load(payload.pop("result_json", "{}"), {})
    payload["rollback_result"] = json_load(payload.pop("rollback_result_json", "{}"), {})
    payload["languages"] = json_load(payload.pop("languages_json", "[]"), [])
    return payload


def _scope_batch(
    batch: sqlite3.Row | None,
    project_id: str,
    kind: str,
    *,
    token_lookup: bool,
) -> sqlite3.Row:
    if batch is None:
        code = "invalid_token" if token_lookup else "batch_not_found"
        message = "导入 token 无效。" if token_lookup else "导入批次不存在。"
        raise ArchiveBatchError(409, code, message)
    if batch["project_id"] != project_id or batch["kind"] != kind:
        raise ArchiveBatchError(
            409,
            "batch_scope_mismatch",
            "导入批次不属于当前项目或归档类型。",
            batch_id=batch["id"],
        )
    return batch


def _validate_batch_artifact(
    conn: sqlite3.Connection,
    batch: sqlite3.Row,
    adapter: ArchiveEntityAdapter,
) -> None:
    try:
        artifact = db.get_artifact(batch["artifact_id"], conn=conn)
        path = Path(artifact["path"])
        matches = (
            artifact["project_id"] == batch["project_id"]
            and path.is_file()
            and adapter.artifact_checksum(path) == batch["artifact_checksum"]
        )
    except (KeyError, OSError):
        matches = False
    if not matches:
        raise ArchiveBatchError(
            409,
            "artifact_changed",
            "分析后的 artifact 文件或归属已变化。",
            batch_id=batch["id"],
        )


def _reserve_state_version(
    conn: sqlite3.Connection,
    project_id: str,
    kind: str,
    base_version: int,
    batch_id: str,
) -> None:
    row = conn.execute(
        "SELECT version FROM archive_state_versions WHERE project_id = ? AND kind = ?",
        (project_id, kind),
    ).fetchone()
    current = int(row["version"] if row else 0)
    if current != base_version:
        raise ArchiveBatchError(409, "state_drift", "分析后归档状态已变化，请重新分析。", batch_id=batch_id)
    if row:
        cursor = conn.execute(
            "UPDATE archive_state_versions SET version = version + 1 "
            "WHERE project_id = ? AND kind = ? AND version = ?",
            (project_id, kind, base_version),
        )
        if cursor.rowcount != 1:
            raise ArchiveBatchError(409, "state_drift", "分析后归档状态已变化，请重新分析。", batch_id=batch_id)
    else:
        try:
            conn.execute(
                "INSERT INTO archive_state_versions(project_id, kind, version) VALUES (?, ?, 1)",
                (project_id, kind),
            )
        except sqlite3.IntegrityError as exc:
            raise ArchiveBatchError(
                409,
                "state_drift",
                "分析后归档状态已变化，请重新分析。",
                batch_id=batch_id,
            ) from exc


def _compact_committed_result(
    conn: sqlite3.Connection,
    batch: sqlite3.Row,
    adapter: ArchiveEntityAdapter,
    *,
    summary: dict[str, Any] | None = None,
    changed_count: int | None = None,
) -> dict[str, Any]:
    if changed_count is None:
        changed = conn.execute(
            "SELECT COUNT(*) AS count FROM archive_import_revisions WHERE batch_id = ?",
            (batch["id"],),
        ).fetchone()
        changed_count = int(changed["count"] if changed else 0)
    imported = conn.execute(
        "SELECT COUNT(DISTINCT entity_id) AS count FROM archive_import_batch_items "
        "WHERE batch_id = ? AND entity_id <> '' "
        "AND planned_action IN ('insert', 'update', 'unchanged') AND TRIM(target) <> ''",
        (batch["id"],),
    ).fetchone()
    state = conn.execute(
        "SELECT version FROM archive_state_versions WHERE project_id = ? AND kind = ?",
        (batch["project_id"], adapter.kind),
    ).fetchone()
    language_rows = conn.execute(
        "SELECT language, planned_action, COUNT(*) AS count FROM archive_import_batch_items "
        "WHERE batch_id = ? AND language <> '' GROUP BY language, planned_action",
        (batch["id"],),
    ).fetchall()
    language_summary: dict[str, dict[str, int]] = {}
    for row in language_rows:
        language_summary.setdefault(str(row["language"]), {})[str(row["planned_action"])] = int(row["count"] or 0)
    return {
        "project_id": batch["project_id"],
        "kind": adapter.kind,
        "batch_id": batch["id"],
        "status": "committed",
        "summary": summary if summary is not None else json_load(batch["summary_json"], {}),
        "changed_count": changed_count,
        "imported_count": int(imported["count"] if imported else 0),
        "languages": json_load(batch["languages_json"], []),
        "language_summary": language_summary,
        "dataset_key": batch["dataset_key"],
        "sheet": batch["sheet_key"],
        "state_version": int(state["version"] if state else 0),
    }


def _legacy_committed_result_from_items(
    conn: sqlite3.Connection,
    batch: sqlite3.Row,
    adapter: ArchiveEntityAdapter,
    token: str,
) -> dict[str, Any]:
    entities: list[dict[str, Any]] = []
    seen: set[str] = set()
    items = conn.execute(
        "SELECT entity_id, planned_action, expected_after_json FROM archive_import_batch_items "
        "WHERE batch_id = ? ORDER BY ordinal",
        (batch["id"],),
    ).fetchall()
    for item in items:
        if str(item["planned_action"]) not in {"insert", "update", "unchanged"}:
            continue
        after = json_load(item["expected_after_json"], {})
        if not isinstance(after, dict) or not str(after.get("target") or "").strip():
            continue
        entity_id = str(after.get("id") or item["entity_id"] or "")
        dedupe_key = entity_id or hash_json(after)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        entities.append(adapter.normalize_row(after))
    stored = json_load(batch["result_json"], {})
    state_version = int(stored.get("state_version") or 0) if isinstance(stored, dict) else 0
    return {
        "project_id": batch["project_id"],
        "kind": adapter.kind,
        "batch_id": batch["id"],
        "token": token,
        "status": "committed",
        "summary": json_load(batch["summary_json"], {}),
        "changed_count": int(stored.get("changed_count") or 0) if isinstance(stored, dict) else 0,
        "imported_count": len(entities),
        adapter.collection_key: entities,
        "languages": json_load(batch["languages_json"], []),
        "dataset_key": batch["dataset_key"],
        "sheet": batch["sheet_key"],
        "state_version": state_version,
    }


def _committed_result(
    conn: sqlite3.Connection,
    batch: sqlite3.Row,
    adapter: ArchiveEntityAdapter,
    token: str,
    *,
    compact: bool,
) -> dict[str, Any]:
    if compact:
        return _compact_committed_result(conn, batch, adapter)
    stored = json_load(batch["result_json"], {})
    if isinstance(stored, dict) and adapter.collection_key in stored:
        return stored
    return _legacy_committed_result_from_items(conn, batch, adapter, token)


def commit_archive_batch(
    project_id: str,
    token: str,
    adapter: ArchiveEntityAdapter,
    *,
    compact: bool = False,
) -> dict[str, Any]:
    with db.connect() as conn:
        initial = _scope_batch(
            conn.execute("SELECT * FROM archive_import_batches WHERE token = ?", (token,)).fetchone(),
            project_id,
            adapter.kind,
            token_lookup=True,
        )
        if initial["status"] == "committed":
            return _committed_result(conn, initial, adapter, token, compact=compact)
        if initial["status"] == "rolled_back":
            raise ArchiveBatchError(
                409,
                "batch_rolled_back",
                "已回滚批次不能再次提交。",
                batch_id=initial["id"],
            )
        _validate_batch_artifact(conn, initial, adapter)

    try:
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            batch = _scope_batch(
                conn.execute("SELECT * FROM archive_import_batches WHERE token = ?", (token,)).fetchone(),
                project_id,
                adapter.kind,
                token_lookup=True,
            )
            if batch["status"] == "committed":
                return _committed_result(conn, batch, adapter, token, compact=compact)
            if batch["status"] == "rolled_back":
                raise ArchiveBatchError(
                    409,
                    "batch_rolled_back",
                    "已回滚批次不能再次提交。",
                    batch_id=batch["id"],
                )
            _validate_batch_artifact(conn, batch, adapter)
            summary = json_load(batch["summary_json"], {})
            if int(summary.get("conflict") or 0) > 0:
                raise ArchiveBatchError(
                    409,
                    "conflicts_present",
                    "分析包含阻断冲突，不能提交。",
                    batch_id=batch["id"],
                )
            current_rows = conn.execute(
                f"SELECT * FROM {adapter.table} WHERE project_id = ?",
                (project_id,),
            ).fetchall()
            if adapter.state_checksum(current_rows) != batch["base_state_checksum"]:
                raise ArchiveBatchError(
                    409,
                    "state_drift",
                    "分析后归档状态已变化，请重新分析。",
                    batch_id=batch["id"],
                )
            _reserve_state_version(
                conn,
                project_id,
                adapter.kind,
                int(batch["base_state_version"]),
                batch["id"],
            )
            items = conn.execute(
                "SELECT * FROM archive_import_batch_items WHERE batch_id = ? ORDER BY ordinal",
                (batch["id"],),
            ).fetchall()
            changed_count = 0
            referenced_ids: list[str] = []
            for item in items:
                action = str(item["planned_action"])
                entity_id = str(item["entity_id"] or "")
                if not compact and entity_id and action in {"insert", "update", "unchanged"} and str(item["target"] or "").strip():
                    referenced_ids.append(entity_id)
                if action not in {"insert", "update", "clear", "deactivate"}:
                    continue
                before_row = conn.execute(
                    f"SELECT * FROM {adapter.table} WHERE id = ?",
                    (entity_id,),
                ).fetchone()
                if adapter.row_hash(before_row) != str(item["before_hash"] or ""):
                    raise ArchiveBatchError(
                        409,
                        "state_drift",
                        "批次目标记录已变化，请重新分析。",
                        batch_id=batch["id"],
                    )
                after = json_load(item["expected_after_json"], {})
                if action == "insert":
                    written = adapter.insert_expected(conn, after)
                    operation = "insert"
                else:
                    written = adapter.replace_expected(conn, after)
                    operation = action
                changed_count += 1
                conn.execute(
                    """
                    INSERT INTO archive_import_revisions
                      (id, project_id, kind, batch_id, entity_id, operation, ordinal,
                       before_json, after_json, before_hash, after_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        db.new_id("air"),
                        project_id,
                        adapter.kind,
                        batch["id"],
                        entity_id,
                        operation,
                        int(item["ordinal"]),
                        json_dump(adapter.normalize_row(before_row)) if before_row is not None else "{}",
                        json_dump(written),
                        adapter.row_hash(before_row),
                        adapter.row_hash(written),
                        db.now_iso(),
                    ),
                )
            if compact:
                result = _compact_committed_result(
                    conn,
                    batch,
                    adapter,
                    summary=summary,
                    changed_count=changed_count,
                )
            else:
                entities: list[dict[str, Any]] = []
                for entity_id in dict.fromkeys(referenced_ids):
                    row = conn.execute(
                        f"SELECT * FROM {adapter.table} WHERE id = ? AND active = 1",
                        (entity_id,),
                    ).fetchone()
                    if row:
                        entities.append(adapter.normalize_row(row))
                state_row = conn.execute(
                    "SELECT version FROM archive_state_versions WHERE project_id = ? AND kind = ?",
                    (project_id, adapter.kind),
                ).fetchone()
                result = {
                    "project_id": project_id,
                    "kind": adapter.kind,
                    "batch_id": batch["id"],
                    "token": token,
                    "status": "committed",
                    "summary": summary,
                    "changed_count": changed_count,
                    "imported_count": len(entities),
                    adapter.collection_key: entities,
                    "languages": json_load(batch["languages_json"], []),
                    "dataset_key": batch["dataset_key"],
                    "sheet": batch["sheet_key"],
                    "state_version": int(state_row["version"] if state_row else 0),
                }
            now = db.now_iso()
            conn.execute(
                "UPDATE archive_import_batches SET status = 'committed', result_json = ?, "
                "committed_at = ?, updated_at = ? WHERE id = ?",
                (json_dump(result), now, now, batch["id"]),
            )
            return result
    except sqlite3.IntegrityError as exc:
        raise ArchiveBatchError(
            409,
            "commit_constraint_conflict",
            "提交违反归档身份唯一约束。",
            batch_id=initial["id"],
        ) from exc


def _compact_batch_result(batch: sqlite3.Row, revision: int) -> dict[str, Any]:
    payload = dict(batch)
    return {
        "id": payload.get("id"),
        "project_id": payload.get("project_id"),
        "kind": payload.get("kind"),
        "artifact_id": payload.get("artifact_id"),
        "status": payload.get("status"),
        "mode": payload.get("mode"),
        "dataset_key": payload.get("dataset_key"),
        "sheet_key": payload.get("sheet_key"),
        "languages": json_load(payload.get("languages_json"), []),
        "summary": json_load(payload.get("summary_json"), {}),
        "revision": str(revision),
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
        "committed_at": payload.get("committed_at"),
        "rolled_back_at": payload.get("rolled_back_at"),
    }


def list_archive_import_batches(project_id: str, kind: str, *, compact: bool = False) -> dict[str, Any]:
    try:
        db.get_project(project_id)
    except KeyError as exc:
        raise ArchiveBatchError(404, "project_not_found", "项目不存在。") from exc
    with db.connect() as conn:
        if compact:
            rows = conn.execute(
                "SELECT id, project_id, kind, artifact_id, status, mode, dataset_key, sheet_key, "
                "languages_json, summary_json, base_state_version, created_at, updated_at, committed_at, rolled_back_at "
                "FROM archive_import_batches WHERE project_id = ? AND kind = ? "
                "ORDER BY created_at DESC, id DESC",
                (project_id, kind),
            ).fetchall()
            state = conn.execute(
                "SELECT version FROM archive_state_versions WHERE project_id = ? AND kind = ?",
                (project_id, kind),
            ).fetchone()
            revision = int(state["version"] if state else 0)
            return {
                "project_id": project_id,
                "kind": kind,
                "compact": True,
                "batches": [_compact_batch_result(row, revision) for row in rows],
            }
        rows = conn.execute(
            "SELECT * FROM archive_import_batches WHERE project_id = ? AND kind = ? "
            "ORDER BY created_at DESC, id DESC",
            (project_id, kind),
        ).fetchall()
    return {"project_id": project_id, "kind": kind, "batches": [batch_result(row) for row in rows]}


def rollback_archive_import_batch(
    project_id: str,
    batch_id: str,
    adapter: ArchiveEntityAdapter,
) -> dict[str, Any]:
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        batch = _scope_batch(
            conn.execute("SELECT * FROM archive_import_batches WHERE id = ?", (batch_id,)).fetchone(),
            project_id,
            adapter.kind,
            token_lookup=False,
        )
        if batch["status"] == "rolled_back":
            return json_load(batch["rollback_result_json"], {})
        if batch["status"] != "committed":
            raise ArchiveBatchError(
                409,
                "batch_not_committed",
                "只有已提交批次可以回滚。",
                batch_id=batch_id,
            )
        revisions = conn.execute(
            "SELECT * FROM archive_import_revisions WHERE batch_id = ? ORDER BY ordinal DESC",
            (batch_id,),
        ).fetchall()
        for revision in revisions:
            current = conn.execute(
                f"SELECT * FROM {adapter.table} WHERE id = ?",
                (revision["entity_id"],),
            ).fetchone()
            if current is None or adapter.row_hash(current) != str(revision["after_hash"] or ""):
                raise ArchiveBatchError(
                    409,
                    "rollback_state_drift",
                    "批次提交后的记录已被其他写入修改。",
                    batch_id=batch_id,
                )
        if adapter.preflight_rollback:
            adapter.preflight_rollback(conn, list(revisions), batch_id)
        restored = 0
        tombstoned = 0
        for revision in revisions:
            current_row = conn.execute(
                f"SELECT * FROM {adapter.table} WHERE id = ?",
                (revision["entity_id"],),
            ).fetchone()
            current = adapter.normalize_row(current_row)
            if revision["operation"] == "insert":
                current.update({"active": 0, "updated_at": db.now_iso()})
                adapter.replace_expected(conn, current)
                tombstoned += 1
            else:
                before = json_load(revision["before_json"], {})
                adapter.replace_expected(conn, before)
                restored += 1
        state_row = conn.execute(
            "SELECT version FROM archive_state_versions WHERE project_id = ? AND kind = ?",
            (project_id, adapter.kind),
        ).fetchone()
        result = {
            "project_id": project_id,
            "kind": adapter.kind,
            "batch_id": batch_id,
            "status": "rolled_back",
            "restored_count": restored,
            "tombstoned_count": tombstoned,
            "state_version": int(state_row["version"] if state_row else 0),
        }
        now = db.now_iso()
        conn.execute(
            "UPDATE archive_import_batches SET status = 'rolled_back', rollback_result_json = ?, "
            "rolled_back_at = ?, updated_at = ? WHERE id = ?",
            (json_dump(result), now, now, batch_id),
        )
        return result
