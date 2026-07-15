"""Login/logout/me/change-password endpoints.

login/logout/me are A1 batch 1 (no global enforcement); the mode switch that
makes authentication mandatory in cloud deployments is A1 batch 2's job.
change-password is A1 batch 3, paired with the first-login enforcement gate
in ``main.py``'s ``_enforce_authentication`` middleware.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from .. import auth, authz, db, operator_context
from ..config import DATA_ROOT, deployment_mode
from ..schemas import ChangePasswordRequest, LoginRequest

router = APIRouter()

LOGIN_ERROR_DETAIL = "用户名或密码错误"
MIN_NEW_PASSWORD_LENGTH = 8


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=auth.SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=deployment_mode() == "cloud",
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
    # The login request itself has no session yet, so the authentication
    # middleware cannot have populated operator_context's contextvar with
    # this user's identity for this request -- pass it explicitly instead of
    # falling back to whatever (unrelated) X-Operator nickname was sent.
    operator_context.record_operator_audit(
        DATA_ROOT,
        "login",
        {"username": user["username"]},
        operator=user.get("display_name") or user["username"],
    )
    return auth.public_user(user)


@router.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict[str, Any]:
    token = request.cookies.get(auth.SESSION_COOKIE_NAME, "")
    auth.revoke_session(token)
    _clear_session_cookie(response)
    # Login failures are intentionally not audited (would let a brute-force
    # attempt flood the audit log); a logout call with no prior valid session
    # has no identity to attribute either, so record_operator_audit's
    # contextvar-empty no-op is exactly the right behavior here.
    operator_context.record_operator_audit(DATA_ROOT, "logout")
    return {"ok": True}


@router.get("/api/auth/me")
def me(request: Request) -> dict[str, Any]:
    """Report the caller's identity plus the frontend's permission-gate inputs.

    Auth-off/local mode's dominant case is "no session cookie at all" (the
    frontend never shows a login page here) -- that must resolve to the
    synthetic local administrator, not 401, or the app-shell gate would
    wrongly bounce every local deployment to a login screen. A *present*
    session cookie is still honored either way (an operator can log in with
    a real account even while enforcement happens to be off), and an
    invalid/expired cookie is always rejected regardless of mode -- only the
    "no cookie presented" case falls back to the synthetic admin, and only
    when enforcement is off.
    """
    auth_enabled = auth.auth_required()
    token = request.cookies.get(auth.SESSION_COOKIE_NAME, "")
    if token:
        user = auth.get_user_for_session_token(token)
        if user is None:
            raise HTTPException(status_code=401, detail="未登录")
    elif auth_enabled:
        raise HTTPException(status_code=401, detail="未登录")
    else:
        user = auth.current_user() or auth.LOCAL_ADMIN_USER
    return {
        **auth.public_user(user),
        "auth_enabled": auth_enabled,
        "capabilities": authz.capabilities_for_role(user.get("role", "")),
    }


@router.post("/api/auth/change-password")
def change_password(payload: ChangePasswordRequest, response: Response) -> dict[str, Any]:
    user = auth.current_user()
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    if user["id"] == auth.LOCAL_ADMIN_USER["id"]:
        # Auth-off mode never persists LOCAL_ADMIN_USER to the users table --
        # there is no password row to change.
        raise HTTPException(status_code=400, detail="本地模式无需修改密码")

    stored = db.get_user(user["id"])
    if not auth.verify_password(stored["password_hash"], payload.current_password):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    if len(payload.new_password) < MIN_NEW_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"新密码至少 {MIN_NEW_PASSWORD_LENGTH} 位")

    db.update_user(
        user["id"],
        {"password_hash": auth.hash_password(payload.new_password), "must_change_password": False},
    )
    # Revoke every existing session (including the one used for this request)
    # and issue a fresh one -- simpler than "revoke others, keep this one" and
    # gives the same guarantee: the pre-change-password token is dead, and
    # exactly one valid session (this browser's) survives.
    db.delete_sessions_for_user(user["id"])
    token, _session = auth.issue_session(user["id"])
    _set_session_cookie(response, token)
    operator_context.record_operator_audit(DATA_ROOT, "change_password", {"username": user["username"]})
    return {"ok": True}
