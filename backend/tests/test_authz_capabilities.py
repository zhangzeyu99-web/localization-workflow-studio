from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.auth as auth
import app.db as db
import app.main as main_module
from app import route_capabilities
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
    # See test_users_admin.py's identical teardown comment: app.main.AUTH_REQUIRED
    # is a bare module global re-read by lifespan() on every call, not captured
    # per-app-instance, so a reload() here must be undone before the next test
    # file runs or it leaks "auth required" into unrelated test modules.
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
    return response.json()


def _clear_must_change_password(username: str) -> None:
    user = db.get_user_by_username(username)
    assert user is not None
    db.update_user(user["id"], {"must_change_password": False})


# ---------------------------------------------------------------------------
# role -> capability matrix
# ---------------------------------------------------------------------------


def test_capability_matrix_matches_plan() -> None:
    from app import authz

    assert authz.capability_allowed("admin", authz.PROJECT_READ)
    assert authz.capability_allowed("admin", authz.ASSETS_CURATE)
    assert authz.capability_allowed("admin", authz.PROJECT_MANAGE)
    assert authz.capability_allowed("admin", authz.ADMIN)

    assert authz.capability_allowed("ops", authz.PROJECT_READ)
    assert authz.capability_allowed("ops", authz.TASK_RUN)
    assert authz.capability_allowed("ops", authz.ASSETS_CURATE)
    assert authz.capability_allowed("ops", authz.PROJECT_MANAGE)
    assert not authz.capability_allowed("ops", authz.ADMIN)

    assert authz.capability_allowed("member", authz.PROJECT_READ)
    assert authz.capability_allowed("member", authz.TASK_RUN)
    assert not authz.capability_allowed("member", authz.ASSETS_CURATE)
    assert not authz.capability_allowed("member", authz.PROJECT_MANAGE)
    assert not authz.capability_allowed("member", authz.ADMIN)


# ---------------------------------------------------------------------------
# member vs ops vs admin against real endpoints
# ---------------------------------------------------------------------------


def test_member_forbidden_on_assets_curate_endpoint_even_as_project_member(monkeypatch: pytest.MonkeyPatch) -> None:
    """ASSETS_CURATE (manual glossary term creation): member is a project
    member but still 403s -- capability, not membership, is the blocker.
    """
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        project = admin_client.post(PROJECTS_URL, json={"name": "Capability Project", "type": "QA"}).json()
        _create_user_via_api(admin_client, "member-1", "member")
        _clear_must_change_password("member-1")
        member = db.get_user_by_username("member-1")
        db.add_project_member(project["id"], member["id"], added_by="root-admin")

    with TestClient(test_app) as client:
        _login(client, "member-1", USER_PASSWORD)
        response = client.post(
            f"/api/projects/{project['id']}/glossary",
            json={"source": "按钮", "target": "Button", "language": "en"},
        )
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": "权限不足"}


def test_ops_allowed_on_assets_curate_endpoint_for_own_member_project(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        project = admin_client.post(PROJECTS_URL, json={"name": "Ops Curate Project", "type": "QA"}).json()
        _create_user_via_api(admin_client, "ops-1", "ops")
        _clear_must_change_password("ops-1")
        ops_user = db.get_user_by_username("ops-1")
        db.add_project_member(project["id"], ops_user["id"], added_by="root-admin")

    with TestClient(test_app) as client:
        _login(client, "ops-1", USER_PASSWORD)
        response = client.post(
            f"/api/projects/{project['id']}/glossary",
            json={"source": "按钮", "target": "Button", "language": "en"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "按钮"


def test_member_allowed_on_task_run_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """TASK_RUN (creating a run): member has this capability and is a
    project member, so this must not be 401/403 -- we don't need the run to
    actually execute anything for this to prove the gate lets it through.
    """
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        project = admin_client.post(PROJECTS_URL, json={"name": "Task Run Project", "type": "QA"}).json()
        _create_user_via_api(admin_client, "member-2", "member")
        _clear_must_change_password("member-2")
        member = db.get_user_by_username("member-2")
        db.add_project_member(project["id"], member["id"], added_by="root-admin")

    with TestClient(test_app) as client:
        _login(client, "member-2", USER_PASSWORD)
        response = client.post(
            "/api/runs",
            json={"project_id": project["id"], "kind": "translation", "language": "en"},
        )
    assert response.status_code not in (401, 403), response.text
    assert response.status_code == 200, response.text


def test_member_forbidden_on_delete_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """PROJECT_MANAGE (delete project): member is a project member but the
    matrix says member can never delete a project, even one they created.
    """
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        project = admin_client.post(PROJECTS_URL, json={"name": "Undeletable By Member", "type": "QA"}).json()
        _create_user_via_api(admin_client, "member-3", "member")
        _clear_must_change_password("member-3")
        member = db.get_user_by_username("member-3")
        db.add_project_member(project["id"], member["id"], added_by="root-admin")

    with TestClient(test_app) as client:
        _login(client, "member-3", USER_PASSWORD)
        response = client.delete(f"/api/projects/{project['id']}")
    assert response.status_code == 403, response.text


def test_admin_bypasses_capability_and_membership_entirely(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as client:
        _bootstrap_admin_client(client)
        project = client.post(PROJECTS_URL, json={"name": "Admin Sees All", "type": "QA"}).json()
        # Admin never got a project_members row (see _auto_add_creator_as_member),
        # yet must still be able to read/curate/delete it.
        assert not db.is_project_member(project["id"], db.get_user_by_username("root-admin")["id"])
        detail = client.get(f"/api/projects/{project['id']}")
        assert detail.status_code == 200, detail.text
        curated = client.post(
            f"/api/projects/{project['id']}/glossary",
            json={"source": "术语", "target": "Term", "language": "en"},
        )
        assert curated.status_code == 200, curated.text
        deleted = client.delete(f"/api/projects/{project['id']}")
        assert deleted.status_code == 200, deleted.text


# ---------------------------------------------------------------------------
# fail-closed startup assertion
# ---------------------------------------------------------------------------


def test_fail_closed_startup_assertion_rejects_unregistered_route() -> None:
    fake_app = FastAPI()

    @fake_app.get("/api/totally-unregistered-route")
    def _fake() -> dict:
        return {"ok": True}

    with pytest.raises(RuntimeError, match=r"totally-unregistered-route"):
        route_capabilities.assert_full_route_coverage(fake_app)


def test_fail_closed_startup_assertion_passes_for_real_app() -> None:
    # The real app already asserts this at import time in main.py; re-running
    # it here pins the behavior against accidental future regressions (e.g.
    # someone catching/ignoring the RuntimeError at the call site).
    route_capabilities.assert_full_route_coverage(_build_app())


def test_every_capability_route_key_is_a_real_capability_constant() -> None:
    from app import authz

    for capability in route_capabilities.CAPABILITY_BY_ROUTE.values():
        assert capability in authz.ALL_CAPABILITIES


# ---------------------------------------------------------------------------
# auth-off (local) mode: zero regression promise
# ---------------------------------------------------------------------------


def test_auth_off_mode_ignores_capability_and_membership_gates_entirely() -> None:
    test_app = _build_app()
    with TestClient(test_app) as client:
        project = client.post(PROJECTS_URL, json={"name": "Local Mode Project", "type": "QA"}).json()
        curated = client.post(
            f"/api/projects/{project['id']}/glossary",
            json={"source": "本地", "target": "Local", "language": "en"},
        )
        deleted = client.delete(f"/api/projects/{project['id']}")

    assert curated.status_code == 200, curated.text
    assert deleted.status_code == 200, deleted.text
