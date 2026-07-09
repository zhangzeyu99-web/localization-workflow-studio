import unittest

from utils.ui_length_checker import (
    assess_ui_length,
    check_ui_length,
    compute_ui_length_budget,
    is_short_text_candidate,
)


class UILengthCheckerTests(unittest.TestCase):
    def test_short_text_candidate_uses_source_length_within_ten_chars(self):
        self.assertTrue(is_short_text_candidate("消息推送", "Push Notifications"))
        self.assertTrue(is_short_text_candidate("当前积分奖励", "Current Points Reward"))
        self.assertFalse(is_short_text_candidate("这是一整句完整的系统说明文本", "This is a full sentence.",))

    def test_budget_for_english_and_indonesian_short_texts(self):
        self.assertEqual(compute_ui_length_budget(4, lang="en"), 22)
        self.assertEqual(compute_ui_length_budget(4, lang="idn"), 23)
        self.assertEqual(compute_ui_length_budget(4, lang="id"), 23)
        self.assertEqual(compute_ui_length_budget(4, lang="vi"), 23)
        self.assertEqual(compute_ui_length_budget(4, lang="th"), 22)
        self.assertEqual(compute_ui_length_budget(10, lang="en"), 32)

    def test_ui_rows_use_hard_policy(self):
        assessment = assess_ui_length(
            row_id=1,
            original="消息推送",
            translation="Push notifications enabled immediately",
            is_ui=True,
            lang="en",
        )

        self.assertIsNotNone(assessment)
        self.assertEqual(assessment.policy, "hard")
        self.assertTrue(assessment.overflow)

    def test_non_ui_short_rows_use_soft_policy(self):
        assessment = assess_ui_length(
            row_id=2,
            original="当前积分奖励",
            translation="Current Event Point Reward Available",
            is_ui=False,
            lang="en",
        )

        self.assertIsNotNone(assessment)
        self.assertEqual(assessment.policy, "soft")
        self.assertTrue(assessment.overflow)

    def test_numbered_proper_names_are_exempt(self):
        assessment = assess_ui_length(
            row_id=3,
            original="红山谷14",
            translation="Red Valley 14",
            is_ui=True,
            lang="en",
        )

        self.assertIsNotNone(assessment)
        self.assertEqual(assessment.policy, "exempt")

    def test_flags_over_budget_compact_ui_text(self):
        results = check_ui_length(
            row_id=4,
            original="消息推送",
            translation="Push notifications enabled immediately",
            is_ui=True,
            lang="en",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].check_type, "ui_length_overflow")
        self.assertEqual(results[0].policy, "hard")

    def test_flags_over_budget_short_text_as_soft_watch(self):
        results = check_ui_length(
            row_id=5,
            original="当前积分奖励",
            translation="Current Event Point Reward Available",
            is_ui=False,
            lang="en",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].check_type, "short_text_length_watch")
        self.assertEqual(results[0].policy, "soft")

    def test_allows_natural_short_equipment_terms_after_budget_relaxation(self):
        results = check_ui_length(
            row_id=7,
            original="神锋装甲",
            translation="Divine Edge Armor",
            is_ui=True,
            lang="en",
        )

        self.assertEqual(results, [])

    def test_allows_natural_item_terms_after_budget_relaxation(self):
        results = check_ui_length(
            row_id=8,
            original="10点改良精粹",
            translation="10 Improvement Essence",
            is_ui=True,
            lang="en",
        )

        self.assertEqual(results, [])

    def test_accepts_compact_translation_within_budget(self):
        results = check_ui_length(
            row_id=6,
            original="消息推送",
            translation="Push Alerts",
            is_ui=True,
            lang="en",
        )

        self.assertEqual(results, [])

    def test_allows_clear_four_character_ui_terms_after_budget_relaxation(self):
        results = check_ui_length(
            row_id=9,
            original="决战蜂后",
            translation="Showdown With Queen Bee",
            is_ui=True,
            lang="en",
        )

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
