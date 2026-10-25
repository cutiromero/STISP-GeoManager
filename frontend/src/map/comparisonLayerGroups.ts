import type {
  QueryResponse,
  ResourceProfileResponse,
  GeoJsonFeatureCollection,
} from "../api/generated/types.gen";
import type { LoadedLayerGroup, LoadedVectorLayer } from "../types";
import {
  createEmptyLayerGroup,
  createVectorLayerGroup,
} from "../utils/layerFactory";
import { resourceLayerKey } from "../utils/uniqueLoadedLayers";
import { geologicalColor } from "./geologyReviewData";
import {
  comparisonFeatureKey,
  type ComparisonLayerPlacement,
} from "./geologyWorkbenchCompareData";

const roleNames = { before: "改前", after: "改后", changes: "修改范围" };
export const comparisonGroupId = (workflowId: string) =>
  `geology-comparison-${workflowId}`;

function comparisonStyle(
  layer: LoadedVectorLayer,
  placement: ComparisonLayerPlacement,
) {
  const symbolization = structuredClone(layer.symbolization);
  if (placement.roles.includes("changes")) {
    symbolization.renderer = { type: "single" };
    symbolization.fill.fillColor = "#e99032";
    symbolization.fill.fillOpacity = 0.22;
    symbolization.fill.fillOutlineColor = "#c86612";
    symbolization.line.lineColor = "#c86612";
    symbolization.line.lineWidth = 3;
    symbolization.circle.circleColor = "#e99032";
    symbolization.circle.circleStrokeColor = "#c86612";
    return symbolization;
  }
  const features = layer.geojson.features;
  const lithologyField =
    ["class", "geo_sym", "name"].find((key) =>
      features.some((feature) => feature.properties[key] !== undefined),
    ) ?? "class";
  const field =
    placement.element === "岩性" || placement.element === "地质图"
      ? lithologyField
      : placement.element === "调查建议"
        ? "grade"
        : "state";
  const values = [
    ...new Set(
      features.map((feature) => String(feature.properties[field] ?? "未记录")),
    ),
  ];
  const fallback =
    placement.element === "构造"
      ? "#76566d"
      : placement.element === "矿物"
        ? "#648e91"
        : "#537fc0";
  symbolization.renderer = {
    type: "uniqueValue",
    field,
    classes: values.map((value) => ({
      id: `comparison-${value}`,
      label: value,
      values: [value],
      color:
        field === lithologyField &&
        ["岩性", "地质图"].includes(placement.element)
          ? String(
              features.find(
                (feature) => String(feature.properties[field]) === value,
              )?.properties.fill_color ?? geologicalColor(value),
            )
          : value === "exclude"
            ? "#8d9baa"
            : value === "downweight"
              ? "#ad8b54"
              : value === "review"
                ? "#b483b2"
                : value === "A"
                  ? "#db9a35"
                  : fallback,
      iconImage: "",
      size: 5,
      count: features.filter(
        (feature) => String(feature.properties[field]) === value,
      ).length,
      visible: true,
    })),
    defaultClass: {
      id: "comparison-other",
      label: "其他",
      values: [],
      color: fallback,
      iconImage: "",
      size: 5,
      count: 0,
      visible: true,
    },
  };
  symbolization.fill.fillOpacity =
    placement.element === "岩性" || placement.element === "地质图" ? 0.95 : 0.2;
  return symbolization;
}

/** Rehome an existing resource atomically instead of creating a duplicate layer. */
export function upsertComparisonLayer(
  groups: LoadedLayerGroup[],
  profile: ResourceProfileResponse,
  result: QueryResponse,
  placement: ComparisonLayerPlacement,
): LoadedLayerGroup[] {
  const key = `resource:${profile.resource.id}`,
    groupId = comparisonGroupId(placement.workflowId);
  const existing = groups
    .flatMap((group) => group.children)
    .find(
      (layer) =>
        layer.layerType === "vector" && resourceLayerKey(layer) === key,
    );
  const base = createVectorLayerGroup(profile.resource, profile, result, {
    attributeFilters: [],
    spatialFilter: null,
  }).children[0] as LoadedVectorLayer;
  const previous = existing?.layerType === "vector" ? existing : undefined;
  const displayData = placement.displayData ?? result.geojson;
  const metadata = {
    ...base.metadata,
    ...previous?.metadata,
    对比任务: placement.workflowId,
    对比角色: placement.roles.map((role) => roleNames[role]).join(" / "),
    对比要素: placement.element,
    comparisonRoles: placement.roles.join(","),
    comparisonElement: placement.element,
  };
  const layer: LoadedVectorLayer = {
    ...base,
    ...previous,
    name: profile.resource.name,
    id: previous?.id ?? `${groupId}-resource-${profile.resource.id}`,
    geojson: displayData,
    fields: result.fields,
    metadata,
    visible:
      previous?.metadata.对比任务 === placement.workflowId
        ? previous.visible
        : placement.roles.includes("after") ||
          placement.roles.includes("changes") ||
          !groups.some(
            (group) =>
              group.id === groupId &&
              group.children.some((child) =>
                String(child.metadata.comparisonRoles).includes("after"),
              ),
          ),
    symbolization:
      previous?.metadata.对比任务 === placement.workflowId
        ? previous.symbolization
        : comparisonStyle(base, placement),
  };
  const target = groups.find((group) => group.id === groupId) ?? {
    ...createEmptyLayerGroup(`${placement.title} 对比`),
    id: groupId,
    metadata: { 对比任务: placement.workflowId },
  };
  const cleaned = groups.map((group) => ({
    ...group,
    children: group.children.filter((child) => resourceLayerKey(child) !== key),
  }));
  const children = [
    ...(cleaned.find((group) => group.id === groupId)?.children ??
      target.children),
    layer,
  ];
  const hasAfter = children.some((child) =>
    String(child.metadata.comparisonRoles).split(",").includes("after"),
  );
  const defaultChildren = hasAfter
    ? children.map((child) => ({
        ...child,
        visible: String(child.metadata.comparisonRoles)
          .split(",")
          .some((role) => ["after", "changes"].includes(role)),
      }))
    : children;
  const resultGroup = {
    ...target,
    // The first tree layer renders on top: keep changes and evidence above the rock polygons.
    children: [...defaultChildren].sort((a, b) => {
      const rank = (item: typeof a) => {
        const roles = String(item.metadata.comparisonRoles).split(",");
        if (roles.includes("changes")) return 0;
        const element = String(item.metadata.comparisonElement);
        const overlayRank =
          element === "构造交汇"
            ? 1
            : element === "构造"
              ? 2
              : element === "调查建议"
                ? 3
                : element === "矿物"
                  ? 4
                  : 9;
        return (roles.includes("after") ? 10 : 20) + overlayRank;
      };
      return rank(a) - rank(b);
    }),
    visible: true,
    summary: `${children.length}个任务图层 / 改前、改后与修改范围`,
  };
  return [
    resultGroup,
    ...cleaned.filter(
      (group) =>
        group.id !== groupId &&
        (group.children.length || (group.isManual && !group.metadata.对比任务)),
    ),
  ];
}

export function displayComparisonLayers(
  groups: LoadedLayerGroup[],
  workflowId: string,
  side: "before" | "after",
  changes: GeoJsonFeatureCollection,
  sourceData: ReadonlyMap<number, GeoJsonFeatureCollection>,
) {
  const keys = new Set(
    changes.features.map(comparisonFeatureKey).filter((key) => key !== null),
  );
  return groups.map((group) =>
    group.id !== comparisonGroupId(workflowId)
      ? group
      : {
          ...group,
          visible: true,
          children: group.children.map((layer) => {
            const roles = String(layer.metadata.comparisonRoles ?? "").split(
              ",",
            );
            const highlight = roles.includes("changes");
            const original = sourceData.get(layer.sourceResource.id);
            const hasAfter = group.children.some((child) =>
              String(child.metadata.comparisonRoles)
                .split(",")
                .includes("after"),
            );
            return {
              ...layer,
              visible:
                highlight ||
                roles.includes(side) ||
                (side === "after" && !hasAfter && roles.includes("before")),
              ...(layer.layerType === "vector" && highlight && original
                ? {
                    geojson: {
                      type: "FeatureCollection" as const,
                      features: original.features.filter((feature) => {
                        const key = comparisonFeatureKey(feature);
                        return key !== null && keys.has(key);
                      }),
                    },
                  }
                : {}),
            };
          }),
        },
  );
}
