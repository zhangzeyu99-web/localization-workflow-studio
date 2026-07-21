from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
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
        "frontend/dist/assets/app.js": "console.log('runtime-profile')\n",
        "deploy/lws.service": "[Service]\nExecStart=/opt/lws/start-lws.sh\n",
        "deploy/nginx.conf": "server {}\n",
        "deploy/lws.env.example": "LWS_DATA_ROOT=/var/lib/lws\n",
        "deploy/profiles/local-off.env.example": (
            "LWS_DEPLOYMENT_MODE=local\nLWS_AUTH_MODE=off\nLWS_SERVE_FRONTEND=1\nLWS_DATA_ROOT=C:\\ProgramData\\LocalizationWorkflowStudio\\data\n"
        ),
        "deploy/profiles/cloud-required.env.example": (
            "LWS_DEPLOYMENT_MODE=cloud\n"
            "LWS_AUTH_MODE=required\n"
            "LWS_SERVE_FRONTEND=0\n"
            "LWS_DATA_ROOT=/srv/lwstudio/data\n"
            "LWS_GIT_SHA=replace-with-package-manifest-git-sha\n"
            "LWS_ADMIN_USER=admin\n"
            "LWS_ADMIN_PASSWORD=replace-with-strong-bootstrap-password\n"
        ),
        "start-lws.sh": "#!/usr/bin/env bash\n",
        "start-workbench.cmd": "@echo off\n",
        "check.py": "def main():\n    return 0\n",
        "backend/app/main.py": "app = object()\n",
        "scripts/create_admin.py": "def main():\n    return 0\n",
        "scripts/deployment_auth.py": "def login(*args, **kwargs):\n    return {}\n",
        "scripts/deployment_check.py": "def main():\n    return 0\n",
        "scripts/stability_check.py": "def main():\n    return 0\n",
        "scripts/start-workbench.ps1": "Write-Output 'start'\n",
        "scripts/lws-workbench-control.ps1": "Write-Output 'control'\n",
        "scripts/stop-workbench.ps1": "Write-Output 'stop'\n",
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
        files = {name.removeprefix(package_root + "/"): archive.read(name) for name in names}
    return package_root, files


def _canonical_tree_digest(files: dict[str, bytes], members: set[str]) -> str:
    records = bytearray()
    for name in sorted(members):
        content_hash = hashlib.sha256(files[name]).hexdigest()
        records.extend(name.encode("utf-8"))
        records.extend(b"\0")
        records.extend(content_hash.encode("ascii"))
        records.extend(b"\n")
    return hashlib.sha256(records).hexdigest()


def _configure_clean_git(package, monkeypatch) -> None:
    monkeypatch.setattr(package, "_git_dirty", lambda: False)
    monkeypatch.setattr(
        package,
        "_git_sha_full",
        lambda: "deadbeefcafebabefeedface0123456789abcdef",
        raising=False,
    )


def test_build_refuses_dirty_tree(tmp_path, monkeypatch):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    monkeypatch.setattr(package, "ROOT", source)
    monkeypatch.setattr(package, "_git_dirty", lambda: True)

    with pytest.raises(RuntimeError, match="dirty"):
        package.build(tmp_path / "out", rebuild_frontend=False)


def test_build_requires_prebuilt_frontend_and_deployment_entries(tmp_path, monkeypatch):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    (source / "deploy" / "nginx.conf").unlink()
    monkeypatch.setattr(package, "ROOT", source)
    _configure_clean_git(package, monkeypatch)

    with pytest.raises(RuntimeError, match="deploy/nginx.conf"):
        package.build(tmp_path / "out", rebuild_frontend=False)


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
    _configure_clean_git(package, monkeypatch)

    zip_path = package.build(output_dir, rebuild_frontend=False)
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
    _configure_clean_git(package, monkeypatch)

    with pytest.raises(RuntimeError, match="secret|credential|token"):
        package.build(tmp_path / "out", rebuild_frontend=False)


def test_build_scans_text_before_copy_and_during_archive_readback(tmp_path, monkeypatch):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    allowed_text = source / "workflow" / "glossary" / "templates" / "runtime.txt"
    allowed_text.parent.mkdir(parents=True)
    allowed_text.write_text("safe production template", encoding="utf-8")
    monkeypatch.setattr(package, "ROOT", source)
    _configure_clean_git(package, monkeypatch)

    calls: list[str] = []
    real_scanner = package._scan_text_bytes

    def tracking_scanner(content: bytes, *, origin: str) -> None:
        calls.append(origin)
        real_scanner(content, origin=origin)

    monkeypatch.setattr(package, "_scan_text_bytes", tracking_scanner)
    zip_path = package.build(tmp_path / "out", rebuild_frontend=False)
    _, files = _archive_files(zip_path)

    assert "workflow/glossary/templates/runtime.txt" in files
    assert any(origin.endswith("workflow/glossary/templates/runtime.txt") for origin in calls)
    assert any(origin.startswith("archive:") and origin.endswith("workflow/glossary/templates/runtime.txt") for origin in calls)


def test_build_scans_required_env_example_even_without_text_suffix(tmp_path, monkeypatch):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    (source / "deploy" / "lws.env.example").write_text(
        "API_KEY=live_key_1234567890abcdefghij",
        encoding="utf-8",
    )
    monkeypatch.setattr(package, "ROOT", source)
    _configure_clean_git(package, monkeypatch)

    with pytest.raises(RuntimeError, match="secret|credential|token"):
        package.build(tmp_path / "out", rebuild_frontend=False)


def test_completed_archive_is_readable_complete_and_hash_verified(tmp_path, monkeypatch):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    monkeypatch.setattr(package, "ROOT", source)
    _configure_clean_git(package, monkeypatch)

    zip_path = package.build(tmp_path / "out", rebuild_frontend=False)
    package_root, files = _archive_files(zip_path)

    assert package_root == "localization-workflow-studio-v9.9.9-gdeadbeefcafe-universal"
    assert zip_path.name == f"{package_root}.zip"

    sidecar = zip_path.with_name(f"{zip_path.name}.sha256")
    digest, filename = sidecar.read_text(encoding="utf-8").strip().split("  ", 1)
    assert filename == zip_path.name
    assert digest == hashlib.sha256(zip_path.read_bytes()).hexdigest()

    assert package.REQUIRED_MEMBERS <= set(files)
    assert "settings.local.json" not in files
    manifest = json.loads(files["PACKAGE_MANIFEST.json"])
    assert {
        "schema_version": manifest["schema_version"],
        "artifact_kind": manifest["artifact_kind"],
        "version": manifest["version"],
        "git_sha": manifest["git_sha"],
        "git_sha_full": manifest["git_sha_full"],
        "source_git_dirty": manifest["source_git_dirty"],
        "source_state": manifest["source_state"],
        "frontend_configuration": manifest["frontend_configuration"],
        "supported_runtime_profiles": manifest["supported_runtime_profiles"],
        "contains_settings_local": manifest["contains_settings_local"],
        "archive_verified": manifest["archive_verified"],
    } == {
        "schema_version": 2,
        "artifact_kind": "universal",
        "version": "9.9.9",
        "git_sha": "deadbeefcafe",
        "git_sha_full": "deadbeefcafebabefeedface0123456789abcdef",
        "source_git_dirty": False,
        "source_state": "clean_git_commit",
        "frontend_configuration": "runtime_profile",
        "supported_runtime_profiles": ["local-off", "cloud-required"],
        "contains_settings_local": False,
        "archive_verified": True,
    }
    assert manifest["build_id"] == package_root
    assert "frontend_settings_button_hidden" not in manifest
    assert manifest["entrypoints"] == {
        "windows_start": "scripts/start-workbench.ps1",
        "windows_control": "scripts/lws-workbench-control.ps1",
        "linux_backend": "start-lws.sh",
        "backend_app": "backend/app/main.py",
        "create_admin": "scripts/create_admin.py",
        "deployment_check": "check.py",
        "stability_check": "scripts/stability_check.py",
    }

    frontend_files = {name.removeprefix("frontend/dist/"): content for name, content in files.items() if name.startswith("frontend/dist/")}
    runtime_members = set(files) - package.GENERATED_MEMBERS
    assert manifest["frontend_dist_sha256"] == _canonical_tree_digest(
        frontend_files,
        set(frontend_files),
    )
    assert manifest["runtime_payload_sha256"] == _canonical_tree_digest(
        files,
        runtime_members,
    )

    rows = files["SHA256SUMS.txt"].decode("utf-8").splitlines()
    hashes = {name: digest for digest, name in (row.split("  ", 1) for row in rows)}
    assert set(hashes) == set(files) - {"SHA256SUMS.txt"}
    for name, digest in hashes.items():
        assert hashlib.sha256(files[name]).hexdigest() == digest

    readme = files["DEPLOY_README.zh-CN.md"].decode("utf-8")
    assert "npm install" not in readme
    assert "同一个 ZIP" in readme
    assert "local-off" in readme
    assert "cloud-required" in readme
    assert "LWS_DEPLOYMENT_MODE=local" in readme
    assert "LWS_AUTH_MODE=off" in readme
    assert "LWS_DEPLOYMENT_MODE=cloud" in readme
    assert "LWS_AUTH_MODE=required" in readme
    assert "settings.local.json" in readme
    assert "$LWS_DATA_ROOT/settings.local.json" in readme
    assert "/srv/lwstudio/current" in readme
    assert "/srv/lwstudio/data" in readme
    assert "scripts/create_admin.py" in readme
    assert "LWS_ADMIN_USER" in readme
    assert "LWS_ADMIN_PASSWORD" in readme
    assert "anonymous_projects" in readme
    assert "--auth-user" in readme
    assert "--auth-password" in readme
    assert 'cd "$APP_HOME"' in readme
    assert readme.index('cd "$APP_HOME"') < readme.index(".venv/bin/python check.py")
    assert "deploy/lws.service" in readme
    assert "systemctl daemon-reload" in readme
    assert "systemctl enable --now lws" in readme
    assert "deploy/nginx.conf" in readme
    assert "nginx -t" in readme
    assert "systemctl reload nginx" in readme
    cloud_install_steps = [
        'cd "$APP_HOME"',
        "python3.11 -m venv .venv",
        ".venv/bin/python -m pip install -r backend/requirements.txt",
        ".venv/bin/python -m pip install -r workflow/glossary/requirements.txt",
        ".venv/bin/python -m pip install -r workflow/localization/requirements.txt",
        "sudo install -d -m 750 -o root -g lwstudio /etc/lwstudio",
        ("sudo install -m 640 -o root -g lwstudio deploy/profiles/cloud-required.env.example /etc/lwstudio/lws.env"),
        "sudo install -d -m 750 -o lwstudio -g lwstudio /srv/lwstudio/data",
        "sudo install -m 644 deploy/lws.service /etc/systemd/system/lws.service",
        "sudo systemctl enable --now lws",
        "sudo install -m 644 deploy/nginx.conf /etc/nginx/conf.d/lwstudio.conf",
    ]
    positions = [readme.index(step) for step in cloud_install_steps]
    assert positions == sorted(positions)
    assert "LWS_GIT_SHA=replace-with-package-manifest-git-sha" in readme
    assert "LWS_ADMIN_PASSWORD=replace-with-strong-bootstrap-password" in readme
    assert "发布目录之外" in readme
    assert "/etc/lwstudio/lws.env" in readme
    verification_commands = readme.split("部署后运行：", 1)[1]
    assert "python3.11" not in verification_commands
    assert "$(.venv/bin/python -c" in verification_commands
    assert ".venv/bin/python check.py" in verification_commands
    assert ".venv/bin/python scripts/stability_check.py" in verification_commands
    assert "scripts/create_admin.py" in files
    assert "scripts/deployment_auth.py" in files
    assert "scripts/start-workbench.ps1" in files
    assert "scripts/lws-workbench-control.ps1" in files
    assert "scripts/stop-workbench.ps1" in files
    assert "start-workbench.cmd" in files
    assert files["deploy/profiles/local-off.env.example"].decode("utf-8").splitlines()[:2] == ["LWS_DEPLOYMENT_MODE=local", "LWS_AUTH_MODE=off"]
    assert files["deploy/profiles/cloud-required.env.example"].decode("utf-8").splitlines()[:2] == ["LWS_DEPLOYMENT_MODE=cloud", "LWS_AUTH_MODE=required"]
    assert not any(name.startswith("frontend/src/") for name in files)
    assert "frontend/package.json" not in files
    assert "/opt/lwstudio" not in readme
    assert "/var/lib/lwstudio" not in readme


def test_cli_no_longer_accepts_settings_file_option(monkeypatch):
    package = _load_module()
    monkeypatch.setattr("sys.argv", ["build_release_package.py", "--settings-file", "secret.json"])
    with pytest.raises(SystemExit) as exc:
        package.main()
    assert exc.value.code == 2


def test_frontend_settings_visibility_is_runtime_only():
    root = SCRIPT.parents[1]
    vite_config = (root / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    vite_env = (root / "frontend" / "src" / "vite-env.d.ts").read_text(encoding="utf-8")
    main = (root / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")

    combined = vite_config + vite_env + main
    assert "LWS_HIDE_SETTINGS" not in combined
    assert "__HIDE_SETTINGS__" not in combined
    assert "runtimeVersion?.deployment_mode === 'local' && can(ADMIN)" in main


@pytest.mark.parametrize("deprecated_flag", ["--hide-settings", "--allow-dirty"])
def test_cli_rejects_deprecated_build_flags(monkeypatch, deprecated_flag):
    package = _load_module()
    monkeypatch.setattr(
        package,
        "build",
        lambda *args, **kwargs: pytest.fail("deprecated flag reached build()"),
    )
    monkeypatch.setattr("sys.argv", ["build_release_package.py", deprecated_flag])
    with pytest.raises(SystemExit) as exc:
        package.main()
    assert exc.value.code == 2


def test_archive_verification_rejects_modified_runtime_payload_digest(
    tmp_path,
    monkeypatch,
):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    monkeypatch.setattr(package, "ROOT", source)
    _configure_clean_git(package, monkeypatch)
    zip_path = package.build(tmp_path / "out", rebuild_frontend=False)
    package_root, files = _archive_files(zip_path)

    manifest = json.loads(files["PACKAGE_MANIFEST.json"])
    manifest["runtime_payload_sha256"] = "0" * 64
    files["PACKAGE_MANIFEST.json"] = json.dumps(manifest).encode("utf-8")
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in files.items() if name != "SHA256SUMS.txt"}
    files["SHA256SUMS.txt"] = ("".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items()))).encode("utf-8")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(f"{package_root}/{name}", content)

    with pytest.raises(RuntimeError, match="runtime payload"):
        package._verify_archive(zip_path)


def test_archive_verification_rejects_directory_symlink(tmp_path, monkeypatch):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    monkeypatch.setattr(package, "ROOT", source)
    _configure_clean_git(package, monkeypatch)
    zip_path = package.build(tmp_path / "out", rebuild_frontend=False)
    package_root, _ = _archive_files(zip_path)

    link = zipfile.ZipInfo(f"{package_root}/backend/app/linked-directory/")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(zip_path, "a") as archive:
        archive.writestr(link, "../../outside")

    with pytest.raises(RuntimeError, match="symlink"):
        package._verify_archive(zip_path)


@pytest.mark.parametrize("directory", ["unrelated-empty", ".git"])
def test_archive_verification_rejects_unallowed_empty_directory(
    tmp_path,
    monkeypatch,
    directory,
):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    monkeypatch.setattr(package, "ROOT", source)
    _configure_clean_git(package, monkeypatch)
    zip_path = package.build(tmp_path / "out", rebuild_frontend=False)
    package_root, _ = _archive_files(zip_path)

    with zipfile.ZipFile(zip_path, "a") as archive:
        archive.writestr(f"{package_root}/{directory}/", b"")

    with pytest.raises(RuntimeError, match="directory|forbidden|allowlist"):
        package._verify_archive(zip_path)


def test_build_rechecks_clean_source_after_frontend_build(tmp_path, monkeypatch):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    monkeypatch.setattr(package, "ROOT", source)
    monkeypatch.setattr(
        package,
        "_git_sha_full",
        lambda: "deadbeefcafebabefeedface0123456789abcdef",
    )
    dirty_states = iter([False, True])
    monkeypatch.setattr(package, "_git_dirty", lambda: next(dirty_states))
    frontend_builds = 0

    def build_frontend() -> None:
        nonlocal frontend_builds
        frontend_builds += 1

    monkeypatch.setattr(package, "_build_frontend", build_frontend)

    with pytest.raises(RuntimeError, match="dirty"):
        package.build(tmp_path / "out", rebuild_frontend=True)
    assert frontend_builds == 1


def test_build_deletes_artifact_if_head_changes_during_packaging(
    tmp_path,
    monkeypatch,
):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    monkeypatch.setattr(package, "ROOT", source)
    monkeypatch.setattr(package, "_git_dirty", lambda: False)
    original_sha = "deadbeefcafebabefeedface0123456789abcdef"
    changed_sha = "0123456789abcdefdeadbeefcafebabefeedface"
    sha_states = iter([original_sha, original_sha, original_sha, changed_sha])
    monkeypatch.setattr(package, "_git_sha_full", lambda: next(sha_states))
    output_dir = tmp_path / "out"
    artifact = output_dir / "localization-workflow-studio-v9.9.9-gdeadbeefcafe-universal.zip"

    with pytest.raises(RuntimeError, match="HEAD changed"):
        package.build(output_dir, rebuild_frontend=False)

    assert not artifact.exists()
    assert not artifact.with_name(f"{artifact.name}.sha256").exists()


def test_build_deletes_partial_artifacts_if_archive_write_fails(
    tmp_path,
    monkeypatch,
):
    package = _load_module()
    source = tmp_path / "source"
    _write_required_tree(source)
    monkeypatch.setattr(package, "ROOT", source)
    _configure_clean_git(package, monkeypatch)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    artifact = output_dir / "localization-workflow-studio-v9.9.9-gdeadbeefcafe-universal.zip"
    sidecar = artifact.with_name(f"{artifact.name}.sha256")
    artifact.write_bytes(b"stale archive")
    sidecar.write_text("stale sidecar", encoding="utf-8")

    def fail_archive_write(*args, **kwargs):
        raise OSError("simulated archive write failure")

    monkeypatch.setattr(zipfile.ZipFile, "write", fail_archive_write)

    with pytest.raises(OSError, match="simulated archive write failure"):
        package.build(output_dir, rebuild_frontend=False)

    assert not artifact.exists()
    assert not sidecar.exists()


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
    _configure_clean_git(package, monkeypatch)

    with pytest.raises(RuntimeError, match="symlink"):
        package.build(tmp_path / "out", rebuild_frontend=False)
