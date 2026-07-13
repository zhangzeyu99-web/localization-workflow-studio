from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.large_text_multilingual_gate import parse_langs  # noqa: E402
from utils.large_text_multilingual_pack import prepare_pack  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a large multilingual workbook pack.")
    parser.add_argument("--input", action="append", required=True, type=Path)
    parser.add_argument("--term-base", type=Path)
    parser.add_argument("--history-dir", action="append", default=[], type=Path)
    parser.add_argument("--target-langs", required=True)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    result = prepare_pack(
        inputs=args.input,
        term_base=args.term_base,
        history_dirs=args.history_dir,
        target_langs=parse_langs(args.target_langs),
        work_dir=args.work_dir,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
