from __future__ import annotations

import gc
import os
import shutil
import time
from pathlib import Path

os.environ.setdefault("LWS_DATA_ROOT", str(Path(os.environ.get("TEMP", ".")) / "lws-test-data"))
os.environ.setdefault("LWS_ENABLE_TEST_PROVIDER", "1")


def wait_for_background_jobs(timeout: float = 5.0) -> None:
    try:
        import app.jobs as jobs
    except Exception:
        return
    with jobs._LOCK:  # type: ignore[attr-defined]
        active = jobs._ACTIVE_JOB  # type: ignore[attr-defined]
    if active and active.thread.is_alive():
        active.cancel_event.set()
        active.thread.join(timeout)


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
