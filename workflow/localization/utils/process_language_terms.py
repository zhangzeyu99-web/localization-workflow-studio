"""Term-base loading and normalization for the main processing script.

Implementation module split out of process_language.py. Import these symbols
through process_language to keep the public surface stable.
"""
import json
import re
from pathlib import Path

import pandas as pd

from utils.term_checker import merge_builtin_name_terms


def _normalize_term_lookup(data: dict) -> dict[str, dict]:
    normalized: dict[str, dict] = {}
    for cn_term, value in data.items():
        cn = str(cn_term).strip()
        if not cn:
            continue

        primary = ''
        variants: list[str] = []
        enforce_case = False

        if isinstance(value, str):
            primary = value.strip()
        elif isinstance(value, list):
            items = [str(x).strip() for x in value if str(x).strip()]
            if items:
                primary = items[0]
                variants = items[1:]
        elif isinstance(value, dict):
            primary = str(value.get('primary', '')).strip()
            raw_vars = value.get('variants', [])
            if isinstance(raw_vars, str):
                raw_vars = [raw_vars]
            variants = [str(x).strip() for x in raw_vars if str(x).strip()]
            enforce_case = bool(value.get('enforce_case', False))

        seen = set()
        dedup_variants = []
        for v in variants:
            k = v.lower()
            if k == primary.lower() or k in seen:
                continue
            seen.add(k)
            dedup_variants.append(v)

        if primary or dedup_variants:
            if not primary:
                primary = dedup_variants[0]
                dedup_variants = dedup_variants[1:]
            constraint = ''
            if isinstance(value, dict):
                constraint = str(value.get('constraint', '')).strip()
                if constraint.lower() == 'nan':
                    constraint = ''
            normalized[cn] = {
                'primary': primary,
                'variants': dedup_variants,
                'enforce_case': enforce_case,
                'constraint': constraint,
            }
    return normalized


LANG_TERM_PATTERNS = {
    'en': {
        'primary': [r'英文', r'英语', r'主译法', r'名词译法', r'english'],
        'variant': [r'英语2', r'英文2', r'补充形式', r'另一词性', r'动词译法'],
    },
    'idn': {
        'primary': [r'印尼语', r'印度尼西亚语', r'indonesian', r'bahasa indonesia'],
        'variant': [r'印尼语2', r'印度尼西亚语2', r'补充形式', r'另一词性', r'动词译法'],
    },
    'ko': {
        'primary': [r'^ko$', r'^kr$', r'korean', r'韩语', r'韓語', r'한국어'],
        'variant': [r'^ko2$', r'^kr2$', r'ko\s*2', r'kr\s*2', r'korean2', r'韩语2', r'韓語2', r'한국어2', r'补充形式', r'另一词性', r'动词译法'],
    },
    'ja': {
        'primary': [r'^ja$', r'^jp$', r'japanese', r'日语', r'日語', r'日本語'],
        'variant': [r'^ja2$', r'^jp2$', r'ja\s*2', r'japanese2', r'日语2', r'日語2', r'日本語2', r'补充形式', r'另一词性', r'动词译法'],
    },
    'fr': {
        'primary': [r'^fr$', r'french', r'法语', r'法文', r'fran[cç]ais'],
        'variant': [r'^fr2$', r'fr\s*2', r'french2', r'法语2', r'法文2', r'补充形式', r'另一词性', r'动词译法'],
    },
    'de': {
        'primary': [r'^de$', r'german', r'德语', r'德文', r'deutsch'],
        'variant': [r'^de2$', r'de\s*2', r'german2', r'德语2', r'德文2', r'补充形式', r'另一词性', r'动词译法'],
    },
    'ru': {
        'primary': [r'^ru$', r'russian', r'俄语', r'俄文', r'русский'],
        'variant': [r'^ru2$', r'ru\s*2', r'russian2', r'俄语2', r'俄文2', r'补充形式', r'另一词性', r'动词译法'],
    },
    'it': {
        'primary': [r'^it$', r'italian', r'意大利语', r'意大利文', r'italiano'],
        'variant': [r'^it2$', r'it\s*2', r'italian2', r'意大利语2', r'意大利文2', r'补充形式', r'另一词性', r'动词译法'],
    },
    'es': {
        'primary': [r'^es$', r'spanish', r'西班牙语', r'西班牙文', r'español', r'espanol'],
        'variant': [r'^es2$', r'es\s*2', r'spanish2', r'西班牙语2', r'西班牙文2', r'补充形式', r'另一词性', r'动词译法'],
    },
    'pt': {
        'primary': [r'^pt$', r'portuguese', r'葡萄牙语', r'葡萄牙文', r'português', r'portugues'],
        'variant': [r'^pt2$', r'pt\s*2', r'portuguese2', r'葡萄牙语2', r'葡萄牙文2', r'补充形式', r'另一词性', r'动词译法'],
    },
    'tr': {
        'primary': [r'^tr$', r'turkish', r'土耳其语', r'土耳其文', r'türkçe', r'turkce'],
        'variant': [r'^tr2$', r'tr\s*2', r'turkish2', r'土耳其语2', r'土耳其文2', r'补充形式', r'另一词性', r'动词译法'],
    },
    'th': {
        'primary': [r'^th$', r'thai', r'泰语', r'泰文', r'ภาษาไทย'],
        'variant': [r'^th2$', r'th\s*2', r'thai2', r'泰语2', r'泰文2', r'补充形式', r'另一词性', r'动词译法'],
    },
    'ar': {
        'primary': [r'^ar$', r'arabic', r'阿拉伯语', r'阿拉伯文', r'العربية'],
        'variant': [r'^ar2$', r'ar\s*2', r'arabic2', r'阿拉伯语2', r'阿拉伯文2', r'补充形式', r'另一词性', r'动词译法'],
    },
}


def _load_term_base(path: str | None, lang: str = 'en') -> dict[str, dict]:
    """Load term base from Excel (.xlsx) or JSON (.json).

    Excel format: same as language table — ID / 原文 / 译文.
    JSON format:  {"lookup": {"中文": "English"}} or flat {"中文": "English"}.
    """
    if not path or not Path(path).exists():
        return merge_builtin_name_terms({}, lang)

    ext = Path(path).suffix.lower()
    if ext in ('.xlsx', '.xls'):
        df = pd.read_excel(path)
        cols = [str(c).strip() for c in df.columns]
        col_map = {str(c).strip(): c for c in df.columns}

        def _pick(patterns: list[str]) -> str | None:
            for c in cols:
                lc = c.lower()
                for p in patterns:
                    if re.search(p, lc):
                        return col_map[c]
            return None

        cn_col = _pick([r'中文术语', r'简体中文', r'中文原文', r'原文', r'中文', r'^cn$', r'^zh$', r'source', r'original'])
        lang_patterns = LANG_TERM_PATTERNS.get(lang, LANG_TERM_PATTERNS['en'])
        target_col = _pick(lang_patterns['primary']) or _pick([r'^en$', r'译文', r'翻译', r'translation', r'target'])
        alt_col = _pick(lang_patterns['variant']) or _pick([r'^en2$', r'variant', r'variants', r'alternate'])
        constraint_col = _pick([r'约束', r'constraint'])

        from utils.text_normalize import strip_tags_and_vars
        split_variants = re.compile(r'[;,|/、]+')
        lookup: dict[str, dict] = {}

        if cn_col and target_col:
            for _, row in df.iterrows():
                src = strip_tags_and_vars(str(row.get(cn_col, '')))
                primary = strip_tags_and_vars(str(row.get(target_col, '')))
                alt_raw = str(row.get(alt_col, '')).strip() if alt_col else ''
                constraint_raw = str(row.get(constraint_col, '')).strip() if constraint_col else ''
                if constraint_raw.lower() == 'nan':
                    constraint_raw = ''
                variants = []
                if alt_raw and alt_raw.lower() != 'nan':
                    variants = [
                        strip_tags_and_vars(x)
                        for x in split_variants.split(alt_raw)
                        if strip_tags_and_vars(x)
                    ]

                if not src:
                    continue

                entry = lookup.setdefault(src, {'primary': '', 'variants': [], 'enforce_case': False, 'constraint': ''})
                if primary and not entry['primary']:
                    entry['primary'] = primary
                for v in variants:
                    if v.lower() == entry['primary'].lower():
                        continue
                    if all(v.lower() != ex.lower() for ex in entry['variants']):
                        entry['variants'].append(v)
                if constraint_raw and not entry.get('constraint'):
                    entry['constraint'] = constraint_raw

            return merge_builtin_name_terms(_normalize_term_lookup(lookup), lang)

        # Fallback: old format parsing
        from utils.excel_reader import read_language_file, get_text_pairs
        df2, cm = read_language_file(path)
        pairs = get_text_pairs(df2, cm)
        raw_lookup = {}
        for _, row in pairs.iterrows():
            src = strip_tags_and_vars(str(row['original']))
            tgt = strip_tags_and_vars(str(row['translation']))
            if src and tgt:
                raw_lookup[src] = tgt
        return merge_builtin_name_terms(_normalize_term_lookup(raw_lookup), lang)

    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    raw = data.get('lookup', data) if isinstance(data, dict) else {}
    return merge_builtin_name_terms(_normalize_term_lookup(raw if isinstance(raw, dict) else {}), lang)
