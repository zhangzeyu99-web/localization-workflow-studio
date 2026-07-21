"""Login/logout/me/change-password endpoints.

login/logout/me are A1 batch 1 (no global enforcement); the mode switch that
makes authentication mandatory in cloud deployments is A1 batch 2's job.
change-password is A1 batch 3, paired with the first-login enforcement gate
in ``main.py``'s ``_enforce_authentication`` middleware.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import auth, authz, db, operator_context
from ..config import DATA_ROOT, RuntimeProfile
from ..schemas import ChangePasswordRequest, LoginRequest, RegisterRequest

router = APIRouter()

LOGIN_ERROR_DETAIL = "用户名或密码错误"
MIN_NEW_PASSWORD_LENGTH = 8


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _runtime_profile(request: Request) -> RuntimeProfile:
    return request.app.state.runtime_profile


def _set_session_cookie(
    response: Response,
    token: str,
    runtime_profile: RuntimeProfile,
) -> None:
    response.set_cookie(
        key=auth.SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=runtime_profile.secure_cookies,
        path="/",
        max_age=auth.SESSION_TTL_DAYS * 24 * 3600,
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=auth.SESSION_COOKIE_NAME, path="/")


def _me_payload(user: dict[str, Any], *, auth_enabled: bool) -> dict[str, Any]:
    return {
        **auth.public_user(user),
        "auth_enabled": auth_enabled,
        "capabilities": authz.capabilities_for_role(user.get("role", "")),
    }


@router.post(
    "/api/auth/register",
    status_code=201,
    dependencies=[Depends(authz.require_account_mode)],
)
def register(payload: RegisterRequest, request: Request, response: Response) -> dict[str, Any]:
    runtime_profile = _runtime_profile(request)
    retry_after = auth.registration_rate_limiter.check_and_record(_client_ip(request))
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="注册请求过多，请稍后重试。",
            headers={"Retry-After": str(retry_after)},
        )

    username = payload.username
    try:
        user = db.create_user(
            username,
            auth.hash_password(payload.password),
            "member",
            display_name=payload.display_name or username,
            status="active",
            must_change_password=False,
        )
    except db.UsernameConflictError as exc:
        raise HTTPException(status_code=409, detail="用户名已存在") from exc

    token, _session = auth.issue_session(user["id"])
    _set_session_cookie(response, token, runtime_profile)
    operator_context.record_operator_audit(
        DATA_ROOT,
        "self_register",
        {"user_id": user["id"], "username": user["username"]},
        operator=user["username"],
    )
    return _me_payload(user, auth_enabled=runtime_profile.auth_required)


@router.post(
    "/api/auth/login",
    dependencies=[Depends(authz.require_account_mode)],
)
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    runtime_profile = _runtime_profile(request)
    username = payload.username.strip()
    rate_key = auth.login_rate_limiter.key(username, _client_ip(request))

    remaining = auth.login_rate_limiter.locked_seconds_remaining(rate_key)
    if remaining > 0:
        raise HTTPException(status_code=429, detail=f"登录尝试过多，请在 {int(remaining) + 1} 秒后重试。")
    if not auth.login_rate_limiter.can_attempt(rate_key):
        raise HTTPException(status_code=429, detail="登录请求过多，请稍后重试。")

    user = db.get_user_by_username(username)
    # Same 401 for "no such user", "wrong password", and "disabled account"
    # so a caller can't distinguish a bad password from account enumeration.
    if user is None or user.get("status") == "disabled" or not auth.verify_password(user["password_hash"], payload.password):
        if not auth.login_rate_limiter.record_failure(rate_key):
            raise HTTPException(status_code=429, detail="登录请求过多，请稍后重试。")
        raise HTTPException(status_code=401, detail=LOGIN_ERROR_DETAIL)

    auth.login_rate_limiter.record_success(rate_key)
    token, _session = auth.issue_session(user["id"])
    db.update_user(user["id"], {"last_login_at": db.now_iso()})
    _set_session_cookie(response, token, runtime_profile)
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
    return _me_payload(user, auth_enabled=runtime_profile.auth_required)


@router.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict[str, Any]:
    token = request.cookies.get(auth.SESSION_COOKIE_NAME, "")
    session_user = auth.get_user_for_session_token(token) if token else None
    auth.revoke_session(token)
    _clear_session_cookie(response)
    if session_user is not None:
        operator_context.record_operator_audit(
            DATA_ROOT,
            "logout",
            operator=session_user.get("display_name") or session_user["username"],
        )
    return {"ok": True}


@router.get("/api/auth/me")
def me(request: Request, response: Response) -> dict[str, Any]:
    """Report the caller's identity plus the frontend's permission-gate inputs.

    Auth-off always exposes the synthetic local administrator. Any cookie is
    revoked and cleared so a required-mode identity cannot leak into this
    profile or revive when authentication is enabled again.
    """
    auth_enabled = _runtime_profile(request).auth_required
    cookie_present = auth.SESSION_COOKIE_NAME in request.cookies
    token = request.cookies.get(auth.SESSION_COOKIE_NAME, "")
    if not auth_enabled:
        if cookie_present:
            auth.revoke_session(token)
            _clear_session_cookie(response)
        return _me_payload(auth.LOCAL_ADMIN_USER, auth_enabled=False)

    user = auth.get_user_for_session_token(token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return _me_payload(user, auth_enabled=auth_enabled)


@router.post(
    "/api/auth/change-password",
    dependencies=[Depends(authz.require_account_mode)],
)
def change_password(payload: ChangePasswordRequest, request: Request, response: Response) -> dict[str, Any]:
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
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")

    db.update_user(
        user["id"],
        {"password_hash": auth.hash_password(payload.new_password), "must_change_password": False},
        revoke_sessions=True,
    )
    # Revoke every existing session (including the one used for this request)
    # and issue a fresh one -- simpler than "revoke others, keep this one" and
    # gives the same guarantee: the pre-change-password token is dead, and
    # exactly one valid session (this browser's) survives.
    token, _session = auth.issue_session(user["id"])
    _set_session_cookie(response, token, _runtime_profile(request))
    operator_context.record_operator_audit(DATA_ROOT, "change_password", {"username": user["username"]})
    return {"ok": True}
