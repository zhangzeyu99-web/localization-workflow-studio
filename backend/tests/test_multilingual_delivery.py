from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ["LWS_DATA_ROOT"] = str(Path(tempfile.gettempdir()) / "lws-test-data")

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

import app.db as db
from app.config import DEFAULT_SETTINGS, save_settings
from app.main import app
from conftest import reset_data_root, wait_for_background_jobs


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    data_root = Path(os.environ["LWS_DATA_ROOT"])
    reset_data_root(data_root)
    db.init_db()
    save_settings(DEFAULT_SETTINGS)
    yield
    wait_for_background_jobs()
    save_settings(DEFAULT_SETTINGS)


def _write_source(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Language"
    ws.append(["ID", "CN", "EN", "KR"])
    ws.append([1, "开始游戏", "", ""])
    ws.append([2, "领取奖励", "", ""])
    wb.save(path)
    wb.close()


def _write_final(path: Path, language_header: str, values: list[str]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Language"
    ws.append(["ID", "CN", language_header])
    ws.append([1, "开始游戏", values[0]])
    ws.append([2, "领取奖励", values[1]])
    wb.save(path)
    wb.close()


def _add_passed_final(project_id: str, source_id: str, language: str, final_path: Path, header: str, values: list[str]) -> dict:
    _write_final(final_path, header, values)
    run = db.insert_run(
        project_id,
        "translation",
        language,
        metadata={
            "input_artifact_id": source_id,
            "parent_input_artifact_id": source_id,
            "task_origin": "translation_run",
            "quality_summary": {"passed": True, "hard_errors": 0},
        },
    )
    db.update_run(run["id"], status="passed", metadata={**run["metadata"], "quality_summary": {"passed": True, "hard_errors": 0}})
    db.add_artifact(project_id, f"final {language}", final_path, "qa_final_workbook", run_id=run["id"])
    return db.get_run(run["id"])


def test_merged_delivery_combines_passed_language_outputs(tmp_path: Path) -> None:
    project = db.insert_project("merged delivery", "QA", "")
    source_path = tmp_path / "source.xlsx"
    _write_source(source_path)
    source = db.add_artifact(project["id"], "source", source_path, "language_table")
    _add_passed_final(project["id"], source["id"], "en", tmp_path / "en.xlsx", "EN", ["Start Game", "Claim Rewards"])
    _add_passed_final(project["id"], source["id"], "ko", tmp_path / "kr.xlsx", "KR", ["게임 시작", "보상 받기"])

    with TestClient(app) as client:
        response = client.post(
            f"/api/projects/{project['id']}/delivery-package/merged",
            json={"input_artifact_id": source["id"], "languages": ["en", "ko"]},
        )

    assert response.status_code == 200
    payload = response.json()
    final_file = next(item for item in payload["files"] if item["kind"] == "merged_final")
    wb = load_workbook(final_file["path"], data_only=True)
    try:
        ws = wb.active
        assert [cell.value for cell in ws[1]][:4] == ["ID", "CN", "EN", "KR"]
        assert ws.cell(row=2, column=3).value == "Start Game"
        assert ws.cell(row=2, column=4).value == "게임 시작"
        assert ws.cell(row=3, column=3).value == "Claim Rewards"
        assert ws.cell(row=3, column=4).value == "보상 받기"
    finally:
        wb.close()


def test_single_delivery_writes_readback_gate_artifact(tmp_path: Path) -> None:
    project = db.insert_project("single delivery", "QA", "")
    source_path = tmp_path / "source.xlsx"
    _write_source(source_path)
    source = db.add_artifact(project["id"], "source", source_path, "language_table")
    run = _add_passed_final(project["id"], source["id"], "en", tmp_path / "en.xlsx", "EN", ["Start Game", "Claim Rewards"])

    with TestClient(app) as client:
        response = client.post(f"/api/projects/{project['id']}/delivery-package", params={"run_id": run["id"]})

    assert response.status_code == 200
    payload = response.json()
    readback_file = next(item for item in payload["files"] if item["kind"] == "readback_gate")
    with open(readback_file["path"], encoding="utf-8") as handle:
        gate_result = json.load(handle)
    assert gate_result["readback_verified"] is True
    assert gate_result["hard_blockers"] == 0


def test_single_delivery_blocks_when_final_workbook_has_blank_target_cell(tmp_path: Path) -> None:
    project = db.insert_project("single delivery blocked", "QA", "")
    source_path = tmp_path / "source.xlsx"
    _write_source(source_path)
    source = db.add_artifact(project["id"], "source", source_path, "language_table")
    final_path = tmp_path / "en.xlsx"
    _write_final(final_path, "EN", ["Start Game", ""])
    run = db.insert_run(
        project["id"],
        "translation",
        "en",
        metadata={
            "input_artifact_id": source["id"],
            "parent_input_artifact_id": source["id"],
            "task_origin": "translation_run",
            "quality_summary": {"passed": True, "hard_errors": 0},
        },
    )
    db.update_run(run["id"], status="passed", metadata={**run["metadata"], "quality_summary": {"passed": True, "hard_errors": 0}})
    db.add_artifact(project["id"], "final en", final_path, "qa_final_workbook", run_id=run["id"])

    with TestClient(app) as client:
        response = client.post(f"/api/projects/{project['id']}/delivery-package", params={"run_id": run["id"]})

    assert response.status_code == 409


def test_merged_delivery_writes_readback_gate_artifact(tmp_path: Path) -> None:
    project = db.insert_project("merged delivery readback", "QA", "")
    source_path = tmp_path / "source.xlsx"
    _write_source(source_path)
    source = db.add_artifact(project["id"], "source", source_path, "language_table")
    _add_passed_final(project["id"], source["id"], "en", tmp_path / "en.xlsx", "EN", ["Start Game", "Claim Rewards"])
    _add_passed_final(project["id"], source["id"], "ko", tmp_path / "kr.xlsx", "KR", ["게임 시작", "보상 받기"])

    with TestClient(app) as client:
        response = client.post(
            f"/api/projects/{project['id']}/delivery-package/merged",
            json={"input_artifact_id": source["id"], "languages": ["en", "ko"]},
        )

    assert response.status_code == 200
    payload = response.json()
    readback_file = next(item for item in payload["files"] if item["kind"] == "readback_gate")
    with open(readback_file["path"], encoding="utf-8") as handle:
        gate_result = json.load(handle)
    assert gate_result["readback_verified"] is True


def test_merged_delivery_rejects_cross_project_source(tmp_path: Path) -> None:
    first = db.insert_project("A", "QA", "")
    second = db.insert_project("B", "QA", "")
    source_path = tmp_path / "source.xlsx"
    _write_source(source_path)
    source = db.add_artifact(first["id"], "source", source_path, "language_table")

    with TestClient(app) as client:
        response = client.post(
            f"/api/projects/{second['id']}/delivery-package/merged",
            json={"input_artifact_id": source["id"], "languages": ["en"]},
        )

    assert response.status_code == 409
