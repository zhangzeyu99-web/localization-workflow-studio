"""Regression guards: test cleanup must never touch runtime project data."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from conftest import reset_data_root


def test_cleanup_rejects_business_directory_before_any_deletion() -> None:
    with pytest.raises(RuntimeError, match="Refusing to clean"):
        reset_data_root(Path("D:/codex/localization-workflow-studio-data"))
    with pytest.raises(RuntimeError, match="Refusing to clean"):
        reset_data_root(Path(tempfile.gettempdir()))


def test_conftest_overrides_inherited_runtime_directory(tmp_path: Path) -> None:
    sentinel = tmp_path / "business" / "keep.txt"
    sentinel.parent.mkdir()
    sentinel.write_text("preserve", encoding="utf-8")
    env = dict(os.environ, LWS_DATA_ROOT=str(sentinel.parent), LWS_AUTH_MODE="required", LWS_DEPLOYMENT_MODE="cloud")
    conftest = Path(__file__).with_name("conftest.py")
    code = (
        "import os, runpy; "
        f"runpy.run_path({str(conftest)!r}); "
        f"assert os.environ['LWS_DATA_ROOT'] != {str(sentinel.parent)!r}; "
        "assert 'LWS_AUTH_MODE' not in os.environ; "
        "assert 'LWS_DEPLOYMENT_MODE' not in os.environ"
    )
    subprocess.run([sys.executable, "-c", code], env=env, check=True, capture_output=True, text=True)
    assert sentinel.read_text(encoding="utf-8") == "preserve"
