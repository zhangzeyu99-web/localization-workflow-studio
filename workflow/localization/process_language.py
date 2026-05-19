"""Localization QA — main processing script.

Runs all checks on a language Excel file and produces:
  1. result_{lang}.xlsx   — Sheet "完整结果" + Sheet "需确认"
  2. report_{lang}.xlsx   — Sheet "总览" / "错误模式" / "学习笔记" / "详细记录"

Usage:
    python process_language.py --input language.xlsx --output-dir ./output/ --auto-fix
    python process_language.py --input language.xlsx --term-base terms.json --auto-fix
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from utils.excel_reader import read_language_file, get_text_pairs
from utils.language_detection import inspect_language_file
from utils.variable_checker import check_all as check_variables
from utils.term_checker import check_term_hit, check_chinese_residue, merge_builtin_name_terms
from utils.pattern_detector import detect_patterns
from utils.ui_detector import is_ui_text
from utils.ai_checker import prepare_all_batches, apply_corrections
from utils.text_normalize import repair_translation_surface
from utils.ui_length_checker import assess_ui_length, check_ui_length
from utils.readability_checker import check_readability


# ─────────────────────────────────────────────────────────────
# Row state tracker
# ─────────────────────────────────────────────────────────────

class RowState:
    __slots__ = (
        'row_id', 'original', 'translation', 'fixed_translation',
        'notes', 'is_ui', 'ui_confidence', 'issues',
        'needs_human_review', 'human_review_reason', 'ai_suggestion',
        'review_confidence',
        'short_text_length_policy', 'short_text_source_len',
        'short_text_target_len', 'short_text_budget',
    )

    def __init__(self, row_id: int, original: str, translation: str):
        self.row_id = row_id
        self.original = original
        self.translation = translation
        self.fixed_translation = translation
        self.notes: list[str] = []
        self.is_ui = False
        self.ui_confidence = 0.0
        self.issues: list = []
        self.needs_human_review = False
        self.human_review_reason = ''
        self.ai_suggestion = ''
        self.review_confidence = 1.0
        self.short_text_length_policy = ''
        self.short_text_source_len = 0
        self.short_text_target_len = 0
        self.short_text_budget = 0


# ─────────────────────────────────────────────────────────────
# Check phases
# ─────────────────────────────────────────────────────────────

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

        cn_col = _pick([r'中文术语', r'原文', r'中文', r'source', r'original'])
        lang_patterns = LANG_TERM_PATTERNS.get(lang, LANG_TERM_PATTERNS['en'])
        target_col = _pick(lang_patterns['primary']) or _pick([r'译文', r'翻译', r'translation', r'target'])
        alt_col = _pick(lang_patterns['variant']) or _pick([r'variant', r'variants', r'alternate'])
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


def _safe_apply_fix(state, new_translation: str, note: str):
    """Apply a fix only if it doesn't introduce Chinese residue or extra variables."""
    from utils.text_normalize import normalize_escapes, extract_vars
    from collections import Counter
    import re
    cn_pat = re.compile(r'[\u4e00-\u9fa5]')

    old_norm = normalize_escapes(state.fixed_translation)
    new_norm = normalize_escapes(new_translation)

    if cn_pat.search(new_norm) and not cn_pat.search(old_norm):
        return False

    orig_var_counts = Counter(extract_vars(state.original))
    new_var_counts = Counter(extract_vars(new_translation))
    if any(new_var_counts.get(v, 0) > orig_var_counts.get(v, 0) for v in new_var_counts):
        return False

    state.fixed_translation = new_translation
    state.notes.append(note)
    return True


def _run_variable_checks(states: dict[int, RowState], auto_fix: bool):
    for state in states.values():
        for r in check_variables(state.row_id, state.original, state.fixed_translation):
            state.issues.append(r)
            if auto_fix and r.auto_fix and r.severity == 'error':
                _safe_apply_fix(state, r.auto_fix, f"自动修复({r.check_type}): {r.message}")
            elif r.severity == 'error':
                state.needs_human_review = True
                state.human_review_reason = r.message
                state.ai_suggestion = r.auto_fix or state.fixed_translation
                state.review_confidence = r.confidence


def _run_surface_fixes(states: dict[int, RowState], auto_fix: bool, lang: str):
    for state in states.values():
        repaired = repair_translation_surface(state.original, state.fixed_translation, lang=lang)
        if repaired == state.fixed_translation:
            continue
        if auto_fix:
            _safe_apply_fix(state, repaired, "符号/占位符规范化")
        else:
            state.needs_human_review = True
            state.human_review_reason = "符号或占位符格式异常"
            state.ai_suggestion = repaired
            state.review_confidence = 0.95


def _run_term_checks(states: dict[int, RowState], term_lookup: dict, auto_fix: bool):
    if not term_lookup:
        return
    for state in states.values():
        for r in check_term_hit(state.row_id, state.original, state.fixed_translation, term_lookup):
            state.issues.append(r)
            if auto_fix and r.auto_fix and r.confidence >= 0.8:
                _safe_apply_fix(state, r.auto_fix, f"术语修复: {r.message}")
            elif r.severity == 'error':
                state.needs_human_review = True
                state.human_review_reason = r.message
                state.ai_suggestion = r.auto_fix or state.fixed_translation
                state.review_confidence = r.confidence


def _run_chinese_residue_checks(states: dict[int, RowState]):
    for state in states.values():
        for r in check_chinese_residue(state.row_id, state.fixed_translation):
            state.issues.append(r)
            state.needs_human_review = True
            state.human_review_reason = r.message
            state.ai_suggestion = state.fixed_translation
            state.review_confidence = 0.5


def _run_pattern_checks(states: dict[int, RowState], auto_fix: bool):
    rows = [
        {'id': s.row_id, 'original': s.original, 'translation': s.fixed_translation}
        for s in states.values()
    ]
    groups, issues = detect_patterns(rows, min_group_size=3)

    for issue in issues:
        state = states.get(issue.row_id)
        if not state:
            continue
        state.issues.append(issue)

        if auto_fix and issue.auto_fix and issue.confidence >= 0.7:
            _safe_apply_fix(state, issue.auto_fix, f"句式统一: {issue.best_pattern[:50]}")
        elif issue.confidence >= 0.6:
            state.needs_human_review = True
            state.human_review_reason = issue.message
            state.ai_suggestion = issue.auto_fix or state.fixed_translation
            state.review_confidence = issue.confidence
        else:
            state.needs_human_review = True
            state.human_review_reason = (
                f"句式存疑(置信度{issue.confidence:.0%}): {issue.message}"
            )
            state.ai_suggestion = issue.auto_fix or state.fixed_translation
            state.review_confidence = issue.confidence

    return groups


def _run_ui_detection(states: dict[int, RowState]):
    for state in states.values():
        is_ui_flag, conf, _ = is_ui_text(state.original, state.fixed_translation)
        state.is_ui = is_ui_flag
        state.ui_confidence = conf


def _run_ui_length_checks(states: dict[int, RowState], lang: str):
    for state in states.values():
        assessment = assess_ui_length(
            row_id=state.row_id,
            original=state.original,
            translation=state.fixed_translation,
            is_ui=state.is_ui,
            lang=lang,
        )
        if assessment:
            state.short_text_length_policy = assessment.policy
            state.short_text_source_len = assessment.source_length
            state.short_text_target_len = assessment.target_length
            state.short_text_budget = assessment.budget
        for issue in check_ui_length(
            row_id=state.row_id,
            original=state.original,
            translation=state.fixed_translation,
            is_ui=state.is_ui,
            lang=lang,
        ):
            state.issues.append(issue)
            state.needs_human_review = True
            state.human_review_reason = issue.message
            state.ai_suggestion = state.fixed_translation
            state.review_confidence = issue.confidence


def _run_readability_checks(states: dict[int, RowState], lang: str):
    for state in states.values():
        for issue in check_readability(
            row_id=state.row_id,
            original=state.original,
            translation=state.fixed_translation,
            lang=lang,
        ):
            state.issues.append(issue)
            state.needs_human_review = True
            state.human_review_reason = issue.message
            state.ai_suggestion = state.fixed_translation
            state.review_confidence = issue.confidence


def prepare_ai_review(
    states: dict[int, RowState],
    batch_size: int = 200,
    term_lookup: dict | None = None,
    lang: str = 'en',
    scope: str = 'all',
    include_term_priority: bool = False,
):
    """Prepare AI review batches from current states (after machine review).

    scope:
      - 'all': all rows
      - 'issues_only': only rows with any issue
      - 'term_hit': only rows whose original hits any term in term_lookup
    """
    _LOW_VALUE_ONLY = {'newline_mismatch'}
    _LOW_CONFIDENCE_THRESHOLD = 0.5

    def _is_low_value(s):
        """Skip rows that only have low-value issues AI can't fix well."""
        if not s.issues:
            return True
        issue_types = {getattr(i, 'check_type', '') for i in s.issues}
        if issue_types <= _LOW_VALUE_ONLY:
            return True
        if issue_types == {'pattern_inconsistency'}:
            max_conf = max((getattr(i, 'confidence', 1.0) for i in s.issues), default=1.0)
            if max_conf < _LOW_CONFIDENCE_THRESHOLD:
                return True
        return False

    if scope == 'issues_only':
        selected_states = [s for s in states.values() if s.issues and not _is_low_value(s)]
    elif scope == 'term_hit':
        if term_lookup:
            selected_states = [
                s for s in states.values()
                if any(cn in str(s.original) for cn in term_lookup if len(cn) >= 2)
            ]
        else:
            selected_states = list(states.values())
    else:
        selected_states = list(states.values())

    rows = []
    for s in selected_states:
        item = {
            'id': s.row_id,
            'original': s.original,
            'translation': s.fixed_translation,
        }
        if include_term_priority:
            item['is_ui'] = s.is_ui
            item['term_status'] = (
                'TERM_ERROR' if any(
                    getattr(i, 'check_type', '') in {'term_missing', 'term_partial_hit', 'term_capitalization', 'romanized_name_residue'}
                    for i in s.issues
                ) else 'TERM_OK'
            )
            item['term_issue_types'] = '; '.join(sorted(set(
                getattr(i, 'check_type', '')
                for i in s.issues
                if getattr(i, 'check_type', '') in {'term_missing', 'term_partial_hit', 'term_capitalization', 'romanized_name_residue'}
            )))
        if s.short_text_length_policy and s.short_text_length_policy != 'exempt':
            item['ui_length_policy'] = s.short_text_length_policy
            item['ui_length_source_len'] = int(s.short_text_source_len)
            item['ui_length_target_len'] = int(s.short_text_target_len)
            item['ui_length_budget'] = int(s.short_text_budget)
        rows.append(item)
    return prepare_all_batches(rows, batch_size=batch_size, term_lookup=term_lookup, lang=lang)


# ─────────────────────────────────────────────────────────────
# Output builders
# ─────────────────────────────────────────────────────────────

def _build_result_full(
    df: pd.DataFrame,
    col_map: dict,
    states: dict[int, RowState],
    lang_index: int = 0,
) -> pd.DataFrame:
    """Sheet '完整结果': full data with fixes applied + notes column."""
    id_col = col_map['id_col']
    trans_col = col_map['languages'][lang_index]['translation_col']
    result = df.copy()

    note_col = '备注'
    if note_col not in result.columns:
        result[note_col] = ''

    for _, row in result.iterrows():
        rid = row[id_col]
        state = states.get(rid)
        if not state:
            continue
        if state.fixed_translation != state.translation:
            result.loc[result[id_col] == rid, trans_col] = state.fixed_translation
        if state.notes:
            result.loc[result[id_col] == rid, note_col] = '; '.join(state.notes)

    return result


def _build_result_review(
    states: dict[int, RowState],
    ai_reviewed_ids: set[int] | None = None,
    ai_corrected_ids: set[int] | None = None,
) -> pd.DataFrame:
    """Sheet '需确认': subset of rows needing human review."""
    reviewed = ai_reviewed_ids or set()
    corrected = ai_corrected_ids or set()
    rows = []
    for state in states.values():
        if not state.needs_human_review:
            continue

        term_error_types = {'term_missing', 'term_partial_hit', 'term_capitalization', 'romanized_name_residue'}
        has_term_issue = any(
            getattr(i, 'check_type', '') in term_error_types for i in state.issues
        )

        if state.row_id in corrected:
            ai_status = 'AI已修正'
        elif state.row_id in reviewed:
            if has_term_issue:
                ai_status = 'AI未修正(术语有误)'
            else:
                ai_status = 'AI确认无误'
        else:
            ai_status = 'AI未审查'

        rows.append({
            'ID': state.row_id,
            '原文': state.original,
            '当前译文': state.fixed_translation,
            'AI建议': state.ai_suggestion or state.fixed_translation,
            '原因': state.human_review_reason,
            '置信度': f"{state.review_confidence:.0%}",
            '是否UI': '是' if state.is_ui else '否',
            'AI处理状态': ai_status,
        })
    if not rows:
        return pd.DataFrame(columns=['ID', '原文', '当前译文', 'AI建议', '原因', '置信度', '是否UI', 'AI处理状态'])
    return pd.DataFrame(rows)


def _build_term_only_view(
    states: dict[int, RowState],
    term_lookup: dict[str, dict] | None,
) -> pd.DataFrame:
    """Sheet '术语行筛选': rows whose source contains term-base CN entries."""
    cols = [
        'ID', '原文', '当前译文', '命中术语中文', '标准译法', '术语命中数',
        '术语判定', '术语问题类型', '是否已机审改写'
    ]
    if not term_lookup:
        return pd.DataFrame(columns=cols)

    term_error_types = {'term_missing', 'term_partial_hit', 'term_capitalization', 'romanized_name_residue'}

    # Prebuild term candidates (skip too-short CN terms to reduce noisy hits)
    term_items: list[tuple[str, str]] = []
    for cn_term, term_item in term_lookup.items():
        cn = str(cn_term).strip()
        if len(cn) < 2:
            continue
        primary = str(term_item.get('primary', '')) if isinstance(term_item, dict) else str(term_item)
        variants = term_item.get('variants', []) if isinstance(term_item, dict) else []
        all_tgt = [primary] + [str(v) for v in variants if str(v).strip()]
        tgt_text = ' / '.join([x for x in all_tgt if x])
        term_items.append((cn, tgt_text))

    # Long terms first so short generic terms don't flood results
    term_items.sort(key=lambda x: len(x[0]), reverse=True)

    rows = []
    for state in states.values():
        hits: list[tuple[str, str]] = []
        src = str(state.original)
        for cn_term, tgt_text in term_items:
            if cn_term and cn_term in src:
                # If this shorter term is fully covered by an already selected longer term, skip it.
                if any(cn_term in sel_cn for sel_cn, _ in hits):
                    continue
                hits.append((cn_term, tgt_text))
                if len(hits) >= 8:
                    break
        if not hits:
            continue

        uniq = []
        seen = set()
        for cn, tgt in hits:
            key = (cn, tgt)
            if key in seen:
                continue
            seen.add(key)
            uniq.append((cn, tgt))

        hit_issue_types = []
        for issue in state.issues:
            ctype = getattr(issue, 'check_type', '')
            if ctype in term_error_types:
                hit_issue_types.append(ctype)

        if hit_issue_types:
            term_status = '术语有误'
            issue_text = '; '.join(sorted(set(hit_issue_types)))
        else:
            term_status = '命中术语无误'
            issue_text = ''

        rows.append({
            'ID': state.row_id,
            '原文': state.original,
            '当前译文': state.fixed_translation,
            '命中术语中文': '; '.join(cn for cn, _ in uniq),
            '标准译法': '; '.join(tgt for _, tgt in uniq),
            '术语命中数': len(uniq),
            '术语判定': term_status,
            '术语问题类型': issue_text,
            '是否已机审改写': '是' if state.fixed_translation != state.translation else '否',
        })

    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows)


def _build_report_sheets(
    states: dict[int, RowState],
    groups: list,
    input_file: str,
    lang: str,
) -> dict[str, pd.DataFrame]:
    """Build the 4 report sheets as DataFrames."""
    total = len(states)
    auto_fixed = sum(1 for s in states.values() if s.fixed_translation != s.translation)
    human_review = sum(1 for s in states.values() if s.needs_human_review)
    no_change = max(0, total - auto_fixed - human_review)
    ui_count = sum(1 for s in states.values() if s.is_ui)

    # Sheet 1: 总览
    summary_df = pd.DataFrame([
        {'指标': '总行数', '数值': total},
        {'指标': '自动修复', '数值': auto_fixed},
        {'指标': '需人工确认', '数值': human_review},
        {'指标': '无需改动', '数值': no_change},
        {'指标': 'UI文本数', '数值': ui_count},
        {'指标': '句式组数', '数值': len(groups)},
        {'指标': '来源文件', '数值': Path(input_file).name},
        {'指标': '语言', '数值': lang},
        {'指标': '处理时间', '数值': datetime.now().strftime('%Y-%m-%d %H:%M:%S')},
    ])

    # Sheet 2: 错误模式
    pattern_counter: Counter = Counter()
    pattern_examples: dict[str, list] = defaultdict(list)
    for state in states.values():
        for issue in state.issues:
            ctype = getattr(issue, 'check_type', 'unknown')
            pattern_counter[ctype] += 1
            if len(pattern_examples[ctype]) < 5:
                pattern_examples[ctype].append(state.row_id)

    _DESC = {
        'variable_missing': '原文变量在译文中缺失',
        'variable_extra': '译文中出现原文没有的变量',
        'variable_order': '变量出现顺序与原文不同',
        'bbcode_open_mismatch': 'BBCode开标签数量不匹配',
        'bbcode_close_mismatch': 'BBCode闭标签数量不匹配',
        'bbcode_unclosed': '译文BBCode标签未闭合',
        'bbcode_color_mismatch': '颜色代码值与原文不一致',
        'newline_mismatch': '换行符数量不匹配',
        'term_missing': '标准术语未在译文中出现',
        'term_partial_hit': '多词术语仅部分匹配',
        'term_capitalization': '术语大小写问题',
        'romanized_name_residue': '译文中残留拼音或音译专名',
        'ui_length_overflow': 'UI短文案长度超出预算',
        'short_text_length_watch': '短文本长度偏长（软提示）',
        'opaque_abbreviation': '译文包含不可读缩写或内部代码式文案',
        'clipped_word': '译文包含截断词或过度压缩缩写',
        'title_case_overuse': '错误/状态/提示类文案过度使用 Title Case',
        'chinese_residue': '译文中残留中文字符',
        'pattern_inconsistency': '译文句式与组内标准不一致',
    }
    error_rows = []
    for ctype, count in pattern_counter.most_common():
        error_rows.append({
            '错误类型': ctype,
            '数量': count,
            '示例ID': ', '.join(str(i) for i in pattern_examples[ctype]),
            '描述': _DESC.get(ctype, ctype),
        })
    errors_df = pd.DataFrame(error_rows) if error_rows else pd.DataFrame(
        columns=['错误类型', '数量', '示例ID', '描述']
    )

    # Sheet 3: 学习笔记
    notes = []
    if pattern_counter.get('pattern_inconsistency', 0) > 0:
        notes.append(f"发现 {pattern_counter['pattern_inconsistency']} 处句式不一致，涉及 {len(groups)} 个模板组")
    if pattern_counter.get('variable_missing', 0) > 0:
        notes.append(f"{pattern_counter['variable_missing']} 行存在变量缺失")
    if pattern_counter.get('chinese_residue', 0) > 0:
        notes.append(f"{pattern_counter['chinese_residue']} 行译文残留中文字符")
    if ui_count > 0:
        notes.append(f"{ui_count} 条文本被识别为UI元素（占比 {ui_count/total:.1%}）")
    notes_df = pd.DataFrame({'学习笔记': notes}) if notes else pd.DataFrame(columns=['学习笔记'])

    # Sheet 4: 详细记录
    detail_rows = []
    for state in states.values():
        if state.fixed_translation != state.translation or state.needs_human_review:
            detail_rows.append({
                'ID': state.row_id,
                '原文': state.original,
                '修改前': state.translation,
                '修改后': state.fixed_translation,
                '原因': '; '.join(state.notes) if state.notes else '需人工确认',
                '是否UI': '是' if state.is_ui else '否',
            })
    details_df = pd.DataFrame(detail_rows) if detail_rows else pd.DataFrame(
        columns=['ID', '原文', '修改前', '修改后', '原因', '是否UI']
    )

    return {
        '总览': summary_df,
        '错误模式': errors_df,
        '学习笔记': notes_df,
        '详细记录': details_df,
    }


# ─────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────

def run_machine_review(
    input_path: str,
    term_base_path: str | None = None,
    auto_fix: bool = True,
    lang_index: int = 0,
    lang: str = 'en',
) -> tuple:
    """Phase 1: Run all rule-based checks.

    Returns (df, col_map, states, groups) for further processing.
    """
    print(f"[1/9] 读取输入: {input_path}")
    df, col_map = read_language_file(input_path)
    pairs = get_text_pairs(df, col_map, lang_index=lang_index)
    print(f"       {len(pairs)} 行已加载")
    profile = inspect_language_file(input_path, lang_index=lang_index)
    print(f"       检测语言: source={profile['source_lang']} target={profile['target_lang']}")
    if profile['target_lang'] not in ('unknown', lang):
        print(f"       [预警] 目标语言检测为 {profile['target_lang']}，与请求的 {lang} 不一致")
    if profile['source_lang'] != 'zh':
        print(f"       [预警] 源语言检测为 {profile['source_lang']}，术语和句式检查可能降级")

    states: dict[int, RowState] = {}
    skipped = 0
    for _, row in pairs.iterrows():
        raw_id = row['id']
        if pd.isna(raw_id):
            skipped += 1
            continue
        try:
            rid = int(raw_id)
        except (ValueError, TypeError):
            skipped += 1
            continue
        states[rid] = RowState(rid, str(row['original']), str(row['translation']))
    if skipped:
        print(f"       (跳过 {skipped} 行无效ID)")

    print(f"[2/9] 加载术语库")
    term_lookup = _load_term_base(term_base_path, lang=lang)
    print(f"       {len(term_lookup)} 条术语" if term_lookup else "       (无术语库)")

    print(f"[3/9] 变量 & 标签检查")
    _run_surface_fixes(states, auto_fix, lang)
    _run_variable_checks(states, auto_fix)

    print(f"[4/9] 术语检查")
    _run_term_checks(states, term_lookup, auto_fix)

    print(f"[5/9] 句式一致性检查")
    groups = _run_pattern_checks(states, auto_fix)

    print(f"[6/9] 中文残留检查")
    _run_chinese_residue_checks(states)

    print(f"[7/9] UI文本识别")
    _run_ui_detection(states)

    print(f"[8/9] UI长度预算检查")
    _run_ui_length_checks(states, lang)

    print("[9/9] 可读缩写/截断词检查")
    _run_readability_checks(states, lang)

    total_issues = sum(len(s.issues) for s in states.values())
    print(f"\n       机审发现 {total_issues} 个问题")

    return df, col_map, states, groups


def write_outputs(
    df: pd.DataFrame,
    col_map: dict,
    states: dict[int, RowState],
    groups: list,
    input_path: str,
    lang: str = 'en',
    output_dir: str = './output',
    lang_index: int = 0,
    term_lookup: dict | None = None,
    term_only_view: bool = False,
    ai_reviewed_ids: set[int] | None = None,
    ai_corrected_ids: set[int] | None = None,
) -> dict:
    """Phase 3: Write final output files after all reviews are done.

    Writes to output root (latest, always overwritten) AND to an archive
    subfolder named {lang}_{timestamp} for history.

    Returns a summary dict.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Clean old result/report files from root before writing new ones
    for old_file in out.glob('result_*.xlsx'):
        old_file.unlink()
    for old_file in out.glob('report_*.xlsx'):
        old_file.unlink()

    # Archive subfolder: output/{source}_{lang}_{timestamp}/
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    source_name = Path(input_path).stem
    archive_dir = out / f"{source_name}_{lang}_{timestamp}"
    archive_dir.mkdir(parents=True, exist_ok=True)

    full_df = _build_result_full(df, col_map, states, lang_index)
    review_df = _build_result_review(states, ai_reviewed_ids, ai_corrected_ids)
    term_only_df = _build_term_only_view(states, term_lookup) if term_only_view else None
    report_sheets = _build_report_sheets(states, groups, input_path, lang)

    # Write to both locations
    for target_dir, label in [(out, "最新"), (archive_dir, "归档")]:
        result_path = target_dir / f"result_{lang}.xlsx"
        with pd.ExcelWriter(result_path, engine='openpyxl') as writer:
            full_df.to_excel(writer, sheet_name='完整结果', index=False)
            review_df.to_excel(writer, sheet_name='需确认', index=False)
            if term_only_df is not None:
                term_only_df.to_excel(writer, sheet_name='术语行筛选', index=False)

        report_path = target_dir / f"report_{lang}.xlsx"
        with pd.ExcelWriter(report_path, engine='openpyxl') as writer:
            for sheet_name, sheet_df in report_sheets.items():
                sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)

    result_path = out / f"result_{lang}.xlsx"
    report_path = out / f"report_{lang}.xlsx"

    print(f"\n  -> {result_path}  (完整结果 + 需确认 {len(review_df)} 条)")
    if term_only_df is not None:
        print(f"  -> 术语行筛选: {len(term_only_df)} 条")
    print(f"  -> {report_path}  (4 sheets)")
    print(f"  -> {archive_dir}/  (归档)")

    summary = {
        'total_processed': len(states),
        'auto_fixed': sum(1 for s in states.values() if s.fixed_translation != s.translation),
        'need_human_review': sum(1 for s in states.values() if s.needs_human_review),
        'no_change': max(0, len(states) - sum(1 for s in states.values() if s.fixed_translation != s.translation) - sum(1 for s in states.values() if s.needs_human_review)),
        'ui_texts': sum(1 for s in states.values() if s.is_ui),
        'total_issues': sum(len(s.issues) for s in states.values()),
        'result_path': str(result_path),
        'report_path': str(report_path),
        'archive_dir': str(archive_dir),
    }

    print(f"\n{'='*50}")
    print(f"  总行数:       {summary['total_processed']}")
    print(f"  自动修复:     {summary['auto_fixed']}")
    print(f"  需人工确认:   {summary['need_human_review']}")
    print(f"  无需改动:     {summary['no_change']}")
    print(f"  UI文本:       {summary['ui_texts']}")
    print(f"{'='*50}")

    return summary


def process(
    input_path: str,
    term_base_path: str | None = None,
    lang: str = 'en',
    output_dir: str = './output',
    auto_fix: bool = True,
    lang_index: int = 0,
) -> dict:
    """Run the full pipeline (machine review only, no AI).

    For AI-assisted review, use run_machine_review() + write_outputs()
    separately, with AI review in between.
    """
    df, col_map, states, groups = run_machine_review(
        input_path, term_base_path, auto_fix, lang_index, lang,
    )
    return write_outputs(
        df, col_map, states, groups, input_path, lang, output_dir, lang_index,
    )


def main():
    parser = argparse.ArgumentParser(description='游戏本地化质检工具')
    parser.add_argument('--input', required=True, help='语言表 Excel 文件')
    parser.add_argument('--term-base', default=None, help='术语库 JSON 文件（可选）')
    parser.add_argument('--lang', default='en', help='目标语言代码（默认 en）')
    parser.add_argument('--output-dir', default='./output', help='输出目录')
    parser.add_argument('--auto-fix', action='store_true', help='自动修复可修复项')
    parser.add_argument('--lang-index', type=int, default=0, help='多语言文件列索引')

    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"错误: 文件不存在: {args.input}", file=sys.stderr)
        sys.exit(1)

    process(
        input_path=args.input,
        term_base_path=args.term_base,
        lang=args.lang,
        output_dir=args.output_dir,
        auto_fix=args.auto_fix,
        lang_index=args.lang_index,
    )


if __name__ == '__main__':
    main()
