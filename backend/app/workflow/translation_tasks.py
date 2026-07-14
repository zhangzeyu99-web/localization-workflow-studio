from __future__ import annotations

from typing import Any

from .. import db


_LEGACY_UNFINISHED_STATUSES = {"failed", "needs_input", "canceled"}
_ACTIVE_RUN_STATUSES = {"queued", "running"}
_CLOSED_TRANSLATION_TASK_STATES = {"delivered", "abandoned", "closed"}


def translation_task_continuation_metadata(source_run: dict[str, Any]) -> dict[str, Any]:
    source_metadata = source_run.get("metadata") or {}
    parent_input_artifact_id = (
        source_metadata.get("parent_input_artifact_id")
        or source_metadata.get("multilingual_source_artifact_id")
        or source_metadata.get("input_artifact_id")
    )
    return {
        "parent_input_artifact_id": parent_input_artifact_id,
        "multilingual_source_artifact_id": source_metadata.get("multilingual_source_artifact_id") or parent_input_artifact_id,
        "translation_task_id": source_metadata.get("translation_task_id"),
    }


def translation_task_runs(project_id: str, translation_task_id: str) -> list[dict[str, Any]]:
    task_id = str(translation_task_id or "").strip()
    if not task_id:
        return []
    return [
        run
        for run in db.list_runs(project_id)
        if run.get("kind") in {"translation", "qa"}
        and str((run.get("metadata") or {}).get("translation_task_id") or "") == task_id
    ]


def mark_translation_task_state(project_id: str, translation_task_id: str, state: str) -> dict[str, Any]:
    task_id = str(translation_task_id or "").strip()
    normalized_state = str(state or "").strip().lower()
    if not task_id:
        raise ValueError("translation task id is required")
    if normalized_state not in {"delivered", "abandoned", "closed"}:
        raise ValueError("unsupported translation task state")
    return db.set_translation_task_terminal_state(project_id, task_id, normalized_state)


def abandon_legacy_translation_run(run_id: str) -> dict[str, Any]:
    run = db.get_run(run_id)
    metadata = run.get("metadata") or {}
    if run.get("kind") not in {"translation", "qa"} or metadata.get("task_origin") == "quick_task":
        raise ValueError("run is not a formal translation task")
    if str(metadata.get("translation_task_id") or "").strip():
        raise ValueError("run belongs to an identified translation task")
    if run.get("status") in _ACTIVE_RUN_STATUSES:
        raise ValueError("running translation task cannot be abandoned")
    if run.get("status") not in _LEGACY_UNFINISHED_STATUSES:
        raise ValueError("only unfinished legacy translation tasks can be abandoned")

    current_state = str(metadata.get("translation_task_state") or "").strip().lower()
    if current_state in _CLOSED_TRANSLATION_TASK_STATES:
        return {
            "project_id": run["project_id"],
            "run_id": run["id"],
            "state": current_state,
        }

    db.merge_run_metadata(
        run["id"],
        {
            "translation_task_state": "abandoned",
            "translation_task_state_updated_at": db.now_iso(),
        },
    )
    db.add_event(run["id"], "legacy translation task marked abandoned")
    return {
        "project_id": run["project_id"],
        "run_id": run["id"],
        "state": "abandoned",
    }


__all__ = [name for name in globals() if not name.startswith("__")]
