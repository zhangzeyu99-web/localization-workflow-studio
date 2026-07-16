from __future__ import annotations

import sqlite3


def _source_key(value: object) -> str:
    return "".join(str(value or "").split()).casefold()


def _backfill_source_keys(conn: sqlite3.Connection, table: str, kind: str) -> None:
    rows = conn.execute(
        f"SELECT id, project_id, source FROM {table} WHERE source_key = '' AND TRIM(source) <> ''"
    ).fetchall()
    if not rows:
        return
    project_ids = sorted({str(row["project_id"]) for row in rows})
    placeholders = ",".join("?" for _ in project_ids)
    has_state_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'archive_state_versions'"
    ).fetchone()
    prior_versions: dict[str, int] = {}
    if has_state_table:
        prior_versions = {
            str(row["project_id"]): int(row["version"])
            for row in conn.execute(
                f"SELECT project_id, version FROM archive_state_versions "
                f"WHERE kind = ? AND project_id IN ({placeholders})",
                [kind, *project_ids],
            ).fetchall()
        }
    conn.executemany(
        f"UPDATE {table} SET source_key = ? WHERE id = ?",
        [(_source_key(row["source"]), row["id"]) for row in rows],
    )
    if has_state_table:
        conn.execute(
            f"DELETE FROM archive_state_versions WHERE kind = ? AND project_id IN ({placeholders})",
            [kind, *project_ids],
        )
        conn.executemany(
            "INSERT INTO archive_state_versions(project_id, kind, version) VALUES (?, ?, ?)",
            [(project_id, kind, version) for project_id, version in prior_versions.items()],
        )


def ensure_archive_import_schema(conn: sqlite3.Connection) -> None:
    """Install the generic archive batch tables and archive state hooks."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(translation_entries)").fetchall()}
    review_status_added = "review_status" not in columns
    additions = {
        "source_key": "TEXT NOT NULL DEFAULT ''",
        "active": "INTEGER NOT NULL DEFAULT 1",
        "dataset_key": "TEXT NOT NULL DEFAULT ''",
        "last_import_batch_id": "TEXT NOT NULL DEFAULT ''",
        "review_status": "TEXT NOT NULL DEFAULT 'pending'",
    }
    for name, declaration in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE translation_entries ADD COLUMN {name} {declaration}")
    if review_status_added:
        conn.execute("UPDATE translation_entries SET review_status = 'legacy_approved'")

    glossary_columns = {row["name"] for row in conn.execute("PRAGMA table_info(glossary_terms)").fetchall()}
    glossary_review_status_added = "review_status" not in glossary_columns
    for name, declaration in additions.items():
        if name not in glossary_columns:
            conn.execute(f"ALTER TABLE glossary_terms ADD COLUMN {name} {declaration}")
    if glossary_review_status_added:
        conn.execute("UPDATE glossary_terms SET review_status = 'legacy_approved'")

    _backfill_source_keys(conn, "translation_entries", "translations")
    _backfill_source_keys(conn, "glossary_terms", "glossary")

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS archive_state_versions (
            project_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(project_id, kind),
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS archive_import_batches (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            artifact_id TEXT NOT NULL DEFAULT '',
            artifact_checksum TEXT NOT NULL DEFAULT '',
            token TEXT NOT NULL UNIQUE,
            request_json TEXT NOT NULL DEFAULT '{}',
            summary_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            rollback_result_json TEXT NOT NULL DEFAULT '{}',
            mode TEXT NOT NULL DEFAULT 'merge',
            dataset_key TEXT NOT NULL DEFAULT '',
            sheet_key TEXT NOT NULL DEFAULT '',
            languages_json TEXT NOT NULL DEFAULT '[]',
            base_state_version INTEGER NOT NULL DEFAULT 0,
            base_state_checksum TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'analyzed',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            committed_at TEXT NOT NULL DEFAULT '',
            rolled_back_at TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS archive_import_batch_items (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            kind TEXT NOT NULL,
            entity_id TEXT NOT NULL DEFAULT '',
            identity_json TEXT NOT NULL DEFAULT '{}',
            language TEXT NOT NULL DEFAULT '',
            entry_key TEXT NOT NULL DEFAULT '',
            source_key TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            target TEXT NOT NULL DEFAULT '',
            target_column_present INTEGER NOT NULL DEFAULT 0,
            explicit_empty INTEGER NOT NULL DEFAULT 0,
            planned_action TEXT NOT NULL,
            before_hash TEXT NOT NULL DEFAULT '',
            expected_after_json TEXT NOT NULL DEFAULT '{}',
            conflict_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(batch_id, ordinal),
            FOREIGN KEY(batch_id) REFERENCES archive_import_batches(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS archive_import_revisions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            before_json TEXT NOT NULL DEFAULT '{}',
            after_json TEXT NOT NULL DEFAULT '{}',
            before_hash TEXT NOT NULL DEFAULT '',
            after_hash TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(batch_id, ordinal),
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY(batch_id) REFERENCES archive_import_batches(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_archive_import_batches_project_kind_created
          ON archive_import_batches(project_id, kind, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_archive_import_batch_items_batch
          ON archive_import_batch_items(batch_id, ordinal);
        CREATE INDEX IF NOT EXISTS idx_archive_import_revisions_batch
          ON archive_import_revisions(batch_id, ordinal);
        CREATE INDEX IF NOT EXISTS idx_translation_entries_archive_page
          ON translation_entries(project_id, active, source_key, language, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_glossary_terms_archive_page
          ON glossary_terms(project_id, active, confirmed, source_key, language, updated_at DESC);

        CREATE TRIGGER IF NOT EXISTS trg_translation_entries_archive_state_insert
        AFTER INSERT ON translation_entries
        BEGIN
          INSERT INTO archive_state_versions(project_id, kind, version)
          VALUES (NEW.project_id, 'translations', 1)
          ON CONFLICT(project_id, kind) DO UPDATE SET version = version + 1;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_translation_entries_archive_state_update
        AFTER UPDATE ON translation_entries
        BEGIN
          INSERT INTO archive_state_versions(project_id, kind, version)
          VALUES (NEW.project_id, 'translations', 1)
          ON CONFLICT(project_id, kind) DO UPDATE SET version = version + 1;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_translation_entries_archive_state_delete
        AFTER DELETE ON translation_entries
        BEGIN
          INSERT INTO archive_state_versions(project_id, kind, version)
          VALUES (OLD.project_id, 'translations', 1)
          ON CONFLICT(project_id, kind) DO UPDATE SET version = version + 1;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_glossary_terms_archive_state_insert
        AFTER INSERT ON glossary_terms
        BEGIN
          INSERT INTO archive_state_versions(project_id, kind, version)
          VALUES (NEW.project_id, 'glossary', 1)
          ON CONFLICT(project_id, kind) DO UPDATE SET version = version + 1;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_glossary_terms_archive_state_update
        AFTER UPDATE ON glossary_terms
        BEGIN
          INSERT INTO archive_state_versions(project_id, kind, version)
          VALUES (NEW.project_id, 'glossary', 1)
          ON CONFLICT(project_id, kind) DO UPDATE SET version = version + 1;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_glossary_terms_archive_state_delete
        AFTER DELETE ON glossary_terms
        BEGIN
          INSERT INTO archive_state_versions(project_id, kind, version)
          VALUES (OLD.project_id, 'glossary', 1)
          ON CONFLICT(project_id, kind) DO UPDATE SET version = version + 1;
        END;
        """
    )
