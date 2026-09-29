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
    timestamp = db.now_iso()
    with db.connect() as conn:
        conn.executemany(
            """
            INSERT INTO projects (id, name, type, description, created_at, updated_at)
            VALUES (?, ?, 'test', '', ?, ?)
            """,
            [
                (project_id, project_id, timestamp, timestamp)
                for project_id in ("project-a", "project-b", "project-old", "project-new", "project-active")
            ],
        )
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
