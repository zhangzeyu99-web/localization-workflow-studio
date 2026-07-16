from __future__ import annotations

import json
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.background_jobs as background_jobs
import app.db as db
import app.job_queue as job_queue
import app.routers.qa as qa_router
import app.routers.runs as runs_router
import app.workflow as workflow
import app.workflow.delivery as delivery_workflow
import app.workflow.qa as qa_workflow
import app.workflow.qa_model_fixes as qa_model_fixes
import app.workflow.translation_orchestrator as translation_orchestrator
from app.config import DEFAULT_SETTINGS, save_settings
from app.main import app
from app.providers import TranslationItem
from app.schemas import ManualFixRequest, ModelFixRequest, TranslateRequest
from app.workflow.delivery import build_delivery_package
from app.workflow.qa import create_manual_fix_qa_run, run_qa_sync
from app.workflow.translation import run_translate_sync
from app.workflow.translation_tasks import mark_translation_task_state
from conftest import reset_data_root, wait_for_background_jobs


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    data_root = Path(os.environ.setdefault("LWS_DATA_ROOT", str(Path(tempfile.gettempdir()) / "lws-test-data")))
    reset_data_root(data_root)
    db.init_db()
    save_settings(DEFAULT_SETTINGS)
    yield
    wait_for_background_jobs()
    save_settings(DEFAULT_SETTINGS)


def _write_workbook(path: Path, *, target: str = "Start Game") -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Language"
    sheet.append(["ID", "CN", "EN"])
    sheet.append(["btn.start", "开始游戏", target])
    workbook.save(path)
    workbook.close()
    return path


def _quick_run(
    project_id: str,
    artifact_id: str,
    *,
    kind: str = "translation",
    task_id: str = "quick-task-t1",
) -> dict:
    return db.insert_run(
        project_id,
        kind,
        "en",
        metadata={
            "input_artifact_id": artifact_id,
            "task_origin": "quick_task",
            "translation_task_id": task_id,
            "task_code": "QA" if kind == "qa" else "AI",
        },
    )


def _seed_archive(project_id: str) -> None:
    db.insert_translation_entry(
        project_id,
        {
            "entry_key": "archived-1",
            "source": "开始游戏",
            "target": "Archived Start",
            "language": "en",
            "sheet": "Language",
            "row_number": 2,
            "source_type": "qa_passed",
        },
    )


def test_quick_identity_inherits_through_direct_manual_and_model_fix_qa(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = db.insert_project("Quick lineage", "quick-task", "")
    workbook_path = _write_workbook(tmp_path / "quick-lineage.xlsx", target="Forbidden Brand")
    artifact = db.add_artifact(project["id"], "quick-lineage.xlsx", workbook_path, "quick_input")
    source_run = _quick_run(project["id"], artifact["id"], kind="translation")

    with TestClient(app) as client:
        direct_response = client.post(
            "/api/runs",
            json={
                "project_id": project["id"],
                "kind": "qa",
                "language": "en",
                "input_artifact_id": artifact["id"],
                "source_run_id": source_run["id"],
            },
        )
    assert direct_response.status_code == 200, direct_response.text
    direct_run = direct_response.json()
    assert direct_run["metadata"]["task_origin"] == "quick_task"
    assert direct_run["metadata"]["translation_task_id"] == "quick-task-t1"

    fixed_artifact = db.add_artifact(project["id"], "manual-fixed.xlsx", workbook_path, "manual_fixed_workbook")
    manual_run = create_manual_fix_qa_run(
        direct_run,
        fixed_artifact,
        artifact,
        [{"sheet": "Language", "row": 2, "translation": "Start Game"}],
    )
    assert manual_run["metadata"]["task_origin"] == "quick_task"
    assert manual_run["metadata"]["translation_task_id"] == "quick-task-t1"

    db.update_run(
        direct_run["id"],
        status="failed",
        metadata={
            **direct_run["metadata"],
            "quality_summary": {"passed": False, "hard_errors": 1},
        },
    )
    monkeypatch.setattr(
        qa_model_fixes,
        "list_quality_issues",
        lambda _run_id: {
            "issues": [
                {
                    "id": "project_harness:0:Language:2:forbidden_translation",
                    "source": "project_harness",
                    "rule_source": "project_harness",
                    "severity": "hard",
                    "sheet": "Language",
                    "row": 2,
                    "check_type": "forbidden_translation",
                    "message": "forbidden wording",
                    "current_translation": "Forbidden Brand",
                }
            ]
        },
    )
    monkeypatch.setattr(
        qa_model_fixes,
        "_call_semantic_provider",
        lambda _settings, _prompt: '{"fixes":[{"issue_id":"project_harness:0:Language:2:forbidden_translation","sheet":"Language","row":2,"translation":"Start Game"}]}',
    )
    monkeypatch.setattr(
        qa_model_fixes,
        "run_qa_sync",
        lambda run_id, settings=None, cancel_event=None: {"run": db.get_run(run_id), "artifacts": [], "quality_summary": {}},
    )
    model_result = qa_model_fixes.apply_model_fixes(
        direct_run["id"],
        SimpleNamespace(max_issues=20, rerun_qa=True),
        settings={"provider": "openai", "api_key": "test-key", "model": "gpt-test"},
    )
    model_run = model_result["qa_result"]["run"]
    assert model_run["metadata"]["task_origin"] == "quick_task"
    assert model_run["metadata"]["translation_task_id"] == "quick-task-t1"


def test_quick_txt_delivery_marks_delivered_after_file_readback_without_archiving(tmp_path: Path) -> None:
    project = db.insert_project("Quick TXT delivery", "quick-task", "")
    source_path = tmp_path / "source.txt"
    source_path.write_text("Start Game\n", encoding="utf-8")
    source = db.add_artifact(project["id"], "source.txt", source_path, "quick_input")
    run = _quick_run(project["id"], source["id"])
    db.update_run(run["id"], status="passed")
    final_path = tmp_path / "translated.txt"
    final_path.write_text("Translated Start\n", encoding="utf-8")
    db.add_artifact(project["id"], "translated.txt", final_path, "final_text", run_id=run["id"], role="delivery")
    _seed_archive(project["id"])
    before = db.list_translation_entries(project["id"], language="en")

    package = build_delivery_package(project["id"], run_id=run["id"])

    assert package["archive"] is None
    assert package["deliverable"]["run_id"] == run["id"]
    assert package["deliverable"]["translation_task_id"] == "quick-task-t1"
    assert Path(package["files"][0]["path"]).read_text(encoding="utf-8") == "Translated Start\n"
    assert db.list_translation_entries(project["id"], language="en") == before
    refreshed = db.get_run(run["id"])
    assert refreshed["metadata"]["translation_task_state"] == "delivered"


def test_quick_txt_english_rejects_thai_provider_output_before_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = db.insert_project("Quick wrong-language guard", "quick-task", "")
    source_path = tmp_path / "wrong-language.txt"
    source_path.write_text("服务器维护完成后请选择所在省份。\n", encoding="utf-8")
    source = db.add_artifact(project["id"], source_path.name, source_path, "quick_input")
    run = _quick_run(
        project["id"],
        source["id"],
        task_id="quick-task-wrong-language",
    )
    save_settings({**DEFAULT_SETTINGS, "provider": "test-fake", "max_batch_attempts": 1})

    async def thai_provider(
        rows: list[dict[str, object]],
        _provider_settings: dict[str, object],
        _project_prompt: str,
    ) -> list[TranslationItem]:
        return [TranslationItem(id=row["id"], translation="จังหวัด") for row in rows]

    monkeypatch.setattr(translation_orchestrator, "translate_batch", thai_provider)

    with TestClient(app) as client:
        translate_response = client.post(
            f"/api/runs/{run['id']}/translate",
            json={"provider": "test-fake", "batch_size": 1},
        )
        delivery_response = client.post(
            f"/api/projects/{project['id']}/delivery-package?run_id={run['id']}"
        )

    refreshed = db.get_run(run["id"])
    artifacts = db.list_artifacts(run_id=run["id"])
    assert translate_response.status_code >= 400 or refreshed["status"] in {"failed", "needs_input"}
    assert refreshed["status"] in {"failed", "needs_input"}
    assert not any(artifact["kind"] == "final_text" for artifact in artifacts)
    assert delivery_response.status_code == 409
    assert refreshed["metadata"].get("translation_task_state") != "delivered"


def test_quick_txt_delivery_readback_failure_keeps_task_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = db.insert_project("Quick TXT delivery retry", "quick-task", "")
    source_path = tmp_path / "source-retry.txt"
    source_path.write_text("Start Game\n", encoding="utf-8")
    source = db.add_artifact(project["id"], source_path.name, source_path, "quick_input")
    run = _quick_run(project["id"], source["id"], task_id="quick-task-delivery-retry")
    final_path = tmp_path / "translated-retry.txt"
    final_path.write_text("Translated Start\n", encoding="utf-8")
    db.add_artifact(project["id"], final_path.name, final_path, "final_text", run_id=run["id"], role="delivery")
    db.update_run(run["id"], status="passed")
    real_copy2 = delivery_workflow.shutil.copy2

    def corrupt_copy(_source: object, destination: object) -> object:
        Path(destination).write_bytes(b"corrupt")
        return destination

    monkeypatch.setattr(delivery_workflow.shutil, "copy2", corrupt_copy)
    with pytest.raises(ValueError, match="读回不一致"):
        build_delivery_package(project["id"], run_id=run["id"])

    failed = db.get_run(run["id"])
    assert "translation_task_state" not in failed["metadata"]
    monkeypatch.setattr(delivery_workflow.shutil, "copy2", real_copy2)

    package = build_delivery_package(project["id"], run_id=run["id"])

    assert package["archive"] is None
    assert db.get_run(run["id"])["metadata"]["translation_task_state"] == "delivered"


def test_quick_workbook_delivery_does_not_archive_but_marks_delivered(tmp_path: Path) -> None:
    project = db.insert_project("Quick workbook delivery", "quick-task", "")
    source_path = _write_workbook(tmp_path / "source.xlsx", target="")
    source = db.add_artifact(project["id"], "source.xlsx", source_path, "quick_input")
    run = _quick_run(project["id"], source["id"])
    final_path = _write_workbook(tmp_path / "translated.xlsx")
    final = db.add_artifact(project["id"], "translated.xlsx", final_path, "qa_final_workbook", run_id=run["id"])
    db.update_run(
        run["id"],
        status="passed",
        metadata={**run["metadata"], "quality_summary": {"passed": True, "hard_errors": 0}, "input_artifacts": {"qa_final_workbook": final["id"]}},
    )
    _seed_archive(project["id"])
    before = db.list_translation_entries(project["id"], language="en")

    package = build_delivery_package(project["id"], run_id=run["id"])

    assert package["archive"] is None
    assert db.list_translation_entries(project["id"], language="en") == before
    assert db.get_run(run["id"])["metadata"]["translation_task_state"] == "delivered"


def test_formal_workbook_delivery_still_archives(tmp_path: Path) -> None:
    project = db.insert_project("Formal workbook delivery", "QA", "")
    source_path = _write_workbook(tmp_path / "formal-source.xlsx", target="")
    source = db.add_artifact(project["id"], "formal-source.xlsx", source_path, "language_table")
    run = db.insert_run(
        project["id"],
        "translation",
        "en",
        metadata={
            "input_artifact_id": source["id"],
            "task_origin": "translation_run",
            "translation_task_id": "formal-task-t1",
            "quality_summary": {"passed": True, "hard_errors": 0},
        },
    )
    final_path = _write_workbook(tmp_path / "formal-translated.xlsx")
    final = db.add_artifact(project["id"], "formal-translated.xlsx", final_path, "qa_final_workbook", run_id=run["id"])
    db.update_run(
        run["id"],
        status="passed",
        metadata={**run["metadata"], "input_artifacts": {"qa_final_workbook": final["id"]}},
    )

    package = build_delivery_package(project["id"], run_id=run["id"])

    assert package["archive"] is not None
    assert len(db.list_translation_entries(project["id"], language="en")) == 1


def test_quick_translation_reads_archive_reference_without_writing_archive(tmp_path: Path) -> None:
    project = db.insert_project("Quick lookup", "quick-task", "")
    source_path = tmp_path / "quick.txt"
    source_path.write_text("开始游戏\n", encoding="utf-8")
    source = db.add_artifact(project["id"], "quick.txt", source_path, "quick_input")
    _seed_archive(project["id"])
    before = db.list_translation_entries(project["id"], language="en")
    run = _quick_run(project["id"], source["id"])

    result = run_translate_sync(run["id"], TranslateRequest(provider="test-fake", batch_size=1))

    workpack = next(item for item in result["artifacts"] if item["kind"] == "translation_workpack")
    assert "Archived Start" in Path(workpack["path"]).read_text(encoding="utf-8")
    assert db.list_translation_entries(project["id"], language="en") == before
    assert "translation_archive" in result["run"]["metadata"]
    assert result["run"]["metadata"]["translation_archive"] is None


def test_quick_qa_pass_does_not_archive_while_formal_qa_still_does(tmp_path: Path) -> None:
    quick_project = db.insert_project("Quick QA archive isolation", "quick-task", "")
    quick_path = _write_workbook(tmp_path / "quick-qa.xlsx")
    quick_artifact = db.add_artifact(quick_project["id"], "quick-qa.xlsx", quick_path, "quick_input")
    _seed_archive(quick_project["id"])
    before = db.list_translation_entries(quick_project["id"], language="en")
    quick_run = _quick_run(quick_project["id"], quick_artifact["id"], kind="qa")

    quick_result = run_qa_sync(quick_run["id"])

    assert quick_result["run"]["status"] == "passed"
    assert quick_result["run"]["metadata"]["translation_archive"] is None
    assert db.list_translation_entries(quick_project["id"], language="en") == before

    formal_project = db.insert_project("Formal QA archive regression", "QA", "")
    formal_path = _write_workbook(tmp_path / "formal-qa.xlsx")
    formal_artifact = db.add_artifact(formal_project["id"], "formal-qa.xlsx", formal_path, "final_workbook")
    formal_run = db.insert_run(
        formal_project["id"],
        "qa",
        "en",
        metadata={"input_artifact_id": formal_artifact["id"], "task_origin": "direct_import", "translation_task_id": "formal-qa-t1"},
    )

    formal_result = run_qa_sync(formal_run["id"])

    assert formal_result["run"]["metadata"]["translation_archive"] is not None
    assert len(db.list_translation_entries(formal_project["id"], language="en")) == 1


def test_quick_manual_fix_qa_rerun_does_not_archive(tmp_path: Path) -> None:
    project = db.insert_project("Quick manual fix archive isolation", "quick-task", "")
    path = _write_workbook(tmp_path / "quick-manual-fix.xlsx", target="Needs Fix")
    artifact = db.add_artifact(project["id"], path.name, path, "quick_input")
    _seed_archive(project["id"])
    before = db.list_translation_entries(project["id"], language="en")
    run = _quick_run(project["id"], artifact["id"], kind="qa", task_id="quick-task-manual-fix-archive")

    result = qa_workflow.apply_manual_fixes(
        run["id"],
        ManualFixRequest(
            fixes=[{"sheet": "Language", "row": 2, "translation": "Start Game"}],
            rerun_qa=True,
        ),
    )

    qa_result = result["qa_result"]
    assert qa_result["run"]["metadata"]["task_origin"] == "quick_task"
    assert qa_result["run"]["metadata"]["translation_task_id"] == "quick-task-manual-fix-archive"
    assert qa_result["run"]["metadata"]["translation_archive"] is None
    assert db.list_translation_entries(project["id"], language="en") == before


def test_quick_model_fix_qa_rerun_does_not_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = db.insert_project("Quick model fix archive isolation", "quick-task", "")
    path = _write_workbook(tmp_path / "quick-model-fix.xlsx", target="Forbidden Brand")
    artifact = db.add_artifact(project["id"], path.name, path, "quick_input")
    _seed_archive(project["id"])
    before = db.list_translation_entries(project["id"], language="en")
    run = _quick_run(project["id"], artifact["id"], kind="qa", task_id="quick-task-model-fix-archive")
    monkeypatch.setattr(
        qa_model_fixes,
        "list_quality_issues",
        lambda _run_id: {
            "issues": [
                {
                    "id": "project_harness:0:Language:2:forbidden_translation",
                    "source": "project_harness",
                    "rule_source": "project_harness",
                    "severity": "hard",
                    "sheet": "Language",
                    "row": 2,
                    "check_type": "forbidden_translation",
                    "message": "forbidden wording",
                    "current_translation": "Forbidden Brand",
                }
            ]
        },
    )
    monkeypatch.setattr(
        qa_model_fixes,
        "_call_semantic_provider",
        lambda _settings, _prompt: '{"fixes":[{"issue_id":"project_harness:0:Language:2:forbidden_translation","sheet":"Language","row":2,"translation":"Start Game"}]}',
    )

    result = qa_model_fixes.apply_model_fixes(
        run["id"],
        ModelFixRequest(max_issues=1, rerun_qa=True),
        settings={"provider": "openai", "api_key": "test-key", "model": "gpt-test"},
    )

    qa_result = result["qa_result"]
    assert qa_result["run"]["metadata"]["task_origin"] == "quick_task"
    assert qa_result["run"]["metadata"]["translation_task_id"] == "quick-task-model-fix-archive"
    assert qa_result["run"]["metadata"]["translation_archive"] is None
    assert db.list_translation_entries(project["id"], language="en") == before


@pytest.mark.parametrize(
    ("kind", "endpoint", "job_prefix"),
    [
        ("translation", "translate", "run"),
        ("qa", "qa", "qa"),
    ],
)
def test_quick_start_queues_behind_preexisting_lane_job(
    tmp_path: Path,
    kind: str,
    endpoint: str,
    job_prefix: str,
) -> None:
    path = _write_workbook(tmp_path / f"{kind}-preexisting.xlsx")

    with TestClient(app) as client:
        project = db.insert_project(f"Quick {kind} persistent queue", "quick-task", "")
        artifact = db.add_artifact(project["id"], path.name, path, "quick_input")
        run = _quick_run(project["id"], artifact["id"], kind=kind, task_id=f"quick-task-{kind}-preexisting")
        existing = job_queue.enqueue_job(
            job_id="announcement:preexisting",
            lane="quick_announcement",
            job_kind="announcement",
            project_id=project["id"],
            target_id="preexisting",
            autostart=False,
        )
        assert job_queue.claim_next_job("quick_announcement")["job_id"] == existing["job_id"]
        response = client.post(
            f"/api/runs/{run['id']}/{endpoint}/start",
            json={"provider": "test-fake"} if kind == "translation" else None,
        )

    assert response.status_code == 200, response.text
    refreshed = db.get_run(run["id"])
    assert refreshed["status"] == "queued"
    assert "translation_task_state" not in refreshed["metadata"]
    queued = job_queue.get_job(f"{job_prefix}:{run['id']}")
    assert queued is not None
    assert queued["lane"] == "quick_announcement"
    assert queued["status"] == "queued"


@pytest.mark.parametrize(
    "kind",
    [
        "translation",
        "qa",
    ],
)
def test_quick_queue_persistence_failure_leaves_run_retryable_without_ghost(
    tmp_path: Path,
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_workbook(tmp_path / f"{kind}-queue-write.xlsx")
    monkeypatch.setattr(
        background_jobs.job_queue,
        "enqueue_job",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("queue write failed")),
    )

    project = db.insert_project(f"Quick {kind} queue write failure", "quick-task", "")
    artifact = db.add_artifact(project["id"], path.name, path, "quick_input")
    run = _quick_run(project["id"], artifact["id"], kind=kind, task_id=f"quick-task-{kind}-queue-write")
    job_prefix = "run" if kind == "translation" else "qa"

    with pytest.raises(RuntimeError, match="queue write failed"):
        if kind == "translation":
            runs_router._start_translation_background(run["id"], TranslateRequest(provider="test-fake"))
        else:
            qa_router._start_background_qa(run["id"])

    refreshed = db.get_run(run["id"])
    assert refreshed["status"] == "created"
    assert "translation_task_state" not in refreshed["metadata"]
    assert job_queue.get_job(f"{job_prefix}:{run['id']}") is None


def test_quick_and_formal_runs_use_independent_persistent_lanes_without_capacity_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(job_queue, "dispatch_lane", lambda _lane: False)
    quick_project = db.insert_project("Quick persistent lane", "quick-task", "")
    quick_path = _write_workbook(tmp_path / "quick-lane.xlsx")
    quick_artifact = db.add_artifact(quick_project["id"], quick_path.name, quick_path, "quick_input")
    quick_run = _quick_run(
        quick_project["id"],
        quick_artifact["id"],
        task_id="quick-task-persistent-lane",
    )
    formal_project = db.insert_project("Formal persistent lane", "QA", "")
    formal_path = _write_workbook(tmp_path / "formal-lane.xlsx")
    formal_artifact = db.add_artifact(formal_project["id"], formal_path.name, formal_path, "language_table")
    formal_run = db.insert_run(
        formal_project["id"],
        "translation",
        "en",
        metadata={
            "input_artifact_id": formal_artifact["id"],
            "task_origin": "translation_run",
            "translation_task_id": "formal-task-persistent-lane",
        },
    )

    quick_result = runs_router._start_translation_background(
        quick_run["id"],
        TranslateRequest(provider="test-fake"),
    )
    formal_result = runs_router._start_translation_background(
        formal_run["id"],
        TranslateRequest(provider="test-fake"),
    )

    assert quick_result["status"] == "queued"
    assert formal_result["status"] == "queued"
    assert job_queue.get_job(f"run:{quick_run['id']}")["lane"] == "quick_announcement"
    assert job_queue.get_job(f"run:{formal_run['id']}")["lane"] == "language_table"
    assert "translation_task_state" not in db.get_run(quick_run["id"])["metadata"]
    assert "translation_task_state" not in db.get_run(formal_run["id"])["metadata"]


@pytest.mark.parametrize(
    ("kind", "endpoint", "start_method", "job_prefix"),
    [
        ("translation", "translate", "start_translation", "run"),
        ("qa", "qa", "start_qa", "qa"),
    ],
)
def test_terminal_quick_run_is_rejected_before_background_scheduling(
    tmp_path: Path,
    kind: str,
    endpoint: str,
    start_method: str,
    job_prefix: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = db.insert_project(f"Terminal quick {kind}", "quick-task", "")
    path = _write_workbook(tmp_path / f"terminal-{kind}.xlsx")
    artifact = db.add_artifact(project["id"], path.name, path, "quick_input")
    run = _quick_run(project["id"], artifact["id"], kind=kind, task_id=f"quick-task-terminal-{kind}")
    mark_translation_task_state(project["id"], f"quick-task-terminal-{kind}", "canceled")
    scheduled: list[str] = []
    monkeypatch.setattr(
        background_jobs,
        start_method,
        lambda run_id, *_args: scheduled.append(run_id) or db.get_run(run_id),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/runs/{run['id']}/{endpoint}/start",
            json={"provider": "test-fake"} if kind == "translation" else None,
        )

    assert response.status_code == 409, response.text
    assert scheduled == []
    assert job_queue.get_job(f"{job_prefix}:{run['id']}") is None
    refreshed = db.get_run(run["id"])
    assert refreshed["status"] == "canceled"
    assert refreshed["metadata"]["translation_task_state"] == "canceled"


def test_terminal_commit_during_persistent_queue_staging_prevents_translation_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = db.insert_project("Quick scheduler race", "quick-task", "")
    path = _write_workbook(tmp_path / "scheduler-race.xlsx")
    artifact = db.add_artifact(project["id"], path.name, path, "quick_input")
    run = _quick_run(project["id"], artifact["id"], task_id="quick-task-scheduler-race")
    staged = threading.Event()
    terminal_committed = threading.Event()
    activated: list[str] = []
    real_enqueue = job_queue.enqueue_job

    def controlled_enqueue(**kwargs: object) -> dict:
        queued = real_enqueue(**kwargs)
        assert queued["status"] == job_queue.STAGING_STATUS
        staged.set()
        assert terminal_committed.wait(timeout=5)
        return queued

    monkeypatch.setattr(background_jobs.job_queue, "enqueue_job", controlled_enqueue)
    monkeypatch.setattr(
        background_jobs.job_queue,
        "activate_job",
        lambda job_id, **_kwargs: activated.append(job_id) or job_queue.get_job(job_id),
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            runs_router._start_translation_background,
            run["id"],
            TranslateRequest(provider="test-fake"),
        )
        assert staged.wait(timeout=5)
        mark_translation_task_state(project["id"], "quick-task-scheduler-race", "canceled")
        terminal_committed.set()
        with pytest.raises(db.TranslationTaskClosedError):
            future.result(timeout=5)

    assert activated == []
    queued = job_queue.get_job(f"run:{run['id']}")
    assert queued is None or queued["status"] not in {job_queue.STAGING_STATUS, "queued", "running"}
    refreshed = db.get_run(run["id"])
    assert refreshed["status"] == "canceled"
    assert refreshed["metadata"]["translation_task_state"] == "canceled"


@pytest.mark.parametrize("mode", ["qa", "model_fix"])
def test_qa_and_model_fix_terminal_commit_during_staging_prevents_activation(
    tmp_path: Path,
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = db.insert_project(f"Quick {mode} scheduler race", "quick-task", "")
    path = _write_workbook(tmp_path / f"{mode}-scheduler-race.xlsx")
    artifact = db.add_artifact(project["id"], path.name, path, "quick_input")
    task_id = f"quick-task-{mode}-scheduler-race"
    run = _quick_run(project["id"], artifact["id"], kind="qa", task_id=task_id)
    staged = threading.Event()
    terminal_committed = threading.Event()
    activated: list[str] = []
    real_enqueue = job_queue.enqueue_job
    expected_kind = "qa" if mode == "qa" else "model_fix"
    job_prefix = "qa" if mode == "qa" else "model-fix"

    def controlled_enqueue(**kwargs: object) -> dict:
        assert kwargs["job_kind"] == expected_kind
        assert kwargs["target_id"] == run["id"]
        queued = real_enqueue(**kwargs)
        assert queued["status"] == job_queue.STAGING_STATUS
        staged.set()
        assert terminal_committed.wait(timeout=5)
        return queued

    monkeypatch.setattr(background_jobs.job_queue, "enqueue_job", controlled_enqueue)
    monkeypatch.setattr(
        background_jobs.job_queue,
        "activate_job",
        lambda job_id, **_kwargs: activated.append(job_id) or job_queue.get_job(job_id),
    )
    if mode == "qa":
        invoke = lambda: qa_router._start_background_qa(run["id"])
    else:
        invoke = lambda: qa_router.model_fixes_start(
            run["id"],
            ModelFixRequest(max_issues=1, rerun_qa=True),
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(invoke)
        assert staged.wait(timeout=5)
        mark_translation_task_state(project["id"], task_id, "canceled")
        terminal_committed.set()
        with pytest.raises(db.TranslationTaskClosedError):
            future.result(timeout=5)

    assert activated == []
    queued = job_queue.get_job(f"{job_prefix}:{run['id']}")
    assert queued is None or queued["status"] not in {job_queue.STAGING_STATUS, "queued", "running"}
    refreshed = db.get_run(run["id"])
    assert refreshed["status"] == "canceled"
    assert refreshed["metadata"]["translation_task_state"] == "canceled"


@pytest.mark.parametrize(
    ("kind", "endpoint", "job_prefix"),
    [
        ("translation", "translate", "run"),
        ("qa", "qa", "qa"),
    ],
)
def test_quick_cancel_updates_persistent_job_and_cancels_run_and_task(
    tmp_path: Path,
    kind: str,
    endpoint: str,
    job_prefix: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_workbook(tmp_path / f"{kind}-cancel.xlsx")
    monkeypatch.setattr(job_queue, "dispatch_lane", lambda _lane: False)

    with TestClient(app) as client:
        project = db.insert_project(f"Quick {kind} cancel", "quick-task", "")
        artifact = db.add_artifact(project["id"], path.name, path, "quick_input")
        run = _quick_run(project["id"], artifact["id"], kind=kind, task_id=f"quick-task-{kind}-cancel")
        if kind == "translation":
            start_response = client.post(
                f"/api/runs/{run['id']}/{endpoint}/start",
                json={"provider": "test-fake"},
            )
        else:
            start_response = client.post(f"/api/runs/{run['id']}/{endpoint}/start")
        assert start_response.status_code == 200, start_response.text
        response = client.post(f"/api/runs/{run['id']}/{endpoint}/cancel")

    assert response.status_code == 200, response.text
    canceled = job_queue.get_job(f"{job_prefix}:{run['id']}")
    assert canceled is not None
    assert canceled["lane"] == "quick_announcement"
    assert canceled["status"] == "canceled"
    assert canceled["cancel_requested"] is True
    refreshed = db.get_run(run["id"])
    assert refreshed["status"] == "canceled"
    assert refreshed["metadata"]["translation_task_state"] == "canceled"


def test_canceled_quick_task_rejects_late_qa_result(tmp_path: Path) -> None:
    project = db.insert_project("Quick late QA", "quick-task", "")
    path = _write_workbook(tmp_path / "late-qa.xlsx")
    artifact = db.add_artifact(project["id"], path.name, path, "quick_input")
    run = _quick_run(project["id"], artifact["id"], kind="qa", task_id="quick-task-late-qa")
    mark_translation_task_state(project["id"], "quick-task-late-qa", "canceled")

    artifacts_before = db.list_artifacts(run_id=run["id"])
    with pytest.raises(db.TranslationTaskClosedError):
        run_qa_sync(run["id"])

    refreshed = db.get_run(run["id"])
    assert refreshed["status"] == "canceled"
    assert refreshed["metadata"]["translation_task_state"] == "canceled"
    assert db.list_artifacts(run_id=run["id"]) == artifacts_before


def test_canceled_quick_task_rejects_late_translation_result(tmp_path: Path) -> None:
    project = db.insert_project("Quick late translation", "quick-task", "")
    path = tmp_path / "late-translation.txt"
    path.write_text("开始游戏\n", encoding="utf-8")
    artifact = db.add_artifact(project["id"], path.name, path, "quick_input")
    run = _quick_run(project["id"], artifact["id"], task_id="quick-task-late-translation")
    mark_translation_task_state(project["id"], "quick-task-late-translation", "canceled")

    artifacts_before = db.list_artifacts(run_id=run["id"])
    with pytest.raises(db.TranslationTaskClosedError):
        run_translate_sync(run["id"], TranslateRequest(provider="test-fake", batch_size=1))

    refreshed = db.get_run(run["id"])
    assert refreshed["status"] == "canceled"
    assert refreshed["metadata"]["translation_task_state"] == "canceled"
    assert db.list_artifacts(run_id=run["id"]) == artifacts_before


def test_terminal_quick_task_blocks_late_continuation_creation(tmp_path: Path) -> None:
    project = db.insert_project("Quick late continuation", "quick-task", "")
    path = _write_workbook(tmp_path / "late-continuation.xlsx")
    artifact = db.add_artifact(project["id"], path.name, path, "quick_input")
    run = _quick_run(project["id"], artifact["id"], kind="qa", task_id="quick-task-late-continuation")
    mark_translation_task_state(project["id"], "quick-task-late-continuation", "canceled")

    with pytest.raises(db.TranslationTaskClosedError):
        db.insert_run(
            project["id"],
            "qa",
            "en",
            metadata={
                "input_artifact_id": artifact["id"],
                "task_origin": "quick_task",
                "translation_task_id": "quick-task-late-continuation",
            },
        )

    task_runs = [
        item
        for item in db.list_runs(project["id"])
        if (item.get("metadata") or {}).get("translation_task_id") == "quick-task-late-continuation"
    ]
    assert [item["id"] for item in task_runs] == [run["id"]]


def test_terminal_quick_task_rejects_manual_fix_before_artifact_creation(tmp_path: Path) -> None:
    project = db.insert_project("Quick late manual fix", "quick-task", "")
    path = _write_workbook(tmp_path / "late-manual-fix.xlsx")
    artifact = db.add_artifact(project["id"], path.name, path, "quick_input")
    run = _quick_run(project["id"], artifact["id"], kind="qa", task_id="quick-task-late-manual-fix")
    mark_translation_task_state(project["id"], "quick-task-late-manual-fix", "canceled")
    artifacts_before = db.list_artifacts(run_id=run["id"])

    with TestClient(app) as client:
        response = client.post(
            f"/api/runs/{run['id']}/manual-fixes",
            json={"fixes": [{"sheet": "Language", "row": 2, "translation": "Start Game"}], "rerun_qa": True},
        )

    assert response.status_code == 409, response.text
    assert db.list_artifacts(run_id=run["id"]) == artifacts_before


def test_manual_fix_terminal_commit_at_stage_boundary_creates_no_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = db.insert_project("Quick manual stage race", "quick-task", "")
    path = _write_workbook(tmp_path / "manual-stage-race.xlsx")
    artifact = db.add_artifact(project["id"], path.name, path, "quick_input")
    run = _quick_run(project["id"], artifact["id"], kind="qa", task_id="quick-task-manual-stage-race")
    artifacts_before = db.list_artifacts(run_id=run["id"])

    def close_after_apply(*_args: object, **_kwargs: object) -> list[dict]:
        mark_translation_task_state(project["id"], "quick-task-manual-stage-race", "canceled")
        return [{"sheet": "Language", "row": 2, "translation": "Start Game"}]

    monkeypatch.setattr(qa_workflow, "_apply_workbook_fixes", close_after_apply)

    with pytest.raises(db.TranslationTaskClosedError):
        qa_workflow.apply_manual_fixes(
            run["id"],
            ManualFixRequest(
                fixes=[{"sheet": "Language", "row": 2, "translation": "Start Game"}],
                rerun_qa=False,
            ),
        )

    assert db.list_artifacts(run_id=run["id"]) == artifacts_before


def test_model_fix_terminal_commit_at_stage_boundary_creates_no_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = db.insert_project("Quick model stage race", "quick-task", "")
    path = _write_workbook(tmp_path / "model-stage-race.xlsx", target="Forbidden Brand")
    artifact = db.add_artifact(project["id"], path.name, path, "quick_input")
    run = _quick_run(project["id"], artifact["id"], kind="qa", task_id="quick-task-model-stage-race")
    artifacts_before = db.list_artifacts(run_id=run["id"])
    monkeypatch.setattr(
        qa_model_fixes,
        "list_quality_issues",
        lambda _run_id: {
            "issues": [
                {
                    "id": "project_harness:0:Language:2:forbidden_translation",
                    "source": "project_harness",
                    "rule_source": "project_harness",
                    "severity": "hard",
                    "sheet": "Language",
                    "row": 2,
                    "check_type": "forbidden_translation",
                    "message": "forbidden wording",
                    "current_translation": "Forbidden Brand",
                }
            ]
        },
    )
    monkeypatch.setattr(
        qa_model_fixes,
        "_call_semantic_provider",
        lambda _settings, _prompt: '{"fixes":[{"issue_id":"project_harness:0:Language:2:forbidden_translation","sheet":"Language","row":2,"translation":"Start Game"}]}',
    )

    def close_after_apply(*_args: object, **_kwargs: object) -> list[dict]:
        mark_translation_task_state(project["id"], "quick-task-model-stage-race", "canceled")
        return [{"sheet": "Language", "row": 2, "translation": "Start Game"}]

    monkeypatch.setattr(qa_model_fixes, "_apply_workbook_fixes", close_after_apply)

    with pytest.raises(db.TranslationTaskClosedError):
        qa_model_fixes.apply_model_fixes(
            run["id"],
            ModelFixRequest(max_issues=1, rerun_qa=False),
            settings={"provider": "openai", "api_key": "test-key", "model": "gpt-test"},
        )

    assert db.list_artifacts(run_id=run["id"]) == artifacts_before


def test_terminal_state_reapply_backfills_legacy_late_run(tmp_path: Path) -> None:
    project = db.insert_project("Quick legacy continuation", "quick-task", "")
    path = _write_workbook(tmp_path / "legacy-continuation.xlsx")
    artifact = db.add_artifact(project["id"], path.name, path, "quick_input")
    source = _quick_run(project["id"], artifact["id"], kind="qa", task_id="quick-task-legacy-continuation")
    child = db.insert_run(
        project["id"],
        "qa",
        "en",
        metadata={
            "input_artifact_id": artifact["id"],
            "task_origin": "quick_task",
            "translation_task_id": "quick-task-legacy-continuation",
        },
    )
    mark_translation_task_state(project["id"], "quick-task-legacy-continuation", "canceled")
    with db.connect() as conn:
        metadata = db.get_run(child["id"], conn=conn)["metadata"]
        metadata.pop("translation_task_state", None)
        metadata.pop("translation_task_state_updated_at", None)
        conn.execute(
            "UPDATE runs SET status = 'passed', metadata_json = ? WHERE id = ?",
            (json.dumps(metadata, ensure_ascii=False), child["id"]),
        )

    result = mark_translation_task_state(project["id"], "quick-task-legacy-continuation", "delivered")

    assert result["state"] == "canceled"
    assert child["id"] in result["updated_run_ids"]
    repaired = db.get_run(child["id"])
    assert repaired["status"] == "canceled"
    assert repaired["metadata"]["translation_task_state"] == "canceled"
    assert db.get_run(source["id"])["metadata"]["translation_task_state"] == "canceled"


def test_model_fix_worker_stops_before_apply_when_cancel_event_is_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = db.insert_project("Quick model cancel", "quick-task", "")
    path = _write_workbook(tmp_path / "model-cancel.xlsx")
    artifact = db.add_artifact(project["id"], path.name, path, "quick_input")
    run = _quick_run(project["id"], artifact["id"], kind="qa", task_id="quick-task-model-cancel")
    applied: list[str] = []
    monkeypatch.setattr(
        workflow,
        "apply_model_fixes",
        lambda *_args, **_kwargs: applied.append("called") or {},
    )

    cancel_event = threading.Event()
    cancel_event.set()
    background_jobs._model_fix_handler(
        {
            "job_id": f"model-fix:{run['id']}",
            "job_kind": "model_fix",
            "project_id": project["id"],
            "target_id": run["id"],
            "operator_name": "",
            "payload": {"max_issues": 1, "rerun_qa": True},
        },
        cancel_event,
    )

    assert applied == []
    refreshed = db.get_run(run["id"])
    assert refreshed["status"] == "canceled"
    assert refreshed["metadata"]["translation_task_state"] == "canceled"


def test_canceled_quick_task_rejects_late_model_fix_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = db.insert_project("Quick late model fix", "quick-task", "")
    path = _write_workbook(tmp_path / "late-model-fix.xlsx")
    artifact = db.add_artifact(project["id"], path.name, path, "quick_input")
    run = _quick_run(project["id"], artifact["id"], kind="qa", task_id="quick-task-late-model-fix")
    mark_translation_task_state(project["id"], "quick-task-late-model-fix", "canceled")
    scheduled: list[str] = []
    monkeypatch.setattr(
        background_jobs,
        "start_model_fix",
        lambda run_id, _payload: scheduled.append(run_id) or db.get_run(run_id),
    )

    with pytest.raises(qa_router.HTTPException) as exc_info:
        qa_router.model_fixes_start(run["id"], ModelFixRequest(max_issues=1, rerun_qa=True))

    assert exc_info.value.status_code == 409
    assert scheduled == []
    assert job_queue.get_job(f"model-fix:{run['id']}") is None
    refreshed = db.get_run(run["id"])
    assert refreshed["status"] == "canceled"
    assert refreshed["metadata"]["translation_task_state"] == "canceled"
