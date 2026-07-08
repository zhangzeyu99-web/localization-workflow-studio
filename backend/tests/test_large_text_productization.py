from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ["LWS_DATA_ROOT"] = str(Path(tempfile.gettempdir()) / "lws-test-data")

import app.db as db
from app.config import DEFAULT_SETTINGS, save_settings
from app.workflow.large_text import build_large_text_preflight, normalize_large_text_mode
from conftest import reset_data_root, wait_for_background_jobs


def setup_function() -> None:
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()
    save_settings(DEFAULT_SETTINGS)


def teardown_function() -> None:
    wait_for_background_jobs()
    save_settings(DEFAULT_SETTINGS)


def test_build_large_text_preflight_marks_large_multilingual_pack() -> None:
    rows = [{"id": f"row-{index}", "source": "长文本" * 160} for index in range(6000)]

    result = build_large_text_preflight(
        rows,
        target_languages=["en", "ko", "ja", "fr", "de"],
        source_rows=6000,
        workbook_count=1,
        full_proofread=False,
    )

    assert result["workflow"] == "large_text_product_v1"
    assert result["unique_items"] == 6000
    assert result["target_language_count"] == 5
    assert result["estimated_target_cells"] == 30000
    assert result["long_text_items"] == 6000
    assert result["large_pack"] is True
    assert {"unique_items>5000", "target_languages>4"} <= set(result["large_pack_reasons"])


def test_normalize_large_text_mode_defaults_to_auto() -> None:
    assert normalize_large_text_mode(None) == "auto"
    assert normalize_large_text_mode("strict") == "strict"
    assert normalize_large_text_mode("off") == "off"
