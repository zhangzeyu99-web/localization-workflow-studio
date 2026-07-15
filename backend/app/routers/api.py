from __future__ import annotations

from fastapi import APIRouter

from . import announcement, artifacts, auth, delivery, glossary, projects, qa, runs, system, translations, users

router = APIRouter()
for _module in (system, auth, projects, glossary, translations, delivery, announcement, runs, qa, artifacts, users):
    router.include_router(_module.router)
