import unittest

from utils.language_config import (
    LANGUAGE_FILE_HINTS,
    LANGUAGE_NAMES,
    LANGUAGE_OUTPUT_SUFFIX,
    LANGUAGE_TARGET_HEADERS,
    SUPPORTED_TRANSLATION_LANGUAGES,
    normalize_language_code,
    target_header_candidates,
)


class LanguageRegistryConsistencyTests(unittest.TestCase):
    def test_every_supported_language_has_full_metadata(self):
        for code in SUPPORTED_TRANSLATION_LANGUAGES:
            with self.subTest(lang=code):
                self.assertIn(code, LANGUAGE_NAMES)
                self.assertIn(code, LANGUAGE_FILE_HINTS)
                self.assertIn(code, LANGUAGE_OUTPUT_SUFFIX)
                self.assertIn(code, LANGUAGE_TARGET_HEADERS)

    def test_supported_set_covers_historical_delivery_languages(self):
        # Delivery history evidence: 土拨鼠 8-language deep proofreading
        # (en/ja/fr/de/ru/it/es/pt/tr headers), 明日2 full-language workbooks,
        # 勇者 ES/PT full translation, KR勇者 announcements, 闪电突击 EN/IDN/ES/PT,
        # announcement AR column, th/vi/idn Southeast Asia lines.
        historical = {"en", "ko", "ja", "th", "vi", "idn", "fr", "de", "ru", "it", "es", "pt", "tr", "ar"}
        self.assertTrue(historical.issubset(set(SUPPORTED_TRANSLATION_LANGUAGES)))

    def test_output_suffixes_are_unique(self):
        suffixes = list(LANGUAGE_OUTPUT_SUFFIX.values())
        self.assertEqual(len(suffixes), len(set(suffixes)))


class LanguageAliasNormalizationTests(unittest.TestCase):
    def test_common_aliases_normalize_to_supported_codes(self):
        cases = {
            "英语": "en",
            "KR": "ko",
            "jp": "ja",
            "泰语": "th",
            "VN": "vi",
            "id": "idn",
            "印度尼西亚语": "idn",
            "法语": "fr",
            "德语": "de",
            "俄语": "ru",
            "意大利语": "it",
            "西班牙语": "es",
            "西语": "es",
            "葡萄牙语": "pt",
            "pt-BR": "pt",
            "巴葡": "pt",
            "土耳其语": "tr",
            "TK": "tr",
            "阿拉伯语": "ar",
            "阿语": "ar",
        }
        for alias, expected in cases.items():
            with self.subTest(alias=alias):
                self.assertEqual(normalize_language_code(alias), expected)
                self.assertIn(expected, SUPPORTED_TRANSLATION_LANGUAGES)

    def test_target_headers_resolve_chinese_column_names(self):
        self.assertIn("西班牙语", target_header_candidates("es"))
        self.assertIn("阿拉伯语", target_header_candidates("ar"))
        self.assertIn("土耳其语", target_header_candidates("tr"))


if __name__ == "__main__":
    unittest.main()
