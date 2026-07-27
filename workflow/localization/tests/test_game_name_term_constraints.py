import unittest

from utils.term_checker import check_term_hit, is_exact_term_metadata
from utils.translation_harness import _term_hits


class GameNameTermConstraintTests(unittest.TestCase):
    def test_exact_metadata_recognizes_game_name_but_not_negation(self):
        self.assertTrue(is_exact_term_metadata("游戏名"))
        self.assertTrue(is_exact_term_metadata("game name"))
        self.assertFalse(is_exact_term_metadata("非游戏名"))
        self.assertFalse(is_exact_term_metadata("not a game name"))

    def test_game_name_does_not_accept_pluralized_variant(self):
        results = check_term_hit(
            row_id=1,
            original="菇勇者传说现已上线",
            translation="Legend of Mushrooms is now available",
            term_lookup={
                "菇勇者传说": {
                    "primary": "Legend of Mushroom",
                    "variants": [],
                    "category": "游戏名",
                }
            },
        )

        self.assertEqual(len(results), 1)
        self.assertIn(results[0].check_type, {"term_missing", "term_partial_hit"})
        self.assertEqual(results[0].severity, "error")

    def test_common_multiword_term_accepts_pluralized_variant(self):
        results = check_term_hit(
            row_id=2,
            original="联盟成员可领取奖励",
            translation="Alliance Members can claim rewards",
            term_lookup={
                "联盟成员": {
                    "primary": "Alliance Member",
                    "variants": [],
                    "category": "普通术语",
                }
            },
        )

        self.assertEqual(results, [])

    def test_longest_source_term_suppresses_overlapping_child_term(self):
        results = check_term_hit(
            row_id=3,
            original="高级联盟成员可领取奖励",
            translation="Senior Alliance Member can claim rewards",
            term_lookup={
                "联盟成员": {"primary": "Alliance Member", "variants": []},
                "高级联盟成员": {"primary": "Senior Alliance Member", "variants": []},
            },
        )

        self.assertEqual(results, [])

    def test_short_term_is_checked_at_independent_occurrence(self):
        results = check_term_hit(
            row_id=4,
            original="菇勇者传说中的菇勇者可领取奖励",
            translation="The Shroomie in Legend of Mushroom can claim rewards",
            term_lookup={
                "菇勇者": {"primary": "Shroomie", "variants": []},
                "菇勇者传说": {"primary": "Legend of Mushroom", "variants": []},
            },
        )

        self.assertEqual(results, [])

    def test_partial_multiword_term_is_hard_error(self):
        results = check_term_hit(
            row_id=5,
            original="联盟成员可领取奖励",
            translation="Alliance players can claim rewards",
            term_lookup={
                "联盟成员": {"primary": "Alliance Member", "variants": []},
            },
        )

        self.assertEqual(results[0].check_type, "term_partial_hit")
        self.assertEqual(results[0].severity, "error")

    def test_translation_prompt_uses_longest_overlapping_term_and_keeps_metadata(self):
        hits = _term_hits(
            "高级联盟成员可领取奖励",
            {
                "联盟成员": {
                    "primary": "Alliance Member",
                    "variants": [],
                    "category": "普通术语",
                },
                "高级联盟成员": {
                    "primary": "Senior Alliance Member",
                    "variants": [],
                    "category": "游戏名",
                    "name_type": "game",
                },
            },
        )

        self.assertEqual([hit["source"] for hit in hits], ["高级联盟成员"])
        self.assertEqual(hits[0]["category"], "游戏名")
        self.assertEqual(hits[0]["name_type"], "game")


if __name__ == "__main__":
    unittest.main()
