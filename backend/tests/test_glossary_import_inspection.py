from __future__ import annotations

import os
import json
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app import db
from app.main import app
from conftest import reset_data_root


@pytest.fixture(autouse=True)
def reset_state() -> None:
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()


def workbook_bytes(sheets: dict[str, list[list]]) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def test_large_glossary_upload_inspects_all_languages_without_archiving() -> None:
    content = workbook_bytes({"术语": [["ID", "CN", "EN", "FR", "分类"]] + [
        [str(index), f"术语{index}", f"Term {index}", "", "道具"] for index in range(1001)
    ]})
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "large glossary"}).json()
        url = f"/api/projects/{project['id']}"
        response = client.post(f"{url}/files?kind=term_base", files={"file": ("terms.xlsx", content)})
        assert response.status_code == 200, response.text
        artifact = response.json()
        response = client.post(f"{url}/glossary/import/inspect", json={"artifact_id": artifact["id"]})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["languages"] == ["en", "fr"]
        assert result["sheet"] == "术语"
        assert result["source_rows"] == 1001
        assert result["warnings"]
        assert Path(db.get_artifact(artifact["id"])["path"]).read_bytes() == content
        assert client.get(f"{url}/glossary").json() == []
        assert client.get(f"{url}/glossary/import/batches").json()["batches"] == []
        preview = client.post(f"{url}/glossary/import-preview", json={"artifact_id": artifact["id"]})
        assert preview.status_code == 200, preview.text


def test_inspection_requires_sheet_choice_and_enforces_project_ownership() -> None:
    content = workbook_bytes({
        "英语": [["ID", "CN", "EN"], ["1", "剑", "Sword"]],
        "法语": [["ID", "CN", "FR"], ["1", "剑", "Épée"]],
    })
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "sheets"}).json()
        url = f"/api/projects/{project['id']}"
        artifact = client.post(f"{url}/files?kind=term_base", files={"file": ("terms.xlsx", content)}).json()
        payload = {"artifact_id": artifact["id"]}
        response = client.post(f"{url}/glossary/import/inspect", json=payload)
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "sheet_selection_required"
        response = client.post(f"{url}/glossary/import/inspect", json={**payload, "sheet": "法语"})
        assert response.status_code == 200, response.text
        assert response.json()["languages"] == ["fr"]
        other = client.post("/api/projects", json={"name": "other"}).json()
        response = client.post(f"/api/projects/{other['id']}/glossary/import/inspect", json=payload)
        assert response.status_code == 404


@pytest.mark.parametrize("filename,content,expected", [
    ("terms.csv", "ID,CN,PT,DE\n1,剑,Espada,Schwert\n".encode("utf-8"), ["de", "pt"]),
    ("terms.json", '[{"term_key":"1","source":"剑","target":"Épée","language":"fr"}]'.encode("utf-8"), ["fr"]),
    ("generic.csv", "ID,CN,target\n1,剑,Sword\n".encode("utf-8"), []),
    ("generic.xlsx", workbook_bytes({"术语": [["ID", "CN", "target"], ["1", "剑", "Sword"]]}), []),
])
def test_inspection_uses_real_headers_or_explicit_json_languages(filename: str, content: bytes, expected: list[str]) -> None:
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "formats"}).json()
        url = f"/api/projects/{project['id']}"
        artifact = client.post(f"{url}/files?kind=term_base", files={"file": (filename, content)}).json()
        response = client.post(f"{url}/glossary/import/inspect", json={"artifact_id": artifact["id"]})
        assert response.status_code == 200, response.text
        assert response.json()["languages"] == expected
        assert response.json()["source_rows"] == 1


def test_inspection_respects_explicit_target_column() -> None:
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "mapped target"}).json()
        url = f"/api/projects/{project['id']}"
        content = "ID,CN,EN,FR\n1,剑,Sword,Épée\n".encode("utf-8")
        artifact = client.post(f"{url}/files?kind=term_base", files={"file": ("terms.csv", content)}).json()
        payload = {"artifact_id": artifact["id"], "target_column": "EN"}
        response = client.post(f"{url}/glossary/import/inspect", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["languages"] == ["en"]
        response = client.post(f"{url}/glossary/import/inspect", json={**payload, "target_column": "missing"})
        assert response.status_code == 400


@pytest.mark.parametrize("other_rows", [
    [["ID", "CN", "EN"]],
    [["CN", "说明"], ["剑", "这页只有备注，没有译文"]],
    [["ID", "CN", "target"], ["1", "剑", "Sword"]],
])
def test_inspection_selects_the_same_data_sheet_as_analysis(other_rows: list[list]) -> None:
    content = workbook_bytes({
        "模板或备注": other_rows,
        "术语": [["ID", "CN", "FR"], ["1", "剑", "Épée"]],
    })
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "sheet consistency"}).json()
        url = f"/api/projects/{project['id']}"
        uploaded = client.post(f"{url}/files?kind=term_base", files={"file": ("terms.xlsx", content)})
        assert uploaded.status_code == 200, uploaded.text
        artifact = uploaded.json()
        payload = {"artifact_id": artifact["id"]}
        inspected = client.post(f"{url}/glossary/import/inspect", json=payload)
        assert inspected.status_code == 200, inspected.text
        assert inspected.json()["sheet"] == "术语"
        assert inspected.json()["languages"] == ["fr"]
        assert inspected.json()["source_rows"] == 1
        analyzed = client.post(f"{url}/glossary/import/analyze", json={
            **payload, "confirmed_glossary": True, "languages": inspected.json()["languages"],
            "sheet": inspected.json()["sheet"],
        })
        assert analyzed.status_code == 200, analyzed.text
        assert analyzed.json()["sheet"] == inspected.json()["sheet"]
        assert analyzed.json()["can_commit"] is True
        assert analyzed.json()["summary"]["insert"] == 1
        assert analyzed.json()["changes"][0]["target"] == "Épée"
        assert Path(db.get_artifact(artifact["id"])["path"]).read_bytes() == content
        assert client.get(f"{url}/glossary").json() == []


@pytest.mark.parametrize("unreadable", ["missing", "corrupt"])
def test_inspection_reports_unreadable_artifacts_without_server_error(unreadable: str) -> None:
    valid_content = workbook_bytes({"术语": [["ID", "CN", "EN"], ["1", "剑", "Sword"]]})
    content = b"not an xlsx archive" if unreadable == "corrupt" else valid_content
    with TestClient(app, raise_server_exceptions=False) as client:
        project = client.post("/api/projects", json={"name": "unreadable source"}).json()
        url = f"/api/projects/{project['id']}"
        uploaded = client.post(f"{url}/files?kind=term_base", files={"file": ("terms.xlsx", content)})
        assert uploaded.status_code == 200, uploaded.text
        artifact = uploaded.json()
        path = Path(db.get_artifact(artifact["id"])["path"])
        if unreadable == "missing":
            path.unlink()
        inspected = client.post(f"{url}/glossary/import/inspect", json={"artifact_id": artifact["id"]})
        assert inspected.status_code == (404 if unreadable == "missing" else 400), inspected.text
        assert inspected.json()["detail"]["code"] == ("artifact_file_missing" if unreadable == "missing" else "invalid_glossary_file")
        assert "message" in inspected.json()["detail"]
        assert db.get_artifact(artifact["id"])["id"] == artifact["id"]
        if unreadable == "corrupt":
            assert path.read_bytes() == content
        assert client.get(f"{url}/glossary").json() == []
        assert client.get(f"{url}/glossary/import/batches").json()["batches"] == []


def test_inspection_offers_nonempty_sheets_with_missing_source_for_resolution() -> None:
    content = workbook_bytes({
        "正常术语": [["ID", "CN", "FR"], ["1", "剑", "Épée"]],
        "待补中文": [["ID", "CN", "EN"], ["2", "", "Gem"]],
        "空模板": [["ID", "CN", "EN"]],
    })
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "source resolution sheets"}).json()
        url = f"/api/projects/{project['id']}"
        artifact = client.post(f"{url}/files?kind=term_base", files={"file": ("terms.xlsx", content)}).json()
        payload = {"artifact_id": artifact["id"]}
        inspected = client.post(f"{url}/glossary/import/inspect", json=payload)
        assert inspected.status_code == 400, inspected.text
        assert inspected.json()["detail"]["code"] == "sheet_selection_required"
        assert inspected.json()["detail"]["candidates"] == ["正常术语", "待补中文"]
        inspected = client.post(f"{url}/glossary/import/inspect", json={**payload, "sheet": "待补中文"})
        assert inspected.status_code == 200, inspected.text
        assert inspected.json()["languages"] == ["en"]
        assert inspected.json()["source_rows"] == 1
        assert any("没有非空源文行" in warning for warning in inspected.json()["warnings"])
        analyzed = client.post(f"{url}/glossary/import/analyze", json={
            **payload, "sheet": inspected.json()["sheet"],
            "languages": inspected.json()["languages"], "confirmed_glossary": True,
        })
        assert analyzed.status_code == 200, analyzed.text
        assert analyzed.json()["can_commit"] is False
        assert analyzed.json()["conflict_groups"][0]["codes"] == ["missing_source"]
        assert Path(db.get_artifact(artifact["id"])["path"]).read_bytes() == content
        assert client.get(f"{url}/glossary").json() == []


@pytest.mark.parametrize("invalid_language", ["", "not-a-language"])
@pytest.mark.parametrize("with_valid_row", [True, False])
def test_inspection_warns_about_invalid_json_languages_without_blocking_resolution(
    invalid_language: str, with_valid_row: bool,
) -> None:
    rows = [{"term_key": "1", "source": "剑", "target": "Épée", "language": "fr"}] if with_valid_row else []
    rows.append({"term_key": "2", "source": "宝石", "target": "Gem", "language": invalid_language})
    content = json.dumps(rows).encode("utf-8")
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "invalid language discovery"}).json()
        url = f"/api/projects/{project['id']}"
        artifact = client.post(f"{url}/files?kind=term_base", files={"file": ("terms.json", content)}).json()
        payload = {"artifact_id": artifact["id"]}
        inspected = client.post(f"{url}/glossary/import/inspect", json=payload)
        assert inspected.status_code == 200, inspected.text
        assert inspected.json()["languages"] == (["fr"] if with_valid_row else [])
        assert inspected.json()["source_rows"] == len(rows)
        assert any("language" in warning for warning in inspected.json()["warnings"])
        assert client.get(f"{url}/glossary/import/batches").json()["batches"] == []
        analyzed = client.post(f"{url}/glossary/import/analyze", json={
            **payload, "confirmed_glossary": True,
            "languages": inspected.json()["languages"] or ["en"],
        })
        assert analyzed.status_code == 200, analyzed.text
        assert analyzed.json()["can_commit"] is False
        assert analyzed.json()["conflict_groups"][0]["codes"] == ["invalid_language"]
        assert Path(db.get_artifact(artifact["id"])["path"]).read_bytes() == content
        assert client.get(f"{url}/glossary").json() == []


def test_inspection_counts_all_nonempty_rows_including_rows_needing_resolution() -> None:
    content = json.dumps([
        {"term_key": "1", "source": "剑", "target": "Sword", "language": "en"},
        {}, None,
        {"term_key": "2", "source": "", "target": "Gem", "language": "en"},
        {"term_key": "3", "source": "金币", "target": "Gold", "language": "bad-code"},
        {"term_key": "", "source": "", "target": "", "language": ""},
    ]).encode("utf-8")
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "inspection row count"}).json()
        url = f"/api/projects/{project['id']}"
        artifact = client.post(f"{url}/files?kind=term_base", files={"file": ("terms.json", content)}).json()
        payload = {"artifact_id": artifact["id"]}
        inspected = client.post(f"{url}/glossary/import/inspect", json=payload)
        assert inspected.status_code == 200, inspected.text
        assert inspected.json()["source_rows"] == 3
        analyzed = client.post(f"{url}/glossary/import/analyze", json={
            **payload, "languages": ["en"], "confirmed_glossary": True,
        })
        assert analyzed.status_code == 200, analyzed.text
        assert analyzed.json()["summary"]["source_rows"] == inspected.json()["source_rows"]
        assert client.get(f"{url}/glossary").json() == []
