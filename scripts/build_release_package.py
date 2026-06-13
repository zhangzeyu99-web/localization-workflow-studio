from __future__ import annotations

import argparse
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


def _write_install_doc(target_root: Path, version: str, sha: str) -> None:
    text = f"""# 本地化工作台安装说明

版本：{version}
提交：{sha}
打包时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 包内包含

- backend/：FastAPI 后端源码。
- frontend/：前端源码；如果打包前已构建，也包含 frontend/dist/。
- workflow/：内置术语提取与本地化处理工作流。
- scripts/：Windows、本地、Linux 启动与线上自检脚本。
- docs/、examples/：文档和示例。
- settings.example.json：配置样例，不包含真实 API key。

## 包内不包含

- .git、node_modules、Python 虚拟环境。
- lws-data、SQLite 数据库、上传文件、运行日志、交付产物。
- settings.local.json、API key、真实项目内容。

## Linux / 线上部署

推荐目录：

```bash
/data/web/lwstudio
```

安装依赖：

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

启动后端：

```bash
chmod +x ./start-lws.sh
APP_HOME=/data/web/lwstudio \\
LWS_DATA_ROOT=/data/web/lwstudio/lws-data \\
LWS_DEPLOYMENT_MODE=cloud \\
LWS_MAX_UPLOAD_MB=1024 \\
./start-lws.sh
```

Nginx：

```nginx
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
```

上线自检：

```bash
python3.11 scripts/deployment_check.py --base-url https://your-domain.example.com --require-cloud --require-provider
python3.11 scripts/stability_check.py --base-url https://your-domain.example.com
```

关键验收：

- /api/version 能返回当前版本和提交号。
- /api/health 的 deployment_mode 是 cloud。
- data_root_writable、uploads_writable、database.connected 都是 true。
- provider_configured 是 true。
- 上传自检可读，生成 sha256 和 preview。

## Windows 本地启动

```powershell
cd D:\\apps\\localization-workflow-studio
python -m pip install -r backend\\requirements.txt
python -m pip install -r workflow\\glossary\\requirements.txt
python -m pip install -r workflow\\localization\\requirements.txt
cd frontend
npm install
npm run build
cd ..
.\\scripts\\start-workbench.ps1 -Lan
```

## 配置提醒

- 正式翻译、项目 AI 分析、公告 AI 翻译需要在网页右上角“设置”配置可用 API。
- 私有配置写入 LWS_DATA_ROOT/settings.local.json，不进入仓库和发布包。
- 不使用 Google Translate、deep_translator、googletrans 或浏览器机翻。
- 线上第一版固定单后端实例、单 worker；不要用多个 uvicorn worker 直接共享 SQLite。
"""
    (target_root / "INSTALL.zh-CN.md").write_text(text, encoding="utf-8")


def _write_manifest(target_root: Path, version: str, sha: str, files: list[Path]) -> None:
    manifest = {
        "name": "localization-workflow-studio",
        "version": version,
        "git_sha": sha,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "file_count": len(files),
        "contains_frontend_dist": (target_root / "frontend" / "dist" / "index.html").exists(),
        "excluded_runtime_data": True,
        "entrypoints": {
            "linux_backend": "start-lws.sh",
            "windows_local": "start-workbench.cmd",
            "deployment_check": "scripts/deployment_check.py",
            "stability_check": "scripts/stability_check.py",
        },
    }
    (target_root / "PACKAGE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def build(output_dir: Path, package_label: str) -> Path:
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

    _write_install_doc(staging_root, version, sha)
    copied.append(Path("INSTALL.zh-CN.md"))
    _write_manifest(staging_root, version, sha, copied)
    copied.append(Path("PACKAGE_MANIFEST.json"))

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
    parser.add_argument("--label", default="本地化工作台")
    args = parser.parse_args()
    zip_path = build(Path(args.output_dir), args.label)
    print(zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
