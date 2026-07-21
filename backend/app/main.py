from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app import auth, background_jobs, config, db, job_queue, operator_context, route_capabilities
    from app.errors import UserFacingError, http_status_for_user_facing_error
    from app.workflow import user_facing_error
    from app.routers.api import router as api_router
else:
    from . import auth, background_jobs, config, db, job_queue, operator_context, route_capabilities
    from .errors import UserFacingError, http_status_for_user_facing_error
    from .workflow import user_facing_error
    from .routers.api import router as api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime_profile = app.state.runtime_profile
    profile_token = config.bind_runtime_profile(runtime_profile)
    try:
        db.init_db()
        if runtime_profile.auth_required:
            db.purge_expired_sessions()
            auth.bootstrap_initial_admin(
                required=True,
                username=app.state.bootstrap_admin_username,
                password=app.state.bootstrap_admin_password,
            )
        else:
            db.delete_all_sessions()
        background_jobs.register_handlers()
        interrupted = job_queue.recover_interrupted_jobs()
        background_jobs.reconcile_startup(interrupted)
        job_queue.resume_dispatchers()
        try:
            yield
        finally:
            job_queue.shutdown_dispatchers(cancel_running=False)
    finally:
        config.reset_runtime_profile(profile_token)


def _cors_origins() -> list[str]:
    defaults = ["http://localhost:5173", "http://127.0.0.1:5173"]
    configured = os.environ.get("LWS_CORS_ORIGINS", "")
    extra = [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [*defaults, *[origin for origin in extra if origin not in defaults]]


def _app_version() -> str:
    try:
        return (Path(__file__).resolve().parents[2] / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


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
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/me"),
    # check.py delegates to deployment_check.py, whose pre-login reads are
    # limited to version and health. Its upload-readability probe writes files
    # to disk, so it must NOT be exempted here (unauthenticated disk-fill
    # surface); when auth is required, deployment_check logs in first.
    ("GET", "/api/version"),
    ("GET", "/api/health"),
}

# While a forced first-login password change is pending, a logged-in user may
# only look at their own identity, log out, or change the password itself --
# every other /api/* route is blocked with a 403 (not 401: the session is
# valid, it just isn't allowed to do business yet) until the change succeeds.
_FORCE_PASSWORD_CHANGE_ALLOWED_ENDPOINTS = {
    ("GET", "/api/auth/me"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/change-password"),
}


async def _enforce_authentication(request: Request, call_next):
    runtime_profile = request.app.state.runtime_profile
    request.state.runtime_profile = runtime_profile
    profile_token = config.bind_runtime_profile(runtime_profile)
    try:
        return await _enforce_authentication_with_profile(
            request,
            call_next,
            runtime_profile,
        )
    finally:
        config.reset_runtime_profile(profile_token)


async def _enforce_authentication_with_profile(
    request: Request,
    call_next,
    runtime_profile: config.RuntimeProfile,
):
    path = request.url.path
    operator_header = request.headers.get("x-operator")

    if not runtime_profile.auth_required:
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
        if user.get("must_change_password") and (request.method.upper(), path) not in _FORCE_PASSWORD_CHANGE_ALLOWED_ENDPOINTS:
            return JSONResponse(
                status_code=403,
                content={"detail": "首次登录请先修改密码"},
                headers={"Cache-Control": "no-store"},
            )
        return await call_next(request)

    operator_context.set_current_operator(operator_header)
    if (request.method.upper(), path) in _PRELOGIN_API_ENDPOINTS:
        return await call_next(request)
    return JSONResponse(
        status_code=401,
        content={"detail": "未登录"},
        headers={"Cache-Control": "no-store"},
    )


async def _capture_operator_header(request: Request, call_next):
    """Make the optional ``X-Operator`` nickname available to this request's
    handler (sync or async) via operator_context.current_operator(), without
    threading it through every function signature. See operator_context.py
    for why this is safe across FastAPI's sync-endpoint threadpool.
    """
    operator_context.set_current_operator(request.headers.get("x-operator"))
    return await call_next(request)


async def _handle_user_facing_error(request: Request, exc: UserFacingError) -> JSONResponse:
    """Safety net: a UserFacingError escaping any route becomes a sanitized JSON error.

    Response shape matches HTTPException ({"detail": ...}) so frontend apiErrorText keeps working.
    """
    _ = request
    return JSONResponse(
        status_code=http_status_for_user_facing_error(exc),
        content={"detail": user_facing_error(exc)},
    )


async def _handle_project_not_active(request: Request, exc: db.ProjectNotActiveError) -> JSONResponse:
    _ = request
    missing = exc.state == "missing"
    return JSONResponse(
        status_code=404 if missing else 409,
        content={"detail": "项目不存在" if missing else "项目正在删除，请稍后重试"},
    )


def create_app(
    runtime_profile: config.RuntimeProfile | None = None,
) -> FastAPI:
    profile = runtime_profile or config.STARTUP_RUNTIME_PROFILE
    application = FastAPI(
        title="Localization Workflow Studio",
        version=_app_version(),
        lifespan=lifespan,
    )
    application.state.runtime_profile = profile
    application.state.bootstrap_admin_username = os.environ.get(
        "LWS_ADMIN_USER",
        "",
    ).strip()
    application.state.bootstrap_admin_password = os.environ.get(
        "LWS_ADMIN_PASSWORD",
        "",
    )
    # A single, centrally-reviewable dependency guards every /api/ route's
    # capability + project-membership requirement -- see route_capabilities.py
    # for the (method, path) -> capability table and docs/ROUTE_CAPABILITIES.md
    # for the per-route rationale. assert_full_route_coverage() fails the app at
    # construction time (not just "on first request") if any /api/ route is not
    # explicitly registered there, so a forgotten new route can't default to
    # "allowed".
    application.include_router(
        api_router,
        dependencies=[Depends(route_capabilities.enforce_route_access)],
    )
    route_capabilities.assert_full_route_coverage(application)
    application.middleware("http")(_no_store_api_responses)
    application.middleware("http")(_enforce_authentication)
    application.middleware("http")(_capture_operator_header)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_exception_handler(UserFacingError, _handle_user_facing_error)
    application.add_exception_handler(
        db.ProjectNotActiveError,
        _handle_project_not_active,
    )
    return application


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False, app_dir=str(Path(__file__).resolve().parents[1]))
