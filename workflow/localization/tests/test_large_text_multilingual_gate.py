from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook, load_workbook

from utils.large_text_multilingual_gate import (
    apply_dry_run,
    cache_lint,
    preflight,
    readback_gate,
)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


class LargeTextMultilingualGateTests(unittest.TestCase):
    def test_preflight_flags_large_pack_and_long_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            items = Path(tmp) / "items.jsonl"
            write_jsonl(
                items,
                [
                    {"key": "1", "cn": "短文本"},
                    {"key": "2", "cn": "长" * 301},
                ],
            )

            result = preflight(items, target_langs=["DE", "FR", "ES", "PT", "RU"])

            self.assertEqual(result["unique_items"], 2)
            self.assertEqual(result["target_languages"], ["DE", "FR", "ES", "PT", "RU"])
            self.assertEqual(result["estimated_target_cells"], 10)
            self.assertEqual(result["long_text_items"], 1)
            self.assertIs(result["large_pack"], True)
            self.assertIn("target_languages>4", result["large_pack_reasons"])

    def test_preflight_accepts_windows_utf8_bom_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            items = Path(tmp) / "items.jsonl"
            items.write_text('\ufeff{"key":"1","cn":"开始"}\n', encoding="utf-8")

            result = preflight(items, target_langs=["EN"])

            self.assertEqual(result["unique_items"], 1)
            self.assertEqual(result["target_languages"], ["EN"])

    def test_cache_lint_blocks_missing_translation_cjk_and_token_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache.jsonl"
            write_jsonl(
                cache,
                [
                    {
                        "key": "ok",
                        "cn": "获得{num}金币",
                        "tokens": ["{num}"],
                        "translations": {"DE": "{num} Gold erhalten"},
                    },
                    {
                        "key": "bad",
                        "cn": "消耗{num}钻石和20点体力",
                        "tokens": ["{num}"],
                        "translations": {"DE": "消耗 Diamanten"},
                    },
                    {"key": "missing", "cn": "开始战斗", "translations": {}},
                ],
            )

            result = cache_lint(cache, target_langs=["DE"])

            self.assertEqual(result["hard_blockers"], 4)
            issue_types = {issue["type"] for issue in result["issues"]}
            self.assertLessEqual({"cjk_residue", "protected_token_missing", "number_missing", "empty_translation"}, issue_types)

    def test_cache_lint_accepts_equivalent_wan_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache.jsonl"
            write_jsonl(
                cache,
                [
                    {
                        "key": "number",
                        "cn": "战力达到66.9万",
                        "translations": {"ES": "Alcanza 669,000 de poder"},
                    }
                ],
            )

            result = cache_lint(cache, target_langs=["ES"])

            self.assertEqual(result["hard_blockers"], 0)

    def test_apply_dry_run_uses_safe_style_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.xlsx"
            output = root / "dry_run.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet["A1"] = "source"
            sheet["B1"] = "target"
            sheet["B1"].style = "Headline 1"
            workbook.save(template)

            result = apply_dry_run(template, output)

            self.assertIs(result["ok"], True)
            self.assertTrue(output.exists())
            copied = load_workbook(output)
            try:
                self.assertEqual(copied.active["B2"].value, "dry-run")
            finally:
                copied.close()

    def test_readback_gate_rejects_process_files_and_blank_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            delivery = Path(tmp) / "delivery"
            delivery.mkdir()
            (delivery / "_work.jsonl").write_text("{}", encoding="utf-8")
            workbook_path = delivery / "final.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["ID", "CN", "DE"])
            sheet.append([1, "开始", "Starten"])
            sheet.append([2, "结束", None])
            workbook.save(workbook_path)

            result = readback_gate(delivery, target_langs=["DE"])

            self.assertEqual(result["hard_blockers"], 2)
            issue_types = {issue["type"] for issue in result["issues"]}
            self.assertLessEqual({"process_file_in_delivery", "blank_target_cell"}, issue_types)


if __name__ == "__main__":
    unittest.main()
