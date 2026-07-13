from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

os.environ.setdefault("LWS_DATA_ROOT", str(Path(tempfile.gettempdir()) / "lws-test-data"))

import pytest

import app.db as db
from conftest import reset_data_root, wait_for_background_jobs


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    data_root = Path(os.environ["LWS_DATA_ROOT"])
    reset_data_root(data_root)
    db.init_db()
    yield
    wait_for_background_jobs()


def test_merge_run_metadata_merges_disjoint_keys() -> None:
    project = db.insert_project("merge metadata basic", "QA", "")
    run = db.insert_run(project["id"], "translation", "en", metadata={"seed": "value"})
    merged = db.merge_run_metadata(run["id"], {"reason": "needs_input"})
    assert merged["seed"] == "value"
    assert merged["reason"] == "needs_input"
    stored = db.get_run(run["id"])
    assert stored["metadata"]["seed"] == "value"
    assert stored["metadata"]["reason"] == "needs_input"


def test_merge_run_metadata_concurrent_threads_preserve_both_keys() -> None:
    """Regression test for the N-5 read-modify-write metadata race.

    Two threads repeatedly patch different top-level keys on the same run.
    Before merge_run_metadata existed, the old
    ``metadata={**db.get_run(run_id).get("metadata", {}), ...}`` pattern could
    lose one thread's key under concurrency (last write wins on the whole
    dict). merge_run_metadata must keep both keys every round.
    """
    project = db.insert_project("merge metadata concurrency", "QA", "")
    run = db.insert_run(project["id"], "translation", "en", metadata={})
    run_id = run["id"]
    iterations = 50
    errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def worker(key: str) -> None:
        for i in range(iterations):
            try:
                barrier.wait(timeout=5)
                db.merge_run_metadata(run_id, {key: i})
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)
                break

    thread_a = threading.Thread(target=worker, args=("alpha",))
    thread_b = threading.Thread(target=worker, args=("beta",))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=60)
    thread_b.join(timeout=60)

    assert not errors, f"merge_run_metadata raised under concurrency: {errors}"
    final_metadata = db.get_run(run_id)["metadata"]
    assert "alpha" in final_metadata
    assert "beta" in final_metadata
    assert final_metadata["alpha"] == iterations - 1
    assert final_metadata["beta"] == iterations - 1


def test_merge_announcement_task_metadata_merges_disjoint_keys() -> None:
    project = db.insert_project("merge announcement metadata", "QA", "")
    task = db.insert_announcement_task(project["id"], {"title": "t", "metadata": {"seed": "value"}})
    merged = db.merge_announcement_task_metadata(task["id"], {"queued_at": "now"})
    assert merged["seed"] == "value"
    assert merged["queued_at"] == "now"
    stored = db.get_announcement_task(task["id"])
    assert stored["metadata"]["seed"] == "value"
    assert stored["metadata"]["queued_at"] == "now"


def test_merge_run_metadata_raises_key_error_for_missing_run() -> None:
    with pytest.raises(KeyError):
        db.merge_run_metadata("run_does_not_exist", {"a": 1})
