import type { AppLocale } from "../i18n";
import type {
  NonGeoAnalytics,
  NonGeoFieldProfile,
  NonGeoTableQueryResult,
  NonGeoTableRow,
  ResourceListItem,
} from "../types";

export const NON_GEO_DEMO_RESOURCE_ID = -1;

type DemoBundle = {
  resource: ResourceListItem;
  analytics: NonGeoAnalytics;
  table: NonGeoTableQueryResult;
};

type MeasureDefinition = {
  name: string;
  zh: string;
  en: string;
  unit: string;
  min: number;
  max: number;
  mean: number;
};

const measureDefinitions: MeasureDefinition[] = [
  {
    name: "plot_number",
    zh: "地点号",
    en: "Plot number",
    unit: "",
    min: 1,
    max: 58,
    mean: 28.7,
  },
  {
    name: "height_m",
    zh: "株高",
    en: "Plant height",
    unit: "m",
    min: 0.12,
    max: 23.6,
    mean: 6.84,
  },
  {
    name: "dbh_cm",
    zh: "胸径",
    en: "Diameter at breast height",
    unit: "cm",
    min: 0.8,
    max: 96.4,
    mean: 21.7,
  },
  {
    name: "crown_width_m",
    zh: "冠幅",
    en: "Crown width",
    unit: "m",
    min: 0.2,
    max: 18.9,
    mean: 4.75,
  },
  {
    name: "leaf_area_cm2",
    zh: "叶面积",
    en: "Leaf area",
    unit: "cm²",
    min: 0.64,
    max: 42.8,
    mean: 13.9,
  },
  {
    name: "specific_leaf_area",
    zh: "比叶面积",
    en: "Specific leaf area",
    unit: "cm²/g",
    min: 28.4,
    max: 286.1,
    mean: 128.7,
  },
  {
    name: "leaf_dry_matter",
    zh: "叶干物质含量",
    en: "Leaf dry matter content",
    unit: "mg/g",
    min: 118,
    max: 468,
    mean: 286,
  },
  {
    name: "leaf_thickness_mm",
    zh: "叶片厚度",
    en: "Leaf thickness",
    unit: "mm",
    min: 0.12,
    max: 1.86,
    mean: 0.62,
  },
  {
    name: "wood_density",
    zh: "木材密度",
    en: "Wood density",
    unit: "g/cm³",
    min: 0.29,
    max: 0.91,
    mean: 0.57,
  },
  {
    name: "seed_mass_mg",
    zh: "种子质量",
    en: "Seed mass",
    unit: "mg",
    min: 0.08,
    max: 18.6,
    mean: 3.42,
  },
  {
    name: "chlorophyll_index",
    zh: "叶绿素指数",
    en: "Chlorophyll index",
    unit: "SPAD",
    min: 12.4,
    max: 71.2,
    mean: 39.8,
  },
  {
    name: "leaf_nitrogen",
    zh: "叶氮含量",
    en: "Leaf nitrogen",
    unit: "mg/g",
    min: 6.2,
    max: 34.8,
    mean: 17.6,
  },
  {
    name: "leaf_phosphorus",
    zh: "叶磷含量",
    en: "Leaf phosphorus",
    unit: "mg/g",
    min: 0.42,
    max: 4.86,
    mean: 1.73,
  },
  {
    name: "leaf_carbon",
    zh: "叶碳含量",
    en: "Leaf carbon",
    unit: "mg/g",
    min: 318,
    max: 512,
    mean: 438,
  },
  {
    name: "soil_moisture",
    zh: "土壤含水量",
    en: "Soil moisture",
    unit: "%",
    min: 1.8,
    max: 36.7,
    mean: 12.9,
  },
  {
    name: "soil_salinity",
    zh: "土壤盐度",
    en: "Soil salinity",
    unit: "g/kg",
    min: 0.18,
    max: 24.6,
    mean: 5.12,
  },
  {
    name: "groundwater_depth",
    zh: "地下水埋深",
    en: "Groundwater depth",
    unit: "m",
    min: 0.8,
    max: 12.4,
    mean: 5.37,
  },
  {
    name: "canopy_cover",
    zh: "冠层覆盖度",
    en: "Canopy cover",
    unit: "%",
    min: 2.1,
    max: 86.4,
    mean: 31.8,
  },
  {
    name: "species_richness",
    zh: "物种丰富度",
    en: "Species richness",
    unit: "",
    min: 2,
    max: 29,
    mean: 11.4,
  },
  {
    name: "shannon_index",
    zh: "香农多样性指数",
    en: "Shannon diversity index",
    unit: "",
    min: 0.18,
    max: 3.42,
    mean: 1.76,
  },
  {
    name: "importance_value",
    zh: "重要值",
    en: "Importance value",
    unit: "%",
    min: 0.8,
    max: 82.7,
    mean: 18.9,
  },
];

const regionCounts = [
  ["巴州地区", "Bayingolin", 483],
  ["阿克苏地区", "Aksu", 373],
  ["和田地区", "Hotan", 373],
  ["喀什地区", "Kashgar", 331],
  ["内蒙古", "Inner Mongolia", 162],
  ["塔城", "Tacheng", 146],
  ["伊犁州", "Ili", 108],
  ["阿勒泰", "Altay", 90],
] as const;

const familyCounts = [
  ["豆科", "Fabaceae", 434],
  ["杨柳科", "Salicaceae", 431],
  ["柽柳科", "Tamaricaceae", 425],
  ["禾本科", "Poaceae", 344],
  ["藜科", "Amaranthaceae", 289],
  ["菊科", "Asteraceae", 151],
] as const;

const lifeFormCounts = [
  ["草本", "Herb", 974],
  ["灌木", "Shrub", 795],
  ["乔木", "Tree", 642],
] as const;

const siteTypeCounts = [
  ["河岸林", "Riparian forest", 801],
  ["荒漠边缘", "Desert margin", 624],
  ["绿洲农田", "Oasis farmland", 488],
  ["恢复样地", "Restoration plot", 498],
] as const;

const rowSeeds = [
  ["巴州地区", "杨柳科", "乔木", "河岸林", "胡杨", "Populus euphratica"],
  ["阿克苏地区", "柽柳科", "灌木", "河岸林", "多枝柽柳", "Tamarix ramosissima"],
  ["和田地区", "豆科", "灌木", "荒漠边缘", "骆驼刺", "Alhagi sparsifolia"],
  ["喀什地区", "禾本科", "草本", "绿洲农田", "芦苇", "Phragmites australis"],
  ["内蒙古", "藜科", "灌木", "荒漠边缘", "梭梭", "Haloxylon ammodendron"],
  ["塔城", "菊科", "草本", "恢复样地", "蒿属植物", "Artemisia sp."],
  ["伊犁州", "杨柳科", "乔木", "河岸林", "灰杨", "Populus pruinosa"],
  ["阿勒泰", "豆科", "草本", "恢复样地", "甘草", "Glycyrrhiza uralensis"],
  ["巴州地区", "柽柳科", "灌木", "河岸林", "刚毛柽柳", "Tamarix hispida"],
  ["阿克苏地区", "禾本科", "草本", "河岸林", "芨芨草", "Achnatherum splendens"],
  ["和田地区", "藜科", "草本", "荒漠边缘", "盐穗木", "Halostachys caspica"],
  ["喀什地区", "杨柳科", "乔木", "恢复样地", "胡杨幼树", "Populus euphratica"],
] as const;

export function createNonGeoDemo(locale: AppLocale): DemoBundle {
  const english = locale === "en-US";
  const l = (zh: string, en: string) => (english ? en : zh);
  const resource: ResourceListItem = {
    id: NON_GEO_DEMO_RESOURCE_ID,
    name: l(
      "胡杨群落物种功能性状演示数据",
      "Poplar community functional-traits demo",
    ),
    code: "platform-demo-poplar-community-traits",
    dataType: "table",
    spatialClass: "non_spatial",
    domainType: "community",
    category: null,
    categoryPath: [
      {
        id: -10,
        code: "thematic",
        name: l("胡杨专题数据", "Poplar thematic data"),
      },
      { id: -11, code: "thematic_community", name: l("群落", "Community") },
    ],
    classificationStatus: "classified",
    availableViews: ["table", "metadata"],
    defaultView: "table",
    source: l("平台内置演示", "Platform demo"),
    provider: l("STISP 演示数据集", "STISP demonstration dataset"),
    dataDate: "2026-08-19",
    spatialExtent: "",
    coordinateSystem: "",
    fileFormat: "DEMO",
    description: l(
      "用于稳定展示胡杨群落组成、功能性状、环境因子、字段画像与明细查询的内置演示数据；不替代用户导入的真实观测记录。",
      "A built-in dataset for demonstrating poplar community composition, functional traits, environmental factors, field profiling, and detail queries. It does not replace user-imported observations.",
    ),
    qualityNote: l(
      "演示数据，仅用于产品功能展示。",
      "Demonstration data for product presentation only.",
    ),
    sizeBytes: 428_600,
    itemCount: 2_411,
    status: "active",
    isQueryable: false,
    isRenderable: false,
    updatedAt: "2026-08-19T12:00:00+08:00",
  };

  const categoryDefinitions = [
    { name: "region", zh: "地区", en: "Region", values: regionCounts },
    { name: "family", zh: "科名", en: "Family", values: familyCounts },
    {
      name: "life_form",
      zh: "生活型（乔、灌、草）",
      en: "Life form (tree, shrub, herb)",
      values: lifeFormCounts,
    },
    {
      name: "site_type",
      zh: "样地类型",
      en: "Site type",
      values: siteTypeCounts,
    },
  ] as const;

  const fields: NonGeoFieldProfile[] = [
    ...categoryDefinitions.map((field) => ({
      name: field.name,
      type: "string",
      label: l(field.zh, field.en),
      description: l(`${field.zh}分类`, `${field.en} category`),
      unit: "",
      role: "category" as const,
      nullable: false,
      nonNullCount: 2_411,
      nullCount: 0,
      completeness: 1,
      uniqueCount: field.values.length,
      sampleValues: field.values.slice(0, 3).map((item) => l(item[0], item[1])),
    })),
    ...measureDefinitions.map((field, index) => ({
      name: field.name,
      type: "float",
      label: l(field.zh, field.en),
      description: l(`${field.zh}数值指标`, `${field.en} measurement`),
      unit: field.unit,
      role: "measure" as const,
      nullable: index % 5 === 0,
      nonNullCount: index % 5 === 0 ? 2_385 : 2_411,
      nullCount: index % 5 === 0 ? 26 : 0,
      completeness: index % 5 === 0 ? 2_385 / 2_411 : 1,
      uniqueCount: Math.min(2_411, 80 + index * 37),
      sampleValues: [field.min, field.mean, field.max],
      min: field.min,
      max: field.max,
      mean: field.mean,
    })),
    ...(
      [
        ["species_cn", "种", "Species"],
        ["scientific_name", "学名", "Scientific name"],
        ["genus", "属名", "Genus"],
        ["survey_team", "调查团队", "Survey team"],
        ["habitat_note", "生境描述", "Habitat note"],
        ["voucher_note", "凭证标本备注", "Voucher note"],
      ] as const
    ).map(([name, zh, en], index) => ({
      name,
      type: "string",
      label: l(zh, en),
      description: l(`${zh}文本信息`, `${en} text`),
      unit: "",
      role: "text" as const,
      nullable: index > 3,
      nonNullCount: index > 3 ? 2_286 : 2_411,
      nullCount: index > 3 ? 125 : 0,
      completeness: index > 3 ? 2_286 / 2_411 : 1,
      uniqueCount: index < 3 ? 86 + index * 12 : 24 + index,
      sampleValues:
        index === 0
          ? rowSeeds.slice(0, 3).map((item) => l(item[4], item[5]))
          : [l("已记录", "Recorded")],
    })),
  ];

  const rows: NonGeoTableRow[] = rowSeeds.map((seed, index) => ({
    region: l(
      seed[0],
      regionCounts.find((item) => item[0] === seed[0])?.[1] ?? seed[0],
    ),
    family: l(
      seed[1],
      familyCounts.find((item) => item[0] === seed[1])?.[1] ?? seed[1],
    ),
    life_form: l(
      seed[2],
      lifeFormCounts.find((item) => item[0] === seed[2])?.[1] ?? seed[2],
    ),
    site_type: l(
      seed[3],
      siteTypeCounts.find((item) => item[0] === seed[3])?.[1] ?? seed[3],
    ),
    plot_number: 1 + index * 5,
    height_m: Number((1.8 + index * 1.37).toFixed(2)),
    dbh_cm: Number((2.4 + index * 3.18).toFixed(2)),
    crown_width_m: Number((0.8 + index * 0.64).toFixed(2)),
    leaf_area_cm2: Number((5.1 + index * 1.73).toFixed(2)),
    specific_leaf_area: Number((72 + index * 8.6).toFixed(1)),
    soil_moisture: Number((6.5 + (index % 6) * 3.1).toFixed(1)),
    species_cn: l(seed[4], seed[5]),
  }));

  const previewFieldNames = [
    "region",
    "family",
    "life_form",
    "site_type",
    "plot_number",
    "height_m",
    "dbh_cm",
    "specific_leaf_area",
  ];
  const previewFields = fields
    .filter((field) => previewFieldNames.includes(field.name))
    .sort(
      (a, b) =>
        previewFieldNames.indexOf(a.name) - previewFieldNames.indexOf(b.name),
    )
    .map((field) => ({
      name: field.name,
      type: field.type,
      nullable: field.nullable,
      sampleValues: field.sampleValues,
      description: `${field.label}${field.unit ? ` (${field.unit})` : ""}`,
    }));
  const table: NonGeoTableQueryResult = {
    resourceId: resource.id,
    resourceName: resource.name,
    totalCount: 2_411,
    returnedCount: rows.length,
    limit: 80,
    offset: 0,
    fields: previewFields,
    rows,
  };

  const categoricalDistributions = categoryDefinitions.map((field) => ({
    field: field.name,
    label: l(field.zh, field.en),
    total: 2_411,
    items: field.values.map((item) => ({
      value: l(item[0], item[1]),
      count: item[2],
      ratio: item[2] / 2_411,
    })),
  }));
  const distributionMeasures = measureDefinitions.slice(0, 6);
  const numericDistributions = distributionMeasures.map((field, index) => {
    const span = field.max - field.min;
    const counts = [215, 388, 476, 562, 438, 332];
    return {
      field: field.name,
      label: l(field.zh, field.en),
      min: field.min,
      max: field.max,
      mean: field.mean,
      median: Number((field.min + span * (0.48 + index * 0.01)).toFixed(3)),
      q1: Number((field.min + span * 0.26).toFixed(3)),
      q3: Number((field.min + span * 0.72).toFixed(3)),
      bins: counts.map((count, binIndex) => {
        const binMin = field.min + (span / counts.length) * binIndex;
        const binMax = field.min + (span / counts.length) * (binIndex + 1);
        return {
          label: `${binMin.toFixed(1)}–${binMax.toFixed(1)}`,
          min: binMin,
          max: binMax,
          count,
          ratio: count / 2_411,
        };
      }),
    };
  });

  const analytics: NonGeoAnalytics = {
    resource,
    summary: {
      rowCount: 2_411,
      analyzedRowCount: 2_411,
      sampled: false,
      fieldCount: 31,
      numericFieldCount: 21,
      textFieldCount: 6,
      categoricalFieldCount: 4,
      completeness: 0.996,
      updatedAt: resource.updatedAt,
      suggestedView: "community",
    },
    fields,
    categoricalDistributions,
    numericDistributions,
    correlation: {
      fields: distributionMeasures
        .slice(1, 5)
        .map((field) => l(field.zh, field.en)),
      values: [
        [1, 0.82, 0.71, 0.28],
        [0.82, 1, 0.76, 0.34],
        [0.71, 0.76, 1, 0.46],
        [0.28, 0.34, 0.46, 1],
      ],
    },
    tablePreview: table,
    insights: [
      l(
        "当前展示平台内置演示数据，不替代真实调查记录。",
        "This view uses the built-in platform demo and does not replace real survey records.",
      ),
      l(
        "演示资源包含 2,411 条记录和 31 个字段。",
        "The demo resource contains 2,411 records and 31 fields.",
      ),
      l(
        "字段平均完整率约为 99.6%。",
        "Average field completeness is approximately 99.6%.",
      ),
      l(
        "提供 21 个数值指标，可用于分布、相关性和性状关系分析。",
        "Twenty-one numeric indicators support distribution, correlation, and trait-relationship analysis.",
      ),
    ],
  };
  return { resource, analytics, table };
}
