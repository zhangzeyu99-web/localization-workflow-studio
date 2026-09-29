from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.db as db
from app.main import app
from app.workflow.asset_import_export import archive_translation_artifact
from conftest import reset_data_root


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()


def _create_project(client: TestClient, name: str) -> dict:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 200, response.text
    return response.json()


def _upload_bytes(
    client: TestClient,
    project_id: str,
    filename: str,
    content: bytes,
    kind: str,
    mime: str = "application/octet-stream",
) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/files?kind={kind}",
        files={"file": (filename, content, mime)},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _workbook_bytes(sheets: list[tuple[str, list[list[object]]]]) -> bytes:
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


def _translation_rows(response_payload: dict) -> dict[tuple[str, str], dict]:
    return {
        (str(row.get("source") or ""), str(row.get("language") or "")): row
        for row in response_payload["entries"]
    }


def test_archive_translation_artifact_imports_only_requested_language(tmp_path: Path) -> None:
    project = db.insert_project("single language archive")
    path = tmp_path / "qa-final.xlsx"
    path.write_bytes(
        _workbook_bytes(
            [
                (
                    "Language",
                    [["ID", "CN", "EN", "KR", "JP"], ["A-1", "开始游戏", "Start Game", "게임 시작", "ゲーム開始"]],
                )
            ]
        )
    )
    artifact = db.add_artifact(project["id"], "QA final", path, "qa_final_workbook")

    result = archive_translation_artifact(project["id"], artifact["id"], language="en")

    assert result["languages"] == ["en"]
    persisted = db.list_translation_entries(project["id"])
    assert [(row["language"], row["target"]) for row in persisted] == [("en", "Start Game")]


def test_missing_explicit_target_column_never_falls_back_to_detected_language_column() -> None:
    content = _workbook_bytes([("Data", [["ID", "CN", "EN"], ["A-1", "开始游戏", "Start Game"]])])
    with TestClient(app) as client:
        translation_project = _create_project(client, "missing translation column")
        translation_artifact = _upload_bytes(
            client,
            translation_project["id"],
            "translations.xlsx",
            content,
            "language_table",
        )
        translation = client.post(
            f"/api/projects/{translation_project['id']}/translations/import",
            json={
                "artifact_id": translation_artifact["id"],
                "language": "en",
                "target_column": "MISSING",
            },
        )

        glossary_project = _create_project(client, "missing glossary column")
        glossary_artifact = _upload_bytes(client, glossary_project["id"], "glossary.xlsx", content, "term_base")
        glossary = client.post(
            f"/api/projects/{glossary_project['id']}/glossary/import-preview",
            json={
                "artifact_id": glossary_artifact["id"],
                "language": "en",
                "target_column": "MISSING",
            },
        )

    assert translation.status_code == 400, translation.text
    assert db.list_translation_entries(translation_project["id"]) == []
    assert glossary.status_code == 400, glossary.text
    assert db.list_glossary_terms(glossary_project["id"]) == []


def test_multilingual_translation_csv_api_roundtrip() -> None:
    content = "ID,CN,EN,KR\nA-1,开始游戏,Start Game,게임 시작\n".encode("utf-8-sig")
    with TestClient(app) as client:
        project = _create_project(client, "translation csv")
        artifact = _upload_bytes(client, project["id"], "translations.csv", content, "language_table", "text/csv")
        imported = client.post(
            f"/api/projects/{project['id']}/translations/import",
            json={"artifact_id": artifact["id"]},
        )

    assert imported.status_code == 200, imported.text
    rows = _translation_rows(imported.json())
    assert imported.json()["languages"] == ["en", "ko"]
    assert rows[("开始游戏", "en")]["target"] == "Start Game"
    assert rows[("开始游戏", "ko")]["target"] == "게임 시작"
