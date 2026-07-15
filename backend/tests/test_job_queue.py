from __future__ import annotations

import importlib
import json
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
        queue.shutdown_dispatchers(timeout=2.0)
        queue.clear_handlers()

    database = tmp_path / "job-queue.sqlite3"
    monkeypatch.setattr(db, "DB_PATH", database)
    db.init_db()
    yield

    try:
        queue = _queue()
    except ModuleNotFoundError:
        return
    queue.shutdown_dispatchers(timeout=2.0)
    queue.clear_handlers()


def _enqueue(
    job_id: str,
    *,
    lane: str = "language_table",
    job_kind: str = "translate",
    project_id: str = "project-a",
    target_id: str | None = None,
    payload: dict[str, Any] | None = None,
    autostart: bool = True,
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
    )


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
    assert queue.active_job_for_project("project-b", lane="language_table") is None
    release.set()
    _wait_until(lambda: queue.get_job("blocking")["status"] == "completed")
    assert started == ["blocking"]


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
    assert observed_cancel.wait(2.0)
    _wait_until(lambda: queue.get_job("cancel-running")["status"] == "canceled")
    _wait_until(lambda: queue.get_job("after-cancel")["status"] == "completed")
    assert handled == ["cancel-running", "after-cancel"]


def test_handler_exception_releases_lane_and_dispatches_next() -> None:
    queue = _queue()
    handled: list[str] = []

    def handler(record: dict[str, Any], cancel_event: threading.Event) -> None:
        handled.append(record["job_id"])
        if record["job_id"] == "fails":
            raise RuntimeError("test failure")

    queue.register_handler("translate", handler)
    _enqueue("fails")
    _enqueue("after-failure")

    _wait_until(lambda: queue.get_job("fails")["status"] == "failed")
    _wait_until(lambda: queue.get_job("after-failure")["status"] == "completed")
    assert handled == ["fails", "after-failure"]


def test_shutdown_waits_for_finishing_dispatcher_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = _queue()
    finishing = threading.Event()
    allow_finish = threading.Event()
    shutdown_returned = threading.Event()
    original_dispatch = queue.dispatch_lane

    def delayed_follow_up_dispatch(lane: str) -> bool:
        if threading.current_thread().name.startswith("lws-queue-"):
            finishing.set()
            allow_finish.wait(2.0)
            return False
        return original_dispatch(lane)

    monkeypatch.setattr(queue, "dispatch_lane", delayed_follow_up_dispatch)
    queue.register_handler("translate", lambda record, cancel_event: None)
    _enqueue("cleanup-race")
    assert finishing.wait(2.0)

    shutdown_thread = threading.Thread(
        target=lambda: (queue.shutdown_dispatchers(timeout=2.0), shutdown_returned.set())
    )
    shutdown_thread.start()
    try:
        time.sleep(0.05)
        assert not shutdown_returned.is_set()
    finally:
        allow_finish.set()
        shutdown_thread.join(2.0)
    assert shutdown_returned.is_set()


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


def test_interrupted_job_id_can_be_reenqueued_for_explicit_retry() -> None:
    queue = _queue()
    _enqueue("retry-interrupted", payload={"attempt": 1})
    assert queue.claim_next_job("language_table")["job_id"] == "retry-interrupted"
    assert [row["job_id"] for row in queue.recover_interrupted_jobs()] == ["retry-interrupted"]

    retried = _enqueue("retry-interrupted", payload={"attempt": 2}, autostart=False)

    assert retried["status"] == "queued"
    assert retried["payload"] == {"attempt": 2}
    assert len(queue.list_jobs()) == 1


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
