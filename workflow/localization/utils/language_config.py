"""Shared language metadata for workbook localization workflows."""
from __future__ import annotations

from typing import Iterable


SUPPORTED_TRANSLATION_LANGUAGES = ("en", "th", "vi", "idn", "ko", "ja")

LANGUAGE_NAMES = {
    "en": "English",
    "th": "Thai",
    "vi": "Vietnamese",
    "idn": "Indonesian",
    "fr": "French",
    "de": "German",
    "tr": "Turkish",
    "es": "Spanish",
    "pt": "Portuguese",
    "ru": "Russian",
    "it": "Italian",
    "ko": "Korean",
    "ja": "Japanese",
}

LANGUAGE_ALIASES = {
    "english": "en",
    "eng": "en",
    "\u82f1\u8bed": "en",
    "\u82f1\u6587": "en",
    "thai": "th",
    "tha": "th",
    "\u6cf0\u8bed": "th",
    "\u6cf0\u6587": "th",
    "vietnamese": "vi",
    "vie": "vi",
    "vn": "vi",
    "\u8d8a\u5357\u8bed": "vi",
    "\u8d8a\u5357\u6587": "vi",
    "id": "idn",
    "indonesian": "idn",
    "bahasa indonesia": "idn",
    "\u5370\u5c3c": "idn",
    "\u5370\u5c3c\u8bed": "idn",
    "\u5370\u5ea6\u5c3c\u897f\u4e9a": "idn",
    "\u5370\u5ea6\u5c3c\u897f\u4e9a\u8bed": "idn",
    "turkish": "tr",
    "tk": "tr",
    "turk": "tr",
}

LANGUAGE_FILE_HINTS = {
    "en": ("\u82f1\u8bed", "\u82f1\u6587", "english", "en"),
    "th": ("\u6cf0\u8bed", "\u6cf0\u6587", "thai", "th"),
    "vi": ("\u8d8a\u5357\u8bed", "\u8d8a\u5357\u6587", "vietnamese", "viet", "vi", "vn"),
    "idn": ("\u5370\u5c3c", "\u5370\u5ea6\u5c3c\u897f\u4e9a", "indonesian", "bahasa indonesia", "idn", "id"),
}

LANGUAGE_OUTPUT_SUFFIX = {
    "en": "english",
    "th": "thai",
    "vi": "vietnamese",
    "idn": "indonesian",
}

LANGUAGE_TARGET_HEADERS = {
    "en": ("en", "english", "\u82f1\u8bed", "\u82f1\u6587"),
    "th": ("th", "thai", "\u6cf0\u8bed", "\u6cf0\u6587"),
    "vi": ("vi", "vie", "vietnamese", "\u8d8a\u5357\u8bed", "\u8d8a\u5357\u6587"),
    "idn": ("id", "idn", "indonesian", "bahasa indonesia", "\u5370\u5c3c", "\u5370\u5c3c\u8bed", "\u5370\u5ea6\u5c3c\u897f\u4e9a\u8bed"),
    "fr": ("fr", "french", "\u6cd5\u8bed"),
    "de": ("de", "german", "\u5fb7\u8bed"),
    "tr": ("tr", "tk", "turkish", "\u571f\u8033\u5176\u8bed"),
    "es": ("es", "spanish", "\u897f\u73ed\u7259\u8bed"),
    "pt": ("pt", "portuguese", "\u8461\u8404\u7259\u8bed"),
    "ru": ("ru", "russian", "\u4fc4\u8bed"),
    "it": ("it", "italian", "\u610f\u5927\u5229\u8bed"),
    "ko": ("ko", "kr", "korean", "\u97e9\u8bed"),
    "ja": ("ja", "jp", "japanese", "\u65e5\u8bed"),
}

GENERIC_TARGET_HEADERS = (
    "\u8bd1\u6587",
    "\u7ffb\u8bd1",
    "translation",
    "target",
)

SOURCE_HEADERS = (
    "cn",
    "zh",
    "\u4e2d\u6587",
    "\u7b80\u4f53\u4e2d\u6587",
    "\u4e2d\u6587\u672f\u8bed",
    "\u539f\u6587",
    "source",
    "original",
)

GENERIC_VARIANT_HEADERS = (
    "\u8865\u5145\u5f62\u5f0f",
    "\u53e6\u4e00\u8bcd\u6027",
    "\u52a8\u8bcd\u8bd1\u6cd5",
    "variant",
    "variants",
    "alternate",
    "alternates",
)


def normalize_language_code(lang: str | None) -> str:
    text = str(lang or "").strip().lower().replace("_", "-")
    return LANGUAGE_ALIASES.get(text, text)


def language_name(lang: str | None) -> str:
    code = normalize_language_code(lang)
    return LANGUAGE_NAMES.get(code, code)


def language_file_hints(lang: str | None) -> tuple[str, ...]:
    code = normalize_language_code(lang)
    return LANGUAGE_FILE_HINTS.get(code, (code,))


def target_header_candidates(lang: str | None, *, include_generic: bool = False) -> set[str]:
    code = normalize_language_code(lang)
    headers = set(LANGUAGE_TARGET_HEADERS.get(code, (code,)))
    if include_generic:
        headers.update(GENERIC_TARGET_HEADERS)
    return _normalize_headers(headers)


def variant_header_candidates(lang: str | None) -> set[str]:
    candidates: set[str] = set(GENERIC_VARIANT_HEADERS)
    for header in LANGUAGE_TARGET_HEADERS.get(normalize_language_code(lang), ()):
        candidates.add(f"{header}2")
        candidates.add(f"{header}_2")
    return _normalize_headers(candidates)


def all_language_target_headers() -> set[str]:
    values: list[str] = []
    for headers in LANGUAGE_TARGET_HEADERS.values():
        values.extend(headers)
    return _normalize_headers(values)


def _normalize_headers(headers: Iterable[str]) -> set[str]:
    return {str(header or "").strip().lower() for header in headers if str(header or "").strip()}
