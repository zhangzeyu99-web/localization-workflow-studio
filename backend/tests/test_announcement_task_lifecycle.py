from __future__ import annotations

import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.db as db
import app.jobs as jobs
from app import workflow
from app.main import app
from conftest import reset_data_root, wait_for_background_jobs


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    data_root = Path(os.environ.setdefault("LWS_DATA_ROOT", str(Path(tempfile.gettempdir()) / "lws-test-data")))
    reset_data_root(data_root)
    db.init_db()
    yield
    wait_for_background_jobs()


def _create_announcement_source(project_id: str, tmp_path: Path, name: str = "announcement.txt") -> dict:
    source_path = tmp_path / name
    source_path.write_text("维护公告", encoding="utf-8")
    return db.add_artifact(project_id, name, source_path, "asset", mime="text/plain", origin="uploaded")


def test_translation_cancel_preserves_concurrent_cancel_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    project = db.insert_project("Announcement cancel audit", "QA", "")
    task = db.insert_announcement_task(
        project["id"],
        {
            "title": "cancel audit",
            "selected_languages": ["en"],
            "status": "running",
            "current_step": 7,
            "metadata": {},
        },
    )
    stale_task = db.get_announcement_task(task["id"])
    db.merge_announcement_task_metadata(task["id"], {"canceled_by": "Bob"})

    real_get = db.get_announcement_task
    stale_reads = 0

    def stale_get_once(task_id: str, *args: object, **kwargs: object) -> dict:
        nonlocal stale_reads
        if task_id == task["id"] and stale_reads == 0:
            stale_reads += 1
            return stale_task
        return real_get(task_id, *args, **kwargs)

    monkeypatch.setattr(db, "get_announcement_task", stale_get_once)
    workflow.cancel_announcement_translation_task(task["id"])

    assert real_get(task["id"])["metadata"]["canceled_by"] == "Bob"


def test_duplicate_create_returns_existing_unfinished_task_conflict(tmp_path: Path) -> None:
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Announcement create conflict", "type": "QA"}).json()
        source = _create_announcement_source(project["id"], tmp_path)
        payload = {"source_artifact_id": source["id"], "languages": ["en"]}

        first = client.post(f"/api/projects/{project['id']}/announcement-tasks", json=payload)
        second = client.post(f"/api/projects/{project['id']}/announcement-tasks", json=payload)

        assert first.status_code == 200, first.text
        assert second.status_code == 409, second.text
        assert second.json()["detail"] == {
            "code": "unfinished_announcement_task_exists",
            "task_id": first.json()["id"],
            "status": first.json()["status"],
        }
        assert len(db.list_announcement_tasks(project["id"])) == 1


def test_concurrent_creates_leave_one_unfinished_task(tmp_path: Path) -> None:
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Concurrent announcement create", "type": "QA"}).json()
        source = _create_announcement_source(project["id"], tmp_path)
        payload = {"source_artifact_id": source["id"], "languages": ["en"]}
        start = threading.Barrier(2)

        def create() -> tuple[int, dict]:
            start.wait(timeout=5)
            response = client.post(f"/api/projects/{project['id']}/announcement-tasks", json=payload)
            return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = [future.result(timeout=10) for future in [executor.submit(create), executor.submit(create)]]

        assert sorted(status for status, _ in responses) == [200, 409]
        created = next(body for status, body in responses if status == 200)
        conflict = next(body["detail"] for status, body in responses if status == 409)
        assert conflict == {
            "code": "unfinished_announcement_task_exists",
            "task_id": created["id"],
            "status": created["status"],
        }
        assert len(db.list_announcement_tasks(project["id"])) == 1


@pytest.mark.parametrize("active_status", ["queued", "running"])
def test_duplicate_create_prefers_active_legacy_task_conflict(
    tmp_path: Path,
    active_status: str,
) -> None:
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": f"Legacy {active_status} conflict", "type": "QA"}).json()
        source = _create_announcement_source(project["id"], tmp_path)
        payload = {"source_artifact_id": source["id"], "languages": ["en"]}

        draft = db.insert_announcement_task(
            project["id"],
            {
                "title": "legacy draft",
                "source_artifact_id": source["id"],
                "source_format": "txt",
                "selected_languages": ["en"],
            },
        )
        db.update_announcement_task(draft["id"], status="delivered")
        active = db.insert_announcement_task(
            project["id"],
            {
                "title": f"legacy {active_status}",
                "source_artifact_id": source["id"],
                "source_format": "txt",
                "selected_languages": ["en"],
            },
        )
        db.update_announcement_task(active["id"], status=active_status)
        db.update_announcement_task(draft["id"], status="draft", allow_terminal_update=True)

        response = client.post(f"/api/projects/{project['id']}/announcement-tasks", json=payload)

        assert response.status_code == 409, response.text
        assert response.json()["detail"] == {
            "code": "unfinished_announcement_task_exists",
            "task_id": active["id"],
            "status": active_status,
        }


def test_generic_cancel_signals_singleton_and_blocks_late_worker_write(tmp_path: Path) -> None:
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Announcement cancel worker", "type": "QA"}).json()
        source = _create_announcement_source(project["id"], tmp_path)
        task = db.insert_announcement_task(
            project["id"],
            {
                "title": "cancel worker",
                "source_artifact_id": source["id"],
                "source_format": "txt",
                "selected_languages": ["en"],
                "status": "queued",
                "current_step": 7,
            },
        )
        worker_started = threading.Event()
        cancellation_seen = threading.Event()

        def late_worker(cancel_event: threading.Event) -> None:
            worker_started.set()
            if cancel_event.wait(timeout=2):
                cancellation_seen.set()
            db.update_announcement_task(task["id"], status="running", current_step=7, metadata={"late_worker_write": True})
            db.upsert_announcement_task_language(
                task["id"],
                project["id"],
                "en",
                status="running",
                current_step=7,
                metadata={"late_worker_write": True},
            )

        started, conflict = jobs.start_singleton_job(project["id"], f"announcement:{task['id']}", late_worker)
        assert started and conflict is None
        assert worker_started.wait(timeout=2)
        try:
            response = client.post(f"/api/announcement-tasks/{task['id']}/cancel")
            assert response.status_code == 200, response.text
            assert cancellation_seen.wait(timeout=1)
            wait_for_background_jobs(timeout=3)
            persisted = db.get_announcement_task(task["id"])
            assert persisted["status"] == "canceled"
            assert "late_worker_write" not in persisted["metadata"]
            assert persisted["languages"][0]["status"] == "canceled"
            assert "late_worker_write" not in persisted["languages"][0]["metadata"]
        finally:
            jobs.cancel_singleton_job(project["id"], f"announcement:{task['id']}")
            wait_for_background_jobs(timeout=3)


def test_conditional_cancel_accepts_still_stopped_task(tmp_path: Path) -> None:
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Conditional announcement cancel", "type": "QA"}).json()
        source = _create_announcement_source(project["id"], tmp_path)
        task = db.insert_announcement_task(
            project["id"],
            {
                "title": "stopped draft",
                "source_artifact_id": source["id"],
                "source_format": "txt",
                "selected_languages": ["en"],
                "status": "source_ready",
                "current_step": 2,
            },
        )

        response = client.post(
            f"/api/announcement-tasks/{task['id']}/cancel",
            json={"expected_statuses": ["source_ready", "failed"]},
        )

        assert response.status_code == 200, response.text
        assert response.json()["task"]["status"] == "canceled"
        assert db.get_announcement_task(task["id"])["status"] == "canceled"


def test_conditional_cancel_rejects_task_that_became_running(tmp_path: Path) -> None:
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Conditional cancel conflict", "type": "QA"}).json()
        source = _create_announcement_source(project["id"], tmp_path)
        task = db.insert_announcement_task(
            project["id"],
            {
                "title": "draft becomes active",
                "source_artifact_id": source["id"],
                "source_format": "txt",
                "selected_languages": ["en"],
                "status": "source_ready",
                "current_step": 2,
            },
        )
        db.update_announcement_task(task["id"], status="running", current_step=7)

        response = client.post(
            f"/api/announcement-tasks/{task['id']}/cancel",
            json={"expected_statuses": ["source_ready", "failed"]},
        )

        assert response.status_code == 409, response.text
        assert response.json()["detail"] == {
            "code": "announcement_task_status_conflict",
            "task_id": task["id"],
            "status": "running",
        }
        assert db.get_announcement_task(task["id"])["status"] == "running"


def test_repeated_cancel_repairs_legacy_running_language_and_is_idempotent(tmp_path: Path) -> None:
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Legacy partial cancellation", "type": "QA"}).json()
        source = _create_announcement_source(project["id"], tmp_path)
        task = db.insert_announcement_task(
            project["id"],
            {
                "title": "partially canceled",
                "source_artifact_id": source["id"],
                "source_format": "txt",
                "selected_languages": ["en"],
                "status": "running",
                "current_step": 7,
            },
        )
        db.update_announcement_task(
            task["id"],
            status="canceled",
            current_step=7,
            metadata={"canceled_at": "2026-07-15T00:00:00+00:00"},
        )
        db.upsert_announcement_task_language(
            task["id"],
            project["id"],
            "en",
            status="running",
            current_step=7,
            metadata={"legacy_partial_cancel": True},
        )

        repaired = client.post(f"/api/announcement-tasks/{task['id']}/cancel")
        repeated = client.post(f"/api/announcement-tasks/{task['id']}/cancel")

        assert repaired.status_code == 200, repaired.text
        assert repeated.status_code == 200, repeated.text
        repaired_task = repaired.json()["task"]
        assert repaired_task["status"] == "canceled"
        assert repaired_task["languages"][0]["status"] == "canceled"
        assert repaired_task["languages"][0]["metadata"]["legacy_partial_cancel"] is True
        assert repaired_task["languages"][0]["metadata"]["canceled_at"] == repaired_task["metadata"]["canceled_at"]
        assert repeated.json()["task"] == repaired_task


@pytest.mark.parametrize("terminal_status", ["delivered", "canceled"])
def test_announcement_terminal_status_is_idempotent_and_rejects_late_updates(
    tmp_path: Path,
    terminal_status: str,
) -> None:
    project = db.insert_project(f"Announcement terminal {terminal_status}", "QA", "")
    source = _create_announcement_source(project["id"], tmp_path)
    task = db.insert_announcement_task(
        project["id"],
        {
            "title": terminal_status,
            "source_artifact_id": source["id"],
            "source_format": "txt",
            "selected_languages": ["en"],
            "status": "source_ready",
            "current_step": 2,
        },
    )
    terminal = db.update_announcement_task(
        task["id"],
        status=terminal_status,
        current_step=9,
        metadata={"terminal_marker": terminal_status},
    )
    terminal_language = db.upsert_announcement_task_language(
        task["id"],
        project["id"],
        "en",
        status=terminal_status,
        current_step=9,
        metadata={"terminal_marker": terminal_status},
    )

    late = db.update_announcement_task(
        task["id"],
        status="running",
        current_step=7,
        metadata={"late_worker_write": True},
    )
    late_language = db.upsert_announcement_task_language(
        task["id"],
        project["id"],
        "en",
        status="running",
        current_step=7,
        metadata={"late_worker_write": True},
    )

    assert late["status"] == terminal_status
    assert late["current_step"] == 9
    assert late["metadata"] == terminal["metadata"]
    assert late_language["status"] == terminal_status
    assert late_language["current_step"] == 9
    assert late_language["metadata"] == terminal_language["metadata"]
