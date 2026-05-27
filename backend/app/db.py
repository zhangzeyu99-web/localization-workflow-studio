from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import DB_PATH, ensure_data_dirs
from .languages import ANNOUNCEMENT_LANGUAGE_ORDER, normalize_language


ARTIFACT_ROLE_BY_KIND = {
    "language_table": "language_source",
    "term_base": "glossary_source",
    "glossary_detail": "glossary_source",
    "announcement_glossary": "glossary_source",
    "glossary_final": "glossary_curated",
    "final_workbook": "translation_workbook",
    "manual_fixed_workbook": "translation_workbook",
    "qa_final_workbook": "translation_workbook",
    "raw_translated_workbook": "translation_draft",
    "translation_response": "translation_response",
    "glossary_snapshot": "run_snapshot",
    "prompt_snapshot": "run_snapshot",
    "project_harness_snapshot": "run_snapshot",
    "announcement_lookup_workbook": "reference_pack",
    "announcement_lookup_manifest": "reference_pack",
    "announcement_lookup_prompt_context": "reference_pack",
    "announcement_terms_workbook": "reference_pack",
    "announcement_terms_validation": "reference_pack",
    "announcement_terms_manifest": "reference_pack",
    "announcement_ai_supplement_packet": "reference_pack",
    "announcement_ai_supplement_report": "reference_pack",
    "announcement_translation_workbook": "translation_workbook",
    "announcement_workpack": "translation_workpack",
    "announcement_ai_response": "translation_response",
    "announcement_qa_summary": "qa_report",
    "announcement_output_file": "delivery",
    "announcement_delivery_package": "delivery",
    "announcement_docx_translation_workbook": "translation_workbook",
    "announcement_docx_manifest": "reference_pack",
    "announcement_docx_workpack": "translation_workpack",
    "announcement_docx_qa_summary": "qa_report",
    "announcement_docx_output_docx": "delivery",
    "announcement_docx_delivery_package": "delivery",
    "qa_report": "qa_report",
    "qa_result": "qa_report",
    "qa_changes": "qa_report",
    "quality_summary": "qa_report",
    "semantic_qa_context": "qa_report",
    "delivery_file": "delivery",
    "translation_prompt": "prompt",
    "compiled_style_hint": "prompt",
    "project_profile": "profile",
    "project_brief": "profile",
    "project_harness_snapshot": "harness_snapshot",
}

UPLOADED_KINDS = {"upload", "asset", "language_table", "term_base", "final_workbook"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    ensure_data_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    ensure_data_dirs()
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT '',
                icon TEXT NOT NULL DEFAULT '🎮',
                description TEXT NOT NULL DEFAULT '',
                profile_json TEXT NOT NULL DEFAULT '{}',
                prompt_text TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS glossary_terms (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                term_key TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL,
                target TEXT NOT NULL DEFAULT '',
                target_alt TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT 'en',
                category TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT 'manual',
                confirmed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );
            CREATE TABLE IF NOT EXISTS glossary_batches (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                run_id TEXT,
                source_artifact_id TEXT NOT NULL DEFAULT '',
                label TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT 'en',
                status TEXT NOT NULL DEFAULT 'pending',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id),
                FOREIGN KEY(run_id) REFERENCES runs(id)
            );
            CREATE TABLE IF NOT EXISTS glossary_candidates (
                id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                existing_term_id TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL DEFAULT 'new',
                term_key TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                target TEXT NOT NULL DEFAULT '',
                target_alt TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT 'en',
                category TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                translation_status TEXT NOT NULL DEFAULT 'needs_translation',
                translation_source TEXT NOT NULL DEFAULT 'none',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(batch_id) REFERENCES glossary_batches(id),
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );
            CREATE TABLE IF NOT EXISTS translation_entries (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                entry_key TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                target TEXT NOT NULL DEFAULT '',
                target_alt TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT 'en',
                sheet TEXT NOT NULL DEFAULT '',
                row_number INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT 'manual',
                source_artifact_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                language TEXT NOT NULL DEFAULT 'en',
                status TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                run_id TEXT,
                label TEXT NOT NULL,
                kind TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT '',
                origin TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                path TEXT NOT NULL,
                mime TEXT NOT NULL DEFAULT 'application/octet-stream',
                size INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id),
                FOREIGN KEY(run_id) REFERENCES runs(id)
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES runs(id)
            );
            CREATE TABLE IF NOT EXISTS announcement_tasks (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                source_artifact_id TEXT NOT NULL DEFAULT '',
                source_format TEXT NOT NULL DEFAULT '',
                selected_languages_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'draft',
                current_step INTEGER NOT NULL DEFAULT 1,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );
            CREATE TABLE IF NOT EXISTS announcement_task_languages (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                language TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                current_step INTEGER NOT NULL DEFAULT 1,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(task_id, language),
                FOREIGN KEY(task_id) REFERENCES announcement_tasks(id),
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );
            """
        )
        _ensure_column(conn, "artifacts", "role", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "artifacts", "origin", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "artifacts", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "glossary_terms", "term_key", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "glossary_terms", "target_alt", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "glossary_terms", "language", "TEXT NOT NULL DEFAULT 'en'")
        _ensure_column(conn, "glossary_batches", "language", "TEXT NOT NULL DEFAULT 'en'")
        _ensure_column(conn, "glossary_candidates", "language", "TEXT NOT NULL DEFAULT 'en'")
        _ensure_column(conn, "glossary_batches", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "glossary_candidates", "translation_status", "TEXT NOT NULL DEFAULT 'needs_translation'")
        _ensure_column(conn, "glossary_candidates", "translation_source", "TEXT NOT NULL DEFAULT 'none'")
        _ensure_column(conn, "glossary_candidates", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "translation_entries", "target_alt", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "translation_entries", "language", "TEXT NOT NULL DEFAULT 'en'")
        _ensure_column(conn, "translation_entries", "source_artifact_id", "TEXT NOT NULL DEFAULT ''")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    for key in ("profile_json", "metadata_json"):
        if key in payload:
            payload[key.replace("_json", "")] = json.loads(payload.pop(key) or "{}")
    return payload


def infer_artifact_role(kind: str) -> str:
    return ARTIFACT_ROLE_BY_KIND.get(kind, kind or "upload")


def infer_artifact_origin(kind: str) -> str:
    return "uploaded" if kind in UPLOADED_KINDS else "generated"


def artifact_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["metadata"] = json.loads(payload.pop("metadata_json", "{}") or "{}")
    payload["role"] = payload.get("role") or infer_artifact_role(str(payload.get("kind", "")))
    payload["origin"] = payload.get("origin") or infer_artifact_origin(str(payload.get("kind", "")))
    return payload


def insert_project(name: str, project_type: str = "", description: str = "", icon: str = "🎮") -> dict[str, Any]:
    project_id = new_id("proj")
    ts = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO projects (id, name, type, icon, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, name, project_type, icon, description, ts, ts),
        )
        return get_project(project_id, conn=conn)


def find_project_by_name(name: str) -> dict[str, Any] | None:
    normalized = _project_name_key(name)
    if not normalized:
        return None
    with connect() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY created_at ASC").fetchall()
        for row in rows:
            if _project_name_key(row["name"]) == normalized:
                return row_to_dict(row)
    return None


def _project_name_key(value: Any) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def get_project(project_id: str, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own = conn is None
    ctx = connect() if own else None
    active = ctx.__enter__() if ctx else conn
    try:
        row = active.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(project_id)
        return row_to_dict(row)
    finally:
        if ctx:
            ctx.__exit__(None, None, None)


def list_projects() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [row_to_dict(row) for row in rows]


def update_project(project_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    allowed = {"name", "type", "icon", "description", "prompt_text"}
    fields: list[str] = []
    values: list[Any] = []
    for key, value in updates.items():
        if key == "profile":
            fields.append("profile_json = ?")
            values.append(json.dumps(value or {}, ensure_ascii=False))
        elif key in allowed:
            fields.append(f"{key} = ?")
            values.append(value)
    fields.append("updated_at = ?")
    values.append(now_iso())
    values.append(project_id)
    with connect() as conn:
        conn.execute(f"UPDATE projects SET {', '.join(fields)} WHERE id = ?", values)
        return get_project(project_id, conn=conn)


def insert_run(project_id: str, kind: str, language: str = "en", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    run_id = new_id("run")
    ts = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO runs (id, project_id, kind, language, status, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, project_id, kind, language, "queued", json.dumps(metadata or {}, ensure_ascii=False), ts, ts),
        )
        return get_run(run_id, conn=conn)


def get_run(run_id: str, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own = conn is None
    ctx = connect() if own else None
    active = ctx.__enter__() if ctx else conn
    try:
        row = active.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return row_to_dict(row)
    finally:
        if ctx:
            ctx.__exit__(None, None, None)


def update_run(run_id: str, status: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    fields = ["updated_at = ?"]
    values: list[Any] = [now_iso()]
    if status:
        fields.append("status = ?")
        values.append(status)
    if metadata is not None:
        fields.append("metadata_json = ?")
        values.append(json.dumps(metadata, ensure_ascii=False))
    values.append(run_id)
    with connect() as conn:
        conn.execute(f"UPDATE runs SET {', '.join(fields)} WHERE id = ?", values)
        return get_run(run_id, conn=conn)


def list_runs(project_id: str | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        if project_id:
            rows = conn.execute("SELECT * FROM runs WHERE project_id = ? ORDER BY created_at DESC", (project_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
        return [row_to_dict(row) for row in rows]


def add_event(run_id: str, message: str, level: str = "info") -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO events (run_id, level, message, created_at) VALUES (?, ?, ?, ?)",
            (run_id, level, message, now_iso()),
        )


def list_events(run_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM events WHERE run_id = ? ORDER BY id ASC", (run_id,)).fetchall()
        return [dict(row) for row in rows]


def announcement_task_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["selected_languages"] = json.loads(payload.pop("selected_languages_json", "[]") or "[]")
    payload["metadata"] = json.loads(payload.pop("metadata_json", "{}") or "{}")
    return payload


def announcement_task_language_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["metadata"] = json.loads(payload.pop("metadata_json", "{}") or "{}")
    return payload


def insert_announcement_task(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    task_id = new_id("ann")
    ts = now_iso()
    selected_languages = [normalize_language(code) for code in payload.get("selected_languages", []) if normalize_language(code) in set(ANNOUNCEMENT_LANGUAGE_ORDER)]
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO announcement_tasks
              (id, project_id, title, source_artifact_id, source_format, selected_languages_json, status, current_step, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                project_id,
                str(payload.get("title") or "").strip(),
                str(payload.get("source_artifact_id") or "").strip(),
                str(payload.get("source_format") or "").strip(),
                json.dumps(selected_languages, ensure_ascii=False),
                str(payload.get("status") or "draft"),
                int(payload.get("current_step") or 1),
                json.dumps(payload.get("metadata") or {}, ensure_ascii=False),
                ts,
                ts,
            ),
        )
        for language in selected_languages:
            _upsert_announcement_task_language(conn, task_id, project_id, language, {"status": "draft", "current_step": 1, "metadata": {}})
        return get_announcement_task(task_id, conn=conn)


def get_announcement_task(task_id: str, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own = conn is None
    ctx = connect() if own else None
    active = ctx.__enter__() if ctx else conn
    try:
        row = active.execute("SELECT * FROM announcement_tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        task = announcement_task_row_to_dict(row)
        task["languages"] = [
            announcement_task_language_row_to_dict(lang_row)
            for lang_row in active.execute(
                "SELECT * FROM announcement_task_languages WHERE task_id = ? ORDER BY language ASC",
                (task_id,),
            ).fetchall()
        ]
        return task
    finally:
        if ctx:
            ctx.__exit__(None, None, None)


def list_announcement_tasks(project_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM announcement_tasks WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
        return [get_announcement_task(row["id"], conn=conn) for row in rows]


def update_announcement_task(
    task_id: str,
    *,
    status: str | None = None,
    current_step: int | None = None,
    selected_languages: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    source_artifact_id: str | None = None,
    source_format: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    fields = ["updated_at = ?"]
    values: list[Any] = [now_iso()]
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if current_step is not None:
        fields.append("current_step = ?")
        values.append(int(current_step))
    if selected_languages is not None:
        normalized = [normalize_language(code) for code in selected_languages if normalize_language(code) in set(ANNOUNCEMENT_LANGUAGE_ORDER)]
        fields.append("selected_languages_json = ?")
        values.append(json.dumps(normalized, ensure_ascii=False))
    if metadata is not None:
        fields.append("metadata_json = ?")
        values.append(json.dumps(metadata, ensure_ascii=False))
    if source_artifact_id is not None:
        fields.append("source_artifact_id = ?")
        values.append(source_artifact_id)
    if source_format is not None:
        fields.append("source_format = ?")
        values.append(source_format)
    if title is not None:
        fields.append("title = ?")
        values.append(title)
    values.append(task_id)
    with connect() as conn:
        conn.execute(f"UPDATE announcement_tasks SET {', '.join(fields)} WHERE id = ?", values)
        task = get_announcement_task(task_id, conn=conn)
        if selected_languages is not None:
            for language in task["selected_languages"]:
                _upsert_announcement_task_language(conn, task_id, task["project_id"], language, {"status": "draft", "current_step": task["current_step"], "metadata": {}})
        return get_announcement_task(task_id, conn=conn)


def upsert_announcement_task_language(
    task_id: str,
    project_id: str,
    language: str,
    *,
    status: str | None = None,
    current_step: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    language = normalize_language(language)
    with connect() as conn:
        return _upsert_announcement_task_language(
            conn,
            task_id,
            project_id,
            language,
            {"status": status, "current_step": current_step, "metadata": metadata},
        )


def _upsert_announcement_task_language(
    conn: sqlite3.Connection,
    task_id: str,
    project_id: str,
    language: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM announcement_task_languages WHERE task_id = ? AND language = ?",
        (task_id, language),
    ).fetchone()
    ts = now_iso()
    if row is None:
        lang_id = new_id("annlang")
        conn.execute(
            """
            INSERT INTO announcement_task_languages
              (id, task_id, project_id, language, status, current_step, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lang_id,
                task_id,
                project_id,
                language,
                str(payload.get("status") or "draft"),
                int(payload.get("current_step") or 1),
                json.dumps(payload.get("metadata") or {}, ensure_ascii=False),
                ts,
                ts,
            ),
        )
    else:
        existing = announcement_task_language_row_to_dict(row)
        status = payload.get("status") if payload.get("status") is not None else existing["status"]
        current_step = payload.get("current_step") if payload.get("current_step") is not None else existing["current_step"]
        metadata = payload.get("metadata") if payload.get("metadata") is not None else existing["metadata"]
        conn.execute(
            """
            UPDATE announcement_task_languages
            SET status = ?, current_step = ?, metadata_json = ?, updated_at = ?
            WHERE task_id = ? AND language = ?
            """,
            (status, int(current_step), json.dumps(metadata or {}, ensure_ascii=False), ts, task_id, language),
        )
    row = conn.execute(
        "SELECT * FROM announcement_task_languages WHERE task_id = ? AND language = ?",
        (task_id, language),
    ).fetchone()
    if row is None:
        raise KeyError(language)
    return announcement_task_language_row_to_dict(row)


def add_artifact(
    project_id: str,
    label: str,
    path: str | Path,
    kind: str,
    run_id: str | None = None,
    mime: str = "application/octet-stream",
    role: str | None = None,
    origin: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact_id = new_id("art")
    file_path = Path(path)
    ts = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO artifacts (id, project_id, run_id, label, kind, role, origin, metadata_json, path, mime, size, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                project_id,
                run_id,
                label,
                kind,
                role or infer_artifact_role(kind),
                origin or infer_artifact_origin(kind),
                json.dumps(metadata or {}, ensure_ascii=False),
                str(file_path),
                mime,
                file_path.stat().st_size if file_path.exists() else 0,
                ts,
            ),
        )
        return get_artifact(artifact_id, conn=conn)


def get_artifact(artifact_id: str, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own = conn is None
    ctx = connect() if own else None
    active = ctx.__enter__() if ctx else conn
    try:
        row = active.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return artifact_row_to_dict(row)
    finally:
        if ctx:
            ctx.__exit__(None, None, None)


def list_artifacts(
    project_id: str | None = None,
    run_id: str | None = None,
    role: str | None = None,
    origin: str | None = None,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM artifacts"
    clauses: list[str] = []
    values: list[str] = []
    if project_id:
        clauses.append("project_id = ?")
        values.append(project_id)
    if run_id:
        clauses.append("run_id = ?")
        values.append(run_id)
    if role:
        legacy_kinds = _kinds_for_role(role)
        if legacy_kinds:
            clauses.append("(role = ? OR (role = '' AND kind IN ({0})))".format(",".join("?" for _ in legacy_kinds)))
            values.append(role)
            values.extend(legacy_kinds)
        else:
            clauses.append("role = ?")
            values.append(role)
    if origin:
        clauses.append("origin = ?")
        values.append(origin)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC"
    with connect() as conn:
        artifacts = [artifact_row_to_dict(row) for row in conn.execute(query, values).fetchall()]
        if role:
            artifacts = [artifact for artifact in artifacts if artifact["role"] == role]
        if origin:
            artifacts = [artifact for artifact in artifacts if artifact["origin"] == origin]
        return artifacts


def _kinds_for_role(role: str) -> list[str]:
    return [kind for kind, mapped_role in ARTIFACT_ROLE_BY_KIND.items() if mapped_role == role]


def update_artifact(artifact_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    allowed = {"label", "role", "origin"}
    fields: list[str] = []
    values: list[Any] = []
    for key, value in updates.items():
        if key == "metadata":
            fields.append("metadata_json = ?")
            values.append(json.dumps(value or {}, ensure_ascii=False))
        elif key in allowed:
            fields.append(f"{key} = ?")
            values.append(value or "")
    if not fields:
        return get_artifact(artifact_id)
    values.append(artifact_id)
    with connect() as conn:
        conn.execute(f"UPDATE artifacts SET {', '.join(fields)} WHERE id = ?", values)
        return get_artifact(artifact_id, conn=conn)


def batch_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["metadata"] = json.loads(payload.pop("metadata_json", "{}") or "{}")
    return payload


def create_glossary_batch(
    project_id: str,
    run_id: str | None = None,
    source_artifact_id: str = "",
    label: str = "",
    language: str = "en",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    batch_id = new_id("gb")
    ts = now_iso()
    language = normalize_language(language)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO glossary_batches
              (id, project_id, run_id, source_artifact_id, label, language, status, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                project_id,
                run_id,
                source_artifact_id,
                label or "Glossary scan batch",
                language,
                "pending",
                json.dumps(metadata or {}, ensure_ascii=False),
                ts,
                ts,
            ),
        )
        return get_glossary_batch(batch_id, conn=conn)


def get_glossary_batch(batch_id: str, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own = conn is None
    ctx = connect() if own else None
    active = ctx.__enter__() if ctx else conn
    try:
        row = active.execute("SELECT * FROM glossary_batches WHERE id = ?", (batch_id,)).fetchone()
        if row is None:
            raise KeyError(batch_id)
        return batch_row_to_dict(row)
    finally:
        if ctx:
            ctx.__exit__(None, None, None)


def list_glossary_batches(project_id: str, language: str | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        clauses = ["project_id = ?"]
        values: list[Any] = [project_id]
        if language:
            clauses.append("language = ?")
            values.append(normalize_language(language))
        batches = [
            _with_candidate_counts(conn, batch_row_to_dict(row))
            for row in conn.execute(
                "SELECT * FROM glossary_batches WHERE " + " AND ".join(clauses) + " ORDER BY created_at DESC",
                values,
            ).fetchall()
        ]
        return batches


def latest_glossary_batch(project_id: str, language: str | None = None) -> dict[str, Any] | None:
    batches = list_glossary_batches(project_id, language=language)
    return batches[0] if batches else None


def _with_candidate_counts(conn: sqlite3.Connection, batch: dict[str, Any]) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
          SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END) AS accepted,
          SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) AS rejected,
          SUM(CASE WHEN action = 'new' AND status = 'pending' THEN 1 ELSE 0 END) AS pending_new,
          SUM(CASE WHEN action = 'supplement' AND status = 'pending' THEN 1 ELSE 0 END) AS pending_supplement
        FROM glossary_candidates
        WHERE batch_id = ?
        """,
        (batch["id"],),
    ).fetchone()
    batch["counts"] = {key: int(rows[key] or 0) for key in rows.keys()}
    return batch


def add_glossary_candidate(project_id: str, batch_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    candidate_id = new_id("gc")
    ts = now_iso()
    target = str(payload.get("target") or "").strip()
    language = normalize_language(payload.get("language") or get_glossary_batch(batch_id).get("language") or "en")
    translation_status = payload.get("translation_status") or ("suggested" if target else "needs_translation")
    translation_source = payload.get("translation_source") or ("language_table" if target else "none")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO glossary_candidates
              (id, batch_id, project_id, existing_term_id, action, term_key, source, target, target_alt, language, category, note, translation_status, translation_source, metadata_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                batch_id,
                project_id,
                payload.get("existing_term_id", ""),
                payload.get("action", "new"),
                payload.get("term_key", ""),
                payload.get("source", ""),
                target,
                payload.get("target_alt", ""),
                language,
                payload.get("category", ""),
                payload.get("note", ""),
                translation_status,
                translation_source,
                json.dumps(payload.get("metadata") or {}, ensure_ascii=False),
                payload.get("status", "pending"),
                ts,
                ts,
            ),
        )
        return get_glossary_candidate(candidate_id, conn=conn)


def candidate_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["metadata"] = json.loads(payload.pop("metadata_json", "{}") or "{}")
    return payload


def get_glossary_candidate(candidate_id: str, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own = conn is None
    ctx = connect() if own else None
    active = ctx.__enter__() if ctx else conn
    try:
        row = active.execute("SELECT * FROM glossary_candidates WHERE id = ?", (candidate_id,)).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        return candidate_row_to_dict(row)
    finally:
        if ctx:
            ctx.__exit__(None, None, None)


def list_glossary_candidates(project_id: str, batch_id: str | None = None, status: str | None = None, language: str | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        return _list_glossary_candidates(conn, project_id, batch_id, status, language=language)


def _list_glossary_candidates(
    conn: sqlite3.Connection,
    project_id: str,
    batch_id: str | None = None,
    status: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["project_id = ?"]
    values: list[Any] = [project_id]
    if batch_id:
        clauses.append("batch_id = ?")
        values.append(batch_id)
    if status:
        clauses.append("status = ?")
        values.append(status)
    if language:
        clauses.append("language = ?")
        values.append(normalize_language(language))
    query = "SELECT * FROM glossary_candidates WHERE " + " AND ".join(clauses)
    query += """
        ORDER BY
          CASE status WHEN 'pending' THEN 0 WHEN 'accepted' THEN 1 ELSE 2 END,
          CASE action WHEN 'new' THEN 0 ELSE 1 END,
          updated_at DESC
    """
    return [candidate_row_to_dict(row) for row in conn.execute(query, values).fetchall()]


def update_glossary_candidate(candidate_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    allowed = {"term_key", "source", "target", "target_alt", "language", "category", "note", "status", "translation_status", "translation_source", "metadata"}
    fields: list[str] = []
    values: list[Any] = []
    for key, value in updates.items():
        if key in allowed:
            if key == "metadata":
                fields.append("metadata_json = ?")
                values.append(json.dumps(value or {}, ensure_ascii=False))
            else:
                fields.append(f"{key} = ?")
                values.append(normalize_language(value) if key == "language" else value or "")
    if "target" in updates and str(updates.get("target") or "").strip():
        if "translation_status" not in updates:
            fields.append("translation_status = ?")
            values.append("suggested")
        if "translation_source" not in updates:
            fields.append("translation_source = ?")
            values.append("manual")
    if not fields:
        return get_glossary_candidate(candidate_id)
    fields.append("updated_at = ?")
    values.append(now_iso())
    values.append(candidate_id)
    with connect() as conn:
        conn.execute(f"UPDATE glossary_candidates SET {', '.join(fields)} WHERE id = ?", values)
        candidate = get_glossary_candidate(candidate_id, conn=conn)
        _refresh_glossary_batch_status(conn, candidate["batch_id"])
        return candidate


def accept_glossary_candidates(project_id: str, batch_id: str, candidate_ids: list[str] | None = None) -> dict[str, Any]:
    return _resolve_glossary_candidates(project_id, batch_id, "accepted", candidate_ids)


def reject_glossary_candidates(project_id: str, batch_id: str, candidate_ids: list[str] | None = None) -> dict[str, Any]:
    return _resolve_glossary_candidates(project_id, batch_id, "rejected", candidate_ids)


def _resolve_glossary_candidates(project_id: str, batch_id: str, status: str, candidate_ids: list[str] | None = None) -> dict[str, Any]:
    if status not in {"accepted", "rejected"}:
        raise ValueError(status)
    with connect() as conn:
        batch = get_glossary_batch(batch_id, conn=conn)
        if batch["project_id"] != project_id:
            raise KeyError(batch_id)
        clauses = ["project_id = ?", "batch_id = ?", "status = 'pending'"]
        values: list[Any] = [project_id, batch_id]
        if candidate_ids:
            clauses.append("id IN ({0})".format(",".join("?" for _ in candidate_ids)))
            values.extend(candidate_ids)
        rows = conn.execute("SELECT * FROM glossary_candidates WHERE " + " AND ".join(clauses), values).fetchall()
        candidates = [candidate_row_to_dict(row) for row in rows]
        blocked_candidates: list[dict[str, Any]] = []
        accepted_terms: list[dict[str, Any]] = []
        for candidate in candidates:
            if status == "accepted" and not str(candidate.get("target") or "").strip():
                blocked_candidates.append({**candidate, "block_reason": "missing_target"})
                continue
            if status == "accepted":
                accepted_terms.append(_apply_glossary_candidate(conn, candidate))
            conn.execute(
                "UPDATE glossary_candidates SET status = ?, updated_at = ? WHERE id = ?",
                (status, now_iso(), candidate["id"]),
            )
        _refresh_glossary_batch_status(conn, batch_id)
        return {
            "batch": _with_candidate_counts(conn, get_glossary_batch(batch_id, conn=conn)),
            "resolved_count": len(candidates) - len(blocked_candidates),
            "blocked_count": len(blocked_candidates),
            "blocked_candidates": blocked_candidates,
            "accepted_terms": accepted_terms,
            "candidates": _list_glossary_candidates(conn, project_id, batch_id=batch_id, language=batch.get("language")),
        }


def _apply_glossary_candidate(conn: sqlite3.Connection, candidate: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "term_key": candidate.get("term_key", ""),
        "source": candidate.get("source", ""),
        "target": candidate.get("target", ""),
        "target_alt": candidate.get("target_alt", ""),
        "language": normalize_language(candidate.get("language") or "en"),
        "category": candidate.get("category", ""),
        "note": candidate.get("note", ""),
        "confirmed": True,
    }
    existing_term_id = str(candidate.get("existing_term_id") or "")
    if existing_term_id:
        existing = get_glossary_term(existing_term_id, conn=conn)
        updates = {
            "term_key": payload["term_key"] or existing.get("term_key", ""),
            "source": payload["source"] or existing.get("source", ""),
            "target": payload["target"],
            "target_alt": payload["target_alt"],
            "language": payload["language"],
            "category": payload["category"] or existing.get("category", ""),
            "note": payload["note"],
            "confirmed": True,
        }
        return update_glossary_term(existing_term_id, updates, conn=conn)
    payload["source_type"] = "generated"
    return insert_glossary_term(candidate["project_id"], payload, conn=conn)


def _refresh_glossary_batch_status(conn: sqlite3.Connection, batch_id: str) -> None:
    row = conn.execute(
        """
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending
        FROM glossary_candidates
        WHERE batch_id = ?
        """,
        (batch_id,),
    ).fetchone()
    total = int(row["total"] or 0)
    pending = int(row["pending"] or 0)
    status = "empty" if total == 0 else "pending" if pending else "resolved"
    conn.execute("UPDATE glossary_batches SET status = ?, updated_at = ? WHERE id = ?", (status, now_iso(), batch_id))


def insert_glossary_term(project_id: str, payload: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    term_id = new_id("term")
    ts = now_iso()
    language = normalize_language(payload.get("language") or "en")
    own = conn is None
    ctx = connect() if own else None
    active = ctx.__enter__() if ctx else conn
    try:
        active.execute(
            """
            INSERT INTO glossary_terms
              (id, project_id, term_key, source, target, target_alt, language, category, note, source_type, confirmed, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                term_id,
                project_id,
                payload.get("term_key", ""),
                payload.get("source", ""),
                payload.get("target", ""),
                payload.get("target_alt", ""),
                language,
                payload.get("category", ""),
                payload.get("note", ""),
                payload.get("source_type", "manual"),
                1 if payload.get("confirmed") else 0,
                ts,
                ts,
            ),
        )
        return get_glossary_term(term_id, conn=active)
    finally:
        if ctx:
            ctx.__exit__(None, None, None)


def upsert_glossary_term(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    source_key = _glossary_source_key(payload.get("source"))
    language = normalize_language(payload.get("language") or "en")
    payload = {**payload, "language": language}
    if not source_key:
        return insert_glossary_term(project_id, payload)
    with connect() as conn:
        rows = _glossary_rows_by_source_key(conn, project_id, source_key, language)
        if not rows:
            return insert_glossary_term(project_id, payload)
        canonical = _choose_glossary_canonical(rows)
        updates: dict[str, Any] = {}
        for field in ("term_key", "source", "target", "target_alt", "language", "category", "note"):
            value = payload.get(field)
            if value is not None and str(value).strip():
                updates[field] = value
        if payload.get("source_type"):
            updates["source_type"] = payload["source_type"]
        if "confirmed" in payload:
            updates["confirmed"] = bool(payload.get("confirmed"))
        if updates:
            update_glossary_term(canonical["id"], updates)
        dedupe_project_glossary_terms(project_id, preferred_term_id=canonical["id"], merge_duplicates=False)
        return get_glossary_term(canonical["id"])


def get_glossary_term(term_id: str, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own = conn is None
    ctx = connect() if own else None
    active = ctx.__enter__() if ctx else conn
    try:
        row = active.execute("SELECT * FROM glossary_terms WHERE id = ?", (term_id,)).fetchone()
        if row is None:
            raise KeyError(term_id)
        payload = dict(row)
        payload["confirmed"] = bool(payload["confirmed"])
        return payload
    finally:
        if ctx:
            ctx.__exit__(None, None, None)


def list_glossary_terms(project_id: str, language: str | None = None) -> list[dict[str, Any]]:
    dedupe_project_glossary_terms(project_id, language=language)
    with connect() as conn:
        clauses = ["project_id = ?", "confirmed = 1"]
        values: list[Any] = [project_id]
        if language:
            clauses.append("language = ?")
            values.append(normalize_language(language))
        rows = conn.execute(
            """
            SELECT * FROM glossary_terms
            WHERE """ + " AND ".join(clauses) + """
            ORDER BY
              confirmed ASC,
              CASE
                WHEN TRIM(target) = '' AND TRIM(target_alt) = '' THEN 0
                ELSE 1
              END ASC,
              updated_at DESC
            """,
            values,
        ).fetchall()
        result = []
        for row in rows:
            payload = dict(row)
            payload["confirmed"] = bool(payload["confirmed"])
            result.append(payload)
        return result


def dedupe_project_glossary_terms(
    project_id: str,
    preferred_term_id: str | None = None,
    merge_duplicates: bool = True,
    language: str | None = None,
) -> dict[str, Any]:
    result = {"groups": 0, "deleted": 0, "updated": 0, "canonical_id": ""}
    with connect() as conn:
        clauses = ["project_id = ?"]
        values: list[Any] = [project_id]
        if language:
            clauses.append("language = ?")
            values.append(normalize_language(language))
        rows = conn.execute("SELECT * FROM glossary_terms WHERE " + " AND ".join(clauses), values).fetchall()
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            payload = dict(row)
            source_key = _glossary_source_key(payload.get("source"))
            if not source_key:
                continue
            key = (normalize_language(payload.get("language") or "en"), source_key)
            groups.setdefault(key, []).append(payload)

        for terms in groups.values():
            if len(terms) < 2:
                continue
            result["groups"] += 1
            canonical = _choose_glossary_canonical(terms, preferred_term_id)
            result["canonical_id"] = canonical["id"]
            duplicates = [term for term in terms if term["id"] != canonical["id"]]
            updates: dict[str, Any] = {}
            if merge_duplicates:
                for duplicate in duplicates:
                    for field in ("term_key", "target", "target_alt", "category", "note"):
                        incoming = duplicate.get(field)
                        if _glossary_blank(canonical.get(field)) and not _glossary_blank(incoming):
                            canonical[field] = incoming
                            updates[field] = incoming
                    if not bool(canonical.get("confirmed")) and bool(duplicate.get("confirmed")):
                        canonical["confirmed"] = True
                        updates["confirmed"] = True
                    if _glossary_source_type_rank(canonical.get("source_type")) > _glossary_source_type_rank(duplicate.get("source_type")):
                        canonical["source_type"] = duplicate.get("source_type") or ""
                        updates["source_type"] = canonical["source_type"]
            if updates:
                assignments = []
                values: list[Any] = []
                for key, value in updates.items():
                    assignments.append(f"{key} = ?")
                    values.append(1 if key == "confirmed" and value else value)
                assignments.append("updated_at = ?")
                values.append(now_iso())
                values.append(canonical["id"])
                conn.execute(f"UPDATE glossary_terms SET {', '.join(assignments)} WHERE id = ?", values)
                result["updated"] += 1
            duplicate_ids = [term["id"] for term in duplicates]
            if duplicate_ids:
                conn.executemany("DELETE FROM glossary_terms WHERE id = ?", [(term_id,) for term_id in duplicate_ids])
                result["deleted"] += len(duplicate_ids)
    return result


def _glossary_rows_by_source_key(conn: sqlite3.Connection, project_id: str, source_key: str, language: str = "en") -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM glossary_terms WHERE project_id = ? AND language = ?",
        (project_id, normalize_language(language)),
    ).fetchall()
    return [dict(row) for row in rows if _glossary_source_key(row["source"]) == source_key]


def _choose_glossary_canonical(terms: list[dict[str, Any]], preferred_term_id: str | None = None) -> dict[str, Any]:
    if preferred_term_id:
        for term in terms:
            if term["id"] == preferred_term_id:
                return term
    return sorted(terms, key=_glossary_term_rank)[0]


def _glossary_term_rank(term: dict[str, Any]) -> tuple[int, int, int, str]:
    has_translation = not _glossary_blank(term.get("target")) or not _glossary_blank(term.get("target_alt"))
    confirmed = bool(term.get("confirmed"))
    return (
        0 if confirmed else 1,
        0 if has_translation else 1,
        _glossary_source_type_rank(term.get("source_type")),
        str(term.get("updated_at") or ""),
    )


def _glossary_source_type_rank(value: Any) -> int:
    source_type = str(value or "").strip()
    if source_type in {"manual", "curated"}:
        return 0
    if source_type == "imported":
        return 1
    if source_type == "generated":
        return 2
    return 3


def _glossary_source_key(value: Any) -> str:
    return "".join(str(value or "").split()).casefold()


def _glossary_blank(value: Any) -> bool:
    return str(value or "").strip() in {"", "-"}


def update_glossary_term(term_id: str, payload: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    allowed = {"term_key", "source", "target", "target_alt", "language", "category", "note", "source_type", "confirmed"}
    fields = []
    values: list[Any] = []
    for key, value in payload.items():
        if key not in allowed:
            continue
        fields.append(f"{key} = ?")
        if key == "confirmed":
            values.append(1 if value else 0)
        elif key == "language":
            values.append(normalize_language(value))
        else:
            values.append(value)
    fields.append("updated_at = ?")
    values.append(now_iso())
    values.append(term_id)
    own = conn is None
    ctx = connect() if own else None
    active = ctx.__enter__() if ctx else conn
    try:
        active.execute(f"UPDATE glossary_terms SET {', '.join(fields)} WHERE id = ?", values)
        return get_glossary_term(term_id, conn=active)
    finally:
        if ctx:
            ctx.__exit__(None, None, None)


def delete_glossary_term(term_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM glossary_terms WHERE id = ?", (term_id,))


def insert_translation_entry(project_id: str, payload: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    entry_id = new_id("tr")
    ts = now_iso()
    language = normalize_language(payload.get("language") or "en")
    own = conn is None
    ctx = connect() if own else None
    active = ctx.__enter__() if ctx else conn
    try:
        active.execute(
            """
            INSERT INTO translation_entries
              (id, project_id, entry_key, source, target, target_alt, language, sheet, row_number, note, source_type, source_artifact_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                project_id,
                str(payload.get("entry_key") or "").strip(),
                str(payload.get("source") or "").strip(),
                str(payload.get("target") or "").strip(),
                str(payload.get("target_alt") or "").strip(),
                language,
                str(payload.get("sheet") or "").strip(),
                int(payload.get("row_number") or 0),
                str(payload.get("note") or "").strip(),
                str(payload.get("source_type") or "manual").strip() or "manual",
                str(payload.get("source_artifact_id") or "").strip(),
                ts,
                ts,
            ),
        )
        return get_translation_entry(entry_id, conn=active)
    finally:
        if ctx:
            ctx.__exit__(None, None, None)


def upsert_translation_entry(project_id: str, payload: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own = conn is None
    ctx = connect() if own else None
    active = ctx.__enter__() if ctx else conn
    try:
        existing = _find_translation_entry(active, project_id, payload)
        if existing is None:
            return insert_translation_entry(project_id, payload, conn=active)
        updates = {
            key: payload.get(key)
            for key in ("entry_key", "source", "target", "target_alt", "language", "sheet", "row_number", "note", "source_type", "source_artifact_id")
            if payload.get(key) not in (None, "")
        }
        return update_translation_entry(existing["id"], updates, conn=active)
    finally:
        if ctx:
            ctx.__exit__(None, None, None)


def _find_translation_entry(conn: sqlite3.Connection, project_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    entry_key = str(payload.get("entry_key") or "").strip()
    language = normalize_language(payload.get("language") or "en")
    if entry_key:
        row = conn.execute(
            "SELECT * FROM translation_entries WHERE project_id = ? AND entry_key = ? AND language = ? LIMIT 1",
            (project_id, entry_key, language),
        ).fetchone()
        if row:
            return dict(row)
    source_key = _translation_source_key(payload.get("source"))
    if source_key:
        rows = conn.execute("SELECT * FROM translation_entries WHERE project_id = ? AND language = ?", (project_id, language)).fetchall()
        for row in rows:
            if _translation_source_key(row["source"]) == source_key:
                return dict(row)
    return None


def get_translation_entry(entry_id: str, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own = conn is None
    ctx = connect() if own else None
    active = ctx.__enter__() if ctx else conn
    try:
        row = active.execute("SELECT * FROM translation_entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            raise KeyError(entry_id)
        return dict(row)
    finally:
        if ctx:
            ctx.__exit__(None, None, None)


def list_translation_entries(project_id: str, language: str | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        if language:
            rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM translation_entries WHERE project_id = ? AND language = ?",
                    (project_id, normalize_language(language)),
                ).fetchall()
            ]
        else:
            rows = [dict(row) for row in conn.execute("SELECT * FROM translation_entries WHERE project_id = ?", (project_id,)).fetchall()]
    return sorted(rows, key=_translation_entry_rank)


def update_translation_entry(entry_id: str, payload: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    allowed = {"entry_key", "source", "target", "target_alt", "language", "sheet", "row_number", "note", "source_type", "source_artifact_id"}
    fields: list[str] = []
    values: list[Any] = []
    for key, value in payload.items():
        if key not in allowed:
            continue
        fields.append(f"{key} = ?")
        values.append(normalize_language(value) if key == "language" else value)
    fields.append("updated_at = ?")
    values.append(now_iso())
    values.append(entry_id)
    own = conn is None
    ctx = connect() if own else None
    active = ctx.__enter__() if ctx else conn
    try:
        active.execute(f"UPDATE translation_entries SET {', '.join(fields)} WHERE id = ?", values)
        return get_translation_entry(entry_id, conn=active)
    finally:
        if ctx:
            ctx.__exit__(None, None, None)


def delete_translation_entry(entry_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM translation_entries WHERE id = ?", (entry_id,))


def _translation_entry_rank(entry: dict[str, Any]) -> tuple[int, int, str, str]:
    key = str(entry.get("entry_key") or "").strip()
    if key.isdigit():
        return (0, int(key), str(entry.get("sheet") or ""), str(entry.get("source") or ""))
    return (1, int(entry.get("row_number") or 0), key, str(entry.get("source") or ""))


def _translation_source_key(value: Any) -> str:
    return "".join(str(value or "").split()).casefold()
