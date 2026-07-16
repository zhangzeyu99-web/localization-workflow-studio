from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
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
    "start-lws.sh",
    "backend/app/main.py",
    "scripts/create_admin.py",
    "scripts/deployment_auth.py",
    "settings.example.json",
}
REQUIRED_MEMBERS = REQUIRED_SOURCE_MEMBERS | {
    "ONLINE_DEPLOY_README.zh-CN.md",
    "PACKAGE_MANIFEST.json",
    "SHA256SUMS.txt",
}
GENERATED_MEMBERS = {
    "ONLINE_DEPLOY_README.zh-CN.md",
    "PACKAGE_MANIFEST.json",
    "SHA256SUMS.txt",
}

TOP_LEVEL_RELEASE_FILES = {
    "VERSION",
    "check.py",
    "settings.example.json",
    "start-lws.sh",
}
DEPLOY_RELEASE_FILES = {
    "deploy/lws.env.example",
    "deploy/lws.service",
    "deploy/nginx.conf",
}
SCRIPT_RELEASE_FILES = {
    "scripts/create_admin.py",
    "scripts/deployment_auth.py",
    "scripts/deployment_check.py",
    "scripts/stability_check.py",
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
        re.compile(
            r"(?<![A-Za-z0-9])((?:sk-ant-|sk-)[A-Za-z0-9._-]{20,})"
        ),
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
        re.compile(
            r"(?<![A-Za-z0-9])((?:ghp_|github_pat_|xox[baprs]-|AIza)[A-Za-z0-9._-]{16,})"
        ),
    ),
)
PLACEHOLDER_MARKERS = {
    "changeme",
    "dummy",
    "example",
    "not-a-real",
    "placeholder",
    "replace-me",
    "sample",
    "test-key",
    "your-api-key",
    "your_api_key",
}


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


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
    except OSError:
        return "unknown"


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
    return (
        relative.suffix.lower() in TEXT_EXTENSIONS
        or name == "version"
        or name.endswith(".env.example")
    )


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
                raise RuntimeError(
                    f"secret-like credential or token detected in {origin} ({label})"
                )


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


def _write_archive_sidecar(zip_path: Path) -> Path:
    sidecar = zip_path.with_name(f"{zip_path.name}.sha256")
    expected = _sha256(zip_path)
    sidecar.write_text(f"{expected}  {zip_path.name}\n", encoding="utf-8")
    digest, filename = sidecar.read_text(encoding="utf-8").strip().split("  ", 1)
    if filename != zip_path.name or digest != expected:
        raise RuntimeError("release archive SHA-256 sidecar verification failed")
    return sidecar


def _build_frontend(*, hide_settings: bool) -> None:
    env = dict(os.environ)
    if hide_settings:
        env["LWS_HIDE_SETTINGS"] = "1"
    else:
        env.pop("LWS_HIDE_SETTINGS", None)
    subprocess.check_call(
        ["npm", "run", "build"],
        cwd=ROOT / "frontend",
        env=env,
        shell=(os.name == "nt"),
    )


def _assert_required_source_members() -> None:
    missing = sorted(
        member for member in REQUIRED_SOURCE_MEMBERS if not (ROOT / member).is_file()
    )
    if missing:
        raise RuntimeError("release package is missing required source members: " + ", ".join(missing))


def _write_install_doc(target_root: Path, version: str, sha: str) -> None:
    text = f"""# 本地化工作台线上部署说明

版本：{version}
源码提交：{sha}
打包时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 包内内容

- `backend/`：FastAPI 后端及依赖清单。
- `frontend/dist/`：已经构建完成、可直接由 Nginx 托管的前端文件。
- `workflow/glossary/`、`workflow/localization/`：运行所需代码、模板和回归规则。
- `deploy/lws.service`：systemd 服务模板。
- `deploy/nginx.conf`：Nginx 反向代理与缓存策略模板。
- `deploy/lws.env.example`：非敏感环境变量模板。
- `scripts/create_admin.py`：首次上线创建或重置管理员的命令行入口。
- `scripts/deployment_auth.py`：部署检查与稳定性检查共用的登录辅助模块。
- `start-lws.sh`：后端启动入口。
- `settings.example.json`：服务端 API 配置模板，不含密钥。
- `PACKAGE_MANIFEST.json`：包来源与安全状态。
- `SHA256SUMS.txt`：除校验清单自身外，每个包成员的 SHA-256。

包内绝不包含 `settings.local.json`、`.env`、API 密钥、私有交接文档或运行期数据。
仓库文档、测试/E2E、前端源码及非生产脚本也不在发布白名单内。

## 目录与配置

发布代码和运行数据必须分离。示例：

```bash
export APP_HOME=/srv/lwstudio/current
export LWS_DATA_ROOT=/srv/lwstudio/data
sudo install -d -m 750 -o lwstudio -g lwstudio "$LWS_DATA_ROOT"
sudo -u lwstudio cp "$APP_HOME/settings.example.json" "$LWS_DATA_ROOT/settings.local.json"
sudo -u lwstudio chmod 600 "$LWS_DATA_ROOT/settings.local.json"
```

随后只在独立的 `$LWS_DATA_ROOT/settings.local.json` 中填写线上 API 地址与密钥。不要把该文件放回发布目录。

## 安装后端依赖

前端已经在可信构建环境中完成构建；服务器不需要 Node.js，也不要重新构建前端。

```bash
cd /srv/lwstudio/current
python3.11 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
.venv/bin/python -m pip install -r workflow/glossary/requirements.txt
.venv/bin/python -m pip install -r workflow/localization/requirements.txt
```

## 初始化管理员

cloud 模式默认强制登录。首次启动且用户表为空时，在受限权限的
`/etc/lwstudio/lws.env` 中临时配置：

```bash
LWS_AUTH_MODE=required
LWS_ADMIN_USER=admin
LWS_ADMIN_PASSWORD=replace-with-strong-bootstrap-password
```

也可以在启动服务前直接创建或重置管理员：

```bash
LWS_DATA_ROOT=/srv/lwstudio/data \
LWS_ADMIN_PASSWORD='replace-with-strong-bootstrap-password' \
.venv/bin/python scripts/create_admin.py --username admin
```

初始管理员首次登录后必须修改密码。引导完成后，从环境文件移除
`LWS_ADMIN_PASSWORD` 并重启服务。

## 启动与接入

1. 按实际路径调整 `deploy/lws.env.example`，安装为 systemd 的 EnvironmentFile。
2. 安装并调整 `deploy/lws.service`，启动后端服务。
3. 安装并调整 `deploy/nginx.conf`，让 `/api/` 反代后端，让其余请求读取 `frontend/dist/`。
4. 确认 CDN 或上游代理不会把 `/api/` 和 HTML 改写成长缓存。

部署后执行：

```bash
release_sha="$(python3.11 -c 'import json; print(json.load(open("PACKAGE_MANIFEST.json", encoding="utf-8"))["git_sha"])')"
python3.11 check.py \
  --base-url https://ai-lwstudio.gz4399.com \
  --require-cloud \
  --require-provider \
  --expect-version {version} \
  --expect-git-sha "$release_sha" \
  --check-frontend-assets frontend/dist/assets \
  --auth-user admin \
  --auth-password '管理员密码'
python3.11 scripts/stability_check.py \
  --base-url https://ai-lwstudio.gz4399.com \
  --auth-user admin \
  --auth-password '管理员密码'
```

部署检查中的 `auth_fail_closed` 必须为 `ok=true`，确认未登录访问核心
业务 API 会返回 401；随后还必须用管理员会话通过上传可读性探针。
"""
    (target_root / "ONLINE_DEPLOY_README.zh-CN.md").write_text(text, encoding="utf-8")


def _write_manifest(
    target_root: Path,
    version: str,
    sha: str,
    *,
    dirty: bool,
    hide_settings: bool,
) -> None:
    current_files = sum(1 for path in target_root.rglob("*") if path.is_file())
    manifest = {
        "name": "localization-workflow-studio",
        "version": version,
        "git_sha": sha,
        "source_git_dirty": dirty,
        "source_state": "dirty_working_tree_allowed" if dirty else "clean_git_commit",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "file_count": current_files + 2,
        "contains_frontend_dist": True,
        "contains_settings_local": False,
        "frontend_settings_button_hidden": hide_settings,
        "excluded_runtime_data": True,
        "archive_verified": True,
        "package_policy": "production_runtime_allowlist",
        "credential_scan": "source_and_archive_text",
        "entrypoints": {
            "linux_backend": "start-lws.sh",
            "backend_app": "backend/app/main.py",
            "create_admin": "scripts/create_admin.py",
            "deployment_check": "check.py",
            "stability_check": "scripts/stability_check.py",
        },
    }
    (target_root / "PACKAGE_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_sha256sums(target_root: Path) -> None:
    rows = []
    for path in sorted(target_root.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            relative = path.relative_to(target_root).as_posix()
            rows.append(f"{_sha256(path)}  {relative}")
    (target_root / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _relative_archive_files(archive: zipfile.ZipFile) -> dict[str, str]:
    file_names = [name for name in archive.namelist() if not name.endswith("/")]
    if not file_names:
        raise RuntimeError("release archive is empty")
    roots = {name.split("/", 1)[0] for name in file_names}
    if len(roots) != 1:
        raise RuntimeError("release archive must contain exactly one package root")
    root = next(iter(roots)) + "/"
    relative: dict[str, str] = {}
    for name in file_names:
        member = name.removeprefix(root)
        member_path = Path(member)
        if not member or member_path.is_absolute() or ".." in member_path.parts:
            raise RuntimeError(f"unsafe archive member: {name}")
        if member in relative:
            raise RuntimeError(f"duplicate archive member: {member}")
        relative[member] = name
    return relative


def _verify_archive(zip_path: Path, *, dirty: bool) -> None:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise RuntimeError(f"corrupt archive member: {bad_member}")

            relative = _relative_archive_files(archive)
            missing = sorted(REQUIRED_MEMBERS - set(relative))
            if missing:
                raise RuntimeError("release archive is missing required members: " + ", ".join(missing))
            forbidden = sorted(
                member for member in relative if _is_forbidden_relative(Path(member))
            )
            if forbidden:
                raise RuntimeError("release archive contains forbidden members: " + ", ".join(forbidden))
            unexpected = sorted(
                member for member in relative if not _is_allowed_archive_member(Path(member))
            )
            if unexpected:
                raise RuntimeError(
                    "release archive contains members outside the production allowlist: "
                    + ", ".join(unexpected)
                )
            for member, archive_name in relative.items():
                member_path = Path(member)
                if _is_text_candidate(member_path):
                    _scan_text_bytes(
                        archive.read(archive_name),
                        origin=f"archive:{member}",
                    )

            manifest = json.loads(archive.read(relative["PACKAGE_MANIFEST.json"]))
            if manifest.get("contains_settings_local") is not False:
                raise RuntimeError("manifest must state that settings.local.json is absent")
            if manifest.get("archive_verified") is not True:
                raise RuntimeError("manifest is missing archive verification state")
            if manifest.get("source_git_dirty") is not dirty:
                raise RuntimeError("manifest dirty state does not match the source tree")

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
                missing_hashes = sorted(expected_members - set(expected_hashes))
                extra_hashes = sorted(set(expected_hashes) - expected_members)
                raise RuntimeError(
                    f"SHA256SUMS member mismatch; missing={missing_hashes}, extra={extra_hashes}"
                )
            for member, expected in expected_hashes.items():
                actual = hashlib.sha256(archive.read(relative[member])).hexdigest()
                if actual != expected:
                    raise RuntimeError(f"SHA-256 mismatch for {member}")
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"release archive is not readable: {zip_path}") from exc


def build(
    output_dir: Path,
    package_label: str,
    *,
    hide_settings: bool = False,
    rebuild_frontend: bool = True,
    allow_dirty: bool = False,
) -> Path:
    dirty = _git_dirty()
    if dirty and not allow_dirty:
        raise RuntimeError(
            "refusing to package a dirty or untracked source tree; commit/stash it or pass --allow-dirty explicitly"
        )

    version = _version()
    sha = _git_sha()
    if rebuild_frontend:
        _build_frontend(hide_settings=hide_settings)
    _assert_required_source_members()

    stamp = datetime.now().strftime("%Y%m%d")
    root_name = f"localization-workflow-studio-v{version}-{stamp}"
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

        _write_install_doc(staging_root, version, sha)
        _write_manifest(
            staging_root,
            version,
            sha,
            dirty=dirty,
            hide_settings=hide_settings,
        )
        _write_sha256sums(staging_root)

        staged_members = {
            path.relative_to(staging_root).as_posix()
            for path in staging_root.rglob("*")
            if path.is_file()
        }
        missing = sorted(REQUIRED_MEMBERS - staged_members)
        if missing:
            raise RuntimeError("staged release is missing required members: " + ", ".join(missing))
        forbidden = sorted(
            member for member in staged_members if _is_forbidden_relative(Path(member))
        )
        if forbidden:
            raise RuntimeError("staged release contains forbidden members: " + ", ".join(forbidden))
        unexpected = sorted(
            member for member in staged_members if not _is_allowed_archive_member(Path(member))
        )
        if unexpected:
            raise RuntimeError(
                "staged release contains members outside the production allowlist: "
                + ", ".join(unexpected)
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        zip_path = output_dir / f"{package_label}-v{version}-{stamp}.zip"
        sidecar_path = zip_path.with_name(f"{zip_path.name}.sha256")
        if zip_path.exists():
            zip_path.unlink()
        sidecar_path.unlink(missing_ok=True)
        with zipfile.ZipFile(
            zip_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            strict_timestamps=False,
        ) as archive:
            for path in sorted(staging_root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging_root.parent).as_posix())

        try:
            _verify_archive(zip_path, dirty=dirty)
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
    parser = argparse.ArgumentParser(
        description="Build and read back a sanitized Localization Workflow Studio release zip."
    )
    parser.add_argument("--output-dir", default=str(Path.home() / "Desktop"))
    parser.add_argument("--label", default="本地化工作台线上部署包")
    parser.add_argument(
        "--hide-settings",
        action="store_true",
        help="Build the frontend with the settings button hidden (LWS_HIDE_SETTINGS=1).",
    )
    parser.add_argument(
        "--no-rebuild-frontend",
        action="store_true",
        help="Package the existing frontend/dist without rebuilding it.",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Explicitly package a dirty working tree and mark that state in the manifest.",
    )
    args = parser.parse_args()
    zip_path = build(
        Path(args.output_dir),
        args.label,
        hide_settings=args.hide_settings,
        rebuild_frontend=not args.no_rebuild_frontend,
        allow_dirty=args.allow_dirty,
    )
    print(zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
