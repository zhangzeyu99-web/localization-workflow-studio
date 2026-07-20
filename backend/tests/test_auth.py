from __future__ import annotations

import importlib
import json
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("LWS_DATA_ROOT", str(Path(tempfile.gettempdir()) / "lws-test-data"))

import pytest
from fastapi.testclient import TestClient

import app.auth as auth
import app.authz as authz
import app.db as db
import app.main as main_module
from app.config import DATA_ROOT
from app.operator_context import AUDIT_LOG_FILENAME
from conftest import reset_data_root

app = main_module.app

LOGIN_URL = "/api/auth/login"
LOGOUT_URL = "/api/auth/logout"
ME_URL = "/api/auth/me"
REGISTER_URL = "/api/auth/register"

ADMIN_PASSWORD = "Initial-Admin-Password!"
_AUTH_ENV_VARS = ("LWS_AUTH_MODE", "LWS_DEPLOYMENT_MODE", "LWS_ADMIN_USER", "LWS_ADMIN_PASSWORD")


def _build_app():
    return importlib.reload(main_module).app


def _required_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LWS_AUTH_MODE", "required")
    monkeypatch.setenv("LWS_ADMIN_USER", "root-admin")
    monkeypatch.setenv("LWS_ADMIN_PASSWORD", ADMIN_PASSWORD)
    return _build_app()


def _cloud_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LWS_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("LWS_ADMIN_USER", "root-admin")
    monkeypatch.setenv("LWS_ADMIN_PASSWORD", ADMIN_PASSWORD)
    return _build_app()


def _clear_registration_limiter() -> None:
    limiter = getattr(auth, "registration_rate_limiter", None)
    if limiter is not None:
        limiter._state.clear()  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def reset_test_state(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _AUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    _build_app()
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()
    auth.login_rate_limiter._state.clear()  # type: ignore[attr-defined]
    _clear_registration_limiter()
    yield
    auth.login_rate_limiter._state.clear()  # type: ignore[attr-defined]
    _clear_registration_limiter()
    for name in _AUTH_ENV_VARS:
        os.environ.pop(name, None)
    _build_app()


def _create_user(username: str, password: str = "Sup3rSecret!", role: str = "admin", status: str = "active") -> dict:
    return db.create_user(username, auth.hash_password(password), role, display_name=username.title(), status=status)


def test_cloud_self_registration_returns_me_shape_and_authenticated_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _cloud_app(monkeypatch)
    password = "Register-Pass1!"

    with TestClient(
        test_app,
        base_url="https://testserver",
        client=("203.0.113.50", 50000),
    ) as client:
        response = client.post(
            REGISTER_URL,
            json={"username": "  new-member  ", "password": password},
        )
        assert response.status_code == 201, response.text
        registered = response.json()
        me_response = client.get(ME_URL)

    assert me_response.status_code == 200, me_response.text
    assert registered == me_response.json()
    assert set(registered) == {
        "id",
        "username",
        "display_name",
        "role",
        "must_change_password",
        "auth_enabled",
        "capabilities",
    }
    assert registered["username"] == "new-member"
    assert registered["display_name"] == "new-member"
    assert registered["role"] == "member"
    assert registered["must_change_password"] is False
    assert registered["auth_enabled"] is True
    assert registered["capabilities"] == authz.capabilities_for_role("member")
    set_cookie = response.headers.get("set-cookie", "")
    assert f"{auth.SESSION_COOKIE_NAME}=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "secure" in set_cookie.lower()

    stored = db.get_user_by_username("new-member")
    assert stored is not None
    assert stored["status"] == "active"
    assert stored["must_change_password"] is False
    assert auth.verify_password(stored["password_hash"], password)
    assert db.list_projects() == []

    raw_audit = (DATA_ROOT / AUDIT_LOG_FILENAME).read_text(encoding="utf-8")
    entries = [json.loads(line) for line in raw_audit.splitlines()]
    assert len(entries) == 1
    assert entries[0]["action"] == "self_register"
    assert entries[0]["detail"] == {
        "user_id": registered["id"],
        "username": "new-member",
    }
    assert password not in raw_audit
    assert "203.0.113.50" not in raw_audit


def test_self_registration_trims_display_name_but_not_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)
    password = " 1234567"

    with TestClient(test_app) as client:
        response = client.post(
            REGISTER_URL,
            json={
                "username": "trim-check",
                "display_name": "  Trimmed Name  ",
                "password": password,
            },
        )

    assert response.status_code == 201, response.text
    assert response.json()["display_name"] == "Trimmed Name"
    stored = db.get_user_by_username("trim-check")
    assert stored is not None
    assert auth.verify_password(stored["password_hash"], password)
    assert auth.verify_password(stored["password_hash"], password.strip()) is False


@pytest.mark.parametrize("forbidden_field", ["role", "status", "must_change_password"])
def test_self_registration_rejects_server_owned_fields_without_creating_user(
    monkeypatch: pytest.MonkeyPatch,
    forbidden_field: str,
) -> None:
    test_app = _required_app(monkeypatch)
    username = f"extra-{forbidden_field}"
    payload: dict[str, object] = {
        "username": username,
        "password": "Register-Pass1!",
        forbidden_field: "admin" if forbidden_field == "role" else True,
    }

    with TestClient(test_app) as client:
        response = client.post(REGISTER_URL, json=payload)

    assert response.status_code == 422, response.text
    assert db.get_user_by_username(username) is None


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "   ", "password": "Register-Pass1!"},
        {"username": "u" * 129, "password": "Register-Pass1!"},
        {"username": "valid-user", "display_name": "d" * 129, "password": "Register-Pass1!"},
        {"username": "valid-user", "password": "short-7"},
        {"username": "valid-user", "password": "p" * 129},
    ],
)
def test_self_registration_validation_rejects_invalid_lengths(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    test_app = _required_app(monkeypatch)

    with TestClient(test_app) as client:
        response = client.post(REGISTER_URL, json=payload)

    assert response.status_code == 422, response.text


def test_self_registration_same_and_case_variant_duplicates_return_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)
    payload = {"username": "CaseUser", "password": "Register-Pass1!"}

    with TestClient(test_app) as client:
        first = client.post(REGISTER_URL, json=payload)
        same_case = client.post(REGISTER_URL, json=payload)
        case_variant = client.post(
            REGISTER_URL,
            json={"username": "caseuser", "password": "Register-Pass1!"},
        )

    assert first.status_code == 201, first.text
    assert same_case.status_code == 409, same_case.text
    assert case_variant.status_code == 409, case_variant.text
    assert [user["username"] for user in db.list_users()].count("CaseUser") == 1
    assert db.get_user_by_username("caseuser") is None


def test_concurrent_case_variant_self_registrations_create_exactly_one_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)
    start = threading.Barrier(2)

    with TestClient(test_app) as client:

        def register(username: str) -> tuple[int, dict]:
            start.wait(timeout=5)
            response = client.post(
                REGISTER_URL,
                json={"username": username, "password": "Register-Pass1!"},
            )
            return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(register, username) for username in ("RaceUser", "raceuser")]
            responses = [future.result(timeout=15) for future in futures]

    assert sorted(status for status, _body in responses) == [201, 409]
    assert sum(user["username"].casefold() == "raceuser" for user in db.list_users()) == 1


def test_self_registration_rate_limits_31st_attempt_per_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)
    monkeypatch.setattr(auth, "hash_password", lambda _password: "test-password-hash")
    payload = {"username": "rate-limited", "password": "Register-Pass1!"}

    with TestClient(test_app, client=("198.51.100.10", 50000)) as first_ip:
        accepted = [first_ip.post(REGISTER_URL, json=payload) for _ in range(30)]
        blocked = first_ip.post(REGISTER_URL, json=payload)

    assert accepted[0].status_code == 201, accepted[0].text
    assert all(response.status_code == 409 for response in accepted[1:])
    assert blocked.status_code == 429, blocked.text
    retry_after = blocked.headers.get("retry-after", "")
    assert retry_after.isdigit()
    assert int(retry_after) >= 1

    with TestClient(test_app, client=("198.51.100.11", 50000)) as second_ip:
        different_ip = second_ip.post(
            REGISTER_URL,
            json={"username": "different-ip", "password": "Register-Pass1!"},
        )
    assert different_ip.status_code == 201, different_ip.text


def test_registration_rate_limiter_bounds_tracked_ip_keys() -> None:
    fake_time = [0.0]
    limiter = auth.RegistrationRateLimiter(
        max_attempts=1,
        window_seconds=10.0,
        max_keys=2,
        clock=lambda: fake_time[0],
    )

    assert limiter.check_and_record("192.0.2.1") is None
    assert limiter.check_and_record("192.0.2.2") is None
    assert limiter.check_and_record("192.0.2.3") == 10
    assert len(limiter._state) == 2  # noqa: SLF001

    fake_time[0] = 10.1
    assert limiter.check_and_record("192.0.2.3") is None
    assert list(limiter._state) == ["192.0.2.3"]  # noqa: SLF001


def test_registration_rate_limiter_capacity_retry_after_waits_for_slot_release() -> None:
    fake_time = [0.0]
    limiter = auth.RegistrationRateLimiter(
        max_attempts=3,
        window_seconds=10.0,
        max_keys=1,
        clock=lambda: fake_time[0],
    )

    assert limiter.check_and_record("192.0.2.1") is None
    fake_time[0] = 5.0
    assert limiter.check_and_record("192.0.2.1") is None
    fake_time[0] = 6.0

    assert limiter.check_and_record("192.0.2.2") == 9


def test_self_registration_is_forbidden_when_auth_is_off_and_local_admin_survives() -> None:
    with TestClient(app) as client:
        response = client.post(
            REGISTER_URL,
            json={"username": "local-user", "password": "Register-Pass1!"},
        )
        me_response = client.get(ME_URL)

    assert response.status_code == 403, response.text
    assert db.get_user_by_username("local-user") is None
    assert me_response.status_code == 200, me_response.text
    assert me_response.json()["id"] == auth.LOCAL_ADMIN_USER["id"]


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


def test_login_success_returns_same_me_payload_with_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)
    _create_user("login-shape", role="member")

    with TestClient(test_app) as client:
        login_response = client.post(
            LOGIN_URL,
            json={"username": "login-shape", "password": "Sup3rSecret!"},
        )
        me_response = client.get(ME_URL)

    assert login_response.status_code == 200, login_response.text
    assert me_response.status_code == 200, me_response.text
    assert login_response.json() == me_response.json()
    assert login_response.json()["auth_enabled"] is True
    assert login_response.json()["capabilities"] == authz.capabilities_for_role("member")


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


def test_login_username_matching_remains_case_sensitive() -> None:
    _create_user("CaseLogin")

    with TestClient(app) as client:
        case_variant = client.post(
            LOGIN_URL,
            json={"username": "caselogin", "password": "Sup3rSecret!"},
        )
        exact_case = client.post(
            LOGIN_URL,
            json={"username": "CaseLogin", "password": "Sup3rSecret!"},
        )

    assert case_variant.status_code == 401
    assert exact_case.status_code == 200, exact_case.text


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


@pytest.mark.parametrize("session_kind", ["invalid", "revoked"])
def test_me_with_invalid_or_revoked_session_cookie_falls_back_to_local_admin_when_auth_is_off(
    session_kind: str,
) -> None:
    token = auth.generate_session_token()
    if session_kind == "revoked":
        user = _create_user("revoked-session-owner")
        token, _session = auth.issue_session(user["id"])
        auth.revoke_session(token)

    with TestClient(app) as client:
        client.cookies.set(auth.SESSION_COOKIE_NAME, token)
        response = client.get(ME_URL)

    assert response.status_code == 200, response.text
    assert response.json()["id"] == auth.LOCAL_ADMIN_USER["id"]
    assert response.json()["auth_enabled"] is False
    assert response.json()["capabilities"] == sorted(authz.ALL_CAPABILITIES)
    clear_cookie = response.headers.get("set-cookie", "").lower()
    assert f"{auth.SESSION_COOKIE_NAME}=" in clear_cookie
    assert "max-age=0" in clear_cookie


def test_me_with_invalid_session_cookie_is_rejected_when_auth_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)

    with TestClient(test_app) as client:
        client.cookies.set(auth.SESSION_COOKIE_NAME, auth.generate_session_token())
        response = client.get(ME_URL)

    assert response.status_code == 401
    assert response.json() == {"detail": "未登录"}


def test_session_resolution_cannot_mix_old_session_with_new_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _create_user("role-race", role="member")
    token, _session = auth.issue_session(user["id"])
    original_session_lookup = db.get_session_by_token_hash

    def promote_after_session_read(token_hash: str):
        session = original_session_lookup(token_hash)
        db.update_user(user["id"], {"role": "admin"}, revoke_sessions=True)
        return session

    monkeypatch.setattr(db, "get_session_by_token_hash", promote_after_session_read)

    resolved = auth.get_user_for_session_token(token)

    assert resolved is not None
    assert resolved["role"] == "member"


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


def test_expired_session_falls_back_to_local_admin_and_is_lazily_purged_when_auth_is_off() -> None:
    user = _create_user("frank")
    token = auth.generate_session_token()
    token_hash = auth.hash_token(token)
    db.create_session(user["id"], token_hash, "2000-01-01T00:00:00+00:00")

    with TestClient(app) as client:
        client.cookies.set(auth.SESSION_COOKIE_NAME, token)
        response = client.get(ME_URL)

    assert response.status_code == 200, response.text
    assert response.json()["id"] == auth.LOCAL_ADMIN_USER["id"]
    assert response.json()["auth_enabled"] is False
    clear_cookie = response.headers.get("set-cookie", "").lower()
    assert f"{auth.SESSION_COOKIE_NAME}=" in clear_cookie
    assert "max-age=0" in clear_cookie

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


def test_login_rate_limiter_sweeps_stale_keys_and_caps_unique_key_count() -> None:
    fake_time = [0.0]
    limiter = auth.LoginRateLimiter(
        max_failures=3,
        window_seconds=10.0,
        lockout_seconds=5.0,
        max_keys=3,
        clock=lambda: fake_time[0],
    )

    for index in range(3):
        limiter.record_failure(limiter.key(f"user-{index}", "10.0.0.1"))
    assert len(limiter._state) == 3  # noqa: SLF001 - deterministic capacity regression

    tracked = limiter.record_failure(limiter.key("user-3", "10.0.0.1"))
    assert tracked is False
    assert len(limiter._state) == 3  # noqa: SLF001
    assert limiter.key("user-0", "10.0.0.1") in limiter._state  # noqa: SLF001

    fake_time[0] += 10.1
    assert limiter.record_failure(limiter.key("fresh-user", "10.0.0.1")) is True
    assert list(limiter._state) == [limiter.key("fresh-user", "10.0.0.1")]  # noqa: SLF001


def test_login_rate_limiter_capacity_pressure_does_not_evict_locked_account() -> None:
    fake_time = [0.0]
    limiter = auth.LoginRateLimiter(
        max_failures=2,
        window_seconds=600.0,
        lockout_seconds=600.0,
        max_keys=3,
        clock=lambda: fake_time[0],
    )
    target_key = limiter.key("admin", "10.0.0.1")
    limiter.record_failure(target_key)
    limiter.record_failure(target_key)
    assert limiter.locked_seconds_remaining(target_key) == 600.0

    assert limiter.record_failure(limiter.key("decoy-1", "10.0.0.1")) is True
    assert limiter.record_failure(limiter.key("decoy-2", "10.0.0.1")) is True
    assert limiter.record_failure(limiter.key("decoy-3", "10.0.0.1")) is False

    assert limiter.locked_seconds_remaining(target_key) == 600.0
    assert target_key in limiter._state  # noqa: SLF001


def test_login_endpoint_fails_closed_when_rate_limit_capacity_is_full(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth.login_rate_limiter, "max_keys", 1)
    assert auth.login_rate_limiter.record_failure("occupied|10.0.0.1") is True
    _create_user("untracked")
    verify_calls = 0
    original_verify = auth.verify_password

    def counted_verify(password_hash: str, password: str) -> bool:
        nonlocal verify_calls
        verify_calls += 1
        return original_verify(password_hash, password)

    monkeypatch.setattr(auth, "verify_password", counted_verify)

    with TestClient(app) as client:
        response = client.post(LOGIN_URL, json={"username": "untracked", "password": "wrong"})

    assert response.status_code == 429
    assert verify_calls == 0


def test_login_rejects_overlong_username_before_rate_limit_tracking() -> None:
    with TestClient(app) as client:
        response = client.post(LOGIN_URL, json={"username": "u" * 129, "password": "irrelevant"})

    assert response.status_code == 422
    assert auth.login_rate_limiter._state == {}  # noqa: SLF001
