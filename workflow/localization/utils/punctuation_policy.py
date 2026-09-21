"""Deterministic width and client-punctuation checks; never strip language accents."""
from __future__ import annotations

import json
import re
import unicodedata

from utils.language_config import normalize_language_code


FULLWIDTH_PATTERN = re.compile(r'[\uff01-\uff60\uffe0-\uffe6\u3000，。！？：；（）【】、]')
ASCII_PUNCTUATION = {
    **dict.fromkeys('\u2018\u2019\u201a\u201b', "'"),
    **dict.fromkeys('\u201c\u201d\u201e\u201f', '"'),
    **dict.fromkeys('\u2010\u2011\u2012', '-'),
    '\u2013': ' - ', '\u2014': ' - ', '\u2015': ' - ', '\u2026': '...',
    '\u00a0': ' ', '\u202f': ' ',
}
CJK_PUNCTUATION = {'。': '.', '【': '[', '】': ']', '、': ','}
PROTECTED = re.compile(r'''</?[A-Za-z](?:[^<>'"]|"[^"]*"|'[^']*')*>|<@\d+>|\{[^{}]*\}|\[[^\[\]]*\]|%[sdif]|##\d+|\\n''')


def _ascii_mode(lang: str, mode: str | None) -> bool:
    if mode not in (None, 'ascii', 'typographic'):
        raise ValueError('punctuation mode must be ascii or typographic')
    return mode == 'ascii' if mode else normalize_language_code(lang) == 'en'


def punctuation_issues(text: str, lang: str = 'en', mode: str | None = None) -> dict[str, str]:
    ascii_mode = _ascii_mode(lang, mode)
    findings = {}
    if normalize_language_code(lang) not in {'ja', 'ko', 'zh', 'zh-cn', 'zh-tw'}:
        chars = sorted(set(FULLWIDTH_PATTERN.findall(str(text))))
        if chars:
            findings['fullwidth_punctuation'] = 'Fullwidth/CJK characters: ' + ', '.join(f'U+{ord(c):04X}' for c in chars)
    if ascii_mode:
        chars = sorted(set(str(text)) & ASCII_PUNCTUATION.keys())
        if chars:
            findings['incompatible_punctuation'] = 'Client requires ASCII punctuation: ' + ', '.join(f'U+{ord(c):04X}' for c in chars)
    return findings


def repair_punctuation(text: str, lang: str = 'en', mode: str | None = None) -> str:
    ascii_mode = _ascii_mode(lang, mode)
    if normalize_language_code(lang) in {'ja', 'ko', 'zh', 'zh-cn', 'zh-tw'}:
        return text
    try:
        if isinstance(json.loads(text), (dict, list)):
            # Structured payloads must be repaired through the existing text-slot path.
            return text
    except (ValueError, TypeError):
        pass

    def convert(chunk):
        result = []
        for char in chunk:
            if FULLWIDTH_PATTERN.fullmatch(char):
                result.append(CJK_PUNCTUATION.get(char, unicodedata.normalize('NFKC', char)))
            else:
                result.append(ASCII_PUNCTUATION.get(char, char) if ascii_mode else char)
        result = ''.join(result)
        result = re.sub(r' +(?=- )|(?<= -) +', ' ', result)
        return result

    return transform_unprotected(text, convert)


def transform_unprotected(text: str, transform) -> str:
    """Apply a text-only transform while preserving tags and runtime tokens byte-for-byte."""
    pieces, start = [], 0
    for match in PROTECTED.finditer(text):
        pieces.extend((transform(text[start:match.start()]), match.group()))
        start = match.end()
    pieces.append(transform(text[start:]))
    return ''.join(pieces)
