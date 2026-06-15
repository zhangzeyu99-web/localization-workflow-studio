from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

import httpx


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


def run(base_url: str, *, require_cloud: bool = False, require_provider: bool = False, expect_version: str | None = None) -> int:
    failed = False
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        try:
            version = _get_json(client, base_url, "/api/version")
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

        try:
            with tempfile.TemporaryDirectory() as tmp:
                probe = Path(tmp) / "upload-readability-probe.txt"
                probe.write_text("deployment upload readability probe\n中文读写自检\n", encoding="utf-8")
                with probe.open("rb") as fh:
                    response = client.post(
                        f"{base_url.rstrip('/')}/api/diagnostics/upload-readability",
                        files={"file": (probe.name, fh, "text/plain")},
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
    parser.add_argument("--require-cloud", action="store_true", help="Fail if /api/health deployment_mode is not cloud.")
    parser.add_argument("--require-provider", action="store_true", help="Fail if provider API key is not configured.")
    parser.add_argument("--expect-version", default=None, help="Expected /api/version value. Defaults to local VERSION file.")
    args = parser.parse_args()
    return run(args.base_url, require_cloud=args.require_cloud, require_provider=args.require_provider, expect_version=args.expect_version)


if __name__ == "__main__":
    raise SystemExit(main())
