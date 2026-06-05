"""CLI for the announcement DOCX retrieval-style translation harness."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.announcement_docx_harness import (
    apply_announcement_translations,
    deliver_announcement_outputs,
    import_announcement_ai_responses,
    inspect_announcement_task_dir,
    prepare_announcement_docx_harness,
    stage_announcement_task_dir,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare, apply, or deliver announcement DOCX translations")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Identify loose sources, term files, references, and target languages")
    inspect_parser.add_argument("--input-dir", required=True, help="Raw task directory")

    stage_parser = subparsers.add_parser("stage", help="Normalize a raw task directory into harness-ready source_input")
    stage_parser.add_argument("--input-dir", required=True, help="Raw task directory")

    prepare_parser = subparsers.add_parser("prepare", help="Build the intermediate translation workbook")
    prepare_parser.add_argument("--input-dir", required=True, help="Task directory containing DOCX and terms workbook")
    prepare_parser.add_argument("--lang", action="append", default=None, help="Language header or code to prepare; repeatable")

    import_parser = subparsers.add_parser("import-ai", help="Import model-authored ai_response_*.jsonl files")
    import_parser.add_argument("--input-dir", required=True, help="Task directory used during prepare")
    import_parser.add_argument("--translation-workbook", default=None, help="Intermediate translation workbook")
    import_parser.add_argument("--response-dir", default=None, help="Directory containing ai_response_<code>.jsonl files")
    import_parser.add_argument("--lang", action="append", default=None, help="Language header or code to import; repeatable")

    apply_parser = subparsers.add_parser("apply", help="Validate translations and write language DOCX files")
    apply_parser.add_argument("--input-dir", required=True, help="Task directory used during prepare")
    apply_parser.add_argument("--translation-workbook", required=True, help="Filled announcement translation workbook")

    deliver_parser = subparsers.add_parser("deliver", help="Copy passed outputs to a clean delivery directory")
    deliver_parser.add_argument("--input-dir", required=True, help="Task directory used during apply")
    deliver_parser.add_argument("--date-stamp", default=None, help="Optional YYYYMMDD suffix for delivery directory")

    args = parser.parse_args()
    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        print(f"input_dir not found: {input_dir}", file=sys.stderr)
        return 2

    if args.command == "inspect":
        inspection = inspect_announcement_task_dir(input_dir)
        print(f"input_dir={inspection.input_dir}")
        print(f"sources={','.join(path.name for path in inspection.source_files)}")
        print(f"term_files={','.join(path.name for path in inspection.term_files)}")
        print(f"reference_files={','.join(path.name for path in inspection.reference_files)}")
        print(f"languages={','.join(f'{header}:{code}' for header, code in inspection.languages)}")
        return 0

    if args.command == "stage":
        staged = stage_announcement_task_dir(input_dir)
        print(f"staging_dir={staged.staging_dir}")
        print(f"sources={','.join(path.name for path in staged.source_files)}")
        print(f"term_files={','.join(path.name for path in staged.term_files)}")
        print(f"languages={','.join(f'{header}:{code}' for header, code in staged.languages)}")
        return 0

    if args.command == "prepare":
        prepared = prepare_announcement_docx_harness(input_dir, languages=args.lang)
        print(f"translation_workbook={prepared.translation_workbook}")
        print(f"manifest={prepared.manifest_path}")
        print(f"work_dir={prepared.work_dir}")
        print(f"documents={prepared.doc_count}")
        print(f"paragraphs={prepared.row_count}")
        return 0

    if args.command == "import-ai":
        imported = import_announcement_ai_responses(
            input_dir,
            translation_workbook=args.translation_workbook,
            response_dir=args.response_dir,
            languages=args.lang,
        )
        print(f"translation_workbook={imported.translation_workbook}")
        print(f"work_dir={imported.work_dir}")
        print(f"languages={','.join(imported.languages)}")
        print(f"rows={imported.row_count}")
        return 0

    if args.command == "apply":
        workbook = Path(args.translation_workbook)
        if not workbook.exists():
            print(f"translation_workbook not found: {workbook}", file=sys.stderr)
            return 2
        applied = apply_announcement_translations(input_dir, workbook)
        print(f"hard_blockers={applied.hard_blockers}")
        print(f"output_dir={applied.output_dir}")
        print(f"qa_summary={applied.qa_summary_path}")
        print(f"docx_count={len(applied.output_docx_paths)}")
        return 0

    delivered = deliver_announcement_outputs(input_dir, date_stamp=args.date_stamp)
    print(f"delivery_dir={delivered.delivery_dir}")
    print(f"files={len(delivered.files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
