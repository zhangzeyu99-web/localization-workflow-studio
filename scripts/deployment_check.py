from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

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


def _get_json(client: httpx.Client, base_url: str, path: str) -> dict[str, Any]:
    response = client.get(f"{base_url.rstrip('/')}{path}")
    response.raise_for_status()
    return response.json()


def local_frontend_assets(assets_dir: Path) -> list[str]:
    # Mirrors backend _frontend_assets(): sorted file names, capped at 20.
    return sorted(path.name for path in assets_dir.glob("*") if path.is_file())[:20]


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


def run(
    base_url: str,
    *,
    require_cloud: bool = False,
    require_provider: bool = False,
    expect_version: str | None = None,
    frontend_assets_dir: Path | None = None,
    auth_user: str | None = None,
    auth_password: str | None = None,
) -> int:
    failed = False
    reported_assets: list[str] | None = None
    version_fetched = False
    deployment_mode: str | None = None
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        try:
            version = _get_json(client, base_url, "/api/version")
            version_fetched = True
            raw_assets = version.get("frontend_assets")
            reported_assets = [str(item) for item in raw_assets] if isinstance(raw_assets, list) else []
            expected = _expected_version(expect_version)
            actual = str(version.get("version") or "").strip()
            version_ok = bool(actual)
            if expected and actual != expected:
                version_ok = False
                version["expected_version"] = expected
                version["error"] = f"deployed version {actual or '<empty>'} does not match expected {expected}"
            if not version_ok:
                failed = True
            _print_step("version", version_ok, version)
        except Exception as exc:
            failed = True
            _print_step("version", False, str(exc))

        if frontend_assets_dir is not None:
            if not version_fetched:
                failed = True
                _print_step("frontend_assets", False, "could not compare frontend assets: /api/version was unreachable")
            else:
                comparison = compare_frontend_assets(reported_assets, local_frontend_assets(frontend_assets_dir))
                comparison["assets_dir"] = str(frontend_assets_dir)
                if not comparison["ok"]:
                    failed = True
                _print_step("frontend_assets", bool(comparison["ok"]), comparison)

        try:
            health = _get_json(client, base_url, "/api/health")
            checks = {
                "ok": bool(health.get("ok")),
                "data_root_writable": bool((health.get("storage") or {}).get("data_root_writable")),
                "uploads_writable": bool((health.get("storage") or {}).get("uploads_writable")),
                "database_connected": bool((health.get("database") or {}).get("connected")),
                "provider_configured": bool((health.get("provider") or {}).get("provider_configured")),
                "deployment_mode": health.get("deployment_mode"),
            }
            deployment_mode = checks["deployment_mode"]
            step_ok = True
            if require_cloud and checks["deployment_mode"] != "cloud":
                step_ok = False
                checks["error"] = "deployment_mode is not cloud"
            if require_provider and not checks["provider_configured"]:
                step_ok = False
                checks["error"] = "provider is not configured"
            if not checks["ok"] or not checks["data_root_writable"] or not checks["uploads_writable"] or not checks["database_connected"]:
                step_ok = False
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
    parser.add_argument(
        "--check-frontend-assets",
        nargs="?",
        const=str(ROOT / "frontend" / "dist" / "assets"),
        default=None,
        metavar="PATH",
        help="Compare backend-reported frontend_assets with a local dist assets dir. Off by default; PATH defaults to frontend/dist/assets.",
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
        frontend_assets_dir=Path(args.check_frontend_assets) if args.check_frontend_assets else None,
        auth_user=args.auth_user,
        auth_password=args.auth_password,
    )


if __name__ == "__main__":
    raise SystemExit(main())
