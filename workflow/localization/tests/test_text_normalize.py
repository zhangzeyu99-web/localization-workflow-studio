import unittest

from utils.text_normalize import normalize_english_punctuation


class EnglishPunctuationNormalizationTests(unittest.TestCase):
    def test_preserves_time_ratio_and_url_colons(self):
        self.assertEqual(normalize_english_punctuation("Event starts at 10:00"), "Event starts at 10:00")
        self.assertEqual(normalize_english_punctuation("Use a 16:9 layout"), "Use a 16:9 layout")
        self.assertEqual(normalize_english_punctuation("https://example.com"), "https://example.com")

    def test_still_spaces_label_colons_and_list_punctuation(self):
        self.assertEqual(normalize_english_punctuation("Status:ready,continue;now"), "Status: ready, continue; now")


if __name__ == "__main__":
    unittest.main()
