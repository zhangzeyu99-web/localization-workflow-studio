"""Row-level rule checks for the quality harness.

Implementation module split out of utils/quality_harness.py. Import these
symbols through utils.quality_harness to keep the public surface stable.
"""
from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass, field

from utils.readability_checker import check_readability
from utils.term_checker import check_chinese_residue, check_term_hit
from utils.text_normalize import strip_tags_and_vars
from utils.ui_detector import is_ui_text
from utils.ui_length_checker import check_ui_length
from utils.variable_checker import CheckResult, check_all as check_variables

HTML_ENTITY_PATTERN = re.compile(r'&(?:#[0-9]+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);')
INTERNAL_TOKEN_PATTERN = re.compile(r'\b[A-Z]{2,}[A-Z0-9]*\d[A-Z0-9]*\b')
HASH_CODE_PATTERN = re.compile(r'#[A-Z]{2,}(?:##\d+|#\d+)*\b')
HASHED_INTERNAL_CODE_PATTERN = re.compile(r'\b[A-Z]{2,}[A-Z0-9]*#[A-Z][A-Z0-9#]*\b')
COLOR_TAG_PATTERN = re.compile(r'(?:\[/?color(?:=[^\]]+)?\]|</?color(?:=[^>]+)?>)', re.IGNORECASE)
LETTER_PLACEHOLDER_COMPACTION_PATTERN = re.compile(r'\b[A-Z]{1,6}(?:##\d+|#\d+){2,}[A-Z0-9#]*\b')
PLACEHOLDER_WORD_GLUE_PATTERN = re.compile(r'##\d+[A-Za-z]{2,}##\d+')
ORPHAN_LEADING_CLITIC_PATTERN = re.compile(r"^\s*['’]s\b", re.IGNORECASE)
BROKEN_BULLET_PATTERN = re.compile(r'(?:^|\\n|\n)\?[A-Za-z0-9]')
SANDWICHED_QUESTION_PATTERN = re.compile(r'\b[A-Za-z0-9]+\s+\?\s+[A-Za-z0-9]')
SOURCE_SEPARATOR_PATTERN = re.compile(r'[·•・:：/|｜>→\-]')
FULLWIDTH_PUNCTUATION_PATTERN = re.compile(r'[，。！？：；（）【】％＋－]')
WORD_START_PATTERN = re.compile(r'[A-Za-z]')
NUMBERED_SOURCE_PATTERN = re.compile(r'^\s*(?P<stem>.+?)-(?P<number>\d{1,6})\s*$')
NUMBERED_TARGET_PATTERN = re.compile(r'^\s*(?P<stem>.+?)(?P<separator>\s*-\s*)(?P<number>\d{1,6})\s*$')
CJK_PATTERN = re.compile(r'[\u3400-\u9fff]')
MIN_NUMBERED_TERM_GROUP_SIZE = 3

DEFAULT_HARD_ISSUES = {
    'variable_missing',
    'variable_extra',
    'variable_order',
    'bbcode_open_mismatch',
    'bbcode_close_mismatch',
    'bbcode_unclosed',
    'bbcode_color_mismatch',
    'newline_mismatch',
    'chinese_residue',
    'term_missing',
    'term_partial_hit',
    'term_capitalization',
    'ui_length_overflow',
    'opaque_abbreviation',
    'clipped_word',
    'title_case_overuse',
    'romanized_name_residue',
    'internal_token_leak',
    'hash_code_abbreviation',
    'placeholder_compaction',
    'placeholder_word_glue',
    'html_entity_leak',
    'orphan_leading_clitic',
    'leading_lowercase',
    'punctuation_corruption',
    'fullwidth_punctuation',
    'person_name_term_mismatch',
    'numbered_term_inconsistency',
}


@dataclass
class HarnessResult:
    passed: bool
    total_cases: int = 0
    rows_scanned: int = 0
    issue_counts: Counter = field(default_factory=Counter)
    issues: list[dict] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'passed': self.passed,
            'total_cases': self.total_cases,
            'rows_scanned': self.rows_scanned,
            'issue_counts': dict(self.issue_counts),
            'issues': self.issues,
            'failures': self.failures,
        }


def check_row(row_id, source: str, translation: str, lang: str = 'en') -> list[CheckResult]:
    """Run all row-level hard gates used by the harness."""
    results: list[CheckResult] = []
    source = str(source or '')
    translation = str(translation or '')

    results.extend(check_variables(row_id, source, translation))
    results.extend(check_chinese_residue(row_id, translation, lang=lang))
    results.extend(check_readability(row_id, source, translation, lang=lang))
    results.extend(_check_surface_regressions(row_id, source, translation, lang=lang))

    if any(r.check_type == 'internal_token_leak' for r in results):
        results = [r for r in results if r.check_type != 'opaque_abbreviation']

    return results


def _check_ui_length(row_id, source: str, translation: str, lang: str) -> list[CheckResult]:
    is_ui, _, _ = is_ui_text(source, translation)
    return [
        _coerce_check_result(issue, source, translation)
        for issue in check_ui_length(row_id, source, translation, is_ui=is_ui, lang=lang)
    ]


def _check_terms(
    row_id,
    source: str,
    translation: str,
    term_lookup: dict[str, dict],
    soft: bool = False,
    lang: str = 'en',
) -> list[CheckResult]:
    if not term_lookup:
        return []
    source_key = str(source or '').strip()
    # A glossary row is reliable as a hard gate for a standalone UI label.
    # Inside a longer sentence, requiring every matched Chinese subterm to
    # appear literally in English creates false blockers for natural phrasing
    # (for example, "奖励已领取" -> "Claimed"). Projects can opt a term into
    # contextual enforcement through a strong-term category.
    applicable_terms = term_lookup if soft else {
        term: entry
        for term, entry in term_lookup.items()
        if term == source_key or bool(entry.get('enforce_in_context'))
    }
    if not applicable_terms:
        return []
    results: list[CheckResult] = []
    for issue in check_term_hit(row_id, source, translation, applicable_terms, lang=lang):
        check_type = issue.check_type
        severity = issue.severity
        message = issue.message
        if soft:
            check_type = f"term_soft_{check_type.removeprefix('term_')}"
            severity = 'warning'
            message = f"Soft term warning: {message}"
        results.append(_coerce_check_result(issue, source, translation, check_type=check_type, severity=severity, message=message))
    return results


def _coerce_check_result(
    issue,
    source: str,
    translation: str,
    check_type: str | None = None,
    severity: str | None = None,
    message: str | None = None,
) -> CheckResult:
    return CheckResult(
        row_id=getattr(issue, 'row_id', ''),
        check_type=check_type or getattr(issue, 'check_type', ''),
        severity=severity or getattr(issue, 'severity', 'error'),
        message=message or getattr(issue, 'message', ''),
        original=source,
        translation=translation,
        auto_fix=getattr(issue, 'auto_fix', ''),
        confidence=getattr(issue, 'confidence', 1.0),
    )


def _append_numbered_term_consistency_issues(
    rows: list[dict],
    result: HarnessResult,
    fail_set: set[str],
    term_lookup: dict[str, dict] | None = None,
    lang: str = 'en',
) -> None:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        parsed = _parse_numbered_source(row.get('source', ''))
        if not parsed:
            continue
        source_stem, source_number = parsed
        target_parts = _parse_numbered_target(row.get('translation', ''), source_number)
        item = dict(row)
        item['source_stem'] = source_stem
        item['source_number'] = source_number
        item['target_signature'] = target_parts
        groups.setdefault(source_stem, []).append(item)

    for source_stem, group in groups.items():
        if len(group) < MIN_NUMBERED_TERM_GROUP_SIZE:
            continue
        signatures = Counter(item['target_signature'] for item in group)
        if len(signatures) <= 1:
            continue
        canonical = _choose_numbered_canonical(source_stem, group, term_lookup or {}, lang)
        expected = _format_numbered_target_signature(canonical)
        for item in group:
            if item['target_signature'] == canonical:
                continue
            actual = _format_numbered_target_signature(item['target_signature'])
            message = (
                f"Numbered source term '{source_stem}-#' uses inconsistent target prefixes; "
                f"expected '{expected}', got '{actual}'"
            )
            result.issue_counts['numbered_term_inconsistency'] += 1
            if 'numbered_term_inconsistency' in fail_set:
                result.passed = False
                result.issues.append({
                    'file': item['file'],
                    'sheet': item['sheet'],
                    'row': item['row'],
                    'id': item['id'],
                    'check_type': 'numbered_term_inconsistency',
                    'severity': 'error',
                    'message': message,
                    'source': item['source'],
                    'translation': item['translation'],
                    'auto_fix': '',
                })


def _choose_numbered_canonical(
    source_stem: str,
    group: list[dict],
    term_lookup: dict[str, dict],
    lang: str,
) -> tuple[str, str, str]:
    term_signature = _numbered_signature_from_term(source_stem, term_lookup)
    if term_signature is not None:
        return term_signature
    for item in group:
        if _numbered_item_is_readable(item, lang):
            return item['target_signature']
    return group[0]['target_signature']


def _numbered_signature_from_term(
    source_stem: str,
    term_lookup: dict[str, dict],
) -> tuple[str, str, str] | None:
    entry = term_lookup.get(source_stem)
    if not entry:
        return None
    primary = _primary_term(entry)
    if not primary:
        return None
    return (primary, '-', '#')


def _primary_term(entry) -> str:
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, list):
        return str(entry[0]).strip() if entry else ''
    if isinstance(entry, dict):
        return str(entry.get('primary', '')).strip()
    return ''


def _numbered_item_is_readable(item: dict, lang: str) -> bool:
    issues = check_row(item.get('id'), item.get('source', ''), item.get('translation', ''), lang=lang)
    return not any(issue.check_type in DEFAULT_HARD_ISSUES for issue in issues)


def _parse_numbered_source(source: str) -> tuple[str, str] | None:
    match = NUMBERED_SOURCE_PATTERN.match(str(source or ''))
    if not match:
        return None
    stem = match.group('stem').strip()
    if len(stem) < 2 or not CJK_PATTERN.search(stem):
        return None
    return stem, match.group('number')


def _parse_numbered_target(translation: str, source_number: str) -> tuple[str, str, str]:
    text = str(translation or '').strip()
    match = NUMBERED_TARGET_PATTERN.match(text)
    if not match:
        return (text, '', '')
    stem = re.sub(r'\s+', ' ', match.group('stem').strip())
    separator = match.group('separator')
    target_number = match.group('number')
    if target_number != source_number:
        return (stem, separator, target_number)
    return (stem, separator, '#')


def _format_numbered_target_signature(signature: tuple[str, str, str]) -> str:
    stem, separator, number = signature
    if not separator:
        return stem
    suffix = '#' if number == '#' else number
    return f'{stem}{separator}{suffix}'


def _check_person_name_terms(
    row_id,
    source: str,
    translation: str,
    person_name_terms: list[tuple[str, str]],
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for cn_name, expected in _matched_person_name_terms(source, person_name_terms):
        if _contains_expected_person_name(translation, expected):
            continue
        results.append(_issue(
            row_id,
            'person_name_term_mismatch',
            f"Person name '{cn_name}' must use glossary spelling '{expected}'",
            source,
            translation,
        ))
    return results


def _matched_person_name_terms(
    source: str,
    person_name_terms: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    source = str(source or '')
    covered: list[tuple[int, int]] = []
    matches: list[tuple[str, str]] = []
    for cn_name, expected in person_name_terms:
        start = 0
        while True:
            index = source.find(cn_name, start)
            if index < 0:
                break
            span = (index, index + len(cn_name))
            if not any(not (span[1] <= left or span[0] >= right) for left, right in covered):
                covered.append(span)
                matches.append((cn_name, expected))
            start = index + 1
    return matches


def _contains_expected_person_name(translation: str, expected: str) -> bool:
    expected = str(expected or '').strip()
    if not expected:
        return True
    pattern = re.compile(rf"(?<![A-Za-z]){re.escape(expected)}(?:'s)?(?![A-Za-z])")
    return bool(pattern.search(str(translation or '')))


def _check_surface_regressions(row_id, source: str, translation: str, lang: str = 'en') -> list[CheckResult]:
    results: list[CheckResult] = []

    if HTML_ENTITY_PATTERN.search(translation):
        results.append(_issue(
            row_id,
            'html_entity_leak',
            'HTML entity leaked into translation',
            source,
            translation,
            auto_fix=html.unescape(translation),
        ))

    colorless_translation = COLOR_TAG_PATTERN.sub('', translation)

    token_match = INTERNAL_TOKEN_PATTERN.search(colorless_translation)
    if token_match and not _looks_like_allowed_runtime_code(token_match.group(0), source):
        results.append(_issue(
            row_id,
            'internal_token_leak',
            f"Internal token-like text leaked: {token_match.group(0)}",
            source,
            translation,
        ))

    hashed_internal_match = HASHED_INTERNAL_CODE_PATTERN.search(colorless_translation)
    if hashed_internal_match:
        results.append(_issue(
            row_id,
            'hash_code_abbreviation',
            f"Hashed internal-code abbreviation leaked: {hashed_internal_match.group(0)}",
            source,
            translation,
        ))

    hash_match = HASH_CODE_PATTERN.search(colorless_translation)
    if hash_match:
        results.append(_issue(
            row_id,
            'hash_code_abbreviation',
            f"Hash-prefixed code abbreviation leaked: {hash_match.group(0)}",
            source,
            translation,
        ))

    compact_match = LETTER_PLACEHOLDER_COMPACTION_PATTERN.search(translation)
    if compact_match:
        results.append(_issue(
            row_id,
            'placeholder_compaction',
            f"Letters are compacted into placeholders: {compact_match.group(0)}",
            source,
            translation,
        ))

    glued_match = PLACEHOLDER_WORD_GLUE_PATTERN.search(translation)
    if glued_match:
        results.append(_issue(
            row_id,
            'placeholder_word_glue',
            f"Word is glued between placeholders: {glued_match.group(0)}",
            source,
            translation,
        ))

    if lang != 'en':
        return results

    if ORPHAN_LEADING_CLITIC_PATTERN.search(translation):
        results.append(_issue(
            row_id,
            'orphan_leading_clitic',
            "Translation starts with orphan possessive clitic",
            source,
            translation,
        ))

    if _has_leading_lowercase(source, translation):
        results.append(_issue(
            row_id,
            'leading_lowercase',
            "Sentence-like translation starts with lowercase",
            source,
            translation,
            severity='warning',
        ))

    if _has_punctuation_corruption(source, translation):
        results.append(_issue(
            row_id,
            'punctuation_corruption',
            "Suspicious quote or question punctuation corruption",
            source,
            translation,
        ))

    if FULLWIDTH_PUNCTUATION_PATTERN.search(translation):
        results.append(_issue(
            row_id,
            'fullwidth_punctuation',
            "Fullwidth punctuation remains in Latin-script translation",
            source,
            translation,
        ))

    return results


def _issue(
    row_id,
    check_type: str,
    message: str,
    source: str,
    translation: str,
    severity: str = 'error',
    auto_fix: str = '',
) -> CheckResult:
    return CheckResult(
        row_id=row_id,
        check_type=check_type,
        severity=severity,
        message=message,
        original=source,
        translation=translation,
        auto_fix=auto_fix,
    )


def _looks_like_allowed_runtime_code(token: str, source: str) -> bool:
    if token in source:
        return True
    # Common version-style or short gameplay terms are handled elsewhere.
    return bool(re.fullmatch(r'(?:HP|ATK|DEF|DMG|DPS|PVP|PVE|VIP|FPS|SFX|UI|ID)\d*', token))


def _visible_start(text: str) -> str:
    stripped = str(text)
    token_pattern = re.compile(
        r'^\s*(?:\\n|\n|<[^>]+>|#\{[^,{}]+,\{[^}]+\}\}|#\{[^,{}]+,[^}]*\}|#L\{[^}]*\}|\{[^}]+\}|##\d+|'
        r'\[(?:/?size(?:=\d+)?|/?color(?:=[^\]]+)?|[A-Za-z]+\d+|\d+)\])+',
        re.IGNORECASE,
    )
    while True:
        new = token_pattern.sub('', stripped)
        if new == stripped:
            break
        stripped = new
    stripped = re.sub(r'^\s*(?:\\n|\n|\d+[\.)]\s*)+', '', stripped)
    return stripped.lstrip()


def _has_leading_lowercase(source: str, translation: str) -> bool:
    if re.match(r'^\s*\d', translation):
        return False
    if _starts_with_runtime_payload(translation):
        return False
    visible_words = strip_tags_and_vars(translation).replace('\\n', ' ')
    if not WORD_START_PATTERN.search(visible_words):
        return False
    visible = _visible_start(translation)
    match = WORD_START_PATTERN.search(visible)
    if not match:
        return False
    char = match.group(0)
    if not char.islower():
        return False
    source_visible_len = len(re.sub(r'\s+', '', source))
    return source_visible_len >= 8 or bool(re.search(r'[。！？!?]$', source))


def _starts_with_runtime_payload(text: str) -> bool:
    return bool(re.match(
        r'^\s*(?:<[^>]+>\s*)*(?:##\d+|#\{[^,{}]+,\{[^}]+\}\}|#\{[^,{}]+,[^}]*\}|#L\{[^}]*\}|\{[^}]+\}|\[[A-Za-z]+\d+\])',
        str(text),
    ))


def _has_punctuation_corruption(source: str, translation: str) -> bool:
    if translation.count('"') % 2 == 1 and '"' not in source:
        return True
    if '◇' in source and BROKEN_BULLET_PATTERN.search(translation):
        return True
    source_asks_question = bool(re.search(r'[？?]|吗|么|什么|怎么|为何|是否', source))
    source_has_separator = bool(SOURCE_SEPARATOR_PATTERN.search(str(source or '')))
    if not source_asks_question and source_has_separator and SANDWICHED_QUESTION_PATTERN.search(translation):
        return True
    if source_asks_question and '?' not in translation and '"' in translation:
        return True
    return False
