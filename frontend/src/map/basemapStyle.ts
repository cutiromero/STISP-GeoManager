import type {
  ExpressionSpecification,
  FilterSpecification,
  Map as MapboxMap,
  StyleSpecification,
} from "mapbox-gl";
import type { Bootstrap } from "../types";
import { currentLocale } from "../i18n";

export type MapBasemapConfig = Bootstrap["map"];

export const mapboxSatelliteStyle =
  "mapbox://styles/mapbox/satellite-streets-v12";
export const osmChineseVectorStyle =
  "https://tiles.openfreemap.org/styles/liberty";
export function mapLabelLanguage() {
  return currentLocale() === "en-US" ? "en" : "zh-Hans";
}
export const osmRasterTileMaxZoom = 19;

type SatelliteBasemapColorCorrection = {
  "raster-saturation": number;
  "raster-contrast": number;
  "raster-brightness-min": number;
  "raster-brightness-max": number;
};

export const satelliteBasemapColorCorrection: SatelliteBasemapColorCorrection =
  {
    "raster-saturation": -0.55,
    "raster-contrast": -0.1,
    "raster-brightness-min": 0.04,
    "raster-brightness-max": 0.9,
  };
export const satelliteBasemapThumbnailFilter = [
  `saturate(${paintRatioToCssPercent(satelliteBasemapColorCorrection["raster-saturation"])})`,
  `contrast(${paintRatioToCssPercent(satelliteBasemapColorCorrection["raster-contrast"])})`,
  `brightness(${Math.round(satelliteBasemapColorCorrection["raster-brightness-max"] * 100)}%)`,
].join(" ");

export const chineseLabelExpression: ExpressionSpecification = [
  "coalesce",
  ["get", "name:zh-Hans"],
  ["get", "name:zh"],
  ["get", "name_zh-Hans"],
  ["get", "name_zh"],
  ["get", "name:nonlatin"],
  ["get", "name"],
];

export const englishLabelExpression: ExpressionSpecification = [
  "coalesce",
  ["get", "name:en"],
  ["get", "name_en"],
  ["get", "name"],
];

type StyleLayerWithExpressions = {
  id: string;
  filter?: unknown;
  layout?: Record<string, unknown>;
  paint?: Record<string, unknown>;
};

export function applyChineseBasemapLanguage(map: MapboxMap) {
  const language = mapLabelLanguage();
  map.setLanguage(language);
  const labelExpression =
    language === "en" ? englishLabelExpression : chineseLabelExpression;

  const style = map.getStyle();
  for (const layer of style.layers ?? []) {
    if (
      layer.type !== "symbol" ||
      !layer.layout ||
      !("text-field" in layer.layout) ||
      !map.getLayer(layer.id)
    ) {
      continue;
    }

    const textField = JSON.stringify(layer.layout["text-field"]);
    if (!textField.includes("name")) continue;
    map.setLayoutProperty(layer.id, "text-field", labelExpression);
  }
}

export function applyBasemapExpressionSafety(map: MapboxMap) {
  const style = map.getStyle();
  for (const layer of style.layers ?? []) {
    const expressionLayer = layer as StyleLayerWithExpressions;
    if (!map.getLayer(layer.id)) continue;

    if (expressionLayer.filter) {
      const filter = withSafeNumericAssertions(expressionLayer.filter);
      if (filter !== expressionLayer.filter) {
        map.setFilter(layer.id, filter as FilterSpecification);
      }
    }

    for (const [property, value] of Object.entries(
      expressionLayer.layout ?? {},
    )) {
      const safeValue = withSafeNumericAssertions(value);
      if (safeValue !== value) {
        map.setLayoutProperty(layer.id, property as never, safeValue as never);
      }
    }

    for (const [property, value] of Object.entries(
      expressionLayer.paint ?? {},
    )) {
      const safeValue = withSafeNumericAssertions(value);
      if (safeValue !== value) {
        map.setPaintProperty(layer.id, property as never, safeValue as never);
      }
    }
  }
}

export function applySatelliteBasemapColorCorrection(map: MapboxMap) {
  const style = map.getStyle();
  for (const layer of style.layers ?? []) {
    if (layer.type !== "raster" || !map.getLayer(layer.id)) {
      continue;
    }

    const properties = Object.keys(satelliteBasemapColorCorrection) as Array<
      keyof SatelliteBasemapColorCorrection
    >;
    for (const property of properties) {
      map.setPaintProperty(
        layer.id,
        property,
        satelliteBasemapColorCorrection[property],
      );
    }
  }
}

export function sanitizeStyleNumericAssertions(
  style: StyleSpecification,
): StyleSpecification {
  const next = JSON.parse(JSON.stringify(style)) as StyleSpecification;
  for (const layer of next.layers ?? []) {
    const expressionLayer = layer as StyleLayerWithExpressions;
    if (expressionLayer.filter) {
      expressionLayer.filter = withSafeNumericAssertions(
        expressionLayer.filter,
      ) as FilterSpecification;
    }
    for (const [property, value] of Object.entries(
      expressionLayer.layout ?? {},
    )) {
      expressionLayer.layout![property] = withSafeNumericAssertions(value);
    }
    for (const [property, value] of Object.entries(
      expressionLayer.paint ?? {},
    )) {
      expressionLayer.paint![property] = withSafeNumericAssertions(value);
    }
  }
  return next;
}

function withSafeNumericAssertions(value: unknown): unknown {
  if (!Array.isArray(value)) {
    return value;
  }

  let changed = false;
  const next = value.map((item) => {
    const safeItem = withSafeNumericAssertions(item);
    if (safeItem !== item) {
      changed = true;
    }
    return safeItem;
  });

  if (next[0] === "number" && next.length === 2) {
    changed = true;
    next.push(0);
  }

  return changed ? next : value;
}

function paintRatioToCssPercent(value: number) {
  return `${Math.round(Math.max(0, 1 + value) * 100)}%`;
}

const osmTileUrls = [
  "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
  "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
  "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
];
const osmTileUrlPattern =
  /https:\/\/[abc]\.tile\.openstreetmap\.org\/\d+\/\d+\/\d+\.png/i;

export function createOsmRasterStyle(
  sourceId = "osm-raster",
  layerId = "osm-raster",
): StyleSpecification {
  return {
    version: 8,
    sources: {
      [sourceId]: {
        type: "raster",
        tiles: osmTileUrls,
        tileSize: 256,
        maxzoom: osmRasterTileMaxZoom,
        attribution: "&copy; OpenStreetMap contributors",
      },
    },
    layers: [
      {
        id: layerId,
        type: "raster",
        source: sourceId,
        minzoom: 0,
        maxzoom: 24,
      },
    ],
  };
}

export function isOsmRasterTileError(value: unknown) {
  return osmTileUrlPattern.test(errorText(value));
}

function errorText(value: unknown, depth = 0): string {
  if (depth > 2 || value == null) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (value instanceof Error) {
    return value.message;
  }
  if (typeof value !== "object") {
    return String(value);
  }

  const record = value as Record<string, unknown>;
  return ["message", "url", "statusText", "error"]
    .map((key) => errorText(record[key], depth + 1))
    .filter(Boolean)
    .join(" ");
}

export function shouldUseMapboxBasemap(mapConfig: MapBasemapConfig) {
  return (
    Boolean(mapConfig.mapboxAccessToken) && mapConfig.defaultBasemap !== "osm"
  );
}

export function createBasemapStyle(
  mapConfig: MapBasemapConfig,
  options: {
    osmSourceId?: string;
    osmLayerId?: string;
  } = {},
) {
  if (shouldUseMapboxBasemap(mapConfig)) {
    return mapboxSatelliteStyle;
  }
  return createOsmRasterStyle(options.osmSourceId, options.osmLayerId);
}
