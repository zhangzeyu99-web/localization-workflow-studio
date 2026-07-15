from __future__ import annotations

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_release_package.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_release_package", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_required_tree(root: Path) -> None:
    required = {
        "VERSION": "9.9.9\n",
        "frontend/dist/index.html": "<!doctype html><title>LWS</title>",
        "deploy/lws.service": "[Service]\nExecStart=/opt/lws/start-lws.sh\n",
        "deploy/nginx.conf": "server {}\n",
        "deploy/lws.env.example": "LWS_DATA_ROOT=/var/lib/lws\n",
        "start-lws.sh": "#!/usr/bin/env bash\n",
        "backend/app/main.py": "app = object()\n",
        "settings.example.json": "{}\n",
    }
    for name, content in required.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _archive_files(zip_path: Path) -> tuple[str, dict[str, bytes]]:
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.testzip() is None
        names = [name for name in archive.namelist() if not name.endswith("/")]
        package_root = names[0].split("/", 1)[0]
        files = {
            name.removeprefix(package_root + "/"): archive.read(name)
            for name in names
        }
    return package_root, files


def test_build_refuses_dirty_tree_unless_explicitly_allowed(tmp_path, monkeypatch):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    monkeypatch.setattr(package, "ROOT", source)
    monkeypatch.setattr(package, "_git_dirty", lambda: True)
    monkeypatch.setattr(package, "_git_sha", lambda: "deadbeef")

    with pytest.raises(RuntimeError, match="dirty"):
        package.build(tmp_path / "out", "release", rebuild_frontend=False)

    zip_path = package.build(
        tmp_path / "out",
        "release",
        rebuild_frontend=False,
        allow_dirty=True,
    )
    _, files = _archive_files(zip_path)
    manifest = json.loads(files["PACKAGE_MANIFEST.json"])
    assert manifest["source_git_dirty"] is True
    assert manifest["source_state"] == "dirty_working_tree_allowed"


def test_build_requires_prebuilt_frontend_and_deployment_entries(tmp_path, monkeypatch):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    (source / "deploy" / "nginx.conf").unlink()
    monkeypatch.setattr(package, "ROOT", source)
    monkeypatch.setattr(package, "_git_dirty", lambda: False)

    with pytest.raises(RuntimeError, match="deploy/nginx.conf"):
        package.build(tmp_path / "out", "release", rebuild_frontend=False)


def test_package_excludes_secrets_process_docs_runtime_and_own_outputs(tmp_path, monkeypatch):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    forbidden = {
        "settings.local.json": '{"api_key":"do-not-ship"}',
        ".env": "TOKEN=do-not-ship",
        ".env.production": "TOKEN=do-not-ship",
        "config/api_key.txt": "do-not-ship",
        "config/client_secret.json": "do-not-ship",
        "secrets/token.txt": "do-not-ship",
        "docs/codex-handoffs/private.md": "private",
        "docs/superpowers/plan.md": "private",
        "workflow/glossary/docs/terminology-thread-handoff.md": "private",
        "credentials.json": '{"access_token":"do-not-ship"}',
        ".npmrc": "//registry.example/:_authToken=do-not-ship",
        "frontend/src/main.tsx": "console.log('source only')",
        "backend/tests/test_e2e.py": "raise AssertionError('test only')",
        "workflow/localization/tests/test_runtime.py": "raise AssertionError('test only')",
        "lws-data/lws.sqlite3": "runtime",
        "uploads/input.xlsx": "runtime",
        "outputs/result.xlsx": "runtime",
    }
    for name, content in forbidden.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    output_dir = source / "release-output"
    output_dir.mkdir(parents=True)
    (output_dir / "old.zip").write_text("recursive-content", encoding="utf-8")
    monkeypatch.setattr(package, "ROOT", source)
    monkeypatch.setattr(package, "_git_dirty", lambda: False)
    monkeypatch.setattr(package, "_git_sha", lambda: "deadbeef")

    zip_path = package.build(output_dir, "release", rebuild_frontend=False)
    _, files = _archive_files(zip_path)
    lowered = {name.lower() for name in files}
    for forbidden_name in forbidden:
        assert forbidden_name.lower() not in lowered
    assert not any(name.startswith("release-output/") for name in files)
    assert "settings.example.json" in files
    assert "frontend/src/main.tsx" not in files
    assert "backend/tests/test_e2e.py" not in files


@pytest.mark.parametrize(
    "secret_text",
    [
        "Bearer eyJhbGciOiJIUzI1NiJ9.real-signature-value",
        "API_KEY=live_key_1234567890abcdefghij",
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz123456",
    ],
)
def test_build_rejects_real_secret_content_in_allowlisted_text(
    tmp_path,
    monkeypatch,
    secret_text,
):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    candidate = source / "workflow" / "localization" / "templates" / "notes.txt"
    candidate.parent.mkdir(parents=True)
    candidate.write_text(secret_text, encoding="utf-8")
    monkeypatch.setattr(package, "ROOT", source)
    monkeypatch.setattr(package, "_git_dirty", lambda: False)

    with pytest.raises(RuntimeError, match="secret|credential|token"):
        package.build(tmp_path / "out", "release", rebuild_frontend=False)


def test_build_scans_text_before_copy_and_during_archive_readback(tmp_path, monkeypatch):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    allowed_text = source / "workflow" / "glossary" / "templates" / "runtime.txt"
    allowed_text.parent.mkdir(parents=True)
    allowed_text.write_text("safe production template", encoding="utf-8")
    monkeypatch.setattr(package, "ROOT", source)
    monkeypatch.setattr(package, "_git_dirty", lambda: False)
    monkeypatch.setattr(package, "_git_sha", lambda: "deadbeef")

    calls: list[str] = []
    real_scanner = package._scan_text_bytes

    def tracking_scanner(content: bytes, *, origin: str) -> None:
        calls.append(origin)
        real_scanner(content, origin=origin)

    monkeypatch.setattr(package, "_scan_text_bytes", tracking_scanner)
    zip_path = package.build(tmp_path / "out", "release", rebuild_frontend=False)
    _, files = _archive_files(zip_path)

    assert "workflow/glossary/templates/runtime.txt" in files
    assert any(origin.endswith("workflow/glossary/templates/runtime.txt") for origin in calls)
    assert any(
        origin.startswith("archive:")
        and origin.endswith("workflow/glossary/templates/runtime.txt")
        for origin in calls
    )


def test_build_scans_required_env_example_even_without_text_suffix(tmp_path, monkeypatch):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    (source / "deploy" / "lws.env.example").write_text(
        "API_KEY=live_key_1234567890abcdefghij",
        encoding="utf-8",
    )
    monkeypatch.setattr(package, "ROOT", source)
    monkeypatch.setattr(package, "_git_dirty", lambda: False)

    with pytest.raises(RuntimeError, match="secret|credential|token"):
        package.build(tmp_path / "out", "release", rebuild_frontend=False)


def test_completed_archive_is_readable_complete_and_hash_verified(tmp_path, monkeypatch):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    monkeypatch.setattr(package, "ROOT", source)
    monkeypatch.setattr(package, "_git_dirty", lambda: False)
    monkeypatch.setattr(package, "_git_sha", lambda: "deadbeef")

    zip_path = package.build(tmp_path / "out", "release", rebuild_frontend=False)
    _, files = _archive_files(zip_path)

    sidecar = zip_path.with_name(f"{zip_path.name}.sha256")
    digest, filename = sidecar.read_text(encoding="utf-8").strip().split("  ", 1)
    assert filename == zip_path.name
    assert digest == hashlib.sha256(zip_path.read_bytes()).hexdigest()

    assert package.REQUIRED_MEMBERS <= set(files)
    assert "settings.local.json" not in files
    manifest = json.loads(files["PACKAGE_MANIFEST.json"])
    assert manifest["contains_settings_local"] is False
    assert manifest["archive_verified"] is True

    rows = files["SHA256SUMS.txt"].decode("utf-8").splitlines()
    hashes = {name: digest for digest, name in (row.split("  ", 1) for row in rows)}
    assert set(hashes) == set(files) - {"SHA256SUMS.txt"}
    for name, digest in hashes.items():
        assert hashlib.sha256(files[name]).hexdigest() == digest

    readme = files["ONLINE_DEPLOY_README.zh-CN.md"].decode("utf-8")
    assert "npm install" not in readme
    assert "settings.local.json" in readme
    assert "$LWS_DATA_ROOT/settings.local.json" in readme
    assert "/srv/lwstudio/current" in readme
    assert "/srv/lwstudio/data" in readme
    assert "/opt/lwstudio" not in readme
    assert "/var/lib/lwstudio" not in readme


def test_cli_no_longer_accepts_settings_file_option(monkeypatch):
    package = _load_module()
    monkeypatch.setattr("sys.argv", ["build_release_package.py", "--settings-file", "secret.json"])
    with pytest.raises(SystemExit) as exc:
        package.main()
    assert exc.value.code == 2


def test_package_rejects_symlinks_inside_allowed_runtime_paths(tmp_path, monkeypatch):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    outside = tmp_path / "outside.py"
    outside.write_text("EXTERNAL = True\n", encoding="utf-8")
    linked = source / "backend" / "app" / "linked.py"
    try:
        linked.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    monkeypatch.setattr(package, "ROOT", source)
    monkeypatch.setattr(package, "_git_dirty", lambda: False)
    monkeypatch.setattr(package, "_git_sha", lambda: "deadbeef")

    with pytest.raises(RuntimeError, match="symlink"):
        package.build(tmp_path / "out", "release", rebuild_frontend=False)
