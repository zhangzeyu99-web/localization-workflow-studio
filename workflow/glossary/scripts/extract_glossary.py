"""Thin CLI entry for glossary extraction.

The implementation lives in the ``glossary_extraction`` package at the repo
root. This script keeps the historical import surface alive: tests and sibling
scripts import this module (``import extract_glossary`` or via
``importlib.util.spec_from_file_location``) and expect every public symbol of
the old monolith to be available here.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from glossary_extraction import (  # noqa: E402
    ai_supplement as _ai_supplement_module,
    announcement as _announcement_module,
    cli as _cli_module,
    constants as _constants_module,
    excel_io as _excel_io_module,
    experience as _experience_module,
    heuristics as _heuristics_module,
    models as _models_module,
    reporting as _reporting_module,
)
from glossary_extraction.constants import *  # noqa: E402,F401,F403
from glossary_extraction.models import *  # noqa: E402,F401,F403
from glossary_extraction.heuristics import *  # noqa: E402,F401,F403
from glossary_extraction.experience import *  # noqa: E402,F401,F403
from glossary_extraction.excel_io import *  # noqa: E402,F401,F403
from glossary_extraction.announcement import *  # noqa: E402,F401,F403
from glossary_extraction.ai_supplement import *  # noqa: E402,F401,F403
from glossary_extraction.reporting import *  # noqa: E402,F401,F403
from glossary_extraction.cli import *  # noqa: E402,F401,F403
from glossary_extraction.cli import build_parser, main  # noqa: E402,F401

_PACKAGE_MODULES = (
    _constants_module,
    _models_module,
    _heuristics_module,
    _experience_module,
    _excel_io_module,
    _announcement_module,
    _ai_supplement_module,
    _reporting_module,
    _cli_module,
)


class _FacadeModule(type(sys)):
    """Propagate attribute writes into every package module defining the name.

    The old monolith exposed one flat namespace, so tests could monkeypatch
    e.g. ``extract_glossary.load_workbook`` and affect every caller. After the
    package split the same write must reach the modules that hold their own
    binding of that name.
    """

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        for module in _PACKAGE_MODULES:
            if name in module.__dict__:
                module.__dict__[name] = value


sys.modules[__name__].__class__ = _FacadeModule


if __name__ == "__main__":
    raise SystemExit(main())
