from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import pytest
import httpx
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.db as db
import app.workflow as workflow
import app.workflow.line_proofread as line_proofread
from app.config import DEFAULT_SETTINGS, save_settings
from app.main import app
from app.providers import TranslationItem
from conftest import reset_data_root, wait_for_background_jobs


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()
    save_settings(DEFAULT_SETTINGS)
    yield
    wait_for_background_jobs()
    save_settings(DEFAULT_SETTINGS)


@pytest.mark.parametrize("qa_pass", [1, 2], ids=["initial-qa", "proofread-qa"])
@pytest.mark.parametrize("cancel_boundary", ["before_qa", "after_machine_review", "after_semantic", "before_archive", "not_canceled"])
def test_translation_cancellation_stops_embedded_qa_before_further_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qa_pass: int,
    cancel_boundary: str,
) -> None:
    workbook = tmp_path / "source.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Language"
    ws.append(["ID", "CN", "EN"])
    ws.append([1, "开始游戏", ""])
    wb.save(workbook)
    wb.close()

    boundary_reached = threading.Event()
    release_worker = threading.Event()
    cancel_issued = threading.Event()
    worker_cancel_events: list[threading.Event] = []
    qa_calls: list[dict[str, Any]] = []
    semantic_calls_after_cancel: list[str] = []
    original_qa = workflow.run_localization_qa
    original_subprocess = workflow.run_subprocess
    original_translate = workflow.run_translate_sync
    original_add_artifact = db.add_artifact

    def observed_translation(*args: Any, **kwargs: Any) -> dict[str, Any]:
        worker_cancel_events.append(kwargs["cancel_event"])
        return original_translate(*args, **kwargs)

    def pause_at_cancel_boundary() -> None:
        boundary_reached.set()
        if not release_worker.wait(10.0):
            raise AssertionError("test did not release the QA boundary")

    def observed_qa(*args: Any, **kwargs: Any) -> dict[str, Any]:
        qa_calls.append({
            "cancel_event_supplied": kwargs.get("cancel_event") is not None,
            "same_worker_event": kwargs.get("cancel_event") is worker_cancel_events[-1],
        })
        if len(qa_calls) == qa_pass and cancel_boundary == "before_qa":
            pause_at_cancel_boundary()
        return original_qa(*args, **kwargs)

    def observed_subprocess(args: list[str], *rest: Any, **kwargs: Any) -> Any:
        result = original_subprocess(args, *rest, **kwargs)
        if (
            len(qa_calls) == qa_pass
            and cancel_boundary == "after_machine_review"
            and Path(args[1]).name == "process_language.py"
        ):
            pause_at_cancel_boundary()
        return result

    def observed_add_artifact(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_add_artifact(*args, **kwargs)
        if (
            cancel_boundary == "before_archive"
            and len(qa_calls) == qa_pass
            and len(args) > 3
            and args[3] == "translation_manifest"
        ):
            pause_at_cancel_boundary()
        return result

    async def local_translation_provider(batch: list[dict[str, Any]], *_args: Any) -> list[TranslationItem]:
        return [TranslationItem(id=row["id"], translation="Start Game") for row in batch]

    def local_text_provider(_settings: dict[str, Any], prompt: str, **_kwargs: Any) -> str:
        if "semantic QA" in prompt:
            if cancel_issued.is_set():
                semantic_calls_after_cancel.append(prompt)
            if len(qa_calls) == qa_pass and cancel_boundary == "after_semantic":
                pause_at_cancel_boundary()
            return json.dumps({"passed": True, "issues": []})
        return json.dumps({"suggestions": [{
            "record_id": "1",
            "sheet": "Language",
            "row": 2,
            "suggested_target": "Start the Game",
            "reason": "Natural button text",
        }]})

    def reject_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("unexpected network request from cancellation regression")

    async def reject_async_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("unexpected network request from cancellation regression")

    monkeypatch.setattr(workflow, "run_localization_qa", observed_qa)
    monkeypatch.setattr(workflow, "run_translate_sync", observed_translation)
    monkeypatch.setattr(workflow, "run_subprocess", observed_subprocess)
    monkeypatch.setattr(db, "add_artifact", observed_add_artifact)
    monkeypatch.setattr(workflow, "translate_batch", local_translation_provider)
    monkeypatch.setattr(workflow, "call_text", local_text_provider)
    monkeypatch.setattr(line_proofread, "call_text", local_text_provider)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", reject_network)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", reject_async_network)
    save_settings({
        **DEFAULT_SETTINGS,
        "provider": "openai",
        "api_key": "test-only-local-provider-stub",
        "model": "local-provider-stub",
        "max_batch_attempts": 1,
    })

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Embedded QA cancellation", "type": "QA"}).json()
        with workbook.open("rb") as source:
            artifact = client.post(
                f"/api/projects/{project['id']}/files?kind=language_table",
                files={"file": (workbook.name, source, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()
        run = client.post("/api/runs", json={
            "project_id": project["id"],
            "kind": "translation",
            "language": "en",
            "input_artifact_id": artifact["id"],
        }).json()
        started = client.post(f"/api/runs/{run['id']}/translate/start", json={
            "enable_line_proofread": qa_pass == 2,
            "confirm_api_budget": True,
            "confirm_term_gap": True,
        })
        assert started.status_code == 200, started.text
        try:
            if cancel_boundary != "not_canceled":
                assert boundary_reached.wait(15.0), client.get(f"/api/runs/{run['id']}").json()
                canceled = client.post(f"/api/runs/{run['id']}/translate/cancel")
                assert canceled.status_code == 200, canceled.text
                cancel_issued.set()
                assert worker_cancel_events[-1].is_set()
        finally:
            release_worker.set()
        wait_for_background_jobs()
        final = client.get(f"/api/runs/{run['id']}").json()
        archive = client.get(f"/api/projects/{project['id']}/translations").json()

    observed = {
        "semantic_calls_after_cancel": len(semantic_calls_after_cancel),
        "archived_rows": len(archive),
        "final_status": final["status"],
    }
    assert observed == {
        "semantic_calls_after_cancel": 0,
        "archived_rows": 1 if cancel_boundary == "not_canceled" else 0,
        "final_status": "passed" if cancel_boundary == "not_canceled" else "canceled",
    }, json.dumps({"observed": observed, "qa_calls": qa_calls})
    assert all(call["same_worker_event"] for call in qa_calls)
