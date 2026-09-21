"""Boundary: AGENT-ONLY private approved-name snapshot preparation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.approved_name_snapshot import main

if __name__ == "__main__":
    raise SystemExit(main())
