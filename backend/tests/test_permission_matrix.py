from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.auth as auth
import app.db as db
import app.main as main_module
from app.workflow import project_dir
from conftest import reset_data_root

ADMIN_PASSWORD = "Initial-Admin-Password!"
USER_PASSWORD = "Sup3rSecret1!"

_AUTH_ENV_VARS = (
    "LWS_AUTH_MODE",
    "LWS_DEPLOYMENT_MODE",
    "LWS_ADMIN_USER",
    "LWS_ADMIN_PASSWORD",
)


def _build_app():
    return importlib.reload(main_module).app


@pytest.fixture(autouse=True)
def reset_auth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _AUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    auth.login_rate_limiter._state.clear()  # type: ignore[attr-defined]
    yield
    auth.login_rate_limiter._state.clear()  # type: ignore[attr-defined]
    for name in _AUTH_ENV_VARS:
        os.environ.pop(name, None)
    _build_app()


def _required_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LWS_AUTH_MODE", "required")
    monkeypatch.setenv("LWS_ADMIN_USER", "root-admin")
    monkeypatch.setenv("LWS_ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("LWS_ENABLE_TEST_PROVIDER", "1")
    return _build_app()


def _login(client: TestClient, username: str, password: str = USER_PASSWORD) -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text


def _bootstrap_admin(client: TestClient) -> dict[str, Any]:
    _login(client, "root-admin", ADMIN_PASSWORD)
    admin = db.get_user_by_username("root-admin")
    assert admin is not None
    db.update_user(admin["id"], {"must_change_password": False})
    return admin


def _create_user(client: TestClient, username: str, role: str) -> dict[str, Any]:
    response = client.post(
        "/api/users",
        json={
            "username": username,
            "display_name": username,
            "role": role,
            "initial_password": USER_PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    user = db.get_user_by_username(username)
    assert user is not None
    db.update_user(user["id"], {"must_change_password": False})
    return user


def _create_language_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Language"
    sheet.append(["ID", "CN", "EN"])
    sheet.append(["BTN_START", "开始游戏", ""])
    sheet.append(["BTN_CLAIM", "领取奖励", ""])
    workbook.save(path)


def _upload_language_table(client: TestClient, project_id: str, path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        response = client.post(
            f"/api/projects/{project_id}/files?kind=language_table",
            files={
                "file": (
                    path.name,
                    stream,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    assert response.status_code == 200, response.text
    return response.json()


def test_member_runs_translation_delivery_and_automatic_archive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin(admin_client)
        _create_user(admin_client, "matrix-member", "member")

    workbook = tmp_path / "member-language.xlsx"
    _create_language_workbook(workbook)
    with TestClient(test_app) as member_client:
        _login(member_client, "matrix-member")
        project_response = member_client.post(
            "/api/projects", json={"name": "Member Translation Matrix", "type": "QA"}
        )
        assert project_response.status_code == 200, project_response.text
        project = project_response.json()
        member = db.get_user_by_username("matrix-member")
        assert member is not None
        assert db.is_project_member(project["id"], member["id"])

        source = _upload_language_table(member_client, project["id"], workbook)
        run_response = member_client.post(
            "/api/runs",
            json={
                "project_id": project["id"],
                "kind": "translation",
                "language": "en",
                "input_artifact_id": source["id"],
                "batch_size": 2,
            },
        )
        assert run_response.status_code == 200, run_response.text
        run = run_response.json()

        translate_response = member_client.post(
            f"/api/runs/{run['id']}/translate",
            json={"provider": "test-fake", "batch_size": 2},
        )
        assert translate_response.status_code == 200, translate_response.text
        assert translate_response.json()["run"]["status"] == "passed"

        delivery_response = member_client.post(
            f"/api/projects/{project['id']}/delivery-package",
            params={"run_id": run["id"]},
        )
        assert delivery_response.status_code == 200, delivery_response.text

        archive_response = member_client.get(
            f"/api/projects/{project['id']}/translations?language=en"
        )
        assert archive_response.status_code == 200, archive_response.text
        archived = archive_response.json()
        assert {entry["entry_key"] for entry in archived} == {"BTN_START", "BTN_CLAIM"}
        assert {entry["source_type"] for entry in archived} == {"qa_passed"}


def test_member_is_forbidden_from_all_destructive_asset_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin(admin_client)
        _create_user(admin_client, "restricted-member", "member")

    with TestClient(test_app) as member_client:
        _login(member_client, "restricted-member")
        project = member_client.post(
            "/api/projects", json={"name": "Restricted Member Project", "type": "QA"}
        ).json()
        member = db.get_user_by_username("restricted-member")
        assert member is not None
        term = db.upsert_glossary_term(
            project["id"], {"source": "按钮", "target": "Button", "language": "en"}
        )
        entry = db.upsert_translation_entry(
            project["id"],
            {
                "entry_key": "BTN",
                "source": "按钮",
                "target": "Button",
                "language": "en",
            },
        )

        requests = [
            ("delete", f"/api/projects/{project['id']}", None),
            (
                "post",
                f"/api/projects/{project['id']}/glossary",
                {"source": "商店", "target": "Shop", "language": "en"},
            ),
            (
                "patch",
                f"/api/projects/{project['id']}/glossary/{term['id']}",
                {"target": "UI Button"},
            ),
            ("delete", f"/api/projects/{project['id']}/glossary/{term['id']}", None),
            (
                "post",
                f"/api/projects/{project['id']}/glossary/import-preview",
                {"artifact_id": "blocked-before-validation"},
            ),
            (
                "post",
                f"/api/projects/{project['id']}/glossary/import",
                {"artifact_id": "blocked-before-validation"},
            ),
            (
                "post",
                f"/api/projects/{project['id']}/glossary/extract",
                {"input_artifact_id": "blocked-before-validation"},
            ),
            (
                "post",
                f"/api/projects/{project['id']}/glossary/batches/fake-batch/translate-missing",
                None,
            ),
            (
                "post",
                f"/api/projects/{project['id']}/translations",
                {"entry_key": "NEW", "source": "新", "target": "New"},
            ),
            (
                "patch",
                f"/api/projects/{project['id']}/translations/{entry['id']}",
                {"target": "Updated"},
            ),
            (
                "delete",
                f"/api/projects/{project['id']}/translations/{entry['id']}",
                None,
            ),
            (
                "post",
                f"/api/projects/{project['id']}/translations/import",
                {"artifact_id": "blocked-before-validation"},
            ),
            ("patch", f"/api/projects/{project['id']}", {"description": "blocked"}),
            (
                "patch",
                f"/api/projects/{project['id']}/harness",
                {"tone": "blocked"},
            ),
            (
                "post",
                f"/api/projects/{project['id']}/members",
                {"user_id": member["id"]},
            ),
        ]
        for method, url, payload in requests:
            response = member_client.request(method, url, json=payload)
            assert response.status_code == 403, f"{method.upper()} {url}: {response.text}"
            assert response.json() == {"detail": "权限不足"}


def test_ops_has_full_asset_and_project_management_on_member_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin(admin_client)
        _create_user(admin_client, "matrix-ops", "ops")
        invitee = _create_user(admin_client, "ops-invitee", "member")

    with TestClient(test_app) as ops_client:
        _login(ops_client, "matrix-ops")
        project = ops_client.post(
            "/api/projects", json={"name": "Ops Full Matrix", "type": "QA"}
        ).json()

        added = ops_client.post(
            f"/api/projects/{project['id']}/members", json={"user_id": invitee["id"]}
        )
        assert added.status_code == 200, added.text
        removed = ops_client.delete(
            f"/api/projects/{project['id']}/members/{invitee['id']}"
        )
        assert removed.status_code == 200, removed.text

        created_term = ops_client.post(
            f"/api/projects/{project['id']}/glossary",
            json={"source": "按钮", "target": "Button", "language": "en"},
        )
        assert created_term.status_code == 200, created_term.text
        term = created_term.json()
        updated_term = ops_client.patch(
            f"/api/projects/{project['id']}/glossary/{term['id']}",
            json={"target": "UI Button"},
        )
        assert updated_term.status_code == 200, updated_term.text
        deleted_term = ops_client.delete(
            f"/api/projects/{project['id']}/glossary/{term['id']}"
        )
        assert deleted_term.status_code == 200, deleted_term.text

        created_entry = ops_client.post(
            f"/api/projects/{project['id']}/translations",
            json={
                "entry_key": "BTN",
                "source": "按钮",
                "target": "Button",
                "language": "en",
            },
        )
        assert created_entry.status_code == 200, created_entry.text
        entry = created_entry.json()
        updated_entry = ops_client.patch(
            f"/api/projects/{project['id']}/translations/{entry['id']}",
            json={"target": "UI Button"},
        )
        assert updated_entry.status_code == 200, updated_entry.text
        deleted_entry = ops_client.delete(
            f"/api/projects/{project['id']}/translations/{entry['id']}"
        )
        assert deleted_entry.status_code == 200, deleted_entry.text

        deleted_project = ops_client.delete(f"/api/projects/{project['id']}")
        assert deleted_project.status_code == 200, deleted_project.text
        assert deleted_project.json() == {"deleted": True}


def test_ops_gets_404_for_every_project_scoped_domain_when_not_a_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin(admin_client)
        project = admin_client.post(
            "/api/projects", json={"name": "Hidden From Ops", "type": "QA"}
        ).json()
        _create_user(admin_client, "outsider-ops", "ops")
        invitee = _create_user(admin_client, "hidden-invitee", "member")
        term = db.upsert_glossary_term(
            project["id"], {"source": "按钮", "target": "Button", "language": "en"}
        )
        entry = db.upsert_translation_entry(
            project["id"], {"entry_key": "BTN", "source": "按钮", "target": "Button"}
        )

    with TestClient(test_app) as ops_client:
        _login(ops_client, "outsider-ops")
        requests = [
            ("delete", f"/api/projects/{project['id']}", None),
            (
                "post",
                f"/api/projects/{project['id']}/glossary",
                {"source": "商店", "target": "Shop"},
            ),
            (
                "patch",
                f"/api/projects/{project['id']}/glossary/{term['id']}",
                {"target": "UI Button"},
            ),
            ("delete", f"/api/projects/{project['id']}/glossary/{term['id']}", None),
            (
                "post",
                f"/api/projects/{project['id']}/glossary/import",
                {"artifact_id": "hidden-artifact"},
            ),
            (
                "post",
                f"/api/projects/{project['id']}/glossary/extract",
                {"input_artifact_id": "hidden-artifact"},
            ),
            (
                "post",
                f"/api/projects/{project['id']}/translations",
                {"entry_key": "NEW", "source": "新", "target": "New"},
            ),
            (
                "patch",
                f"/api/projects/{project['id']}/translations/{entry['id']}",
                {"target": "Updated"},
            ),
            (
                "delete",
                f"/api/projects/{project['id']}/translations/{entry['id']}",
                None,
            ),
            (
                "post",
                f"/api/projects/{project['id']}/translations/import",
                {"artifact_id": "hidden-artifact"},
            ),
            ("patch", f"/api/projects/{project['id']}", {"description": "hidden"}),
            ("patch", f"/api/projects/{project['id']}/harness", {"tone": "hidden"}),
            (
                "post",
                f"/api/projects/{project['id']}/members",
                {"user_id": invitee["id"]},
            ),
        ]
        for method, url, payload in requests:
            response = ops_client.request(method, url, json=payload)
            assert response.status_code == 404, f"{method.upper()} {url}: {response.text}"


def test_admin_bypasses_membership_and_can_manage_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        admin = _bootstrap_admin(admin_client)
        member = _create_user(admin_client, "admin-visible-member", "member")

    with TestClient(test_app) as member_client:
        _login(member_client, "admin-visible-member")
        project = member_client.post(
            "/api/projects", json={"name": "Admin Membership Bypass", "type": "QA"}
        ).json()

    assert not db.is_project_member(project["id"], admin["id"])
    with TestClient(test_app) as admin_client:
        _login(admin_client, "root-admin", ADMIN_PASSWORD)
        users = admin_client.get("/api/users")
        assert users.status_code == 200, users.text
        assert {"root-admin", "admin-visible-member"} <= {
            user["username"] for user in users.json()
        }
        detail = admin_client.get(f"/api/projects/{project['id']}")
        assert detail.status_code == 200, detail.text
        curated = admin_client.post(
            f"/api/projects/{project['id']}/glossary",
            json={"source": "全局", "target": "Global", "language": "en"},
        )
        assert curated.status_code == 200, curated.text
        added = admin_client.post(
            f"/api/projects/{project['id']}/members", json={"user_id": member["id"]}
        )
        assert added.status_code == 200, added.text
        deleted = admin_client.delete(f"/api/projects/{project['id']}")
        assert deleted.status_code == 200, deleted.text


def test_role_downgrade_takes_effect_on_the_next_request_in_same_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin(admin_client)
        ops = _create_user(admin_client, "downgraded-ops", "ops")

    with TestClient(test_app) as ops_client:
        _login(ops_client, "downgraded-ops")
        project = ops_client.post(
            "/api/projects", json={"name": "Immediate Downgrade", "type": "QA"}
        ).json()
        before = ops_client.post(
            f"/api/projects/{project['id']}/glossary",
            json={"source": "降级", "target": "Downgrade"},
        )
        assert before.status_code == 200, before.text

        with TestClient(test_app) as admin_client:
            _login(admin_client, "root-admin", ADMIN_PASSWORD)
            changed = admin_client.patch(f"/api/users/{ops['id']}", json={"role": "member"})
            assert changed.status_code == 200, changed.text

        after = ops_client.post(
            f"/api/projects/{project['id']}/glossary",
            json={"source": "立即", "target": "Immediate"},
        )
        assert after.status_code == 403, after.text
        assert after.json() == {"detail": "权限不足"}


def test_member_can_create_announcement_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin(admin_client)
        _create_user(admin_client, "announcement-member", "member")

    with TestClient(test_app) as member_client:
        _login(member_client, "announcement-member")
        project = member_client.post(
            "/api/projects", json={"name": "Announcement Matrix", "type": "QA"}
        ).json()
        response = member_client.post(
            f"/api/projects/{project['id']}/announcement-tasks",
            json={
                "title": "维护公告",
                "text": "服务器将在今晚维护。",
                "languages": ["en"],
            },
        )
        assert response.status_code == 200, response.text


def test_non_member_cannot_download_by_bare_artifact_id_or_delivery_filename(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    test_app = _required_app(monkeypatch)
    workbook = tmp_path / "protected-download.xlsx"
    _create_language_workbook(workbook)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin(admin_client)
        project = admin_client.post(
            "/api/projects", json={"name": "Protected Downloads", "type": "QA"}
        ).json()
        artifact = _upload_language_table(admin_client, project["id"], workbook)
        delivery_dir = project_dir(project["id"]) / "delivery"
        delivery_dir.mkdir(parents=True, exist_ok=True)
        (delivery_dir / "protected.txt").write_text("secret delivery", encoding="utf-8")
        _create_user(admin_client, "download-outsider", "member")

    with TestClient(test_app) as outsider_client:
        _login(outsider_client, "download-outsider")
        artifact_response = outsider_client.get(
            f"/api/artifacts/{artifact['id']}/download"
        )
        delivery_response = outsider_client.get(
            f"/api/projects/{project['id']}/delivery/protected.txt"
        )

    assert artifact_response.status_code == 404, artifact_response.text
    assert delivery_response.status_code == 404, delivery_response.text


@pytest.mark.parametrize(
    "url",
    [
        "/api/artifacts/unknown-artifact/download",
        "/api/projects/unknown-project/delivery/protected.txt",
    ],
)
def test_unauthenticated_downloads_return_401(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as client:
        response = client.get(url)
    assert response.status_code == 401, response.text
    assert response.json() == {"detail": "未登录"}
