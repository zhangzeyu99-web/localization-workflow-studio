"""Term-base collection and workbook sheet/column detection for the quality harness.

Implementation module split out of utils/quality_harness.py. Import these
symbols through utils.quality_harness to keep the public surface stable.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Sequence

from openpyxl import load_workbook

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

LANGUAGE_TARGET_HEADERS = {
    'en': {'en', 'english', '英文', '英语', '译文', 'translation', 'target'},
    'ko': {'ko', 'kr', 'korean', '韩语', '韓語', '한국어', '译文', 'translation', 'target'},
    'ja': {'ja', 'jp', 'japanese', '日语', '日語', '日本語', '译文', 'translation', 'target'},
}

LANGUAGE_VARIANT_HEADERS = {
    'en': {'en2', 'english2', '英语2', '英文2', 'variant', 'variants', 'alternate', 'alternates'},
    'ko': {'ko2', 'kr2', 'korean2', '韩语2', '韓語2', '한국어2', 'variant', 'variants', 'alternate', 'alternates'},
    'ja': {'ja2', 'jp2', 'japanese2', '日语2', '日語2', '日本語2', 'variant', 'variants', 'alternate', 'alternates'},
}


def _target_header_candidates(lang: str) -> set[str]:
    return LANGUAGE_TARGET_HEADERS.get(lang, LANGUAGE_TARGET_HEADERS['en'])


def _variant_header_candidates(lang: str) -> set[str]:
    return LANGUAGE_VARIANT_HEADERS.get(lang, LANGUAGE_VARIANT_HEADERS['en'])


def _all_target_header_candidates() -> set[str]:
    values: set[str] = set()
    for candidates in LANGUAGE_TARGET_HEADERS.values():
        values.update(candidates)
    return values


def _all_variant_header_candidates() -> set[str]:
    values: set[str] = set()
    for candidates in LANGUAGE_VARIANT_HEADERS.values():
        values.update(candidates)
    return values


def _collect_term_context(
    workbook,
    term_base: str | Path | Sequence[str | Path] | None,
    lang: str = 'en',
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

    _collect_terms_from_workbook(workbook, add, lang=lang)

    for path in _iter_term_base_paths(term_base):
        term_path = Path(path)
        if not term_path.exists():
            continue
        if term_path.suffix.lower() == '.json':
            _collect_terms_from_json(term_path, add, lang=lang)
            continue
        term_wb = load_workbook(term_path, read_only=False, data_only=True)
        try:
            _collect_terms_from_workbook(term_wb, add, all_sheets=True, lang=lang)
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


def _collect_terms_from_workbook(workbook, add, all_sheets: bool = False, lang: str = 'en') -> None:
    for ws in workbook.worksheets:
        is_glossary_sheet = _is_glossary_sheet(ws)
        header = [str(value or '').strip().lower() for value in next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())]
        cn_idx = _find_header(header, {'cn', 'zh', '中文', '简体中文', '中文术语', '原文', 'source', 'original'})
        target_idx = _find_header(header, _target_header_candidates(lang))
        variant_idx = _find_header(header, _variant_header_candidates(lang))
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


def _collect_terms_from_json(path: Path, add, lang: str = 'en') -> None:
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
            target = value.get('primary') or value.get(lang) or value.get('target') or value.get('en') or ''
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


def _is_person_name_category(category: str) -> bool:
    text = str(category or '').strip().lower()
    return any(marker in text for marker in PERSON_NAME_CATEGORY_MARKERS)


def _is_generic_role_target(target: str) -> bool:
    normalized = re.sub(r"[^A-Za-z\s]", '', str(target or '')).strip().lower()
    return normalized in GENERIC_ROLE_TARGETS


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


def _detect_columns(ws, lang: str = 'en') -> tuple[int | None, int | None, int | None]:
    first = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
    headers = [str(v or '').strip().lower() for v in first]

    def pick(candidates: set[str], fallback: int | None) -> int | None:
        for idx, header in enumerate(headers):
            if header in candidates:
                return idx
        return fallback if fallback is None or fallback < len(headers) else None

    id_col = pick({'id', 'key'}, 0)
    src_col = pick({'cn', 'zh', '中文', '简体中文', '原文', 'source', 'original'}, 1)
    tgt_col = pick(_target_header_candidates(lang), 2)
    return id_col, src_col, tgt_col


def _is_glossary_sheet(ws) -> bool:
    title = str(ws.title or '').strip().lower()
    compact_title = re.sub(r'\s+', '', title)
    if title in GLOSSARY_SHEET_NAMES or compact_title in {'termbase', 'terms'} or '术语' in title:
        return True

    first = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
    headers = [str(v or '').strip().lower() for v in first[:4]]
    if headers == ['cn', 'en', 'en2', '分类']:
        return True
    return (
        len(headers) >= 4
        and headers[0] in {'cn', 'zh', 'source', 'original', '中文', '简体中文', '原文'}
        and headers[1] in _all_target_header_candidates()
        and headers[2] in _all_variant_header_candidates()
        and headers[3] in {'分类', '类别', 'category', 'type', 'tag', 'tags'}
    )


def _is_support_sheet(ws) -> bool:
    title = str(ws.title or '').strip().lower()
    compact_title = re.sub(r'[\s_-]+', '', title)
    return any(keyword in title or keyword.replace(' ', '') in compact_title for keyword in SUPPORT_SHEET_NAME_KEYWORDS)
