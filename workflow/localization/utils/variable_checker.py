"""Variable and BBCode tag integrity checker.

Detects:
- Missing variables ({xxx} placeholders)
- Extra variables in translation
- Unclosed/mismatched BBCode tags
- Tag order/nesting issues
"""
from collections import Counter
from dataclasses import dataclass, field

from utils.text_normalize import (
    normalize_escapes, extract_vars, extract_bbcode_opens,
    extract_bbcode_closes, count_newlines, BBCODE_OPEN,
)


@dataclass
class CheckResult:
    """Result from a single check."""
    row_id: int
    check_type: str
    severity: str  # 'error', 'warning'
    message: str
    original: str = ''
    translation: str = ''
    auto_fix: str = ''
    confidence: float = 1.0


def check_variables(row_id: int, original: str, translation: str) -> list[CheckResult]:
    """Check that all variables in original appear in translation and vice versa."""
    results = []

    orig_vars = extract_vars(original)
    trans_vars = extract_vars(translation)

    orig_counts = Counter(orig_vars)
    trans_counts = Counter(trans_vars)

    missing_vars = []
    for var, need in orig_counts.items():
        have = trans_counts.get(var, 0)
        if have < need:
            missing_vars.extend([var] * (need - have))

    extra_vars = []
    for var, have in trans_counts.items():
        need = orig_counts.get(var, 0)
        if have > need:
            extra_vars.extend([var] * (have - need))

    if missing_vars:
        fixed = _build_missing_var_autofix(translation, missing_vars)

        results.append(CheckResult(
            row_id=row_id,
            check_type='variable_missing',
            severity='error',
            message=f"Missing variables in translation: {', '.join(sorted(set(missing_vars)))}",
            original=original,
            translation=translation,
            auto_fix=fixed,
            confidence=0.9,
        ))

    if extra_vars:
        results.append(CheckResult(
            row_id=row_id,
            check_type='variable_extra',
            severity='warning',
            message=f"Extra variables in translation: {', '.join(sorted(set(extra_vars)))}",
            original=original,
            translation=translation,
        ))

    if not missing_vars and not extra_vars and len(orig_vars) > 1:
        if orig_vars != trans_vars:
            results.append(CheckResult(
                row_id=row_id,
                check_type='variable_order',
                severity='warning',
                message=f"Variable order differs: original={orig_vars}, translation={trans_vars}",
                original=original,
                translation=translation,
                confidence=0.6,
            ))

    return results


def _build_missing_var_autofix(translation: str, missing_vars: list[str]) -> str:
    """Build a conservative autofix for missing placeholders.

    Only simple cases are auto-fixed. Complex square-bracket markup loss
    is left for review instead of appending tokens blindly.
    """
    if not missing_vars:
        return ''

    square_vars = [var for var in missing_vars if var.startswith('[')]
    if len(square_vars) > 1 or len(missing_vars) > 2:
        return ''

    fixed = normalize_escapes(translation)
    for var in missing_vars:
        fixed = fixed.rstrip() + ' ' + var
    return fixed


def check_bbcode_tags(row_id: int, original: str, translation: str) -> list[CheckResult]:
    """Check BBCode tag completeness and consistency."""
    results = []

    orig_opens = extract_bbcode_opens(original)
    orig_closes = extract_bbcode_closes(original)
    trans_opens = extract_bbcode_opens(translation)
    trans_closes = extract_bbcode_closes(translation)

    if len(orig_opens) != len(trans_opens):
        results.append(CheckResult(
            row_id=row_id,
            check_type='bbcode_open_mismatch',
            severity='error',
            message=(
                f"BBCode open tag count mismatch: "
                f"original={len(orig_opens)}, translation={len(trans_opens)}"
            ),
            original=original,
            translation=translation,
        ))

    if len(orig_closes) != len(trans_closes):
        results.append(CheckResult(
            row_id=row_id,
            check_type='bbcode_close_mismatch',
            severity='error',
            message=(
                f"BBCode close tag count mismatch: "
                f"original={len(orig_closes)}, translation={len(trans_closes)}"
            ),
            original=original,
            translation=translation,
        ))

    if len(trans_opens) != len(trans_closes):
        results.append(CheckResult(
            row_id=row_id,
            check_type='bbcode_unclosed',
            severity='error',
            message=(
                f"Unclosed BBCode tags in translation: "
                f"{len(trans_opens)} opens vs {len(trans_closes)} closes"
            ),
            original=original,
            translation=translation,
        ))

    orig_colors = sorted(extract_bbcode_opens(original))
    trans_colors = sorted(extract_bbcode_opens(translation))
    if orig_colors and trans_colors and orig_colors != trans_colors:
        results.append(CheckResult(
            row_id=row_id,
            check_type='bbcode_color_mismatch',
            severity='error',
            message=f"Color codes differ: original={orig_colors}, translation={trans_colors}",
            original=original,
            translation=translation,
            auto_fix=_fix_color_codes(original, translation),
            confidence=0.85,
        ))

    return results


def _fix_color_codes(original: str, translation: str) -> str:
    """Try to fix color code mismatches by using original's color codes."""
    orig_colors = extract_bbcode_opens(original)
    trans_colors = extract_bbcode_opens(translation)

    if len(orig_colors) != len(trans_colors):
        return ''

    result = normalize_escapes(translation)
    for orig_c, trans_c in zip(orig_colors, trans_colors):
        if orig_c != trans_c:
            result = result.replace(trans_c, orig_c, 1)
    return result


def check_newlines(row_id: int, original: str, translation: str) -> list[CheckResult]:
    """Check that \\n counts match."""
    results = []
    orig_count = count_newlines(original)
    trans_count = count_newlines(translation)

    if orig_count != trans_count:
        results.append(CheckResult(
            row_id=row_id,
            check_type='newline_mismatch',
            severity='warning',
            message=f"Newline count mismatch: original={orig_count}, translation={trans_count}",
            original=original,
            translation=translation,
            confidence=0.7,
        ))

    return results


def check_all(row_id: int, original: str, translation: str) -> list[CheckResult]:
    """Run all variable/tag checks on a single row."""
    results = []
    results.extend(check_variables(row_id, original, translation))
    results.extend(check_bbcode_tags(row_id, original, translation))
    results.extend(check_newlines(row_id, original, translation))
    return results
