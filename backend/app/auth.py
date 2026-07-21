"""Local password authentication primitives: hashing, sessions, brute-force guard.

Scope for A1 batch 1: pure building blocks (no FastAPI dependency wiring, no
mode switch enforcement). Nothing here changes the behavior of any existing
route -- it is only consumed by the new ``/api/auth/*`` router.
"""

from __future__ import annotations

import contextvars
import hashlib
import math
import os
import secrets
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from . import db
from .config import RuntimeProfile, current_runtime_profile

SESSION_COOKIE_NAME = "lws_session"
SESSION_TTL_DAYS = 14

LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 600.0
LOGIN_LOCKOUT_SECONDS = 600.0
LOGIN_MAX_TRACKED_KEYS = 4096
REGISTRATION_MAX_ATTEMPTS = 30
REGISTRATION_WINDOW_SECONDS = 600.0
REGISTRATION_MAX_TRACKED_KEYS = 4096

_password_hasher = PasswordHasher()
_current_user_var: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "lws_current_user",
    default=None,
)

LOCAL_ADMIN_USER: dict[str, Any] = {
    "id": "local-admin",
    "username": "local-admin",
    "display_name": "local-admin",
    "role": "admin",
    "status": "active",
    "external_id": "",
    "must_change_password": False,
}


def auth_required(profile: RuntimeProfile | None = None) -> bool:
    """Return the immutable startup profile's authentication policy."""
    return (profile or current_runtime_profile()).auth_required


def set_current_user(user: dict[str, Any] | None) -> None:
    _current_user_var.set(user)


def current_user() -> dict[str, Any] | None:
    return _current_user_var.get()


def bootstrap_initial_admin(*, required: bool | None = None) -> dict[str, Any] | None:
    """Create the first administrator in required mode, or fail closed."""
    enforcement_enabled = auth_required() if required is None else required
    if not enforcement_enabled or db.count_users() > 0:
        return None
    username = os.environ.get("LWS_ADMIN_USER", "").strip()
    password = os.environ.get("LWS_ADMIN_PASSWORD", "")
    if not username or not password:
        raise RuntimeError(
            "认证已开启但 users 表为空；请同时设置 LWS_ADMIN_USER 和 "
            "LWS_ADMIN_PASSWORD，或先运行 scripts/create_admin.py。"
        )
    return db.create_user(
        username,
        hash_password(password),
        "admin",
        display_name=username,
        must_change_password=True,
    )


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Return True iff ``password`` matches ``password_hash``.

    Any malformed/foreign hash or mismatch is treated as "does not match"
    rather than propagating -- callers must not leak hash-format details.
    """
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_session_token() -> str:
    """256-bit random session token; only its SHA-256 hash is ever persisted."""
    return secrets.token_urlsafe(32)


def session_expiry_iso(now: datetime | None = None) -> str:
    base = now or datetime.now(timezone.utc)
    return (base + timedelta(days=SESSION_TTL_DAYS)).isoformat()


def issue_session(user_id: str) -> tuple[str, dict[str, Any]]:
    token = generate_session_token()
    session = db.create_session(user_id, hash_token(token), session_expiry_iso())
    return token, session


def get_user_for_session_token(token: str) -> dict[str, Any] | None:
    """Resolve a raw cookie token to its owning user, or None if invalid/expired/disabled.

    Session validity and the user role/status are read from one SQLite snapshot
    so a revoked old cookie cannot be paired with a newly elevated role.
    """
    if not token:
        return None
    user = db.get_user_by_session_token_hash(hash_token(token))
    if user is None:
        return None
    if user.get("status") == "disabled":
        return None
    return user


def revoke_session(token: str) -> None:
    if not token:
        return
    db.delete_session(hash_token(token))


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    """Fields safe to return to the client -- never includes password_hash."""
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user.get("display_name") or "",
        "role": user["role"],
        "must_change_password": bool(user.get("must_change_password")),
    }


class LoginRateLimiter:
    """In-process sliding-window brute-force guard keyed by ``username+client_ip``.

    Single-instance/SQLite deployment: process memory is sufficient and avoids
    a DB round-trip on every login attempt. Not persisted across restarts,
    which is acceptable since a restart is already an operational event.

    Semantics: >= ``max_failures`` failures within ``window_seconds`` locks the
    key for ``lockout_seconds`` starting from the triggering failure. A
    success clears all tracked state for the key.
    """

    def __init__(
        self,
        max_failures: int = LOGIN_MAX_FAILURES,
        window_seconds: float = LOGIN_WINDOW_SECONDS,
        lockout_seconds: float = LOGIN_LOCKOUT_SECONDS,
        max_keys: int = LOGIN_MAX_TRACKED_KEYS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self.max_keys = max(1, int(max_keys))
        self._clock = clock
        self._state: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def key(username: str, client_ip: str) -> str:
        return f"{username}|{client_ip}"

    def _sweep_stale(self, now: float) -> None:
        retention_seconds = max(self.window_seconds, self.lockout_seconds)
        while self._state:
            _key, entry = next(iter(self._state.items()))
            if now - float(entry["last_failure_at"]) < retention_seconds:
                break
            self._state.popitem(last=False)

    def locked_seconds_remaining(self, key: str) -> float:
        with self._lock:
            now = self._clock()
            self._sweep_stale(now)
            entry = self._state.get(key)
            if not entry or not entry.get("locked_until"):
                return 0.0
            remaining = entry["locked_until"] - now
            if remaining <= 0:
                self._state.pop(key, None)
                return 0.0
            return remaining

    def can_attempt(self, key: str) -> bool:
        with self._lock:
            self._sweep_stale(self._clock())
            return key in self._state or len(self._state) < self.max_keys

    def record_failure(self, key: str) -> bool:
        with self._lock:
            now = self._clock()
            self._sweep_stale(now)
            entry = self._state.pop(key, None)
            if entry is None:
                if len(self._state) >= self.max_keys:
                    return False
                entry = {"failures": [], "locked_until": None, "last_failure_at": now}
            entry["failures"] = [t for t in entry["failures"] if now - t < self.window_seconds] + [now]
            entry["last_failure_at"] = now
            if len(entry["failures"]) >= self.max_failures:
                entry["locked_until"] = now + self.lockout_seconds
            self._state[key] = entry
            return True

    def record_success(self, key: str) -> None:
        with self._lock:
            self._state.pop(key, None)


class RegistrationRateLimiter:
    """Bounded in-process rolling-window limiter keyed only by client IP."""

    def __init__(
        self,
        max_attempts: int = REGISTRATION_MAX_ATTEMPTS,
        window_seconds: float = REGISTRATION_WINDOW_SECONDS,
        max_keys: int = REGISTRATION_MAX_TRACKED_KEYS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_attempts = max(1, int(max_attempts))
        self.window_seconds = float(window_seconds)
        self.max_keys = max(1, int(max_keys))
        self._clock = clock
        self._state: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()

    def _sweep_stale(self, now: float) -> None:
        for key, attempts in list(self._state.items()):
            fresh = [attempt for attempt in attempts if now - attempt < self.window_seconds]
            if fresh:
                self._state[key] = fresh
            else:
                self._state.pop(key, None)

    def _capacity_retry_after(self, now: float) -> int:
        earliest_expiry = min(
            attempts[-1] + self.window_seconds
            for attempts in self._state.values()
            if attempts
        )
        return max(1, math.ceil(earliest_expiry - now))

    def check_and_record(self, client_ip: str) -> int | None:
        """Record an accepted handler attempt, or return integer retry seconds."""
        with self._lock:
            now = self._clock()
            self._sweep_stale(now)
            attempts = self._state.pop(client_ip, None)
            if attempts is None:
                if len(self._state) >= self.max_keys:
                    return self._capacity_retry_after(now)
                attempts = []
            if len(attempts) >= self.max_attempts:
                self._state[client_ip] = attempts
                return max(1, math.ceil(attempts[0] + self.window_seconds - now))
            attempts.append(now)
            self._state[client_ip] = attempts
            return None


login_rate_limiter = LoginRateLimiter()
registration_rate_limiter = RegistrationRateLimiter()
