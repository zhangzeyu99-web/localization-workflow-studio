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
    from app import background_jobs, db, job_queue, operator_context
    from app.errors import UserFacingError, http_status_for_user_facing_error
    from app.workflow import user_facing_error
    from app.routers.api import router as api_router
else:
    from . import background_jobs, db, job_queue, operator_context
    from .errors import UserFacingError, http_status_for_user_facing_error
    from .workflow import user_facing_error
    from .routers.api import router as api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ = app
    db.init_db()
    background_jobs.register_handlers()
    interrupted = job_queue.recover_interrupted_jobs()
    background_jobs.reconcile_startup(interrupted)
    job_queue.resume_dispatchers()
    try:
        yield
    finally:
        job_queue.shutdown_dispatchers(cancel_running=False)


def _cors_origins() -> list[str]:
    defaults = ["http://localhost:5173", "http://127.0.0.1:5173"]
    configured = os.environ.get("LWS_CORS_ORIGINS", "")
    extra = [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [*defaults, *[origin for origin in extra if origin not in defaults]]


app = FastAPI(title="Localization Workflow Studio", version="1.4.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
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


@app.middleware("http")
async def _capture_operator_header(request: Request, call_next):
    """Make the optional ``X-Operator`` nickname available to this request's
    handler (sync or async) via operator_context.current_operator(), without
    threading it through every function signature. See operator_context.py
    for why this is safe across FastAPI's sync-endpoint threadpool.
    """
    operator_context.set_current_operator(request.headers.get("x-operator"))
    return await call_next(request)


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
