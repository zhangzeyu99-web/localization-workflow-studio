from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import auth, db  # noqa: E402

MAX_USERNAME_LENGTH = 128
MIN_PASSWORD_LENGTH = 8


def _read_password() -> str:
    from_environment = os.environ.get("LWS_ADMIN_PASSWORD")
    if from_environment:
        return from_environment
    password = getpass.getpass("管理员密码: ")
    confirmation = getpass.getpass("再次输入管理员密码: ")
    if password != confirmation:
        raise ValueError("两次输入的密码不一致")
    if not password:
        raise ValueError("管理员密码不能为空")
    return password


def create_or_reset_admin(username: str, password: str) -> tuple[dict, bool]:
    db.init_db()
    normalized_username = username.strip()
    if not normalized_username:
        raise ValueError("用户名不能为空")
    if len(normalized_username) > MAX_USERNAME_LENGTH:
        raise ValueError(f"用户名不能超过 {MAX_USERNAME_LENGTH} 个字符")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"管理员密码至少 {MIN_PASSWORD_LENGTH} 位")
    existing = db.get_user_by_username(normalized_username)
    updates = {
        "password_hash": auth.hash_password(password),
        "role": "admin",
        "status": "active",
        "must_change_password": True,
    }
    if existing is not None:
        updated = db.update_user(existing["id"], updates, revoke_sessions=True)
        return updated, False
    return (
        db.create_user(
            normalized_username,
            updates["password_hash"],
            "admin",
            display_name=normalized_username,
            must_change_password=True,
        ),
        True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="直接在 Studio 数据库中创建或重置管理员账号。",
    )
    parser.add_argument("--username", required=True, help="要创建或重置的管理员用户名")
    args = parser.parse_args()
    try:
        user, created = create_or_reset_admin(args.username, _read_password())
    except ValueError as exc:
        parser.error(str(exc))
    action = "已创建" if created else "已重置"
    print(f"{action}管理员：{user['username']}（首次登录后必须修改密码）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
