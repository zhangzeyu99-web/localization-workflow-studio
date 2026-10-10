from __future__ import annotations

import json
import os
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.db as db
from app.main import app
from conftest import reset_data_root


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()


def _create_project(client: TestClient, name: str) -> dict:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 200, response.text
    return response.json()


def _upload_bytes(
    client: TestClient,
    project_id: str,
    filename: str,
    content: bytes,
    kind: str,
    mime: str = "application/octet-stream",
) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/files?kind={kind}",
        files={"file": (filename, content, mime)},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _workbook_bytes(sheets: list[tuple[str, list[list[object]]]]) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets:
        worksheet = workbook.create_sheet(title)
        for row in rows:
            worksheet.append(row)
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def _duplicate_glossary_content() -> bytes:
    return _workbook_bytes([("Glossary", [
        ["ID", "CN", "EN", "FR", "DE", "分类", "备注"],
        ["823", "传说 · 徽章", "Legend Badge", "Insigne", "Abzeichen", "道具", "保留原译"],
        ["824", "传说·徽章", "Legend Badge", "Autre insigne", "Abzeichen", "道具", "另一译法"],
        [None, None, None, None, None, None, None],
        ["827", "史诗 · 徽章", "Epic Badge", "Épique", "Episch", "道具", ""],
        ["828", "史诗·徽章", "Epic Badge", "Autre épique", "Episch", "道具", ""],
        ["900", "金币", "Gold", "", "Gold", "货币", ""],
    ])])


def test_glossary_conflicts_are_grouped_and_explicit_row_ignores_preserve_other_terms() -> None:
    content = _duplicate_glossary_content()
    with TestClient(app) as client:
        project = _create_project(client, "resolved glossary rows")
        artifact = _upload_bytes(client, project["id"], "terms.xlsx", content, "term_base")
        endpoint = f"/api/projects/{project['id']}/glossary/import"
        request = {"artifact_id": artifact["id"], "confirmed_glossary": True}
        unresolved = client.post(f"{endpoint}/analyze", json=request)
        assert unresolved.status_code == 200, unresolved.text
        preview = unresolved.json()
        assert preview["summary"]["conflict"] == 2
        assert preview["summary"]["conflict_records"] == 12
        assert [{row["row_key"] for row in group["rows"]} for group in preview["conflict_groups"]] == [
            {"row:2", "row:3"}, {"row:5", "row:6"},
        ]
        assert preview["conflict_groups"][0]["rows"][1]["targets"]["fr"] == "Autre insigne"
        blocked = client.post(f"{endpoint}/commit", json={"token": preview["token"]})
        assert blocked.status_code == 409, blocked.text
        resolved = client.post(f"{endpoint}/analyze", json={
            **request,
            "row_decisions": [{"row_key": key, "action": "ignore"} for key in ("row:3", "row:6")],
        })
        assert resolved.status_code == 200, resolved.text
        preview = resolved.json()
        assert preview["can_commit"] is True
        assert preview["summary"]["conflict"] == 0
        assert preview["summary"]["ignored_rows"] == 2
        assert preview["summary"]["insert"] == 8
        assert preview["summary"]["skip"] == 1
        committed = client.post(f"{endpoint}/commit", json={"token": preview["token"]})
        assert committed.status_code == 200, committed.text
        terms = db.list_glossary_terms(project["id"])
        assert len(terms) == 8
        assert {term["term_key"] for term in terms} == {"823", "827", "900"}
        assert next(term["target"] for term in terms if term["term_key"] == "823" and term["language"] == "fr") == "Insigne"
        assert Path(db.get_artifact(artifact["id"])["path"]).read_bytes() == content
        with db.connect() as connection:
            stored = connection.execute("SELECT request_json FROM archive_import_batches WHERE id = ?", (preview["batch_id"],)).fetchone()
        assert [decision["row_key"] for decision in json.loads(stored["request_json"])["row_decisions"]] == ["row:3", "row:6"]


def test_glossary_row_edits_are_revalidated_across_all_selected_languages() -> None:
    with TestClient(app) as client:
        project = _create_project(client, "edited glossary rows")
        artifact = _upload_bytes(client, project["id"], "terms.xlsx", _duplicate_glossary_content(), "term_base")
        endpoint = f"/api/projects/{project['id']}/glossary/import"
        request = {"artifact_id": artifact["id"], "confirmed_glossary": True, "row_decisions": [
            {"row_key": "row:3", "action": "edit", "source": "传说徽章（特殊）", "note": "用户修订", "targets": {"fr": "Insigne spécial"}},
            {"row_key": "row:6", "action": "ignore"},
        ]}
        resolved = client.post(f"{endpoint}/analyze", json=request)
        assert resolved.status_code == 200, resolved.text
        preview = resolved.json()
        assert preview["conflict_groups"] == []
        assert preview["summary"]["ignored_rows"] == 1
        assert preview["summary"]["insert"] == 11
        committed = client.post(f"{endpoint}/commit", json={"token": preview["token"]})
        assert committed.status_code == 200, committed.text
        edited_terms = [row for row in db.list_glossary_terms(project["id"]) if row["term_key"] == "824"]
        assert len(edited_terms) == 3
        assert {row["source"] for row in edited_terms} == {"传说徽章（特殊）"}
        assert {row["note"] for row in edited_terms} == {"用户修订"}
        assert next(row["target"] for row in edited_terms if row["language"] == "fr") == "Insigne spécial"
        repeated = client.post(f"{endpoint}/analyze", json=request)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["summary"]["unchanged"] == 11
        still_conflicting = client.post(f"{endpoint}/analyze", json={
            **request, "row_decisions": [{"row_key": "row:3", "action": "edit", "source": "史诗·徽章"}],
        })
        assert still_conflicting.status_code == 200, still_conflicting.text
        assert still_conflicting.json()["can_commit"] is False


@pytest.mark.parametrize("decisions", [
    [{"row_key": "row:999", "action": "ignore"}],
    [{"row_key": "row:2", "action": "ignore"}, {"row_key": "row:2", "action": "edit", "source": "不同"}],
    [{"row_key": "row:2", "action": "edit", "source": "  "}],
    [{"row_key": "row:2", "action": "edit", "targets": {"ko": "잘못된 언어"}}],
    [{"row_key": "row:2", "action": "edit", "targets": {"unknown": "Bad language"}}],
])
def test_glossary_invalid_row_decisions_fail_without_writing_terms(decisions: list[dict]) -> None:
    with TestClient(app) as client:
        project = _create_project(client, "invalid glossary decisions")
        artifact = _upload_bytes(client, project["id"], "terms.xlsx", _duplicate_glossary_content(), "term_base")
        result = client.post(f"/api/projects/{project['id']}/glossary/import/analyze", json={
            "artifact_id": artifact["id"], "confirmed_glossary": True, "row_decisions": decisions,
        })
    assert result.status_code == 400, result.text
    assert result.json()["detail"]["code"] == "invalid_row_decision"
    assert db.list_glossary_terms(project["id"]) == []


@pytest.mark.parametrize(("languages", "target_column"), [([], None), (["en", "fr"], None), (["en"], "target")])
def test_glossary_json_row_keys_use_original_array_positions_before_language_filtering(languages: list[str], target_column: str | None) -> None:
    mappings = [
        {"term_key": "A", "source": "相同", "language": "en", "target": "First"},
        None,
        {"term_key": "A", "source": "相同", "language": "fr", "target": "Premier"},
        {"term_key": "B", "source": "相 同", "language": "en", "target": "Second"},
    ]
    with TestClient(app) as client:
        project = _create_project(client, "json glossary row positions")
        artifact = _upload_bytes(client, project["id"], "terms.json", json.dumps(mappings).encode("utf-8"), "term_base")
        endpoint = f"/api/projects/{project['id']}/glossary/import"
        request = {"artifact_id": artifact["id"], "confirmed_glossary": True, "languages": languages, "target_column": target_column}
        original = client.post(f"{endpoint}/analyze", json=request)
        assert original.status_code == 200, original.text
        expected_keys = {"row:1", "row:4"} if target_column else {"row:1", "row:3", "row:4"}
        assert {row["row_key"] for row in original.json()["conflict_groups"][0]["rows"]} == expected_keys
        resolved = client.post(f"{endpoint}/analyze", json={
            **request, "row_decisions": [{"row_key": "row:4", "action": "ignore"}],
        })
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["summary"]["conflict"] == 0
        assert resolved.json()["summary"]["insert"] == (1 if target_column else 2)
        assert resolved.json()["summary"]["ignored_rows"] == 1


def test_glossary_row_decisions_keep_protection_and_state_drift_guards() -> None:
    content = "ID,CN,EN\nA,战力,New Power\nB,金币,Gold\n".encode("utf-8-sig")
    with TestClient(app) as client:
        project = _create_project(client, "glossary decision protection")
        seeded = client.post(f"/api/projects/{project['id']}/glossary", json={
            "term_key": "A", "source": "战力", "target": "Manual Power", "language": "en",
        })
        assert seeded.status_code == 200, seeded.text
        artifact = _upload_bytes(client, project["id"], "terms.csv", content, "term_base")
        endpoint = f"/api/projects/{project['id']}/glossary/import"
        request = {"artifact_id": artifact["id"], "confirmed_glossary": True, "row_decisions": [
            {"row_key": "row:2", "action": "edit", "targets": {"en": "Edited Power"}},
        ]}
        protected = client.post(f"{endpoint}/analyze", json=request)
        assert protected.status_code == 200, protected.text
        assert protected.json()["conflict_groups"][0]["codes"] == ["protected_source"]
        blocked = client.post(f"{endpoint}/commit", json={"token": protected.json()["token"]})
        assert blocked.status_code == 409, blocked.text
        resolved = client.post(f"{endpoint}/analyze", json={
            **request, "row_decisions": [{"row_key": "row:2", "action": "ignore"}],
        })
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["can_commit"] is True
        assert resolved.json()["summary"]["insert"] == 1
        changed = client.post(f"/api/projects/{project['id']}/glossary", json={
            "term_key": "C", "source": "宝石", "target": "Gem", "language": "en",
        })
        assert changed.status_code == 200, changed.text
        stale = client.post(f"{endpoint}/commit", json={"token": resolved.json()["token"]})
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"]["code"] == "state_drift"
        assert db.get_glossary_term(seeded.json()["id"])["target"] == "Manual Power"


def test_glossary_conflict_rows_are_not_truncated_by_the_change_sample_limit() -> None:
    mappings = [
        {"ID": f"{index}-{variant}", "CN": f"徽章{index}", "EN": "Badge", "FR": "Insigne"}
        for index in range(30) for variant in range(2)
    ]
    with TestClient(app) as client:
        project = _create_project(client, "complete glossary conflict groups")
        artifact = _upload_bytes(client, project["id"], "terms.json", json.dumps(mappings).encode("utf-8"), "term_base")
        result = client.post(f"/api/projects/{project['id']}/glossary/import/analyze", json={
            "artifact_id": artifact["id"], "confirmed_glossary": True,
        })
    assert result.status_code == 200, result.text
    preview = result.json()
    assert len(preview["changes"]) == 50
    assert len(preview["conflict_groups"]) == 30
    assert sum(len(group["rows"]) for group in preview["conflict_groups"]) == 60
    assert preview["conflict_groups"][-1]["rows"][-1]["row_key"] == "row:60"


def test_glossary_shared_field_edit_keeps_unselected_protected_language_resolvable() -> None:
    with TestClient(app) as client:
        project = _create_project(client, "shared protected glossary decisions")
        endpoint = f"/api/projects/{project['id']}/glossary/import"
        initial = _upload_bytes(client, project["id"], "initial.csv", "ID,CN,EN,FR,备注\nA,战力,Power,Puissance,旧备注\n".encode("utf-8-sig"), "term_base")
        imported = client.post(endpoint, json={"artifact_id": initial["id"]})
        assert imported.status_code == 200, imported.text
        french = next(term for term in db.list_glossary_terms(project["id"]) if term["language"] == "fr")
        protected = client.patch(f"/api/projects/{project['id']}/glossary/{french['id']}", json={"target": "Puissance"})
        assert protected.status_code == 200, protected.text
        request = {
            "artifact_id": initial["id"], "confirmed_glossary": True, "languages": ["en"],
            "row_decisions": [{"row_key": "row:2", "action": "edit", "note": ""}],
        }
        analysis = client.post(f"{endpoint}/analyze", json=request)
        assert analysis.status_code == 200, analysis.text
        assert analysis.json()["summary"]["conflict"] == 1
        assert analysis.json()["conflict_groups"][0]["rows"][0]["row_key"] == "row:2"
        assert analysis.json()["conflicts"][0]["language"] == "fr"
        allowed = client.post(f"{endpoint}/analyze", json={**request, "override_protected": True})
        assert allowed.status_code == 200, allowed.text
        committed = client.post(f"{endpoint}/commit", json={"token": allowed.json()["token"]})
        assert committed.status_code == 200, committed.text
        terms = [db.get_glossary_term(term["id"]) for term in imported.json()["terms"]]
        assert {term["note"] for term in terms} == {""}
        assert {term["language"]: term["target"] for term in terms} == {"en": "Power", "fr": "Puissance"}
        assert db.get_glossary_term(french["id"])["confirmed"] is False


@pytest.mark.parametrize("column_field", ["target_column", "target_alt_column"])
def test_glossary_explicit_target_column_cannot_be_assigned_to_multiple_languages(column_field: str) -> None:
    with TestClient(app) as client:
        project = _create_project(client, "single mapped glossary language")
        content = _workbook_bytes([("Glossary", [["ID", "CN", "EN", "FR"], ["A", "金币", "Gold", "Or"]])])
        artifact = _upload_bytes(client, project["id"], "terms.xlsx", content, "term_base")
        endpoint = f"/api/projects/{project['id']}/glossary/import/analyze"
        request = {"artifact_id": artifact["id"], "confirmed_glossary": True, column_field: "EN"}
        blocked = client.post(endpoint, json={**request, "languages": ["en", "fr"]})
        assert blocked.status_code == 400, blocked.text
        assert "指定单个译文列时只能选择一种目标语言" in blocked.json()["detail"]["message"]
        allowed = client.post(endpoint, json={**request, "languages": ["en", "EN"]})
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["languages"] == ["en"]
        assert allowed.json()["summary"]["insert"] == 1
        assert db.list_glossary_terms(project["id"]) == []


@pytest.mark.parametrize("format", ["xlsx", "csv", "json"])
@pytest.mark.parametrize("explicit_target", [False, True])
def test_glossary_nonempty_rows_without_source_are_resolvable_not_silently_omitted(format: str, explicit_target: bool) -> None:
    if format == "xlsx":
        content = _workbook_bytes([("Glossary", [["ID", "CN", "EN"], ["A", "金币", "Gold"], [], ["B", "", "Gem"]])])
    elif format == "csv":
        content = "ID,CN,EN\nA,金币,Gold\n,,\nB,,Gem\n".encode("utf-8-sig")
    else:
        content = json.dumps([{"ID": "A", "CN": "金币", "EN": "Gold"}, {}, {"ID": "B", "CN": "", "EN": "Gem"}]).encode("utf-8")
    invalid_key = "row:3" if format == "json" else "row:4"
    with TestClient(app) as client:
        project = _create_project(client, "glossary missing source row")
        artifact = _upload_bytes(client, project["id"], f"terms.{format}", content, "term_base")
        endpoint = f"/api/projects/{project['id']}/glossary/import"
        request = {"artifact_id": artifact["id"], "confirmed_glossary": True}
        if explicit_target:
            request.update({"target_column": "EN", "languages": ["en"]})
        initial = client.post(f"{endpoint}/analyze", json=request)
        assert initial.status_code == 200, initial.text
        preview = initial.json()
        assert preview["can_commit"] is False
        assert preview["summary"]["insert"] == 1
        assert preview["summary"]["conflict"] == 1
        assert preview["conflict_groups"][0]["codes"] == ["missing_source"]
        assert preview["conflict_groups"][0]["rows"][0]["row_key"] == invalid_key
        ignored = client.post(f"{endpoint}/analyze", json={
            **request, "row_decisions": [{"row_key": invalid_key, "action": "ignore"}],
        })
        assert ignored.status_code == 200, ignored.text
        assert ignored.json()["can_commit"] is True
        assert ignored.json()["summary"]["ignored_rows"] == 1
        edited = client.post(f"{endpoint}/analyze", json={
            **request, "row_decisions": [{"row_key": invalid_key, "action": "edit", "source": "宝石"}],
        })
        assert edited.status_code == 200, edited.text
        assert edited.json()["can_commit"] is True
        assert edited.json()["summary"]["insert"] == 2
        committed = client.post(f"{endpoint}/commit", json={"token": edited.json()["token"]})
        assert committed.status_code == 200, committed.text
        assert {(term["source"], term["target"]) for term in db.list_glossary_terms(project["id"])} == {("金币", "Gold"), ("宝石", "Gem")}


@pytest.mark.parametrize("invalid_language", ["", "not-a-language"])
@pytest.mark.parametrize("explicit_target", [False, True])
def test_glossary_invalid_json_language_rows_need_explicit_ignore(invalid_language: str, explicit_target: bool) -> None:
    content = json.dumps([
        {"term_key": "A", "source": "金币", "language": "en", "target": "Gold"},
        None,
        {"term_key": "B", "source": "宝石", "language": invalid_language, "target": "Gem"},
    ]).encode("utf-8")
    with TestClient(app) as client:
        project = _create_project(client, "glossary invalid JSON language")
        artifact = _upload_bytes(client, project["id"], "terms.json", content, "term_base")
        endpoint = f"/api/projects/{project['id']}/glossary/import"
        request = {"artifact_id": artifact["id"], "confirmed_glossary": True, "languages": ["en"]}
        if explicit_target:
            request["target_column"] = "target"
        initial = client.post(f"{endpoint}/analyze", json=request)
        assert initial.status_code == 200, initial.text
        preview = initial.json()
        assert preview["can_commit"] is False
        assert preview["summary"]["insert"] == 1
        assert preview["summary"]["conflict"] == 1
        group = preview["conflict_groups"][0]
        assert group["codes"] == ["invalid_language"]
        assert group["rows"][0]["row_key"] == "row:3"
        assert group["rows"][0]["edit_blocked_reason"]
        assert list(group["rows"][0]["targets"].values()) == ["Gem"]
        falsely_edited = client.post(f"{endpoint}/analyze", json={
            **request, "row_decisions": [{"row_key": "row:3", "action": "edit", "source": "新宝石"}],
        })
        assert falsely_edited.status_code == 400, falsely_edited.text
        ignored = client.post(f"{endpoint}/analyze", json={
            **request, "row_decisions": [{"row_key": "row:3", "action": "ignore"}],
        })
        assert ignored.status_code == 200, ignored.text
        assert ignored.json()["can_commit"] is True
        assert ignored.json()["summary"]["ignored_rows"] == 1
        committed = client.post(f"{endpoint}/commit", json={"token": ignored.json()["token"]})
        assert committed.status_code == 200, committed.text
        assert [(term["source"], term["language"]) for term in db.list_glossary_terms(project["id"])] == [("金币", "en")]


@pytest.mark.parametrize("kind", ["missing_source", "invalid_language", "invalid_language_empty"])
def test_glossary_file_with_only_invalid_rows_still_offers_a_row_decision(kind: str) -> None:
    if kind == "missing_source":
        filename = "only-invalid.xlsx"
        content = _workbook_bytes([("Glossary", [["ID", "CN", "EN"], ["A", "", "Gold"]])])
    else:
        filename = "only-invalid.json"
        raw_language = "" if kind == "invalid_language_empty" else "unknown"
        content = json.dumps([{"term_key": "A", "source": "金币", "language": raw_language, "target": "Gold"}]).encode("utf-8")
    with TestClient(app) as client:
        project = _create_project(client, "only invalid glossary rows")
        artifact = _upload_bytes(client, project["id"], filename, content, "term_base")
        result = client.post(f"/api/projects/{project['id']}/glossary/import/analyze", json={
            "artifact_id": artifact["id"], "confirmed_glossary": True,
        })
    assert result.status_code == 200, result.text
    assert result.json()["can_commit"] is False
    assert result.json()["conflict_groups"][0]["codes"] == ["missing_source" if kind == "missing_source" else "invalid_language"]


@pytest.mark.parametrize(("file_state", "status", "code"), [
    ("missing", 404, "artifact_file_missing"), ("invalid", 400, "invalid_glossary_file"),
])
def test_glossary_analyze_reports_missing_or_invalid_files_without_server_error(
    tmp_path: Path, file_state: str, status: int, code: str,
) -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        project = _create_project(client, "unreadable glossary source")
        if file_state == "missing":
            artifact = db.add_artifact(project["id"], "missing.xlsx", tmp_path / "missing.xlsx", "term_base")
        else:
            artifact = _upload_bytes(client, project["id"], "broken.xlsx", b"not an xlsx archive", "term_base")
        result = client.post(f"/api/projects/{project['id']}/glossary/import/analyze", json={
            "artifact_id": artifact["id"], "confirmed_glossary": True,
        })
    assert result.status_code == status, result.text
    assert result.json()["detail"]["code"] == code
    assert db.get_artifact(artifact["id"])["id"] == artifact["id"]
