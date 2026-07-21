from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


_ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"
_INDEX_CACHE_CONTROL = "no-cache"


def frontend_serving_enabled(env: Mapping[str, str]) -> bool:
    """Return whether backend SPA serving is explicitly enabled."""
    value = env.get("LWS_SERVE_FRONTEND")
    if value is None or value == "0":
        return False
    if value == "1":
        return True
    raise RuntimeError("LWS_SERVE_FRONTEND must be absent, '0', or '1'")


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _safe_asset_path(
    assets_root: Path,
    dist_root: Path,
    asset_path: str,
) -> Path | None:
    if not _is_within(assets_root, dist_root):
        return None
    normalized = asset_path.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    candidate = assets_root.joinpath(*parts).resolve(strict=False)
    if not _is_within(candidate, assets_root) or not _is_within(
        candidate,
        dist_root,
    ):
        return None
    return candidate if candidate.is_file() else None


def _is_traversal(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(part == ".." for part in PurePosixPath(normalized).parts)


def install_frontend_routes(
    app: FastAPI,
    *,
    dist_root: Path,
    enabled: bool,
) -> None:
    """Install immutable assets and a no-cache SPA fallback when enabled."""
    if not enabled:
        return

    resolved_dist_root = dist_root.resolve(strict=False)
    unresolved_index_path = resolved_dist_root / "index.html"
    if not unresolved_index_path.is_file():
        raise RuntimeError("LWS_SERVE_FRONTEND=1 requires frontend/dist/index.html")
    index_path = unresolved_index_path.resolve(strict=True)
    if not _is_within(index_path, resolved_dist_root):
        raise RuntimeError("frontend/dist/index.html resolves outside frontend/dist")
    assets_root = (resolved_dist_root / "assets").resolve(strict=False)

    @app.get("/assets/{asset_path:path}", include_in_schema=False)
    def frontend_asset(asset_path: str):
        candidate = _safe_asset_path(assets_root, resolved_dist_root, asset_path)
        if candidate is None:
            return _not_found()
        return FileResponse(
            candidate,
            headers={"Cache-Control": _ASSET_CACHE_CONTROL},
        )

    def index_response() -> FileResponse:
        return FileResponse(
            index_path,
            media_type="text/html",
            headers={"Cache-Control": _INDEX_CACHE_CONTROL},
        )

    @app.get("/index.html", include_in_schema=False)
    @app.get("/", include_in_schema=False)
    def frontend_root():
        return index_response()

    @app.exception_handler(StarletteHTTPException)
    async def frontend_fallback(
        request: Request,
        exc: StarletteHTTPException,
    ):
        path = request.url.path.lstrip("/")
        if (
            exc.status_code == 404
            and request.method in {"GET", "HEAD"}
            and path != "api"
            and not path.startswith("api/")
            and path != "assets"
            and not path.startswith("assets/")
            and not _is_traversal(path)
        ):
            return index_response()
        return await http_exception_handler(request, exc)  # type: ignore[arg-type]
