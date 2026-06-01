from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable


@dataclass
class BackgroundJob:
    id: str
    thread: threading.Thread
    cancel_event: threading.Event


_LOCK = threading.Lock()
_ACTIVE_JOB: BackgroundJob | None = None


def start_singleton_job(job_id: str, target: Callable[[threading.Event], None]) -> tuple[bool, str | None]:
    global _ACTIVE_JOB
    with _LOCK:
        if _ACTIVE_JOB and _ACTIVE_JOB.thread.is_alive():
            if _ACTIVE_JOB.id == job_id:
                return False, None
            return False, _ACTIVE_JOB.id
        cancel_event = threading.Event()

        def run_and_clear() -> None:
            global _ACTIVE_JOB
            try:
                target(cancel_event)
            finally:
                with _LOCK:
                    if _ACTIVE_JOB and _ACTIVE_JOB.id == job_id:
                        _ACTIVE_JOB = None

        thread = threading.Thread(target=run_and_clear, name=f"lws-longtext-{job_id}", daemon=True)
        _ACTIVE_JOB = BackgroundJob(id=job_id, thread=thread, cancel_event=cancel_event)
        thread.start()
        return True, None


def cancel_singleton_job(job_id: str) -> bool:
    with _LOCK:
        if _ACTIVE_JOB and _ACTIVE_JOB.id == job_id and _ACTIVE_JOB.thread.is_alive():
            _ACTIVE_JOB.cancel_event.set()
            return True
    return False


def active_job_id() -> str | None:
    with _LOCK:
        if _ACTIVE_JOB and _ACTIVE_JOB.thread.is_alive():
            return _ACTIVE_JOB.id
    return None
