from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.auth as auth
import app.db as db
import app.main as main_module
from conftest import reset_data_root

ADMIN_PASSWORD = "Initial-Admin-Password!"
USER_PASSWORD = "Sup3rSecret1!"

PROJECTS_URL = "/api/projects"
USERS_URL = "/api/users"
LOGIN_URL = "/api/auth/login"


def _build_app():
    return importlib.reload(main_module).app


_AUTH_ENV_VARS = ("LWS_AUTH_MODE", "LWS_DEPLOYMENT_MODE", "LWS_ADMIN_USER", "LWS_ADMIN_PASSWORD")


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


def _required_app(monkeypatch: pytest.MonkeyPatch, *, username: str = "root-admin"):
    monkeypatch.setenv("LWS_AUTH_MODE", "required")
    monkeypatch.setenv("LWS_ADMIN_USER", username)
    monkeypatch.setenv("LWS_ADMIN_PASSWORD", ADMIN_PASSWORD)
    return _build_app()


def _login(client: TestClient, username: str, password: str):
    response = client.post(LOGIN_URL, json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response


def _bootstrap_admin_client(client: TestClient, *, username: str = "root-admin") -> None:
    _login(client, username, ADMIN_PASSWORD)
    admin = db.get_user_by_username(username)
    assert admin is not None
    db.update_user(admin["id"], {"must_change_password": False})


def _create_user_via_api(client: TestClient, username: str, role: str, *, password: str = USER_PASSWORD) -> dict:
    response = client.post(
        USERS_URL,
        json={"username": username, "display_name": username, "role": role, "initial_password": password},
    )
    assert response.status_code == 200, response.text
    user = db.get_user_by_username(username)
    db.update_user(user["id"], {"must_change_password": False})
    return response.json()


# ---------------------------------------------------------------------------
# visibility: non-member -> 404, member -> visible
# ---------------------------------------------------------------------------


def test_non_member_gets_404_on_project_detail_and_subresources(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        project = admin_client.post(PROJECTS_URL, json={"name": "Not My Project", "type": "QA"}).json()
        _create_user_via_api(admin_client, "outsider-ops", "ops")
        _create_user_via_api(admin_client, "outsider-member", "member")

    for username in ("outsider-ops", "outsider-member"):
        with TestClient(test_app) as client:
            _login(client, username, USER_PASSWORD)
            detail = client.get(f"/api/projects/{project['id']}")
            glossary = client.get(f"/api/projects/{project['id']}/glossary")
        assert detail.status_code == 404, f"{username}: {detail.text}"
        assert glossary.status_code == 404, f"{username}: {glossary.text}"


def test_member_added_can_see_project_and_removed_member_cannot(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        project = admin_client.post(PROJECTS_URL, json={"name": "Invite Flow", "type": "QA"}).json()
        _create_user_via_api(admin_client, "invited-member", "member")
        user = db.get_user_by_username("invited-member")

        add_response = admin_client.post(
            f"/api/projects/{project['id']}/members", json={"user_id": user["id"]}
        )
        assert add_response.status_code == 200, add_response.text
        assert add_response.json()["username"] == "invited-member"

    with TestClient(test_app) as client:
        _login(client, "invited-member", USER_PASSWORD)
        visible = client.get(f"/api/projects/{project['id']}")
        assert visible.status_code == 200, visible.text

    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        remove_response = admin_client.delete(f"/api/projects/{project['id']}/members/{user['id']}")
        assert remove_response.status_code == 200, remove_response.text
        assert remove_response.json() == {"deleted": True}

    with TestClient(test_app) as client:
        _login(client, "invited-member", USER_PASSWORD)
        gone = client.get(f"/api/projects/{project['id']}")
        assert gone.status_code == 404, gone.text


# ---------------------------------------------------------------------------
# GET /api/projects list filtering
# ---------------------------------------------------------------------------


def test_project_list_filtered_by_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        visible_project = admin_client.post(PROJECTS_URL, json={"name": "Member Can See", "type": "QA"}).json()
        hidden_project = admin_client.post(PROJECTS_URL, json={"name": "Member Cannot See", "type": "QA"}).json()
        _create_user_via_api(admin_client, "listing-member", "member")
        user = db.get_user_by_username("listing-member")
        db.add_project_member(visible_project["id"], user["id"], added_by="root-admin")

        admin_list = {p["id"] for p in admin_client.get(PROJECTS_URL).json()}
        assert {visible_project["id"], hidden_project["id"]} <= admin_list

    with TestClient(test_app) as client:
        _login(client, "listing-member", USER_PASSWORD)
        member_list = {p["id"] for p in client.get(PROJECTS_URL).json()}
    assert visible_project["id"] in member_list
    assert hidden_project["id"] not in member_list


def test_member_created_project_is_auto_membered_and_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        _create_user_via_api(admin_client, "self-serve-member", "member")

    with TestClient(test_app) as client:
        _login(client, "self-serve-member", USER_PASSWORD)
        created = client.post(PROJECTS_URL, json={"name": "Member Built This", "type": "QA"}).json()
        listed = {p["id"] for p in client.get(PROJECTS_URL).json()}
        detail = client.get(f"/api/projects/{created['id']}")

    assert created["id"] in listed
    assert detail.status_code == 200, detail.text
    user = db.get_user_by_username("self-serve-member")
    assert db.is_project_member(created["id"], user["id"])


# ---------------------------------------------------------------------------
# member-management permissions
# ---------------------------------------------------------------------------


def test_ops_manages_own_member_project_members_successfully(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        project = admin_client.post(PROJECTS_URL, json={"name": "Ops Managed Project", "type": "QA"}).json()
        _create_user_via_api(admin_client, "managing-ops", "ops")
        _create_user_via_api(admin_client, "invitee", "member")
        _create_user_via_api(admin_client, "disabled-invitee", "member")
        ops_user = db.get_user_by_username("managing-ops")
        invitee = db.get_user_by_username("invitee")
        disabled_invitee = db.get_user_by_username("disabled-invitee")
        db.update_user(disabled_invitee["id"], {"status": "disabled"})
        db.add_project_member(project["id"], ops_user["id"], added_by="root-admin")

    with TestClient(test_app) as ops_client:
        _login(ops_client, "managing-ops", USER_PASSWORD)
        addable_response = ops_client.get(f"/api/projects/{project['id']}/members/addable")
        assert addable_response.status_code == 200, addable_response.text
        assert addable_response.json() == [
            {
                "id": invitee["id"],
                "username": "invitee",
                "display_name": "invitee",
                "role": "member",
            }
        ]
        add_response = ops_client.post(
            f"/api/projects/{project['id']}/members", json={"user_id": invitee["id"]}
        )
        assert add_response.status_code == 200, add_response.text
        assert ops_client.get(f"/api/projects/{project['id']}/members/addable").json() == []
        list_response = ops_client.get(f"/api/projects/{project['id']}/members")
        assert list_response.status_code == 200, list_response.text
        usernames = {row["username"] for row in list_response.json()}
        assert {"managing-ops", "invitee"} <= usernames

        remove_response = ops_client.delete(f"/api/projects/{project['id']}/members/{invitee['id']}")
        assert remove_response.status_code == 200, remove_response.text


def test_ops_managing_non_member_project_gets_404(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        project = admin_client.post(PROJECTS_URL, json={"name": "Not Ops Project", "type": "QA"}).json()
        _create_user_via_api(admin_client, "outsider-ops-2", "ops")
        _create_user_via_api(admin_client, "someone", "member")
        someone = db.get_user_by_username("someone")

    with TestClient(test_app) as ops_client:
        _login(ops_client, "outsider-ops-2", USER_PASSWORD)
        responses = [
            ops_client.get(f"/api/projects/{project['id']}/members/addable"),
            ops_client.post(
                f"/api/projects/{project['id']}/members", json={"user_id": someone["id"]}
            ),
        ]
    assert all(response.status_code == 404 for response in responses), [response.text for response in responses]


def test_member_cannot_add_project_members(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        project = admin_client.post(PROJECTS_URL, json={"name": "Member Cannot Manage", "type": "QA"}).json()
        _create_user_via_api(admin_client, "plain-member", "member")
        _create_user_via_api(admin_client, "another-user", "member")
        plain_member = db.get_user_by_username("plain-member")
        another_user = db.get_user_by_username("another-user")
        db.add_project_member(project["id"], plain_member["id"], added_by="root-admin")

    with TestClient(test_app) as client:
        _login(client, "plain-member", USER_PASSWORD)
        responses = [
            client.get(f"/api/projects/{project['id']}/members/addable"),
            client.post(
                f"/api/projects/{project['id']}/members", json={"user_id": another_user["id"]}
            ),
        ]
    assert all(response.status_code == 403 for response in responses), [response.text for response in responses]


def test_admin_can_manage_members_of_any_project_without_being_a_member(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        project = admin_client.post(PROJECTS_URL, json={"name": "Admin Managed", "type": "QA"}).json()
        _create_user_via_api(admin_client, "future-member", "member")
        future_member = db.get_user_by_username("future-member")

        admin_id = db.get_user_by_username("root-admin")["id"]
        assert not db.is_project_member(project["id"], admin_id)

        add_response = admin_client.post(
            f"/api/projects/{project['id']}/members", json={"user_id": future_member["id"]}
        )
        assert add_response.status_code == 200, add_response.text


# ---------------------------------------------------------------------------
# auth-off (local) mode: zero regression promise
# ---------------------------------------------------------------------------


def test_auth_off_mode_project_visibility_and_membership_endpoints_unaffected() -> None:
    test_app = _build_app()
    with TestClient(test_app) as client:
        project = client.post(PROJECTS_URL, json={"name": "Local Members Regression", "type": "QA"}).json()
        detail = client.get(f"/api/projects/{project['id']}")
        listed = client.get(PROJECTS_URL)
        members = client.get(f"/api/projects/{project['id']}/members")

    assert detail.status_code == 200, detail.text
    assert listed.status_code == 200, listed.text
    assert any(p["id"] == project["id"] for p in listed.json())
    assert members.status_code == 200, members.text
