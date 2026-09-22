import {
  platformProjectBounds,
  type MapBounds,
  type MapCompositionLayout,
} from "./layoutTypes";
import {
  applyStandardGeometry,
  constrainCompositionLayout,
  layoutHasOutOfBoundsBoxes,
  standardCompositionBoxes,
} from "./layoutGeometry";

export type {
  CompositionGridType,
  LayoutBox,
  MapBounds,
  MapCompositionLayout,
  PaperOrientation,
  PaperPreset,
  TextElement,
} from "./layoutTypes";
export { platformProjectBounds } from "./layoutTypes";
export { constrainCompositionLayout } from "./layoutGeometry";

export function defaultCompositionLayout(
  title: string,
  bounds: MapBounds,
  sourceText = "数据来源：平台已加载数据资源",
): MapCompositionLayout {
  const boxes = standardCompositionBoxes(297, 210, "landscape");
  return {
    version: 1,
    editor: { order: [], locked: [] },
    extraTexts: [],
    page: {
      preset: "A4",
      orientation: "landscape",
      widthMm: 297,
      heightMm: 210,
      dpi: 300,
      backgroundColor: "#ffffff",
    },
    mapFrame: {
      ...boxes.mapFrame,
      bounds,
      borderColor: "#1f2937",
      borderWidthPt: 0.8,
    },
    title: {
      enabled: true,
      text: title,
      ...boxes.title,
      fontSizePt: 18,
      color: "#102a2e",
      align: "center",
    },
    subtitle: {
      enabled: false,
      text: "",
      ...boxes.subtitle,
      fontSizePt: 10,
      color: "#475569",
      align: "center",
    },
    legend: {
      enabled: true,
      title: "图例",
      ...boxes.legend,
      columns: 1,
      fontSizePt: 8,
      backgroundColor: "#fffffff2",
      borderColor: "#8fa2a6",
    },
    overview: {
      enabled: true,
      ...boxes.overview,
      bounds: platformProjectBounds,
      borderColor: "#ef4444",
    },
    northArrow: {
      enabled: true,
      ...boxes.northArrow,
    },
    scaleBar: {
      enabled: true,
      ...boxes.scaleBar,
      color: "#111827",
    },
    grid: {
      enabled: false,
      type: "geographic",
      interval: suggestedGeographicGridInterval(bounds),
      color: "#64748b88",
      labelColor: "#334155",
      fontSizePt: 7,
    },
    source: {
      enabled: true,
      text: sourceText,
      ...boxes.source,
      fontSizePt: 7,
      color: "#475569",
      align: "left",
    },
    note: {
      enabled: true,
      text: `制图说明：WebGIS 平台专题制图 · ${new Date().toLocaleDateString("zh-CN")}`,
      ...boxes.note,
      fontSizePt: 7,
      color: "#475569",
      align: "right",
    },
  };
}

export function suggestedGeographicGridInterval(bounds: MapBounds) {
  const target = Math.max(bounds[2] - bounds[0], bounds[3] - bounds[1]) / 6;
  return preferredInterval(
    target,
    [
      0.0001, 0.0002, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2,
      0.5, 1, 2, 5, 10, 20, 30,
    ],
  );
}

export function suggestedProjectedGridInterval(bounds: MapBounds) {
  const west = mercatorX(bounds[0]);
  const east = mercatorX(bounds[2]);
  const south = mercatorY(bounds[1]);
  const north = mercatorY(bounds[3]);
  const target = Math.max(east - west, north - south) / 6;
  return preferredInterval(
    target,
    [
      10, 20, 50, 100, 200, 500, 1_000, 2_000, 5_000, 10_000, 20_000, 50_000,
      100_000, 200_000, 500_000, 1_000_000, 2_000_000,
    ],
  );
}

export function normalizeCompositionLayout(
  raw: unknown,
  title: string,
  fallbackBounds: MapBounds,
  sourceText?: string,
): MapCompositionLayout {
  const fallback = defaultCompositionLayout(title, fallbackBounds, sourceText);
  if (!isRecord(raw)) return fallback;
  const merged = structuredClone(fallback);
  mergeKnown(merged, raw);
  if (
    typeof raw.basemapId === "string" &&
    [
      "mapbox-satellite",
      "mapbox-streets",
      "tianditu-vector",
      "tianditu-imagery",
      "osm",
    ].includes(raw.basemapId)
  ) {
    merged.basemapId = raw.basemapId as MapCompositionLayout["basemapId"];
  }
  merged.editor.order = Array.isArray(merged.editor.order)
    ? merged.editor.order.filter((id) => typeof id === "string")
    : [];
  merged.editor.locked = Array.isArray(merged.editor.locked)
    ? merged.editor.locked.filter((id) => typeof id === "string")
    : [];
  const seen = new Set<string>();
  merged.extraTexts = (Array.isArray(raw.extraTexts) ? raw.extraTexts : [])
    .slice(0, 100)
    .filter((item) => {
      if (
        !isRecord(item) ||
        typeof item.id !== "string" ||
        !item.id.startsWith("text-") ||
        seen.has(item.id)
      )
        return false;
      seen.add(item.id);
      return true;
    })
    .map((item) => {
      const text = { ...fallback.note, id: item.id as string };
      mergeKnown(text, item);
      return text;
    });
  merged.mapFrame.bounds = normalizeBounds(
    isRecord(raw.mapFrame) ? raw.mapFrame.bounds : undefined,
    fallbackBounds,
  );
  merged.overview.bounds = normalizeBounds(
    isRecord(raw.overview) ? raw.overview.bounds : undefined,
    platformProjectBounds,
  );
  const repaired = layoutHasOutOfBoundsBoxes(merged)
    ? applyStandardGeometry(merged)
    : merged;
  return constrainCompositionLayout(repaired);
}

export function pagePixelSize(layout: MapCompositionLayout) {
  const scale = layout.page.dpi / 25.4;
  return {
    width: Math.round(layout.page.widthMm * scale),
    height: Math.round(layout.page.heightMm * scale),
  };
}

export function boundsFromUnknown(
  value: unknown,
  fallback: MapBounds,
): MapBounds {
  return normalizeBounds(value, fallback);
}

export function panMapBounds(
  bounds: MapBounds,
  longitudeRatio: number,
  latitudeRatio: number,
): MapBounds {
  const longitudeOffset = (bounds[2] - bounds[0]) * longitudeRatio;
  const latitudeOffset = (bounds[3] - bounds[1]) * latitudeRatio;
  const [west, east] = fitCoordinateRange(
    bounds[0] + longitudeOffset,
    bounds[2] + longitudeOffset,
    -180,
    180,
  );
  const [south, north] = fitCoordinateRange(
    bounds[1] + latitudeOffset,
    bounds[3] + latitudeOffset,
    -85.05112878,
    85.05112878,
  );
  return [west, south, east, north];
}

export function zoomMapBounds(bounds: MapBounds, factor: number): MapBounds {
  const safeFactor = Number.isFinite(factor)
    ? Math.max(0.05, Math.min(20, factor))
    : 1;
  const longitudeCenter = (bounds[0] + bounds[2]) / 2;
  const latitudeCenter = (bounds[1] + bounds[3]) / 2;
  const longitudeRadius = ((bounds[2] - bounds[0]) * safeFactor) / 2;
  const latitudeRadius = ((bounds[3] - bounds[1]) * safeFactor) / 2;
  const [west, east] = fitCoordinateRange(
    longitudeCenter - longitudeRadius,
    longitudeCenter + longitudeRadius,
    -180,
    180,
  );
  const [south, north] = fitCoordinateRange(
    latitudeCenter - latitudeRadius,
    latitudeCenter + latitudeRadius,
    -85.05112878,
    85.05112878,
  );
  return [west, south, east, north];
}

function normalizeBounds(value: unknown, fallback: MapBounds): MapBounds {
  if (
    Array.isArray(value) &&
    value.length === 4 &&
    value.every((item) => typeof item === "number" && Number.isFinite(item)) &&
    value[0] < value[2] &&
    value[1] < value[3]
  ) {
    return value as MapBounds;
  }
  return fallback;
}

function fitCoordinateRange(
  start: number,
  end: number,
  minimum: number,
  maximum: number,
): [number, number] {
  const span = Math.min(maximum - minimum, Math.max(1e-8, end - start));
  let fittedStart = (start + end - span) / 2;
  let fittedEnd = fittedStart + span;
  if (fittedStart < minimum) {
    fittedEnd += minimum - fittedStart;
    fittedStart = minimum;
  }
  if (fittedEnd > maximum) {
    fittedStart -= fittedEnd - maximum;
    fittedEnd = maximum;
  }
  return [Math.max(minimum, fittedStart), Math.min(maximum, fittedEnd)];
}

function mergeKnown(target: unknown, source: unknown) {
  if (!isRecord(target) || !isRecord(source)) return;
  for (const key of Object.keys(target)) {
    const sourceValue = source[key];
    const targetValue = target[key];
    if (sourceValue === undefined) continue;
    if (isRecord(targetValue) && isRecord(sourceValue)) {
      mergeKnown(targetValue, sourceValue);
    } else if (
      typeof sourceValue === typeof targetValue ||
      (Array.isArray(sourceValue) && Array.isArray(targetValue))
    ) {
      target[key] = sourceValue;
    }
  }
}

function isRecord(value: unknown): value is Record<string, any> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function preferredInterval(target: number, intervals: number[]) {
  return (
    intervals.find((interval) => interval >= target) ??
    intervals[intervals.length - 1]!
  );
}

function mercatorX(longitude: number) {
  return 6_378_137 * ((longitude * Math.PI) / 180);
}

function mercatorY(latitude: number) {
  const clamped = Math.max(-85.05112878, Math.min(85.05112878, latitude));
  const radians = (clamped * Math.PI) / 180;
  return 6_378_137 * Math.log(Math.tan(Math.PI / 4 + radians / 2));
}
