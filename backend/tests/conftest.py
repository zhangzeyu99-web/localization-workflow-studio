from __future__ import annotations

import gc
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

# Never inherit the desktop/server's business data directory into destructive
# test fixtures. Establish isolation before any app/config module is imported.
_TEST_DATA_ROOT = Path(tempfile.mkdtemp(prefix="lws-pytest-"))
os.environ["LWS_DATA_ROOT"] = str(_TEST_DATA_ROOT)
os.environ["LWS_ENABLE_TEST_PROVIDER"] = "1"
os.environ.pop("LWS_DEPLOYMENT_MODE", None)
os.environ.pop("LWS_AUTH_MODE", None)


@pytest.fixture(autouse=True)
def _reset_shared_rate_limiter_registry():
    """Process-wide rate limiter buckets (keyed by provider+api_key) must not
    leak between tests running in the same pytest process, or one test's
    quota usage would silently throttle an unrelated later test.
    """
    from app.translation_batches import reset_shared_rate_limiter_registry

    reset_shared_rate_limiter_registry()
    yield
    reset_shared_rate_limiter_registry()


def wait_for_background_jobs(timeout: float = 15.0) -> None:
    """Wait for all active background jobs (if any) to finish.

    Lets jobs complete naturally first so tests that start a job and then
    call this helper to await its normal completion aren't racing a forced
    cancellation against the worker thread's own progress. Only falls back to
    ``cancel_event.set()`` if a job is still running after the grace period,
    as a safety net for cleanup callers (e.g. ``reset_data_root``) that need
    to unblock stuck/long-running jobs before tearing down the data dir.

    Since M2, leases (and therefore active jobs) are per-project, so more than
    one job can be running concurrently; this waits for all of them rather
    than assuming a single global job.
    """
    try:
        import app.jobs as jobs
    except Exception:
        active_jobs = []
    else:
        with jobs._LOCK:  # type: ignore[attr-defined]
            active_jobs = [job for job in jobs._ACTIVE_JOBS.values() if job.thread.is_alive()]  # type: ignore[attr-defined]
    for job in active_jobs:
        job.thread.join(timeout)
    still_running = [job for job in active_jobs if job.thread.is_alive()]
    for job in still_running:
        job.cancel_event.set()
    for job in still_running:
        job.thread.join(timeout)

    try:
        import app.job_queue as job_queue
    except Exception:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with job_queue._RUNTIME_LOCK:  # type: ignore[attr-defined]
            queue_threads = [thread for thread in job_queue._THREADS if thread.is_alive()]  # type: ignore[attr-defined]
        if not queue_threads:
            return
        for thread in queue_threads:
            thread.join(min(0.1, max(0.0, deadline - time.monotonic())))
    job_queue.shutdown_dispatchers(timeout=timeout, cancel_running=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with job_queue._RUNTIME_LOCK:  # type: ignore[attr-defined]
            queue_threads = [thread for thread in job_queue._THREADS if thread.is_alive()]  # type: ignore[attr-defined]
        if not queue_threads:
            break
        for thread in queue_threads:
            thread.join(min(0.1, max(0.0, deadline - time.monotonic())))
    with job_queue._RUNTIME_LOCK:  # type: ignore[attr-defined]
        queue_threads = [thread for thread in job_queue._THREADS if thread.is_alive()]  # type: ignore[attr-defined]
    if queue_threads:
        raise RuntimeError("queue worker threads did not stop before test cleanup")
    job_queue.reset_dispatcher_state()


def reset_data_root(path: Path) -> None:
    resolved = path.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if not resolved.is_relative_to(temp_root):
        raise RuntimeError(f"Refusing to clean a non-temporary data directory: {resolved}")
    relative = resolved.relative_to(temp_root)
    if not relative.parts or not relative.parts[0].startswith(("lws-", "pytest-of-")):
        raise RuntimeError(f"Refusing to clean a directory not owned by tests: {resolved}")
    wait_for_background_jobs()
    gc.collect()
    if not path.exists():
        return
    last_error: Exception | None = None
    for _ in range(8):
        try:
            shutil.rmtree(path)
            return
        except (PermissionError, OSError) as exc:
            last_error = exc
            wait_for_background_jobs(timeout=1.0)
            gc.collect()
            time.sleep(0.25)
    if last_error:
        raise last_error
