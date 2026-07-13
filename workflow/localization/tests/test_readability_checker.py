import unittest

from utils.readability_checker import check_readability


class ReadabilityCheckerTests(unittest.TestCase):
    def _types(self, translation):
        return {
            issue.check_type
            for issue in check_readability(
                row_id=1,
                original="请输入举报原因",
                translation=translation,
                lang="en",
            )
        }

    def test_flags_opaque_ui_abbreviations(self):
        self.assertIn("opaque_abbreviation", self._types("PERR"))
        self.assertIn("opaque_abbreviation", self._types("DTT"))
        self.assertIn("opaque_abbreviation", self._types("IJA"))

    def test_flags_code_like_abbreviation_with_placeholders(self):
        self.assertIn("opaque_abbreviation", self._types("CL##1##2"))

    def test_flags_clipped_words_from_over_compression(self):
        issues = self._types("Coll imme afte purc")

        self.assertIn("clipped_word", issues)

    def test_flags_title_case_overuse_for_error_or_status_messages(self):
        issues = {
            issue.check_type
            for issue in check_readability(
                row_id=2,
                original="该账号角色过多",
                translation="Too Many Roles",
                lang="en",
            )
        }

        self.assertIn("title_case_overuse", issues)

    def test_title_case_overuse_suggests_sentence_case(self):
        issues = check_readability(
            row_id=3,
            original="系统错误",
            translation="System Error",
            lang="en",
        )

        self.assertEqual(issues[0].auto_fix, "System error")

    def test_flags_login_truncation(self):
        self.assertIn("clipped_word", self._types("Logi time"))

    def test_flags_romanized_chinese_name_residue(self):
        issues = {
            issue.check_type
            for issue in check_readability(
                row_id=6,
                original="\u53a8\u5e08\u4f0a\u82b3",
                translation="Chef Yifang",
                lang="en",
            )
        }

        self.assertIn("romanized_name_residue", issues)

    def test_flags_profession_and_resource_overcompression(self):
        cases = [
            ("\u80fd\u6e90\u5b66\u5bb6\u5965\u6587", "Ener Scie Owen"),
            ("10\u70b9\u6539\u826f\u7cbe\u7cb9", "10 Pts impr esse"),
            ("\u6682\u65e0\u641c\u7d22\u7ed3\u679c", "No sear resu yet"),
            ("\u795e\u950b\u88c5\u7532", "Shen Armo"),
            ("\u6ca1\u6709\u7a7a\u4f59\u5e8a\u4f4d", "No beds avai"),
            ("\u96f7\u9706\u4e4b\u4ee4", "Orde Thun"),
            ("\u75be\u901f\u8ffd\u8e2a\u5f39", "Fast Trac Bull"),
            ("\u7206\u88c2\u8f70\u51fb", "Expl bomb"),
            ("\u7a7f\u900f\u5b50\u5f39", "Pene bull"),
            ("\u8986\u76d6\u6253\u51fb", "Satu Stri"),
            ("\u6700\u7ec8\u653b\u901f", "Fina ATK SPD"),
            ("\u591a\u91cd\u5236\u88c1", "Mult sanc"),
            ("\u667a\u80fd\u5236\u5bfc", "Inte guid"),
            ("\u8363\u8000\u5951\u7ea6", "Glor Cont"),
            ("\u5185\u5bb9\u4e0d\u80fd\u4e3a\u7a7a", "Cont cann empt"),
            ("\u60a8\u7684\u8d21\u732e\uff1a##1", "Your cont ##1"),
            ("\u4f4d\u7f6e\u4e0d\u53ef\u6446\u653e", "Loca cann plac"),
            ("\u5df2\u7a7f\u6234\u7684\u88c5\u5907\u4e0d\u53ef\u91cd\u7f6e", "Wear equi cann rese"),
            ("\u6ca1\u6709\u53ef\u7a7f\u6234\u7684\u88c5\u5907", "No wear equi"),
            ("\u5f3a\u529b\u88c5\u5907\u793c\u5305", "Stro equi Pack"),
            ("\u56de\u590d##1\uff1a", "Repl ##1"),
            ("\u56de\u590d\uff1a\u6b64\u6d88\u606f\u5df2\u8fc7\u671f", "Repl This mess expi"),
            ("\u6ca1\u6709\u672a\u8bfb\u90ae\u4ef6", "No unre mess"),
            ("\u9a9a\u6270/\u5237\u5c4f/\u5783\u573e\u4fe1\u606f", "Hara swip spam mess"),
            ("\u90e8\u961f\u5bb9\u91cf", "Troo capa"),
            ("\u8bad\u7ec3\u5bb9\u91cf", "Trai Capa"),
            ("\u786e\u8ba4\u82b1\u8d39##1\u4e2a\u94bb\u77f3\uff1f", "Conf spen ##1 diam"),
            ("\u6218\u673a\u6539\u88c5\u7b49\u7ea7\uff1a##1", "Figh modi leve ##1"),
            ("\u79bb\u7ebf\u6536\u76ca", "Offline Rwds"),
        ]

        for original, translation in cases:
            issues = {
                issue.check_type
                for issue in check_readability(
                    row_id=7,
                    original=original,
                    translation=translation,
                    lang="en",
                )
            }
            self.assertIn("clipped_word", issues)

    def test_allows_stable_game_abbreviations_and_plain_ui_copy(self):
        self.assertEqual(self._types("HP"), set())
        self.assertEqual(self._types("ATK"), set())
        self.assertEqual(self._types("PVP"), set())
        self.assertEqual(self._types("More Info"), set())

    def test_allows_natural_profession_and_resource_terms(self):
        cases = [
            ("\u53a8\u5e08\u4f0a\u82b3", "Chef Yvonne"),
            ("\u80fd\u6e90\u5b66\u5bb6\u5965\u6587", "Energy Scientist Owen"),
            ("10\u70b9\u6539\u826f\u7cbe\u7cb9", "10 Improvement Essence"),
            ("\u6682\u65e0\u641c\u7d22\u7ed3\u679c", "No search results"),
            ("\u795e\u950b\u88c5\u7532", "Divine Edge Armor"),
            ("\u6ca1\u6709\u7a7a\u4f59\u5e8a\u4f4d", "No beds available"),
            ("\u96f7\u9706\u4e4b\u4ee4", "Thunder Order"),
            ("\u75be\u901f\u8ffd\u8e2a\u5f39", "Rapid Tracking Round"),
            ("\u7206\u88c2\u8f70\u51fb", "Explosive Bombardment"),
            ("\u7a7f\u900f\u5b50\u5f39", "Piercing Bullet"),
            ("\u8986\u76d6\u6253\u51fb", "Saturation Strike"),
            ("\u6700\u7ec8\u653b\u901f", "Final ATK SPD"),
            ("\u591a\u91cd\u5236\u88c1", "Multiple Sanctions"),
            ("\u667a\u80fd\u5236\u5bfc", "Smart Guidance"),
            ("\u8363\u8000\u5951\u7ea6", "Glory Contract"),
            ("\u5185\u5bb9\u4e0d\u80fd\u4e3a\u7a7a", "Content cannot be empty"),
            ("\u60a8\u7684\u8d21\u732e\uff1a##1", "Your contribution: ##1"),
            ("\u4f4d\u7f6e\u4e0d\u53ef\u6446\u653e", "Cannot place here"),
            ("\u5df2\u7a7f\u6234\u7684\u88c5\u5907\u4e0d\u53ef\u91cd\u7f6e", "Equipped gear cannot be reset"),
            ("\u6ca1\u6709\u53ef\u7a7f\u6234\u7684\u88c5\u5907", "No wearable gear available"),
            ("\u5f3a\u529b\u88c5\u5907\u793c\u5305", "Powerful Gear Pack"),
            ("\u56de\u590d##1\uff1a", "Reply ##1:"),
            ("\u56de\u590d\uff1a\u6b64\u6d88\u606f\u5df2\u8fc7\u671f", "Reply: This message has expired"),
            ("\u6ca1\u6709\u672a\u8bfb\u90ae\u4ef6", "No unread mail"),
            ("\u9a9a\u6270/\u5237\u5c4f/\u5783\u573e\u4fe1\u606f", "Harassment, spam, or junk messages"),
            ("\u90e8\u961f\u5bb9\u91cf", "Troop Capacity"),
            ("\u8bad\u7ec3\u5bb9\u91cf", "Training Capacity"),
            ("\u786e\u8ba4\u82b1\u8d39##1\u4e2a\u94bb\u77f3\uff1f", "Spend ##1 Diamonds?"),
            ("\u6218\u673a\u6539\u88c5\u7b49\u7ea7\uff1a##1", "Fighter Mod Level: ##1"),
            ("\u79bb\u7ebf\u6536\u76ca", "Offline Rewards"),
        ]

        for original, translation in cases:
            self.assertEqual(
                check_readability(
                    row_id=8,
                    original=original,
                    translation=translation,
                    lang="en",
                ),
                [],
            )

    def test_allows_reasonable_title_case_labels(self):
        issues = check_readability(
            row_id=4,
            original="战令",
            translation="Battle Pass",
            lang="en",
        )

        self.assertEqual(issues, [])

    def test_allows_reasonable_login_feature_title(self):
        issues = check_readability(
            row_id=5,
            original="七日登录",
            translation="7-Day Login",
            lang="en",
        )

        self.assertEqual(issues, [])

    def test_does_not_apply_english_clipped_word_dictionary_to_spanish(self):
        issues = check_readability(
            row_id=9,
            original="我是玩家名字",
            translation="Soy el nombre del jugador de capa alta",
            lang="es",
        )

        self.assertNotIn("clipped_word", {issue.check_type for issue in issues})


if __name__ == "__main__":
    unittest.main()
