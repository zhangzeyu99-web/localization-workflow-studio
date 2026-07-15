"""Authorization dependencies layered on top of ``auth.current_user()``.

Scope for A1 batch 3: a single ``require_admin`` FastAPI dependency guarding
the admin-only user management API. It intentionally reads the same
``auth.current_user()`` contextvar the authentication middleware populates,
so the existing "auth off -> synthetic local-admin" behavior is preserved
for free -- LOCAL_ADMIN_USER has role "admin", so it passes this check
without any special-casing here.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from . import auth


def require_admin() -> dict[str, Any]:
    user = auth.current_user()
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
