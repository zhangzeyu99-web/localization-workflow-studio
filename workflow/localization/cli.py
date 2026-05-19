"""Game Localization QA Workflow — CLI version.

Interactive command-line interface with the same two-phase workflow as the GUI:
  Phase 1: Machine review (automatic)
  Phase 2: AI review (clipboard-guided, batch by batch)

Agent (non-interactive) mode:
  python cli.py --input lang.xlsx --auto-fix --agent prepare   # machine review + write prompt files
  python cli.py --input lang.xlsx --auto-fix --agent merge     # read response files + output final

Normal (interactive) mode:
  python cli.py --input language.xlsx --auto-fix
  python cli.py --input language.xlsx --term-base terms.xlsx --batch-size 500
  python cli.py --input language.xlsx --auto-fix --skip-ai
"""
import argparse
import os
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from process_language import (
    run_machine_review, write_outputs, prepare_ai_review, _load_term_base,
)
from utils.ai_checker import (
    apply_corrections,
    merge_review_batches,
    parse_ai_response,
    prepare_recheck_batches,
    write_response_templates,
    write_review_files,
)

CHATGPT_URL = "https://chatgpt.com/"


# ─── Clipboard helpers (using tkinter, no extra deps) ─────

def _clipboard_copy(text: str):
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()
        return True
    except Exception:
        return False


def _clipboard_get() -> str:
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        text = r.clipboard_get()
        r.destroy()
        return text
    except Exception:
        return ''


# ─── Pretty print helpers ─────────────────────────────────

def _hr(char='─', width=60):
    print(char * width)


def _header(text):
    _hr('═')
    print(f"  {text}")
    _hr('═')


def _section(text):
    print(f"\n{'─'*4} {text} {'─' * (54 - len(text))}")


# ─── Phase 1: Machine Review ──────────────────────────────

def phase1(args):
    _header("第一步 · 机审质检")
    print()

    df, col_map, states, groups = run_machine_review(
        args.input,
        args.term_base,
        args.auto_fix,
        args.lang_index,
        args.lang,
    )

    total = len(states)
    fixed = sum(1 for s in states.values() if s.fixed_translation != s.translation)
    issues = sum(len(s.issues) for s in states.values())

    print(f"\n  机审完成: {total} 行, 发现 {issues} 个问题, 自动修复 {fixed} 处")

    return df, col_map, states, groups


# ─── Phase 2: AI Review ───────────────────────────────────

def phase2(states, term_lookup, batch_size, lang='en'):
    _header("第二步 · AI审查")

    batches = prepare_ai_review(states, batch_size=batch_size, term_lookup=term_lookup, lang=lang)
    total_batches = len(batches)
    total_corrections = 0

    print(f"\n  共 {total_batches} 个批次, 每批约 {batch_size} 行")
    print(f"  操作: 复制提示词 → 粘贴到 ChatGPT → 复制回复 → 粘贴结果\n")

    current = 0
    while current < total_batches:
        batch = batches[current]
        _section(f"第 {current + 1}/{total_batches} 批  (ID {batch.row_ids[0]}~{batch.row_ids[-1]}, {len(batch.row_ids)} 行)")

        while True:
            print()
            print("  [C] 复制提示词到剪贴板")
            print("  [O] 打开 ChatGPT")
            print("  [P] 粘贴AI结果（从剪贴板读取）")
            print("  [V] 手动输入AI结果（逐行粘贴）")
            print("  [B] 返回上一批")
            print("  [S] 跳过此批")
            print("  [F] 完成AI审查（跳过剩余所有批次）")
            print()

            choice = input("  请选择 > ").strip().upper()

            if choice == 'C':
                if _clipboard_copy(batch.prompt_text):
                    print(f"  ✓ 已复制到剪贴板 ({len(batch.prompt_text)} 字符)")
                else:
                    # Fallback: save to file
                    fp = Path('ai_review') / f'batch_{current + 1}.txt'
                    fp.parent.mkdir(exist_ok=True)
                    fp.write_text(batch.prompt_text, encoding='utf-8')
                    print(f"  ⚠ 剪贴板不可用，已保存到 {fp}")

            elif choice == 'O':
                webbrowser.open(CHATGPT_URL)
                print("  ✓ 已打开浏览器")

            elif choice == 'P':
                response = _clipboard_get()
                if not response:
                    print("  ✗ 剪贴板为空，请先复制AI的回复")
                    continue

                batch.response_text = response
                batch.corrections = parse_ai_response(response)
                batch.is_done = True
                modified = apply_corrections(batch.corrections, states)
                total_corrections += modified

                print(f"  ✓ 解析到 {len(batch.corrections)} 条修正, 应用 {modified} 处")
                current += 1
                break

            elif choice == 'V':
                print("  请粘贴AI回复（输入空行结束）:")
                lines = []
                while True:
                    try:
                        line = input()
                    except EOFError:
                        break
                    if line.strip() == '':
                        break
                    lines.append(line)

                if not lines:
                    print("  ✗ 无内容")
                    continue

                response = '\n'.join(lines)
                batch.response_text = response
                batch.corrections = parse_ai_response(response)
                batch.is_done = True
                modified = apply_corrections(batch.corrections, states)
                total_corrections += modified

                print(f"  ✓ 解析到 {len(batch.corrections)} 条修正, 应用 {modified} 处")
                current += 1
                break

            elif choice == 'B':
                if current > 0:
                    prev = batches[current - 1]
                    if prev.is_done and prev.corrections:
                        for c in prev.corrections:
                            state = states.get(c.row_id)
                            if state and 'AI审校修正' in state.notes:
                                state.fixed_translation = state.translation
                                state.notes = [n for n in state.notes if n != 'AI审校修正']
                                total_corrections = max(0, total_corrections - 1)
                        prev.corrections.clear()
                        prev.response_text = ''
                        prev.is_done = False
                    current -= 1
                    print(f"  ← 已返回第 {current + 1} 批")
                    break
                else:
                    print("  已经是第一批了")

            elif choice == 'S':
                print(f"  → 跳过第 {current + 1} 批")
                current += 1
                break

            elif choice == 'F':
                undone = sum(1 for b in batches[current:] if not b.is_done)
                if undone > 0:
                    confirm = input(f"  还有 {undone} 批未审查，确定跳过？[y/N] > ").strip().lower()
                    if confirm != 'y':
                        continue
                current = total_batches
                break

            else:
                print("  无效选项，请重新选择")

    print(f"\n  AI审查完成, 共修正 {total_corrections} 处")
    return total_corrections


# ─── Main ─────────────────────────────────────────────────

def _collect_recheck_rows(states, batches):
    term_error_types = {'term_missing', 'term_partial_hit', 'term_capitalization'}
    recheck_rows = []
    ai_batch_ids = set()
    for batch in batches:
        ai_batch_ids.update(batch.row_ids)

    for state in states.values():
        if state.row_id not in ai_batch_ids:
            continue
        has_term_issue = any(getattr(issue, 'check_type', '') in term_error_types for issue in state.issues)
        if not has_term_issue:
            continue
        issue_desc = '; '.join(sorted(set(
            getattr(issue, 'check_type', '')
            for issue in state.issues
            if getattr(issue, 'check_type', '') in term_error_types
        )))
        recheck_rows.append(
            {
                'id': state.row_id,
                'original': state.original,
                'translation': state.fixed_translation,
                'term_issue': issue_desc,
            }
        )
    return recheck_rows


def _reset_review_dir(review_dir: Path):
    review_dir.mkdir(parents=True, exist_ok=True)
    for pattern in (
        'batch_*.txt',
        'batch_*.json',
        'batch_*_response.txt',
        'batch_recheck_*.txt',
        'batch_recheck_*.json',
        'batch_recheck_*_response.txt',
        'review_run_manifest.json',
        'review_recheck_manifest.json',
    ):
        for path in review_dir.glob(pattern):
            path.unlink()


def agent_prepare(args):
    """Non-interactive: machine review + write AI prompt files to disk."""
    _header("Agent 模式: prepare")

    df, col_map, states, groups = phase1(args)

    term_lookup = _load_term_base(args.term_base, lang=args.lang)
    batches = prepare_ai_review(
        states,
        batch_size=args.batch_size,
        term_lookup=term_lookup,
        lang=args.lang,
        scope=args.ai_scope,
        include_term_priority=True,
    )

    review_dir = Path(args.output_dir) / 'ai_review'
    _reset_review_dir(review_dir)
    write_review_files(
        review_dir=review_dir,
        batches=batches,
        states=states,
        batch_type='main',
        lang=args.lang,
        input_path=args.input,
        ai_scope=args.ai_scope,
    )
    seeded_main = write_response_templates(review_dir, batch_type='main', overwrite=False)

    _header("生成机审输出")
    summary = write_outputs(
        df, col_map, states, groups,
        args.input, args.lang, args.output_dir, args.lang_index,
        term_lookup=term_lookup,
        term_only_view=args.term_only_view,
    )

    recheck_rows = _collect_recheck_rows(states, batches)
    if recheck_rows:
        recheck_batches = prepare_recheck_batches(
            recheck_rows, batch_size=args.batch_size,
            term_lookup=term_lookup, lang=args.lang,
        )
        write_review_files(
            review_dir=review_dir,
            batches=recheck_batches,
            states=states,
            batch_type='recheck',
            lang=args.lang,
            input_path=args.input,
            ai_scope='recheck_term_issues',
        )
        seeded_recheck = write_response_templates(review_dir, batch_type='recheck', overwrite=False)
        print(f"  术语漏网行:   {len(recheck_rows)} 行 → {len(recheck_batches)} 个二次审查提示词")
    else:
        seeded_recheck = 0

    _section("prepare 完成")
    print(f"  机审结果:     {summary['result_path']}")
    print(f"  质检报告:     {summary['report_path']}")
    scope_text = {"all": "全量", "issues_only": "仅机审问题行", "term_hit": "仅术语命中行"}.get(args.ai_scope, "全量")
    print(f"  AI审查范围:   {scope_text}")
    print(f"  AI提示词:     {review_dir}/ ({len(batches)} 个文件)")
    print(f"  响应模板:     主批次 {seeded_main} 个, 二次批次 {seeded_recheck} 个")
    if recheck_rows:
        print(f"  二次审查提示词: {len(recheck_rows)} 行术语漏网")
    print()
    print(f"  下一步: 读取 batch_N.txt → 发给 LLM → 保存回复为 batch_N_response.txt")
    if recheck_rows:
        print(f"  二次审查: 读取 batch_recheck_N.txt → 发给 LLM → 保存为 batch_recheck_N_response.txt")
    print(f"  然后运行: python cli.py --input {args.input} --auto-fix --agent merge")
    _hr('═')
    print()


def agent_merge(args):
    """Non-interactive: read AI response files + merge corrections + final output."""
    _header("Agent 模式: merge")

    df, col_map, states, groups = phase1(args)

    review_dir = Path(args.output_dir) / 'ai_review'
    if not review_dir.exists():
        print(f"  错误: ai_review 目录不存在: {review_dir}", file=sys.stderr)
        print(f"  请先运行: python cli.py --input {args.input} --auto-fix --agent prepare")
        sys.exit(1)

    ai_reviewed_ids: set[int] = set()
    ai_corrected_ids: set[int] = set()
    main_reviewed, main_corrected, main_summaries = merge_review_batches(
        review_dir,
        states,
        batch_type='main',
        strict=args.strict_review,
    )
    ai_reviewed_ids.update(main_reviewed)
    ai_corrected_ids.update(main_corrected)
    if main_summaries:
        total_corrections = 0
        for summary_item in main_summaries:
            total_corrections += summary_item['modified']
            print(
                f"  {summary_item['batch_name']}: "
                f"{summary_item['corrections']} 条修正, 应用 {summary_item['modified']} 处"
            )
        print(f"\n  AI审查合计: {total_corrections} 处修正")
    else:
        print("  警告: 未找到主审查 manifest，跳过 AI 合并")

    recheck_reviewed, recheck_corrected, recheck_summaries = merge_review_batches(
        review_dir,
        states,
        batch_type='recheck',
        strict=args.strict_review,
        ignore_fingerprint_for=main_corrected,
    )
    if recheck_summaries:
        _section("二次审查合并")
        total_recheck = 0
        for summary_item in recheck_summaries:
            total_recheck += summary_item['modified']
            print(
                f"  {summary_item['batch_name']}: "
                f"{summary_item['corrections']} 条修正, 应用 {summary_item['modified']} 处"
            )
        print(f"\n  二次审查合计: {total_recheck} 处修正")
    ai_reviewed_ids.update(recheck_reviewed)
    ai_corrected_ids.update(recheck_corrected)

    _header("生成最终输出")
    term_lookup = _load_term_base(args.term_base, lang=args.lang)
    summary = write_outputs(
        df, col_map, states, groups,
        args.input, args.lang, args.output_dir, args.lang_index,
        term_lookup=term_lookup,
        term_only_view=args.term_only_view,
        ai_reviewed_ids=ai_reviewed_ids,
        ai_corrected_ids=ai_corrected_ids,
    )

    _section("merge 完成")
    print(f"  总行数:       {summary['total_processed']}")
    print(f"  自动修复:     {summary['auto_fixed']}")
    print(f"  需人工确认:   {summary['need_human_review']}")
    print(f"  无需改动:     {summary['no_change']}")
    print(f"\n  最终结果:     {summary['result_path']}")
    print(f"  质检报告:     {summary['report_path']}")
    _hr('═')
    print()


def main():
    parser = argparse.ArgumentParser(
        description='游戏本地化质检工具 (CLI)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 交互模式（人工操作）
  python cli.py --input language.xlsx --auto-fix
  python cli.py --input language.xlsx --term-base terms.xlsx --batch-size 500
  python cli.py --input language.xlsx --auto-fix --skip-ai

  # Agent 模式（非交互，三步完成）
  python cli.py --input lang.xlsx --auto-fix --agent prepare
  # ... agent 读 prompt 文件 → 发 LLM → 写 response 文件 ...
  python cli.py --input lang.xlsx --auto-fix --agent merge
        """,
    )
    parser.add_argument('--input', required=True, help='语言表 Excel 文件')
    parser.add_argument('--term-base', default=None, help='术语库文件（Excel 或 JSON，可选）')
    parser.add_argument('--lang', default='en', help='目标语言代码（默认 en）')
    parser.add_argument('--output-dir', default='./output', help='输出目录（默认 ./output/）')
    parser.add_argument('--auto-fix', action='store_true', help='自动修复可修复项')
    parser.add_argument('--lang-index', type=int, default=0, help='多语言文件列索引')
    parser.add_argument('--batch-size', type=int, default=100,
                        help='AI审查每批行数（默认 100，首跑建议小批量）')
    parser.add_argument('--skip-ai', action='store_true', help='跳过AI审查，仅运行机审')
    parser.add_argument('--agent', choices=['prepare', 'merge'], default=None,
                        help='Agent 非交互模式: prepare=机审+生成提示词, merge=合并AI结果')
    parser.add_argument('--term-only-view', action='store_true', help='在结果文件新增“术语行筛选”sheet')
    parser.add_argument('--ai-scope', default='issues_only', choices=['all', 'issues_only', 'term_hit'],
                        help='AI审查范围: all=全量, issues_only=仅机审问题行, term_hit=仅术语命中行')
    parser.add_argument('--strict-review', action='store_true',
                        help='启用严格 AI 回复校验：必须逐条覆盖批次 ID，且输入指纹必须一致')

    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"错误: 文件不存在: {args.input}", file=sys.stderr)
        sys.exit(1)

    # Agent mode: non-interactive
    if args.agent == 'prepare':
        agent_prepare(args)
        return
    if args.agent == 'merge':
        agent_merge(args)
        return

    # Interactive mode: original flow
    print()
    df, col_map, states, groups = phase1(args)

    ai_corrections = 0
    if not args.skip_ai:
        term_lookup = _load_term_base(args.term_base, lang=args.lang)
        ai_corrections = phase2(states, term_lookup, args.batch_size, args.lang)
    else:
        print("\n  (已跳过AI审查)")

    _header("生成输出文件")
    term_lookup = _load_term_base(args.term_base, lang=args.lang)
    summary = write_outputs(
        df, col_map, states, groups,
        args.input, args.lang, args.output_dir, args.lang_index,
        term_lookup=term_lookup,
        term_only_view=args.term_only_view,
    )

    _section("最终汇总")
    print(f"  总行数:       {summary['total_processed']}")
    print(f"  自动修复:     {summary['auto_fixed']}（机审 + AI审）")
    print(f"  需人工确认:   {summary['need_human_review']}")
    print(f"  无需改动:     {summary['no_change']}")
    print(f"  UI文本:       {summary['ui_texts']}")
    print(f"  AI修正:       {ai_corrections}")
    print(f"\n  结果文件:     {summary['result_path']}")
    print(f"  质检报告:     {summary['report_path']}")
    _hr('═')
    print()


if __name__ == '__main__':
    main()
