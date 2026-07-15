from __future__ import annotations

import threading
from typing import Any

from . import db, job_queue, operator_context
from .config import load_settings
from .schemas import AnnouncementTaskTranslateRequest, ModelFixRequest, MultilingualQueueRequest, TranslateRequest


RUN_TERMINAL_STATUSES = {"passed", "failed", "needs_input", "canceled"}
_SUBMISSION_LOCK = threading.RLock()


def lane_for_run(run: dict[str, Any], job_kind: str) -> str:
    if job_kind in {"translation", "qa"} and (run.get("metadata") or {}).get("task_origin") == "quick_task":
        return "quick_announcement"
    return lane_for_job(job_kind)


def lane_for_job(job_kind: str) -> str:
    return "quick_announcement" if job_kind == "announcement" else "language_table"


def register_handlers() -> None:
    job_queue.register_handler("translation", _translation_handler)
    job_queue.register_handler("qa", _qa_handler)
    job_queue.register_handler("model_fix", _model_fix_handler)
    job_queue.register_handler("announcement", _announcement_handler)
    job_queue.register_handler("multilingual_translate", _multilingual_translation_handler)
    job_queue.register_handler("multilingual_qa", _multilingual_qa_handler)


def start_translation(run_id: str, request: TranslateRequest | dict[str, Any]) -> dict[str, Any]:
    payload = request if isinstance(request, TranslateRequest) else TranslateRequest.model_validate(request)
    return _enqueue_run(run_id, "translation", payload.model_dump(exclude_none=True))


def start_qa(run_id: str) -> dict[str, Any]:
    return _enqueue_run(run_id, "qa", {})


def start_model_fix(run_id: str, request: ModelFixRequest | dict[str, Any]) -> dict[str, Any]:
    payload = request if isinstance(request, ModelFixRequest) else ModelFixRequest.model_validate(request)
    return _enqueue_run(run_id, "model_fix", payload.model_dump(exclude_none=True))


def start_announcement(
    task_id: str,
    request: AnnouncementTaskTranslateRequest | dict[str, Any],
) -> dict[str, Any]:
    with _SUBMISSION_LOCK:
        return _start_announcement(task_id, request)


def _start_announcement(
    task_id: str,
    request: AnnouncementTaskTranslateRequest | dict[str, Any],
) -> dict[str, Any]:
    task = db.get_announcement_task(task_id)
    payload = request if isinstance(request, AnnouncementTaskTranslateRequest) else AnnouncementTaskTranslateRequest.model_validate(request)
    operator_name = operator_context.require_operator_for_cloud()
    queued = job_queue.enqueue_job(
        job_id=f"announcement:{task_id}",
        lane="quick_announcement",
        job_kind="announcement",
        project_id=task["project_id"],
        target_id=task_id,
        payload=payload.model_dump(exclude_none=True),
        operator_name=operator_name,
        autostart=False,
        staged=True,
    )
    if queued.get("stage_owned"):
        try:
            db.merge_announcement_task_metadata(task_id, {"queued_at": queued["queued_at"]})
            db.update_announcement_task(task_id, status="queued", current_step=7)
        except Exception:
            job_queue.abandon_staged_job(queued["job_id"])
            raise
        job_queue.activate_job(queued["job_id"])
    return db.get_announcement_task(task_id)


def start_multilingual(
    job_kind: str,
    project_id: str,
    input_artifact_id: str,
    request: MultilingualQueueRequest,
    child_run_ids: list[str],
) -> dict[str, Any]:
    with _SUBMISSION_LOCK:
        return _start_multilingual(job_kind, project_id, input_artifact_id, request, child_run_ids)


def _start_multilingual(
    job_kind: str,
    project_id: str,
    input_artifact_id: str,
    request: MultilingualQueueRequest,
    child_run_ids: list[str],
) -> dict[str, Any]:
    suffix = "translate" if job_kind == "multilingual_translate" else "qa"
    queued = job_queue.enqueue_job(
        job_id=f"multilingual:{suffix}:{project_id}:{input_artifact_id}",
        lane="language_table",
        job_kind=job_kind,
        project_id=project_id,
        target_id=input_artifact_id,
        payload={"request": request.model_dump(exclude_none=True), "child_run_ids": child_run_ids},
        operator_name=operator_context.require_operator_for_cloud(),
        autostart=False,
        staged=True,
    )
    if queued.get("stage_owned"):
        try:
            for run_id in child_run_ids:
                run = db.get_run(run_id)
                if run.get("status") in {"created", "failed", "needs_input", "canceled"}:
                    db.merge_run_metadata(run_id, {"queued_at": queued["queued_at"]})
                    db.update_run(run_id, status="queued")
        except Exception:
            job_queue.abandon_staged_job(queued["job_id"])
            raise
        return job_queue.activate_job(queued["job_id"])
    return queued


def cancel(job_id: str) -> dict[str, Any] | None:
    with _SUBMISSION_LOCK:
        return _cancel(job_id)


def _cancel(job_id: str) -> dict[str, Any] | None:
    existing = job_queue.get_job(job_id)
    if existing is None or existing.get("status") not in job_queue.ACTIVE_STATUSES:
        return None
    canceled_by = operator_context.require_operator_for_cloud()
    queue_job = job_queue.cancel_job(job_id, canceled_by=canceled_by)
    if queue_job is None:
        return None
    queued_cancel = queue_job["status"] == "canceled"
    audit = {
        "canceled_by": canceled_by,
        "cancel_requested_at": queue_job.get("cancel_requested_at"),
    }
    if queued_cancel:
        audit["canceled_at"] = queue_job.get("canceled_at")
    kind = str(existing.get("job_kind") or "")
    if kind == "announcement":
        task_id = str(existing["target_id"])
        db.merge_announcement_task_metadata(task_id, audit)
        if queued_cancel:
            task = db.update_announcement_task(task_id, status="prepared", current_step=7)
            for item in task.get("languages") or []:
                if item.get("status") in {"queued", "running"}:
                    language_metadata = dict(item.get("metadata") or {})
                    language_metadata.update(audit)
                    db.upsert_announcement_task_language(
                        task_id,
                        task["project_id"],
                        str(item["language"]),
                        status="prepared",
                        current_step=7,
                        metadata=language_metadata,
                    )
        business_target: dict[str, Any] = db.get_announcement_task(task_id)
    elif kind.startswith("multilingual_"):
        runs = []
        for run_id in _record_run_ids(existing):
            db.merge_run_metadata(run_id, audit)
            run = db.get_run(run_id)
            if queued_cancel and run.get("status") == "queued":
                db.update_run(run_id, status="canceled")
                db.add_event(run_id, operator_context.prefixed_message("排队任务已取消", canceled_by))
            elif not queued_cancel:
                db.add_event(run_id, operator_context.prefixed_message("已请求取消，任务将在阶段边界停止", canceled_by))
            runs.append(db.get_run(run_id))
        business_target = {"runs": runs}
    else:
        run_id = str(existing["target_id"])
        if kind == "model_fix" and queued_cancel:
            audit["model_fix_status"] = "canceled"
        elif kind == "model_fix":
            audit["model_fix_status"] = "cancel_requested"
        if not queued_cancel:
            audit["cancel_requested_by"] = canceled_by
        db.merge_run_metadata(run_id, audit)
        if queued_cancel:
            db.update_run(run_id, status="canceled")
            db.add_event(run_id, operator_context.prefixed_message("排队任务已取消", canceled_by))
        else:
            db.add_event(run_id, operator_context.prefixed_message("已请求取消，任务将在阶段边界停止", canceled_by))
        business_target = db.get_run(run_id)
    return {"queue_job": queue_job, "business_target": business_target}


def cancel_announcement_task(task_id: str) -> dict[str, Any]:
    with _SUBMISSION_LOCK:
        _cancel(f"announcement:{task_id}")
        from . import workflow

        return workflow.cancel_announcement_task(task_id)


def _enqueue_run(run_id: str, job_kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _SUBMISSION_LOCK:
        return _enqueue_run_locked(run_id, job_kind, payload)


def _enqueue_run_locked(run_id: str, job_kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    run = db.get_run(run_id)
    operator_name = operator_context.require_operator_for_cloud()
    prefixes = {"translation": "run", "qa": "qa", "model_fix": "model-fix"}
    job_id = f"{prefixes[job_kind]}:{run_id}"
    lane = lane_for_run(run, job_kind)
    queued = job_queue.enqueue_job(
        job_id=job_id,
        lane=lane,
        job_kind=job_kind,
        project_id=run["project_id"],
        target_id=run_id,
        payload=payload,
        operator_name=operator_name,
        autostart=False,
        staged=True,
    )
    if queued.get("stage_owned"):
        metadata_patch: dict[str, Any] = {"queued_at": queued["queued_at"]}
        if job_kind == "model_fix":
            metadata_patch.update(
                {
                    "model_fix_status": "queued",
                    "model_fix_max_issues": payload.get("max_issues"),
                    "model_fix_rerun_qa": payload.get("rerun_qa"),
                }
            )
        try:
            db.merge_run_metadata(run_id, metadata_patch)
            db.update_run(run_id, status="queued")
            db.add_event(run_id, operator_context.prefixed_message(f"{job_kind} background job queued"))
        except Exception:
            job_queue.abandon_staged_job(queued["job_id"])
            raise
        job_queue.activate_job(queued["job_id"])
    return db.get_run(run_id)


def _run_as_submitted_operator(record: dict[str, Any], callback: Any) -> None:
    previous = operator_context.current_operator()
    operator_context.set_current_operator(record.get("operator_name") or "")
    try:
        callback()
    finally:
        operator_context.set_current_operator(previous)


def _translation_handler(record: dict[str, Any], cancel_event: threading.Event) -> None:
    def execute() -> None:
        from . import workflow

        try:
            request = TranslateRequest.model_validate(record.get("payload") or {})
            workflow.run_translate_sync(record["target_id"], request, cancel_event=cancel_event)
        except Exception as exc:
            current = db.get_run(record["target_id"])
            if current.get("status") not in RUN_TERMINAL_STATUSES:
                db.merge_run_metadata(record["target_id"], {"error": workflow.user_facing_error(exc)})
                db.update_run(record["target_id"], status="failed")
            raise

    _run_as_submitted_operator(record, execute)


def _qa_handler(record: dict[str, Any], cancel_event: threading.Event) -> None:
    def execute() -> None:
        from . import workflow

        try:
            workflow.run_qa_sync(record["target_id"], settings=load_settings(), cancel_event=cancel_event)
        except workflow.QaCanceled:
            db.merge_run_metadata(record["target_id"], {"canceled_at": db.now_iso()})
            db.update_run(record["target_id"], status="canceled")
            db.add_event(record["target_id"], "QA canceled before completion; no partial results were written")
        except Exception as exc:
            friendly = workflow.user_facing_error(exc)
            db.merge_run_metadata(record["target_id"], {"error": friendly})
            db.update_run(record["target_id"], status="failed")
            db.add_event(record["target_id"], f"qa failed: {friendly}", level="error")
            raise

    _run_as_submitted_operator(record, execute)


def _model_fix_handler(record: dict[str, Any], cancel_event: threading.Event) -> None:
    def execute() -> None:
        from . import workflow

        run_id = record["target_id"]
        try:
            request = ModelFixRequest.model_validate(record.get("payload") or {})
            settings = load_settings()
            db.merge_run_metadata(
                run_id,
                {
                    "model_fix_status": "running",
                    "model_fix_started_at": db.now_iso(),
                    "model_fix_max_issues": request.max_issues,
                    "model_fix_rerun_qa": request.rerun_qa,
                },
            )
            db.update_run(run_id, status="running")
            result = workflow.apply_model_fixes(run_id, request, settings=settings)
            qa_result = result.get("qa_result") or {}
            qa_run = qa_result.get("run") or {}
            terminal_status = str(qa_run.get("status") or "needs_input")
            if cancel_event.is_set():
                terminal_status = "canceled"
            db.merge_run_metadata(
                run_id,
                {
                    "model_fix_status": terminal_status,
                    "model_fix_finished_at": db.now_iso(),
                    "model_fix_count": len(result.get("model_fixes") or []),
                    "model_fix_result_run_id": qa_run.get("id") or "",
                    "model_fix_fixed_artifact_id": (result.get("fixed_artifact") or {}).get("id") or "",
                    "model_fix_quality_summary": qa_result.get("quality_summary") or {},
                },
            )
            db.update_run(run_id, status=terminal_status)
            db.add_event(run_id, f"model fixes finished: status={terminal_status}, fixes={len(result.get('model_fixes') or [])}")
        except Exception as exc:
            friendly = workflow.user_facing_error(exc)
            db.merge_run_metadata(
                run_id,
                {
                    "model_fix_status": "failed",
                    "model_fix_finished_at": db.now_iso(),
                    "model_fix_error": friendly,
                    "error": friendly,
                },
            )
            db.update_run(run_id, status="failed")
            db.add_event(run_id, f"model fixes failed: {friendly}", level="error")
            raise

    _run_as_submitted_operator(record, execute)


def _announcement_handler(record: dict[str, Any], cancel_event: threading.Event) -> None:
    def execute() -> None:
        from . import workflow

        try:
            request = AnnouncementTaskTranslateRequest.model_validate(record.get("payload") or {})
            workflow.translate_announcement_task(record["target_id"], request, cancel_event=cancel_event)
        except Exception as exc:
            if cancel_event.is_set():
                current = db.get_announcement_task(record["target_id"])
                if (current.get("metadata") or {}).get("canceled_at"):
                    workflow.cancel_announcement_task(record["target_id"])
                elif current.get("status") != "canceled":
                    workflow.cancel_announcement_translation_task(record["target_id"])
                return
            current = db.get_announcement_task(record["target_id"])
            if current.get("status") not in {"translated", "canceled", "needs_input", "awaiting_ai_response", "prepared"}:
                db.merge_announcement_task_metadata(record["target_id"], {"error": workflow.user_facing_error(exc)})
                db.update_announcement_task(record["target_id"], status="failed", current_step=7)
            raise
        else:
            current = db.get_announcement_task(record["target_id"])
            if cancel_event.is_set():
                if (current.get("metadata") or {}).get("canceled_at"):
                    workflow.cancel_announcement_task(record["target_id"])
                elif current.get("status") not in {"translated", "prepared", "canceled"}:
                    workflow.cancel_announcement_translation_task(record["target_id"])

    _run_as_submitted_operator(record, execute)


def _multilingual_translation_handler(record: dict[str, Any], cancel_event: threading.Event) -> None:
    def execute() -> None:
        from .workflow import multilingual

        try:
            multilingual.execute_multilingual_translation_job(record, cancel_event)
        except Exception as exc:
            _fail_multilingual_children(record, exc)
            raise

    _run_as_submitted_operator(record, execute)


def _multilingual_qa_handler(record: dict[str, Any], cancel_event: threading.Event) -> None:
    def execute() -> None:
        from .workflow import multilingual

        try:
            multilingual.execute_multilingual_qa_job(record, cancel_event)
        except Exception as exc:
            _fail_multilingual_children(record, exc)
            raise

    _run_as_submitted_operator(record, execute)


def _fail_multilingual_children(record: dict[str, Any], exc: Exception) -> None:
    from . import workflow

    friendly = workflow.user_facing_error(exc)
    for run_id in _record_run_ids(record):
        try:
            run = db.get_run(run_id)
        except KeyError:
            continue
        if run.get("status") in RUN_TERMINAL_STATUSES:
            continue
        db.merge_run_metadata(run_id, {"error": friendly})
        db.update_run(run_id, status="failed")
        db.add_event(run_id, f"multilingual job failed: {friendly}", level="error")


def reconcile_startup(interrupted_jobs: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "interrupted_runs": 0,
        "interrupted_announcements": 0,
        "terminal_queue_rows_cleaned": 0,
        "orphaned_queued_runs": 0,
        "legacy_running_runs": 0,
    }
    handled_run_ids: set[str] = set()
    for record in interrupted_jobs:
        kind = str(record.get("job_kind") or "")
        if kind == "announcement":
            task = db.get_announcement_task(record["target_id"])
            if _announcement_is_terminal(task):
                job_queue.set_job_status(record["job_id"], "completed")
                continue
            _interrupt_announcement(task)
            summary["interrupted_announcements"] += 1
            continue
        run_ids = _record_run_ids(record)
        for run_id in run_ids:
            run = db.get_run(run_id)
            handled_run_ids.add(run_id)
            if run.get("status") in RUN_TERMINAL_STATUSES:
                continue
            _interrupt_run(run_id)
            summary["interrupted_runs"] += 1

    for record in job_queue.list_jobs(status="queued"):
        kind = str(record.get("job_kind") or "")
        if kind == "announcement":
            task = db.get_announcement_task(record["target_id"])
            if _announcement_is_terminal(task):
                job_queue.set_job_status(record["job_id"], "completed")
                summary["terminal_queue_rows_cleaned"] += 1
            elif task.get("status") != "queued":
                db.merge_announcement_task_metadata(task["id"], {"queued_at": record["queued_at"]})
                db.update_announcement_task(task["id"], status="queued", current_step=7)
            continue
        run_ids = _record_run_ids(record)
        terminal = bool(run_ids)
        for run_id in run_ids:
            run = db.get_run(run_id)
            handled_run_ids.add(run_id)
            if run.get("status") not in RUN_TERMINAL_STATUSES:
                terminal = False
                if run.get("status") != "queued":
                    db.merge_run_metadata(run_id, {"queued_at": record["queued_at"]})
                    db.update_run(run_id, status="queued")
        if terminal:
            job_queue.set_job_status(record["job_id"], "completed")
            summary["terminal_queue_rows_cleaned"] += 1

    active_run_ids: set[str] = set()
    for record in job_queue.list_active_jobs():
        active_run_ids.update(_record_run_ids(record))
    legacy_job_ids = {
        str(row.get("job_id") or "")
        for row in db.list_job_leases()
        if row.get("status") in {"running", "cancel_requested"}
    }
    for run in db.list_runs():
        run_id = str(run["id"])
        if run.get("status") == "queued" and run_id not in active_run_ids:
            if _legacy_job_matches(run_id, legacy_job_ids):
                _interrupt_run(run_id)
                summary["legacy_running_runs"] += 1
            else:
                db.merge_run_metadata(
                    run_id,
                    {"reason": "orphaned_legacy_queue_cleanup", "canceled_at": db.now_iso()},
                )
                db.update_run(run_id, status="canceled")
                db.add_event(run_id, "已清理服务升级前遗留的孤立排队任务", level="warning")
                summary["orphaned_queued_runs"] += 1
        elif run.get("status") == "running" and run_id not in handled_run_ids:
            _interrupt_run(run_id)
            summary["legacy_running_runs"] += 1
    db.mark_running_job_leases_interrupted()
    return summary


def _record_run_ids(record: dict[str, Any]) -> list[str]:
    if str(record.get("job_kind") or "").startswith("multilingual_"):
        return [str(item) for item in (record.get("payload") or {}).get("child_run_ids") or [] if str(item)]
    target_id = str(record.get("target_id") or "")
    return [target_id] if target_id else []


def _interrupt_run(run_id: str) -> None:
    db.merge_run_metadata(
        run_id,
        {"reason": "service_restart_continue", "interrupted_at": db.now_iso()},
    )
    db.update_run(run_id, status="needs_input")
    db.add_event(run_id, "服务已重启，请继续当前任务", level="warning")


def _announcement_is_terminal(task: dict[str, Any]) -> bool:
    return task.get("status") in {"translated", "delivered", "canceled", "failed", "needs_input"}


def _interrupt_announcement(task: dict[str, Any]) -> None:
    db.merge_announcement_task_metadata(
        task["id"],
        {"reason": "service_restart_continue", "interrupted_at": db.now_iso()},
    )
    db.update_announcement_task(task["id"], status="needs_input", current_step=7)
    for item in task.get("languages") or []:
        if item.get("status") in {"queued", "running"}:
            metadata = {**(item.get("metadata") or {}), "reason": "service_restart_continue"}
            db.upsert_announcement_task_language(
                task["id"],
                task["project_id"],
                str(item["language"]),
                status="prepared",
                current_step=7,
                metadata=metadata,
            )


def _legacy_job_matches(run_id: str, job_ids: set[str]) -> bool:
    return any(job_id == run_id or job_id.endswith(f":{run_id}") for job_id in job_ids)
