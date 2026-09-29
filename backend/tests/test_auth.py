from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("LWS_DATA_ROOT", str(Path(tempfile.gettempdir()) / "lws-test-data"))

import pytest
from fastapi.testclient import TestClient

import app.auth as auth
import app.config as config
import app.db as db
import app.main as main_module
from conftest import reset_data_root

LOGIN_URL = "/api/auth/login"
LOGOUT_URL = "/api/auth/logout"
ME_URL = "/api/auth/me"
REGISTER_URL = "/api/auth/register"

ADMIN_PASSWORD = "Initial-Admin-Password!"
_AUTH_ENV_VARS = ("LWS_AUTH_MODE", "LWS_DEPLOYMENT_MODE", "LWS_ADMIN_USER", "LWS_ADMIN_PASSWORD")
LOCAL_OFF_PROFILE = config.RuntimeProfile("local", "off")
LOCAL_REQUIRED_PROFILE = config.RuntimeProfile("local", "required")
CLOUD_REQUIRED_PROFILE = config.RuntimeProfile("cloud", "required")


def _build_app(profile: config.RuntimeProfile = LOCAL_OFF_PROFILE):
    return main_module.create_app(profile)


def _required_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    username: str = "root-admin",
):
    monkeypatch.setenv("LWS_ADMIN_USER", username)
    monkeypatch.setenv("LWS_ADMIN_PASSWORD", ADMIN_PASSWORD)
    return _build_app(LOCAL_REQUIRED_PROFILE)


def _clear_registration_limiter() -> None:
    limiter = getattr(auth, "registration_rate_limiter", None)
    if limiter is not None:
        limiter._state.clear()  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def reset_test_state(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _AUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()
    auth.login_rate_limiter._state.clear()  # type: ignore[attr-defined]
    _clear_registration_limiter()
    yield
    auth.login_rate_limiter._state.clear()  # type: ignore[attr-defined]
    _clear_registration_limiter()
    for name in _AUTH_ENV_VARS:
        os.environ.pop(name, None)


def _create_user(username: str, password: str = "Sup3rSecret!", role: str = "admin", status: str = "active") -> dict:
    return db.create_user(username, auth.hash_password(password), role, display_name=username.title(), status=status)


def test_login_success_returns_public_user_fields_and_httponly_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)
    _create_user("alice")
    with TestClient(test_app) as client:
        response = client.post(LOGIN_URL, json={"username": "alice", "password": "Sup3rSecret!"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["username"] == "alice"
        assert body["role"] == "admin"
        assert body["must_change_password"] is False
        assert "password_hash" not in body
        assert "password" not in body

        set_cookie = response.headers.get("set-cookie", "")
        assert f"{auth.SESSION_COOKIE_NAME}=" in set_cookie
        assert "httponly" in set_cookie.lower()
        assert "samesite=lax" in set_cookie.lower()
        # Local deployment mode must not force Secure (no HTTPS guarantee locally).
        assert "secure" not in set_cookie.lower()


def test_login_wrong_password_returns_401_with_generic_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)
    _create_user("bob")
    with TestClient(test_app) as client:
        response = client.post(LOGIN_URL, json={"username": "bob", "password": "wrong-password"})
        assert response.status_code == 401
        assert response.json()["detail"] == "用户名或密码错误"


def test_me_with_invalid_session_cookie_is_rejected_when_auth_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)

    with TestClient(test_app) as client:
        client.cookies.set(auth.SESSION_COOKIE_NAME, auth.generate_session_token())
        response = client.get(ME_URL)

    assert response.status_code == 401
    assert response.json() == {"detail": "未登录"}


def test_logout_invalidates_session_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)
    _create_user("erin")
    with TestClient(test_app) as client:
        assert client.post(LOGIN_URL, json={"username": "erin", "password": "Sup3rSecret!"}).status_code == 200
        assert client.get(ME_URL).status_code == 200

        logout_response = client.post(LOGOUT_URL)
        assert logout_response.status_code == 200
        assert logout_response.json()["ok"] is True

        # Required mode no longer recognizes the revoked session.
        after_logout = client.get(ME_URL)
        assert after_logout.status_code == 401, after_logout.text

        # Logging out again with no active session must not error.
        second_logout = client.post(LOGOUT_URL)
        assert second_logout.status_code == 200
        assert second_logout.json()["ok"] is True
