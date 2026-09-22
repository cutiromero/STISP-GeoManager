import type { Map as MapboxMap } from "mapbox-gl";
import {
  createMapRangeExportPlan,
  exportMapRangeImage,
} from "../map/mapExport";
import type { GeoJsonGeometry } from "../types";
import type { MapBounds } from "./layout";

export async function renderBoundsImage(
  map: MapboxMap,
  bounds: MapBounds,
  targetWidth: number,
  targetHeight: number,
  accessToken?: string,
  signal?: AbortSignal,
  basemapId?: import("../map/basemapCatalog").BasemapId,
): Promise<ImageBitmap> {
  const tileZoom = tileZoomForTarget(bounds, targetWidth, targetHeight);
  const blob = await exportMapRangeImage(map, boundsGeometry(bounds), {
    dpi: 96,
    tileZoom,
    format: "png",
    targetAspect: targetWidth / Math.max(1, targetHeight),
    renderSize: { width: targetWidth, height: targetHeight },
    accessToken,
    signal,
    basemapId,
  });
  return createImageBitmap(blob);
}

export function boundsImagePlan(
  bounds: MapBounds,
  width: number,
  height: number,
) {
  return createMapRangeExportPlan(boundsGeometry(bounds), {
    dpi: 96,
    tileZoom: tileZoomForTarget(bounds, width, height),
    targetAspect: width / height,
    renderSize: { width, height },
  });
}

export function fitOverviewBounds(
  overviewBounds: MapBounds,
  mainBounds: MapBounds,
  targetWidth: number,
  targetHeight: number,
): MapBounds {
  const west = Math.min(overviewBounds[0], mainBounds[0]);
  const south = Math.min(overviewBounds[1], mainBounds[1]);
  const east = Math.max(overviewBounds[2], mainBounds[2]);
  const north = Math.max(overviewBounds[3], mainBounds[3]);
  const paddingRatio = 0.06;
  let minX = longitudeX(west);
  let maxX = longitudeX(east);
  let minY = mercatorY(north);
  let maxY = mercatorY(south);
  const initialWidth = Math.max(1e-6, maxX - minX);
  const initialHeight = Math.max(1e-6, maxY - minY);
  minX -= initialWidth * paddingRatio;
  maxX += initialWidth * paddingRatio;
  minY -= initialHeight * paddingRatio;
  maxY += initialHeight * paddingRatio;

  const targetAspect = Math.max(0.1, targetWidth / Math.max(1, targetHeight));
  const width = maxX - minX;
  const height = maxY - minY;
  if (width / height < targetAspect) {
    const fittedWidth = height * targetAspect;
    const centerX = (minX + maxX) / 2;
    minX = centerX - fittedWidth / 2;
    maxX = centerX + fittedWidth / 2;
  } else {
    const fittedHeight = width / targetAspect;
    const centerY = (minY + maxY) / 2;
    minY = centerY - fittedHeight / 2;
    maxY = centerY + fittedHeight / 2;
  }

  [minX, maxX] = fitUnitRange(minX, maxX);
  [minY, maxY] = fitUnitRange(minY, maxY);
  return [
    longitudeFromX(minX),
    latitudeFromMercatorY(maxY),
    longitudeFromX(maxX),
    latitudeFromMercatorY(minY),
  ];
}

export function boundsGeometry(bounds: MapBounds): GeoJsonGeometry {
  const [west, south, east, north] = bounds;
  return {
    type: "Polygon",
    coordinates: [
      [
        [west, south],
        [east, south],
        [east, north],
        [west, north],
        [west, south],
      ],
    ],
  };
}

export function tileZoomForTarget(
  bounds: MapBounds,
  targetWidth: number,
  targetHeight: number,
) {
  const [west, south, east, north] = bounds;
  const baseWidth = (Math.abs(east - west) / 360) * 512;
  const baseHeight = Math.abs(mercatorY(north) - mercatorY(south)) * 512;
  const widthRatio = targetWidth / Math.max(1, baseWidth);
  const heightRatio = targetHeight / Math.max(1, baseHeight);
  const zoom = Math.ceil(Math.log2(Math.max(widthRatio, heightRatio))) - 1;
  return Math.max(0, Math.min(22, zoom));
}

function mercatorY(latitude: number) {
  const clamped = Math.max(-85.05112878, Math.min(85.05112878, latitude));
  const radians = (clamped * Math.PI) / 180;
  return (
    (1 - Math.log(Math.tan(radians) + 1 / Math.cos(radians)) / Math.PI) / 2
  );
}

function longitudeX(longitude: number) {
  return (Math.max(-180, Math.min(180, longitude)) + 180) / 360;
}

function longitudeFromX(value: number) {
  return value * 360 - 180;
}

function latitudeFromMercatorY(value: number) {
  const radians = Math.atan(Math.sinh(Math.PI * (1 - 2 * value)));
  return (radians * 180) / Math.PI;
}

function fitUnitRange(minimum: number, maximum: number): [number, number] {
  const span = Math.min(1, Math.max(1e-6, maximum - minimum));
  const center = (minimum + maximum) / 2;
  let start = center - span / 2;
  let end = center + span / 2;
  if (start < 0) {
    end -= start;
    start = 0;
  }
  if (end > 1) {
    start -= end - 1;
    end = 1;
  }
  return [Math.max(0, start), Math.min(1, end)];
}
