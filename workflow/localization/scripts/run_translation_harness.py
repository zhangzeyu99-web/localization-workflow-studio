"""CLI for the agent-operated full translation harness.

Boundary: PRODUCT RUNTIME DEPENDENCY. The FastAPI backend invokes this script
as a subprocess (see backend/app/workflow/translation.py). Keep the CLI
contract stable and validate changes with `python -m pytest backend/tests -q`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from process_language import process
from utils.language_config import SUPPORTED_TRANSLATION_LANGUAGES
from utils.translation_harness import apply_translation_response, prepare_translation_harness


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare or apply an agent-operated full-translation harness")
    parser.add_argument("--input", required=True, help="Language workbook")
    parser.add_argument("--term-base", default=None, help="Term-base workbook or JSON")
    parser.add_argument(
        "--lang",
        default="en",
        help=f"Target language; supported: {', '.join(SUPPORTED_TRANSLATION_LANGUAGES)}",
    )
    parser.add_argument("--output-dir", default=None, help="Output directory for harness artifacts")
    parser.add_argument("--lang-index", type=int, default=None, help="Target language column index; defaults to matching --lang by header")
    parser.add_argument("--response", default=None, help="translation_response.jsonl to validate and apply")
    parser.add_argument("--manifest", default=None, help="translation_manifest.json; defaults to output-dir manifest")
    parser.add_argument("--run-qa", action="store_true", help="Run existing machine QA after applying response")
    parser.add_argument(
        "--style-hint",
        action="append",
        default=[],
        help="Short project-specific translation guidance; can be passed more than once",
    )
    parser.add_argument("--style-hint-file", default=None, help="UTF-8 text file with project-specific guidance")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"input not found: {input_path}", file=sys.stderr)
        return 2
    output_dir = Path(args.output_dir) if args.output_dir else input_path.parent / "translation_harness"
    style_hint = _collect_style_hint(args.style_hint, args.style_hint_file)

    if args.response:
        manifest_path = Path(args.manifest) if args.manifest else output_dir / "translation_manifest.json"
        applied = apply_translation_response(
            input_path=input_path,
            manifest_path=manifest_path,
            response_path=Path(args.response),
            output_dir=output_dir,
            lang=args.lang,
        )
        print(f"final_workbook={applied.final_workbook_path}")
        print(f"cache={applied.cache_path}")
        print(f"rows={applied.row_count}")
        if args.run_qa:
            qa_dir = output_dir / "qa"
            summary = process(
                input_path=str(applied.final_workbook_path),
                term_base_path=args.term_base,
                lang=args.lang,
                output_dir=str(qa_dir),
                auto_fix=True,
                lang_index=args.lang_index,
            )
            print(f"qa_result={summary['result_path']}")
            print(f"qa_report={summary['report_path']}")
        return 0

    prepared = prepare_translation_harness(
        input_path=input_path,
        term_base_path=args.term_base,
        lang=args.lang,
        output_dir=output_dir,
        lang_index=args.lang_index,
        style_hint=style_hint,
    )
    print(f"workpack={prepared.workpack_path}")
    print(f"manifest={prepared.manifest_path}")
    print(f"response_template={prepared.response_template_path}")
    print(f"requires_full_translation={prepared.target_status.requires_full_translation}")
    print(f"target_status={prepared.target_status.reason}")
    if style_hint:
        print(f"style_hint={style_hint}")
    return 0


def _collect_style_hint(inline_hints: list[str], hint_file: str | None) -> str:
    parts: list[str] = []
    for hint in inline_hints or []:
        cleaned = " ".join(str(hint).split())
        if cleaned:
            parts.append(cleaned)
    if hint_file:
        file_text = Path(hint_file).read_text(encoding="utf-8-sig")
        cleaned = " ".join(file_text.split())
        if cleaned:
            parts.append(cleaned)
    return "; ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
