from __future__ import annotations

import time
import threading
from pathlib import Path
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

import app.background_jobs as background_jobs
import app.db as db
import app.job_queue as job_queue
import app.workflow as workflow
from app.config import DEFAULT_SETTINGS, save_settings
from app.main import app


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "condition was not met before timeout"


@pytest.fixture(autouse=True)
def isolated_background_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    job_queue.shutdown_dispatchers(timeout=2.0, cancel_running=True)
    job_queue.clear_handlers()
    job_queue.reset_dispatcher_state()
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "background-jobs.sqlite3")
    db.init_db()
    yield
    job_queue.shutdown_dispatchers(timeout=2.0, cancel_running=True)
    job_queue.clear_handlers()
    job_queue.reset_dispatcher_state()


def _translation_run(project_id: str, *, origin: str, language: str = "en") -> dict[str, Any]:
    return db.insert_run(
        project_id,
        "translation",
        language,
        metadata={"task_origin": origin},
    )


def test_run_create_api_returns_created_and_allows_same_kind_fifo_candidates() -> None:
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "created API runs", "type": "QA"}).json()
        first = client.post("/api/runs", json={"project_id": project["id"], "kind": "translation", "language": "en"})
        second = client.post("/api/runs", json={"project_id": project["id"], "kind": "translation", "language": "ko"})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["status"] == "created"
    assert second.json()["status"] == "created"


def test_business_state_is_not_rewritten_after_a_preceding_job_claims_the_new_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocker_release = threading.Event()
    blocker_started = threading.Event()

    def blocker(record: dict[str, Any], cancel_event: threading.Event) -> None:
        _ = record, cancel_event
        blocker_started.set()
        blocker_release.wait(2.0)

    def fake_translate(run_id: str, request: object, cancel_event: threading.Event) -> dict[str, Any]:
        _ = request, cancel_event
        db.update_run(run_id, status="running")
        db.update_run(run_id, status="passed")
        return {"run": db.get_run(run_id)}

    background_jobs.register_handlers()
    job_queue.register_handler("blocker", blocker)
    job_queue.enqueue_job(
        job_id="preceding-job",
        lane="language_table",
        job_kind="blocker",
        project_id="project-blocker",
        target_id="",
    )
    assert blocker_started.wait(2.0)
    project = db.insert_project("activation race", "QA", "")
    run = _translation_run(project["id"], origin="translation_run")
    original_enqueue = job_queue.enqueue_job

    def release_preceding_after_persist(**kwargs: Any) -> dict[str, Any]:
        row = original_enqueue(**kwargs)
        blocker_release.set()
        _wait_until(lambda: job_queue.get_job("preceding-job")["status"] == "completed")
        return row

    monkeypatch.setattr(workflow, "run_translate_sync", fake_translate)
    monkeypatch.setattr(background_jobs.job_queue, "enqueue_job", release_preceding_after_persist)

    background_jobs.start_translation(run["id"], {})
    _wait_until(lambda: job_queue.get_job(f"run:{run['id']}")["status"] == "completed")

    assert db.get_run(run["id"])["status"] == "passed"


def test_cancel_uses_the_atomic_queue_result_when_a_queued_job_is_claimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = db.insert_project("cancel claim race", "QA", "")
    run = _translation_run(project["id"], origin="translation_run")
    job_id = f"run:{run['id']}"
    job_queue.enqueue_job(
        job_id=job_id,
        lane="language_table",
        job_kind="translation",
        project_id=project["id"],
        target_id=run["id"],
        autostart=False,
    )
    db.update_run(run["id"], status="queued")
    original_get_job = job_queue.get_job
    first_read = True

    def claim_after_first_read(requested_job_id: str) -> dict[str, Any] | None:
        nonlocal first_read
        snapshot = original_get_job(requested_job_id)
        if first_read:
            first_read = False
            claimed = job_queue.claim_next_job("language_table")
            assert claimed and claimed["job_id"] == job_id
        return snapshot

    monkeypatch.setattr(background_jobs.job_queue, "get_job", claim_after_first_read)
    result = background_jobs.cancel(job_id)

    assert result is not None
    assert result["queue_job"]["status"] == "running"
    assert result["queue_job"]["cancel_requested"] is True
    assert db.get_run(run["id"])["status"] == "queued"
    assert db.get_run(run["id"])["metadata"]["cancel_requested_by"] == result["queue_job"]["canceled_by"]


def test_run_cancel_waits_for_staged_submission_and_cancels_the_activated_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = db.insert_project("run staged cancel", "QA", "")
    run = _translation_run(project["id"], origin="translation_run")
    staged = threading.Event()
    release_stage = threading.Event()
    cancel_finished = threading.Event()
    original_enqueue = job_queue.enqueue_job
    errors: list[BaseException] = []
    cancel_results: list[dict[str, Any] | None] = []

    def pause_staged_owner(**kwargs: Any) -> dict[str, Any]:
        row = original_enqueue(**kwargs)
        if row.get("stage_owned"):
            staged.set()
            release_stage.wait(2.0)
        return row

    def start() -> None:
        try:
            background_jobs.start_translation(run["id"], {})
        except BaseException as exc:
            errors.append(exc)

    def cancel() -> None:
        try:
            cancel_results.append(background_jobs.cancel(f"run:{run['id']}"))
        except BaseException as exc:
            errors.append(exc)
        finally:
            cancel_finished.set()

    monkeypatch.setattr(background_jobs.job_queue, "enqueue_job", pause_staged_owner)
    start_thread = threading.Thread(target=start)
    cancel_thread = threading.Thread(target=cancel)
    start_thread.start()
    assert staged.wait(2.0)
    cancel_thread.start()
    assert cancel_finished.wait(0.1) is False
    release_stage.set()
    start_thread.join(2.0)
    cancel_thread.join(2.0)

    assert errors == []
    assert cancel_results[0] is not None
    assert cancel_results[0]["queue_job"]["status"] == "canceled"
    assert db.get_run(run["id"])["status"] == "canceled"


def test_task_level_announcement_cancel_waits_for_staged_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = db.insert_project("announcement staged cancel", "QA", "")
    task = db.insert_announcement_task(
        project["id"],
        {"title": "staged whole-task cancel", "selected_languages": ["en"], "status": "prepared", "current_step": 6},
    )
    staged = threading.Event()
    release_stage = threading.Event()
    cancel_finished = threading.Event()
    original_enqueue = job_queue.enqueue_job
    errors: list[BaseException] = []
    cancel_results: list[dict[str, Any]] = []

    def pause_staged_owner(**kwargs: Any) -> dict[str, Any]:
        row = original_enqueue(**kwargs)
        if row.get("stage_owned"):
            staged.set()
            release_stage.wait(2.0)
        return row

    def start() -> None:
        try:
            background_jobs.start_announcement(task["id"], {"languages": ["en"]})
        except BaseException as exc:
            errors.append(exc)

    def cancel() -> None:
        try:
            cancel_results.append(background_jobs.cancel_announcement_task(task["id"]))
        except BaseException as exc:
            errors.append(exc)
        finally:
            cancel_finished.set()

    monkeypatch.setattr(background_jobs.job_queue, "enqueue_job", pause_staged_owner)
    start_thread = threading.Thread(target=start)
    cancel_thread = threading.Thread(target=cancel)
    start_thread.start()
    assert staged.wait(2.0)
    cancel_thread.start()
    assert cancel_finished.wait(0.1) is False
    release_stage.set()
    start_thread.join(2.0)
    cancel_thread.join(2.0)

    assert errors == []
    assert cancel_results[0]["task"]["status"] == "canceled"
    assert job_queue.get_job(f"announcement:{task['id']}")["status"] == "canceled"
    assert db.get_announcement_task(task["id"])["status"] == "canceled"


def test_app_lifespan_stops_queue_dispatchers_without_canceling_running_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    original_shutdown = job_queue.shutdown_dispatchers

    def record_shutdown(*args: Any, **kwargs: Any) -> None:
        calls.append(kwargs)
        original_shutdown(*args, **kwargs)

    monkeypatch.setattr(job_queue, "shutdown_dispatchers", record_shutdown)
    with TestClient(app):
        pass

    assert calls
    assert calls[-1].get("cancel_running") is False


@pytest.mark.parametrize(
    ("job_kind", "payload"),
    [
        ("translation", {"batch_size": {"invalid": True}}),
        ("model_fix", {"max_issues": {"invalid": True}}),
    ],
)
def test_invalid_persisted_run_payload_marks_business_run_failed(job_kind: str, payload: dict[str, Any]) -> None:
    background_jobs.register_handlers()
    project = db.insert_project(f"invalid {job_kind} payload", "QA", "")
    run = _translation_run(project["id"], origin="translation_run")
    db.update_run(run["id"], status="queued")
    prefixes = {"translation": "run", "model_fix": "model-fix"}
    job_id = f"{prefixes[job_kind]}:{run['id']}"
    job_queue.enqueue_job(
        job_id=job_id,
        lane="language_table",
        job_kind=job_kind,
        project_id=project["id"],
        target_id=run["id"],
        payload=payload,
    )

    _wait_until(lambda: job_queue.get_job(job_id)["status"] == "failed")

    stored = db.get_run(run["id"])
    assert stored["status"] == "failed"
    assert stored["metadata"]["error"]


def test_invalid_persisted_announcement_payload_marks_business_task_failed() -> None:
    background_jobs.register_handlers()
    project = db.insert_project("invalid announcement payload", "QA", "")
    task = db.insert_announcement_task(
        project["id"],
        {"title": "invalid payload", "selected_languages": ["en"], "status": "queued", "current_step": 7},
    )
    job_id = f"announcement:{task['id']}"
    job_queue.enqueue_job(
        job_id=job_id,
        lane="quick_announcement",
        job_kind="announcement",
        project_id=project["id"],
        target_id=task["id"],
        payload={"languages": {"invalid": True}},
    )

    _wait_until(lambda: job_queue.get_job(job_id)["status"] == "failed")

    stored = db.get_announcement_task(task["id"])
    assert stored["status"] == "failed"
    assert stored["metadata"]["error"]


def test_invalid_persisted_multilingual_payload_marks_children_failed() -> None:
    background_jobs.register_handlers()
    project = db.insert_project("invalid multilingual payload", "QA", "")
    child = _translation_run(project["id"], origin="translation_run")
    db.update_run(child["id"], status="queued")
    job_id = f"multilingual:translate:{project['id']}:source"
    job_queue.enqueue_job(
        job_id=job_id,
        lane="language_table",
        job_kind="multilingual_translate",
        project_id=project["id"],
        target_id="source",
        payload={"request": {"languages": ["en"]}, "child_run_ids": ["missing-child", child["id"]]},
    )

    _wait_until(lambda: job_queue.get_job(job_id)["status"] == "failed")

    stored = db.get_run(child["id"])
    assert stored["status"] == "failed"
    assert stored["metadata"]["error"]


def test_same_project_formal_and_quick_runs_execute_on_two_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    started: set[str] = set()
    lock = threading.Lock()

    def fake_translate(run_id: str, request: object, cancel_event: threading.Event) -> dict[str, Any]:
        _ = request
        db.update_run(run_id, status="running")
        with lock:
            started.add(run_id)
        while not release.wait(0.01):
            if cancel_event.is_set():
                db.update_run(run_id, status="canceled")
                return {"run": db.get_run(run_id)}
        db.update_run(run_id, status="passed")
        return {"run": db.get_run(run_id)}

    monkeypatch.setattr(workflow, "run_translate_sync", fake_translate)
    project = db.insert_project("dual lane project", "QA", "")
    formal = _translation_run(project["id"], origin="translation_run", language="en")
    quick = _translation_run(project["id"], origin="quick_task", language="ko")

    with TestClient(app) as client:
        first = client.post(
            f"/api/runs/{formal['id']}/translate/start",
            json={"batch_size": 2},
            headers={"X-Operator": "Alice"},
        )
        second = client.post(
            f"/api/runs/{quick['id']}/translate/start",
            json={"batch_size": 2},
            headers={"X-Operator": "Bob"},
        )
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        _wait_until(lambda: started == {formal["id"], quick["id"]})

        active = client.get("/api/system/active-jobs").json()
        assert {entry["lane"] for entry in active} == {"language_table", "quick_announcement"}
        assert {entry["operator_name"] for entry in active} == {"Alice", "Bob"}

        release.set()
        _wait_until(lambda: all(job["status"] == "completed" for job in job_queue.list_jobs()))


def test_same_lane_accepts_fifo_and_queue_api_reports_position_and_ahead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    releases: dict[str, threading.Event] = {}
    started: list[str] = []

    def fake_translate(run_id: str, request: object, cancel_event: threading.Event) -> dict[str, Any]:
        _ = request, cancel_event
        db.update_run(run_id, status="running")
        started.append(run_id)
        releases.setdefault(run_id, threading.Event()).wait(2.0)
        db.update_run(run_id, status="passed")
        return {"run": db.get_run(run_id)}

    monkeypatch.setattr(workflow, "run_translate_sync", fake_translate)
    first_project = db.insert_project("fifo first", "QA", "")
    second_project = db.insert_project("fifo second", "QA", "")
    first_run = _translation_run(first_project["id"], origin="translation_run")
    second_run = _translation_run(second_project["id"], origin="translation_run")
    releases[first_run["id"]] = threading.Event()
    releases[second_run["id"]] = threading.Event()

    with TestClient(app) as client:
        first = client.post(
            f"/api/runs/{first_run['id']}/translate/start",
            json={},
            headers={"X-Operator": "Alice"},
        )
        assert first.status_code == 200, first.text
        _wait_until(lambda: started == [first_run["id"]])

        second = client.post(
            f"/api/runs/{second_run['id']}/translate/start",
            json={},
            headers={"X-Operator": "Bob"},
        )
        assert second.status_code == 200, second.text
        assert db.get_run(second_run["id"])["status"] == "queued"

        payload = client.get("/api/system/job-queues").json()
        assert [lane["lane"] for lane in payload["lanes"]] == ["language_table", "quick_announcement"]
        language_lane = payload["lanes"][0]
        assert language_lane["running"]["job_id"] == f"run:{first_run['id']}"
        assert len(language_lane["queued"]) == 1
        queued = language_lane["queued"][0]
        assert queued["job_id"] == f"run:{second_run['id']}"
        assert queued["project_id"] == second_project["id"]
        assert queued["project_name"] == "fifo second"
        assert queued["operator_name"] == "Bob"
        assert queued["status"] == "queued"
        assert queued["position"] == 1
        assert queued["ahead"] == 1

        releases[first_run["id"]].set()
        _wait_until(lambda: started == [first_run["id"], second_run["id"]])
        releases[second_run["id"]].set()
        _wait_until(lambda: all(job["status"] == "completed" for job in job_queue.list_jobs()))


def test_qa_model_fix_and_announcement_routes_use_persistent_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_qa = threading.Event()
    release_announcement = threading.Event()

    def fake_qa(run_id: str, *, settings: dict[str, Any], cancel_event: threading.Event) -> dict[str, Any]:
        _ = settings, cancel_event
        db.update_run(run_id, status="running")
        release_qa.wait(2.0)
        db.update_run(run_id, status="passed")
        return {"run": db.get_run(run_id)}

    def fake_model_fix(run_id: str, payload: object, *, settings: dict[str, Any]) -> dict[str, Any]:
        _ = payload, settings
        return {"model_fixes": [], "qa_result": {"run": {"id": run_id, "status": "passed"}}}

    def fake_announcement(task_id: str, payload: object, *, cancel_event: threading.Event) -> dict[str, Any]:
        _ = payload, cancel_event
        db.update_announcement_task(task_id, status="running", current_step=7)
        release_announcement.wait(2.0)
        db.update_announcement_task(task_id, status="translated", current_step=8)
        return {"task": db.get_announcement_task(task_id)}

    monkeypatch.setattr(workflow, "run_qa_sync", fake_qa)
    monkeypatch.setattr(workflow, "apply_model_fixes", fake_model_fix)
    monkeypatch.setattr(workflow, "translate_announcement_task", fake_announcement)
    save_settings({**DEFAULT_SETTINGS, "provider": "test-fake", "model": "route-runtime"})
    project = db.insert_project("remaining route kinds", "QA", "")
    qa_run = db.insert_run(project["id"], "qa", "en", metadata={"task_origin": "direct_import"})
    fix_run = db.insert_run(project["id"], "qa", "en", metadata={"task_origin": "direct_import"})
    db.update_run(fix_run["id"], status="failed")
    task = db.insert_announcement_task(
        project["id"],
        {"title": "queued announcement", "selected_languages": ["en"], "status": "prepared", "current_step": 6},
    )

    with TestClient(app) as client:
        qa_response = client.post(
            f"/api/runs/{qa_run['id']}/qa/start",
            headers={"X-Operator": "Alice"},
        )
        assert qa_response.status_code == 200, qa_response.text
        _wait_until(lambda: db.get_run(qa_run["id"])["status"] == "running")

        fix_response = client.post(
            f"/api/runs/{fix_run['id']}/model-fixes/start",
            json={"max_issues": 3, "rerun_qa": False},
            headers={"X-Operator": "Bob"},
        )
        announcement_response = client.post(
            f"/api/announcement-tasks/{task['id']}/translate/start",
            json={"languages": ["en"], "batch_size": 2},
            headers={"X-Operator": "Carol"},
        )
        assert fix_response.status_code == 200, fix_response.text
        assert announcement_response.status_code == 200, announcement_response.text

        assert job_queue.get_job(f"qa:{qa_run['id']}")["status"] == "running"
        assert job_queue.get_job(f"model-fix:{fix_run['id']}")["status"] == "queued"
        assert job_queue.get_job(f"announcement:{task['id']}")["status"] == "running"
        assert db.get_run(fix_run["id"])["status"] == "queued"

        release_qa.set()
        release_announcement.set()
        _wait_until(lambda: all(row["status"] == "completed" for row in job_queue.list_jobs()))


def test_generic_cancel_audits_queued_job_and_cancels_business_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    started = threading.Event()

    def fake_translate(run_id: str, request: object, cancel_event: threading.Event) -> dict[str, Any]:
        _ = request, cancel_event
        db.update_run(run_id, status="running")
        started.set()
        release.wait(2.0)
        db.update_run(run_id, status="passed")
        return {"run": db.get_run(run_id)}

    monkeypatch.setattr(workflow, "run_translate_sync", fake_translate)
    project = db.insert_project("queued cancellation", "QA", "")
    first = _translation_run(project["id"], origin="translation_run", language="en")
    second = _translation_run(project["id"], origin="translation_run", language="ko")

    with TestClient(app) as client:
        assert client.post(f"/api/runs/{first['id']}/translate/start", json={}).status_code == 200
        assert started.wait(2.0)
        assert client.post(f"/api/runs/{second['id']}/translate/start", json={}).status_code == 200
        job_id = f"run:{second['id']}"

        response = client.post(
            f"/api/system/job-queues/{job_id}/cancel",
            headers={"X-Operator": "Bob"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["queue_job"]["status"] == "canceled"
        assert payload["queue_job"]["operator_name"] == ""
        assert payload["queue_job"]["canceled_by"] == "Bob"
        assert payload["queue_job"]["cancel_requested_at"]
        assert payload["queue_job"]["canceled_at"] == payload["queue_job"]["cancel_requested_at"]
        assert payload["business_target"]["status"] == "canceled"
        assert payload["business_target"]["metadata"]["canceled_by"] == "Bob"
        assert any("Bob" in event["message"] for event in db.list_events(second["id"]))

        release.set()
        _wait_until(lambda: job_queue.get_job(f"run:{first['id']}")["status"] == "completed")


def test_generic_cancel_requests_running_job_and_handler_stops_at_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    saw_cancel = threading.Event()

    def fake_translate(run_id: str, request: object, cancel_event: threading.Event) -> dict[str, Any]:
        _ = request
        db.update_run(run_id, status="running")
        entered.set()
        assert cancel_event.wait(2.0)
        saw_cancel.set()
        db.update_run(run_id, status="canceled")
        return {"run": db.get_run(run_id)}

    monkeypatch.setattr(workflow, "run_translate_sync", fake_translate)
    project = db.insert_project("running cancellation", "QA", "")
    run = _translation_run(project["id"], origin="translation_run")

    with TestClient(app) as client:
        started = client.post(
            f"/api/runs/{run['id']}/translate/start",
            json={},
            headers={"X-Operator": "Alice"},
        )
        assert started.status_code == 200, started.text
        assert entered.wait(2.0)

        response = client.post(
            f"/api/system/job-queues/run:{run['id']}/cancel",
            headers={"X-Operator": "Carol"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["queue_job"]["cancel_requested"] is True
        assert response.json()["queue_job"]["canceled_by"] == "Carol"
        assert db.get_run(run["id"])["metadata"]["cancel_requested_by"] == "Carol"
        assert any("Carol" in event["message"] for event in db.list_events(run["id"]))
        assert saw_cancel.wait(2.0)
        _wait_until(lambda: job_queue.get_job(f"run:{run['id']}")["status"] == "canceled")


def test_generic_cancel_returns_404_for_unknown_job() -> None:
    with TestClient(app) as client:
        response = client.post("/api/system/job-queues/missing-job/cancel", headers={"X-Operator": "Bob"})

    assert response.status_code == 404


def test_running_announcement_cancel_returns_task_to_prepared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()

    def fake_announcement(task_id: str, payload: object, *, cancel_event: threading.Event) -> dict[str, Any]:
        _ = payload
        db.update_announcement_task(task_id, status="running", current_step=7)
        entered.set()
        assert cancel_event.wait(2.0)
        raise RuntimeError("announcement canceled at boundary")

    monkeypatch.setattr(workflow, "translate_announcement_task", fake_announcement)
    project = db.insert_project("running announcement cancel", "QA", "")
    task = db.insert_announcement_task(
        project["id"],
        {"title": "cancel me", "selected_languages": ["en"], "status": "prepared", "current_step": 6},
    )

    with TestClient(app) as client:
        started = client.post(
            f"/api/announcement-tasks/{task['id']}/translate/start",
            json={"languages": ["en"]},
            headers={"X-Operator": "Alice"},
        )
        assert started.status_code == 200, started.text
        assert entered.wait(2.0)
        canceled = client.post(
            f"/api/announcement-tasks/{task['id']}/translate/cancel",
            headers={"X-Operator": "Bob"},
        )
        assert canceled.status_code == 200, canceled.text
        _wait_until(lambda: job_queue.get_job(f"announcement:{task['id']}")["status"] == "canceled")

    stored = db.get_announcement_task(task["id"])
    assert stored["status"] == "prepared"
    assert stored["metadata"]["canceled_by"] == "Bob"


def test_task_level_announcement_cancel_signals_running_queue_and_stays_canceled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    saw_cancel = threading.Event()

    def fake_announcement(task_id: str, payload: object, *, cancel_event: threading.Event) -> dict[str, Any]:
        _ = payload
        db.update_announcement_task(task_id, status="running", current_step=7)
        entered.set()
        assert cancel_event.wait(2.0)
        saw_cancel.set()
        raise RuntimeError("announcement task canceled")

    monkeypatch.setattr(workflow, "translate_announcement_task", fake_announcement)
    project = db.insert_project("task-level announcement cancel", "QA", "")
    task = db.insert_announcement_task(
        project["id"],
        {"title": "cancel whole task", "selected_languages": ["en"], "status": "prepared", "current_step": 6},
    )

    with TestClient(app) as client:
        started = client.post(
            f"/api/announcement-tasks/{task['id']}/translate/start",
            json={"languages": ["en"]},
            headers={"X-Operator": "Alice"},
        )
        assert started.status_code == 200, started.text
        assert entered.wait(2.0)
        canceled = client.post(
            f"/api/announcement-tasks/{task['id']}/cancel",
            headers={"X-Operator": "Bob"},
        )
        assert canceled.status_code == 200, canceled.text
        assert saw_cancel.wait(2.0)
        _wait_until(lambda: job_queue.get_job(f"announcement:{task['id']}")["status"] == "canceled")

    stored = db.get_announcement_task(task["id"])
    assert stored["status"] == "canceled"
    assert stored["metadata"]["canceled_by"] == "Bob"
    assert stored["metadata"]["cancel_requested_at"]


def test_queued_announcement_cancel_returns_task_to_prepared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    entered = threading.Event()

    def fake_translate(run_id: str, request: object, cancel_event: threading.Event) -> dict[str, Any]:
        _ = request, cancel_event
        db.update_run(run_id, status="running")
        entered.set()
        release.wait(2.0)
        db.update_run(run_id, status="passed")
        return {"run": db.get_run(run_id)}

    monkeypatch.setattr(workflow, "run_translate_sync", fake_translate)
    project = db.insert_project("queued announcement cancel", "QA", "")
    blocker = _translation_run(project["id"], origin="quick_task")
    task = db.insert_announcement_task(
        project["id"],
        {"title": "queued cancel", "selected_languages": ["en"], "status": "prepared", "current_step": 6},
    )

    with TestClient(app) as client:
        assert client.post(f"/api/runs/{blocker['id']}/translate/start", json={}).status_code == 200
        assert entered.wait(2.0)
        started = client.post(f"/api/announcement-tasks/{task['id']}/translate/start", json={"languages": ["en"]})
        assert started.status_code == 200, started.text
        assert job_queue.get_job(f"announcement:{task['id']}")["status"] == "queued"
        canceled = client.post(
            f"/api/announcement-tasks/{task['id']}/translate/cancel",
            headers={"X-Operator": "Bob"},
        )
        assert canceled.status_code == 200, canceled.text
        assert canceled.json()["task"]["status"] == "prepared"
        assert job_queue.get_job(f"announcement:{task['id']}")["status"] == "canceled"
        assert db.get_announcement_task(task["id"])["metadata"]["canceled_by"] == "Bob"
        release.set()


def test_queued_task_level_announcement_cancel_stays_canceled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    entered = threading.Event()

    def fake_translate(run_id: str, request: object, cancel_event: threading.Event) -> dict[str, Any]:
        _ = request, cancel_event
        db.update_run(run_id, status="running")
        entered.set()
        release.wait(2.0)
        db.update_run(run_id, status="passed")
        return {"run": db.get_run(run_id)}

    monkeypatch.setattr(workflow, "run_translate_sync", fake_translate)
    project = db.insert_project("queued task-level announcement cancel", "QA", "")
    blocker = _translation_run(project["id"], origin="quick_task")
    task = db.insert_announcement_task(
        project["id"],
        {"title": "queued whole-task cancel", "selected_languages": ["en"], "status": "prepared", "current_step": 6},
    )

    with TestClient(app) as client:
        assert client.post(f"/api/runs/{blocker['id']}/translate/start", json={}).status_code == 200
        assert entered.wait(2.0)
        assert client.post(f"/api/announcement-tasks/{task['id']}/translate/start", json={"languages": ["en"]}).status_code == 200
        assert job_queue.get_job(f"announcement:{task['id']}")["status"] == "queued"
        canceled = client.post(
            f"/api/announcement-tasks/{task['id']}/cancel",
            headers={"X-Operator": "Bob"},
        )
        assert canceled.status_code == 200, canceled.text
        assert canceled.json()["task"]["status"] == "canceled"
        assert job_queue.get_job(f"announcement:{task['id']}")["status"] == "canceled"
        assert db.get_announcement_task(task["id"])["status"] == "canceled"
        assert db.get_announcement_task(task["id"])["metadata"]["canceled_by"] == "Bob"
        release.set()


def test_queued_multilingual_cancel_cancels_child_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.background_jobs as background_jobs

    release = threading.Event()
    entered = threading.Event()

    def fake_translate(run_id: str, request: object, cancel_event: threading.Event) -> dict[str, Any]:
        _ = request, cancel_event
        db.update_run(run_id, status="running")
        entered.set()
        release.wait(2.0)
        db.update_run(run_id, status="passed")
        return {"run": db.get_run(run_id)}

    monkeypatch.setattr(workflow, "run_translate_sync", fake_translate)
    project = db.insert_project("queued multilingual cancel", "QA", "")
    blocker = _translation_run(project["id"], origin="translation_run")
    child = db.insert_run(
        project["id"],
        "translation",
        "ko",
        metadata={"parent_input_artifact_id": "source-artifact", "multilingual_source_artifact_id": "source-artifact"},
    )

    with TestClient(app) as client:
        assert client.post(f"/api/runs/{blocker['id']}/translate/start", json={}).status_code == 200
        assert entered.wait(2.0)
        controller = background_jobs.start_multilingual(
            "multilingual_translate",
            project["id"],
            "source-artifact",
            background_jobs.MultilingualQueueRequest(input_artifact_id="source-artifact", languages=["ko"]),
            [child["id"]],
        )
        assert controller["status"] == "queued"
        canceled = client.post(
            f"/api/system/job-queues/{controller['job_id']}/cancel",
            headers={"X-Operator": "Carol"},
        )
        assert canceled.status_code == 200, canceled.text
        target_runs = canceled.json()["business_target"]["runs"]
        assert target_runs[0]["status"] == "canceled"
        assert target_runs[0]["metadata"]["canceled_by"] == "Carol"
        release.set()
