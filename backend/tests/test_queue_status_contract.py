from __future__ import annotations

import pytest

from app.routers import system


@pytest.mark.parametrize(
    ("requested", "committed", "can_cancel"),
    [(False, False, True), (True, False, False), (False, True, False), (True, True, False)],
)
def test_queue_status_preserves_stop_request_and_archive_cancel_boundary(monkeypatch, requested, committed, can_cancel):
    monkeypatch.setattr(system.db, "get_project", lambda _: {"name": "隔离状态契约"})
    monkeypatch.setattr(system.db, "get_run", lambda _: {"metadata": {}})
    entry = system._queue_entry({
        "job_id": "status-job", "job_kind": "translation", "project_id": "fixture",
        "status": "running", "cancel_requested": requested,
        "payload": {"archive_commit": {"at": "now"}} if committed else {},
    })
    assert entry["status"] == "running"  # A stop request is not a terminal result.
    assert entry["cancel_requested"] is requested
    assert entry["archive_committed"] is committed
    assert entry["can_cancel"] is can_cancel
