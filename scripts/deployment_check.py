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
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} must return a JSON object")
    return payload, response


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


_PROFILE_FIELDS = ("deployment_mode", "auth_mode", "runtime_profile")
_VALID_RUNTIME_PROFILES = {
    ("local", "off"): "local-off",
    ("local", "required"): "local-required",
    ("cloud", "off"): "cloud-off",
    ("cloud", "required"): "cloud-required",
}


def _normalize_profile_expectations(
    *,
    expect_deployment_mode: str | None,
    expect_auth_mode: str | None,
    expect_runtime_profile: str | None,
    require_cloud: bool,
) -> tuple[str | None, str | None, str | None]:
    if expect_deployment_mode not in {None, "local", "cloud"}:
        raise ValueError("expect_deployment_mode must be local or cloud")
    if expect_auth_mode not in {None, "off", "required"}:
        raise ValueError("expect_auth_mode must be off or required")
    valid_identifiers = set(_VALID_RUNTIME_PROFILES.values())
    if expect_runtime_profile not in {None, *valid_identifiers}:
        raise ValueError(
            "expect_runtime_profile must be local-off, local-required, cloud-off, or cloud-required"
        )
    if require_cloud and expect_deployment_mode == "local":
        raise ValueError("--require-cloud contradicts expect_deployment_mode=local")

    effective_deployment = "cloud" if require_cloud else expect_deployment_mode
    runtime_components = next(
        (
            pair
            for pair, identifier in _VALID_RUNTIME_PROFILES.items()
            if identifier == expect_runtime_profile
        ),
        None,
    )
    contradictory = False
    if runtime_components is not None:
        runtime_deployment, runtime_auth = runtime_components
        contradictory = bool(
            (effective_deployment and effective_deployment != runtime_deployment)
            or (expect_auth_mode and expect_auth_mode != runtime_auth)
        )
    if effective_deployment and expect_auth_mode:
        contradictory = contradictory or (
            (effective_deployment, expect_auth_mode) not in _VALID_RUNTIME_PROFILES
        )
    if contradictory:
        raise ValueError("contradictory runtime profile expectations")
    return effective_deployment, expect_auth_mode, expect_runtime_profile


def _check_runtime_profile(
    version: dict[str, Any] | None,
    health: dict[str, Any] | None,
    *,
    expect_deployment_mode: str | None,
    expect_auth_mode: str | None,
    expect_runtime_profile: str | None,
) -> tuple[bool, dict[str, Any], str | None]:
    payload: dict[str, Any] = {
        "version": {},
        "health": {},
        "expected": {
            "deployment_mode": expect_deployment_mode,
            "auth_mode": expect_auth_mode,
            "runtime_profile": expect_runtime_profile,
        },
    }
    errors: list[str] = []
    if version is None or health is None:
        errors.append("/api/version and /api/health are both required for runtime profile validation")
    else:
        version_values = {
            field: str(version.get(field) or "").strip() for field in _PROFILE_FIELDS
        }
        health_values = {
            field: str(health.get(field) or "").strip() for field in _PROFILE_FIELDS
        }
        payload["version"] = version_values
        payload["health"] = health_values
        for field in _PROFILE_FIELDS:
            if not version_values[field]:
                errors.append(f"/api/version is missing {field}")
            if not health_values[field]:
                errors.append(f"/api/health is missing {field}")
            if version_values[field] != health_values[field]:
                errors.append(
                    "/api/version and /api/health disagree on "
                    f"{field}: {version_values[field] or '<empty>'} != "
                    f"{health_values[field] or '<empty>'}"
                )

        if not errors:
            deployment_mode = version_values["deployment_mode"]
            auth_mode = version_values["auth_mode"]
            runtime_profile = version_values["runtime_profile"]
            expected_identifier = _VALID_RUNTIME_PROFILES.get(
                (deployment_mode, auth_mode)
            )
            if expected_identifier is None or runtime_profile != expected_identifier:
                errors.append(
                    "invalid runtime profile: "
                    f"{deployment_mode}/{auth_mode}/{runtime_profile}"
                )
            if (
                expect_deployment_mode is not None
                and deployment_mode != expect_deployment_mode
            ):
                errors.append(
                    f"deployment_mode expected {expect_deployment_mode} but reported {deployment_mode}"
                )
            if expect_auth_mode is not None and auth_mode != expect_auth_mode:
                errors.append(
                    f"auth_mode expected {expect_auth_mode} but reported {auth_mode}"
                )
            if (
                expect_runtime_profile is not None
                and runtime_profile != expect_runtime_profile
            ):
                errors.append(
                    "runtime_profile expected "
                    f"{expect_runtime_profile} but reported {runtime_profile}"
                )
            if not errors:
                return True, payload, auth_mode

    if errors:
        payload["error"] = "; ".join(errors)
    return False, payload, None


def run(
    base_url: str,
    *,
    expect_deployment_mode: str | None = None,
    expect_auth_mode: str | None = None,
    expect_runtime_profile: str | None = None,
    require_cloud: bool = False,
    require_provider: bool = False,
    expect_version: str | None = None,
    expect_git_sha: str | None = None,
    frontend_assets_dir: Path | None = None,
    auth_user: str | None = None,
    auth_password: str | None = None,
) -> int:
    (
        expect_deployment_mode,
        expect_auth_mode,
        expect_runtime_profile,
    ) = _normalize_profile_expectations(
        expect_deployment_mode=expect_deployment_mode,
        expect_auth_mode=expect_auth_mode,
        expect_runtime_profile=expect_runtime_profile,
        require_cloud=require_cloud,
    )
    failed = False
    reported_assets: list[str] | None = None
    version_fetched = False
    html_asset_paths: list[str] = []
    effective_frontend_assets_dir = frontend_assets_dir if frontend_assets_dir is not None else ROOT / "frontend" / "dist" / "assets"
    version_payload: dict[str, Any] | None = None
    health_payload: dict[str, Any] | None = None
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
            version_payload = version
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
            health_payload = health
            checks = {
                "ok": bool(health.get("ok")),
                "data_root_writable": bool((health.get("storage") or {}).get("data_root_writable")),
                "uploads_writable": bool((health.get("storage") or {}).get("uploads_writable")),
                "database_connected": bool((health.get("database") or {}).get("connected")),
                "provider_configured": bool((health.get("provider") or {}).get("provider_configured")),
                "deployment_mode": health.get("deployment_mode"),
                "auth_mode": health.get("auth_mode"),
                "runtime_profile": health.get("runtime_profile"),
                "cache_control": health_response.headers.get("Cache-Control", ""),
            }
            step_ok = True
            health_errors: list[str] = []
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

        profile_ok, profile_result, actual_auth_mode = _check_runtime_profile(
            version_payload,
            health_payload,
            expect_deployment_mode=expect_deployment_mode,
            expect_auth_mode=expect_auth_mode,
            expect_runtime_profile=expect_runtime_profile,
        )
        if not profile_ok:
            failed = True
        _print_step("runtime_profile", profile_ok, profile_result)

        boundary_ok = False
        if profile_ok and actual_auth_mode is not None:
            try:
                status_code = unauthenticated_probe_status(base_url, "/api/projects")
                expected_status = 401 if actual_auth_mode == "required" else 200
                boundary_ok = status_code == expected_status
                boundary_result: dict[str, Any] = {
                    "auth_mode": actual_auth_mode,
                    "status_code": status_code,
                    "expected_status": expected_status,
                }
                if not boundary_ok:
                    failed = True
                    boundary_result["error"] = (
                        "anonymous GET /api/projects returned "
                        f"{status_code}; expected {expected_status} for auth_mode={actual_auth_mode}"
                    )
                _print_step("anonymous_projects", boundary_ok, boundary_result)
            except Exception as exc:
                failed = True
                _print_step("anonymous_projects", False, str(exc))
        else:
            _print_step(
                "anonymous_projects",
                False,
                {"error": "skipped because runtime profile validation failed"},
            )

        auth_ready = False
        if not profile_ok or not boundary_ok or actual_auth_mode is None:
            _print_step(
                "auth_login",
                False,
                {"error": "skipped because runtime profile or anonymous boundary validation failed"},
            )
        elif actual_auth_mode == "required":
            if not auth_user or not auth_password:
                failed = True
                _print_step(
                    "auth_login",
                    False,
                    {
                        "error": (
                            "auth_mode=required needs both --auth-user and "
                            "--auth-password before business probes"
                        )
                    },
                )
            else:
                try:
                    user_body = login(
                        client,
                        base_url,
                        auth_user,
                        auth_password,
                    )
                    auth_ready = True
                    _print_step(
                        "auth_login",
                        True,
                        {
                            "username": user_body.get("username"),
                            "role": user_body.get("role"),
                        },
                    )
                except PasswordChangeRequiredError as exc:
                    failed = True
                    _print_step(
                        "auth_login",
                        False,
                        {
                            "error": str(exc),
                            "action_required": "change_password",
                        },
                    )
                except AuthLoginError as exc:
                    failed = True
                    _print_step("auth_login", False, str(exc))
                except Exception as exc:
                    failed = True
                    _print_step("auth_login", False, str(exc))
        elif auth_user or auth_password:
            failed = True
            _print_step(
                "auth_login",
                False,
                {
                    "error": (
                        "--auth-user and --auth-password must not be provided "
                        "when auth_mode=off"
                    )
                },
            )
        else:
            auth_ready = True
            _print_step(
                "auth_login",
                True,
                {"mode": "synthetic_local_admin"},
            )

        try:
            if not auth_ready:
                raise RuntimeError(
                    "upload readability probe skipped because authentication validation failed"
                )
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
                        "authenticated account lacks ADMIN capability or still requires a password change"
                        if actual_auth_mode == "required"
                        else "auth_mode=off did not expose the synthetic local administrator"
                    )
                    raise RuntimeError(
                        f"HTTP {response.status_code}: {response_error_detail(response)}; {hint}"
                    )
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
    parser.add_argument(
        "--expect-deployment-mode",
        choices=("local", "cloud"),
        default=None,
    )
    parser.add_argument(
        "--expect-auth-mode",
        choices=("off", "required"),
        default=None,
    )
    parser.add_argument(
        "--expect-runtime-profile",
        choices=("local-off", "local-required", "cloud-off", "cloud-required"),
        default=None,
    )
    parser.add_argument(
        "--require-cloud",
        action="store_true",
        help="Compatibility alias for --expect-deployment-mode cloud.",
    )
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
            "Required once the deployment enforces login (LWS_AUTH_MODE=required)."
        ),
    )
    parser.add_argument("--auth-password", default=None, help="Password for --auth-user.")
    args = parser.parse_args()
    try:
        return run(
            args.base_url,
            expect_deployment_mode=args.expect_deployment_mode,
            expect_auth_mode=args.expect_auth_mode,
            expect_runtime_profile=args.expect_runtime_profile,
            require_cloud=args.require_cloud,
            require_provider=args.require_provider,
            expect_version=args.expect_version,
            expect_git_sha=args.expect_git_sha,
            frontend_assets_dir=Path(args.check_frontend_assets),
            auth_user=args.auth_user,
            auth_password=args.auth_password,
        )
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
