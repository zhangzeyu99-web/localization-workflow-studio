"""Approved edits must reach new glossary exports without changing other languages."""
from io import BytesIO
import os
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import db
from app.main import app
from conftest import reset_data_root


def test_approved_term_change_is_read_back_from_new_delivery() -> None:
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()
    with TestClient(app) as client:
        response = client.post("/api/projects", json={"name": "Glossary delivery regression"})
        assert response.status_code == 200
        project_id = response.json()["id"]
        url = f"/api/projects/{project_id}/glossary"
        terms = {}
        for language, target in (("en", "Night Realm"), ("fr", "Royaume nocturne")):
            response = client.post(url, json={"term_key": "TERM-1", "source": "夜之领域", "target": target, "language": language})
            assert response.status_code == 200, response.text
            terms[language] = response.json()
        before = client.get(url + "/export?format=xlsx").content
        response = client.patch(url + "/" + terms["en"]["id"], json={"target": "Realm of Night"})
        assert response.status_code == 200, response.text
        response = client.get(url + "/export?format=xlsx")
        assert response.status_code == 200
        for content, expected in ((before, "Night Realm"), (response.content, "Realm of Night")):
            book = load_workbook(BytesIO(content), read_only=True)
            try:
                rows = list(book.active.values)
                row = dict(zip(rows[0], rows[1]))
                assert row["ID"] == "TERM-1"
                assert row["CN"] == "夜之领域"
                assert row["EN"] == expected
                assert row["FR"] == "Royaume nocturne"
            finally:
                book.close()
