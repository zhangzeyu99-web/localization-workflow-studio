from __future__ import annotations

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
