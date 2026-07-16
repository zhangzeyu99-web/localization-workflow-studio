from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class BackgroundJob:
    id: str
    thread: threading.Thread
    cancel_event: threading.Event
    lease_name: str


_LOCK = threading.Lock()
_ACTIVE_JOBS: dict[str, BackgroundJob] = {}

_LEASE_PREFIX = "long_text"

_JOB_KIND_PREFIXES: tuple[tuple[str, str], ...] = (
    ("run:", "translation"),
    ("model-fix:", "model_fix"),
    ("announcement:", "announcement"),
    ("multilingual:translate:", "multilingual_translate"),
    ("multilingual:qa:", "multilingual_qa"),
    ("qa:", "qa"),
)

_JOB_KIND_LABELS: dict[str, str] = {
    "translation": "翻译任务",
    "model_fix": "模型修复任务",
    "announcement": "公告翻译任务",
    "multilingual_translate": "多语言翻译队列",
    "multilingual_qa": "多语言 QA 队列",
    "qa": "QA 校对任务",
    "unknown": "AI 任务",
}


def lease_name_for_project(project_id: str) -> str:
    return f"{_LEASE_PREFIX}:{project_id}"


def describe_job_kind(job_id: str) -> str:
    for prefix, kind in _JOB_KIND_PREFIXES:
        if job_id.startswith(prefix):
            return kind
    return "unknown"


def describe_job(job_id: str) -> str:
    return _JOB_KIND_LABELS.get(describe_job_kind(job_id), _JOB_KIND_LABELS["unknown"])


def _resolve_max_concurrent_jobs() -> int:
    """Read the configured global job cap.

    Must be called *before* acquiring ``_LOCK``: ``load_settings()`` does
    file IO (reads ``settings.local.json``), and holding a process-wide
    lock during file IO needlessly blocks every other project's job-start
    attempt for the duration of that IO.
    """
    from .config import load_settings

    try:
        value = int(load_settings().get("max_concurrent_ai_jobs") or 2)
    except (TypeError, ValueError):
        value = 2
    return max(1, min(value, 4))


def start_singleton_job(
    project_id: str,
    job_id: str,
    target: Callable[[threading.Event], None],
    *,
    pre_start: Callable[[], dict[str, Any] | None] | None = None,
    task_run_id: str | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    """Start a background job under the per-project lease.

    Returns ``(True, None)`` on success. On rejection returns ``(False, reason)``
    where ``reason`` is either ``None`` (caller already owns the running job,
    i.e. an idempotent no-op) or a structured dict with one of:
    - ``{"reason": "project_busy", "active_job_id": <job_id>}``
    - ``{"reason": "capacity", "active_count": N, "limit": N}``
    - a structured rejection returned by ``pre_start``
    """
    lease_name = lease_name_for_project(project_id)
    # Read outside the lock: this is a settings.local.json file read, not
    # in-process state, so it must not hold up every other project's
    # job-start attempt while the lock is held.
    limit = _resolve_max_concurrent_jobs()
    global _ACTIVE_JOBS
    with _LOCK:
        existing = _ACTIVE_JOBS.get(lease_name)
        if existing and existing.thread.is_alive():
            if existing.id == job_id:
                return False, None
            return False, {"reason": "project_busy", "active_job_id": existing.id}
        if pre_start is not None:
            pre_start_conflict = pre_start()
            if pre_start_conflict:
                return False, pre_start_conflict
        from . import db

        if task_run_id:
            acquired, lease_conflict = db.acquire_job_lease_for_open_task_run(lease_name, job_id, task_run_id)
            if not acquired:
                return False, lease_conflict
        elif not db.acquire_job_lease(lease_name, job_id):
            lease = db.get_job_lease(lease_name)
            active_job = str((lease or {}).get("job_id") or "")
            if active_job and active_job != job_id:
                return False, {"reason": "project_busy", "active_job_id": active_job}
            return False, None

        active_count = sum(1 for job in _ACTIVE_JOBS.values() if job.thread.is_alive())
        if active_count >= limit:
            db.release_job_lease(lease_name, job_id, status="capacity_rejected")
            return False, {"reason": "capacity", "active_count": active_count, "limit": limit}

        cancel_event = threading.Event()

        def run_and_clear() -> None:
            try:
                target(cancel_event)
            finally:
                from . import db

                db.release_job_lease(lease_name, job_id)
                with _LOCK:
                    current = _ACTIVE_JOBS.get(lease_name)
                    if current and current.id == job_id:
                        del _ACTIVE_JOBS[lease_name]

        thread = threading.Thread(target=run_and_clear, name=f"lws-longtext-{job_id}", daemon=True)
        _ACTIVE_JOBS[lease_name] = BackgroundJob(id=job_id, thread=thread, cancel_event=cancel_event, lease_name=lease_name)
        thread.start()
        return True, None


def cancel_singleton_job(project_id: str, job_id: str) -> bool:
    from . import db

    lease_name = lease_name_for_project(project_id)
    lease_canceled = db.cancel_job_lease(lease_name, job_id)
    with _LOCK:
        job = _ACTIVE_JOBS.get(lease_name)
        if job and job.id == job_id and job.thread.is_alive():
            job.cancel_event.set()
            return True
    return lease_canceled


def active_job_id_for_project(project_id: str) -> str | None:
    lease_name = lease_name_for_project(project_id)
    with _LOCK:
        job = _ACTIVE_JOBS.get(lease_name)
        if job and job.thread.is_alive():
            return job.id
    try:
        from . import db

        lease = db.get_job_lease(lease_name)
        if lease and lease.get("status") == "running":
            return str(lease.get("job_id") or "") or None
    except Exception:
        return None
    return None


def active_jobs() -> list[dict[str, Any]]:
    """Return all currently running jobs, cross-referencing the in-process
    registry with persisted ``job_leases`` rows so a lease that survives a
    restart (or a lease driven by an in-memory job not yet flushed to disk)
    is still reported.
    """
    from . import db

    with _LOCK:
        in_memory = {name: job.id for name, job in _ACTIVE_JOBS.items() if job.thread.is_alive()}

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        rows = db.list_job_leases(status="running")
    except Exception:
        rows = []
    for row in rows:
        name = str(row.get("name") or "")
        job_id = str(row.get("job_id") or "")
        result.append({"lease_name": name, "job_id": job_id, "started_at": row.get("updated_at")})
        seen.add(name)
    for name, job_id in in_memory.items():
        if name in seen:
            continue
        result.append({"lease_name": name, "job_id": job_id, "started_at": None})
    return result


def active_job_id() -> str | None:
    """Backward-compat shim: returns some globally active job id, if any.

    Prefer :func:`active_job_id_for_project` or :func:`active_jobs` for new
    code now that leases are project-scoped.
    """
    jobs_list = active_jobs()
    return str(jobs_list[0]["job_id"]) if jobs_list else None
