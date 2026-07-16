from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.db as db
import app.archive_batch_engine as archive_batch_engine
from app.main import app
from conftest import reset_data_root


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()


def _create_project(client: TestClient, name: str = "archive pagination") -> dict:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 200, response.text
    return response.json()


def _add_glossary(
    client: TestClient,
    project_id: str,
    term_key: str,
    source: str,
    target: str,
    language: str,
    *,
    category: str = "",
    note: str = "",
) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/glossary",
        json={
            "term_key": term_key,
            "source": source,
            "target": target,
            "language": language,
            "category": category,
            "note": note,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _add_translation(
    client: TestClient,
    project_id: str,
    entry_key: str,
    source: str,
    target: str,
    language: str,
    *,
    note: str = "",
) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/translations",
        json={
            "entry_key": entry_key,
            "source": source,
            "target": target,
            "language": language,
            "note": note,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_glossary_wide_pages_cn_concepts_and_only_embeds_selected_languages() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        _add_glossary(client, project["id"], "T-2", "战机", "Warplane", "en")
        _add_glossary(client, project["id"], "K-2", "战机", "전투기", "ko")
        _add_glossary(
            client,
            project["id"],
            "T-1",
            "钻石",
            "Diamond",
            "en",
            category="currency",
            note="premium resource",
        )
        _add_glossary(client, project["id"], "K-1", "钻石", "다이아몬드", "ko")
        _add_glossary(client, project["id"], "T-3", "等级", "Level", "en")
        inactive = _add_glossary(client, project["id"], "T-0", "废弃", "Inactive", "en")
        deleted = client.delete(f"/api/projects/{project['id']}/glossary/{inactive['id']}")
        assert deleted.status_code == 200, deleted.text

        response = client.get(
            f"/api/projects/{project['id']}/glossary/wide",
            params={"page": 1, "page_size": 2, "languages": "en", "sort": "id"},
        )
        category_search = client.get(
            f"/api/projects/{project['id']}/glossary/wide",
            params={"q": "premium resource", "languages": "ko"},
        )
        default_language = client.get(
            f"/api/projects/{project['id']}/glossary/wide",
            params={"page_size": 1},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_rows"] == 3
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert payload["total_pages"] == 2
    assert payload["languages"] == ["en", "ko"]
    assert payload["coverage"] == {"en": 3, "ko": 2}
    assert len(payload["rows"]) == 2
    assert [row["source"] for row in payload["rows"]] == ["钻石", "战机"]
    assert all(set(row["translations"]) == {"en"} for row in payload["rows"])
    assert isinstance(payload["revision"], str)
    assert category_search.status_code == 200, category_search.text
    searched = category_search.json()
    assert searched["total_rows"] == 1
    assert searched["rows"][0]["source"] == "钻石"
    assert set(searched["rows"][0]["translations"]) == {"ko"}
    assert set(default_language.json()["rows"][0]["translations"]) == {"en"}


def test_translation_wide_searches_any_target_and_pages_without_duplicates() -> None:
    with TestClient(app) as client:
        project = _create_project(client, "translation archive pagination")
        _add_translation(client, project["id"], "A-2", "领取 奖励", "Claim Reward", "en", note="button")
        _add_translation(client, project["id"], "K-2", "领取奖励", "보상 받기", "ko", note="버튼")
        _add_translation(client, project["id"], "A-1", "开始游戏", "Start Game", "en")
        _add_translation(client, project["id"], "K-1", "开始 游戏", "게임 시작", "ko")
        _add_translation(client, project["id"], "A-3", "等级", "Level", "en")
        inactive = _add_translation(client, project["id"], "A-0", "废弃", "Inactive", "en")
        deleted = client.delete(f"/api/projects/{project['id']}/translations/{inactive['id']}")
        assert deleted.status_code == 200, deleted.text

        target_search = client.get(
            f"/api/projects/{project['id']}/translations/wide",
            params={"q": "보상", "languages": "en"},
        )
        id_search = client.get(
            f"/api/projects/{project['id']}/translations/wide",
            params={"q": "K-1", "languages": "ko"},
        )
        first_page = client.get(
            f"/api/projects/{project['id']}/translations/wide",
            params={"page": 1, "page_size": 2, "languages": "en,ko", "sort": "id"},
        )
        second_page = client.get(
            f"/api/projects/{project['id']}/translations/wide",
            params={"page": 2, "page_size": 2, "languages": "en,ko", "sort": "id"},
        )

    assert target_search.status_code == 200, target_search.text
    target_payload = target_search.json()
    assert target_payload["total_rows"] == 1
    assert target_payload["rows"][0]["source_key"] == "领取奖励"
    assert set(target_payload["rows"][0]["translations"]) == {"en"}
    assert id_search.status_code == 200, id_search.text
    assert id_search.json()["rows"][0]["source_key"] == "开始游戏"
    assert set(id_search.json()["rows"][0]["translations"]) == {"ko"}

    first = first_page.json()
    second = second_page.json()
    assert first["total_rows"] == second["total_rows"] == 3
    assert first["coverage"] == {"en": 3, "ko": 2}
    first_keys = {row["source_key"] for row in first["rows"]}
    second_keys = {row["source_key"] for row in second["rows"]}
    assert len(first["rows"]) == 2
    assert len(second["rows"]) == 1
    assert first_keys.isdisjoint(second_keys)
    assert first_keys | second_keys == {"开始游戏", "领取奖励", "等级"}


def test_project_detail_include_archives_false_keeps_stats_and_small_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(app) as client:
        project = _create_project(client, "light project snapshot")
        _add_glossary(client, project["id"], "T-1", "战机", "Warplane", "en")
        translation = client.post(
            f"/api/projects/{project['id']}/translations",
            json={"entry_key": "A-1", "source": "开始游戏", "target": "Start Game", "language": "en"},
        )
        assert translation.status_code == 200, translation.text
        db.insert_run(project["id"], "translation")

        def fail_full_materialization(*_args: object, **_kwargs: object) -> list[dict]:
            raise AssertionError("light project snapshot must not list full archives")

        monkeypatch.setattr(db, "list_glossary_terms", fail_full_materialization)
        monkeypatch.setattr(db, "list_translation_entries", fail_full_materialization)
        lightweight = client.get(
            f"/api/projects/{project['id']}",
            params={"include_archives": "false"},
        )
        monkeypatch.undo()
        compatible = client.get(f"/api/projects/{project['id']}")

    assert lightweight.status_code == 200, lightweight.text
    light = lightweight.json()
    assert light["archives_embedded"] is False
    assert "glossary" not in light
    assert "translations" not in light
    assert isinstance(light["artifacts"], list)
    assert isinstance(light["runs"], list)
    assert isinstance(light["announcement_tasks"], list)
    assert isinstance(light["harness"], dict)
    assert light["stats"]["archived_rows"] == 1
    assert light["stats"]["glossary"] == 1

    assert compatible.status_code == 200, compatible.text
    full = compatible.json()
    assert full["archives_embedded"] is True
    assert len(full["glossary"]) == 1
    assert len(full["translations"]) == 1


def test_source_keys_migrate_and_track_updates_while_revisions_track_writes() -> None:
    with TestClient(app) as client:
        project = _create_project(client, "archive source keys and revisions")
        term = _add_glossary(client, project["id"], "T-1", " 战 机 ", "Warplane", "en")
        entry = _add_translation(client, project["id"], "A-1", " Start Game ", "Start", "en")
        glossary_revision = int(
            client.get(f"/api/projects/{project['id']}/glossary/wide").json()["revision"]
        )
        translation_revision = int(
            client.get(f"/api/projects/{project['id']}/translations/wide").json()["revision"]
        )

        updated_term = client.patch(
            f"/api/projects/{project['id']}/glossary/{term['id']}",
            json={"source": "新 战机", "target": "New Warplane"},
        )
        updated_entry = client.patch(
            f"/api/projects/{project['id']}/translations/{entry['id']}",
            json={"source": "New Game", "target": "New Start"},
        )
        assert updated_term.status_code == 200, updated_term.text
        assert updated_entry.status_code == 200, updated_entry.text
        after_update_glossary = int(
            client.get(f"/api/projects/{project['id']}/glossary/wide").json()["revision"]
        )
        after_update_translation = int(
            client.get(f"/api/projects/{project['id']}/translations/wide").json()["revision"]
        )
        assert after_update_glossary > glossary_revision
        assert after_update_translation > translation_revision

        deleted = client.delete(f"/api/projects/{project['id']}/translations/{entry['id']}")
        assert deleted.status_code == 200, deleted.text
        after_delete_translation = int(
            client.get(f"/api/projects/{project['id']}/translations/wide").json()["revision"]
        )
        assert after_delete_translation > after_update_translation

        artifact = client.post(
            f"/api/projects/{project['id']}/files?kind=final_workbook",
            files={
                "file": (
                    "archive.csv",
                    "ID,CN,EN\nA-2,领取奖励,Claim Reward\n".encode("utf-8-sig"),
                    "text/csv",
                )
            },
        )
        assert artifact.status_code == 200, artifact.text
        imported = client.post(
            f"/api/projects/{project['id']}/translations/import",
            json={"artifact_id": artifact.json()["id"]},
        )
        assert imported.status_code == 200, imported.text
        after_import_translation = int(
            client.get(f"/api/projects/{project['id']}/translations/wide").json()["revision"]
        )
        assert after_import_translation > after_delete_translation

    with db.connect() as conn:
        stored_term = conn.execute(
            "SELECT source_key FROM glossary_terms WHERE id = ?",
            (term["id"],),
        ).fetchone()
        stored_entry = conn.execute(
            "SELECT source_key FROM translation_entries WHERE entry_key = 'A-2'",
        ).fetchone()
        assert stored_term["source_key"] == "新战机"
        assert stored_entry["source_key"] == "领取奖励"
        conn.execute("UPDATE glossary_terms SET source_key = '' WHERE id = ?", (term["id"],))
        conn.execute("UPDATE translation_entries SET source_key = '' WHERE entry_key = 'A-2'")
        versions_before_migration = {
            row["kind"]: int(row["version"])
            for row in conn.execute(
                "SELECT kind, version FROM archive_state_versions WHERE project_id = ?",
                (project["id"],),
            ).fetchall()
        }

    db.init_db()

    with db.connect() as conn:
        versions_after_migration = {
            row["kind"]: int(row["version"])
            for row in conn.execute(
                "SELECT kind, version FROM archive_state_versions WHERE project_id = ?",
                (project["id"],),
            ).fetchall()
        }
        assert versions_after_migration == versions_before_migration
        assert conn.execute(
            "SELECT source_key FROM glossary_terms WHERE id = ?",
            (term["id"],),
        ).fetchone()["source_key"] == "新战机"
        imported_entry = conn.execute(
            "SELECT id, source_key FROM translation_entries WHERE entry_key = 'A-2'",
        ).fetchone()
        assert imported_entry["source_key"] == "领取奖励"

    with TestClient(app) as client:
        before_physical_delete = int(
            client.get(f"/api/projects/{project['id']}/translations/wide").json()["revision"]
        )
        with db.connect() as conn:
            conn.execute("DELETE FROM translation_entries WHERE id = ?", (imported_entry["id"],))
        after_physical_delete = int(
            client.get(f"/api/projects/{project['id']}/translations/wide").json()["revision"]
        )
    assert after_physical_delete > before_physical_delete


@pytest.mark.parametrize(
    ("kind", "table", "key_field", "wide_path", "through_init_db"),
    [
        ("translations", "translation_entries", "entry_key", "translations", True),
        ("glossary", "glossary_terms", "term_key", "glossary", False),
    ],
)
def test_legacy_dedupe_syncs_source_key_when_copying_source(
    kind: str,
    table: str,
    key_field: str,
    wide_path: str,
    through_init_db: bool,
) -> None:
    project = db.insert_project(f"legacy {kind} source key dedupe")
    timestamp = "2026-07-15T00:00:00+00:00"
    canonical_id = f"canonical_{kind}"
    duplicate_id = f"duplicate_{kind}"
    with db.connect() as conn:
        if table == "translation_entries":
            conn.execute("DROP INDEX idx_translation_entries_project_language_entry_key_unique")
            conn.executemany(
                """
                INSERT INTO translation_entries
                  (id, project_id, entry_key, source, source_key, target, language, active,
                   created_at, updated_at)
                VALUES (?, ?, 'LEGACY-1', ?, ?, ?, 'en', 1, ?, ?)
                """,
                [
                    (canonical_id, project["id"], "", "", "Ready", timestamp, timestamp),
                    (duplicate_id, project["id"], "Canonical Source", "canonicalsource", "", timestamp, timestamp),
                ],
            )
        else:
            conn.executemany(
                """
                INSERT INTO glossary_terms
                  (id, project_id, term_key, source, source_key, target, language, confirmed,
                   active, created_at, updated_at)
                VALUES (?, ?, 'LEGACY-1', ?, ?, ?, 'en', 1, 1, ?, ?)
                """,
                [
                    (canonical_id, project["id"], "", "", "Ready", timestamp, timestamp),
                    (duplicate_id, project["id"], "Canonical Source", "canonicalsource", "", timestamp, timestamp),
                ],
            )
            db._dedupe_table_by_key(conn, table, ("project_id", "language", key_field))

    if through_init_db:
        db.init_db()

    with db.connect() as conn:
        canonical = conn.execute(f"SELECT source, source_key FROM {table} WHERE id = ?", (canonical_id,)).fetchone()
        remaining = conn.execute(
            f"SELECT COUNT(*) AS count FROM {table} WHERE project_id = ? AND {key_field} = 'LEGACY-1'",
            (project["id"],),
        ).fetchone()
    assert remaining["count"] == 1
    assert canonical["source"] == "Canonical Source"
    assert canonical["source_key"] == "canonicalsource"

    with TestClient(app) as client:
        wide = client.get(f"/api/projects/{project['id']}/{wide_path}/wide")
    assert wide.status_code == 200, wide.text
    assert wide.json()["total_rows"] == 1


@pytest.mark.parametrize(
    ("target", "query", "distractor"),
    [
        ("ПРИВЕТ", "ПРИВЕТ", "OTHER"),
        ("CAFÉ", "CAFÉ", "CAFE"),
        (r"CODE_100%\PATH", r"_100%\PATH", "CODEX1000XPATH"),
    ],
)
def test_wide_search_uses_unicode_casefold_and_literal_like_escape(
    target: str,
    query: str,
    distractor: str,
) -> None:
    with TestClient(app) as client:
        project = _create_project(client, f"unicode search {query}")
        _add_translation(client, project["id"], "A-1", "Expected", target, "en")
        _add_translation(client, project["id"], "A-2", "Distractor", distractor, "en")
        response = client.get(
            f"/api/projects/{project['id']}/translations/wide",
            params={"q": query, "languages": "en"},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_rows"] == 1
    assert [row["source"] for row in payload["rows"]] == ["Expected"]


def test_translation_wide_10000_by_10_loads_only_one_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = db.insert_project("large archive page")
    languages = ("en", "ko", "ja", "fr", "de", "ru", "it", "es", "pt", "tr")
    timestamp = "2026-07-15T00:00:00+00:00"

    def rows() -> object:
        for index in range(10_000):
            source = f"源文 {index:05d}"
            source_key = f"源文{index:05d}"
            for language in languages:
                yield (
                    f"tr_{index:05d}_{language}",
                    project["id"],
                    f"ID-{index:05d}",
                    source,
                    source_key,
                    f"Target {index:05d} {language}",
                    "",
                    language,
                    "Sheet1",
                    index + 2,
                    "",
                    "imported",
                    "",
                    1,
                    "large-dataset",
                    "",
                    "approved",
                    timestamp,
                    timestamp,
                )

    with db.connect() as conn:
        conn.executemany(
            """
            INSERT INTO translation_entries
              (id, project_id, entry_key, source, source_key, target, target_alt, language,
               sheet, row_number, note, source_type, source_artifact_id, active, dataset_key,
               last_import_batch_id, review_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows(),
        )

    def fail_full_materialization(*_args: object, **_kwargs: object) -> list[dict]:
        raise AssertionError("wide pagination must not call list_translation_entries")

    monkeypatch.setattr(db, "list_translation_entries", fail_full_materialization)
    started = time.perf_counter()
    with TestClient(app) as client:
        response = client.get(
            f"/api/projects/{project['id']}/translations/wide",
            params={"page": 3, "page_size": 25, "languages": "en,ko", "sort": "source"},
        )
    elapsed = time.perf_counter() - started

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_rows"] == 10_000
    assert payload["page"] == 3
    assert payload["page_size"] == 25
    assert payload["total_pages"] == 400
    assert len(payload["rows"]) == 25
    assert all(set(row["translations"]) == {"en", "ko"} for row in payload["rows"])
    assert payload["languages"] == list(languages)
    assert payload["coverage"] == {language: 10_000 for language in languages}
    assert "源文 09999" not in response.text
    assert len(response.content) < 100_000
    assert elapsed < 5.0


def test_compact_import_batches_keep_lineage_without_full_result_arrays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "COMPACT-LINEAGE-MUST-NOT-RETURN-FULL-ROW-" + ("X" * 100_000)
    with TestClient(app) as client:
        project = _create_project(client, "compact import lineage")
        artifact = client.post(
            f"/api/projects/{project['id']}/files?kind=language_table",
            files={
                "file": (
                    "lineage.csv",
                    f"ID,CN,EN\nA-1,{marker},Compact target\n".encode("utf-8-sig"),
                    "text/csv",
                )
            },
        )
        assert artifact.status_code == 200, artifact.text
        analyzed = client.post(
            f"/api/projects/{project['id']}/translations/import/analyze",
            json={"artifact_id": artifact.json()["id"], "languages": ["en"], "mode": "merge"},
        )
        assert analyzed.status_code == 200, analyzed.text
        committed = client.post(
            f"/api/projects/{project['id']}/translations/import/commit",
            json={"token": analyzed.json()["token"]},
        )
        assert committed.status_code == 200, committed.text

        compatible = client.get(f"/api/projects/{project['id']}/translations/import/batches")
        def fail_full_batch_materialization(*_args: object, **_kwargs: object) -> dict:
            raise AssertionError("compact batch listing must not deserialize full result_json")

        monkeypatch.setattr(archive_batch_engine, "batch_result", fail_full_batch_materialization)
        compact = client.get(
            f"/api/projects/{project['id']}/translations/import/batches",
            params={"compact": "true"},
        )

    assert compatible.status_code == 200, compatible.text
    default_batch = compatible.json()["batches"][0]
    assert default_batch["result"]["entries"][0]["source"] == marker

    assert compact.status_code == 200, compact.text
    compact_batch = compact.json()["batches"][0]
    assert compact_batch["id"] == default_batch["id"]
    assert compact_batch["status"] == "committed"
    assert compact_batch["dataset_key"] == analyzed.json()["dataset_key"]
    assert compact_batch["sheet_key"] == analyzed.json()["sheet"]
    assert compact_batch["languages"] == ["en"]
    assert compact_batch["revision"]
    assert "result" not in compact_batch
    assert "request" not in compact_batch
    assert marker not in compact.text
    assert not ({"entries", "terms", "items", "before", "after"} & set(compact_batch))


@pytest.mark.parametrize("kind", ["glossary", "translations"])
def test_source_key_summary_and_delete_cover_all_active_languages(kind: str) -> None:
    with TestClient(app) as client:
        project = _create_project(client, f"delete all {kind} languages")
        for language, target in (("en", "Power"), ("ko", "전투력"), ("vn", "Sức mạnh")):
            if kind == "glossary":
                _add_glossary(client, project["id"], f"POWER-{language}", "战力", target, language)
            else:
                _add_translation(client, project["id"], f"POWER-{language}", "战力", target, language)
        before = int(client.get(f"/api/projects/{project['id']}/{kind}/wide").json()["revision"])

        summary = client.get(
            f"/api/projects/{project['id']}/{kind}/by-source-key",
            params={"source_key": "战力"},
        )
        deleted = client.delete(
            f"/api/projects/{project['id']}/{kind}/by-source-key",
            params={"source_key": "战力", "expected_revision": summary.json()["revision"]},
        )
        readback = client.get(
            f"/api/projects/{project['id']}/{kind}/wide",
            params={"languages": "en,ko,vn"},
        )

    assert summary.status_code == 200, summary.text
    assert summary.json()["count"] == 3
    assert summary.json()["languages"] == ["en", "ko", "vn"]
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_count"] == 3
    assert deleted.json()["languages"] == ["en", "ko", "vn"]
    assert int(deleted.json()["revision"]) > before
    assert readback.status_code == 200, readback.text
    assert readback.json()["total_rows"] == 0


@pytest.mark.parametrize("kind", ["glossary", "translations"])
def test_source_key_delete_rejects_revision_drift_without_deleting(kind: str) -> None:
    with TestClient(app) as client:
        project = _create_project(client, f"delete CAS {kind}")
        if kind == "glossary":
            _add_glossary(client, project["id"], "POWER-en", "战力", "Power", "en")
        else:
            _add_translation(client, project["id"], "POWER-en", "战力", "Power", "en")

        stale = client.get(
            f"/api/projects/{project['id']}/{kind}/by-source-key",
            params={"source_key": "战力"},
        ).json()

        if kind == "glossary":
            _add_glossary(client, project["id"], "POWER-vn", "战力", "Sức mạnh", "vn")
        else:
            _add_translation(client, project["id"], "POWER-vn", "战力", "Sức mạnh", "vn")

        rejected = client.delete(
            f"/api/projects/{project['id']}/{kind}/by-source-key",
            params={"source_key": "战力", "expected_revision": stale["revision"]},
        )
        after_rejection = client.get(
            f"/api/projects/{project['id']}/{kind}/by-source-key",
            params={"source_key": "战力"},
        ).json()
        accepted = client.delete(
            f"/api/projects/{project['id']}/{kind}/by-source-key",
            params={"source_key": "战力", "expected_revision": after_rejection["revision"]},
        )

    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"] == {
        "code": "archive_revision_conflict",
        "message": "归档内容已变化，请刷新后重新确认删除范围。",
        "expected_revision": stale["revision"],
        "current_revision": after_rejection["revision"],
    }
    assert after_rejection["count"] == 2
    assert after_rejection["languages"] == ["en", "vn"]
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["deleted_count"] == 2


@pytest.mark.parametrize("kind", ["glossary", "translations"])
def test_wide_page_ignores_historical_target_alt_for_search_coverage_and_output(kind: str) -> None:
    with TestClient(app) as client:
        project = _create_project(client, f"legacy alt only {kind}")
        if kind == "glossary":
            record = _add_glossary(client, project["id"], "LEGACY", "旧术语", "", "en")
            table = "glossary_terms"
        else:
            record = _add_translation(client, project["id"], "LEGACY", "旧译文", "", "en")
            table = "translation_entries"
        with db.connect() as conn:
            conn.execute(
                f"UPDATE {table} SET target = '', target_alt = 'GHOST EN2 VALUE' WHERE id = ?",
                (record["id"],),
            )

        visible = client.get(
            f"/api/projects/{project['id']}/{kind}/wide",
            params={"languages": "en"},
        )
        searched = client.get(
            f"/api/projects/{project['id']}/{kind}/wide",
            params={"q": "GHOST EN2 VALUE", "languages": "en"},
        )

    assert visible.status_code == 200, visible.text
    payload = visible.json()
    assert payload["total_rows"] == 1
    assert payload["languages"] == []
    assert payload["record_languages"] == ["en"]
    assert payload["coverage"] == {}
    value = payload["rows"][0]["translations"]["en"]
    assert value["id"] == record["id"]
    assert value["target"] == ""
    assert value["target_alt"] == ""
    assert "GHOST EN2 VALUE" not in visible.text
    assert searched.status_code == 200, searched.text
    assert searched.json()["total_rows"] == 0


@pytest.mark.parametrize("kind", ["glossary", "translations"])
def test_blank_target_language_remains_discoverable_and_editable(kind: str) -> None:
    with TestClient(app) as client:
        project = _create_project(client, f"blank language record {kind}")
        if kind == "glossary":
            _add_glossary(client, project["id"], "POWER", "战力", "Power", "en")
            blank = _add_glossary(client, project["id"], "POWER", "战力", "", "ko")
            shared = {"term_key": "POWER", "source": "战力", "category": "", "note": ""}
        else:
            _add_translation(client, project["id"], "POWER", "战力", "Power", "en")
            blank = _add_translation(client, project["id"], "POWER", "战力", "", "ko")
            shared = {"entry_key": "POWER", "source": "战力", "note": ""}

        initial = client.get(
            f"/api/projects/{project['id']}/{kind}/wide",
            params={"languages": "en"},
        )
        patched = client.patch(
            f"/api/projects/{project['id']}/{kind}/by-source-key",
            params={"source_key": "战力"},
            json={
                "expected_revision": initial.json()["revision"],
                "shared": shared,
                "targets": {"ko": "전투력"},
            },
        )
        readback = client.get(
            f"/api/projects/{project['id']}/{kind}/wide",
            params={"languages": "en,ko"},
        )

    assert initial.status_code == 200, initial.text
    assert initial.json()["languages"] == ["en"]
    assert initial.json()["record_languages"] == ["en", "ko"]
    assert initial.json()["coverage"] == {"en": 1}
    assert patched.status_code == 200, patched.text
    assert patched.json()["updated_target_languages"] == ["ko"]
    assert readback.status_code == 200, readback.text
    value = readback.json()["rows"][0]["translations"]["ko"]
    assert value["id"] == blank["id"]
    assert value["target"] == "전투력"
    assert readback.json()["coverage"] == {"en": 1, "ko": 1}


@pytest.mark.parametrize("kind", ["glossary", "translations"])
def test_source_key_patch_updates_all_shared_fields_but_only_explicit_targets(kind: str) -> None:
    with TestClient(app) as client:
        project = _create_project(client, f"atomic wide edit {kind}")
        if kind == "glossary":
            _add_glossary(client, project["id"], "POWER", "战力", "Power", "en", category="system", note="old")
            _add_glossary(client, project["id"], "POWER", "战力", "전투력", "ko", category="system", note="old")
            shared = {"term_key": "POWER-NEW", "source": "战斗力", "category": "attribute", "note": "new"}
        else:
            _add_translation(client, project["id"], "POWER", "战力", "Power", "en", note="old")
            _add_translation(client, project["id"], "POWER", "战力", "전투력", "ko", note="old")
            shared = {"entry_key": "POWER-NEW", "source": "战斗力", "note": "new"}
        before = client.get(
            f"/api/projects/{project['id']}/{kind}/wide",
            params={"languages": "en"},
        ).json()
        updated = client.patch(
            f"/api/projects/{project['id']}/{kind}/by-source-key",
            params={"source_key": "战力"},
            json={
                "expected_revision": before["revision"],
                "shared": shared,
                "targets": {"en": "Combat Power"},
            },
        )
        readback = client.get(
            f"/api/projects/{project['id']}/{kind}/wide",
            params={"languages": "en,ko"},
        )

    assert updated.status_code == 200, updated.text
    assert updated.json()["updated_target_languages"] == ["en"]
    assert int(updated.json()["revision"]) > int(before["revision"])
    assert readback.status_code == 200, readback.text
    payload = readback.json()
    assert payload["total_rows"] == 1
    row = payload["rows"][0]
    assert row["source"] == "战斗力"
    assert row["translations"]["en"]["target"] == "Combat Power"
    assert row["translations"]["ko"]["target"] == "전투력"
    assert row["note"] == "new"
    assert row["term_key" if kind == "glossary" else "entry_key"] == "POWER-NEW"
    if kind == "glossary":
        assert row["category"] == "attribute"


@pytest.mark.parametrize("kind", ["glossary", "translations"])
def test_source_key_patch_rejects_revision_drift_with_zero_writes(kind: str) -> None:
    with TestClient(app) as client:
        project = _create_project(client, f"atomic wide edit CAS {kind}")
        if kind == "glossary":
            _add_glossary(client, project["id"], "POWER", "战力", "Power", "en")
        else:
            _add_translation(client, project["id"], "POWER", "战力", "Power", "en")
        before = client.get(f"/api/projects/{project['id']}/{kind}/wide").json()
        if kind == "glossary":
            _add_glossary(client, project["id"], "POWER", "战力", "전투력", "ko")
            shared = {"term_key": "CHANGED", "source": "已修改", "category": "", "note": ""}
        else:
            _add_translation(client, project["id"], "POWER", "战力", "전투력", "ko")
            shared = {"entry_key": "CHANGED", "source": "已修改", "note": ""}
        rejected = client.patch(
            f"/api/projects/{project['id']}/{kind}/by-source-key",
            params={"source_key": "战力"},
            json={"expected_revision": before["revision"], "shared": shared, "targets": {"en": "Changed"}},
        )
        readback = client.get(
            f"/api/projects/{project['id']}/{kind}/wide",
            params={"languages": "en,ko"},
        ).json()

    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"]["code"] == "archive_revision_conflict"
    assert readback["total_rows"] == 1
    assert readback["rows"][0]["source"] == "战力"
    assert readback["rows"][0]["translations"]["en"]["target"] == "Power"
    assert readback["rows"][0]["translations"]["ko"]["target"] == "전투력"


@pytest.mark.parametrize("kind", ["glossary", "translations"])
def test_wide_page_preserves_lightweight_source_provenance(kind: str) -> None:
    with TestClient(app) as client:
        project = _create_project(client, f"wide provenance {kind}")
        if kind == "glossary":
            _add_glossary(client, project["id"], "POWER", "战力", "Power", "en")
            imported = _add_glossary(client, project["id"], "POWER", "战力", "전투력", "ko")
            table = "glossary_terms"
        else:
            _add_translation(client, project["id"], "POWER", "战力", "Power", "en")
            imported = _add_translation(client, project["id"], "POWER", "战力", "전투력", "ko")
            table = "translation_entries"
        with db.connect() as conn:
            conn.execute(
                f"UPDATE {table} SET source_type = 'imported', review_status = 'legacy_approved' WHERE id = ?",
                (imported["id"],),
            )
        response = client.get(
            f"/api/projects/{project['id']}/{kind}/wide",
            params={"languages": "en,ko"},
        )
        revision = response.json()["revision"]
        if kind == "glossary":
            shared = {"term_key": "POWER", "source": "战力", "category": "", "note": ""}
        else:
            shared = {"entry_key": "POWER", "source": "战力", "note": ""}
        patched = client.patch(
            f"/api/projects/{project['id']}/{kind}/by-source-key",
            params={"source_key": "战力"},
            json={"expected_revision": revision, "shared": shared, "targets": {"en": "Combat Power"}},
        )
        after = client.get(
            f"/api/projects/{project['id']}/{kind}/wide",
            params={"languages": "en,ko"},
        )

    assert response.status_code == 200, response.text
    values = response.json()["rows"][0]["translations"]
    assert values["en"]["source_type"] == "manual"
    assert values["en"]["review_status"] == "approved"
    assert values["ko"]["source_type"] == "imported"
    assert values["ko"]["review_status"] == "legacy_approved"
    assert patched.status_code == 200, patched.text
    assert patched.json()["updated_count"] == 1
    after_values = after.json()["rows"][0]["translations"]
    assert after_values["en"]["source_type"] == "manual"
    assert after_values["en"]["target"] == "Combat Power"
    assert after_values["ko"]["source_type"] == "imported"
    assert after_values["ko"]["review_status"] == "legacy_approved"


def test_compact_commit_persists_only_summary_and_is_idempotent() -> None:
    marker = "COMPACT-COMMIT-MUST-NOT-PERSIST-ENTITY-" + ("Y" * 100_000)
    with TestClient(app) as client:
        project = _create_project(client, "compact commit")
        artifact = client.post(
            f"/api/projects/{project['id']}/files?kind=language_table",
            files={
                "file": (
                    "compact-commit.csv",
                    f"ID,CN,EN\nA-1,{marker},Compact target\n".encode("utf-8-sig"),
                    "text/csv",
                )
            },
        )
        assert artifact.status_code == 200, artifact.text
        analyzed = client.post(
            f"/api/projects/{project['id']}/translations/import/analyze",
            json={"artifact_id": artifact.json()["id"], "languages": ["en"], "mode": "merge"},
        )
        assert analyzed.status_code == 200, analyzed.text
        compact = client.post(
            f"/api/projects/{project['id']}/translations/import/commit",
            params={"compact": "true"},
            json={"token": analyzed.json()["token"]},
        )
        repeated = client.post(
            f"/api/projects/{project['id']}/translations/import/commit",
            params={"compact": "true"},
            json={"token": analyzed.json()["token"]},
        )
        legacy_after_compact = client.post(
            f"/api/projects/{project['id']}/translations/import/commit",
            json={"token": analyzed.json()["token"]},
        )
        stored = client.get(f"/api/projects/{project['id']}/translations/import/batches")

        default_artifact = client.post(
            f"/api/projects/{project['id']}/files?kind=language_table",
            files={
                "file": (
                    "default-commit.csv",
                    "ID,CN,EN\nA-2,默认兼容,Default compatible\n".encode("utf-8-sig"),
                    "text/csv",
                )
            },
        )
        default_analysis = client.post(
            f"/api/projects/{project['id']}/translations/import/analyze",
            json={"artifact_id": default_artifact.json()["id"], "languages": ["en"], "mode": "merge"},
        )
        default_commit = client.post(
            f"/api/projects/{project['id']}/translations/import/commit",
            json={"token": default_analysis.json()["token"]},
        )
        compact_after_default = client.post(
            f"/api/projects/{project['id']}/translations/import/commit",
            params={"compact": "true"},
            json={"token": default_analysis.json()["token"]},
        )

    assert compact.status_code == 200, compact.text
    compact_result = compact.json()
    assert compact_result["status"] == "committed"
    assert compact_result["changed_count"] == 1
    assert compact_result["imported_count"] == 1
    assert compact_result["language_summary"] == {"en": {"insert": 1}}
    assert compact_result["state_version"]
    assert "entries" not in compact_result
    assert "terms" not in compact_result
    assert marker not in compact.text
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == compact_result
    assert legacy_after_compact.status_code == 200, legacy_after_compact.text
    assert legacy_after_compact.json()["entries"][0]["source"] == marker
    assert legacy_after_compact.json()["imported_count"] == 1
    compact_stored = next(batch for batch in stored.json()["batches"] if batch["id"] == compact_result["batch_id"])
    assert compact_stored["result"] == compact_result
    assert marker not in stored.text

    assert default_commit.status_code == 200, default_commit.text
    assert default_commit.json()["entries"][0]["source"] == "默认兼容"
    assert compact_after_default.status_code == 200, compact_after_default.text
    assert compact_after_default.json()["imported_count"] == 1
    assert compact_after_default.json()["language_summary"] == {"en": {"insert": 1}}
    assert "entries" not in compact_after_default.json()


@pytest.mark.parametrize("kind", ["glossary", "translations"])
def test_wide_page_keeps_active_empty_target_record_id(kind: str) -> None:
    with TestClient(app) as client:
        project = _create_project(client, f"empty target {kind}")
        if kind == "glossary":
            created = _add_glossary(client, project["id"], "EMPTY", "空译文", "", "en")
        else:
            created = _add_translation(client, project["id"], "EMPTY", "空译文", "", "en")
        wide = client.get(f"/api/projects/{project['id']}/{kind}/wide")

    assert wide.status_code == 200, wide.text
    payload = wide.json()
    assert payload["total_rows"] == 1
    assert payload["coverage"] == {}
    assert payload["languages"] == []
    value = payload["rows"][0]["translations"]["en"]
    assert value["id"] == created["id"]
    assert value["target"] == ""
