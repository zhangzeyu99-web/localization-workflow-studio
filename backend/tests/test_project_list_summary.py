from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth, config, db
from app.main import app, create_app
from conftest import reset_data_root


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()


def _seed_project(name: str, tmp_path: Path) -> dict:
    project = db.insert_project(name, "QA", "")
    project_id = project["id"]
    source = db.insert_run(project_id, "translation", metadata={"large_payload": "x" * 10000})
    for key in ("source_run_id", "manual_fix_source_run_id", "model_fix_source_run_id"):
        db.insert_run(project_id, "qa", metadata={key: source["id"]})
    db.insert_run(project_id, "translation", metadata={"translation_task_id": "quick-task-example"})
    db.insert_run(project_id, "qa", metadata={"announcement_task_id": "legacy-announcement"})
    db.insert_run(project_id, "glossary")
    delivery = db.add_artifact(project_id, "delivery", tmp_path / "result.xlsx", "qa_final_workbook", source["id"])
    db.add_artifact(project_id, "same run result", tmp_path / "result.json", "qa_result", source["id"])
    for status in ("delivered", "canceled", "draft"):
        db.insert_announcement_task(project_id, {
            "status": status,
            "selected_languages": ["en", "fr"],
            "metadata": {"delivery_artifact_id": delivery["id"], "translate_run_id": source["id"]},
        })
    for language in ("en", "fr"):
        db.upsert_translation_entry(project_id, {
            "entry_key": "A1", "source": "测 试\n文本", "target": "Text", "language": language,
        })
    db.upsert_glossary_term(project_id, {
        "term_key": "T1", "source": "测试", "target": "Test", "language": "en", "confirmed": True,
    })
    return project


def test_project_list_matches_detail_statistics_without_per_project_detail_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(app) as client:
        projects = [_seed_project(f"summary-{index}", tmp_path) for index in range(4)]
        expected = {project["id"]: client.get(f"/api/projects/{project['id']}").json() for project in projects}
        statements: list[str] = []
        original_connect = db.connect

        @contextmanager
        def traced_connect():
            with original_connect() as conn:
                conn.set_trace_callback(lambda sql: statements.append(sql) if sql.lstrip().upper().startswith("SELECT") else None)
                yield conn

        with monkeypatch.context() as patch:
            patch.setattr(db, "connect", traced_connect)
            response = client.get("/api/projects")
        assert response.status_code == 200, response.text
        summaries = response.json()
        assert [item["id"] for item in summaries] == [item["id"] for item in db.list_projects()]
        for item in summaries:
            detail = expected[item["id"]]
            assert item["stats"] == detail["stats"]
            assert item["stats"] == {
                "tasks": 4, "execution_runs": 7, "language_tasks": 2, "deliverables": 2,
                "announcement_tasks": 2, "translation_runs": 2, "qa_runs": 4,
                "words": "8", "archived_rows": 2, "langs": 2, "glossary": 1,
            }
            assert not {"runs", "artifacts", "announcement_tasks", "translations", "glossary"} & item.keys()
            assert len(detail["runs"]) == 7
            assert len(detail["announcement_tasks"]) == 3
            assert detail["announcement_tasks"][0]["languages"]
            assert detail["announcement_tasks"][0]["artifacts"]
        # Listing four projects should take a bounded set of aggregate reads,
        # independent of the number of announcement languages and artifacts.
        assert len(statements) <= 8, f"summary issued {len(statements)} SELECT queries"


@pytest.mark.parametrize("role", ["member", "ops"])
def test_project_summaries_only_include_authorized_projects(role: str, tmp_path: Path) -> None:
    password = "Summary-Test-Password!"
    db.create_user("summary-admin", auth.hash_password(password), "admin")
    user = db.create_user(f"summary-{role}", auth.hash_password(password), role)
    allowed = _seed_project("visible-summary", tmp_path)
    hidden = _seed_project("hidden-summary", tmp_path)
    db.add_project_member(allowed["id"], user["id"])
    required_app = create_app(config.RuntimeProfile("local", "required"))
    with TestClient(required_app) as client:
        login = client.post("/api/auth/login", json={"username": user["username"], "password": password})
        assert login.status_code == 200, login.text
        summaries = client.get("/api/projects")
        assert summaries.status_code == 200, summaries.text
        assert [item["id"] for item in summaries.json()] == [allowed["id"]]
        detail = client.get(f"/api/projects/{allowed['id']}")
        assert detail.status_code == 200, detail.text
        assert summaries.json()[0]["stats"] == detail.json()["stats"]
        assert client.get(f"/api/projects/{hidden['id']}").status_code == 404
        client.post("/api/auth/logout")
        admin_login = client.post("/api/auth/login", json={"username": "summary-admin", "password": password})
        assert admin_login.status_code == 200, admin_login.text
        assert {item["id"] for item in client.get("/api/projects").json()} == {allowed["id"], hidden["id"]}
