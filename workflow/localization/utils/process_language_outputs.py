"""Result and report workbook builders for the main processing script.

Implementation module split out of process_language.py. Import these symbols
through process_language to keep the public surface stable.
"""
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from utils.process_language_review import RowId, RowState, _coerce_row_id


# ─────────────────────────────────────────────────────────────
# Output builders
# ─────────────────────────────────────────────────────────────

def _build_result_full(
    df: pd.DataFrame,
    col_map: dict,
    states: dict[RowId, RowState],
    lang_index: int = 0,
) -> pd.DataFrame:
    """Sheet '完整结果': full data with fixes applied + notes column."""
    id_col = col_map['id_col']
    trans_col = col_map['languages'][lang_index]['translation_col']
    result = df.copy()

    note_col = '备注'
    if note_col not in result.columns:
        result[note_col] = ''

    normalized_ids = result[id_col].map(_coerce_row_id)
    for index, row in result.iterrows():
        rid = normalized_ids.loc[index]
        state = states.get(rid)
        if not state:
            continue
        if state.fixed_translation != state.translation:
            result.loc[normalized_ids == rid, trans_col] = state.fixed_translation
        if state.notes:
            result.loc[normalized_ids == rid, note_col] = '; '.join(state.notes)

    return result


def _build_result_review(
    states: dict[RowId, RowState],
    ai_reviewed_ids: set[RowId] | None = None,
    ai_corrected_ids: set[RowId] | None = None,
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
    states: dict[RowId, RowState],
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
    states: dict[RowId, RowState],
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
        'skill_name_word_count_watch': '技能名超过两词/字符软预算，需结合含义和重名风险压缩',
        'location_name_compactness_watch': '地名核心词或字符偏长，需结合自然语序压缩',
        'name_translation_collision_watch': '不同中文技能名或地名使用了同一目标语名称',
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


def write_outputs(
    df: pd.DataFrame,
    col_map: dict,
    states: dict[RowId, RowState],
    groups: list,
    input_path: str,
    lang: str = 'en',
    output_dir: str = './output',
    lang_index: int = 0,
    term_lookup: dict | None = None,
    term_only_view: bool = False,
    ai_reviewed_ids: set[RowId] | None = None,
    ai_corrected_ids: set[RowId] | None = None,
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
