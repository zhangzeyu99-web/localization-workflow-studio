from __future__ import annotations

import sys
import types

from . import (
    common as common,
    project_analysis as project_analysis,
    prompt_snapshots as prompt_snapshots,
    materials as materials,
    announcement as announcement,
    announcement_segments as announcement_segments,
    announcement_ai as announcement_ai,
    announcement_outputs as announcement_outputs,
    translation_readiness as translation_readiness,
    subprocess_runner as subprocess_runner,
    naming as naming,
    jsonl_helpers as jsonl_helpers,
    table_helpers as table_helpers,
    announcement_shared as announcement_shared,
    glossary as glossary,
    delivery as delivery,
    qa as qa,
    quick_task as quick_task,
    translation as translation,
)

_MODULES = [
    common,
    project_analysis,
    prompt_snapshots,
    materials,
    announcement,
    announcement_segments,
    announcement_ai,
    announcement_outputs,
    translation_readiness,
    subprocess_runner,
    naming,
    jsonl_helpers,
    table_helpers,
    announcement_shared,
    glossary,
    delivery,
    qa,
    quick_task,
    translation,
]

# Merge every split module into the package namespace and then inject the same
# namespace back into each module. This preserves the old single-file global
# lookup behaviour while keeping the implementation physically split.
_SHARED_GLOBALS: dict[str, object] = {}
for _module in _MODULES:
    for _name, _value in vars(_module).items():
        if _name.startswith("__"):
            continue
        _SHARED_GLOBALS[_name] = _value

globals().update(_SHARED_GLOBALS)
for _module in _MODULES:
    vars(_module).update(_SHARED_GLOBALS)

__all__ = sorted(name for name in _SHARED_GLOBALS if not name.startswith("__"))


class _WorkflowPackage(types.ModuleType):
    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        for module in _MODULES:
            if hasattr(module, name):
                setattr(module, name, value)


sys.modules[__name__].__class__ = _WorkflowPackage
