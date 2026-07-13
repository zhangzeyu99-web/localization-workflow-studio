import unittest

import pandas as pd

from utils.excel_reader import detect_columns, get_text_pairs, resolve_language_index


class ExcelReaderColumnDetectionTests(unittest.TestCase):
    def test_detects_id_cn_en_layout(self):
        df = pd.DataFrame(
            [
                [1, "使用", "Use"],
                [2, "确认", "Confirm"],
            ],
            columns=["ID", "CN", "EN"],
        )

        col_map = detect_columns(df)
        pairs = get_text_pairs(df, col_map)

        self.assertEqual(col_map["id_col"], "ID")
        self.assertEqual(col_map["original_col"], "CN")
        self.assertEqual(col_map["languages"][0]["translation_col"], "EN")
        self.assertEqual(pairs.loc[0, "original"], "使用")
        self.assertEqual(pairs.loc[0, "translation"], "Use")

    def test_detects_cn_en_en2_term_layout_without_shifting_translation(self):
        df = pd.DataFrame(
            [
                [1, "主堡", "Fortress", ""],
            ],
            columns=["ID", "CN", "EN", "EN2"],
        )

        col_map = detect_columns(df)

        self.assertEqual(col_map["original_col"], "CN")
        self.assertEqual(col_map["languages"][0]["translation_col"], "EN")
        self.assertEqual(col_map["languages"][0]["note_col"], "EN2")

    def test_metadata_column_before_lowercase_en_does_not_shift_translation(self):
        df = pd.DataFrame(
            [
                [17162, "每日宝箱", 0, ""],
                [17163, "今日", 0, ""],
            ],
            columns=["ID", "Cn", "Type", "en"],
        )

        col_map = detect_columns(df)
        pairs = get_text_pairs(df, col_map)

        self.assertEqual(col_map["id_col"], "ID")
        self.assertEqual(col_map["original_col"], "Cn")
        self.assertEqual(col_map["languages"][0]["translation_col"], "en")
        self.assertEqual(pairs.loc[0, "translation"], "")

    def test_detects_ja_and_ko_target_columns_by_language_code(self):
        df = pd.DataFrame(
            [
                [1, "领取奖励", "報酬を受け取る", "보상 받기"],
            ],
            columns=["ID", "CN", "JA", "KO"],
        )

        col_map = detect_columns(df)

        self.assertEqual([lang["translation_col"] for lang in col_map["languages"]], ["JA", "KO"])
        self.assertEqual(get_text_pairs(df, col_map, lang_index=0).loc[0, "translation"], "報酬を受け取る")
        self.assertEqual(get_text_pairs(df, col_map, lang_index=1).loc[0, "translation"], "보상 받기")

    def test_detects_jp_and_kr_target_columns_by_language_code_alias(self):
        df = pd.DataFrame(
            [
                [1, "领取奖励", "報酬を受け取る", "보상 받기"],
            ],
            columns=["ID", "CN", "JP", "KR"],
        )

        col_map = detect_columns(df)

        self.assertEqual([lang["translation_col"] for lang in col_map["languages"]], ["JP", "KR"])
        self.assertEqual(get_text_pairs(df, col_map, lang_index=0).loc[0, "translation"], "報酬を受け取る")
        self.assertEqual(get_text_pairs(df, col_map, lang_index=1).loc[0, "translation"], "보상 받기")

    def test_detects_all_explicit_target_headers_and_resolves_requested_language(self):
        headers = ["EN", "IDN", "DE", "FR", "ES", "PT", "RU", "IT", "TR", "TH"]
        df = pd.DataFrame([[1, "领取奖励", *("" for _ in headers)]], columns=["ID", "CN", *headers])

        col_map = detect_columns(df)

        self.assertEqual([lang["translation_col"] for lang in col_map["languages"]], headers)
        self.assertEqual(resolve_language_index(col_map, "it"), headers.index("IT"))
        self.assertEqual(resolve_language_index(col_map, "ru"), headers.index("RU"))


if __name__ == "__main__":
    unittest.main()
