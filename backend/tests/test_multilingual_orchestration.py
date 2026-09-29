from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("LWS_DATA_ROOT", str(Path(tempfile.gettempdir()) / "lws-test-data"))
os.environ["LWS_ENABLE_TEST_PROVIDER"] = "1"

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

import app.db as db
from app.config import DEFAULT_SETTINGS, save_settings
from app.main import app
from conftest import reset_data_root, wait_for_background_jobs


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    data_root = Path(os.environ["LWS_DATA_ROOT"])
    reset_data_root(data_root)
    db.init_db()
    save_settings(DEFAULT_SETTINGS)
    yield
    wait_for_background_jobs()
    save_settings(DEFAULT_SETTINGS)


def _language_table(path: Path, headers: list[str]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Language"
    ws.append(["ID", "CN", *headers])
    ws.append([1, "开始游戏", *("" for _ in headers)])
    ws.append([2, "领取奖励", *("" for _ in headers)])
    wb.save(path)
    wb.close()


def _add_language_table(project_id: str, path: Path, headers: list[str]) -> dict:
    _language_table(path, headers)
    return db.add_artifact(project_id, "source", path, "language_table", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def test_italian_translation_writes_it_column_in_multilingual_workbook(tmp_path: Path) -> None:
    project = db.insert_project("Italian target column", "QA", "")
    artifact = _add_language_table(project["id"], tmp_path / "source.xlsx", ["EN", "IT"])
    save_settings({**DEFAULT_SETTINGS, "provider": "test-fake", "model": "test-fake-localization", "batch_size": 10})

    with TestClient(app) as client:
        run = client.post(
            "/api/runs",
            json={"project_id": project["id"], "kind": "translation", "language": "it", "input_artifact_id": artifact["id"]},
        ).json()
        response = client.post(f"/api/runs/{run['id']}/translate", json={"provider": "test-fake", "batch_size": 10})

    assert response.status_code == 200, response.text
    assert response.json()["run"]["status"] == "passed"
    final_artifact = next(item for item in db.list_artifacts(run_id=run["id"]) if item["kind"] == "qa_final_workbook")
    workbook = load_workbook(final_artifact["path"], read_only=True, data_only=False)
    try:
        sheet = workbook.active
        assert sheet.cell(2, 3).value in {None, ""}
        assert str(sheet.cell(2, 4).value).startswith("TestFake")
    finally:
        workbook.close()
