"""Compact UI naming policy for glossary-classified skills and locations."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

from utils.language_config import normalize_language_code
from utils.text_normalize import strip_tags_and_vars


SKILL_NAME_TYPE = "ui_skill_name"
LOCATION_NAME_TYPE = "ui_location_name"
BUILDING_NAME_TYPE = "ui_building_name"

_SKILL_EXCLUDES = {
    "技能描述",
    "技能效果",
    "技能说明",
    "技能文本",
    "skill description",
    "skill effect",
    "ability description",
    "ability effect",
}
_LOCATION_EXCLUDES = {
    "地图说明",
    "地图描述",
    "地点说明",
    "地点描述",
    "场景说明",
    "location description",
    "map description",
    "place description",
}
_BUILDING_EXCLUDES = {
    "建筑说明",
    "建筑描述",
    "建筑效果",
    "设施说明",
    "设施描述",
    "设施效果",
    "building description",
    "building effect",
    "facility description",
    "facility effect",
}
_SKILL_EXACT = {
    "技能",
    "技能名",
    "技能名称",
    "招式",
    "招式名",
    "天赋",
    "天赋名",
    "被动",
    "被动名",
    "skill",
    "skills",
    "skill name",
    "ability",
    "abilities",
    "ability name",
    "talent",
    "talent name",
}
_LOCATION_EXACT = {
    "地名",
    "地点",
    "地点名",
    "地点名称",
    "地图",
    "地图名",
    "区域",
    "区域名",
    "场景",
    "场景名",
    "place name",
    "location",
    "location name",
    "map",
    "map name",
    "region",
    "region name",
    "area",
    "area name",
}
_BUILDING_EXACT = {
    "建筑",
    "建筑名",
    "建筑名称",
    "设施",
    "设施名",
    "设施名称",
    "building",
    "building name",
    "facility",
    "facility name",
}
_ENGLISH_CONNECTORS = {
    "a",
    "an",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "to",
}
_ENGLISH_WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")


@dataclass(frozen=True)
class NamePolicyIssue:
    row_id: int | str
    check_type: str
    severity: str
    message: str
    confidence: float = 0.75
    auto_fix: str = ""


def _normalized_category(category: str) -> str:
    return unicodedata.normalize("NFKC", str(category or "")).strip().lower()


def _category_tokens(category: str) -> set[str]:
    text = _normalized_category(category)
    return {
        token.strip()
        for token in re.split(r"[/|,;，；、\n]+", text)
        if token.strip()
    }


def classify_name_type(category: str) -> str:
    """Classify only explicit glossary categories; never infer from source length."""
    text = _normalized_category(category)
    if not text:
        return ""
    if any(
        marker in text
        for marker in _SKILL_EXCLUDES | _LOCATION_EXCLUDES | _BUILDING_EXCLUDES
    ):
        return ""

    tokens = _category_tokens(text)
    if tokens & _SKILL_EXACT or text in _SKILL_EXACT:
        return SKILL_NAME_TYPE
    if tokens & _LOCATION_EXACT or text in _LOCATION_EXACT:
        return LOCATION_NAME_TYPE
    if tokens & _BUILDING_EXACT or text in _BUILDING_EXACT:
        return BUILDING_NAME_TYPE
    return ""


def build_name_policy(name_type: str, lang: str = "en") -> dict[str, Any]:
    lang = normalize_language_code(lang)
    if name_type == SKILL_NAME_TYPE:
        if lang == "en":
            return {
                "preferred_words": 2,
                "max_characters": 24,
                "case": "title_case",
                "strict": False,
                "exception": "allow_more_when_meaning_or_uniqueness_would_be_lost",
            }
        return {
            "preferred_semantic_units": 2,
            "case": "language_natural",
            "strict": False,
            "exception": "natural_grammar_and_meaning_take_priority",
        }
    if name_type == LOCATION_NAME_TYPE:
        if lang == "en":
            return {
                "preferred_content_words": 2,
                "max_characters": 28,
                "case": "title_case",
                "strict": False,
                "exception": "articles_connectors_and_established_names_are_allowed",
            }
        return {
            "preferred_semantic_units": 2,
            "case": "language_natural",
            "strict": False,
            "exception": "natural_grammar_and_established_names_take_priority",
        }
    if name_type == BUILDING_NAME_TYPE:
        if lang == "en":
            return {
                "preferred_content_words": 2,
                "max_characters": 18,
                "map_label_max_characters": 14,
                "case": "title_case",
                "tier_policy": "separate_ui_badge_when_supported",
                "strict": False,
                "exception": "meaning_and_established_terms_take_priority",
            }
        return {
            "preferred_semantic_units": 2,
            "case": "language_natural",
            "tier_policy": "separate_ui_badge_when_supported",
            "strict": False,
            "exception": "natural_grammar_and_meaning_take_priority",
        }
    return {}


def resolve_name_type(source: str, term_lookup: dict[str, Any] | None) -> str:
    """Resolve a name type from an exact glossary entry after removing runtime markup."""
    if not term_lookup:
        return ""
    visible_source = strip_tags_and_vars(str(source or "")).strip()
    entry = term_lookup.get(visible_source)
    if entry is None:
        return ""
    if isinstance(entry, str):
        return (
            entry
            if entry in {SKILL_NAME_TYPE, LOCATION_NAME_TYPE, BUILDING_NAME_TYPE}
            else ""
        )
    if not isinstance(entry, dict):
        return ""
    explicit = str(entry.get("name_type", "")).strip()
    if explicit in {SKILL_NAME_TYPE, LOCATION_NAME_TYPE, BUILDING_NAME_TYPE}:
        return explicit
    return classify_name_type(str(entry.get("category", "") or entry.get("type", "")))


def _english_words(text: str) -> list[str]:
    return _ENGLISH_WORD_RE.findall(strip_tags_and_vars(str(text or "")))


def evaluate_name_translation(
    row_id: int | str,
    source: str,
    translation: str,
    name_type: str,
    lang: str = "en",
) -> list[NamePolicyIssue]:
    """Return soft compactness warnings; semantic exceptions remain model-reviewed."""
    if normalize_language_code(lang) != "en" or not translation:
        return []

    policy = build_name_policy(name_type, lang)
    words = _english_words(translation)
    visible_length = len(strip_tags_and_vars(str(translation)).strip())

    if name_type == SKILL_NAME_TYPE:
        preferred = int(policy["preferred_words"])
        max_characters = int(policy["max_characters"])
        if len(words) <= preferred and visible_length <= max_characters:
            return []
        return [
            NamePolicyIssue(
                row_id=row_id,
                check_type="skill_name_word_count_watch",
                severity="warning",
                message=(
                    f"技能名偏长：{len(words)} 个英文词、{visible_length} 个字符；"
                    f"优先压缩到 {preferred} 词 / {max_characters} 字符内，"
                    "但不得牺牲含义或与其他技能重名"
                ),
            )
        ]

    if name_type == LOCATION_NAME_TYPE:
        content_words = [word for word in words if word.lower() not in _ENGLISH_CONNECTORS]
        preferred = int(policy["preferred_content_words"])
        max_characters = int(policy["max_characters"])
        if len(content_words) <= preferred and visible_length <= max_characters:
            return []
        return [
            NamePolicyIssue(
                row_id=row_id,
                check_type="location_name_compactness_watch",
                severity="warning",
                message=(
                    f"地名偏长：{len(content_words)} 个核心英文词、{visible_length} 个字符；"
                    f"优先压缩到 {preferred} 个核心词 / {max_characters} 字符内，"
                    "冠词、介词和既有专名可按自然表达保留"
                ),
            )
        ]
    if name_type == BUILDING_NAME_TYPE:
        content_words = [
            word
            for word in words
            if word.lower() not in _ENGLISH_CONNECTORS
        ]
        preferred = int(policy["preferred_content_words"])
        max_characters = int(policy["max_characters"])
        map_budget = int(policy["map_label_max_characters"])
        if len(content_words) <= preferred and visible_length <= max_characters:
            return []
        return [
            NamePolicyIssue(
                row_id=row_id,
                check_type="building_name_compactness_watch",
                severity="warning",
                message=(
                    f"建筑名偏长：{len(content_words)} 个核心英文词、"
                    f"{visible_length} 个字符；正式名优先压缩到 "
                    f"{preferred} 个核心词 / {max_characters} 字符内，"
                    f"地图短标签建议不超过 {map_budget} 字符，"
                    "等级和 I-V 阶级尽量交给 UI 徽标，但不得牺牲含义"
                ),
            )
        ]
    return []


def _normalized_translation_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", strip_tags_and_vars(str(text or ""))).casefold()
    return re.sub(r"[\W_]+", " ", normalized, flags=re.UNICODE).strip()


def find_name_collisions(
    rows: Iterable[dict[str, Any]],
    lang: str = "en",
) -> list[NamePolicyIssue]:
    """Warn when different source names collapse to one target name."""
    del lang  # Collision detection is language-independent.
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        name_type = str(row.get("name_type", ""))
        if name_type not in {
            SKILL_NAME_TYPE,
            LOCATION_NAME_TYPE,
            BUILDING_NAME_TYPE,
        }:
            continue
        target_key = _normalized_translation_key(str(row.get("translation", "")))
        source = str(row.get("source", "")).strip()
        if not target_key or not source:
            continue
        groups.setdefault((name_type, target_key), []).append(row)

    issues: list[NamePolicyIssue] = []
    for (_, _), grouped_rows in groups.items():
        sources = {str(row.get("source", "")).strip() for row in grouped_rows}
        if len(sources) <= 1:
            continue
        source_list = " / ".join(sorted(sources))
        emitted_sources: set[str] = set()
        for row in grouped_rows:
            source = str(row.get("source", "")).strip()
            if source in emitted_sources:
                continue
            emitted_sources.add(source)
            issues.append(
                NamePolicyIssue(
                    row_id=row.get("id", ""),
                    check_type="name_translation_collision_watch",
                    severity="warning",
                    message=f"不同中文专名使用了同一译名：{source_list}",
                    confidence=0.8,
                )
            )
    return issues
