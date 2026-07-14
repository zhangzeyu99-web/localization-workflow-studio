from __future__ import annotations

import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.db as db
import app.workflow.translation_tasks as translation_tasks
from app.config import DEFAULT_SETTINGS, save_settings
from app.main import app
from app.workflow.translation_tasks import mark_translation_task_state
from conftest import reset_data_root, wait_for_background_jobs


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    data_root = Path(os.environ.setdefault("LWS_DATA_ROOT", str(Path(tempfile.gettempdir()) / "lws-test-data")))
    reset_data_root(data_root)
    db.init_db()
    save_settings(DEFAULT_SETTINGS)
    yield
    wait_for_background_jobs()
    save_settings(DEFAULT_SETTINGS)


def _legacy_unfinished_run_ids(project: dict) -> set[str]:
    closed_states = {"abandoned", "closed", "delivered"}
    return {
        run["id"]
        for run in project.get("runs", [])
        if run.get("kind") in {"translation", "qa"}
        and run.get("status") in {"failed", "needs_input", "canceled"}
        and not (run.get("metadata") or {}).get("translation_task_id")
        and str((run.get("metadata") or {}).get("translation_task_state") or "") not in closed_states
    }


def test_legacy_unfinished_run_can_be_abandoned_and_stays_closed_after_project_refresh() -> None:
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Legacy task abandon", "type": "QA"}).json()
        run = db.insert_run(
            project["id"],
            "translation",
            "en",
            metadata={"input_artifact_id": "legacy-source", "task_origin": "translation_run"},
        )
        db.update_run(run["id"], status="canceled")

        before = client.get(f"/api/projects/{project['id']}").json()
        assert run["id"] in _legacy_unfinished_run_ids(before)

        response = client.post(f"/api/runs/{run['id']}/abandon-translation-task")

        assert response.status_code == 200, response.text
        assert response.json() == {
            "project_id": project["id"],
            "run_id": run["id"],
            "state": "abandoned",
        }
        refreshed = client.get(f"/api/projects/{project['id']}").json()
        refreshed_run = next(item for item in refreshed["runs"] if item["id"] == run["id"])
        assert refreshed_run["metadata"]["translation_task_state"] == "abandoned"
        assert run["id"] not in _legacy_unfinished_run_ids(refreshed)


def test_running_legacy_translation_run_cannot_be_abandoned() -> None:
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Running legacy task", "type": "QA"}).json()
        run = db.insert_run(
            project["id"],
            "translation",
            "en",
            metadata={"input_artifact_id": "legacy-source", "task_origin": "translation_run"},
        )
        db.update_run(run["id"], status="running")

        response = client.post(f"/api/runs/{run['id']}/abandon-translation-task")

        assert response.status_code == 409, response.text
        assert "running translation task cannot be abandoned" in response.json()["detail"]
        refreshed = client.get(f"/api/runs/{run['id']}").json()
        assert "translation_task_state" not in refreshed["metadata"]


@pytest.mark.parametrize(
    ("explicit_task_id", "expected_task_id"),
    [
        (None, "task-source"),
        ("task-explicit", "task-explicit"),
    ],
)
def test_qa_run_inherits_source_translation_task_lineage(
    tmp_path: Path,
    explicit_task_id: str | None,
    expected_task_id: str,
) -> None:
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "QA lineage", "type": "QA"}).json()
        source_artifact = db.add_artifact(
            project["id"],
            "source.xlsx",
            tmp_path / "source.xlsx",
            "language_table",
        )
        qa_input_artifact = db.add_artifact(
            project["id"],
            "translated.xlsx",
            tmp_path / "translated.xlsx",
            "qa_input",
        )
        source_response = client.post(
            "/api/runs",
            json={
                "project_id": project["id"],
                "kind": "translation",
                "language": "en",
                "input_artifact_id": source_artifact["id"],
                "translation_task_id": "task-source",
            },
        )
        assert source_response.status_code == 200, source_response.text

        qa_payload = {
            "project_id": project["id"],
            "kind": "qa",
            "language": "en",
            "input_artifact_id": qa_input_artifact["id"],
            "source_run_id": source_response.json()["id"],
        }
        if explicit_task_id is not None:
            qa_payload["translation_task_id"] = explicit_task_id
        qa_response = client.post("/api/runs", json=qa_payload)

        assert qa_response.status_code == 200, qa_response.text
        metadata = qa_response.json()["metadata"]
        assert metadata["input_artifact_id"] == qa_input_artifact["id"]
        assert metadata["parent_input_artifact_id"] == source_artifact["id"]
        assert metadata["multilingual_source_artifact_id"] == source_artifact["id"]
        assert metadata["translation_task_id"] == expected_task_id


@pytest.mark.parametrize("terminal_state", ["abandoned", "closed"])
def test_delivered_does_not_reopen_terminal_translation_task(terminal_state: str) -> None:
    project = db.insert_project(f"Terminal task {terminal_state}", "QA", "")
    run = db.insert_run(
        project["id"],
        "translation",
        "en",
        metadata={"translation_task_id": "task-terminal", "task_origin": "translation_run"},
    )
    db.update_run(run["id"], status="passed")
    mark_translation_task_state(project["id"], "task-terminal", terminal_state)
    before = db.get_run(run["id"])
    events_before = db.list_events(run["id"])

    result = mark_translation_task_state(project["id"], "task-terminal", "delivered")

    after = db.get_run(run["id"])
    assert result["state"] == terminal_state
    assert result["updated_run_ids"] == []
    assert after["metadata"]["translation_task_state"] == terminal_state
    assert after["metadata"]["translation_task_state_updated_at"] == before["metadata"]["translation_task_state_updated_at"]
    assert db.list_events(run["id"]) == events_before


def test_marking_translation_task_delivered_twice_is_idempotent() -> None:
    project = db.insert_project("Idempotent delivered task", "QA", "")
    run = db.insert_run(
        project["id"],
        "translation",
        "en",
        metadata={"translation_task_id": "task-delivered", "task_origin": "translation_run"},
    )
    db.update_run(run["id"], status="passed")
    mark_translation_task_state(project["id"], "task-delivered", "delivered")
    before = db.get_run(run["id"])
    events_before = db.list_events(run["id"])

    result = mark_translation_task_state(project["id"], "task-delivered", "delivered")

    after = db.get_run(run["id"])
    assert result["state"] == "delivered"
    assert result["updated_run_ids"] == []
    assert after["metadata"]["translation_task_state_updated_at"] == before["metadata"]["translation_task_state_updated_at"]
    assert db.list_events(run["id"]) == events_before


def test_abandon_does_not_overwrite_delivered_translation_task() -> None:
    project = db.insert_project("Delivered task ignores late abandon", "QA", "")
    run = db.insert_run(
        project["id"],
        "translation",
        "en",
        metadata={"translation_task_id": "task-delivered-late-abandon", "task_origin": "translation_run"},
    )
    db.update_run(run["id"], status="passed")
    mark_translation_task_state(project["id"], "task-delivered-late-abandon", "delivered")
    before = db.get_run(run["id"])
    events_before = db.list_events(run["id"])

    result = mark_translation_task_state(project["id"], "task-delivered-late-abandon", "abandoned")

    after = db.get_run(run["id"])
    assert result["state"] == "delivered"
    assert result["updated_run_ids"] == []
    assert after["metadata"]["translation_task_state"] == "delivered"
    assert after["metadata"]["translation_task_state_updated_at"] == before["metadata"]["translation_task_state_updated_at"]
    assert db.list_events(run["id"]) == events_before


def test_concurrent_terminal_updates_choose_one_state_for_every_task_run(monkeypatch: pytest.MonkeyPatch) -> None:
    project = db.insert_project("Concurrent terminal task", "QA", "")
    runs = [
        db.insert_run(
            project["id"],
            kind,
            "en",
            metadata={"translation_task_id": "task-concurrent-terminal", "task_origin": "translation_run"},
        )
        for kind in ("translation", "qa")
    ]
    for run in runs:
        db.update_run(run["id"], status="passed")

    reads_complete = threading.Barrier(2)
    original_translation_task_runs = translation_tasks.translation_task_runs

    def synchronized_open_task_read(project_id: str, task_id: str) -> list[dict]:
        open_runs = original_translation_task_runs(project_id, task_id)
        reads_complete.wait(timeout=5)
        return open_runs

    monkeypatch.setattr(translation_tasks, "translation_task_runs", synchronized_open_task_read)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                translation_tasks.mark_translation_task_state,
                project["id"],
                "task-concurrent-terminal",
                state,
            )
            for state in ("delivered", "abandoned")
        ]
        results = [future.result(timeout=10) for future in futures]

    result_states = {result["state"] for result in results}
    assert len(result_states) == 1
    winning_state = result_states.pop()
    assert sorted(len(result["updated_run_ids"]) for result in results) == [0, 2]
    assert {
        db.get_run(run["id"])["metadata"]["translation_task_state"]
        for run in runs
    } == {winning_state}
