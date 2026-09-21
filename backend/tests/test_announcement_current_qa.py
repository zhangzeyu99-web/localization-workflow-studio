from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.db as db
from app.config import DEFAULT_SETTINGS, save_settings
from app.main import app
from app.workflow.announcement import _announcement_hard_blocker_count
from conftest import reset_data_root, wait_for_background_jobs


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch: pytest.MonkeyPatch):
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()
    save_settings(DEFAULT_SETTINGS)

    def reject_network(*_args, **_kwargs):
        raise AssertionError("unexpected external HTTP request in announcement QA regression")

    async def reject_async_network(*_args, **_kwargs):
        raise AssertionError("unexpected external HTTP request in announcement QA regression")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", reject_network)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", reject_async_network)
    yield
    wait_for_background_jobs()
    save_settings(DEFAULT_SETTINGS)


@pytest.mark.parametrize("current_has_blocker", [False, True], ids=["repaired", "regressed"])
def test_delivery_uses_reapplied_current_qa_not_historical_failure(current_has_blocker: bool) -> None:
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Current announcement QA", "type": "announcement"}).json()
        glossary = client.post(f"/api/projects/{project['id']}/glossary", json={
            "source": "菇勇者传说", "target": "Legend of Mushroom", "language": "en",
            "source_type": "manual", "confirmed": True,
        })
        assert glossary.status_code == 200, glossary.text
        created = client.post(f"/api/projects/{project['id']}/announcement-tasks", json={
            "text": "《菇勇者传说》联动公告", "languages": ["en"], "include_project_archive": True,
        })
        assert created.status_code == 200, created.text
        task_id = created.json()["id"]
        for action in ["extract-terms", "lookup-translations", "prepare"]:
            response = client.post(f"/api/announcement-tasks/{task_id}/{action}", json={
                "languages": ["en"], "include_project_archive": True, "ai_supplement": False,
            })
            assert response.status_code == 200, response.text
        workpack = next(item for item in response.json()["artifacts"] if item["kind"] == "announcement_workpack")
        rows = [json.loads(line) for line in Path(workpack["path"]).read_text(encoding="utf-8").splitlines()]
        qa_ids = []
        for has_blocker in [not current_has_blocker, current_has_blocker]:
            translation = "Shroomie Legendary" if has_blocker else "Legend of Mushroom collaboration announcement"
            payload = "\n".join(json.dumps({"para_id": row["para_id"], "translation": translation}) for row in rows)
            uploaded = client.post(f"/api/projects/{project['id']}/files?kind=asset", files={
                "file": ("response.jsonl", payload.encode("utf-8"), "application/jsonl"),
            })
            assert uploaded.status_code == 200, uploaded.text
            imported = client.post(f"/api/announcement-tasks/{task_id}/import-ai", json={
                "languages": ["en"], "response_artifact_ids": [uploaded.json()["id"]],
            })
            assert imported.status_code == 200, imported.text
            applied = client.post(f"/api/announcement-tasks/{task_id}/apply", json={"languages": ["en"]})
            assert applied.status_code == 200, applied.text
            task = applied.json()["task"]
            qa_id = task["metadata"]["qa_summary_artifact_id"]
            qa_ids.append(qa_id)
            assert task["metadata"]["hard_blockers"] == int(has_blocker)
            assert task["languages"][0]["metadata"]["qa_summary_artifact_id"] == qa_id
            assert task["languages"][0]["metadata"]["hard_blockers"] == int(has_blocker)
        assert qa_ids[0] != qa_ids[1]
        assert db.get_artifact(qa_ids[0])["kind"] == "announcement_qa_summary"

        delivered = client.post(f"/api/announcement-tasks/{task_id}/deliver", json={"languages": ["en"]})
        assert delivered.status_code == 200, delivered.text
        assert delivered.json()["summary"]["hard_blockers"] == int(current_has_blocker)
        assert delivered.json()["summary"]["forced"] is current_has_blocker
        package_metadata = delivered.json()["artifacts"][0]["metadata"]
        assert bool(package_metadata.get("forced")) is current_has_blocker


@pytest.mark.parametrize("case, expected", [
    ("current_zero", 0), ("current_positive", 3), ("task_positive", 2),
    ("current_issues", 2), ("current_child", 2), ("legacy_child", 2),
    ("historical_child", 0), ("missing_pointer", 5), ("dangling_pointer", 5),
    ("wrong_task", 5), ("wrong_kind", 5), ("missing_count", 5), ("invalid_count", 5),
])
def test_current_qa_selection_keeps_current_and_legacy_blocker_evidence(
    monkeypatch: pytest.MonkeyPatch, case: str, expected: int,
) -> None:
    metadata = {"qa_summary_artifact_id": "current", "hard_blockers": 0, "qa_issues": []}
    current = {"id": "current", "project_id": "project", "kind": "announcement_qa_summary", "metadata": {"task_id": "task", "hard_blockers": 0}}
    old = {"id": "old", "project_id": "project", "kind": "announcement_qa_summary", "metadata": {"task_id": "task", "hard_blockers": 5, "superseded": True}}
    task = {"id": "task", "project_id": "project", "metadata": metadata, "languages": []}
    if case == "current_positive":
        current["metadata"]["hard_blockers"] = 3
    elif case == "task_positive":
        metadata["hard_blockers"] = 2
    elif case == "current_issues":
        metadata["qa_issues"] = [{"severity": "hard"}, {}]
    elif case in {"current_child", "legacy_child", "historical_child"}:
        child_metadata = {"hard_blockers": 2}
        if case != "legacy_child":
            child_metadata["qa_summary_artifact_id"] = "old" if case == "historical_child" else "current"
        task["languages"] = [{"language": "en", "metadata": child_metadata}]
    elif case == "missing_pointer":
        metadata.pop("qa_summary_artifact_id")
    elif case == "dangling_pointer":
        metadata["qa_summary_artifact_id"] = "missing"
    elif case == "wrong_task":
        current["metadata"]["task_id"] = "other-task"
    elif case == "wrong_kind":
        current["kind"] = "asset"
    elif case == "missing_count":
        current["metadata"].pop("hard_blockers")
    elif case == "invalid_count":
        current["metadata"]["hard_blockers"] = "unknown"
    monkeypatch.setattr(db, "list_artifacts", lambda **_kwargs: [current, old])

    assert _announcement_hard_blocker_count(task, metadata) == expected
