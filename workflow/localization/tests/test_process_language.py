import unittest

from process_language import (
    RowState,
    _run_readability_checks,
    _run_ui_length_checks,
    prepare_ai_review,
)


class ProcessLanguageUILengthTests(unittest.TestCase):
    def test_run_ui_length_checks_marks_hard_overflow_rows_for_review(self):
        state = RowState(1, "消息推送", "Push notifications enabled immediately")
        state.is_ui = True
        states = {1: state}

        _run_ui_length_checks(states, lang="en")

        self.assertTrue(state.needs_human_review)
        self.assertEqual(state.issues[0].check_type, "ui_length_overflow")
        self.assertEqual(state.short_text_length_policy, "hard")
        self.assertEqual(state.review_confidence, 0.9)

    def test_run_ui_length_checks_marks_soft_overflow_rows_for_review(self):
        state = RowState(2, "当前积分奖励", "Current Event Point Reward Available")
        state.is_ui = False
        states = {2: state}

        _run_ui_length_checks(states, lang="en")

        self.assertTrue(state.needs_human_review)
        self.assertEqual(state.issues[0].check_type, "short_text_length_watch")
        self.assertEqual(state.short_text_length_policy, "soft")
        self.assertEqual(state.review_confidence, 0.7)

    def test_run_ui_length_checks_exempts_numbered_proper_names(self):
        state = RowState(3, "红山谷14", "Red Valley 14")
        state.is_ui = True
        states = {3: state}

        _run_ui_length_checks(states, lang="en")

        self.assertEqual(state.issues, [])
        self.assertFalse(state.needs_human_review)
        self.assertEqual(state.short_text_length_policy, "exempt")

    def test_prepare_ai_review_includes_len_metadata_for_soft_short_text(self):
        state = RowState(4, "当前积分奖励", "Current Event Point Reward Available")
        state.is_ui = False
        states = {4: state}
        _run_ui_length_checks(states, lang="en")

        batches = prepare_ai_review(states, batch_size=10, lang="en", scope="issues_only")

        self.assertEqual(len(batches), 1)
        prompt = batches[0].prompt_text
        self.assertIn("mode=soft", prompt)
        self.assertIn("budget<=", prompt)

    def test_run_readability_checks_marks_opaque_abbreviations_for_review(self):
        state = RowState(5, "请输入举报原因", "PERR")
        states = {5: state}

        _run_readability_checks(states, lang="en")

        self.assertTrue(state.needs_human_review)
        self.assertEqual(state.issues[0].check_type, "opaque_abbreviation")
        self.assertEqual(state.review_confidence, 0.95)


if __name__ == "__main__":
    unittest.main()
