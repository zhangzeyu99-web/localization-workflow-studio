from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("LWS_DATA_ROOT", str(Path(tempfile.gettempdir()) / "lws-test-data"))

import pytest
from fastapi.testclient import TestClient

import app.auth as auth
import app.authz as authz
import app.db as db
from app.main import app
from conftest import reset_data_root

LOGIN_URL = "/api/auth/login"
LOGOUT_URL = "/api/auth/logout"
ME_URL = "/api/auth/me"


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()
    auth.login_rate_limiter._state.clear()  # type: ignore[attr-defined]
    yield
    auth.login_rate_limiter._state.clear()  # type: ignore[attr-defined]


def _create_user(username: str, password: str = "Sup3rSecret!", role: str = "admin", status: str = "active") -> dict:
    return db.create_user(username, auth.hash_password(password), role, display_name=username.title(), status=status)


def test_login_success_returns_public_user_fields_and_httponly_cookie() -> None:
    _create_user("alice")
    with TestClient(app) as client:
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


def test_login_cookie_is_secure_in_cloud_deployment_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_user("cloud-user")
    monkeypatch.setenv("LWS_DEPLOYMENT_MODE", "cloud")
    with TestClient(app) as client:
        response = client.post(LOGIN_URL, json={"username": "cloud-user", "password": "Sup3rSecret!"})
        assert response.status_code == 200, response.text
        set_cookie = response.headers.get("set-cookie", "")
        assert "secure" in set_cookie.lower()


def test_login_wrong_password_returns_401_with_generic_message() -> None:
    _create_user("bob")
    with TestClient(app) as client:
        response = client.post(LOGIN_URL, json={"username": "bob", "password": "wrong-password"})
        assert response.status_code == 401
        assert response.json()["detail"] == "用户名或密码错误"


def test_login_unknown_username_returns_same_401_message_as_wrong_password() -> None:
    with TestClient(app) as client:
        response = client.post(LOGIN_URL, json={"username": "does-not-exist", "password": "whatever"})
        assert response.status_code == 401
        assert response.json()["detail"] == "用户名或密码错误"


def test_login_disabled_user_returns_401_even_with_correct_password() -> None:
    _create_user("carol", status="disabled")
    with TestClient(app) as client:
        response = client.post(LOGIN_URL, json={"username": "carol", "password": "Sup3rSecret!"})
        assert response.status_code == 401
        assert response.json()["detail"] == "用户名或密码错误"


def test_me_without_session_falls_back_to_local_admin_when_auth_is_off() -> None:
    """This module's app is built with no LWS_AUTH_MODE/cloud deployment env,
    so enforcement is off. The dominant real-world case for that mode is a
    fresh page load with no session cookie at all -- the frontend's app-shell
    gate must see the synthetic local administrator (200), not 401, or every
    local deployment would incorrectly show a login screen."""
    with TestClient(app) as client:
        response = client.get(ME_URL)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["id"] == auth.LOCAL_ADMIN_USER["id"]
        assert body["role"] == "admin"
        assert body["auth_enabled"] is False
        assert body["capabilities"] == sorted(authz.ALL_CAPABILITIES)


def test_me_with_valid_session_returns_current_user() -> None:
    _create_user("dave")
    with TestClient(app) as client:
        login_response = client.post(LOGIN_URL, json={"username": "dave", "password": "Sup3rSecret!"})
        assert login_response.status_code == 200

        me_response = client.get(ME_URL)
        assert me_response.status_code == 200
        body = me_response.json()
        assert body["username"] == "dave"
        # A real session cookie is honored even though this app's enforcement
        # switch is off (see the fallback test above for the "no cookie" case).
        assert body["auth_enabled"] is False
        assert body["capabilities"] == sorted(authz.ALL_CAPABILITIES)


def test_logout_invalidates_session_and_is_idempotent() -> None:
    _create_user("erin")
    with TestClient(app) as client:
        assert client.post(LOGIN_URL, json={"username": "erin", "password": "Sup3rSecret!"}).status_code == 200
        assert client.get(ME_URL).status_code == 200

        logout_response = client.post(LOGOUT_URL)
        assert logout_response.status_code == 200
        assert logout_response.json()["ok"] is True

        # Logout clears the cookie, so this app's "no cookie + auth off"
        # fallback answers with the synthetic local admin rather than 401 --
        # the important assertion is that it is no longer erin's session.
        after_logout = client.get(ME_URL)
        assert after_logout.status_code == 200, after_logout.text
        assert after_logout.json()["id"] == auth.LOCAL_ADMIN_USER["id"]

        # Logging out again with no active session must not error.
        second_logout = client.post(LOGOUT_URL)
        assert second_logout.status_code == 200
        assert second_logout.json()["ok"] is True


def test_expired_session_is_rejected_and_lazily_purged() -> None:
    user = _create_user("frank")
    token = auth.generate_session_token()
    token_hash = auth.hash_token(token)
    db.create_session(user["id"], token_hash, "2000-01-01T00:00:00+00:00")

    with TestClient(app) as client:
        client.cookies.set(auth.SESSION_COOKIE_NAME, token)
        response = client.get(ME_URL)
        assert response.status_code == 401

    # get_session_by_token_hash lazily deletes the expired row on read.
    assert db.get_session_by_token_hash(token_hash) is None


def test_purge_expired_sessions_removes_only_expired_rows() -> None:
    user = _create_user("grace")
    expired_token_hash = auth.hash_token(auth.generate_session_token())
    live_token_hash = auth.hash_token(auth.generate_session_token())
    db.create_session(user["id"], expired_token_hash, "2000-01-01T00:00:00+00:00")
    db.create_session(user["id"], live_token_hash, auth.session_expiry_iso())

    purged = db.purge_expired_sessions()
    assert purged == 1
    assert db.get_session_by_token_hash(live_token_hash) is not None


def test_password_hash_is_argon2_and_never_stores_plaintext() -> None:
    user = _create_user("henry", password="MyPlainPassword1!")
    stored = db.get_user(user["id"])
    assert stored["password_hash"] != "MyPlainPassword1!"
    assert stored["password_hash"].startswith("$argon2id$")
    assert auth.verify_password(stored["password_hash"], "MyPlainPassword1!") is True
    assert auth.verify_password(stored["password_hash"], "WrongPassword") is False


def test_login_rate_limiter_locks_after_max_failures_and_recovers_after_lockout_window() -> None:
    """Unit-level check of the sliding window + lockout logic with an injected clock."""
    fake_time = [0.0]
    limiter = auth.LoginRateLimiter(max_failures=3, window_seconds=10.0, lockout_seconds=5.0, clock=lambda: fake_time[0])
    key = limiter.key("someone", "10.0.0.1")

    limiter.record_failure(key)
    limiter.record_failure(key)
    assert limiter.locked_seconds_remaining(key) == 0.0

    limiter.record_failure(key)  # 3rd failure within the window triggers the lock
    assert limiter.locked_seconds_remaining(key) > 0.0

    fake_time[0] += 5.1  # advance past the lockout duration
    assert limiter.locked_seconds_remaining(key) == 0.0

    limiter.record_success(key)
    limiter.record_failure(key)
    limiter.record_failure(key)
    assert limiter.locked_seconds_remaining(key) == 0.0  # only 2 failures since the reset


def test_login_endpoint_returns_429_after_repeated_failures_and_recovers_after_window(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_user("iris")
    fake_time = [0.0]
    monkeypatch.setattr(auth.login_rate_limiter, "_clock", lambda: fake_time[0])
    monkeypatch.setattr(auth.login_rate_limiter, "max_failures", 5)
    monkeypatch.setattr(auth.login_rate_limiter, "window_seconds", 600.0)
    monkeypatch.setattr(auth.login_rate_limiter, "lockout_seconds", 600.0)

    with TestClient(app) as client:
        for _ in range(5):
            response = client.post(LOGIN_URL, json={"username": "iris", "password": "wrong-password"})
            assert response.status_code == 401

        locked_response = client.post(LOGIN_URL, json={"username": "iris", "password": "Sup3rSecret!"})
        assert locked_response.status_code == 429

        fake_time[0] += 601.0  # advance past the lockout window
        recovered_response = client.post(LOGIN_URL, json={"username": "iris", "password": "Sup3rSecret!"})
        assert recovered_response.status_code == 200, recovered_response.text


def test_change_password_in_local_auth_off_mode_returns_400() -> None:
    """In auth-off/local mode every request is the synthetic LOCAL_ADMIN_USER
    (see _enforce_authentication), which has no row in the users table --
    there is no password to change."""
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/change-password",
            json={"current_password": "whatever", "new_password": "New-Strong-Pass1!"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "本地模式无需修改密码"


def test_login_rate_limit_is_scoped_per_username_and_ip_key() -> None:
    _create_user("jack")
    key_a = auth.login_rate_limiter.key("jack", "1.1.1.1")
    key_b = auth.login_rate_limiter.key("jack", "2.2.2.2")
    for _ in range(auth.login_rate_limiter.max_failures):
        auth.login_rate_limiter.record_failure(key_a)
    assert auth.login_rate_limiter.locked_seconds_remaining(key_a) > 0.0
    assert auth.login_rate_limiter.locked_seconds_remaining(key_b) == 0.0
