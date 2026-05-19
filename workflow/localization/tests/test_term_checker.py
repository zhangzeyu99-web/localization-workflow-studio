import unittest

from utils.term_checker import check_term_hit, merge_builtin_name_terms


class TermCheckerTests(unittest.TestCase):
    def test_merges_builtin_name_terms_when_term_base_missing_entries(self):
        merged = merge_builtin_name_terms({}, lang="en")

        self.assertIn("红山谷", merged)
        self.assertEqual(merged["红山谷"]["primary"], "Red Valley")
        self.assertIn("巨石阵", merged)
        self.assertEqual(merged["巨石阵"]["primary"], "Stonehenge")

    def test_flags_romanized_name_residue_for_english_map_name(self):
        term_lookup = {
            "红山谷": {"primary": "Red Valley", "variants": []},
        }

        results = check_term_hit(
            row_id=101,
            original="红山谷14",
            translation="Hongshangu14",
            term_lookup=term_lookup,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].check_type, "romanized_name_residue")
        self.assertEqual(results[0].auto_fix, "Red Valley 14")

    def test_flags_romanized_name_residue_for_indonesian_map_name(self):
        term_lookup = {
            "玫瑰湖": {"primary": "Danau Mawar", "variants": []},
        }

        results = check_term_hit(
            row_id=102,
            original="玫瑰湖5",
            translation="Meiguihu 5",
            term_lookup=term_lookup,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].check_type, "romanized_name_residue")
        self.assertEqual(results[0].auto_fix, "Danau Mawar 5")

    def test_flags_spaced_romanized_name_residue(self):
        term_lookup = {
            "溪谷湿地": {"primary": "Creek Wetland", "variants": []},
        }

        results = check_term_hit(
            row_id=104,
            original="溪谷湿地6",
            translation="Xigu Wetland 6",
            term_lookup=term_lookup,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].check_type, "romanized_name_residue")
        self.assertEqual(results[0].auto_fix, "Creek Wetland 6")

    def test_does_not_flag_standard_name_when_expected_name_exists(self):
        term_lookup = {
            "红山谷": {"primary": "Red Valley", "variants": []},
        }

        results = check_term_hit(
            row_id=103,
            original="红山谷14",
            translation="Red Valley 14",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_plural_variant_for_hero_term(self):
        term_lookup = {
            "英雄": {"primary": "Heroes", "variants": []},
        }

        results = check_term_hit(
            row_id=1,
            original="英雄不存在",
            translation="Hero does not exist",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_damage_alias_for_dmg_term(self):
        term_lookup = {
            "伤害": {"primary": "DMG", "variants": []},
        }

        results = check_term_hit(
            row_id=2,
            original="造成额外伤害",
            translation="Deals extra damage",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_attack_alias_for_atk_term(self):
        term_lookup = {
            "攻击": {"primary": "ATK", "variants": []},
        }

        results = check_term_hit(
            row_id=3,
            original="不能攻击盟友",
            translation="Cannot attack allies",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_level_up_family_for_upgrade_term(self):
        term_lookup = {
            "升级": {"primary": "Upgrade", "variants": ["Upgrading"]},
        }

        results = check_term_hit(
            row_id=4,
            original="请先升级建筑",
            translation="Please Level Up the building first",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_character_alias_for_role_term(self):
        term_lookup = {
            "角色": {"primary": "Role", "variants": []},
        }

        results = check_term_hit(
            row_id=5,
            original="创建角色失败",
            translation="Character creation failed",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_training_form_for_train_term(self):
        term_lookup = {
            "训练": {"primary": "Train", "variants": []},
        }

        results = check_term_hit(
            row_id=6,
            original="训练完成",
            translation="Training Complete",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_shared_form_for_share_term(self):
        term_lookup = {
            "分享": {"primary": "Share", "variants": ["Sharing"]},
        }

        results = check_term_hit(
            row_id=7,
            original="分享成功",
            translation="Shared successfully",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_combat_alias_for_battle_term(self):
        term_lookup = {
            "战斗": {"primary": "Battle", "variants": []},
        }

        results = check_term_hit(
            row_id=8,
            original="战斗中无法治疗",
            translation="Cannot heal during combat",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_built_form_for_build_term(self):
        term_lookup = {
            "建造": {"primary": "Build", "variants": ["Construction"]},
        }

        results = check_term_hit(
            row_id=9,
            original="已建造完成",
            translation="The building has been completed",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_improve_alias_for_add_term(self):
        term_lookup = {
            "提升": {"primary": "Add", "variants": ["Increasement"]},
        }

        results = check_term_hit(
            row_id=10,
            original="提升联盟加成效果",
            translation="Improve alliance bonus effects",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_purchased_for_buy_term(self):
        term_lookup = {
            "购买": {"primary": "Buy", "variants": ["Purchase"]},
        }

        results = check_term_hit(
            row_id=11,
            original="已购买",
            translation="Purchased",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_claimed_for_claim_term(self):
        term_lookup = {
            "领取": {"primary": "Claim", "variants": []},
        }

        results = check_term_hit(
            row_id=12,
            original="奖励已领取",
            translation="Reward already claimed",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_deploy_for_march_term(self):
        term_lookup = {
            "出征": {"primary": "March", "variants": []},
        }

        results = check_term_hit(
            row_id=13,
            original="出征",
            translation="Deploy",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_help_for_faq_term(self):
        term_lookup = {
            "帮助": {"primary": "FAQ", "variants": []},
        }

        results = check_term_hit(
            row_id=14,
            original="帮助名额已满",
            translation="Help slots are full",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_boost_for_speedup_term(self):
        term_lookup = {
            "加速": {"primary": "Speedup", "variants": []},
        }

        results = check_term_hit(
            row_id=15,
            original="治疗加速",
            translation="Healing Boost",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_regenerate_for_recover_term(self):
        term_lookup = {
            "恢复": {"primary": "Recover", "variants": []},
        }

        results = check_term_hit(
            row_id=16,
            original="自动恢复",
            translation="Regenerate automatically",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_obtained_for_get_term(self):
        term_lookup = {
            "获取": {"primary": "Get", "variants": ["Acquisition"]},
        }

        results = check_term_hit(
            row_id=17,
            original="未获取",
            translation="Not obtained",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_indonesian_diklaim_for_klaim_term(self):
        term_lookup = {
            "领取": {"primary": "Klaim", "variants": []},
        }

        results = check_term_hit(
            row_id=18,
            original="奖励已领取",
            translation="Hadiah telah diklaim",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_indonesian_membeli_for_beli_term(self):
        term_lookup = {
            "购买": {"primary": "Beli", "variants": ["Pembelian"]},
        }

        results = check_term_hit(
            row_id=19,
            original="您购买了礼包",
            translation="Anda membeli paket",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_indonesian_diatur_for_pengaturan_term(self):
        term_lookup = {
            "设置": {"primary": "Pengaturan", "variants": []},
        }

        results = check_term_hit(
            row_id=20,
            original="编队未设置",
            translation="Tim belum diatur",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_indonesian_berbaris_for_pasukan_term(self):
        term_lookup = {
            "出征": {"primary": "Pasukan", "variants": []},
        }

        results = check_term_hit(
            row_id=21,
            original="是否出征",
            translation="Apakah akan berbaris",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_indonesian_acara_for_event_term(self):
        term_lookup = {
            "活动": {"primary": "Event", "variants": []},
        }

        results = check_term_hit(
            row_id=22,
            original="活动开启中",
            translation="Acara sedang berlangsung",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_accepts_indonesian_kerusakan_for_dmg_term(self):
        term_lookup = {
            "伤害": {"primary": "DMG", "variants": []},
        }

        results = check_term_hit(
            row_id=23,
            original="造成范围伤害",
            translation="menimbulkan kerusakan area",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])

    def test_numeric_term_does_not_match_inside_placeholder_number(self):
        term_lookup = {
            "1小时": {"primary": "1 Hour", "variants": []},
        }

        results = check_term_hit(
            row_id=24,
            original="##1小时##2分钟",
            translation="##1 hr ##2 min",
            term_lookup=term_lookup,
        )

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
