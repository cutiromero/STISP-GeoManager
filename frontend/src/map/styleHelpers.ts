import type {
  AnyLayer,
  ExpressionSpecification,
  Map as MapboxMap,
} from "mapbox-gl";
import type { VectorSymbolization } from "../symbolization";
import { clamp } from "../utils/geometry";
import { removeVectorInteraction } from "./featureInteraction";

export function stateColor(baseColor: string | ExpressionSpecification) {
  return [
    "case",
    ["boolean", ["feature-state", "selected"], false],
    "#e4582b",
    ["boolean", ["feature-state", "highlight"], false],
    "#f2c36d",
    normalizeMapboxColorValue(baseColor),
  ] as unknown as ExpressionSpecification;
}

export function stateNumber(
  base: number | ExpressionSpecification,
  selected: number | ExpressionSpecification,
  highlight: number | ExpressionSpecification,
) {
  return [
    "case",
    ["boolean", ["feature-state", "selected"], false],
    selected,
    ["boolean", ["feature-state", "highlight"], false],
    highlight,
    base,
  ] as unknown as ExpressionSpecification;
}

export function hasMapStyle(map: MapboxMap) {
  return Boolean((map as unknown as { style?: unknown }).style);
}

export function upsertLayer(map: MapboxMap, layer: AnyLayer) {
  if (!hasMapStyle(map)) return;
  if (
    "source" in layer &&
    typeof layer.source === "string" &&
    layer.source.startsWith("loaded-") &&
    !("source-layer" in layer) &&
    map.getSource?.(layer.source)?.type === "vector"
  ) {
    layer = { ...layer, "source-layer": "features" } as AnyLayer;
  }
  const normalizedLayer = normalizeLayerPaintColors(layer);
  const existing = map.getLayer(normalizedLayer.id);
  if (existing && existing.type !== normalizedLayer.type) {
    removeStyleLayer(map, normalizedLayer.id);
  }
  if (!map.getLayer(normalizedLayer.id)) {
    map.addLayer(normalizedLayer);
    return;
  }
  if (
    "filter" in normalizedLayer &&
    !styleValuesEqual(
      map.getFilter?.(normalizedLayer.id),
      normalizedLayer.filter,
    )
  ) {
    map.setFilter(normalizedLayer.id, normalizedLayer.filter);
  }
  const writableMap = map as unknown as {
    getLayoutProperty?: (layerId: string, property: string) => unknown;
    getPaintProperty?: (layerId: string, property: string) => unknown;
    setLayoutProperty: (
      layerId: string,
      property: string,
      value: unknown,
    ) => void;
    setPaintProperty: (
      layerId: string,
      property: string,
      value: unknown,
    ) => void;
  };
  for (const [property, value] of Object.entries(
    normalizedLayer.layout ?? {},
  )) {
    if (
      !styleValuesEqual(
        writableMap.getLayoutProperty?.(normalizedLayer.id, property),
        value,
      )
    ) {
      writableMap.setLayoutProperty(normalizedLayer.id, property, value);
    }
  }
  for (const [property, value] of Object.entries(normalizedLayer.paint ?? {})) {
    if (
      !styleValuesEqual(
        writableMap.getPaintProperty?.(normalizedLayer.id, property),
        value,
      )
    ) {
      writableMap.setPaintProperty(normalizedLayer.id, property, value);
    }
  }
}

function styleValuesEqual(current: unknown, next: unknown): boolean {
  if (current === next) return true;
  return (
    typeof current === "object" &&
    typeof next === "object" &&
    JSON.stringify(current) === JSON.stringify(next)
  );
}

export function normalizeMapboxColorValue<T>(value: T): T {
  if (typeof value === "string") {
    return normalizeHexAlphaColor(value) as T;
  }
  if (Array.isArray(value)) {
    return value.map((item) => normalizeMapboxColorValue(item)) as T;
  }
  return value;
}

function normalizeLayerPaintColors(layer: AnyLayer): AnyLayer {
  if (!("paint" in layer) || !layer.paint) return layer;
  return {
    ...layer,
    paint: Object.fromEntries(
      Object.entries(layer.paint).map(([property, value]) => [
        property,
        property.endsWith("-color") ? normalizeMapboxColorValue(value) : value,
      ]),
    ),
  } as AnyLayer;
}

function normalizeHexAlphaColor(value: string): string {
  const long = value.match(/^#([0-9a-f]{6})([0-9a-f]{2})$/i);
  const short = value.match(/^#([0-9a-f]{3})([0-9a-f])$/i);
  if (!long && !short) return value;
  const rgb = long
    ? long[1]!
    : short![1]!
        .split("")
        .map((part) => `${part}${part}`)
        .join("");
  const alphaHex = long ? long[2]! : `${short![2]!}${short![2]!}`;
  const red = Number.parseInt(rgb.slice(0, 2), 16);
  const green = Number.parseInt(rgb.slice(2, 4), 16);
  const blue = Number.parseInt(rgb.slice(4, 6), 16);
  const alpha = Number((Number.parseInt(alphaHex, 16) / 255).toFixed(4));
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

export function removeStyleLayer(map: MapboxMap, layerId: string) {
  removeVectorInteraction(map, layerId);
  if (!hasMapStyle(map)) return;
  if (map.getLayer(layerId)) {
    map.removeLayer(layerId);
  }
}

export function buildVectorPaintProperties(
  style: VectorSymbolization,
  layerOpacity: number,
) {
  const circleOpacity = clamp(style.circle.circleOpacity * layerOpacity, 0, 1);
  const circleStrokeOpacity = clamp(
    style.circle.circleStrokeOpacity * layerOpacity,
    0,
    1,
  );
  const symbolIconOpacity = clamp(
    style.symbol.iconOpacity * layerOpacity,
    0,
    1,
  );
  const symbolTextOpacity = clamp(
    style.symbol.textOpacity * layerOpacity,
    0,
    1,
  );
  const lineOpacity = clamp(style.line.lineOpacity * layerOpacity, 0, 1);
  const fillOpacity = clamp(style.fill.fillOpacity * layerOpacity, 0, 1);

  return {
    circleOpacity,
    circleStrokeOpacity,
    symbolIconOpacity,
    symbolTextOpacity,
    lineOpacity,
    fillOpacity,
  };
}
