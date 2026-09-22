import type { GeoJSONSourceSpecification } from "mapbox-gl";
import type { LoadedVectorLayer } from "../types";

const largeLineOrPolygonFeatureCount = 2000;
const defaultClusterMaxZoom = 12;
const defaultClusterRadius = 50;

export function vectorGeojsonSourceOptions(
  layer: LoadedVectorLayer,
): GeoJSONSourceSpecification {
  const featureCount = layer.geojson.features.length;
  const pointOnly = featureCount > 0 && isPointOnlyGeometry(layer.geometryType);
  const cluster = shouldClusterVectorLayer(layer);
  const source: GeoJSONSourceSpecification = {
    type: "geojson",
    data: layer.geojson as never,
    generateId: true,
    maxzoom: pointOnly ? 12 : 16,
    ...(pointOnly ? { buffer: 0 } : {}),
    ...(!pointOnly && featureCount >= largeLineOrPolygonFeatureCount
      ? { tolerance: 0.75 }
      : {}),
    ...(cluster
      ? {
          cluster: true,
          clusterMaxZoom:
            layer.symbolization.cluster?.maxZoom ?? defaultClusterMaxZoom,
          clusterRadius:
            layer.symbolization.cluster?.radius ?? defaultClusterRadius,
        }
      : {}),
  };
  return source;
}

export function shouldClusterVectorLayer(layer: LoadedVectorLayer) {
  return (
    layer.geojson.features.length > 0 &&
    isPointOnlyGeometry(layer.geometryType) &&
    layer.symbolization.pointMode !== "heatmap" &&
    layer.symbolization.cluster?.enabled === true
  );
}

export function vectorSourceKey(layer: LoadedVectorLayer) {
  const options = vectorGeojsonSourceOptions(layer);
  return JSON.stringify({
    buffer: options.buffer,
    cluster: options.cluster,
    clusterMaxZoom: options.clusterMaxZoom,
    clusterRadius: options.clusterRadius,
    maxzoom: options.maxzoom,
    tolerance: options.tolerance,
  });
}

function isPointOnlyGeometry(geometryType: string) {
  const geometryTypes = geometryType
    .split(/[,/|+\s]+/)
    .map((type) => type.trim())
    .filter(Boolean);
  return (
    geometryTypes.length > 0 &&
    geometryTypes.every((type) => type === "Point" || type === "MultiPoint")
  );
}
