from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("LWS_DATA_ROOT", r"D:\codex\localization-workflow-studio-data"))
LOCALIZATION_ROOT = REPO_ROOT / "workflow" / "localization"
GLOSSARY_ROOT = REPO_ROOT / "workflow" / "glossary"
SETTINGS_PATH = DATA_ROOT / "settings.local.json"
SETTINGS_EXAMPLE_PATH = REPO_ROOT / "settings.example.json"
DB_PATH = DATA_ROOT / "studio.sqlite3"


DEFAULT_SETTINGS: dict[str, Any] = {
    "provider": "mock",
    "protocol": "chat-completions",
    "base_url": "https://api.openai.com",
    "api_key": "",
    "model": "gpt-4.1-mini",
    "batch_size": 90,
    "multimodal": {
        "images": True,
        "pdf": True,
        "video": False,
        "audio": False,
    },
}


def ensure_data_dirs() -> None:
    for subdir in ("projects", "runs", "artifacts", "uploads"):
        (DATA_ROOT / subdir).mkdir(parents=True, exist_ok=True)


def load_settings() -> dict[str, Any]:
    ensure_data_dirs()
    if not SETTINGS_PATH.exists():
        save_settings(DEFAULT_SETTINGS)
        return dict(DEFAULT_SETTINGS)
    payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    merged = dict(DEFAULT_SETTINGS)
    merged.update(payload)
    merged["multimodal"] = {**DEFAULT_SETTINGS["multimodal"], **payload.get("multimodal", {})}
    return merged


def save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    ensure_data_dirs()
    sanitized = dict(DEFAULT_SETTINGS)
    sanitized.update(settings)
    sanitized["multimodal"] = {**DEFAULT_SETTINGS["multimodal"], **settings.get("multimodal", {})}
    SETTINGS_PATH.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8")
    return sanitized


def public_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(settings or load_settings())
    payload["api_key"] = "configured" if payload.get("api_key") else ""
    payload["settings_path"] = str(SETTINGS_PATH)
    payload["data_root"] = str(DATA_ROOT)
    return payload

