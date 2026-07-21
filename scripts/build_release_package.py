from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_DIR_NAMES = {
    ".git",
    ".github",
    ".local-logs",
    ".playwright-cli",
    ".pytest_cache",
    ".ruff_cache",
    ".superpowers",
    ".tmp",
    ".venv",
    "__pycache__",
    "artifacts",
    "codex-handoffs",
    "frontend-v2",
    "localization-workflow-studio-data",
    "logs",
    "lws-data",
    "node_modules",
    "outputs",
    "playwright-report",
    "projects",
    "release-staging",
    "release_archives",
    "runs",
    "runtime",
    "superpowers",
    "test-results",
    "tmp",
    "uploads",
}
EXCLUDED_SUFFIXES = {
    ".bak",
    ".db",
    ".log",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
    ".tmp",
}

REQUIRED_SOURCE_MEMBERS = {
    "frontend/dist/index.html",
    "deploy/lws.service",
    "deploy/nginx.conf",
    "deploy/lws.env.example",
    "deploy/profiles/local-off.env.example",
    "deploy/profiles/cloud-required.env.example",
    "start-lws.sh",
    "start-workbench.cmd",
    "check.py",
    "backend/app/main.py",
    "scripts/create_admin.py",
    "scripts/deployment_auth.py",
    "scripts/deployment_check.py",
    "scripts/stability_check.py",
    "scripts/start-workbench.ps1",
    "scripts/lws-workbench-control.ps1",
    "scripts/stop-workbench.ps1",
    "settings.example.json",
}
GENERATED_MEMBERS = {
    "DEPLOY_README.zh-CN.md",
    "PACKAGE_MANIFEST.json",
    "SHA256SUMS.txt",
}
REQUIRED_MEMBERS = REQUIRED_SOURCE_MEMBERS | GENERATED_MEMBERS

TOP_LEVEL_RELEASE_FILES = {
    "VERSION",
    "check.py",
    "settings.example.json",
    "start-lws.sh",
    "start-workbench.cmd",
}
DEPLOY_RELEASE_FILES = {
    "deploy/lws.env.example",
    "deploy/lws.service",
    "deploy/nginx.conf",
    "deploy/profiles/local-off.env.example",
    "deploy/profiles/cloud-required.env.example",
}
SCRIPT_RELEASE_FILES = {
    "scripts/create_admin.py",
    "scripts/deployment_auth.py",
    "scripts/deployment_check.py",
    "scripts/stability_check.py",
    "scripts/start-workbench.ps1",
    "scripts/lws-workbench-control.ps1",
    "scripts/stop-workbench.ps1",
}
GLOSSARY_ROOT_RELEASE_FILES = {
    "workflow/glossary/VERSION",
    "workflow/glossary/requirements.txt",
}
LOCALIZATION_ROOT_RELEASE_FILES = {
    "workflow/localization/cli.py",
    "workflow/localization/process_language.py",
    "workflow/localization/requirements.txt",
    "workflow/localization/workspace_runner.py",
}
TEXT_EXTENSIONS = {
    ".cfg",
    ".csv",
    ".conf",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".map",
    ".ps1",
    ".py",
    ".service",
    ".sh",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
    ".tsv",
    ".txt",
    ".yaml",
    ".yml",
    ".xml",
}
SECRET_PATTERNS = (
    (
        "provider key",
        re.compile(r"(?<![A-Za-z0-9])((?:sk-ant-|sk-)[A-Za-z0-9._-]{20,})"),
    ),
    (
        "bearer token",
        re.compile(r"(?i)\bBearer\s+([A-Za-z0-9][A-Za-z0-9._-]{19,})"),
    ),
    (
        "assigned API credential",
        re.compile(
            r"(?im)(?:^|[\"'])\s*(?:api[_-]?key|access[_-]?token|auth[_-]?token|secret)"
            r"\s*[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9][A-Za-z0-9._-]{19,})"
        ),
    ),
    (
        "service token",
        re.compile(r"(?<![A-Za-z0-9])((?:ghp_|github_pat_|xox[baprs]-|AIza)[A-Za-z0-9._-]{16,})"),
    ),
)
PLACEHOLDER_MARKERS = {
    "changeme",
    "dummy",
    "example",
    "not-a-real",
    "placeholder",
    "replace-me",
    "replace-with",
    "sample",
    "test-key",
    "your-api-key",
    "your_api_key",
}

ENTRYPOINTS = {
    "windows_start": "scripts/start-workbench.ps1",
    "windows_control": "scripts/lws-workbench-control.ps1",
    "linux_backend": "start-lws.sh",
    "backend_app": "backend/app/main.py",
    "create_admin": "scripts/create_admin.py",
    "deployment_check": "check.py",
    "stability_check": "scripts/stability_check.py",
}
SUPPORTED_RUNTIME_PROFILES = ["local-off", "cloud-required"]


def _git_sha_full() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            .strip()
            .lower()
        )
    except Exception as exc:
        raise RuntimeError("unable to resolve the source Git commit") from exc


def _git_dirty() -> bool:
    try:
        output = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return bool(output.strip())
    except Exception:
        return True


def _version() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("release package requires VERSION") from exc


def _is_forbidden_relative(relative: Path) -> bool:
    lowered_parts = tuple(part.lower() for part in relative.parts)
    if any(part in EXCLUDED_DIR_NAMES for part in lowered_parts[:-1]):
        return True

    for part in lowered_parts:
        if "handoff" in part or "process-doc" in part:
            return True
        if "credential" in part:
            return True
        if part == "settings.local.json" or part.startswith("settings.local."):
            return True
        if part == ".env" or part.startswith(".env."):
            return True
        if part in {".netrc", ".npmrc", ".pypirc"}:
            return True
        if "api_key" in part or "api-key" in part or "apikey" in part:
            return True
        if "secret" in part:
            return True

    name = relative.name.lower()
    if name.endswith(".local"):
        return True
    return relative.suffix.lower() in EXCLUDED_SUFFIXES


def _is_allowed_source_member(relative: Path) -> bool:
    member = relative.as_posix()
    if member in TOP_LEVEL_RELEASE_FILES | DEPLOY_RELEASE_FILES | SCRIPT_RELEASE_FILES:
        return True
    if member == "backend/requirements.txt":
        return True
    if member.startswith("backend/app/"):
        return relative.suffix.lower() == ".py"
    if member.startswith("frontend/dist/"):
        return True
    if member in GLOSSARY_ROOT_RELEASE_FILES:
        return True
    if member.startswith("workflow/glossary/glossary_extraction/"):
        return relative.suffix.lower() == ".py"
    if member.startswith("workflow/glossary/scripts/"):
        return relative.suffix.lower() == ".py"
    if member.startswith("workflow/glossary/templates/"):
        return True
    if member.startswith("workflow/glossary/fixtures/"):
        return relative.suffix.lower() == ".json"
    if member.startswith("workflow/glossary/data/experience/"):
        return relative.suffix.lower() == ".json"
    if member in LOCALIZATION_ROOT_RELEASE_FILES:
        return True
    if member.startswith("workflow/localization/utils/"):
        return relative.suffix.lower() == ".py"
    if member.startswith("workflow/localization/scripts/"):
        return relative.suffix.lower() == ".py"
    if member.startswith("workflow/localization/templates/"):
        return True
    if member.startswith("workflow/localization/fixtures/"):
        return relative.suffix.lower() == ".json"
    return False


def _is_allowed_archive_member(relative: Path) -> bool:
    return relative.as_posix() in GENERATED_MEMBERS or _is_allowed_source_member(relative)


def _is_text_candidate(relative: Path) -> bool:
    name = relative.name.lower()
    return relative.suffix.lower() in TEXT_EXTENSIONS or name == "version" or name.endswith(".env.example")


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def _scan_text_bytes(content: bytes, *, origin: str) -> None:
    if b"\x00" in content:
        return
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return
    for label, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            candidate = match.group(1)
            if not _is_placeholder(candidate):
                raise RuntimeError(f"secret-like credential or token detected in {origin} ({label})")


def _scan_file(path: Path, relative: Path) -> None:
    if _is_text_candidate(relative):
        _scan_text_bytes(path.read_bytes(), origin=relative.as_posix())


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _iter_files(*, excluded_roots: Iterable[Path] = ()) -> Iterable[Path]:
    resolved_exclusions = tuple(path.resolve() for path in excluded_roots)
    for path in ROOT.rglob("*"):
        if path.is_dir():
            continue
        relative = path.relative_to(ROOT)
        if _is_allowed_source_member(relative) and path.is_symlink():
            raise RuntimeError(f"refusing symlink in release source: {relative.as_posix()}")
        resolved = path.resolve()
        if any(_is_within(resolved, excluded) for excluded in resolved_exclusions):
            continue
        if not _is_allowed_source_member(relative):
            continue
        if _is_forbidden_relative(relative):
            continue
        _scan_file(path, relative)
        yield path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha256(root: Path, files: Iterable[Path]) -> str:
    """Hash sorted relative paths and their content hashes using the release contract."""
    records = bytearray()
    relative_files = sorted(
        ((path.relative_to(root).as_posix(), path) for path in files),
        key=lambda item: item[0],
    )
    for relative, path in relative_files:
        records.extend(relative.encode("utf-8"))
        records.extend(b"\0")
        records.extend(_sha256(path).encode("ascii"))
        records.extend(b"\n")
    return hashlib.sha256(records).hexdigest()


def _write_archive_sidecar(zip_path: Path) -> Path:
    sidecar = zip_path.with_name(f"{zip_path.name}.sha256")
    sidecar.write_text(f"{_sha256(zip_path)}  {zip_path.name}\n", encoding="utf-8")
    _verify_archive_sidecar(zip_path)
    return sidecar


def _verify_archive_sidecar(zip_path: Path) -> None:
    sidecar = zip_path.with_name(f"{zip_path.name}.sha256")
    try:
        digest, filename = sidecar.read_text(encoding="utf-8").strip().split("  ", 1)
    except (OSError, ValueError) as exc:
        raise RuntimeError("release archive SHA-256 sidecar is unreadable") from exc
    if filename != zip_path.name or digest != _sha256(zip_path):
        raise RuntimeError("release archive SHA-256 sidecar verification failed")


def _build_frontend() -> None:
    subprocess.check_call(
        ["npm", "run", "build"],
        cwd=ROOT / "frontend",
        env=dict(os.environ),
        shell=(os.name == "nt"),
    )


def _assert_required_source_members() -> None:
    missing = sorted(member for member in REQUIRED_SOURCE_MEMBERS if not (ROOT / member).is_file())
    if missing:
        raise RuntimeError("release package is missing required source members: " + ", ".join(missing))


def _write_install_doc(target_root: Path, version: str, sha: str) -> None:
    text = f"""# 本地化工作台通用部署说明

版本：{version}
源码提交：{sha}
打包时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

本发布物是同一个 ZIP，可按运行时环境变量用于本地和云端，不需要重新构建前端。

## 支持的精确运行配置

- `local-off`：`LWS_DEPLOYMENT_MODE=local`、`LWS_AUTH_MODE=off`，参考 `deploy/profiles/local-off.env.example`。
- `cloud-required`：`LWS_DEPLOYMENT_MODE=cloud`、`LWS_AUTH_MODE=required`，参考 `deploy/profiles/cloud-required.env.example`。

包内不含 `settings.local.json`、凭据、数据库、上传文件、日志、测试、CI、前端源码或包管理器文件。运行数据必须放在发布目录外。

## 本地启动

Windows 可运行 `start-workbench.cmd`，或调用 `scripts/start-workbench.ps1`。控制和停止入口分别为
`scripts/lws-workbench-control.ps1` 与 `scripts/stop-workbench.ps1`。

## 云端部署

```bash
export APP_HOME=/srv/lwstudio/current
export LWS_DATA_ROOT=/srv/lwstudio/data
sudo install -d -m 750 -o lwstudio -g lwstudio "$LWS_DATA_ROOT"
sudo -u lwstudio cp "$APP_HOME/settings.example.json" "$LWS_DATA_ROOT/settings.local.json"
sudo -u lwstudio chmod 600 "$LWS_DATA_ROOT/settings.local.json"
```

仅在 `$LWS_DATA_ROOT/settings.local.json` 中填写私有 API 配置。依赖从包内三个 requirements 文件安装，服务器不需要 Node.js。

首次启动可用 `LWS_ADMIN_USER` 与 `LWS_ADMIN_PASSWORD` 引导管理员，也可运行
`scripts/create_admin.py`。完成首次登录和改密后应移除引导密码。

部署后运行：

```bash
release_sha="$(python3.11 -c 'import json; print(json.load(open("PACKAGE_MANIFEST.json", encoding="utf-8"))["git_sha"])')"
python3.11 check.py \
  --base-url https://example.invalid \
  --expect-deployment-mode cloud \
  --expect-auth-mode required \
  --expect-runtime-profile cloud-required \
  --expect-version {version} \
  --expect-git-sha "$release_sha" \
  --check-frontend-assets frontend/dist/assets \
  --auth-user admin \
  --auth-password 'replace-with-admin-password'
python3.11 scripts/stability_check.py \
  --base-url https://example.invalid \
  --auth-user admin \
  --auth-password 'replace-with-admin-password'
```

云端验收中的 `auth_fail_closed` 必须通过。
"""
    (target_root / "DEPLOY_README.zh-CN.md").write_text(text, encoding="utf-8")


def _write_manifest(
    target_root: Path,
    version: str,
    sha_full: str,
    *,
    build_id: str,
    frontend_dist_sha256: str,
    runtime_payload_sha256: str,
) -> None:
    current_files = sum(1 for path in target_root.rglob("*") if path.is_file())
    manifest = {
        "schema_version": 2,
        "name": "localization-workflow-studio",
        "artifact_kind": "universal",
        "version": version,
        "git_sha": sha_full[:12],
        "git_sha_full": sha_full,
        "source_git_dirty": False,
        "source_state": "clean_git_commit",
        "build_id": build_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "file_count": current_files + 2,
        "frontend_configuration": "runtime_profile",
        "frontend_dist_sha256": frontend_dist_sha256,
        "runtime_payload_sha256": runtime_payload_sha256,
        "supported_runtime_profiles": SUPPORTED_RUNTIME_PROFILES,
        "contains_frontend_dist": True,
        "contains_settings_local": False,
        "excluded_runtime_data": True,
        "archive_verified": True,
        "package_policy": "universal_runtime_allowlist",
        "credential_scan": "source_and_archive_text",
        "entrypoints": ENTRYPOINTS,
    }
    (target_root / "PACKAGE_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_sha256sums(target_root: Path) -> None:
    rows = []
    for path in sorted(target_root.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            relative = path.relative_to(target_root).as_posix()
            rows.append(f"{_sha256(path)}  {relative}")
    (target_root / "SHA256SUMS.txt").write_text(
        "\n".join(rows) + "\n",
        encoding="utf-8",
    )


def _relative_archive_files(archive: zipfile.ZipFile) -> tuple[str, dict[str, str]]:
    infos = [info for info in archive.infolist() if not info.is_dir()]
    if not infos:
        raise RuntimeError("release archive is empty")
    roots = {info.filename.split("/", 1)[0] for info in infos}
    if len(roots) != 1:
        raise RuntimeError("release archive must contain exactly one package root")
    package_root = next(iter(roots))
    root_prefix = package_root + "/"
    relative: dict[str, str] = {}
    for info in infos:
        if stat.S_ISLNK(info.external_attr >> 16):
            raise RuntimeError(f"release archive contains symlink: {info.filename}")
        member = info.filename.removeprefix(root_prefix)
        member_path = Path(member)
        if not member or member_path.is_absolute() or ".." in member_path.parts:
            raise RuntimeError(f"unsafe archive member: {info.filename}")
        if member in relative:
            raise RuntimeError(f"duplicate archive member: {member}")
        relative[member] = info.filename
    return package_root, relative


def _verify_manifest_identity(manifest: dict[str, object], package_root: str) -> None:
    sha_full = manifest.get("git_sha_full")
    sha = manifest.get("git_sha")
    if not isinstance(sha_full, str) or not re.fullmatch(r"[0-9a-f]{40}", sha_full):
        raise RuntimeError("manifest git_sha_full must be 40 lowercase hex characters")
    if sha != sha_full[:12]:
        raise RuntimeError("manifest short and full Git SHA values do not match")
    expected_root = f"localization-workflow-studio-v{manifest.get('version')}-g{sha}-universal"
    if package_root != expected_root:
        raise RuntimeError("archive root does not match manifest identity")
    expected = {
        "schema_version": 2,
        "name": "localization-workflow-studio",
        "artifact_kind": "universal",
        "source_git_dirty": False,
        "source_state": "clean_git_commit",
        "build_id": package_root,
        "frontend_configuration": "runtime_profile",
        "supported_runtime_profiles": SUPPORTED_RUNTIME_PROFILES,
        "contains_frontend_dist": True,
        "contains_settings_local": False,
        "excluded_runtime_data": True,
        "archive_verified": True,
        "package_policy": "universal_runtime_allowlist",
        "credential_scan": "source_and_archive_text",
        "entrypoints": ENTRYPOINTS,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise RuntimeError(f"manifest identity mismatch for {key}")


def _verify_archive(zip_path: Path) -> None:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise RuntimeError(f"corrupt archive member: {bad_member}")

            package_root, relative = _relative_archive_files(archive)
            if zip_path.name != f"{package_root}.zip":
                raise RuntimeError("archive filename does not match its package root")
            missing = sorted(REQUIRED_MEMBERS - set(relative))
            if missing:
                raise RuntimeError("release archive is missing required members: " + ", ".join(missing))
            forbidden = sorted(member for member in relative if _is_forbidden_relative(Path(member)))
            if forbidden:
                raise RuntimeError("release archive contains forbidden members: " + ", ".join(forbidden))
            unexpected = sorted(member for member in relative if not _is_allowed_archive_member(Path(member)))
            if unexpected:
                raise RuntimeError("release archive contains members outside the universal allowlist: " + ", ".join(unexpected))
            for member, archive_name in relative.items():
                if _is_text_candidate(Path(member)):
                    _scan_text_bytes(
                        archive.read(archive_name),
                        origin=f"archive:{member}",
                    )

            manifest = json.loads(archive.read(relative["PACKAGE_MANIFEST.json"]))
            _verify_manifest_identity(manifest, package_root)

            rows = archive.read(relative["SHA256SUMS.txt"]).decode("utf-8").splitlines()
            expected_hashes: dict[str, str] = {}
            for row in rows:
                try:
                    digest, member = row.split("  ", 1)
                except ValueError as exc:
                    raise RuntimeError(f"invalid SHA256SUMS row: {row!r}") from exc
                if member in expected_hashes:
                    raise RuntimeError(f"duplicate SHA256SUMS member: {member}")
                expected_hashes[member] = digest
            expected_members = set(relative) - {"SHA256SUMS.txt"}
            if set(expected_hashes) != expected_members:
                raise RuntimeError("SHA256SUMS member set does not match the archive")
            for member, expected in expected_hashes.items():
                actual = hashlib.sha256(archive.read(relative[member])).hexdigest()
                if actual != expected:
                    raise RuntimeError(f"SHA-256 mismatch for {member}")

            with tempfile.TemporaryDirectory(prefix="lws-release-readback-") as temp_dir:
                extracted_root = Path(temp_dir) / package_root
                for member, archive_name in relative.items():
                    target = extracted_root / Path(member)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(archive_name))
                frontend_root = extracted_root / "frontend" / "dist"
                frontend_digest = _tree_sha256(
                    frontend_root,
                    (path for path in frontend_root.rglob("*") if path.is_file()),
                )
                runtime_digest = _tree_sha256(
                    extracted_root,
                    (path for path in extracted_root.rglob("*") if path.is_file() and path.relative_to(extracted_root).as_posix() not in GENERATED_MEMBERS),
                )
                if manifest.get("frontend_dist_sha256") != frontend_digest:
                    raise RuntimeError("frontend dist tree digest mismatch")
                if manifest.get("runtime_payload_sha256") != runtime_digest:
                    raise RuntimeError("runtime payload tree digest mismatch")
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"release archive is not readable: {zip_path}") from exc


def _validate_staging(staging_root: Path) -> None:
    members = {path.relative_to(staging_root).as_posix() for path in staging_root.rglob("*") if path.is_file()}
    missing = sorted(REQUIRED_MEMBERS - members)
    if missing:
        raise RuntimeError("staged release is missing required members: " + ", ".join(missing))
    forbidden = sorted(member for member in members if _is_forbidden_relative(Path(member)))
    if forbidden:
        raise RuntimeError("staged release contains forbidden members: " + ", ".join(forbidden))
    unexpected = sorted(member for member in members if not _is_allowed_archive_member(Path(member)))
    if unexpected:
        raise RuntimeError("staged release contains members outside the universal allowlist: " + ", ".join(unexpected))


def build(output_dir: Path, *, rebuild_frontend: bool = True) -> Path:
    if _git_dirty():
        raise RuntimeError("refusing to package a dirty or untracked source tree; commit or stash it first")

    version = _version()
    sha_full = _git_sha_full()
    if not re.fullmatch(r"[0-9a-f]{40}", sha_full):
        raise RuntimeError("source Git SHA must be 40 lowercase hex characters")
    if rebuild_frontend:
        _build_frontend()
    _assert_required_source_members()

    root_name = f"localization-workflow-studio-v{version}-g{sha_full[:12]}-universal"
    staging_parent = ROOT.parent / "release-staging"
    staging_root = staging_parent / root_name
    output_dir = output_dir.resolve()
    if staging_root.exists():
        shutil.rmtree(staging_root)
    staging_root.mkdir(parents=True, exist_ok=True)

    try:
        for source in _iter_files(excluded_roots=(output_dir, staging_parent)):
            relative = source.relative_to(ROOT)
            target = staging_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        frontend_root = staging_root / "frontend" / "dist"
        frontend_digest = _tree_sha256(
            frontend_root,
            (path for path in frontend_root.rglob("*") if path.is_file()),
        )
        runtime_digest = _tree_sha256(
            staging_root,
            (path for path in staging_root.rglob("*") if path.is_file()),
        )
        _write_install_doc(staging_root, version, sha_full[:12])
        _write_manifest(
            staging_root,
            version,
            sha_full,
            build_id=root_name,
            frontend_dist_sha256=frontend_digest,
            runtime_payload_sha256=runtime_digest,
        )
        _write_sha256sums(staging_root)
        _validate_staging(staging_root)

        output_dir.mkdir(parents=True, exist_ok=True)
        zip_path = output_dir / f"{root_name}.zip"
        sidecar_path = zip_path.with_name(f"{zip_path.name}.sha256")
        zip_path.unlink(missing_ok=True)
        sidecar_path.unlink(missing_ok=True)
        with zipfile.ZipFile(
            zip_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            strict_timestamps=False,
        ) as archive:
            for path in sorted(staging_root.rglob("*")):
                if path.is_file():
                    archive.write(
                        path,
                        path.relative_to(staging_root.parent).as_posix(),
                    )

        try:
            _verify_archive(zip_path)
            _write_archive_sidecar(zip_path)
        except Exception:
            zip_path.unlink(missing_ok=True)
            sidecar_path.unlink(missing_ok=True)
            raise
        return zip_path
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=("Build and read back one sanitized, runtime-configured universal Localization Workflow Studio release zip."))
    parser.add_argument("--output-dir", default=str(Path.home() / "Desktop"))
    parser.add_argument(
        "--no-rebuild-frontend",
        action="store_true",
        help="Package the existing frontend/dist without rebuilding it.",
    )
    args = parser.parse_args()
    zip_path = build(
        Path(args.output_dir),
        rebuild_frontend=not args.no_rebuild_frontend,
    )
    print(zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
