from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import time
from pathlib import Path

os.environ["LWS_DATA_ROOT"] = str(Path(tempfile.gettempdir()) / "lws-test-data")

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.db as db
import app.workflow as workflow
from app.config import DEFAULT_SETTINGS, save_settings
from app.main import app
from app.providers import test_fake_translate_batch
from conftest import reset_data_root, wait_for_background_jobs


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    data_root = Path(os.environ["LWS_DATA_ROOT"])
    reset_data_root(data_root)
    db.init_db()
    save_settings(DEFAULT_SETTINGS)
    yield
    wait_for_background_jobs()
    save_settings(DEFAULT_SETTINGS)


def _language_table(path: Path, rows: int = 6, prefix: str = "按钮") -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Language"
    ws.append(["ID", "cn", "en"])
    for index in range(1, rows + 1):
        ws.append([index, f"{prefix} {index}", ""])
    wb.save(path)
    wb.close()
    return path


def _create_project_with_run(client: TestClient, tmp_path: Path, name: str) -> tuple[dict, dict]:
    workbook = _language_table(tmp_path / f"{name}.xlsx")
    project = client.post("/api/projects", json={"name": name, "type": "QA"}).json()
    with workbook.open("rb") as fh:
        artifact = client.post(
            f"/api/projects/{project['id']}/files?kind=language_table",
            files={"file": (f"{name}.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        ).json()
    run = client.post(
        "/api/runs",
        json={"project_id": project["id"], "kind": "translation", "language": "en", "input_artifact_id": artifact["id"], "batch_size": 2},
    ).json()
    return project, run


def _slow_test_fake_translate_batch(delay_seconds: float):
    async def _translate(batch, provider_settings, project_prompt):
        await asyncio.sleep(delay_seconds)
        return test_fake_translate_batch(batch, provider_settings)

    return _translate


def _wait_for_terminal_run(client: TestClient, run_id: str, timeout_iterations: int = 200) -> dict:
    terminal = None
    for _ in range(timeout_iterations):
        current = client.get(f"/api/runs/{run_id}").json()
        if current["status"] in {"passed", "failed", "needs_input", "canceled"}:
            terminal = current
            break
        time.sleep(0.1)
    assert terminal is not None, "run did not reach a terminal state in time"
    return terminal


def test_delete_project_rejected_while_job_active_then_allowed_after_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(workflow, "translate_batch", _slow_test_fake_translate_batch(0.6))

    with TestClient(app) as client:
        project, run = _create_project_with_run(client, tmp_path, "Delete Guard")

        started = client.post(f"/api/runs/{run['id']}/translate/start", json={"provider": "test-fake", "batch_size": 2})
        assert started.status_code == 200, started.text

        rejected = client.delete(f"/api/projects/{project['id']}")
        assert rejected.status_code == 409, rejected.text
        detail = rejected.json()["detail"]
        assert "正在执行任务" in detail
        # The project must not have been touched by the rejected delete.
        assert client.get(f"/api/projects/{project['id']}").status_code == 200

        terminal = _wait_for_terminal_run(client, run["id"])
        assert terminal["status"] == "passed"

        # The run row flips to "passed" (inside the worker thread's target())
        # a moment before that same thread's `finally` block releases the
        # per-project job lease, so there is a brief, load-sensitive window
        # right after the terminal status is observed where the lease still
        # looks active. Retry instead of asserting on the very first attempt.
        deleted = client.delete(f"/api/projects/{project['id']}")
        for _ in range(50):
            if deleted.status_code != 409:
                break
            time.sleep(0.05)
            deleted = client.delete(f"/api/projects/{project['id']}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json() == {"deleted": True}
        assert client.get(f"/api/projects/{project['id']}").status_code == 404


def test_concurrent_project_harness_updates_do_not_lose_writes() -> None:
    """Regression test for M3 batch 3: concurrent read-modify-write cycles on
    the SAME project's project_harness.json must not silently clobber one
    another (a naive read-then-write without a per-project lock would lose
    updates whenever two writers interleave their read and write steps).
    """
    project = db.insert_project("Harness Lock Race", "QA", "")
    thread_count = 8
    updates_per_thread = 15
    barrier = threading.Barrier(thread_count)
    errors: list[BaseException] = []

    def worker(thread_index: int) -> None:
        try:
            barrier.wait(timeout=10)
            for update_index in range(updates_per_thread):
                key = f"race_field_{thread_index}_{update_index}"

                def _merge(current: dict, key: str = key) -> dict:
                    project_metadata = dict(current.get("project_metadata") or {})
                    project_metadata[key] = "written"
                    return {"project_metadata": project_metadata}

                workflow.update_project_harness(project["id"], _merge)
        except BaseException as exc:  # noqa: BLE001 - surface to the main thread
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "harness update worker thread did not finish in time"

    assert not errors, errors
    final = workflow.read_project_harness(project["id"])
    project_metadata = final.get("project_metadata") or {}
    expected_keys = {f"race_field_{t}_{u}" for t in range(thread_count) for u in range(updates_per_thread)}
    missing = expected_keys - set(project_metadata.keys())
    assert not missing, f"lost {len(missing)}/{len(expected_keys)} concurrent harness updates: {sorted(missing)[:10]}"


def test_concurrent_improvement_suggestion_appends_do_not_lose_items() -> None:
    """Regression test for M3 batch 3: concurrent appends to the SAME
    project's improvement_suggestions.json must not lose entries the way a
    naive read-then-write-the-whole-list pattern would under interleaving.
    """
    project = db.insert_project("Improvement Suggestions Race", "QA", "")
    thread_count = 8
    items_per_thread = 10
    barrier = threading.Barrier(thread_count)
    errors: list[BaseException] = []

    def worker(thread_index: int) -> None:
        try:
            barrier.wait(timeout=10)
            for item_index in range(items_per_thread):
                workflow.create_project_improvement(
                    project["id"],
                    {"category": "soft_rule", "title": f"race-{thread_index}-{item_index}", "detail": ""},
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "improvement-suggestion worker thread did not finish in time"

    assert not errors, errors
    suggestions = workflow.list_improvements(project["id"])
    titles = {item.get("title") for item in suggestions}
    expected_titles = {f"race-{t}-{i}" for t in range(thread_count) for i in range(items_per_thread)}
    missing = expected_titles - titles
    assert not missing, f"lost {len(missing)}/{len(expected_titles)} concurrent improvement-suggestion appends"
