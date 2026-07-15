"""Authorization primitives layered on top of ``auth.current_user()``.

A1 batch 3 scope: ``require_admin``, a single FastAPI dependency guarding the
admin-only user management API.

A2 batch 1+2 scope: a small capability vocabulary (``PROJECT_READ``,
``TASK_RUN``, ``ASSETS_CURATE``, ``PROJECT_MANAGE``, ``ADMIN``), a role ->
capability-set mapping per the plan's §2.1 matrix, and ``require_project_access``
for the project-membership check. The per-route wiring that decides *which*
capability a given (method, path) needs lives in ``route_capabilities.py`` --
this module only knows how to answer "does this role have this capability"
and "is this user allowed to see this project", not which route asked.

All of these read the same ``auth.current_user()`` contextvar the
authentication middleware populates, so the existing "auth off -> synthetic
local-admin" behavior keeps working for free: ``LOCAL_ADMIN_USER`` has role
"admin", which is always allowed and always bypasses the membership check.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException

from . import auth, db

PROJECT_READ = "project:read"
TASK_RUN = "task:run"
ASSETS_CURATE = "assets:curate"
PROJECT_MANAGE = "project:manage"
ADMIN = "admin:*"

ALL_CAPABILITIES = {PROJECT_READ, TASK_RUN, ASSETS_CURATE, PROJECT_MANAGE, ADMIN}

# Plan §2.1 role -> capability matrix. "admin" gets every capability
# (including future ones added to ALL_CAPABILITIES) rather than an
# enumerated set, so a newly-introduced capability defaults to
# "admin can, nobody else can yet" instead of silently excluding admins.
ROLE_CAPABILITIES: dict[str, set[str]] = {
    "ops": {PROJECT_READ, TASK_RUN, ASSETS_CURATE, PROJECT_MANAGE},
    "member": {PROJECT_READ, TASK_RUN},
}


def capability_allowed(role: str, capability: str) -> bool:
    if role == "admin":
        return True
    return capability in ROLE_CAPABILITIES.get(role, set())


def require_admin() -> dict[str, Any]:
    user = auth.current_user()
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def require_capability(capability: str) -> Callable[[], dict[str, Any]]:
    """FastAPI dependency factory: 401 if not logged in, 403 if the user's
    role lacks ``capability``. Mainly useful for the small number of
    endpoints (e.g. the future members router) that want an explicit
    ``Depends(...)`` instead of relying on the central route-capability
    table in ``route_capabilities.py``.
    """

    def _dependency() -> dict[str, Any]:
        user = auth.current_user()
        if user is None:
            raise HTTPException(status_code=401, detail="未登录")
        if not capability_allowed(user.get("role", ""), capability):
            raise HTTPException(status_code=403, detail="权限不足")
        return user

    return _dependency


def require_project_access(project_id: str) -> dict[str, Any]:
    """Admins see every project; everyone else must be a member.

    Not-a-member is reported as 404 (not 403) on purpose: the plan's
    fundamental non-negotiable is that a project's mere existence must not be
    enumerable by someone who isn't allowed to see it. This is also used
    outside of FastAPI's dependency injection (e.g. inside list-filtering
    handlers), so it is a plain function rather than a Depends-only factory.
    """
    user = auth.current_user()
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    if user.get("role") == "admin":
        return user
    if not db.is_project_member(project_id, user["id"]):
        raise HTTPException(status_code=404, detail="project not found")
    return user
