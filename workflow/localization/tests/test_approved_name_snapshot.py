import json
import tempfile
from pathlib import Path

import pytest
from openpyxl import Workbook

from utils.approved_name_snapshot import build_snapshot
from utils.large_text_multilingual_pack import _load_terms, _term_hits
from utils.large_text_multilingual_gate import cache_lint


def test_approved_names_reach_recomputed_gate_and_preserve_inputs():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "names.xlsx"
        book = Workbook()
        book.active.append(["ID", "CN", "EN", "RU"])
        book.active.append(["CharacterNameAda", "艾达", "Ada", "Ада"])
        book.save(source)
        original = source.read_bytes()
        snapshot = root / "terms.json"
        build_snapshot(term_base=None, names_workbook=source, sheet_name="Sheet", name_rows=[2], target_langs=["RU"], output=snapshot)
        terms = _load_terms(snapshot, ["RU"])
        assert terms[0]["approved_origin"]["row"] == 2
        row = {"key": "body", "cn": "艾达来了。", "source_mode": "en", "translation_source": "Ada is here.",
               "translations": {"RU": "Эда здесь."}, "term_hits": _term_hits("艾达来了。", terms, source_en="Ada is here.")}
        cache = root / "cache.jsonl"
        cache.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
        assert any(i["type"] == "term_missing" for i in cache_lint(cache, target_langs=["RU"], term_base=snapshot)["issues"])
        row["translations"]["RU"] = "Ада здесь."
        cache.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
        assert cache_lint(cache, target_langs=["RU"], term_base=snapshot)["hard_blockers"] == 0
        assert source.read_bytes() == original


def test_approved_name_conflicts_and_incomplete_rows_fail_before_output(tmp_path):
    source = tmp_path / "names.xlsx"
    book = Workbook()
    book.active.append(["ID", "CN", "EN", "RU"])
    book.active.append(["name", "艾达", "Ada", "Ада"])
    book.active.append(["name2", "艾达", "Ada", "Эда"])
    book.active.append(["name3", "贝拉", "Bella", None])
    book.save(source)
    for rows in ([2, 3], [4], [99]):
        output = tmp_path / "snapshot.json"
        with pytest.raises(ValueError):
            build_snapshot(term_base=None, names_workbook=source, sheet_name="Sheet", name_rows=rows, target_langs=["RU"], output=output)
        assert not output.exists()
