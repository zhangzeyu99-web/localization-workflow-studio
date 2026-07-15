from __future__ import annotations

import importlib
import json
import logging
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import pytest

import app.db as db


def _queue():
    return importlib.import_module("app.job_queue")


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "condition was not met before timeout"


@pytest.fixture(autouse=True)
def isolated_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    try:
        queue = _queue()
    except ModuleNotFoundError:
        queue = None
    if queue is not None:
        queue.shutdown_dispatchers(timeout=2.0, cancel_running=True)
        queue.clear_handlers()
        queue.reset_dispatcher_state()

    database = tmp_path / "job-queue.sqlite3"
    monkeypatch.setattr(db, "DB_PATH", database)
    db.init_db()
    yield

    try:
        queue = _queue()
    except ModuleNotFoundError:
        return
    queue.shutdown_dispatchers(timeout=2.0, cancel_running=True)
    queue.clear_handlers()
    queue.reset_dispatcher_state()


def _enqueue(
    job_id: str,
    *,
    lane: str = "language_table",
    job_kind: str = "translate",
    project_id: str = "project-a",
    target_id: str | None = None,
    payload: dict[str, Any] | None = None,
    autostart: bool = True,
    staged: bool = False,
):
    return _queue().enqueue_job(
        job_id=job_id,
        lane=lane,
        job_kind=job_kind,
        project_id=project_id,
        target_id=target_id or job_id,
        payload=payload or {},
        operator_name="Alice",
        autostart=autostart,
        staged=staged,
    )


def test_new_runs_are_created_and_same_kind_does_not_block_creation() -> None:
    project = db.insert_project("created run queue contract", "QA", "")

    first = db.insert_run(project["id"], "translation", "en", metadata={})
    second = db.insert_run(project["id"], "translation", "ko", metadata={})

    assert first["status"] == "created"
    assert second["status"] == "created"


def test_business_lane_classification_uses_quick_origin_only_for_translation_and_qa() -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    quick_run = {"metadata": {"task_origin": "quick_task"}}
    formal_run = {"metadata": {"task_origin": "translation_run"}}

    assert background_jobs.lane_for_run(quick_run, "translation") == "quick_announcement"
    assert background_jobs.lane_for_run(quick_run, "qa") == "quick_announcement"
    assert background_jobs.lane_for_run(formal_run, "translation") == "language_table"
    assert background_jobs.lane_for_job("announcement") == "quick_announcement"
    assert background_jobs.lane_for_job("model_fix") == "language_table"
    assert background_jobs.lane_for_job("multilingual_translate") == "language_table"


def test_translation_enqueue_failure_does_not_leave_false_queued_state(monkeypatch: pytest.MonkeyPatch) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    project = db.insert_project("enqueue rollback", "QA", "")
    run = db.insert_run(project["id"], "translation", "en", metadata={"task_origin": "translation_run"})
    monkeypatch.setattr(background_jobs.job_queue, "enqueue_job", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("disk full")))

    with pytest.raises(RuntimeError, match="disk full"):
        background_jobs.start_translation(run["id"], {"batch_size": 8})

    stored = db.get_run(run["id"])
    assert stored["status"] == "created"
    assert "queued_at" not in stored["metadata"]


def test_qa_handler_loads_settings_after_dispatch_and_restores_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    from app import operator_context
    from app.config import DEFAULT_SETTINGS, save_settings
    import app.workflow as workflow

    queue = _queue()
    release = threading.Event()
    blocker_started = threading.Event()
    observed: dict[str, Any] = {}

    def blocker(record: dict[str, Any], cancel_event: threading.Event) -> None:
        _ = record, cancel_event
        blocker_started.set()
        release.wait(2.0)

    def fake_qa(run_id: str, *, settings: dict[str, Any], cancel_event: threading.Event) -> dict[str, Any]:
        observed.update(run_id=run_id, model=settings["model"], operator=operator_context.current_operator())
        db.update_run(run_id, status="passed")
        return {"run": db.get_run(run_id)}

    background_jobs.register_handlers()
    queue.register_handler("blocker", blocker)
    _enqueue("settings-blocker", job_kind="blocker")
    assert blocker_started.wait(2.0)

    project = db.insert_project("runtime settings", "QA", "")
    run = db.insert_run(project["id"], "qa", "en", metadata={"task_origin": "direct_import"})
    monkeypatch.setattr(workflow, "run_qa_sync", fake_qa)
    save_settings({**DEFAULT_SETTINGS, "provider": "test-fake", "model": "before-enqueue"})
    operator_context.set_current_operator("Alice")
    queued = background_jobs.start_qa(run["id"])
    assert queued["status"] == "queued"
    assert queue.get_job(f"qa:{run['id']}")["payload"] == {}

    save_settings({**DEFAULT_SETTINGS, "provider": "test-fake", "model": "after-enqueue"})
    release.set()
    _wait_until(lambda: queue.get_job(f"qa:{run['id']}")["status"] == "completed")

    assert observed == {"run_id": run["id"], "model": "after-enqueue", "operator": "Alice"}


def test_business_adapter_registers_all_six_handlers_idempotently() -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    queue = _queue()

    background_jobs.register_handlers()
    first = dict(queue._HANDLERS)
    background_jobs.register_handlers()

    assert set(queue._HANDLERS) == {
        "translation",
        "qa",
        "model_fix",
        "announcement",
        "multilingual_translate",
        "multilingual_qa",
    }
    assert queue._HANDLERS == first


def test_model_fix_handler_reads_settings_only_when_dispatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    from app.config import DEFAULT_SETTINGS, save_settings
    import app.workflow as workflow

    queue = _queue()
    release = threading.Event()
    blocker_started = threading.Event()
    observed: dict[str, Any] = {}

    def blocker(record: dict[str, Any], cancel_event: threading.Event) -> None:
        _ = record, cancel_event
        blocker_started.set()
        release.wait(2.0)

    def fake_apply(run_id: str, payload: object, *, settings: dict[str, Any]) -> dict[str, Any]:
        _ = payload
        observed.update(run_id=run_id, model=settings["model"])
        return {"model_fixes": [], "qa_result": {"run": {"id": run_id, "status": "passed"}}}

    background_jobs.register_handlers()
    queue.register_handler("blocker", blocker)
    _enqueue("model-settings-blocker", job_kind="blocker")
    assert blocker_started.wait(2.0)

    project = db.insert_project("model fix runtime settings", "QA", "")
    run = db.insert_run(project["id"], "qa", "en", metadata={})
    db.update_run(run["id"], status="failed")
    monkeypatch.setattr(workflow, "apply_model_fixes", fake_apply)
    save_settings({**DEFAULT_SETTINGS, "provider": "test-fake", "model": "before-model-fix"})
    queued = background_jobs.start_model_fix(run["id"], {"max_issues": 3, "rerun_qa": False})
    assert queued["status"] == "queued"

    save_settings({**DEFAULT_SETTINGS, "provider": "test-fake", "model": "after-model-fix"})
    release.set()
    _wait_until(lambda: queue.get_job(f"model-fix:{run['id']}")["status"] == "completed")

    assert observed == {"run_id": run["id"], "model": "after-model-fix"}
    assert db.get_run(run["id"])["status"] == "passed"


def test_multilingual_qa_handler_reads_one_fresh_settings_snapshot_after_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    from app.config import DEFAULT_SETTINGS, save_settings
    import app.workflow.multilingual as multilingual

    queue = _queue()
    release = threading.Event()
    blocker_started = threading.Event()
    observed: list[str] = []

    def blocker(record: dict[str, Any], cancel_event: threading.Event) -> None:
        _ = record, cancel_event
        blocker_started.set()
        release.wait(2.0)

    def fake_qa(run_id: str, *, settings: dict[str, Any], cancel_event: threading.Event) -> dict[str, Any]:
        _ = cancel_event
        observed.append(settings["model"])
        db.update_run(run_id, status="passed")
        return {"run": db.get_run(run_id)}

    background_jobs.register_handlers()
    queue.register_handler("blocker", blocker)
    _enqueue("multi-qa-settings-blocker", job_kind="blocker")
    assert blocker_started.wait(2.0)
    project = db.insert_project("multilingual QA settings", "QA", "")
    child = db.insert_run(
        project["id"],
        "qa",
        "en",
        metadata={"parent_input_artifact_id": "source", "multilingual_source_artifact_id": "source"},
    )
    monkeypatch.setattr(multilingual, "run_qa_sync", fake_qa)
    save_settings({**DEFAULT_SETTINGS, "provider": "test-fake", "model": "multi-before"})
    background_jobs.start_multilingual(
        "multilingual_qa",
        project["id"],
        "source",
        background_jobs.MultilingualQueueRequest(input_artifact_id="source", languages=["en"]),
        [child["id"]],
    )
    save_settings({**DEFAULT_SETTINGS, "provider": "test-fake", "model": "multi-after"})
    release.set()
    _wait_until(lambda: queue.get_job(f"multilingual:qa:{project['id']}:source")["status"] == "completed")

    assert observed == ["multi-after"]


def test_announcement_enqueue_failure_keeps_prepared_state(monkeypatch: pytest.MonkeyPatch) -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    project = db.insert_project("announcement enqueue rollback", "QA", "")
    task = db.insert_announcement_task(
        project["id"],
        {"title": "rollback", "selected_languages": ["en"], "status": "prepared", "current_step": 6},
    )
    monkeypatch.setattr(background_jobs.job_queue, "enqueue_job", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("db busy")))

    with pytest.raises(RuntimeError, match="db busy"):
        background_jobs.start_announcement(task["id"], {"languages": ["en"], "batch_size": 2})

    stored = db.get_announcement_task(task["id"])
    assert stored["status"] == "prepared"
    assert stored["current_step"] == 6
    assert "queued_at" not in stored["metadata"]


def test_enqueue_is_atomic_idempotent_and_round_trips_safe_payload() -> None:
    safe_payload = {"provider": "openai", "batch_size": 8, "languages": ["en", "ko"]}

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(lambda _: _enqueue("same-job", payload=safe_payload), range(16)))

    assert {row["job_id"] for row in rows} == {"same-job"}
    assert len(_queue().list_jobs()) == 1
    stored = _queue().get_job("same-job")
    assert stored is not None
    assert stored["payload"] == safe_payload
    assert "test-secret-key" not in json.dumps(stored, ensure_ascii=False)
    with sqlite3.connect(db.DB_PATH) as conn:
        raw_payload = conn.execute("SELECT payload_json FROM job_queue WHERE job_id = ?", ("same-job",)).fetchone()[0]
    assert json.loads(raw_payload) == safe_payload
    assert "test-secret-key" not in raw_payload


def test_atomic_claim_allows_only_one_running_job_per_lane() -> None:
    _enqueue("claim-1")
    _enqueue("claim-2")

    barrier = threading.Barrier(2)

    def claim():
        barrier.wait()
        return _queue().claim_next_job("language_table")

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(lambda _: claim(), range(2)))

    assert len([row for row in claimed if row is not None]) == 1
    snapshot = _queue().queue_snapshot()
    assert [row["status"] for row in snapshot["language_table"]] == ["running", "queued"]


def test_database_rejects_two_running_rows_in_one_lane() -> None:
    timestamp = db.now_iso()
    with sqlite3.connect(db.DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO job_queue (
                job_id, lane, job_kind, project_id, target_id, payload_json,
                operator_name, status, cancel_requested, canceled_by,
                queued_at, started_at, updated_at
            ) VALUES (?, 'language_table', 'translate', 'project-a', '', '{}', '', 'running', 0, '', ?, ?, ?)
            """,
            ("running-1", timestamp, timestamp, timestamp),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO job_queue (
                    job_id, lane, job_kind, project_id, target_id, payload_json,
                    operator_name, status, cancel_requested, canceled_by,
                    queued_at, started_at, updated_at
                ) VALUES (?, 'language_table', 'translate', 'project-b', '', '{}', '', 'running', 0, '', ?, ?, ?)
                """,
                ("running-2", timestamp, timestamp, timestamp),
            )


def test_init_db_migrates_job_queue_cancel_audit_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_db = tmp_path / "job-queue-before-cancel-audit.sqlite3"
    with sqlite3.connect(legacy_db) as conn:
        conn.execute(
            """
            CREATE TABLE job_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL UNIQUE,
                lane TEXT NOT NULL,
                job_kind TEXT NOT NULL,
                project_id TEXT NOT NULL,
                target_id TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                operator_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                canceled_by TEXT NOT NULL DEFAULT '',
                queued_at TEXT NOT NULL,
                started_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )

    monkeypatch.setattr(db, "DB_PATH", legacy_db)
    db.init_db()

    with sqlite3.connect(legacy_db) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(job_queue)")}
    assert {"cancel_requested_at", "canceled_at"}.issubset(columns)


def test_same_lane_is_fifo_and_completion_dispatches_next() -> None:
    queue = _queue()
    release_first = threading.Event()
    started: list[str] = []
    running = 0
    max_running = 0
    state_lock = threading.Lock()

    def handler(record: dict[str, Any], cancel_event: threading.Event) -> None:
        nonlocal running, max_running
        with state_lock:
            started.append(record["job_id"])
            running += 1
            max_running = max(max_running, running)
        if record["job_id"] == "fifo-1":
            release_first.wait(2.0)
        with state_lock:
            running -= 1

    queue.register_handler("translate", handler)
    _enqueue("fifo-1")
    _wait_until(lambda: started == ["fifo-1"])
    _enqueue("fifo-2")
    _enqueue("fifo-3")
    assert [row["status"] for row in queue.queue_snapshot()["language_table"]] == ["running", "queued", "queued"]

    release_first.set()
    _wait_until(lambda: [queue.get_job(job_id)["status"] for job_id in ("fifo-1", "fifo-2", "fifo-3")] == ["completed"] * 3)

    assert started == ["fifo-1", "fifo-2", "fifo-3"]
    assert max_running == 1


def test_enqueue_can_persist_without_autostart_until_explicit_dispatch() -> None:
    queue = _queue()
    handled: list[str] = []
    queue.register_handler("translate", lambda record, cancel_event: handled.append(record["job_id"]))

    persisted = _enqueue("persist-first", autostart=False)

    assert persisted["status"] == "queued"
    assert handled == []
    assert queue.dispatch_lane("language_table") is True
    _wait_until(lambda: queue.get_job("persist-first")["status"] == "completed")
    assert handled == ["persist-first"]


def test_staged_enqueue_has_exactly_one_owner_for_an_active_job_id() -> None:
    first = _enqueue("stage-owner", autostart=False, staged=True)
    second = _enqueue("stage-owner", autostart=False, staged=True)

    assert first["status"] == "staged"
    assert first["stage_owned"] is True
    assert second["status"] == "staged"
    assert second["stage_owned"] is False


def test_two_lanes_run_in_parallel() -> None:
    queue = _queue()
    both_started = threading.Event()
    release = threading.Event()
    started: set[str] = set()
    lock = threading.Lock()

    def handler(record: dict[str, Any], cancel_event: threading.Event) -> None:
        with lock:
            started.add(record["lane"])
            if started == {"language_table", "quick_announcement"}:
                both_started.set()
        release.wait(2.0)

    queue.register_handler("translate", handler)
    queue.register_handler("announcement", handler)
    _enqueue("lane-language")
    _enqueue("lane-announcement", lane="quick_announcement", job_kind="announcement")

    assert both_started.wait(2.0)
    assert {row["lane"] for row in queue.list_jobs(status="running")} == {"language_table", "quick_announcement"}
    release.set()
    _wait_until(lambda: all(row["status"] == "completed" for row in queue.list_jobs()))


def test_cancel_queued_job_removes_it_from_active_queue() -> None:
    queue = _queue()
    release = threading.Event()
    started: list[str] = []

    def handler(record: dict[str, Any], cancel_event: threading.Event) -> None:
        started.append(record["job_id"])
        release.wait(2.0)

    queue.register_handler("translate", handler)
    _enqueue("blocking")
    _wait_until(lambda: started == ["blocking"])
    _enqueue("cancel-queued", project_id="project-b")

    canceled = queue.cancel_job("cancel-queued", canceled_by="Bob")

    assert canceled is not None
    assert canceled["status"] == "canceled"
    assert canceled["canceled_by"] == "Bob"
    assert canceled["cancel_requested_at"]
    assert canceled["canceled_at"] == canceled["cancel_requested_at"]
    assert queue.active_job_for_project("project-b", lane="language_table") is None
    release.set()
    _wait_until(lambda: queue.get_job("blocking")["status"] == "completed")
    assert started == ["blocking"]
    retried = _enqueue("cancel-queued", project_id="project-b", autostart=False)
    assert retried["cancel_requested_at"] is None
    assert retried["canceled_at"] is None


def test_cancel_running_job_sets_event_and_persists_request() -> None:
    queue = _queue()
    observed_cancel = threading.Event()
    handled: list[str] = []

    def handler(record: dict[str, Any], cancel_event: threading.Event) -> None:
        handled.append(record["job_id"])
        if record["job_id"] == "cancel-running":
            assert cancel_event.wait(2.0)
            observed_cancel.set()

    queue.register_handler("translate", handler)
    _enqueue("cancel-running")
    _wait_until(lambda: queue.get_job("cancel-running")["status"] == "running")
    _enqueue("after-cancel")

    requested = queue.cancel_job("cancel-running", canceled_by="Bob")

    assert requested is not None
    assert requested["cancel_requested"] is True
    assert requested["canceled_by"] == "Bob"
    assert requested["cancel_requested_at"]
    assert requested["canceled_at"] is None
    assert observed_cancel.wait(2.0)
    _wait_until(lambda: queue.get_job("cancel-running")["status"] == "canceled")
    canceled = queue.get_job("cancel-running")
    assert canceled["cancel_requested_at"] == requested["cancel_requested_at"]
    assert canceled["canceled_at"]
    assert canceled["updated_at"] != requested["updated_at"]
    _wait_until(lambda: queue.get_job("after-cancel")["status"] == "completed")
    assert handled == ["cancel-running", "after-cancel"]


def test_handler_exception_releases_lane_and_dispatches_next(caplog: pytest.LogCaptureFixture) -> None:
    queue = _queue()
    handled: list[str] = []

    def handler(record: dict[str, Any], cancel_event: threading.Event) -> None:
        handled.append(record["job_id"])
        if record["job_id"] == "fails":
            raise RuntimeError("test failure")

    queue.register_handler("translate", handler)
    with caplog.at_level(logging.ERROR, logger="app.job_queue"):
        _enqueue("fails")
        _enqueue("after-failure")

        _wait_until(lambda: queue.get_job("fails")["status"] == "failed")
        _wait_until(lambda: queue.get_job("after-failure")["status"] == "completed")
    assert handled == ["fails", "after-failure"]
    assert any(record.exc_info and "job handler failed" in record.message for record in caplog.records)


def test_default_shutdown_preserves_running_for_restart_and_stops_lane() -> None:
    queue = _queue()
    current_started = threading.Event()
    release_current = threading.Event()
    current_cancel_event: list[threading.Event] = []
    handled: list[str] = []

    def handler(record: dict[str, Any], cancel_event: threading.Event) -> None:
        handled.append(record["job_id"])
        if record["job_id"] == "shutdown-running":
            current_cancel_event.append(cancel_event)
            current_started.set()
            release_current.wait(2.0)

    queue.register_handler("translate", handler)
    _enqueue("shutdown-running")
    assert current_started.wait(2.0)
    _enqueue("shutdown-queued")

    try:
        queue.shutdown_dispatchers(timeout=0.05)
        assert current_cancel_event and not current_cancel_event[0].is_set()
    finally:
        release_current.set()
        queue.shutdown_dispatchers(timeout=2.0)

    assert queue.get_job("shutdown-running")["status"] == "running"
    assert queue.get_job("shutdown-queued")["status"] == "queued"
    assert handled == ["shutdown-running"]

    interrupted = queue.recover_interrupted_jobs()
    assert [row["job_id"] for row in interrupted] == ["shutdown-running"]
    queue.register_handler("translate", handler)
    assert queue.resume_dispatchers() == ["language_table"]
    _wait_until(lambda: queue.get_job("shutdown-queued")["status"] == "completed")
    assert handled == ["shutdown-running", "shutdown-queued"]


def test_test_cleanup_stops_lane_before_forcing_cancel_so_next_job_does_not_spawn() -> None:
    from conftest import wait_for_background_jobs

    queue = _queue()
    first_started = threading.Event()
    handled: list[str] = []

    def handler(record: dict[str, Any], cancel_event: threading.Event) -> None:
        handled.append(record["job_id"])
        first_started.set()
        cancel_event.wait(2.0)

    queue.register_handler("translate", handler)
    _enqueue("cleanup-first")
    assert first_started.wait(2.0)
    _enqueue("cleanup-second")

    wait_for_background_jobs(timeout=0.05)

    with queue._RUNTIME_LOCK:
        assert not [thread for thread in queue._THREADS if thread.is_alive()]
    assert handled == ["cleanup-first"]
    assert queue.get_job("cleanup-second")["status"] == "queued"


def test_test_cleanup_fails_without_resetting_dispatcher_while_thread_is_alive() -> None:
    from conftest import wait_for_background_jobs

    queue = _queue()
    started = threading.Event()
    release = threading.Event()

    def handler(record: dict[str, Any], cancel_event: threading.Event) -> None:
        _ = record, cancel_event
        started.set()
        release.wait(2.0)

    queue.register_handler("translate", handler)
    _enqueue("cleanup-stubborn")
    assert started.wait(2.0)

    try:
        with pytest.raises(RuntimeError, match="queue worker threads did not stop"):
            wait_for_background_jobs(timeout=0.02)
        assert queue._STOPPING is True
    finally:
        release.set()
        queue.shutdown_dispatchers(timeout=2.0, cancel_running=True)
        queue.reset_dispatcher_state()


def test_recovery_interrupts_old_running_and_requires_explicit_resume() -> None:
    queue = _queue()
    _enqueue("old-running", project_id="project-old")
    _enqueue("survives-restart", project_id="project-new")
    assert queue.claim_next_job("language_table")["job_id"] == "old-running"

    interrupted = queue.recover_interrupted_jobs()

    assert [row["job_id"] for row in interrupted] == ["old-running"]
    assert queue.get_job("old-running")["status"] == "interrupted"
    assert queue.get_job("survives-restart")["status"] == "queued"
    assert queue.resume_dispatchers() == []
    assert queue.get_job("survives-restart")["status"] == "queued"

    handled: list[str] = []
    queue.register_handler("translate", lambda record, cancel_event: handled.append(record["job_id"]))
    assert handled == []
    assert queue.resume_dispatchers() == ["language_table"]
    _wait_until(lambda: queue.get_job("survives-restart")["status"] == "completed")
    assert handled == ["survives-restart"]


def test_recovery_activates_staged_run_and_announcement_after_business_state_was_queued() -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    queue = _queue()
    project = db.insert_project("staged crash recovery", "QA", "")
    run = db.insert_run(project["id"], "translation", "en", metadata={"task_origin": "translation_run"})
    db.update_run(run["id"], status="queued")
    task = db.insert_announcement_task(
        project["id"],
        {"title": "staged announcement", "selected_languages": ["en"], "status": "queued", "current_step": 7},
    )
    queue.enqueue_job(
        job_id=f"run:{run['id']}",
        lane="language_table",
        job_kind="translation",
        project_id=project["id"],
        target_id=run["id"],
        staged=True,
        autostart=False,
    )
    queue.enqueue_job(
        job_id=f"announcement:{task['id']}",
        lane="quick_announcement",
        job_kind="announcement",
        project_id=project["id"],
        target_id=task["id"],
        staged=True,
        autostart=False,
    )

    interrupted = queue.recover_interrupted_jobs()
    background_jobs.reconcile_startup(interrupted)

    assert interrupted == []
    assert queue.get_job(f"run:{run['id']}")["status"] == "queued"
    assert queue.get_job(f"announcement:{task['id']}")["status"] == "queued"
    assert db.get_run(run["id"])["status"] == "queued"
    assert db.get_announcement_task(task["id"])["status"] == "queued"


def test_interrupted_job_id_can_be_reenqueued_for_explicit_retry() -> None:
    queue = _queue()
    _enqueue("retry-interrupted", payload={"attempt": 1})
    assert queue.claim_next_job("language_table")["job_id"] == "retry-interrupted"
    assert [row["job_id"] for row in queue.recover_interrupted_jobs()] == ["retry-interrupted"]

    retried = _enqueue("retry-interrupted", payload={"attempt": 2}, autostart=False)

    assert retried["status"] == "queued"
    assert retried["payload"] == {"attempt": 2}
    assert len(queue.list_jobs()) == 1


def test_business_reconcile_marks_interrupted_run_needs_input_without_rerunning_handler() -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    queue = _queue()
    project = db.insert_project("restart interrupted", "QA", "")
    run = db.insert_run(project["id"], "qa", "en", metadata={})
    db.update_run(run["id"], status="running")
    _enqueue(
        f"qa:{run['id']}",
        job_kind="qa",
        project_id=project["id"],
        target_id=run["id"],
        autostart=False,
    )
    assert queue.claim_next_job("language_table")["job_id"] == f"qa:{run['id']}"

    interrupted = queue.recover_interrupted_jobs()
    summary = background_jobs.reconcile_startup(interrupted)

    stored = db.get_run(run["id"])
    assert summary["interrupted_runs"] == 1
    assert stored["status"] == "needs_input"
    assert stored["metadata"]["reason"] == "service_restart_continue"
    assert any(event["message"] == "服务已重启，请继续当前任务" for event in db.list_events(run["id"]))
    handled: list[str] = []
    queue.register_handler("qa", lambda record, cancel_event: handled.append(record["job_id"]))
    queue.resume_dispatchers()
    assert handled == []


def test_business_reconcile_preserves_terminal_run_and_cleans_queued_residual() -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    queue = _queue()
    project = db.insert_project("restart terminal", "QA", "")
    run = db.insert_run(project["id"], "translation", "en", metadata={"delivery_artifact_id": "art_keep"})
    db.update_run(run["id"], status="passed")
    _enqueue(
        f"run:{run['id']}",
        job_kind="translation",
        project_id=project["id"],
        target_id=run["id"],
        autostart=False,
    )

    summary = background_jobs.reconcile_startup([])

    stored = db.get_run(run["id"])
    assert summary["terminal_queue_rows_cleaned"] == 1
    assert stored["status"] == "passed"
    assert stored["metadata"]["delivery_artifact_id"] == "art_keep"
    assert queue.get_job(f"run:{run['id']}")["status"] == "completed"
    handled: list[str] = []
    queue.register_handler("translation", lambda record, cancel_event: handled.append(record["job_id"]))
    queue.resume_dispatchers()
    assert handled == []


def test_business_reconcile_cleans_interrupted_queue_row_when_run_finished_during_shutdown() -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    queue = _queue()
    project = db.insert_project("shutdown terminal", "QA", "")
    run = db.insert_run(project["id"], "translation", "en", metadata={"delivery_artifact_id": "art_keep"})
    db.update_run(run["id"], status="passed")
    _enqueue(
        f"run:{run['id']}",
        job_kind="translation",
        project_id=project["id"],
        target_id=run["id"],
        autostart=False,
    )
    assert queue.claim_next_job("language_table")["job_id"] == f"run:{run['id']}"

    summary = background_jobs.reconcile_startup(queue.recover_interrupted_jobs())

    assert summary["terminal_queue_rows_cleaned"] == 1
    assert db.get_run(run["id"])["status"] == "passed"
    assert queue.get_job(f"run:{run['id']}")["status"] == "completed"


def test_business_reconcile_cancels_orphaned_queued_qa_and_interrupts_legacy_running() -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    project = db.insert_project("legacy cleanup", "QA", "")
    orphan = db.insert_run(project["id"], "qa", "en", metadata={})
    legacy_running = db.insert_run(project["id"], "translation", "ko", metadata={})
    db.update_run(orphan["id"], status="queued")
    db.update_run(legacy_running["id"], status="running")

    summary = background_jobs.reconcile_startup([])

    cleaned = db.get_run(orphan["id"])
    interrupted = db.get_run(legacy_running["id"])
    assert summary["orphaned_queued_runs"] == 1
    assert cleaned["status"] == "canceled"
    assert cleaned["metadata"]["reason"] == "orphaned_legacy_queue_cleanup"
    assert any("孤立" in event["message"] for event in db.list_events(orphan["id"]))
    assert interrupted["status"] == "needs_input"
    assert interrupted["metadata"]["reason"] == "service_restart_continue"


def test_business_reconcile_safely_interrupts_queued_run_with_matching_legacy_lease() -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    from app import jobs

    project = db.insert_project("matching legacy lease", "QA", "")
    run = db.insert_run(project["id"], "qa", "en", metadata={})
    db.update_run(run["id"], status="queued")
    assert db.acquire_job_lease(jobs.lease_name_for_project(project["id"]), f"qa:{run['id']}")

    background_jobs.reconcile_startup([])

    stored = db.get_run(run["id"])
    assert stored["status"] == "needs_input"
    assert stored["metadata"]["reason"] == "service_restart_continue"


def test_business_reconcile_marks_interrupted_announcement_and_prepares_languages() -> None:
    background_jobs = importlib.import_module("app.background_jobs")
    queue = _queue()
    project = db.insert_project("restart announcement", "QA", "")
    task = db.insert_announcement_task(
        project["id"],
        {"title": "restart", "selected_languages": ["en", "ko"], "status": "running", "current_step": 7},
    )
    for item in task["languages"]:
        db.upsert_announcement_task_language(
            task["id"],
            project["id"],
            item["language"],
            status="running",
            current_step=7,
        )
    _enqueue(
        f"announcement:{task['id']}",
        lane="quick_announcement",
        job_kind="announcement",
        project_id=project["id"],
        target_id=task["id"],
        autostart=False,
    )
    assert queue.claim_next_job("quick_announcement")["job_id"] == f"announcement:{task['id']}"

    background_jobs.reconcile_startup(queue.recover_interrupted_jobs())

    stored = db.get_announcement_task(task["id"])
    assert stored["status"] == "needs_input"
    assert stored["metadata"]["reason"] == "service_restart_continue"
    assert {item["status"] for item in stored["languages"]} == {"prepared"}


def test_jobs_active_views_prefer_persistent_queue_rows() -> None:
    import app.jobs as jobs

    _enqueue("active-queue", project_id="project-active")
    assert jobs.active_job_for_project("project-active")["job_id"] == "active-queue"
    assert jobs.active_jobs() == []
    claimed = _queue().claim_next_job("language_table")
    assert claimed is not None

    active = jobs.active_job_for_project("project-active")

    assert active is not None
    assert active["job_id"] == "active-queue"
    rows = jobs.active_jobs()
    assert [row["job_id"] for row in rows] == ["active-queue"]
    assert rows[0]["lane"] == "language_table"
    assert rows[0]["lease_name"] == "long_text:project-active"
