import { requestJson } from "../api/client";
import { getActiveProject, projectSignal } from "../projects/session";
import type {
  AgentWorkflow,
  GeoJsonFeatureCollection,
  QueryResponse,
  ResourceProfileResponse,
} from "../api/generated/types.gen";

export const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

export function reviewResourceIds(workflow: AgentWorkflow) {
  const stages = Array.isArray(workflow.plan.stages)
    ? workflow.plan.stages
    : [];
  const edit = stages
    .map(record)
    .find((stage) => stage.identifier === "geology-map-correct");
  const outputs = Array.isArray(edit?.outputs) ? edit.outputs.map(record) : [];
  const validId = (value: unknown) =>
    typeof value === "number" && Number.isInteger(value) && value > 0
      ? value
      : null;
  return {
    before: validId(record(workflow.plan.inputs).initial_map),
    after: validId(
      outputs.find((output) => output.key === "corrected")?.resourceId,
    ),
    differences: validId(
      outputs.find((output) => output.key === "changes_map")?.resourceId,
    ),
  };
}

let activeReads = 0;
let fullReadQueue: Promise<unknown> = Promise.resolve();
const pendingReads: Array<() => void> = [];
async function readDisplayQuery(
  id: number,
  projectId: string | null,
  signal: AbortSignal,
) {
  if (activeReads >= 2)
    await new Promise<void>((resolve) => pendingReads.push(resolve));
  else activeReads++;
  try {
    if (signal.aborted || getActiveProject() !== projectId)
      throw new DOMException(
        "项目已切换，已停止读取旧项目图层。",
        "AbortError",
      );
    return await requestJson<QueryResponse>(
      `/api/catalog/resources/${id}/query/`,
      {
        method: "POST",
        body: {
          attributeFilters: [],
          spatialFilter: null,
          limit: 10000,
          displayGeometry: true,
        },
      },
    );
  } finally {
    const next = pendingReads.shift();
    if (next) next();
    else activeReads--;
  }
}

export async function queryReviewMap(
  id: number,
  options: {
    mixed?: boolean;
    allowEmpty?: boolean;
    loadStyle?: boolean;
    displayGeometry?: boolean;
  } = {},
) {
  return (await queryReviewMapResult(id, options)).geojson;
}

export async function queryReviewMapResult(
  id: number,
  options: {
    mixed?: boolean;
    allowEmpty?: boolean;
    loadStyle?: boolean;
    displayGeometry?: boolean;
  } = {},
) {
  const projectId = getActiveProject();
  const signal = projectSignal();
  if (signal.aborted || getActiveProject() !== projectId)
    throw new DOMException("项目已切换，已停止读取旧项目图层。", "AbortError");
  const response = options.displayGeometry
    ? readDisplayQuery(id, projectId, signal)
    : fullReadQueue.then(() => {
        if (signal.aborted || getActiveProject() !== projectId)
          throw new DOMException(
            "项目已切换，已停止读取旧项目图层。",
            "AbortError",
          );
        return requestJson<QueryResponse>(
          `/api/catalog/resources/${id}/query/`,
          {
            method: "POST",
            body: { attributeFilters: [], spatialFilter: null, limit: 10000 },
          },
        );
      });
  if (!options.displayGeometry) fullReadQueue = response.catch(() => undefined);
  const result = await response;
  if (result.limitExceeded)
    throw new Error("图件超过双图预览范围，请缩小检查范围后查看");
  if (
    result.resourceId !== id ||
    result.returnedCount !== result.geojson.features.length ||
    result.totalCount > result.returnedCount
  )
    throw new Error("图件返回不完整，请核对资源后重新查看");
  if (!result.geojson.features.length && !options.allowEmpty)
    throw new Error("图件尚无可显示的面数据");
  if (
    !options.mixed &&
    result.geojson.features.some(
      (feature) => !["Polygon", "MultiPolygon"].includes(feature.geometry.type),
    )
  )
    throw new Error("双图预览需要完整的面图件");
  if (
    options.loadStyle === true &&
    result.geojson.features.some(
      (feature) =>
        ["Polygon", "MultiPolygon"].includes(feature.geometry.type) &&
        typeof feature.properties.name === "string",
    )
  ) {
    const profile = await requestJson<ResourceProfileResponse>(
      `/api/catalog/resources/${id}/profile/`,
    );
    colorReviewMap(result.geojson, profile.defaultVisualization ?? {});
  }
  return result;
}

export function colorReviewMap(
  data: GeoJsonFeatureCollection,
  visualization: Record<string, unknown>,
) {
  const renderer = record(record(visualization.symbolization).renderer);
  if (renderer.type !== "uniqueValue" || renderer.field !== "name") return;
  const classes = (Array.isArray(renderer.classes) ? renderer.classes : []).map(
    record,
  );
  const colors = new Map(
    classes.map((item) => [String(item.value), String(item.color)]),
  );
  const fallback = record(renderer.defaultClass).color;
  data.features = data.features.map((feature) => ({
    ...feature,
    properties: {
      ...feature.properties,
      fill_color: colors.get(String(feature.properties.name)) ?? fallback,
      unit_color_by_name: true,
    },
  }));
}

export function previewSuggestions(
  workflow: AgentWorkflow,
): GeoJsonFeatureCollection {
  const approved = workflow.modificationReview?.approvedSuggestionIds ?? [];
  return {
    type: "FeatureCollection",
    features: (workflow.modificationReview?.suggestions ?? [])
      .filter((item) => !approved.length || approved.includes(item.id))
      .map((item) => ({
        type: "Feature",
        id: item.id,
        geometry: item.preview,
        properties: {
          suggestion_id: item.id,
          feature_id: item.featureId,
          kind: item.kind,
          current_label: item.currentState,
          suggested_label: item.suggestedState,
          reason: item.reason,
          area_m2: item.areaM2,
          status: workflow.modificationReview?.approvedSuggestionIds.includes(
            item.id,
          )
            ? "已批准"
            : "建议修改",
        },
      })),
  };
}

export function reviewSuggestionIndex(
  workflow: AgentWorkflow,
  differences: GeoJsonFeatureCollection,
  suggestionId: string | null,
) {
  if (!suggestionId) return -1;
  const suggestion = workflow.modificationReview?.suggestions.find(
    (item) => item.id === suggestionId,
  );
  return differences.features.findIndex(
    ({ properties }) =>
      properties.suggestion_id === suggestionId ||
      (suggestion &&
        String(properties.feature_id) === suggestion.featureId &&
        properties.kind === suggestion.kind),
  );
}

export function reviewBounds(collection: GeoJsonFeatureCollection) {
  let west = Infinity,
    south = Infinity,
    east = -Infinity,
    north = -Infinity;
  const scan = (value: unknown) => {
    if (!Array.isArray(value)) return;
    if (
      typeof value[0] === "number" &&
      typeof value[1] === "number" &&
      Number.isFinite(value[0]) &&
      Number.isFinite(value[1])
    ) {
      west = Math.min(west, value[0]);
      east = Math.max(east, value[0]);
      south = Math.min(south, value[1]);
      north = Math.max(north, value[1]);
    } else value.forEach(scan);
  };
  collection.features.forEach((feature) =>
    scan(record(feature.geometry).coordinates),
  );
  return Number.isFinite(west) &&
    west >= -180 &&
    east <= 180 &&
    south >= -90 &&
    north <= 90
    ? ([west, south, east, north] as [number, number, number, number])
    : null;
}

const palette = [
  "#98bfe6",
  "#d0b5d4",
  "#eac58b",
  "#c7d5ac",
  "#b7d8e1",
  "#cbbfb1",
  "#aeb7dc",
  "#e2b3b7",
  "#c1d6e4",
  "#e5d4a3",
  "#b6ccc3",
  "#bbbbe0",
  "#eac4a6",
  "#cfb8cc",
  "#b4d3d1",
  "#d6cdaf",
];
export function geologicalColor(value: unknown) {
  const key = Number(value);
  return Number.isInteger(key) && key >= 0
    ? (palette[key % palette.length] ?? "#d4dce5")
    : "#d4dce5";
}

export function reviewLegend(...data: GeoJsonFeatureCollection[]) {
  const values = new Map<
    string,
    { key: string; name: string; color: string }
  >();
  data
    .flatMap((collection) => collection.features)
    .forEach(({ properties: p }) => {
      const key = String(
        p.unit_color_by_name
          ? p.name
          : (p.class ?? p.geo_sym ?? p.code ?? p.name),
      );
      values.set(key, {
        key,
        name: p.unit_color_by_name
          ? String(p.name)
          : `${String(p.name ?? "地质单元")} / ${String(p.geo_sym ?? p.code ?? key)}`,
        color:
          typeof p.fill_color === "string" &&
          /^#[\da-f]{6}$/i.test(p.fill_color)
            ? p.fill_color
            : geologicalColor(p.class),
      });
    });
  return [...values.values()].sort((a, b) =>
    Number.isFinite(Number(a.key)) && Number.isFinite(Number(b.key))
      ? Number(a.key) - Number(b.key)
      : a.name.localeCompare(b.name, "zh-CN"),
  );
}
