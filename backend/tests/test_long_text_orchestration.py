from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
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
from app.providers import TranslationItem


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    data_root = Path(os.environ["LWS_DATA_ROOT"])
    if data_root.exists():
        shutil.rmtree(data_root)
    db.init_db()
    save_settings(DEFAULT_SETTINGS)
    yield
    save_settings(DEFAULT_SETTINGS)


def test_dynamic_manifest_splits_8000_rows_without_single_row_overhead() -> None:
    rows = [{"id": index, "source": f"公告按钮 {index}"} for index in range(8000)]
    settings = {**DEFAULT_SETTINGS, "batch_size": 90, "max_batch_input_tokens": 12000}

    manifest = workflow._build_batch_manifest(rows, "Project prompt", settings, batch_size=90, language="en")

    batches = manifest["batches"]
    assert 80 <= len(batches) <= 200
    assert all(batch["row_count"] > 1 for batch in batches)
    assert sum(batch["row_count"] for batch in batches) == 8000
    assert manifest["estimated_total_input_tokens"] > 0


def test_orchestrator_caps_concurrency_and_resumes_completed_batches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = db.insert_project("E2E Long Text", "QA", "", "🎮")
    run = db.insert_run(project["id"], "translation", "en", metadata={})
    rows = [{"id": index, "source": f"按钮 {index} {{count}}"} for index in range(12)]
    settings = {
        **DEFAULT_SETTINGS,
        "provider": "test-fake",
        "batch_size": 2,
        "max_concurrent_batches": 2,
        "max_requests_per_minute": 120,
        "max_estimated_tokens_per_minute": 2_000_000,
        "api_budget_warning_tokens": 20_000_000,
        "max_batch_attempts": 2,
    }
    state = {"active": 0, "max_active": 0, "calls": 0}

    async def fake_translate_batch(batch, provider_settings, project_prompt):
        _ = provider_settings, project_prompt
        state["calls"] += 1
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        await asyncio.sleep(0.01)
        state["active"] -= 1
        return [TranslationItem(id=row["id"], translation=f"Translated {row['id']} {{count}}") for row in batch]

    monkeypatch.setattr(workflow, "translate_batch", fake_translate_batch)

    result = asyncio.run(
        workflow._translate_rows_with_orchestration(
            run_id=run["id"],
            rows=rows,
            settings=settings,
            project_prompt="Translate.",
            work_dir=tmp_path,
            batch_size=2,
            language="en",
            confirm_api_budget=True,
        )
    )
    assert len(result) == 12
    assert state["max_active"] == 2
    assert state["calls"] == 6

    resumed = asyncio.run(
        workflow._translate_rows_with_orchestration(
            run_id=run["id"],
            rows=rows,
            settings=settings,
            project_prompt="Translate.",
            work_dir=tmp_path,
            batch_size=2,
            language="en",
            confirm_api_budget=True,
        )
    )
    assert len(resumed) == 12
    assert state["calls"] == 6


def test_orchestrator_pauses_before_api_when_budget_requires_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = db.insert_project("E2E Budget", "QA", "", "🎮")
    run = db.insert_run(project["id"], "translation", "en", metadata={})
    rows = [{"id": index, "source": "很长的公告正文" * 20} for index in range(5)]
    settings = {**DEFAULT_SETTINGS, "provider": "test-fake", "api_budget_warning_tokens": 10}

    async def fail_if_called(batch, provider_settings, project_prompt):
        _ = batch, provider_settings, project_prompt
        raise AssertionError("provider should not be called before budget confirmation")

    monkeypatch.setattr(workflow, "translate_batch", fail_if_called)

    result = asyncio.run(
        workflow._translate_rows_with_orchestration(
            run_id=run["id"],
            rows=rows,
            settings=settings,
            project_prompt="Translate.",
            work_dir=tmp_path,
            batch_size=90,
            language="en",
            confirm_api_budget=False,
        )
    )
    updated = db.get_run(run["id"])
    assert result == []
    assert updated["status"] == "needs_input"
    assert updated["metadata"]["reason"] == "api_budget_confirmation_required"


def test_batch_validation_blocks_missing_tokens_and_untranslated_en() -> None:
    batch = [{"id": "A-1", "source": "领取奖励 {count}\\n"}]
    with pytest.raises(ValueError, match="lost structural token"):
        workflow._validate_translated_batch(batch, [{"id": "A-1", "translation": "Claim Rewards"}], "en")
    with pytest.raises(ValueError, match="obvious Chinese"):
        workflow._validate_translated_batch(batch, [{"id": "A-1", "translation": "领取奖励 {count}\\n"}], "en")


def test_rate_limiter_does_not_deadlock_when_single_batch_exceeds_tpm() -> None:
    limiter = workflow._AsyncTokenRateLimiter(requests_per_minute=1, tokens_per_minute=1000)

    waited = asyncio.run(limiter.acquire(5000))

    assert waited == 0


def test_provider_retry_delay_handles_rate_limit_and_generic_errors() -> None:
    assert workflow._provider_retry_delay_seconds(RuntimeError("responses failed: 429 rate limit"), 1) >= 3
    assert workflow._provider_retry_delay_seconds(RuntimeError("bad json"), 1) >= 1


def test_translate_start_returns_immediately_and_background_job_finishes(tmp_path: Path) -> None:
    workbook = tmp_path / "async-language.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Language"
    ws.append(["ID", "cn", "en"])
    for index in range(1, 7):
        ws.append([index, f"按钮 {index}", ""])
    wb.save(workbook)
    wb.close()

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "E2E Async Long", "type": "QA"}).json()
        with workbook.open("rb") as fh:
            artifact = client.post(
                f"/api/projects/{project['id']}/files?kind=language_table",
                files={"file": ("async-language.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()
        run = client.post(
            "/api/runs",
            json={"project_id": project["id"], "kind": "translation", "language": "en", "input_artifact_id": artifact["id"], "batch_size": 2},
        ).json()
        started = client.post(f"/api/runs/{run['id']}/translate/start", json={"provider": "test-fake", "batch_size": 2})
        assert started.status_code == 200, started.text
        assert started.json()["status"] in {"queued", "running"}

        terminal = None
        for _ in range(80):
            current = client.get(f"/api/runs/{run['id']}").json()
            if current["status"] in {"passed", "failed", "needs_input", "canceled"}:
                terminal = current
                break
            time.sleep(0.25)
        assert terminal is not None
        assert terminal["status"] == "passed"
        assert terminal["metadata"]["translation_progress"]["completed_batches"] == 3
        request_download = client.get(f"/api/runs/{run['id']}/translate/batches/1/request")
        assert request_download.status_code == 200
        response_download = client.get(f"/api/runs/{run['id']}/translate/batches/1/response")
        assert response_download.status_code == 200


def test_failed_batch_keeps_request_raw_response_and_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = db.insert_project("E2E Failed Batch", "QA", "", "🎮")
    run = db.insert_run(project["id"], "translation", "en", metadata={})
    rows = [{"id": 1, "source": "领取 {count}"}]
    settings = {**DEFAULT_SETTINGS, "provider": "test-fake", "max_batch_attempts": 1, "api_budget_warning_tokens": 20_000_000}

    async def bad_translate_batch(batch, provider_settings, project_prompt):
        _ = batch, provider_settings, project_prompt
        return [TranslationItem(id=1, translation="Claim")]

    monkeypatch.setattr(workflow, "translate_batch", bad_translate_batch)
    with pytest.raises(ValueError, match="lost structural token"):
        asyncio.run(
            workflow._translate_rows_with_orchestration(
                run_id=run["id"],
                rows=rows,
                settings=settings,
                project_prompt="Translate.",
                work_dir=tmp_path,
                batch_size=1,
                language="en",
                confirm_api_budget=True,
            )
        )
    batch_dir = tmp_path / "batches_1"
    assert (batch_dir / "batch_00001.request.jsonl").exists()
    assert (batch_dir / "batch_00001.raw_response.jsonl").exists()
    assert (batch_dir / "batch_00001.error.json").exists()


def test_reconcile_interrupted_background_jobs_marks_resume_state() -> None:
    project = db.insert_project("E2E Reconcile", "QA", "", "🎮")
    run = db.insert_run(project["id"], "translation", "en", metadata={})
    db.update_run(run["id"], status="running", metadata={"input_artifact_id": "art_missing"})
    task = db.insert_announcement_task(
        project["id"],
        {
            "title": "公告",
            "source_artifact_id": "art_missing",
            "source_format": "txt",
            "selected_languages": ["en"],
            "status": "running",
            "current_step": 7,
            "metadata": {},
        },
    )
    db.upsert_announcement_task_language(task["id"], project["id"], "en", status="running", current_step=7)

    summary = workflow.reconcile_interrupted_background_jobs()

    assert summary == {"translation_runs": 1, "announcement_tasks": 1}
    assert db.get_run(run["id"])["status"] == "needs_input"
    updated_task = db.get_announcement_task(task["id"])
    assert updated_task["status"] == "needs_input"
    assert updated_task["languages"][0]["status"] == "prepared"


def test_cancel_announcement_translation_keeps_task_resumable() -> None:
    project = db.insert_project("E2E Announcement Cancel", "QA", "", "🎮")
    task = db.insert_announcement_task(
        project["id"],
        {
            "title": "公告",
            "source_artifact_id": "art_missing",
            "source_format": "txt",
            "selected_languages": ["en"],
            "status": "running",
            "current_step": 7,
            "metadata": {},
        },
    )
    db.upsert_announcement_task_language(task["id"], project["id"], "en", status="running", current_step=7)

    result = workflow.cancel_announcement_translation_task(task["id"])["task"]

    assert result["status"] == "prepared"
    assert result["current_step"] == 7
    assert result["languages"][0]["status"] == "prepared"
    assert result["metadata"]["reason"] == "announcement_translation_canceled"
