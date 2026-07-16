from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import quote

os.environ.setdefault("LWS_DATA_ROOT", str(Path(tempfile.gettempdir()) / "lws-test-data"))

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.db as db
import app.routers.qa as qa_router
from app.config import DATA_ROOT
from app.main import app
from app.operator_context import AUDIT_LOG_FILENAME, sanitize_operator_name
from conftest import reset_data_root, wait_for_background_jobs


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()
    yield


def _translated_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Language"
    ws.append(["ID", "cn", "en"])
    ws.append([1, "\u9886\u53d6\u5956\u52b1", "Claim Rewards"])
    ws.append([2, "\u5f00\u59cb\u6e38\u620f", "Start Game"])
    wb.save(path)
    wb.close()


def _untranslated_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Language"
    ws.append(["ID", "cn", "en"])
    ws.append([1, "领取奖励", ""])
    ws.append([2, "开始游戏", ""])
    wb.save(path)
    wb.close()


def _events_text(client: TestClient, run_id: str) -> str:
    events = client.get(f"/api/runs/{run_id}/events").json()
    return "\n".join(str(event.get("message") or "") for event in events)


def test_sanitize_operator_name_strips_control_chars_and_caps_length() -> None:
    assert sanitize_operator_name("  Alice\n\t ") == "Alice"
    assert sanitize_operator_name("x" * 100) == "x" * 40
    assert sanitize_operator_name(None) == ""
    assert sanitize_operator_name("") == ""


def test_cloud_translation_start_requires_operator_before_status_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LWS_DEPLOYMENT_MODE", "cloud")
    workbook = tmp_path / "untranslated.xlsx"
    _untranslated_workbook(workbook)

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Cloud Operator", "type": "QA"}).json()
        with workbook.open("rb") as fh:
            artifact = client.post(
                f"/api/projects/{project['id']}/files?kind=language_table",
                files={"file": ("untranslated.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()
        run = client.post(
            "/api/runs",
            json={
                "project_id": project["id"],
                "kind": "translation",
                "language": "en",
                "input_artifact_id": artifact["id"],
                "batch_size": 2,
            },
        ).json()
        original_status = run["status"]

        for action in ("start", "resume"):
            rejected = client.post(
                f"/api/runs/{run['id']}/translate/{action}",
                json={"provider": "test-fake", "batch_size": 2},
            )
            assert rejected.status_code == 400
            assert rejected.json()["detail"] == "请先设置操作人昵称，再启动 AI 任务。"
            assert client.get(f"/api/runs/{run['id']}").json()["status"] == original_status

        started = client.post(
            f"/api/runs/{run['id']}/translate/start",
            json={"provider": "test-fake", "batch_size": 2},
            headers={"X-Operator": "Alice"},
        )
        assert started.status_code == 200, started.text

    wait_for_background_jobs()


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [
        ("qa/start", None),
        ("model-fixes/start", {"max_issues": 20, "rerun_qa": True}),
    ],
)
def test_cloud_qa_entry_points_require_operator_without_mutating_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    payload: dict[str, object] | None,
) -> None:
    monkeypatch.setenv("LWS_DEPLOYMENT_MODE", "cloud")
    workbook = tmp_path / "translated.xlsx"
    _translated_workbook(workbook)
    project = db.insert_project("Cloud QA Operator", "QA", "")
    artifact = db.add_artifact(
        project["id"],
        "source",
        workbook,
        "final_workbook",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    run = db.insert_run(
        project["id"],
        "qa",
        "en",
        metadata={"input_artifact_id": artifact["id"]},
    )
    db.update_run(run["id"], status="needs_input")

    with TestClient(app) as client:
        original = db.get_run(run["id"])
        response = client.post(f"/api/runs/{run['id']}/{endpoint}", json=payload)
        current = db.get_run(run["id"])

    assert response.status_code == 400
    assert response.json()["detail"] == "请先设置操作人昵称，再启动 AI 任务。"
    assert current["status"] == original["status"]
    assert current["metadata"] == original["metadata"]


@pytest.mark.parametrize("action", ["start", "resume"])
def test_cloud_announcement_entry_points_require_operator_without_mutating_task(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    monkeypatch.setenv("LWS_DEPLOYMENT_MODE", "cloud")
    project = db.insert_project("Cloud Announcement Operator", "QA", "")
    task = db.insert_announcement_task(
        project["id"],
        {
            "title": "Operator gate",
            "selected_languages": ["en"],
            "status": "prepared",
            "current_step": 6,
            "metadata": {"prepared": True},
        },
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/announcement-tasks/{task['id']}/translate/{action}",
            json={"languages": ["en"], "provider": "test-fake", "batch_size": 2},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "请先设置操作人昵称，再启动 AI 任务。"
    current = db.get_announcement_task(task["id"])
    assert current["status"] == task["status"]
    assert current["current_step"] == task["current_step"]
    assert current["metadata"] == task["metadata"]


@pytest.mark.parametrize("workflow", ["translate", "qa"])
def test_cloud_multilingual_entry_points_require_operator_without_creating_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workflow: str,
) -> None:
    monkeypatch.setenv("LWS_DEPLOYMENT_MODE", "cloud")
    workbook = tmp_path / "multilingual.xlsx"
    _untranslated_workbook(workbook)
    project = db.insert_project("Cloud Multilingual Operator", "QA", "")
    artifact = db.add_artifact(
        project["id"],
        "source",
        workbook,
        "language_table",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/projects/{project['id']}/multilingual/{workflow}/start",
            json={"input_artifact_id": artifact["id"], "languages": ["en"], "batch_size": 2},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "请先设置操作人昵称，再启动 AI 任务。"
    assert db.list_runs(project["id"]) == []


def test_cloud_manual_fix_rerun_preserves_operator_required_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LWS_DEPLOYMENT_MODE", "cloud")
    apply_called = False

    def fake_apply(*args: object, **kwargs: object) -> dict:
        nonlocal apply_called
        apply_called = True
        return {}

    with TestClient(app) as client:
        monkeypatch.setattr(qa_router.db, "get_run", lambda run_id: {"id": run_id, "project_id": "project-test"})
        monkeypatch.setattr(qa_router, "apply_manual_fixes", fake_apply)
        response = client.post(
            "/api/runs/run-test/manual-fixes/start",
            json={"fixes": [{"sheet": "Language", "row": 2, "translation": "Reward"}], "rerun_qa": True},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "请先设置操作人昵称，再启动 AI 任务。"
    assert apply_called is False


def test_run_creation_event_is_prefixed_with_operator_nickname_when_header_present(tmp_path: Path) -> None:
    workbook = tmp_path / "translated.xlsx"
    _translated_workbook(workbook)

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Operator Attribution", "type": "QA"}).json()
        with workbook.open("rb") as fh:
            artifact = client.post(
                f"/api/projects/{project['id']}/files?kind=final_workbook",
                files={"file": ("translated.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()

        run_with_operator = client.post(
            "/api/runs",
            json={"project_id": project["id"], "kind": "qa", "language": "en", "input_artifact_id": artifact["id"]},
            headers={"X-Operator": "Alice"},
        ).json()
        assert "[Alice] run created" in _events_text(client, run_with_operator["id"])

        run_without_operator = client.post(
            "/api/runs",
            json={"project_id": project["id"], "kind": "translation", "language": "en", "input_artifact_id": artifact["id"]},
        ).json()
        events = client.get(f"/api/runs/{run_without_operator['id']}/events").json()
        creation_messages = [str(event.get("message") or "") for event in events if "run created" in str(event.get("message") or "")]
        assert creation_messages == ["run created (kind=translation)"]


def test_percent_encoded_unicode_operator_header_is_decoded_before_attribution() -> None:
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Unicode Operator", "type": "QA"}).json()
        run = client.post(
            "/api/runs",
            json={"project_id": project["id"], "kind": "translation", "language": "en"},
            headers={"X-Operator": quote("张三", safe="")},
        ).json()

        assert "[张三] run created" in _events_text(client, run["id"])


def test_delivery_event_is_prefixed_with_operator_nickname(tmp_path: Path) -> None:
    workbook = tmp_path / "translated.xlsx"
    _translated_workbook(workbook)

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Operator Delivery", "type": "QA"}).json()
        with workbook.open("rb") as fh:
            artifact = client.post(
                f"/api/projects/{project['id']}/files?kind=final_workbook",
                files={"file": ("translated.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()
        run = client.post(
            "/api/runs",
            json={"project_id": project["id"], "kind": "qa", "language": "en", "input_artifact_id": artifact["id"]},
        ).json()
        qa_response = client.post(f"/api/runs/{run['id']}/qa")
        assert qa_response.status_code == 200, qa_response.text

        package_response = client.post(
            f"/api/projects/{project['id']}/delivery-package?run_id={run['id']}",
            headers={"X-Operator": "Bob"},
        )
        assert package_response.status_code == 200, package_response.text

        events_text = _events_text(client, run["id"])
        assert "[Bob] delivery translation archive updated" in events_text


def test_delete_project_with_operator_header_writes_audit_log_entry() -> None:
    audit_path = DATA_ROOT / AUDIT_LOG_FILENAME
    audit_path.unlink(missing_ok=True)

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Operator Delete Me", "type": "QA"}).json()
        response = client.delete(f"/api/projects/{project['id']}", headers={"X-Operator": "Carol"})
        assert response.status_code == 200
        assert response.json()["deleted"] is True

    assert audit_path.exists()
    entries = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    matching = [entry for entry in entries if entry.get("action") == "delete_project" and entry.get("detail", {}).get("project_id") == project["id"]]
    assert len(matching) == 1
    assert matching[0]["operator"] == "Carol"
    assert matching[0]["detail"]["project_name"] == "Operator Delete Me"


def test_delete_project_without_operator_header_does_not_write_audit_log_entry() -> None:
    audit_path = DATA_ROOT / AUDIT_LOG_FILENAME
    audit_path.unlink(missing_ok=True)

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Operator Delete No Header", "type": "QA"}).json()
        response = client.delete(f"/api/projects/{project['id']}")
        assert response.status_code == 200

    assert not audit_path.exists()
