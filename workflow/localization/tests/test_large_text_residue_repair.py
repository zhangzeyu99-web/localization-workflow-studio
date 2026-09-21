from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from utils.large_text_residue_repair import repair_cache_residue


class LargeTextResidueRepairTests(unittest.TestCase):
    def test_repairs_only_known_residue_and_preserves_passing_cells(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache.jsonl"
            passing = "Already approved <@1> text"
            rows = [
                {
                    "key": "pass",
                    "cn": "已通过",
                    "term_hits": [],
                    "translations": {"EN": passing},
                },
                {
                    "key": "repair",
                    "cn": "今日打包 第三章",
                    "term_hits": [
                        {"source": "今日打包", "translations": {"EN": "Daily Pack"}}
                    ],
                    "translations": {"EN": "今日打包 Chapter 三"},
                },
                {
                    "key": "unsafe",
                    "cn": "自由文本",
                    "term_hits": [],
                    "translations": {"EN": "unresolved 中文 prose"},
                },
            ]
            cache.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                encoding="utf-8",
            )

            report = repair_cache_residue(
                cache,
                target_langs=["EN"],
                report_path=root / "repairs.json",
            )

            output = [json.loads(line) for line in cache.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(output[0]["translations"]["EN"], passing)
            self.assertEqual(output[1]["translations"]["EN"], "Daily Pack Chapter III")
            self.assertEqual(output[2]["translations"]["EN"], "unresolved 中文 prose")
            self.assertEqual(report["changed_cells"], 1)


if __name__ == "__main__":
    unittest.main()
