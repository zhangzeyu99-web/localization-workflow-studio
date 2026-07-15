from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app import auth, db, operator_context
    from app.errors import UserFacingError, http_status_for_user_facing_error
    from app.workflow import reconcile_interrupted_background_jobs, user_facing_error
    from app.routers.api import router as api_router
else:
    from . import auth, db, operator_context
    from .errors import UserFacingError, http_status_for_user_facing_error
    from .workflow import reconcile_interrupted_background_jobs, user_facing_error
    from .routers.api import router as api_router


AUTH_REQUIRED = auth.auth_required()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ = app
    db.init_db()
    db.purge_expired_sessions()
    auth.bootstrap_initial_admin(required=AUTH_REQUIRED)
    reconcile_interrupted_background_jobs()
    yield


def _cors_origins() -> list[str]:
    defaults = ["http://localhost:5173", "http://127.0.0.1:5173"]
    configured = os.environ.get("LWS_CORS_ORIGINS", "")
    extra = [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [*defaults, *[origin for origin in extra if origin not in defaults]]


app = FastAPI(title="Localization Workflow Studio", version="1.3.1", lifespan=lifespan)
app.include_router(api_router)


@app.middleware("http")
async def _no_store_api_responses(request: Request, call_next):
    """API responses must never be cached by browsers, proxies, or CDNs.

    Without an explicit Cache-Control header, an intermediary CDN in front of
    nginx may cache GET responses such as /api/version or project lists and
    keep serving stale data after a redeploy.
    """
    response = await call_next(request)
    if request.url.path.startswith("/api/") and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    return response


_PRELOGIN_API_ENDPOINTS = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/me"),
    # check.py delegates to deployment_check.py, whose pre-login reads are
    # limited to version and health. Its upload-readability probe writes files
    # to disk, so it must NOT be exempted here (unauthenticated disk-fill
    # surface); when auth is required, deployment_check must log in first --
    # adding --auth-user/--auth-password there is a planned A4 task (see
    # docs/superpowers/plans/2026-07-15-account-permission-system.md §3).
    ("GET", "/api/version"),
    ("GET", "/api/health"),
}


@app.middleware("http")
async def _enforce_authentication(request: Request, call_next):
    path = request.url.path
    operator_header = request.headers.get("x-operator")

    if not AUTH_REQUIRED:
        request.state.user = auth.LOCAL_ADMIN_USER
        auth.set_current_user(auth.LOCAL_ADMIN_USER)
        # Local/off mode intentionally preserves the legacy X-Operator audit
        # behavior even though authorization sees the synthetic administrator.
        operator_context.set_current_operator(operator_header)
        return await call_next(request)

    auth.set_current_user(None)
    if not path.startswith("/api/"):
        return await call_next(request)

    token = request.cookies.get(auth.SESSION_COOKIE_NAME, "")
    user = auth.get_user_for_session_token(token)
    if user is not None:
        request.state.user = user
        auth.set_current_user(user)
        operator_context.set_current_operator(user.get("display_name") or user.get("username"))
        return await call_next(request)

    operator_context.set_current_operator(operator_header)
    if (request.method.upper(), path) in _PRELOGIN_API_ENDPOINTS:
        return await call_next(request)
    return JSONResponse(
        status_code=401,
        content={"detail": "未登录"},
        headers={"Cache-Control": "no-store"},
    )


@app.middleware("http")
async def _capture_operator_header(request: Request, call_next):
    """Make the optional ``X-Operator`` nickname available to this request's
    handler (sync or async) via operator_context.current_operator(), without
    threading it through every function signature. See operator_context.py
    for why this is safe across FastAPI's sync-endpoint threadpool.
    """
    operator_context.set_current_operator(request.headers.get("x-operator"))
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(UserFacingError)
async def _handle_user_facing_error(request: Request, exc: UserFacingError) -> JSONResponse:
    """Safety net: a UserFacingError escaping any route becomes a sanitized JSON error.

    Response shape matches HTTPException ({"detail": ...}) so frontend apiErrorText keeps working.
    """
    _ = request
    return JSONResponse(
        status_code=http_status_for_user_facing_error(exc),
        content={"detail": user_facing_error(exc)},
    )


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False, app_dir=str(Path(__file__).resolve().parents[1]))
