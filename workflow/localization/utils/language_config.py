"""Shared language metadata for workbook localization workflows.

The supported set covers every language requested in delivery history
(EN/KO/JA/TH/VI/IDN plus the 土拨鼠 8-language, 明日2 full-language,
勇者 ES/PT, and announcement AR workstreams) and matches the studio
backend's language list plus VI.
"""
from __future__ import annotations

from typing import Iterable


SUPPORTED_TRANSLATION_LANGUAGES = (
    "en",
    "ko",
    "ja",
    "th",
    "vi",
    "idn",
    "fr",
    "de",
    "ru",
    "it",
    "es",
    "pt",
    "tr",
    "ar",
)

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
    "ar": "Arabic",
}

LANGUAGE_ALIASES = {
    "english": "en",
    "eng": "en",
    "英语": "en",
    "英文": "en",
    "thai": "th",
    "tha": "th",
    "泰语": "th",
    "泰文": "th",
    "vietnamese": "vi",
    "vie": "vi",
    "vn": "vi",
    "越南语": "vi",
    "越南文": "vi",
    "id": "idn",
    "ind": "idn",
    "indonesian": "idn",
    "bahasa indonesia": "idn",
    "印尼": "idn",
    "印尼语": "idn",
    "印度尼西亚": "idn",
    "印度尼西亚语": "idn",
    "korean": "ko",
    "kor": "ko",
    "kr": "ko",
    "韩语": "ko",
    "韩文": "ko",
    "japanese": "ja",
    "jpn": "ja",
    "jp": "ja",
    "日语": "ja",
    "日文": "ja",
    "french": "fr",
    "fre": "fr",
    "fra": "fr",
    "法语": "fr",
    "法文": "fr",
    "german": "de",
    "ger": "de",
    "deu": "de",
    "德语": "de",
    "德文": "de",
    "russian": "ru",
    "rus": "ru",
    "俄语": "ru",
    "俄文": "ru",
    "italian": "it",
    "ita": "it",
    "意大利语": "it",
    "意语": "it",
    "spanish": "es",
    "spa": "es",
    "西班牙语": "es",
    "西语": "es",
    "portuguese": "pt",
    "por": "pt",
    "pt-br": "pt",
    "ptbr": "pt",
    "葡萄牙语": "pt",
    "葡语": "pt",
    "巴葡": "pt",
    "turkish": "tr",
    "tk": "tr",
    "tur": "tr",
    "turk": "tr",
    "土耳其语": "tr",
    "土耳其文": "tr",
    "arabic": "ar",
    "ara": "ar",
    "阿拉伯语": "ar",
    "阿语": "ar",
}

LANGUAGE_FILE_HINTS = {
    "en": ("英语", "英文", "english", "en"),
    "th": ("泰语", "泰文", "thai", "th"),
    "vi": ("越南语", "越南文", "vietnamese", "viet", "vi", "vn"),
    "idn": ("印尼", "印度尼西亚", "indonesian", "bahasa indonesia", "idn", "id"),
    "ko": ("韩语", "韩文", "korean", "ko", "kr"),
    "ja": ("日语", "日文", "japanese", "ja", "jp"),
    "fr": ("法语", "法文", "french", "fr"),
    "de": ("德语", "德文", "german", "de"),
    "ru": ("俄语", "俄文", "russian", "ru"),
    "it": ("意大利语", "意语", "italian", "it"),
    "es": ("西班牙语", "西语", "spanish", "es"),
    "pt": ("葡萄牙语", "葡语", "巴葡", "portuguese", "pt"),
    "tr": ("土耳其语", "土耳其文", "turkish", "tr", "tk"),
    "ar": ("阿拉伯语", "阿语", "arabic", "ar"),
}

LANGUAGE_OUTPUT_SUFFIX = {
    "en": "english",
    "th": "thai",
    "vi": "vietnamese",
    "idn": "indonesian",
    "ko": "korean",
    "ja": "japanese",
    "fr": "french",
    "de": "german",
    "ru": "russian",
    "it": "italian",
    "es": "spanish",
    "pt": "portuguese",
    "tr": "turkish",
    "ar": "arabic",
}

LANGUAGE_TARGET_HEADERS = {
    "en": ("en", "english", "英语", "英文"),
    "th": ("th", "thai", "泰语", "泰文"),
    "vi": ("vi", "vie", "vietnamese", "越南语", "越南文"),
    "idn": ("id", "idn", "indonesian", "bahasa indonesia", "印尼", "印尼语", "印度尼西亚语"),
    "fr": ("fr", "french", "法语", "法文"),
    "de": ("de", "german", "德语", "德文"),
    "tr": ("tr", "tk", "turkish", "土耳其语"),
    "es": ("es", "spanish", "西班牙语", "西语"),
    "pt": ("pt", "pt-br", "portuguese", "葡萄牙语", "葡语"),
    "ru": ("ru", "russian", "俄语", "俄文"),
    "it": ("it", "italian", "意大利语"),
    "ko": ("ko", "kr", "korean", "韩语", "韩文"),
    "ja": ("ja", "jp", "japanese", "日语", "日文"),
    "ar": ("ar", "arabic", "阿拉伯语", "阿语"),
}

GENERIC_TARGET_HEADERS = (
    "译文",
    "翻译",
    "translation",
    "target",
)

SOURCE_HEADERS = (
    "cn",
    "zh",
    "中文",
    "简体中文",
    "中文术语",
    "原文",
    "source",
    "original",
)

GENERIC_VARIANT_HEADERS = (
    "补充形式",
    "另一词性",
    "动词译法",
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
