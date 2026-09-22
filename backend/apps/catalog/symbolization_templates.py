from __future__ import annotations

from math import isfinite
from typing import Any, Iterable

import pandas as pd


PLATFORM_SYMBOL_ICON_IDS = {
    "gm-marker",
    "gm-point",
    "gm-sample",
    "gm-plot",
    "gm-transect",
    "gm-collection",
    "gm-revisit",
    "gm-populus",
    "gm-tree",
    "gm-leaf",
    "gm-seed",
    "gm-species",
    "gm-community",
    "gm-ancient-tree",
    "gm-station",
    "gm-water",
    "gm-groundwater",
    "gm-soil",
    "gm-salinity",
    "gm-climate",
    "gm-sensor",
    "gm-satellite",
    "gm-pixel",
    "gm-ndvi",
    "gm-npp",
    "gm-imagery",
    "gm-zonal",
    "gm-dna",
    "gm-tube",
    "gm-vial",
    "gm-core-germplasm",
    "gm-germplasm",
    "gm-alert",
    "gm-error",
    "gm-pending",
    "gm-confirmed",
    "gm-quality",
    "gm-priority",
}

UNIQUE_PALETTE = [
    "#D65A8A",
    "#2878B5",
    "#2F7D62",
    "#D9912B",
    "#6F5BD9",
    "#C95E2F",
    "#2A9D8F",
    "#8A8F98",
]

GRADUATED_RAMPS = {
    "green": ["#E4F6D6", "#B8E186", "#7FBC61", "#2F7D62", "#145A46"],
    "blue": ["#D8EEF8", "#9BD3E6", "#55A9CF", "#2878B5", "#174D7C"],
    "orange": ["#FFF2C6", "#F6D66F", "#D9912B", "#C95E2F", "#8F3521"],
    "purple": ["#ECE5F8", "#C7B8EA", "#9884D9", "#6F5BD9", "#44339A"],
}

FIELD_ALIASES = {
    "sex": ["性别", "雌雄", "DNA性别", "dna性别"],
    "altitude": ["海拔（米）", "海拔", "高程", "altitude", "elevation"],
    "species": ["物种中文名", "种", "species", "中文名"],
    "family": ["科中文名", "科"],
    "genus": ["属中文名", "属"],
    "region": ["地州", "地区"],
    "habitat": ["栖息地类型", "生境类型", "habitat"],
    "distribution": ["分布方式"],
    "importance": ["重要值", "IV", "importance"],
    "density": ["密度（某物种个体数/样方面积）", "密度", "density"],
    "coverage": ["盖度（草、灌）/100", "盖度", "coverage"],
    "community_group": ["样方分组", "分组", "group"],
    "shannon": ["Shannon 多样性指数", "Shannon", "shannon"],
    "richness": ["物种丰富度", "丰富度", "species richness", "richness"],
    "soil_salt": ["土壤总盐", "盐分", "soil_salinity", "salinity"],
    "soil_water": ["土壤含水量", "soil_moisture", "moisture"],
    "npp": ["净初级生产力", "NPP", "npp"],
}


def recommended_symbolization_templates(
    domain_type: str, frame: pd.DataFrame, field_names: Iterable[str]
) -> list[dict[str, Any]]:
    fields = list(field_names)
    builders = {
        "germplasm": _germplasm_templates,
        "individual": _individual_templates,
        "population": _population_templates,
        "community": _community_templates,
        "field_survey": _field_survey_templates,
    }
    templates = builders.get(domain_type, lambda *_: [])(frame, fields)
    return sorted(templates, key=lambda item: (not item["isPrimary"], item["priority"]))


def _germplasm_templates(frame: pd.DataFrame, fields: list[str]) -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    sex_field = _find_field(fields, "sex")
    altitude_field = _find_field(fields, "altitude")
    if sex_field:
        female_values = ["雌株", "雌株珠", "雌性", "♀"]
        male_values = ["雄株", "雄性", "♂"]
        counts = _category_counts(frame, sex_field)
        templates.append(
            _template(
                "germplasm.dna-sex-tree.v1",
                "种质性别树图标",
                "按 DNA 性别区分雌株、雄株和未知样本，适合作为种质数据默认地图表达。",
                "germplasm",
                "uniqueValue",
                sex_field,
                True,
                10,
                _unique_symbolization(
                    sex_field,
                    "germplasm.dna-sex-tree.v1",
                    "germplasm",
                    "gm-tree",
                    [
                        _unique_class(
                            "female",
                            "雌株",
                            female_values,
                            "#D65A8A",
                            "gm-tree",
                            1.08,
                            _count_values(counts, female_values),
                        ),
                        _unique_class(
                            "male",
                            "雄株",
                            male_values,
                            "#2878B5",
                            "gm-tree",
                            1.08,
                            _count_values(counts, male_values),
                        ),
                    ],
                    _unique_default(
                        "未知/其他",
                        "gm-tree",
                        _count_other(counts, [*female_values, *male_values]),
                    ),
                    circle_color="#2F7D62",
                ),
                warnings=_alias_warning(sex_field, "性别"),
            )
        )
    if altitude_field:
        templates.append(
            _graduated_template(
                frame,
                altitude_field,
                "germplasm.altitude.graduated.v1",
                "种质海拔分级",
                "按采集点海拔分级，辅助查看种质资源的垂直分布差异。",
                "germplasm",
                False,
                30,
                "blue",
                "gm-tree",
            )
        )
    return templates


def _individual_templates(
    frame: pd.DataFrame, fields: list[str]
) -> list[dict[str, Any]]:
    species_field = _find_field(fields, "species")
    family_field = _find_field(fields, "family")
    altitude_field = _find_field(fields, "altitude")
    templates: list[dict[str, Any]] = []
    if species_field:
        templates.append(
            _category_template(
                frame,
                species_field,
                "individual.species.unique.v1",
                "个体物种分类",
                "按物种中文名区分个体采集记录，类别较多时自动归入其他物种。",
                "individual",
                True,
                10,
                "gm-species",
                "其他物种",
                max_classes=24,
                warnings=_alias_warning(species_field, "物种中文名"),
            )
        )
    elif family_field:
        templates.append(
            _category_template(
                frame,
                family_field,
                "individual.family.unique.v1",
                "个体科属分类",
                "未命中物种中文名时，按科中文名作为个体数据备用分类方案。",
                "individual",
                True,
                20,
                "gm-species",
                "其他科",
                match_status="fallback",
                warnings=["未命中“物种中文名”，已降级为“科中文名”分类。"],
            )
        )
    if altitude_field:
        templates.append(
            _graduated_template(
                frame,
                altitude_field,
                "individual.altitude.graduated.v1",
                "个体海拔分级",
                "按采集点海拔分级，辅助查看个体记录的垂直分布。",
                "individual",
                False,
                30,
                "blue",
                "gm-species",
            )
        )
    return templates


def _population_templates(
    frame: pd.DataFrame, fields: list[str]
) -> list[dict[str, Any]]:
    importance_field = _find_field(fields, "importance")
    density_field = _find_field(fields, "density")
    habitat_field = _find_field(fields, "habitat")
    templates: list[dict[str, Any]] = []
    if importance_field or density_field:
        primary = importance_field or density_field
        assert primary is not None
        templates.append(
            _graduated_template(
                frame,
                primary,
                "population.importance.graduated.v1"
                if importance_field
                else "population.density.graduated.v1",
                "种群重要值分级" if importance_field else "种群密度分级",
                "按重要值或密度突出种群优势度和空间差异。",
                "population",
                True,
                10,
                "green",
                "gm-populus",
                match_status="matched" if importance_field else "fallback",
                warnings=[] if importance_field else ["未命中“重要值”，已降级为密度分级。"],
            )
        )
    if habitat_field:
        templates.append(
            _habitat_template(
                frame,
                habitat_field,
                "population.habitat.unique.v1",
                "种群生境类型",
                "按栖息地类型区分种群调查样方，适合查看生境组成。",
                "population",
                False,
                20,
                "gm-plot",
            )
        )
    return templates


def _community_templates(frame: pd.DataFrame, fields: list[str]) -> list[dict[str, Any]]:
    shannon_field = _find_field(fields, "shannon")
    richness_field = _find_field(fields, "richness")
    salt_field = _find_field(fields, "soil_salt")
    group_field = _find_field(fields, "community_group")
    templates: list[dict[str, Any]] = []
    if shannon_field or richness_field:
        primary = shannon_field or richness_field
        assert primary is not None
        templates.append(
            _graduated_template(
                frame,
                primary,
                "community.shannon.graduated.v1"
                if shannon_field
                else "community.richness.graduated.v1",
                "群落多样性分级" if shannon_field else "群落丰富度分级",
                "按 Shannon 多样性指数或物种丰富度展示群落多样性格局。",
                "community",
                True,
                10,
                "green",
                "gm-community",
                match_status="matched" if shannon_field else "fallback",
                warnings=[]
                if shannon_field
                else ["未命中“Shannon 多样性指数”，已降级为物种丰富度分级。"],
            )
        )
    if group_field:
        templates.append(
            _community_group_template(frame, group_field)
        )
    if salt_field:
        templates.append(
            _graduated_template(
                frame,
                salt_field,
                "community.soil-salt.graduated.v1",
                "群落土壤盐分分级",
                "按土壤总盐分级，辅助识别盐渍化梯度。",
                "community",
                False,
                30,
                "orange",
                "gm-salinity",
            )
        )
    return templates


def _field_survey_templates(
    frame: pd.DataFrame, fields: list[str]
) -> list[dict[str, Any]]:
    habitat_field = _find_field(fields, "habitat")
    distribution_field = _find_field(fields, "distribution")
    importance_field = _find_field(fields, "importance")
    density_field = _find_field(fields, "density")
    templates: list[dict[str, Any]] = []
    if habitat_field:
        templates.append(
            _habitat_template(
                frame,
                habitat_field,
                "field_survey.habitat.unique.v1",
                "野外调查生境类型",
                "按栖息地类型区分调查样点，适合作为野外调查数据的默认地图表达。",
                "field_survey",
                True,
                10,
                "gm-sample",
            )
        )
    elif distribution_field:
        templates.append(
            _category_template(
                frame,
                distribution_field,
                "field_survey.distribution.unique.v1",
                "野外调查分布方式",
                "未命中栖息地类型时，按分布方式区分调查记录。",
                "field_survey",
                True,
                20,
                "gm-sample",
                "其他分布",
                match_status="fallback",
                warnings=["未命中“栖息地类型”，已降级为“分布方式”分类。"],
            )
        )
    if importance_field or density_field:
        primary = importance_field or density_field
        assert primary is not None
        templates.append(
            _graduated_template(
                frame,
                primary,
                "field_survey.importance.graduated.v1"
                if importance_field
                else "field_survey.density.graduated.v1",
                "野外调查重要值分级" if importance_field else "野外调查密度分级",
                "按重要值或密度分级，适合查看调查样点的优势度差异。",
                "field_survey",
                False,
                30,
                "green",
                "gm-plot",
                match_status="matched" if importance_field else "fallback",
                warnings=[] if importance_field else ["未命中“重要值”，已降级为密度分级。"],
            )
        )
    return templates


def _habitat_template(
    frame: pd.DataFrame,
    field: str,
    template_id: str,
    name: str,
    description: str,
    business_type: str,
    is_primary: bool,
    priority: int,
    base_icon: str,
) -> dict[str, Any]:
    counts = _category_counts(frame, field)
    class_specs = [
        ("forest", "林地", ["林地"], "#2F7D62", "gm-tree", 1.06),
        ("grassland", "草地", ["草地"], "#7FBC61", "gm-leaf", 1.0),
        ("river", "河沟", ["河沟", "河道", "沟渠"], "#2878B5", "gm-water", 1.0),
        ("farmland", "农田", ["农田"], "#D9912B", base_icon, 1.0),
        ("roadside", "路旁", ["路旁"], "#8A8F98", "gm-marker", 0.96),
    ]
    assigned: list[str] = []
    classes = []
    for class_id, label, values, color, icon, size in class_specs:
        count = _count_values(counts, values)
        if count <= 0:
            continue
        assigned.extend(values)
        classes.append(_unique_class(class_id, label, values, color, icon, size, count))
    if not classes:
        return _category_template(
            frame,
            field,
            template_id,
            name,
            description,
            business_type,
            is_primary,
            priority,
            base_icon,
            "其他生境",
        )
    return _template(
        template_id,
        name,
        description,
        business_type,
        "uniqueValue",
        field,
        is_primary,
        priority,
        _unique_symbolization(
            field,
            template_id,
            business_type,
            base_icon,
            classes,
            _unique_default("其他生境", base_icon, _count_other(counts, assigned)),
        ),
    )


def _community_group_template(frame: pd.DataFrame, field: str) -> dict[str, Any]:
    counts = _category_counts(frame, field)
    specs = [
        ("group-a", "A组", ["A"], "#2F7D62"),
        ("group-b", "B组", ["B"], "#2878B5"),
        ("group-c", "C组", ["C"], "#D9912B"),
    ]
    classes = [
        _unique_class(class_id, label, values, color, "gm-community", 1.0, _count_values(counts, values))
        for class_id, label, values, color in specs
        if _count_values(counts, values) > 0
    ]
    return _template(
        "community.group.unique.v1",
        "群落样方分组",
        "按样方分组区分群落样点，适合核对模板内 A/B/C 分组。",
        "community",
        "uniqueValue",
        field,
        False,
        20,
        _unique_symbolization(
            field,
            "community.group.unique.v1",
            "community",
            "gm-community",
            classes,
            _unique_default("其他样方", "gm-community", _count_other(counts, ["A", "B", "C"])),
        ),
    )


def _category_template(
    frame: pd.DataFrame,
    field: str,
    template_id: str,
    name: str,
    description: str,
    business_type: str,
    is_primary: bool,
    priority: int,
    icon: str,
    default_label: str,
    *,
    max_classes: int = 12,
    match_status: str = "matched",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    counts = _category_counts(frame, field)
    classes = []
    assigned: list[str] = []
    for index, (value, count) in enumerate(counts[:max_classes]):
        color = UNIQUE_PALETTE[index % len(UNIQUE_PALETTE)]
        assigned.append(value)
        classes.append(
            _unique_class(
                _stable_class_id(value, index),
                value,
                [value],
                color,
                icon,
                1.0,
                count,
            )
        )
    notes = list(warnings or [])
    if len(counts) > max_classes:
        notes.append(f"字段“{field}”类别较多，仅展开前 {max_classes} 类，其余归入默认类。")
    return _template(
        template_id,
        name,
        description,
        business_type,
        "uniqueValue",
        field,
        is_primary,
        priority,
        _unique_symbolization(
            field,
            template_id,
            business_type,
            icon,
            classes,
            _unique_default(default_label, icon, _count_other(counts, assigned)),
        ),
        match_status=match_status,
        warnings=notes,
    )


def _graduated_template(
    frame: pd.DataFrame,
    field: str,
    template_id: str,
    name: str,
    description: str,
    business_type: str,
    is_primary: bool,
    priority: int,
    ramp: str,
    icon: str,
    *,
    match_status: str = "matched",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    values, non_numeric_count = _numeric_values(frame, field)
    classes = _graduated_classes(values, ramp, icon)
    notes = list(warnings or [])
    if non_numeric_count:
        notes.append(f"字段“{field}”存在 {non_numeric_count} 条空值或非数值，已归入默认类。")
    return _template(
        template_id,
        name,
        description,
        business_type,
        "graduated",
        field,
        is_primary,
        priority,
        _graduated_symbolization(
            field,
            template_id,
            business_type,
            ramp,
            icon,
            classes,
            non_numeric_count,
        ),
        match_status=match_status,
        warnings=notes,
    )


def _template(
    template_id: str,
    name: str,
    description: str,
    business_type: str,
    renderer_type: str,
    primary_field: str,
    is_primary: bool,
    priority: int,
    symbolization: dict[str, Any],
    *,
    match_status: str = "matched",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "templateId": template_id,
        "name": name,
        "description": description,
        "businessType": business_type,
        "rendererType": renderer_type,
        "primaryField": primary_field,
        "matchedFields": [primary_field] if primary_field else [],
        "matchStatus": match_status,
        "isPrimary": is_primary,
        "priority": priority,
        "symbolization": _sanitize_symbolization(symbolization),
        "warnings": warnings or [],
    }


def _unique_symbolization(
    field: str,
    template_id: str,
    business_type: str,
    icon: str,
    classes: list[dict[str, Any]],
    default_class: dict[str, Any],
    *,
    circle_color: str = "#2F7D62",
) -> dict[str, Any]:
    return {
        "opacity": 90,
        "pointMode": "symbol",
        "renderer": {
            "type": "uniqueValue",
            "field": field,
            "templateId": template_id,
            "businessType": business_type,
            "updatedByUser": False,
            "classes": classes,
            "defaultClass": default_class,
            "normalizationNotes": [],
        },
        "symbol": {"iconImage": icon, "iconSize": 1, "textField": ""},
        "circle": {"circleColor": circle_color, "circleRadius": 7},
    }


def _graduated_symbolization(
    field: str,
    template_id: str,
    business_type: str,
    ramp: str,
    icon: str,
    classes: list[dict[str, Any]],
    default_count: int,
) -> dict[str, Any]:
    return {
        "opacity": 90,
        "pointMode": "symbol",
        "renderer": {
            "type": "graduated",
            "field": field,
            "method": "quantile",
            "classCount": max(1, len(classes)),
            "precision": 2,
            "colorRamp": ramp,
            "templateId": template_id,
            "businessType": business_type,
            "updatedByUser": False,
            "classes": classes,
            "defaultClass": {
                "id": "no-data",
                "label": "无数值/空值",
                "min": None,
                "max": None,
                "color": "#8A8F98",
                "iconImage": icon,
                "size": 0.9,
                "count": default_count,
                "visible": True,
            },
        },
        "symbol": {"iconImage": icon, "iconSize": 1, "textField": ""},
        "circle": {"circleColor": GRADUATED_RAMPS.get(ramp, GRADUATED_RAMPS["green"])[-2], "circleRadius": 7},
    }


def _unique_class(
    class_id: str,
    label: str,
    values: list[str],
    color: str,
    icon: str,
    size: float,
    count: int,
) -> dict[str, Any]:
    return {
        "id": class_id,
        "label": label,
        "values": values,
        "color": color,
        "iconImage": _safe_icon(icon),
        "size": size,
        "count": int(count),
        "visible": True,
    }


def _unique_default(label: str, icon: str, count: int) -> dict[str, Any]:
    return _unique_class("other", label, [], "#8A8F98", icon, 0.92, count)


def _graduated_classes(values: list[float], ramp: str, icon: str) -> list[dict[str, Any]]:
    if not values:
        return []
    colors = GRADUATED_RAMPS.get(ramp, GRADUATED_RAMPS["green"])
    breaks = _quantile_breaks(values, 5)
    classes = []
    for index, (minimum, maximum) in enumerate(breaks):
        color = colors[min(index, len(colors) - 1)]
        classes.append(
            {
                "id": f"range-{index + 1}",
                "label": _range_label(minimum, maximum),
                "min": minimum,
                "max": maximum,
                "color": color,
                "iconImage": _safe_icon(icon),
                "size": round(0.88 + index * 0.08, 2),
                "count": _count_numeric(values, minimum, maximum, index == len(breaks) - 1),
                "visible": True,
            }
        )
    return classes


def _find_field(fields: list[str], alias_key: str) -> str | None:
    aliases = FIELD_ALIASES[alias_key]
    normalized = {_normalize_field(field): field for field in fields}
    for alias in aliases:
        exact = normalized.get(_normalize_field(alias))
        if exact:
            return exact
    for field in fields:
        normalized_field = _normalize_field(field)
        if any(_normalize_field(alias) in normalized_field for alias in aliases):
            return field
    return None


def _category_counts(frame: pd.DataFrame, field: str) -> list[tuple[str, int]]:
    if field not in frame:
        return []
    values = frame[field].dropna().astype(str).str.strip()
    values = values[values != ""]
    return [(str(value), int(count)) for value, count in values.value_counts().items()]


def _numeric_values(frame: pd.DataFrame, field: str) -> tuple[list[float], int]:
    if field not in frame:
        return [], 0
    raw = frame[field].dropna()
    parsed = pd.to_numeric(raw.astype(str).str.replace(",", "", regex=False), errors="coerce")
    values = [float(value) for value in parsed.dropna().tolist() if isfinite(float(value))]
    non_numeric_count = int(len(raw) - len(values))
    values.sort()
    return values, non_numeric_count


def _quantile_breaks(values: list[float], class_count: int) -> list[tuple[float, float]]:
    if not values:
        return []
    if values[0] == values[-1]:
        return [(_round(values[0]), _round(values[-1]))]
    breaks: list[tuple[float, float]] = []
    previous = values[0]
    for index in range(1, class_count + 1):
        position = max(0, min((len(values) * index + class_count - 1) // class_count - 1, len(values) - 1))
        end = values[position]
        if index == class_count or end > previous or not breaks:
            breaks.append((_round(previous), _round(end)))
            previous = end
    return [(minimum, maximum) for minimum, maximum in breaks if minimum <= maximum]


def _count_values(counts: list[tuple[str, int]], values: list[str]) -> int:
    value_set = {str(value).strip() for value in values}
    return sum(count for value, count in counts if value in value_set)


def _count_other(counts: list[tuple[str, int]], assigned: Iterable[str]) -> int:
    assigned_set = {str(value).strip() for value in assigned}
    return sum(count for value, count in counts if value not in assigned_set)


def _count_numeric(values: list[float], minimum: float, maximum: float, include_max: bool) -> int:
    if include_max:
        return sum(1 for value in values if minimum <= value <= maximum)
    return sum(1 for value in values if minimum <= value < maximum)


def _range_label(minimum: float, maximum: float) -> str:
    if minimum == maximum:
        return _format_number(minimum)
    return f"{_format_number(minimum)} - {_format_number(maximum)}"


def _format_number(value: float) -> str:
    text = f"{value:.2f}"
    return text.rstrip("0").rstrip(".")


def _round(value: float) -> float:
    return round(float(value), 6)


def _normalize_field(value: str) -> str:
    return (
        str(value)
        .lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
        .replace("（", "(")
        .replace("）", ")")
    )


def _safe_icon(icon: str) -> str:
    return icon if icon in PLATFORM_SYMBOL_ICON_IDS else "gm-marker"


def _sanitize_symbolization(symbolization: dict[str, Any]) -> dict[str, Any]:
    renderer = symbolization.get("renderer")
    if isinstance(renderer, dict):
        classes = renderer.get("classes")
        if isinstance(classes, list):
            for item in classes:
                if isinstance(item, dict):
                    item["iconImage"] = _safe_icon(str(item.get("iconImage") or ""))
        default_class = renderer.get("defaultClass")
        if isinstance(default_class, dict):
            default_class["iconImage"] = _safe_icon(str(default_class.get("iconImage") or ""))
    symbol = symbolization.get("symbol")
    if isinstance(symbol, dict):
        symbol["iconImage"] = _safe_icon(str(symbol.get("iconImage") or ""))
    return symbolization


def _stable_class_id(value: str, index: int) -> str:
    ascii_id = "".join(char.lower() if char.isalnum() and ord(char) < 128 else "-" for char in value)
    ascii_id = "-".join(part for part in ascii_id.split("-") if part)
    return ascii_id or f"class-{index + 1}"


def _alias_warning(field: str, expected: str) -> list[str]:
    if field == expected:
        return []
    return [f"已按字段别名将“{field}”识别为“{expected}”。"]
