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
import app.jobs as jobs
import app.workflow.multilingual as multilingual
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


def test_multilingual_status_maps_existing_child_runs(tmp_path: Path) -> None:
    project = db.insert_project("multi status", "QA", "")
    artifact = _add_language_table(project["id"], tmp_path / "source.xlsx", ["EN", "KR"])
    en_run = db.insert_run(
        project["id"],
        "translation",
        "en",
        metadata={"input_artifact_id": artifact["id"], "task_origin": "translation_run"},
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/projects/{project['id']}/multilingual/status",
            params={"input_artifact_id": artifact["id"], "languages": "en,ko"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert [item["language"] for item in payload["languages"]] == ["en", "ko"]
    assert payload["languages"][0]["translation_run_id"] == en_run["id"]
    assert payload["languages"][1]["translation_run_id"] is None


def test_start_multilingual_translation_creates_missing_child_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = db.insert_project("multi translate", "QA", "")
    artifact = _add_language_table(project["id"], tmp_path / "source.xlsx", ["EN", "KR"])

    def fake_translate(run_id: str, request: object, cancel_event: object | None = None) -> dict:
        _ = request, cancel_event
        run = db.get_run(run_id)
        db.update_run(run_id, status="passed", metadata={**run.get("metadata", {}), "fake_completed": True})
        return {"run": db.get_run(run_id), "artifacts": []}

    monkeypatch.setattr(multilingual, "run_translate_sync", fake_translate)
    with TestClient(app) as client:
        response = client.post(
            f"/api/projects/{project['id']}/multilingual/translate/start",
            json={"input_artifact_id": artifact["id"], "languages": ["en", "ko"], "batch_size": 10, "task_code": "T"},
        )
        wait_for_background_jobs()
        status = client.get(
            f"/api/projects/{project['id']}/multilingual/status",
            params={"input_artifact_id": artifact["id"], "languages": "en,ko"},
        ).json()

    assert response.status_code == 200
    assert {item["language"] for item in response.json()["languages"]} == {"en", "ko"}
    assert all(item["translation_run_id"] for item in status["languages"])
    assert all(item["status"] == "passed" for item in status["languages"])


def test_multilingual_start_rejects_existing_project_job_before_creating_child_runs(tmp_path: Path) -> None:
    project = db.insert_project("multi busy", "QA", "")
    artifact = _add_language_table(project["id"], tmp_path / "source.xlsx", ["EN", "KR"])
    lease_name = jobs.lease_name_for_project(project["id"])

    with TestClient(app) as client:
        assert db.acquire_job_lease(lease_name, "run:existing", operator_name="Alice")
        try:
            response = client.post(
                f"/api/projects/{project['id']}/multilingual/translate/start",
                json={"input_artifact_id": artifact["id"], "languages": ["en", "ko"], "batch_size": 10, "task_code": "T"},
            )

            assert response.status_code == 409
            assert "Alice" in response.json()["detail"]
            assert db.list_runs(project["id"]) == []
        finally:
            db.release_job_lease(lease_name, "run:existing")


def test_multilingual_capacity_rejection_does_not_leave_child_runs_queued(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = db.insert_project("multi capacity", "QA", "")
    artifact = _add_language_table(project["id"], tmp_path / "source.xlsx", ["EN", "KR"])
    monkeypatch.setattr(
        multilingual,
        "start_singleton_job",
        lambda project_id, job_id, worker: (False, {"reason": "capacity", "active_count": 2, "limit": 2}),
    )

    result = multilingual.start_multilingual_translation_queue(
        project["id"],
        multilingual.MultilingualQueueRequest(
            input_artifact_id=artifact["id"],
            languages=["en", "ko"],
            batch_size=10,
            task_code="T",
        ),
    )

    assert result["queue_started"] is False
    assert result["active_conflict"]["reason"] == "capacity"
    child_runs = db.list_runs(project["id"])
    assert len(child_runs) == 2
    assert {run["status"] for run in child_runs} == {"created"}


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


def test_multilingual_status_rejects_cross_project_artifact(tmp_path: Path) -> None:
    first = db.insert_project("A", "QA", "")
    second = db.insert_project("B", "QA", "")
    artifact = _add_language_table(first["id"], tmp_path / "source.xlsx", ["EN"])

    with TestClient(app) as client:
        response = client.get(
            f"/api/projects/{second['id']}/multilingual/status",
            params={"input_artifact_id": artifact["id"], "languages": "en"},
        )

    assert response.status_code == 400



def test_multilingual_status_exposes_large_text_metadata(tmp_path: Path) -> None:
    project = db.insert_project("multi large text", "QA", "")
    artifact = _add_language_table(project["id"], tmp_path / "source.xlsx", ["EN"])
    run = db.insert_run(
        project["id"],
        "translation",
        "en",
        metadata={
            "input_artifact_id": artifact["id"],
            "task_origin": "translation_run",
            "large_text": {
                "mode": "auto",
                "preflight": {"large_pack": True, "unique_items": 6001, "estimated_target_cells": 6001},
                "cache_lint": {"status": "passed", "hard_blockers": 0},
            },
        },
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/projects/{project['id']}/multilingual/status",
            params={"input_artifact_id": artifact["id"], "languages": "en"},
        )

    assert response.status_code == 200
    item = response.json()["languages"][0]
    assert item["translation_run_id"] == run["id"]
    assert item["large_text"]["preflight"]["large_pack"] is True
    assert item["large_text"]["cache_lint"]["status"] == "passed"


def test_multilingual_qa_skips_languages_without_translated_input(tmp_path: Path) -> None:
    project = db.insert_project("multi qa skip", "QA", "")
    artifact = _add_language_table(project["id"], tmp_path / "source.xlsx", ["EN", "KR"])

    with TestClient(app) as client:
        response = client.post(
            f"/api/projects/{project['id']}/multilingual/qa/start",
            json={"input_artifact_id": artifact["id"], "languages": ["en", "ko"]},
        )

    assert response.status_code == 200
    result = response.json()
    assert result["created_run_ids"] == []
    assert {item["status"] for item in result["languages"]} == {"pending"}
