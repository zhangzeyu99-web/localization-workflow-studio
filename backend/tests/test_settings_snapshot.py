from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path

os.environ["LWS_DATA_ROOT"] = str(Path(tempfile.gettempdir()) / "lws-test-data")

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.config as config
import app.db as db
import app.jobs as jobs
import app.workflow as workflow
from app.config import DEFAULT_SETTINGS, save_settings
from app.main import app
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


def _project_harness_failed_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Language"
    ws.append(["ID", "cn", "en"])
    ws.append([1, "领取奖励", "Forbidden Brand Reward"])
    ws.append([2, "Start game source", "Start Game"])
    wb.save(path)
    wb.close()


def test_start_singleton_job_resolves_concurrency_limit_before_locking() -> None:
    """Regression test for the M2->M3 handoff risk: ``_resolve_max_concurrent_jobs``
    used to call ``load_settings()`` (file IO) while holding ``jobs._LOCK``,
    which would block every other project's job-start attempt for the
    duration of that file read. It must now be read before the lock.
    """
    original_load_settings = config.load_settings
    lock_state_during_calls: list[bool] = []

    def spy_load_settings():
        lock_state_during_calls.append(jobs._LOCK.locked())
        return original_load_settings()

    project = db.insert_project("Lock Order Check", "QA", "")
    done = threading.Event()

    def target(cancel_event) -> None:
        _ = cancel_event
        done.set()

    try:
        config.load_settings = spy_load_settings
        started, conflict = jobs.start_singleton_job(project["id"], "run:lock-order-check", target)
        assert started, conflict
        assert done.wait(timeout=5)
    finally:
        config.load_settings = original_load_settings

    assert lock_state_during_calls, "expected load_settings() to be invoked while starting the job"
    assert all(not locked for locked in lock_state_during_calls), (
        "load_settings() must never run while jobs._LOCK is held: " f"{lock_state_during_calls}"
    )


def test_model_fix_job_keeps_settings_snapshot_across_rerun_qa_despite_concurrent_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test for M3 batch 2: a background AI job (model-fix, which
    internally reruns QA -> semantic QA) must use ONE settings snapshot for
    its entire execution. A settings PATCH that lands between the model-fix
    provider call and the QA-rerun's semantic-QA provider call (both inside
    the SAME job) must not change which model/provider the QA-rerun sees.
    """
    workbook_path = Path(tempfile.mkdtemp()) / "project-failed.xlsx"
    _project_harness_failed_workbook(workbook_path)

    observed_models: list[str] = []
    observed_lock = threading.Lock()
    model_fix_call_started = threading.Event()
    proceed_with_qa_rerun = threading.Event()

    def fake_model(settings: dict, prompt: str) -> str:
        with observed_lock:
            observed_models.append(settings.get("model"))
        if "待修复行" in prompt:
            # This is the model-fix repair call. Signal the test to PATCH
            # settings now, then block until told to proceed, so the
            # QA-rerun's own provider call (later in this same job) happens
            # strictly after settings have changed.
            model_fix_call_started.set()
            assert proceed_with_qa_rerun.wait(timeout=10), "test did not signal to proceed in time"
            return (
                '{"fixes":[{"issue_id":"project_harness:0:Language:2:forbidden_translation",'
                '"sheet":"Language","row":2,"translation":"Reward","note":"remove forbidden phrase"}]}'
            )
        return '{"passed": true, "issues": []}'

    monkeypatch.setattr(workflow, "_call_semantic_provider", fake_model)

    with TestClient(app) as client:
        # provider=openai-chat is used (rather than plain openai) because
        # normalize_settings() forces the preset's default model for
        # "openai", ignoring a custom "model" value -- openai-chat is the
        # provider whose custom model field is respected, which this test
        # needs in order to tell the two settings snapshots apart.
        setup_response = client.patch("/api/settings", json={"provider": "openai-chat", "api_key": "test-key", "model": "gpt-before-patch"})
        assert setup_response.status_code == 200, setup_response.text
        assert setup_response.json()["model"] == "gpt-before-patch"
        project = client.post("/api/projects", json={"name": "Settings Snapshot Model Fix", "type": "QA"}).json()
        client.patch(f"/api/projects/{project['id']}/harness", json={"forbidden_translations": ["Forbidden Brand"]})
        with workbook_path.open("rb") as fh:
            translated_artifact = client.post(
                f"/api/projects/{project['id']}/files?kind=final_workbook",
                files={"file": ("project-failed.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()
        failed_run = client.post(
            "/api/runs",
            json={"project_id": project["id"], "kind": "qa", "language": "en", "input_artifact_id": translated_artifact["id"], "task_code": "QA"},
        ).json()
        assert client.post(f"/api/runs/{failed_run['id']}/qa").json()["run"]["status"] == "failed"

        start_response = client.post(f"/api/runs/{failed_run['id']}/model-fixes/start", json={"max_issues": 20, "rerun_qa": True})
        assert start_response.status_code == 200, start_response.text

        assert model_fix_call_started.wait(timeout=10), "model-fix provider call did not happen in time"
        patch_response = client.patch("/api/settings", json={"model": "gpt-after-patch"})
        assert patch_response.status_code == 200, patch_response.text
        assert patch_response.json()["model"] == "gpt-after-patch"
        proceed_with_qa_rerun.set()

        final_run = None
        for _ in range(150):
            final_run = client.get(f"/api/runs/{failed_run['id']}").json()
            if final_run["metadata"].get("model_fix_status") != "running":
                break
            time.sleep(0.1)
        assert final_run is not None
        assert final_run["metadata"]["model_fix_status"] == "passed", final_run

    # Both the model-fix repair call AND every QA-rerun semantic QA call must
    # have observed the job's original snapshot ("gpt-before-patch"), never
    # the mid-job PATCH ("gpt-after-patch") -- even though the process-wide
    # settings file was genuinely changed while this job was still running.
    assert len(observed_models) >= 2, observed_models
    assert set(observed_models) == {"gpt-before-patch"}, observed_models
    assert config.load_settings()["model"] == "gpt-after-patch"
