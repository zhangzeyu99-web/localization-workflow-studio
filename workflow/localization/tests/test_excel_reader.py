import unittest

import pandas as pd

from utils.excel_reader import detect_columns, get_text_pairs


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


if __name__ == "__main__":
    unittest.main()
