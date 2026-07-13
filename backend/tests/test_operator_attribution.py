from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("LWS_DATA_ROOT", str(Path(tempfile.gettempdir()) / "lws-test-data"))

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.db as db
from app.config import DATA_ROOT
from app.main import app
from app.operator_context import AUDIT_LOG_FILENAME, sanitize_operator_name
from conftest import reset_data_root


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


def _events_text(client: TestClient, run_id: str) -> str:
    events = client.get(f"/api/runs/{run_id}/events").json()
    return "\n".join(str(event.get("message") or "") for event in events)


def test_sanitize_operator_name_strips_control_chars_and_caps_length() -> None:
    assert sanitize_operator_name("  Alice\n\t ") == "Alice"
    assert sanitize_operator_name("x" * 100) == "x" * 40
    assert sanitize_operator_name(None) == ""
    assert sanitize_operator_name("") == ""


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
