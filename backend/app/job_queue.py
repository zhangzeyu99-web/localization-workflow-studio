from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable

from . import db


logger = logging.getLogger(__name__)

LANES = ("language_table", "quick_announcement")
ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("completed", "failed", "canceled", "interrupted")

JobRecord = dict[str, Any]
JobHandler = Callable[[JobRecord, threading.Event], None]


@dataclass
class _RunningJob:
    job_id: str
    thread: threading.Thread
    cancel_event: threading.Event


_RUNTIME_LOCK = threading.RLock()
_HANDLERS: dict[str, JobHandler] = {}
_RUNNING: dict[str, _RunningJob] = {}
_THREADS: set[threading.Thread] = set()
_STOPPING = False


def _validate_lane(lane: str) -> None:
    if lane not in LANES:
        raise ValueError(f"unsupported job lane: {lane}")


def _record(row: Any) -> JobRecord:
    result = dict(row)
    result["cancel_requested"] = bool(result.get("cancel_requested"))
    result["payload"] = json.loads(result.pop("payload_json", "{}") or "{}")
    return result


def enqueue_job(
    *,
    job_id: str,
    lane: str,
    job_kind: str,
    project_id: str,
    target_id: str,
    payload: dict[str, Any] | None = None,
    operator_name: str = "",
    autostart: bool = True,
) -> JobRecord:
    """Persist a job exactly once and dispatch it when its handler is ready."""
    _validate_lane(lane)
    payload_json = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))
    timestamp = db.now_iso()
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO job_queue (
                job_id, lane, job_kind, project_id, target_id, payload_json,
                operator_name, status, cancel_requested, canceled_by,
                cancel_requested_at, canceled_at, queued_at, started_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0, '', NULL, NULL, ?, NULL, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                lane = excluded.lane,
                job_kind = excluded.job_kind,
                project_id = excluded.project_id,
                target_id = excluded.target_id,
                payload_json = excluded.payload_json,
                operator_name = excluded.operator_name,
                status = 'queued',
                cancel_requested = 0,
                canceled_by = '',
                cancel_requested_at = NULL,
                canceled_at = NULL,
                queued_at = excluded.queued_at,
                started_at = NULL,
                updated_at = excluded.updated_at
            WHERE job_queue.status IN ('completed', 'failed', 'canceled', 'interrupted')
            """,
            (
                job_id,
                lane,
                job_kind,
                project_id,
                target_id,
                payload_json,
                operator_name,
                timestamp,
                timestamp,
            ),
        )
        row = conn.execute("SELECT * FROM job_queue WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"failed to persist queued job {job_id}")
    result = _record(row)
    with _RUNTIME_LOCK:
        handler_ready = result["job_kind"] in _HANDLERS
    if autostart and result["status"] == "queued" and handler_ready:
        dispatch_lane(result["lane"])
    return result


def get_job(job_id: str) -> JobRecord | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM job_queue WHERE job_id = ?", (job_id,)).fetchone()
    return _record(row) if row is not None else None


def list_jobs(*, status: str | None = None, lane: str | None = None) -> list[JobRecord]:
    if lane is not None:
        _validate_lane(lane)
    clauses: list[str] = []
    values: list[Any] = []
    if status is not None:
        clauses.append("status = ?")
        values.append(status)
    if lane is not None:
        clauses.append("lane = ?")
        values.append(lane)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM job_queue{where} ORDER BY queued_at ASC, id ASC",
            values,
        ).fetchall()
    return [_record(row) for row in rows]


def list_active_jobs(*, project_id: str | None = None, lane: str | None = None) -> list[JobRecord]:
    if lane is not None:
        _validate_lane(lane)
    clauses = ["status IN ('queued', 'running')"]
    values: list[Any] = []
    if project_id is not None:
        clauses.append("project_id = ?")
        values.append(project_id)
    if lane is not None:
        clauses.append("lane = ?")
        values.append(lane)
    with db.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM job_queue
            WHERE {' AND '.join(clauses)}
            ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, queued_at ASC, id ASC
            """,
            values,
        ).fetchall()
    return [_record(row) for row in rows]


def active_job_for_project(project_id: str, *, lane: str | None = None) -> JobRecord | None:
    rows = list_active_jobs(project_id=project_id, lane=lane)
    return rows[0] if rows else None


def queue_snapshot() -> dict[str, list[JobRecord]]:
    return {lane: list_active_jobs(lane=lane) for lane in LANES}


def claim_next_job(lane: str) -> JobRecord | None:
    """Atomically claim the FIFO head when the lane has no running job."""
    _validate_lane(lane)
    timestamp = db.now_iso()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        running = conn.execute(
            "SELECT 1 FROM job_queue WHERE lane = ? AND status = 'running' LIMIT 1",
            (lane,),
        ).fetchone()
        if running is not None:
            return None
        candidate = conn.execute(
            """
            SELECT id FROM job_queue
            WHERE lane = ? AND status = 'queued'
            ORDER BY queued_at ASC, id ASC
            LIMIT 1
            """,
            (lane,),
        ).fetchone()
        if candidate is None:
            return None
        changed = conn.execute(
            """
            UPDATE job_queue
            SET status = 'running', started_at = ?, updated_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (timestamp, timestamp, candidate["id"]),
        )
        if changed.rowcount != 1:
            return None
        row = conn.execute("SELECT * FROM job_queue WHERE id = ?", (candidate["id"],)).fetchone()
    return _record(row) if row is not None else None


def _requeue_unhandled(job_id: str) -> None:
    with db.connect() as conn:
        conn.execute(
            """
            UPDATE job_queue
            SET status = 'queued', started_at = NULL, updated_at = ?
            WHERE job_id = ? AND status = 'running'
            """,
            (db.now_iso(), job_id),
        )


def _finish_job(job_id: str, status: str) -> None:
    timestamp = db.now_iso()
    with db.connect() as conn:
        conn.execute(
            """
            UPDATE job_queue
            SET status = ?,
                canceled_at = CASE
                    WHEN ? = 'canceled' THEN COALESCE(canceled_at, ?)
                    ELSE canceled_at
                END,
                updated_at = ?
            WHERE job_id = ? AND status = 'running'
            """,
            (status, status, timestamp, timestamp, job_id),
        )


def register_handler(job_kind: str, handler: JobHandler) -> None:
    with _RUNTIME_LOCK:
        _HANDLERS[job_kind] = handler


def unregister_handler(job_kind: str) -> None:
    with _RUNTIME_LOCK:
        _HANDLERS.pop(job_kind, None)


def clear_handlers() -> None:
    with _RUNTIME_LOCK:
        _HANDLERS.clear()


def dispatch_lane(lane: str) -> bool:
    _validate_lane(lane)
    with _RUNTIME_LOCK:
        if _STOPPING:
            return False
        running = _RUNNING.get(lane)
        if running is not None and running.thread.is_alive():
            return False
        claimed = claim_next_job(lane)
        if claimed is None:
            return False
        handler = _HANDLERS.get(claimed["job_kind"])
        if handler is None:
            _requeue_unhandled(claimed["job_id"])
            return False
        cancel_event = threading.Event()

        def run() -> None:
            failed = False
            try:
                handler(claimed, cancel_event)
            except Exception:
                logger.exception("job handler failed: %s", claimed["job_id"])
                failed = True
            finally:
                with _RUNTIME_LOCK:
                    stopping = _STOPPING
                if not stopping:
                    current = get_job(claimed["job_id"])
                    canceled = cancel_event.is_set() or bool((current or {}).get("cancel_requested"))
                    _finish_job(claimed["job_id"], "canceled" if canceled else ("failed" if failed else "completed"))
                with _RUNTIME_LOCK:
                    active = _RUNNING.get(lane)
                    if active is not None and active.job_id == claimed["job_id"]:
                        _RUNNING.pop(lane, None)
                try:
                    if not stopping:
                        dispatch_lane(lane)
                finally:
                    with _RUNTIME_LOCK:
                        _THREADS.discard(threading.current_thread())

        thread = threading.Thread(target=run, name=f"lws-queue-{lane}-{claimed['job_id']}", daemon=True)
        _RUNNING[lane] = _RunningJob(claimed["job_id"], thread, cancel_event)
        _THREADS.add(thread)
        thread.start()
        return True


def resume_dispatchers() -> list[str]:
    """Explicitly resume persisted queued work after startup recovery."""
    global _STOPPING
    with _RUNTIME_LOCK:
        _STOPPING = False
    return [lane for lane in LANES if dispatch_lane(lane)]


def reset_dispatcher_state() -> None:
    """Reset the process-local stopping guard after test/runtime teardown."""
    global _STOPPING
    with _RUNTIME_LOCK:
        _STOPPING = False


def cancel_job(job_id: str, *, canceled_by: str = "") -> JobRecord | None:
    timestamp = db.now_iso()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT lane, status FROM job_queue WHERE job_id = ?", (job_id,)).fetchone()
        if row is None or row["status"] not in ACTIVE_STATUSES:
            return None
        if row["status"] == "queued":
            conn.execute(
                """
                UPDATE job_queue
                SET status = 'canceled', cancel_requested = 1, canceled_by = ?,
                    cancel_requested_at = ?, canceled_at = ?, updated_at = ?
                WHERE job_id = ? AND status = 'queued'
                """,
                (canceled_by, timestamp, timestamp, timestamp, job_id),
            )
        else:
            conn.execute(
                """
                UPDATE job_queue
                SET cancel_requested = 1,
                    canceled_by = CASE WHEN cancel_requested_at IS NULL THEN ? ELSE canceled_by END,
                    cancel_requested_at = COALESCE(cancel_requested_at, ?),
                    updated_at = ?
                WHERE job_id = ? AND status = 'running'
                """,
                (canceled_by, timestamp, timestamp, job_id),
            )
        updated = conn.execute("SELECT * FROM job_queue WHERE job_id = ?", (job_id,)).fetchone()
    if row["status"] == "running":
        with _RUNTIME_LOCK:
            running = _RUNNING.get(row["lane"])
            if running is not None and running.job_id == job_id:
                running.cancel_event.set()
    return _record(updated) if updated is not None else None


def recover_interrupted_jobs() -> list[JobRecord]:
    """Move pre-restart running records out of the active queue without rerunning them."""
    timestamp = db.now_iso()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT * FROM job_queue WHERE status = 'running' ORDER BY queued_at ASC, id ASC"
        ).fetchall()
        conn.execute(
            "UPDATE job_queue SET status = 'interrupted', updated_at = ? WHERE status = 'running'",
            (timestamp,),
        )
    interrupted = []
    for row in rows:
        result = _record(row)
        result["status"] = "interrupted"
        result["updated_at"] = timestamp
        interrupted.append(result)
    return interrupted


def shutdown_dispatchers(*, timeout: float = 5.0, cancel_running: bool = False) -> None:
    global _STOPPING
    with _RUNTIME_LOCK:
        _STOPPING = True
        _HANDLERS.clear()
        running = list(_RUNNING.values())
        threads = list(_THREADS)
    if cancel_running:
        for job in running:
            job.cancel_event.set()
    for thread in threads:
        if thread is not threading.current_thread():
            thread.join(timeout)
