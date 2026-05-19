from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ["LWS_DATA_ROOT"] = str(Path(tempfile.gettempdir()) / "lws-test-data")

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app


def _sample_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Language"
    ws.append(["ID", "cn", "en"])
    ws.append([1, "领取奖励", ""])
    ws.append([2, "开始游戏", ""])
    ws.append([3, "系统错误", ""])
    ws.append([4, "主线任务", ""])
    ws.append([5, "欢迎回来，{playerName}", ""])
    wb.save(path)
    wb.close()


def test_mock_provider_runs_english_workflow_end_to_end(tmp_path: Path) -> None:
    workbook = tmp_path / "sample-language.xlsx"
    _sample_workbook(workbook)

    with TestClient(app) as client:
        project_response = client.post(
            "/api/projects",
            json={
                "name": "Synthetic Frontier",
                "type": "科幻 SLG",
                "icon": "🚀",
                "description": "Synthetic public demo project.",
            },
        )
        assert project_response.status_code == 200
        project = project_response.json()

        analysis_response = client.post(
            f"/api/projects/{project['id']}/analyze",
            json={"intro": "A synthetic strategy game for testing localization workflow.", "asset_artifact_ids": []},
        )
        assert analysis_response.status_code == 200
        assert "Return only id + translation JSONL" in analysis_response.json()["prompt"]

        with workbook.open("rb") as fh:
            upload_response = client.post(
                f"/api/projects/{project['id']}/files?kind=language_table",
                files={"file": ("sample-language.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        assert upload_response.status_code == 200
        source_artifact = upload_response.json()

        run_response = client.post(
            "/api/runs",
            json={
                "project_id": project["id"],
                "kind": "translation",
                "language": "en",
                "input_artifact_id": source_artifact["id"],
                "batch_size": 3,
            },
        )
        assert run_response.status_code == 200
        run = run_response.json()

        translate_response = client.post(f"/api/runs/{run['id']}/translate", json={"provider": "mock"})
        assert translate_response.status_code == 200, translate_response.text
        result = translate_response.json()
        assert result["run"]["status"] == "passed"
        kinds = {artifact["kind"] for artifact in result["artifacts"]}
        assert {"final_workbook", "qa_report", "qa_result", "translation_manifest"}.issubset(kinds)
        project_detail_response = client.get(f"/api/projects/{project['id']}")
        assert project_detail_response.status_code == 200
        assert project_detail_response.json()["stats"]["words"] == "11"
        assert project_detail_response.json()["stats"]["langs"] == 1
