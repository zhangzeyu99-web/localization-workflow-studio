"""Quality regression harness for localization outputs.

The harness is intentionally independent from one project workbook. It can run
small string fixtures and scan Excel language tables so quality regressions are
caught before final delivery.
"""
from __future__ import annotations

import html
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from openpyxl import load_workbook

from utils.readability_checker import check_readability
from utils.term_checker import check_chinese_residue, check_term_hit
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
GLOSSARY_SHEET_NAMES = {'术语表', 'glossary', 'terms', 'term base', 'termbase'}
TERM_BASE_FILENAME_KEYWORDS = {'术语', 'glossary', 'term', 'termbase'}
OUTPUT_DIR_NAME_HINTS = {'output', 'out', 'final', 'result'}
SUPPORT_SHEET_NAME_KEYWORDS = {
    '裁决',
    '审计',
    '返修',
    'audit',
    'decision',
    'review log',
    'fix log',
}
PERSON_NAME_CATEGORY_MARKERS = {'人名', '角色', 'person', 'name', 'character'}
SOFT_TERM_CATEGORY_MARKERS = {'soft', 'generic', 'common', '参考', '泛词', '通用词'}
GENERIC_ROLE_TARGETS = {
    'ally',
    'base',
    'boss',
    'captain',
    'character',
    'commander',
    'enemy',
    'hero',
    'member',
    'miner',
    'player',
    'protagonist',
    'role',
    'soldier',
    'survivor',
}

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


def load_fixture(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def check_row(row_id, source: str, translation: str, lang: str = 'en') -> list[CheckResult]:
    """Run all row-level hard gates used by the harness."""
    results: list[CheckResult] = []
    source = str(source or '')
    translation = str(translation or '')

    results.extend(check_variables(row_id, source, translation))
    results.extend(check_chinese_residue(row_id, translation))
    results.extend(check_readability(row_id, source, translation, lang=lang))
    results.extend(_check_surface_regressions(row_id, source, translation))

    if any(r.check_type == 'internal_token_leak' for r in results):
        results = [r for r in results if r.check_type != 'opaque_abbreviation']

    return results


def run_fixture(fixture: dict, lang: str = 'en') -> HarnessResult:
    cases = fixture.get('cases', [])
    result = HarnessResult(passed=True, total_cases=len(cases))

    for case in cases:
        row_id = case.get('id', '')
        case_lang = case.get('lang', lang)
        issues = check_row(
            row_id=row_id,
            source=case.get('source', ''),
            translation=case.get('translation', ''),
            lang=case_lang,
        )
        actual = sorted({issue.check_type for issue in issues})
        expected = sorted(case.get('expected_issues', []))

        for issue_type in actual:
            result.issue_counts[issue_type] += 1

        if actual != expected:
            result.passed = False
            result.failures.append({
                'id': row_id,
                'source': case.get('source', ''),
                'translation': case.get('translation', ''),
                'expected_issues': expected,
                'actual_issues': actual,
            })

    return result


def scan_workbook(
    path: str | Path,
    lang: str = 'en',
    fail_on: Iterable[str] | None = None,
    term_base: str | Path | Sequence[str | Path] | None = None,
    auto_discover_terms: bool = True,
) -> HarnessResult:
    """Scan a workbook language table.

    The scanner expects either headers containing ID/CN/EN-like names or a
    simple first-three-column layout: ID, source, target.
    """
    fail_set = set(fail_on or DEFAULT_HARD_ISSUES)
    result = HarnessResult(passed=True)
    workbook_path = Path(path)
    wb = load_workbook(workbook_path, read_only=False, data_only=False)

    try:
        term_sources = _resolve_term_base_paths(workbook_path, term_base, auto_discover_terms)
        term_context = _collect_term_context(wb, term_sources)
        strong_term_lookup = term_context['strong']
        soft_term_lookup = term_context['soft']
        person_name_terms = term_context['person_names']
        for ws in wb.worksheets:
            if _is_glossary_sheet(ws) or _is_support_sheet(ws):
                continue
            id_col, src_col, tgt_col = _detect_columns(ws)
            if src_col is None or tgt_col is None:
                continue
            max_col = max(c for c in (id_col, src_col, tgt_col) if c is not None) + 1
            numbered_rows: list[dict] = []
            for row_index, row in enumerate(
                ws.iter_rows(min_row=2, max_col=max_col, values_only=True),
                start=2,
            ):
                row_id = row[id_col] if id_col is not None else row_index
                source = row[src_col]
                target = row[tgt_col]
                if not isinstance(source, str) or not isinstance(target, str):
                    continue

                result.rows_scanned += 1
                numbered_rows.append({
                    'file': str(workbook_path),
                    'sheet': ws.title,
                    'row': row_index,
                    'id': row_id,
                    'source': source,
                    'translation': target,
                })
                row_issues = check_row(row_id, source, target, lang=lang)
                row_issues.extend(_check_ui_length(row_id, source, target, lang=lang))
                row_issues.extend(_check_terms(row_id, source, target, strong_term_lookup))
                row_issues.extend(_check_terms(row_id, source, target, soft_term_lookup, soft=True))
                row_issues.extend(_check_person_name_terms(row_id, source, target, person_name_terms))
                for issue in row_issues:
                    result.issue_counts[issue.check_type] += 1
                    if issue.check_type in fail_set:
                        result.passed = False
                        result.issues.append({
                            'file': str(workbook_path),
                            'sheet': ws.title,
                            'row': row_index,
                            'id': row_id,
                            'check_type': issue.check_type,
                            'severity': issue.severity,
                            'message': issue.message,
                            'source': source,
                            'translation': target,
                            'auto_fix': issue.auto_fix,
                        })

            _append_numbered_term_consistency_issues(numbered_rows, result, fail_set, strong_term_lookup, lang=lang)

        if result.rows_scanned == 0:
            result.passed = False
            result.issue_counts['workbook_scan_empty'] += 1
            result.issues.append({
                'file': str(workbook_path),
                'sheet': '',
                'row': 0,
                'id': '',
                'check_type': 'workbook_scan_empty',
                'severity': 'error',
                'message': 'No workbook rows were scanned; check sheet names and headers before treating QA as passed',
                'source': '',
                'translation': '',
                'auto_fix': '',
            })
    finally:
        wb.close()

    return result


def _collect_term_context(
    workbook,
    term_base: str | Path | Sequence[str | Path] | None,
) -> dict[str, object]:
    strong_terms: dict[str, dict] = {}
    soft_terms: dict[str, dict] = {}
    person_name_terms: list[tuple[str, str]] = []
    seen_person_names: set[tuple[str, str]] = set()

    def add(
        cn: str,
        target: str,
        category: str = '',
        variants: Sequence[str] | None = None,
        enforce_case: bool = False,
    ) -> None:
        cn = _clean_term_cell(cn)
        target = _clean_term_cell(target)
        category = _clean_term_cell(category)
        variants = [_clean_term_cell(v) for v in (variants or [])]
        variants = [v for v in variants if v and v.lower() != target.lower()]
        if not cn or not target:
            return
        if _is_person_name_category(category):
            if _is_generic_role_target(target):
                return
            key = (cn, target)
            if key not in seen_person_names:
                seen_person_names.add(key)
                person_name_terms.append(key)
            return
        bucket = soft_terms if _is_soft_term_category(category) else strong_terms
        _add_term_lookup_entry(bucket, cn, target, variants, enforce_case)

    _collect_terms_from_workbook(workbook, add)

    for path in _iter_term_base_paths(term_base):
        term_path = Path(path)
        if not term_path.exists():
            continue
        if term_path.suffix.lower() == '.json':
            _collect_terms_from_json(term_path, add)
            continue
        term_wb = load_workbook(term_path, read_only=False, data_only=True)
        try:
            _collect_terms_from_workbook(term_wb, add, all_sheets=True)
        finally:
            term_wb.close()

    # Strong terms win when a later soft row repeats the same source term.
    for cn in list(soft_terms):
        if cn in strong_terms:
            del soft_terms[cn]

    person_name_terms.sort(key=lambda item: len(item[0]), reverse=True)
    return {
        'strong': strong_terms,
        'soft': soft_terms,
        'person_names': person_name_terms,
    }


def _collect_terms_from_workbook(workbook, add, all_sheets: bool = False) -> None:
    for ws in workbook.worksheets:
        is_glossary_sheet = _is_glossary_sheet(ws)
        header = [str(value or '').strip().lower() for value in next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())]
        cn_idx = _find_header(header, {'cn', 'zh', '中文', '中文术语', '原文', 'source', 'original'})
        target_idx = _find_header(header, {'en', 'english', '英文', '英语', '译文', 'translation', 'target'})
        variant_idx = _find_header(header, {'en2', '英语2', '英文2', 'variant', 'variants', 'alternate', 'alternates'})
        category_idx = _find_header(header, {'分类', '类别', 'category', 'type', 'tag', 'tags'})
        enforce_idx = _find_header(header, {'enforce_case', '大小写', '大小写约束'})

        if is_glossary_sheet:
            cn_idx = cn_idx if cn_idx is not None else _fallback_index(header, 0)
            target_idx = target_idx if target_idx is not None else _fallback_index(header, 1)
            variant_idx = variant_idx if variant_idx is not None else _fallback_index(header, 2)
            category_idx = category_idx if category_idx is not None else _fallback_index(header, 3)
        elif not all_sheets:
            continue
        elif cn_idx is None or target_idx is None:
            continue
        elif category_idx is None and len(workbook.worksheets) > 1:
            # Avoid treating a full delivery workbook passed as --term-base as a glossary.
            continue

        if cn_idx is None or target_idx is None:
            continue
        max_idx = max(index for index in (cn_idx, target_idx, variant_idx, category_idx, enforce_idx) if index is not None)
        for row in ws.iter_rows(min_row=2, max_col=max_idx + 1, values_only=True):
            cn = row[cn_idx] if cn_idx < len(row) else ''
            target = row[target_idx] if target_idx < len(row) else ''
            raw_variants = row[variant_idx] if variant_idx is not None and variant_idx < len(row) else ''
            category = row[category_idx] if category_idx is not None and category_idx < len(row) else ''
            enforce_raw = row[enforce_idx] if enforce_idx is not None and enforce_idx < len(row) else ''
            add(cn, target, category, _split_term_variants(raw_variants), _truthy_cell(enforce_raw))


def _collect_terms_from_json(path: Path, add) -> None:
    data = json.loads(path.read_text(encoding='utf-8'))
    lookup = data.get('lookup', data) if isinstance(data, dict) else {}
    if not isinstance(lookup, dict):
        return
    for cn, value in lookup.items():
        if isinstance(value, str):
            add(cn, value)
        elif isinstance(value, list):
            values = [_clean_term_cell(v) for v in value]
            values = [v for v in values if v]
            if values:
                add(cn, values[0], variants=values[1:])
        elif isinstance(value, dict):
            target = value.get('primary') or value.get('en') or value.get('target') or ''
            raw_variants = value.get('variants', [])
            if isinstance(raw_variants, str):
                variants = _split_term_variants(raw_variants)
            else:
                variants = [_clean_term_cell(v) for v in raw_variants if _clean_term_cell(v)]
            category = value.get('category') or value.get('type') or value.get('constraint') or ''
            add(cn, target, category, variants, bool(value.get('enforce_case', False)))


def _add_term_lookup_entry(
    lookup: dict[str, dict],
    cn: str,
    target: str,
    variants: Sequence[str],
    enforce_case: bool,
) -> None:
    entry = lookup.setdefault(cn, {'primary': target, 'variants': [], 'enforce_case': False})
    if not entry.get('primary'):
        entry['primary'] = target
    for variant in variants:
        if variant.lower() == str(entry.get('primary', '')).lower():
            continue
        if all(variant.lower() != str(existing).lower() for existing in entry.get('variants', [])):
            entry.setdefault('variants', []).append(variant)
    entry['enforce_case'] = bool(entry.get('enforce_case')) or enforce_case


def _split_term_variants(value) -> list[str]:
    text = _clean_term_cell(value)
    if not text:
        return []
    return [_clean_term_cell(part) for part in re.split(r'[;,|/、]+', text) if _clean_term_cell(part)]


def _clean_term_cell(value) -> str:
    text = str(value or '').strip()
    return '' if text.lower() == 'nan' else text


def _truthy_cell(value) -> bool:
    text = _clean_term_cell(value).lower()
    return text in {'1', 'true', 'yes', 'y', '是', '强制'}


def _is_soft_term_category(category: str) -> bool:
    text = str(category or '').strip().lower()
    return any(marker in text for marker in SOFT_TERM_CATEGORY_MARKERS)


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
) -> list[CheckResult]:
    if not term_lookup:
        return []
    results: list[CheckResult] = []
    for issue in check_term_hit(row_id, source, translation, term_lookup):
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


def _resolve_term_base_paths(
    workbook_path: Path,
    term_base: str | Path | Sequence[str | Path] | None,
    auto_discover_terms: bool,
) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()

    def add(path: str | Path) -> None:
        candidate = Path(path)
        try:
            key = str(candidate.resolve()).lower()
        except OSError:
            key = str(candidate.absolute()).lower()
        if key in seen:
            return
        seen.add(key)
        paths.append(candidate)

    for path in _iter_term_base_paths(term_base):
        add(path)

    if auto_discover_terms:
        for path in _discover_term_base_paths(workbook_path):
            add(path)

    return paths


def _discover_term_base_paths(workbook_path: Path) -> list[Path]:
    workbook_path = Path(workbook_path)
    search_dirs = [workbook_path.parent]
    if _looks_like_output_dir(workbook_path.parent):
        search_dirs.append(workbook_path.parent.parent)

    discovered: list[Path] = []
    seen: set[str] = set()
    for directory in search_dirs:
        if not directory.exists() or not directory.is_dir():
            continue
        for candidate in directory.iterdir():
            if not candidate.is_file() or candidate.name.startswith('~$'):
                continue
            if candidate.resolve() == workbook_path.resolve():
                continue
            if candidate.suffix.lower() not in {'.xlsx', '.xlsm', '.json'}:
                continue
            stem = candidate.stem.lower().replace(' ', '')
            if not any(keyword in stem for keyword in TERM_BASE_FILENAME_KEYWORDS):
                continue
            key = str(candidate.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            discovered.append(candidate)
    return discovered


def _looks_like_output_dir(path: Path) -> bool:
    name = path.name.lower().replace('-', '_')
    return any(name == hint or name.startswith(f'{hint}_') or name.endswith(f'_{hint}') for hint in OUTPUT_DIR_NAME_HINTS)


def _iter_term_base_paths(term_base: str | Path | Sequence[str | Path] | None) -> list[str | Path]:
    if term_base is None:
        return []
    if isinstance(term_base, (str, Path)):
        return [term_base]
    return list(term_base)


def _find_header(headers: list[str], candidates: set[str]) -> int | None:
    for index, header in enumerate(headers):
        if header in candidates:
            return index
    return None


def _fallback_index(headers: list[str], fallback: int) -> int | None:
    return fallback if fallback < len(headers) else None


def _is_person_name_category(category: str) -> bool:
    text = str(category or '').strip().lower()
    return any(marker in text for marker in PERSON_NAME_CATEGORY_MARKERS)


def _is_generic_role_target(target: str) -> bool:
    normalized = re.sub(r"[^A-Za-z\s]", '', str(target or '')).strip().lower()
    return normalized in GENERIC_ROLE_TARGETS


def merge_results(results: list[HarnessResult]) -> HarnessResult:
    merged = HarnessResult(passed=all(r.passed for r in results))
    for result in results:
        merged.total_cases += result.total_cases
        merged.rows_scanned += result.rows_scanned
        merged.issue_counts.update(result.issue_counts)
        merged.issues.extend(result.issues)
        merged.failures.extend(result.failures)
    return merged


def _check_surface_regressions(row_id, source: str, translation: str) -> list[CheckResult]:
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


def _detect_columns(ws) -> tuple[int | None, int | None, int | None]:
    first = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
    headers = [str(v or '').strip().lower() for v in first]

    def pick(candidates: set[str], fallback: int | None) -> int | None:
        for idx, header in enumerate(headers):
            if header in candidates:
                return idx
        return fallback if fallback is None or fallback < len(headers) else None

    id_col = pick({'id', 'key'}, 0)
    src_col = pick({'cn', 'zh', '中文', '原文', 'source', 'original'}, 1)
    tgt_col = pick({'en', 'english', '译文', 'translation', 'target'}, 2)
    return id_col, src_col, tgt_col


def _is_glossary_sheet(ws) -> bool:
    title = str(ws.title or '').strip().lower()
    compact_title = re.sub(r'\s+', '', title)
    if title in GLOSSARY_SHEET_NAMES or compact_title in {'termbase', 'terms'} or '术语' in title:
        return True

    first = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
    headers = [str(v or '').strip().lower() for v in first[:4]]
    return headers == ['cn', 'en', 'en2', '分类']


def _is_support_sheet(ws) -> bool:
    title = str(ws.title or '').strip().lower()
    compact_title = re.sub(r'[\s_-]+', '', title)
    return any(keyword in title or keyword.replace(' ', '') in compact_title for keyword in SUPPORT_SHEET_NAME_KEYWORDS)


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
        r'^\s*(?:\\n|\n|<[^>]+>|\{[^}]+\}|##\d+|'
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
        r'^\s*(?:<[^>]+>\s*)*(?:##\d+|\{[^}]+\}|\[[A-Za-z]+\d+\])',
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
