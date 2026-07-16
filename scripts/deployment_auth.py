"""Shared login helpers for check.py's deployment_check and stability_check.

A4 of docs/superpowers/plans/2026-07-15-account-permission-system.md: both
smoke-check scripts need the same "log in first, then run the rest of the
checks with that session" flow once a deployment has ``LWS_AUTH_MODE=required``
(cloud default). This module exists so that flow -- and, more importantly,
its two failure modes that must NOT be misreported as a generic deployment
failure -- lives in exactly one place instead of being duplicated:

- Wrong credentials / disabled account / rate-limited -> ``AuthLoginError``.
- Correct credentials but the account still owes its first-login mandatory
  password change (A1 batch 3) -> ``PasswordChangeRequiredError``. Every
  other authenticated ``/api/*`` call 403s with "首次登录请先修改密码" until
  that happens, so callers must stop and surface this as an actionable
  operator instruction, not a broken-deployment symptom.
"""

from __future__ import annotations

from typing import Any

import httpx


class AuthLoginError(RuntimeError):
    """The login call itself failed: bad credentials, disabled account, or
    rate-limited by the server's brute-force guard."""


class PasswordChangeRequiredError(RuntimeError):
    """Login succeeded but the account has a pending first-login password
    change, so its session cannot be used for any other API call yet."""

    def __init__(self, username: str) -> None:
        super().__init__(
            f"账号 {username} 处于首次登录强制改密状态，登录态暂时无法用于其它接口。"
            f"请先通过前端登录并完成改密，或运行 `python scripts/create_admin.py "
            f"--username {username}` 重置密码后重试。"
        )
        self.username = username


def response_error_detail(response: httpx.Response) -> str:
    """Best-effort human-readable detail for a non-2xx response.

    Prefers the API's ``{"detail": ...}`` JSON error shape (see
    ``UserFacingError``'s exception handler in main.py); falls back to raw
    text for anything else so a probe never crashes trying to explain why it
    failed.
    """
    try:
        detail = response.json().get("detail")
    except Exception:
        detail = None
    return str(detail) if detail else response.text[:500]


def login(client: httpx.Client, base_url: str, username: str, password: str) -> dict[str, Any]:
    """Log ``client`` in, leaving the session cookie on it for later calls.

    Returns the ``/api/auth/login`` response body (public user fields,
    including ``must_change_password``) on success. Raises ``AuthLoginError``
    if the login call itself failed, or ``PasswordChangeRequiredError`` if it
    succeeded but the session cannot be used for anything else yet.
    """
    if not username or not password:
        raise AuthLoginError("需要同时提供 --auth-user 和 --auth-password 才能登录")
    response = client.post(
        f"{base_url.rstrip('/')}/api/auth/login",
        json={"username": username, "password": password},
    )
    if response.status_code != 200:
        raise AuthLoginError(f"登录失败（HTTP {response.status_code}）：{response_error_detail(response)}")
    body = response.json()
    if body.get("must_change_password"):
        raise PasswordChangeRequiredError(username)
    return body


def unauthenticated_probe_status(
    base_url: str,
    path: str,
    *,
    timeout: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """GET ``path`` with a brand-new, cookie-free client; return its status code.

    Used for the fail-closed self-check: this must be indistinguishable from
    "never logged in" regardless of whether the caller's own client happens
    to hold an authenticated session, so it always opens its own throwaway
    client rather than reusing/clearing the caller's. ``transport`` defaults
    to ``None`` (real network); tests pass ``httpx.MockTransport(...)``.
    """
    with httpx.Client(timeout=timeout, follow_redirects=True, transport=transport) as anon_client:
        response = anon_client.get(f"{base_url.rstrip('/')}{path}")
    return response.status_code
