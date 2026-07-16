from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("LWS_DATA_ROOT", str(Path(tempfile.gettempdir()) / "lws-test-data"))

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.db as db
from app.config import DEFAULT_SETTINGS, save_settings
from app.main import app
from app.workflow import QaCanceled, run_qa_sync
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


def _failing_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Language"
    ws.append(["ID", "cn", "en"])
    ws.append([1, "领取奖励", "Forbidden Brand Reward"])
    ws.append([2, "开始游戏", "Start Game"])
    wb.save(path)
    wb.close()


def _passing_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Language"
    ws.append(["ID", "cn", "en"])
    ws.append([1, "领取奖励", "Claim Reward"])
    ws.append([2, "开始游戏", "Start Game"])
    wb.save(path)
    wb.close()


def _upload_final_workbook(client: TestClient, project_id: str, path: Path) -> dict:
    with path.open("rb") as fh:
        return client.post(
            f"/api/projects/{project_id}/files?kind=final_workbook",
            files={"file": (path.name, fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        ).json()


def _wait_for_terminal_run(client: TestClient, run_id: str, timeout_s: float = 30.0) -> dict:
    deadline = time.time() + timeout_s
    run: dict = {}
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run.get("status") not in {"queued", "running"}:
            return run
        time.sleep(0.2)
    return run


def test_qa_background_start_finishes_with_failed_status(tmp_path: Path) -> None:
    workbook = tmp_path / "failing.xlsx"
    _failing_workbook(workbook)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "QA BG Fail", "type": "QA"}).json()
        client.patch(f"/api/projects/{project['id']}/harness", json={"forbidden_translations": ["Forbidden Brand"]})
        artifact = _upload_final_workbook(client, project["id"], workbook)
        run = client.post(
            "/api/runs",
            json={"project_id": project["id"], "kind": "qa", "language": "en", "input_artifact_id": artifact["id"]},
        ).json()

        response = client.post(f"/api/runs/{run['id']}/qa/start")
        assert response.status_code == 200, response.text
        started = response.json()
        assert started["status"] in {"queued", "running", "failed"}

        final = _wait_for_terminal_run(client, run["id"])
        assert final["status"] == "failed"
        issues = client.get(f"/api/runs/{run['id']}/quality-issues").json()["issues"]
        assert any(issue["check_type"] == "forbidden_translation" for issue in issues)
        # The background job must have produced the same artifacts as sync QA.
        kinds = {item["kind"] for item in client.get(f"/api/runs/{run['id']}").json().get("artifacts") or []}
        run_artifacts = [a for a in client.get(f"/api/projects/{project['id']}").json()["artifacts"] if a.get("run_id") == run["id"]]
        kinds = kinds | {item["kind"] for item in run_artifacts}
        assert "qa_final_workbook" in kinds


def test_legacy_failed_qa_result_remains_deliverable(tmp_path: Path) -> None:
    workbook = tmp_path / "legacy-failed.xlsx"
    _failing_workbook(workbook)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Legacy QA Result", "type": "QA"}).json()
        source = _upload_final_workbook(client, project["id"], workbook)
        run = client.post(
            "/api/runs",
            json={"project_id": project["id"], "kind": "qa", "language": "en", "input_artifact_id": source["id"]},
        ).json()
        db.add_artifact(
            project["id"],
            "Legacy QA reviewed workbook",
            workbook,
            "qa_result",
            run_id=run["id"],
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        db.update_run(
            run["id"],
            status="failed",
            metadata={"input_artifact_id": source["id"], "quality_summary": {"passed": False, "hard_errors": 1}},
        )

        deliverables = client.get(f"/api/projects/{project['id']}/deliverables").json()["deliverables"]

        assert len(deliverables) == 1
        assert deliverables[0]["run_id"] == run["id"]
        assert deliverables[0]["delivered_with_issues"] is True
        assert client.get(f"/api/projects/{project['id']}").json()["stats"]["deliverables"] == 1


def test_qa_background_start_passes_clean_workbook(tmp_path: Path) -> None:
    workbook = tmp_path / "passing.xlsx"
    _passing_workbook(workbook)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "QA BG Pass", "type": "QA"}).json()
        artifact = _upload_final_workbook(client, project["id"], workbook)
        run = client.post(
            "/api/runs",
            json={"project_id": project["id"], "kind": "qa", "language": "en", "input_artifact_id": artifact["id"]},
        ).json()
        response = client.post(f"/api/runs/{run['id']}/qa/start")
        assert response.status_code == 200, response.text
        final = _wait_for_terminal_run(client, run["id"])
        assert final["status"] == "passed"
        assert final["metadata"]["quality_summary"]["passed"] is True


def test_qa_cancel_endpoint_returns_404_without_active_queue_job(tmp_path: Path) -> None:
    workbook = tmp_path / "passing.xlsx"
    _passing_workbook(workbook)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "QA BG Cancel", "type": "QA"}).json()
        artifact = _upload_final_workbook(client, project["id"], workbook)
        run = client.post(
            "/api/runs",
            json={"project_id": project["id"], "kind": "qa", "language": "en", "input_artifact_id": artifact["id"]},
        ).json()
        response = client.post(f"/api/runs/{run['id']}/qa/cancel")
        assert response.status_code == 404
        assert db.get_run(run["id"])["status"] == "created"


def test_run_qa_sync_raises_when_cancel_event_preset(tmp_path: Path) -> None:
    workbook = tmp_path / "passing.xlsx"
    _passing_workbook(workbook)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "QA Cancel Unit", "type": "QA"}).json()
        artifact = _upload_final_workbook(client, project["id"], workbook)
        run = client.post(
            "/api/runs",
            json={"project_id": project["id"], "kind": "qa", "language": "en", "input_artifact_id": artifact["id"]},
        ).json()
        cancel_event = threading.Event()
        cancel_event.set()
        with pytest.raises(QaCanceled):
            run_qa_sync(run["id"], cancel_event=cancel_event)
        # No terminal status was written by the pipeline itself.
        assert client.get(f"/api/runs/{run['id']}").json()["status"] != "passed"


def test_manual_fixes_start_reruns_qa_in_background(tmp_path: Path) -> None:
    workbook = tmp_path / "failing.xlsx"
    _failing_workbook(workbook)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Manual Fix BG", "type": "QA"}).json()
        client.patch(f"/api/projects/{project['id']}/harness", json={"forbidden_translations": ["Forbidden Brand"]})
        artifact = _upload_final_workbook(client, project["id"], workbook)
        failed_run = client.post(
            "/api/runs",
            json={"project_id": project["id"], "kind": "qa", "language": "en", "input_artifact_id": artifact["id"]},
        ).json()
        assert client.post(f"/api/runs/{failed_run['id']}/qa").json()["run"]["status"] == "failed"

        response = client.post(
            f"/api/runs/{failed_run['id']}/manual-fixes/start",
            json={
                "fixes": [{"sheet": "Language", "row": 2, "translation": "Reward", "note": "remove forbidden phrase"}],
                "rerun_qa": True,
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["fixed_artifact"]["origin"] == "manual"
        assert result["qa_run"], "background QA run should be returned"
        qa_run_id = result["qa_run"]["id"]
        final = _wait_for_terminal_run(client, qa_run_id)
        assert final["status"] == "passed"
        assert final["metadata"]["manual_fix_source_run_id"] == failed_run["id"]
        # Manual-fix metadata still lands in the project harness like the sync path.
        harness = client.get(f"/api/projects/{project['id']}/harness").json()["project_harness"]
        assert harness["manual_fixes"][0]["translation"] == "Reward"
