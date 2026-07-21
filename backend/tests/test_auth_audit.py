from __future__ import annotations

import json
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
from app.config import DATA_ROOT
from app.operator_context import AUDIT_LOG_FILENAME
from conftest import reset_data_root

LOGIN_URL = "/api/auth/login"
LOGOUT_URL = "/api/auth/logout"

BOOTSTRAP_PASSWORD = "Initial-Admin-Password!"
LOCAL_REQUIRED_PROFILE = config.RuntimeProfile("local", "required")


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    for name in ("LWS_AUTH_MODE", "LWS_DEPLOYMENT_MODE", "LWS_ADMIN_USER", "LWS_ADMIN_PASSWORD"):
        os.environ.pop(name, None)
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()
    auth.login_rate_limiter._state.clear()  # type: ignore[attr-defined]
    yield
    auth.login_rate_limiter._state.clear()  # type: ignore[attr-defined]


def _required_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    username: str = "root-admin",
):
    monkeypatch.setenv("LWS_ADMIN_USER", username)
    monkeypatch.setenv("LWS_ADMIN_PASSWORD", BOOTSTRAP_PASSWORD)
    return main_module.create_app(LOCAL_REQUIRED_PROFILE)


def _audit_entries() -> list[dict]:
    path = DATA_ROOT / AUDIT_LOG_FILENAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _create_user(username: str, password: str = "Sup3rSecret!", role: str = "admin") -> dict:
    return db.create_user(username, auth.hash_password(password), role, display_name=username.title())


def test_successful_login_is_audited_with_real_identity_not_x_operator_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The login request itself has no session yet, so the authentication
    middleware cannot have populated operator_context's contextvar with the
    logging-in user's identity for this request -- the audit entry must
    still name the real account, not whatever unrelated X-Operator nickname
    header the caller happened to send."""
    test_app = _required_app(monkeypatch)
    _create_user("heidi")
    with TestClient(test_app) as client:
        response = client.post(
            LOGIN_URL,
            json={"username": "heidi", "password": "Sup3rSecret!"},
            headers={"X-Operator": "Spoofed Nickname"},
        )
        assert response.status_code == 200, response.text

    entries = _audit_entries()
    assert entries, "login must produce an audit entry"
    assert entries[-1]["action"] == "login"
    assert entries[-1]["operator"] == "Heidi"
    assert entries[-1]["detail"]["username"] == "heidi"


def test_failed_login_is_not_audited(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auditing every failed attempt would let a brute-force run flood the
    audit log; only successful logins are recorded (A4 requirement)."""
    test_app = _required_app(monkeypatch)
    _create_user("ivan")
    with TestClient(test_app) as client:
        wrong_password = client.post(LOGIN_URL, json={"username": "ivan", "password": "wrong"})
        assert wrong_password.status_code == 401
        unknown_user = client.post(LOGIN_URL, json={"username": "no-such-user", "password": "whatever"})
        assert unknown_user.status_code == 401

    assert _audit_entries() == []


def test_logout_of_real_session_is_audited(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once authentication is enforced, the middleware resolves operator
    identity from the session on every authenticated request (including
    logout itself), so this does not need an explicit ``operator=`` override
    the way the login handler does."""
    test_app = _required_app(monkeypatch, username="judy")
    with TestClient(test_app) as client:
        login = client.post(LOGIN_URL, json={"username": "judy", "password": BOOTSTRAP_PASSWORD})
        assert login.status_code == 200, login.text
        logout_response = client.post(LOGOUT_URL)
        assert logout_response.status_code == 200

    entries = _audit_entries()
    assert [entry["action"] for entry in entries] == ["login", "logout"]
    assert entries[-1]["operator"] == "judy"


def test_logout_without_an_active_session_is_not_audited(monkeypatch: pytest.MonkeyPatch) -> None:
    """A logout call with no valid session cookie has no identity to
    attribute; an unauthenticated X-Operator header must not forge one."""
    test_app = _required_app(monkeypatch, username="kelly")
    with TestClient(test_app) as client:
        response = client.post(LOGOUT_URL, headers={"X-Operator": "forged-outsider"})
        assert response.status_code == 200

    assert _audit_entries() == []
