"""Unit tests for scripts/deployment_auth.py, the shared login helper used by
check.py's deployment_check and stability_check (A4).

Loaded the same way test_risk_hardening.py loads scripts/deployment_check.py
(importlib file-spec, not a package import) so this does not depend on
"scripts" being importable as a package from the current working directory.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module():
    script_path = (_REPO_ROOT / "scripts" / "deployment_auth.py").resolve()
    spec = importlib.util.spec_from_file_location("deployment_auth", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


deployment_auth = _load_module()


def test_login_success_returns_public_user_and_leaves_session_cookie_on_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/auth/login"
        assert request.method == "POST"
        return httpx.Response(
            200,
            json={"username": "alice", "role": "admin", "must_change_password": False},
            headers={"set-cookie": "lws_session=abc123; Path=/; HttpOnly"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        body = deployment_auth.login(client, "http://test", "alice", "secret")
        assert body["username"] == "alice"
        assert client.cookies.get("lws_session") == "abc123"


def test_login_wrong_credentials_raises_auth_login_error_with_server_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "用户名或密码错误"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(deployment_auth.AuthLoginError, match="用户名或密码错误"):
            deployment_auth.login(client, "http://test", "alice", "wrong-password")


def test_login_rate_limited_raises_auth_login_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"detail": "登录尝试过多，请在 600 秒后重试。"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(deployment_auth.AuthLoginError, match="429"):
            deployment_auth.login(client, "http://test", "alice", "secret")


def test_login_pending_first_login_password_change_raises_dedicated_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"username": "bob", "role": "admin", "must_change_password": True})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(deployment_auth.PasswordChangeRequiredError) as exc_info:
            deployment_auth.login(client, "http://test", "bob", "secret")

    message = str(exc_info.value)
    assert "bob" in message
    assert "create_admin.py" in message
    assert exc_info.value.username == "bob"


def test_login_without_credentials_raises_before_any_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not make a network call without credentials")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(deployment_auth.AuthLoginError):
            deployment_auth.login(client, "http://test", "", "")
        with pytest.raises(deployment_auth.AuthLoginError):
            deployment_auth.login(client, "http://test", "alice", "")


def test_unauthenticated_probe_status_uses_a_cookie_free_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "cookie" not in request.headers
        assert request.url.path == "/api/projects"
        return httpx.Response(401, json={"detail": "未登录"})

    status = deployment_auth.unauthenticated_probe_status(
        "http://test", "/api/projects", transport=httpx.MockTransport(handler)
    )
    assert status == 401


def test_unauthenticated_probe_status_reports_broken_fail_closed_gate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    status = deployment_auth.unauthenticated_probe_status(
        "http://test", "/api/projects", transport=httpx.MockTransport(handler)
    )
    assert status == 200


def test_response_error_detail_prefers_json_detail_field() -> None:
    response = httpx.Response(403, json={"detail": "需要管理员权限"})
    assert deployment_auth.response_error_detail(response) == "需要管理员权限"


def test_response_error_detail_falls_back_to_raw_text_for_non_json_bodies() -> None:
    response = httpx.Response(500, text="internal server error trace")
    assert deployment_auth.response_error_detail(response) == "internal server error trace"
