from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import quote

os.environ.setdefault("LWS_DATA_ROOT", str(Path(tempfile.gettempdir()) / "lws-test-data"))

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.background_jobs as background_jobs
import app.auth as auth
import app.db as db
import app.operator_context as operator_context
import app.routers.qa as qa_router
from app.config import DATA_ROOT, RuntimeProfile, bind_runtime_profile, reset_runtime_profile
from app.main import app, create_app
from app.operator_context import AUDIT_LOG_FILENAME, sanitize_operator_name
from app.schemas import ManualFixRequest, ModelFixRequest, MultilingualQueueRequest, TranslateRequest
from app.workflow.multilingual import start_multilingual_qa_queue, start_multilingual_translation_queue
from conftest import reset_data_root


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()
    yield


@pytest.fixture
def cloud_runtime_profile() -> None:
    profile = RuntimeProfile.from_environment(
        {"LWS_DEPLOYMENT_MODE": "cloud"},
        data_root=DATA_ROOT,
        app_root=Path("D:/lws-profile-tests/app"),
    )
    profile_token = bind_runtime_profile(profile)
    try:
        import app.operator_context as operator_context

        operator_context.set_current_operator("")
        yield
    finally:
        reset_runtime_profile(profile_token)


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
    cloud_runtime_profile: None,
) -> None:
    workbook = tmp_path / "untranslated.xlsx"
    _untranslated_workbook(workbook)
    project = db.insert_project("Cloud Operator", "QA", "")
    artifact = db.add_artifact(
        project["id"],
        "untranslated.xlsx",
        workbook,
        "language_table",
    )
    run = db.insert_run(
        project["id"],
        "translation",
        "en",
        metadata={"input_artifact_id": artifact["id"], "batch_size": 2},
    )
    original_status = run["status"]

    with pytest.raises(HTTPException) as exc_info:
        background_jobs.start_translation(
            run["id"],
            TranslateRequest(provider="test-fake", batch_size=2),
        )
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "请先设置操作人昵称，再启动 AI 任务。"
    assert db.get_run(run["id"])["status"] == original_status


@pytest.mark.parametrize("action", ["start", "resume"])
def test_cloud_translation_http_routes_use_authenticated_operator_nickname(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    workbook = tmp_path / "untranslated.xlsx"
    _untranslated_workbook(workbook)
    project = db.insert_project("Cloud HTTP Operator", "QA", "")
    artifact = db.add_artifact(
        project["id"],
        "untranslated.xlsx",
        workbook,
        "language_table",
    )
    run = db.insert_run(
        project["id"],
        "translation",
        "en",
        metadata={"input_artifact_id": artifact["id"], "batch_size": 2},
    )
    db.create_user(
        "http-operator",
        auth.hash_password("HTTP-Operator-Pass1!"),
        "admin",
        display_name="Alice",
    )
    test_app = create_app(RuntimeProfile("cloud", "required"))
    observed: dict[str, str] = {}

    def fake_start_translation(run_id: str, _payload: TranslateRequest) -> dict[str, object]:
        observed["run_id"] = run_id
        observed["operator"] = operator_context.current_operator()
        return db.get_run(run_id)

    monkeypatch.setattr(background_jobs, "start_translation", fake_start_translation)

    with TestClient(test_app, base_url="https://testserver") as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "http-operator", "password": "HTTP-Operator-Pass1!"},
        )
        response = client.post(
            f"/api/runs/{run['id']}/translate/{action}",
            json={"provider": "test-fake", "batch_size": 2},
        )

    assert login.status_code == 200, login.text
    assert response.status_code == 200, response.text
    assert observed == {"run_id": run["id"], "operator": "Alice"}


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [
        ("qa/start", None),
        ("model-fixes/start", {"max_issues": 20, "rerun_qa": True}),
    ],
)
def test_cloud_qa_entry_points_require_operator_without_mutating_run(
    tmp_path: Path,
    cloud_runtime_profile: None,
    endpoint: str,
    payload: dict[str, object] | None,
) -> None:
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

    original = db.get_run(run["id"])
    with pytest.raises(HTTPException) as exc_info:
        if endpoint == "qa/start":
            background_jobs.start_qa(run["id"])
        else:
            background_jobs.start_model_fix(
                run["id"],
                ModelFixRequest.model_validate(payload),
            )
    current = db.get_run(run["id"])

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "请先设置操作人昵称，再启动 AI 任务。"
    assert current["status"] == original["status"]
    assert current["metadata"] == original["metadata"]


def test_cloud_announcement_entry_points_require_operator_without_mutating_task(
    cloud_runtime_profile: None,
) -> None:
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

    with pytest.raises(HTTPException) as exc_info:
        background_jobs.start_announcement(
            task["id"],
            {"languages": ["en"], "provider": "test-fake", "batch_size": 2},
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "请先设置操作人昵称，再启动 AI 任务。"
    current = db.get_announcement_task(task["id"])
    assert current["status"] == task["status"]
    assert current["current_step"] == task["current_step"]
    assert current["metadata"] == task["metadata"]


@pytest.mark.parametrize("action", ["start", "resume"])
def test_cloud_announcement_http_routes_use_authenticated_operator_nickname(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    project = db.insert_project("Cloud Announcement HTTP Operator", "QA", "")
    task = db.insert_announcement_task(
        project["id"],
        {
            "title": "Operator route coverage",
            "selected_languages": ["en"],
            "status": "prepared",
            "current_step": 6,
        },
    )
    db.create_user(
        "announcement-operator",
        auth.hash_password("Announcement-Operator-Pass1!"),
        "admin",
        display_name="Alice",
    )
    test_app = create_app(RuntimeProfile("cloud", "required"))
    observed: dict[str, str] = {}

    def fake_start_announcement(task_id: str, _payload: object) -> dict[str, object]:
        observed["task_id"] = task_id
        observed["operator"] = operator_context.current_operator()
        return db.get_announcement_task(task_id)

    monkeypatch.setattr(background_jobs, "start_announcement", fake_start_announcement)

    with TestClient(test_app, base_url="https://testserver") as client:
        login = client.post(
            "/api/auth/login",
            json={
                "username": "announcement-operator",
                "password": "Announcement-Operator-Pass1!",
            },
        )
        response = client.post(
            f"/api/announcement-tasks/{task['id']}/translate/{action}",
            json={"languages": ["en"], "provider": "test-fake", "batch_size": 2},
        )

    assert login.status_code == 200, login.text
    assert response.status_code == 200, response.text
    assert observed == {"task_id": task["id"], "operator": "Alice"}


@pytest.mark.parametrize("workflow", ["translate", "qa"])
def test_cloud_multilingual_entry_points_require_operator_without_creating_runs(
    tmp_path: Path,
    cloud_runtime_profile: None,
    workflow: str,
) -> None:
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

    payload = MultilingualQueueRequest(
        input_artifact_id=artifact["id"],
        languages=["en"],
        batch_size=2,
    )
    with pytest.raises(HTTPException) as exc_info:
        if workflow == "translate":
            start_multilingual_translation_queue(project["id"], payload)
        else:
            start_multilingual_qa_queue(project["id"], payload)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "请先设置操作人昵称，再启动 AI 任务。"
    assert db.list_runs(project["id"]) == []


def test_cloud_manual_fix_rerun_preserves_operator_required_error(
    monkeypatch: pytest.MonkeyPatch,
    cloud_runtime_profile: None,
) -> None:
    apply_called = False

    def fake_apply(*args: object, **kwargs: object) -> dict:
        nonlocal apply_called
        apply_called = True
        return {}

    monkeypatch.setattr(qa_router.db, "get_run", lambda run_id: {"id": run_id, "project_id": "project-test"})
    monkeypatch.setattr(qa_router, "apply_manual_fixes", fake_apply)
    with pytest.raises(HTTPException) as exc_info:
        qa_router.manual_fixes_start(
            "run-test",
            ManualFixRequest.model_validate(
                {
                    "fixes": [{"sheet": "Language", "row": 2, "translation": "Reward"}],
                    "rerun_qa": True,
                }
            ),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "请先设置操作人昵称，再启动 AI 任务。"
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
