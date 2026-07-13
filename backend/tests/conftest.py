from __future__ import annotations

import gc
import os
import shutil
import time
from pathlib import Path

import pytest

os.environ.setdefault("LWS_DATA_ROOT", str(Path(os.environ.get("TEMP", ".")) / f"lws-test-data-{os.getpid()}"))
os.environ.setdefault("LWS_ENABLE_TEST_PROVIDER", "1")


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
        return
    with jobs._LOCK:  # type: ignore[attr-defined]
        active_jobs = [job for job in jobs._ACTIVE_JOBS.values() if job.thread.is_alive()]  # type: ignore[attr-defined]
    if not active_jobs:
        return
    for job in active_jobs:
        job.thread.join(timeout)
    still_running = [job for job in active_jobs if job.thread.is_alive()]
    for job in still_running:
        job.cancel_event.set()
    for job in still_running:
        job.thread.join(timeout)


def reset_data_root(path: Path) -> None:
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
