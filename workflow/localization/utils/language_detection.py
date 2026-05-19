"""Lightweight language inspection for localization workspaces."""
from __future__ import annotations

import re
from pathlib import Path

from utils.excel_reader import read_language_file, get_text_pairs


EN_STOPWORDS = {
    'the', 'and', 'to', 'of', 'in', 'for', 'with', 'you', 'your', 'can',
    'not', 'this', 'that', 'is', 'are', 'will', 'have', 'from', 'reward',
    'building', 'level', 'please', 'unlock',
}

IDN_STOPWORDS = {
    'yang', 'dan', 'di', 'ke', 'dengan', 'untuk', 'tidak', 'akan', 'dapat',
    'pada', 'dari', 'ini', 'itu', 'adalah', 'bangunan', 'tingkatkan',
    'hadiah', 'persekutuan', 'pemimpin', 'gunakan', 'dalam',
}


def detect_text_language(texts: list[str]) -> str:
    joined = ' '.join(str(text) for text in texts if str(text).strip())
    if not joined.strip():
        return 'unknown'

    if re.search(r'[\u4e00-\u9fff]', joined):
        return 'zh'

    words = re.findall(r"[A-Za-z']+", joined.lower())
    if not words:
        return 'unknown'

    en_hits = sum(1 for word in words if word in EN_STOPWORDS)
    idn_hits = sum(1 for word in words if word in IDN_STOPWORDS)

    if idn_hits > en_hits:
        return 'idn'
    if en_hits > idn_hits:
        return 'en'

    # Fallback heuristics for short UI phrases.
    if any(word.endswith(('kan', 'nya')) for word in words):
        return 'idn'
    if any(word in {'the', 'and', 'building', 'reward'} for word in words):
        return 'en'
    return 'unknown'


def inspect_language_file(path: str | Path, lang_index: int = 0, sample_size: int = 100) -> dict:
    df, col_map = read_language_file(str(path))
    pairs = get_text_pairs(df, col_map, lang_index=lang_index)

    source_samples = [
        str(text) for text in pairs['original'].head(sample_size).tolist() if str(text).strip()
    ]
    target_samples = [
        str(text) for text in pairs['translation'].head(sample_size).tolist() if str(text).strip()
    ]

    return {
        'source_lang': detect_text_language(source_samples),
        'target_lang': detect_text_language(target_samples),
        'row_count': len(pairs),
    }
