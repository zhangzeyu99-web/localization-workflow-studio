from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from openpyxl import Workbook

import app.db as db
import app.workflow.delivery as delivery_workflow
from app.config import DEFAULT_SETTINGS, save_settings
from app.workflow.delivery import build_delivery_package
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
