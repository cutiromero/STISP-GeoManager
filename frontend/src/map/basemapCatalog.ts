import type { StyleSpecification } from "mapbox-gl";
import i18n from "../i18n";
import { createOsmRasterStyle, mapboxSatelliteStyle } from "./basemapStyle";
import { tiandituTileProviderName } from "./tiandituTileProviderConfig";

export type BasemapId =
  | "mapbox-satellite"
  | "mapbox-streets"
  | "tianditu-vector"
  | "tianditu-imagery"
  | "osm";

export type BasemapProvider = "mapbox" | "tianditu" | "osm";
export type BasemapCredentialName = "mapboxAccessToken" | "tiandituKey";
export type BasemapVisual =
  | "satellite"
  | "streets"
  | "tianditu"
  | "tianditu-imagery"
  | "fallback";

export interface BasemapCredentials {
  mapboxAccessToken?: string;
  tiandituKey?: string;
}

export interface BasemapCredentialState {
  available: boolean;
  missing: BasemapCredentialName[];
  reason?: string;
  degraded?: boolean;
  warning?: string;
}

export interface BasemapPostProcess {
  applyExpressionSafety: boolean;
  applyChineseLanguage: boolean;
  applySatelliteColorCorrection: boolean;
  hideAdministrativeBoundaries: boolean;
}

export interface BasemapDefinition {
  id: BasemapId;
  label: string;
  description: string;
  provider: BasemapProvider;
  selectable: boolean;
  style: string | StyleSpecification;
  sourceIds: readonly string[];
  requireAllSourceIds?: boolean;
  errorMarkers: readonly string[];
  attribution: string;
  credentials: BasemapCredentialState;
  postProcess: BasemapPostProcess;
  visual: BasemapVisual;
}

export interface BasemapFallbackOptions {
  userPreference?: string | null;
  systemDefault?: string | null;
}

export const mapboxStreetsStyle = "mapbox://styles/mapbox/streets-v12";
export const tiandituMapboxGlyphs =
  "mapbox://fonts/mapbox/{fontstack}/{range}.pbf";

const tiandituVectorSourceId = "basemap-tianditu-vector";
const tiandituLabelSourceId = "basemap-tianditu-labels";
const tiandituImagerySourceId = "basemap-tianditu-imagery";
const tiandituImageryLabelSourceId = "basemap-tianditu-imagery-labels";
const osmSourceId = "osm-raster";
const osmLayerId = "osm-raster";

const mapboxSatelliteSourceIds = [
  "composite",
  "mapbox-satellite",
  "mapbox",
] as const;
const mapboxStreetsSourceIds = ["composite"] as const;
const tiandituSourceIds = [
  tiandituVectorSourceId,
  tiandituLabelSourceId,
] as const;
const tiandituImagerySourceIds = [
  tiandituImagerySourceId,
  tiandituImageryLabelSourceId,
] as const;

const basemapIdAliases: Readonly<Record<string, BasemapId>> = {
  satellite: "mapbox-satellite",
  streets: "mapbox-streets",
  tianditu: "tianditu-vector",
  "mapbox-satellite": "mapbox-satellite",
  "mapbox-streets": "mapbox-streets",
  "tianditu-vector": "tianditu-vector",
  "tianditu-imagery": "tianditu-imagery",
  osm: "osm",
};

export function createBasemapCatalog(
  credentials: BasemapCredentials,
): readonly BasemapDefinition[] {
  const hasMapboxToken = hasCredential(credentials.mapboxAccessToken);
  const hasTiandituKey = hasCredential(credentials.tiandituKey);
  const mapboxCredentials = mapboxCredentialState(hasMapboxToken);
  const tiandituCredentials = tiandituCredentialState(
    hasTiandituKey,
    hasMapboxToken,
  );

  return [
    {
      id: "mapbox-satellite",
      label: i18n.t("map.mapboxSatellite"),
      description: i18n.t("map.mapboxSatelliteDescription"),
      provider: "mapbox",
      selectable: true,
      style: mapboxSatelliteStyle,
      sourceIds: mapboxSatelliteSourceIds,
      errorMarkers: [
        mapboxSatelliteStyle,
        "api.mapbox.com",
        "tiles.mapbox.com",
        "mapbox://",
      ],
      attribution: "© Mapbox © OpenStreetMap",
      credentials: mapboxCredentials,
      postProcess: {
        applyExpressionSafety: true,
        applyChineseLanguage: true,
        applySatelliteColorCorrection: true,
        hideAdministrativeBoundaries: true,
      },
      visual: "satellite",
    },
    {
      id: "mapbox-streets",
      label: i18n.t("map.mapboxStreets"),
      description: i18n.t("map.mapboxStreetsDescription"),
      provider: "mapbox",
      selectable: true,
      style: mapboxStreetsStyle,
      sourceIds: mapboxStreetsSourceIds,
      errorMarkers: [
        mapboxStreetsStyle,
        "api.mapbox.com",
        "tiles.mapbox.com",
        "mapbox://",
      ],
      attribution: "© Mapbox © OpenStreetMap",
      credentials: mapboxCredentials,
      postProcess: {
        applyExpressionSafety: true,
        applyChineseLanguage: true,
        applySatelliteColorCorrection: false,
        hideAdministrativeBoundaries: false,
      },
      visual: "streets",
    },
    {
      id: "tianditu-vector",
      label: i18n.t("map.tiandituVector"),
      description: i18n.t("map.tiandituVectorDescription"),
      provider: "tianditu",
      selectable: true,
      style: createTiandituVectorStyle(credentials.tiandituKey),
      sourceIds: tiandituSourceIds,
      requireAllSourceIds: true,
      errorMarkers: [
        "tianditu.gov.cn",
        tiandituVectorSourceId,
        tiandituLabelSourceId,
      ],
      attribution: "© 天地图",
      credentials: tiandituCredentials,
      postProcess: {
        applyExpressionSafety: false,
        applyChineseLanguage: false,
        applySatelliteColorCorrection: false,
        hideAdministrativeBoundaries: false,
      },
      visual: "tianditu",
    },
    {
      id: "tianditu-imagery",
      label: i18n.t("map.tiandituImagery"),
      description: i18n.t("map.tiandituImageryDescription"),
      provider: "tianditu",
      selectable: true,
      style: createTiandituImageryStyle(credentials.tiandituKey),
      sourceIds: tiandituImagerySourceIds,
      requireAllSourceIds: true,
      errorMarkers: [
        "tianditu.gov.cn",
        tiandituImagerySourceId,
        tiandituImageryLabelSourceId,
      ],
      attribution: "© 天地图",
      credentials: tiandituCredentials,
      postProcess: {
        applyExpressionSafety: false,
        applyChineseLanguage: false,
        applySatelliteColorCorrection: false,
        hideAdministrativeBoundaries: false,
      },
      visual: "tianditu-imagery",
    },
    {
      id: "osm",
      label: i18n.t("map.osmFallback"),
      description: i18n.t("map.osmFallbackDescription"),
      provider: "osm",
      selectable: false,
      style: createOsmRasterStyle(osmSourceId, osmLayerId),
      sourceIds: [osmSourceId],
      errorMarkers: ["tile.openstreetmap.org", osmSourceId],
      attribution: "© OpenStreetMap contributors",
      credentials: {
        available: true,
        missing: [],
        degraded: true,
        warning: "公共匿名瓦片仅作内部技术兜底，不承诺生产服务等级。",
      },
      postProcess: {
        applyExpressionSafety: false,
        applyChineseLanguage: false,
        applySatelliteColorCorrection: false,
        hideAdministrativeBoundaries: false,
      },
      visual: "fallback",
    },
  ];
}

export function resolveBasemapDefinition(
  catalog: readonly BasemapDefinition[],
  id: string | null | undefined,
): BasemapDefinition | undefined {
  if (!id) return undefined;
  const normalizedId = basemapIdAliases[id.trim().toLowerCase()];
  if (!normalizedId) return undefined;
  return catalog.find((basemap) => basemap.id === normalizedId);
}

export function availableBasemapFallback(
  catalog: readonly BasemapDefinition[],
  options: BasemapFallbackOptions = {},
): BasemapDefinition {
  const preferredCandidates = [options.userPreference, options.systemDefault];

  for (const id of preferredCandidates) {
    const basemap = resolveBasemapDefinition(catalog, id);
    if (basemap?.selectable && basemap.credentials.available) return basemap;
  }

  const selectableFallbacks = [
    "mapbox-satellite",
    "mapbox-streets",
    "tianditu-vector",
    "tianditu-imagery",
  ];

  for (const id of selectableFallbacks) {
    const basemap = resolveBasemapDefinition(catalog, id);
    if (basemap?.selectable && basemap.credentials.available) return basemap;
  }

  const technicalFallback = resolveBasemapDefinition(catalog, "osm");
  if (technicalFallback?.credentials.available) return technicalFallback;
  throw new Error("底图目录中没有可用的底图");
}

function createTiandituVectorStyle(
  key: string | undefined,
): StyleSpecification {
  return createTiandituRasterStyle({
    baseLayer: "vec",
    baseSourceId: tiandituVectorSourceId,
    key,
    labelLayer: "cva",
    labelSourceId: tiandituLabelSourceId,
  });
}

function createTiandituImageryStyle(
  key: string | undefined,
): StyleSpecification {
  return createTiandituRasterStyle({
    baseLayer: "img",
    baseSourceId: tiandituImagerySourceId,
    key,
    labelLayer: "cia",
    labelSourceId: tiandituImageryLabelSourceId,
  });
}

type TiandituLayer = "vec" | "cva" | "img" | "cia";

function createTiandituRasterStyle({
  baseLayer,
  baseSourceId,
  key,
  labelLayer,
  labelSourceId,
}: {
  baseLayer: TiandituLayer;
  baseSourceId: string;
  key: string | undefined;
  labelLayer: TiandituLayer;
  labelSourceId: string;
}): StyleSpecification {
  return {
    version: 8,
    glyphs: tiandituMapboxGlyphs,
    sources: {
      [baseSourceId]: {
        type: "raster",
        provider: tiandituTileProviderName,
        url: tiandituTileJsonUrl(baseLayer, key),
      },
      [labelSourceId]: {
        type: "raster",
        provider: tiandituTileProviderName,
        url: tiandituTileJsonUrl(labelLayer, key),
      },
    },
    layers: [
      {
        id: baseSourceId,
        type: "raster",
        source: baseSourceId,
      },
      {
        id: labelSourceId,
        type: "raster",
        source: labelSourceId,
      },
    ],
  };
}

function tiandituTileJsonUrl(layer: TiandituLayer, key: string | undefined) {
  const encodedKey = encodeURIComponent(key?.trim() ?? "");
  // The custom provider intercepts this metadata request and returns TileJSON.
  // Keeping tiles out of the style lets Mapbox GL retain provider maxzoom and
  // natively overscale the last available parent tile at higher camera zooms.
  return `https://t0.tianditu.gov.cn/${layer}_w/wmts?SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0&LAYER=${layer}&tk=${encodedKey}`;
}

function mapboxCredentialState(
  hasMapboxToken: boolean,
): BasemapCredentialState {
  return hasMapboxToken
    ? { available: true, missing: [] }
    : {
        available: false,
        missing: ["mapboxAccessToken"],
        reason: "未配置 Mapbox Token",
      };
}

function tiandituCredentialState(
  hasTiandituKey: boolean,
  hasMapboxToken: boolean,
): BasemapCredentialState {
  if (!hasTiandituKey) {
    return {
      available: false,
      missing: ["tiandituKey"],
      reason: "未配置天地图 Key",
    };
  }
  if (!hasMapboxToken) {
    return {
      available: true,
      missing: ["mapboxAccessToken"],
      degraded: true,
      warning: "底图可用，但平台业务文字字体能力受限。",
    };
  }
  return { available: true, missing: [] };
}

function hasCredential(value: string | undefined) {
  return Boolean(value?.trim());
}
