from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ["LWS_DATA_ROOT"] = str(Path(tempfile.gettempdir()) / "lws-test-data")

import pytest

import app.db as db
from conftest import reset_data_root, wait_for_background_jobs


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    data_root = Path(os.environ["LWS_DATA_ROOT"])
    reset_data_root(data_root)
    db.init_db()
    yield
    wait_for_background_jobs()


def test_connect_enables_wal_journal_mode() -> None:
    with db.connect() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() == "wal"


def test_connect_sets_synchronous_normal() -> None:
    with db.connect() as conn:
        # NORMAL == 1 in SQLite's PRAGMA synchronous encoding.
        sync_level = conn.execute("PRAGMA synchronous").fetchone()[0]
        assert int(sync_level) == 1
