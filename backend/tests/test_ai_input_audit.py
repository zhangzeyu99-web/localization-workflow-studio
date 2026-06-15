from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ["LWS_DATA_ROOT"] = str(Path(tempfile.gettempdir()) / "lws-test-data")
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.db as db
import app.routers.system as system_router
from app.config import DEFAULT_SETTINGS, save_settings
from app.main import app
from app.workflow.prompt_snapshots import create_prompt_and_harness_snapshots
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


def _xlsx_language_table(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "lang"
    ws.append(["ID", "CN", "EN"])
    ws.append([1, "开始游戏", ""])
    ws.append([2, "领取奖励", ""])
    wb.save(path)


def test_project_ai_input_summary_reports_uploaded_materials(tmp_path: Path) -> None:
    project = db.insert_project("Audit Project", "SLG", "dark fantasy SLG", "国服")
    note_path = tmp_path / "brief.md"
    note_path.write_text("# 暗黑SLG\n\n这是一份暗黑题材 SLG 项目资料", encoding="utf-8")
    artifact = db.add_artifact(project["id"], "brief.md", note_path, "asset", mime="text/markdown")

    with TestClient(app) as client:
        response = client.post(
            f"/api/projects/{project['id']}/analyze",
            json={"intro": "暗黑SLG", "asset_artifact_ids": [artifact["id"]], "target_language": "en"},
        )
        assert response.status_code == 200

        summary = client.get(f"/api/projects/{project['id']}/ai-input-summary")
        assert summary.status_code == 200
        payload = summary.json()
        assert payload["analysis"]["summary"]["total"] == 1
        material = payload["analysis"]["materials"][0]
        assert material["filename"] == "brief.md"
        assert material["included_in_ai"] is True
        assert "暗黑题材" in material["excerpt"]
        assert material["readable"] is True


def test_project_analysis_rejects_cross_project_artifact(tmp_path: Path) -> None:
    project_a = db.insert_project("Project A", "SLG", "", "国服")
    project_b = db.insert_project("Project B", "SLG", "", "国服")
    note_path = tmp_path / "brief.md"
    note_path.write_text("# A 项目资料", encoding="utf-8")
    artifact = db.add_artifact(project_a["id"], "brief.md", note_path, "asset", mime="text/markdown")

    with TestClient(app) as client:
        response = client.post(
            f"/api/projects/{project_b['id']}/analyze",
            json={"intro": "B", "asset_artifact_ids": [artifact["id"]], "target_language": "en"},
        )
        assert response.status_code == 400
        assert "brief.md" in response.text


def test_project_analysis_rejects_missing_artifact_file(tmp_path: Path) -> None:
    project = db.insert_project("Missing File", "SLG", "", "国服")
    note_path = tmp_path / "missing.md"
    note_path.write_text("# 缺失资料", encoding="utf-8")
    artifact = db.add_artifact(project["id"], "missing.md", note_path, "asset", mime="text/markdown")
    note_path.unlink()

    with TestClient(app) as client:
        response = client.post(
            f"/api/projects/{project['id']}/analyze",
            json={"intro": "missing", "asset_artifact_ids": [artifact["id"]], "target_language": "en"},
        )
        assert response.status_code == 400
        assert "missing.md" in response.text


def test_uploaded_project_material_is_readable_and_enters_analysis() -> None:
    project = db.insert_project("Upload Audit", "SLG", "", "国服")
    with TestClient(app) as client:
        upload = client.post(
            f"/api/projects/{project['id']}/files?kind=asset&purpose=project_material",
            files={"file": ("brief.md", b"# Upload Brief\n\ncloud readable material", "text/markdown")},
        )
        assert upload.status_code == 200
        artifact = upload.json()
        assert artifact["metadata"]["readable"] is True
        assert artifact["project_id"] == project["id"]

        response = client.post(
            f"/api/projects/{project['id']}/analyze",
            json={"intro": "upload", "asset_artifact_ids": [artifact["id"]], "target_language": "en"},
        )
        assert response.status_code == 200
        summary = client.get(f"/api/projects/{project['id']}/ai-input-summary").json()
        assert summary["analysis"]["materials"][0]["readable"] is True
        assert "cloud readable material" in summary["analysis"]["materials"][0]["excerpt"]


def test_upload_readability_self_test_saves_and_reads_file() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/diagnostics/upload-readability",
            files={"file": ("probe.txt", b"cloud self test", "text/plain")},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["readable"] is True
        assert payload["size"] == len(b"cloud self test")
        assert "cloud self test" in payload["preview"]
        health = client.get("/api/health").json()
        assert health["latest_upload_readability"]["sha256"] == payload["sha256"]


def test_project_analysis_rejects_materials_that_do_not_enter_ai(tmp_path: Path) -> None:
    project = db.insert_project("Unsupported Material", "SLG", "", "G")
    binary = tmp_path / "recording.bin"
    binary.write_bytes(b"\x00\x01\x02")
    artifact = db.add_artifact(project["id"], "recording.bin", binary, "asset", mime="application/octet-stream")
    with TestClient(app) as client:
        response = client.post(
            f"/api/projects/{project['id']}/analyze",
            json={"intro": "unsupported", "asset_artifact_ids": [artifact["id"]], "target_language": "en"},
        )
        assert response.status_code == 400
        assert "没有成功解析进 AI" in response.text


def test_project_scoped_artifact_download_rejects_other_project(tmp_path: Path) -> None:
    project_a = db.insert_project("Download A", "SLG", "", "G")
    project_b = db.insert_project("Download B", "SLG", "", "G")
    path = Path(os.environ["LWS_DATA_ROOT"]) / "projects" / project_a["id"] / "uploads" / "brief.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# A", encoding="utf-8")
    artifact = db.add_artifact(project_a["id"], "brief.md", path, "asset", mime="text/markdown")
    with TestClient(app) as client:
        ok = client.get(f"/api/projects/{project_a['id']}/artifacts/{artifact['id']}/download")
        assert ok.status_code == 200
        blocked = client.get(f"/api/projects/{project_b['id']}/artifacts/{artifact['id']}/download")
        assert blocked.status_code == 404


def test_project_scoped_translation_inspection_rejects_other_project(tmp_path: Path) -> None:
    project_a = db.insert_project("Inspect A", "SLG", "", "G")
    project_b = db.insert_project("Inspect B", "SLG", "", "G")
    workbook = tmp_path / "source.xlsx"
    _xlsx_language_table(workbook)
    artifact = db.add_artifact(project_a["id"], "source.xlsx", workbook, "language_table", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with TestClient(app) as client:
        ok_readiness = client.get(f"/api/projects/{project_a['id']}/artifacts/{artifact['id']}/translation-readiness?batch_size=90")
        assert ok_readiness.status_code == 200
        blocked_readiness = client.get(f"/api/projects/{project_b['id']}/artifacts/{artifact['id']}/translation-readiness?batch_size=90")
        assert blocked_readiness.status_code == 404
        ok_targets = client.get(f"/api/projects/{project_a['id']}/artifacts/{artifact['id']}/translation-targets")
        assert ok_targets.status_code == 200
        blocked_targets = client.get(f"/api/projects/{project_b['id']}/artifacts/{artifact['id']}/translation-targets")
        assert blocked_targets.status_code == 404


def test_translation_ai_input_summary_reports_workpack_and_prompt(tmp_path: Path) -> None:
    project = db.insert_project("Audit Translation", "QA", "", "国服")
    workbook = tmp_path / "source.xlsx"
    _xlsx_language_table(workbook)
    artifact = db.add_artifact(project["id"], "source.xlsx", workbook, "language_table", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    run = db.insert_run(project["id"], "translation", "en", metadata={"input_artifact_id": artifact["id"], "task_origin": "translation_run", "batch_size": 2})
    work_dir = Path(os.environ["LWS_DATA_ROOT"]) / "runs" / run["id"] / "translation"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "translation_workpack.jsonl").write_text(
        '{"id":1,"source":"开始游戏","term_hits":[{"source":"开始","target":"Start"}]}\n'
        '{"id":2,"source":"领取奖励","term_hits":[]}\n',
        encoding="utf-8",
    )
    snapshot = work_dir / "snapshots" / "compiled_project_harness_prompt.txt"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("请严格保留变量和 UI 文案", encoding="utf-8")
    db.add_artifact(project["id"], "Prompt snapshot", snapshot, "prompt_snapshot", run_id=run["id"], mime="text/plain")

    with TestClient(app) as client:
        response = client.get(f"/api/runs/{run['id']}/ai-input-summary")
        assert response.status_code == 200
        payload = response.json()
        assert payload["workpack"]["rows"] == 2
        assert payload["workpack"]["term_hit_rows"] == 1
        assert payload["prompt"]["available"] is True
        assert "UI 文案" in payload["prompt"]["preview"]
        assert payload["workpack"]["samples"][0]["term_hits_count"] == 1
        assert payload["workpack"]["estimated_batches"] == 1


def test_announcement_ai_input_summary_reports_segments_terms_and_prompt(tmp_path: Path) -> None:
    project = db.insert_project("Audit Announcement", "SLG", "", "国服")
    source = tmp_path / "notice.txt"
    source.write_text("英雄集结活动开启", encoding="utf-8")
    source_artifact = db.add_artifact(project["id"], "notice.txt", source, "asset", mime="text/plain")
    task = db.insert_announcement_task(
        project["id"],
        {
            "title": "notice.txt",
            "source_artifact_id": source_artifact["id"],
            "source_format": "txt",
            "selected_languages": ["en"],
            "status": "prepared",
            "current_step": 7,
            "metadata": {},
        },
    )
    run = db.insert_run(project["id"], "announcement_lookup", "en", metadata={"task_id": task["id"]})
    workpack = tmp_path / "notice_workpack_EN.jsonl"
    workpack.write_text('{"id":"seg-1","source":"英雄集结","term_hits":[{"source":"英雄","target":"Hero"}]}\n', encoding="utf-8")
    prompt = tmp_path / "notice_prompt_EN.txt"
    prompt.write_text("请参考术语表翻译公告文本", encoding="utf-8")
    workpack_artifact = db.add_artifact(project["id"], "公告 workpack (EN)", workpack, "announcement_workpack", run_id=run["id"], mime="application/jsonl", metadata={"task_id": task["id"], "language": "en"})
    prompt_artifact = db.add_artifact(project["id"], "公告提示词 (EN)", prompt, "prompt_snapshot", run_id=run["id"], mime="text/plain", metadata={"task_id": task["id"], "language": "en"})
    db.update_announcement_task(
        task["id"],
        metadata={
            "workpack_artifact_ids": {"en": workpack_artifact["id"]},
            "prompt_artifact_ids": {"en": prompt_artifact["id"]},
            "lookup_summary": {"terms": 1, "translations": 0, "missing_terms": 0},
            "segments": 1,
        },
    )

    with TestClient(app) as client:
        response = client.get(f"/api/announcement-tasks/{task['id']}/ai-input-summary")
        assert response.status_code == 200
        payload = response.json()
        assert payload["segments"] == 1
        assert payload["lookup"]["terms"] == 1
        assert payload["languages"][0]["workpack_rows"] == 1
        assert payload["languages"][0]["term_hits"] == 1
        assert "术语表" in payload["languages"][0]["prompt_preview"]


def test_announcement_ai_input_summary_handles_missing_prepared_artifacts(tmp_path: Path) -> None:
    project = db.insert_project("Audit Announcement Missing", "SLG", "", "G")
    source = tmp_path / "notice.txt"
    source.write_text("notice source", encoding="utf-8")
    source_artifact = db.add_artifact(project["id"], "notice.txt", source, "asset", mime="text/plain")
    task = db.insert_announcement_task(
        project["id"],
        {
            "title": "notice.txt",
            "source_artifact_id": source_artifact["id"],
            "source_format": "txt",
            "selected_languages": ["en"],
            "status": "lookup_ready",
            "current_step": 6,
            "metadata": {},
        },
    )

    with TestClient(app) as client:
        response = client.get(f"/api/announcement-tasks/{task['id']}/ai-input-summary")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "not_prepared"
        assert payload["languages"] == []

        db.update_announcement_task(task["id"], metadata={"workpack_artifact_ids": {"en": "missing-artifact"}})
        stale = client.get(f"/api/announcement-tasks/{task['id']}/ai-input-summary")
        assert stale.status_code == 200
        stale_payload = stale.json()
        assert stale_payload["status"] == "not_prepared"
        assert stale_payload["warnings"]


def test_health_reports_cloud_storage_and_provider_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LWS_DEPLOYMENT_MODE", "cloud")
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["deployment_mode"] == "cloud"
        assert payload["storage"]["data_root_writable"] is True
        assert payload["storage"]["uploads_writable"] is True
        assert payload["database"]["connected"] is True
        assert "provider_configured" in payload["provider"]


def test_deployment_mode_defaults_to_cloud_under_data_web(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LWS_DEPLOYMENT_MODE", raising=False)
    monkeypatch.setattr(system_router, "DATA_ROOT", Path("/data/web/lwstudio/lws-data"))
    monkeypatch.setattr(system_router, "APP_ROOT", Path("/data/web/lwstudio"))

    assert system_router._deployment_mode() == "cloud"


def test_saved_project_prompt_overrides_stale_prompt_file(tmp_path: Path) -> None:
    project = db.insert_project("Prompt Override", "SLG", "", "G")
    prompt_root = Path(os.environ["LWS_DATA_ROOT"]) / "projects" / project["id"] / "profile"
    prompt_root.mkdir(parents=True, exist_ok=True)
    prompt_path = prompt_root / "translation_prompt_en.txt"
    prompt_path.write_text("OLD PROMPT SHOULD NOT BE USED", encoding="utf-8")
    manual_prompt = "MANUAL PROJECT PROMPT: keep UI concise and follow project glossary."

    with TestClient(app) as client:
        response = client.patch(
            f"/api/projects/{project['id']}",
            json={"profile": {"prompts_by_language": {"en": manual_prompt}, "display_prompts_by_language": {"en": manual_prompt}}},
        )
        assert response.status_code == 200
        assert prompt_path.read_text(encoding="utf-8") == manual_prompt

    run = db.insert_run(project["id"], "translation", "en", metadata={})
    snapshots = create_prompt_and_harness_snapshots(project["id"], run["id"], tmp_path / "snapshots", language="en")
    assert manual_prompt in snapshots["prompt"]
    assert "OLD PROMPT" not in snapshots["prompt"]
