import type { MapBounds, MapCompositionLayout } from "./layout";
import type { PixelBox } from "./canvasElements";

export function drawGrid(
  context: CanvasRenderingContext2D,
  frame: PixelBox,
  bounds: MapBounds,
  grid: MapCompositionLayout["grid"],
  pxPerMm: number,
) {
  if (!grid.enabled || grid.interval <= 0) return;
  context.save();
  context.beginPath();
  context.rect(frame.x, frame.y, frame.width, frame.height);
  context.clip();
  context.strokeStyle = grid.color;
  context.fillStyle = grid.labelColor;
  context.lineWidth = Math.max(1, pxPerMm * 0.15);
  context.font = `${grid.fontSizePt * 0.352778 * pxPerMm}px "Microsoft YaHei", sans-serif`;
  context.textBaseline = "top";
  if (grid.type === "projected") {
    drawProjectedGrid(context, frame, bounds, grid.interval);
  } else {
    drawGeographicGrid(context, frame, bounds, grid.interval);
  }
  context.restore();
}

export function drawOverviewExtent(
  context: CanvasRenderingContext2D,
  frame: PixelBox,
  overviewBounds: MapBounds,
  mainBounds: MapBounds,
  color: string,
) {
  const extent = overviewExtentPixelBox(frame, overviewBounds, mainBounds);
  const lineWidth = Math.max(2, frame.width * 0.012);
  const inset = lineWidth / 2;
  const x1 = clamp(extent.x, frame.x + inset, frame.x + frame.width - inset);
  const y1 = clamp(extent.y, frame.y + inset, frame.y + frame.height - inset);
  const x2 = clamp(
    extent.x + extent.width,
    frame.x + inset,
    frame.x + frame.width - inset,
  );
  const y2 = clamp(
    extent.y + extent.height,
    frame.y + inset,
    frame.y + frame.height - inset,
  );
  context.save();
  context.beginPath();
  context.rect(frame.x, frame.y, frame.width, frame.height);
  context.clip();
  context.strokeStyle = color;
  context.lineWidth = lineWidth;
  context.strokeRect(x1, y1, Math.max(0, x2 - x1), Math.max(0, y2 - y1));
  context.restore();
}

export function overviewExtentPixelBox(
  frame: PixelBox,
  overviewBounds: MapBounds,
  mainBounds: MapBounds,
): PixelBox {
  const x1 =
    frame.x + longitudeRatio(mainBounds[0], overviewBounds) * frame.width;
  const x2 =
    frame.x + longitudeRatio(mainBounds[2], overviewBounds) * frame.width;
  const y1 =
    frame.y + latitudeRatio(mainBounds[3], overviewBounds) * frame.height;
  const y2 =
    frame.y + latitudeRatio(mainBounds[1], overviewBounds) * frame.height;
  const left = clamp(Math.min(x1, x2), frame.x, frame.x + frame.width);
  const right = clamp(Math.max(x1, x2), frame.x, frame.x + frame.width);
  const top = clamp(Math.min(y1, y2), frame.y, frame.y + frame.height);
  const bottom = clamp(Math.max(y1, y2), frame.y, frame.y + frame.height);
  return {
    x: left,
    y: top,
    width: Math.max(0, right - left),
    height: Math.max(0, bottom - top),
  };
}

function drawGeographicGrid(
  context: CanvasRenderingContext2D,
  frame: PixelBox,
  bounds: MapBounds,
  interval: number,
) {
  for (
    let longitude = Math.ceil(bounds[0] / interval) * interval;
    longitude < bounds[2];
    longitude += interval
  ) {
    const x = frame.x + longitudeRatio(longitude, bounds) * frame.width;
    line(context, x, frame.y, x, frame.y + frame.height);
    context.fillText(`${formatNumber(longitude)}°`, x + 2, frame.y + 2);
  }
  for (
    let latitude = Math.ceil(bounds[1] / interval) * interval;
    latitude < bounds[3];
    latitude += interval
  ) {
    const y = frame.y + latitudeRatio(latitude, bounds) * frame.height;
    line(context, frame.x, y, frame.x + frame.width, y);
    context.fillText(`${formatNumber(latitude)}°`, frame.x + 2, y + 2);
  }
}

function drawProjectedGrid(
  context: CanvasRenderingContext2D,
  frame: PixelBox,
  bounds: MapBounds,
  interval: number,
) {
  const west = mercatorX(bounds[0]);
  const east = mercatorX(bounds[2]);
  const south = mercatorY(bounds[1]);
  const north = mercatorY(bounds[3]);
  for (
    let xValue = Math.ceil(west / interval) * interval;
    xValue < east;
    xValue += interval
  ) {
    const x = frame.x + ((xValue - west) / (east - west)) * frame.width;
    line(context, x, frame.y, x, frame.y + frame.height);
    context.fillText(`${Math.round(xValue / 1000)} km`, x + 2, frame.y + 2);
  }
  for (
    let yValue = Math.ceil(south / interval) * interval;
    yValue < north;
    yValue += interval
  ) {
    const y = frame.y + (1 - (yValue - south) / (north - south)) * frame.height;
    line(context, frame.x, y, frame.x + frame.width, y);
    context.fillText(`${Math.round(yValue / 1000)} km`, frame.x + 2, y + 2);
  }
}

function longitudeRatio(longitude: number, bounds: MapBounds) {
  return (longitude - bounds[0]) / (bounds[2] - bounds[0]);
}

function latitudeRatio(latitude: number, bounds: MapBounds) {
  const north = normalizedMercatorY(bounds[3]);
  const south = normalizedMercatorY(bounds[1]);
  return (normalizedMercatorY(latitude) - north) / (south - north);
}

function normalizedMercatorY(latitude: number) {
  const radians =
    (Math.max(-85.05112878, Math.min(85.05112878, latitude)) * Math.PI) / 180;
  return (
    (1 - Math.log(Math.tan(radians) + 1 / Math.cos(radians)) / Math.PI) / 2
  );
}

function mercatorX(longitude: number) {
  return 6_378_137 * ((longitude * Math.PI) / 180);
}

function mercatorY(latitude: number) {
  const radians =
    (Math.max(-85.05112878, Math.min(85.05112878, latitude)) * Math.PI) / 180;
  return 6_378_137 * Math.log(Math.tan(Math.PI / 4 + radians / 2));
}

function line(
  context: CanvasRenderingContext2D,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
) {
  context.beginPath();
  context.moveTo(x1, y1);
  context.lineTo(x2, y2);
  context.stroke();
}

function formatNumber(value: number) {
  return Number(value.toFixed(3)).toString();
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}
