from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

import app.db as db
from app.schemas import MultilingualQueueRequest


def _queue():
    return importlib.import_module("app.job_queue")


@pytest.fixture(autouse=True)
def isolated_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    queue = _queue()
    queue.shutdown_dispatchers(timeout=2.0, cancel_running=True)
    queue.clear_handlers()
    queue.reset_dispatcher_state()
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "integrated-queue.sqlite3")
    db.init_db()

    from app import operator_context

    previous_operator = operator_context.current_operator()
    operator_context.set_current_operator("Alice")
    yield
    operator_context.set_current_operator(previous_operator)
    queue.shutdown_dispatchers(timeout=2.0, cancel_running=True)
    queue.clear_handlers()
    queue.reset_dispatcher_state()


def test_multilingual_staging_cannot_requeue_terminal_task_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    queue = _queue()
    project = db.insert_project("Multilingual terminal race", "QA", "")
    task_id = "task-multilingual-terminal"
    child = db.insert_run(
        project["id"],
        "translation",
        "en",
        metadata={"translation_task_id": task_id, "task_origin": "translation_run"},
    )
    activated: list[str] = []
    real_enqueue = queue.enqueue_job

    def close_after_staging(**kwargs: Any) -> dict[str, Any]:
        queued = real_enqueue(**kwargs)
        assert queued["status"] == queue.STAGING_STATUS
        db.set_translation_task_terminal_state(project["id"], task_id, "canceled")
        return queued

    def capture_activation(job_id: str, *, autostart: bool = True) -> dict[str, Any]:
        _ = autostart
        activated.append(job_id)
        queued = queue.get_job(job_id)
        assert queued is not None
        return queued

    monkeypatch.setattr(background_jobs.job_queue, "enqueue_job", close_after_staging)
    monkeypatch.setattr(background_jobs.job_queue, "activate_job", capture_activation)
    request = MultilingualQueueRequest(
        input_artifact_id="source-artifact",
        languages=["en"],
        translation_task_id=task_id,
    )

    with pytest.raises(db.TranslationTaskClosedError):
        background_jobs.start_multilingual(
            "multilingual_translate",
            project["id"],
            "source-artifact",
            request,
            [child["id"]],
        )

    refreshed = db.get_run(child["id"])
    assert refreshed["status"] == "canceled"
    assert refreshed["metadata"]["translation_task_state"] == "canceled"
    assert activated == []
    job_id = f"multilingual:translate:{project['id']}:source-artifact:{task_id}"
    queued = queue.get_job(job_id)
    assert queued is None or queued["status"] not in {queue.STAGING_STATUS, "queued", "running"}


def test_task_cancel_cas_persists_audit_before_signaling_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    project = db.insert_project("Announcement cancel CAS", "QA", "")
    task = db.insert_announcement_task(
        project["id"],
        {
            "title": "cancel CAS",
            "selected_languages": ["en"],
            "status": "source_ready",
            "current_step": 2,
        },
    )
    observed: dict[str, Any] = {}

    def capture_cancel(job_id: str) -> None:
        observed["job_id"] = job_id
        observed["task"] = db.get_announcement_task(task["id"])
        return None

    monkeypatch.setattr(background_jobs, "_cancel", capture_cancel)

    result = background_jobs.cancel_announcement_task(task["id"], ["source_ready", "failed"])

    assert observed["job_id"] == f"announcement:{task['id']}"
    persisted_at_signal = observed["task"]
    assert persisted_at_signal["status"] == "canceled"
    assert persisted_at_signal["metadata"]["cancel_scope"] == "task"
    assert persisted_at_signal["metadata"]["canceled_by"] == "Alice"
    assert persisted_at_signal["metadata"]["cancel_requested_at"]
    assert persisted_at_signal["metadata"]["task_cancel_requested_at"]
    assert persisted_at_signal["metadata"]["canceled_at"]
    assert result["task"]["status"] == "canceled"


def test_restart_recovers_cancel_requested_running_job_as_canceled() -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    queue = _queue()
    project = db.insert_project("Restart cancel requested", "quick-task", "")
    task_id = "quick-task-restart-cancel"
    run = db.insert_run(
        project["id"],
        "qa",
        "en",
        metadata={"translation_task_id": task_id, "task_origin": "quick_task"},
    )
    db.update_run(run["id"], status="running")
    job_id = f"qa:{run['id']}"
    queue.enqueue_job(
        job_id=job_id,
        lane="quick_announcement",
        job_kind="qa",
        project_id=project["id"],
        target_id=run["id"],
        payload={},
        operator_name="Alice",
        autostart=False,
    )
    assert queue.claim_next_job("quick_announcement")["job_id"] == job_id
    requested = queue.cancel_job(job_id, canceled_by="Alice")
    assert requested is not None
    assert requested["status"] == "running"
    assert requested["cancel_requested"] is True

    recovered = queue.recover_interrupted_jobs()
    summary = background_jobs.reconcile_startup(recovered)

    queue_row = queue.get_job(job_id)
    assert queue_row is not None
    assert queue_row["status"] == "canceled"
    assert queue_row["canceled_by"] == "Alice"
    assert queue_row["cancel_requested_at"] == requested["cancel_requested_at"]
    assert queue_row["canceled_at"]
    persisted = db.get_run(run["id"])
    assert persisted["status"] == "canceled"
    assert persisted["metadata"]["translation_task_state"] == "canceled"
    assert persisted["metadata"]["canceled_by"] == "Alice"
    assert persisted["metadata"]["cancel_requested_at"] == requested["cancel_requested_at"]
    assert persisted["metadata"]["canceled_at"] == queue_row["canceled_at"]
    assert summary["recovered_canceled_jobs"] == 1


@pytest.mark.parametrize(
    ("origin", "task_should_close"),
    [("translation_run", False), ("quick_task", True)],
)
def test_restart_cancel_preserves_formal_scope_and_closes_quick_scope(
    origin: str,
    task_should_close: bool,
) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    queue = _queue()
    project = db.insert_project(f"restart cancel scope {origin}", "QA", "")
    task_id = f"task-restart-cancel-{origin}"
    run = db.insert_run(
        project["id"],
        "qa",
        "en",
        metadata={"translation_task_id": task_id, "task_origin": origin},
    )
    sibling = db.insert_run(
        project["id"],
        "translation",
        "ko",
        metadata={"translation_task_id": task_id, "task_origin": origin},
    )
    db.update_run(run["id"], status="running")
    job_id = f"qa:{run['id']}"
    lane = "quick_announcement" if origin == "quick_task" else "language_table"
    queue.enqueue_job(
        job_id=job_id,
        lane=lane,
        job_kind="qa",
        project_id=project["id"],
        target_id=run["id"],
        payload={},
        autostart=False,
    )
    assert queue.claim_next_job(lane)["job_id"] == job_id
    queue.cancel_job(job_id, canceled_by="Alice")

    background_jobs.reconcile_startup(queue.recover_interrupted_jobs())

    stored = db.get_run(run["id"])
    stored_sibling = db.get_run(sibling["id"])
    assert stored["status"] == "canceled"
    if task_should_close:
        assert stored["metadata"]["translation_task_state"] == "canceled"
        assert stored_sibling["status"] == "canceled"
        assert stored_sibling["metadata"]["translation_task_state"] == "canceled"
    else:
        assert not stored["metadata"].get("translation_task_state")
        assert stored_sibling["status"] == "created"
        assert not stored_sibling["metadata"].get("translation_task_state")


def test_restart_does_not_reopen_terminal_task_from_interrupted_row() -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    queue = _queue()
    project = db.insert_project("Restart terminal interrupted", "QA", "")
    task_id = "task-restart-terminal-interrupted"
    run = db.insert_run(
        project["id"],
        "translation",
        "en",
        metadata={"translation_task_id": task_id, "task_origin": "translation_run"},
    )
    db.update_run(run["id"], status="passed")
    db.set_translation_task_terminal_state(project["id"], task_id, "delivered")
    db.update_run(run["id"], status="running")
    job_id = f"run:{run['id']}"
    queue.enqueue_job(
        job_id=job_id,
        lane="language_table",
        job_kind="translation",
        project_id=project["id"],
        target_id=run["id"],
        payload={},
        operator_name="Alice",
        autostart=False,
    )
    assert queue.claim_next_job("language_table")["job_id"] == job_id

    summary = background_jobs.reconcile_startup(queue.recover_interrupted_jobs())

    persisted = db.get_run(run["id"])
    assert persisted["status"] == "canceled"
    assert persisted["metadata"]["translation_task_state"] == "delivered"
    assert "interrupted_at" not in persisted["metadata"]
    assert "reason" not in persisted["metadata"]
    assert queue.get_job(job_id)["status"] == "completed"
    assert summary["interrupted_runs"] == 0
