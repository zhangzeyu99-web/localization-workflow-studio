from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_deployment_check() -> ModuleType:
    script_path = (_REPO_ROOT / "scripts" / "deployment_check.py").resolve()
    spec = importlib.util.spec_from_file_location("deployment_check_contract_test", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_client(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    *,
    html: str,
    html_cache_control: str,
    api_cache_control: str,
    git_sha: str = "abc123",
    reported_assets: list[str] | None = None,
    asset_status: int = 200,
    asset_cache_control: str = "public, max-age=31536000, immutable",
    asset_statuses: dict[str, int] | None = None,
    asset_cache_controls: dict[str, str] | None = None,
    requested_assets: list[str] | None = None,
) -> None:
    real_client = httpx.Client
    if reported_assets is None:
        reported_assets = ["index-built.js"]
    asset_statuses = asset_statuses or {}
    asset_cache_controls = asset_cache_controls or {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200,
                text=html,
                headers={"Cache-Control": html_cache_control, "Content-Type": "text/html"},
            )
        if request.url.path == "/api/version":
            return httpx.Response(
                200,
                json={"version": "1.3.1", "git_sha": git_sha, "frontend_assets": reported_assets},
                headers={"Cache-Control": api_cache_control},
            )
        if request.url.path == "/api/health":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "deployment_mode": "cloud",
                    "storage": {"data_root_writable": True, "uploads_writable": True},
                    "database": {"connected": True},
                    "provider": {"provider_configured": True},
                },
                headers={"Cache-Control": api_cache_control},
            )
        if request.url.path == "/api/diagnostics/upload-readability":
            return httpx.Response(
                200,
                json={"ok": True, "readable": True, "sha256": "probe-sha", "filename": "probe.txt", "size": 1},
                headers={"Cache-Control": "no-store"},
            )
        if request.url.path.startswith("/assets/"):
            if requested_assets is not None:
                requested_assets.append(request.url.path)
            return httpx.Response(
                asset_statuses.get(request.url.path, asset_status),
                content=b"built asset",
                headers={"Cache-Control": asset_cache_controls.get(request.url.path, asset_cache_control)},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    def client_factory(*args: Any, **kwargs: Any) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(handler), follow_redirects=True)

    monkeypatch.setattr(module.httpx, "Client", client_factory)


def _printed_steps(capsys: pytest.CaptureFixture[str]) -> dict[str, dict[str, Any]]:
    return {item["step"]: item for item in (json.loads(line) for line in capsys.readouterr().out.splitlines())}


def _local_assets(tmp_path: Path, *names: str) -> Path:
    assets_dir = tmp_path / "dist-assets"
    assets_dir.mkdir()
    for name in names:
        (assets_dir / name).write_text("built asset", encoding="utf-8")
    return assets_dir


def test_local_frontend_assets_does_not_truncate_full_build(tmp_path: Path) -> None:
    module = _load_deployment_check()
    assets_dir = _local_assets(tmp_path, *(f"chunk-{index:02d}.js" for index in range(25)))

    assert module.local_frontend_assets(assets_dir) == [f"chunk-{index:02d}.js" for index in range(25)]


def test_version_frontend_assets_does_not_truncate_complete_build(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.routers import system

    assets_dir = tmp_path / "frontend" / "dist" / "assets"
    assets_dir.mkdir(parents=True)
    expected = [f"chunk-{index:02d}.js" for index in range(25)]
    for name in expected:
        (assets_dir / name).write_text("built asset", encoding="utf-8")
    monkeypatch.setattr(system, "APP_ROOT", tmp_path)

    assert system.version()["frontend_assets"] == expected


def test_run_rejects_vite_dev_html_and_cacheable_public_responses(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_deployment_check()
    _install_client(
        monkeypatch,
        module,
        html=(
            '<script type="module" src="/@vite/client"></script>'
            '<script src="/@react-refresh"></script>'
            '<script src="/assets/index-built.js"></script>'
        ),
        html_cache_control="public, max-age=86400",
        api_cache_control="max-age=86400",
    )

    result = module.run(
        "https://studio.example.test",
        expect_version="1.3.1",
        frontend_assets_dir=_local_assets(tmp_path, "index-built.js"),
    )

    assert result == 1
    steps = _printed_steps(capsys)
    assert steps["frontend"]["ok"] is False
    assert "Vite development page" in steps["frontend"]["result"]["error"]
    assert "Cache-Control must include no-cache or no-store" in steps["frontend"]["result"]["error"]
    assert steps["version"]["ok"] is False
    assert "/api/version Cache-Control must include no-store" in steps["version"]["result"]["error"]
    assert steps["health"]["ok"] is False
    assert "/api/health Cache-Control must include no-store" in steps["health"]["result"]["error"]


def test_run_rejects_git_sha_mismatch_only_when_expected(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_deployment_check()
    _install_client(
        monkeypatch,
        module,
        html='<!doctype html><div id="root"></div><script src="/assets/index-built.js"></script>',
        html_cache_control="no-cache, must-revalidate",
        api_cache_control="no-store",
        git_sha="deployed-sha",
    )

    result = module.run(
        "https://studio.example.test",
        expect_version="1.3.1",
        expect_git_sha="expected-sha",
        frontend_assets_dir=_local_assets(tmp_path, "index-built.js"),
    )

    assert result == 1
    version_step = _printed_steps(capsys)["version"]
    assert version_step["ok"] is False
    assert "deployed git_sha deployed-sha does not match expected expected-sha" in version_step["result"]["error"]


@pytest.mark.parametrize("expect_git_sha", [None, "deployed-sha"])
def test_run_accepts_production_cache_contract_and_optional_matching_git_sha(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    expect_git_sha: str | None,
) -> None:
    module = _load_deployment_check()
    _install_client(
        monkeypatch,
        module,
        html=(
            '<!doctype html><link href="/assets/index-built.css" rel="stylesheet">'
            '<div id="root"></div><script src="/assets/index-built.js"></script>'
        ),
        html_cache_control="no-cache, must-revalidate",
        api_cache_control="private, no-store",
        git_sha="deployed-sha",
        reported_assets=["index-built.css", "index-built.js"],
    )

    result = module.run(
        "https://studio.example.test",
        expect_version="1.3.1",
        expect_git_sha=expect_git_sha,
        frontend_assets_dir=_local_assets(tmp_path, "index-built.css", "index-built.js"),
    )

    assert result == 0
    steps = _printed_steps(capsys)
    assert steps["frontend"]["ok"] is True
    assert steps["version"]["ok"] is True
    assert steps["health"]["ok"] is True


def test_run_rejects_public_html_asset_not_reported_by_version(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_deployment_check()
    _install_client(
        monkeypatch,
        module,
        html='<script src="/assets/index-stale.js"></script>',
        html_cache_control="no-cache",
        api_cache_control="no-store",
        reported_assets=["index-built.js"],
    )

    result = module.run(
        "https://studio.example.test",
        expect_version="1.3.1",
        frontend_assets_dir=_local_assets(tmp_path, "index-built.js"),
    )

    assert result == 1
    public_assets = _printed_steps(capsys)["public_assets"]
    assert public_assets["ok"] is False
    assert public_assets["result"]["missing_from_version"] == ["index-stale.js"]
    assert "public HTML assets are absent from /api/version frontend_assets" in public_assets["result"]["error"]


def test_run_rejects_production_html_without_asset_reference(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_deployment_check()
    _install_client(
        monkeypatch,
        module,
        html='<!doctype html><div id="root"></div>',
        html_cache_control="no-cache",
        api_cache_control="no-store",
    )

    result = module.run(
        "https://studio.example.test",
        expect_version="1.3.1",
        frontend_assets_dir=_local_assets(tmp_path, "index-built.js"),
    )

    assert result == 1
    steps = _printed_steps(capsys)
    assert steps["frontend"]["ok"] is False
    assert "does not reference any /assets/*" in steps["frontend"]["result"]["error"]
    assert steps["public_assets"]["ok"] is False


def test_run_defaults_to_local_frontend_build_and_rejects_missing_directory(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_deployment_check()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    _install_client(
        monkeypatch,
        module,
        html='<script src="/assets/index-built.js"></script>',
        html_cache_control="no-store",
        api_cache_control="no-store",
    )

    result = module.run("https://studio.example.test", expect_version="1.3.1")

    assert result == 1
    frontend_assets = _printed_steps(capsys)["frontend_assets"]
    assert frontend_assets["ok"] is False
    assert str(tmp_path / "frontend" / "dist" / "assets") in frontend_assets["result"]["assets_dir"]
    assert "local frontend/dist/assets is empty or missing" in frontend_assets["result"]["error"]


@pytest.mark.parametrize(
    ("asset_status", "asset_cache_control", "expected_error"),
    [
        (404, "public, immutable", "returned HTTP 404"),
        (200, "public, max-age=31536000", "Cache-Control must include immutable"),
    ],
)
def test_run_rejects_unavailable_or_nonimmutable_public_asset(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    asset_status: int,
    asset_cache_control: str,
    expected_error: str,
) -> None:
    module = _load_deployment_check()
    _install_client(
        monkeypatch,
        module,
        html='<script src="/assets/index-built.js"></script>',
        html_cache_control="no-cache",
        api_cache_control="no-store",
        asset_status=asset_status,
        asset_cache_control=asset_cache_control,
    )

    result = module.run(
        "https://studio.example.test",
        expect_version="1.3.1",
        frontend_assets_dir=_local_assets(tmp_path, "index-built.js"),
    )

    assert result == 1
    public_assets = _printed_steps(capsys)["public_assets"]
    assert public_assets["ok"] is False
    assert expected_error in public_assets["result"]["error"]


@pytest.mark.parametrize(
    ("lazy_status", "lazy_cache_control", "expected_error"),
    [
        (404, "public, immutable", "returned HTTP 404"),
        (200, "public, max-age=31536000", "Cache-Control must include immutable"),
    ],
)
def test_run_checks_lazy_chunk_not_directly_referenced_by_html(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    lazy_status: int,
    lazy_cache_control: str,
    expected_error: str,
) -> None:
    module = _load_deployment_check()
    _install_client(
        monkeypatch,
        module,
        html='<script src="/assets/index-built.js"></script>',
        html_cache_control="no-cache",
        api_cache_control="no-store",
        reported_assets=["index-built.js", "lazy-chunk.js"],
        asset_statuses={"/assets/lazy-chunk.js": lazy_status},
        asset_cache_controls={"/assets/lazy-chunk.js": lazy_cache_control},
    )

    result = module.run(
        "https://studio.example.test",
        expect_version="1.3.1",
        frontend_assets_dir=_local_assets(tmp_path, "index-built.js", "lazy-chunk.js"),
    )

    assert result == 1
    public_assets = _printed_steps(capsys)["public_assets"]
    assert public_assets["ok"] is False
    lazy_check = next(item for item in public_assets["result"]["checks"] if item["path"] == "/assets/lazy-chunk.js")
    assert expected_error in lazy_check["error"]


def test_run_gets_every_asset_in_complete_25_file_manifest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_deployment_check()
    names = [f"chunk-{index:02d}.js" for index in range(25)]
    requested_assets: list[str] = []
    _install_client(
        monkeypatch,
        module,
        html='<script src="/assets/chunk-00.js"></script>',
        html_cache_control="no-cache",
        api_cache_control="no-store",
        reported_assets=names,
        requested_assets=requested_assets,
    )

    result = module.run(
        "https://studio.example.test",
        expect_version="1.3.1",
        frontend_assets_dir=_local_assets(tmp_path, *names),
    )

    assert result == 0
    assert requested_assets == [f"/assets/{name}" for name in names]
    assert len(_printed_steps(capsys)["public_assets"]["result"]["checks"]) == 25
