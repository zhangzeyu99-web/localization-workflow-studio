"""Boundary: AGENT-ONLY name-collision and cumulative-delivery validation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.name_collision_gate import main

if __name__ == "__main__":
    raise SystemExit(main())
