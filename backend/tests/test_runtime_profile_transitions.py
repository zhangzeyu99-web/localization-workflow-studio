from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.auth as auth
import app.config as config
import app.db as db
import app.main as main_module
from app.config import DATA_ROOT
from conftest import reset_data_root

ADMIN_PASSWORD = "Initial-Admin-Password!"
USER_PASSWORD = "Sup3rSecret1!"
_PROFILE_ENV_VARS = (
    "LWS_AUTH_MODE",
    "LWS_DEPLOYMENT_MODE",
    "LWS_ADMIN_USER",
    "LWS_ADMIN_PASSWORD",
)
_ACCOUNT_TABLES = {"users", "sessions", "project_members"}


def _clear_auth_rate_limiters() -> None:
    auth.login_rate_limiter._state.clear()  # noqa: SLF001
    auth.registration_rate_limiter._state.clear()  # noqa: SLF001


@pytest.fixture(autouse=True)
def reset_test_state(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _PROFILE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()
    _clear_auth_rate_limiters()
    yield
    _clear_auth_rate_limiters()
    for name in _PROFILE_ENV_VARS:
        os.environ.pop(name, None)


def _account_table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN ('users', 'sessions', 'project_members')
            """
        ).fetchall()
    }


def _business_rows(conn: sqlite3.Connection) -> dict[str, tuple[tuple[object, ...], ...]]:
    table_names = [
        row["name"]
        for row in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
        if row["name"] not in _ACCOUNT_TABLES
    ]
    return {
        table_name: tuple(tuple(row) for row in conn.execute(f'SELECT * FROM "{table_name}" ORDER BY rowid').fetchall())
        for table_name in table_names
    }


def _profile_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    deployment_mode: str,
    auth_mode: str,
    admin_user: str | None = None,
    admin_password: str | None = None,
):
    if admin_user is None:
        monkeypatch.delenv("LWS_ADMIN_USER", raising=False)
    else:
        monkeypatch.setenv("LWS_ADMIN_USER", admin_user)
    if admin_password is None:
        monkeypatch.delenv("LWS_ADMIN_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("LWS_ADMIN_PASSWORD", admin_password)
    profile = config.RuntimeProfile(
        deployment_mode=deployment_mode,
        auth_mode=auth_mode,
    )
    return main_module.create_app(profile)


def test_pre_account_database_upgrade_preserves_business_rows_and_files() -> None:
    db.init_db()
    project = db.insert_project(
        "Legacy Local Project",
        "QA",
        "created before account tables",
    )
    project_file = DATA_ROOT / "projects" / project["id"] / "legacy.txt"
    project_file.parent.mkdir(parents=True, exist_ok=True)
    project_file.write_bytes(b"legacy-business-payload")
    settings_path = DATA_ROOT / "settings.local.json"
    settings_bytes = b'{"provider":"openai","api_key":""}\n'
    settings_path.write_bytes(settings_bytes)

    with db.connect() as conn:
        conn.executescript(
            """
            DROP TABLE IF EXISTS project_members;
            DROP TABLE IF EXISTS sessions;
            DROP TABLE IF EXISTS users;
            """
        )
        account_tables_before = _account_table_names(conn)
        business_rows_before = _business_rows(conn)

    assert account_tables_before == set()

    db.init_db()

    with db.connect() as conn:
        account_tables_after = _account_table_names(conn)
        business_rows_after = _business_rows(conn)

    assert db.get_project(project["id"]) == project
    assert business_rows_after == business_rows_before
    assert project_file.read_bytes() == b"legacy-business-payload"
    assert settings_path.read_bytes() == settings_bytes
    assert account_tables_after == _ACCOUNT_TABLES


def test_required_off_required_transition_preserves_data_visibility_and_revokes_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db.init_db()
    visible_project = db.insert_project("Member Project", "QA", "")
    hidden_project = db.insert_project("Other Project", "QA", "")
    sentinel = DATA_ROOT / "projects" / visible_project["id"] / "sentinel.bin"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_bytes(b"profile-transition-sentinel")
    sentinel_artifact = db.add_artifact(
        visible_project["id"],
        "Transition sentinel",
        sentinel,
        "uploaded_file",
    )

    required_app = _profile_app(
        monkeypatch,
        deployment_mode="cloud",
        auth_mode="required",
        admin_user="transition-admin",
        admin_password=ADMIN_PASSWORD,
    )
    with TestClient(required_app, base_url="https://testserver") as client:
        admin = db.get_user_by_username("transition-admin")
        assert admin is not None
        db.update_user(admin["id"], {"must_change_password": False})
        member = db.create_user(
            "transition-member",
            auth.hash_password(USER_PASSWORD),
            "member",
            display_name="Transition Member",
        )
        membership = db.add_project_member(
            visible_project["id"],
            member["id"],
            added_by=admin["id"],
        )
        old_token, _session = auth.issue_session(member["id"])
        old_token_hash = auth.hash_token(old_token)
        client.cookies.set(auth.SESSION_COOKIE_NAME, old_token)
        required_projects = client.get("/api/projects")

    assert required_projects.status_code == 200
    assert {item["id"] for item in required_projects.json()} == {
        visible_project["id"],
    }
    assert db.get_session_by_token_hash(old_token_hash) is not None
    with db.connect() as conn:
        business_rows_before = _business_rows(conn)

    off_app = _profile_app(
        monkeypatch,
        deployment_mode="local",
        auth_mode="off",
    )
    with TestClient(off_app) as client:
        off_identity = client.get("/api/auth/me")
        off_projects = client.get("/api/projects")
        off_users = client.get("/api/users")

    assert off_identity.status_code == 200
    assert off_identity.json()["id"] == auth.LOCAL_ADMIN_USER["id"]
    assert off_projects.status_code == 200
    assert {item["id"] for item in off_projects.json()} == {
        visible_project["id"],
        hidden_project["id"],
    }
    assert off_users.status_code == 403
    assert db.get_session_by_token_hash(old_token_hash) is None
    assert db.get_user_by_username("transition-admin") is not None
    assert db.get_user_by_username("transition-member") is not None
    assert db.is_project_member(visible_project["id"], member["id"])
    assert db.list_project_members(visible_project["id"])[0]["created_at"] == membership["created_at"]
    assert db.get_artifact(sentinel_artifact["id"])["path"] == str(sentinel)
    assert sentinel.read_bytes() == b"profile-transition-sentinel"
    with db.connect() as conn:
        assert _business_rows(conn) == business_rows_before

    required_again = _profile_app(
        monkeypatch,
        deployment_mode="cloud",
        auth_mode="required",
    )
    with TestClient(required_again, base_url="https://testserver") as client:
        client.cookies.set(auth.SESSION_COOKIE_NAME, old_token)
        old_session_response = client.get("/api/projects")
        login_response = client.post(
            "/api/auth/login",
            json={
                "username": "transition-member",
                "password": USER_PASSWORD,
            },
        )
        new_session_projects = client.get("/api/projects")

    assert old_session_response.status_code == 401
    assert login_response.status_code == 200
    assert new_session_projects.status_code == 200
    assert {item["id"] for item in new_session_projects.json()} == {
        visible_project["id"],
    }
    assert db.get_project(hidden_project["id"])["name"] == "Other Project"
    assert db.is_project_member(visible_project["id"], member["id"])
    assert db.get_artifact(sentinel_artifact["id"])["path"] == str(sentinel)
    assert sentinel.read_bytes() == b"profile-transition-sentinel"
    with db.connect() as conn:
        assert _business_rows(conn) == business_rows_before

    final_off_app = _profile_app(
        monkeypatch,
        deployment_mode="local",
        auth_mode="off",
    )
    with TestClient(final_off_app) as client:
        final_off_projects = client.get("/api/projects")

    assert final_off_projects.status_code == 200
    assert {item["id"] for item in final_off_projects.json()} == {
        visible_project["id"],
        hidden_project["id"],
    }
    assert db.get_user_by_username("transition-admin") is not None
    assert db.get_user_by_username("transition-member") is not None
    assert db.is_project_member(visible_project["id"], member["id"])
    assert db.list_project_members(visible_project["id"])[0]["created_at"] == membership["created_at"]
    assert db.get_artifact(sentinel_artifact["id"])["path"] == str(sentinel)
    assert sentinel.read_bytes() == b"profile-transition-sentinel"
    with db.connect() as conn:
        assert _business_rows(conn) == business_rows_before
