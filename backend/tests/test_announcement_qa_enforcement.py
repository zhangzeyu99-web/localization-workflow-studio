from __future__ import annotations

import pytest

from app.workflow.announcement_outputs import (
    _announcement_translation_prompt,
    _repair_announcement_translation_text,
    _validate_announcement_translation_rows,
)


def _game_name_rows(
    translation: str,
    *,
    language: str = "en",
    sentence_target: str | None = None,
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    segment = {
        "id": "segment-1",
        "source": "《菇勇者传说》联动活动",
    }
    sentence_adaptations = []
    if sentence_target is not None:
        sentence_adaptations.append(
            {
                "match_type": "official_exact",
                "official_cn_template": "《菇勇者传说》联动活动",
                "target": sentence_target,
            }
        )
    rows = {
        "segment-1": {
            "translations": {language: translation},
            "protected_tokens": [],
            "term_hits": {
                language: [
                    {
                        "source": "菇勇者传说",
                        "target": "Legend of Mushroom",
                    }
                ]
            },
            "sentence_adaptations": {language: sentence_adaptations},
        }
    }
    return [segment], rows


def test_term_missing_repair_does_not_append_required_term_to_wrong_translation() -> None:
    repaired = _repair_announcement_translation_text(
        "Shroomie Legendary",
        source="《菇勇者传说》联动活动",
        language="en",
        protected_tokens=[],
        term_hits=[{"source": "菇勇者传说", "target": "Legend of Mushroom"}],
        issues=[
            {
                "severity": "hard",
                "check_type": "term_missing",
                "segment_id": "segment-1",
                "language": "en",
            }
        ],
    )

    assert repaired == "Shroomie Legendary"
    segments, rows = _game_name_rows(repaired)
    issues = _validate_announcement_translation_rows(segments, rows, ["en"])
    assert [issue["check_type"] for issue in issues] == ["term_missing"]


def test_official_exact_wrong_target_does_not_bypass_required_term() -> None:
    segments, rows = _game_name_rows(
        "Shroomie Legendary",
        sentence_target="Shroomie Legendary",
    )

    issues = _validate_announcement_translation_rows(segments, rows, ["en"])

    assert [issue["check_type"] for issue in issues] == ["term_missing"]


def test_official_exact_correct_target_does_not_bypass_wrong_actual_translation() -> None:
    segments, rows = _game_name_rows(
        "Shroomie Legendary",
        sentence_target="Legend of Mushroom x OVERLORD Collab Event",
    )

    issues = _validate_announcement_translation_rows(segments, rows, ["en"])

    assert [issue["check_type"] for issue in issues] == ["term_missing"]


def test_official_exact_target_containing_required_term_can_cover_term_hit() -> None:
    official_target = "Legend of Mushroom x OVERLORD Collab Event"
    segments, rows = _game_name_rows(
        official_target,
        sentence_target=official_target,
    )

    assert _validate_announcement_translation_rows(segments, rows, ["en"]) == []


def test_prompt_never_allows_sentence_adaptation_to_override_term_hits() -> None:
    prompt = _announcement_translation_prompt(
        {"name": "Legend of Mushroom"},
        "en",
        "Address players as Shroomie.",
        {"missing_terms": []},
    )

    assert "Every target in term_hits is mandatory exact wording" in prompt
    assert "Sentence adaptations never override term_hits" in prompt
    assert "Use sentence_adaptations before term_hits" not in prompt


@pytest.mark.parametrize("language", ["en", "idn"])
@pytest.mark.parametrize(
    "translation",
    [
        "Legend of Mushrooms",
        "The Legend of Mushroomland",
        "Legend of Mushroomé",
        "Legend of Mushroom中",
    ],
)
def test_ascii_language_mandatory_target_rejects_joined_word_match(
    language: str,
    translation: str,
) -> None:
    segments, rows = _game_name_rows(translation, language=language)

    issues = _validate_announcement_translation_rows(segments, rows, [language])

    assert "term_missing" in [issue["check_type"] for issue in issues]


@pytest.mark.parametrize("language", ["en", "idn"])
@pytest.mark.parametrize(
    "translation",
    [
        "legend of mushroom",
        "《Legend of Mushroom》",
        "(LEGEND OF MUSHROOM)!",
    ],
)
def test_ascii_language_mandatory_target_accepts_case_and_punctuation_boundaries(
    language: str,
    translation: str,
) -> None:
    segments, rows = _game_name_rows(translation, language=language)

    assert _validate_announcement_translation_rows(segments, rows, [language]) == []


def test_non_ascii_language_keeps_contiguous_mandatory_target_match() -> None:
    segments = [{"id": "segment-1", "source": "勇者伝説イベント"}]
    rows = {
        "segment-1": {
            "translations": {"ja": "新勇者伝説イベント"},
            "protected_tokens": [],
            "term_hits": {"ja": [{"source": "勇者伝説", "target": "勇者伝説"}]},
            "sentence_adaptations": {"ja": []},
        }
    }

    assert _validate_announcement_translation_rows(segments, rows, ["ja"]) == []


def test_legacy_single_word_common_term_accepts_natural_plural() -> None:
    segments = [{"id": "segment-1", "source": "各位幸存者请集结"}]
    rows = {
        "segment-1": {
            "translations": {"en": "Survivors, rally now."},
            "protected_tokens": [],
            "term_hits": {"en": [{"source": "幸存者", "target": "Survivor"}]},
        }
    }

    assert _validate_announcement_translation_rows(segments, rows, ["en"]) == []


def test_common_multiword_term_accepts_natural_plural_when_category_is_known() -> None:
    segments = [{"id": "segment-1", "source": "联盟成员可领取奖励"}]
    rows = {
        "segment-1": {
            "translations": {"en": "Alliance Members can claim rewards."},
            "protected_tokens": [],
            "term_hits": {
                "en": [
                    {
                        "source": "联盟成员",
                        "target": "Alliance Member",
                        "category": "普通术语",
                    }
                ]
            },
        }
    }

    assert _validate_announcement_translation_rows(segments, rows, ["en"]) == []


def test_single_word_game_name_still_rejects_pluralized_variant() -> None:
    segments = [{"id": "segment-1", "source": "霸主联动开启"}]
    rows = {
        "segment-1": {
            "translations": {"en": "Overlords collaboration begins."},
            "protected_tokens": [],
            "term_hits": {
                "en": [
                    {
                        "source": "霸主",
                        "target": "Overlord",
                        "category": "游戏名",
                    }
                ]
            },
        }
    }

    issues = _validate_announcement_translation_rows(segments, rows, ["en"])

    assert [issue["check_type"] for issue in issues] == ["term_missing"]
