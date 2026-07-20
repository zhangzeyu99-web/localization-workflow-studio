"""Centralized capability + project-membership gate for every ``/api/`` route.

A2 batch 1+2. Design rationale (see docs/superpowers/plans/2026-07-15-account
-permission-system.md §2.1/§2.4 and docs/ROUTE_CAPABILITIES.md for the full
per-route table): rather than sprinkling ``Depends(require_capability(...))``
across nine router files, every route's required capability is registered
once in ``CAPABILITY_BY_ROUTE`` below. A single dependency
(``enforce_route_access``) is attached to the whole ``api_router`` in
``main.py`` and looks the current request's ``(method, path template)`` up in
that table at request time. This keeps the review surface to one file and
lets ``assert_full_route_coverage`` fail the app at startup if any route --
present today or added tomorrow -- is missing from the table.

Path template resolution: FastAPI's ``APIRoute.matches`` sets
``request.scope["route"]`` to the matched ``APIRoute`` object before any
dependency runs, and ``APIRoute.path`` is the exact template string
(``"/api/projects/{project_id}"``) that also appears in ``app.openapi()``'s
paths -- so the same strings drive both the runtime gate and the startup
assertion.

Project-membership resolution: most routes carry ``project_id`` directly in
the path. A handful of sub-resource routes only carry ``run_id``,
``task_id`` (announcement tasks), or a bare ``artifact_id`` -- for those,
``resolve_project_id`` looks the owning project up through the corresponding
``db.get_*`` accessor. If the referenced resource does not exist, resolution
is skipped (returns ``None``) and the route handler's own ``KeyError`` -> 404
mapping is left to answer -- this preserves "404 either way" without this
gate needing to duplicate every handler's not-found logic.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from . import auth, db
from .authz import ADMIN, ASSETS_CURATE, PROJECT_MANAGE, PROJECT_READ, TASK_RUN, capability_allowed

RouteKey = tuple[str, str]

# ---------------------------------------------------------------------------
# Exempt routes: no capability required. Either the endpoint is part of the
# authentication bootstrap itself (must work before any capability exists),
# is an unauthenticated health/version probe, or is already guarded by its
# own ``require_admin`` router-level dependency (the /api/users* family).
# ---------------------------------------------------------------------------
EXEMPT_ROUTES: dict[RouteKey, str] = {
    ("POST", "/api/auth/login"): "登录入口本身；调用者此时必然没有 session",
    ("POST", "/api/auth/register"): "公开自助注册入口；路由自身限制为仅认证开启模式可用",
    ("POST", "/api/auth/logout"): "任何已登录身份都能登出自己，不需要业务能力",
    ("GET", "/api/auth/me"): "前端探测登录态本身，不含业务数据",
    ("POST", "/api/auth/change-password"): "首登强制改密必须在拿到任何能力之前可用",
    ("GET", "/api/version"): "只读系统版本信息，未登录也可探活，见 main.py _PRELOGIN_API_ENDPOINTS",
    ("GET", "/api/health"): "只读健康检查，部署探活需要，未登录也可访问",
    ("GET", "/api/users"): "已由 users.router 的 Depends(require_admin) 保护",
    ("POST", "/api/users"): "已由 users.router 的 Depends(require_admin) 保护",
    ("PATCH", "/api/users/{user_id}"): "已由 users.router 的 Depends(require_admin) 保护",
    ("POST", "/api/users/{user_id}/reset-password"): "已由 users.router 的 Depends(require_admin) 保护",
}

# ---------------------------------------------------------------------------
# Every other /api/ route's required capability. See docs/ROUTE_CAPABILITIES.md
# for the one-line rationale behind each entry.
# ---------------------------------------------------------------------------
CAPABILITY_BY_ROUTE: dict[RouteKey, str] = {
    # -- announcement tasks (public-text workflow; matrix row: all 3 roles) --
    ("GET", "/api/announcement-tasks/{task_id}"): PROJECT_READ,
    ("GET", "/api/announcement-tasks/{task_id}/ai-input-summary"): PROJECT_READ,
    ("POST", "/api/announcement-tasks/{task_id}/apply"): TASK_RUN,
    ("POST", "/api/announcement-tasks/{task_id}/cancel"): TASK_RUN,
    ("POST", "/api/announcement-tasks/{task_id}/deliver"): TASK_RUN,
    ("POST", "/api/announcement-tasks/{task_id}/extract-terms"): TASK_RUN,
    ("POST", "/api/announcement-tasks/{task_id}/fix-hard-blockers"): TASK_RUN,
    ("POST", "/api/announcement-tasks/{task_id}/import-ai"): TASK_RUN,
    ("POST", "/api/announcement-tasks/{task_id}/import-terms"): TASK_RUN,
    ("POST", "/api/announcement-tasks/{task_id}/inspect-constraints"): TASK_RUN,
    ("POST", "/api/announcement-tasks/{task_id}/lookup-translations"): TASK_RUN,
    ("POST", "/api/announcement-tasks/{task_id}/prepare"): TASK_RUN,
    ("POST", "/api/announcement-tasks/{task_id}/translate"): TASK_RUN,
    ("POST", "/api/announcement-tasks/{task_id}/translate/cancel"): TASK_RUN,
    ("POST", "/api/announcement-tasks/{task_id}/translate/resume"): TASK_RUN,
    ("POST", "/api/announcement-tasks/{task_id}/translate/start"): TASK_RUN,
    # -- artifacts (bare artifact_id; project resolved via db.get_artifact) --
    ("PATCH", "/api/artifacts/{artifact_id}"): ASSETS_CURATE,
    ("GET", "/api/artifacts/{artifact_id}/download"): PROJECT_READ,
    ("GET", "/api/artifacts/{artifact_id}/translation-readiness"): PROJECT_READ,
    ("GET", "/api/artifacts/{artifact_id}/translation-targets"): PROJECT_READ,
    # -- system / diagnostics --
    ("POST", "/api/diagnostics/upload-readability"): ADMIN,
    ("GET", "/api/import-templates/{kind}"): PROJECT_READ,
    ("GET", "/api/languages"): PROJECT_READ,
    ("GET", "/api/settings"): PROJECT_READ,
    ("PATCH", "/api/settings"): ADMIN,
    ("GET", "/api/system/active-jobs"): PROJECT_READ,
    ("GET", "/api/system/job-queues"): PROJECT_READ,
    ("POST", "/api/system/job-queues/{job_id}/cancel"): TASK_RUN,
    # -- projects --
    ("GET", "/api/projects"): PROJECT_READ,
    ("POST", "/api/projects"): PROJECT_READ,
    ("GET", "/api/projects/{project_id}"): PROJECT_READ,
    ("PATCH", "/api/projects/{project_id}"): ASSETS_CURATE,
    ("DELETE", "/api/projects/{project_id}"): PROJECT_MANAGE,
    ("GET", "/api/projects/{project_id}/ai-input-summary"): PROJECT_READ,
    ("POST", "/api/projects/{project_id}/analyze"): ASSETS_CURATE,
    ("GET", "/api/projects/{project_id}/harness"): PROJECT_READ,
    ("PATCH", "/api/projects/{project_id}/harness"): ASSETS_CURATE,
    ("GET", "/api/projects/{project_id}/assets"): PROJECT_READ,
    ("POST", "/api/projects/{project_id}/files"): TASK_RUN,
    ("POST", "/api/projects/{project_id}/files/chunk"): TASK_RUN,
    ("GET", "/api/projects/{project_id}/artifacts/{artifact_id}/download"): PROJECT_READ,
    ("GET", "/api/projects/{project_id}/artifacts/{artifact_id}/translation-readiness"): PROJECT_READ,
    ("GET", "/api/projects/{project_id}/artifacts/{artifact_id}/translation-targets"): PROJECT_READ,
    ("GET", "/api/projects/{project_id}/improvements"): PROJECT_READ,
    ("POST", "/api/projects/{project_id}/improvements"): ASSETS_CURATE,
    # -- project members (new in this batch) --
    ("GET", "/api/projects/{project_id}/members"): PROJECT_READ,
    ("GET", "/api/projects/{project_id}/members/addable"): PROJECT_MANAGE,
    ("POST", "/api/projects/{project_id}/members"): PROJECT_MANAGE,
    ("DELETE", "/api/projects/{project_id}/members/{user_id}"): PROJECT_MANAGE,
    # -- announcement (legacy docx entry points are deprecated=True but still live) --
    ("POST", "/api/projects/{project_id}/announcement-docx/apply"): TASK_RUN,
    ("POST", "/api/projects/{project_id}/announcement-docx/deliver"): TASK_RUN,
    ("POST", "/api/projects/{project_id}/announcement-docx/import-ai"): TASK_RUN,
    ("POST", "/api/projects/{project_id}/announcement-docx/prepare"): TASK_RUN,
    ("POST", "/api/projects/{project_id}/announcement-lookup"): TASK_RUN,
    ("GET", "/api/projects/{project_id}/announcement-tasks"): PROJECT_READ,
    ("POST", "/api/projects/{project_id}/announcement-tasks"): TASK_RUN,
    ("POST", "/api/projects/{project_id}/announcement-terms"): TASK_RUN,
    # -- delivery --
    ("GET", "/api/projects/{project_id}/deliverables"): PROJECT_READ,
    ("POST", "/api/projects/{project_id}/delivery-package"): TASK_RUN,
    ("POST", "/api/projects/{project_id}/delivery-package/merged"): TASK_RUN,
    ("GET", "/api/projects/{project_id}/delivery/{filename}"): TASK_RUN,
    # -- glossary --
    ("GET", "/api/projects/{project_id}/glossary"): PROJECT_READ,
    ("POST", "/api/projects/{project_id}/glossary"): ASSETS_CURATE,
    ("GET", "/api/projects/{project_id}/glossary/wide"): PROJECT_READ,
    ("GET", "/api/projects/{project_id}/glossary/by-source-key"): PROJECT_READ,
    ("PATCH", "/api/projects/{project_id}/glossary/by-source-key"): ASSETS_CURATE,
    ("DELETE", "/api/projects/{project_id}/glossary/by-source-key"): ASSETS_CURATE,
    ("GET", "/api/projects/{project_id}/glossary/batches"): PROJECT_READ,
    ("PATCH", "/api/projects/{project_id}/glossary/candidates/{candidate_id}"): ASSETS_CURATE,
    ("POST", "/api/projects/{project_id}/glossary/batches/{batch_id}/accept"): ASSETS_CURATE,
    ("POST", "/api/projects/{project_id}/glossary/batches/{batch_id}/translate-missing"): ASSETS_CURATE,
    ("POST", "/api/projects/{project_id}/glossary/batches/{batch_id}/reject"): ASSETS_CURATE,
    ("PATCH", "/api/projects/{project_id}/glossary/{term_id}"): ASSETS_CURATE,
    ("DELETE", "/api/projects/{project_id}/glossary/{term_id}"): ASSETS_CURATE,
    ("POST", "/api/projects/{project_id}/glossary/import-preview"): ASSETS_CURATE,
    ("POST", "/api/projects/{project_id}/glossary/import"): ASSETS_CURATE,
    ("POST", "/api/projects/{project_id}/glossary/import/analyze"): ASSETS_CURATE,
    ("POST", "/api/projects/{project_id}/glossary/import/commit"): ASSETS_CURATE,
    ("GET", "/api/projects/{project_id}/glossary/import/batches"): PROJECT_READ,
    ("POST", "/api/projects/{project_id}/glossary/import/batches/{batch_id}/rollback"): ASSETS_CURATE,
    ("GET", "/api/projects/{project_id}/glossary/export"): PROJECT_READ,
    ("POST", "/api/projects/{project_id}/glossary/extract"): ASSETS_CURATE,
    # -- multilingual queueing --
    ("GET", "/api/projects/{project_id}/multilingual/status"): PROJECT_READ,
    ("POST", "/api/projects/{project_id}/multilingual/translate/start"): TASK_RUN,
    ("POST", "/api/projects/{project_id}/multilingual/qa/start"): TASK_RUN,
    # -- translations (archive) --
    ("GET", "/api/projects/{project_id}/translations"): PROJECT_READ,
    ("POST", "/api/projects/{project_id}/translations"): ASSETS_CURATE,
    ("GET", "/api/projects/{project_id}/translations/wide"): PROJECT_READ,
    ("GET", "/api/projects/{project_id}/translations/by-source-key"): PROJECT_READ,
    ("PATCH", "/api/projects/{project_id}/translations/by-source-key"): ASSETS_CURATE,
    ("DELETE", "/api/projects/{project_id}/translations/by-source-key"): ASSETS_CURATE,
    ("PATCH", "/api/projects/{project_id}/translations/{entry_id}"): ASSETS_CURATE,
    ("DELETE", "/api/projects/{project_id}/translations/{entry_id}"): ASSETS_CURATE,
    ("POST", "/api/projects/{project_id}/translations/import"): ASSETS_CURATE,
    ("POST", "/api/projects/{project_id}/translations/import/analyze"): ASSETS_CURATE,
    ("POST", "/api/projects/{project_id}/translations/import/commit"): ASSETS_CURATE,
    ("GET", "/api/projects/{project_id}/translations/import/batches"): PROJECT_READ,
    ("POST", "/api/projects/{project_id}/translations/import/batches/{batch_id}/rollback"): ASSETS_CURATE,
    ("GET", "/api/projects/{project_id}/translations/export"): PROJECT_READ,
    # -- runs --
    ("POST", "/api/runs"): TASK_RUN,
    ("GET", "/api/runs"): PROJECT_READ,
    ("POST", "/api/runs/{run_id}/abandon-translation-task"): TASK_RUN,
    ("GET", "/api/runs/{run_id}"): PROJECT_READ,
    ("GET", "/api/runs/{run_id}/ai-input-summary"): PROJECT_READ,
    ("GET", "/api/runs/{run_id}/events"): PROJECT_READ,
    ("POST", "/api/runs/{run_id}/improvement-review"): ASSETS_CURATE,
    ("POST", "/api/runs/{run_id}/manual-fixes"): TASK_RUN,
    ("POST", "/api/runs/{run_id}/manual-fixes/start"): TASK_RUN,
    ("POST", "/api/runs/{run_id}/model-fixes"): TASK_RUN,
    ("POST", "/api/runs/{run_id}/model-fixes/start"): TASK_RUN,
    ("POST", "/api/runs/{run_id}/qa"): TASK_RUN,
    ("POST", "/api/runs/{run_id}/qa/start"): TASK_RUN,
    ("POST", "/api/runs/{run_id}/qa/cancel"): TASK_RUN,
    ("GET", "/api/runs/{run_id}/quality-issues"): PROJECT_READ,
    ("POST", "/api/runs/{run_id}/semantic-qa"): TASK_RUN,
    ("POST", "/api/runs/{run_id}/translate"): TASK_RUN,
    ("POST", "/api/runs/{run_id}/translate/start"): TASK_RUN,
    ("POST", "/api/runs/{run_id}/translate/resume"): TASK_RUN,
    ("POST", "/api/runs/{run_id}/translate/cancel"): TASK_RUN,
    ("GET", "/api/runs/{run_id}/translate/progress"): PROJECT_READ,
    ("GET", "/api/runs/{run_id}/translate/batches/{batch_index}/{kind}"): PROJECT_READ,
    ("POST", "/api/projects/{project_id}/translation-tasks/{translation_task_id}/abandon"): TASK_RUN,
}


def _http_method_key(method: str) -> str:
    return "GET" if method.upper() == "HEAD" else method.upper()


def resolve_project_id(path_params: dict[str, Any]) -> str | None:
    """Best-effort project_id lookup for a matched route's path params.

    Returns ``None`` when the route isn't project-scoped at all, or when the
    referenced parent resource (run/task/artifact) doesn't exist -- in the
    latter case the route handler's own ``KeyError`` -> 404 mapping is the
    right answer, not a membership check on a resource that isn't there.
    """
    project_id = path_params.get("project_id")
    if project_id:
        return str(project_id)
    run_id = path_params.get("run_id")
    if run_id:
        try:
            return db.get_run(str(run_id))["project_id"]
        except KeyError:
            return None
    task_id = path_params.get("task_id")
    if task_id:
        try:
            return db.get_announcement_task(str(task_id))["project_id"]
        except KeyError:
            return None
    artifact_id = path_params.get("artifact_id")
    if artifact_id:
        try:
            return db.get_artifact(str(artifact_id))["project_id"]
        except KeyError:
            return None
    return None


def enforce_route_access(request: Request) -> None:
    """The single dependency attached to the whole ``api_router`` in
    ``main.py``. Runs for every ``/api/`` request after FastAPI has already
    matched a route (so ``request.scope["route"].path`` is the exact
    template registered in ``CAPABILITY_BY_ROUTE``/``EXEMPT_ROUTES``).
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if path is None:
        # Should be unreachable: this dependency only runs once a route has
        # matched. Fail closed rather than assume "allowed" if it ever is.
        raise HTTPException(status_code=403, detail="权限不足")
    key = (_http_method_key(request.method), path)
    if key in EXEMPT_ROUTES:
        return
    capability = CAPABILITY_BY_ROUTE.get(key)
    if capability is None:
        # The startup assertion (assert_full_route_coverage) guarantees this
        # cannot happen for the app actually served in production; treat it
        # as fail-closed rather than fail-open for any route that slips
        # through anyway (e.g. added to a live app object after startup).
        raise HTTPException(status_code=403, detail="权限不足")

    user = auth.current_user()
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    if not capability_allowed(user.get("role", ""), capability):
        raise HTTPException(status_code=403, detail="权限不足")
    if user.get("role") == "admin":
        return

    project_id = resolve_project_id(dict(request.path_params))
    if project_id is None:
        return
    if not db.is_project_member(project_id, user["id"]):
        raise HTTPException(status_code=404, detail="project not found")


def assert_full_route_coverage(app: Any) -> None:
    """Startup-time fail-closed assertion: every ``/api/`` route on ``app``
    must be registered in ``CAPABILITY_BY_ROUTE`` or ``EXEMPT_ROUTES``.

    Uses ``app.openapi()`` (rather than walking ``app.routes`` directly) so
    this does not depend on FastAPI/Starlette's internal route-tree
    representation -- the OpenAPI paths dict is a stable, public contract
    and uses the exact same path-template strings as
    ``request.scope["route"].path`` at request time.
    """
    schema = app.openapi()
    missing: list[str] = []
    for path, methods in schema.get("paths", {}).items():
        if not path.startswith("/api/"):
            continue
        for method in methods:
            method_upper = method.upper()
            if method_upper not in {"GET", "POST", "PATCH", "DELETE", "PUT"}:
                continue
            key = (method_upper, path)
            if key in EXEMPT_ROUTES or key in CAPABILITY_BY_ROUTE:
                continue
            missing.append(f"{method_upper} {path}")
    if missing:
        raise RuntimeError(
            "以下 /api/ 路由未在 route_capabilities.CAPABILITY_BY_ROUTE 或 "
            "EXEMPT_ROUTES 中登记能力，fail-closed 拒绝启动：\n" + "\n".join(sorted(missing))
        )
