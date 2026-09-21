from __future__ import annotations

import csv
import io
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.db as db
import app.auth as auth
import app.main as main_module
from app.main import app
from conftest import reset_data_root


@pytest.fixture(autouse=True)
def isolated_test_state() -> None:
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()


def create_project(client: TestClient, name: str = "待复核术语") -> dict:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 200, response.text
    return response.json()


def import_pending_terms(client: TestClient, project_id: str, rows: list[tuple[str, str, str]]) -> dict:
    for term_key, source, _ in rows:
        response = client.post(f"/api/projects/{project_id}/glossary", json={
            "term_key": term_key, "source": source, "target": "Original", "language": "en",
        })
        assert response.status_code == 200, response.text
    csv_text = io.StringIO()
    writer = csv.writer(csv_text)
    writer.writerow(["ID", "CN", "EN"])
    writer.writerows(rows)
    uploaded = client.post(f"/api/projects/{project_id}/files?kind=term_base", files={
        "file": ("pending.csv", csv_text.getvalue().encode("utf-8"), "text/csv"),
    })
    assert uploaded.status_code == 200, uploaded.text
    analyzed = client.post(f"/api/projects/{project_id}/glossary/import/analyze", json={
        "artifact_id": uploaded.json()["id"], "languages": ["en"], "mode": "merge",
        "confirmed_glossary": True, "override_protected": True,
    })
    assert analyzed.status_code == 200, analyzed.text
    assert analyzed.json()["can_commit"] is True
    committed = client.post(f"/api/projects/{project_id}/glossary/import/commit?compact=true", json={"token": analyzed.json()["token"]})
    assert committed.status_code == 200, committed.text
    return committed.json()


def pending_page(client: TestClient, project_id: str, **params: object) -> dict:
    response = client.get(f"/api/projects/{project_id}/glossary/pending", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_pending_glossary_is_discoverable_with_paging_search_and_batch_filter() -> None:
    with TestClient(app) as client:
        project = create_project(client)
        project_id = project["id"]
        batch = import_pending_terms(client, project_id, [
            ("T-1", "术语甲", "Alpha"), ("T-2", "术语乙", "Bonus 100%"), ("T-3", "术语丙", "Gamma"),
        ])
        first = pending_page(client, project_id, page=1, page_size=2)
        second = pending_page(client, project_id, page=2, page_size=2)
        assert first["total_rows"] == second["total_rows"] == 3
        assert first["total_pages"] == 2
        assert len(first["items"]) == 2
        assert len(second["items"]) == 1
        items = first["items"] + second["items"]
        assert len({item["id"] for item in items}) == 3
        assert all(item["revision"] and item["confirmed"] is False for item in items)
        assert all(item["active"] and item["source_type"] == "imported" and item["review_status"] == "pending" for item in items)
        assert pending_page(client, project_id, q="BONUS")["items"][0]["target"] == "Bonus 100%"
        assert pending_page(client, project_id, q="%")["total_rows"] == 1
        assert pending_page(client, project_id, language="ko")["total_rows"] == 0
        assert pending_page(client, project_id, batch_id=batch["batch_id"])["total_rows"] == 3
        assert pending_page(client, project_id, batch_id="other-batch")["total_rows"] == 0
        assert client.get(f"/api/projects/{project_id}/glossary").json() == []
        assert client.get(f"/api/projects/{project_id}/glossary/wide").json()["total_rows"] == 0


def test_pending_confirmation_is_manual_and_rejects_a_stale_editor() -> None:
    with TestClient(app) as client:
        project_id = create_project(client)["id"]
        import_pending_terms(client, project_id, [("T-1", "战力", "Combat Strength")])
        pending = pending_page(client, project_id)["items"][0]
        response = client.patch(f"/api/projects/{project_id}/glossary/{pending['id']}", json={
            "expected_revision": pending["revision"], "target": "Combat Power", "note": "人工复核",
        })
        assert response.status_code == 200, response.text
        confirmed = response.json()
        assert confirmed["target"] == "Combat Power"
        assert confirmed["source_type"] == "manual"
        assert confirmed["confirmed"] is True
        assert confirmed["active"] == 1
        assert confirmed["review_status"] == "approved"
        assert pending_page(client, project_id)["total_rows"] == 0
        stale = client.patch(f"/api/projects/{project_id}/glossary/{pending['id']}", json={
            "expected_revision": pending["revision"], "target": "Stale edit",
        })
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"]["code"] == "glossary_revision_conflict"
        assert confirmed.get("revision") and confirmed["revision"] != pending["revision"]
        assert client.get(f"/api/projects/{project_id}/glossary").json()[0]["target"] == "Combat Power"


def test_pending_confirmation_requires_revision_and_does_not_cross_projects() -> None:
    with TestClient(app) as client:
        project_id = create_project(client)["id"]
        other_project_id = create_project(client, "其他项目")["id"]
        import_pending_terms(client, project_id, [("T-1", "战力", "Combat Strength")])
        pending = pending_page(client, project_id)["items"][0]
        missing = client.patch(f"/api/projects/{project_id}/glossary/{pending['id']}", json={"target": "Blind edit"})
        assert missing.status_code == 422, missing.text
        wrong_project = client.patch(f"/api/projects/{other_project_id}/glossary/{pending['id']}", json={
            "expected_revision": pending["revision"], "target": "Foreign edit",
        })
        assert wrong_project.status_code == 404, wrong_project.text
        assert pending_page(client, other_project_id)["total_rows"] == 0
        assert pending_page(client, project_id)["items"][0]["revision"] == pending["revision"]
        assert client.get("/api/projects/missing-project/glossary/pending").status_code == 404


def test_simultaneous_confirmations_allow_only_one_writer() -> None:
    with TestClient(app) as client:
        project_id = create_project(client)["id"]
        import_pending_terms(client, project_id, [("T-1", "战力", "Combat Strength")])
        pending = pending_page(client, project_id)["items"][0]
        barrier = threading.Barrier(4)

        def confirm(index: int):
            barrier.wait(timeout=10)
            return client.patch(f"/api/projects/{project_id}/glossary/{pending['id']}", json={
                "expected_revision": pending["revision"], "target": f"Editor {index}",
            })

        with ThreadPoolExecutor(max_workers=4) as executor:
            responses = list(executor.map(confirm, range(4)))
        assert sorted(response.status_code for response in responses) == [200, 409, 409, 409]
        winner = next(response.json() for response in responses if response.status_code == 200)
        assert client.get(f"/api/projects/{project_id}/glossary").json()[0]["target"] == winner["target"]


def test_pending_visibility_excludes_other_states_and_validates_paging() -> None:
    with TestClient(app) as client:
        project_id = create_project(client)["id"]
        for index, overrides in enumerate([
            {}, {"active": False}, {"confirmed": True}, {"source_type": "manual"}, {"review_status": "approved"},
        ]):
            db.insert_glossary_term(project_id, {
                "source": f"术语{index}", "target": f"Term {index}", "language": "ko", "active": True,
                "confirmed": False, "source_type": "imported", "review_status": "pending", **overrides,
            })
        page = pending_page(client, project_id, language="ko")
        assert page["total_rows"] == 1
        assert page["items"][0]["source"] == "术语0"
        assert pending_page(client, project_id, page=2, page_size=1)["items"] == []
        for params in ({"page": 0}, {"page_size": 0}, {"page_size": 201}):
            assert client.get(f"/api/projects/{project_id}/glossary/pending", params=params).status_code == 422


def test_confirmation_enables_lookup_and_export_but_protects_against_batch_rollback() -> None:
    with TestClient(app) as client:
        project_id = create_project(client)["id"]
        batch = import_pending_terms(client, project_id, [("T-1", "战力", "Combat Strength")])
        pending = pending_page(client, project_id)["items"][0]
        lookup_url = f"/api/projects/{project_id}/announcement-lookup"
        before = client.post(lookup_url, json={"text": "战力提升", "language": "en"})
        assert before.status_code == 200, before.text
        assert before.json()["summary"]["matched_terms"] == 0
        exported = client.get(f"/api/projects/{project_id}/glossary/export?format=csv")
        assert exported.status_code == 200
        assert "Combat Strength" not in exported.text
        confirmed = client.patch(f"/api/projects/{project_id}/glossary/{pending['id']}", json={
            "expected_revision": pending["revision"], "target": "Combat Power",
        })
        assert confirmed.status_code == 200, confirmed.text
        after = client.post(lookup_url, json={"text": "战力提升", "language": "en"})
        assert after.status_code == 200, after.text
        assert after.json()["summary"]["matched_terms"] == 1
        assert "Combat Power" in client.get(f"/api/projects/{project_id}/glossary/export?format=csv").text
        rollback = client.post(f"/api/projects/{project_id}/glossary/import/batches/{batch['batch_id']}/rollback")
        assert rollback.status_code == 409, rollback.text
        assert client.get(f"/api/projects/{project_id}/glossary").json()[0]["target"] == "Combat Power"
        assert pending_page(client, project_id, batch_id=batch["batch_id"])["total_rows"] == 0


def test_unreviewed_batch_can_still_rollback_and_invalidates_pending_revision() -> None:
    with TestClient(app) as client:
        project_id = create_project(client)["id"]
        batch = import_pending_terms(client, project_id, [("T-1", "战力", "Combat Strength")])
        pending = pending_page(client, project_id)["items"][0]
        rolled_back = client.post(f"/api/projects/{project_id}/glossary/import/batches/{batch['batch_id']}/rollback")
        assert rolled_back.status_code == 200, rolled_back.text
        assert pending_page(client, project_id)["total_rows"] == 0
        stale = client.patch(f"/api/projects/{project_id}/glossary/{pending['id']}", json={
            "expected_revision": pending["revision"], "target": "Stale review",
        })
        assert stale.status_code == 409, stale.text
        assert client.get(f"/api/projects/{project_id}/glossary").json()[0]["target"] == "Original"


def test_confirming_one_record_does_not_invalidate_another_pending_record() -> None:
    with TestClient(app) as client:
        project_id = create_project(client)["id"]
        import_pending_terms(client, project_id, [("T-1", "战力", "Combat Strength"), ("T-2", "技能", "Skill")])
        pending = pending_page(client, project_id)["items"]
        for term in pending:
            response = client.patch(f"/api/projects/{project_id}/glossary/{term['id']}", json={
                "expected_revision": term["revision"], "target": term["target"],
            })
            assert response.status_code == 200, response.text
        assert pending_page(client, project_id)["total_rows"] == 0
        assert len(client.get(f"/api/projects/{project_id}/glossary").json()) == 2


def test_confirmed_manual_edit_remains_compatible_without_revision() -> None:
    with TestClient(app) as client:
        project_id = create_project(client)["id"]
        created = client.post(f"/api/projects/{project_id}/glossary", json={
            "source": "战力", "target": "Original", "language": "en",
        })
        assert created.status_code == 200, created.text
        saved = client.patch(f"/api/projects/{project_id}/glossary/{created.json()['id']}", json={
            "target": "Updated manual term",
        })
        assert saved.status_code == 200, saved.text
        assert saved.json()["target"] == "Updated manual term"
        assert saved.json()["confirmed"] is True
        assert saved.json()["revision"]


def test_deleted_pending_record_cannot_be_restored_by_stale_confirmation() -> None:
    with TestClient(app) as client:
        project_id = create_project(client)["id"]
        import_pending_terms(client, project_id, [("T-1", "战力", "Combat Strength")])
        pending = pending_page(client, project_id)["items"][0]
        deleted = client.delete(f"/api/projects/{project_id}/glossary/{pending['id']}")
        assert deleted.status_code == 200, deleted.text
        saved = client.patch(f"/api/projects/{project_id}/glossary/{pending['id']}", json={
            "expected_revision": pending["revision"], "target": "Stale confirmation",
        })
        assert saved.status_code == 409, saved.text
        assert db.get_glossary_term(pending["id"])["active"] == 0
        assert pending_page(client, project_id)["total_rows"] == 0


@pytest.mark.parametrize("role,is_member,expected_write", [
    ("member", True, 403), ("ops", True, 200), ("admin", False, 200), ("ops", False, 404),
])
def test_pending_review_preserves_role_and_project_permissions(
    monkeypatch: pytest.MonkeyPatch, role: str, is_member: bool, expected_write: int,
) -> None:
    monkeypatch.setenv("LWS_AUTH_MODE", "required")
    monkeypatch.setenv("LWS_ADMIN_USER", "pending-admin")
    monkeypatch.setenv("LWS_ADMIN_PASSWORD", "Pending-Admin-Password!")
    auth.login_rate_limiter._state.clear()
    profile = main_module.config.RuntimeProfile.from_environment(
        os.environ, data_root=main_module.config.DATA_ROOT, app_root=main_module.config.REPO_ROOT,
    )
    test_app = main_module.create_app(profile)
    with TestClient(test_app) as admin_client:
        logged_in = admin_client.post("/api/auth/login", json={"username": "pending-admin", "password": "Pending-Admin-Password!"})
        assert logged_in.status_code == 200, logged_in.text
        admin = db.get_user_by_username("pending-admin")
        db.update_user(admin["id"], {"must_change_password": False})
        project_id = create_project(admin_client)["id"]
        import_pending_terms(admin_client, project_id, [("T-1", "战力", "Combat Strength")])
        pending = pending_page(admin_client, project_id)["items"][0]
        created_user = admin_client.post("/api/users", json={
            "username": "pending-user", "display_name": "待复核用户", "role": role, "initial_password": "Pending-User-Password!",
        })
        assert created_user.status_code == 200, created_user.text
        user = db.get_user_by_username("pending-user")
        db.update_user(user["id"], {"must_change_password": False})
        if is_member:
            db.add_project_member(project_id, user["id"], added_by=admin["id"])
        with TestClient(test_app) as user_client:
            login = user_client.post("/api/auth/login", json={"username": "pending-user", "password": "Pending-User-Password!"})
            assert login.status_code == 200, login.text
            listed = user_client.get(f"/api/projects/{project_id}/glossary/pending")
            assert listed.status_code == (200 if is_member or role == "admin" else 404), listed.text
            if listed.status_code == 200:
                assert listed.json()["items"][0]["id"] == pending["id"]
            saved = user_client.patch(f"/api/projects/{project_id}/glossary/{pending['id']}", json={
                "expected_revision": pending["revision"], "target": "Reviewed",
            })
            assert saved.status_code == expected_write, saved.text
        assert pending_page(admin_client, project_id)["total_rows"] == (0 if expected_write == 200 else 1)
