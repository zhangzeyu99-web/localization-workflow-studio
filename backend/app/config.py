from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("LWS_DATA_ROOT", r"D:\codex\localization-workflow-studio-data"))
LOCALIZATION_ROOT = REPO_ROOT / "workflow" / "localization"
GLOSSARY_ROOT = REPO_ROOT / "workflow" / "glossary"
SETTINGS_PATH = DATA_ROOT / "settings.local.json"
SETTINGS_EXAMPLE_PATH = REPO_ROOT / "settings.example.json"
DB_PATH = DATA_ROOT / "studio.sqlite3"


REAL_PROVIDERS = {"openai", "openai-chat", "anthropic"}
TEST_FAKE_PROVIDER = "test-fake"
LEGACY_TEST_PROVIDER_NAMES = {TEST_FAKE_PROVIDER}


_API_KEY_PATTERNS = (
    re.compile(r"(?im)^\s*(?:api\s*key|key|token|密钥|令牌)\s*[:：]\s*([A-Za-z0-9][A-Za-z0-9._-]{10,})\s*$"),
    re.compile(r"\b(sk-ant-[A-Za-z0-9._-]{10,}|sk-[A-Za-z0-9._-]{10,}|cr_[A-Za-z0-9._-]{10,})\b"),
)
_BASE_URL_PATTERN = re.compile(r"https?://[^\s，,]+", re.I)


def normalize_api_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text == "configured":
        return ""
    if "\n" not in text and "\r" not in text and all(ord(ch) < 128 for ch in text):
        return text
    for pattern in _API_KEY_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            return str(matches[-1]).strip()
    return text


def extract_base_url(value: Any) -> str:
    text = str(value or "")
    matches = _BASE_URL_PATTERN.findall(text)
    return matches[-1].rstrip("/") if matches else ""


def test_provider_enabled() -> bool:
    return str(os.environ.get("LWS_ENABLE_TEST_PROVIDER") or "").lower() in {"1", "true", "yes"}


def normalize_provider_name(value: Any, *, allow_test_provider: bool | None = None) -> str:
    provider = str(value or DEFAULT_SETTINGS["provider"]).strip()
    if provider == "openai-compatible":
        provider = "openai"
    if provider == "codex-relay":
        provider = "openai-chat"
    allow_test = test_provider_enabled() if allow_test_provider is None else allow_test_provider
    if provider in LEGACY_TEST_PROVIDER_NAMES and allow_test:
        return TEST_FAKE_PROVIDER
    if provider in REAL_PROVIDERS:
        return provider
    return str(DEFAULT_SETTINGS["provider"])


DEFAULT_SETTINGS: dict[str, Any] = {
    "provider": "openai",
    "preset": "balanced",
    "protocol": "responses",
    "base_url": "https://api.openai.com",
    "api_key": "",
    "model": "gpt-5.5",
    "reasoning_effort": "medium",
    "max_output_tokens": 8192,
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
    "critical": {
        "batch_size": 40,
        "max_concurrent_batches": 1,
        "max_requests_per_minute": 6,
        "max_estimated_tokens_per_minute": 70000,
        "max_batch_input_tokens": 16000,
        "max_project_context_tokens": 8000,
        "api_budget_warning_tokens": 2000000,
        "max_batch_attempts": 3,
        "provider_timeout_seconds": 240,
    },
}


PROVIDER_PRESETS: dict[str, dict[str, dict[str, str | int | None]]] = {
    "openai": {
        "fast": {"label": "快速", "model": "gpt-5.4-mini", "reasoning_effort": "low", "base_url": "https://api.openai.com", "max_output_tokens": 8192},
        "balanced": {"label": "平衡", "model": "gpt-5.5", "reasoning_effort": "medium", "base_url": "https://api.openai.com", "max_output_tokens": 8192},
        "deep": {"label": "深度", "model": "gpt-5.5-pro", "reasoning_effort": "high", "base_url": "https://api.openai.com", "max_output_tokens": 16384},
        "critical": {"label": "关键校对", "model": "gpt-5.5-pro", "reasoning_effort": "xhigh", "base_url": "https://api.openai.com", "max_output_tokens": 16384},
    },
    "openai-chat": {
        "fast": {"label": "快速", "model": "gpt-5.5", "reasoning_effort": "medium", "base_url": "", "max_output_tokens": 8192},
        "balanced": {"label": "平衡", "model": "gpt-5.5", "reasoning_effort": "medium", "base_url": "", "max_output_tokens": 8192},
        "deep": {"label": "深度", "model": "gpt-5.5", "reasoning_effort": "high", "base_url": "", "max_output_tokens": 16384},
        "critical": {"label": "关键校对", "model": "gpt-5.5", "reasoning_effort": "xhigh", "base_url": "", "max_output_tokens": 16384},
    },
    "anthropic": {
        "fast": {"label": "快速", "model": "claude-haiku-4-5-20251001", "reasoning_effort": "none", "base_url": "https://api.anthropic.com", "max_output_tokens": 8192},
        "balanced": {"label": "平衡", "model": "claude-sonnet-4-6", "reasoning_effort": "adaptive", "base_url": "https://api.anthropic.com", "max_output_tokens": 8192},
        "deep": {"label": "深度", "model": "claude-opus-4-7", "reasoning_effort": "adaptive", "base_url": "https://api.anthropic.com", "max_output_tokens": 16384},
        "critical": {"label": "关键校对", "model": "claude-opus-4-7", "reasoning_effort": "adaptive", "base_url": "https://api.anthropic.com", "max_output_tokens": 16384},
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
    provider = normalize_provider_name(payload.get("provider"))
    payload["provider"] = provider
    raw_api_key = payload.get("api_key") or ""
    extracted_base_url = extract_base_url(raw_api_key)
    raw_base_url = payload.get("base_url") or ""
    normalized_base_url = extract_base_url(raw_base_url) or str(raw_base_url).strip()
    payload["api_key"] = normalize_api_key(raw_api_key)
    if provider == TEST_FAKE_PROVIDER:
        payload["preset"] = payload.get("preset") or "balanced"
        payload["model"] = payload.get("model") or "test-fake-localization"
        payload["reasoning_effort"] = "none"
        payload["protocol"] = TEST_FAKE_PROVIDER
        _normalize_long_text_settings(payload)
        return payload

    preset = str(payload.get("preset") or DEFAULT_SETTINGS["preset"])
    if preset not in PROVIDER_PRESETS[provider]:
        preset = str(DEFAULT_SETTINGS["preset"])
    selected = PROVIDER_PRESETS[provider][preset]
    payload["preset"] = preset
    if provider == "openai-chat":
        payload["model"] = str(payload.get("model") or selected["model"]).strip()
        payload["reasoning_effort"] = str(payload.get("reasoning_effort") or selected["reasoning_effort"]).strip()
        payload["base_url"] = str(normalized_base_url or extracted_base_url or selected["base_url"]).rstrip("/")
        payload["max_output_tokens"] = int(selected["max_output_tokens"] or 8192)
    else:
        payload["model"] = selected["model"]
        payload["reasoning_effort"] = selected["reasoning_effort"]
        payload["base_url"] = selected["base_url"]
        payload["max_output_tokens"] = selected["max_output_tokens"]
    payload["protocol"] = "chat-completions" if provider == "openai-chat" else ("responses" if provider == "openai" else "messages")
    _normalize_long_text_settings(payload)
    return payload


def _normalize_long_text_settings(payload: dict[str, Any]) -> None:
    preset = str(payload.get("preset") or DEFAULT_SETTINGS["preset"])
    profile = LONG_TEXT_PRESET_DEFAULTS.get(preset, LONG_TEXT_PRESET_DEFAULTS["balanced"])
    for key, value in profile.items():
        payload[key] = value

