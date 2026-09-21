import unittest

from utils.name_policy import (
    BUILDING_NAME_TYPE,
    LOCATION_NAME_TYPE,
    SKILL_NAME_TYPE,
    classify_name_type,
    evaluate_name_translation,
    find_name_collisions,
)


class NamePolicyTests(unittest.TestCase):
    def test_classify_name_type_uses_explicit_categories_only(self):
        self.assertEqual(classify_name_type("技能名"), SKILL_NAME_TYPE)
        self.assertEqual(classify_name_type("UI/技能"), SKILL_NAME_TYPE)
        self.assertEqual(classify_name_type("地点名"), LOCATION_NAME_TYPE)
        self.assertEqual(classify_name_type("Map Name"), LOCATION_NAME_TYPE)
        self.assertEqual(classify_name_type("建筑名"), BUILDING_NAME_TYPE)
        self.assertEqual(classify_name_type("UI/Facility Name"), BUILDING_NAME_TYPE)
        self.assertEqual(classify_name_type("技能描述"), "")
        self.assertEqual(classify_name_type("地图说明"), "")
        self.assertEqual(classify_name_type("建筑说明"), "")
        self.assertEqual(classify_name_type("道具/装备/礼包"), "")

    def test_skill_name_prefers_two_readable_english_words(self):
        issues = evaluate_name_translation(
            row_id=1,
            source="终焉之境",
            translation="Realm of the Final Ending",
            name_type=SKILL_NAME_TYPE,
            lang="en",
        )

        self.assertEqual([issue.check_type for issue in issues], ["skill_name_word_count_watch"])
        self.assertEqual(issues[0].severity, "warning")

    def test_location_name_counts_content_words_not_connectors(self):
        accepted = evaluate_name_translation(
            row_id=2,
            source="太阳神殿",
            translation="Temple of the Sun",
            name_type=LOCATION_NAME_TYPE,
            lang="en",
        )
        verbose = evaluate_name_translation(
            row_id=3,
            source="永夜之谷",
            translation="Valley of Eternal Dark Night",
            name_type=LOCATION_NAME_TYPE,
            lang="en",
        )

        self.assertEqual(accepted, [])
        self.assertEqual([issue.check_type for issue in verbose], ["location_name_compactness_watch"])

    def test_building_name_uses_mobile_map_ui_budget(self):
        accepted = evaluate_name_translation(
            row_id=4,
            source="载具中心",
            translation="Vehicle Center",
            name_type=BUILDING_NAME_TYPE,
            lang="en",
        )
        verbose = evaluate_name_translation(
            row_id=5,
            source="载具组件工厂",
            translation="Support Aircraft Parts Factory",
            name_type=BUILDING_NAME_TYPE,
            lang="en",
        )

        self.assertEqual(accepted, [])
        self.assertEqual(
            [issue.check_type for issue in verbose],
            ["building_name_compactness_watch"],
        )
        self.assertIn("地图短标签建议不超过 14 字符", verbose[0].message)

    def test_name_collision_warns_when_different_sources_share_one_target(self):
        issues = find_name_collisions(
            [
                {
                    "id": 10,
                    "source": "烈焰斩",
                    "translation": "Flame Strike",
                    "name_type": SKILL_NAME_TYPE,
                },
                {
                    "id": 11,
                    "source": "火焰冲击",
                    "translation": "Flame Strike",
                    "name_type": SKILL_NAME_TYPE,
                },
                {
                    "id": 12,
                    "source": "烈焰斩",
                    "translation": "Flame Strike",
                    "name_type": SKILL_NAME_TYPE,
                },
            ],
            lang="en",
        )

        self.assertEqual({issue.row_id for issue in issues}, {10, 11})
        self.assertTrue(all(issue.check_type == "name_translation_collision_watch" for issue in issues))

    def test_non_english_name_policy_is_model_guidance_not_surface_word_limit(self):
        issues = evaluate_name_translation(
            row_id=20,
            source="太阳神殿",
            translation="Temple de la lumière du soleil",
            name_type=LOCATION_NAME_TYPE,
            lang="fr",
        )

        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
