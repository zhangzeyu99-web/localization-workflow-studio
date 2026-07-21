from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.auth as auth
import app.config as config
import app.db as db
import app.main as main_module
import app.operator_context as operator_context
import app.routers.system as system_router
from conftest import reset_data_root


@pytest.fixture(autouse=True)
def reset_runtime_profile_test_data() -> None:
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))


def _runtime_profile(env: dict[str, str]):
    profile_type = getattr(config, "RuntimeProfile", None)
    assert profile_type is not None, "RuntimeProfile must be defined in app.config"
    return profile_type.from_environment(
        env,
        data_root=Path("D:/lws-profile-tests/data"),
        app_root=Path("D:/lws-profile-tests/app"),
    )


def _create_app():
    factory = getattr(main_module, "create_app", None)
    assert callable(factory), "app.main.create_app must construct a profile-bound app"
    profile = config.RuntimeProfile.from_environment(
        os.environ,
        data_root=config.DATA_ROOT,
        app_root=config.REPO_ROOT,
    )
    return factory(profile)


@pytest.mark.parametrize(
    ("env", "deployment_mode", "auth_mode", "identifier"),
    [
        ({}, "local", "off", "local-off"),
        ({"LWS_DEPLOYMENT_MODE": "local", "LWS_AUTH_MODE": "required"}, "local", "required", "local-required"),
        ({"LWS_DEPLOYMENT_MODE": "cloud"}, "cloud", "required", "cloud-required"),
        ({"LWS_DEPLOYMENT_MODE": " CLOUD ", "LWS_AUTH_MODE": " REQUIRED "}, "cloud", "required", "cloud-required"),
    ],
)
def test_runtime_profile_accepts_supported_modes_and_defaults(
    env: dict[str, str],
    deployment_mode: str,
    auth_mode: str,
    identifier: str,
) -> None:
    profile = _runtime_profile(env)

    assert profile.deployment_mode == deployment_mode
    assert profile.auth_mode == auth_mode
    assert profile.identifier == identifier
    assert profile.auth_required is (auth_mode == "required")
    assert profile.secure_cookies is (deployment_mode == "cloud")


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"LWS_DEPLOYMENT_MODE": "edge"}, "LWS_DEPLOYMENT_MODE"),
        ({"LWS_AUTH_MODE": "optional"}, "LWS_AUTH_MODE"),
        (
            {"LWS_DEPLOYMENT_MODE": "cloud", "LWS_AUTH_MODE": "off"},
            "cloud.*off",
        ),
    ],
)
def test_runtime_profile_rejects_invalid_or_unsafe_combinations(
    env: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(RuntimeError, match=message):
        _runtime_profile(env)


def test_runtime_profile_is_immutable() -> None:
    profile = _runtime_profile({})

    with pytest.raises(FrozenInstanceError):
        profile.auth_mode = "required"


@pytest.mark.parametrize(
    ("deployment_mode", "auth_mode"),
    [
        ("edge", "off"),
        ("local", "optional"),
        ("cloud", "off"),
    ],
)
def test_runtime_profile_constructor_cannot_bypass_validation(
    deployment_mode: str,
    auth_mode: str,
) -> None:
    profile_type = getattr(config, "RuntimeProfile", None)
    assert profile_type is not None

    with pytest.raises(RuntimeError):
        profile_type(deployment_mode, auth_mode)


def test_invalid_runtime_profile_fails_app_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LWS_DEPLOYMENT_MODE", "invalid")

    with pytest.raises(RuntimeError, match="LWS_DEPLOYMENT_MODE"):
        _create_app()


def test_default_app_reuses_the_process_startup_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup_profile = getattr(config, "STARTUP_RUNTIME_PROFILE", None)
    assert startup_profile is not None, "config must parse one process startup profile"
    monkeypatch.setenv("LWS_DEPLOYMENT_MODE", "local")
    monkeypatch.setenv("LWS_AUTH_MODE", "required")

    test_app = main_module.create_app()

    assert test_app.state.runtime_profile is startup_profile


def test_app_profile_does_not_hot_switch_after_environment_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LWS_DEPLOYMENT_MODE", "local")
    monkeypatch.setenv("LWS_AUTH_MODE", "off")
    test_app = _create_app()

    @test_app.get("/runtime-profile/operator-probe")
    def operator_probe() -> dict[str, str]:
        return {"operator": operator_context.require_operator_for_cloud()}

    monkeypatch.setenv("LWS_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("LWS_AUTH_MODE", "required")
    db.init_db()
    user = db.create_user(
        "profile-cookie-user",
        auth.hash_password("Profile-Pass1!"),
        "admin",
    )

    with TestClient(test_app) as client:
        health = client.get("/api/health")
        version = client.get("/api/version")
        business = client.get("/api/projects")
        login = client.post(
            "/api/auth/login",
            json={"username": user["username"], "password": "Profile-Pass1!"},
        )
        operator = client.get("/runtime-profile/operator-probe")

    for response in (health, version):
        assert response.status_code == 200, response.text
        assert response.json()["deployment_mode"] == "local"
        assert response.json()["auth_mode"] == "off"
        assert response.json()["runtime_profile"] == "local-off"
    assert business.status_code == 200, business.text
    assert login.status_code == 200, login.text
    assert "secure" not in login.headers.get("set-cookie", "").lower()
    assert operator.status_code == 200, operator.text
    assert operator.json() == {"operator": ""}


def test_cloud_profile_stays_fail_closed_and_uses_secure_cookie_after_env_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LWS_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("LWS_AUTH_MODE", "required")
    monkeypatch.setenv("LWS_ADMIN_USER", "profile-cloud-admin")
    monkeypatch.setenv("LWS_ADMIN_PASSWORD", "Initial-Profile-Pass1!")
    test_app = _create_app()

    monkeypatch.setenv("LWS_DEPLOYMENT_MODE", "local")
    monkeypatch.setenv("LWS_AUTH_MODE", "off")

    with TestClient(test_app, base_url="https://testserver") as client:
        denied = client.get("/api/projects")
        health = client.get("/api/health")
        version = client.get("/api/version")
        login = client.post(
            "/api/auth/login",
            json={
                "username": "profile-cloud-admin",
                "password": "Initial-Profile-Pass1!",
            },
        )

    assert denied.status_code == 401
    for response in (health, version):
        assert response.status_code == 200, response.text
        assert response.json()["deployment_mode"] == "cloud"
        assert response.json()["auth_mode"] == "required"
        assert response.json()["runtime_profile"] == "cloud-required"
    assert login.status_code == 200, login.text
    assert "secure" in login.headers.get("set-cookie", "").lower()


def test_two_apps_keep_independent_profiles_while_clients_overlap() -> None:
    db.init_db()
    db.create_user(
        "profile-isolation-admin",
        auth.hash_password("Profile-Isolation-Pass1!"),
        "admin",
    )
    off_profile = config.RuntimeProfile("local", "off")
    required_profile = config.RuntimeProfile("local", "required")
    off_app = main_module.create_app(off_profile)
    required_app = main_module.create_app(required_profile)

    assert off_app.state.runtime_profile is off_profile
    assert required_app.state.runtime_profile is required_profile
    with TestClient(off_app) as off_client:
        assert off_client.get("/api/projects").status_code == 200
        with TestClient(required_app) as required_client:
            assert required_client.get("/api/projects").status_code == 401
            assert off_client.get("/api/projects").status_code == 200


def test_request_bound_profile_is_distinct_from_unbound_startup_fallback() -> None:
    startup_profile = config.STARTUP_RUNTIME_PROFILE
    cloud_profile = config.RuntimeProfile("cloud", "required")
    assert startup_profile.identifier != cloud_profile.identifier
    db.init_db()
    db.create_user(
        "profile-binding-admin",
        auth.hash_password("Profile-Binding-Pass1!"),
        "admin",
    )
    cloud_app = main_module.create_app(cloud_profile)

    @cloud_app.get("/runtime-profile/request-bound-direct-call")
    def request_bound_direct_call() -> dict[str, object]:
        return system_router.version()

    unbound_before = system_router.version()
    with TestClient(cloud_app, base_url="https://testserver") as client:
        request_bound = client.get("/runtime-profile/request-bound-direct-call")
    unbound_after = system_router.version()

    assert request_bound.status_code == 200, request_bound.text
    assert request_bound.json()["runtime_profile"] == "cloud-required"
    assert unbound_before["runtime_profile"] == startup_profile.identifier
    assert unbound_after["runtime_profile"] == startup_profile.identifier


@pytest.mark.parametrize("module_name", ["app.config", "app.main"])
@pytest.mark.parametrize(
    ("profile_env", "message"),
    [
        (
            {"LWS_DEPLOYMENT_MODE": "edge"},
            "LWS_DEPLOYMENT_MODE must be 'local' or 'cloud'",
        ),
        (
            {"LWS_DEPLOYMENT_MODE": "local", "LWS_AUTH_MODE": "optional"},
            "LWS_AUTH_MODE must be 'off' or 'required'",
        ),
        (
            {"LWS_DEPLOYMENT_MODE": "cloud", "LWS_AUTH_MODE": "off"},
            "cloud deployment cannot use auth mode off",
        ),
    ],
)
def test_invalid_profile_fails_real_import_boundary_in_subprocess(
    tmp_path: Path,
    module_name: str,
    profile_env: dict[str, str],
    message: str,
) -> None:
    env = os.environ.copy()
    env.pop("LWS_DEPLOYMENT_MODE", None)
    env.pop("LWS_AUTH_MODE", None)
    env.update(profile_env)
    env["LWS_DATA_ROOT"] = str(tmp_path / "data")
    backend_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        cwd=backend_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert message in output
