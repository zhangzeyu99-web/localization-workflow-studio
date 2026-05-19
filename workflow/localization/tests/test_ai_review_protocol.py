import tempfile
import unittest
from pathlib import Path

from process_language import RowState
from utils.ai_checker import (
    BatchInfo,
    format_batch_prompt,
    merge_review_batches,
    parse_ai_response,
    parse_review_response,
    write_review_files,
    write_response_templates,
)


class AIReviewProtocolTests(unittest.TestCase):
    def test_format_batch_prompt_includes_ui_length_guidance_and_len_metadata(self):
        prompt = format_batch_prompt(
            batch_rows=[
                {
                    "id": 1,
                    "original": "消息推送",
                    "translation": "Push Notifications",
                    "is_ui": True,
                    "ui_length_policy": "hard",
                    "ui_length_source_len": 4,
                    "ui_length_target_len": 17,
                    "ui_length_budget": 12,
                }
            ],
            batch_num=1,
            total_batches=1,
            lang="en",
        )

        self.assertIn("Short-text length rule for Chinese source text with 10 or fewer characters", prompt)
        self.assertIn("LEN:mode=hard,source=4,target=17,budget<=12", prompt)
        self.assertIn("ID | Source | Translation | UI | LEN", prompt)
        self.assertIn("Do not invent opaque abbreviations", prompt)
        self.assertIn("never use opaque abbreviations or clipped words", prompt)
        self.assertIn("Use sentence case by default for English status, error, and prompt text", prompt)

    def test_parse_review_response_supports_exhaustive_keep_and_fix_lines(self):
        decisions = parse_review_response(
            "1 | KEEP\n2 | FIX | Updated translation\n",
            strict=True,
        )

        self.assertEqual(decisions[1].action, "KEEP")
        self.assertEqual(decisions[2].action, "FIX")
        self.assertEqual(decisions[2].corrected_translation, "Updated translation")

    def test_parse_ai_response_keeps_backward_compatible_fix_lines(self):
        corrections = parse_ai_response("1 | Updated translation\n")

        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0].row_id, 1)
        self.assertEqual(corrections[0].corrected_translation, "Updated translation")

    def test_merge_review_batches_applies_only_manifest_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            review_dir = Path(tmp)
            states = {
                1: RowState(1, "orig-1", "trans-1"),
                2: RowState(2, "orig-2", "trans-2"),
            }
            batches = [
                BatchInfo(batch_num=1, total_batches=1, row_ids=[1, 2], prompt_text="prompt"),
            ]
            write_review_files(
                review_dir=review_dir,
                batches=batches,
                states=states,
                batch_type="main",
                lang="en",
                input_path="demo.xlsx",
                ai_scope="all",
            )
            (review_dir / "batch_1_response.txt").write_text(
                "1 | KEEP\n2 | FIX | better-2\n",
                encoding="utf-8",
            )

            reviewed_ids, corrected_ids, summaries = merge_review_batches(review_dir, states, batch_type="main")

            self.assertEqual(reviewed_ids, {1, 2})
            self.assertEqual(corrected_ids, {2})
            self.assertEqual(states[1].fixed_translation, "trans-1")
            self.assertEqual(states[2].fixed_translation, "better-2")
            self.assertEqual(len(summaries), 1)

    def test_merge_review_batches_rejects_incomplete_responses_in_strict_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            review_dir = Path(tmp)
            states = {
                1: RowState(1, "orig-1", "trans-1"),
                2: RowState(2, "orig-2", "trans-2"),
            }
            batches = [
                BatchInfo(batch_num=1, total_batches=1, row_ids=[1, 2], prompt_text="prompt"),
            ]
            write_review_files(
                review_dir=review_dir,
                batches=batches,
                states=states,
                batch_type="main",
                lang="en",
                input_path="demo.xlsx",
                ai_scope="all",
            )
            (review_dir / "batch_1_response.txt").write_text(
                "1 | KEEP\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                merge_review_batches(review_dir, states, batch_type="main", strict=True)

    def test_merge_review_batches_rejects_dataset_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            review_dir = Path(tmp)
            states = {
                1: RowState(1, "orig-1", "trans-1"),
            }
            batches = [
                BatchInfo(batch_num=1, total_batches=1, row_ids=[1], prompt_text="prompt"),
            ]
            write_review_files(
                review_dir=review_dir,
                batches=batches,
                states=states,
                batch_type="main",
                lang="en",
                input_path="demo.xlsx",
                ai_scope="all",
            )
            states[1].fixed_translation = "changed-after-prepare"
            (review_dir / "batch_1_response.txt").write_text(
                "1 | FIX | better-1\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                merge_review_batches(review_dir, states, batch_type="main")

    def test_write_response_templates_seeds_keep_lines_for_all_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            review_dir = Path(tmp)
            states = {
                1: RowState(1, "orig-1", "trans-1"),
                2: RowState(2, "orig-2", "trans-2"),
            }
            batches = [
                BatchInfo(batch_num=1, total_batches=1, row_ids=[1, 2], prompt_text="prompt"),
            ]
            write_review_files(
                review_dir=review_dir,
                batches=batches,
                states=states,
                batch_type="main",
                lang="en",
                input_path="demo.xlsx",
                ai_scope="all",
            )

            created = write_response_templates(review_dir, batch_type="main")

            self.assertEqual(created, 1)
            text = (review_dir / "batch_1_response.txt").read_text(encoding="utf-8")
            self.assertEqual(text, "1 | KEEP\n2 | KEEP\n")

    def test_merge_review_batches_accepts_seeded_keep_templates(self):
        with tempfile.TemporaryDirectory() as tmp:
            review_dir = Path(tmp)
            states = {
                1: RowState(1, "orig-1", "trans-1"),
                2: RowState(2, "orig-2", "trans-2"),
            }
            batches = [
                BatchInfo(batch_num=1, total_batches=1, row_ids=[1, 2], prompt_text="prompt"),
            ]
            write_review_files(
                review_dir=review_dir,
                batches=batches,
                states=states,
                batch_type="main",
                lang="en",
                input_path="demo.xlsx",
                ai_scope="all",
            )
            write_response_templates(review_dir, batch_type="main")

            reviewed_ids, corrected_ids, summaries = merge_review_batches(review_dir, states, batch_type="main")

            self.assertEqual(reviewed_ids, {1, 2})
            self.assertEqual(corrected_ids, set())
            self.assertEqual(states[1].fixed_translation, "trans-1")
            self.assertEqual(states[2].fixed_translation, "trans-2")
            self.assertEqual(len(summaries), 1)

    def test_recheck_merge_can_ignore_drift_for_rows_already_corrected_in_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            review_dir = Path(tmp)
            states = {
                10: RowState(10, "orig-10", "trans-10"),
            }
            main_batches = [
                BatchInfo(batch_num=1, total_batches=1, row_ids=[10], prompt_text="prompt"),
            ]
            recheck_batches = [
                BatchInfo(batch_num=1, total_batches=1, row_ids=[10], prompt_text="prompt"),
            ]
            write_review_files(
                review_dir=review_dir,
                batches=main_batches,
                states=states,
                batch_type="main",
                lang="en",
                input_path="demo.xlsx",
                ai_scope="all",
            )
            write_review_files(
                review_dir=review_dir,
                batches=recheck_batches,
                states=states,
                batch_type="recheck",
                lang="en",
                input_path="demo.xlsx",
                ai_scope="recheck_term_issues",
            )
            (review_dir / "batch_1_response.txt").write_text(
                "10 | FIX | better-10\n",
                encoding="utf-8",
            )
            (review_dir / "batch_recheck_1_response.txt").write_text(
                "10 | KEEP\n",
                encoding="utf-8",
            )

            reviewed_ids, corrected_ids, _ = merge_review_batches(review_dir, states, batch_type="main")
            self.assertEqual(reviewed_ids, {10})
            self.assertEqual(corrected_ids, {10})
            self.assertEqual(states[10].fixed_translation, "better-10")

            reviewed_ids, corrected_ids, _ = merge_review_batches(
                review_dir,
                states,
                batch_type="recheck",
                ignore_fingerprint_for={10},
            )
            self.assertEqual(reviewed_ids, {10})
            self.assertEqual(corrected_ids, set())


if __name__ == "__main__":
    unittest.main()
