from __future__ import annotations

from pathlib import Path
from typing import Any

from .languages import visible_language_code


WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def safe_delivery_name(name: Any, *, fallback: str = "project", max_length: int = 120) -> str:
    cleaned = "".join(ch if ch not in '<>:"/\\|?*' else " " for ch in str(name or ""))
    cleaned = " ".join(cleaned.split()).strip(" .")
    if not cleaned:
        cleaned = fallback
    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"{cleaned}_file"
    return cleaned[:max_length].rstrip(" .") or fallback


def safe_filename(name: Any, *, fallback: str = "upload.bin", max_length: int = 180) -> str:
    raw = str(name or fallback)
    suffix = Path(raw).suffix
    stem = Path(raw).stem
    safe_stem = safe_delivery_name(stem, fallback=Path(fallback).stem or "upload", max_length=max_length)
    safe_suffix = "".join(ch for ch in suffix if ch not in '<>:"/\\|?*')
    if safe_suffix and not safe_suffix.startswith("."):
        safe_suffix = f".{safe_suffix}"
    budget = max(1, max_length - len(safe_suffix))
    candidate = f"{safe_stem[:budget].rstrip(' .')}{safe_suffix}"
    if not candidate or candidate.upper() in WINDOWS_RESERVED_NAMES:
        candidate = fallback
    return candidate


def source_stem(value: Any, *, fallback: str = "announcement") -> str:
    return safe_delivery_name(Path(str(value or fallback)).stem, fallback=fallback)


def language_code(value: Any) -> str:
    return visible_language_code(value)
