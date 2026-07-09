"""Excel reading module for localization workflow.

Reads language tables and term tables from Excel files.
Supports single-language and multi-language column layouts.
"""
import re
from pathlib import Path
from typing import Optional

import pandas as pd


# Common column name patterns (Chinese / English)
_ID_PATTERNS = re.compile(r'^[Ii][Dd]$|^序号$|^编号$|ID$')
_ORIG_PATTERNS = re.compile(
    r'^(原文|中文定义|中文对照|中文原文|中文|source|original|cn|zh|chs|chinese)$',
    re.IGNORECASE,
)
_TRANS_PATTERNS = re.compile(
    r'^(译文|翻译|translation|target'
    r'|英语|英文|泰语|泰文|越南语|越南文|印尼语|法语|德语|土耳其语|西班牙语|葡萄牙语|俄语|日语|韩语'
    r'|English|Thai|Vietnamese|Indonesian|French|German|Turkish|Spanish|Portuguese|Russian|Japanese|Korean'
    r'|en|th|vi|id(?:\.\d+)?|idn|fr|de|tr|es|pt|ru|ja|jp|ko|kr)$',
    re.IGNORECASE,
)
_NOTE_PATTERNS = re.compile(r'^(备注|note|notes|comment)$', re.IGNORECASE)


def _detect_column_role(col_name: str) -> Optional[str]:
    """Detect column role from its name."""
    name = str(col_name).strip()
    if _ID_PATTERNS.search(name):
        return 'id'
    if _ORIG_PATTERNS.search(name):
        return 'original'
    if _TRANS_PATTERNS.search(name):
        return 'translation'
    if _NOTE_PATTERNS.search(name):
        return 'note'
    return None


def detect_columns(df: pd.DataFrame) -> dict:
    """Detect column mapping from DataFrame.

    Returns a dict like:
        {
            'id_col': 'ID',
            'original_col': '原文',
            'languages': [
                {'translation_col': '译文', 'note_col': '备注'},
                ...
            ]
        }
    """
    columns = list(df.columns)
    result = {'id_col': None, 'original_col': None, 'languages': []}

    # First pass: try name-based detection
    unmatched = []
    for col in columns:
        role = _detect_column_role(col)
        if role == 'id' and result['id_col'] is None:
            result['id_col'] = col
        elif role == 'original' and result['original_col'] is None:
            result['original_col'] = col
        else:
            unmatched.append((col, role))

    # Build language pairs from remaining columns.
    # Prefer explicit target-language headers. Metadata columns such as "Type"
    # must not become the first target column when a later "en"/"EN" column exists.
    current_lang = {}
    has_explicit_translation = any(role == 'translation' for _, role in unmatched)
    for col, role in unmatched:
        if role == 'translation':
            if current_lang.get('translation_col'):
                result['languages'].append(current_lang)
                current_lang = {}
            current_lang['translation_col'] = col
        elif role == 'note':
            if current_lang.get('translation_col'):
                current_lang['note_col'] = col
        else:
            if has_explicit_translation:
                # Unknown columns before an explicit language target are metadata.
                # Unknown columns after a target are the optional note/alt column.
                if current_lang.get('translation_col') and not current_lang.get('note_col'):
                    current_lang['note_col'] = col
                continue
            # Fallback for legacy sheets without explicit target headers.
            if not current_lang.get('translation_col'):
                current_lang['translation_col'] = col
            else:
                current_lang['note_col'] = col

    if current_lang.get('translation_col'):
        result['languages'].append(current_lang)

    # Fallback: positional detection (A=ID, B=original, C=translation, D=note, ...)
    if result['id_col'] is None and len(columns) >= 1:
        result['id_col'] = columns[0]
    if result['original_col'] is None and len(columns) >= 2:
        result['original_col'] = columns[1]
    if not result['languages'] and len(columns) >= 3:
        result['languages'] = []
        i = 2
        while i < len(columns):
            lang = {'translation_col': columns[i]}
            if i + 1 < len(columns):
                lang['note_col'] = columns[i + 1]
                i += 2
            else:
                i += 1
            result['languages'].append(lang)

    return result


def read_language_file(
    file_path: str,
    sheet_name: int | str = 0,
) -> tuple[pd.DataFrame, dict]:
    """Read a language Excel file.

    Returns:
        (df, column_map) where df is the raw DataFrame and column_map
        describes the detected column structure.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if path.suffix.lower() in ('.xlsx', '.xls'):
        df = pd.read_excel(file_path, sheet_name=sheet_name)
    elif path.suffix.lower() == '.csv':
        df = pd.read_csv(file_path)
    else:
        raise ValueError(f"Unsupported file format: {path.suffix}")

    # Ensure string types for text columns (skip ID)
    for col in df.columns[1:]:
        df[col] = df[col].astype(str).replace('nan', '')

    column_map = detect_columns(df)
    return df, column_map


def read_term_file(
    file_path: str,
    sheet_name: int | str = 0,
) -> tuple[pd.DataFrame, dict]:
    """Read a term table Excel file. Same structure as language file."""
    return read_language_file(file_path, sheet_name)


def get_text_pairs(
    df: pd.DataFrame,
    column_map: dict,
    lang_index: int = 0,
) -> pd.DataFrame:
    """Extract ID / original / translation triples for a specific language.

    Returns a DataFrame with columns: id, original, translation
    """
    id_col = column_map['id_col']
    orig_col = column_map['original_col']

    if lang_index >= len(column_map['languages']):
        raise IndexError(
            f"Language index {lang_index} out of range "
            f"(only {len(column_map['languages'])} languages found)"
        )

    lang_info = column_map['languages'][lang_index]
    trans_col = lang_info['translation_col']
    note_col = lang_info.get('note_col')

    result = pd.DataFrame({
        'id': df[id_col],
        'original': df[orig_col].astype(str),
        'translation': df[trans_col].astype(str),
    })

    if note_col and note_col in df.columns:
        result['note'] = df[note_col].astype(str).replace('nan', '')
    else:
        result['note'] = ''

    return result
