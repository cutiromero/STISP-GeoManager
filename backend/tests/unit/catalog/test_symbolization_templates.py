import pandas as pd
from django.test import SimpleTestCase

from apps.catalog.symbolization_templates import (
    PLATFORM_SYMBOL_ICON_IDS,
    recommended_symbolization_templates,
)


class RecommendedSymbolizationTemplateTests(SimpleTestCase):
    def test_germplasm_template_uses_sex_unique_value_renderer(self):
        frame = pd.DataFrame(
            {
                "DNA样本编号": ["A001", "A002", "A003"],
                "性别": ["雌株", "雄株", "雌株珠"],
                "海拔（米）": [812, 845, 801],
            }
        )

        templates = recommended_symbolization_templates(
            "germplasm", frame, frame.columns
        )

        primary = templates[0]
        self.assertEqual(primary["templateId"], "germplasm.dna-sex-tree.v1")
        self.assertTrue(primary["isPrimary"])
        self.assertEqual(primary["rendererType"], "uniqueValue")
        self.assertEqual(primary["primaryField"], "性别")
        self.assertEqual(primary["symbolization"]["pointMode"], "symbol")
        self.assert_renderer_uses_platform_icons(primary)

    def test_individual_template_prefers_species_classification(self):
        frame = pd.DataFrame(
            {
                "采集号": ["I001", "I002", "I003"],
                "物种中文名": ["胡杨", "灰叶胡杨", "胡杨"],
                "科中文名": ["杨柳科", "杨柳科", "杨柳科"],
                "海拔": [910, 880, 905],
            }
        )

        templates = recommended_symbolization_templates(
            "individual", frame, frame.columns
        )

        primary = templates[0]
        self.assertEqual(primary["templateId"], "individual.species.unique.v1")
        self.assertEqual(primary["rendererType"], "uniqueValue")
        self.assertEqual(primary["primaryField"], "物种中文名")
        self.assert_renderer_uses_platform_icons(primary)

    def test_population_template_prefers_importance_graduated_renderer(self):
        frame = pd.DataFrame(
            {
                "栖息地类型": ["林地", "草地", "河沟", "林地"],
                "重要值": [0.18, 0.42, 0.61, 0.88],
                "密度": [12.5, 8.2, 5.4, 16.7],
            }
        )

        templates = recommended_symbolization_templates(
            "population", frame, frame.columns
        )

        primary = templates[0]
        self.assertEqual(primary["templateId"], "population.importance.graduated.v1")
        self.assertEqual(primary["rendererType"], "graduated")
        self.assertEqual(primary["primaryField"], "重要值")
        self.assertEqual(primary["symbolization"]["renderer"]["method"], "quantile")
        self.assertGreaterEqual(
            len(primary["symbolization"]["renderer"]["classes"]), 1
        )
        self.assert_renderer_uses_platform_icons(primary)

    def test_community_template_prefers_shannon_and_adds_salt_alternative(self):
        frame = pd.DataFrame(
            {
                "样方分组": ["A", "B", "C"],
                "Shannon 多样性指数": [1.2, 1.7, 2.3],
                "物种丰富度": [7, 9, 12],
                "土壤总盐": [0.3, 0.8, 1.4],
            }
        )

        templates = recommended_symbolization_templates(
            "community", frame, frame.columns
        )
        template_ids = [item["templateId"] for item in templates]

        self.assertEqual(templates[0]["templateId"], "community.shannon.graduated.v1")
        self.assertIn("community.group.unique.v1", template_ids)
        self.assertIn("community.soil-salt.graduated.v1", template_ids)
        for template in templates:
            self.assert_renderer_uses_platform_icons(template)

    def test_field_survey_template_prefers_habitat_unique_value_renderer(self):
        frame = pd.DataFrame(
            {
                "栖息地类型": ["林地", "草地", "河沟", "农田"],
                "重要值": [0.21, 0.34, 0.56, 0.78],
            }
        )

        templates = recommended_symbolization_templates(
            "field_survey", frame, frame.columns
        )

        primary = templates[0]
        self.assertEqual(primary["templateId"], "field_survey.habitat.unique.v1")
        self.assertEqual(primary["rendererType"], "uniqueValue")
        self.assertEqual(primary["primaryField"], "栖息地类型")
        self.assert_renderer_uses_platform_icons(primary)

    def assert_renderer_uses_platform_icons(self, template):
        symbolization = template["symbolization"]
        self.assertIn(symbolization["symbol"]["iconImage"], PLATFORM_SYMBOL_ICON_IDS)
        renderer = symbolization["renderer"]
        for item in renderer["classes"]:
            self.assertIn(item["iconImage"], PLATFORM_SYMBOL_ICON_IDS)
        self.assertIn(
            renderer["defaultClass"]["iconImage"], PLATFORM_SYMBOL_ICON_IDS
        )
