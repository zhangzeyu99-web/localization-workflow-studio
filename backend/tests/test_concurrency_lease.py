from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path

os.environ["LWS_DATA_ROOT"] = str(Path(tempfile.gettempdir()) / "lws-test-data")

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
