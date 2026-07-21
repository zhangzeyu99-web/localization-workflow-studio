from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
from types import ModuleType
from unittest.mock import patch

import httpx
import pytest

from app import config


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_stability_check() -> ModuleType:
    script_path = REPO_ROOT / "scripts" / "stability_check.py"
    spec = importlib.util.spec_from_file_location("stability_check_contract_test", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cloud_data_root_is_required_and_absolute() -> None:
    with pytest.raises(RuntimeError, match="LWS_DATA_ROOT"):
        config._resolve_data_root({"LWS_DEPLOYMENT_MODE": "cloud"})

    with pytest.raises(RuntimeError, match="absolute"):
        config._resolve_data_root(
            {"LWS_DEPLOYMENT_MODE": "cloud", "LWS_DATA_ROOT": "data/lwstudio"}
        )

    assert config._resolve_data_root(
        {"LWS_DEPLOYMENT_MODE": "cloud", "LWS_DATA_ROOT": "/srv/lwstudio/data"}
    ) == Path("/srv/lwstudio/data")

    with pytest.raises(RuntimeError, match="outside"):
        config._resolve_data_root(
            {
                "LWS_DEPLOYMENT_MODE": "cloud",
                "LWS_DATA_ROOT": str(REPO_ROOT / "lws-data"),
            }
        )


def test_cloud_data_root_rejects_symlink_into_repository(tmp_path: Path) -> None:
    repo_link = tmp_path / "repo-link"
    try:
        repo_link.symlink_to(REPO_ROOT, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(RuntimeError, match="outside"):
        config._resolve_data_root(
            {
                "LWS_DEPLOYMENT_MODE": "cloud",
                "LWS_DATA_ROOT": str(repo_link / "lws-data"),
            }
        )


def test_settings_are_replaced_atomically_and_private_on_posix(tmp_path: Path) -> None:
    target = tmp_path / "settings.local.json"

    with (
        patch.object(config.os, "replace", wraps=os.replace) as replace,
        patch.object(config.os, "chmod", wraps=os.chmod) as chmod,
    ):
        config._atomic_write_private_json(
            target,
            {"api_key": "private"},
            platform_name="posix",
        )

    assert json.loads(target.read_text(encoding="utf-8")) == {"api_key": "private"}
    assert replace.call_count == 1
    assert replace.call_args.args[1] == target
    assert chmod.call_args_list[-1].args == (target, 0o600)
    assert not list(tmp_path.glob(".settings.local.json.*.tmp"))


def test_systemd_unit_enforces_single_non_root_worker_and_current_release() -> None:
    unit = (REPO_ROOT / "deploy" / "lws.service").read_text(encoding="utf-8")

    assert "User=lwstudio" in unit
    assert "Group=lwstudio" in unit
    assert "WorkingDirectory=/srv/lwstudio/current" in unit
    assert "EnvironmentFile=/etc/lwstudio/lws.env" in unit
    assert "Restart=on-failure" in unit
    assert "--workers 1" in unit
    assert "127.0.0.1" in unit
    assert "npm run dev" not in unit


def test_nginx_template_enforces_same_origin_cache_and_upload_contract() -> None:
    nginx = (REPO_ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")

    assert "root /srv/lwstudio/current/frontend/dist;" in nginx
    assert "client_max_body_size 1g;" in nginx
    assert "location /api/" in nginx
    assert "proxy_pass http://127.0.0.1:8082;" in nginx
    assert "proxy_read_timeout 600s;" in nginx
    assert "proxy_send_timeout 600s;" in nginx
    assert 'Cache-Control "no-store" always' in nginx
    assert 'Cache-Control "no-cache" always' in nginx
    assert 'Cache-Control "public, max-age=31536000, immutable" always' in nginx
    assert "proxy_cache off;" in nginx
    assert "proxy_no_cache 1;" in nginx
    assert "proxy_request_buffering off;" in nginx
    assert "npm run dev" not in nginx
    assert ":5173" not in nginx


def test_environment_example_uses_external_data_root_and_contains_no_secret() -> None:
    env_file = REPO_ROOT / "deploy" / "lws.env.example"
    env_text = env_file.read_text(encoding="utf-8")
    values = dict(
        line.split("=", 1)
        for line in env_text.splitlines()
        if line and not line.startswith("#")
    )

    assert values["LWS_DEPLOYMENT_MODE"] == "cloud"
    assert values["LWS_AUTH_MODE"] == "required"
    assert values["LWS_DATA_ROOT"] == "/srv/lwstudio/data"
    assert values["LWS_GIT_SHA"] == "replace-with-release-git-sha"
    assert values["LWS_ADMIN_USER"] == "admin"
    assert values["LWS_ADMIN_PASSWORD"] == "replace-with-strong-bootstrap-password"
    assert PurePosixPath(values["LWS_DATA_ROOT"]).is_absolute()
    assert "/releases/" not in values["LWS_DATA_ROOT"]
    assert "API_KEY" not in env_text.upper()
    assert "SECRET" not in env_text.upper()


def test_linux_launcher_sets_explicit_profile_and_manifest_sha_fallback() -> None:
    launcher = (REPO_ROOT / "start-lws.sh").read_text(encoding="utf-8")

    assert 'export LWS_DEPLOYMENT_MODE="${LWS_DEPLOYMENT_MODE:-cloud}"' in launcher
    assert 'export LWS_AUTH_MODE="${LWS_AUTH_MODE:-required}"' in launcher
    assert 'if [[ -z "${LWS_GIT_SHA:-}" && -f "$APP_HOME/PACKAGE_MANIFEST.json" ]]; then' in launcher
    assert 'json.load(open(sys.argv[1], encoding="utf-8"))' in launcher
    assert 'isinstance(value, str) and value.strip()' in launcher
    assert 'export LWS_GIT_SHA="$manifest_git_sha"' in launcher
    assert 'runtime profile' in launcher
    assert 'auth mode' in launcher
    assert 'git SHA' in launcher
    assert '--workers 1' in launcher
    assert 'mkdir -p "$LWS_DATA_ROOT"' in launcher


def test_backend_requirements_include_argon2_password_hashing() -> None:
    requirements = (REPO_ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8")

    assert "argon2-cffi>=23.1.0" in requirements


def test_public_release_docs_match_repository_version() -> None:
    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    github_guide = (REPO_ROOT / "docs" / "GITHUB_MANAGEMENT.md").read_text(encoding="utf-8")
    pages_index = (REPO_ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert f"当前有账号版：`{version}`" in github_guide
    assert f"正式版 v{version}" in pages_index
    assert f"<strong>{version}</strong><span>当前有账号版</span>" in pages_index


def test_v160_release_commands_are_shell_safe_and_self_contained() -> None:
    release_note = (REPO_ROOT / "docs" / "releases" / "v1.6.0.md").read_text(encoding="utf-8")
    bash_blocks = [section.split("```", 1)[0] for section in release_note.split("```bash")[1:]]

    assert "<git-sha>" not in release_note
    assert "将 `REPLACE_WITH_GIT_SHA` 替换为" in release_note
    assert len(bash_blocks) == 2

    deploy_block, acceptance_block = bash_blocks
    for block in bash_blocks:
        assert "set -euo pipefail" in block
        assert "20260720-REPLACE_WITH_GIT_SHA" in block
        assert 'cd "$release"' in block
        assert "PACKAGE_GIT_SHA=" in block
        assert "PACKAGE_MANIFEST.json" in block

    assert "if sudo grep -q '^LWS_GIT_SHA=' \"$env_file\"; then" in deploy_block
    assert 'sudo sed -i "s/^LWS_GIT_SHA=.*/LWS_GIT_SHA=$PACKAGE_GIT_SHA/" "$env_file"' in deploy_block
    assert "else\n  printf 'LWS_GIT_SHA=%s\\n' \"$PACKAGE_GIT_SHA\" | sudo tee -a \"$env_file\" >/dev/null" in deploy_block
    assert 'sudo grep -Fx "LWS_GIT_SHA=$PACKAGE_GIT_SHA" "$env_file"' in deploy_block
    assert "scripts/deployment_check.py" in acceptance_block


def test_cloud_acceptance_checks_git_sha_and_exact_frontend_assets() -> None:
    guide = (REPO_ROOT / "docs" / "CLOUD_DEPLOYMENT.md").read_text(encoding="utf-8")

    assert "PACKAGE_MANIFEST.json" in guide
    assert "--expect-git-sha" in guide
    assert "--check-frontend-assets frontend/dist/assets" in guide
    assert "公网 HTML 引用" in guide
    assert "`/api/version` 清单" in guide
    assert "本地 `frontend/dist`" in guide


def test_stability_check_sends_an_operator_for_ai_jobs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_stability_check()
    monkeypatch.setattr(module, "OUT_DIR", tmp_path)
    check = module.StabilityCheck("https://example.test")
    headers = dict(check.session.headers)
    check.session.close()
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["operator"] = request.headers.get("X-Operator")
        return httpx.Response(200, json={"ok": True})

    check.session = httpx.Client(
        follow_redirects=True,
        headers=headers,
        transport=httpx.MockTransport(handler),
    )
    try:
        check.post("/api/test")
    finally:
        check.session.close()

    assert seen["operator"] == "stability-check"
