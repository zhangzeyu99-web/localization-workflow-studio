"""Run localization quality regression fixtures and workbook scans."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.quality_harness import load_fixture, merge_results, run_fixture, scan_workbook


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run localization quality harness")
    parser.add_argument("fixtures", nargs="*", help="Fixture JSON files to run")
    parser.add_argument("--workbook", action="append", default=[], help="Workbook path to scan")
    parser.add_argument("--term-base", action="append", default=[], help="Optional term-base workbook/JSON override; workbook scans also auto-discover nearby term bases")
    parser.add_argument("--lang", default="en", help="Target language code")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--max-issues", type=int, default=30, help="Text output issue sample limit")
    args = parser.parse_args(argv)

    results = []
    for fixture_path in args.fixtures:
        fixture = load_fixture(fixture_path)
        results.append(run_fixture(fixture, lang=args.lang))

    for workbook_path in args.workbook:
        results.append(scan_workbook(workbook_path, lang=args.lang, term_base=args.term_base))

    if not results:
        parser.error("provide at least one fixture or --workbook")

    merged = merge_results(results)
    if args.json:
        print(json.dumps(merged.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_text_summary(merged, args.max_issues)

    return 0 if merged.passed else 1


def _print_text_summary(result, max_issues: int) -> None:
    print(f"passed: {result.passed}")
    print(f"fixture_cases: {result.total_cases}")
    print(f"workbook_rows: {result.rows_scanned}")
    print("issue_counts:")
    if result.issue_counts:
        for issue_type, count in result.issue_counts.most_common():
            print(f"  {issue_type}: {count}")
    else:
        print("  none")

    if result.failures:
        print("fixture_failures:")
        for failure in result.failures[:max_issues]:
            print(
                f"  {failure['id']}: expected={failure['expected_issues']} "
                f"actual={failure['actual_issues']}"
            )

    if result.issues:
        print("workbook_issues:")
        for issue in result.issues[:max_issues]:
            print(
                f"  {issue['file']}::{issue['sheet']}!row{issue['row']} "
                f"ID={issue['id']} {issue['check_type']}: {issue['translation']}"
            )


if __name__ == "__main__":
    raise SystemExit(main())
