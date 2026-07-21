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
    deployment_mode: str = "local",
    auth_mode: str = "off",
    runtime_profile: str = "local-off",
    version_profile: dict[str, str] | None = None,
    health_profile: dict[str, str] | None = None,
    anonymous_projects_status: int = 200,
    version_json: Any | None = None,
    health_json: Any | None = None,
) -> None:
    real_client = httpx.Client
    if reported_assets is None:
        reported_assets = ["index-built.js"]
    asset_statuses = asset_statuses or {}
    asset_cache_controls = asset_cache_controls or {}
    base_profile = {
        "deployment_mode": deployment_mode,
        "auth_mode": auth_mode,
        "runtime_profile": runtime_profile,
    }
    version_fields = {**base_profile, **(version_profile or {})}
    health_fields = {**base_profile, **(health_profile or {})}

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
                json=(
                    version_json
                    if version_json is not None
                    else {
                        "version": "1.3.1",
                        "git_sha": git_sha,
                        "frontend_assets": reported_assets,
                        **version_fields,
                    }
                ),
                headers={"Cache-Control": api_cache_control},
            )
        if request.url.path == "/api/health":
            return httpx.Response(
                200,
                json=(
                    health_json
                    if health_json is not None
                    else {
                        "ok": True,
                        **health_fields,
                        "storage": {
                            "data_root_writable": True,
                            "uploads_writable": True,
                        },
                        "database": {"connected": True},
                        "provider": {"provider_configured": True},
                    }
                ),
                headers={"Cache-Control": api_cache_control},
            )
        if request.url.path == "/api/projects":
            return httpx.Response(
                anonymous_projects_status,
                json=[] if anonymous_projects_status == 200 else {"detail": "Not authenticated"},
                headers={"Cache-Control": "no-store"},
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


def test_run_combines_git_asset_and_authenticated_cloud_checks(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_deployment_check()
    _install_client(
        monkeypatch,
        module,
        html='<script src="/assets/index-built.js"></script>',
        html_cache_control="no-cache",
        api_cache_control="no-store",
        git_sha="release-sha",
        deployment_mode="cloud",
        auth_mode="required",
        runtime_profile="cloud-required",
        anonymous_projects_status=401,
    )
    login_args: list[tuple[str, str]] = []

    def fake_login(client: httpx.Client, base_url: str, username: str, password: str) -> dict[str, str]:
        _ = client, base_url
        login_args.append((username, password))
        return {"username": username, "role": "admin"}

    monkeypatch.setattr(module, "login", fake_login)
    monkeypatch.setattr(module, "unauthenticated_probe_status", lambda *args, **kwargs: 401)

    result = module.run(
        "https://studio.example.test",
        require_cloud=True,
        expect_deployment_mode="cloud",
        expect_auth_mode="required",
        expect_runtime_profile="cloud-required",
        expect_version="1.3.1",
        expect_git_sha="release-sha",
        frontend_assets_dir=_local_assets(tmp_path, "index-built.js"),
        auth_user="release-admin",
        auth_password="release-password",
    )

    assert result == 0
    assert login_args == [("release-admin", "release-password")]
    steps = _printed_steps(capsys)
    assert steps["version"]["ok"] is True
    assert steps["public_assets"]["ok"] is True
    assert steps["frontend_assets"]["ok"] is True
    assert steps["anonymous_projects"]["ok"] is True
    assert steps["auth_login"]["ok"] is True
    assert steps["upload_readability"]["ok"] is True


def test_run_accepts_local_off_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_deployment_check()
    _install_client(
        monkeypatch,
        module,
        html='<script src="/assets/index-built.js"></script>',
        html_cache_control="no-cache",
        api_cache_control="no-store",
        deployment_mode="local",
        auth_mode="off",
        runtime_profile="local-off",
        anonymous_projects_status=200,
    )

    result = module.run(
        "http://127.0.0.1:5173",
        expect_deployment_mode="local",
        expect_auth_mode="off",
        expect_runtime_profile="local-off",
        expect_version="1.3.1",
        frontend_assets_dir=_local_assets(tmp_path, "index-built.js"),
    )

    assert result == 0
    steps = _printed_steps(capsys)
    assert steps["runtime_profile"]["ok"] is True
    assert steps["anonymous_projects"]["ok"] is True
    assert steps["anonymous_projects"]["result"]["status_code"] == 200
    assert steps["auth_login"]["result"]["mode"] == "synthetic_local_admin"
    assert steps["upload_readability"]["ok"] is True


@pytest.mark.parametrize(
    ("expected_key", "expected_value", "error_fragment"),
    [
        ("expect_deployment_mode", "local", "deployment_mode"),
        ("expect_auth_mode", "off", "auth_mode"),
        ("expect_runtime_profile", "local-off", "runtime_profile"),
    ],
)
def test_run_rejects_each_runtime_profile_expectation_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    expected_key: str,
    expected_value: str,
    error_fragment: str,
) -> None:
    module = _load_deployment_check()
    _install_client(
        monkeypatch,
        module,
        html='<script src="/assets/index-built.js"></script>',
        html_cache_control="no-cache",
        api_cache_control="no-store",
        deployment_mode="cloud",
        auth_mode="required",
        runtime_profile="cloud-required",
        anonymous_projects_status=401,
    )
    kwargs = {expected_key: expected_value}

    result = module.run(
        "https://studio.example.test",
        expect_version="1.3.1",
        frontend_assets_dir=_local_assets(tmp_path, "index-built.js"),
        **kwargs,
    )

    assert result == 1
    profile_step = _printed_steps(capsys)["runtime_profile"]
    assert profile_step["ok"] is False
    assert error_fragment in profile_step["result"]["error"]


@pytest.mark.parametrize(
    ("field", "health_value"),
    [
        ("deployment_mode", "local"),
        ("auth_mode", "off"),
        ("runtime_profile", "local-off"),
    ],
)
def test_run_rejects_version_and_health_profile_disagreement(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    field: str,
    health_value: str,
) -> None:
    module = _load_deployment_check()
    _install_client(
        monkeypatch,
        module,
        html='<script src="/assets/index-built.js"></script>',
        html_cache_control="no-cache",
        api_cache_control="no-store",
        deployment_mode="cloud",
        auth_mode="required",
        runtime_profile="cloud-required",
        anonymous_projects_status=401,
        health_profile={field: health_value},
    )

    result = module.run(
        "https://studio.example.test",
        expect_version="1.3.1",
        frontend_assets_dir=_local_assets(tmp_path, "index-built.js"),
    )

    assert result == 1
    profile_step = _printed_steps(capsys)["runtime_profile"]
    assert profile_step["ok"] is False
    assert "/api/version and /api/health disagree" in profile_step["result"]["error"]


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [("version", []), ("health", "not-an-object")],
)
def test_run_reports_non_object_version_or_health_json_as_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    endpoint: str,
    payload: Any,
) -> None:
    module = _load_deployment_check()
    _install_client(
        monkeypatch,
        module,
        html='<script src="/assets/index-built.js"></script>',
        html_cache_control="no-cache",
        api_cache_control="no-store",
        version_json=payload if endpoint == "version" else None,
        health_json=payload if endpoint == "health" else None,
    )

    result = module.run(
        "https://studio.example.test",
        expect_version="1.3.1",
        frontend_assets_dir=_local_assets(tmp_path, "index-built.js"),
    )

    assert result == 1
    steps = _printed_steps(capsys)
    assert steps[endpoint]["ok"] is False
    assert "JSON object" in steps[endpoint]["result"]
    assert steps["runtime_profile"]["ok"] is False


@pytest.mark.parametrize(
    (
        "deployment_mode",
        "auth_mode",
        "runtime_profile",
        "anonymous_projects_status",
        "expected_status",
    ),
    [
        ("cloud", "required", "cloud-required", 200, 401),
        ("local", "off", "local-off", 401, 200),
    ],
)
def test_run_rejects_wrong_anonymous_projects_boundary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    deployment_mode: str,
    auth_mode: str,
    runtime_profile: str,
    anonymous_projects_status: int,
    expected_status: int,
) -> None:
    module = _load_deployment_check()
    _install_client(
        monkeypatch,
        module,
        html='<script src="/assets/index-built.js"></script>',
        html_cache_control="no-cache",
        api_cache_control="no-store",
        deployment_mode=deployment_mode,
        auth_mode=auth_mode,
        runtime_profile=runtime_profile,
        anonymous_projects_status=anonymous_projects_status,
    )

    result = module.run(
        "https://studio.example.test",
        expect_version="1.3.1",
        frontend_assets_dir=_local_assets(tmp_path, "index-built.js"),
    )

    assert result == 1
    anonymous = _printed_steps(capsys)["anonymous_projects"]
    assert anonymous["ok"] is False
    assert anonymous["result"]["expected_status"] == expected_status


def test_run_accepts_local_required_with_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_deployment_check()
    _install_client(
        monkeypatch,
        module,
        html='<script src="/assets/index-built.js"></script>',
        html_cache_control="no-cache",
        api_cache_control="no-store",
        deployment_mode="local",
        auth_mode="required",
        runtime_profile="local-required",
        anonymous_projects_status=401,
    )
    monkeypatch.setattr(
        module,
        "login",
        lambda client, base_url, username, password: {
            "username": username,
            "role": "admin",
        },
    )

    result = module.run(
        "http://127.0.0.1:8000",
        expect_deployment_mode="local",
        expect_auth_mode="required",
        expect_runtime_profile="local-required",
        expect_version="1.3.1",
        frontend_assets_dir=_local_assets(tmp_path, "index-built.js"),
        auth_user="local-admin",
        auth_password="local-password",
    )

    assert result == 0
    steps = _printed_steps(capsys)
    assert steps["runtime_profile"]["ok"] is True
    assert steps["anonymous_projects"]["ok"] is True
    assert steps["auth_login"]["ok"] is True


def test_run_rejects_invalid_reported_runtime_pair(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_deployment_check()
    _install_client(
        monkeypatch,
        module,
        html='<script src="/assets/index-built.js"></script>',
        html_cache_control="no-cache",
        api_cache_control="no-store",
        deployment_mode="cloud",
        auth_mode="off",
        runtime_profile="cloud-off",
        anonymous_projects_status=200,
    )

    result = module.run(
        "https://studio.example.test",
        expect_version="1.3.1",
        frontend_assets_dir=_local_assets(tmp_path, "index-built.js"),
    )

    assert result == 1
    profile_step = _printed_steps(capsys)["runtime_profile"]
    assert profile_step["ok"] is False
    assert "invalid runtime profile" in profile_step["result"]["error"]


def test_required_mode_requires_credentials_before_business_probes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_deployment_check()
    _install_client(
        monkeypatch,
        module,
        html='<script src="/assets/index-built.js"></script>',
        html_cache_control="no-cache",
        api_cache_control="no-store",
        deployment_mode="cloud",
        auth_mode="required",
        runtime_profile="cloud-required",
        anonymous_projects_status=401,
    )

    result = module.run(
        "https://studio.example.test",
        expect_auth_mode="required",
        expect_version="1.3.1",
        frontend_assets_dir=_local_assets(tmp_path, "index-built.js"),
    )

    assert result == 1
    steps = _printed_steps(capsys)
    assert steps["anonymous_projects"]["ok"] is True
    assert steps["auth_login"]["ok"] is False
    assert "--auth-user" in steps["auth_login"]["result"]["error"]
    assert steps["upload_readability"]["ok"] is False


def test_off_mode_rejects_credentials_instead_of_attempting_login(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_deployment_check()
    _install_client(
        monkeypatch,
        module,
        html='<script src="/assets/index-built.js"></script>',
        html_cache_control="no-cache",
        api_cache_control="no-store",
        deployment_mode="local",
        auth_mode="off",
        runtime_profile="local-off",
        anonymous_projects_status=200,
    )

    result = module.run(
        "http://127.0.0.1:5173",
        expect_auth_mode="off",
        expect_version="1.3.1",
        frontend_assets_dir=_local_assets(tmp_path, "index-built.js"),
        auth_user="not-allowed",
        auth_password="not-allowed",
    )

    assert result == 1
    auth_step = _printed_steps(capsys)["auth_login"]
    assert auth_step["ok"] is False
    assert "must not be provided" in auth_step["result"]["error"]


def test_run_rejects_contradictory_require_cloud_alias() -> None:
    module = _load_deployment_check()

    with pytest.raises(ValueError, match="--require-cloud"):
        module.run(
            "https://studio.example.test",
            require_cloud=True,
            expect_deployment_mode="local",
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"require_cloud": True, "expect_auth_mode": "off"},
        {"require_cloud": True, "expect_runtime_profile": "local-required"},
        {
            "expect_deployment_mode": "local",
            "expect_auth_mode": "required",
            "expect_runtime_profile": "cloud-required",
        },
    ],
)
def test_run_rejects_contradictory_expected_profile_components(
    kwargs: dict[str, Any],
) -> None:
    module = _load_deployment_check()

    with pytest.raises(ValueError, match="contradictory runtime profile expectations"):
        module.run("https://studio.example.test", **kwargs)


def test_main_rejects_contradictory_require_cloud_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_deployment_check()
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "deployment_check.py",
            "--base-url",
            "https://studio.example.test",
            "--require-cloud",
            "--expect-deployment-mode",
            "local",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        module.main()
    assert exc_info.value.code == 2


def test_main_forwards_runtime_profile_cli_expectations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_deployment_check()
    captured: dict[str, Any] = {}

    def fake_run(base_url: str, **kwargs: Any) -> int:
        captured.update({"base_url": base_url, **kwargs})
        return 0

    monkeypatch.setattr(module, "run", fake_run)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "deployment_check.py",
            "--base-url",
            "https://studio.example.test",
            "--expect-deployment-mode",
            "cloud",
            "--expect-auth-mode",
            "required",
            "--expect-runtime-profile",
            "cloud-required",
        ],
    )

    assert module.main() == 0
    assert captured["expect_deployment_mode"] == "cloud"
    assert captured["expect_auth_mode"] == "required"
    assert captured["expect_runtime_profile"] == "cloud-required"


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
