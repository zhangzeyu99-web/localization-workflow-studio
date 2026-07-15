"""Login/logout/me endpoints (A1 batch 1: no global enforcement yet).

Nothing here changes any other router's behavior. The mode switch that makes
authentication mandatory in cloud deployments is A1 batch 2's job.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from .. import auth, db
from ..schemas import LoginRequest
from .system import _deployment_mode

router = APIRouter()

LOGIN_ERROR_DETAIL = "用户名或密码错误"


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=auth.SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=_deployment_mode() == "cloud",
        path="/",
        max_age=auth.SESSION_TTL_DAYS * 24 * 3600,
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=auth.SESSION_COOKIE_NAME, path="/")


@router.post("/api/auth/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    username = payload.username.strip()
    rate_key = auth.login_rate_limiter.key(username, _client_ip(request))

    remaining = auth.login_rate_limiter.locked_seconds_remaining(rate_key)
    if remaining > 0:
        raise HTTPException(status_code=429, detail=f"登录尝试过多，请在 {int(remaining) + 1} 秒后重试。")

    user = db.get_user_by_username(username)
    # Same 401 for "no such user", "wrong password", and "disabled account"
    # so a caller can't distinguish a bad password from account enumeration.
    if user is None or user.get("status") == "disabled" or not auth.verify_password(user["password_hash"], payload.password):
        auth.login_rate_limiter.record_failure(rate_key)
        raise HTTPException(status_code=401, detail=LOGIN_ERROR_DETAIL)

    auth.login_rate_limiter.record_success(rate_key)
    token, _session = auth.issue_session(user["id"])
    db.update_user(user["id"], {"last_login_at": db.now_iso()})
    _set_session_cookie(response, token)
    return auth.public_user(user)


@router.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict[str, Any]:
    token = request.cookies.get(auth.SESSION_COOKIE_NAME, "")
    auth.revoke_session(token)
    _clear_session_cookie(response)
    return {"ok": True}


@router.get("/api/auth/me")
def me(request: Request) -> dict[str, Any]:
    token = request.cookies.get(auth.SESSION_COOKIE_NAME, "")
    user = auth.get_user_for_session_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return auth.public_user(user)
