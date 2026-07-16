from __future__ import annotations

import json
import os
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.db as db
import app.routers.glossary as glossary_router
from app.main import app
from app.workflow.glossary_backfill import backfill_project_glossary_from_final
from conftest import reset_data_root


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()


def _create_project(client: TestClient, name: str = "glossary archive") -> dict:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 200, response.text
    return response.json()


def _workbook_bytes(rows: list[list[object]], sheet: str = "Glossary") -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    for row in rows:
        worksheet.append(row)
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def _upload_bytes(
    client: TestClient,
    project_id: str,
    filename: str,
    content: bytes,
    *,
    kind: str = "term_base",
) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/files?kind={kind}",
        files={"file": (filename, content, "application/octet-stream")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _upload_rows(
    client: TestClient,
    project_id: str,
    rows: list[list[object]],
    *,
    filename: str = "glossary.xlsx",
    kind: str = "term_base",
) -> dict:
    return _upload_bytes(client, project_id, filename, _workbook_bytes(rows), kind=kind)


def _analyze(
    client: TestClient,
    project_id: str,
    artifact_id: str,
    **overrides: object,
) -> dict:
    payload: dict[str, object] = {
        "artifact_id": artifact_id,
        "confirmed_glossary": True,
        "mode": "merge",
    }
    payload.update(overrides)
    response = client.post(f"/api/projects/{project_id}/glossary/import/analyze", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _commit(client: TestClient, project_id: str, token: str) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/glossary/import/commit",
        json={"token": token},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _all_terms(project_id: str) -> list[dict]:
    with db.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM glossary_terms WHERE project_id = ? ORDER BY language, term_key, id",
                (project_id,),
            ).fetchall()
        ]


def _state_version(project_id: str) -> int:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT version FROM archive_state_versions WHERE project_id = ? AND kind = 'glossary'",
            (project_id,),
        ).fetchone()
    return int(row["version"] if row else 0)


@pytest.mark.parametrize("format_name", ["xlsx", "csv", "json"])
def test_safe_glossary_roundtrip_supports_xlsx_csv_json_and_never_persists_target_alt(
    format_name: str,
) -> None:
    rows = [["ID", "CN", "EN", "EN2"], ["T-1", "战力", "Combat Power", "CP"]]
    if format_name == "xlsx":
        filename = "glossary.xlsx"
        content = _workbook_bytes(rows)
    elif format_name == "csv":
        filename = "glossary.csv"
        content = "ID,CN,EN,EN2\nT-1,战力,Combat Power,CP\n".encode("utf-8-sig")
    else:
        filename = "glossary.json"
        content = json.dumps(
            [{"ID": "T-1", "CN": "战力", "EN": "Combat Power", "EN2": "CP"}],
            ensure_ascii=False,
        ).encode("utf-8")

    with TestClient(app) as client:
        project = _create_project(client, f"safe glossary {format_name}")
        artifact = _upload_bytes(client, project["id"], filename, content)
        analysis = _analyze(client, project["id"], artifact["id"], language="en")
        assert analysis["can_commit"] is True
        assert analysis["summary"]["insert"] == 1
        committed = _commit(client, project["id"], analysis["token"])
        exported = client.get(f"/api/projects/{project['id']}/glossary/export?format=json")

    assert committed["kind"] == "glossary"
    assert committed["changed_count"] == 1
    term = committed["terms"][0]
    assert term["source"] == "战力"
    assert term["target"] == "Combat Power"
    assert term["target_alt"] == ""
    assert term["source_type"] == "imported"
    assert term["review_status"] == "approved"
    assert term["confirmed"] is True
    assert term["active"] == 1
    assert exported.status_code == 200, exported.text
    assert exported.json()["terms"][0]["target_alt"] == ""


def test_single_language_glossary_shared_update_keeps_wide_concept_and_rolls_back_all_siblings() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload_rows(
            client,
            project["id"],
            [
                ["ID", "CN", "EN", "KO", "FR", "分类", "备注"],
                ["T-1", "旧术语", "Old EN", "오래된 KO", "Ancien FR", "旧分类", "旧备注"],
            ],
            filename="shared-glossary-base.xlsx",
        )
        base_analysis = _analyze(client, project["id"], base["id"])
        _commit(client, project["id"], base_analysis["token"])
        with db.connect() as conn:
            conn.execute(
                "UPDATE glossary_terms SET active = 0 WHERE project_id = ? AND language = 'fr'",
                (project["id"],),
            )
        before = {(row["language"], row["term_key"]): row for row in _all_terms(project["id"])}

        update = _upload_rows(
            client,
            project["id"],
            [["ID", "CN", "EN", "分类", "备注"], ["T-1", "新术语", "New EN", "新分类", "新备注"]],
            filename="shared-glossary-update.xlsx",
        )
        analysis = _analyze(
            client,
            project["id"],
            update["id"],
            languages=["en"],
            dataset_key=base_analysis["dataset_key"],
        )
        with db.connect() as conn:
            items = conn.execute(
                "SELECT language, entity_id, planned_action FROM archive_import_batch_items "
                "WHERE batch_id = ? ORDER BY ordinal",
                (analysis["batch_id"],),
            ).fetchall()
        committed = _commit(client, project["id"], analysis["token"])
        wide = client.get(
            f"/api/projects/{project['id']}/glossary/wide",
            params={"languages": "en,ko"},
        )
        with db.connect() as conn:
            revision_count = conn.execute(
                "SELECT COUNT(*) FROM archive_import_revisions WHERE batch_id = ?",
                (analysis["batch_id"],),
            ).fetchone()[0]
        changed = {(row["language"], row["term_key"]): row for row in _all_terms(project["id"])}
        rolled_back = client.post(
            f"/api/projects/{project['id']}/glossary/import/batches/{analysis['batch_id']}/rollback"
        )

    assert analysis["can_commit"] is True
    assert {row["language"] for row in items} == {"en", "ko", "fr"}
    assert all(row["planned_action"] == "update" for row in items)
    assert len(items) == len({row["entity_id"] for row in items}) == 3
    assert committed["changed_count"] == 3
    assert revision_count == 3
    assert wide.status_code == 200, wide.text
    assert wide.json()["total_rows"] == 1
    wide_row = wide.json()["rows"][0]
    assert wide_row["source"] == "新术语"
    assert wide_row["term_key"] == "T-1"
    assert wide_row["category"] == "新分类"
    assert wide_row["note"] == "新备注"
    assert wide_row["translations"]["en"]["target"] == "New EN"
    assert wide_row["translations"]["ko"]["target"] == "오래된 KO"
    assert {(row["source"], row["category"], row["note"]) for row in changed.values()} == {
        ("新术语", "新分类", "新备注")
    }
    assert changed[("fr", "T-1")]["active"] == 0
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["restored_count"] == 3
    restored = {(row["language"], row["term_key"]): row for row in _all_terms(project["id"])}
    for key in (("en", "T-1"), ("ko", "T-1"), ("fr", "T-1")):
        for field in ("source", "target", "category", "note", "active"):
            assert restored[key][field] == before[key][field]


def test_cross_language_shared_source_collision_blocks_glossary_batch_without_writes() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload_rows(
            client,
            project["id"],
            [
                ["ID", "CN", "EN", "KO"],
                ["T-1", "旧术语", "Old EN", "오래된 KO"],
                ["T-2", "占用术语", "", "충돌 KO"],
            ],
            filename="shared-glossary-collision-base.xlsx",
        )
        base_analysis = _analyze(client, project["id"], base["id"])
        _commit(client, project["id"], base_analysis["token"])
        before = _all_terms(project["id"])

        update = _upload_rows(
            client,
            project["id"],
            [["ID", "CN", "EN"], ["T-1", "占用术语", "New EN"]],
            filename="shared-glossary-collision-update.xlsx",
        )
        response = client.post(
            f"/api/projects/{project['id']}/glossary/import/analyze",
            json={
                "artifact_id": update["id"],
                "confirmed_glossary": True,
                "mode": "merge",
                "languages": ["en"],
                "dataset_key": base_analysis["dataset_key"],
            },
        )
        assert response.status_code == 200, response.text
        analysis = response.json()
        blocked = client.post(
            f"/api/projects/{project['id']}/glossary/import/commit",
            json={"token": analysis["token"]},
        )

    assert analysis["can_commit"] is False
    assert "concept_source_conflict" in {conflict["code"] for conflict in analysis["conflicts"]}
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "conflicts_present"
    assert _all_terms(project["id"]) == before


def test_same_glossary_id_with_inconsistent_shared_input_is_blocked() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload_rows(
            client,
            project["id"],
            [["ID", "CN", "EN", "KO"], ["T-1", "旧术语", "Old EN", "오래된 KO"]],
            filename="shared-glossary-input-base.xlsx",
        )
        base_analysis = _analyze(client, project["id"], base["id"])
        _commit(client, project["id"], base_analysis["token"])
        artifact = _upload_bytes(
            client,
            project["id"],
            "shared-glossary-input.json",
            json.dumps(
                [
                    {
                        "term_key": "T-1",
                        "source": "新术语一",
                        "target": "New EN",
                        "language": "en",
                        "category": "分类一",
                        "note": "备注一",
                    },
                    {
                        "term_key": "T-1",
                        "source": "新术语二",
                        "target": "New KO",
                        "language": "ko",
                        "category": "分类二",
                        "note": "备注二",
                    },
                ],
                ensure_ascii=False,
            ).encode("utf-8"),
        )
        analysis = _analyze(
            client,
            project["id"],
            artifact["id"],
            dataset_key=base_analysis["dataset_key"],
        )

    assert analysis["can_commit"] is False
    assert "shared_identity_mismatch" in {conflict["code"] for conflict in analysis["conflicts"]}


def test_empty_project_rejects_cross_language_same_source_with_different_glossary_ids() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        artifact = _upload_bytes(
            client,
            project["id"],
            "cross-language-glossary-source.json",
            json.dumps(
                [
                    {"term_key": "T-1", "source": "同一术语", "target": "One", "language": "en"},
                    {"term_key": "T-2", "source": "同一术语", "target": "Two", "language": "ko"},
                ],
                ensure_ascii=False,
            ).encode("utf-8"),
        )
        analysis = _analyze(client, project["id"], artifact["id"])
        blocked = client.post(
            f"/api/projects/{project['id']}/glossary/import/commit",
            json={"token": analysis["token"]},
        )

    assert analysis["can_commit"] is False
    assert "source_multiple_ids" in {conflict["code"] for conflict in analysis["conflicts"]}
    assert blocked.status_code == 409
    assert _all_terms(project["id"]) == []


def test_empty_project_rejects_cross_language_mixed_glossary_identity() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        artifact = _upload_bytes(
            client,
            project["id"],
            "cross-language-mixed-glossary.json",
            json.dumps(
                [
                    {"term_key": "T-1", "source": "同一术语", "target": "One", "language": "en"},
                    {"term_key": "", "source": "同一术语", "target": "Two", "language": "ko"},
                ],
                ensure_ascii=False,
            ).encode("utf-8"),
        )
        analysis = _analyze(client, project["id"], artifact["id"])

    assert analysis["can_commit"] is False
    assert "source_mixed_identity" in {conflict["code"] for conflict in analysis["conflicts"]}
    assert _all_terms(project["id"]) == []


def test_glossary_blank_target_with_existing_language_updates_shared_fields_only() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload_rows(
            client,
            project["id"],
            [
                ["ID", "CN", "EN", "KO", "分类", "备注"],
                ["T-1", "旧术语", "Old EN", "오래된 KO", "旧分类", "旧备注"],
            ],
            filename="blank-target-glossary-base.xlsx",
        )
        base_analysis = _analyze(client, project["id"], base["id"])
        _commit(client, project["id"], base_analysis["token"])
        update = _upload_rows(
            client,
            project["id"],
            [
                ["ID", "CN", "EN", "KO", "分类", "备注"],
                ["T-1", "新术语", "New EN", "", "新分类", "新备注"],
            ],
            filename="blank-target-glossary-update.xlsx",
        )
        analysis = _analyze(
            client,
            project["id"],
            update["id"],
            languages=["en", "ko"],
            dataset_key=base_analysis["dataset_key"],
        )
        _commit(client, project["id"], analysis["token"])

    rows = {(row["language"], row["term_key"]): row for row in _all_terms(project["id"])}
    assert analysis["can_commit"] is True
    assert rows[("en", "T-1")]["target"] == "New EN"
    assert rows[("ko", "T-1")]["target"] == "오래된 KO"
    assert rows[("ko", "T-1")]["source"] == "新术语"
    assert rows[("ko", "T-1")]["category"] == "新分类"
    assert rows[("ko", "T-1")]["note"] == "新备注"


def test_blank_new_language_row_propagates_shared_glossary_fields_to_existing_sibling() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload_rows(
            client,
            project["id"],
            [
                ["ID", "CN", "KO", "分类", "备注"],
                ["T-1", "旧术语", "오래된 KO", "旧分类", "旧备注"],
            ],
            filename="blank-new-language-glossary-base.xlsx",
        )
        base_analysis = _analyze(client, project["id"], base["id"])
        _commit(client, project["id"], base_analysis["token"])
        update = _upload_rows(
            client,
            project["id"],
            [
                ["ID", "CN", "EN", "分类", "备注"],
                ["T-1", "新术语", "", "新分类", "新备注"],
            ],
            filename="blank-new-language-glossary-update.xlsx",
        )
        analysis = _analyze(
            client,
            project["id"],
            update["id"],
            languages=["en"],
            dataset_key=base_analysis["dataset_key"],
        )
        committed = _commit(client, project["id"], analysis["token"])

    rows = {(row["language"], row["term_key"]): row for row in _all_terms(project["id"])}
    assert analysis["can_commit"] is True
    assert analysis["summary"]["skip"] == 1
    assert committed["changed_count"] == 1
    assert ("en", "T-1") not in rows
    assert rows[("ko", "T-1")]["source"] == "新术语"
    assert rows[("ko", "T-1")]["category"] == "新分类"
    assert rows[("ko", "T-1")]["note"] == "新备注"
    assert rows[("ko", "T-1")]["target"] == "오래된 KO"


def test_hidden_protected_glossary_sibling_requires_override_and_rolls_back() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload_rows(
            client,
            project["id"],
            [["ID", "CN", "EN", "KO"], ["T-1", "旧术语", "Old EN", "오래된 KO"]],
            filename="protected-glossary-sibling-base.xlsx",
        )
        base_analysis = _analyze(client, project["id"], base["id"])
        _commit(client, project["id"], base_analysis["token"])
        with db.connect() as conn:
            conn.execute(
                "UPDATE glossary_terms SET source_type = 'manual', review_status = 'approved', confirmed = 1 "
                "WHERE project_id = ? AND language = 'ko'",
                (project["id"],),
            )
        before = {(row["language"], row["term_key"]): row for row in _all_terms(project["id"])}
        update = _upload_rows(
            client,
            project["id"],
            [["ID", "CN", "EN"], ["T-1", "新术语", "New EN"]],
            filename="protected-glossary-sibling-update.xlsx",
        )
        blocked = _analyze(
            client,
            project["id"],
            update["id"],
            languages=["en"],
            dataset_key=base_analysis["dataset_key"],
        )
        blocked_commit = client.post(
            f"/api/projects/{project['id']}/glossary/import/commit",
            json={"token": blocked["token"]},
        )
        allowed = _analyze(
            client,
            project["id"],
            update["id"],
            languages=["en"],
            dataset_key=base_analysis["dataset_key"],
            override_protected=True,
        )
        committed = _commit(client, project["id"], allowed["token"])
        changed = {(row["language"], row["term_key"]): row for row in _all_terms(project["id"])}
        rolled_back = client.post(
            f"/api/projects/{project['id']}/glossary/import/batches/{committed['batch_id']}/rollback"
        )

    assert blocked["can_commit"] is False
    assert "protected_source" in {conflict["code"] for conflict in blocked["conflicts"]}
    assert blocked_commit.status_code == 409
    assert changed[("ko", "T-1")]["source_type"] == "imported"
    assert changed[("ko", "T-1")]["review_status"] == "pending"
    assert changed[("ko", "T-1")]["confirmed"] == 0
    assert rolled_back.status_code == 200, rolled_back.text
    restored = {(row["language"], row["term_key"]): row for row in _all_terms(project["id"])}
    for key in (("en", "T-1"), ("ko", "T-1")):
        for field in ("source", "target", "source_type", "review_status", "confirmed"):
            assert restored[key][field] == before[key][field]


def test_glossary_merge_allows_appending_new_unkeyed_row() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        base = _upload_rows(
            client,
            project["id"],
            [["CN", "EN", "KO"], ["旧术语", "Old EN", "오래된 KO"]],
            filename="unkeyed-glossary-append-base.xlsx",
        )
        base_analysis = _analyze(client, project["id"], base["id"])
        _commit(client, project["id"], base_analysis["token"])
        appended = _upload_rows(
            client,
            project["id"],
            [["CN", "EN"], ["旧术语", "Old EN"], ["追加术语", "Added EN"]],
            filename="unkeyed-glossary-append.xlsx",
        )
        analysis = _analyze(
            client,
            project["id"],
            appended["id"],
            languages=["en"],
            dataset_key=base_analysis["dataset_key"],
        )
        committed = _commit(client, project["id"], analysis["token"])

    assert analysis["can_commit"] is True
    assert analysis["summary"]["insert"] == 1
    assert committed["changed_count"] == 1
    assert {row["source"] for row in _all_terms(project["id"])} == {"旧术语", "追加术语"}


def test_direct_import_requires_explicit_confirmation_and_routes_language_tables_to_candidates() -> None:
    rows = [["ID", "CN", "EN"], ["T-1", "战力", "CP"]]
    with TestClient(app) as client:
        project = _create_project(client)
        glossary_artifact = _upload_rows(client, project["id"], rows)
        language_table = _upload_rows(
            client,
            project["id"],
            rows,
            filename="language-table.xlsx",
            kind="language_table",
        )

        missing_confirmation = client.post(
            f"/api/projects/{project['id']}/glossary/import/analyze",
            json={"artifact_id": glossary_artifact["id"], "mode": "merge"},
        )
        snapshot = client.post(
            f"/api/projects/{project['id']}/glossary/import/analyze",
            json={
                "artifact_id": glossary_artifact["id"],
                "mode": "snapshot",
                "confirmed_glossary": True,
            },
        )
        direct_language_table = client.post(
            f"/api/projects/{project['id']}/glossary/import/analyze",
            json={
                "artifact_id": language_table["id"],
                "mode": "merge",
                "confirmed_glossary": True,
            },
        )

    assert missing_confirmation.status_code in {400, 422}
    assert snapshot.status_code == 400
    assert direct_language_table.status_code == 400
    assert _all_terms(project["id"]) == []


def test_legacy_import_delegates_to_safe_batch_only_for_glossary_artifacts() -> None:
    rows = [["ID", "CN", "EN"], ["T-1", "战力", "CP"]]
    with TestClient(app) as client:
        project = _create_project(client)
        glossary_artifact = _upload_rows(client, project["id"], rows)
        language_table = _upload_rows(
            client,
            project["id"],
            rows,
            filename="language-table.xlsx",
            kind="language_table",
        )
        imported = client.post(
            f"/api/projects/{project['id']}/glossary/import",
            json={"artifact_id": glossary_artifact["id"]},
        )
        rejected = client.post(
            f"/api/projects/{project['id']}/glossary/import",
            json={"artifact_id": language_table["id"]},
        )
        batches = client.get(f"/api/projects/{project['id']}/glossary/import/batches")

    assert imported.status_code == 200, imported.text
    assert imported.json()["terms"][0]["source_type"] == "imported"
    assert rejected.status_code == 400
    assert batches.status_code == 200, batches.text
    assert len(batches.json()["batches"]) == 1
    assert batches.json()["batches"][0]["status"] == "committed"


def test_legacy_import_still_honors_protected_terms() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        manual = client.post(
            f"/api/projects/{project['id']}/glossary",
            json={"term_key": "T-1", "source": "战力", "target": "CP"},
        )
        assert manual.status_code == 200, manual.text
        artifact = _upload_rows(
            client,
            project["id"],
            [["ID", "CN", "EN"], ["T-1", "战力", "Combat Power"]],
        )
        imported = client.post(
            f"/api/projects/{project['id']}/glossary/import",
            json={"artifact_id": artifact["id"]},
        )

    assert imported.status_code == 409
    assert imported.json()["detail"]["code"] == "conflicts_present"
    assert db.get_glossary_term(manual.json()["id"])["target"] == "CP"


def test_merge_blank_skip_unchanged_timestamp_and_inactive_identity_reactivation() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        first_artifact = _upload_rows(
            client,
            project["id"],
            [["ID", "CN", "EN"], ["T-1", "战力", "CP"]],
            filename="first.xlsx",
        )
        first = _commit(client, project["id"], _analyze(client, project["id"], first_artifact["id"])["token"])
        term_id = first["terms"][0]["id"]
        original_updated_at = first["terms"][0]["updated_at"]

        same_artifact = _upload_rows(
            client,
            project["id"],
            [["ID", "CN", "EN"], ["T-1", "战力", "CP"]],
            filename="same.xlsx",
        )
        same_analysis = _analyze(client, project["id"], same_artifact["id"])
        assert same_analysis["summary"]["unchanged"] == 1
        same = _commit(client, project["id"], same_analysis["token"])
        assert same["terms"][0]["updated_at"] == original_updated_at

        blank_artifact = _upload_rows(
            client,
            project["id"],
            [["ID", "CN", "EN"], ["T-1", "战力", ""]],
            filename="blank.xlsx",
        )
        blank_analysis = _analyze(client, project["id"], blank_artifact["id"])
        assert blank_analysis["summary"]["skip"] == 1
        _commit(client, project["id"], blank_analysis["token"])

        deleted = client.delete(f"/api/projects/{project['id']}/glossary/{term_id}")
        assert deleted.status_code == 200, deleted.text
        assert client.get(f"/api/projects/{project['id']}/glossary").json() == []
        reactivate = _commit(
            client,
            project["id"],
            _analyze(client, project["id"], same_artifact["id"])["token"],
        )

    assert reactivate["terms"][0]["id"] == term_id
    assert reactivate["terms"][0]["active"] == 1
    assert _all_terms(project["id"])[0]["target"] == "CP"


@pytest.mark.parametrize(
    ("rows", "conflict_code"),
    [
        (
            [["ID", "CN", "EN"], ["T-1", "战力", "CP"], ["T-1", "等级", "Level"]],
            "duplicate_id",
        ),
        (
            [["ID", "CN", "EN"], ["", "战 力", "CP"], ["", "战力", "Power"]],
            "duplicate_source",
        ),
    ],
)
def test_identity_conflicts_are_structured_and_commit_is_atomic(
    rows: list[list[object]],
    conflict_code: str,
) -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        artifact = _upload_rows(client, project["id"], rows)
        analysis = _analyze(client, project["id"], artifact["id"])
        committed = client.post(
            f"/api/projects/{project['id']}/glossary/import/commit",
            json={"token": analysis["token"]},
        )

    assert analysis["can_commit"] is False
    assert any(conflict["code"] == conflict_code for conflict in analysis["conflicts"])
    assert committed.status_code == 409
    assert _all_terms(project["id"]) == []


def test_existing_id_and_source_cross_match_is_a_blocking_conflict() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        first = _upload_rows(
            client,
            project["id"],
            [["ID", "CN", "EN"], ["T-1", "战力", "CP"], ["T-2", "等级", "Level"]],
            filename="seed.xlsx",
        )
        _commit(client, project["id"], _analyze(client, project["id"], first["id"])["token"])
        crossed = _upload_rows(
            client,
            project["id"],
            [["ID", "CN", "EN"], ["T-1", "等级", "Wrong"]],
            filename="crossed.xlsx",
        )
        analysis = _analyze(client, project["id"], crossed["id"])

    assert analysis["can_commit"] is False
    assert any(conflict["code"] == "id_source_cross_match" for conflict in analysis["conflicts"])
    assert {row["target"] for row in _all_terms(project["id"])} == {"CP", "Level"}


def test_keyed_import_never_reuses_unkeyed_cn_identity() -> None:
    project = db.insert_project("strict keyed glossary identity")
    unkeyed = db.insert_glossary_term(
        project["id"],
        {
            "term_key": "",
            "source": "战力",
            "target": "CP",
            "language": "en",
            "source_type": "imported",
            "confirmed": True,
            "review_status": "approved",
        },
    )
    unkeyed_ko = db.insert_glossary_term(
        project["id"],
        {
            "term_key": "",
            "source": "战力",
            "target": "전투력",
            "language": "ko",
            "source_type": "imported",
            "confirmed": True,
            "review_status": "approved",
        },
    )
    with TestClient(app) as client:
        artifact = _upload_rows(
            client,
            project["id"],
            [["ID", "CN", "EN"], ["T-1", "战力", "Combat Power"]],
        )
        analysis = _analyze(client, project["id"], artifact["id"])

    assert analysis["can_commit"] is False
    assert any(conflict["code"] == "new_id_source_exists" for conflict in analysis["conflicts"])
    assert analysis["summary"]["update"] == 0
    assert db.get_glossary_term(unkeyed["id"])["term_key"] == ""
    assert db.get_glossary_term(unkeyed_ko["id"])["term_key"] == ""


def test_manual_post_reactivates_inactive_strict_id_when_source_changes() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        created = client.post(
            f"/api/projects/{project['id']}/glossary",
            json={"term_key": "M-1", "source": "旧源文", "target": "Old"},
        )
        assert created.status_code == 200, created.text
        term_id = created.json()["id"]
        deleted = client.delete(f"/api/projects/{project['id']}/glossary/{term_id}")
        assert deleted.status_code == 200, deleted.text

        reactivated = client.post(
            f"/api/projects/{project['id']}/glossary",
            json={"term_key": "M-1", "source": "新源文", "target": "New"},
        )

    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["id"] == term_id
    assert reactivated.json()["source"] == "新源文"
    assert reactivated.json()["active"] == 1
    assert reactivated.json()["source_type"] == "manual"
    assert len(_all_terms(project["id"])) == 1


@pytest.mark.parametrize("source_type", ["manual", "curated"])
def test_protected_terms_require_override_then_rollback_restores_review_state(source_type: str) -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        created = client.post(
            f"/api/projects/{project['id']}/glossary",
            json={
                "term_key": "T-1",
                "source": "战力",
                "target": "CP",
                "source_type": source_type,
                "confirmed": False,
            },
        )
        assert created.status_code == 200, created.text
        protected = created.json()
        assert protected["source_type"] == "manual"
        assert protected["review_status"] == "approved"
        assert protected["confirmed"] is True

        artifact = _upload_rows(
            client,
            project["id"],
            [["ID", "CN", "EN"], ["T-1", "战力", "Combat Power"]],
        )
        blocked = _analyze(client, project["id"], artifact["id"])
        assert blocked["can_commit"] is False
        override = _analyze(client, project["id"], artifact["id"], override_protected=True)
        committed = _commit(client, project["id"], override["token"])
        changed = committed["terms"][0]
        assert changed["source_type"] == "imported"
        assert changed["review_status"] == "pending"
        assert changed["confirmed"] is False

        rolled_back = client.post(
            f"/api/projects/{project['id']}/glossary/import/batches/{committed['batch_id']}/rollback"
        )

    assert rolled_back.status_code == 200, rolled_back.text
    restored = db.get_glossary_term(protected["id"])
    assert restored["target"] == "CP"
    assert restored["source_type"] == "manual"
    assert restored["review_status"] == "approved"
    assert restored["confirmed"] is True


def test_checksum_scope_state_drift_and_commit_idempotence_are_structured_409s() -> None:
    with TestClient(app) as client:
        owner = _create_project(client, "owner")
        foreign = _create_project(client, "foreign")
        artifact = _upload_rows(
            client,
            owner["id"],
            [["ID", "CN", "EN"], ["T-1", "战力", "CP"]],
        )
        cross_project = client.post(
            f"/api/projects/{foreign['id']}/glossary/import/analyze",
            json={"artifact_id": artifact["id"], "confirmed_glossary": True, "mode": "merge"},
        )
        analysis = _analyze(client, owner["id"], artifact["id"])
        first = _commit(client, owner["id"], analysis["token"])
        second = _commit(client, owner["id"], analysis["token"])

        drift_analysis = _analyze(client, owner["id"], artifact["id"])
        manual = client.post(
            f"/api/projects/{owner['id']}/glossary",
            json={"term_key": "T-2", "source": "等级", "target": "Level"},
        )
        assert manual.status_code == 200, manual.text
        drift = client.post(
            f"/api/projects/{owner['id']}/glossary/import/commit",
            json={"token": drift_analysis["token"]},
        )

        checksum_analysis = _analyze(client, owner["id"], artifact["id"])
        Path(db.get_artifact(artifact["id"])["path"]).write_bytes(b"changed")
        checksum = client.post(
            f"/api/projects/{owner['id']}/glossary/import/commit",
            json={"token": checksum_analysis["token"]},
        )

    assert cross_project.status_code == 404
    assert first == second
    assert drift.status_code == 409
    assert drift.json()["detail"]["code"] == "state_drift"
    assert checksum.status_code == 409
    assert checksum.json()["detail"]["code"] == "artifact_changed"


def test_normal_reads_filter_inactive_without_mutating_duplicates_or_versions() -> None:
    project = db.insert_project("non mutating glossary reads")
    timestamp = db.now_iso()
    with db.connect() as conn:
        conn.executemany(
            """
            INSERT INTO glossary_terms
              (id, project_id, term_key, source, target, target_alt, language, category, note,
               source_type, confirmed, active, dataset_key, last_import_batch_id, review_status,
               created_at, updated_at)
            VALUES (?, ?, '', ?, ?, '', 'en', '', '', 'imported', 1, ?, '', '', 'approved', ?, ?)
            """,
            [
                ("term_active", project["id"], "战力", "CP", 1, timestamp, timestamp),
                ("term_inactive", project["id"], "战 力", "Old CP", 0, timestamp, timestamp),
            ],
        )
    before_version = _state_version(project["id"])
    before_count = len(_all_terms(project["id"]))

    with TestClient(app) as client:
        listed = client.get(f"/api/projects/{project['id']}/glossary")
        wide = client.get(f"/api/projects/{project['id']}/glossary/wide")

    assert listed.status_code == 200, listed.text
    assert [term["id"] for term in listed.json()] == ["term_active"]
    assert wide.status_code == 200, wide.text
    assert all(row["source"] != "战 力" for row in wide.json()["rows"])
    assert len(_all_terms(project["id"])) == before_count
    assert _state_version(project["id"]) == before_version


def test_candidate_accept_reject_version_lineage_cross_project_and_prompt_opt_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(app) as client:
        project = _create_project(client, "candidate owner")
        foreign = _create_project(client, "candidate foreign")
        source_artifact = _upload_rows(
            client,
            project["id"],
            [["ID", "CN", "EN"], ["T-1", "战力", "CP"]],
            kind="language_table",
        )
        run = db.insert_run(
            project["id"],
            "glossary",
            metadata={"input_artifact_id": source_artifact["id"]},
        )
        final_output = tmp_path / "generated-glossary.xlsx"
        final_output.write_bytes(
            _workbook_bytes(
                [["ID", "CN", "EN"], ["T-1", "战力", "CP"], ["T-2", "等级", "Level"]]
            )
        )
        staged = backfill_project_glossary_from_final(project["id"], final_output, run["id"])
        batch = db.get_glossary_batch(staged["batch_id"])
        assert batch["source_artifact_id"] == source_artifact["id"]
        candidates = db.list_glossary_candidates(project["id"], batch_id=batch["id"])
        assert _all_terms(project["id"]) == []
        before_accept = _state_version(project["id"])
        accepted = client.post(
            f"/api/projects/{project['id']}/glossary/batches/{batch['id']}/accept",
            json={"candidate_ids": [candidates[0]["id"]]},
        )
        rejected = client.post(
            f"/api/projects/{project['id']}/glossary/batches/{batch['id']}/reject",
            json={"candidate_ids": [candidates[1]["id"]]},
        )
        assert accepted.status_code == 200, accepted.text
        assert rejected.status_code == 200, rejected.text
        assert len(_all_terms(project["id"])) == 1
        assert _state_version(project["id"]) > before_accept

        called = {"count": 0}

        def fake_extract(project_id: str, payload: object) -> dict:
            called["count"] += 1
            assert getattr(payload, "update_project_prompt") is False
            db.update_project(project_id, {"prompt_text": "concurrent user prompt"})
            return {"batch_id": "fake", "input_artifact_id": getattr(payload, "input_artifact_id")}

        monkeypatch.setattr(glossary_router, "extract_glossary", fake_extract)
        foreign_extract = client.post(
            f"/api/projects/{foreign['id']}/glossary/extract",
            json={"input_artifact_id": source_artifact["id"], "update_project_prompt": False},
        )
        db.update_project(project["id"], {"prompt_text": "original prompt"})
        own_extract = client.post(
            f"/api/projects/{project['id']}/glossary/extract",
            json={"input_artifact_id": source_artifact["id"], "update_project_prompt": False},
        )

    assert foreign_extract.status_code == 404
    assert own_extract.status_code == 200, own_extract.text
    assert called["count"] == 1
    assert db.get_project(project["id"])["prompt_text"] == "concurrent user prompt"


def test_candidate_accept_reuses_inactive_id_and_relabels_generated_provenance() -> None:
    with TestClient(app) as client:
        project = _create_project(client)
        inactive = client.post(
            f"/api/projects/{project['id']}/glossary",
            json={"term_key": "C-1", "source": "旧候选源文", "target": "Old"},
        )
        active = client.post(
            f"/api/projects/{project['id']}/glossary",
            json={"term_key": "C-2", "source": "人工源文", "target": "Manual"},
        )
        assert inactive.status_code == 200, inactive.text
        assert active.status_code == 200, active.text
        inactive_id = inactive.json()["id"]
        active_id = active.json()["id"]
        client.delete(f"/api/projects/{project['id']}/glossary/{inactive_id}")

        batch = db.create_glossary_batch(project["id"], label="identity candidates", language="en")
        first = db.add_glossary_candidate(
            project["id"],
            batch["id"],
            {"term_key": "C-1", "source": "新候选源文", "target": "Generated One", "language": "en"},
        )
        second = db.add_glossary_candidate(
            project["id"],
            batch["id"],
            {
                "existing_term_id": active_id,
                "term_key": "C-2",
                "source": "人工源文",
                "target": "Generated Two",
                "language": "en",
            },
        )
        accepted = client.post(
            f"/api/projects/{project['id']}/glossary/batches/{batch['id']}/accept",
            json={"candidate_ids": [first["id"], second["id"]]},
        )

    assert accepted.status_code == 200, accepted.text
    by_key = {term["term_key"]: term for term in accepted.json()["accepted_terms"]}
    assert by_key["C-1"]["id"] == inactive_id
    assert by_key["C-1"]["source"] == "新候选源文"
    assert by_key["C-2"]["id"] == active_id
    for term in by_key.values():
        assert term["active"] == 1
        assert term["source_type"] == "generated"
        assert term["review_status"] == "approved"
        assert term["confirmed"] is True
    assert len(_all_terms(project["id"])) == 2


def test_candidate_accept_keeps_multiple_terms_from_one_duplicate_row_key() -> None:
    project = db.insert_project("duplicate candidate row key")
    batch = db.create_glossary_batch(project["id"], label="same source row", language="en")
    first = db.add_glossary_candidate(
        project["id"],
        batch["id"],
        {"term_key": "ROW-2", "source": "每日登录奖励", "target": "Daily Login Reward", "language": "en"},
    )
    second = db.add_glossary_candidate(
        project["id"],
        batch["id"],
        {"term_key": "ROW-2", "source": "金币", "target": "Coin", "language": "en"},
    )

    with TestClient(app) as client:
        accepted = client.post(
            f"/api/projects/{project['id']}/glossary/batches/{batch['id']}/accept",
            json={"candidate_ids": [first["id"], second["id"]]},
        )

    assert accepted.status_code == 200, accepted.text
    assert {term["source"] for term in accepted.json()["accepted_terms"]} == {"每日登录奖励", "金币"}
    assert {term["source"] for term in _all_terms(project["id"])} == {"每日登录奖励", "金币"}


def test_header_only_generated_final_is_empty_backfill_but_invalid_user_import(tmp_path: Path) -> None:
    content = _workbook_bytes([["ID", "CN", "EN", "EN2"]])
    generated = tmp_path / "header-only-generated-final.xlsx"
    generated.write_bytes(content)

    with TestClient(app) as client:
        project = _create_project(client, "header only generated final")
        artifact = _upload_bytes(client, project["id"], generated.name, content)
        ordinary_import = client.post(
            f"/api/projects/{project['id']}/glossary/import",
            json={"artifact_id": artifact["id"]},
        )

    assert ordinary_import.status_code == 400, ordinary_import.text

    result = backfill_project_glossary_from_final(project["id"], generated)

    assert result["candidates"] == 0
    assert result["unique_candidates"] == 0
    assert result["inserted"] == 0


def test_prompt_opt_out_performs_zero_prompt_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(app) as client:
        project = _create_project(client, "prompt opt out")
        db.update_project(project["id"], {"prompt_text": "original prompt"})
        artifact = _upload_rows(
            client,
            project["id"],
            [["ID", "CN", "EN"], *[[f"T-{index}", "战机", "Warplane"] for index in range(1, 11)]],
            kind="language_table",
        )
        real_update_project = db.update_project
        prompt_writes: list[str] = []

        def track_update_project(project_id: str, updates: dict[str, object]) -> dict:
            if "prompt_text" in updates:
                prompt_writes.append(str(updates["prompt_text"]))
            return real_update_project(project_id, updates)

        monkeypatch.setattr(db, "update_project", track_update_project)
        response = client.post(
            f"/api/projects/{project['id']}/glossary/extract",
            json={
                "input_artifact_id": artifact["id"],
                "id_column": "ID",
                "source_column": "CN",
                "target_column": "EN",
                "language": "en",
                "ai_candidate_supplement": False,
                "update_project_prompt": False,
            },
        )

    assert response.status_code == 200, response.text
    assert prompt_writes == []
    assert db.get_project(project["id"])["prompt_text"] == "original prompt"
