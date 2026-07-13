from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.large_text_multilingual_executor import translate_manifest  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run resumable multilingual API translation")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--relay-config", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=60)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    result = translate_manifest(
        args.manifest,
        relay_config=args.relay_config,
        batch_size=args.batch_size,
        workers=args.workers,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
