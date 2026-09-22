from django.db import migrations


TAXONOMY = (
    (
        "base_geo",
        "基础地理信息数据",
        "描述区域空间框架、基础地理要素和土地利用/覆被的数据。",
        10,
        False,
        (
            ("base_geo_admin", "行政区划", "行政边界、行政单元及相关编码。", 10),
            (
                "base_geo_elements",
                "基础地理要素",
                "水系、道路、保护地、地形等基础空间要素。",
                20,
            ),
            ("base_geo_lucc", "LUCC", "土地利用/覆被现状、分类成果及变化数据。", 30),
        ),
    ),
    (
        "habitat",
        "胡杨生境数据",
        "描述胡杨生长环境中的水、土壤、气候和生物因子。",
        20,
        False,
        (
            ("habitat_water", "水", "地表水、地下水、水文过程与水质指标。", 10),
            ("habitat_soil", "土壤", "土壤样品、理化性质、盐分和养分指标。", 20),
            ("habitat_climate", "气候", "温度、降水、蒸散及其他气候指标。", 30),
            (
                "habitat_biotic",
                "生物环境",
                "伴生生物、土壤微生物和其他生物环境因子。",
                40,
            ),
        ),
    ),
    (
        "distribution",
        "胡杨空间分布信息",
        "描述胡杨分布范围、调查位置及其现场影像证据。",
        30,
        False,
        (
            (
                "distribution_vector",
                "分布矢量",
                "胡杨分布点、分布范围、斑块和相关矢量成果。",
                10,
            ),
            (
                "distribution_survey_image",
                "调查点图片",
                "与调查点、调查事件、个体或样方关联的科研照片。",
                20,
            ),
        ),
    ),
    (
        "thematic",
        "胡杨专题数据",
        "按基因/种质到景观的生态组织尺度管理胡杨专题数据。",
        40,
        False,
        (
            (
                "thematic_gene_germplasm",
                "基因与种质",
                "种质资源、分子数据、基因组数据及其样品来源。",
                10,
            ),
            ("thematic_individual", "个体", "单株胡杨及其时序观测。", 20),
            ("thematic_population", "种群", "胡杨种群单元、范围和种群指标。", 30),
            ("thematic_community", "群落", "群落组成、多样性和功能性状。", 40),
            (
                "thematic_ecosystem",
                "生态系统",
                "水—土—气候—生物耦合过程和生态系统综合指标。",
                50,
            ),
            (
                "thematic_landscape_rs",
                "景观与遥感",
                "遥感影像、指数、变化检测和景观格局数据。",
                60,
            ),
        ),
    ),
)


def seed_data_taxonomy(apps, schema_editor):
    dictionary_item = apps.get_model("catalog", "DictionaryItem")
    data_category = "data_category"
    for root_code, root_name, description, sort_order, selectable, children in TAXONOMY:
        root, _ = dictionary_item.objects.update_or_create(
            dict_type=data_category,
            code=root_code,
            defaults={
                "name": root_name,
                "description": description,
                "parent": None,
                "is_selectable": selectable,
                "sort_order": sort_order,
                "is_active": True,
            },
        )
        for child_code, child_name, child_description, child_order in children:
            dictionary_item.objects.update_or_create(
                dict_type=data_category,
                code=child_code,
                defaults={
                    "name": child_name,
                    "description": child_description,
                    "parent": root,
                    "is_selectable": True,
                    "sort_order": child_order,
                    "is_active": True,
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0010_dictionaryitem_hierarchy"),
    ]

    operations = [
        migrations.RunPython(seed_data_taxonomy, migrations.RunPython.noop),
    ]
