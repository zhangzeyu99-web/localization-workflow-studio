"""Short-text length budget checks for compact UI and similar entries."""
from __future__ import annotations

import re
from dataclasses import dataclass

from utils.text_normalize import strip_tags_and_vars

SHORT_TEXT_MAX_SOURCE_LENGTH = 10
_SENTENCE_PUNCTUATION = re.compile(r"[。！？；!?]|\.{2,}")
_RICH_TEXT_TAG = re.compile(r"\[(?:/?(?:color|size|b|i|u|s)\b[^\]]*)\]", re.IGNORECASE)
_TRAILING_NUMBER = re.compile(r"^\D+\d+$")


@dataclass
class UILengthAssessment:
    row_id: int
    source_length: int
    target_length: int
    budget: int
    policy: str
    reason: str = ""

    @property
    def overflow(self) -> bool:
        return self.target_length > self.budget


@dataclass
class UILengthCheckResult:
    row_id: int
    check_type: str
    severity: str
    message: str
    source_length: int
    target_length: int
    budget: int
    policy: str = "hard"
    confidence: float = 0.9
    auto_fix: str = ""


def visible_text_length(text: str) -> int:
    normalized = strip_tags_and_vars(str(text))
    normalized = re.sub(r"\s+", "", normalized)
    return len(normalized)


def _visible_text(text: str) -> str:
    return strip_tags_and_vars(str(text)).strip()


def _has_sentence_punctuation(text: str) -> bool:
    return bool(_SENTENCE_PUNCTUATION.search(_visible_text(text)))


def _is_multiline(text: str) -> bool:
    raw = str(text)
    return any(token in raw for token in ("\n", "\\n", "\r"))


def _has_complex_rich_text(text: str) -> bool:
    return len(_RICH_TEXT_TAG.findall(str(text))) >= 2


def _looks_like_numbered_proper_name(original: str, translation: str) -> bool:
    source = _visible_text(original)
    target = _visible_text(translation)
    if not source or not target:
        return False
    if not _TRAILING_NUMBER.match(source):
        return False
    if not re.search(r"\d+$", target):
        return False
    return True


def is_short_text_candidate(original: str, translation: str) -> bool:
    source = _visible_text(original)
    target = _visible_text(translation)
    if not source or not target:
        return False
    if _is_multiline(original) or _is_multiline(translation):
        return False
    return 1 <= visible_text_length(source) <= SHORT_TEXT_MAX_SOURCE_LENGTH


def compute_ui_length_budget(source_length: int, lang: str = "en") -> int:
    if lang == "idn":
        return min(34, max(12, source_length * 2 + 15))
    return min(32, max(10, source_length * 2 + 14))


def assess_ui_length(
    row_id: int,
    original: str,
    translation: str,
    is_ui: bool,
    lang: str = "en",
) -> UILengthAssessment | None:
    if not is_short_text_candidate(original, translation):
        return None

    source_length = visible_text_length(original)
    target_length = visible_text_length(translation)
    budget = compute_ui_length_budget(source_length, lang=lang)

    if _looks_like_numbered_proper_name(original, translation):
        return UILengthAssessment(
            row_id=row_id,
            source_length=source_length,
            target_length=target_length,
            budget=budget,
            policy="exempt",
            reason="numbered_proper_name",
        )

    if _has_complex_rich_text(original) or _has_complex_rich_text(translation):
        return UILengthAssessment(
            row_id=row_id,
            source_length=source_length,
            target_length=target_length,
            budget=budget,
            policy="exempt",
            reason="complex_rich_text",
        )

    if is_ui and not _has_sentence_punctuation(original):
        return UILengthAssessment(
            row_id=row_id,
            source_length=source_length,
            target_length=target_length,
            budget=budget,
            policy="hard",
            reason="compact_ui",
        )

    return UILengthAssessment(
        row_id=row_id,
        source_length=source_length,
        target_length=target_length,
        budget=budget,
        policy="soft",
        reason="short_text",
    )


def check_ui_length(
    row_id: int,
    original: str,
    translation: str,
    is_ui: bool,
    lang: str = "en",
) -> list[UILengthCheckResult]:
    assessment = assess_ui_length(
        row_id=row_id,
        original=original,
        translation=translation,
        is_ui=is_ui,
        lang=lang,
    )
    if not assessment or assessment.policy == "exempt" or not assessment.overflow:
        return []

    if assessment.policy == "hard":
        return [
            UILengthCheckResult(
                row_id=row_id,
                check_type="ui_length_overflow",
                severity="error",
                message=(
                    "Compact short text is too long for UI display: "
                    f"source={assessment.source_length}, target={assessment.target_length}, budget<={assessment.budget}"
                ),
                source_length=assessment.source_length,
                target_length=assessment.target_length,
                budget=assessment.budget,
                policy=assessment.policy,
                confidence=0.9,
            )
        ]

    return [
        UILengthCheckResult(
            row_id=row_id,
            check_type="short_text_length_watch",
            severity="warning",
            message=(
                "Short text is longer than the preferred compact range: "
                f"source={assessment.source_length}, target={assessment.target_length}, budget<={assessment.budget}"
            ),
            source_length=assessment.source_length,
            target_length=assessment.target_length,
            budget=assessment.budget,
            policy=assessment.policy,
            confidence=0.7,
        )
    ]
