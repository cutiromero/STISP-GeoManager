import type {
  AgentWorkflow,
  GeoJsonFeatureCollection,
  QueryResponse,
} from "../api/generated/types.gen";

const exterior = [
  [98.4, 35.6],
  [98.43, 35.6],
  [98.43, 35.62],
  [98.4, 35.62],
  [98.4, 35.6],
];
const gap = [
  [98.415, 35.607],
  [98.415, 35.61],
  [98.418, 35.61],
  [98.418, 35.607],
  [98.415, 35.607],
];
const second = [
  [98.43, 35.6],
  [98.45, 35.6],
  [98.45, 35.62],
  [98.43, 35.62],
  [98.43, 35.6],
];
export const beforeReviewMap: GeoJsonFeatureCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      id: "unit-a",
      geometry: { type: "Polygon", coordinates: [exterior, gap] },
      properties: {
        feature_id: "unit-a",
        class: 5,
        name: "八宝山组",
        code: "T3b",
        path: "沉积岩/八宝山组",
        geologic_age: "早白垩世",
      },
    },
    {
      type: "Feature",
      id: "unit-b",
      geometry: { type: "Polygon", coordinates: [second] },
      properties: {
        feature_id: "unit-b",
        class: 9,
        name: "第四系",
        code: "Q",
        path: "沉积层/第四系",
        geologic_age: "第四纪",
      },
    },
  ],
};
export const afterReviewMap: GeoJsonFeatureCollection = {
  type: "FeatureCollection",
  features: [
    {
      ...beforeReviewMap.features[0]!,
      geometry: { type: "Polygon", coordinates: [exterior] },
      properties: {
        ...beforeReviewMap.features[0]!.properties,
        geologic_age: "晚三叠世",
      },
    },
    beforeReviewMap.features[1]!,
  ],
};
export const reviewDifferences: GeoJsonFeatureCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      id: "issue-gap",
      geometry: { type: "Polygon", coordinates: [gap] },
      properties: {
        feature_id: "unit-a",
        issue_id: "issue-gap",
        kind: "fill_gap",
        class: 5,
        name: "八宝山组",
        current_label: "未分类空白",
        suggested_label: "八宝山组（T3b）",
        old_value: "unclassified",
        new_value: "5",
        verified_reason:
          "制图范围完整，空白由同一地质单元包围，且已核对例外条件。",
        area_m2: 30000,
        change_status: "applied",
      },
    },
    {
      type: "Feature",
      id: "issue-age",
      geometry: { type: "Polygon", coordinates: [exterior, gap] },
      properties: {
        feature_id: "unit-a",
        issue_id: "issue-age",
        kind: "set_age",
        class: 5,
        name: "八宝山组",
        current_label: "早白垩世",
        suggested_label: "晚三叠世",
        old_value: "Early Cretaceous",
        new_value: "Late Triassic",
        verified_reason:
          "地层名称和地区符合专家知识的适用范围，仅更新时代属性。",
        area_m2: 600000,
        change_status: "applied",
      },
    },
  ],
};

export function reviewWorkflow(actual = false): AgentWorkflow {
  return {
    id: "review-workflow",
    projectId: 3,
    workflowType: "geology_map_review",
    goal: "检查待检查地质图",
    model: "qwen",
    status: actual ? "waiting_compute" : "waiting_approval",
    detail: actual ? "正在复核修正后地图" : "请批准要修正的建议",
    currentStep: actual ? "recheck" : "review_modifications",
    iteration: 3,
    operatorSteps: actual ? 2 : 1,
    maxIterations: 8,
    maxOperatorSteps: 12,
    executeOperators: true,
    resourceIds: [101, 102, 103],
    algorithmVersionId: null,
    parameters: {},
    resultIds: [],
    evidence: [],
    runtime: "worker",
    steps: [],
    createdAt: "",
    updatedAt: "",
    importResults: true,
    resultResourceIds: actual ? [201, 202] : [],
    planHash: "current-plan",
    plan: {
      phase: actual ? "waiting_compute" : "review_modifications",
      inputs: { initial_map: 101, coverage: 102, rules: 103 },
      stages: [
        {
          name: "edit",
          identifier: "geology-map-correct",
          ...(actual
            ? {
                taskId: "real-compute-task",
                outputs: [
                  { key: "corrected", resourceId: 201 },
                  { key: "changes_map", resourceId: 202 },
                ],
              }
            : {}),
        },
      ],
    },
    modificationReview: {
      proposalHash: "current-proposal",
      approvedSuggestionIds: actual ? ["suggest-gap", "suggest-age"] : [],
      suggestions: reviewDifferences.features.map((feature, index) => ({
        id: index ? "suggest-age" : "suggest-gap",
        kind: index ? "set_age" : "fill_gap",
        featureId: "unit-a",
        title: index ? "更新地层时代" : "填补内部漏填",
        currentState: String(feature.properties.current_label),
        suggestedState: String(feature.properties.suggested_label),
        reason: String(feature.properties.verified_reason),
        areaM2: Number(feature.properties.area_m2),
        ruleId: index ? "age-rule" : "coverage-rule",
        knowledgeRefs: [],
        preview: feature.geometry,
        bounds: index
          ? [98.4, 35.6, 98.43, 35.62]
          : [98.415, 35.607, 98.418, 35.61],
      })),
    },
  };
}

export function reviewQuery(
  id: number,
  geojson: GeoJsonFeatureCollection,
): QueryResponse {
  return {
    resourceId: id,
    resourceName:
      id === 101 ? "待检查地质图" : id === 201 ? "修正后地质图" : "修改范围",
    totalCount: geojson.features.length,
    returnedCount: geojson.features.length,
    limit: 10000,
    limitExceeded: false,
    bounds: [98.4, 35.6, 98.45, 35.62],
    elapsedMs: 2,
    fields: [],
    geojson,
    warnings: [],
  };
}
