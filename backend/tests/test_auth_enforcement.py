from __future__ import annotations

import json
import importlib
import os
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import app.auth as auth
import app.db as db
import app.main as main_module
from app.config import DATA_ROOT
from app.operator_context import AUDIT_LOG_FILENAME
from conftest import reset_data_root


PASSWORD = "Initial-Admin-Password!"


def _build_app():
    return importlib.reload(main_module).app


@pytest.fixture(autouse=True)
def reset_auth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "LWS_AUTH_MODE",
        "LWS_DEPLOYMENT_MODE",
        "LWS_ADMIN_USER",
        "LWS_ADMIN_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    auth.login_rate_limiter._state.clear()  # type: ignore[attr-defined]
    yield
    auth.login_rate_limiter._state.clear()  # type: ignore[attr-defined]


def _required_app(monkeypatch: pytest.MonkeyPatch, *, username: str = "admin"):
    monkeypatch.setenv("LWS_AUTH_MODE", "required")
    monkeypatch.setenv("LWS_ADMIN_USER", username)
    monkeypatch.setenv("LWS_ADMIN_PASSWORD", PASSWORD)
    return _build_app()


def test_local_mode_defaults_to_auth_off_and_exposes_synthetic_admin() -> None:
    test_app = _build_app()

    @test_app.get("/api/test-current-user")
    def current_user(request: Request) -> dict:
        return {
            "state": request.state.user,
            "context": auth.current_user(),
        }

    with TestClient(test_app) as client:
        project_response = client.post("/api/projects", json={"name": "Local Project", "type": "QA"})
        identity_response = client.get("/api/test-current-user")

    assert project_response.status_code == 200, project_response.text
    assert identity_response.status_code == 200, identity_response.text
    assert identity_response.json()["state"]["id"] == "local-admin"
    assert identity_response.json()["state"]["role"] == "admin"
    assert identity_response.json()["context"]["id"] == "local-admin"


def test_required_mode_rejects_business_api_then_allows_it_after_login(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)

    with TestClient(test_app) as client:
        denied = client.get("/api/projects")
        login = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
        # Bootstrap always forces a first-login password change (A1 batch 3),
        # so the business API stays gated by a distinct 403 until that
        # happens -- see test_first_login_password_change_gate below for the
        # dedicated coverage of that gate itself.
        still_gated = client.get("/api/projects")
        client.post(
            "/api/auth/change-password",
            json={"current_password": PASSWORD, "new_password": "Post-Bootstrap-Pass1!"},
        )
        allowed = client.get("/api/projects")

    assert denied.status_code == 401
    assert denied.json() == {"detail": "未登录"}
    assert login.status_code == 200, login.text
    assert still_gated.status_code == 403
    assert still_gated.json() == {"detail": "首次登录请先修改密码"}
    assert allowed.status_code == 200, allowed.text


def test_authentication_401_and_403_responses_keep_cors_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)
    headers = {"Origin": "http://localhost:5173"}

    with TestClient(test_app) as client:
        unauthenticated = client.get("/api/projects", headers=headers)
        login = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": PASSWORD},
            headers=headers,
        )
        must_change_password = client.get("/api/projects", headers=headers)

    assert login.status_code == 200, login.text
    assert unauthenticated.status_code == 401
    assert must_change_password.status_code == 403
    for response in (unauthenticated, must_change_password):
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert response.headers["access-control-allow-credentials"] == "true"


def test_required_mode_allows_only_exact_prelogin_self_check_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)

    with TestClient(test_app) as client:
        version = client.get("/api/version")
        health = client.get("/api/health")
        # Writes files to disk, so it must require a session despite being
        # part of deployment_check's smoke flow (login support there is A4).
        upload = client.post(
            "/api/diagnostics/upload-readability",
            files={"file": ("probe.txt", "中文 probe", "text/plain")},
        )
        me = client.get("/api/auth/me")
        future_auth_route = client.get("/api/auth/not-a-real-route")

    assert version.status_code == 200, version.text
    assert health.status_code == 200, health.text
    assert upload.status_code == 401
    assert upload.json() == {"detail": "未登录"}
    assert me.status_code == 401
    assert future_auth_route.status_code == 401


def test_cloud_mode_defaults_to_auth_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LWS_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("LWS_ADMIN_USER", "cloud-admin")
    monkeypatch.setenv("LWS_ADMIN_PASSWORD", PASSWORD)

    with TestClient(_build_app()) as client:
        response = client.get("/api/projects")

    assert response.status_code == 401


def test_explicit_auth_off_overrides_cloud_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LWS_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("LWS_AUTH_MODE", "off")

    with TestClient(_build_app()) as client:
        response = client.get("/api/projects")

    assert response.status_code == 200, response.text


def test_required_mode_bootstraps_initial_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch, username="first-admin")

    with TestClient(test_app):
        user = db.get_user_by_username("first-admin")

    assert user is not None
    assert user["role"] == "admin"
    assert user["status"] == "active"
    assert user["must_change_password"] is True
    assert auth.verify_password(user["password_hash"], PASSWORD)


def test_required_mode_without_bootstrap_credentials_fails_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LWS_AUTH_MODE", "required")

    with pytest.raises(RuntimeError, match=r"LWS_ADMIN_USER.*LWS_ADMIN_PASSWORD.*create_admin"):
        with TestClient(_build_app()):
            pass


def test_authenticated_operator_uses_display_name_not_spoofed_header(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch, username="auditor")
    audit_path = DATA_ROOT / AUDIT_LOG_FILENAME

    with TestClient(test_app) as client:
        user = db.get_user_by_username("auditor")
        assert user is not None
        # Bootstrap forces a first-login password change (A1 batch 3); clear
        # it directly so this test can focus on operator-attribution rather
        # than re-proving the password-change gate covered elsewhere.
        db.update_user(user["id"], {"display_name": "真实管理员", "must_change_password": False})
        login = client.post("/api/auth/login", json={"username": "auditor", "password": PASSWORD})
        assert login.status_code == 200, login.text
        project = client.post("/api/projects", json={"name": "Audit Project", "type": "QA"}).json()
        deleted = client.delete(
            f"/api/projects/{project['id']}",
            headers={"X-Operator": "Spoofed Operator"},
        )

    assert deleted.status_code == 200, deleted.text
    entries = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert entries[-1]["operator"] == "真实管理员"


def test_startup_purges_expired_sessions() -> None:
    db.init_db()
    user = db.create_user("expired-owner", auth.hash_password(PASSWORD), "admin")
    token_hash = auth.hash_token("expired-token")
    db.create_session(user["id"], token_hash, "2000-01-01T00:00:00+00:00")

    with TestClient(_build_app()):
        with db.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()[0]

    assert count == 0
