"""Make top-level modules (process_language, cli, utils, ...) importable
regardless of pytest invocation directory, e.g. when the studio repo runs
``python -m pytest workflow/localization/tests -q`` from its own root."""

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
