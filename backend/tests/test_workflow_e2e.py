from __future__ import annotations

import os
import json
import re
import tempfile
import zipfile
from pathlib import Path

os.environ.setdefault("LWS_DATA_ROOT", str(Path(tempfile.gettempdir()) / "lws-test-data"))

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


def _sample_term_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Glossary"
    ws.append(["ID", "CN", "EN", "EN2", "分类", "note"])
    ws.append([1, "最强指挥官", "Strongest Commander", "Top Commander", "title", "confirmed project term"])
    ws.append([2, "联盟", "Alliance", "Guild", "system", "common game term"])
    wb.save(path)
    wb.close()


def _translated_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Language"
    ws.append(["ID", "cn", "en"])
    ws.append([1, "领取奖励", "Claim Rewards"])
    ws.append([2, "开始游戏", "Start Game"])
    ws.append([3, "系统错误", "System Error"])
    ws.append([4, "主线任务", "Main Quest"])
    ws.append([5, "欢迎回来，{playerName}", "Welcome back, {playerName}"])
    wb.create_sheet("EmptySheet")
    wb.save(path)
    wb.close()


def _target_language_workbook(path: Path, target_header: str, targets: list[str] | None = None) -> None:
    values = targets or ["", ""]
    wb = Workbook()
    ws = wb.active
    ws.title = "Language"
    ws.append(["ID", "CN", target_header])
    ws.append(["btn.claim", "领取奖励", values[0]])
    ws.append(["msg.welcome", "欢迎回来，{playerName}", values[1]])
    wb.save(path)
    wb.close()


def _announcement_ko_terms(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Glossary"
    ws.append(["ID", "CN", "KR"])
    ws.append(["term_hero", "英雄", "영웅"])
    ws.append(["term_awaken", "觉醒", "각성"])
    wb.save(path)
    wb.close()


def test_announcement_task_txt_multilingual_flow_uses_selected_constraint_priority_and_delivers(tmp_path: Path) -> None:
    source_path = tmp_path / "notice.txt"
    terms_path = tmp_path / "notice_terms.xlsx"
    source_path.write_text("英雄觉醒 2026/5/20\n", encoding="utf-8")
    _announcement_ko_terms(terms_path)

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "公告任务 TXT", "type": "RPG"}).json()
        client.post(
            f"/api/projects/{project['id']}/translations",
            json={
                "entry_key": "hero",
                "source": "英雄",
                "target": "히어로",
                "language": "ko",
                "source_type": "qa_passed",
            },
        )
        archive_before_flow = client.get(f"/api/projects/{project['id']}/translations?language=ko").json()
        with source_path.open("rb") as fh:
            source_artifact = client.post(
                f"/api/projects/{project['id']}/files?kind=asset",
                files={"file": ("notice.txt", fh, "text/plain")},
            ).json()
        with terms_path.open("rb") as fh:
            terms_artifact = client.post(
                f"/api/projects/{project['id']}/files?kind=language_table",
                files={"file": ("notice_terms.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()

        task = client.post(
            f"/api/projects/{project['id']}/announcement-tasks",
            json={"source_artifact_id": source_artifact["id"], "language_table_artifact_ids": [terms_artifact["id"]], "languages": ["ko"]},
        ).json()
        task_id = task["id"]
        assert task["source_format"] == "txt"

        for endpoint in ("inspect-constraints", "extract-terms", "lookup-translations"):
            response = client.post(
                f"/api/announcement-tasks/{task_id}/{endpoint}",
                json={"language_table_artifact_ids": [terms_artifact["id"]], "languages": ["ko"], "include_project_archive": True},
            )
            assert response.status_code == 200, response.text

        prepare_response = client.post(f"/api/announcement-tasks/{task_id}/prepare", json={"languages": ["ko"]})
        assert prepare_response.status_code == 200, prepare_response.text
        prepared = prepare_response.json()
        workpack = next(artifact for artifact in prepared["artifacts"] if artifact["kind"] == "announcement_workpack")
        rows = [json.loads(line) for line in Path(workpack["path"]).read_text(encoding="utf-8").splitlines()]
        assert rows[0]["term_hits"] == [{"source": "英雄", "target": "영웅"}, {"source": "觉醒", "target": "각성"}]

        response_path = tmp_path / "ai_response_ko.jsonl"
        response_path.write_text(
            "\n".join(json.dumps({"para_id": row["para_id"], "translation": "영웅 각성 2026/5/20"}, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )
        with response_path.open("rb") as fh:
            response_artifact = client.post(
                f"/api/projects/{project['id']}/files?kind=asset",
                files={"file": ("ai_response_ko.jsonl", fh, "application/jsonl")},
            ).json()
        imported = client.post(
            f"/api/announcement-tasks/{task_id}/import-ai",
            json={"languages": ["ko"], "response_artifact_ids": [response_artifact["id"]]},
        )
        assert imported.status_code == 200, imported.text
        applied = client.post(f"/api/announcement-tasks/{task_id}/apply", json={"languages": ["ko"]})
        assert applied.status_code == 200, applied.text
        assert client.get(f"/api/projects/{project['id']}/translations?language=ko").json() == archive_before_flow
        delivered = client.post(f"/api/announcement-tasks/{task_id}/deliver", json={"languages": ["ko"], "date_stamp": "20260526"})
        assert delivered.status_code == 200, delivered.text
        archive_after_delivery = client.get(f"/api/projects/{project['id']}/translations?language=ko").json()
        assert archive_after_delivery == archive_before_flow
        assert delivered.json()["summary"]["translation_archive"] is None
        assert delivered.json()["task"]["metadata"]["translation_archive"] is None
        package = next(artifact for artifact in delivered.json()["artifacts"] if artifact["kind"] == "announcement_delivery_package")
        package_path = Path(package["path"])
        assert package_path.exists()
        assert re.fullmatch(r".+_notice_announcement_delivery_20260526\.zip", package_path.name)
        assert ".txt_announcement" not in package_path.name
        with zipfile.ZipFile(package_path) as archive:
            names = sorted(archive.namelist())
        assert names == ["KR/notice_KR.txt", "QA摘要.xlsx"]
        assert not any(name.endswith(".json") or name.endswith(".jsonl") or "manifest" in name.lower() or "workpack" in name.lower() for name in names)
        repeated = client.post(f"/api/announcement-tasks/{task_id}/deliver", json={"languages": ["ko"], "date_stamp": "20260526"})
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["summary"]["reused"] is True
        assert repeated.json()["summary"]["delivery_artifact_id"] == package["id"]
        assert repeated.json()["summary"]["translation_archive"] is None
        assert client.get(f"/api/projects/{project['id']}/translations?language=ko").json() == archive_before_flow

        deliverables = client.get(f"/api/projects/{project['id']}/deliverables").json()["deliverables"]
        announcement_deliverable = next(item for item in deliverables if item["task_code"] == "ANN")
        assert announcement_deliverable["status"] == "delivered"
        assert announcement_deliverable["task_type"] == "公告任务"
        assert announcement_deliverable["language"] == "KR"
        assert announcement_deliverable["delivered_with_issues"] is False
        assert announcement_deliverable["files"]["package"]["download_url"].startswith(f"/api/projects/{project['id']}/artifacts/")
        assert announcement_deliverable["files"]["qa_summary"]["download_url"].startswith(f"/api/projects/{project['id']}/artifacts/")
        assert announcement_deliverable["files"]["outputs"][0]["download_url"].startswith(f"/api/projects/{project['id']}/artifacts/")

        forced = client.post(f"/api/announcement-tasks/{task_id}/deliver", json={"languages": ["ko"], "date_stamp": "20260526", "force": True})
        assert forced.status_code == 200, forced.text
        assert forced.json()["summary"]["translation_archive"] is None
        assert client.get(f"/api/projects/{project['id']}/translations?language=ko").json() == archive_before_flow
        forced_package = next(artifact for artifact in forced.json()["artifacts"] if artifact["kind"] == "announcement_delivery_package")
        assert forced_package["id"] != package["id"]
        assert [(entry["source"], entry["target"]) for entry in client.get(f"/api/projects/{project['id']}/translations?language=ko").json()] == [("英雄", "히어로")]
        superseded_package = db.get_artifact(package["id"])
        assert superseded_package["metadata"]["superseded"] is True
        assert superseded_package["metadata"]["superseded_by"] == forced_package["id"]
        visible_packages = [
            artifact for artifact in db.list_artifacts(project_id=project["id"], role="delivery")
            if artifact["kind"] == "announcement_delivery_package" and (artifact.get("metadata") or {}).get("task_id") == task_id
        ]
        assert [artifact["id"] for artifact in visible_packages] == [forced_package["id"]]
        project_detail = client.get(f"/api/projects/{project['id']}").json()
        assert project_detail["stats"]["tasks"] == 1
        assert project_detail["stats"]["announcement_tasks"] == 1
        assert project_detail["stats"]["language_tasks"] == 0
        assert project_detail["stats"]["deliverables"] == 1
        assert project_detail["stats"]["execution_runs"] > project_detail["stats"]["tasks"]

        qa_artifact = next(artifact for artifact in applied.json()["artifacts"] if artifact["kind"] == "announcement_qa_summary")
        qa_wb = load_workbook(qa_artifact["path"], read_only=True, data_only=True)
        try:
            assert qa_wb.sheetnames == ["Summary", "Issues", "Outputs"]
            summary = {row[0]: row[1] for row in qa_wb["Summary"].iter_rows(min_row=2, values_only=True)}
            assert summary["hard_blockers"] == 0
            assert summary["outputs"] == 1
            assert summary["languages"] == "KR"
            outputs = list(qa_wb["Outputs"].iter_rows(min_row=2, values_only=True))
            assert outputs[0][0] == "KR"
            assert outputs[0][1] == "notice_KR.txt"
        finally:
            qa_wb.close()


def test_fake_provider_runs_english_workflow_end_to_end(tmp_path: Path) -> None:
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
        assert "只返回 JSONL" in analysis_response.json()["prompt"]
        analyzed_project = analysis_response.json()["project"]
        display_prompt = analyzed_project["profile"]["display_prompts_by_language"]["en"]
        assert "\u9879\u76ee\u5b9a\u4f4d" in display_prompt
        assert "?" * 4 not in display_prompt
        assert "JSONL" not in display_prompt

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

        translate_response = client.post(f"/api/runs/{run['id']}/translate", json={"provider": "test-fake"})
        assert translate_response.status_code == 200, translate_response.text
        result = translate_response.json()
        assert result["run"]["status"] == "passed"
        kinds = {artifact["kind"] for artifact in result["artifacts"]}
        assert {
            "raw_translated_workbook",
            "qa_final_workbook",
            "qa_report",
            "qa_result",
            "qa_changes",
            "translation_manifest",
            "glossary_snapshot",
            "prompt_snapshot",
            "project_harness_snapshot",
        }.issubset(kinds)
        final_artifact = next(artifact for artifact in result["artifacts"] if artifact["kind"] == "qa_final_workbook")
        assert final_artifact["role"] == "translation_workbook"
        assert final_artifact["origin"] == "generated"
        metadata = result["run"]["metadata"]
        assert metadata["input_artifacts"]["source_workbook"] == source_artifact["id"]
        assert metadata["input_artifacts"]["qa_final_workbook"] == final_artifact["id"]
        assert metadata["semantic_qa"]["status"] == "skipped_no_key"
        assert metadata["translation_archive"]["imported_count"] == 5
        assert result["run"]["metadata"]["harness"]["source"] == "project_harness"
        progress = metadata["translation_progress"]
        assert progress["batch_size"] == 3
        assert progress["total_batches"] == 2
        assert progress["completed_batches"] == 2
        assert progress["percent"] == 100
        batch_dir = Path(os.environ["LWS_DATA_ROOT"]) / "runs" / run["id"] / "translation" / "batches_3"
        assert (batch_dir / "batch_00001.jsonl").exists()
        assert (batch_dir / "batch_00002.jsonl").exists()
        events = client.get(f"/api/runs/{run['id']}/events").json()
        assert any("completed and persisted" in event["message"] for event in events)
        project_detail_response = client.get(f"/api/projects/{project['id']}")
        assert project_detail_response.status_code == 200
        assert project_detail_response.json()["stats"]["words"] == "33"
        assert project_detail_response.json()["stats"]["archived_rows"] == 5
        assert project_detail_response.json()["stats"]["translation_runs"] == 1
        assert project_detail_response.json()["stats"]["qa_runs"] == 0
        assert project_detail_response.json()["stats"]["langs"] == 1
        resume_response = client.post(f"/api/runs/{run['id']}/translate", json={"provider": "test-fake", "batch_size": 3})
        assert resume_response.status_code == 200, resume_response.text
        resume_events = client.get(f"/api/runs/{run['id']}/events").json()
        assert any("resume: batch 1/2 already completed" in event["message"] for event in resume_events)


def test_korean_fake_translation_workflow_end_to_end(tmp_path: Path) -> None:
    workbook = tmp_path / "ko-language.xlsx"
    _target_language_workbook(workbook, "KO")

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "E2E Korean", "type": "QA"}).json()
        with workbook.open("rb") as fh:
            source_artifact = client.post(
                f"/api/projects/{project['id']}/files?kind=language_table",
                files={"file": ("ko-language.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()

        readiness_response = client.get(f"/api/artifacts/{source_artifact['id']}/translation-readiness?language=ko&batch_size=90")
        assert readiness_response.status_code == 200, readiness_response.text
        readiness = readiness_response.json()
        assert readiness["target_language"] == "ko"
        assert readiness["needs_translation"] is True
        assert readiness["source_rows"] == 2

        run_response = client.post(
            "/api/runs",
            json={"project_id": project["id"], "kind": "translation", "language": "ko", "input_artifact_id": source_artifact["id"]},
        )
        assert run_response.status_code == 200, run_response.text
        run = run_response.json()
        translate_response = client.post(f"/api/runs/{run['id']}/translate", json={"provider": "test-fake"})
        assert translate_response.status_code == 200, translate_response.text
        result = translate_response.json()

        assert result["run"]["status"] == "passed"
        assert result["run"]["language"] == "ko"
        assert result["run"]["metadata"]["translation_archive"]["imported_count"] == 2
        final_artifact = next(artifact for artifact in result["artifacts"] if artifact["kind"] == "qa_final_workbook")
        wb = load_workbook(final_artifact["path"], read_only=True, data_only=True)
        try:
            assert wb["Language"].cell(2, 3).value
        finally:
            wb.close()


def test_glossary_preview_import_and_export(tmp_path: Path) -> None:
    terms = tmp_path / "terms.xlsx"
    _sample_term_workbook(terms)

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Glossary Import", "type": "QA"}).json()
        with terms.open("rb") as fh:
            upload_response = client.post(
                f"/api/projects/{project['id']}/files?kind=term_base",
                files={"file": ("terms.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        term_artifact = upload_response.json()

        preview_response = client.post(
            f"/api/projects/{project['id']}/glossary/import-preview",
            json={"artifact_id": term_artifact["id"]},
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()
        assert preview["rows"][0]["source"] == "最强指挥官"
        assert preview["rows"][0]["target"] == "Strongest Commander"
        assert preview["rows"][0]["target_alt"] == ""
        assert preview["rows"][0]["term_key"] == "1"
        assert preview["rows"][0]["category"] == "title"

        import_response = client.post(
            f"/api/projects/{project['id']}/glossary/import",
            json={"artifact_id": term_artifact["id"]},
        )
        assert import_response.status_code == 200
        assert import_response.json()["imported_count"] == 2

        project_terms = client.get(f"/api/projects/{project['id']}/glossary").json()
        assert {term["source"] for term in project_terms} == {"最强指挥官", "联盟"}
        assert {term["source_type"] for term in project_terms} == {"imported"}
        assert {term["target_alt"] for term in project_terms} == {""}
        assert {term["category"] for term in project_terms} == {"title", "system"}

        manual_response = client.post(
            f"/api/projects/{project['id']}/glossary",
            json={
                "term_key": "M-1",
                "source": "战机",
                "target": "Warplane",
                "target_alt": "Fighter",
                "category": "unit",
                "note": "manual term",
                "source_type": "manual",
                "confirmed": True,
            },
        )
        assert manual_response.status_code == 200
        manual = manual_response.json()
        update_response = client.patch(
            f"/api/projects/{project['id']}/glossary/{manual['id']}",
            json={"target": "Fighter Jet", "note": "edited term"},
        )
        assert update_response.status_code == 200

        export_response = client.get(f"/api/projects/{project['id']}/glossary/export?format=json")
        assert export_response.status_code == 200
        exported = export_response.json()
        assert len(exported["terms"]) == 3
        assert all("source_type" not in term and "confirmed" not in term for term in exported["terms"])
        assert any(term["source"] == "战机" and term["target"] == "Fighter Jet" and term["note"] == "edited term" for term in exported["terms"])
        xlsx_response = client.get(f"/api/projects/{project['id']}/glossary/export?format=xlsx")
        assert xlsx_response.status_code == 200
        assert "spreadsheetml" in xlsx_response.headers["content-type"]
        exported_xlsx = tmp_path / "exported_terms.xlsx"
        exported_xlsx.write_bytes(xlsx_response.content)
        wb = load_workbook(exported_xlsx, read_only=True)
        try:
            ws = wb.active
            headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
            assert headers == ["ID", "CN", "EN", "分类", "备注"]
        finally:
            wb.close()
        csv_response = client.get(f"/api/projects/{project['id']}/glossary/export?format=csv")
        assert csv_response.status_code == 200
        assert csv_response.content.decode("utf-8-sig").splitlines()[0] == "ID,CN,EN,分类,备注"


@pytest.mark.parametrize(
    ("language", "filename"), [("ko", "quick.txt"), ("vi", "quick_vn.txt")], ids=["korean", "vietnamese"]
)
def test_quick_task_can_translate_txt_and_deliver_same_format(tmp_path: Path, language: str, filename: str) -> None:
    source = tmp_path / filename
    source.write_text("\u5f00\u59cb\u6e38\u620f\n\n\u4fdd\u5b58 {0}\n", encoding="utf-8")

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Quick TXT", "type": "quick-task"}).json()
        with source.open("rb") as fh:
            quick_input = client.post(
                f"/api/projects/{project['id']}/files?kind=quick_input",
                files={"file": (filename, fh, "text/plain")},
            ).json()

        targets = client.get(f"/api/artifacts/{quick_input['id']}/translation-targets").json()
        assert targets["supported_file"] is True
        assert targets["source_detected"] is True
        readiness = client.get(f"/api/artifacts/{quick_input['id']}/translation-readiness?language={language}&batch_size=1").json()
        assert readiness["source_rows"] == 2
        assert readiness["needs_translation"] is True

        run = client.post(
            "/api/runs",
            json={
                "project_id": project["id"],
                "kind": "translation",
                "language": language,
                "input_artifact_id": quick_input["id"],
                "task_origin": "quick_task",
                "batch_size": 1,
            },
        ).json()
        result = client.post(f"/api/runs/{run['id']}/translate", json={"provider": "test-fake", "batch_size": 1}).json()
        assert result["run"]["status"] == "passed"
        final_artifact = next(artifact for artifact in result["artifacts"] if artifact["kind"] == "final_text")
        final_text = Path(final_artifact["path"]).read_text(encoding="utf-8")
        assert "TestFake" in final_text
        assert "{0}" in final_text
        assert final_text.count("\n") == 3

        if language == "vi":
            assert result["run"]["language"] == "vn"
            assert Path(final_artifact["path"]).name == "quick_vn_VI.txt"
            manifest_artifact = next(artifact for artifact in result["artifacts"] if artifact["kind"] == "translation_manifest")
            assert json.loads(Path(manifest_artifact["path"]).read_text(encoding="utf-8"))["language"] == "vn"

        package = client.post(f"/api/projects/{project['id']}/delivery-package?run_id={run['id']}").json()
        assert len(package["files"]) == 1
        assert package["files"][0]["filename"].endswith("_final.txt")


def test_translation_archive_import_edit_and_export(tmp_path: Path) -> None:
    workbook = tmp_path / "translated.xlsx"
    _translated_workbook(workbook)

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Archive", "type": "QA"}).json()
        with workbook.open("rb") as fh:
            artifact = client.post(
                f"/api/projects/{project['id']}/files?kind=final_workbook",
                files={"file": ("translated.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()
        imported = client.post(f"/api/projects/{project['id']}/translations/import", json={"artifact_id": artifact["id"]}).json()
        assert imported["imported_count"] == 5
        entries = client.get(f"/api/projects/{project['id']}/translations").json()
        assert [entry["entry_key"] for entry in entries[:3]] == ["1", "2", "3"]

        updated = client.patch(
            f"/api/projects/{project['id']}/translations/{entries[0]['id']}",
            json={"target": "Claim"},
        ).json()
        assert updated["target"] == "Claim"
        export_json = client.get(f"/api/projects/{project['id']}/translations/export?format=json").json()
        assert export_json["entries"][0]["target"] == "Claim"
        export_xlsx = client.get(f"/api/projects/{project['id']}/translations/export?format=xlsx")
        assert export_xlsx.status_code == 200
        assert export_xlsx.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument")


def test_delivery_package_contains_only_task_outputs(tmp_path: Path) -> None:
    terms = tmp_path / "terms.xlsx"
    workbook = tmp_path / "translated.xlsx"
    _sample_term_workbook(terms)
    _translated_workbook(workbook)

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "小小战机", "type": "飞行射击", "description": "来源：测试文件"}).json()
        client.patch(f"/api/projects/{project['id']}", json={"prompt_text": "项目提示词：准确翻译，术语以项目术语表为准。"})
        with terms.open("rb") as fh:
            term_artifact = client.post(
                f"/api/projects/{project['id']}/files?kind=term_base",
                files={"file": ("terms.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()
        import_response = client.post(f"/api/projects/{project['id']}/glossary/import", json={"artifact_id": term_artifact["id"]})
        assert import_response.status_code == 200
        with workbook.open("rb") as fh:
            translated_artifact = client.post(
                f"/api/projects/{project['id']}/files?kind=final_workbook",
                files={"file": ("translated.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            ).json()
        run = client.post(
            "/api/runs",
            json={"project_id": project["id"], "kind": "qa", "language": "en", "input_artifact_id": translated_artifact["id"], "task_code": "QA"},
        ).json()
        qa_response = client.post(f"/api/runs/{run['id']}/qa")
        assert qa_response.status_code == 200, qa_response.text

        deliverables_response = client.get(f"/api/projects/{project['id']}/deliverables")
        assert deliverables_response.status_code == 200
        deliverables = deliverables_response.json()["deliverables"]
        assert len(deliverables) == 1
        assert deliverables[0]["task_label"] == f"QA-{run['id'].replace('run_', '')[:6]}"
        assert deliverables[0]["processed_rows"] == 5
        assert deliverables[0]["provider"] == "rules-only"
        assert deliverables[0]["model"] == "-"
        assert deliverables[0]["status"] == "passed"

        package_response = client.post(f"/api/projects/{project['id']}/delivery-package?run_id={run['id']}")
        assert package_response.status_code == 200, package_response.text
        package = package_response.json()
        filenames = [item["filename"] for item in package["files"]]
        assert len(filenames) == 2
        assert re.fullmatch(r"小小战机_EN_\d{12}_QA-[0-9a-f]{6}_[0-9a-f]{12}_final\.xlsx", filenames[0])
        assert re.fullmatch(r"小小战机_EN_\d{12}_QA-[0-9a-f]{6}_[0-9a-f]{12}_changes\.xlsx", filenames[1])
        assert not any("readback_gate" in filename for filename in filenames)
        assert not any(
            "input_copy" in filename
            or "manifest" in filename
            or "jsonl" in filename
            or "project_meta" in filename
            or "translation_prompt" in filename
            or "glossary" in filename
            for filename in filenames
        )
        for item in package["files"]:
            assert Path(item["path"]).exists()
            assert item["download_url"].endswith(item["filename"])
        refreshed = client.get(f"/api/projects/{project['id']}/deliverables").json()["deliverables"][0]
        assert refreshed["files"]["final"]["download_url"].endswith("_final.xlsx")
        assert refreshed["files"]["changes"]["download_url"].endswith("_changes.xlsx")
