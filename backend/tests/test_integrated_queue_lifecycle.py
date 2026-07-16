from __future__ import annotations

import importlib
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

import app.db as db
from app.schemas import AnnouncementTaskTranslateRequest, MultilingualQueueRequest


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


def test_announcement_staging_cannot_activate_terminal_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    queue = _queue()
    project = db.insert_project("Announcement terminal race", "QA", "")
    task = db.insert_announcement_task(
        project["id"],
        {
            "title": "terminal race",
            "selected_languages": ["en"],
            "status": "prepared",
            "current_step": 7,
        },
    )
    activated: list[str] = []
    real_enqueue = queue.enqueue_job

    def close_after_staging(**kwargs: Any) -> dict[str, Any]:
        queued = real_enqueue(**kwargs)
        assert queued["status"] == queue.STAGING_STATUS
        db.cancel_announcement_task(task["id"], db.now_iso())
        return queued

    def capture_activation(job_id: str, *, autostart: bool = True) -> dict[str, Any]:
        _ = autostart
        activated.append(job_id)
        queued = queue.get_job(job_id)
        assert queued is not None
        return queued

    monkeypatch.setattr(background_jobs.job_queue, "enqueue_job", close_after_staging)
    monkeypatch.setattr(background_jobs.job_queue, "activate_job", capture_activation)

    with pytest.raises(db.AnnouncementTaskStatusConflictError):
        background_jobs.start_announcement(
            task["id"],
            AnnouncementTaskTranslateRequest(languages=["en"], provider="test-fake"),
        )

    assert db.get_announcement_task(task["id"])["status"] == "canceled"
    assert activated == []
    queued = queue.get_job(f"announcement:{task['id']}")
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


def test_task_cancel_requires_cloud_operator_before_persisting_terminal_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    operator_context = importlib.import_module("app.operator_context")
    project = db.insert_project("Announcement cancel identity", "QA", "")
    task = db.insert_announcement_task(
        project["id"],
        {
            "title": "cancel identity",
            "selected_languages": ["en"],
            "status": "source_ready",
            "current_step": 2,
        },
    )
    signaled: list[str] = []

    def require_identity_after_signal(job_id: str) -> None:
        signaled.append(job_id)
        operator_context.require_operator_for_cloud()

    monkeypatch.setenv("LWS_DEPLOYMENT_MODE", "cloud")
    operator_context.set_current_operator("")
    monkeypatch.setattr(background_jobs, "_cancel", require_identity_after_signal)

    with pytest.raises(HTTPException) as exc_info:
        background_jobs.cancel_announcement_task(task["id"], ["source_ready", "failed"])

    assert exc_info.value.status_code == 400
    persisted = db.get_announcement_task(task["id"])
    assert persisted["status"] == "source_ready"
    assert "cancel_scope" not in persisted["metadata"]
    assert signaled == []


def test_task_cancel_cas_rejects_stale_status_without_signaling_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    project = db.insert_project("Announcement stale cancel CAS", "QA", "")
    task = db.insert_announcement_task(
        project["id"],
        {
            "title": "stale cancel CAS",
            "selected_languages": ["en"],
            "status": "running",
            "current_step": 7,
        },
    )
    signaled: list[str] = []
    monkeypatch.setattr(background_jobs, "_cancel", lambda job_id: signaled.append(job_id))

    with pytest.raises(db.AnnouncementTaskStatusConflictError):
        background_jobs.cancel_announcement_task(task["id"], ["source_ready", "failed"])

    persisted = db.get_announcement_task(task["id"])
    assert persisted["status"] == "running"
    assert "cancel_scope" not in persisted["metadata"]
    assert signaled == []


def test_repeated_announcement_cancel_preserves_first_terminal_audit() -> None:
    project = db.insert_project("Announcement cancel idempotency", "QA", "")
    task = db.insert_announcement_task(
        project["id"],
        {
            "title": "cancel idempotency",
            "selected_languages": ["en"],
            "status": "source_ready",
            "current_step": 2,
        },
    )
    first = db.cancel_announcement_task(
        task["id"],
        "2026-07-16T01:00:00+00:00",
        audit_patch={
            "cancel_scope": "task",
            "cancel_requested_at": "2026-07-16T01:00:00+00:00",
            "task_cancel_requested_at": "2026-07-16T01:00:00+00:00",
            "canceled_by": "Alice",
        },
    )
    repeated = db.cancel_announcement_task(
        task["id"],
        "2026-07-16T02:00:00+00:00",
        audit_patch={
            "cancel_scope": "task",
            "cancel_requested_at": "2026-07-16T02:00:00+00:00",
            "task_cancel_requested_at": "2026-07-16T02:00:00+00:00",
            "canceled_by": "Bob",
        },
    )

    assert repeated["metadata"] == first["metadata"]
    assert repeated["languages"] == first["languages"]
    assert repeated["metadata"]["canceled_by"] == "Alice"


def test_qa_handler_drops_failure_after_translation_task_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    workflow = importlib.import_module("app.workflow")
    project = db.insert_project("QA late terminal", "quick-task", "")
    task_id = "quick-task-qa-late-terminal"
    run = db.insert_run(
        project["id"],
        "qa",
        "en",
        metadata={"translation_task_id": task_id, "task_origin": "quick_task"},
    )
    snapshot: dict[str, Any] = {}

    def close_then_fail(*_args: Any, **_kwargs: Any) -> None:
        db.set_translation_task_terminal_state(project["id"], task_id, "canceled")
        snapshot.update(db.get_run(run["id"]))
        raise RuntimeError("late qa failure")

    monkeypatch.setattr(workflow, "run_qa_sync", close_then_fail)

    background_jobs._qa_handler(
        {
            "target_id": run["id"],
            "operator_name": "Alice",
            "payload": {},
        },
        threading.Event(),
    )

    persisted = db.get_run(run["id"])
    assert persisted["status"] == "canceled"
    assert persisted["metadata"] == snapshot["metadata"]


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_model_fix_handler_drops_result_after_translation_task_closes(
    outcome: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    workflow = importlib.import_module("app.workflow")
    project = db.insert_project(f"Model fix late terminal {outcome}", "quick-task", "")
    task_id = f"quick-task-model-late-{outcome}"
    run = db.insert_run(
        project["id"],
        "qa",
        "en",
        metadata={"translation_task_id": task_id, "task_origin": "quick_task"},
    )
    snapshot: dict[str, Any] = {}
    observed_cancel_event: list[threading.Event] = []

    def close_during_apply(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        observed_cancel_event.append(kwargs["cancel_event"])
        db.set_translation_task_terminal_state(project["id"], task_id, "canceled")
        snapshot.update(db.get_run(run["id"]))
        if outcome == "failure":
            raise RuntimeError("late model failure")
        return {"qa_result": {"run": {"status": "passed"}}, "model_fixes": [{}]}

    monkeypatch.setattr(workflow, "apply_model_fixes", close_during_apply)
    cancel_event = threading.Event()

    background_jobs._model_fix_handler(
        {
            "target_id": run["id"],
            "operator_name": "Alice",
            "payload": {"max_issues": 1, "rerun_qa": True},
        },
        cancel_event,
    )

    persisted = db.get_run(run["id"])
    assert observed_cancel_event == [cancel_event]
    assert persisted["status"] == "canceled"
    assert persisted["metadata"] == snapshot["metadata"]


def test_delete_project_removes_every_persistent_queue_row() -> None:
    queue = _queue()
    project = db.insert_project("Delete persistent queue rows", "QA", "")
    survivor = db.insert_project("Keep persistent queue rows", "QA", "")
    statuses = ["completed", "failed", "canceled", "interrupted"]
    for status in statuses:
        job_id = f"delete-{status}"
        queue.enqueue_job(
            job_id=job_id,
            lane="language_table",
            job_kind="translation",
            project_id=project["id"],
            target_id=job_id,
            payload={"secret": status},
            operator_name="Alice",
            autostart=False,
        )
        queue.set_job_status(job_id, status)
    queue.enqueue_job(
        job_id="delete-staged",
        lane="quick_announcement",
        job_kind="announcement",
        project_id=project["id"],
        target_id="announcement-secret",
        payload={"secret": "staged"},
        operator_name="Alice",
        autostart=False,
        staged=True,
    )
    queue.abandon_staged_job("delete-staged")
    queue.enqueue_job(
        job_id="survivor-completed",
        lane="language_table",
        job_kind="translation",
        project_id=survivor["id"],
        target_id="survivor",
        payload={},
        autostart=False,
    )
    queue.set_job_status("survivor-completed", "completed")

    db.delete_project(project["id"])

    assert all(row["project_id"] != project["id"] for row in queue.list_jobs())
    assert queue.get_job("survivor-completed") is not None


def test_delete_project_fails_closed_when_queue_lookup_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _queue()
    projects_router = importlib.import_module("app.routers.projects")
    project = db.insert_project("Delete queue lookup failure", "QA", "")
    monkeypatch.setattr(
        queue,
        "active_job_for_project",
        lambda _project_id: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")),
    )

    with pytest.raises(HTTPException) as exc_info:
        projects_router.delete_project(project["id"])

    assert exc_info.value.status_code == 503
    assert db.get_project(project["id"])["id"] == project["id"]


def test_delete_project_rechecks_queue_when_enqueue_wins_after_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _queue()
    projects_router = importlib.import_module("app.routers.projects")
    project = db.insert_project("Delete versus late enqueue", "QA", "")
    preflight_reached = threading.Event()
    enqueue_finished = threading.Event()
    worker_errors: list[BaseException] = []

    def enqueue_after_preflight() -> None:
        try:
            assert preflight_reached.wait(2.0)
            queue.enqueue_job(
                job_id="late-enqueue",
                lane="language_table",
                job_kind="translation",
                project_id=project["id"],
                target_id="late-run",
                payload={},
                autostart=False,
            )
        except BaseException as exc:  # pragma: no cover - asserted in parent thread
            worker_errors.append(exc)
        finally:
            enqueue_finished.set()

    def stale_preflight(_project_id: str) -> None:
        preflight_reached.set()
        assert enqueue_finished.wait(2.0)
        return None

    worker = threading.Thread(target=enqueue_after_preflight)
    worker.start()
    monkeypatch.setattr(projects_router, "active_job_id_for_project", stale_preflight)

    with pytest.raises(HTTPException) as exc_info:
        projects_router.delete_project(project["id"])

    worker.join(2.0)
    assert not worker.is_alive()
    assert worker_errors == []
    assert exc_info.value.status_code == 409
    assert db.get_project(project["id"])["id"] == project["id"]
    assert queue.get_job("late-enqueue")["status"] == "queued"


def test_delete_project_rechecks_queue_when_claim_wins_after_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = _queue()
    projects_router = importlib.import_module("app.routers.projects")
    project = db.insert_project("Delete versus late claim", "QA", "")
    queue.enqueue_job(
        job_id="late-claim",
        lane="quick_announcement",
        job_kind="qa",
        project_id=project["id"],
        target_id="late-run",
        payload={},
        autostart=False,
    )
    preflight_reached = threading.Event()
    claim_finished = threading.Event()
    claimed: list[dict[str, Any] | None] = []
    worker_errors: list[BaseException] = []

    def claim_after_preflight() -> None:
        try:
            assert preflight_reached.wait(2.0)
            claimed.append(queue.claim_next_job("quick_announcement"))
        except BaseException as exc:  # pragma: no cover - asserted in parent thread
            worker_errors.append(exc)
        finally:
            claim_finished.set()

    def stale_preflight(_project_id: str) -> None:
        preflight_reached.set()
        assert claim_finished.wait(2.0)
        return None

    worker = threading.Thread(target=claim_after_preflight)
    worker.start()
    monkeypatch.setattr(projects_router, "active_job_id_for_project", stale_preflight)

    with pytest.raises(HTTPException) as exc_info:
        projects_router.delete_project(project["id"])

    worker.join(2.0)
    assert not worker.is_alive()
    assert worker_errors == []
    assert claimed and claimed[0] is not None
    assert claimed[0]["job_id"] == "late-claim"
    assert exc_info.value.status_code == 409
    assert db.get_project(project["id"])["id"] == project["id"]
    assert queue.get_job("late-claim")["status"] == "running"


def test_delete_project_fails_closed_when_legacy_lease_lookup_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_router = importlib.import_module("app.routers.projects")
    project = db.insert_project("Delete legacy lease lookup failure", "QA", "")
    monkeypatch.setattr(
        db,
        "get_job_lease",
        lambda _lease_name: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")),
    )

    with pytest.raises(HTTPException) as exc_info:
        projects_router.delete_project(project["id"])

    assert exc_info.value.status_code == 503
    assert db.get_project(project["id"])["id"] == project["id"]


def test_queue_and_legacy_lease_reject_project_marked_deleting() -> None:
    queue = _queue()
    project = db.insert_project("Reject work while deleting", "QA", "")
    queue.enqueue_job(
        job_id="deleting-staged",
        lane="language_table",
        job_kind="translation",
        project_id=project["id"],
        target_id="staged-run",
        payload={},
        autostart=False,
        staged=True,
    )
    queue.enqueue_job(
        job_id="deleting-queued",
        lane="quick_announcement",
        job_kind="qa",
        project_id=project["id"],
        target_id="queued-run",
        payload={},
        autostart=False,
    )
    with db.connect() as conn:
        conn.execute(
            "UPDATE projects SET lifecycle_state = 'deleting' WHERE id = ?",
            (project["id"],),
        )

    with pytest.raises(db.ProjectNotActiveError):
        queue.enqueue_job(
            job_id="deleting-new",
            lane="language_table",
            job_kind="translation",
            project_id=project["id"],
            target_id="new-run",
            payload={},
            autostart=False,
        )
    with pytest.raises(db.ProjectNotActiveError):
        queue.activate_job("deleting-staged", autostart=False)
    assert queue.claim_next_job("quick_announcement") is None
    assert not db.acquire_job_lease(f"long_text:{project['id']}", "legacy-after-delete")


def test_delete_project_rolls_back_state_and_cascade_when_cleanup_fails() -> None:
    queue = _queue()
    project = db.insert_project("Rollback failed project cascade", "QA", "")
    run = db.insert_run(project["id"], "translation", "en", metadata={})
    queue.enqueue_job(
        job_id="rollback-terminal-job",
        lane="language_table",
        job_kind="translation",
        project_id=project["id"],
        target_id=run["id"],
        payload={},
        autostart=False,
        staged=True,
    )
    queue.abandon_staged_job("rollback-terminal-job")
    with db.connect() as conn:
        conn.execute(
            f"""
            CREATE TRIGGER block_project_run_delete
            BEFORE DELETE ON runs
            WHEN OLD.project_id = '{project['id']}'
            BEGIN
              SELECT RAISE(ABORT, 'blocked project cascade');
            END
            """
        )

    with pytest.raises(sqlite3.DatabaseError, match="blocked project cascade"):
        db.delete_project(project["id"])

    assert db.get_project(project["id"])["id"] == project["id"]
    assert db.get_run(run["id"])["id"] == run["id"]
    assert queue.get_job("rollback-terminal-job")["status"] == "failed"
    with db.connect() as conn:
        state = conn.execute(
            "SELECT lifecycle_state FROM projects WHERE id = ?",
            (project["id"],),
        ).fetchone()["lifecycle_state"]
    assert state == "active"


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


def test_prefix_only_quick_task_uses_quick_lane_and_closes_on_restart_cancel() -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    queue = _queue()
    project = db.insert_project("prefix-only quick restart cancel", "QA", "")
    task_id = "quick-task-prefix-only-restart"
    run = db.insert_run(project["id"], "qa", "en", metadata={"translation_task_id": task_id})
    sibling = db.insert_run(project["id"], "translation", "ko", metadata={"translation_task_id": task_id})
    db.update_run(run["id"], status="running")
    assert background_jobs.lane_for_run(run, "qa") == "quick_announcement"
    assert background_jobs.lane_for_run(run, "model_fix") == "quick_announcement"
    job_id = f"qa:{run['id']}"
    queue.enqueue_job(
        job_id=job_id,
        lane="quick_announcement",
        job_kind="qa",
        project_id=project["id"],
        target_id=run["id"],
        payload={},
        autostart=False,
    )
    assert queue.claim_next_job("quick_announcement")["job_id"] == job_id
    queue.cancel_job(job_id, canceled_by="Alice")

    background_jobs.reconcile_startup(queue.recover_interrupted_jobs())

    stored = db.get_run(run["id"])
    stored_sibling = db.get_run(sibling["id"])
    assert stored["status"] == "canceled"
    assert stored["metadata"]["translation_task_state"] == "canceled"
    assert stored_sibling["status"] == "canceled"
    assert stored_sibling["metadata"]["translation_task_state"] == "canceled"


@pytest.mark.parametrize(
    ("handler_name", "origin", "task_should_close"),
    [("_qa_handler", "translation_run", False), ("_model_fix_handler", "translation_run", False), ("_qa_handler", "quick_task", True)],
)
def test_cancel_before_work_uses_task_origin_scope(
    handler_name: str,
    origin: str,
    task_should_close: bool,
) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    project = db.insert_project(f"cancel before work {handler_name} {origin}", "QA", "")
    task_id = f"task-cancel-before-work-{handler_name}-{origin}"
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
    db.update_run(run["id"], status="queued")
    cancel_event = threading.Event()
    cancel_event.set()

    getattr(background_jobs, handler_name)(
        {"target_id": run["id"], "operator_name": "Alice", "payload": {}},
        cancel_event,
    )

    stored = db.get_run(run["id"])
    stored_sibling = db.get_run(sibling["id"])
    assert stored["status"] == "canceled"
    if task_should_close:
        assert stored["metadata"]["translation_task_state"] == "canceled"
        assert stored_sibling["status"] == "canceled"
    else:
        assert not stored["metadata"].get("translation_task_state")
        assert stored_sibling["status"] == "created"


@pytest.mark.parametrize(
    ("origin", "task_should_close"),
    [("translation_run", False), ("quick_task", True)],
)
def test_generic_queued_cancel_uses_task_origin_scope(origin: str, task_should_close: bool) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    queue = _queue()
    project = db.insert_project(f"generic queued cancel {origin}", "QA", "")
    task_id = f"task-generic-queued-cancel-{origin}"
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
    db.update_run(run["id"], status="queued")
    job_id = f"qa:{run['id']}"
    queue.enqueue_job(
        job_id=job_id,
        lane="quick_announcement" if origin == "quick_task" else "language_table",
        job_kind="qa",
        project_id=project["id"],
        target_id=run["id"],
        payload={},
        autostart=False,
    )

    result = background_jobs.cancel(job_id)

    assert result is not None
    stored = db.get_run(run["id"])
    stored_sibling = db.get_run(sibling["id"])
    assert stored["status"] == "canceled"
    if task_should_close:
        assert stored["metadata"]["translation_task_state"] == "canceled"
        assert stored_sibling["status"] == "canceled"
    else:
        assert not stored["metadata"].get("translation_task_state")
        assert stored_sibling["status"] == "created"


@pytest.mark.parametrize(
    ("origin", "task_should_close"),
    [("translation_run", False), ("quick_task", True)],
)
def test_generic_running_cancel_closes_only_quick_scope(origin: str, task_should_close: bool) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    queue = _queue()
    project = db.insert_project(f"generic running cancel {origin}", "QA", "")
    task_id = f"task-generic-running-cancel-{origin}"
    run = db.insert_run(
        project["id"],
        "translation",
        "en",
        metadata={"translation_task_id": task_id, "task_origin": origin},
    )
    sibling = db.insert_run(
        project["id"],
        "qa",
        "ko",
        metadata={"translation_task_id": task_id, "task_origin": origin},
    )
    db.update_run(run["id"], status="running")
    job_id = f"run:{run['id']}"
    lane = "quick_announcement" if origin == "quick_task" else "language_table"
    queue.enqueue_job(
        job_id=job_id,
        lane=lane,
        job_kind="translation",
        project_id=project["id"],
        target_id=run["id"],
        payload={},
        autostart=False,
    )
    assert queue.claim_next_job(lane)["job_id"] == job_id

    result = background_jobs.cancel(job_id)

    assert result is not None
    assert result["queue_job"]["cancel_requested"] is True
    stored = db.get_run(run["id"])
    stored_sibling = db.get_run(sibling["id"])
    if task_should_close:
        assert stored["status"] == "canceled"
        assert stored["metadata"]["translation_task_state"] == "canceled"
        assert stored_sibling["status"] == "canceled"
    else:
        assert stored["status"] == "running"
        assert not stored["metadata"].get("translation_task_state")
        assert stored_sibling["status"] == "created"


@pytest.mark.parametrize(
    ("origin", "task_should_close"),
    [("translation_run", False), ("quick_task", True)],
)
def test_running_qa_cancel_boundary_uses_task_origin_scope(
    monkeypatch: pytest.MonkeyPatch,
    origin: str,
    task_should_close: bool,
) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    workflow = importlib.import_module("app.workflow")
    project = db.insert_project(f"running QA cancel boundary {origin}", "QA", "")
    task_id = f"task-running-qa-cancel-{origin}"
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
    cancel_event = threading.Event()

    def cancel_during_qa(*_args: Any, **_kwargs: Any) -> None:
        cancel_event.set()
        raise workflow.QaCanceled("QA canceled")

    monkeypatch.setattr(workflow, "run_qa_sync", cancel_during_qa)

    background_jobs._qa_handler(
        {"target_id": run["id"], "operator_name": "Alice", "payload": {}},
        cancel_event,
    )

    stored = db.get_run(run["id"])
    stored_sibling = db.get_run(sibling["id"])
    assert stored["status"] == "canceled"
    if task_should_close:
        assert stored["metadata"]["translation_task_state"] == "canceled"
        assert stored_sibling["status"] == "canceled"
    else:
        assert not stored["metadata"].get("translation_task_state")
        assert stored_sibling["status"] == "created"


@pytest.mark.parametrize(
    ("origin", "task_should_close"),
    [("translation_run", False), ("quick_task", True)],
)
def test_running_qa_late_cancel_after_workflow_return_uses_task_origin_scope(
    monkeypatch: pytest.MonkeyPatch,
    origin: str,
    task_should_close: bool,
) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    workflow = importlib.import_module("app.workflow")
    project = db.insert_project(f"late QA cancel {origin}", "QA", "")
    task_id = f"task-late-qa-cancel-{origin}"
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
    cancel_event = threading.Event()

    def finish_after_cancel(*_args: Any, **_kwargs: Any) -> None:
        cancel_event.set()
        db.update_run_if_task_open(run["id"], status="passed")

    monkeypatch.setattr(workflow, "run_qa_sync", finish_after_cancel)

    background_jobs._qa_handler(
        {"target_id": run["id"], "operator_name": "Alice", "payload": {}},
        cancel_event,
    )

    stored = db.get_run(run["id"])
    stored_sibling = db.get_run(sibling["id"])
    assert stored["status"] == "canceled"
    if task_should_close:
        assert stored["metadata"]["translation_task_state"] == "canceled"
        assert stored_sibling["status"] == "canceled"
    else:
        assert not stored["metadata"].get("translation_task_state")
        assert stored_sibling["status"] == "created"


@pytest.mark.parametrize(
    ("origin", "task_should_close"),
    [("translation_run", False), ("quick_task", True)],
)
def test_running_model_fix_late_cancel_uses_task_origin_scope(
    monkeypatch: pytest.MonkeyPatch,
    origin: str,
    task_should_close: bool,
) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    workflow = importlib.import_module("app.workflow")
    project = db.insert_project(f"late model-fix cancel {origin}", "QA", "")
    task_id = f"task-late-model-fix-cancel-{origin}"
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
    db.update_run(run["id"], status="failed")
    cancel_event = threading.Event()

    class CancelOnQaResult(dict[str, Any]):
        def get(self, key: str, default: Any = None) -> Any:
            if key == "qa_result":
                cancel_event.set()
            return super().get(key, default)

    monkeypatch.setattr(
        workflow,
        "apply_model_fixes",
        lambda *_args, **_kwargs: CancelOnQaResult(
            {"qa_result": {"run": {"id": run["id"], "status": "passed"}}, "model_fixes": []}
        ),
    )

    background_jobs._model_fix_handler(
        {"target_id": run["id"], "operator_name": "Alice", "payload": {}},
        cancel_event,
    )

    stored = db.get_run(run["id"])
    stored_sibling = db.get_run(sibling["id"])
    assert stored["status"] == "canceled"
    if task_should_close:
        assert stored["metadata"]["translation_task_state"] == "canceled"
        assert stored_sibling["status"] == "canceled"
    else:
        assert not stored["metadata"].get("translation_task_state")
        assert stored_sibling["status"] == "created"


@pytest.mark.parametrize("old_status", ["canceled", "interrupted"])
def test_restart_ignores_stale_terminal_tombstone_when_same_run_has_newer_job(old_status: str) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    queue = _queue()
    project = db.insert_project(f"stale {old_status} tombstone", "QA", "")
    task_id = f"task-stale-{old_status}-tombstone"
    run = db.insert_run(
        project["id"],
        "qa",
        "en",
        metadata={"translation_task_id": task_id, "task_origin": "translation_run"},
    )
    old_job_id = f"model-fix:{run['id']}"
    queue.enqueue_job(
        job_id=old_job_id,
        lane="language_table",
        job_kind="model_fix",
        project_id=project["id"],
        target_id=run["id"],
        payload={},
        autostart=False,
    )
    if old_status == "canceled":
        queue.cancel_job(old_job_id, canceled_by="Alice")
    else:
        assert queue.claim_next_job("language_table")["job_id"] == old_job_id
        queue.recover_interrupted_jobs()

    db.update_run(run["id"], status="queued")
    new_job_id = f"qa:{run['id']}"
    queue.enqueue_job(
        job_id=new_job_id,
        lane="language_table",
        job_kind="qa",
        project_id=project["id"],
        target_id=run["id"],
        payload={},
        autostart=False,
    )
    assert queue.claim_next_job("language_table")["job_id"] == new_job_id

    background_jobs.reconcile_startup(queue.recover_interrupted_jobs())

    stored = db.get_run(run["id"])
    assert stored["status"] == "needs_input"
    assert not stored["metadata"].get("translation_task_state")
    assert queue.get_job(old_job_id)["status"] == old_status
    assert queue.get_job(new_job_id)["status"] == "interrupted"


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


def test_announcement_provider_result_after_cancel_creates_no_response_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    announcement = importlib.import_module("app.workflow.announcement")
    background_jobs = importlib.import_module("app.background_jobs")
    project = db.insert_project("Announcement late provider", "QA", "")
    source_path = tmp_path / "announcement.txt"
    source_path.write_text("Maintenance", encoding="utf-8")
    source = db.add_artifact(project["id"], source_path.name, source_path, "asset", mime="text/plain")
    task = db.insert_announcement_task(
        project["id"],
        {
            "title": "late provider",
            "source_artifact_id": source["id"],
            "source_format": "txt",
            "selected_languages": ["en"],
            "status": "prepared",
            "current_step": 7,
        },
    )
    workbook_path = tmp_path / "announcement_translation.xlsx"
    workbook_path.write_bytes(b"unchanged workbook")
    workbook = db.add_artifact(
        project["id"],
        workbook_path.name,
        workbook_path,
        "announcement_translation_workbook",
    )
    workpack_path = tmp_path / "announcement_workpack_en.jsonl"
    workpack_path.write_text('{"id":"row-1","source":"Maintenance","term_hits":[]}\n', encoding="utf-8")
    workpack = db.add_artifact(
        project["id"],
        workpack_path.name,
        workpack_path,
        "announcement_workpack",
        mime="application/jsonl",
    )
    db.update_announcement_task(
        task["id"],
        status="prepared",
        current_step=7,
        metadata={
            "translation_workbook_artifact_id": workbook["id"],
            "workpack_artifact_ids": {"en": workpack["id"]},
        },
    )
    db.upsert_announcement_task_language(
        task["id"],
        project["id"],
        "en",
        status="prepared",
        current_step=7,
    )
    cancel_event = threading.Event()

    async def provider_returns_after_cancel(**_kwargs: Any) -> list[dict[str, str]]:
        cancel_event.set()
        db.cancel_announcement_task(task["id"], db.now_iso())
        return [{"id": "row-1", "translation": "Maintenance"}]

    monkeypatch.setattr(announcement, "_translate_rows_with_orchestration", provider_returns_after_cancel)
    monkeypatch.setattr(announcement, "run_dir", lambda _run_id: tmp_path / "runs")
    workbook_before = workbook_path.read_bytes()

    background_jobs._announcement_handler(
        {
            "target_id": task["id"],
            "operator_name": "Alice",
            "payload": AnnouncementTaskTranslateRequest(
                languages=["en"],
                provider="test-fake",
            ).model_dump(exclude_none=True),
        },
        cancel_event,
    )

    persisted_task = db.get_announcement_task(task["id"])
    assert persisted_task["status"] == "canceled"
    translate_run = db.get_run(persisted_task["metadata"]["translate_run_id"])
    assert translate_run["status"] == "canceled"
    assert workbook_path.read_bytes() == workbook_before
    assert not [
        artifact
        for artifact in db.list_artifacts(project["id"])
        if artifact["kind"] == "announcement_ai_response"
    ]


def test_startup_reconcile_does_not_revive_terminal_multilingual_child() -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    queue = _queue()
    project = db.insert_project("Multilingual terminal startup", "QA", "")
    task_id = "task-multilingual-terminal-startup"
    child = db.insert_run(
        project["id"],
        "translation",
        "en",
        metadata={"translation_task_id": task_id, "task_origin": "translation_run"},
    )
    db.update_run(child["id"], status="passed")
    db.set_translation_task_terminal_state(project["id"], task_id, "delivered")
    db.update_run(child["id"], status="created")
    job_id = f"multilingual:translate:{project['id']}:source:{task_id}"
    queue.enqueue_job(
        job_id=job_id,
        lane="language_table",
        job_kind="multilingual_translate",
        project_id=project["id"],
        target_id="source",
        payload={
            "request": {
                "input_artifact_id": "source",
                "languages": ["en"],
                "translation_task_id": task_id,
            },
            "child_run_ids": [child["id"]],
        },
        operator_name="Alice",
        autostart=False,
    )

    summary = background_jobs.reconcile_startup([])

    persisted = db.get_run(child["id"])
    assert persisted["status"] == "canceled"
    assert persisted["metadata"]["translation_task_state"] == "delivered"
    assert "queued_at" not in persisted["metadata"]
    assert queue.get_job(job_id)["status"] == "completed"
    assert summary["terminal_queue_rows_cleaned"] == 1
