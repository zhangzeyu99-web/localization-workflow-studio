from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.auth as auth
import app.config as config
import app.db as db
import app.main as main_module
from app.config import DATA_ROOT
from app.operator_context import AUDIT_LOG_FILENAME
from conftest import reset_data_root
import scripts.create_admin as create_admin_module
from scripts.create_admin import create_or_reset_admin

ADMIN_PASSWORD = "Initial-Admin-Password!"
USER_PASSWORD = "Sup3rSecret1!"
LOCAL_OFF_PROFILE = config.RuntimeProfile("local", "off")
LOCAL_REQUIRED_PROFILE = config.RuntimeProfile("local", "required")

USERS_URL = "/api/users"
LOGIN_URL = "/api/auth/login"
ME_URL = "/api/auth/me"
CHANGE_PASSWORD_URL = "/api/auth/change-password"
REGISTER_URL = "/api/auth/register"


def _build_app(profile: config.RuntimeProfile = LOCAL_OFF_PROFILE):
    return main_module.create_app(profile)


_AUTH_ENV_VARS = ("LWS_AUTH_MODE", "LWS_DEPLOYMENT_MODE", "LWS_ADMIN_USER", "LWS_ADMIN_PASSWORD")


@pytest.fixture(autouse=True)
def reset_auth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _AUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    auth.login_rate_limiter._state.clear()  # type: ignore[attr-defined]
    yield
    auth.login_rate_limiter._state.clear()  # type: ignore[attr-defined]
    for name in _AUTH_ENV_VARS:
        os.environ.pop(name, None)


def _required_app(monkeypatch: pytest.MonkeyPatch, *, username: str = "root-admin"):
    monkeypatch.setenv("LWS_ADMIN_USER", username)
    monkeypatch.setenv("LWS_ADMIN_PASSWORD", ADMIN_PASSWORD)
    return _build_app(LOCAL_REQUIRED_PROFILE)


def _login(client: TestClient, username: str, password: str):
    response = client.post(LOGIN_URL, json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response


def _bootstrap_admin_client(client: TestClient, *, username: str = "root-admin") -> None:
    """Log in as the bootstrap admin and clear its forced must_change_password flag.

    Bootstrap (batch 2) always creates the first admin with
    must_change_password=1, which the new batch-3 middleware would otherwise
    block from calling any /api/users endpoint. Tests that exercise admin
    CRUD (rather than the first-login flow itself) need a clean admin.
    """
    _login(client, username, ADMIN_PASSWORD)
    admin = db.get_user_by_username(username)
    assert admin is not None
    db.update_user(admin["id"], {"must_change_password": False})


def _create_user_via_api(
    client: TestClient,
    username: str,
    role: str,
    *,
    password: str = USER_PASSWORD,
    display_name: str | None = None,
) -> dict:
    response = client.post(
        USERS_URL,
        json={
            "username": username,
            "display_name": display_name if display_name is not None else username,
            "role": role,
            "initial_password": password,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# require_admin dependency
# ---------------------------------------------------------------------------


def test_users_api_is_disabled_when_auth_is_off() -> None:
    test_app = _build_app()
    with TestClient(test_app) as client:
        existing = db.create_user(
            "dormant-user",
            auth.hash_password(USER_PASSWORD),
            "member",
        )
        responses = [
            client.get(USERS_URL),
            client.post(
                USERS_URL,
                json={
                    "username": "new-off-user",
                    "display_name": "New Off User",
                    "role": "member",
                    "initial_password": USER_PASSWORD,
                },
            ),
            client.patch(
                f"{USERS_URL}/{existing['id']}",
                json={"role": "ops"},
            ),
            client.post(
                f"{USERS_URL}/{existing['id']}/reset-password",
                json={"initial_password": "Replacement-Pass1!"},
            ),
        ]

    for response in responses:
        assert response.status_code == 403, response.text
        assert response.json() == {"detail": "当前模式未启用账号功能"}
    assert db.get_user_by_username("new-off-user") is None
    assert db.get_user(existing["id"])["role"] == "member"


def test_anonymous_request_gets_401_on_users_api(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as client:
        response = client.get(USERS_URL)
    assert response.status_code == 401


def test_non_admin_roles_get_403_on_users_api(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        _create_user_via_api(admin_client, "ops-user", "ops")
        _create_user_via_api(admin_client, "member-user", "member")
        # Newly-created accounts also carry must_change_password=1; clear it
        # so this test exercises the role check (403 "需要管理员权限") rather
        # than the unrelated first-login gate (403 "首次登录请先修改密码"),
        # which has its own dedicated coverage.
        for username in ("ops-user", "member-user"):
            user = db.get_user_by_username(username)
            db.update_user(user["id"], {"must_change_password": False})

    for username, role in (("ops-user", "ops"), ("member-user", "member")):
        with TestClient(test_app) as client:
            _login(client, username, USER_PASSWORD)
            response = client.get(USERS_URL)
        assert response.status_code == 403, f"{role} should be forbidden: {response.text}"
        assert response.json() == {"detail": "需要管理员权限"}


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_create_user_success_forces_password_change(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as client:
        _bootstrap_admin_client(client)
        created = _create_user_via_api(client, "new-member", "member", display_name="New Member")

    assert created["username"] == "new-member"
    assert created["display_name"] == "New Member"
    assert created["role"] == "member"
    assert created["status"] == "active"
    assert created["must_change_password"] is True
    assert "password_hash" not in created
    assert "password" not in created
    assert created["created_at"]


def test_create_user_duplicate_username_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as client:
        _bootstrap_admin_client(client)
        _create_user_via_api(client, "dup-user", "member")
        response = client.post(
            USERS_URL,
            json={"username": "dup-user", "role": "member", "initial_password": USER_PASSWORD},
        )
    assert response.status_code == 409, response.text


def test_admin_create_user_case_variant_duplicate_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as client:
        _bootstrap_admin_client(client)
        _create_user_via_api(client, "AdminCase", "member")
        response = client.post(
            USERS_URL,
            json={"username": "admincase", "role": "member", "initial_password": USER_PASSWORD},
        )

    assert response.status_code == 409, response.text
    assert sum(user["username"].casefold() == "admincase" for user in db.list_users()) == 1


def test_self_registered_user_appears_in_admin_list_with_account_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as anonymous_client:
        registration = anonymous_client.post(
            REGISTER_URL,
            json={"username": "listed-registration", "password": USER_PASSWORD},
        )
    assert registration.status_code == 201, registration.text

    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        response = admin_client.get(USERS_URL)

    assert response.status_code == 200, response.text
    registered = next(user for user in response.json() if user["username"] == "listed-registration")
    assert registered["id"] == registration.json()["id"]
    assert registered["role"] == "member"
    assert registered["status"] == "active"
    assert registered["must_change_password"] is False
    assert registered["created_at"]
    assert registered["last_login_at"] is None


def test_list_users_orders_newest_registration_first_with_stable_id_tiebreak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        older = _create_user_via_api(admin_client, "older-user", "member")
        tied_a = _create_user_via_api(admin_client, "tied-user-a", "member")
        tied_b = _create_user_via_api(admin_client, "tied-user-b", "member")
        admin = db.get_user_by_username("root-admin")
        assert admin is not None

        with db.connect() as conn:
            conn.execute(
                "UPDATE users SET created_at = ? WHERE id = ?",
                ("2026-01-01T00:00:00+00:00", admin["id"]),
            )
            conn.execute(
                "UPDATE users SET created_at = ? WHERE id = ?",
                ("2026-02-01T00:00:00+00:00", older["id"]),
            )
            conn.executemany(
                "UPDATE users SET created_at = ? WHERE id = ?",
                [
                    ("2026-03-01T00:00:00+00:00", tied_a["id"]),
                    ("2026-03-01T00:00:00+00:00", tied_b["id"]),
                ],
            )

        response = admin_client.get(USERS_URL)

    assert response.status_code == 200, response.text
    tied_ids = sorted((tied_a["id"], tied_b["id"]), reverse=True)
    assert [user["id"] for user in response.json()] == [*tied_ids, older["id"], admin["id"]]


def test_create_admin_cli_case_variant_conflict_exits_cleanly_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db.init_db()
    db.create_user(
        "CliCase",
        auth.hash_password("Existing-Pass1!"),
        "member",
        display_name="CliCase",
    )
    monkeypatch.setenv("LWS_ADMIN_PASSWORD", "Replacement-Pass1!")
    monkeypatch.setattr(sys, "argv", ["create_admin.py", "--username", "clicase"])

    with pytest.raises(SystemExit) as exc_info:
        create_admin_module.main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "已存在" in captured.err
    assert "Traceback" not in captured.err
    assert sum(user["username"].casefold() == "clicase" for user in db.list_users()) == 1


def test_create_user_invalid_role_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as client:
        _bootstrap_admin_client(client)
        response = client.post(
            USERS_URL,
            json={"username": "weird-role", "role": "superadmin", "initial_password": USER_PASSWORD},
        )
    assert response.status_code == 422, response.text


def test_create_user_rejects_username_longer_than_login_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as client:
        _bootstrap_admin_client(client)
        response = client.post(
            USERS_URL,
            json={"username": "u" * 129, "role": "member", "initial_password": USER_PASSWORD},
        )
    assert response.status_code == 422, response.text


def test_list_users_never_exposes_password_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as client:
        _bootstrap_admin_client(client)
        _create_user_via_api(client, "listed-user", "ops")
        response = client.get(USERS_URL)

    assert response.status_code == 200, response.text
    body = response.json()
    usernames = {user["username"] for user in body}
    assert {"root-admin", "listed-user"} <= usernames
    for user in body:
        assert "password_hash" not in user
        assert "password" not in user
        assert "status" in user
        assert "created_at" in user
        assert "last_login_at" in user


def test_update_user_role_and_status(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as client:
        _bootstrap_admin_client(client)
        created = _create_user_via_api(client, "promote-me", "member")

        promoted = client.patch(f"{USERS_URL}/{created['id']}", json={"role": "ops"})
        assert promoted.status_code == 200, promoted.text
        assert promoted.json()["role"] == "ops"

        disabled = client.patch(f"{USERS_URL}/{created['id']}", json={"status": "disabled", "display_name": "Disabled Ops"})
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["status"] == "disabled"
        assert disabled.json()["display_name"] == "Disabled Ops"


def test_role_change_revokes_existing_sessions_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        created = _create_user_via_api(admin_client, "role-change-user", "ops")

        with TestClient(test_app) as user_client:
            _login(user_client, "role-change-user", USER_PASSWORD)
            assert user_client.get(ME_URL).status_code == 200

            update_response = admin_client.patch(
                f"{USERS_URL}/{created['id']}", json={"role": "member"}
            )
            assert update_response.status_code == 200, update_response.text

            assert user_client.get(ME_URL).status_code == 401


def test_create_admin_cli_revokes_existing_session_when_promoting_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        _create_user_via_api(admin_client, "cli-promote-user", "member")

        with TestClient(test_app) as user_client:
            _login(user_client, "cli-promote-user", USER_PASSWORD)
            assert user_client.get(ME_URL).status_code == 200

            updated, created = create_or_reset_admin("cli-promote-user", "Promoted-Admin-Pass1!")

            assert created is False
            assert updated["role"] == "admin"
            assert user_client.get(ME_URL).status_code == 401


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("u" * 129, "Valid-Admin-Pass1!"),
        ("valid-admin", "short"),
    ],
)
def test_create_admin_cli_rejects_credentials_outside_web_limits(
    monkeypatch: pytest.MonkeyPatch,
    username: str,
    password: str,
) -> None:
    _required_app(monkeypatch)
    with pytest.raises(ValueError):
        create_or_reset_admin(username, password)


def test_admin_cannot_demote_self(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as client:
        _bootstrap_admin_client(client)
        admin = db.get_user_by_username("root-admin")
        response = client.patch(f"{USERS_URL}/{admin['id']}", json={"role": "member"})
    assert response.status_code == 400, response.text


def test_admin_cannot_disable_self(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as client:
        _bootstrap_admin_client(client)
        admin = db.get_user_by_username("root-admin")
        response = client.patch(f"{USERS_URL}/{admin['id']}", json={"status": "disabled"})
    assert response.status_code == 400, response.text


def test_disabling_user_revokes_existing_sessions_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        created = _create_user_via_api(admin_client, "soon-disabled", "member")

        with TestClient(test_app) as member_client:
            _login(member_client, "soon-disabled", USER_PASSWORD)
            still_active = member_client.get(ME_URL)
            assert still_active.status_code == 200, still_active.text

            disable_response = admin_client.patch(f"{USERS_URL}/{created['id']}", json={"status": "disabled"})
            assert disable_response.status_code == 200, disable_response.text

            after_disable = member_client.get(ME_URL)
            assert after_disable.status_code == 401, after_disable.text


def test_reset_password_invalidates_old_password_and_old_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        created = _create_user_via_api(admin_client, "reset-me", "member", password="Original-Pass1!")

        with TestClient(test_app) as member_client:
            _login(member_client, "reset-me", "Original-Pass1!")
            assert member_client.get(ME_URL).status_code == 200

            reset_response = admin_client.post(
                f"{USERS_URL}/{created['id']}/reset-password",
                json={"initial_password": "Brand-New-Pass1!"},
            )
            assert reset_response.status_code == 200, reset_response.text
            assert reset_response.json()["must_change_password"] is True

            # Pre-reset session is dead even though the cookie is still sent.
            assert member_client.get(ME_URL).status_code == 401

        with TestClient(test_app) as relogin_client:
            old_password_attempt = relogin_client.post(
                LOGIN_URL, json={"username": "reset-me", "password": "Original-Pass1!"}
            )
            assert old_password_attempt.status_code == 401

            new_password_attempt = relogin_client.post(
                LOGIN_URL, json={"username": "reset-me", "password": "Brand-New-Pass1!"}
            )
            assert new_password_attempt.status_code == 200, new_password_attempt.text
            assert new_password_attempt.json()["must_change_password"] is True


# ---------------------------------------------------------------------------
# change-password + first-login enforcement
# ---------------------------------------------------------------------------


def test_first_login_must_change_password_blocks_business_api(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        _create_user_via_api(admin_client, "fresh-member", "member")

    with TestClient(test_app) as client:
        _login(client, "fresh-member", USER_PASSWORD)

        blocked = client.get("/api/projects")
        assert blocked.status_code == 403
        assert blocked.json() == {"detail": "首次登录请先修改密码"}

        me_response = client.get(ME_URL)
        assert me_response.status_code == 200

        change_response = client.post(
            CHANGE_PASSWORD_URL,
            json={"current_password": USER_PASSWORD, "new_password": "New-Strong-Pass1!"},
        )
        assert change_response.status_code == 200, change_response.text

        allowed_now = client.get("/api/projects")
        assert allowed_now.status_code == 200, allowed_now.text

        logout_response = client.post("/api/auth/logout")
        assert logout_response.status_code == 200


def test_change_password_success_rotates_session_and_clears_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        _create_user_via_api(admin_client, "rotate-me", "member")

    with TestClient(test_app) as client:
        _login(client, "rotate-me", USER_PASSWORD)
        old_cookie = client.cookies.get(auth.SESSION_COOKIE_NAME)
        assert old_cookie

        response = client.post(
            CHANGE_PASSWORD_URL,
            json={"current_password": USER_PASSWORD, "new_password": "New-Strong-Pass1!"},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"ok": True}

        new_cookie = client.cookies.get(auth.SESSION_COOKIE_NAME)
        assert new_cookie and new_cookie != old_cookie

        # The old token is dead even if a client tries to keep using it.
        client.cookies.set(auth.SESSION_COOKIE_NAME, old_cookie)
        assert client.get(ME_URL).status_code == 401

        # The freshly-issued token works.
        client.cookies.set(auth.SESSION_COOKIE_NAME, new_cookie)
        me_response = client.get(ME_URL)
        assert me_response.status_code == 200, me_response.text
        assert me_response.json()["must_change_password"] is False

        user = db.get_user_by_username("rotate-me")
        assert auth.verify_password(user["password_hash"], "New-Strong-Pass1!")


def test_change_password_wrong_current_password_returns_400(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        _create_user_via_api(admin_client, "wrong-current", "member")

    with TestClient(test_app) as client:
        _login(client, "wrong-current", USER_PASSWORD)
        response = client.post(
            CHANGE_PASSWORD_URL,
            json={"current_password": "totally-wrong", "new_password": "New-Strong-Pass1!"},
        )
    assert response.status_code == 400, response.text


def test_change_password_weak_new_password_returns_400(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        _create_user_via_api(admin_client, "weak-new", "member")

    with TestClient(test_app) as client:
        _login(client, "weak-new", USER_PASSWORD)
        response = client.post(
            CHANGE_PASSWORD_URL,
            json={"current_password": USER_PASSWORD, "new_password": "short"},
        )
    assert response.status_code == 400, response.text

    # must_change_password must remain untouched after a rejected attempt.
    user = db.get_user_by_username("weak-new")
    assert user["must_change_password"] is True


def test_change_password_rejects_reusing_current_password(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        _create_user_via_api(admin_client, "reuse-current", "member")

    with TestClient(test_app) as client:
        _login(client, "reuse-current", USER_PASSWORD)
        response = client.post(
            CHANGE_PASSWORD_URL,
            json={"current_password": USER_PASSWORD, "new_password": USER_PASSWORD},
        )

    assert response.status_code == 400, response.text
    user = db.get_user_by_username("reuse-current")
    assert user["must_change_password"] is True


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


def test_admin_and_password_actions_are_audited_without_leaking_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    test_app = _required_app(monkeypatch)
    audit_path = DATA_ROOT / AUDIT_LOG_FILENAME

    with TestClient(test_app) as admin_client:
        _bootstrap_admin_client(admin_client)
        created = _create_user_via_api(admin_client, "audited-user", "member", password="Audited-Pass1!")
        admin_client.patch(f"{USERS_URL}/{created['id']}", json={"role": "ops"})
        admin_client.post(f"{USERS_URL}/{created['id']}/reset-password", json={"initial_password": "Reset-Pass123!"})

        with TestClient(test_app) as member_client:
            _login(member_client, "audited-user", "Reset-Pass123!")
            member_client.post(
                CHANGE_PASSWORD_URL,
                json={"current_password": "Reset-Pass123!", "new_password": "Final-Pass1234!"},
            )

    raw_log = audit_path.read_text(encoding="utf-8")
    for secret in ("Audited-Pass1!", "Reset-Pass123!", "Final-Pass1234!", "totally-wrong"):
        assert secret not in raw_log

    entries = [json.loads(line) for line in raw_log.splitlines()]
    actions = [entry["action"] for entry in entries]
    assert "create_user" in actions
    assert "update_user" in actions
    assert "reset_password" in actions
    assert "change_password" in actions
    for entry in entries:
        assert "password_hash" not in json.dumps(entry)
