from __future__ import annotations

import json
import os
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.db as db
from app.main import app
from conftest import reset_data_root


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()


def _create_project(client: TestClient, name: str = "archive batches") -> dict:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 200, response.text
    return response.json()


def _workbook_bytes(*sheets: tuple[str, list[list[object]]]) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets:
        worksheet = workbook.create_sheet(title)
        for row in rows:
            worksheet.append(row)
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def _upload(
    client: TestClient,
    project_id: str,
    filename: str,
    rows: list[list[object]] | None = None,
    *,
    sheets: tuple[tuple[str, list[list[object]]], ...] = (),
) -> dict:
    content = _workbook_bytes(*(sheets or (("Data", rows or []),)))
    response = client.post(
        f"/api/projects/{project_id}/files?kind=language_table",
        files={
            "file": (
                filename,
                content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _upload_bytes(client: TestClient, project_id: str, filename: str, content: bytes) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/files?kind=language_table",
        files={"file": (filename, content, "application/octet-stream")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _analyze(client: TestClient, project_id: str, artifact_id: str, **overrides: object) -> dict:
    payload: dict[str, object] = {"artifact_id": artifact_id}
    payload.update(overrides)
    response = client.post(
        f"/api/projects/{project_id}/translations/import/analyze",
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _commit(client: TestClient, project_id: str, token: str) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/translations/import/commit",
        json={"token": token},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _all_translation_rows(project_id: str) -> list[dict]:
    with db.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM translation_entries WHERE project_id = ? ORDER BY language, entry_key, id",
                (project_id,),
            ).fetchall()
        ]


def _rows_by_key(project_id: str) -> dict[tuple[str, str], dict]:
    return {
        (row["language"], row["entry_key"]): row
        for row in _all_translation_rows(project_id)
    }


def test_merge_persists_complete_items_and_commit_uses_them_without_reparsing(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        first = _upload(
            client,
            project["id"],
            "t1.xlsx",
            [
                ["ID", "CN", "EN"],
                ["A-1", "开始游戏", "Start"],
                ["A-2", "领取奖励", "Claim"],
                ["A-4", "设置", "Settings"],
                ["A-5", "客服", "Support"],
            ],
        )
        first_analysis = _analyze(client, project["id"], first["id"])

        assert first_analysis["mode"] == "merge"
        assert first_analysis["summary"] == {
            "source_rows": 4,
            "insert": 4,
            "update": 0,
            "unchanged": 0,
            "skip": 0,
            "clear": 0,
            "deactivate": 0,
            "protected": 0,
            "conflict": 0,
        }
        assert first_analysis["dataset_key"]
        assert first_analysis["can_commit"] is True
        with db.connect() as conn:
            stored_items = conn.execute(
                "SELECT planned_action, expected_after_json FROM archive_import_batch_items WHERE batch_id = ? ORDER BY ordinal",
                (first_analysis["batch_id"],),
            ).fetchall()
        assert [row["planned_action"] for row in stored_items] == ["insert"] * 4
        assert all(row["expected_after_json"] for row in stored_items)

        # Commit must not parse the artifact again; all normalized items were persisted by analyze.
        import app.translation_archive_batches as batch_engine

        monkeypatch.setattr(batch_engine, "_parse_translation_artifact", lambda *_args, **_kwargs: pytest.fail("commit reparsed artifact"))
        first_result = _commit(client, project["id"], first_analysis["token"])
        assert first_result["status"] == "committed"
        monkeypatch.undo()

        before = _rows_by_key(project["id"])
        second = _upload(
            client,
            project["id"],
            "t2.xlsx",
            [
                ["ID", "CN", "EN"],
                ["A-1", "开始游戏", "Launch"],
                ["A-2", "领取奖励", ""],
                ["A-3", "退出游戏", "Exit"],
                ["A-4", "设置", "Settings"],
            ],
        )
        second_analysis = _analyze(client, project["id"], second["id"])
        assert second_analysis["dataset_key"] == first_analysis["dataset_key"]
        assert second_analysis["summary"] == {
            "source_rows": 4,
            "insert": 1,
            "update": 1,
            "unchanged": 1,
            "skip": 1,
            "clear": 0,
            "deactivate": 0,
            "protected": 0,
            "conflict": 0,
        }
        second_result = _commit(client, project["id"], second_analysis["token"])
        repeated = _commit(client, project["id"], second_analysis["token"])

    assert repeated == second_result
    after = _rows_by_key(project["id"])
    assert after[("en", "A-1")]["target"] == "Launch"
    assert after[("en", "A-2")]["target"] == "Claim"
    assert after[("en", "A-2")]["updated_at"] == before[("en", "A-2")]["updated_at"]
    assert after[("en", "A-3")]["target"] == "Exit"
    assert after[("en", "A-4")]["updated_at"] == before[("en", "A-4")]["updated_at"]
    assert after[("en", "A-5")]["updated_at"] == before[("en", "A-5")]["updated_at"]


def test_same_content_merge_updates_legacy_lineage_and_cross_sheet_scope() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        db.insert_translation_entry(
            project["id"],
            {
                "entry_key": "A-1",
                "source": "开始游戏",
                "target": "Start",
                "language": "en",
                "sheet": "Legacy",
                "source_type": "imported",
            },
        )
        first_artifact = _upload(
            client,
            project["id"],
            "lineage.xlsx",
            sheets=(("Fresh", [["ID", "CN", "EN"], ["A-1", "开始游戏", "Start"]]),),
        )
        first = _analyze(client, project["id"], first_artifact["id"])
        assert first["summary"]["update"] == 1
        assert first["summary"]["unchanged"] == 0
        _commit(client, project["id"], first["token"])

        current = _rows_by_key(project["id"])[("en", "A-1")]
        assert current["dataset_key"] == first["dataset_key"]
        assert current["sheet"] == "Fresh"
        assert current["source_type"] == "imported"
        assert current["source_artifact_id"] == ""
        assert current["row_number"] == 0
        snapshot = _analyze(
            client,
            project["id"],
            first_artifact["id"],
            mode="snapshot",
            dataset_key=first["dataset_key"],
            languages=["en"],
        )
        assert snapshot["can_commit"] is True

        second_artifact = _upload(
            client,
            project["id"],
            "new-sheet.xlsx",
            sheets=(("Replacement", [["ID", "CN", "EN"], ["A-1", "开始游戏", "Start"]]),),
        )
        second = _analyze(client, project["id"], second_artifact["id"])
        assert second["dataset_key"] == first["dataset_key"]
        assert second["summary"]["update"] == 1
        _commit(client, project["id"], second["token"])

    assert _rows_by_key(project["id"])[("en", "A-1")]["sheet"] == "Replacement"


def test_snapshot_only_changes_selected_lineage_sheet_and_languages() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload(
            client,
            project["id"],
            "base.xlsx",
            [
                ["ID", "CN", "EN", "KO"],
                ["A-1", "开始游戏", "Start", "시작"],
                ["A-2", "领取奖励", "Claim", "보상"],
                ["A-3", "退出游戏", "Exit", "종료"],
            ],
        )
        base_analysis = _analyze(client, project["id"], base["id"], sheet="Data")
        _commit(client, project["id"], base_analysis["token"])

        other_sheet = _upload(
            client,
            project["id"],
            "other.xlsx",
            [["ID", "CN", "EN"], ["B-1", "设置", "Settings"]],
            sheets=(("Other", [["ID", "CN", "EN"], ["B-1", "设置", "Settings"]]),),
        )
        other_analysis = _analyze(
            client,
            project["id"],
            other_sheet["id"],
            sheet="Other",
            dataset_key=base_analysis["dataset_key"],
        )
        _commit(client, project["id"], other_analysis["token"])

        client.post(
            f"/api/projects/{project['id']}/translations",
            json={"entry_key": "M-1", "source": "人工", "target": "Manual", "language": "en"},
        )

        snapshot = _upload(
            client,
            project["id"],
            "snapshot.xlsx",
            [["ID", "CN", "EN"], ["A-1", "开始游戏", "Start"], ["A-2", "领取奖励", ""]],
        )
        analysis = _analyze(
            client,
            project["id"],
            snapshot["id"],
            sheet="Data",
            mode="snapshot",
            dataset_key=base_analysis["dataset_key"],
            languages=["en"],
        )
        assert analysis["summary"]["clear"] == 1
        assert analysis["summary"]["deactivate"] == 1
        _commit(client, project["id"], analysis["token"])

    rows = _rows_by_key(project["id"])
    assert rows[("en", "A-2")]["active"] == 0
    assert rows[("en", "A-2")]["target"] == ""
    assert rows[("en", "A-3")]["active"] == 0
    assert rows[("ko", "A-2")]["active"] == 1
    assert rows[("en", "B-1")]["active"] == 1
    assert rows[("en", "M-1")]["active"] == 1
    assert {row["entry_key"] for row in db.list_translation_entries(project["id"], language="en")} == {"A-1", "B-1", "M-1"}


def test_single_language_shared_identity_update_keeps_wide_concept_and_rolls_back_all_siblings() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload(
            client,
            project["id"],
            "shared-base.xlsx",
            [["ID", "CN", "EN", "KO", "FR", "备注"], ["A-1", "旧源文", "Old EN", "오래된 KO", "Ancien FR", "旧备注"]],
        )
        base_analysis = _analyze(client, project["id"], base["id"], sheet="Data")
        _commit(client, project["id"], base_analysis["token"])
        with db.connect() as conn:
            conn.execute(
                "UPDATE translation_entries SET active = 0 WHERE project_id = ? AND language = 'fr'",
                (project["id"],),
            )
        before = _rows_by_key(project["id"])

        update = _upload(
            client,
            project["id"],
            "shared-update.xlsx",
            [["ID", "CN", "EN", "备注"], ["A-1", "新源文", "New EN", "新备注"]],
        )
        analysis = _analyze(
            client,
            project["id"],
            update["id"],
            sheet="Data",
            languages=["en"],
            dataset_key=base_analysis["dataset_key"],
        )
        with db.connect() as conn:
            items = conn.execute(
                "SELECT language, entity_id, planned_action FROM archive_import_batch_items "
                "WHERE batch_id = ? ORDER BY ordinal",
                (analysis["batch_id"],),
            ).fetchall()
        committed = _commit(client, project["id"], analysis["token"])
        wide = client.get(
            f"/api/projects/{project['id']}/translations/wide",
            params={"languages": "en,ko"},
        )
        with db.connect() as conn:
            revision_count = conn.execute(
                "SELECT COUNT(*) FROM archive_import_revisions WHERE batch_id = ?",
                (analysis["batch_id"],),
            ).fetchone()[0]
        changed = _rows_by_key(project["id"])
        rolled_back = client.post(
            f"/api/projects/{project['id']}/translations/import/batches/{analysis['batch_id']}/rollback"
        )

    assert analysis["can_commit"] is True
    assert {row["language"] for row in items} == {"en", "ko", "fr"}
    assert all(row["planned_action"] == "update" for row in items)
    assert len(items) == len({row["entity_id"] for row in items}) == 3
    assert committed["changed_count"] == 3
    assert revision_count == 3
    assert wide.status_code == 200, wide.text
    assert wide.json()["total_rows"] == 1
    wide_row = wide.json()["rows"][0]
    assert wide_row["source"] == "新源文"
    assert wide_row["note"] == "新备注"
    assert wide_row["translations"]["en"]["target"] == "New EN"
    assert wide_row["translations"]["ko"]["target"] == "오래된 KO"
    assert {(row["source"], row["note"]) for row in changed.values()} == {('新源文', '新备注')}
    assert changed[("fr", "A-1")]["active"] == 0
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["restored_count"] == 3
    restored = _rows_by_key(project["id"])
    for key in (("en", "A-1"), ("ko", "A-1"), ("fr", "A-1")):
        assert restored[key]["source"] == before[key]["source"]
        assert restored[key]["note"] == before[key]["note"]
        assert restored[key]["target"] == before[key]["target"]
        assert restored[key]["active"] == before[key]["active"]


def test_existing_id_can_adopt_source_used_by_another_id() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload(
            client,
            project["id"],
            "shared-collision-base.xlsx",
            [
                ["ID", "CN", "EN", "KO"],
                ["A-1", "旧源文", "Old EN", "오래된 KO"],
                ["A-2", "占用源文", "", "충돌 KO"],
            ],
        )
        base_analysis = _analyze(client, project["id"], base["id"], sheet="Data")
        _commit(client, project["id"], base_analysis["token"])
        before = _all_translation_rows(project["id"])

        update = _upload(
            client,
            project["id"],
            "shared-collision-update.xlsx",
            [["ID", "CN", "EN"], ["A-1", "占用源文", "New EN"]],
        )
        response = client.post(
            f"/api/projects/{project['id']}/translations/import/analyze",
            json={
                "artifact_id": update["id"],
                "sheet": "Data",
                "languages": ["en"],
                "dataset_key": base_analysis["dataset_key"],
            },
        )
        assert response.status_code == 200, response.text
        analysis = response.json()
        committed = client.post(
            f"/api/projects/{project['id']}/translations/import/commit",
            json={"token": analysis["token"]},
        )

    assert analysis["can_commit"] is True
    assert analysis["conflicts"] == []
    assert committed.status_code == 200
    changed = _rows_by_key(project["id"])
    assert changed[("en", "A-1")]["source"] == "占用源文"
    assert changed[("en", "A-1")]["target"] == "New EN"
    assert changed[("ko", "A-1")]["source"] == "占用源文"
    assert changed[("ko", "A-1")]["target"] == "오래된 KO"
    assert changed[("ko", "A-2")]["source"] == "占用源文"
    assert changed[("ko", "A-2")]["target"] == "충돌 KO"
    assert len(changed) == len(before)


def test_same_translation_id_with_inconsistent_shared_input_is_blocked() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload(
            client,
            project["id"],
            "shared-input-base.xlsx",
            [["ID", "CN", "EN", "KO"], ["A-1", "旧源文", "Old EN", "오래된 KO"]],
        )
        base_analysis = _analyze(client, project["id"], base["id"], sheet="Data")
        _commit(client, project["id"], base_analysis["token"])
        artifact = _upload_bytes(
            client,
            project["id"],
            "shared-input.json",
            json.dumps(
                [
                    {"entry_key": "A-1", "source": "新源文一", "target": "New EN", "language": "en"},
                    {"entry_key": "A-1", "source": "新源文二", "target": "New KO", "language": "ko"},
                ],
                ensure_ascii=False,
            ).encode("utf-8"),
        )
        analysis = _analyze(
            client,
            project["id"],
            artifact["id"],
            languages=["en", "ko"],
            dataset_key=base_analysis["dataset_key"],
        )

    assert analysis["can_commit"] is False
    assert "shared_identity_mismatch" in {conflict["code"] for conflict in analysis["conflicts"]}


def test_empty_project_allows_distinct_ids_to_share_source_across_languages() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        artifact = _upload(
            client,
            project["id"],
            "shared-source.xlsx",
            [
                ["ID", "CN", "EN", "FR"],
                ["A-1", "同一源文", "One", "Un"],
                ["A-2", "同一源文", "Two", "Deux"],
            ],
        )
        analysis = _analyze(client, project["id"], artifact["id"], languages=["en", "fr"])
        result = _commit(client, project["id"], analysis["token"]) if analysis["can_commit"] else None

    assert analysis["can_commit"] is True
    assert analysis["conflicts"] == []
    assert analysis["summary"]["insert"] == 4
    assert analysis["summary"]["conflict"] == 0
    assert result and result["status"] == "committed"
    rows = _all_translation_rows(project["id"])
    assert len(rows) == 4
    assert {row["entry_key"] for row in rows} == {"A-1", "A-2"}


def test_reimport_updates_shared_source_rows_independently_by_id() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload(
            client,
            project["id"],
            "shared-source-base.xlsx",
            [
                ["ID", "CN", "EN", "FR"],
                ["A-1", "同一源文", "One", "Un"],
                ["A-2", "同一源文", "Two", "Deux"],
            ],
        )
        base_analysis = _analyze(client, project["id"], base["id"], languages=["en", "fr"])
        _commit(client, project["id"], base_analysis["token"])

        edited = _upload(
            client,
            project["id"],
            "shared-source-edited.xlsx",
            [
                ["ID", "CN", "EN", "FR"],
                ["A-1", "同一源文", "One v2", "Un v2"],
                ["A-2", "同一源文", "Two v2", "Deux v2"],
            ],
        )
        analysis = _analyze(
            client,
            project["id"],
            edited["id"],
            languages=["en", "fr"],
            dataset_key=base_analysis["dataset_key"],
        )
        result = _commit(client, project["id"], analysis["token"]) if analysis["can_commit"] else None

    assert analysis["can_commit"] is True
    assert analysis["conflicts"] == []
    assert analysis["summary"]["update"] == 4
    assert analysis["summary"]["conflict"] == 0
    assert result and result["status"] == "committed"
    rows = _rows_by_key(project["id"])
    assert rows[("en", "A-1")]["target"] == "One v2"
    assert rows[("en", "A-2")]["target"] == "Two v2"
    assert rows[("fr", "A-1")]["target"] == "Un v2"
    assert rows[("fr", "A-2")]["target"] == "Deux v2"


def test_empty_project_rejects_cross_language_mixed_keyed_and_unkeyed_identity() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        artifact = _upload_bytes(
            client,
            project["id"],
            "cross-language-mixed-identity.json",
            json.dumps(
                [
                    {"entry_key": "A-1", "source": "同一源文", "target": "One", "language": "en"},
                    {"entry_key": "", "source": "同一源文", "target": "Two", "language": "ko"},
                ],
                ensure_ascii=False,
            ).encode("utf-8"),
        )
        analysis = _analyze(client, project["id"], artifact["id"], languages=["en", "ko"])

    assert analysis["can_commit"] is False
    assert "source_mixed_identity" in {conflict["code"] for conflict in analysis["conflicts"]}
    assert _all_translation_rows(project["id"]) == []


def test_stable_translation_id_cannot_rename_into_an_unkeyed_concept_source() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload(
            client,
            project["id"],
            "unkeyed-destination-base.xlsx",
            [
                ["ID", "CN", "EN", "KO"],
                ["A-1", "原概念", "Old EN", ""],
                ["", "无 ID 概念", "", "기존 KO"],
            ],
        )
        base_analysis = _analyze(client, project["id"], base["id"], sheet="Data")
        _commit(client, project["id"], base_analysis["token"])
        before = _all_translation_rows(project["id"])
        update = _upload(
            client,
            project["id"],
            "unkeyed-destination-update.xlsx",
            [["ID", "CN", "EN"], ["A-1", "无 ID 概念", "New EN"]],
        )
        analysis = _analyze(
            client,
            project["id"],
            update["id"],
            sheet="Data",
            languages=["en"],
            dataset_key=base_analysis["dataset_key"],
        )

    assert analysis["can_commit"] is False
    assert "concept_source_conflict" in {conflict["code"] for conflict in analysis["conflicts"]}
    assert _all_translation_rows(project["id"]) == before


def test_translation_merge_allows_appending_new_unkeyed_row_number() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload(
            client,
            project["id"],
            "unkeyed-append-base.xlsx",
            [["CN", "EN"], ["旧源文", "Old EN"]],
        )
        base_analysis = _analyze(client, project["id"], base["id"], sheet="Data")
        _commit(client, project["id"], base_analysis["token"])
        appended = _upload(
            client,
            project["id"],
            "unkeyed-append.xlsx",
            [["CN", "EN"], ["旧源文", "Old EN"], ["追加源文", "Added EN"]],
        )
        analysis = _analyze(
            client,
            project["id"],
            appended["id"],
            sheet="Data",
            languages=["en"],
            dataset_key=base_analysis["dataset_key"],
        )
        committed = _commit(client, project["id"], analysis["token"])

    assert analysis["can_commit"] is True
    assert analysis["summary"]["insert"] == 1
    assert committed["changed_count"] == 1
    assert {row["source"] for row in _all_translation_rows(project["id"])} == {"旧源文", "追加源文"}


def test_translation_blank_target_with_existing_language_updates_shared_fields_only() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload(
            client,
            project["id"],
            "blank-target-shared-base.xlsx",
            [["ID", "CN", "EN", "KO", "备注"], ["A-1", "旧源文", "Old EN", "오래된 KO", "旧备注"]],
        )
        base_analysis = _analyze(client, project["id"], base["id"], sheet="Data")
        _commit(client, project["id"], base_analysis["token"])
        update = _upload(
            client,
            project["id"],
            "blank-target-shared-update.xlsx",
            [["ID", "CN", "EN", "KO", "备注"], ["A-1", "新源文", "New EN", "", "新备注"]],
        )
        analysis = _analyze(
            client,
            project["id"],
            update["id"],
            sheet="Data",
            languages=["en", "ko"],
            dataset_key=base_analysis["dataset_key"],
        )
        _commit(client, project["id"], analysis["token"])

    rows = _rows_by_key(project["id"])
    assert analysis["can_commit"] is True
    assert rows[("en", "A-1")]["target"] == "New EN"
    assert rows[("ko", "A-1")]["target"] == "오래된 KO"
    assert rows[("ko", "A-1")]["source"] == "新源文"
    assert rows[("ko", "A-1")]["note"] == "新备注"


def test_blank_new_language_row_propagates_shared_translation_fields_to_existing_sibling() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload(
            client,
            project["id"],
            "blank-new-language-base.xlsx",
            [["ID", "CN", "KO"], ["A-1", "旧源文", "오래된 KO"]],
        )
        base_analysis = _analyze(client, project["id"], base["id"], sheet="Data")
        _commit(client, project["id"], base_analysis["token"])
        update = _upload(
            client,
            project["id"],
            "blank-new-language-update.xlsx",
            [["ID", "CN", "EN"], ["A-1", "新源文", ""]],
        )
        analysis = _analyze(
            client,
            project["id"],
            update["id"],
            sheet="Data",
            languages=["en"],
            dataset_key=base_analysis["dataset_key"],
        )
        committed = _commit(client, project["id"], analysis["token"])

    rows = _rows_by_key(project["id"])
    assert analysis["can_commit"] is True
    assert analysis["summary"]["skip"] == 1
    assert committed["changed_count"] == 1
    assert ("en", "A-1") not in rows
    assert rows[("ko", "A-1")]["source"] == "新源文"
    assert rows[("ko", "A-1")]["target"] == "오래된 KO"


def test_hidden_protected_translation_sibling_requires_override_and_rolls_back() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload(
            client,
            project["id"],
            "protected-sibling-base.xlsx",
            [["ID", "CN", "EN", "KO"], ["A-1", "旧源文", "Old EN", "오래된 KO"]],
        )
        base_analysis = _analyze(client, project["id"], base["id"], sheet="Data")
        _commit(client, project["id"], base_analysis["token"])
        with db.connect() as conn:
            conn.execute(
                "UPDATE translation_entries SET source_type = 'manual', review_status = 'approved' "
                "WHERE project_id = ? AND language = 'ko'",
                (project["id"],),
            )
        before = _rows_by_key(project["id"])
        update = _upload(
            client,
            project["id"],
            "protected-sibling-update.xlsx",
            [["ID", "CN", "EN"], ["A-1", "新源文", "New EN"]],
        )
        blocked = _analyze(
            client,
            project["id"],
            update["id"],
            languages=["en"],
            dataset_key=base_analysis["dataset_key"],
        )
        blocked_commit = client.post(
            f"/api/projects/{project['id']}/translations/import/commit",
            json={"token": blocked["token"]},
        )
        allowed = _analyze(
            client,
            project["id"],
            update["id"],
            languages=["en"],
            dataset_key=base_analysis["dataset_key"],
            override_protected=True,
        )
        committed = _commit(client, project["id"], allowed["token"])
        changed = _rows_by_key(project["id"])
        rolled_back = client.post(
            f"/api/projects/{project['id']}/translations/import/batches/{committed['batch_id']}/rollback"
        )

    assert blocked["can_commit"] is False
    assert "protected_source" in {conflict["code"] for conflict in blocked["conflicts"]}
    assert blocked_commit.status_code == 409
    assert changed[("ko", "A-1")]["source_type"] == "imported"
    assert changed[("ko", "A-1")]["review_status"] == "pending"
    assert rolled_back.status_code == 200, rolled_back.text
    restored = _rows_by_key(project["id"])
    for key in (("en", "A-1"), ("ko", "A-1")):
        for field in ("source", "target", "source_type", "review_status"):
            assert restored[key][field] == before[key][field]


def test_translation_stable_id_claims_unique_cross_language_unkeyed_siblings_and_rolls_back() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload(
            client,
            project["id"],
            "claim-unkeyed-base.xlsx",
            [["CN", "EN", "KO"], ["共享源文", "Old EN", "오래된 KO"]],
        )
        base_analysis = _analyze(client, project["id"], base["id"], sheet="Data")
        _commit(client, project["id"], base_analysis["token"])
        before = _all_translation_rows(project["id"])
        claimed = _upload(
            client,
            project["id"],
            "claim-unkeyed-update.xlsx",
            [["ID", "CN", "EN"], ["A-1", "共享源文", "New EN"]],
        )
        analysis = _analyze(
            client,
            project["id"],
            claimed["id"],
            sheet="Data",
            languages=["en"],
            dataset_key=base_analysis["dataset_key"],
        )
        with db.connect() as conn:
            items = conn.execute(
                "SELECT language, entity_id FROM archive_import_batch_items WHERE batch_id = ? ORDER BY ordinal",
                (analysis["batch_id"],),
            ).fetchall()
        committed = _commit(client, project["id"], analysis["token"])
        claimed_rows = _rows_by_key(project["id"])
        rolled_back = client.post(
            f"/api/projects/{project['id']}/translations/import/batches/{committed['batch_id']}/rollback"
        )

    assert analysis["can_commit"] is True
    assert {row["language"] for row in items} == {"en", "ko"}
    assert len(items) == len({row["entity_id"] for row in items}) == 2
    assert claimed_rows[("en", "A-1")]["target"] == "New EN"
    assert claimed_rows[("ko", "A-1")]["target"] == "오래된 KO"
    assert rolled_back.status_code == 200, rolled_back.text
    restored = _all_translation_rows(project["id"])
    assert [(row["language"], row["entry_key"], row["source"], row["target"]) for row in restored] == [
        (row["language"], row["entry_key"], row["source"], row["target"]) for row in before
    ]


def test_unkeyed_translation_source_change_in_existing_dataset_is_blocked() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload(
            client,
            project["id"],
            "unkeyed-base.xlsx",
            [["CN", "EN", "KO"], ["旧源文", "Old EN", "오래된 KO"]],
        )
        base_analysis = _analyze(client, project["id"], base["id"], sheet="Data")
        _commit(client, project["id"], base_analysis["token"])
        before = _all_translation_rows(project["id"])

        update = _upload(
            client,
            project["id"],
            "unkeyed-update.xlsx",
            [["CN", "EN"], ["新源文", "New EN"]],
        )
        analysis = _analyze(
            client,
            project["id"],
            update["id"],
            sheet="Data",
            languages=["en"],
            dataset_key=base_analysis["dataset_key"],
        )
        blocked = client.post(
            f"/api/projects/{project['id']}/translations/import/commit",
            json={"token": analysis["token"]},
        )

    assert analysis["can_commit"] is False
    assert "unstable_identity_change" in {conflict["code"] for conflict in analysis["conflicts"]}
    assert blocked.status_code == 409
    assert _all_translation_rows(project["id"]) == before


def test_conflicts_and_protected_rows_block_commit_without_partial_writes() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        manual = client.post(
            f"/api/projects/{project['id']}/translations",
            json={"entry_key": "A-1", "source": "开始游戏", "target": "Manual Start", "language": "en"},
        )
        assert manual.status_code == 200, manual.text
        protected_artifact = _upload(
            client,
            project["id"],
            "protected.xlsx",
            [["ID", "CN", "EN"], ["A-1", "开始游戏", "Imported Start"]],
        )
        protected = _analyze(client, project["id"], protected_artifact["id"])
        assert protected["can_commit"] is False
        assert protected["summary"]["protected"] == 1
        before = _all_translation_rows(project["id"])
        blocked = client.post(
            f"/api/projects/{project['id']}/translations/import/commit",
            json={"token": protected["token"]},
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "conflicts_present"
        assert _all_translation_rows(project["id"]) == before

        overridden = _analyze(
            client,
            project["id"],
            protected_artifact["id"],
            override_protected=True,
        )
        _commit(client, project["id"], overridden["token"])
        current = _rows_by_key(project["id"])[("en", "A-1")]
        assert current["source_type"] == "imported"
        assert current["review_status"] == "pending"

        duplicate = _upload(
            client,
            project["id"],
            "duplicate.xlsx",
            [
                ["ID", "CN", "EN"],
                ["A-2", "领取奖励", "Claim"],
                ["A-2", "领取奖励二", "Claim 2"],
            ],
        )
        duplicate_analysis = _analyze(client, project["id"], duplicate["id"])
        assert duplicate_analysis["can_commit"] is False
        assert duplicate_analysis["summary"]["conflict"] >= 1
        before_duplicate_commit = _all_translation_rows(project["id"])
        duplicate_commit = client.post(
            f"/api/projects/{project['id']}/translations/import/commit",
            json={"token": duplicate_analysis["token"]},
        )
        assert duplicate_commit.status_code == 409
        assert _all_translation_rows(project["id"]) == before_duplicate_commit


def test_rollback_restores_update_insert_and_deactivate_then_detects_later_drift() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload(
            client,
            project["id"],
            "base.xlsx",
            [["ID", "CN", "EN"], ["A-1", "开始游戏", "Start"], ["A-2", "领取奖励", "Claim"]],
        )
        base_analysis = _analyze(client, project["id"], base["id"], sheet="Data")
        _commit(client, project["id"], base_analysis["token"])

        changed = _upload(
            client,
            project["id"],
            "changed.xlsx",
            [["ID", "CN", "EN"], ["A-1", "开始游戏", "Launch"], ["A-3", "退出游戏", "Exit"]],
        )
        analysis = _analyze(
            client,
            project["id"],
            changed["id"],
            sheet="Data",
            mode="snapshot",
            dataset_key=base_analysis["dataset_key"],
            languages=["en"],
        )
        assert analysis["summary"]["update"] == 1
        assert analysis["summary"]["insert"] == 1
        assert analysis["summary"]["deactivate"] == 1
        _commit(client, project["id"], analysis["token"])

        rollback = client.post(
            f"/api/projects/{project['id']}/translations/import/batches/{analysis['batch_id']}/rollback"
        )
        assert rollback.status_code == 200, rollback.text
        repeated = client.post(
            f"/api/projects/{project['id']}/translations/import/batches/{analysis['batch_id']}/rollback"
        )
        assert repeated.status_code == 200
        assert repeated.json() == rollback.json()

        restored = _rows_by_key(project["id"])
        assert restored[("en", "A-1")]["target"] == "Start"
        assert restored[("en", "A-2")]["active"] == 1
        assert restored[("en", "A-3")]["active"] == 0

        drift_artifact = _upload(
            client,
            project["id"],
            "drift.xlsx",
            [["ID", "CN", "EN"], ["A-1", "开始游戏", "Newest"]],
        )
        drift_analysis = _analyze(client, project["id"], drift_artifact["id"])
        _commit(client, project["id"], drift_analysis["token"])
        current = _rows_by_key(project["id"])[("en", "A-1")]
        patched = client.patch(
            f"/api/projects/{project['id']}/translations/{current['id']}",
            json={"target": "Manual after import"},
        )
        assert patched.status_code == 200, patched.text
        before_failed_rollback = _all_translation_rows(project["id"])
        blocked = client.post(
            f"/api/projects/{project['id']}/translations/import/batches/{drift_analysis['batch_id']}/rollback"
        )

    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "rollback_state_drift"
    assert _all_translation_rows(project["id"]) == before_failed_rollback


def test_rollback_preflights_no_id_source_identity_uniqueness() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload(
            client,
            project["id"],
            "no-id-base.xlsx",
            [["CN", "EN"], ["相同源文", "Old"]],
        )
        base_analysis = _analyze(client, project["id"], base["id"])
        _commit(client, project["id"], base_analysis["token"])
        update = _upload(
            client,
            project["id"],
            "no-id-update.xlsx",
            [["CN", "EN"], ["相同源文", "New"]],
        )
        update_analysis = _analyze(client, project["id"], update["id"])
        _commit(client, project["id"], update_analysis["token"])
        db.insert_translation_entry(
            project["id"],
            {"source": "相 同 源 文", "target": "Concurrent", "language": "en", "source_type": "imported"},
        )
        response = client.post(
            f"/api/projects/{project['id']}/translations/import/batches/{update_analysis['batch_id']}/rollback"
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "rollback_constraint_conflict"


def test_analyze_persists_all_items_while_returning_only_bounded_change_samples() -> None:
    source_rows = [[f"A-{index:03d}", f"源文{index}", f"Target {index}"] for index in range(75)]
    with TestClient(app) as client:
        project = _create_project(client)
        artifact = _upload(client, project["id"], "large.xlsx", [["ID", "CN", "EN"], *source_rows])
        analysis = _analyze(client, project["id"], artifact["id"])

    assert analysis["summary"]["source_rows"] == 75
    assert len(analysis["changes"]) <= 50
    with db.connect() as conn:
        item_count = conn.execute(
            "SELECT COUNT(*) FROM archive_import_batch_items WHERE batch_id = ?",
            (analysis["batch_id"],),
        ).fetchone()[0]
    assert item_count == 75


@pytest.mark.parametrize(
    "rows,code",
    [
        (
            [["ID", "CN", "EN"], ["A-1", "源文一", "One"], ["A-1", "源文二", "Two"]],
            "duplicate_entry_key",
        ),
        (
            [["ID", "CN", "EN"], ["", "重复 源文", "One"], ["", "重复源文", "Two"]],
            "duplicate_source",
        ),
        (
            [["ID", "CN", "EN"], ["A-1", "混合 身份", "One"], ["", "混合身份", "Two"]],
            "source_mixed_identity",
        ),
    ],
)
def test_batch_identity_conflicts_are_structured_and_never_commit(rows: list[list[object]], code: str) -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        artifact = _upload(client, project["id"], "conflict.xlsx", rows)
        analysis = _analyze(client, project["id"], artifact["id"])
        assert analysis["can_commit"] is False
        assert code in {conflict["code"] for conflict in analysis["conflicts"]}
        response = client.post(
            f"/api/projects/{project['id']}/translations/import/commit",
            json={"token": analysis["token"]},
        )

    assert response.status_code == 409
    assert _all_translation_rows(project["id"]) == []


def test_existing_id_and_cn_cross_match_updates_by_id() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        db.insert_translation_entry(
            project["id"],
            {"entry_key": "A-1", "source": "源文一", "target": "One", "language": "en", "source_type": "imported"},
        )
        db.insert_translation_entry(
            project["id"],
            {"entry_key": "A-2", "source": "源文二", "target": "Two", "language": "en", "source_type": "imported"},
        )
        artifact = _upload(
            client,
            project["id"],
            "cross.xlsx",
            [["ID", "CN", "EN"], ["A-1", "源文二", "Cross"]],
        )
        analysis = _analyze(client, project["id"], artifact["id"])
        result = _commit(client, project["id"], analysis["token"]) if analysis["can_commit"] else None

    assert analysis["can_commit"] is True
    assert analysis["conflicts"] == []
    assert result and result["status"] == "committed"
    rows = _rows_by_key(project["id"])
    assert rows[("en", "A-1")]["source"] == "源文二"
    assert rows[("en", "A-1")]["target"] == "Cross"
    assert rows[("en", "A-2")]["source"] == "源文二"
    assert rows[("en", "A-2")]["target"] == "Two"


@pytest.mark.parametrize("source_type", ["manual", "qa_passed"])
def test_trusted_sources_require_override_and_override_resets_review(source_type: str) -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        db.insert_translation_entry(
            project["id"],
            {
                "entry_key": "A-1",
                "source": "开始游戏",
                "target": "Trusted",
                "language": "en",
                "source_type": source_type,
                "review_status": "approved",
            },
        )
        artifact = _upload(
            client,
            project["id"],
            "override.xlsx",
            [["ID", "CN", "EN"], ["A-1", "开始游戏", "Replacement"]],
        )
        blocked = _analyze(client, project["id"], artifact["id"])
        allowed = _analyze(client, project["id"], artifact["id"], override_protected=True)
        assert blocked["summary"]["protected"] == 1
        assert blocked["can_commit"] is False
        result = _commit(client, project["id"], allowed["token"])

    assert result["summary"]["protected"] == 1
    current = _rows_by_key(project["id"])[("en", "A-1")]
    assert current["target"] == "Replacement"
    assert current["source_type"] == "imported"
    assert current["review_status"] == "pending"


def test_checksum_state_drift_and_two_analyzes_use_structured_409s() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        artifact = _upload(
            client,
            project["id"],
            "state.xlsx",
            [["ID", "CN", "EN"], ["A-1", "开始游戏", "Start"]],
        )
        checksum_analysis = _analyze(client, project["id"], artifact["id"])
        artifact_path = Path(db.get_artifact(artifact["id"])["path"])
        artifact_path.write_bytes(artifact_path.read_bytes() + b"changed")
        checksum_response = client.post(
            f"/api/projects/{project['id']}/translations/import/commit",
            json={"token": checksum_analysis["token"]},
        )
        assert checksum_response.status_code == 409
        assert checksum_response.json()["detail"]["code"] == "artifact_changed"

        artifact = _upload(
            client,
            project["id"],
            "state-fresh.xlsx",
            [["ID", "CN", "EN"], ["A-1", "开始游戏", "Start"]],
        )
        first = _analyze(client, project["id"], artifact["id"])
        second = _analyze(client, project["id"], artifact["id"])
        _commit(client, project["id"], first["token"])
        second_response = client.post(
            f"/api/projects/{project['id']}/translations/import/commit",
            json={"token": second["token"]},
        )
        assert second_response.status_code == 409
        assert second_response.json()["detail"]["code"] == "state_drift"

        third = _analyze(client, project["id"], artifact["id"])
        db.insert_translation_entry(
            project["id"],
            {"entry_key": "M-1", "source": "外部写入", "target": "Manual", "language": "en"},
        )
        third_response = client.post(
            f"/api/projects/{project['id']}/translations/import/commit",
            json={"token": third["token"]},
        )

    assert third_response.status_code == 409
    assert third_response.json()["detail"]["code"] == "state_drift"


def test_commit_rechecks_artifact_checksum_inside_write_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.translation_archive_batches as batch_engine

    with TestClient(app) as client:
        project = _create_project(client)
        artifact = _upload(
            client,
            project["id"],
            "transaction-checksum.xlsx",
            [["ID", "CN", "EN"], ["A-1", "开始游戏", "Start"]],
        )
        analysis = _analyze(client, project["id"], artifact["id"])
        original_checksum = batch_engine._file_checksum
        checksum_calls = 0

        def mutate_after_first_checksum(path: Path) -> str:
            nonlocal checksum_calls
            checksum_calls += 1
            checksum = original_checksum(path)
            if checksum_calls == 1:
                path.write_bytes(path.read_bytes() + b"changed-after-precheck")
            return checksum

        monkeypatch.setattr(batch_engine, "_file_checksum", mutate_after_first_checksum)
        response = client.post(
            f"/api/projects/{project['id']}/translations/import/commit",
            json={"token": analysis["token"]},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "artifact_changed"
    assert checksum_calls >= 2
    assert _all_translation_rows(project["id"]) == []


def test_sheet_selection_missing_language_and_uncached_formula_are_structured_422() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        multiple = _upload(
            client,
            project["id"],
            "multiple.xlsx",
            sheets=(
                ("One", [["ID", "CN", "EN"], ["A-1", "一", "One"]]),
                ("Two", [["ID", "CN", "EN"], ["A-2", "二", "Two"]]),
            ),
        )
        multi_response = client.post(
            f"/api/projects/{project['id']}/translations/import/analyze",
            json={"artifact_id": multiple["id"]},
        )
        assert multi_response.status_code == 422
        assert multi_response.json()["detail"] == {
            "code": "sheet_selection_required",
            "message": "检测到多个可导入的数据工作表，请选择后重试。",
            "sheets": ["One", "Two"],
        }

        base = _upload(
            client,
            project["id"],
            "base.xlsx",
            [["ID", "CN", "EN", "KO"], ["A-1", "开始游戏", "Start", "시작"]],
        )
        base_analysis = _analyze(client, project["id"], base["id"], sheet="Data")
        _commit(client, project["id"], base_analysis["token"])

        missing = _upload(
            client,
            project["id"],
            "missing-ko.xlsx",
            [["ID", "CN", "EN"], ["A-1", "开始游戏", "Start"]],
        )
        missing_response = client.post(
            f"/api/projects/{project['id']}/translations/import/analyze",
            json={
                "artifact_id": missing["id"],
                "sheet": "Data",
                "mode": "snapshot",
                "dataset_key": base_analysis["dataset_key"],
                "languages": ["ko"],
            },
        )
        assert missing_response.status_code == 422
        assert missing_response.json()["detail"]["code"] == "language_column_missing"
        assert _rows_by_key(project["id"])[("ko", "A-1")]["active"] == 1

        formula = _upload(
            client,
            project["id"],
            "formula.xlsx",
            [["ID", "CN", "EN"], ["A-1", "开始游戏", '=CONCAT("New", " Value")']],
        )
        formula_response = client.post(
            f"/api/projects/{project['id']}/translations/import/analyze",
            json={
                "artifact_id": formula["id"],
                "sheet": "Data",
                "mode": "snapshot",
                "dataset_key": base_analysis["dataset_key"],
                "languages": ["en"],
            },
        )

    assert formula_response.status_code == 422
    assert formula_response.json()["detail"]["code"] == "formula_value_unavailable"


@pytest.mark.parametrize(
    ("formula_column", "formula"),
    [
        ("ID", '=CONCAT("A", "-1")'),
        ("CN", '=CONCAT("开始", "游戏")'),
        ("备注", '=CONCAT("基线", "备注")'),
    ],
)
def test_snapshot_rejects_uncached_formula_in_identity_and_note_columns(
    formula_column: str,
    formula: str,
) -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload(
            client,
            project["id"],
            "formula-identity-base.xlsx",
            [["ID", "CN", "EN", "备注"], ["A-1", "开始游戏", "Start", "基线备注"]],
        )
        base_analysis = _analyze(client, project["id"], base["id"], sheet="Data")
        _commit(client, project["id"], base_analysis["token"])

        values = {"ID": "A-1", "CN": "开始游戏", "EN": "Start", "备注": "基线备注"}
        values[formula_column] = formula
        snapshot = _upload(
            client,
            project["id"],
            f"formula-{formula_column}.xlsx",
            [list(values), list(values.values())],
        )
        response = client.post(
            f"/api/projects/{project['id']}/translations/import/analyze",
            json={
                "artifact_id": snapshot["id"],
                "mode": "snapshot",
                "dataset_key": base_analysis["dataset_key"],
                "languages": ["en"],
            },
        )

    payload = response.json()
    assert response.status_code == 422
    assert payload["detail"]["code"] == "formula_value_unavailable"
    assert "can_commit" not in payload
    assert _rows_by_key(project["id"])[("en", "A-1")]["active"] == 1


def test_snapshot_rejects_nonempty_id_with_blank_source_instead_of_deactivating() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload(
            client,
            project["id"],
            "blank-source-base.xlsx",
            [["ID", "CN", "EN"], ["A-1", "开始游戏", "Start"]],
        )
        base_analysis = _analyze(client, project["id"], base["id"], sheet="Data")
        _commit(client, project["id"], base_analysis["token"])

        snapshot = _upload(
            client,
            project["id"],
            "blank-source.xlsx",
            [["ID", "CN", "EN"], ["A-1", "", "Start"]],
        )
        response = client.post(
            f"/api/projects/{project['id']}/translations/import/analyze",
            json={
                "artifact_id": snapshot["id"],
                "sheet": "Data",
                "mode": "snapshot",
                "dataset_key": base_analysis["dataset_key"],
                "languages": ["en"],
            },
        )

    payload = response.json()
    assert response.status_code == 422
    assert payload["detail"]["code"] == "snapshot_source_required"
    assert "can_commit" not in payload
    assert _rows_by_key(project["id"])[("en", "A-1")]["active"] == 1


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("blank-source.csv", b"ID,CN,EN\nA-1,,Start\n"),
        (
            "blank-source.json",
            json.dumps([{"ID": "A-1", "CN": "", "EN": "Start"}], ensure_ascii=False).encode("utf-8"),
        ),
    ],
)
def test_snapshot_rejects_nonempty_id_with_blank_source_in_csv_and_json(
    filename: str,
    content: bytes,
) -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload(
            client,
            project["id"],
            "blank-source-portable-base.xlsx",
            [["ID", "CN", "EN"], ["A-1", "开始游戏", "Start"]],
        )
        base_analysis = _analyze(client, project["id"], base["id"], sheet="Data")
        _commit(client, project["id"], base_analysis["token"])

        snapshot = _upload_bytes(client, project["id"], filename, content)
        response = client.post(
            f"/api/projects/{project['id']}/translations/import/analyze",
            json={
                "artifact_id": snapshot["id"],
                "mode": "snapshot",
                "dataset_key": base_analysis["dataset_key"],
                "languages": ["en"],
            },
        )

    payload = response.json()
    assert response.status_code == 422
    assert payload["detail"]["code"] == "snapshot_source_required"
    assert "can_commit" not in payload
    assert _rows_by_key(project["id"])[("en", "A-1")]["active"] == 1


def test_analyze_rejects_unsupported_language_with_structured_422() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        project = _create_project(client)
        artifact = _upload(
            client,
            project["id"],
            "unsupported-language.xlsx",
            [["ID", "CN", "EN"], ["A-1", "开始游戏", "Start"]],
        )
        response = client.post(
            f"/api/projects/{project['id']}/translations/import/analyze",
            json={"artifact_id": artifact["id"], "languages": ["xx"]},
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_language"


def test_csv_and_json_use_stable_sheet_keys_and_selected_languages() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        csv_artifact = _upload_bytes(client, project["id"], "rows.csv", "ID,CN,EN\nA-1,开始游戏,Start\n".encode("utf-8-sig"))
        csv_analysis = _analyze(client, project["id"], csv_artifact["id"], languages=["en"])
        assert csv_analysis["sheet"] == "__csv__"
        assert csv_analysis["languages"] == ["en"]
        _commit(client, project["id"], csv_analysis["token"])

        json_artifact = _upload_bytes(
            client,
            project["id"],
            "rows.json",
            json.dumps(
                {"entries": [{"entry_key": "A-2", "source": "领取奖励", "target": "Claim", "language": "en"}]},
                ensure_ascii=False,
            ).encode("utf-8"),
        )
        json_analysis = _analyze(client, project["id"], json_artifact["id"], languages=["en"])

    assert json_analysis["sheet"] == "__json__"
    assert json_analysis["summary"]["insert"] == 1


def test_state_version_triggers_cover_all_raw_translation_writes() -> None:
    project = db.insert_project("state triggers", "game", "")
    entry = db.insert_translation_entry(
        project["id"],
        {"entry_key": "A-1", "source": "开始游戏", "target": "Start", "language": "en"},
    )
    with db.connect() as conn:
        after_insert = conn.execute(
            "SELECT version FROM archive_state_versions WHERE project_id = ? AND kind = 'translations'",
            (project["id"],),
        ).fetchone()[0]
        conn.execute("UPDATE translation_entries SET target = 'Launch' WHERE id = ?", (entry["id"],))
        after_update = conn.execute(
            "SELECT version FROM archive_state_versions WHERE project_id = ? AND kind = 'translations'",
            (project["id"],),
        ).fetchone()[0]
        conn.execute("DELETE FROM translation_entries WHERE id = ?", (entry["id"],))
        after_delete = conn.execute(
            "SELECT version FROM archive_state_versions WHERE project_id = ? AND kind = 'translations'",
            (project["id"],),
        ).fetchone()[0]

    assert (after_insert, after_update, after_delete) == (1, 2, 3)


def test_manual_endpoints_force_review_and_delete_to_inactive_tombstone() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        created = client.post(
            f"/api/projects/{project['id']}/translations",
            json={
                "entry_key": "A-1",
                "source": "开始游戏",
                "target": "Start",
                "language": "en",
                "source_type": "qa_passed",
            },
        )
        assert created.status_code == 200, created.text
        assert created.json()["source_type"] == "manual"
        assert created.json()["review_status"] == "approved"
        patched = client.patch(
            f"/api/projects/{project['id']}/translations/{created.json()['id']}",
            json={"target": "Launch", "source_type": "qa_passed"},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["source_type"] == "manual"
        assert patched.json()["review_status"] == "approved"
        deleted = client.delete(f"/api/projects/{project['id']}/translations/{created.json()['id']}")
        assert deleted.status_code == 200

    assert db.list_translation_entries(project["id"]) == []
    tombstone = _all_translation_rows(project["id"])[0]
    assert tombstone["active"] == 0
    assert tombstone["source_type"] == "manual"


def test_legacy_import_and_internal_qa_archive_share_batches_and_review_rules() -> None:
    from app.workflow.asset_import_export import archive_translation_artifact

    with TestClient(app) as client:
        project = _create_project(client)
        old_artifact = _upload(
            client,
            project["id"],
            "old-client.xlsx",
            [["ID", "CN", "EN"], ["A-1", "开始游戏", "Start"]],
        )
        old_response = client.post(
            f"/api/projects/{project['id']}/translations/import",
            json={"artifact_id": old_artifact["id"]},
        )
        assert old_response.status_code == 200, old_response.text
        assert old_response.json()["imported_count"] == 1

        qa_artifact = _upload(
            client,
            project["id"],
            "qa.xlsx",
            [["ID", "CN", "EN"], ["A-2", "领取奖励", "Claim"]],
        )
        qa_result = archive_translation_artifact(project["id"], qa_artifact["id"], language="en", source_type="qa_passed")
        assert qa_result["imported_count"] == 1

        batches = client.get(f"/api/projects/{project['id']}/translations/import/batches")
        assert batches.status_code == 200, batches.text

    assert len(batches.json()["batches"]) == 2
    qa_row = _rows_by_key(project["id"])[("en", "A-2")]
    assert qa_row["source_type"] == "qa_passed"
    assert qa_row["review_status"] == "approved"
    with db.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM archive_import_revisions WHERE project_id = ? AND kind = 'translations'",
            (project["id"],),
        ).fetchone()[0] == 2


def test_internal_qa_archive_upgrades_matching_delivery_with_issues() -> None:
    from app.workflow.asset_import_export import archive_translation_artifact

    with TestClient(app) as client:
        project = _create_project(client)
        db.insert_translation_entry(
            project["id"],
            {
                "entry_key": "A-1",
                "source": "领取奖励",
                "target": "Needs review",
                "language": "en",
                "source_type": "delivered_with_issues",
                "review_status": "pending",
            },
        )
        qa_artifact = _upload(
            client,
            project["id"],
            "qa-passed.xlsx",
            [["ID", "CN", "EN"], ["A-1", "领取奖励", "Claim Reward"]],
        )

        result = archive_translation_artifact(
            project["id"],
            qa_artifact["id"],
            language="en",
            source_type="qa_passed",
        )

    assert result["status"] == "committed"
    assert result["imported_count"] == 1
    current = _rows_by_key(project["id"])[("en", "A-1")]
    assert current["target"] == "Claim Reward"
    assert current["source_type"] == "qa_passed"
    assert current["review_status"] == "approved"


def test_legacy_import_blank_target_skip_does_not_report_existing_entry_as_imported() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        first_artifact = _upload(
            client,
            project["id"],
            "legacy-first.xlsx",
            [["ID", "CN", "EN"], ["A-1", "开始游戏", "Start"]],
        )
        first = client.post(
            f"/api/projects/{project['id']}/translations/import",
            json={"artifact_id": first_artifact["id"]},
        )
        assert first.status_code == 200, first.text
        blank_artifact = _upload(
            client,
            project["id"],
            "legacy-blank.xlsx",
            [["ID", "CN", "EN"], ["A-1", "开始游戏", ""]],
        )
        skipped = client.post(
            f"/api/projects/{project['id']}/translations/import",
            json={"artifact_id": blank_artifact["id"]},
        )

    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["summary"]["skip"] == 1
    assert skipped.json()["imported_count"] == 0
    assert skipped.json()["entries"] == []
    assert _rows_by_key(project["id"])[("en", "A-1")]["target"] == "Start"


def test_internal_qa_archive_conflict_is_audited_without_failing_or_writing() -> None:
    from app.workflow.asset_import_export import archive_translation_artifact

    with TestClient(app) as client:
        project = _create_project(client)
        db.insert_translation_entry(
            project["id"],
            {"entry_key": "A-1", "source": "源文一", "target": "Trusted", "language": "en", "source_type": "qa_passed"},
        )
        db.insert_translation_entry(
            project["id"],
            {"entry_key": "A-2", "source": "源文二", "target": "Existing", "language": "en", "source_type": "imported"},
        )
        artifact = _upload(
            client,
            project["id"],
            "qa-conflict.xlsx",
            [
                ["ID", "CN", "EN"],
                ["A-1", "源文一", "Trusted"],
                ["A-2", "另一源文", "Changed"],
                ["A-3", "源文二", "Existing"],
            ],
        )
        before = _all_translation_rows(project["id"])
        result = archive_translation_artifact(project["id"], artifact["id"], language="en", source_type="qa_passed")

    assert result["status"] == "blocked"
    assert result["imported_count"] == 0
    assert result["summary"]["conflict"] >= 1
    assert _all_translation_rows(project["id"]) == before


def test_token_and_batch_scope_are_project_and_kind_isolated() -> None:
    with TestClient(app) as client:
        project = _create_project(client, "scope one")
        other = _create_project(client, "scope two")
        artifact = _upload(
            client,
            project["id"],
            "scope.xlsx",
            [["ID", "CN", "EN"], ["A-1", "开始游戏", "Start"]],
        )
        analysis = _analyze(client, project["id"], artifact["id"])
        wrong_project = client.post(
            f"/api/projects/{other['id']}/translations/import/commit",
            json={"token": analysis["token"]},
        )
        missing_token = client.post(
            f"/api/projects/{project['id']}/translations/import/commit",
            json={"token": "missing-token"},
        )
        assert wrong_project.status_code == 409
        assert wrong_project.json()["detail"]["code"] == "batch_scope_mismatch"
        assert missing_token.status_code == 409
        assert missing_token.json()["detail"]["code"] == "invalid_token"

        with db.connect() as conn:
            now = db.now_iso()
            conn.execute(
                """
                INSERT INTO archive_import_batches
                  (id, project_id, kind, artifact_id, artifact_checksum, token, request_json,
                   summary_json, result_json, rollback_result_json, mode, dataset_key, sheet_key,
                   languages_json, base_state_version, base_state_checksum, status, created_at, updated_at)
                VALUES (?, ?, 'glossary', ?, '', ?, '{}', '{}', '{}', '{}', 'merge', '', '', '[]', 0, '', 'analyzed', ?, ?)
                """,
                ("batch_glossary_scope", project["id"], artifact["id"], "glossary-token", now, now),
            )
        kind_response = client.post(
            f"/api/projects/{project['id']}/translations/import/commit",
            json={"token": "glossary-token"},
        )
        kind_rollback = client.post(
            f"/api/projects/{project['id']}/translations/import/batches/batch_glossary_scope/rollback"
        )

    assert kind_response.status_code == 409
    assert kind_response.json()["detail"]["code"] == "batch_scope_mismatch"
    assert kind_rollback.status_code == 409
    assert kind_rollback.json()["detail"]["code"] == "batch_scope_mismatch"


def test_existing_rows_migrate_active_and_legacy_approved_once() -> None:
    project = db.insert_project("legacy migration", "game", "")
    with db.connect() as conn:
        conn.execute("DROP TRIGGER IF EXISTS trg_translation_entries_archive_state_insert")
        conn.execute("DROP TRIGGER IF EXISTS trg_translation_entries_archive_state_update")
        conn.execute("DROP TRIGGER IF EXISTS trg_translation_entries_archive_state_delete")
        conn.execute("DROP TABLE translation_entries")
        conn.execute(
            """
            CREATE TABLE translation_entries (
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
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO translation_entries VALUES (?, ?, 'A-1', '开始游戏', 'Start', '', 'en', '', 0, '', 'imported', '', ?, ?)",
            ("legacy-row", project["id"], db.now_iso(), db.now_iso()),
        )

    db.init_db()
    with db.connect() as conn:
        migrated = dict(conn.execute("SELECT * FROM translation_entries WHERE id = 'legacy-row'").fetchone())
        conn.execute("UPDATE translation_entries SET review_status = 'pending' WHERE id = 'legacy-row'")
    db.init_db()
    with db.connect() as conn:
        restarted = dict(conn.execute("SELECT * FROM translation_entries WHERE id = 'legacy-row'").fetchone())

    assert migrated["active"] == 1
    assert migrated["review_status"] == "legacy_approved"
    assert restarted["review_status"] == "pending"
