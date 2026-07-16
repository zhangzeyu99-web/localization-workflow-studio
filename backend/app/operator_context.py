"""Unauthenticated operator attribution for a small shared team.

There is no account/session system in this product (see docs/superpowers/plans
/2026-07-08-multiuser-concurrency.md). This module only lets a browser-local
nickname (sent as the ``X-Operator`` request header) show up next to key
actions so a team can tell who did what. Cloud AI task starts require a
nickname, but it still performs no identity validation and grants no
permissions.

The current request's operator name is exposed through a ``contextvars``
context set by ``OperatorContextMiddleware`` in ``main.py``. FastAPI/Starlette
propagate the request's context into the thread pool used for synchronous
``def`` route handlers (verified: ``contextvars.copy_context()`` is applied by
anyio's ``to_thread.run_sync``), so ``current_operator()`` works from both
sync and async endpoints without threading an extra parameter through every
call site.
"""

from __future__ import annotations

import contextvars
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import HTTPException

_MAX_OPERATOR_LENGTH = 40
_CONTROL_CHARS = re.compile(r"[\r\n\t\x00-\x1f]")

_operator_var: contextvars.ContextVar[str] = contextvars.ContextVar("lws_operator_name", default="")

AUDIT_LOG_FILENAME = "operator_audit.log"


def sanitize_operator_name(value: Any) -> str:
    text = _CONTROL_CHARS.sub("", str(value or "")).strip()
    return text[:_MAX_OPERATOR_LENGTH]


def set_current_operator(value: Any) -> None:
    raw_value = str(value or "")
    try:
        decoded_value = unquote(raw_value, encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        decoded_value = raw_value
    _operator_var.set(sanitize_operator_name(decoded_value))


def current_operator() -> str:
    return _operator_var.get()


def require_operator_for_cloud() -> str:
    from .config import DATA_ROOT

    app_root = Path(__file__).resolve().parents[2]
    raw_mode = os.environ.get("LWS_DEPLOYMENT_MODE")
    if raw_mode is None and (
        str(DATA_ROOT).replace("\\", "/").startswith("/data/web/")
        or str(app_root).replace("\\", "/").startswith("/data/web/")
    ):
        raw_mode = "cloud"
    if (raw_mode or "local").strip().lower() == "cloud" and not current_operator():
        raise HTTPException(status_code=400, detail="请先设置操作人昵称，再启动 AI 任务。")
    return current_operator()


def prefixed_message(message: str, operator: str | None = None) -> str:
    name = sanitize_operator_name(operator) if operator is not None else current_operator()
    return f"[{name}] {message}" if name else message


def record_operator_audit(data_root: Path, action: str, detail: dict[str, Any] | None = None) -> None:
    """Append-only audit trail for actions that do not have a durable
    per-run event sink -- most notably project deletion, which cascades to
    delete that project's own run events in the same transaction, so logging
    to ``db.add_event`` there would be immediately erased.

    No-ops when no operator nickname is set for the current request.
    """
    operator = current_operator()
    if not operator:
        return
    data_root.mkdir(parents=True, exist_ok=True)
    entry: dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "operator": operator,
        "action": action,
    }
    if detail:
        entry["detail"] = detail
    path = data_root / AUDIT_LOG_FILENAME
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
