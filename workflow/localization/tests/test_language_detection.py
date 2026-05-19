import tempfile
import unittest
from pathlib import Path

import pandas as pd

from utils.language_detection import detect_text_language, inspect_language_file
from process_language import _load_term_base


class LanguageDetectionTests(unittest.TestCase):
    def test_detects_english_text(self):
        lang = detect_text_language([
            "Building does not exist in the configuration",
            "Please Level Up the building first",
        ])
        self.assertEqual(lang, "en")

    def test_detects_indonesian_text(self):
        lang = detect_text_language([
            "Bangunan tidak ada dalam konfigurasi",
            "Tingkatkan bangunan terlebih dahulu",
        ])
        self.assertEqual(lang, "idn")

    def test_detects_chinese_text(self):
        lang = detect_text_language([
            "建筑不存在于配置中",
            "请先升级建筑",
        ])
        self.assertEqual(lang, "zh")

    def test_inspects_language_file_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.xlsx"
            df = pd.DataFrame(
                {
                    "ID": [1, 2],
                    "中文": ["建筑不存在于配置中", "请先升级建筑"],
                    "印尼语": ["Bangunan tidak ada dalam konfigurasi", "Tingkatkan bangunan terlebih dahulu"],
                }
            )
            df.to_excel(path, index=False)

            profile = inspect_language_file(path)

            self.assertEqual(profile["source_lang"], "zh")
            self.assertEqual(profile["target_lang"], "idn")

    def test_load_term_base_uses_indonesian_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "terms.xlsx"
            df = pd.DataFrame(
                {
                    "中文术语": ["建筑", "升级"],
                    "英文": ["Building", "Upgrade"],
                    "英语2": ["", "Upgrading"],
                    "印尼语": ["Bangunan", "Tingkatkan"],
                    "印尼语2": ["", "Meningkatkan"],
                }
            )
            df.to_excel(path, index=False)

            term_lookup = _load_term_base(str(path), lang="idn")

            self.assertEqual(term_lookup["建筑"]["primary"], "Bangunan")
            self.assertEqual(term_lookup["升级"]["primary"], "Tingkatkan")
            self.assertIn("Meningkatkan", term_lookup["升级"]["variants"])


if __name__ == "__main__":
    unittest.main()
