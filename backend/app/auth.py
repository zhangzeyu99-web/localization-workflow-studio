"""Local password authentication primitives: hashing, sessions, brute-force guard.

Scope for A1 batch 1: pure building blocks (no FastAPI dependency wiring, no
mode switch enforcement). Nothing here changes the behavior of any existing
route -- it is only consumed by the new ``/api/auth/*`` router.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from . import db

SESSION_COOKIE_NAME = "lws_session"
SESSION_TTL_DAYS = 14

LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 600.0
LOGIN_LOCKOUT_SECONDS = 600.0

_password_hasher = PasswordHasher()


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

    ``db.get_session_by_token_hash`` already deletes the row lazily once its
    ``expires_at`` has passed, so no separate cleanup call is needed here.
    """
    if not token:
        return None
    session = db.get_session_by_token_hash(hash_token(token))
    if session is None:
        return None
    try:
        user = db.get_user(session["user_id"])
    except KeyError:
        db.delete_session(session["token_hash"])
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
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self._clock = clock
        self._state: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def key(username: str, client_ip: str) -> str:
        return f"{username}|{client_ip}"

    def locked_seconds_remaining(self, key: str) -> float:
        with self._lock:
            entry = self._state.get(key)
            if not entry or not entry.get("locked_until"):
                return 0.0
            remaining = entry["locked_until"] - self._clock()
            if remaining <= 0:
                self._state.pop(key, None)
                return 0.0
            return remaining

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            entry = self._state.setdefault(key, {"failures": [], "locked_until": None})
            entry["failures"] = [t for t in entry["failures"] if now - t < self.window_seconds] + [now]
            if len(entry["failures"]) >= self.max_failures:
                entry["locked_until"] = now + self.lockout_seconds

    def record_success(self, key: str) -> None:
        with self._lock:
            self._state.pop(key, None)


login_rate_limiter = LoginRateLimiter()
