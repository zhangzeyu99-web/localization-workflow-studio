"""Workspace-oriented batch runner for localization QA.

Discovers project folders under a shared workspace root, resolves the main
language file plus matching term files, merges term bases, and runs the
existing processing pipeline for each project.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from process_language import (
    _load_term_base,
    prepare_ai_review,
    run_machine_review,
    write_outputs,
)
from utils.ai_checker import (
    merge_review_batches,
    prepare_recheck_batches,
    write_response_templates,
    write_review_files,
)
from utils.language_detection import inspect_language_file


LANG_HINTS = {
    'en': ('英语', '英文', 'english'),
    'idn': ('印尼', '印度尼西亚', 'indonesian', 'idn'),
}

LANG_OUTPUT_SUFFIX = {
    'en': 'english',
    'idn': 'indonesian',
}

IGNORED_PROJECT_DIR_NAMES = {
    '新建文件夹',
    '新建文件夹 (2)',
}


@dataclass
class WorkspaceTask:
    project_name: str
    lang: str
    language_file: Path
    term_files: list[Path]
    output_dir: Path


def _is_temp_file(path: Path) -> bool:
    return path.name.startswith('~$')


def _lang_matches(path: Path, lang: str) -> bool:
    if lang == 'auto':
        return True
    lowered = path.stem.lower()
    hints = LANG_HINTS.get(lang, (lang.lower(),))
    return any(hint.lower() in lowered for hint in hints)


def _is_term_file(path: Path) -> bool:
    return '术语' in path.stem


def _language_file_score(path: Path, project_root: Path) -> tuple:
    name = path.stem
    depth = len(path.relative_to(project_root).parts)
    keyword_score = 0
    if '整体校对' in name:
        keyword_score += 30
    if '语言表' in name:
        keyword_score += 20
    if '校对' in name:
        keyword_score += 10
    if 'ui' in name.lower():
        keyword_score -= 5
    if '新增' in name:
        keyword_score -= 5
    if '升级' in name:
        keyword_score -= 5
    return (keyword_score, -depth, path.stat().st_size, name)


def _term_file_score(path: Path, project_root: Path) -> tuple:
    name = path.stem
    depth = len(path.relative_to(project_root).parts)
    keyword_score = 0
    if '约束完整' in name:
        keyword_score += 30
    elif '约束' in name:
        keyword_score += 20
    elif '完整' in name:
        keyword_score += 10
    return (keyword_score, -depth, path.stat().st_size, name)


def _iter_excel_files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob('*.xlsx')
        if path.is_file() and not _is_temp_file(path)
    )


def _discover_common_term_files(root: Path, lang: str) -> list[Path]:
    candidates = []
    for path in root.glob('*.xlsx'):
        if _is_temp_file(path) or not _is_term_file(path):
            continue
        if not _lang_matches(path, lang):
            continue
        candidates.append(path)
    return sorted(candidates, key=lambda path: path.name)


def _discover_project_language_file(project_root: Path, lang: str) -> Path | None:
    candidates = []
    for path in _iter_excel_files(project_root):
        if _is_term_file(path):
            continue
        if not _lang_matches(path, lang):
            continue
        candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda path: _language_file_score(path, project_root))


def _discover_project_term_files(project_root: Path, lang: str) -> list[Path]:
    candidates = []
    for path in _iter_excel_files(project_root):
        if not _is_term_file(path):
            continue
        if not _lang_matches(path, lang):
            continue
        candidates.append(path)
    if not candidates:
        return []
    sorted_candidates = sorted(candidates, key=lambda path: _term_file_score(path, project_root))
    best_score = _term_file_score(sorted_candidates[-1], project_root)
    return [
        path for path in sorted_candidates
        if _term_file_score(path, project_root) == best_score
    ]


def discover_workspace_tasks(root: str | Path, lang: str = 'en') -> list[WorkspaceTask]:
    workspace_root = Path(root)
    tasks: list[WorkspaceTask] = []
    candidate_langs = list(LANG_HINTS.keys()) if lang == 'auto' else [lang]

    for child in sorted(path for path in workspace_root.iterdir() if path.is_dir()):
        if child.name in IGNORED_PROJECT_DIR_NAMES:
            continue
        for task_lang in candidate_langs:
            language_file = _discover_project_language_file(child, task_lang)
            if language_file is None:
                continue

            common_term_files = _discover_common_term_files(workspace_root, task_lang)
            project_terms = _discover_project_term_files(child, task_lang)
            output_dir = child / f'output_{LANG_OUTPUT_SUFFIX.get(task_lang, task_lang)}'
            tasks.append(
                WorkspaceTask(
                    project_name=child.name,
                    lang=task_lang,
                    language_file=language_file,
                    term_files=[*common_term_files, *project_terms],
                    output_dir=output_dir,
                )
            )

    return tasks


def merge_term_files(paths: list[Path], lang: str = 'en') -> dict:
    merged: dict = {}
    for path in paths:
        for cn_term, value in _load_term_base(str(path), lang=lang).items():
            merged[cn_term] = value
    return merged


def write_merged_term_base(term_files: list[Path], output_dir: Path, lang: str) -> Path | None:
    if not term_files:
        return None

    merged = merge_term_files(term_files, lang=lang)
    output_dir.mkdir(parents=True, exist_ok=True)
    merged_path = output_dir / f'term_base_merged_{lang}.json'
    merged_path.write_text(
        json.dumps({'lookup': merged}, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return merged_path


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


def _resolve_task_context(task: WorkspaceTask, lang: str | None, auto_fix: bool):
    effective_lang = lang or task.lang
    profile = inspect_language_file(task.language_file)
    print(
        f"[预检] {task.project_name}/{task.language_file.name}: "
        f"source={profile['source_lang']} target={profile['target_lang']} request={effective_lang}"
    )
    if profile['target_lang'] not in ('unknown', effective_lang):
        print(f"[预警] 检测到目标语言为 {profile['target_lang']}，将优先按检测结果处理")
        effective_lang = profile['target_lang']

    merged_term_path = write_merged_term_base(task.term_files, task.output_dir, effective_lang)
    term_lookup = _load_term_base(str(merged_term_path), lang=effective_lang) if merged_term_path else {}
    df, col_map, states, groups = run_machine_review(
        input_path=str(task.language_file),
        term_base_path=str(merged_term_path) if merged_term_path else None,
        lang=effective_lang,
        auto_fix=auto_fix,
    )
    return {
        'effective_lang': effective_lang,
        'profile': profile,
        'merged_term_path': merged_term_path,
        'term_lookup': term_lookup,
        'df': df,
        'col_map': col_map,
        'states': states,
        'groups': groups,
    }


def _attach_task_metadata(summary: dict, task: WorkspaceTask, effective_lang: str, merged_term_path: Path | None) -> dict:
    summary['project_name'] = task.project_name
    summary['lang'] = effective_lang
    summary['language_file'] = str(task.language_file)
    summary['merged_term_base'] = str(merged_term_path) if merged_term_path else ''
    return summary


def run_workspace_task(
    task: WorkspaceTask,
    *,
    mode: str = 'machine',
    lang: str | None = None,
    auto_fix: bool = True,
    batch_size: int = 100,
    ai_scope: str = 'all',
    strict_review: bool = True,
    term_only_view: bool = True,
) -> dict:
    context = _resolve_task_context(task, lang, auto_fix)
    effective_lang = context['effective_lang']
    merged_term_path = context['merged_term_path']
    term_lookup = context['term_lookup']
    df = context['df']
    col_map = context['col_map']
    states = context['states']
    groups = context['groups']

    if mode == 'machine':
        summary = write_outputs(
            df,
            col_map,
            states,
            groups,
            str(task.language_file),
            effective_lang,
            str(task.output_dir),
            term_lookup=term_lookup,
            term_only_view=term_only_view,
        )
        return _attach_task_metadata(summary, task, effective_lang, merged_term_path)

    review_dir = task.output_dir / 'ai_review'
    if mode == 'prepare':
        batches = prepare_ai_review(
            states,
            batch_size=batch_size,
            term_lookup=term_lookup,
            lang=effective_lang,
            scope=ai_scope,
            include_term_priority=True,
        )
        _reset_review_dir(review_dir)
        write_review_files(
            review_dir=review_dir,
            batches=batches,
            states=states,
            batch_type='main',
            lang=effective_lang,
            input_path=str(task.language_file),
            ai_scope=ai_scope,
        )
        seeded_main = write_response_templates(review_dir, batch_type='main', overwrite=False)

        recheck_rows = _collect_recheck_rows(states, batches)
        recheck_batch_count = 0
        if recheck_rows:
            recheck_batches = prepare_recheck_batches(
                recheck_rows,
                batch_size=batch_size,
                term_lookup=term_lookup,
                lang=effective_lang,
            )
            recheck_batch_count = len(recheck_batches)
            write_review_files(
                review_dir=review_dir,
                batches=recheck_batches,
                states=states,
                batch_type='recheck',
                lang=effective_lang,
                input_path=str(task.language_file),
                ai_scope='recheck_term_issues',
            )
            seeded_recheck = write_response_templates(review_dir, batch_type='recheck', overwrite=False)
        else:
            seeded_recheck = 0

        summary = write_outputs(
            df,
            col_map,
            states,
            groups,
            str(task.language_file),
            effective_lang,
            str(task.output_dir),
            term_lookup=term_lookup,
            term_only_view=term_only_view,
        )
        summary['review_dir'] = str(review_dir)
        summary['main_batch_count'] = len(batches)
        summary['recheck_batch_count'] = recheck_batch_count
        summary['prepared_rows'] = sum(len(batch.row_ids) for batch in batches)
        summary['seeded_main_templates'] = seeded_main
        summary['seeded_recheck_templates'] = seeded_recheck
        return _attach_task_metadata(summary, task, effective_lang, merged_term_path)

    if mode == 'merge':
        ai_reviewed_ids, ai_corrected_ids, main_summaries = merge_review_batches(
            review_dir,
            states,
            batch_type='main',
            strict=strict_review,
        )
        recheck_reviewed, recheck_corrected, recheck_summaries = merge_review_batches(
            review_dir,
            states,
            batch_type='recheck',
            strict=strict_review,
            ignore_fingerprint_for=main_corrected,
        )
        ai_reviewed_ids.update(recheck_reviewed)
        ai_corrected_ids.update(recheck_corrected)
        summary = write_outputs(
            df,
            col_map,
            states,
            groups,
            str(task.language_file),
            effective_lang,
            str(task.output_dir),
            term_lookup=term_lookup,
            term_only_view=term_only_view,
            ai_reviewed_ids=ai_reviewed_ids,
            ai_corrected_ids=ai_corrected_ids,
        )
        summary['review_dir'] = str(review_dir)
        summary['main_batch_count'] = len(main_summaries)
        summary['recheck_batch_count'] = len(recheck_summaries)
        summary['ai_reviewed_rows'] = len(ai_reviewed_ids)
        summary['ai_corrected_rows'] = len(ai_corrected_ids)
        return _attach_task_metadata(summary, task, effective_lang, merged_term_path)

    raise ValueError(f'Unsupported mode: {mode}')


def main():
    parser = argparse.ArgumentParser(description='按约定目录批量处理本地化项目')
    parser.add_argument('--workspace', required=True, help='工作区根目录')
    parser.add_argument('--lang', default='auto', help='目标语言：en / idn / auto')
    parser.add_argument('--project', default=None, help='只处理指定项目目录名')
    parser.add_argument('--mode', default='machine', choices=['machine', 'prepare', 'merge'],
                        help='运行模式：machine=仅机审输出，prepare=机审+生成严格 AI 审查批次，merge=合并 AI 回写')
    parser.add_argument('--auto-fix', action='store_true', help='启用自动修复')
    parser.add_argument('--batch-size', type=int, default=100, help='AI 审查每批行数（默认 100）')
    parser.add_argument('--ai-scope', default='all', choices=['all', 'issues_only', 'term_hit'],
                        help='AI 审查范围')
    parser.add_argument('--strict-review', action='store_true',
                        help='merge 时启用严格回复校验：批次全覆盖且输入指纹一致')
    args = parser.parse_args()

    tasks = discover_workspace_tasks(args.workspace, lang=args.lang)
    if args.project:
        tasks = [task for task in tasks if task.project_name == args.project]

    if not tasks:
        raise SystemExit('未发现可处理项目')

    for task in tasks:
        summary = run_workspace_task(
            task,
            mode=args.mode,
            lang=None if args.lang == 'auto' else args.lang,
            auto_fix=args.auto_fix,
            batch_size=args.batch_size,
            ai_scope=args.ai_scope,
            strict_review=args.strict_review,
        )
        if args.mode == 'prepare':
            print(
                f"[{summary['project_name']}:{summary['lang']}] "
                f"prepared {summary['prepared_rows']} rows -> {summary['review_dir']}"
            )
        else:
            print(
                f"[{summary['project_name']}:{summary['lang']}] {summary['total_processed']} 行 -> "
                f"{summary['result_path']}"
            )


if __name__ == '__main__':
    main()
