"""Admin-only user management API (A1 batch 3).

Boundary: no DELETE endpoint. Disabling a user (status=disabled) is the only
removal path -- it revokes the account's access immediately while keeping
its id/username around so past audit-log and operator-attribution entries
stay attributable. A hard delete would orphan those references.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .. import auth, db, operator_context
from ..authz import require_admin
from ..config import DATA_ROOT
from ..schemas import UserCreateRequest, UserPasswordResetRequest, UserUpdateRequest

router = APIRouter(dependencies=[Depends(require_admin)])

# role/status legality (admin|ops|member, active|disabled) is enforced by the
# ``Literal`` types on UserCreateRequest/UserUpdateRequest -- FastAPI rejects
# any other value with a 422 before the handler body runs.

# Not part of the batch-3 spec, but applied consistently with the
# change-password endpoint's 8-character floor: an admin-issued initial
# password is still a real credential handed to another account.
MIN_PASSWORD_LENGTH = 8


def _public_user_with_meta(user: dict[str, Any]) -> dict[str, Any]:
    payload = auth.public_user(user)
    payload["status"] = user.get("status", "active")
    payload["created_at"] = user.get("created_at")
    payload["last_login_at"] = user.get("last_login_at")
    return payload


@router.get("/api/users")
def list_users() -> list[dict[str, Any]]:
    return [_public_user_with_meta(user) for user in db.list_users()]


@router.post("/api/users")
def create_user(payload: UserCreateRequest) -> dict[str, Any]:
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if len(payload.initial_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"初始密码至少 {MIN_PASSWORD_LENGTH} 位")
    if db.get_user_by_username(username) is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")

    user = db.create_user(
        username,
        auth.hash_password(payload.initial_password),
        payload.role,
        display_name=payload.display_name.strip() or username,
        must_change_password=True,
    )
    operator_context.record_operator_audit(
        DATA_ROOT, "create_user", {"username": username, "role": payload.role}
    )
    return _public_user_with_meta(user)


@router.patch("/api/users/{user_id}")
def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    try:
        target = db.get_user(user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="用户不存在") from exc

    updates: dict[str, Any] = {}
    if payload.display_name is not None:
        updates["display_name"] = payload.display_name.strip()
    if payload.role is not None:
        if user_id == admin["id"] and payload.role != "admin":
            raise HTTPException(status_code=400, detail="不能修改自己的角色，防止管理员自我锁死")
        updates["role"] = payload.role
    if payload.status is not None:
        if user_id == admin["id"] and payload.status != "active":
            raise HTTPException(status_code=400, detail="不能停用自己的账号，防止管理员自我锁死")
        updates["status"] = payload.status

    if not updates:
        return _public_user_with_meta(target)

    role_changed = "role" in updates and updates["role"] != target.get("role")
    updated = db.update_user(
        user_id,
        updates,
        revoke_sessions=updates.get("status") == "disabled" or role_changed,
    )
    operator_context.record_operator_audit(
        DATA_ROOT,
        "update_user",
        {"username": target["username"], "changes": sorted(updates.keys())},
    )
    return _public_user_with_meta(updated)


@router.post("/api/users/{user_id}/reset-password")
def reset_password(user_id: str, payload: UserPasswordResetRequest) -> dict[str, Any]:
    try:
        target = db.get_user(user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="用户不存在") from exc
    if len(payload.initial_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"初始密码至少 {MIN_PASSWORD_LENGTH} 位")

    updated = db.update_user(
        user_id,
        {
            "password_hash": auth.hash_password(payload.initial_password),
            "must_change_password": True,
        },
        revoke_sessions=True,
    )
    operator_context.record_operator_audit(DATA_ROOT, "reset_password", {"username": target["username"]})
    return _public_user_with_meta(updated)
