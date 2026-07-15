from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LanguageSpec:
    code: str
    label: str
    prompt_name: str
    target_header: str
    visible_code: str
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
    visible_code: str | None = None,
    alt_header: str = "",
    alt_aliases: tuple[str, ...] = (),
) -> LanguageSpec:
    return LanguageSpec(code, label, prompt_name, target_header, visible_code or target_header, alt_header, aliases, alt_aliases)


LANGUAGE_SPECS: dict[str, LanguageSpec] = {
    "en": _spec(
        "en",
        "EN 英语",
        "English",
        "EN",
        ("en", "english", "英文", "英语", "译文", "translation", "target"),
        alt_aliases=("en2", "en 2", "english2", "英语2", "英文2", "target_alt", "alt", "alternate", "variant"),
    ),
    "ko": _spec(
        "ko",
        "KR 韩语",
        "Korean",
        "KR",
        ("ko", "kr", "korean", "韩语", "韩文", "한국어", "조선어", "译文", "translation", "target"),
        alt_aliases=("ko2", "kr2", "ko 2", "kr 2", "korean2", "韩语2", "韩文2", "target_alt", "alt", "alternate", "variant"),
    ),
    "ja": _spec(
        "ja",
        "JP 日语",
        "Japanese",
        "JP",
        ("ja", "jp", "japanese", "日语", "日文", "日本語", "译文", "translation", "target"),
        alt_aliases=("ja2", "jp2", "ja 2", "jp 2", "japanese2", "日语2", "日文2", "target_alt", "alt", "alternate", "variant"),
    ),
    "fr": _spec("fr", "FR 法语", "French", "FR", ("fr", "fre", "french", "法语", "法文", "français", "francais")),
    "de": _spec("de", "DE 德语", "German", "DE", ("de", "ger", "german", "德语", "德文", "deutsch")),
    "ru": _spec("ru", "RU 俄语", "Russian", "RU", ("ru", "rus", "russian", "俄语", "俄文", "русский")),
    "it": _spec("it", "IT 意大利语", "Italian", "IT", ("it", "ita", "italian", "意语", "意大利语", "italiano")),
    "es": _spec("es", "ES 西班牙语", "Spanish", "ES", ("es", "spa", "spanish", "西语", "西班牙语", "español", "espanol")),
    "pt": _spec("pt", "PT 葡萄牙语", "Portuguese", "PT", ("pt", "pt-br", "por", "portuguese", "葡语", "葡萄牙", "葡萄牙语", "巴葡", "português", "portugues")),
    "tr": _spec("tr", "TR 土耳其语", "Turkish", "TR", ("tr", "tk", "tur", "turkish", "土耳其语", "türkçe", "turkce")),
    "idn": _spec("idn", "ID 印尼语", "Indonesian", "IDN", ("idn", "id", "ind", "indonesian", "印尼语", "印度尼西亚语", "bahasa", "bahasa indonesia")),
    "th": _spec("th", "TH 泰语", "Thai", "TH", ("th", "tha", "thai", "泰语", "ภาษาไทย")),
    "vn": _spec(
        "vn",
        "VN 越南语",
        "Vietnamese",
        "VI",
        ("vi", "vie", "vietnamese", "越南语", "越南文"),
        visible_code="VN",
    ),
    "ar": _spec("ar", "AR 阿拉伯语", "Arabic", "AR", ("ar", "ara", "arabic", "阿语", "阿拉伯语", "العربية")),
}

PROJECT_LANGUAGE_ORDER = ("en", "ko", "ja", "fr", "de", "ru", "it", "es", "pt", "tr", "idn", "th", "vn", "ar")
ANNOUNCEMENT_LANGUAGE_ORDER = PROJECT_LANGUAGE_ORDER
SUPPORTED_LANGUAGES = frozenset(LANGUAGE_SPECS)

SOURCE_HEADER_ALIASES: tuple[str, ...] = (
    "source",
    "original",
    "cn",
    "zh",
    "zh-cn",
    "zh_cn",
    "zhcn",
    "chinese",
    "term",
    "原文",
    "源文",
    "源文本",
    "中文",
    "简体中文",
    "中文原文",
    "术语",
)

_LANGUAGE_ALIASES = {
    "kr": "ko",
    "jp": "ja",
    "fre": "fr",
    "ger": "de",
    "rus": "ru",
    "ita": "it",
    "spa": "es",
    "por": "pt",
    "ptbr": "pt",
    "pt-br": "pt",
    "tk": "tr",
    "tur": "tr",
    "id": "idn",
    "ind": "idn",
    "tha": "th",
    "vi": "vn",
    "vie": "vn",
    "ara": "ar",
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


def workflow_language_code(value: Any, *, default: str = "en") -> str:
    code = require_supported_language(value, default=default)
    return "vi" if code == "vn" else code


def canonical_language(value: Any, *, default: str = "en") -> str:
    return require_supported_language(value, default=default)


def language_spec(value: Any) -> LanguageSpec:
    return LANGUAGE_SPECS[require_supported_language(value)]


def visible_language_code(value: Any) -> str:
    return language_spec(value).target_header


def ui_language_code(value: Any) -> str:
    return language_spec(value).visible_code


def target_aliases(value: Any) -> list[str]:
    spec = language_spec(value)
    return list(spec.target_aliases)


def alt_aliases(value: Any) -> list[str]:
    spec = language_spec(value)
    return list(spec.alt_aliases)


def language_payload() -> dict[str, Any]:
    return {
        "languages": [
            {
                "code": code,
                "visible_code": ui_language_code(code),
                "label": spec.label,
                "prompt_name": spec.prompt_name,
                "target_header": spec.target_header,
                "alt_header": spec.alt_header,
                "aliases": sorted({*spec.target_aliases, code, spec.target_header.lower()}),
                "target_aliases": list(spec.target_aliases),
                "alt_aliases": list(spec.alt_aliases),
            }
            for code in PROJECT_LANGUAGE_ORDER
            for spec in [LANGUAGE_SPECS[code]]
        ]
    }
