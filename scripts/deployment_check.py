from __future__ import annotations

import argparse
import json
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import httpx

from deployment_auth import (
    AuthLoginError,
    PasswordChangeRequiredError,
    login,
    response_error_detail,
    unauthenticated_probe_status,
)


def _print_step(name: str, ok: bool, payload: Any) -> None:
    print(json.dumps({"step": name, "ok": ok, "result": payload}, ensure_ascii=False))


def _expected_version(value: str | None = None) -> str:
    if value:
        return value.strip()
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _get_json_response(client: httpx.Client, base_url: str, path: str) -> tuple[dict[str, Any], httpx.Response]:
    response = client.get(f"{base_url.rstrip('/')}{path}")
    response.raise_for_status()
    return response.json(), response


def _has_cache_control(response: httpx.Response, *required: str) -> bool:
    directives = {
        part.strip().partition("=")[0].lower()
        for part in response.headers.get("Cache-Control", "").split(",")
        if part.strip()
    }
    return any(item.lower() in directives for item in required)


class _PublicAssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.paths: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        _ = tag
        for name, value in attrs:
            if name not in {"src", "href"} or not value:
                continue
            parsed = urlsplit(value)
            if not parsed.scheme and not parsed.netloc and parsed.path.startswith("/assets/") and parsed.path.rsplit("/", 1)[-1]:
                self.paths.add(parsed.path)


def public_asset_paths(html: str) -> list[str]:
    parser = _PublicAssetParser()
    parser.feed(html)
    parser.close()
    return sorted(parser.paths)


def local_frontend_assets(assets_dir: Path) -> list[str]:
    return sorted(path.name for path in assets_dir.glob("*") if path.is_file())


def compare_frontend_assets(reported: list[str] | None, local: list[str]) -> dict[str, Any]:
    reported_set = {str(item) for item in (reported or [])}
    local_set = set(local)
    missing_on_server = sorted(local_set - reported_set)
    missing_locally = sorted(reported_set - local_set)
    ok = bool(local_set) and not missing_on_server and not missing_locally
    result: dict[str, Any] = {
        "ok": ok,
        "reported_count": len(reported_set),
        "local_count": len(local_set),
        "missing_on_server": missing_on_server,
        "missing_locally": missing_locally,
    }
    if not local_set:
        result["error"] = "local frontend/dist/assets is empty or missing; run the frontend build first"
    elif not ok:
        result["error"] = (
            "backend-reported frontend assets do not match local dist assets; "
            "the deployed backend is probably serving a different frontend build"
        )
    return result


def check_public_assets(
    client: httpx.Client,
    base_url: str,
    paths: list[str],
    reported: list[str] | None,
) -> dict[str, Any]:
    reported_set = {str(item) for item in (reported or [])}
    public_names = sorted({path.rsplit("/", 1)[-1] for path in paths})
    missing_from_version = sorted(set(public_names) - reported_set)
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    if not paths:
        errors.append("public root HTML does not reference any /assets/* src or href")
    if missing_from_version:
        errors.append("public HTML assets are absent from /api/version frontend_assets")

    for name in sorted(reported_set):
        path = f"/assets/{name}"
        try:
            response = client.get(f"{base_url.rstrip('/')}{path}")
            cache_control = response.headers.get("Cache-Control", "")
            asset_errors: list[str] = []
            if response.status_code != 200:
                asset_errors.append(f"returned HTTP {response.status_code}")
            if not _has_cache_control(response, "immutable"):
                asset_errors.append("Cache-Control must include immutable")
            check: dict[str, Any] = {
                "path": path,
                "status_code": response.status_code,
                "cache_control": cache_control,
                "ok": not asset_errors,
            }
            if asset_errors:
                check["error"] = "; ".join(asset_errors)
                errors.append(f"{path}: {check['error']}")
            checks.append(check)
        except Exception as exc:
            checks.append({"path": path, "ok": False, "error": str(exc)})
            errors.append(f"{path}: request failed: {exc}")

    result: dict[str, Any] = {
        "ok": not errors,
        "html_assets": public_names,
        "missing_from_version": missing_from_version,
        "checks": checks,
    }
    if errors:
        result["error"] = "; ".join(errors)
    return result


def run(
    base_url: str,
    *,
    require_cloud: bool = False,
    require_provider: bool = False,
    expect_version: str | None = None,
    expect_git_sha: str | None = None,
    frontend_assets_dir: Path | None = None,
    auth_user: str | None = None,
    auth_password: str | None = None,
) -> int:
    failed = False
    reported_assets: list[str] | None = None
    version_fetched = False
    html_asset_paths: list[str] = []
    effective_frontend_assets_dir = frontend_assets_dir if frontend_assets_dir is not None else ROOT / "frontend" / "dist" / "assets"
    deployment_mode: str | None = None
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        try:
            response = client.get(f"{base_url.rstrip('/')}/")
            response.raise_for_status()
            vite_markers = [marker for marker in ("/@vite/client", "/@react-refresh") if marker in response.text]
            html_asset_paths = public_asset_paths(response.text)
            cache_control = response.headers.get("Cache-Control", "")
            errors: list[str] = []
            if vite_markers:
                errors.append(f"public root is a Vite development page (found: {', '.join(vite_markers)})")
            if not _has_cache_control(response, "no-cache", "no-store"):
                errors.append("public HTML Cache-Control must include no-cache or no-store")
            if not html_asset_paths:
                errors.append("public root HTML does not reference any /assets/* src or href")
            payload: dict[str, Any] = {
                "cache_control": cache_control,
                "vite_dev_markers": vite_markers,
                "asset_paths": html_asset_paths,
            }
            if errors:
                payload["error"] = "; ".join(errors)
                failed = True
            _print_step("frontend", not errors, payload)
        except Exception as exc:
            failed = True
            _print_step("frontend", False, f"could not verify public root HTML: {exc}")

        try:
            version, version_response = _get_json_response(client, base_url, "/api/version")
            version_fetched = True
            raw_assets = version.get("frontend_assets")
            reported_assets = [str(item) for item in raw_assets] if isinstance(raw_assets, list) else []
            expected = _expected_version(expect_version)
            actual = str(version.get("version") or "").strip()
            version_ok = bool(actual)
            version_errors: list[str] = []
            if expected and actual != expected:
                version_ok = False
                version["expected_version"] = expected
                version_errors.append(f"deployed version {actual or '<empty>'} does not match expected {expected}")
            if expect_git_sha is not None:
                expected_git_sha = expect_git_sha.strip()
                actual_git_sha = str(version.get("git_sha") or "").strip()
                version["expected_git_sha"] = expected_git_sha
                if actual_git_sha != expected_git_sha:
                    version_ok = False
                    version_errors.append(
                        f"deployed git_sha {actual_git_sha or '<empty>'} does not match expected {expected_git_sha or '<empty>'}"
                    )
            version["cache_control"] = version_response.headers.get("Cache-Control", "")
            if not _has_cache_control(version_response, "no-store"):
                version_ok = False
                version_errors.append("/api/version Cache-Control must include no-store")
            if version_errors:
                version["error"] = "; ".join(version_errors)
            if not version_ok:
                failed = True
            _print_step("version", version_ok, version)
        except Exception as exc:
            failed = True
            _print_step("version", False, str(exc))

        if not version_fetched:
            failed = True
            _print_step("public_assets", False, "could not compare public HTML assets: /api/version was unreachable")
        else:
            public_comparison = check_public_assets(client, base_url, html_asset_paths, reported_assets)
            if not public_comparison["ok"]:
                failed = True
            _print_step("public_assets", bool(public_comparison["ok"]), public_comparison)

        if not version_fetched:
            failed = True
            _print_step("frontend_assets", False, "could not compare frontend assets: /api/version was unreachable")
        else:
            comparison = compare_frontend_assets(reported_assets, local_frontend_assets(effective_frontend_assets_dir))
            comparison["assets_dir"] = str(effective_frontend_assets_dir)
            if not comparison["ok"]:
                failed = True
            _print_step("frontend_assets", bool(comparison["ok"]), comparison)

        try:
            health, health_response = _get_json_response(client, base_url, "/api/health")
            checks = {
                "ok": bool(health.get("ok")),
                "data_root_writable": bool((health.get("storage") or {}).get("data_root_writable")),
                "uploads_writable": bool((health.get("storage") or {}).get("uploads_writable")),
                "database_connected": bool((health.get("database") or {}).get("connected")),
                "provider_configured": bool((health.get("provider") or {}).get("provider_configured")),
                "deployment_mode": health.get("deployment_mode"),
                "cache_control": health_response.headers.get("Cache-Control", ""),
            }
            deployment_mode = checks["deployment_mode"]
            step_ok = True
            health_errors: list[str] = []
            if require_cloud and checks["deployment_mode"] != "cloud":
                step_ok = False
                health_errors.append("deployment_mode is not cloud")
            if require_provider and not checks["provider_configured"]:
                step_ok = False
                health_errors.append("provider is not configured")
            if not checks["ok"] or not checks["data_root_writable"] or not checks["uploads_writable"] or not checks["database_connected"]:
                step_ok = False
                health_errors.append("health response reports an unavailable database or unwritable data/upload storage")
            if not _has_cache_control(health_response, "no-store"):
                step_ok = False
                health_errors.append("/api/health Cache-Control must include no-store")
            if health_errors:
                checks["error"] = "; ".join(health_errors)
            if not step_ok:
                failed = True
            _print_step("health", step_ok, checks)
        except Exception as exc:
            failed = True
            _print_step("health", False, str(exc))

        # Fail-closed self-check: a session-less request to a core business
        # endpoint must be rejected once the deployment enforces login. Only
        # meaningful when deployment_mode is cloud (LWS_AUTH_MODE defaults to
        # required there); --require-cloud is what turns a failure here into
        # a hard exit-1, mirroring how the health step above already gates
        # its own deployment_mode/provider assertions on the same flags.
        try:
            status_code = unauthenticated_probe_status(base_url, "/api/projects")
            fail_closed_ok = status_code == 401
            result: dict[str, Any] = {"deployment_mode": deployment_mode, "status_code": status_code}
            if deployment_mode != "cloud":
                result["note"] = "deployment_mode 不是 cloud，本项仅供参考，不影响本地/认证关闭部署"
            elif not fail_closed_ok:
                result["error"] = "未登录访问 GET /api/projects 未返回 401；fail-closed 鉴权可能失效"
                if require_cloud:
                    failed = True
            _print_step("auth_fail_closed", fail_closed_ok or deployment_mode != "cloud", result)
        except Exception as exc:
            if require_cloud:
                failed = True
            _print_step("auth_fail_closed", False, str(exc))

        authenticated = False
        if auth_user:
            try:
                user_body = login(client, base_url, auth_user, auth_password or "")
                authenticated = True
                _print_step("auth_login", True, {"username": user_body.get("username"), "role": user_body.get("role")})
            except PasswordChangeRequiredError as exc:
                failed = True
                _print_step("auth_login", False, {"error": str(exc), "action_required": "change_password"})
            except AuthLoginError as exc:
                failed = True
                _print_step("auth_login", False, str(exc))

        try:
            if auth_user and not authenticated:
                raise RuntimeError("登录未成功，跳过需要登录态的上传自检（见 auth_login 步骤）")
            with tempfile.TemporaryDirectory() as tmp:
                probe = Path(tmp) / "upload-readability-probe.txt"
                probe.write_text("deployment upload readability probe\n中文读写自检\n", encoding="utf-8")
                with probe.open("rb") as fh:
                    response = client.post(
                        f"{base_url.rstrip('/')}/api/diagnostics/upload-readability",
                        files={"file": (probe.name, fh, "text/plain")},
                    )
                if response.status_code in (401, 403):
                    hint = (
                        "云端部署已要求登录（该探针需要 ADMIN 能力）才能探测上传可读性；"
                        "请传入 --auth-user/--auth-password 后重试。"
                        if not auth_user
                        else "已登录账号缺少 ADMIN 能力，或首登改密尚未完成；请使用管理员账号重试。"
                    )
                    raise RuntimeError(f"HTTP {response.status_code}：{response_error_detail(response)}；{hint}")
                response.raise_for_status()
                payload = response.json()
                ok = bool(payload.get("ok")) and bool(payload.get("readable")) and bool(payload.get("sha256"))
                if not ok:
                    failed = True
                _print_step("upload_readability", ok, {
                    "filename": payload.get("filename"),
                    "size": payload.get("size"),
                    "readable": payload.get("readable"),
                    "sha256": payload.get("sha256"),
                    "preview": payload.get("preview"),
                })
        except Exception as exc:
            failed = True
            _print_step("upload_readability", False, str(exc))

    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Check deployed Localization Workflow Studio health.")
    parser.add_argument("--base-url", required=True, help="Example: https://ai-lwstudio.example.com")
    parser.add_argument("--require-cloud", action="store_true", help="Fail if /api/health deployment_mode is not cloud.")
    parser.add_argument("--require-provider", action="store_true", help="Fail if provider API key is not configured.")
    parser.add_argument("--expect-version", default=None, help="Expected /api/version value. Defaults to local VERSION file.")
    parser.add_argument("--expect-git-sha", default=None, help="Expected /api/version git_sha. Checked only when provided.")
    parser.add_argument(
        "--check-frontend-assets",
        nargs="?",
        const=str(ROOT / "frontend" / "dist" / "assets"),
        default=str(ROOT / "frontend" / "dist" / "assets"),
        metavar="PATH",
        help="Compare backend-reported frontend_assets with the full local dist assets dir. Always on; PATH defaults to frontend/dist/assets.",
    )
    parser.add_argument(
        "--auth-user",
        default=None,
        help=(
            "Log in as this user before running checks that need a session "
            "(e.g. the upload-readability probe, which requires ADMIN). "
            "Required once the deployment enforces login (LWS_AUTH_MODE=required / cloud)."
        ),
    )
    parser.add_argument("--auth-password", default=None, help="Password for --auth-user.")
    args = parser.parse_args()
    return run(
        args.base_url,
        require_cloud=args.require_cloud,
        require_provider=args.require_provider,
        expect_version=args.expect_version,
        expect_git_sha=args.expect_git_sha,
        frontend_assets_dir=Path(args.check_frontend_assets),
        auth_user=args.auth_user,
        auth_password=args.auth_password,
    )


if __name__ == "__main__":
    raise SystemExit(main())
