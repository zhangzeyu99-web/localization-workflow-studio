from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["LWS_DATA_ROOT"] = str(Path(tempfile.gettempdir()) / "lws-test-data")

import app.db as db
from app.config import DEFAULT_SETTINGS, save_settings
from app.workflow.large_text import (
    build_large_text_preflight,
    build_translation_cache_rows,
    cache_lint_rows,
    normalize_large_text_mode,
    protected_tokens,
)
from conftest import reset_data_root, wait_for_background_jobs

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_GATE_DIR = REPO_ROOT / "workflow" / "localization"


def _load_workflow_gate():
    """Import the local-harness source-of-truth gate module in isolation.

    The module lives outside the backend package tree (``workflow/localization``)
    and is intentionally not imported by production code (see module docstring
    in ``app.workflow.large_text``). Tests import it directly, scoped to this
    call, to assert behavioral parity against the ported product implementation.
    """
    sys.path.insert(0, str(WORKFLOW_GATE_DIR))
    try:
        module = importlib.import_module("utils.large_text_multilingual_gate")
        importlib.reload(module)
    finally:
        if str(WORKFLOW_GATE_DIR) in sys.path:
            sys.path.remove(str(WORKFLOW_GATE_DIR))
    return module


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


def test_cache_lint_blocks_missing_machine_token_and_number() -> None:
    workpack = [
        {"id": "a", "source": "领取 100K 奖励 {count}"},
        {"id": "b", "source": "分享 [SDT] {num}"},
    ]
    translated = [
        {"id": "a", "translation": "Claim rewards {count}"},
        {"id": "b", "translation": "Share {num}"},
    ]

    cache_rows = build_translation_cache_rows(workpack, translated, "en")
    result = cache_lint_rows(cache_rows, target_languages=["en"])

    assert result["hard_blockers"] == 2
    assert result["hard_by_type"]["number_missing"] == 1
    assert result["hard_by_type"]["protected_token_missing"] == 1


def _write_gate_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_cache_lint_matches_workflow_gate_for_unit_and_word_multiplier_numbers(tmp_path: Path) -> None:
    gate = _load_workflow_gate()
    cases = [
        {"id": "k", "source": "奖励 100K", "translations": {"EN": "Reward 100,020"}},
        {"id": "wan", "source": "奖励 123.1万", "translations": {"EN": "Reward 1231005"}},
        {"id": "one_million", "source": "获得 one million 金币", "translations": {"EN": "Get 1,000,000 gold"}},
        {"id": "juta", "source": "dapatkan 1 juta koin", "translations": {"EN": "get 1,000,000 coins"}},
        {"id": "millones", "source": "obtén 2 millones de oro", "translations": {"EN": "get 2,000,000 gold"}},
    ]

    cache_jsonl = tmp_path / "cache.jsonl"
    _write_gate_jsonl(cache_jsonl, cases)
    workflow_result = gate.cache_lint(cache_jsonl, target_langs=["EN"])

    product_result = cache_lint_rows(cases, target_languages=["en"])

    assert product_result["hard_blockers"] == workflow_result["hard_blockers"] == 0


def test_cache_lint_ignores_expected_cjk_small_numbers_and_dates() -> None:
    gate = _load_workflow_gate()
    cases = [
        {"id": "date", "source": "活动将在3月15日开启", "translations": {"EN": "The event starts on March 15"}},
        {"id": "small_count", "source": "每天可领取3次奖励", "translations": {"EN": "Claim rewards up to three times a day"}},
    ]

    cache_jsonl_dir = Path(tempfile.mkdtemp())
    cache_jsonl = cache_jsonl_dir / "cache.jsonl"
    _write_gate_jsonl(cache_jsonl, cases)
    workflow_result = gate.cache_lint(cache_jsonl, target_langs=["EN"])

    product_result = cache_lint_rows(cases, target_languages=["en"])

    assert product_result["hard_blockers"] == workflow_result["hard_blockers"] == 0


def test_cache_lint_only_auto_protects_machine_like_bracket_tokens() -> None:
    gate = _load_workflow_gate()
    row = {"id": "x", "source": "使用 [SDT] 触发 [A_1] 和 {count}，击败 [Monster]"}

    product_result = protected_tokens(row)
    workflow_result = gate.protected_tokens(row)

    assert product_result == workflow_result
    assert "[SDT]" in product_result
    assert "[A_1]" in product_result
    assert "{count}" in product_result
    assert "[Monster]" not in product_result
