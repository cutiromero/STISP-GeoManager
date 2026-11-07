import type {
  DataResourceProfile,
  LoadedVectorLayer,
  ResourceListItem,
  ResourceQueryResult,
} from "../types";
import { projectUrl } from "../projects/session";

export function tilePreviewResult(
  resource: ResourceListItem,
  profile: DataResourceProfile,
): ResourceQueryResult {
  return {
    resourceId: resource.id,
    resourceName: resource.name,
    totalCount: profile.vectorTiles?.featureCount ?? profile.featureCount ?? 0,
    returnedCount: 0,
    limit: 10000,
    limitExceeded: false,
    fields: profile.fields,
    bounds: profile.bounds,
    elapsedMs: 0,
    warnings: [],
    geojson: { type: "FeatureCollection", features: [] },
  };
}

export function attachVectorTilePreview(
  layer: LoadedVectorLayer,
  preview: NonNullable<DataResourceProfile["vectorTiles"]>,
): LoadedVectorLayer {
  return {
    ...layer,
    vectorTiles: preview,
    viewportOnly: true,
    geojson: { type: "FeatureCollection", features: [] },
    summary: `${preview.featureCount} 条，按视野分块显示${preview.clustered ? "，远景聚合" : ""}`,
    symbolization: {
      ...layer.symbolization,
      cluster: { ...layer.symbolization.cluster, enabled: preview.clustered },
    },
    metadata: {
      ...layer.metadata,
      加载方式: "分级矢量瓦片",
      显示要素总数: preview.featureCount,
    },
  };
}

export function vectorTileSourceOptions(layer: LoadedVectorLayer) {
  const preview = layer.vectorTiles!;
  const aggregate =
    preview.clustered &&
    layer.symbolization.cluster.enabled &&
    layer.symbolization.pointMode !== "heatmap";
  return {
    type: "vector" as const,
    tiles: [
      projectUrl((!aggregate && preview.rawTileUrl) || preview.tileUrl)
        .replace(/%7B/g, "{")
        .replace(/%7D/g, "}"),
    ],
    minzoom: preview.minZoom,
    maxzoom: preview.maxZoom,
    bounds: preview.bounds as [number, number, number, number],
  };
}
