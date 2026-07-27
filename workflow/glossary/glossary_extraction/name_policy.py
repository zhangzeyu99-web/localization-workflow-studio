"""Proper-name classification and UI naming policies."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from glossary_extraction.models import Record


PROPER_NAME_TYPES = frozenset({"ui_skill_name", "location_name"})
VALID_TERM_TYPES = frozenset({"atomic", "ui_skill_name", "location_name", "needs_review"})

SKILL_HINTS = (
    "技能名",
    "skill_name",
    "skillname",
    "ability_name",
    "abilityname",
)
LOCATION_HINTS = (
    "地名",
    "地点名",
    "场景名",
    "地图名",
    "location_name",
    "locationname",
    "map_name",
    "mapname",
    "scene_name",
    "scenename",
)


@dataclass(frozen=True)
class TermTypeDecision:
    term_type: str
    category: str
    confidence: str
    evidence: tuple[str, ...]
    bypass_frequency: bool
    needs_review: bool


@dataclass(frozen=True)
class NamePolicyResult:
    word_count: int
    core_word_count: int
    char_count: int
    warnings: tuple[str, ...]


ENGLISH_LOCATION_STOPWORDS = frozenset(
    {"a", "an", "the", "of", "to", "in", "on", "at", "for"}
)


def plain_text(value: object) -> str:
    return " ".join(str(value or "").split())


def english_words(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*", plain_text(value))


def assess_name_translation(
    term_type: str,
    translation: str,
    language: str,
) -> NamePolicyResult:
    value = plain_text(translation)
    is_english = language.upper() in {"EN", "ENG", "ENGLISH"}
    words = english_words(value) if is_english else []
    core_words = [
        word for word in words if word.lower() not in ENGLISH_LOCATION_STOPWORDS
    ]
    warnings: list[str] = []

    if is_english:
        if term_type == "ui_skill_name" and len(words) > 2:
            warnings.append("english_skill_word_budget")
        if term_type == "ui_skill_name" and len(value) > 24:
            warnings.append("english_skill_char_budget")
        if term_type == "location_name" and len(core_words) > 2:
            warnings.append("english_location_core_word_budget")
        if term_type == "location_name" and len(value) > 28:
            warnings.append("english_location_char_budget")
    elif term_type in PROPER_NAME_TYPES:
        warnings.append("manual_semantic_unit_review")

    return NamePolicyResult(
        word_count=len(words),
        core_word_count=len(core_words),
        char_count=len(value),
        warnings=tuple(warnings),
    )


def normalized_name(value: object) -> str:
    return re.sub(
        r"[\W_]+",
        "",
        plain_text(value).casefold(),
        flags=re.UNICODE,
    )


def find_name_collisions(
    rows: list[dict[str, object]],
    curated_rules: dict[str, object] | None = None,
) -> dict[str, list[str]]:
    names: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.get("TermType") not in PROPER_NAME_TYPES:
            continue
        key = normalized_name(row.get("EN"))
        cn = plain_text(row.get("CN"))
        if key and cn:
            names[key].add(cn)

    raw_terms = (curated_rules or {}).get("terms", {})
    if isinstance(raw_terms, dict):
        for cn, raw_state in raw_terms.items():
            state = raw_state if isinstance(raw_state, dict) else {}
            if state.get("term_type_override") not in PROPER_NAME_TYPES:
                continue
            key = normalized_name(state.get("approved_en"))
            cn_text = plain_text(cn)
            if key and cn_text:
                names[key].add(cn_text)

    return {
        key: sorted(cn_values)
        for key, cn_values in names.items()
        if len(cn_values) > 1
    }


def build_name_review_packet(
    rows: list[dict[str, object]],
    language: str,
) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    for row in rows:
        if row.get("TermType") not in PROPER_NAME_TYPES:
            continue
        candidates.append(
            {
                "ID": row.get("ID", ""),
                "CN": row.get("CN", ""),
                "translation": row.get("EN", ""),
                "term_type": row.get("TermType", ""),
                "category": row.get("Category", ""),
                "type_evidence": row.get("TypeEvidence", ""),
                "example_source": row.get("ExampleSource", ""),
                "example_translation": row.get("ExampleEN", ""),
                "word_count": row.get("NameWordCount", 0),
                "core_word_count": row.get("NameCoreWordCount", 0),
                "char_count": row.get("NameCharCount", 0),
                "warnings": row.get("NamePolicyWarnings", ""),
                "collision_with": row.get("NameCollisionWith", ""),
            }
        )
    return {
        "schema_version": 1,
        "task": "proper_name_review",
        "language": language,
        "instructions": [
            "Check category first; do not infer skill or location names from Chinese length.",
            "Check core meaning, naturalness, over-compression, and project-wide uniqueness.",
            "English skill names should normally fit 2 words and 24 characters.",
            "English location names should normally fit 2 core words and 28 characters.",
            "For non-English languages, judge about 2 core semantic units instead of English word count.",
            "Do not rewrite names merely to satisfy the budget when meaning or uniqueness would be lost.",
        ],
        "candidates": candidates,
    }


def normalized_context(record: Record) -> str:
    return " ".join(
        str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for value in (
            record.term_type_hint,
            record.sheet_name,
            record.source_field,
            record.row_id,
        )
        if str(value or "").strip()
    )


def classify_term_type(
    term: str,
    exact_record_indexes: list[int],
    records: list[Record],
    curated_state: dict[str, Any],
) -> TermTypeDecision:
    del term
    override = str(curated_state.get("term_type_override") or "").strip().lower()
    if override in VALID_TERM_TYPES:
        category = {
            "ui_skill_name": "技能名",
            "location_name": "地名",
            "needs_review": "待确认",
        }.get(override, "")
        return TermTypeDecision(
            term_type=override,
            category=category,
            confidence="high",
            evidence=(f"curated:{override}",),
            bypass_frequency=override in PROPER_NAME_TYPES,
            needs_review=override == "needs_review",
        )

    evidence: list[str] = []
    has_skill = False
    has_location = False
    for index in exact_record_indexes:
        context = normalized_context(records[index])
        if any(hint in context for hint in SKILL_HINTS):
            has_skill = True
            evidence.append(f"skill_context:{records[index].row_id}")
        if any(hint in context for hint in LOCATION_HINTS):
            has_location = True
            evidence.append(f"location_context:{records[index].row_id}")

    if has_skill and has_location:
        return TermTypeDecision("needs_review", "待确认", "low", tuple(evidence), False, True)
    if has_skill:
        return TermTypeDecision("ui_skill_name", "技能名", "high", tuple(evidence), True, False)
    if has_location:
        return TermTypeDecision("location_name", "地名", "high", tuple(evidence), True, False)
    return TermTypeDecision("atomic", "", "medium", tuple(), False, False)
