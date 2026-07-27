from __future__ import annotations

from glossary_extraction.constants import CATEGORY_LABELS
from glossary_extraction.heuristics import category_for
from glossary_extraction.models import Record
from glossary_extraction.name_policy import (
    assess_name_translation,
    build_name_review_packet,
    classify_term_type,
    find_name_collisions,
)


def test_skill_name_uses_explicit_field_or_id_context():
    records = [
        Record(
            "SkillName_1001",
            "鲨潮护盾",
            "Sharkguard",
            sheet_name="技能",
            row_number=2,
            source_field="中文",
            term_type_hint="技能名",
        ),
        Record(
            "SkillDesc_1001",
            "召唤鲨潮并获得护盾",
            "Summons a shark tide and gains a shield.",
            sheet_name="技能",
            row_number=3,
            source_field="中文",
        ),
    ]

    decision = classify_term_type("鲨潮护盾", [0], records, {})

    assert decision.term_type == "ui_skill_name"
    assert decision.category == "技能名"
    assert decision.bypass_frequency is True
    assert decision.needs_review is False


def test_location_name_uses_explicit_context():
    records = [
        Record(
            "MapName_2001",
            "暮色海岸",
            "Dusk Coast",
            sheet_name="地图名称",
            row_number=2,
            source_field="中文",
        )
    ]

    decision = classify_term_type("暮色海岸", [0], records, {})

    assert decision.term_type == "location_name"
    assert decision.category == "地名"
    assert decision.bypass_frequency is True


def test_four_character_text_is_not_a_skill_without_context():
    records = [Record("Text_1", "终极挑战", "Final Challenge")]

    decision = classify_term_type("终极挑战", [0], records, {})

    assert decision.term_type == "atomic"
    assert decision.bypass_frequency is False


def test_conflicting_explicit_signals_require_review():
    records = [
        Record(
            "MapName_2001",
            "暮色海岸",
            "Dusk Coast",
            sheet_name="地图",
            term_type_hint="技能名",
        )
    ]

    decision = classify_term_type("暮色海岸", [0], records, {})

    assert decision.term_type == "needs_review"
    assert decision.needs_review is True


def test_category_for_maps_to_one_delivery_category():
    assert CATEGORY_LABELS[category_for("红色品质")] == "品质"
    assert CATEGORY_LABELS[category_for("公会")] == "联盟"
    assert CATEGORY_LABELS[category_for("火焰技能")] == "技能"
    assert CATEGORY_LABELS[category_for("无法判断的文本")] == "待确认"


def test_english_skill_name_budget_is_warning_only():
    result = assess_name_translation(
        term_type="ui_skill_name",
        translation="Megalodon Water Shield",
        language="EN",
    )

    assert result.word_count == 3
    assert result.char_count == 22
    assert "english_skill_word_budget" in result.warnings


def test_english_location_ignores_articles_and_prepositions_for_core_words():
    result = assess_name_translation(
        term_type="location_name",
        translation="Gates of Dawn",
        language="EN",
    )

    assert result.word_count == 3
    assert result.core_word_count == 2
    assert "english_location_core_word_budget" not in result.warnings


def test_non_english_name_does_not_use_english_word_count_rule():
    result = assess_name_translation(
        term_type="ui_skill_name",
        translation="โล่คลื่นฉลาม",
        language="TH",
    )

    assert not any(warning.startswith("english_") for warning in result.warnings)
    assert "manual_semantic_unit_review" in result.warnings


def test_different_cn_names_with_same_en_are_collisions():
    collisions = find_name_collisions(
        [
            {"CN": "鲨潮护盾", "EN": "Sharkguard", "TermType": "ui_skill_name"},
            {"CN": "鲨卫", "EN": "Sharkguard", "TermType": "ui_skill_name"},
        ],
        curated_rules=None,
    )

    assert collisions == {"sharkguard": ["鲨卫", "鲨潮护盾"]}


def test_collision_scope_includes_curated_project_names():
    collisions = find_name_collisions(
        [{"CN": "鲨潮护盾", "EN": "Sharkguard", "TermType": "ui_skill_name"}],
        curated_rules={
            "version": 1,
            "terms": {
                "鲨卫": {
                    "approved_en": "Sharkguard",
                    "term_type_override": "ui_skill_name",
                }
            },
        },
    )

    assert collisions == {"sharkguard": ["鲨卫", "鲨潮护盾"]}


def test_name_review_packet_contains_only_compact_proper_name_candidates():
    packet = build_name_review_packet(
        [
            {
                "ID": "SkillName_1001",
                "CN": "鲨潮护盾",
                "EN": "Sharkguard",
                "TermType": "ui_skill_name",
                "Category": "技能名",
                "TypeEvidence": "skill_context:SkillName_1001",
                "ExampleSource": "鲨潮护盾",
                "ExampleEN": "Sharkguard",
                "NameWordCount": 1,
                "NameCoreWordCount": 1,
                "NameCharCount": 10,
                "NamePolicyWarnings": "",
                "NameCollisionWith": "",
            },
            {
                "ID": "Text_1",
                "CN": "普通文本",
                "EN": "Normal Text",
                "TermType": "atomic",
                "Category": "UI",
                "ExampleSource": "普通文本",
            },
        ],
        language="EN",
    )

    assert packet["task"] == "proper_name_review"
    assert [row["CN"] for row in packet["candidates"]] == ["鲨潮护盾"]
    assert "普通文本" not in str(packet)
