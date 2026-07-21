from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _frontend_static() -> ModuleType:
    spec = importlib.util.find_spec("app.frontend_static")
    assert spec is not None, "app.frontend_static must provide opt-in SPA serving"
    return importlib.import_module("app.frontend_static")


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, False),
        ({"LWS_SERVE_FRONTEND": "0"}, False),
        ({"LWS_SERVE_FRONTEND": "1"}, True),
    ],
)
def test_frontend_serving_enabled_accepts_only_absent_zero_or_one(
    env: dict[str, str],
    expected: bool,
) -> None:
    module = _frontend_static()

    assert module.frontend_serving_enabled(env) is expected


@pytest.mark.parametrize("value", ["", "true", "yes", "2", " 1 "])
def test_frontend_serving_enabled_rejects_other_explicit_values(value: str) -> None:
    module = _frontend_static()

    with pytest.raises(RuntimeError, match="LWS_SERVE_FRONTEND"):
        module.frontend_serving_enabled({"LWS_SERVE_FRONTEND": value})


def _built_frontend(tmp_path: Path) -> tuple[Path, bytes, bytes]:
    dist_root = tmp_path / "frontend" / "dist"
    assets_root = dist_root / "assets"
    assets_root.mkdir(parents=True)
    index = b'<!doctype html><div id="root">built-spa</div>'
    asset = b"console.log('built asset')"
    (dist_root / "index.html").write_bytes(index)
    (assets_root / "index-abc123.js").write_bytes(asset)
    return dist_root, index, asset


def test_enabled_frontend_serves_assets_and_spa_with_distinct_cache_policies(
    tmp_path: Path,
) -> None:
    module = _frontend_static()
    dist_root, index, asset = _built_frontend(tmp_path)
    app = FastAPI()

    @app.get("/api/known")
    def known_api() -> dict[str, bool]:
        return {"ok": True}

    module.install_frontend_routes(app, dist_root=dist_root, enabled=True)

    with TestClient(app) as client:
        asset_response = client.get("/assets/index-abc123.js")
        assert asset_response.status_code == 200
        assert asset_response.content == asset
        assert asset_response.headers["cache-control"] == "public, max-age=31536000, immutable"

        for path in ("/", "/index.html", "/projects/deep-link"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.content == index
            assert response.headers["cache-control"] == "no-cache"

        assert client.get("/api/known").json() == {"ok": True}
        missing_api = client.get("/api/does-not-exist")
        assert missing_api.status_code == 404
        assert missing_api.headers["content-type"].startswith("application/json")
        assert missing_api.json() == {"detail": "Not Found"}

        for method in ("POST", "PUT", "PATCH", "DELETE"):
            missing_api = client.request(method, "/api/does-not-exist")
            assert missing_api.status_code == 404
            assert missing_api.headers["content-type"].startswith("application/json")
            assert missing_api.json() == {"detail": "Not Found"}

        known_wrong_method = client.post("/api/known")
        assert known_wrong_method.status_code == 405
        assert known_wrong_method.json() == {"detail": "Method Not Allowed"}


def test_frontend_assets_reject_missing_files_and_traversal(tmp_path: Path) -> None:
    module = _frontend_static()
    dist_root, index, _ = _built_frontend(tmp_path)
    secret = dist_root.parent / "secret.txt"
    secret.write_text("outside-dist", encoding="utf-8")
    app = FastAPI()
    module.install_frontend_routes(app, dist_root=dist_root, enabled=True)

    with TestClient(app) as client:
        assert client.get("/assets/missing.js").status_code == 404
        for path in (
            "/assets/%2e%2e/%2e%2e/secret.txt",
            "/assets/%2e%2e%5c%2e%2e%5csecret.txt",
            "/%2e%2e/secret.txt",
        ):
            traversal = client.get(path)
            assert traversal.status_code == 404
            assert traversal.content != secret.read_bytes()
            assert traversal.content != index


def test_frontend_rejects_asset_symlink_that_escapes_dist(tmp_path: Path) -> None:
    module = _frontend_static()
    dist_root = tmp_path / "frontend" / "dist"
    dist_root.mkdir(parents=True)
    (dist_root / "index.html").write_text("built-spa", encoding="utf-8")
    outside_assets = tmp_path / "outside-assets"
    outside_assets.mkdir()
    (outside_assets / "secret.js").write_text("outside-dist", encoding="utf-8")
    try:
        (dist_root / "assets").symlink_to(outside_assets, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")
    app = FastAPI()
    module.install_frontend_routes(app, dist_root=dist_root, enabled=True)

    with TestClient(app) as client:
        response = client.get("/assets/secret.js")
        assert response.status_code == 404
        assert response.content != (outside_assets / "secret.js").read_bytes()


def test_frontend_rejects_index_symlink_that_escapes_dist(tmp_path: Path) -> None:
    module = _frontend_static()
    dist_root = tmp_path / "frontend" / "dist"
    dist_root.mkdir(parents=True)
    outside_index = tmp_path / "outside-index.html"
    outside_index.write_text("outside-dist", encoding="utf-8")
    try:
        (dist_root / "index.html").symlink_to(outside_index)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")

    with pytest.raises(RuntimeError, match="outside frontend/dist"):
        module.install_frontend_routes(
            FastAPI(),
            dist_root=dist_root,
            enabled=True,
        )


def test_disabled_frontend_installs_no_routes(tmp_path: Path) -> None:
    module = _frontend_static()
    app = FastAPI()
    route_count = len(app.routes)

    module.install_frontend_routes(app, dist_root=tmp_path / "missing", enabled=False)

    assert len(app.routes) == route_count
    with TestClient(app) as client:
        assert client.get("/").status_code == 404


def test_enabled_frontend_requires_built_index(tmp_path: Path) -> None:
    module = _frontend_static()

    with pytest.raises(RuntimeError, match="frontend/dist/index.html"):
        module.install_frontend_routes(
            FastAPI(),
            dist_root=tmp_path / "frontend" / "dist",
            enabled=True,
        )


def test_create_app_validates_frontend_flag_and_keeps_explicit_runtime_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import config, main

    profile = config.RuntimeProfile(deployment_mode="local", auth_mode="off")
    monkeypatch.setenv("LWS_SERVE_FRONTEND", "invalid")
    with pytest.raises(RuntimeError, match="LWS_SERVE_FRONTEND"):
        main.create_app(profile)

    monkeypatch.setenv("LWS_SERVE_FRONTEND", "0")
    application = main.create_app(profile)
    assert application.state.runtime_profile is profile
