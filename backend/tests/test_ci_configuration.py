from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _job_blocks(workflow: str) -> dict[str, str]:
    matches = list(re.finditer(r"(?m)^  ([a-z0-9-]+):\s*$", workflow))
    return {
        match.group(1): workflow[match.start() : matches[index + 1].start() if index + 1 < len(matches) else None]
        for index, match in enumerate(matches)
    }


def test_playwright_backends_pin_local_auth_profiles() -> None:
    default_config = _read("frontend/playwright.config.ts")
    auth_config = _read("frontend/playwright.auth.config.ts")

    assert "LWS_DEPLOYMENT_MODE: 'local'" in default_config
    assert "LWS_AUTH_MODE: 'off'" in default_config
    assert "LWS_DEPLOYMENT_MODE: 'local'" in auth_config
    assert "LWS_AUTH_MODE: 'required'" in auth_config


def test_playwright_specs_assert_runtime_identity_and_ui_boundaries() -> None:
    local_suite = _read("frontend/e2e/studio-ui-flow.spec.ts")
    auth_suite = _read("frontend/e2e/auth-flow.spec.ts")
    runtime_smoke = _read("frontend/e2e/runtime-profile-smoke.spec.ts")

    for token in ("/api/version", "deployment_mode", "auth_mode", "runtime_profile", "local-off"):
        assert token in local_suite
    for token in ("login-submit", "show-register", "设置"):
        assert token in local_suite

    for token in ("/api/version", "deployment_mode", "auth_mode", "runtime_profile", "local-required"):
        assert token in auth_suite
    for token in ("login-submit", "show-register"):
        assert token in auth_suite

    for token in (
        "LWS_EXPECT_RUNTIME_PROFILE",
        "local-off",
        "cloud-required",
        "LWS_RUNTIME_SMOKE_USER",
        "LWS_RUNTIME_SMOKE_PASSWORD",
        "/api/version",
        "/api/projects",
        "login-submit",
        "show-register",
        "设置",
    ):
        assert token in runtime_smoke


def test_ci_job_graph_builds_frontend_once_and_packages_without_rebuild() -> None:
    workflow = _read(".github/workflows/ci.yml")
    jobs = _job_blocks(workflow)
    required_jobs = {
        "source-gates",
        "e2e-local-off",
        "e2e-local-required",
        "build-universal",
        "smoke-extracted-local-off",
        "smoke-extracted-cloud-required",
    }
    assert required_jobs <= jobs.keys()

    assert workflow.count("npm run build") == 1
    assert "npm run build" in jobs["source-gates"]
    assert "actions/upload-artifact@v4" in jobs["source-gates"]
    assert "frontend-dist" in jobs["source-gates"]

    build_job = jobs["build-universal"]
    for dependency in ("source-gates", "e2e-local-off", "e2e-local-required"):
        assert dependency in build_job
    assert "actions/download-artifact@v4" in build_job
    assert "frontend-dist" in build_job
    assert "--no-rebuild-frontend" in build_job
    assert "npm run build" not in build_job

    for smoke_job in ("smoke-extracted-local-off", "smoke-extracted-cloud-required"):
        assert "build-universal" in jobs[smoke_job]
        assert "actions/download-artifact@v4" in jobs[smoke_job]
        assert "universal-release" in jobs[smoke_job]
        assert "npm run build" not in jobs[smoke_job]

    publish_jobs = [block for name, block in jobs.items() if "publish" in name or "release" in name and name != "build-universal"]
    for publish_job in publish_jobs:
        assert "smoke-extracted-local-off" in publish_job
        assert "smoke-extracted-cloud-required" in publish_job
        assert "refs/tags/" in publish_job or "workflow_dispatch" in publish_job
        assert "deploy" not in publish_job.lower()


def test_ci_preserves_source_gates_and_uses_canonical_frontend_digest() -> None:
    workflow = _read(".github/workflows/ci.yml")
    source_job = _job_blocks(workflow)["source-gates"]
    build_job = _job_blocks(workflow)["build-universal"]

    for command in (
        "python -m pytest -q",
        "python -m compileall",
        "ruff check",
        "workflow/localization",
        "workflow/glossary",
        "npm ci",
    ):
        assert command in source_job

    assert "_tree_sha256" in source_job
    assert "frontend-dist.sha256" in source_job
    assert "_tree_sha256" in build_job
    assert "frontend-dist.sha256" in build_job
    assert "github.sha" in build_job
    assert "PACKAGE_MANIFEST.json" in build_job
    assert "frontend_dist_sha256" in build_job
    assert "runtime_payload_sha256" in build_job


def test_ci_extracted_smokes_use_the_same_zip_and_verify_profile_boundaries() -> None:
    workflow = _read(".github/workflows/ci.yml")
    jobs = _job_blocks(workflow)
    local_job = jobs["smoke-extracted-local-off"]
    cloud_job = jobs["smoke-extracted-cloud-required"]

    assert "windows-latest" in local_job
    assert "start-workbench.ps1" in local_job
    assert "stop-workbench.ps1" in local_job
    assert "projects/smoke-deep-link" in local_job
    assert "--expect-runtime-profile local-off" in local_job
    assert "LWS_EXPECT_RUNTIME_PROFILE = 'local-off'" in local_job

    assert "ubuntu-latest" in cloud_job
    assert "openssl req -x509" in cloud_job
    assert "LWS_DEPLOYMENT_MODE=cloud" in cloud_job
    assert "LWS_AUTH_MODE=required" in cloud_job
    assert "LWS_SERVE_FRONTEND=1" in cloud_job
    assert "/api/auth/change-password" in cloud_job
    assert "--expect-runtime-profile cloud-required" in cloud_job
    assert "LWS_EXPECT_RUNTIME_PROFILE=cloud-required" in cloud_job

    for smoke_job in (local_job, cloud_job):
        assert "backend/requirements.txt" in smoke_job or "backend\\requirements.txt" in smoke_job
        assert "workflow/glossary/requirements.txt" in smoke_job or "workflow\\glossary\\requirements.txt" in smoke_job
        assert "workflow/localization/requirements.txt" in smoke_job or "workflow\\localization\\requirements.txt" in smoke_job
        assert "scripts/stability_check.py" in smoke_job or "scripts\\stability_check.py" in smoke_job
        assert "runtime-profile-smoke.spec.ts" in smoke_job
        assert "frontend_dist_sha256" in smoke_job
        assert "runtime_payload_sha256" in smoke_job
        assert "sha256" in smoke_job.lower()
