from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.history_lookup import extract_source_queries, lookup_exact_history


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only exact lookup against accepted history workbooks for a small localization task")
    parser.add_argument("--input", required=True, type=Path, help="Current task workbook containing the source column")
    parser.add_argument("--history", action="append", required=True, type=Path, help="Accepted history workbook; repeatable")
    parser.add_argument("--lang", action="append", required=True, help="Requested target language code or alias; repeatable")
    parser.add_argument("--output", required=True, type=Path, help="UTF-8 JSON lookup result")
    args = parser.parse_args()

    queries = extract_source_queries(args.input)
    result = lookup_exact_history(queries, args.history, args.lang)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"queries={result['query_count']} exact={result['exact_count']} "
        f"partial={result['partial_count']} miss={result['miss_count']} "
        f"history_files={len(result['scanned_history_files'])} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
