from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..delivery_naming import safe_delivery_name, source_stem
from ..languages import visible_language_code


def _safe_delivery_name(name: str) -> str:
    return safe_delivery_name(name)


def _safe_source_stem(value: Any) -> str:
    return source_stem(value, fallback="announcement")


def _visible_language_code(language: Any) -> str:
    return visible_language_code(language)


def _today_stamp() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
