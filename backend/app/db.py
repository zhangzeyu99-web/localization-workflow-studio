from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import DB_PATH, ensure_data_dirs


ARTIFACT_ROLE_BY_KIND = {
    "language_table": "language_source",
    "term_base": "glossary_source",
    "glossary_detail": "glossary_source",
    "glossary_final": "glossary_curated",
    "final_workbook": "translation_workbook",
    "manual_fixed_workbook": "translation_workbook",
    "translation_response": "translation_response",
    "qa_report": "qa_report",
    "qa_result": "qa_report",
    "quality_summary": "qa_report",
    "semantic_qa_context": "qa_report",
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
                source TEXT NOT NULL,
                target TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT 'manual',
                confirmed INTEGER NOT NULL DEFAULT 0,
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
            """
        )
        _ensure_column(conn, "artifacts", "role", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "artifacts", "origin", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "artifacts", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")


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


def insert_glossary_term(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    term_id = new_id("term")
    ts = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO glossary_terms
              (id, project_id, source, target, category, note, source_type, confirmed, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                term_id,
                project_id,
                payload.get("source", ""),
                payload.get("target", ""),
                payload.get("category", ""),
                payload.get("note", ""),
                payload.get("source_type", "manual"),
                1 if payload.get("confirmed") else 0,
                ts,
                ts,
            ),
        )
        return get_glossary_term(term_id, conn=conn)


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


def list_glossary_terms(project_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM glossary_terms WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
        result = []
        for row in rows:
            payload = dict(row)
            payload["confirmed"] = bool(payload["confirmed"])
            result.append(payload)
        return result


def update_glossary_term(term_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {"source", "target", "category", "note", "source_type", "confirmed"}
    fields = []
    values: list[Any] = []
    for key, value in payload.items():
        if key not in allowed:
            continue
        fields.append(f"{key} = ?")
        values.append(1 if key == "confirmed" and value else value)
    fields.append("updated_at = ?")
    values.append(now_iso())
    values.append(term_id)
    with connect() as conn:
        conn.execute(f"UPDATE glossary_terms SET {', '.join(fields)} WHERE id = ?", values)
        return get_glossary_term(term_id, conn=conn)


def delete_glossary_term(term_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM glossary_terms WHERE id = ?", (term_id,))
