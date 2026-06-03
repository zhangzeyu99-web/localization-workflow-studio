from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LanguageSpec:
    code: str
    label: str
    prompt_name: str
    target_header: str
    alt_header: str
    target_aliases: tuple[str, ...]
    alt_aliases: tuple[str, ...]


def _spec(
    code: str,
    label: str,
    prompt_name: str,
    target_header: str,
    aliases: tuple[str, ...],
    *,
    alt_header: str = "",
    alt_aliases: tuple[str, ...] = (),
) -> LanguageSpec:
    return LanguageSpec(code, label, prompt_name, target_header, alt_header, aliases, alt_aliases)


LANGUAGE_SPECS: dict[str, LanguageSpec] = {
    "en": _spec(
        "en", "英语 EN", "English", "EN",
        ("en", "english", "英文", "英语", "译文", "translation", "target"),
        alt_header="EN2",
        alt_aliases=("en2", "en 2", "english2", "英语2", "英文2", "target_alt", "alt", "alternate", "variant"),
    ),
    "ko": _spec(
        "ko", "韩语 KR", "Korean", "KR",
        ("ko", "kr", "korean", "韩语", "韓語", "한국어", "조선말", "译文", "translation", "target"),
        alt_header="",
        alt_aliases=("ko2", "kr2", "ko 2", "kr 2", "korean2", "韩语2", "韓語2", "한국어2", "target_alt", "alt", "alternate", "variant"),
    ),
    "ja": _spec(
        "ja", "日语 JP", "Japanese", "JP",
        ("ja", "jp", "japanese", "日语", "日語", "日本語", "译文", "translation", "target"),
        alt_header="",
        alt_aliases=("ja2", "jp2", "ja 2", "jp 2", "japanese2", "日语2", "日語2", "日本語2", "target_alt", "alt", "alternate", "variant"),
    ),
    "fr": _spec("fr", "法语 FR", "French", "FR", ("fr", "fre", "french", "法语", "法文", "français", "francais")),
    "de": _spec("de", "德语 DE", "German", "DE", ("de", "ger", "german", "德语", "德文", "deutsch")),
    "ru": _spec("ru", "俄语 RU", "Russian", "RU", ("ru", "rus", "russian", "俄语", "俄文", "русский")),
    "it": _spec("it", "意大利语 IT", "Italian", "IT", ("it", "ita", "italian", "意语", "意大利语", "italiano")),
    "es": _spec("es", "西班牙语 ES", "Spanish", "ES", ("es", "spa", "spanish", "西语", "西班牙语", "español", "espanol")),
    "pt": _spec("pt", "葡萄牙语 PT", "Portuguese", "PT", ("pt", "pt-br", "por", "portuguese", "葡语", "葡萄牙语", "巴葡", "português", "portugues")),
    "tr": _spec("tr", "土耳其语 TR", "Turkish", "TR", ("tr", "tk", "tur", "turkish", "土耳其语", "türkçe", "turkce")),
    "idn": _spec("idn", "印尼语 ID", "Indonesian", "IDN", ("idn", "id", "ind", "indonesian", "印尼语", "印度尼西亚语", "bahasa", "bahasa indonesia")),
    "th": _spec("th", "泰语 TH", "Thai", "TH", ("th", "tha", "thai", "泰语", "ภาษาไทย")),
    "ar": _spec("ar", "阿拉伯语 AR", "Arabic", "AR", ("ar", "ara", "arabic", "阿语", "阿拉伯语", "العربية")),
}

PROJECT_LANGUAGE_ORDER = ("en", "ko", "ja", "fr", "de", "ru", "it", "es", "pt", "tr", "idn", "th", "ar")
ANNOUNCEMENT_LANGUAGE_ORDER = PROJECT_LANGUAGE_ORDER
SUPPORTED_LANGUAGES = frozenset(LANGUAGE_SPECS)

_LANGUAGE_ALIASES = {
    "kr": "ko", "jp": "ja", "fre": "fr", "ger": "de", "rus": "ru", "ita": "it", "spa": "es", "por": "pt",
    "ptbr": "pt", "pt-br": "pt", "tk": "tr", "tur": "tr", "id": "idn", "ind": "idn", "tha": "th", "ara": "ar",
}


def normalize_language(value: Any, *, default: str = "en") -> str:
    code = str(value or default).strip().lower().replace("_", "-")
    compact = code.replace(" ", "").replace("-", "")
    code = _LANGUAGE_ALIASES.get(code, _LANGUAGE_ALIASES.get(compact, code))
    return code or default


def require_supported_language(value: Any, *, default: str = "en") -> str:
    code = normalize_language(value, default=default)
    if code not in SUPPORTED_LANGUAGES:
        raise ValueError(f"unsupported language: {code}")
    return code


def canonical_language(value: Any, *, default: str = "en") -> str:
    return require_supported_language(value, default=default)


def language_spec(value: Any) -> LanguageSpec:
    return LANGUAGE_SPECS[require_supported_language(value)]


def visible_language_code(value: Any) -> str:
    return language_spec(value).target_header


def target_aliases(value: Any) -> list[str]:
    spec = language_spec(value)
    return list(spec.target_aliases)


def alt_aliases(value: Any) -> list[str]:
    spec = language_spec(value)
    return list(spec.alt_aliases)
