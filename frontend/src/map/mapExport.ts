import { projectTransformRequest } from "../projects/session";
import { basemapIdFromStyle, basemapMaxZoom } from "./basemapSnapshot";
import type { BasemapId } from "./basemapCatalog";
import mapboxgl, {
  type Map as MapboxMap,
  type MapboxOptions,
  type StyleSpecification,
} from "mapbox-gl";
import type { GeoJsonGeometry } from "../types";
import { extractCoordinates } from "../utils/geometry";
import {
  sanitizeStyleNumericAssertions,
  satelliteBasemapColorCorrection,
} from "./basemapStyle";
import {
  bindPlatformSymbolImageFallback,
  registerPlatformSymbolImages,
} from "./symbolImages";

const webMercatorTileSize = 512;
const minExportCssDimension = 320;
const maxExportDimension = 8192;
const maxExportPixels = 36_000_000;
const minMercatorLatitude = -85.05112878;
const maxMercatorLatitude = 85.05112878;
const platformBasemapSourceId = "map-export-platform-basemap";
const platformBasemapLayerId = "map-export-platform-basemap";
const platformBasemapBackgroundLayerId = "map-export-background";
// Export must fail on missing imagery, rather than capture a thumbnail placeholder.
const platformBasemapTileUrl =
  "/api/map/thumbnail-tiles/{z}/{x}/{y}.png?purpose=export";
const mapStyleLoadTimeoutMs = 8000;
const mapTileLoadTimeoutMs = 25_000;
const mapExportMaxAttempts = 2;
const rangeOverlaySourcePrefixes = [
  "query-spatial-filter",
  "query-draw-preview",
  "map-export-range",
];

export type MapImageExportFormat = "png" | "jpg";

export interface MapImageExportOptions {
  basemapId?: BasemapId;
  dpi: number;
  tileZoom: number;
  format: MapImageExportFormat;
  /** Keep the whole requested range visible inside this output aspect ratio. */
  targetAspect?: number;
  renderSize?: { width: number; height: number };
  accessToken?: string;
  signal?: AbortSignal;
}

export interface MapRangeExportPlan {
  bounds: [number, number, number, number];
  center: [number, number];
  cssWidth: number;
  cssHeight: number;
  outputWidth: number;
  outputHeight: number;
  dpi: number;
  tileZoom: number;
}

export interface TileZoomRange {
  min: number;
  max: number;
}

export async function exportMapRangeImage(
  map: MapboxMap,
  geometry: GeoJsonGeometry,
  options: MapImageExportOptions,
): Promise<Blob> {
  const plan = createMapRangeExportPlan(geometry, options);
  await waitForStyleLoad(map, mapStyleLoadTimeoutMs, options.signal);
  const sourceStyle = map.getStyle();
  let lastError: unknown = null;

  for (let attempt = 1; attempt <= mapExportMaxAttempts; attempt += 1) {
    throwIfAborted(options.signal);
    try {
      return await exportMapRangeImageAttempt(sourceStyle, plan, options);
    } catch (error) {
      if (isAbortError(error)) throw error;
      lastError = error;
      if (attempt >= mapExportMaxAttempts) break;
      await abortableDelay(750 * attempt, options.signal);
    }
  }

  throw mapExportFailure(lastError);
}

async function exportMapRangeImageAttempt(
  sourceStyle: StyleSpecification,
  plan: MapRangeExportPlan,
  options: MapImageExportOptions,
): Promise<Blob> {
  const container = createExportContainer(plan);
  const exportStyle = createExportStyle(sourceStyle, options.basemapId);
  let exportMap: MapboxMap | null = null;
  let unbindSymbolFallback: (() => void) | null = null;

  document.body.appendChild(container);
  try {
    const mapOptions: MapboxOptions = {
      transformRequest: projectTransformRequest,
      container,
      style: exportStyle,
      center: plan.center,
      zoom: plan.tileZoom,
      pitch: 0,
      bearing: 0,
      projection: "mercator",
      interactive: false,
      attributionControl: false,
      preserveDrawingBuffer: true,
      performanceMetricsCollection: false,
      fadeDuration: 0,
      localIdeographFontFamily: '"Microsoft YaHei", "PingFang SC", sans-serif',
    };
    if (options.accessToken) {
      mapOptions.accessToken = options.accessToken;
    }

    exportMap = new mapboxgl.Map(mapOptions);
    unbindSymbolFallback = bindPlatformSymbolImageFallback(exportMap);
    await waitForStyleLoad(exportMap, mapStyleLoadTimeoutMs, options.signal);
    registerPlatformSymbolImages(exportMap);
    exportMap.setProjection("mercator");
    exportMap.jumpTo({
      center: plan.center,
      zoom: plan.tileZoom,
      pitch: 0,
      bearing: 0,
    });
    await waitForMapReady(exportMap, mapTileLoadTimeoutMs, options.signal);
    await nextAnimationFrame();
    throwIfAborted(options.signal);
    return await mapCanvasToImageBlob(exportMap.getCanvas(), plan, options);
  } finally {
    unbindSymbolFallback?.();
    exportMap?.remove();
    container.remove();
  }
}

export function createMapRangeExportPlan(
  geometry: GeoJsonGeometry,
  options: Pick<
    MapImageExportOptions,
    "dpi" | "tileZoom" | "targetAspect" | "renderSize"
  >,
): MapRangeExportPlan {
  const dpi = normalizeDpi(options.dpi);
  const tileZoom = normalizeTileZoom(options.tileZoom);
  const bounds = geometryBounds(geometry);
  const projected = projectBounds(bounds, tileZoom);
  let contentWidth = Math.max(1, projected.maxX - projected.minX);
  let contentHeight = Math.max(1, projected.maxY - projected.minY);
  const targetAspect = normalizeTargetAspect(options.targetAspect);
  let cssWidth: number;
  let cssHeight: number;
  if (targetAspect !== null) {
    if (contentWidth / contentHeight < targetAspect) {
      contentWidth = contentHeight * targetAspect;
    } else {
      contentHeight = contentWidth / targetAspect;
    }
    const minimumScale = Math.max(
      1,
      minExportCssDimension / contentWidth,
      minExportCssDimension / contentHeight,
    );
    cssWidth = Math.ceil(contentWidth * minimumScale);
    cssHeight = Math.ceil(contentHeight * minimumScale);
  } else {
    cssWidth = Math.ceil(Math.max(minExportCssDimension, contentWidth));
    cssHeight = Math.ceil(Math.max(minExportCssDimension, contentHeight));
  }
  let renderZoom = tileZoom;
  if (options.renderSize) {
    cssWidth = Math.max(1, Math.round(options.renderSize.width));
    cssHeight = Math.max(1, Math.round(options.renderSize.height));
    renderZoom = Math.min(
      24,
      tileZoom +
        Math.log2(Math.min(cssWidth / contentWidth, cssHeight / contentHeight)),
    );
  }
  const viewportScale = 2 ** (renderZoom - tileZoom);
  const extentWidth = cssWidth / viewportScale;
  const extentHeight = cssHeight / viewportScale;
  const outputWidth = Math.round((cssWidth * dpi) / 96);
  const outputHeight = Math.round((cssHeight * dpi) / 96);
  validateOutputSize(outputWidth, outputHeight);
  const center = unprojectMercatorPixel(
    [
      (projected.minX + projected.maxX) / 2,
      (projected.minY + projected.maxY) / 2,
    ],
    tileZoom,
  );

  return {
    bounds: [
      unprojectMercatorPixel(
        [(projected.minX + projected.maxX - extentWidth) / 2, 0],
        tileZoom,
      )[0],
      unprojectMercatorPixel(
        [0, (projected.minY + projected.maxY + extentHeight) / 2],
        tileZoom,
      )[1],
      unprojectMercatorPixel(
        [(projected.minX + projected.maxX + extentWidth) / 2, 0],
        tileZoom,
      )[0],
      unprojectMercatorPixel(
        [0, (projected.minY + projected.maxY - extentHeight) / 2],
        tileZoom,
      )[1],
    ],
    center,
    cssWidth,
    cssHeight,
    outputWidth,
    outputHeight,
    dpi,
    tileZoom: renderZoom,
  };
}

function normalizeTargetAspect(value: number | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return null;
  }
  return clamp(value, 0.05, 20);
}

export function inferBasemapTileZoomRange(
  style: StyleSpecification,
  excludedSourceIds: ReadonlySet<string> = new Set(),
): TileZoomRange {
  const ranges: TileZoomRange[] = [];
  const sources = style.sources ?? {};
  for (const [sourceId, source] of Object.entries(sources)) {
    if (excludedSourceIds.has(sourceId) || isRangeOverlayId(sourceId)) {
      continue;
    }
    const sourceRange = zoomRangeFromObject(source);
    if (sourceRange) {
      ranges.push(sourceRange);
    }
  }

  for (const layer of style.layers ?? []) {
    const sourceId = sourceIdForStyleLayer(layer);
    if (
      isRangeOverlayId(layer.id) ||
      (sourceId && excludedSourceIds.has(sourceId))
    ) {
      continue;
    }
    const layerRange = zoomRangeFromObject(layer);
    if (layerRange) {
      ranges.push(layerRange);
    }
  }

  if (ranges.length === 0) {
    return { min: 0, max: 22 };
  }

  return normalizeTileZoomRangeBounds({
    min: Math.min(...ranges.map((range) => range.min)),
    max: Math.max(...ranges.map((range) => range.max)),
  });
}

export function addPngDpiMetadata(bytes: Uint8Array, dpi: number): Uint8Array {
  if (!isPng(bytes)) {
    return bytes;
  }
  const chunk = createPhysChunk(normalizeDpi(dpi));
  const parts: Uint8Array[] = [bytes.slice(0, 8)];
  let inserted = false;
  let offset = 8;

  while (offset + 12 <= bytes.length) {
    const length = readUint32(bytes, offset);
    const end = offset + 12 + length;
    if (end > bytes.length) {
      return bytes;
    }
    const type = chunkType(bytes, offset + 4);
    const current = bytes.slice(offset, end);
    offset = end;

    if (type === "pHYs") {
      continue;
    }
    parts.push(current);
    if (type === "IHDR") {
      parts.push(chunk);
      inserted = true;
    }
    if (type === "IEND") {
      break;
    }
  }

  if (!inserted) {
    return bytes;
  }
  return concatBytes(parts);
}

export function addJpegDpiMetadata(bytes: Uint8Array, dpi: number): Uint8Array {
  if (!isJpeg(bytes)) {
    return bytes;
  }
  const normalizedDpi = normalizeDpi(dpi);
  let offset = 2;
  while (offset + 4 <= bytes.length && bytes[offset] === 0xff) {
    const marker = bytes[offset + 1];
    const length = readUint16(bytes, offset + 2);
    if (length < 2 || offset + 2 + length > bytes.length) {
      break;
    }
    if (marker === 0xe0 && isJfifSegment(bytes, offset)) {
      const output = bytes.slice();
      output[offset + 11] = 1;
      writeUint16(output, offset + 12, normalizedDpi);
      writeUint16(output, offset + 14, normalizedDpi);
      return output;
    }
    offset += 2 + length;
  }
  return concatBytes([
    bytes.slice(0, 2),
    createJfifChunk(normalizedDpi),
    bytes.slice(2),
  ]);
}

export function createExportStyle(
  style: StyleSpecification,
  selectedBasemapId?: BasemapId,
): StyleSpecification {
  const next = sanitizeStyleNumericAssertions(style);
  const basemapId = selectedBasemapId ?? basemapIdFromStyle(style);
  next.projection = { name: "mercator" };
  const basemapSourceIds = new Set(
    Object.entries(next.sources ?? {})
      .filter(([sourceId, source]) => isExternalBasemapSource(sourceId, source))
      .map(([sourceId]) => sourceId),
  );
  const usesSatelliteBasemap = selectedBasemapId
    ? selectedBasemapId === "mapbox-satellite"
    : Object.entries(next.sources ?? {}).some(([sourceId, source]) =>
        isSatelliteBasemapSource(sourceId, source),
      );
  next.sources ??= {};
  next.layers = (next.layers ?? []).filter((layer) => {
    if (isRangeOverlayId(layer.id) || layer.type === "background") {
      return false;
    }
    const sourceId = sourceIdForStyleLayer(layer);
    return !sourceId || !basemapSourceIds.has(sourceId);
  });
  for (const sourceId of Object.keys(next.sources)) {
    if (isRangeOverlayId(sourceId) || basemapSourceIds.has(sourceId)) {
      delete next.sources[sourceId];
    }
  }
  next.sources[platformBasemapSourceId] = {
    type: "raster",
    tiles: [`${platformBasemapTileUrl}&basemap=${basemapId}`],
    tileSize: 256,
    minzoom: 0,
    maxzoom: basemapMaxZoom(basemapId),
    attribution: basemapId.startsWith("mapbox")
      ? "© Mapbox © OpenStreetMap"
      : basemapId.startsWith("tianditu")
        ? "© 天地图"
        : "© OpenStreetMap contributors",
  };
  next.layers = [
    {
      id: platformBasemapBackgroundLayerId,
      type: "background",
      paint: { "background-color": "#d9e0e3" },
    },
    {
      id: platformBasemapLayerId,
      type: "raster",
      source: platformBasemapSourceId,
      paint: {
        "raster-fade-duration": 0,
        ...(usesSatelliteBasemap ? satelliteBasemapColorCorrection : {}),
      },
    },
    ...(next.layers ?? []),
  ];
  if (basemapId.startsWith("tianditu-")) {
    const labelId = `${platformBasemapSourceId}-labels`;
    next.sources[labelId] = {
      type: "raster",
      tiles: [`${platformBasemapTileUrl}&basemap=${basemapId}&labels=1`],
      tileSize: 256,
      maxzoom: 18,
    };
    next.layers.splice(2, 0, {
      id: labelId,
      type: "raster",
      source: labelId,
      paint: { "raster-fade-duration": 0 },
    });
  }
  if (next.terrain && basemapSourceIds.has(next.terrain.source)) {
    delete next.terrain;
  }
  return next;
}

function geometryBounds(geometry: GeoJsonGeometry) {
  const coordinates: Array<[number, number]> = [];
  extractCoordinates(geometry.coordinates, coordinates);
  if (coordinates.length === 0) {
    throw new Error("导出范围无有效坐标");
  }

  let west = Number.POSITIVE_INFINITY;
  let south = Number.POSITIVE_INFINITY;
  let east = Number.NEGATIVE_INFINITY;
  let north = Number.NEGATIVE_INFINITY;
  for (const [lng, lat] of coordinates) {
    if (!Number.isFinite(lng) || !Number.isFinite(lat)) continue;
    west = Math.min(west, lng);
    south = Math.min(south, lat);
    east = Math.max(east, lng);
    north = Math.max(north, lat);
  }
  if (![west, south, east, north].every(Number.isFinite)) {
    throw new Error("导出范围无有效坐标");
  }
  return {
    west,
    south: clamp(south, minMercatorLatitude, maxMercatorLatitude),
    east,
    north: clamp(north, minMercatorLatitude, maxMercatorLatitude),
  };
}

function projectBounds(
  bounds: { west: number; south: number; east: number; north: number },
  zoom: number,
) {
  const southWest = projectMercatorPixel([bounds.west, bounds.south], zoom);
  const northEast = projectMercatorPixel([bounds.east, bounds.north], zoom);
  return {
    minX: Math.min(southWest[0], northEast[0]),
    maxX: Math.max(southWest[0], northEast[0]),
    minY: Math.min(southWest[1], northEast[1]),
    maxY: Math.max(southWest[1], northEast[1]),
  };
}

function projectMercatorPixel([lng, lat]: [number, number], zoom: number) {
  const worldSize = webMercatorTileSize * 2 ** zoom;
  const clampedLat = clamp(lat, minMercatorLatitude, maxMercatorLatitude);
  const sinLatitude = Math.sin((clampedLat * Math.PI) / 180);
  return [
    ((lng + 180) / 360) * worldSize,
    (0.5 - Math.log((1 + sinLatitude) / (1 - sinLatitude)) / (4 * Math.PI)) *
      worldSize,
  ] as [number, number];
}

function unprojectMercatorPixel(
  [x, y]: [number, number],
  zoom: number,
): [number, number] {
  const worldSize = webMercatorTileSize * 2 ** zoom;
  const lng = (x / worldSize) * 360 - 180;
  const mercatorY = Math.PI * (1 - (2 * y) / worldSize);
  const lat = (Math.atan(Math.sinh(mercatorY)) * 180) / Math.PI;
  return [lng, lat];
}

function createExportContainer(plan: MapRangeExportPlan) {
  const container = document.createElement("div");
  container.style.position = "fixed";
  container.style.left = "-100000px";
  container.style.top = "0";
  container.style.width = `${plan.cssWidth}px`;
  container.style.height = `${plan.cssHeight}px`;
  container.style.pointerEvents = "none";
  container.style.opacity = "0";
  return container;
}

async function mapCanvasToImageBlob(
  source: HTMLCanvasElement,
  plan: MapRangeExportPlan,
  options: Pick<MapImageExportOptions, "dpi" | "format">,
) {
  const output = document.createElement("canvas");
  output.width = plan.outputWidth;
  output.height = plan.outputHeight;
  const context = output.getContext("2d");
  if (!context) {
    throw new Error("浏览器不支持地图导出画布");
  }
  if (options.format === "jpg") {
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, plan.outputWidth, plan.outputHeight);
  }
  context.drawImage(source, 0, 0, plan.outputWidth, plan.outputHeight);
  const blob = await canvasToImageBlob(output, options.format);
  const bytes = new Uint8Array(await blob.arrayBuffer());
  const metadataBytes =
    options.format === "png"
      ? addPngDpiMetadata(bytes, options.dpi)
      : addJpegDpiMetadata(bytes, options.dpi);
  return new Blob([bytesToArrayBuffer(metadataBytes)], {
    type: imageMimeType(options.format),
  });
}

function canvasToImageBlob(
  canvas: HTMLCanvasElement,
  format: MapImageExportFormat,
) {
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob);
      } else {
        reject(new Error("地图导出失败，请检查底图和瓦片服务是否允许导出"));
      }
    }, imageMimeType(format));
  });
}

export function waitForStyleLoad(
  map: MapboxMap,
  timeoutMs: number = mapStyleLoadTimeoutMs,
  signal?: AbortSignal,
) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError());
      return;
    }
    if (map.isStyleLoaded()) {
      resolve();
      return;
    }
    let settled = false;
    const finish = (error?: Error) => {
      if (settled) return;
      settled = true;
      globalThis.clearTimeout(timeoutId);
      map.off("style.load", handleLoad);
      map.off("render", checkLoaded);
      map.off("error", handleError);
      signal?.removeEventListener("abort", handleAbort);
      if (error) reject(error);
      else resolve();
    };
    const handleLoad = () => finish();
    const checkLoaded = () => {
      if (map.isStyleLoaded()) finish();
    };
    const handleError = (event: { error?: unknown }) =>
      finish(new Error(`底图样式加载失败：${mapLoadErrorText(event.error)}`));
    const handleAbort = () => finish(abortError());
    const timeoutId = globalThis.setTimeout(
      () => finish(new Error("底图样式加载超时")),
      timeoutMs,
    );
    map.once("style.load", handleLoad);
    map.on("render", checkLoaded);
    map.on("error", handleError);
    signal?.addEventListener("abort", handleAbort, { once: true });
    if (signal?.aborted) handleAbort();
  });
}

function waitForMapReady(
  map: MapboxMap,
  timeoutMs: number,
  signal?: AbortSignal,
) {
  return new Promise<void>((resolve, reject) => {
    let settled = false;
    const loadErrors: string[] = [];
    const finish = (error?: Error) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeoutId);
      map.off("idle", checkReady);
      map.off("render", checkReady);
      map.off("error", handleError);
      signal?.removeEventListener("abort", handleAbort);
      if (error) reject(error);
      else resolve();
    };
    const checkReady = () => {
      if (!map.isStyleLoaded() || !map.loaded() || !map.areTilesLoaded()) {
        return;
      }
      if (loadErrors.length > 0) {
        finish(
          new Error(
            `底图或业务瓦片加载失败：${loadErrors.slice(0, 3).join("；")}`,
          ),
        );
        return;
      }
      finish();
    };
    const handleError = (event: { error?: unknown }) => {
      const message = mapLoadErrorText(event.error);
      if (!loadErrors.includes(message)) loadErrors.push(message);
    };
    const handleAbort = () => finish(abortError());
    const timeoutId = window.setTimeout(() => {
      const detail = loadErrors.length
        ? `：${loadErrors.slice(0, 3).join("；")}`
        : "";
      finish(
        new Error(`底图瓦片在 ${timeoutMs / 1000} 秒内未加载完整${detail}`),
      );
    }, timeoutMs);
    map.on("idle", checkReady);
    map.on("render", checkReady);
    map.on("error", handleError);
    signal?.addEventListener("abort", handleAbort, { once: true });
    if (signal?.aborted) {
      handleAbort();
      return;
    }
    checkReady();
  });
}

function isExternalBasemapSource(sourceId: string, source: unknown) {
  const normalizedId = sourceId.toLowerCase();
  if (
    normalizedId === "composite" ||
    normalizedId === "satellite" ||
    normalizedId === "osm-raster" ||
    normalizedId.startsWith("basemap-tianditu-") ||
    normalizedId.startsWith("mapbox")
  ) {
    return true;
  }
  if (typeof source !== "object" || source === null) return false;
  const candidate = source as { url?: unknown; tiles?: unknown };
  if (
    typeof candidate.url === "string" &&
    (candidate.url.startsWith("mapbox://") ||
      candidate.url.includes("openfreemap.org") ||
      candidate.url.includes("tianditu.gov.cn"))
  ) {
    return true;
  }
  if (!Array.isArray(candidate.tiles) || candidate.tiles.length === 0) {
    return false;
  }
  return candidate.tiles.every(
    (tile) =>
      typeof tile === "string" &&
      (tile.includes("api.mapbox.com") ||
        tile.includes("tile.openstreetmap.org") ||
        tile.includes("openfreemap.org") ||
        tile.includes("tianditu.gov.cn")),
  );
}

function isSatelliteBasemapSource(sourceId: string, source: unknown) {
  if (sourceId.toLowerCase().includes("satellite")) return true;
  if (typeof source !== "object" || source === null) return false;
  const candidate = source as { url?: unknown; tiles?: unknown };
  if (
    typeof candidate.url === "string" &&
    candidate.url.toLowerCase().includes("satellite")
  ) {
    return true;
  }
  return (
    Array.isArray(candidate.tiles) &&
    candidate.tiles.some(
      (tile) =>
        typeof tile === "string" && tile.toLowerCase().includes("satellite"),
    )
  );
}

function mapLoadErrorText(value: unknown, depth = 0): string {
  if (depth > 2 || value == null) return "未知瓦片错误";
  if (typeof value === "string") return value;
  if (value instanceof Error) return value.message || value.name;
  if (typeof value !== "object") return String(value);
  const record = value as Record<string, unknown>;
  const messages = ["message", "url", "status", "statusText", "error"]
    .map((key) => mapLoadErrorText(record[key], depth + 1))
    .filter((item) => item !== "未知瓦片错误");
  return messages.join(" ") || "未知瓦片错误";
}

function mapExportFailure(error: unknown) {
  const detail = error instanceof Error ? error.message : String(error ?? "");
  return new Error(
    `出图底图加载失败，平台已自动重试但仍未获得完整瓦片${detail ? `：${detail}` : ""}。请稍后重试或检查服务器外网与底图服务配置。`,
  );
}

function abortableDelay(timeoutMs: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError());
      return;
    }
    const handleAbort = () => {
      window.clearTimeout(timeoutId);
      signal?.removeEventListener("abort", handleAbort);
      reject(abortError());
    };
    const timeoutId = window.setTimeout(() => {
      signal?.removeEventListener("abort", handleAbort);
      resolve();
    }, timeoutMs);
    signal?.addEventListener("abort", handleAbort, { once: true });
  });
}

function throwIfAborted(signal?: AbortSignal) {
  if (signal?.aborted) throw abortError();
}

function abortError() {
  return new DOMException("出图预览已取消", "AbortError");
}

function isAbortError(error: unknown) {
  return error instanceof DOMException
    ? error.name === "AbortError"
    : typeof error === "object" &&
        error !== null &&
        "name" in error &&
        error.name === "AbortError";
}

function nextAnimationFrame() {
  return new Promise<void>((resolve) => {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => resolve());
    });
  });
}

function normalizeDpi(value: number) {
  if (!Number.isFinite(value)) {
    throw new Error("DPI 参数无效");
  }
  return Math.round(clamp(value, 72, 600));
}

function normalizeTileZoom(value: number) {
  if (!Number.isFinite(value)) {
    throw new Error("瓦片等级参数无效");
  }
  return Math.round(clamp(value, 0, 22));
}

function normalizeTileZoomRangeBounds(range: TileZoomRange): TileZoomRange {
  const min = Math.round(clamp(range.min, 0, 22));
  const max = Math.round(clamp(range.max, min, 22));
  return { min, max };
}

function zoomRangeFromObject(value: unknown): TileZoomRange | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const rangeSource = value as { minzoom?: unknown; maxzoom?: unknown };
  const min =
    typeof rangeSource.minzoom === "number" &&
    Number.isFinite(rangeSource.minzoom)
      ? rangeSource.minzoom
      : 0;
  const max =
    typeof rangeSource.maxzoom === "number" &&
    Number.isFinite(rangeSource.maxzoom)
      ? rangeSource.maxzoom
      : null;
  return max === null ? null : normalizeTileZoomRangeBounds({ min, max });
}

function sourceIdForStyleLayer(layer: { source?: unknown }) {
  return typeof layer.source === "string" ? layer.source : null;
}

function validateOutputSize(width: number, height: number) {
  if (
    width > maxExportDimension ||
    height > maxExportDimension ||
    width * height > maxExportPixels
  ) {
    throw new Error("导出图片尺寸过大，请降低 DPI 或瓦片等级后重试");
  }
}

function createPhysChunk(dpi: number) {
  const pixelsPerMeter = Math.round(dpi / 0.0254);
  const type = new TextEncoder().encode("pHYs");
  const data = new Uint8Array(9);
  writeUint32(data, 0, pixelsPerMeter);
  writeUint32(data, 4, pixelsPerMeter);
  data[8] = 1;
  const chunk = new Uint8Array(4 + type.length + data.length + 4);
  writeUint32(chunk, 0, data.length);
  chunk.set(type, 4);
  chunk.set(data, 8);
  writeUint32(chunk, 8 + data.length, crc32(chunk.slice(4, 8 + data.length)));
  return chunk;
}

function createJfifChunk(dpi: number) {
  const chunk = new Uint8Array(18);
  chunk[0] = 0xff;
  chunk[1] = 0xe0;
  writeUint16(chunk, 2, 16);
  chunk.set(new TextEncoder().encode("JFIF\0"), 4);
  chunk[9] = 1;
  chunk[10] = 1;
  chunk[11] = 1;
  writeUint16(chunk, 12, dpi);
  writeUint16(chunk, 14, dpi);
  chunk[16] = 0;
  chunk[17] = 0;
  return chunk;
}

function isRangeOverlayId(id: string) {
  return rangeOverlaySourcePrefixes.some(
    (prefix) => id === prefix || id.startsWith(`${prefix}-`),
  );
}

function isPng(bytes: Uint8Array) {
  return (
    bytes.length >= 8 &&
    bytes[0] === 0x89 &&
    bytes[1] === 0x50 &&
    bytes[2] === 0x4e &&
    bytes[3] === 0x47 &&
    bytes[4] === 0x0d &&
    bytes[5] === 0x0a &&
    bytes[6] === 0x1a &&
    bytes[7] === 0x0a
  );
}

function isJpeg(bytes: Uint8Array) {
  return bytes.length >= 2 && bytes[0] === 0xff && bytes[1] === 0xd8;
}

function isJfifSegment(bytes: Uint8Array, offset: number) {
  return (
    bytes[offset + 4] === 0x4a &&
    bytes[offset + 5] === 0x46 &&
    bytes[offset + 6] === 0x49 &&
    bytes[offset + 7] === 0x46 &&
    bytes[offset + 8] === 0x00
  );
}

function chunkType(bytes: Uint8Array, offset: number) {
  return String.fromCharCode(
    bytes[offset] ?? 0,
    bytes[offset + 1] ?? 0,
    bytes[offset + 2] ?? 0,
    bytes[offset + 3] ?? 0,
  );
}

function readUint32(bytes: Uint8Array, offset: number) {
  return (
    ((bytes[offset] ?? 0) * 0x1000000 +
      ((bytes[offset + 1] ?? 0) << 16) +
      ((bytes[offset + 2] ?? 0) << 8) +
      (bytes[offset + 3] ?? 0)) >>>
    0
  );
}

function readUint16(bytes: Uint8Array, offset: number) {
  return (((bytes[offset] ?? 0) << 8) + (bytes[offset + 1] ?? 0)) >>> 0;
}

function writeUint32(bytes: Uint8Array, offset: number, value: number) {
  bytes[offset] = (value >>> 24) & 0xff;
  bytes[offset + 1] = (value >>> 16) & 0xff;
  bytes[offset + 2] = (value >>> 8) & 0xff;
  bytes[offset + 3] = value & 0xff;
}

function writeUint16(bytes: Uint8Array, offset: number, value: number) {
  bytes[offset] = (value >>> 8) & 0xff;
  bytes[offset + 1] = value & 0xff;
}

function bytesToArrayBuffer(bytes: Uint8Array) {
  const buffer = new ArrayBuffer(bytes.byteLength);
  new Uint8Array(buffer).set(bytes);
  return buffer;
}

function imageMimeType(format: MapImageExportFormat) {
  return format === "png" ? "image/png" : "image/jpeg";
}

function concatBytes(parts: Uint8Array[]) {
  const totalLength = parts.reduce((sum, part) => sum + part.length, 0);
  const output = new Uint8Array(totalLength);
  let offset = 0;
  for (const part of parts) {
    output.set(part, offset);
    offset += part.length;
  }
  return output;
}

function crc32(bytes: Uint8Array) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let index = 0; index < 8; index += 1) {
      crc = crc & 1 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}
