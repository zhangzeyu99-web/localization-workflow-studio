"""P1: translation-archive reference_hits injection into the main translation flow."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ["LWS_DATA_ROOT"] = str(Path(tempfile.gettempdir()) / "lws-test-data")

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.db as db
from app.config import DEFAULT_SETTINGS, save_settings
from app.main import app
from app.translation_batches import batch_input_fingerprint
from app.workflow.reference_lookup import attach_reference_hits, attach_reference_hits_with_snapshot
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


def _seed_archive(project_id: str) -> None:
    db.upsert_translation_entry(
        project_id,
        {
            "entry_key": "1",
            "source": "领取奖励",
            "target": "Claim Rewards",
            "language": "en",
            "sheet": "Language",
            "row_number": 2,
            "source_type": "qa_passed",
        },
    )
    db.upsert_translation_entry(
        project_id,
        {
            "entry_key": "2",
            "source": "欢迎回来，{playerName}",
            "target": "Welcome back, {playerName}",
            "language": "en",
            "sheet": "Language",
            "row_number": 6,
            "source_type": "imported",
        },
    )


def _sample_rows() -> list[dict[str, object]]:
    return [
        {"id": 1, "source": "领取奖励", "term_hits": []},
        {"id": 2, "source": "开始新的游戏旅程", "term_hits": []},
        {"id": 3, "source": "欢迎回来，{playerName}", "term_hits": []},
    ]


def test_attach_reference_hits_populates_rows_and_audit() -> None:
    project = db.insert_project("archive-hit-project")
    _seed_archive(project["id"])
    rows = _sample_rows()

    audit = attach_reference_hits(rows, project["id"], "en")

    assert audit["archive_entries"] == 2
    assert audit["total_rows"] == 3
    assert audit["reference_hit_rows"] == 2
    assert audit["reference_hits"] == 2
    assert rows[0]["reference_hits"] == [
        {
            "source": "领取奖励",
            "target": "Claim Rewards",
            "target_alt": "",
            "source_type": "qa_passed",
            "sheet": "Language",
            "row_number": 2,
        }
    ]
    assert rows[1]["reference_hits"] == []
    assert rows[2]["reference_hits"][0]["target"] == "Welcome back, {playerName}"


def test_attach_reference_hits_with_empty_archive_is_noop_shape() -> None:
    project = db.insert_project("archive-empty-project")
    rows = _sample_rows()

    audit = attach_reference_hits(rows, project["id"], "en")

    assert audit == {
        "language": "en",
        "archive_entries": 0,
        "total_rows": 3,
        "reference_hit_rows": 0,
        "reference_hits": 0,
    }
    assert all(row["reference_hits"] == [] for row in rows)


def test_batch_fingerprint_changes_when_reference_hits_change() -> None:
    settings = dict(DEFAULT_SETTINGS)
    rows_without = [{"id": 1, "source": "领取奖励", "term_hits": [], "reference_hits": []}]
    rows_with = [
        {
            "id": 1,
            "source": "领取奖励",
            "term_hits": [],
            "reference_hits": [{"source": "领取奖励", "target": "Claim Rewards"}],
        }
    ]

    fp_without = batch_input_fingerprint(rows_without, "", settings, 90, "en")
    fp_with = batch_input_fingerprint(rows_with, "", settings, 90, "en")

    assert fp_without != fp_with


def test_snapshot_keeps_hits_stable_when_archive_changes(tmp_path: Path) -> None:
    """Resume safety: archive growth after the first lookup (e.g. the run's own
    import) must not change reference_hits, or the batch fingerprint would
    invalidate the resume cache."""
    project = db.insert_project("archive-snapshot-project")
    snapshot_path = tmp_path / "reference_hits_snapshot.json"

    rows_first = _sample_rows()
    first_audit = attach_reference_hits_with_snapshot(rows_first, project["id"], "en", snapshot_path)
    assert first_audit["source"] == "live_lookup"
    assert first_audit["reference_hits"] == 0
    assert snapshot_path.exists()

    _seed_archive(project["id"])
    rows_second = _sample_rows()
    second_audit = attach_reference_hits_with_snapshot(rows_second, project["id"], "en", snapshot_path)
    assert second_audit["source"] == "snapshot"
    assert second_audit["reference_hits"] == 0
    assert [row["reference_hits"] for row in rows_second] == [row["reference_hits"] for row in rows_first]


def _sample_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Language"
    ws.append(["ID", "cn", "en"])
    ws.append([1, "领取奖励", ""])
    ws.append([2, "开始游戏", ""])
    ws.append([3, "欢迎回来，{playerName}", ""])
    wb.save(path)
    wb.close()


def test_translation_run_injects_reference_hits_from_archive(tmp_path: Path) -> None:
    workbook = tmp_path / "source.xlsx"
    _sample_workbook(workbook)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "归档注入项目"}).json()
        _seed_archive(project["id"])

        with workbook.open("rb") as fh:
            upload = client.post(
                f"/api/projects/{project['id']}/files?kind=language_table",
                files={"file": ("source.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        assert upload.status_code == 200
        run = client.post(
            "/api/runs",
            json={"project_id": project["id"], "kind": "translation", "language": "en", "input_artifact_id": upload.json()["id"]},
        ).json()

        response = client.post(f"/api/runs/{run['id']}/translate", json={"provider": "test-fake"})
        assert response.status_code == 200, response.text
        metadata = response.json()["run"]["metadata"]
        audit = metadata["reference_audit"]
        assert audit["archive_entries"] == 2
        assert audit["reference_hit_rows"] == 2
        assert audit["reference_hits"] == 2

        workpack_path = Path(os.environ["LWS_DATA_ROOT"]) / "runs" / run["id"] / "translation" / "translation_workpack.jsonl"
        rows = [json.loads(line) for line in workpack_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        by_id = {row["id"]: row for row in rows}
        assert by_id[1]["reference_hits"][0]["target"] == "Claim Rewards"
        assert by_id[2]["reference_hits"] == []

        events = client.get(f"/api/runs/{run['id']}/events").json()
        assert any("translation archive lookup" in event["message"] for event in events)
