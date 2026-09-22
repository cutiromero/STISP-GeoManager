import {
  cloneDefaultVectorSymbolization,
  defaultGraduatedClass,
  defaultUniqueValueClass,
  type GraduatedClassificationMethod,
  type GraduatedColorRamp,
  type GraduatedRenderer,
  type GraduatedSymbolClass,
  isUniqueValueRenderer,
  type UniqueValueRenderer,
  type UniqueValueSymbolClass,
  type VectorSymbolization,
} from "./symbolization";
import type {
  GeoJsonFeatureCollection,
  ResourceField,
  ResourceListItem,
} from "./types";

type FeatureLike = GeoJsonFeatureCollection["features"][number];

const uniquePalette = [
  "#D65A8A",
  "#2878B5",
  "#2F7D62",
  "#D9912B",
  "#6F5BD9",
  "#C95E2F",
  "#2A9D8F",
  "#8A8F98",
];

export const graduatedColorRamps = {
  green: {
    label: "生态绿",
    colors: ["#E4F6D6", "#B8E186", "#7FBC61", "#2F7D62", "#145A46"],
  },
  blue: {
    label: "水文蓝",
    colors: ["#D8EEF8", "#9BD3E6", "#55A9CF", "#2878B5", "#174D7C"],
  },
  orange: {
    label: "盐分橙",
    colors: ["#FFF2C6", "#F6D66F", "#D9912B", "#C95E2F", "#8F3521"],
  },
  purple: {
    label: "变化紫",
    colors: ["#ECE5F8", "#C7B8EA", "#9884D9", "#6F5BD9", "#44339A"],
  },
} as const satisfies Record<
  GraduatedColorRamp,
  { label: string; colors: readonly string[] }
>;

export const germplasmDnaSexTemplateId = "germplasm.dna-sex-tree.v1";

type BusinessSymbolizationType =
  | "germplasm"
  | "individual"
  | "population"
  | "community"
  | "field_survey";

const fieldAliases = {
  sex: ["性别", "雌雄", "雌/雄", "DNA性别", "dna性别"],
  altitude: ["海拔（米）", "海拔", "高程", "altitude", "elevation"],
  species: ["物种中文名", "种", "species", "中文名"],
  family: ["科中文名", "科"],
  habitat: ["栖息地类型", "生境类型", "habitat"],
  distribution: ["分布方式"],
  importance: ["重要值", "IV", "importance"],
  density: ["密度（某物种个体数/样方面积）", "密度", "density"],
  communityGroup: ["样方分组", "分组", "group"],
  shannon: ["Shannon 多样性指数", "Shannon", "shannon"],
  richness: ["物种丰富度", "丰富度", "species richness", "richness"],
  soilSalt: ["土壤总盐", "盐分", "soil_salinity", "salinity"],
} as const;

export function vectorSymbolizationWithDefaultTemplate({
  resource,
  fields,
  geojson,
  base,
}: {
  resource: ResourceListItem;
  fields: ResourceField[];
  geojson: GeoJsonFeatureCollection;
  base?: VectorSymbolization;
}): VectorSymbolization {
  const next = base ? { ...base } : cloneDefaultVectorSymbolization();
  if (next.renderer?.updatedByUser) return next;
  return applyBusinessDefaultTemplate(resource, fields, geojson, next) ?? next;
}

export function germplasmDnaSexRenderer(
  field: string,
  counts: Map<string, number>,
): UniqueValueRenderer {
  const femaleValues = ["雌株", "雌株珠", "雌性", "♀"];
  const maleValues = ["雄株", "雄性", "♂"];
  const assigned = new Set([...femaleValues, ...maleValues]);
  return {
    type: "uniqueValue",
    field,
    templateId: germplasmDnaSexTemplateId,
    businessType: "germplasm",
    updatedByUser: false,
    classes: [
      {
        id: "female",
        label: "雌性",
        values: femaleValues,
        color: "#D65A8A",
        iconImage: "gm-tree",
        size: 1.08,
        count: countValues(counts, femaleValues),
        visible: true,
      },
      {
        id: "male",
        label: "雄性",
        values: maleValues,
        color: "#2878B5",
        iconImage: "gm-tree",
        size: 1.08,
        count: countValues(counts, maleValues),
        visible: true,
      },
    ],
    defaultClass: {
      ...defaultUniqueValueClass,
      id: "other",
      label: "未知/其他",
      iconImage: "gm-tree",
      color: "#8A8F98",
      size: 0.96,
      count: countOtherValues(counts, assigned),
      visible: true,
    },
    normalizationNotes: counts.has("雌株珠")
      ? ["字段值“雌株珠”疑似“雌株”的录入别名，默认并入雌性类别。"]
      : [],
  };
}

export function buildUniqueValueRenderer(
  field: string,
  counts: Map<string, number>,
  iconImage = "gm-tree",
): UniqueValueRenderer {
  const entries = [...counts.entries()]
    .filter(([value]) => value.length > 0)
    .sort((left, right) => right[1] - left[1])
    .slice(0, 24);
  const classes = entries.map(([value, count], index) => ({
    id: stableClassId(value, index),
    label: value,
    values: [value],
    color: uniquePalette[index % uniquePalette.length] ?? "#2F7D62",
    iconImage,
    size: 1,
    count,
    visible: true,
  }));
  const assigned = new Set(entries.map(([value]) => value));
  return {
    type: "uniqueValue",
    field,
    updatedByUser: true,
    classes,
    defaultClass: {
      ...defaultUniqueValueClass,
      iconImage,
      count: countOtherValues(counts, assigned),
    },
    normalizationNotes: [],
  };
}

export function refreshUniqueValueCounts(
  renderer: UniqueValueRenderer,
  counts: Map<string, number>,
): UniqueValueRenderer {
  const assigned = new Set<string>();
  const classes = renderer.classes.map((item) => {
    item.values.forEach((value) => assigned.add(value));
    return {
      ...item,
      count: countValues(counts, item.values),
    };
  });
  return {
    ...renderer,
    classes,
    defaultClass: {
      ...renderer.defaultClass,
      count: countOtherValues(counts, assigned),
    },
  };
}

export function buildGraduatedRenderer(
  field: string,
  values: number[],
  {
    method = "equalInterval",
    classCount = 5,
    colorRamp = "green",
    iconImage = "gm-marker",
    precision = 2,
  }: {
    method?: GraduatedClassificationMethod;
    classCount?: number;
    colorRamp?: GraduatedColorRamp;
    iconImage?: string;
    precision?: number;
  } = {},
): GraduatedRenderer {
  const cleanValues = values
    .filter((value) => Number.isFinite(value))
    .sort((left, right) => left - right);
  const safeClassCount = clampInteger(classCount, 3, 9);
  const safePrecision = clampInteger(precision, 0, 6);
  const breaks =
    method === "quantile"
      ? quantileBreaks(cleanValues, safeClassCount)
      : equalIntervalBreaks(cleanValues, safeClassCount);
  const colors = graduatedColorRamps[colorRamp].colors;
  const classes = breaks.map(([min, max], index) => {
    const color = colors[Math.min(index, colors.length - 1)] ?? "#2F7D62";
    return {
      id: `range-${index + 1}`,
      label: formatRangeLabel(min, max, safePrecision, index === 0),
      min,
      max,
      color,
      iconImage,
      size: 0.88 + index * 0.08,
      count: countNumericValues(
        cleanValues,
        min,
        max,
        index === breaks.length - 1,
      ),
      visible: true,
    } satisfies GraduatedSymbolClass;
  });
  return {
    type: "graduated",
    field,
    method,
    classCount: safeClassCount,
    precision: safePrecision,
    colorRamp,
    updatedByUser: true,
    classes,
    defaultClass: {
      ...defaultGraduatedClass,
      iconImage,
      count: 0,
    },
  };
}

export function rebuildGraduatedRenderer(
  renderer: GraduatedRenderer,
  values: number[],
  patch: Partial<
    Pick<
      GraduatedRenderer,
      "field" | "method" | "classCount" | "colorRamp" | "precision"
    >
  > = {},
): GraduatedRenderer {
  const next = {
    ...renderer,
    ...patch,
  };
  if (next.method === "manual") {
    return buildManualGraduatedRenderer(next, values, patch);
  }
  const rebuilt = buildGraduatedRenderer(next.field, values, {
    method: next.method,
    classCount: next.classCount,
    colorRamp: next.colorRamp,
    iconImage:
      next.classes[0]?.iconImage ||
      next.defaultClass.iconImage ||
      defaultGraduatedClass.iconImage,
    precision: next.precision,
  });
  return {
    ...rebuilt,
    updatedByUser: true,
    defaultClass: {
      ...rebuilt.defaultClass,
      label: next.defaultClass.label,
      color: next.defaultClass.color,
      iconImage: next.defaultClass.iconImage,
      size: next.defaultClass.size,
      visible: next.defaultClass.visible,
    },
  };
}

export function resizeManualGraduatedRenderer(
  renderer: GraduatedRenderer,
  values: number[],
  classCount: number,
): GraduatedRenderer {
  return buildManualGraduatedRenderer(
    { ...renderer, method: "manual", classCount },
    values,
    { classCount },
  );
}

export function refreshGraduatedCounts(
  renderer: GraduatedRenderer,
  values: number[],
  nonNumericCount = 0,
): GraduatedRenderer {
  const cleanValues = values
    .filter((value) => Number.isFinite(value))
    .sort((left, right) => left - right);
  return {
    ...renderer,
    classes: renderer.classes.map((item, index) => ({
      ...item,
      count:
        item.min === null || item.max === null
          ? 0
          : countNumericValues(
              cleanValues,
              item.min,
              item.max,
              index === renderer.classes.length - 1 ||
                (renderer.method === "manual" && item.min === item.max),
            ),
    })),
    defaultClass: {
      ...renderer.defaultClass,
      count: nonNumericCount,
    },
  };
}

export function numericValuesFromCounts(counts: Map<string, number>) {
  const values: number[] = [];
  let nonNumericCount = 0;
  for (const [rawValue, count] of counts.entries()) {
    const numericValue = parseNumericValue(rawValue);
    if (numericValue === null) {
      nonNumericCount += count;
      continue;
    }
    for (let index = 0; index < count; index += 1) {
      values.push(numericValue);
    }
  }
  return { values, nonNumericCount };
}

export function parseNumericValue(value: unknown): number | null {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (value === null || value === undefined) return null;
  const text = String(value).trim();
  if (!text) return null;
  const normalized = text.replace(/,/g, "");
  const match = normalized.match(/-?\d+(?:\.\d+)?/);
  if (!match) return null;
  const numberValue = Number(match[0]);
  return Number.isFinite(numberValue) ? numberValue : null;
}

export function graduatedRangeLabel(item: GraduatedSymbolClass) {
  if (item.min === null || item.max === null) return "无数值/空值";
  return item.label || formatGraduatedRangeLabel(item.min, item.max, 2);
}

export function formatGraduatedRangeLabel(
  min: number,
  max: number,
  precision = 2,
) {
  return formatRangeLabel(min, max, precision, false);
}

export function countFeatureValues(
  features: FeatureLike[],
  field: string,
): Map<string, number> {
  const counts = new Map<string, number>();
  for (const feature of features) {
    const properties = feature.properties ?? {};
    const raw = (properties as Record<string, unknown>)[field];
    const key = valueLabel(raw);
    if (!key) continue;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return counts;
}

export function fieldValueOptions(
  counts: Map<string, number>,
): Array<{ value: string; label: string }> {
  return [...counts.entries()]
    .sort((left, right) => right[1] - left[1])
    .map(([value, count]) => ({
      value,
      label: `${value}（${count}）`,
    }));
}

export function classValuesLabel(item: UniqueValueSymbolClass) {
  return item.values.length > 0 ? item.values.join("、") : "其他值/空值";
}

export function isGermplasmTemplateRenderer(
  symbolization: VectorSymbolization,
) {
  return (
    isUniqueValueRenderer(symbolization.renderer) &&
    symbolization.renderer.templateId === germplasmDnaSexTemplateId
  );
}

function applyBusinessDefaultTemplate(
  resource: ResourceListItem,
  fields: ResourceField[],
  geojson: GeoJsonFeatureCollection,
  base: VectorSymbolization,
) {
  const businessType = inferBusinessSymbolizationType(resource, fields);
  if (!businessType) return null;
  switch (businessType) {
    case "germplasm":
      return germplasmDefaultTemplate(resource, fields, geojson, base);
    case "individual":
      return individualDefaultTemplate(fields, geojson, base);
    case "population":
      return populationDefaultTemplate(fields, geojson, base);
    case "community":
      return communityDefaultTemplate(fields, geojson, base);
    case "field_survey":
      return fieldSurveyDefaultTemplate(fields, geojson, base);
    default:
      return null;
  }
}

function germplasmDefaultTemplate(
  resource: ResourceListItem,
  fields: ResourceField[],
  geojson: GeoJsonFeatureCollection,
  base: VectorSymbolization,
) {
  const sexField = findSexField(fields);
  if (sexField && isGermplasmResource(resource, fields)) {
    const counts = countFeatureValues(geojson.features, sexField.name);
    return applyPointRenderer(base, {
      renderer: germplasmDnaSexRenderer(sexField.name, counts),
      iconImage: "gm-tree",
      iconColor: "#2F7D62",
      iconSize: 1.08,
      circleColor: "#2F7D62",
    });
  }
  const altitudeField = findFieldByAliases(fields, fieldAliases.altitude);
  if (!altitudeField) return null;
  return buildGraduatedTemplate(base, geojson, altitudeField.name, {
    templateId: "germplasm.altitude.graduated.v1",
    businessType: "germplasm",
    iconImage: "gm-tree",
    colorRamp: "blue",
  });
}

function individualDefaultTemplate(
  fields: ResourceField[],
  geojson: GeoJsonFeatureCollection,
  base: VectorSymbolization,
) {
  const speciesField = findFieldByAliases(fields, fieldAliases.species);
  if (speciesField) {
    return buildUniqueTemplate(base, geojson, speciesField.name, {
      templateId: "individual.species.unique.v1",
      businessType: "individual",
      iconImage: "gm-species",
      defaultLabel: "其他物种",
      maxClasses: 24,
      circleColor: "#2F7D62",
    });
  }
  const familyField = findFieldByAliases(fields, fieldAliases.family);
  if (familyField) {
    return buildUniqueTemplate(base, geojson, familyField.name, {
      templateId: "individual.family.unique.v1",
      businessType: "individual",
      iconImage: "gm-species",
      defaultLabel: "其他科",
      maxClasses: 16,
      circleColor: "#2F7D62",
    });
  }
  const altitudeField = findFieldByAliases(fields, fieldAliases.altitude);
  if (!altitudeField) return null;
  return buildGraduatedTemplate(base, geojson, altitudeField.name, {
    templateId: "individual.altitude.graduated.v1",
    businessType: "individual",
    iconImage: "gm-species",
    colorRamp: "blue",
  });
}

function populationDefaultTemplate(
  fields: ResourceField[],
  geojson: GeoJsonFeatureCollection,
  base: VectorSymbolization,
) {
  const importanceField = findFieldByAliases(fields, fieldAliases.importance);
  const densityField = findFieldByAliases(fields, fieldAliases.density);
  const numericField = importanceField ?? densityField;
  if (numericField) {
    return buildGraduatedTemplate(base, geojson, numericField.name, {
      templateId: importanceField
        ? "population.importance.graduated.v1"
        : "population.density.graduated.v1",
      businessType: "population",
      iconImage: "gm-populus",
      colorRamp: "green",
    });
  }
  const habitatField = findFieldByAliases(fields, fieldAliases.habitat);
  if (!habitatField) return null;
  return buildHabitatTemplate(base, geojson, habitatField.name, {
    templateId: "population.habitat.unique.v1",
    businessType: "population",
    iconImage: "gm-plot",
  });
}

function communityDefaultTemplate(
  fields: ResourceField[],
  geojson: GeoJsonFeatureCollection,
  base: VectorSymbolization,
) {
  const shannonField = findFieldByAliases(fields, fieldAliases.shannon);
  const richnessField = findFieldByAliases(fields, fieldAliases.richness);
  const diversityField = shannonField ?? richnessField;
  if (diversityField) {
    return buildGraduatedTemplate(base, geojson, diversityField.name, {
      templateId: shannonField
        ? "community.shannon.graduated.v1"
        : "community.richness.graduated.v1",
      businessType: "community",
      iconImage: "gm-community",
      colorRamp: "green",
    });
  }
  const groupField = findFieldByAliases(fields, fieldAliases.communityGroup);
  if (groupField) {
    return buildCommunityGroupTemplate(base, geojson, groupField.name);
  }
  const saltField = findFieldByAliases(fields, fieldAliases.soilSalt);
  if (!saltField) return null;
  return buildGraduatedTemplate(base, geojson, saltField.name, {
    templateId: "community.soil-salt.graduated.v1",
    businessType: "community",
    iconImage: "gm-salinity",
    colorRamp: "orange",
  });
}

function fieldSurveyDefaultTemplate(
  fields: ResourceField[],
  geojson: GeoJsonFeatureCollection,
  base: VectorSymbolization,
) {
  const habitatField = findFieldByAliases(fields, fieldAliases.habitat);
  if (habitatField) {
    return buildHabitatTemplate(base, geojson, habitatField.name, {
      templateId: "field_survey.habitat.unique.v1",
      businessType: "field_survey",
      iconImage: "gm-sample",
    });
  }
  const distributionField = findFieldByAliases(
    fields,
    fieldAliases.distribution,
  );
  if (distributionField) {
    return buildUniqueTemplate(base, geojson, distributionField.name, {
      templateId: "field_survey.distribution.unique.v1",
      businessType: "field_survey",
      iconImage: "gm-sample",
      defaultLabel: "其他分布",
      maxClasses: 16,
      circleColor: "#2F7D62",
    });
  }
  const importanceField = findFieldByAliases(fields, fieldAliases.importance);
  const densityField = findFieldByAliases(fields, fieldAliases.density);
  const numericField = importanceField ?? densityField;
  if (!numericField) return null;
  return buildGraduatedTemplate(base, geojson, numericField.name, {
    templateId: importanceField
      ? "field_survey.importance.graduated.v1"
      : "field_survey.density.graduated.v1",
    businessType: "field_survey",
    iconImage: "gm-plot",
    colorRamp: "green",
  });
}

function buildUniqueTemplate(
  base: VectorSymbolization,
  geojson: GeoJsonFeatureCollection,
  fieldName: string,
  {
    templateId,
    businessType,
    iconImage,
    defaultLabel,
    maxClasses = 12,
    circleColor,
  }: {
    templateId: string;
    businessType: BusinessSymbolizationType;
    iconImage: string;
    defaultLabel: string;
    maxClasses?: number;
    circleColor: string;
  },
) {
  const counts = countFeatureValues(geojson.features, fieldName);
  const renderer = buildUniqueValueRenderer(fieldName, counts, iconImage);
  const classes = renderer.classes.slice(0, maxClasses);
  const assigned = new Set(classes.flatMap((item) => item.values));
  return applyPointRenderer(base, {
    renderer: {
      ...renderer,
      templateId,
      businessType,
      updatedByUser: false,
      classes,
      defaultClass: {
        ...renderer.defaultClass,
        id: "other",
        label: defaultLabel,
        iconImage,
        count: countOtherValues(counts, assigned),
      },
    },
    iconImage,
    iconColor: "#2F7D62",
    iconSize: 1,
    circleColor,
  });
}

function buildHabitatTemplate(
  base: VectorSymbolization,
  geojson: GeoJsonFeatureCollection,
  fieldName: string,
  {
    templateId,
    businessType,
    iconImage,
  }: {
    templateId: string;
    businessType: BusinessSymbolizationType;
    iconImage: string;
  },
) {
  const counts = countFeatureValues(geojson.features, fieldName);
  const specs = [
    {
      id: "forest",
      label: "林地",
      values: ["林地"],
      color: "#2F7D62",
      iconImage: "gm-tree",
      size: 1.06,
    },
    {
      id: "grassland",
      label: "草地",
      values: ["草地"],
      color: "#7FBC61",
      iconImage: "gm-leaf",
      size: 1,
    },
    {
      id: "river",
      label: "河沟",
      values: ["河沟", "河道", "沟渠"],
      color: "#2878B5",
      iconImage: "gm-water",
      size: 1,
    },
    {
      id: "farmland",
      label: "农田",
      values: ["农田"],
      color: "#D9912B",
      iconImage,
      size: 1,
    },
    {
      id: "roadside",
      label: "路旁",
      values: ["路旁"],
      color: "#8A8F98",
      iconImage: "gm-marker",
      size: 0.96,
    },
  ];
  const classes = specs
    .map((item) => ({
      ...item,
      count: countValues(counts, item.values),
      visible: true,
    }))
    .filter((item) => item.count > 0);
  if (classes.length === 0) {
    return buildUniqueTemplate(base, geojson, fieldName, {
      templateId,
      businessType,
      iconImage,
      defaultLabel: "其他生境",
      circleColor: "#2F7D62",
    });
  }
  const assigned = new Set(classes.flatMap((item) => item.values));
  return applyPointRenderer(base, {
    renderer: {
      type: "uniqueValue",
      field: fieldName,
      templateId,
      businessType,
      updatedByUser: false,
      classes,
      defaultClass: {
        ...defaultUniqueValueClass,
        id: "other",
        label: "其他生境",
        iconImage,
        count: countOtherValues(counts, assigned),
      },
      normalizationNotes: [],
    },
    iconImage,
    iconColor: "#2F7D62",
    iconSize: 1,
    circleColor: "#2F7D62",
  });
}

function buildCommunityGroupTemplate(
  base: VectorSymbolization,
  geojson: GeoJsonFeatureCollection,
  fieldName: string,
) {
  const counts = countFeatureValues(geojson.features, fieldName);
  const specs = [
    ["group-a", "A组", ["A"], "#2F7D62"],
    ["group-b", "B组", ["B"], "#2878B5"],
    ["group-c", "C组", ["C"], "#D9912B"],
  ] as const;
  const classes = specs
    .map(([id, label, values, color]) => ({
      id,
      label,
      values: [...values],
      color,
      iconImage: "gm-community",
      size: 1,
      count: countValues(counts, [...values]),
      visible: true,
    }))
    .filter((item) => item.count > 0);
  if (classes.length === 0) {
    return buildUniqueTemplate(base, geojson, fieldName, {
      templateId: "community.group.unique.v1",
      businessType: "community",
      iconImage: "gm-community",
      defaultLabel: "其他样方",
      circleColor: "#2F7D62",
    });
  }
  const assigned = new Set(classes.flatMap((item) => item.values));
  return applyPointRenderer(base, {
    renderer: {
      type: "uniqueValue",
      field: fieldName,
      templateId: "community.group.unique.v1",
      businessType: "community",
      updatedByUser: false,
      classes,
      defaultClass: {
        ...defaultUniqueValueClass,
        id: "other",
        label: "其他样方",
        iconImage: "gm-community",
        count: countOtherValues(counts, assigned),
      },
      normalizationNotes: [],
    },
    iconImage: "gm-community",
    iconColor: "#2F7D62",
    iconSize: 1,
    circleColor: "#2F7D62",
  });
}

function buildGraduatedTemplate(
  base: VectorSymbolization,
  geojson: GeoJsonFeatureCollection,
  fieldName: string,
  {
    templateId,
    businessType,
    iconImage,
    colorRamp,
  }: {
    templateId: string;
    businessType: BusinessSymbolizationType;
    iconImage: string;
    colorRamp: GraduatedColorRamp;
  },
) {
  const { values, nonNumericCount } = numericValuesFromCounts(
    countFeatureValues(geojson.features, fieldName),
  );
  const renderer = refreshGraduatedCounts(
    buildGraduatedRenderer(fieldName, values, {
      method: "quantile",
      colorRamp,
      iconImage,
    }),
    values,
    nonNumericCount,
  );
  const circleColor =
    graduatedColorRamps[colorRamp].colors[
      Math.max(0, graduatedColorRamps[colorRamp].colors.length - 2)
    ] ?? "#2F7D62";
  return applyPointRenderer(base, {
    renderer: {
      ...renderer,
      templateId,
      businessType,
      updatedByUser: false,
    },
    iconImage,
    iconColor: circleColor,
    iconSize: 1,
    circleColor,
  });
}

function applyPointRenderer(
  base: VectorSymbolization,
  {
    renderer,
    iconImage,
    iconColor,
    iconSize,
    circleColor,
  }: {
    renderer: UniqueValueRenderer | GraduatedRenderer;
    iconImage: string;
    iconColor: string;
    iconSize: number;
    circleColor: string;
  },
): VectorSymbolization {
  return {
    ...base,
    pointMode: "symbol",
    renderer,
    symbol: {
      ...base.symbol,
      iconImage,
      iconColor,
      iconSize,
      textField: "",
      textSize: 12,
    },
    circle: {
      ...base.circle,
      circleColor,
      circleRadius: 7,
    },
  };
}

function inferBusinessSymbolizationType(
  resource: ResourceListItem,
  fields: ResourceField[],
): BusinessSymbolizationType | null {
  if (isBusinessSymbolizationType(resource.domainType)) {
    return resource.domainType;
  }
  if (isGermplasmResource(resource, fields)) return "germplasm";
  return null;
}

function isBusinessSymbolizationType(
  value: string | null | undefined,
): value is BusinessSymbolizationType {
  return (
    value === "germplasm" ||
    value === "individual" ||
    value === "population" ||
    value === "community" ||
    value === "field_survey"
  );
}

function findSexField(fields: ResourceField[]) {
  return findFieldByAliases(fields, fieldAliases.sex);
}

function isGermplasmResource(
  resource: ResourceListItem,
  fields: ResourceField[],
) {
  if (resource.domainType === "germplasm") return true;
  const fieldNames = new Set(fields.map((field) => field.name));
  return (
    fieldNames.has("DNA样本编号") &&
    [...fieldNames].some((name) => name.includes("性别"))
  );
}

function findFieldByAliases(
  fields: ResourceField[],
  aliases: readonly string[],
) {
  const normalized = new Map(
    fields.map((field) => [normalizeFieldName(field.name), field] as const),
  );
  for (const alias of aliases) {
    const exact = normalized.get(normalizeFieldName(alias));
    if (exact) return exact;
  }
  return fields.find((field) => {
    const fieldName = normalizeFieldName(field.name);
    return aliases.some((alias) =>
      fieldName.includes(normalizeFieldName(alias)),
    );
  });
}

function normalizeFieldName(value: string) {
  return value
    .toLowerCase()
    .replace(/\s/g, "")
    .replace(/_/g, "")
    .replace(/-/g, "")
    .replace(/（/g, "(")
    .replace(/）/g, ")");
}

function countValues(counts: Map<string, number>, values: string[]) {
  return values.reduce((total, value) => total + (counts.get(value) ?? 0), 0);
}

function countOtherValues(counts: Map<string, number>, assigned: Set<string>) {
  let total = 0;
  for (const [value, count] of counts.entries()) {
    if (!assigned.has(value)) total += count;
  }
  return total;
}

function equalIntervalBreaks(values: number[], classCount: number) {
  if (values.length === 0) return [];
  const min = values[0] ?? 0;
  const max = values[values.length - 1] ?? min;
  if (min === max) return [[min, max]] as Array<[number, number]>;
  const step = (max - min) / classCount;
  return Array.from({ length: classCount }, (_, index) => {
    const start = index === 0 ? min : min + step * index;
    const end = index === classCount - 1 ? max : min + step * (index + 1);
    return [start, end] as [number, number];
  });
}

function quantileBreaks(values: number[], classCount: number) {
  if (values.length === 0) return [];
  const breaks: Array<[number, number]> = [];
  let previous = values[0] ?? 0;
  for (let index = 1; index <= classCount; index += 1) {
    const position = Math.ceil((values.length * index) / classCount) - 1;
    const end =
      values[Math.max(0, Math.min(position, values.length - 1))] ?? previous;
    if (index === classCount || end > previous || breaks.length === 0) {
      breaks.push([previous, end]);
      previous = end;
    }
  }
  return breaks.filter(([min, max], index) => index === 0 || max > min);
}

function countNumericValues(
  values: number[],
  min: number,
  max: number,
  includeMax: boolean,
) {
  return values.filter((value) =>
    includeMax ? value >= min && value <= max : value >= min && value < max,
  ).length;
}

function buildManualGraduatedRenderer(
  renderer: GraduatedRenderer,
  values: number[],
  patch: Partial<
    Pick<
      GraduatedRenderer,
      "field" | "method" | "classCount" | "colorRamp" | "precision"
    >
  >,
): GraduatedRenderer {
  const cleanValues = values
    .filter((value) => Number.isFinite(value))
    .sort((left, right) => left - right);
  const safeClassCount = clampInteger(renderer.classCount, 1, 24);
  const safePrecision = clampInteger(renderer.precision, 0, 6);
  const suggestions = equalIntervalBreaks(
    cleanValues,
    Math.max(1, safeClassCount),
  );
  const colors = graduatedColorRamps[renderer.colorRamp].colors;
  const iconImage =
    renderer.classes[0]?.iconImage ||
    renderer.defaultClass.iconImage ||
    defaultGraduatedClass.iconImage;
  const classes = Array.from({ length: safeClassCount }, (_, index) => {
    const current = renderer.classes[index];
    const suggestion =
      suggestions[index] ??
      suggestions[suggestions.length - 1] ??
      manualFallbackRange(cleanValues, index);
    const min =
      current?.min !== null && current?.min !== undefined
        ? current.min
        : suggestion[0];
    const max =
      current?.max !== null && current?.max !== undefined
        ? current.max
        : suggestion[1];
    const labelWasAuto =
      current?.label ===
      formatGraduatedRangeLabel(
        current?.min ?? min,
        current?.max ?? max,
        safePrecision,
      );
    const label =
      current && !labelWasAuto
        ? current.label
        : formatGraduatedRangeLabel(min, max, safePrecision);
    return {
      id: current?.id ?? `range-${index + 1}`,
      label,
      min,
      max,
      color:
        current?.color ||
        colors[Math.min(index, colors.length - 1)] ||
        "#2F7D62",
      iconImage: current?.iconImage || iconImage,
      size: current?.size ?? 0.88 + index * 0.08,
      count: countNumericValues(
        cleanValues,
        min,
        max,
        index === safeClassCount - 1 || min === max,
      ),
      visible: current?.visible ?? true,
    } satisfies GraduatedSymbolClass;
  });
  return {
    ...renderer,
    ...patch,
    type: "graduated",
    method: "manual",
    classCount: safeClassCount,
    precision: safePrecision,
    updatedByUser: true,
    classes,
    defaultClass: {
      ...renderer.defaultClass,
      iconImage: renderer.defaultClass.iconImage || iconImage,
    },
  };
}

function manualFallbackRange(
  values: number[],
  index: number,
): [number, number] {
  if (values.length === 0) return [index, index + 1];
  const min = values[0] ?? 0;
  const max = values[values.length - 1] ?? min;
  if (min === max) return [min + index, min + index + 1];
  return [min, max];
}

function formatRangeLabel(
  min: number,
  max: number,
  precision: number,
  includeLowerHint: boolean,
) {
  const left = formatNumber(min, precision);
  const right = formatNumber(max, precision);
  if (min === max) return left;
  return includeLowerHint ? `${left} - ${right}` : `${left} - ${right}`;
}

function formatNumber(value: number, precision: number) {
  const fixed = value.toFixed(precision);
  return fixed.replace(/\.?0+$/u, "");
}

function clampInteger(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, Math.round(value)));
}

function valueLabel(value: unknown) {
  if (value === null || value === undefined) return "";
  return String(value).trim();
}

function stableClassId(value: string, index: number) {
  const ascii = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return ascii || `class-${index + 1}`;
}
