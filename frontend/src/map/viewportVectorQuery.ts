import type {
  LoadedLayer,
  LoadedVectorLayer,
  ResourceListItem,
  ResourceQueryPayload,
  ResourceQueryResult,
  SpatialFilter,
} from "../types";
import { rectangleGeometry } from "../utils/geometry";

export function isLargeVectorResource(resource: ResourceListItem) {
  return (
    resource.dataType === "vector" &&
    (resource.itemCount >= 1500 || resource.sizeBytes >= 2 * 1024 * 1024)
  );
}

export function isViewportVectorLayer(layer: LoadedLayer): boolean {
  return (
    layer.layerType === "vector" &&
    !layer.query?.spatialFilter &&
    !layer.query?.attributeFilters.length &&
    (layer.viewportOnly === true || isLargeVectorResource(layer.sourceResource))
  );
}

export function viewportQueryPayload(
  bounds: [number, number, number, number],
  queryLimit: number,
  geometryType = "",
): ResourceQueryPayload {
  let [west, south, east, north] = bounds;
  if (!bounds.every(Number.isFinite)) throw new Error("地图视野无效");
  south = Math.max(-90, south);
  north = Math.min(90, north);
  if (south >= north) throw new Error("地图视野无效");
  if (east < west) east += 360;
  const width = east - west;
  if (width <= 0) throw new Error("地图视野无效");
  let geometry: SpatialFilter["geometry"];
  if (width >= 360) geometry = rectangleGeometry([-180, south], [180, north]);
  else {
    west = ((((west + 180) % 360) + 360) % 360) - 180;
    east = west + width;
    geometry =
      east <= 180
        ? rectangleGeometry([west, south], [east, north])
        : {
            type: "MultiPolygon",
            coordinates: [
              rectangleGeometry([west, south], [180, north]).coordinates,
              rectangleGeometry([-180, south], [east - 360, north]).coordinates,
            ],
          };
  }
  // Keep the map's display budget separate from explicit spatial/attribute queries.
  const point = geometryType.toLowerCase().includes("point");
  const line = geometryType.toLowerCase().includes("line");
  // Use stable scale levels (about half a pixel at 1024px), restoring detail
  // as the view narrows. Explicit queries never use this display-only path.
  const tolerance = Math.min(
    0.05,
    2 ** Math.floor(Math.log2(Math.min(width, north - south) / 2048)),
  );
  return {
    attributeFilters: [],
    spatialFilter: { mode: "rectangle", geometry },
    limit: Math.max(1, Math.min(queryLimit, point ? 1500 : line ? 10000 : 600)),
    displayGeometry: true,
    ...(line && tolerance >= 0.00001
      ? { lineSimplifyTolerance: tolerance }
      : {}),
  };
}

export function applyViewportResult(
  layer: LoadedVectorLayer,
  result: ResourceQueryResult,
  key = "",
): LoadedVectorLayer {
  const summary = `当前视野 ${result.returnedCount}/${result.totalCount} 条${result.limitExceeded ? "，已达显示上限，请放大" : ""}`;
  return {
    ...layer,
    viewportOnly: true,
    geojson: result.geojson,
    fields: result.fields,
    summary,
    metadata: {
      ...layer.metadata,
      展示范围: "当前地图视野",
      返回条数: result.returnedCount,
      命中条数: result.totalCount,
      显示上限: result.limit,
      视野查询键: key,
      视野刷新时间: Date.now(),
    },
  };
}

export function exactViewportExportQuery(
  layer: LoadedVectorLayer,
): ResourceQueryPayload | null {
  if (!isViewportVectorLayer(layer) || !layer.metadata.视野查询键) return null;
  const [, , body] = JSON.parse(String(layer.metadata.视野查询键)) as [
    number,
    string,
    ResourceQueryPayload,
  ];
  if (!body.lineSimplifyTolerance && !layer.vectorTiles) return null;
  return {
    attributeFilters: body.attributeFilters,
    spatialFilter: body.spatialFilter,
    limit: body.limit,
    ...(layer.vectorTiles ? { sourceFeatureIds: true } : {}),
  };
}
