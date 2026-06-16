from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".github",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "playwright-report",
    "test-results",
    ".local-logs",
    "logs",
    "tmp",
    ".tmp",
    "lws-data",
    "localization-workflow-studio-data",
    "uploads",
    "runs",
    "projects",
    "artifacts",
    "outputs",
    "release_archives",
}
DEFAULT_EXCLUDE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".log",
    ".tmp",
    ".bak",
    ".sqlite",
    ".sqlite3",
    ".db",
}
DEFAULT_EXCLUDE_NAMES = {
    "settings.local.json",
    ".env",
    "api_key",
    "api_key.txt",
}


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def _git_dirty() -> bool:
    try:
        out = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
        ignored = []
        for line in out.splitlines():
            path = line[3:] if len(line) > 3 else line
            if path in {"settings.local.json"} or path.startswith("release_archives/"):
                continue
            ignored.append(line)
        return bool(ignored)
    except Exception:
        return True


def _version() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def _should_skip(path: Path) -> bool:
    rel_parts = path.relative_to(ROOT).parts
    if any(part in DEFAULT_EXCLUDE_DIRS for part in rel_parts):
        return True
    name = path.name
    if name in DEFAULT_EXCLUDE_NAMES:
        return True
    if name.endswith(".local"):
        return True
    if path.suffix.lower() in DEFAULT_EXCLUDE_SUFFIXES:
        return True
    if "secret" in name.lower():
        return True
    return False


def _iter_files() -> Iterable[Path]:
    for path in ROOT.rglob("*"):
        if path.is_dir() or _should_skip(path):
            continue
        yield path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_install_doc(target_root: Path, version: str, sha: str, *, includes_settings: bool) -> None:
    settings_note = (
        "本包已包含 settings.local.json。部署时请复制到 $LWS_DATA_ROOT/settings.local.json，并确认该文件只保留在服务器数据目录，不提交到 Git。"
        if includes_settings
        else "本包不包含 settings.local.json。请基于 settings.example.json 创建 $LWS_DATA_ROOT/settings.local.json。"
    )
    text = f"""# 本地化工作台线上部署说明

版本：{version}
源码提交：{sha}
打包时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 包内包含

- `backend/`：FastAPI 后端。
- `frontend/`：前端源码和已构建的 `frontend/dist/`。
- `workflow/`：术语提取、翻译、QA、公告处理等本地工作流。
- `scripts/`：部署检查、稳定性检查和打包脚本。
- `check.py`：线上健康检查入口。
- `settings.example.json`：配置模板。
- `settings.local.json`：仅在显式指定时打入包内，用于服务器配置。
- `PACKAGE_MANIFEST.json`：包清单。
- `SHA256SUMS.txt`：文件校验清单。

## 包内不包含

- `.git`、`.github`、`node_modules`、Python 虚拟环境和缓存。
- SQLite 数据库、上传文件、运行产物、项目数据和日志。
- 本机临时文件、release_archives 和历史压缩包。

## 配置

{settings_note}

推荐环境变量：

```bash
export APP_HOME=/data/web/lwstudio
export LWS_DATA_ROOT=/data/web/lwstudio/lws-data
export LWS_DEPLOYMENT_MODE=cloud
export LWS_MAX_UPLOAD_MB=1024
export LWS_CORS_ORIGINS=https://ai-lwstudio.gz4399.com
```

推荐目录：

```bash
/data/web/lwstudio
/data/web/lwstudio/lws-data
```

## 安装依赖

```bash
cd /data/web/lwstudio
python3.11 -m pip install -r backend/requirements.txt
python3.11 -m pip install -r workflow/glossary/requirements.txt
python3.11 -m pip install -r workflow/localization/requirements.txt

cd frontend
npm install
npm run build
cd ..
```

如果包内已有 `frontend/dist/`，仍建议在目标服务器上重新执行一次 `npm run build`，确认 Node 环境兼容。

## 启动后端

```bash
chmod +x ./start-lws.sh
APP_HOME=/data/web/lwstudio \
LWS_DATA_ROOT=/data/web/lwstudio/lws-data \
LWS_DEPLOYMENT_MODE=cloud \
LWS_MAX_UPLOAD_MB=1024 \
./start-lws.sh
```

生产环境建议只启动一个后端进程。当前任务队列使用 SQLite lease，本轮不建议多 worker 并发启动同一数据目录。

## Nginx 示例

```nginx
server {{
  listen 80;
  server_name ai-lwstudio.gz4399.com;

  root /data/web/lwstudio/frontend/dist;
  client_max_body_size 1024m;

  location / {{
    try_files $uri $uri/ /index.html;
  }}

  location /api/ {{
    proxy_pass http://127.0.0.1:8082;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
  }}
}}
```

## 部署后检查

```bash
python3.11 check.py --base-url https://ai-lwstudio.gz4399.com --require-cloud --require-provider --expect-version {version}
python3.11 scripts/stability_check.py --base-url https://ai-lwstudio.gz4399.com
```

必须确认：

- `/api/version` 返回 `{version}`。
- 前端右下角显示 `v{version}`。
- `/api/health` 返回 `deployment_mode=cloud`。
- data root、uploads、DB 路径指向服务器数据目录。
- Provider 已配置且可联通。
- 静态资源 hash 与当前包一致。

## 运行边界

- AI 只通过已配置 Provider 调用；工作台本地负责拆批、限流、断点续跑、QA、回填和交付。
- 长任务会落盘保存批次状态。刷新页面后可继续查看进度，后端重启后可恢复未完成任务。
- 不接入外部机翻或在线翻译聚合器。
"""
    (target_root / "ONLINE_DEPLOY_README.zh-CN.md").write_text(text, encoding="utf-8")

def _write_manifest(target_root: Path, version: str, sha: str, files: list[Path], *, includes_settings: bool) -> None:
    manifest = {
        "name": "localization-workflow-studio",
        "version": version,
        "git_sha": sha,
        "source_git_dirty": _git_dirty(),
        "source_state": "working_tree" if _git_dirty() else "clean_git_commit",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "file_count": len(files),
        "contains_frontend_dist": (target_root / "frontend" / "dist" / "index.html").exists(),
        "contains_settings_local": includes_settings,
        "excluded_runtime_data": True,
        "entrypoints": {
            "linux_backend": "start-lws.sh",
            "windows_local": "start-workbench.cmd",
            "deployment_check": "check.py",
            "stability_check": "scripts/stability_check.py",
        },
    }
    (target_root / "PACKAGE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_sha256sums(target_root: Path) -> None:
    rows: list[str] = []
    for path in sorted(target_root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(target_root).as_posix()
            rows.append(f"{_sha256(path)}  {rel}")
    (target_root / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def build(output_dir: Path, package_label: str, settings_file: Path | None = None) -> Path:
    version = _version()
    sha = _git_sha()
    stamp = datetime.now().strftime("%Y%m%d")
    root_name = f"localization-workflow-studio-v{version}-{stamp}"
    staging_root = ROOT.parent / "release-staging" / root_name
    if staging_root.exists():
        shutil.rmtree(staging_root)
    staging_root.mkdir(parents=True, exist_ok=True)

    copied: list[Path] = []
    for source in _iter_files():
        relative = source.relative_to(ROOT)
        target = staging_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(relative)

    includes_settings = False
    if settings_file:
        resolved = settings_file.resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"settings file not found: {resolved}")
        shutil.copy2(resolved, staging_root / "settings.local.json")
        copied.append(Path("settings.local.json"))
        includes_settings = True

    _write_install_doc(staging_root, version, sha, includes_settings=includes_settings)
    copied.append(Path("ONLINE_DEPLOY_README.zh-CN.md"))
    _write_manifest(staging_root, version, sha, copied, includes_settings=includes_settings)
    copied.append(Path("PACKAGE_MANIFEST.json"))
    _write_sha256sums(staging_root)
    copied.append(Path("SHA256SUMS.txt"))

    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{package_label}-v{version}-{stamp}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in staging_root.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(staging_root.parent).as_posix())
    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a sanitized release zip for Localization Workflow Studio.")
    parser.add_argument("--output-dir", default=str(Path.home() / "Desktop"))
    parser.add_argument("--label", default="本地化工作台线上部署包")
    parser.add_argument("--settings-file", default="", help="Optional settings.local.json to include in the package root.")
    args = parser.parse_args()
    settings = Path(args.settings_file) if args.settings_file else None
    zip_path = build(Path(args.output_dir), args.label, settings)
    print(zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
