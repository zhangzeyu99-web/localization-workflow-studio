"""Stable term rewrite checker for RPG/UI abbreviation style.

Design goal: rewrite term fragments safely, but avoid sentence-level rewrites.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_TAG_PATTERN = re.compile(r"\[/?color[^\]]*\]|\{[^}]+\}", re.IGNORECASE)
_WS_PATTERN = re.compile(r"\s+")
_EN_LETTER_PATTERN = re.compile(r"[A-Za-z]")
_SENTENCE_PUNCT_PATTERN = re.compile(r"[,.!?;:，。！？；：]")
_STRUCT_WORD_PATTERN = re.compile(r"\b(Increase|Increased|Added|Taken)\b", re.IGNORECASE)
RewriteMode = Literal["strict", "balanced", "aggressive"]

_FIXED_MAP = {
    "Critical Damage": "Crit DMG",
    "Attack Speed": "ASPD",
    "Sniper Rifle": "Sniper",
    "Damage": "DMG",
}

_EXACT_REWRITE = {
    "Attack Speed Increase": "ASPD+",
    "Damage Increase": "DMG+",
    "Damage Taken Added": "DMG Taken+",
    "Damage Taken Increase": "DMG Taken+",
    "Critical Damage Increase": "Crit DMG+",
    "Critical Damage Taken Added": "Crit DMG Taken+",
    "Fire Buff Damage Increase": "Fire DMG+",
    "Ice Buff Damage Increase": "Ice DMG+",
    "Sniper Rifle Attack Speed Increase": "Sniper ASPD+",
}


@dataclass
class TermRewriteResult:
    row_id: int
    check_type: str
    severity: str
    message: str
    original: str = ""
    translation: str = ""
    auto_fix: str = ""
    confidence: float = 1.0


def _clean_text(text: str) -> str:
    t = _TAG_PATTERN.sub("", str(text))
    t = _WS_PATTERN.sub(" ", t).strip()
    return t


def _apply_fixed_map(text: str) -> tuple[str, bool]:
    result = text
    changed = False
    for src, dst in sorted(_FIXED_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        pattern = re.compile(r"\b" + re.escape(src) + r"\b", re.IGNORECASE)
        new_result = pattern.sub(dst, result)
        if new_result != result:
            changed = True
            result = new_result
    return result, changed


def _apply_structure_rules(text: str) -> tuple[str, bool]:
    """Apply structure compression for term-like rows only."""
    changed = False
    result = text

    # X Taken Added / X Taken Increase(d) -> X Taken+
    result2 = re.sub(
        r"\b((?:Crit\s+DMG|DMG|[A-Za-z]+\s+DMG))\s+Taken\s+(Added|Increase|Increased)\b",
        r"\1 Taken+",
        result,
        flags=re.IGNORECASE,
    )
    if result2 != result:
        changed = True
        result = result2

    # X Increase(d) -> X+
    result2 = re.sub(
        r"\b((?:Crit\s+DMG|DMG|ASPD|[A-Za-z]+\s+DMG|[A-Za-z]+\s+ASPD))\s+Increase(?:d)?\b",
        r"\1+",
        result,
        flags=re.IGNORECASE,
    )
    if result2 != result:
        changed = True
        result = result2

    # X Added -> X+
    result2 = re.sub(
        r"\b((?:Crit\s+DMG|DMG|ASPD|[A-Za-z]+\s+DMG))\s+Added\b",
        r"\1+",
        result,
        flags=re.IGNORECASE,
    )
    if result2 != result:
        changed = True
        result = result2

    # Buff DMG+ -> DMG+ (e.g. Fire Buff DMG+ -> Fire DMG+)
    result2 = re.sub(r"\bBuff\s+DMG\+", "DMG+", result, flags=re.IGNORECASE)
    if result2 != result:
        changed = True
        result = result2

    # Normalize title for stable token display.
    result2 = re.sub(r"\btaken\+\b", "Taken+", result, flags=re.IGNORECASE)
    if result2 != result:
        changed = True
        result = result2

    result = _WS_PATTERN.sub(" ", result).strip()
    return result, changed


def _is_sentence_like(text: str) -> bool:
    clean = _clean_text(text)
    words = clean.split()
    if len(words) >= 9:
        return True
    if _SENTENCE_PUNCT_PATTERN.search(clean):
        return True
    return False


def _has_rewrite_signal(text: str) -> bool:
    t = _clean_text(text)
    has_term_source = any(
        re.search(r"\b" + re.escape(src) + r"\b", t, flags=re.IGNORECASE)
        for src in _FIXED_MAP.keys()
    )
    return has_term_source and bool(_STRUCT_WORD_PATTERN.search(t))


def _rewrite_translation(
    translation: str,
    mode: RewriteMode = "strict",
) -> tuple[str, float, bool]:
    """Return (suggestion, confidence, pending_for_ai)."""
    clean = _clean_text(translation)
    if not clean:
        return "", 0.0, False

    for src, dst in _EXACT_REWRITE.items():
        if clean.lower() == src.lower():
            return dst, 0.95, False

    result, changed_a = _apply_fixed_map(clean)
    changed_b = False
    sentence_like = _is_sentence_like(clean)
    use_structure_rules = (
        mode == "aggressive" or
        (mode == "balanced" and not sentence_like)
    )
    if use_structure_rules:
        result, changed_b = _apply_structure_rules(result)

    if result == clean:
        # Keep sentence intact in strict/balanced, let AI handle unresolved rewrite.
        if _has_rewrite_signal(clean):
            if mode == "strict":
                return "", 0.70, True
            if mode == "balanced":
                return "", 0.62 if sentence_like else 0.55, True
            return "", 0.50, True
        return "", 0.0, False

    if mode == "strict":
        confidence = 0.93 if changed_a else 0.0
    elif mode == "balanced":
        confidence = 0.82 if (changed_a or changed_b) else 0.0
    else:
        confidence = 0.75 if (changed_a or changed_b) else 0.0
    if "Taken+" in result:
        confidence = max(confidence, 0.88)
    return result, confidence, False


def check_term_rewrite(
    row_id: int,
    original: str,
    translation: str,
    mode: RewriteMode = "strict",
) -> list[TermRewriteResult]:
    """Suggest abbreviation-style term rewrite for one row.

    mode:
      - strict: term fragment replacements only (grammar-safe default)
      - balanced: fragment replacements + limited structure compression
      - aggressive: allow structure compression everywhere
    """
    trans = str(translation)
    if not _EN_LETTER_PATTERN.search(trans):
        return []

    suggestion, confidence, pending_for_ai = _rewrite_translation(trans, mode=mode)
    if not suggestion and not pending_for_ai:
        return []

    if suggestion and _clean_text(trans).lower() == _clean_text(suggestion).lower():
        return []

    if suggestion:
        return [
            TermRewriteResult(
                row_id=row_id,
                check_type="term_rewrite",
                severity="warning",
                message=f"建议术语缩写为: {suggestion}",
                original=str(original),
                translation=trans,
                auto_fix=suggestion,
                confidence=confidence,
            )
        ]

    return [
        TermRewriteResult(
            row_id=row_id,
            check_type="term_rewrite_pending",
            severity="warning",
            message=f"术语缩写未自动改写（模式={mode}，句子保护/规则未覆盖），请AI按规则处理",
            original=str(original),
            translation=trans,
            auto_fix="",
            confidence=confidence,
        )
    ]
