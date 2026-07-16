from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

os.environ.setdefault("LWS_DATA_ROOT", str(Path(tempfile.gettempdir()) / "lws-test-data"))

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.db as db
import app.jobs as jobs
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


def test_same_project_second_translation_rejected_as_project_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        # create_run() itself already guards against two active runs of the same
        # kind in one project (pre-existing, independent of the job lease), so
        # insert run_2 directly via the db layer to exercise the *lease-level*
        # project_busy rejection in isolation.
        run_2 = db.insert_run(
            project["id"],
            "translation",
            "ko",
            metadata={"input_artifact_id": artifact_2["id"], "batch_size": 2, "task_origin": "translation_run"},
        )

        started_1 = client.post(f"/api/runs/{run_1['id']}/translate/start", json={"provider": "test-fake", "batch_size": 2})
        assert started_1.status_code == 200, started_1.text

        rejected = client.post(f"/api/runs/{run_2['id']}/translate/start", json={"provider": "test-fake", "batch_size": 2})
        assert rejected.status_code == 409
        detail = rejected.json()["detail"]
        assert "该项目正在执行任务" in detail

        terminal_1 = _wait_for_terminal_run(client, run_1["id"])
        assert terminal_1["status"] == "passed"


def test_capacity_limit_rejects_second_project_when_workbench_is_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    save_settings({**DEFAULT_SETTINGS, "max_concurrent_ai_jobs": 1})
    monkeypatch.setattr(workflow, "translate_batch", _slow_test_fake_translate_batch(0.6))

    with TestClient(app) as client:
        project_a, run_a = _create_project_with_run(client, tmp_path, "Capacity A")
        project_b, run_b = _create_project_with_run(client, tmp_path, "Capacity B")

        started_a = client.post(f"/api/runs/{run_a['id']}/translate/start", json={"provider": "test-fake", "batch_size": 2})
        assert started_a.status_code == 200, started_a.text

        rejected = client.post(f"/api/runs/{run_b['id']}/translate/start", json={"provider": "test-fake", "batch_size": 2})
        assert rejected.status_code == 409
        detail = rejected.json()["detail"]
        assert "工作台已有" in detail
        assert "上限 1" in detail

        terminal_a = _wait_for_terminal_run(client, run_a["id"])
        assert terminal_a["status"] == "passed"

        # The run reaches its terminal status inside the worker target; the
        # wrapper releases the lease immediately afterwards. Join that wrapper
        # so this assertion tests cleared capacity rather than the cleanup gap.
        wait_for_background_jobs()
        assert jobs.active_job_id_for_project(project_a["id"]) is None

        # Once project A's job clears, project B should be able to start.
        started_b_retry = client.post(f"/api/runs/{run_b['id']}/translate/start", json={"provider": "test-fake", "batch_size": 2})
        assert started_b_retry.status_code == 200, started_b_retry.text
        terminal_b = _wait_for_terminal_run(client, run_b["id"])
        assert terminal_b["status"] == "passed"


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


def test_active_jobs_endpoint_reports_lease_and_project_details(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflow, "translate_batch", _slow_test_fake_translate_batch(0.6))

    with TestClient(app) as client:
        project, run = _create_project_with_run(client, tmp_path, "Active Jobs Panel")
        started = client.post(f"/api/runs/{run['id']}/translate/start", json={"provider": "test-fake", "batch_size": 2})
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


def test_atomic_task_lease_claim_linearizes_before_later_terminal_and_isolates_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = db.insert_project("Atomic claim before terminal", "QA", "")
    run = db.insert_run(
        project["id"],
        "translation",
        "en",
        metadata={"translation_task_id": "task-claim-before-terminal", "task_origin": "translation_run"},
    )
    scheduler_thread_id: dict[str, int] = {}
    before_lease_write = threading.Event()
    terminal_attempted = threading.Event()
    terminal_committed = threading.Event()
    allow_lease_write = threading.Event()
    allow_worker_check = threading.Event()
    worker_started = threading.Event()
    worker_isolated = threading.Event()
    real_connect = db.connect

    @contextmanager
    def traced_connect():
        with real_connect() as conn:
            if threading.get_ident() == scheduler_thread_id.get("value"):
                paused = False

                def trace(statement: str) -> None:
                    nonlocal paused
                    normalized = " ".join(statement.strip().split()).upper()
                    if paused or "INSERT INTO JOB_LEASES" not in normalized:
                        return
                    paused = True
                    before_lease_write.set()
                    assert terminal_attempted.wait(timeout=5)
                    assert terminal_committed.is_set() is False
                    assert allow_lease_write.wait(timeout=5)

                conn.set_trace_callback(trace)
            yield conn

    monkeypatch.setattr(db, "connect", traced_connect)

    def worker(cancel_event: threading.Event) -> None:
        worker_started.set()
        assert allow_worker_check.wait(timeout=5)
        if cancel_event.is_set():
            worker_isolated.set()
            return
        try:
            workflow.ensure_task_run_open(db.get_run(run["id"]))
        except db.TranslationTaskClosedError:
            worker_isolated.set()

    def start_job() -> tuple[bool, dict | None]:
        scheduler_thread_id["value"] = threading.get_ident()
        return jobs.start_singleton_job(
            project["id"],
            f"run:{run['id']}",
            worker,
            task_run_id=run["id"],
        )

    def close_task() -> None:
        terminal_attempted.set()
        workflow.mark_translation_task_state(project["id"], "task-claim-before-terminal", "canceled")
        terminal_committed.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        start_future = executor.submit(start_job)
        assert before_lease_write.wait(timeout=5)
        terminal_future = executor.submit(close_task)
        assert terminal_attempted.wait(timeout=5)
        time.sleep(0.05)
        assert terminal_committed.is_set() is False
        allow_lease_write.set()
        started, conflict = start_future.result(timeout=5)
        terminal_future.result(timeout=5)

    assert started is True
    assert conflict is None
    assert terminal_committed.is_set() is True
    assert worker_started.wait(timeout=5)
    assert jobs.cancel_singleton_job(project["id"], f"run:{run['id']}") is True
    allow_worker_check.set()
    assert worker_isolated.wait(timeout=5)
    assert db.get_run(run["id"])["status"] == "canceled"
    wait_for_background_jobs()


def test_active_jobs_endpoint_reports_two_projects_running_concurrently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflow, "translate_batch", _slow_test_fake_translate_batch(0.6))

    with TestClient(app) as client:
        project_a, run_a = _create_project_with_run(client, tmp_path, "Panel Concurrency A")
        project_b, run_b = _create_project_with_run(client, tmp_path, "Panel Concurrency B")

        started_a = client.post(f"/api/runs/{run_a['id']}/translate/start", json={"provider": "test-fake", "batch_size": 2})
        assert started_a.status_code == 200, started_a.text
        started_b = client.post(f"/api/runs/{run_b['id']}/translate/start", json={"provider": "test-fake", "batch_size": 2})
        assert started_b.status_code == 200, started_b.text

        observed_both_running = False
        for _ in range(40):
            active = client.get("/api/system/active-jobs").json()
            project_ids = {item["project_id"] for item in active}
            if {project_a["id"], project_b["id"]}.issubset(project_ids):
                observed_both_running = True
                lease_names = {item["lease_name"] for item in active}
                assert f"long_text:{project_a['id']}" in lease_names
                assert f"long_text:{project_b['id']}" in lease_names
                assert all(item["job_kind"] == "translation" for item in active)
                break
            time.sleep(0.05)
        assert observed_both_running, "expected both projects' jobs to be reported by /api/system/active-jobs concurrently"

        assert _wait_for_terminal_run(client, run_a["id"])["status"] == "passed"
        assert _wait_for_terminal_run(client, run_b["id"])["status"] == "passed"
