from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("LWS_DATA_ROOT", str(Path(tempfile.gettempdir()) / "lws-test-data"))

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.background_jobs as background_jobs
import app.db as db
import app.job_queue as job_queue
import app.jobs as jobs
import app.workflow as workflow
from app.config import DEFAULT_SETTINGS, save_settings
from app.main import app
from app.providers import test_fake_translate_batch
from app.schemas import TranslateRequest
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


def test_two_projects_translate_in_parallel_independently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflow, "translate_batch", _slow_test_fake_translate_batch(0.6))

    with TestClient(app) as client:
        project_a, run_a = _create_project_with_run(client, tmp_path, "Concurrency A")
        project_b, run_b = _create_project_with_run(client, tmp_path, "Concurrency B")

        started_a = client.post(f"/api/runs/{run_a['id']}/translate/start", json={"provider": "test-fake", "batch_size": 2})
        assert started_a.status_code == 200, started_a.text
        started_b = client.post(f"/api/runs/{run_b['id']}/translate/start", json={"provider": "test-fake", "batch_size": 2})
        assert started_b.status_code == 200, started_b.text

        # Both projects' background jobs run under different per-project
        # leases, so neither should block the other (pre-M2 behaviour would
        # have rejected the second start with a global lease conflict).
        terminal_a = _wait_for_terminal_run(client, run_a["id"])
        terminal_b = _wait_for_terminal_run(client, run_b["id"])
        assert terminal_a["status"] == "passed"
        assert terminal_b["status"] == "passed"
        assert terminal_a["id"] != terminal_b["id"]


def test_same_project_second_translation_is_accepted_into_fifo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflow, "translate_batch", _slow_test_fake_translate_batch(0.6))

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Busy Project", "type": "QA"}).json()
        workbook_1 = _language_table(tmp_path / "busy-1.xlsx")
        workbook_2 = _language_table(tmp_path / "busy-2.xlsx", prefix="标签")
        with workbook_1.open("rb") as fh:
            artifact_1 = client.post(
                f"/api/projects/{project['id']}/files?kind=language_table",
                files={"file": ("busy-1.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()
        with workbook_2.open("rb") as fh:
            artifact_2 = client.post(
                f"/api/projects/{project['id']}/files?kind=language_table",
                files={"file": ("busy-2.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()
        run_1 = client.post(
            "/api/runs",
            json={"project_id": project["id"], "kind": "translation", "language": "en", "input_artifact_id": artifact_1["id"], "batch_size": 2},
        ).json()
        run_2 = db.insert_run(
            project["id"],
            "translation",
            "en",
            metadata={"input_artifact_id": artifact_2["id"], "batch_size": 2, "task_origin": "translation_run"},
        )

        started_1 = client.post(
            f"/api/runs/{run_1['id']}/translate/start",
            json={"provider": "test-fake", "batch_size": 2},
            headers={"X-Operator": "Alice"},
        )
        assert started_1.status_code == 200, started_1.text

        queued = client.post(
            f"/api/runs/{run_2['id']}/translate/start",
            json={"provider": "test-fake", "batch_size": 2},
            headers={"X-Operator": "Bob"},
        )
        assert queued.status_code == 200, queued.text
        assert job_queue.get_job(f"run:{run_2['id']}")["status"] == "queued"
        assert db.get_run(run_2["id"])["status"] == "queued"

        terminal_1 = _wait_for_terminal_run(client, run_1["id"])
        terminal_2 = _wait_for_terminal_run(client, run_2["id"])
        assert terminal_1["status"] == "passed"
        assert terminal_2["status"] == "passed"


def test_legacy_capacity_setting_does_not_reject_second_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    save_settings({**DEFAULT_SETTINGS, "max_concurrent_ai_jobs": 1})
    monkeypatch.setattr(workflow, "translate_batch", _slow_test_fake_translate_batch(0.6))

    with TestClient(app) as client:
        project_a, run_a = _create_project_with_run(client, tmp_path, "Capacity A")
        project_b, run_b = _create_project_with_run(client, tmp_path, "Capacity B")
        run_b = db.update_run(run_b["id"], status="needs_input")

        started_a = client.post(f"/api/runs/{run_a['id']}/translate/start", json={"provider": "test-fake", "batch_size": 2})
        assert started_a.status_code == 200, started_a.text

        queued = client.post(f"/api/runs/{run_b['id']}/translate/start", json={"provider": "test-fake", "batch_size": 2})
        assert queued.status_code == 200, queued.text
        stored_b = client.get(f"/api/runs/{run_b['id']}").json()
        assert stored_b["status"] == "queued"
        assert stored_b["metadata"]["queued_at"]
        assert "queue_error" not in stored_b["metadata"]

        terminal_a = _wait_for_terminal_run(client, run_a["id"])
        assert terminal_a["status"] == "passed"

        terminal_b = _wait_for_terminal_run(client, run_b["id"])
        assert terminal_b["status"] == "passed"


def test_announcement_start_uses_quick_lane_without_legacy_capacity_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    project = db.insert_project("Announcement Queue Rollback", "QA", "")
    task = db.insert_announcement_task(
        project["id"],
        {
            "title": "Rollback",
            "selected_languages": ["en"],
            "status": "prepared",
            "current_step": 6,
        },
    )
    def fake_translate(task_id: str, payload: object, *, cancel_event: object) -> dict:
        _ = payload, cancel_event
        db.update_announcement_task(task_id, status="translated", current_step=8)
        return {"task": db.get_announcement_task(task_id)}

    monkeypatch.setattr(workflow, "translate_announcement_task", fake_translate)

    with TestClient(app) as client:
        started = client.post(
            f"/api/announcement-tasks/{task['id']}/translate/start",
            json={"languages": ["en"], "provider": "test-fake", "batch_size": 2},
        )

    assert started.status_code == 200, started.text
    queued = job_queue.get_job(f"announcement:{task['id']}")
    assert queued is not None
    assert queued["lane"] == "quick_announcement"


def test_reconcile_interrupted_background_jobs_clears_multiple_residual_leases() -> None:
    project_a = db.insert_project("Reconcile Lease A", "QA", "")
    project_b = db.insert_project("Reconcile Lease B", "QA", "")
    run_a = db.insert_run(project_a["id"], "translation", "en", metadata={})
    run_b = db.insert_run(project_b["id"], "translation", "en", metadata={})
    db.update_run(run_a["id"], status="running", metadata={"input_artifact_id": "art_missing"})
    db.update_run(run_b["id"], status="running", metadata={"input_artifact_id": "art_missing"})

    assert db.acquire_job_lease(jobs.lease_name_for_project(project_a["id"]), f"run:{run_a['id']}")
    assert db.acquire_job_lease(jobs.lease_name_for_project(project_b["id"]), f"run:{run_b['id']}")

    summary = workflow.reconcile_interrupted_background_jobs()

    assert summary["translation_runs"] == 2
    assert db.get_run(run_a["id"])["status"] == "needs_input"
    assert db.get_run(run_b["id"])["status"] == "needs_input"

    lease_a = db.get_job_lease(jobs.lease_name_for_project(project_a["id"]))
    lease_b = db.get_job_lease(jobs.lease_name_for_project(project_b["id"]))
    assert lease_a["status"] == "interrupted"
    assert lease_b["status"] == "interrupted"

    # No active jobs should be reported once every residual lease is interrupted.
    assert jobs.active_jobs() == []


def test_reconcile_does_not_reopen_terminal_task_with_legacy_running_status() -> None:
    project = db.insert_project("Reconcile terminal task", "QA", "")
    run = db.insert_run(
        project["id"],
        "translation",
        "en",
        metadata={"translation_task_id": "task-reconcile-terminal", "task_origin": "translation_run"},
    )
    db.update_run(run["id"], status="passed")
    workflow.mark_translation_task_state(project["id"], "task-reconcile-terminal", "delivered")
    db.update_run(run["id"], status="running")

    summary = workflow.reconcile_interrupted_background_jobs()

    refreshed = db.get_run(run["id"])
    assert summary["translation_runs"] == 0
    assert refreshed["status"] == "canceled"
    assert refreshed["metadata"]["translation_task_state"] == "delivered"
    assert "interrupted_at" not in refreshed["metadata"]


def test_job_lease_persists_operator_name() -> None:
    project = db.insert_project("Operator Lease", "QA", "")
    lease_name = jobs.lease_name_for_project(project["id"])

    assert db.acquire_job_lease(lease_name, "run:operator", operator_name="Alice")

    lease = db.get_job_lease(lease_name)
    assert lease is not None
    assert lease["operator_name"] == "Alice"


def test_init_db_adds_operator_name_to_v132_job_lease_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_db = tmp_path / "v1.3.2.sqlite3"
    with sqlite3.connect(legacy_db) as conn:
        conn.execute(
            """
            CREATE TABLE job_leases (
                name TEXT PRIMARY KEY,
                job_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'idle',
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO job_leases
              (name, job_id, status, cancel_requested, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("long_text:legacy", "run:legacy", "running", 0, "{}", "2026-07-14T00:00:00Z", "2026-07-14T00:00:00Z"),
        )

    monkeypatch.setattr(db, "DB_PATH", legacy_db)
    db.init_db()

    with sqlite3.connect(legacy_db) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(job_leases)")}
        row = conn.execute(
            "SELECT operator_name FROM job_leases WHERE name = ?",
            ("long_text:legacy",),
        ).fetchone()

    assert "operator_name" in columns
    assert row == ("",)


def test_active_jobs_endpoint_reports_lease_and_project_details(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflow, "translate_batch", _slow_test_fake_translate_batch(0.6))

    with TestClient(app) as client:
        project, run = _create_project_with_run(client, tmp_path, "Active Jobs Panel")
        started = client.post(
            f"/api/runs/{run['id']}/translate/start",
            json={"provider": "test-fake", "batch_size": 2},
            headers={"X-Operator": "Alice"},
        )
        assert started.status_code == 200, started.text

        entry = None
        for _ in range(40):
            active = client.get("/api/system/active-jobs").json()
            entry = next((item for item in active if item["project_id"] == project["id"]), None)
            if entry:
                break
            time.sleep(0.05)
        assert entry is not None
        assert entry["job_id"] == f"run:{run['id']}"
        assert entry["job_kind"] == "translation"
        assert entry["project_name"] == "Active Jobs Panel"
        assert entry["lease_name"] == f"long_text:{project['id']}"
        assert entry["started_at"]
        assert entry["operator_name"] == "Alice"

        _wait_for_terminal_run(client, run["id"])


def test_start_singleton_job_pre_start_rejection_creates_no_job_or_lease() -> None:
    project = db.insert_project("Pre-start rejection", "QA", "")
    ran = False

    def target(_cancel_event: object) -> None:
        nonlocal ran
        ran = True

    started, conflict = jobs.start_singleton_job(
        project["id"],
        "run:pre-start-rejected",
        target,
        pre_start=lambda: {"reason": "translation_task_terminal", "state": "canceled"},
    )

    assert started is False
    assert conflict == {"reason": "translation_task_terminal", "state": "canceled"}
    assert ran is False
    assert jobs.active_job_id_for_project(project["id"]) is None
    lease = db.get_job_lease(jobs.lease_name_for_project(project["id"]))
    assert lease is None or lease["status"] != "running"


def test_atomic_task_lease_claim_rejects_terminal_committed_before_claim() -> None:
    project = db.insert_project("Atomic terminal before claim", "QA", "")
    run = db.insert_run(
        project["id"],
        "translation",
        "en",
        metadata={"translation_task_id": "task-terminal-before-claim", "task_origin": "translation_run"},
    )
    workflow.mark_translation_task_state(project["id"], "task-terminal-before-claim", "canceled")
    worker_called = threading.Event()

    started, conflict = jobs.start_singleton_job(
        project["id"],
        f"run:{run['id']}",
        lambda _cancel_event: worker_called.set(),
        task_run_id=run["id"],
    )

    assert started is False
    assert conflict == {
        "reason": "translation_task_terminal",
        "run_id": run["id"],
        "translation_task_id": "task-terminal-before-claim",
        "state": "canceled",
    }
    assert worker_called.is_set() is False
    assert jobs.active_job_id_for_project(project["id"]) is None


def test_persistent_queue_staging_cannot_reopen_task_closed_before_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = db.insert_project("Persistent queue terminal race", "QA", "")
    run = db.insert_run(
        project["id"],
        "translation",
        "en",
        metadata={"translation_task_id": "task-persistent-queue-race", "task_origin": "translation_run"},
    )
    staged = threading.Event()
    terminal_committed = threading.Event()
    activated: list[str] = []
    real_enqueue = job_queue.enqueue_job

    def controlled_enqueue(**kwargs: object) -> dict:
        queued = real_enqueue(**kwargs)
        assert queued["status"] == job_queue.STAGING_STATUS
        staged.set()
        assert terminal_committed.wait(timeout=5)
        return queued

    def capture_activation(job_id: str, *, autostart: bool = True) -> dict:
        _ = autostart
        activated.append(job_id)
        queued = job_queue.get_job(job_id)
        assert queued is not None
        return queued

    monkeypatch.setattr(background_jobs.job_queue, "enqueue_job", controlled_enqueue)
    monkeypatch.setattr(background_jobs.job_queue, "activate_job", capture_activation)

    with ThreadPoolExecutor(max_workers=1) as executor:
        start_future = executor.submit(
            background_jobs.start_translation,
            run["id"],
            TranslateRequest(provider="test-fake"),
        )
        assert staged.wait(timeout=5)
        workflow.mark_translation_task_state(project["id"], "task-persistent-queue-race", "canceled")
        terminal_committed.set()
        with pytest.raises(db.TranslationTaskClosedError):
            start_future.result(timeout=5)

    refreshed = db.get_run(run["id"])
    assert refreshed["status"] == "canceled"
    assert refreshed["metadata"]["translation_task_state"] == "canceled"
    assert activated == []
    queued = job_queue.get_job(f"run:{run['id']}")
    assert queued is None or queued["status"] not in {job_queue.STAGING_STATUS, "queued", "running"}


def test_active_jobs_excludes_second_project_waiting_in_same_lane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflow, "translate_batch", _slow_test_fake_translate_batch(0.6))

    with TestClient(app) as client:
        project_a, run_a = _create_project_with_run(client, tmp_path, "Panel Concurrency A")
        project_b, run_b = _create_project_with_run(client, tmp_path, "Panel Concurrency B")

        started_a = client.post(f"/api/runs/{run_a['id']}/translate/start", json={"provider": "test-fake", "batch_size": 2})
        assert started_a.status_code == 200, started_a.text
        started_b = client.post(f"/api/runs/{run_b['id']}/translate/start", json={"provider": "test-fake", "batch_size": 2})
        assert started_b.status_code == 200, started_b.text

        active = client.get("/api/system/active-jobs").json()
        assert [item["project_id"] for item in active] == [project_a["id"]]
        assert active[0]["lane"] == "language_table"
        queues = client.get("/api/system/job-queues").json()
        language_lane = next(item for item in queues["lanes"] if item["lane"] == "language_table")
        assert language_lane["running"]["project_id"] == project_a["id"]
        assert language_lane["queued"][0]["project_id"] == project_b["id"]
        assert language_lane["queued"][0]["position"] == 1
        assert language_lane["queued"][0]["ahead"] == 1

        assert _wait_for_terminal_run(client, run_a["id"])["status"] == "passed"
        assert _wait_for_terminal_run(client, run_b["id"])["status"] == "passed"
