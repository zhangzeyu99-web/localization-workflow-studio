"""Localization QA — main processing script.

Boundary: PRODUCT RUNTIME DEPENDENCY. The FastAPI backend invokes this file as
a subprocess (see backend/app/workflow/qa.py). Keep the CLI contract stable and
validate changes with `python -m pytest backend/tests -q` in addition to the
local workflow tests.

Runs all checks on a language Excel file and produces:
  1. result_{lang}.xlsx   — Sheet "完整结果" + Sheet "需确认"
  2. report_{lang}.xlsx   — Sheet "总览" / "错误模式" / "学习笔记" / "详细记录"

Usage:
    python process_language.py --input language.xlsx --output-dir ./output/ --auto-fix
    python process_language.py --input language.xlsx --term-base terms.json --auto-fix

Implementation detail: row-state tracking and machine-review check phases live
in utils/process_language_review.py, term-base loading lives in
utils/process_language_terms.py, and result/report workbook builders live in
utils/process_language_outputs.py. This module re-exports those symbols so
existing `from process_language import ...` imports keep working, and keeps
the CLI entry point plus the top-level pipeline orchestration.
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

from utils.excel_reader import read_language_file, get_text_pairs
from utils.language_detection import inspect_language_file
from utils.quality_harness import scan_workbook
from utils.process_language_terms import (  # noqa: F401  (re-exported)
    LANG_TERM_PATTERNS,
    _load_term_base,
    _normalize_term_lookup,
)
from utils.process_language_review import (  # noqa: F401  (re-exported)
    RowId,
    RowState,
    _coerce_row_id,
    _run_chinese_residue_checks,
    _run_pattern_checks,
    _run_readability_checks,
    _run_surface_fixes,
    _run_term_checks,
    _run_ui_detection,
    _run_ui_length_checks,
    _run_variable_checks,
    _safe_apply_fix,
    prepare_ai_review,
    rerun_quality_review,
)
from utils.process_language_outputs import (  # noqa: F401  (re-exported)
    _build_report_sheets,
    _build_result_full,
    _build_result_review,
    _build_term_only_view,
    write_outputs,
)


FINAL_BLOCKING_CHECK_TYPES = {
    'variable_missing',
    'variable_extra',
    'variable_order',
    'bbcode_open_mismatch',
    'bbcode_close_mismatch',
    'bbcode_unclosed',
    'bbcode_color_mismatch',
    'newline_mismatch',
    'chinese_residue',
    'html_entity_leak',
    'internal_token_leak',
    'punctuation_corruption',
    'orphan_leading_clitic',
    'leading_lowercase',
    'ui_length_overflow',
    'opaque_abbreviation',
    'clipped_word',
    'hash_code_abbreviation',
    'placeholder_compaction',
    'placeholder_word_glue',
    'fullwidth_punctuation',
    'workbook_scan_empty',
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

    states: dict[RowId, RowState] = {}
    skipped = 0
    for _, row in pairs.iterrows():
        rid = _coerce_row_id(row['id'])
        if rid is None:
            skipped += 1
            continue
        states[rid] = RowState(rid, str(row['original']), str(row['translation']))
    if skipped:
        print(f"       (跳过 {skipped} 行缺少有效 ID)")

    print("[2/9] 加载术语库")
    term_lookup = _load_term_base(term_base_path, lang=lang)
    print(f"       {len(term_lookup)} 条术语" if term_lookup else "       (无术语库)")

    print("[3/9] 变量 & 标签检查")
    _run_surface_fixes(states, auto_fix, lang)
    _run_variable_checks(states, auto_fix)

    print("[4/9] 术语检查")
    _run_term_checks(states, term_lookup, auto_fix, lang)

    print("[5/9] 句式一致性检查")
    groups = _run_pattern_checks(states, auto_fix)

    print("[6/9] 中文残留检查")
    _run_chinese_residue_checks(states, lang)

    print("[7/9] UI文本识别")
    _run_ui_detection(states)

    print("[8/9] UI长度预算检查")
    _run_ui_length_checks(states, lang)

    print("[9/9] 可读缩写/截断词检查")
    _run_readability_checks(states, lang)

    total_issues = sum(len(s.issues) for s in states.values())
    print(f"\n       机审发现 {total_issues} 个问题")

    return df, col_map, states, groups


def ensure_final_delivery_ready(
    states: dict[RowId, RowState],
    *,
    result_path: str | None = None,
    term_base_path: str | None = None,
    lang: str = 'en',
) -> None:
    """Block delivery when final structural/readability gates still have issues."""

    blockers: dict[str, list[str]] = defaultdict(list)
    for state in states.values():
        for issue in state.issues:
            check_type = getattr(issue, 'check_type', '')
            if check_type in FINAL_BLOCKING_CHECK_TYPES and len(blockers[check_type]) < 5:
                blockers[check_type].append(str(state.row_id))

    if result_path:
        harness_result = scan_workbook(
            result_path,
            lang=lang,
            fail_on=FINAL_BLOCKING_CHECK_TYPES,
            term_base=term_base_path,
        )
        for issue in harness_result.issues:
            check_type = str(issue.get('check_type', ''))
            if check_type in FINAL_BLOCKING_CHECK_TYPES and len(blockers[check_type]) < 5:
                blockers[check_type].append(str(issue.get('id', '')))

    if not blockers:
        return

    parts = []
    for check_type in sorted(blockers):
        examples = ','.join(blockers[check_type])
        parts.append(f"{check_type} (example IDs: {examples})")
    raise ValueError("Final delivery blocked by hard gate issues: " + "; ".join(parts))


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
