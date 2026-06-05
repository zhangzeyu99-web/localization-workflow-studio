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
    "provider": "openai",
    "preset": "balanced",
    "protocol": "responses",
    "base_url": "https://api.openai.com",
    "api_key": "",
    "model": "gpt-5.5",
    "reasoning_effort": "medium",
    "batch_size": 90,
    "max_concurrent_batches": 2,
    "max_requests_per_minute": 12,
    "max_estimated_tokens_per_minute": 120000,
    "max_batch_input_tokens": 12000,
    "max_project_context_tokens": 6000,
    "max_quick_reference_context_tokens": 2000,
    "api_budget_warning_tokens": 1000000,
    "max_batch_attempts": 3,
    "provider_timeout_seconds": 120,
    "multimodal": {
        "images": True,
        "pdf": True,
        "video": False,
        "audio": False,
    },
}

LONG_TEXT_PRESET_DEFAULTS: dict[str, dict[str, int]] = {
    "fast": {
        "batch_size": 100,
        "max_concurrent_batches": 2,
        "max_requests_per_minute": 16,
        "max_estimated_tokens_per_minute": 160000,
        "max_batch_input_tokens": 10000,
        "max_project_context_tokens": 4000,
        "api_budget_warning_tokens": 800000,
        "max_batch_attempts": 2,
        "provider_timeout_seconds": 120,
    },
    "balanced": {
        "batch_size": 90,
        "max_concurrent_batches": 2,
        "max_requests_per_minute": 12,
        "max_estimated_tokens_per_minute": 120000,
        "max_batch_input_tokens": 12000,
        "max_project_context_tokens": 6000,
        "api_budget_warning_tokens": 1000000,
        "max_batch_attempts": 3,
        "provider_timeout_seconds": 120,
    },
    "deep": {
        "batch_size": 60,
        "max_concurrent_batches": 1,
        "max_requests_per_minute": 8,
        "max_estimated_tokens_per_minute": 90000,
        "max_batch_input_tokens": 16000,
        "max_project_context_tokens": 8000,
        "api_budget_warning_tokens": 1500000,
        "max_batch_attempts": 3,
        "provider_timeout_seconds": 180,
    },
}

PROVIDER_PRESETS: dict[str, dict[str, dict[str, str | int | None]]] = {
    "openai": {
        "fast": {
            "label": "快速响应",
            "model": "gpt-5.4-mini",
            "reasoning_effort": "low",
            "base_url": "https://api.openai.com",
            "max_output_tokens": 8192,
        },
        "balanced": {
            "label": "平衡",
            "model": "gpt-5.5",
            "reasoning_effort": "medium",
            "base_url": "https://api.openai.com",
            "max_output_tokens": 8192,
        },
        "deep": {
            "label": "深度思考",
            "model": "gpt-5.5-pro",
            "reasoning_effort": "high",
            "base_url": "https://api.openai.com",
            "max_output_tokens": 16384,
        },
    },
    "anthropic": {
        "fast": {
            "label": "快速响应",
            "model": "claude-haiku-4-5-20251001",
            "reasoning_effort": "none",
            "base_url": "https://api.anthropic.com",
            "max_output_tokens": 8192,
        },
        "balanced": {
            "label": "平衡",
            "model": "claude-sonnet-4-6",
            "reasoning_effort": "adaptive",
            "base_url": "https://api.anthropic.com",
            "max_output_tokens": 8192,
        },
        "deep": {
            "label": "深度思考",
            "model": "claude-opus-4-7",
            "reasoning_effort": "adaptive",
            "base_url": "https://api.anthropic.com",
            "max_output_tokens": 16384,
        },
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
    return normalize_settings(merged)


def save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    ensure_data_dirs()
    sanitized = dict(DEFAULT_SETTINGS)
    sanitized.update(settings)
    sanitized["multimodal"] = {**DEFAULT_SETTINGS["multimodal"], **settings.get("multimodal", {})}
    sanitized = normalize_settings(sanitized)
    SETTINGS_PATH.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8")
    return sanitized


def public_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(settings or load_settings())
    payload["api_key"] = "configured" if payload.get("api_key") else ""
    payload["settings_path"] = str(SETTINGS_PATH)
    payload["data_root"] = str(DATA_ROOT)
    payload["provider_presets"] = PROVIDER_PRESETS
    return payload


def normalize_settings(settings: dict[str, Any]) -> dict[str, Any]:
    payload = dict(settings)
    provider = str(payload.get("provider") or DEFAULT_SETTINGS["provider"])
    if provider == "openai-compatible":
        provider = "openai"
    if provider not in {"openai", "anthropic", "mock"}:
        provider = str(DEFAULT_SETTINGS["provider"])
    payload["provider"] = provider
    if provider == "mock":
        payload["preset"] = payload.get("preset") or "balanced"
        payload["model"] = payload.get("model") or "mock-localization"
        payload["reasoning_effort"] = "none"
        payload["protocol"] = "mock"
        _normalize_long_text_settings(payload)
        return payload

    preset = str(payload.get("preset") or DEFAULT_SETTINGS["preset"])
    if preset not in PROVIDER_PRESETS[provider]:
        preset = str(DEFAULT_SETTINGS["preset"])
    selected = PROVIDER_PRESETS[provider][preset]
    payload["preset"] = preset
    payload["model"] = selected["model"]
    payload["reasoning_effort"] = selected["reasoning_effort"]
    payload["base_url"] = selected["base_url"]
    payload["max_output_tokens"] = selected["max_output_tokens"]
    payload["protocol"] = "responses" if provider == "openai" else "messages"
    _normalize_long_text_settings(payload)
    return payload


def _normalize_long_text_settings(payload: dict[str, Any]) -> None:
    preset = str(payload.get("preset") or DEFAULT_SETTINGS["preset"])
    profile = LONG_TEXT_PRESET_DEFAULTS.get(preset, LONG_TEXT_PRESET_DEFAULTS["balanced"])
    for key, value in profile.items():
        payload[key] = value
