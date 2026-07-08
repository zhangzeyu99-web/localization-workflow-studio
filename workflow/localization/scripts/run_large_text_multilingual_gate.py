"""Boundary: AGENT-ONLY tooling. Not imported or subprocessed by the backend;
backend/app/workflow/large_text.py is a port of these gate rules with parity
tests in backend/tests/test_large_text_productization.py (this gate wins)."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.large_text_multilingual_gate import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
