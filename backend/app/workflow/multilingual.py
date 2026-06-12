from __future__ import annotations

from typing import Any

from .. import db
from ..jobs import active_job_id, start_singleton_job
from ..languages import require_supported_language, visible_language_code
from ..schemas import MultilingualQueueRequest, TranslateRequest
from .qa import run_qa_sync
from .subprocess_runner import user_facing_error
from .translation import run_translate_sync
from .translation_readiness import inspect_translation_readiness


TERMINAL_STATUSES = {"passed", "failed", "needs_input", "canceled"}
ACTIVE_STATUSES = {"queued", "running"}


def normalize_language_list(languages: list[str] | str) -> list[str]:
    raw = languages.split(",") if isinstance(languages, str) else languages
    normalized: list[str] = []
    for item in raw:
        value = str(item or "").strip()
        if not value:
            continue
        code = require_supported_language(value)
        if code not in normalized:
            normalized.append(code)
    if not normalized:
        raise ValueError("请选择至少一种目标语言")
    return normalized


def multilingual_status(project_id: str, input_artifact_id: str, languages: list[str] | str) -> dict[str, Any]:
    _require_project_artifact(project_id, input_artifact_id)
    selected = normalize_language_list(languages)
    rows = [_language_status(project_id, input_artifact_id, language) for language in selected]
    if all(item["status"] in {"passed", "qa_skipped"} for item in rows):
        overall = "passed"
    elif any(item["status"] in ACTIVE_STATUSES for item in rows):
        overall = "running"
    elif any(item["status"] == "failed" for item in rows):
        overall = "failed"
    elif any(item["run_id"] for item in rows):
        overall = "partial"
    else:
        overall = "pending"
    return {
        "project_id": project_id,
        "input_artifact_id": input_artifact_id,
        "overall_status": overall,
        "active_job_id": active_job_id(),
        "languages": rows,
    }


def start_multilingual_translation_queue(project_id: str, payload: MultilingualQueueRequest) -> dict[str, Any]:
    source = _require_project_artifact(project_id, payload.input_artifact_id)
    selected = normalize_language_list(payload.languages)
    _validate_reference_artifacts(project_id, payload)
    created = []
    for language in selected:
        run = _find_translation_run(project_id, payload.input_artifact_id, language)
        if run:
            continue
        metadata = {
            "input_artifact_id": payload.input_artifact_id,
            "parent_input_artifact_id": payload.input_artifact_id,
            "term_artifact_id": payload.term_artifact_id,
            "reference_artifact_ids": payload.reference_artifact_ids,
            "batch_size": payload.batch_size,
            "task_origin": "translation_run",
            "task_code": payload.task_code or "T",
            "multilingual_queue": True,
            "multilingual_source_artifact_id": source["id"],
        }
        run = db.insert_run(project_id, "translation", language, metadata)
        created.append(run["id"])

    job_id = _queue_job_id("translate", project_id, payload.input_artifact_id)

    def worker(cancel_event: Any) -> None:
        for language in selected:
            if cancel_event.is_set():
                break
            run = _find_translation_run(project_id, payload.input_artifact_id, language)
            if not run:
                continue
            if run.get("status") == "passed":
                continue
            if run.get("status") in ACTIVE_STATUSES and active_job_id() != job_id:
                continue
            try:
                db.add_event(run["id"], f"multilingual queue translating {visible_language_code(language)}")
                request = TranslateRequest(
                    batch_size=payload.batch_size,
                    confirm_api_budget=payload.confirm_api_budget,
                )
                run_translate_sync(run["id"], request, cancel_event=cancel_event)
            except Exception as exc:
                try:
                    current = db.get_run(run["id"])
                    db.update_run(
                        run["id"],
                        status=current.get("status") if current.get("status") in TERMINAL_STATUSES else "failed",
                        metadata={**current.get("metadata", {}), "error": user_facing_error(exc)},
                    )
                except Exception:
                    pass

    started, active_conflict = start_singleton_job(job_id, worker)
    status = multilingual_status(project_id, payload.input_artifact_id, selected)
    status["created_run_ids"] = created
    status["queue_started"] = started
    if active_conflict:
        status["active_conflict"] = active_conflict
    return status


def start_multilingual_qa_queue(project_id: str, payload: MultilingualQueueRequest) -> dict[str, Any]:
    _require_project_artifact(project_id, payload.input_artifact_id)
    selected = normalize_language_list(payload.languages)
    _validate_reference_artifacts(project_id, payload)
    created = []
    for language in selected:
        if _find_passed_or_deliverable_run(project_id, payload.input_artifact_id, language):
            continue
        if _find_qa_run(project_id, payload.input_artifact_id, language):
            continue
        qa_input = _qa_input_artifact(project_id, payload.input_artifact_id, language, payload.batch_size)
        if not qa_input:
            continue
        source_translation = _find_translation_run(project_id, payload.input_artifact_id, language)
        metadata = {
            "input_artifact_id": qa_input["id"],
            "parent_input_artifact_id": payload.input_artifact_id,
            "term_artifact_id": payload.term_artifact_id,
            "reference_artifact_ids": payload.reference_artifact_ids,
            "task_origin": "translation_continuation" if source_translation else "direct_import",
            "source_run_id": source_translation["id"] if source_translation else None,
            "task_code": payload.task_code or "QA",
            "multilingual_queue": True,
            "multilingual_source_artifact_id": payload.input_artifact_id,
        }
        run = db.insert_run(project_id, "qa", language, metadata)
        created.append(run["id"])

    job_id = _queue_job_id("qa", project_id, payload.input_artifact_id)

    def worker(cancel_event: Any) -> None:
        for language in selected:
            if cancel_event.is_set():
                break
            run = _find_qa_run(project_id, payload.input_artifact_id, language)
            if not run or run.get("status") == "passed":
                continue
            if run.get("status") in ACTIVE_STATUSES and active_job_id() != job_id:
                continue
            try:
                db.add_event(run["id"], f"multilingual queue running QA {visible_language_code(language)}")
                run_qa_sync(run["id"])
            except Exception as exc:
                try:
                    current = db.get_run(run["id"])
                    db.update_run(run["id"], status="failed", metadata={**current.get("metadata", {}), "error": user_facing_error(exc)})
                except Exception:
                    pass

    started, active_conflict = start_singleton_job(job_id, worker)
    status = multilingual_status(project_id, payload.input_artifact_id, selected)
    status["created_run_ids"] = created
    status["queue_started"] = started
    if active_conflict:
        status["active_conflict"] = active_conflict
    return status


def _language_status(project_id: str, input_artifact_id: str, language: str) -> dict[str, Any]:
    translation_run = _find_translation_run(project_id, input_artifact_id, language)
    qa_run = _find_qa_run(project_id, input_artifact_id, language)
    deliverable_run = _find_passed_or_deliverable_run(project_id, input_artifact_id, language)
    active_run = qa_run or translation_run
    run_for_status = deliverable_run or active_run
    progress = ((translation_run or {}).get("metadata") or {}).get("translation_progress") or {}
    quality = ((run_for_status or {}).get("metadata") or {}).get("quality_summary") or {}
    status = run_for_status.get("status") if run_for_status else "pending"
    if (run_for_status and (run_for_status.get("metadata") or {}).get("qa_skipped")):
        status = "qa_skipped"
    return {
        "language": language,
        "visible_language": visible_language_code(language),
        "run_id": run_for_status.get("id") if run_for_status else None,
        "translation_run_id": translation_run.get("id") if translation_run else None,
        "qa_run_id": qa_run.get("id") if qa_run else None,
        "status": status,
        "step": "qa" if qa_run else ("translation" if translation_run else "pending"),
        "can_continue": bool(run_for_status and run_for_status.get("status") in {"failed", "needs_input", "canceled"}),
        "error": ((run_for_status or {}).get("metadata") or {}).get("error") or "",
        "progress": progress,
        "quality_summary": quality,
    }


def _find_translation_run(project_id: str, input_artifact_id: str, language: str) -> dict[str, Any] | None:
    return _find_child_run(project_id, input_artifact_id, language, "translation")


def _find_qa_run(project_id: str, input_artifact_id: str, language: str) -> dict[str, Any] | None:
    return _find_child_run(project_id, input_artifact_id, language, "qa")


def _find_child_run(project_id: str, input_artifact_id: str, language: str, kind: str) -> dict[str, Any] | None:
    for run in db.list_runs(project_id):
        if run.get("kind") != kind or require_supported_language(run.get("language") or "en") != language:
            continue
        metadata = run.get("metadata") or {}
        candidates = {
            str(metadata.get("input_artifact_id") or ""),
            str(metadata.get("parent_input_artifact_id") or ""),
            str(metadata.get("multilingual_source_artifact_id") or ""),
        }
        if input_artifact_id in candidates:
            return run
    return None


def _find_passed_or_deliverable_run(project_id: str, input_artifact_id: str, language: str) -> dict[str, Any] | None:
    for kind in ("qa", "translation"):
        run = _find_child_run(project_id, input_artifact_id, language, kind)
        if not run:
            continue
        if run.get("status") == "passed" or _run_final_artifact(run):
            return run
    return None


def _qa_input_artifact(project_id: str, input_artifact_id: str, language: str, batch_size: int | None = None) -> dict[str, Any] | None:
    translation_run = _find_translation_run(project_id, input_artifact_id, language)
    if translation_run:
        final_artifact = _run_final_artifact(translation_run)
        if final_artifact:
            return final_artifact
    source_artifact = _require_project_artifact(project_id, input_artifact_id)
    try:
        readiness = inspect_translation_readiness(input_artifact_id, batch_size=batch_size, language=language)
    except Exception:
        return None
    if readiness.get("ready_for_qa"):
        return source_artifact
    return None


def _run_final_artifact(run: dict[str, Any]) -> dict[str, Any] | None:
    accepted = {"qa_final_workbook", "final_workbook", "raw_translated_workbook", "final_text"}
    for artifact in db.list_artifacts(run_id=run["id"]):
        if artifact.get("kind") in accepted:
            return artifact
    return None


def _require_project_artifact(project_id: str, artifact_id: str) -> dict[str, Any]:
    try:
        artifact = db.get_artifact(artifact_id)
    except KeyError as exc:
        raise KeyError("artifact not found") from exc
    if artifact.get("project_id") != project_id:
        raise ValueError("文件不属于当前项目")
    return artifact


def _validate_reference_artifacts(project_id: str, payload: MultilingualQueueRequest) -> None:
    if payload.term_artifact_id:
        _require_project_artifact(project_id, payload.term_artifact_id)
    for artifact_id in payload.reference_artifact_ids:
        _require_project_artifact(project_id, artifact_id)


def _queue_job_id(kind: str, project_id: str, input_artifact_id: str) -> str:
    return f"multilingual:{kind}:{project_id}:{input_artifact_id}"


__all__ = [name for name in globals() if not name.startswith("__")]
