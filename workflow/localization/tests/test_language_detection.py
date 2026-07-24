import tempfile
import unittest
from pathlib import Path

import pandas as pd

from utils.language_detection import detect_text_language, inspect_language_file
from utils.term_checker import check_term_hit
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

    def test_detects_thai_text(self):
        lang = detect_text_language([
            "รับรางวัล",
            "เส้นทางเอาชีวิตรอด",
        ])
        self.assertEqual(lang, "th")

    def test_detects_vietnamese_text(self):
        lang = detect_text_language([
            "Nhận thưởng",
            "Con Đường Sinh Tồn",
        ])
        self.assertEqual(lang, "vi")

    def test_detects_chinese_text(self):
        lang = detect_text_language([
            "建筑不存在于配置中",
            "请先升级建筑",
        ])
        self.assertEqual(lang, "zh")

    def test_detects_japanese_text_with_kana_and_kanji(self):
        lang = detect_text_language([
            "報酬を受け取る",
            "ゲームを開始してください",
        ])
        self.assertEqual(lang, "ja")

    def test_detects_korean_text_with_hangul(self):
        lang = detect_text_language([
            "보상을 받으세요",
            "게임을 시작하세요",
        ])
        self.assertEqual(lang, "ko")

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

    def test_load_term_base_preserves_exact_game_name_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "terms.xlsx"
            df = pd.DataFrame(
                {
                    "CN": ["菇勇者传说"],
                    "EN": ["Legend of Mushroom"],
                    "分类": ["游戏名"],
                }
            )
            df.to_excel(path, index=False)

            term_lookup = _load_term_base(str(path), lang="en")
            results = check_term_hit(
                row_id=1,
                original="菇勇者传说",
                translation="Legend of Mushrooms",
                term_lookup=term_lookup,
            )

            self.assertEqual(len(results), 1)
            self.assertIn(results[0].check_type, {"term_missing", "term_partial_hit"})
            self.assertEqual(results[0].severity, "error")

    def test_load_term_base_category_is_not_shadowed_by_case_constraint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "terms.xlsx"
            df = pd.DataFrame(
                {
                    "CN": ["菇勇者传说"],
                    "EN": ["Legend of Mushroom"],
                    "大小写约束": ["是"],
                    "分类": ["游戏名"],
                }
            )
            df.to_excel(path, index=False)

            term_lookup = _load_term_base(str(path), lang="en")
            results = check_term_hit(
                row_id=1,
                original="菇勇者传说",
                translation="Legend of Mushrooms",
                term_lookup=term_lookup,
            )

            self.assertEqual(len(results), 1)
            self.assertIn(results[0].check_type, {"term_missing", "term_partial_hit"})
            self.assertEqual(results[0].severity, "error")

    def test_load_term_base_uses_japanese_and_korean_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "terms.xlsx"
            df = pd.DataFrame(
                {
                    "CN": ["领取奖励", "战机"],
                    "JA": ["報酬を受け取る", "戦闘機"],
                    "JA2": ["報酬受取", ""],
                    "KO": ["보상 받기", "전투기"],
                    "KO2": ["보상 수령", ""],
                }
            )
            df.to_excel(path, index=False)

            ja_terms = _load_term_base(str(path), lang="ja")
            ko_terms = _load_term_base(str(path), lang="ko")

            self.assertEqual(ja_terms["领取奖励"]["primary"], "報酬を受け取る")
            self.assertIn("報酬受取", ja_terms["领取奖励"]["variants"])
            self.assertEqual(ko_terms["战机"]["primary"], "전투기")
            self.assertIn("보상 수령", ko_terms["领取奖励"]["variants"])

    def test_load_term_base_uses_jp_and_kr_column_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "terms.xlsx"
            df = pd.DataFrame(
                {
                    "CN": ["领取奖励", "战机"],
                    "JP": ["報酬を受け取る", "戦闘機"],
                    "JP2": ["報酬受取", ""],
                    "KR": ["보상 받기", "전투기"],
                    "KR2": ["보상 수령", ""],
                }
            )
            df.to_excel(path, index=False)

            ja_terms = _load_term_base(str(path), lang="ja")
            ko_terms = _load_term_base(str(path), lang="ko")

            self.assertEqual(ja_terms["战机"]["primary"], "戦闘機")
            self.assertIn("報酬受取", ja_terms["领取奖励"]["variants"])
            self.assertEqual(ko_terms["战机"]["primary"], "전투기")
            self.assertIn("보상 수령", ko_terms["领取奖励"]["variants"])


    def test_load_term_base_uses_requested_multilingual_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "terms.xlsx"
            df = pd.DataFrame(
                {
                    "CN": ["领取奖励", "求生之路"],
                    "EN": ["Claim Reward", "Survival Road"],
                    "EN2": ["Claim", ""],
                    "TH": ["รับรางวัล", "เส้นทางเอาชีวิตรอด"],
                    "TH2": ["รับ", ""],
                    "VI": ["Nhận thưởng", "Con Đường Sinh Tồn"],
                    "VI2": ["Nhận", ""],
                    "ID": ["Klaim Hadiah", "Jalan Bertahan Hidup"],
                    "ID2": ["Klaim", ""],
                }
            )
            df.to_excel(path, index=False)

            th_terms = _load_term_base(str(path), lang="th")
            vi_terms = _load_term_base(str(path), lang="vi")
            idn_terms = _load_term_base(str(path), lang="idn")

            self.assertEqual(th_terms["领取奖励"]["primary"], "รับรางวัล")
            self.assertIn("รับ", th_terms["领取奖励"]["variants"])
            self.assertEqual(vi_terms["求生之路"]["primary"], "Con Đường Sinh Tồn")
            self.assertEqual(idn_terms["求生之路"]["primary"], "Jalan Bertahan Hidup")

    def test_load_term_base_uses_supported_visible_language_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "terms.xlsx"
            df = pd.DataFrame(
                {
                    "CN": ["HeroSource"],
                    "FR": ["HeroFR"],
                    "DE": ["HeroDE"],
                    "RU": ["HeroRU"],
                    "IT": ["HeroIT"],
                    "ES": ["HeroES"],
                    "PT": ["HeroPT"],
                    "TR": ["HeroTR"],
                    "TH": ["HeroTH"],
                    "AR": ["HeroAR"],
                }
            )
            df.to_excel(path, index=False)

            expected = {
                "fr": "HeroFR",
                "de": "HeroDE",
                "ru": "HeroRU",
                "it": "HeroIT",
                "es": "HeroES",
                "pt": "HeroPT",
                "tr": "HeroTR",
                "th": "HeroTH",
                "ar": "HeroAR",
            }
            for lang, target in expected.items():
                with self.subTest(lang=lang):
                    term_lookup = _load_term_base(str(path), lang=lang)
                    self.assertEqual(term_lookup["HeroSource"]["primary"], target)


if __name__ == "__main__":
    unittest.main()
