from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app import db
    from app.workflow import reconcile_interrupted_background_jobs
    from app.routers.api import router as api_router
else:
    from . import db
    from .workflow import reconcile_interrupted_background_jobs
    from .routers.api import router as api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ = app
    db.init_db()
    reconcile_interrupted_background_jobs()
    yield


def _cors_origins() -> list[str]:
    defaults = ["http://localhost:5173", "http://127.0.0.1:5173"]
    configured = os.environ.get("LWS_CORS_ORIGINS", "")
    extra = [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [*defaults, *[origin for origin in extra if origin not in defaults]]


app = FastAPI(title="Localization Workflow Studio", version="1.0.3", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False, app_dir=str(Path(__file__).resolve().parents[1]))
