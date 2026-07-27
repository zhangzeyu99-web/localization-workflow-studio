import unittest
import tempfile
from pathlib import Path

from openpyxl import Workbook

from process_language import (
    RowState,
    _run_name_policy_checks,
    _run_readability_checks,
    _run_ui_length_checks,
    prepare_ai_review,
    run_machine_review,
)


class ProcessLanguageUILengthTests(unittest.TestCase):
    def test_machine_review_uses_requested_target_header_when_index_is_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "multilingual.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.append(["ID", "CN", "EN", "IT"])
            ws.append([1, "领取奖励", "Claim reward", "Riscatta ricompensa"])
            wb.save(path)
            wb.close()

            _, _, states, _ = run_machine_review(str(path), lang="it", lang_index=None)

            self.assertEqual(states[1].translation, "Riscatta ricompensa")

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

    def test_run_name_policy_checks_adds_ai_review_metadata_and_collision_warning(self):
        states = {
            10: RowState(10, "终焉之境", "Realm of the Final Ending"),
            11: RowState(11, "烈焰斩", "Flame Strike"),
            12: RowState(12, "火焰冲击", "Flame Strike"),
        }
        term_lookup = {
            "终焉之境": {"primary": "Final Realm", "category": "技能名", "name_type": "ui_skill_name"},
            "烈焰斩": {"primary": "Flame Strike", "category": "技能名", "name_type": "ui_skill_name"},
            "火焰冲击": {"primary": "Flame Strike", "category": "技能名", "name_type": "ui_skill_name"},
        }

        _run_name_policy_checks(states, term_lookup, lang="en")

        self.assertEqual(states[10].name_type, "ui_skill_name")
        self.assertEqual(states[10].name_policy["preferred_words"], 2)
        self.assertIn("skill_name_word_count_watch", [issue.check_type for issue in states[10].issues])
        self.assertIn("name_translation_collision_watch", [issue.check_type for issue in states[11].issues])
        self.assertTrue(states[10].needs_human_review)

    def test_prepare_ai_review_passes_english_reference_metadata(self):
        state = RowState(30, "烈焰斩", "Frappe ardente")
        state.source_mode = "cn+en"
        state.reference_en = "Flame Strike"
        state.reference_en_status = "usable"

        batches = prepare_ai_review({30: state}, batch_size=10, lang="fr", scope="all")

        self.assertEqual(len(batches), 1)
        self.assertIn("SRC:cn+en", batches[0].prompt_text)
        self.assertIn("REF_EN:Flame Strike", batches[0].prompt_text)

    def test_machine_review_loads_english_reference_by_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "multilingual.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.append(["ID", "CN", "EN", "FR"])
            ws.append([40, "烈焰斩", "Flame Strike", "Frappe ardente"])
            wb.save(path)
            wb.close()

            _, _, states, _ = run_machine_review(
                str(path),
                lang="fr",
                lang_index=None,
                source_mode="cn+en",
            )

            self.assertEqual(states[40].source_mode, "cn+en")
            self.assertEqual(states[40].reference_en, "Flame Strike")
            self.assertEqual(states[40].reference_en_status, "usable")


if __name__ == "__main__":
    unittest.main()
