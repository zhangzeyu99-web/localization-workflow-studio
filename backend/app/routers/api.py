from __future__ import annotations

from fastapi import APIRouter

from . import announcement, artifacts, auth, delivery, glossary, projects, qa, runs, system, translations

router = APIRouter()
for _module in (system, auth, projects, glossary, translations, delivery, announcement, runs, qa, artifacts):
    router.include_router(_module.router)
