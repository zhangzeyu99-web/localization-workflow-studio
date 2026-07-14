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
    translation_orchestrator as translation_orchestrator,
    subprocess_runner as subprocess_runner,
    naming as naming,
    jsonl_helpers as jsonl_helpers,
    table_helpers as table_helpers,
    asset_import_export as asset_import_export,
    announcement_shared as announcement_shared,
    glossary as glossary,
    glossary_ai as glossary_ai,
    glossary_backfill as glossary_backfill,
    glossary_keys as glossary_keys,
    translation_tasks as translation_tasks,
    delivery as delivery,
    qa as qa,
    qa_model_fixes as qa_model_fixes,
    semantic_qa as semantic_qa,
    quick_task as quick_task,
    multilingual as multilingual,
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
    translation_orchestrator,
    subprocess_runner,
    naming,
    jsonl_helpers,
    table_helpers,
    asset_import_export,
    announcement_shared,
    glossary,
    glossary_ai,
    glossary_backfill,
    glossary_keys,
    translation_tasks,
    delivery,
    qa,
    qa_model_fixes,
    semantic_qa,
    quick_task,
    multilingual,
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
